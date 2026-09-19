# -*- coding: utf-8 -*-
"""
Render menu thành ảnh PNG.
- render_menu()      : menu text (nền trắng)
- render_card_menu() : menu card grid VUÔNG 1080x1080 giống QAZN
Tự động dò font + cho phép đổi font qua lệnh .setfont
"""
import os
import re
import glob
import json
import time
import threading

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None


# ================= ĐƯỜNG DẪN =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
FONT_CONFIG_FILE = os.path.join(BASE_DIR, "font_config.json")


# ================= FONT SYSTEM =================
_FONT_PRIORITY = [
    "UTM AvoBold.ttf",
    "SFProRounded-Medium.otf",
    "Linotte Semi Bold.ttf",
    "Product Sans Bold.otf",
    "BeVietnamPro-Bold.ttf",
    "BeVietnamPro-SemiBold.ttf",
    "BeVietnamPro-Medium.ttf",
    "BeVietnamPro-Regular.ttf",
    "Roboto-Bold.ttf",
    "NotoSans-Bold.ttf",
]


def _load_font_choice():
    """Đọc font đang chọn từ font_config.json."""
    try:
        if os.path.exists(FONT_CONFIG_FILE):
            with open(FONT_CONFIG_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            name = str(d.get("font", "")).strip()
            if name:
                p = os.path.join(BASE_DIR, name)
                if os.path.exists(p):
                    return p
    except Exception as e:
        print(f"[MENUPIC] Lỗi đọc font config: {e}")
    return None


def _save_font_choice(name):
    try:
        with open(FONT_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"font": name}, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[MENUPIC] Lỗi lưu font config: {e}")
        return False


def set_font(name):
    """Đổi font. Trả về (ok, message)."""
    name = str(name).strip()
    p = os.path.join(BASE_DIR, name)
    if not os.path.exists(p):
        return False, f"Không tìm thấy font '{name}' trong thư mục bot"
    if _save_font_choice(name):
        return True, f"Đã đổi font → {name}"
    return False, "Lỗi lưu font_config.json"


def get_current_font():
    """Trả về tên font đang dùng."""
    p = _load_font_choice()
    if p:
        return os.path.basename(p)
    p = _find_font()
    return os.path.basename(p) if p else "(không có)"


def list_fonts():
    """Liệt kê font có sẵn trong thư mục bot."""
    fonts = []
    for ext in ("*.ttf", "*.otf"):
        for p in glob.glob(os.path.join(BASE_DIR, ext)):
            fonts.append(os.path.basename(p))
    return sorted(fonts)


def _find_font():
    """Tìm font đầu tiên khớp danh sách ưu tiên."""
    # 1. Theo priority
    for name in _FONT_PRIORITY:
        p = os.path.join(BASE_DIR, name)
        if os.path.exists(p):
            return p
    # 2. BeVietnamPro bất kỳ
    for p in glob.glob(os.path.join(BASE_DIR, "*BeVietnamPro*.ttf")):
        return p
    # 3. Bất kỳ .ttf/.otf nào
    for p in glob.glob(os.path.join(BASE_DIR, "*.ttf")) + glob.glob(os.path.join(BASE_DIR, "*.otf")):
        return p
    return None


def _resolve_font_path():
    """Trả về path font đang dùng (user choice > priority)."""
    p = _load_font_choice()
    if p:
        return p
    return _find_font()


# Log lần đầu
_init = _resolve_font_path()
if _init:
    print(f"[MENUPIC] Dùng font: {os.path.basename(_init)}")
else:
    print("[MENUPIC] ⚠️ Không có file font → dùng font mặc định PIL")


# ================= MÀU SẮC =================
BG_SIZE_WHITE = (1080, 1920)
BG_COLOR_WHITE = (255, 255, 255)
COLOR_MAIN_W = (200, 30, 30)
COLOR_HEAD_W = (20, 90, 180)
COLOR_BODY_W = (30, 30, 30)

BG_TOP        = (14, 20, 34)
BG_BOTTOM     = (8, 12, 22)
TITLE_COLOR   = (255, 255, 255)
CARD_BG       = (28, 38, 58, 200)
CARD_BORDER   = (58, 78, 118, 230)
CMD_COLOR     = (255, 255, 255)
DESC_COLOR    = (140, 160, 190)
BADGE_BORDER  = (72, 120, 200)
BADGE_TEXT    = (120, 180, 255)
PAGE_BORDER   = (72, 100, 150)

_bg_cache = None
_bg_lock  = threading.Lock()


# ================= HELPERS =================
_KEEP_RE = re.compile(r'[\x20-\x7E\u00A0-\u1EF9\n]')

def _clean(s: str) -> str:
    return ''.join(c for c in s if _KEEP_RE.match(c))


def _font(size):
    """Load font theo size — ưu tiên font user chọn, đọc động mỗi lần gọi."""
    p = _resolve_font_path()
    if p and os.path.exists(p):
        try:
            return ImageFont.truetype(p, size)
        except Exception as e:
            print(f"[MENUPIC] Load font lỗi: {e}")
    # Fallback system font
    for sysfont in (
        "/system/fonts/Roboto-Bold.ttf",
        "/system/fonts/Roboto-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            if os.path.exists(sysfont):
                return ImageFont.truetype(sysfont, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_with_outline(draw, pos, text, font, fill, outline=(255, 255, 255), thickness=1):
    x, y = pos
    if thickness > 0:
        for dx in range(-thickness, thickness + 1):
            for dy in range(-thickness, thickness + 1):
                if dx or dy:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def _fit_text(draw, text, font, max_width):
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return text + ellipsis


def _make_gradient(W, H, color_top, color_bottom):
    img = Image.new("RGB", (W, H), color_top)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / max(1, H - 1)
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * t)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * t)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    return img


# ================= RENDER MENU (NỀN TRẮNG) =================
def render_menu(text, out_path=None, title=None,
                color_main=COLOR_MAIN_W,
                color_head=COLOR_HEAD_W,
                color_body=COLOR_BODY_W):
    if Image is None:
        raise RuntimeError("Thiếu Pillow. Cài: pip install Pillow")

    W, H = BG_SIZE_WHITE
    bg = Image.new("RGB", (W, H), BG_COLOR_WHITE)

    raw_lines = [_clean(l).rstrip() for l in text.split("\n")]
    lines = [l for l in raw_lines if l.strip()]

    if title is None:
        title = lines[0] if lines else "MENU"
        lines = lines[1:]
    title = _clean(title)

    f_title = _font(66)
    f_head  = _font(40)
    f_body  = _font(32)

    PAD_X = 60
    TOP_Y = 100
    LINE_H = 46
    HEAD_EXTRA = 14

    body_h = 0
    for l in lines:
        st = l.strip()
        is_head = st.endswith(":") or (st and st.isupper()) or st.startswith(("---", "==="))
        body_h += LINE_H + (HEAD_EXTRA if is_head else 0)

    needed = TOP_Y + 120 + 30 + body_h + 80
    canvas_h = max(H, needed)

    if canvas_h > H:
        canvas = Image.new("RGB", (W, canvas_h), BG_COLOR_WHITE)
        canvas.paste(bg, (0, 0))
        base = canvas
    else:
        base = bg

    img = base.convert("RGBA")
    draw = ImageDraw.Draw(img)

    y = TOP_Y
    tw = draw.textlength(title, font=f_title)
    _draw_with_outline(draw, ((W - tw) // 2, y), title, f_title, color_main, thickness=1)
    y += 120

    draw.line([(PAD_X, y), (W - PAD_X, y)], fill=color_main, width=3)
    y += 30

    for l in lines:
        st = l.strip()
        is_head = st.endswith(":") or (st and st.isupper()) or st.startswith(("---", "==="))

        if is_head:
            font  = f_head
            color = color_head
            y += HEAD_EXTRA
        else:
            font  = f_body
            color = color_body

        _draw_with_outline(draw, (PAD_X, y), l, font, color, thickness=1)
        y += LINE_H

        if y > canvas_h - 60:
            break

    if out_path is None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        out_path = os.path.join(CACHE_DIR, f"menu_{int(time.time() * 1000)}.png")

    img.convert("RGB").save(out_path, quality=92, optimize=True)
    return out_path


# ================= RENDER CARD MENU (VUÔNG 1080x1080) =================
def render_card_menu(commands, title="MENU", page_num=1, out_path=None,
                     card_tag="USER"):
    """Menu card VUÔNG 1080x1080 — vẽ trực tiếp, giống QAZN."""
    if Image is None:
        raise RuntimeError("Thiếu Pillow. Cài: pip install Pillow")

    W = 1080
    H = 1080

    COLS = 4
    PAD_X = 25
    PAD_TOP = 20
    PAD_BOT = 20
    GAP = 12

    HEADER_H = 155
    MAX_ROWS = 5

    avail_w = W - PAD_X * 2 - GAP * (COLS - 1)
    CARD_W = avail_w // COLS

    avail_h = H - HEADER_H - PAD_BOT
    rows = min((len(commands) + COLS - 1) // COLS, MAX_ROWS)
    if rows == 0:
        rows = 1
    CARD_H = (avail_h - GAP * (rows - 1)) // rows

    base = _make_gradient(W, H, BG_TOP, BG_BOTTOM).convert("RGBA")
    img = base
    draw = ImageDraw.Draw(img)

    f_title = _font(72)
    f_page  = _font(32)
    f_cmd   = _font(30)
    f_desc  = _font(16)
    f_badge = _font(13)

    title_txt = _clean(title)
    tw = draw.textlength(title_txt, font=f_title)
    draw.text(((W - tw) // 2, 30), title_txt, font=f_title, fill=TITLE_COLOR)

    page_str = f"{page_num:02d}"
    pw = draw.textlength(page_str, font=f_page)
    bx1, by1 = W - pw - 85, 35
    bx2, by2 = W - 30, 88
    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=26,
                           outline=PAGE_BORDER, width=3)
    draw.text((bx1 + (bx2 - bx1 - pw) // 2, by1 + 8),
              page_str, font=f_page, fill=TITLE_COLOR)

    draw.line([(PAD_X, 120), (W - PAD_X, 120)], fill=(50, 70, 110), width=2)

    for i, item in enumerate(commands):
        if i >= MAX_ROWS * COLS:
            break
        r = i // COLS
        c = i % COLS
        x = PAD_X + c * (CARD_W + GAP)
        y = HEADER_H + r * (CARD_H + GAP)

        card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], radius=12,
                             fill=CARD_BG, outline=CARD_BORDER, width=2)
        img.paste(card, (x, y), card)

        cmd_txt  = _clean(item.get("cmd", ""))
        desc_txt = _clean(item.get("desc", ""))
        tag_txt  = _clean(item.get("tag", card_tag))

        draw.text((x + 15, y + 15), cmd_txt, font=f_cmd, fill=CMD_COLOR)

        desc_show = _fit_text(draw, desc_txt, f_desc, CARD_W - 30)
        draw.text((x + 15, y + 55), desc_show, font=f_desc, fill=DESC_COLOR)

        tag_w = draw.textlength(tag_txt, font=f_badge)
        pad_badge_x = 9
        pad_badge_y = 3
        badge_w = tag_w + pad_badge_x * 2
        badge_h = 20
        bx1 = x + CARD_W - badge_w - 10
        by1 = y + CARD_H - badge_h - 10
        bx2 = x + CARD_W - 10
        by2 = y + CARD_H - 10
        draw.rounded_rectangle([bx1, by1, bx2, by2], radius=10,
                               outline=BADGE_BORDER, width=2)
        draw.text((bx1 + pad_badge_x, by1 + pad_badge_y),
                  tag_txt, font=f_badge, fill=BADGE_TEXT)

    if out_path is None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        out_path = os.path.join(CACHE_DIR, f"menu_{int(time.time() * 1000)}.png")

    img.convert("RGB").save(out_path, quality=92, optimize=True)
    return out_path


def clear_cache():
    global _bg_cache
    with _bg_lock:
        _bg_cache = None
