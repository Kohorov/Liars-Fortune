"""Game event images, drawn with Pillow shapes.

The only text drawn is digits and a few Latin words, so nothing depends on
a Cyrillic font being installed on the server. Every function returns PNG
bytes ready for aiogram's BufferedInputFile.
"""
import io
import math
import random
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 960, 540
SS = 2  # supersampling factor for smooth edges

FELT = (22, 92, 60)
FELT_DARK = (10, 46, 30)
NIGHT = (30, 32, 46)
NIGHT_DARK = (10, 11, 18)
WHITE = (250, 248, 242)
RED = (214, 48, 49)
BLACK = (30, 30, 34)
GOLD = (232, 182, 64)
GREEN = (46, 204, 113)
GREY = (90, 94, 110)
PURPLE = (108, 52, 160)

SUITS = {"❤️": "heart", "♥️": "heart", "♦️": "diamond",
         "♠️": "spade", "♣️": "club"}
JOKER = "\U0001f0cf"
UNIVERSAL = "\U0001f3b4"


def _font(size):
    try:
        return ImageFont.load_default(size=size * SS)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _s(*v):
    return [x * SS for x in v]


def _canvas(top, bottom):
    img = Image.new("RGB", (W * SS, H * SS), top)
    d = ImageDraw.Draw(img)
    for y in range(H * SS):
        k = y / (H * SS)
        d.line([(0, y), (W * SS, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip(top, bottom)))
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse(
        [-W * SS * 0.2, -H * SS * 0.3, W * SS * 1.2, H * SS * 1.3], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(80 * SS))
    return Image.composite(img, Image.new("RGB", img.size, bottom), mask)


def _png(img):
    img = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def draw_suit(d, cx, cy, size, suit, color):
    """Suit centered on (cx, cy), about size px tall (unscaled units)."""
    cx, cy, r = cx * SS, cy * SS, size * SS / 2
    if suit == "diamond":
        d.polygon([(cx, cy - r), (cx + r * 0.72, cy), (cx, cy + r), (cx - r * 0.72, cy)], fill=color)
    elif suit == "heart":
        lr = r * 0.52
        top = cy - r * 0.75
        d.ellipse([cx - 2 * lr, top, cx, top + 2 * lr], fill=color)
        d.ellipse([cx, top, cx + 2 * lr, top + 2 * lr], fill=color)
        d.polygon([(cx - 1.98 * lr, top + lr * 1.15), (cx + 1.98 * lr, top + lr * 1.15),
                   (cx, cy + r)], fill=color)
    elif suit == "spade":
        lr = r * 0.48
        d.polygon([(cx, cy - r), (cx + 1.97 * lr, cy + r * 0.22), (cx - 1.97 * lr, cy + r * 0.22)],
                  fill=color)
        d.ellipse([cx - 2 * lr, cy - r * 0.2, cx, cy - r * 0.2 + 2 * lr], fill=color)
        d.ellipse([cx, cy - r * 0.2, cx + 2 * lr, cy - r * 0.2 + 2 * lr], fill=color)
        d.polygon([(cx, cy + r * 0.2), (cx + r * 0.38, cy + r), (cx - r * 0.38, cy + r)], fill=color)
    elif suit == "club":
        lr = r * 0.4
        d.ellipse([cx - lr, cy - r, cx + lr, cy - r + 2 * lr], fill=color)
        d.ellipse([cx - 2.1 * lr, cy - r * 0.3, cx - 0.1 * lr, cy - r * 0.3 + 2 * lr], fill=color)
        d.ellipse([cx + 0.1 * lr, cy - r * 0.3, cx + 2.1 * lr, cy - r * 0.3 + 2 * lr], fill=color)
        d.polygon([(cx, cy - r * 0.2), (cx + r * 0.38, cy + r), (cx - r * 0.38, cy + r)], fill=color)


def _star(d, cx, cy, r, color, points=5, inner=0.45, rot=-90):
    pts = []
    for i in range(points * 2):
        rad = r if i % 2 == 0 else r * inner
        a = math.radians(rot + i * 180 / points)
        pts.append(((cx + rad * math.cos(a)) * SS, (cy + rad * math.sin(a)) * SS))
    d.polygon(pts, fill=color)


def _shadow(img, box, radius):
    sh = Image.new("L", img.size, 0)
    x0, y0, x1, y1 = box
    ImageDraw.Draw(sh).rounded_rectangle(_s(x0 + 6, y0 + 12, x1 + 6, y1 + 12), radius * SS, fill=140)
    sh = sh.filter(ImageFilter.GaussianBlur(10 * SS))
    img.paste((0, 0, 0), (0, 0), sh)


def draw_card(img, x, y, w, h, card, ring=None):
    """One card with its top-left corner at (x, y)."""
    _shadow(img, (x, y, x + w, y + h), 16)
    d = ImageDraw.Draw(img)
    if ring:
        d.rounded_rectangle(_s(x - 7, y - 7, x + w + 7, y + h + 7), 22 * SS, fill=ring)
    cx, cy = x + w / 2, y + h / 2
    suit = SUITS.get(card)
    if suit:
        d.rounded_rectangle(_s(x, y, x + w, y + h), 16 * SS, fill=WHITE)
        color = RED if suit in ("heart", "diamond") else BLACK
        draw_suit(d, cx, cy, w * 0.55, suit, color)
        draw_suit(d, x + 24, y + 28, 26, suit, color)
        draw_suit(d, x + w - 24, y + h - 28, 26, suit, color)
    elif card == JOKER:
        d.rounded_rectangle(_s(x, y, x + w, y + h), 16 * SS, fill=PURPLE)
        d.rounded_rectangle(_s(x + 9, y + 9, x + w - 9, y + h - 9), 12 * SS, outline=GOLD, width=3 * SS)
        _star(d, cx, cy - 14, w * 0.3, GOLD)
        d.text((cx * SS, (y + h - 36) * SS), "JOKER", font=_font(int(w * 0.16)), fill=GOLD, anchor="mm")
    else:  # universal card
        d.rounded_rectangle(_s(x, y, x + w, y + h), 16 * SS, fill=GOLD)
        d.rounded_rectangle(_s(x + 9, y + 9, x + w - 9, y + h - 9), 12 * SS, outline=WHITE, width=3 * SS)
        q = w * 0.2
        draw_suit(d, cx - q, cy - q, q * 1.3, "heart", RED)
        draw_suit(d, cx + q, cy - q, q * 1.3, "spade", BLACK)
        draw_suit(d, cx - q, cy + q, q * 1.3, "club", BLACK)
        draw_suit(d, cx + q, cy + q, q * 1.3, "diamond", RED)


def _mark(d, cx, cy, r, good):
    d.ellipse(_s(cx - r, cy - r, cx + r, cy + r), fill=GREEN if good else RED)
    w = int(r * 0.22) * SS
    if good:
        d.line(_s(cx - r * 0.45, cy + r * 0.02, cx - r * 0.1, cy + r * 0.38, cx + r * 0.5, cy - r * 0.35),
               fill=WHITE, width=w, joint="curve")
    else:
        k = r * 0.4
        d.line(_s(cx - k, cy - k, cx + k, cy + k), fill=WHITE, width=w)
        d.line(_s(cx - k, cy + k, cx + k, cy - k), fill=WHITE, width=w)


def _table_badge(d, table):
    suit = SUITS.get(table)
    d.rounded_rectangle(_s(30, 30, 130, 130), 20 * SS, fill=WHITE, outline=GOLD, width=5 * SS)
    if suit:
        draw_suit(d, 80, 80, 56, suit, RED if suit in ("heart", "diamond") else BLACK)


def reveal(cards, table, bluff):
    """Cards flipped after a LIAR call. bluff=True means the caller was right."""
    return _reveal(tuple(cards), table, bluff)


# Every image depends only on a handful of inputs, so each variant is drawn
# once and reused: drawing takes ~0.1-0.2 s and would stall the event loop.
@lru_cache(maxsize=512)
def _reveal(cards, table, bluff):
    img = _canvas(FELT, FELT_DARK)
    _table_badge(ImageDraw.Draw(img), table)
    n = max(len(cards), 1)
    cw, ch, gap = 170, 240, 40
    total = n * cw + (n - 1) * gap
    x0, y0 = (W - total) / 2, (H - ch) / 2 + 10
    for i, card in enumerate(cards):
        ok = card == table or card == UNIVERSAL or cards == (JOKER,)
        draw_card(img, x0 + i * (cw + gap), y0, cw, ch, card, ring=GREEN if ok else RED)
    _mark(ImageDraw.Draw(img), W - 90, 90, 52, not bluff)
    return _png(img)


@lru_cache(maxsize=None)
def revolver(pulls, dead):
    """Six-chamber cylinder. pulls = trigger pulls so far, including this one."""
    img = _canvas(NIGHT, NIGHT_DARK)
    d = ImageDraw.Draw(img)
    cx, cy, R = 320, H / 2, 190
    if dead:
        for i in range(12):
            _star(d, cx, cy, R + 80 - i * 4, (255, 90 + i * 12, 30), points=12, inner=0.6, rot=i * 9)
    d.ellipse(_s(cx - R, cy - R, cx + R, cy + R), fill=(150, 154, 166))
    d.ellipse(_s(cx - R + 12, cy - R + 12, cx + R - 12, cy + R - 12), fill=(112, 116, 130))
    d.ellipse(_s(cx - 34, cy - 34, cx + 34, cy + 34), fill=(70, 72, 84))
    cr, rr = 52, 118
    for i in range(6):
        a = math.radians(-90 + i * 60)
        x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
        current = i == pulls - 1
        if current and dead:
            fill = (200, 140, 50)
        elif i < pulls:
            fill = (24, 24, 30)
        else:
            fill = (54, 56, 66)
        d.ellipse(_s(x - cr, y - cr, x + cr, y + cr), fill=fill)
        if current and dead:
            d.ellipse(_s(x - 26, y - 26, x + 26, y + 26), fill=(150, 28, 28))
        if current:
            d.ellipse(_s(x - cr - 8, y - cr - 8, x + cr + 8, y + cr + 8),
                      outline=RED if dead else WHITE, width=6 * SS)
    tx = 730
    if dead:
        d.text(((tx + 30) * SS, (H / 2 - 30) * SS), "BANG", font=_font(110), fill=RED, anchor="mm")
    else:
        d.text((tx * SS, (H / 2 - 50) * SS), "CLICK", font=_font(90), fill=WHITE, anchor="mm")
        d.text((tx * SS, (H / 2 + 50) * SS), f"1/{max(6 - pulls, 1)}", font=_font(80),
               fill=GOLD, anchor="mm")
    for i in range(6):  # pull tracker
        x, y = tx - 125 + i * 50, H - 80
        if dead and i == pulls - 1:
            col = RED
        elif i < pulls:
            col = GREY
        else:
            col = (200, 204, 216)
        d.ellipse(_s(x - 14, y - 14, x + 14, y + 14), fill=col)
    return _png(img)


@lru_cache(maxsize=None)
def new_round(table):
    """Fresh deal: the table card everyone has to match."""
    img = _canvas(FELT, FELT_DARK)
    rnd = random.Random(table)
    for i in range(5):  # fanned card backs behind the table card
        back = Image.new("RGBA", (150 * SS, 210 * SS), (0, 0, 0, 0))
        bd = ImageDraw.Draw(back)
        bd.rounded_rectangle([0, 0, 150 * SS - 1, 210 * SS - 1], 14 * SS,
                             fill=(150, 30, 40), outline=WHITE, width=5 * SS)
        bd.rounded_rectangle([16 * SS, 16 * SS, 134 * SS, 194 * SS], 8 * SS,
                             outline=(220, 170, 80), width=3 * SS)
        back = back.rotate(-24 + i * 12 + rnd.uniform(-2, 2), expand=True, resample=Image.BICUBIC)
        pos = (int((W / 2 - back.width / SS / 2 + (i - 2) * 80) * SS), int(150 * SS))
        img.paste(back, pos, back)
    draw_card(img, W / 2 - 110, H / 2 - 155, 220, 310, table, ring=GOLD)
    return _png(img)


@lru_cache(maxsize=None)
def winner():
    """Trophy with confetti."""
    img = _canvas((70, 44, 100), NIGHT_DARK)
    d = ImageDraw.Draw(img)
    rnd = random.Random()
    colors = [GOLD, RED, GREEN, (80, 160, 255), WHITE, (255, 120, 200)]
    for _ in range(160):
        x, y, s = rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(6, 13)
        d.rectangle(_s(x, y, x + s, y + s * 0.5), fill=rnd.choice(colors))
    cx = W / 2
    for side in (-1, 1):  # handles
        hx = cx + side * 140
        d.ellipse(_s(hx - 55, 90, hx + 55, 220), outline=GOLD, width=18 * SS)
    d.pieslice(_s(cx - 130, 40, cx + 130, 310), 0, 180, fill=GOLD)
    d.rectangle(_s(cx - 130, 70, cx + 130, 176), fill=GOLD)
    d.rectangle(_s(cx - 24, 300, cx + 24, 382), fill=(210, 160, 50))
    d.rounded_rectangle(_s(cx - 110, 380, cx + 110, 420), 8 * SS, fill=(200, 150, 45))
    d.rounded_rectangle(_s(cx - 150, 420, cx + 150, 482), 10 * SS, fill=(70, 40, 30))
    _star(d, cx, 175, 58, WHITE)
    return _png(img)
