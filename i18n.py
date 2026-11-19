import json
import os

_SUPPORTED = ("en", "ru", "uz")
_translations: dict[str, dict] = {}

def _load():
    base = os.path.join(os.path.dirname(__file__), "locales")
    for lang in _SUPPORTED:
        path = os.path.join(base, f"{lang}.json")
        with open(path, encoding="utf-8") as f:
            _translations[lang] = json.load(f)

_load()


def t(key: str, lang: str = "en", **kwargs) -> str:
    """Return the translated string for key in lang, falling back to English."""
    lang = lang if lang in _SUPPORTED else "en"
    text = _translations[lang].get(key) or _translations["en"].get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text
