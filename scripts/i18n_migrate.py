"""
AST-based i18n migration.

Finds blocks of the form

    if ln == "uz":
        ms = "..."          (or f-string, or keyboard identifier)
        kb = cancel_button_uz
    elif ln == "ru":
        ...
    else:
        ...

and rewrites them as

    ms = t("some_key", ln)
    kb = kb_variant(ln, en=cancel_button, ru=cancel_button_ru, uz=cancel_button_uz)

adding the extracted strings to locales/{en,ru,uz}.json.

Only converts blocks where EVERY branch consists solely of assignments to the
same variables. Anything else is skipped and reported for manual migration.

Usage:  python scripts/i18n_migrate.py [--dry] file1.py file2.py ...
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALES = os.path.join(ROOT, "locales")
LANGS = ("en", "ru", "uz")
LANG_VARS = {"ln", "ln1", "lang", "user_lang", "language", "user_language"}


def load_locales():
    data = {}
    for lang in LANGS:
        with open(os.path.join(LOCALES, f"{lang}.json"), encoding="utf-8") as f:
            data[lang] = json.load(f)
    return data


def save_locales(data):
    for lang in LANGS:
        with open(os.path.join(LOCALES, f"{lang}.json"), "w", encoding="utf-8") as f:
            json.dump(data[lang], f, ensure_ascii=False, indent=2)
            f.write("\n")


def slugify(text, maxwords=5):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "_".join(words[:maxwords]) or "text"


class Branch:
    """lang -> {varname: value AST node}"""


def match_lang_test(test):
    """Return (langvar, langvalue) for `ln == "uz"` style tests, else None."""
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq) and len(test.comparators) == 1):
        return None
    left, right = test.left, test.comparators[0]
    if isinstance(left, ast.Name) and isinstance(right, ast.Constant):
        var, val = left.id, right.value
    elif isinstance(right, ast.Name) and isinstance(left, ast.Constant):
        var, val = right.id, left.value
    else:
        return None
    if var in LANG_VARS and val in LANGS:
        return var, val
    return None


def branch_assigns(body):
    """Return {var: value_node} if body is only simple assignments, else None."""
    out = {}
    for stmt in body:
        if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)):
            return None
        val = stmt.value
        if not isinstance(val, (ast.Constant, ast.JoinedStr, ast.Name)):
            return None
        if isinstance(val, ast.Constant) and not isinstance(val.value, str):
            return None
        out[stmt.targets[0].id] = val
    return out or None


def collect_block(node):
    """Walk an if/elif/else chain. Return (langvar, {lang: assigns}) or None."""
    branches = {}
    langvar = None
    cur = node
    while True:
        m = match_lang_test(cur.test)
        if not m:
            return None
        var, lang = m
        if langvar is None:
            langvar = var
        elif var != langvar:
            return None
        assigns = branch_assigns(cur.body)
        if assigns is None or lang in branches:
            return None
        branches[lang] = assigns

        if not cur.orelse:
            break
        if len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
            cur = cur.orelse[0]
            continue
        # plain else: acts as the English fallback
        if "en" in branches:
            return None
        assigns = branch_assigns(cur.orelse)
        if assigns is None:
            return None
        branches["en"] = assigns
        break

    if len(branches) < 3 or set(branches) != set(LANGS):
        return None
    varsets = [set(v) for v in branches.values()]
    if any(vs != varsets[0] for vs in varsets):
        return None
    return langvar, branches


def stringify(node, src, exprmap):
    """AST string node -> format-string text; expressions become {pN} refs."""
    if isinstance(node, ast.Constant):
        text = node.value
        return text.replace("{", "{{").replace("}", "}}") if exprmap else text
    parts = []
    for piece in node.values:
        if isinstance(piece, ast.Constant):
            parts.append(str(piece.value).replace("{", "{{").replace("}", "}}"))
        else:  # FormattedValue
            expr_src = ast.get_source_segment(src, piece.value)
            if expr_src is None:
                raise ValueError("unreadable expression")
            if expr_src not in exprmap:
                exprmap[expr_src] = f"p{len(exprmap)}"
            name = exprmap[expr_src]
            conv = f"!{chr(piece.conversion)}" if piece.conversion != -1 else ""
            spec = ""
            if piece.format_spec is not None:
                raise ValueError("format spec not supported")
            parts.append("{" + name + conv + spec + "}")
    return "".join(parts)


def has_placeholders(node):
    return isinstance(node, ast.JoinedStr)


def migrate_file(path, locales, dry=False):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    lines = src.split("\n")

    conversions = []   # (start, end, indent, newlines)
    skipped = []
    converted_ifs = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or id(node) in converted_ifs:
            continue
        if match_lang_test(node.test) is None:
            continue
        result = collect_block(node)
        if result is None:
            skipped.append(node.lineno)
            continue
        langvar, branches = result
        # don't re-process the elif children of a converted chain
        cur = node
        while cur.orelse and len(cur.orelse) == 1 and isinstance(cur.orelse[0], ast.If):
            converted_ifs.add(id(cur.orelse[0]))
            cur = cur.orelse[0]

        indent = re.match(r"\s*", lines[node.lineno - 1]).group(0)
        newlines = []
        for var in branches["en"]:
            values = {lang: branches[lang][var] for lang in LANGS}
            kinds = {type(v) for v in values.values()}
            if kinds <= {ast.Constant, ast.JoinedStr}:
                exprmap = {} if any(has_placeholders(v) for v in values.values()) else None
                try:
                    texts = {
                        lang: stringify(values[lang], src,
                                        exprmap if exprmap is not None else {})
                        for lang in LANGS
                    }
                except ValueError:
                    skipped.append(node.lineno)
                    newlines = None
                    break
                # key: reuse if identical english text already stored
                key = None
                for k, v in locales["en"].items():
                    if v == texts["en"] and locales["ru"].get(k) == texts["ru"]:
                        key = k
                        break
                if key is None:
                    key = slugify(texts["en"])
                    base, n = key, 2
                    while key in locales["en"] and locales["en"][key] != texts["en"]:
                        key = f"{base}_{n}"
                        n += 1
                    for lang in LANGS:
                        locales[lang][key] = texts[lang]
                if exprmap:
                    kwargs = ", ".join(f"{n}={e}" for e, n in exprmap.items())
                    newlines.append(f'{indent}{var} = t("{key}", {langvar}, {kwargs})')
                else:
                    newlines.append(f'{indent}{var} = t("{key}", {langvar})')
            elif kinds == {ast.Name}:
                newlines.append(
                    f'{indent}{var} = kb_variant({langvar}, '
                    f'en={values["en"].id}, ru={values["ru"].id}, uz={values["uz"].id})'
                )
            else:
                skipped.append(node.lineno)
                newlines = None
                break
        if newlines:
            conversions.append((node.lineno, cur.end_lineno, newlines))

    if not conversions:
        return 0, skipped

    for start, end, newlines in sorted(conversions, reverse=True):
        lines[start - 1:end] = newlines
    out = "\n".join(lines)

    if 'from i18n import t' not in out:
        out = "from i18n import t\n" + out
    if "kb_variant(" in out and "keyboard" not in os.path.basename(path):
        if "from keyboards.keyboard import" not in out and "from keyboards.keyboard import *" not in out:
            out = "from keyboards.keyboard import kb_variant\n" + out

    ast.parse(out)  # abort before writing if we produced bad code
    if not dry:
        with open(path + ".bak_i18n", "w", encoding="utf-8") as f:
            f.write(src)
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
    return len(conversions), skipped


def main():
    args = [a for a in sys.argv[1:] if a != "--dry"]
    dry = "--dry" in sys.argv
    locales = load_locales()
    for rel in args:
        path = os.path.join(ROOT, rel)
        n, skipped = migrate_file(path, locales, dry)
        print(f"{rel}: {n} blocks converted, {len(skipped)} skipped"
              + (f" (manual: lines {sorted(set(skipped))})" if skipped else ""))
    if not dry:
        save_locales(locales)
        print("locales updated")


if __name__ == "__main__":
    main()
