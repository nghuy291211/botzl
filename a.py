# -*- coding: utf-8 -*-
import json, os, re, sys, time, platform, random, threading, inspect, tempfile, shutil, subprocess
from datetime import datetime

try:
    from zlapi import ZaloAPI
except Exception as e:
    print(f"[!] Không import được zlapi: {e}"); sys.exit(1)
try:
    from zlapi.models import Message
except Exception: Message = None
try:
    from zlapi.models import Mention
except Exception: Mention = None
try:
    from zlapi.models import ThreadType
except Exception:
    class ThreadType:
        GROUP = "Group"; USER = "User"
try:
    from zlapi.models import Sticker
except Exception: Sticker = None
try:
    from zlapi.models import MessageStyle, MultiMsgStyle
except Exception:
    MessageStyle = None
    MultiMsgStyle = None

# ================== FAST ASYNC SEND QUEUE ==================
import queue as _queue_mod

_FAST_SEND_QUEUE = _queue_mod.Queue(maxsize=8000)
_FAST_SEND_STOP = threading.Event()
_FAST_WORKERS_STARTED = False
_FAST_WORKER_COUNT = 10

def _fast_send_loop():
    while not _FAST_SEND_STOP.is_set():
        try:
            job = _FAST_SEND_QUEUE.get(timeout=0.5)
        except _queue_mod.Empty:
            continue
        if job is None:
            continue
        try:
            job()
        except Exception as e:
            try: print(f"[FAST-Q] {e}")
            except Exception: pass

def _ensure_fast_workers():
    global _FAST_WORKERS_STARTED
    if _FAST_WORKERS_STARTED:
        return
    _FAST_WORKERS_STARTED = True
    for _ in range(_FAST_WORKER_COUNT):
        t = threading.Thread(target=_fast_send_loop, daemon=True, name="FastSend")
        t.start()

def _enqueue_fast(job):
    _ensure_fast_workers()
    try:
        _FAST_SEND_QUEUE.put_nowait(job)
        return True
    except _queue_mod.Full:
        try: _FAST_SEND_QUEUE.get_nowait()
        except Exception: pass
        try:
            _FAST_SEND_QUEUE.put_nowait(job)
            return True
        except Exception:
            return False
# ===========================================================

CONFIG_FILE = "config.json"
if not os.path.exists(CONFIG_FILE):
    print(f"❌ Không tìm thấy {CONFIG_FILE}!"); sys.exit(1)
try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        _cfg = json.load(f)
except Exception as e:
    print(f"❌ Lỗi đọc {CONFIG_FILE}: {e}"); sys.exit(1)

IMEI = str(_cfg.get("imei", "")).strip()
COOKIES = _cfg.get("cookies", {})
if not IMEI or IMEI.startswith("DÁN_"): print("❌ Chưa điền IMEI!"); sys.exit(1)
if not COOKIES or not isinstance(COOKIES, dict): print("❌ Chưa điền COOKIES!"); sys.exit(1)
print(f"✅ Load config OK | IMEI: {len(IMEI)} | {len(COOKIES)} cookies")

PERM_FILE   = "zalo_perms.json"
MUTE_FILE   = "mute_list.json"
COPY_FILE   = "copy_list.json"
GROUP_FILE  = "group_config.json"
STICKER_FILE= "custom_stickers.json"
PREFIX_FILE = "prefix.json"
WAR_FILE    = "war.txt"
CHUI_FILE   = "chui.txt"
SEND_DELAY  = 0.5
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
VOICE_EXTS = (".aac", ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".amr")

# ================== PREFIX ==================
def _load_prefix():
    try:
        if os.path.exists(PREFIX_FILE):
            with open(PREFIX_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            p = str(d.get("prefix", "!")).strip()
            if p and " " not in p and len(p) <= 3 and not p.isalnum():
                return p
    except Exception as e:
        print(f"[PREFIX] Lỗi load: {e}")
    return "!"

def _save_prefix(p):
    try:
        with open(PREFIX_FILE, "w", encoding="utf-8") as f:
            json.dump({"prefix": p}, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[PREFIX] Lỗi lưu: {e}")

PREFIX = _load_prefix()
print(f"✅ Prefix hiện tại: '{PREFIX}'")

START_TIME = time.time()
BOT_OWNER_ID = None
BOT_NAME = "Bot Zalo By Ng Huy 😶‍🌫️😶‍🌫️"
BOT_SLEEPING = False
MUTED_USERS = {}
COPY_TARGETS = {}
WAR_RUNNING = {}
CHUI_RUNNING = {}
SPAM_RUNNING = {}
GROUP_SETTINGS = {}
GAME_STATE = {}
CUSTOM_STICKERS = {}

WAR_DELAY_DEFAULT = 1
WAR_DELAY_MIN = 0.2
WAR_DELAY_MAX = 60.0
WAR_CONFIRM_TIMEOUT = 60
CHUI_DELAY_DEFAULT = 1.0
CHUI_DELAY_MIN = 0.2
CHUI_DELAY_MAX = 60.0
SPAM_DELAY_DEFAULT = 0.5
SPAM_DELAY_MIN = 0.2
SPAM_DELAY_MAX = 60.0
MUTE_DELETE_DELAY = 0.5

WAR_CONFIRM_WORDS = {"yes","y","ok","oke","okay","có","co","ừ","u","đồng ý","dong y","xác nhận","xac nhan"}
WAR_CANCEL_WORDS  = {"no","n","không","khong","hủy","huy","cancel"}
WAR_PENDING = {}
CHUI_PENDING = {}
SPAM_PENDING = {}

# ================== LIKE FF ==================
LIKE_API_URL = "https://likes-9qet.onrender.com/likes"
LIKE_API_KEY = "ditmoemay"
LIKE_DAILY_LIMIT = None
LIKE_USAGE_TODAY = {}

def _call(x):
    if callable(x):
        try: return x()
        except Exception: return x
    return x

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return default
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

ALLOWED_USERS   = load_json(PERM_FILE, {})
MUTED_USERS     = load_json(MUTE_FILE, {})
COPY_TARGETS    = load_json(COPY_FILE, {})
GROUP_SETTINGS  = load_json(GROUP_FILE, {})
CUSTOM_STICKERS = load_json(STICKER_FILE, {})

def is_user_allowed(uid):
    if not uid: return False
    if str(uid) == str(BOT_OWNER_ID): return True
    return str(uid) in ALLOWED_USERS

def is_owner(uid):
    return str(uid) == str(BOT_OWNER_ID)

def _get_group_data(bot, gid):
    info = None
    for mn in ("fetchGroupInfo","getGroupInfo","get_group_info","getGroupInfoById"):
        if hasattr(bot, mn):
            try:
                info = getattr(bot, mn)(gid); break
            except Exception: continue
    if info is None: return None
    grid = info.get("gridInfoMap") if isinstance(info, dict) else getattr(info, "gridInfoMap", None)
    if grid is None: return info
    if isinstance(grid, dict) and grid:
        return list(grid.values())[0]
    if hasattr(grid, "items"):
        try: return list(grid.items())[0][1]
        except Exception: pass
    return grid

def is_group_admin(bot, gid, uid):
    if not uid: return False
    if is_user_allowed(uid): return True
    try:
        gd = _get_group_data(bot, gid)
        if gd is None: return False
        creator = None
        for k in ("creatorId","creator_id","creator","ownerId"):
            v = gd.get(k) if isinstance(gd, dict) else getattr(gd, k, None)
            if v: creator = v; break
        admins = []
        for k in ("adminIds","admin_ids","admins"):
            v = gd.get(k) if isinstance(gd, dict) else getattr(gd, k, None)
            if v: admins = v; break
        if str(creator) == str(uid): return True
        if isinstance(admins, (list, tuple)) and any(str(a) == str(uid) for a in admins): return True
    except Exception: pass
    return False

def get_group_settings(gid):
    gid = str(gid)
    if gid not in GROUP_SETTINGS:
        GROUP_SETTINGS[gid] = {"antilink": False, "antiimage": False, "antivideo": False, "antifile": False, "lock": False}
        save_json(GROUP_FILE, GROUP_SETTINGS)
    return GROUP_SETTINGS[gid]

def save_group_settings():
    save_json(GROUP_FILE, GROUP_SETTINGS)

# ================== MÀU CHỮ ==================
ZALO_COLOR_CODES = {
    "red": "db342e", "orange": "f27806",
    "yellow": "f7b503", "green": "15a85f",
}

def _build_style(text, color):
    if MessageStyle is None or MultiMsgStyle is None:
        return None
    code = ZALO_COLOR_CODES.get(color, "f7b503")
    L = len(text)
    attempts = [
        lambda: MessageStyle(style="color", color=code, offset=0, length=L, auto_format=False),
        lambda: MessageStyle(style="color", color=code, offset=0, length=L),
        lambda: MessageStyle(style="color", color=code, start=0, length=L),
    ]
    for fn in attempts:
        try:
            s = fn()
            try: return MultiMsgStyle([s])
            except Exception: return s
        except Exception:
            continue
    return None


def send_colored_message(bot, tid, ttype, text, color="yellow"):
    text = str(text)[:1900]
    if Message is None:
        return None
    style = _build_style(text, color)
    if style is None:
        return bot_send(bot, tid, ttype, text)

    msg_obj = None
    try:
        msg_obj = Message(text=text, style=style)
    except Exception:
        try:
            msg_obj = Message(text=text)
            msg_obj.style = style
        except Exception:
            return bot_send(bot, tid, ttype, text)

    for mname in ("send", "sendMessage"):
        if hasattr(bot, mname):
            try:
                return getattr(bot, mname)(msg_obj, tid, ttype)
            except Exception as e:
                print(f"[COLOR-SEND] {mname} lỗi: {e}")
    try:
        return bot.send(message=msg_obj, thread_id=tid, thread_type=ttype)
    except Exception as e:
        print(f"[COLOR-SEND] kw lỗi: {e}")
    return bot_send(bot, tid, ttype, text)


def _looks_like_heading_message(text):
    if "\n" not in text:
        return False
    first = text.split("\n", 1)[0].strip()
    heading_emojis = ("🤖","⚙","👑","👥","🛡","🎨","⚔","🎮","❤","ℹ","📋","🔍","🏆","📢","⚡","🚫","⭐","🎯","💡")
    return any(first.startswith(e) for e in heading_emojis)


def _send_with_heading_color(bot, tid, ttype, text, color="yellow"):
    if Message is None or MessageStyle is None or MultiMsgStyle is None:
        return bot_send(bot, tid, ttype, text)

    code = ZALO_COLOR_CODES.get(color, "f7b503")
    lines = text.split("\n")
    styles = []
    pos = 0

    heading_emojis = ("🤖","⚙","👑","👥","🛡","🎨","⚔","🎮","❤","ℹ","📋","🔍","🏆","📢","⚡","🚫","⭐","🎯","💡")

    for i, line in enumerate(lines):
        stripped = line.strip()
        is_heading = False

        if i == 0 and stripped:
            is_heading = True
        elif stripped.startswith(("┏━", "┗━", "╔═", "╚═", "╭", "╰", "║")):
            is_heading = True
        elif stripped and any(stripped.startswith(e) for e in heading_emojis) and ":" in stripped:
            is_heading = True

        if is_heading:
            s = None
            for fn in (
                lambda: MessageStyle(style="color", color=code, offset=pos, length=len(line)),
                lambda: MessageStyle(style="color", color=code, start=pos, length=len(line)),
            ):
                try:
                    s = fn(); break
                except Exception: continue
            if s:
                styles.append(s)

        pos += len(line) + 1

    if not styles:
        return bot_send(bot, tid, ttype, text)

    try:
        multi = MultiMsgStyle(styles)
    except Exception:
        multi = styles[0]

    msg_obj = None
    try:
        msg_obj = Message(text=text, style=multi)
    except Exception:
        try:
            msg_obj = Message(text=text)
            msg_obj.style = multi
        except Exception:
            return bot_send(bot, tid, ttype, text)

    for mname in ("send", "sendMessage"):
        if hasattr(bot, mname):
            try:
                return getattr(bot, mname)(msg_obj, tid, ttype)
            except Exception as e:
                print(f"[HEADING] {mname} lỗi: {e}")
    return bot_send(bot, tid, ttype, text)

# ===========================================================

def bot_send(bot, tid, ttype, text, skip_delay=False):
    text = str(text)[:1900]
    if Message is None: return None
    msg_obj = None
    for kwargs in ({"text": text}, {"description": text}, {"title": text}):
        try: msg_obj = Message(**kwargs); break
        except Exception: pass
    if msg_obj is None: return None
    delay = 0 if skip_delay else SEND_DELAY
    for mname in ("send", "sendMessage"):
        if not hasattr(bot, mname): continue
        try:
            r = getattr(bot, mname)(msg_obj, tid, ttype)
            if delay: time.sleep(delay)
            return r
        except Exception: pass
    try:
        r = bot.send(message=msg_obj, thread_id=tid, thread_type=ttype)
        if delay: time.sleep(delay)
        return r
    except Exception: pass
    return None

def send_reply(bot, tid, ttype, text, mention_id=None, color=None):
    """
    Gửi tin trả lời. Quy tắc màu:
      ✅/🟢 → XANH   |  ❌/🛑 → ĐỎ  |  ⚠️/🔴 → CAM
      Có đề mục → VÀNG cho đề mục
      Còn lại → KHÔNG màu
    """
    text = str(text)
    if not text.strip():
        return

    head = text.lstrip()[:10]

    if head.startswith("✅") or head.startswith("🟢"):
        return send_colored_message(bot, tid, ttype, text, color="green")
    if head.startswith("❌") or head.startswith("🛑"):
        return send_colored_message(bot, tid, ttype, text, color="red")
    if head.startswith("⚠️") or head.startswith("🔴"):
        return send_colored_message(bot, tid, ttype, text, color="orange")

    if color:
        return send_colored_message(bot, tid, ttype, text, color=color)

    if _looks_like_heading_message(text):
        return _send_with_heading_color(bot, tid, ttype, text, color="yellow")

    return bot_send(bot, tid, ttype, text)

def bot_send_mention(bot, tid, ttype, content, target_uid):
    content = str(content)[:1900]
    tag_text = f"@{target_uid}"
    full_text = f"{tag_text} {content}"
    if Message is None:
        return bot_send(bot, tid, ttype, full_text, skip_delay=True)
    if Mention is not None:
        try:
            mention = Mention(target_uid, length=len(tag_text), offset=0)
            msg = Message(text=full_text, mention=mention)
            if hasattr(bot, "sendMentionMessage"):
                try:
                    r = bot.sendMentionMessage(msg, tid, ttype)
                    if r: return r
                except Exception: pass
        except Exception: pass
    if Mention is not None:
        try:
            mention = Mention(target_uid, length=len(tag_text), offset=0)
            msg = Message(text=full_text, mention=mention)
            for mname in ("send", "sendMessage"):
                if hasattr(bot, mname):
                    try:
                        r = getattr(bot, mname)(msg, tid, ttype)
                        if r: return r
                    except Exception: pass
        except Exception: pass
    try:
        msg = Message(text=full_text)
        for mname in ("sendMentionMessage", "send", "sendMessage"):
            if hasattr(bot, mname):
                try:
                    r = getattr(bot, mname)(msg, tid, ttype)
                    if r: return r
                except Exception: pass
    except Exception: pass
    return bot_send(bot, tid, ttype, full_text, skip_delay=True)

def bot_send_nowait(bot, tid, ttype, text):
    text_cut = str(text)[:1900]
    def _do():
        if Message is None: return
        msg_obj = None
        for kwargs in ({"text": text_cut}, {"description": text_cut}, {"title": text_cut}):
            try: msg_obj = Message(**kwargs); break
            except Exception: pass
        if msg_obj is None: return
        for mname in ("send", "sendMessage"):
            if not hasattr(bot, mname): continue
            try:
                getattr(bot, mname)(msg_obj, tid, ttype); return
            except Exception: pass
        try:
            bot.send(message=msg_obj, thread_id=tid, thread_type=ttype)
        except Exception: pass
    return _enqueue_fast(_do)


def bot_send_mention_nowait(bot, tid, ttype, content, target_uid):
    content_cut = str(content)[:1900]
    tag_text = f"@{target_uid}"
    full_text = f"{tag_text} {content_cut}"
    def _do():
        if Message is None: return
        msg_obj = None
        if Mention is not None:
            try:
                mention = Mention(target_uid, length=len(tag_text), offset=0)
                msg_obj = Message(text=full_text, mention=mention)
            except Exception: pass
        if msg_obj is None:
            for kwargs in ({"text": full_text}, {"description": full_text}):
                try: msg_obj = Message(**kwargs); break
                except Exception: pass
        if msg_obj is None: return
        if hasattr(bot, "sendMentionMessage"):
            try:
                bot.sendMentionMessage(msg_obj, tid, ttype); return
            except Exception: pass
        for mname in ("sendMentionMessage", "send", "sendMessage"):
            if not hasattr(bot, mname): continue
            try:
                getattr(bot, mname)(msg_obj, tid, ttype); return
            except Exception: pass
    return _enqueue_fast(_do)

def bot_send_image(bot, tid, ttype, image_path, caption=""):
    if not os.path.exists(image_path): return False
    if hasattr(bot, "sendLocalImage"):
        try:
            r = bot.sendLocalImage(imagePath=image_path, thread_id=tid, thread_type=ttype, message=caption); return True
        except Exception: pass
        if caption:
            try:
                r = bot.sendLocalImage(imagePath=image_path, thread_id=tid, thread_type=ttype, caption=caption); return True
            except Exception: pass
        try:
            r = bot.sendLocalImage(image_path, tid, ttype, caption); return True
        except Exception: pass
        try:
            r = bot.sendLocalImage(image_path, tid, ttype)
            if caption:
                time.sleep(0.5); bot_send(bot, tid, ttype, caption, skip_delay=True)
            return True
        except Exception: pass
    if hasattr(bot, "sendImage"):
        try:
            r = bot.sendImage(image_path, tid, ttype, caption); return True
        except Exception: pass
    return False

def upload_to_catbox(filepath):
    try:
        if not os.path.exists(filepath): return None
        if os.path.getsize(filepath) / (1024 * 1024) > 200: return None
        import requests as req
        with open(filepath, "rb") as f:
            files = {"fileToUpload": (os.path.basename(filepath), f)}
            r = req.post("https://catbox.moe/user/api.php",
                         data={"reqtype": "fileupload", "userhash": ""},
                         files=files, timeout=120)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return r.text.strip()
    except Exception as e:
        print(f"[UPLOAD-CATBOX] Lỗi: {e}")
    return None

def upload_to_uguu(filepath):
    try:
        if not os.path.exists(filepath): return None
        import requests
        with open(filepath, "rb") as f:
            r = requests.post("https://uguu.se/upload.php",
                              files={"files[]": (os.path.basename(filepath), f)},
                              timeout=60)
        print(f"[UPLOAD-UGUU] HTTP {r.status_code} | {r.text[:200]}")
        if r.status_code == 200:
            try:
                d = r.json()
                if d.get("success") and d.get("files"):
                    return d["files"][0].get("url")
            except Exception:
                for line in r.text.splitlines():
                    line = line.strip()
                    if line.startswith("http"):
                        return line
    except Exception as e:
        print(f"[UPLOAD-UGUU] Lỗi: {e}")
    return None

def upload_to_tmpfiles(filepath):
    try:
        if not os.path.exists(filepath): return None
        import requests
        with open(filepath, "rb") as f:
            r = requests.post("https://tmpfiles.org/api/v1/upload",
                              files={"file": (os.path.basename(filepath), f)},
                              timeout=60)
        if r.status_code == 200:
            d = r.json()
            url = d.get("data", {}).get("url")
            if url:
                return url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception as e:
        print(f"[UPLOAD-TMPFILES] Lỗi: {e}")
    return None

def upload_voice_smart(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    tmp_path = filepath
    renamed = False
    if ext == ".aac":
        tmp_path = filepath.rsplit(".", 1)[0] + ".m4a"
        try:
            shutil.copy(filepath, tmp_path)
            renamed = True
        except Exception: tmp_path = filepath

    hosts = [
        ("uguu",     upload_to_uguu),
        ("catbox",   upload_to_catbox),
        ("tmpfiles", upload_to_tmpfiles),
    ]
    for name, fn in hosts:
        print(f"[UPLOAD] Thử host: {name}")
        url = fn(tmp_path)
        if url:
            print(f"[UPLOAD] ✅ {name} → {url}")
            if renamed:
                try: os.remove(tmp_path)
                except Exception: pass
            return url
    if renamed:
        try: os.remove(tmp_path)
        except Exception: pass
    return None

def bot_send_voice(bot, tid, ttype, voice_url):
    if not voice_url: return None
    candidates = [
        ("sendVoice",         lambda m: m(voice_url, tid, ttype)),
        ("sendVoiceMessage",  lambda m: m(voice_url, tid, ttype)),
        ("sendRemoteVoice",   lambda m: m(voice_url, tid, ttype)),
        ("sendVoice",         lambda m: m(voiceUrl=voice_url, thread_id=tid, thread_type=ttype)),
        ("sendVoiceMessage",  lambda m: m(voiceUrl=voice_url, thread_id=tid, thread_type=ttype)),
        ("sendRemoteVoice",   lambda m: m(voiceUrl=voice_url, thread_id=tid, thread_type=ttype)),
    ]
    for mname, caller in candidates:
        if not hasattr(bot, mname): continue
        try:
            r = caller(getattr(bot, mname))
            return r
        except Exception:
            continue
    if Message is not None:
        for kw in ({"voiceUrl": voice_url}, {"voice_url": voice_url}, {"voice": voice_url}):
            try:
                msg = Message(**kw)
                for mname in ("send", "sendMessage"):
                    if hasattr(bot, mname):
                        try: return getattr(bot, mname)(msg, tid, ttype)
                        except Exception: pass
            except Exception: pass
    return None

def format_uptime(s):
    d, h = divmod(int(s), 86400); h, m = divmod(h, 3600); m, s = divmod(m, 60)
    p = []
    if d: p.append(f"{d} ngày")
    if h: p.append(f"{h} giờ")
    if m: p.append(f"{m} phút")
    p.append(f"{s} giây")
    return " ".join(p)

def parse_message_text(message):
    if message is None: return ""
    if isinstance(message, str): return message.strip()
    if isinstance(message, dict):
        for k in ("text", "content", "body", "message"):
            v = message.get(k)
            if isinstance(v, str) and v.strip(): return v.strip()
        return ""
    for k in ("text", "content", "body", "message"):
        v = getattr(message, k, None)
        if isinstance(v, str) and v.strip(): return v.strip()
    return ""

def detect_media_type(message):
    if message is None or isinstance(message, str): return None
    def _get(n): return message.get(n) if isinstance(message, dict) else getattr(message, n, None)
    href = str(_get("href") or _get("url") or "").lower()
    thumb = _get("thumb") or ""
    mtype = str(_get("type") or "").lower()
    psticker = _get("pStickerType"); sticker_by = _get("stickerCreatedBy")
    if psticker and str(psticker) not in ("0","None",""): return "sticker"
    if sticker_by and str(sticker_by) not in ("None",""): return "sticker"
    if "sticker" in href or "sticker" in mtype: return "sticker"
    if "video" in href or "video" in mtype: return "video"
    if any(e in href for e in (".mp4",".mov",".avi",".mkv")): return "video"
    if "file" in mtype or "file" in href: return "file"
    if any(e in href for e in (".pdf",".doc",".docx",".xls",".xlsx",".ppt",".pptx",".zip",".rar",".7z",".apk",".txt")): return "file"
    if "image" in href or "image" in mtype: return "image"
    if any(e in href for e in (".jpg",".jpeg",".png",".gif",".webp",".bmp")): return "image"
    if thumb: return "image"
    return None

LINK_PATTERN = re.compile(r"(https?://\S+|www\.\S+|\S+\.(com|vn|net|org|io|co|me|info|xyz|top|link|site|online|app|dev|fun|club)\b)", re.IGNORECASE)
def contains_link(text): return bool(LINK_PATTERN.search(text)) if text else False

def extract_mentions(obj):
    if obj is None: return []
    uids = []; raw = None
    for k in ("mention","mentions","mentions_data","mentionsData"):
        v = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
        if v: raw = v; break
    if not raw: return []
    lst = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    for m in lst:
        uid = None
        if isinstance(m, dict):
            for k in ("uid","userId","user_id","id","uidFrom"):
                if m.get(k): uid = m[k]; break
        else:
            for k in ("uid","userId","user_id","id","uidFrom"):
                v = getattr(m, k, None)
                if v: uid = v; break
        if uid: uids.append(str(uid))
    return uids

def extract_target_uid(ctext, obj, bot_uid):
    for uid in extract_mentions(obj):
        if str(uid) != str(bot_uid): return uid
    m = re.search(r'@?(\d{8,})', ctext)
    if m: return m.group(1)
    return None

def get_msg_id(obj):
    if obj is None: return None
    for k in ("msgId","msg_id","message_id","globalMsgId","global_msg_id","id"):
        v = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
        if v: return str(v)
    return None

def get_client_msg_id(obj):
    if obj is None: return None
    for k in ("cliMsgId","cli_msg_id","clientMsgId","client_msg_id"):
        v = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
        if v: return str(v)
    return None

def delete_message(bot, obj, tid, ttype, author_id=None):
    if obj is None: return False
    msg_id = get_msg_id(obj); cli_id = get_client_msg_id(obj)
    if not msg_id or not hasattr(bot, "deleteGroupMsg"): return False
    for owner in ([author_id, BOT_OWNER_ID, msg_id] if author_id else [BOT_OWNER_ID, msg_id]):
        for cli in (cli_id, None):
            try:
                bot.deleteGroupMsg(msg_id, str(owner), cli, tid); return True
            except Exception: pass
    return False

def delayed_delete(bot, obj, tid, ttype, author_id=None, delay=None):
    if obj is None: return
    d = MUTE_DELETE_DELAY if delay is None else max(0.0, float(delay))
    def _do():
        try:
            if d > 0: time.sleep(d)
            delete_message(bot, obj, tid, ttype, author_id=author_id)
        except Exception as e:
            try: print(f"[DELAYED-DEL] {e}")
            except Exception: pass
    threading.Thread(target=_do, daemon=True, name="DelayedDelete").start()

# ================== FIX NHÓM THEO ĐÚNG ZLAPI ==================
def kick_user(bot, gid, uid):
    if not uid or str(uid) == str(BOT_OWNER_ID): return False
    try:
        bot.kickUsersInGroup(members=[str(uid)], groupId=str(gid))
        return True
    except Exception as e:
        print(f"[KICK ERROR] {e}")
        return False

def add_user_to_group(bot, gid, uid):
    if not uid: return False
    try:
        bot.addUsersToGroup(user_ids=[str(uid)], groupId=str(gid))
        return True
    except Exception as e:
        print(f"[ADD USER ERROR] {e}")
        return False

def promote_admin(bot, gid, uid):
    if not uid: return False
    try:
        bot.addGroupAdmins(members=[str(uid)], groupId=str(gid))
        return True
    except Exception as e:
        print(f"[PROMOTE ERROR] {e}")
        return False

def demote_admin(bot, gid, uid):
    if not uid: return False
    try:
        bot.removeGroupAdmins(members=[str(uid)], groupId=str(gid))
        return True
    except Exception as e:
        print(f"[DEMOTE ERROR] {e}")
        return False

def rename_group(bot, gid, new_name):
    try:
        bot.changeGroupName(groupName=new_name, groupId=str(gid))
        return True
    except Exception as e:
        print(f"[RENAME ERROR] {e}")
        return False

# ================== HẰNG SỐ ==================
LINE = "─" * 30
DOT = "▸"; DIAMOND = "◆"; STAR = "★"; ARROW = "→"
GREEN = "🟢"; RED = "🔴"; OK = "✅"; FAIL = "❌"; WARN = "⚠️"; INFO = "ℹ️"; LOCK = "🔒"; ROBOT = "🤖"

COMMANDS = {
    "help":"Menu thành viên","menu":"Menu thành viên","menuad":"Menu nhóm","menuvip":"Menu Owner/VIP",
    "info":"Info bot","ping":"Độ trễ","uptime":"Uptime","test":"Test",
    "capquyen":"[Owner] Cấp quyền","thuquyen":"[Owner] Thu quyền","dsquyen":"DS quyền",
    "sleep":"[Owner] Bot ngủ","boton":"[Owner] Đánh thức","botoff":"[Owner] Tắt bot",
    "setlenh":"[Owner] Đổi prefix","rs":"[Owner] Restart bot",
    "war":"[Owner] Spam war (file)","chui":"[Owner] Chửi user (file)","spam":"[Owner] Spam text/sticker",
    "stop":"[Owner] Dừng war/chửi/spam","anh":"[User] Gửi ảnh local","voice":"[User] Gửi voice từ file",
    "copy":"[Owner] Copy user","uncopy":"[Owner] Ngừng copy","dscopy":"DS copy",
    "mute":"[Admin] Khóa chat","muteid":"[Admin] Khóa chat (UID)","unmute":"[Admin] Mở khóa","dsmute":"DS mute","checkmute":"Debug UID",
    "mutetime":"[Admin] Đặt độ trễ thu hồi tin mute",
    "debuggroup":"[Owner] Debug nhóm","debugmem":"[Owner] In key nhóm",
    "groupinfo":"Xem info nhóm","setname":"[Admin] Đổi tên nhóm",
    "kick":"[Admin] Kick TV","adduser":"[Admin] Thêm TV","promote":"[Admin] Bổ nhiệm","demote":"[Admin] Giáng chức",
    "antilink":"[Admin] Chặn link","antiimage":"[Admin] Chặn ảnh","antivideo":"[Admin] Chặn video","antifile":"[Admin] Chặn file",
    "lock":"[Admin] Khóa nhóm","unlock":"[Admin] Mở khóa nhóm","settings":"Xem cài đặt",
    "dice":"Tung xúc xắc","coin":"Lật đồng xu","rps":"Oẳn tù tì","doanso":"Đoán số 1-100",
    "8ball":"Bói toán","rate":"Đánh giá 1-10","rand":"Random số","chon":"Chọn ngẫu nhiên",
    "daovang":"Đảo vàng","tuvan":"Tư vấn",
    "taosticker":"Tạo sticker từ ảnh","stickerlist":"DS sticker","dssticker":"DS sticker",
    "xoasticker":"[Owner] Xóa sticker","guisticker":"Gửi lại sticker",
    "like":"[User] Buff like Free Fire",
}

# ================== MENU THÀNH VIÊN ==================

def handle_help(bot, tid, ttype):
    t = (
        f"╔══════════════════════════╗\n"
        f"║    🤖  MENU THÀNH VIÊN   ║\n"
        f"╚══════════════════════════╝\n"
        f"Prefix hiện tại: `{PREFIX}`\n\n"
        f"┏━━━ ⚙️ HỆ THỐNG ━━━┓\n"
        f"  {DOT} {PREFIX}{'info':<12} {ARROW}  Thông tin bot\n"
        f"  {DOT} {PREFIX}{'ping':<12} {ARROW}  Độ trễ\n"
        f"  {DOT} {PREFIX}{'uptime':<12} {ARROW}  Thời gian chạy\n"
        f"  {DOT} {PREFIX}{'test':<12} {ARROW}  Kiểm tra bot\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"┏━━━ 🎮 MINI GAME ━━━┓\n"
        f"  {DOT} {PREFIX}{'dice':<12} {ARROW}  Tung xúc xắc\n"
        f"  {DOT} {PREFIX}{'coin':<12} {ARROW}  Lật đồng xu\n"
        f"  {DOT} {PREFIX}{'rps':<12} {ARROW}  Oẳn tù tì\n"
        f"  {DOT} {PREFIX}{'doanso':<12} {ARROW}  Đoán số 1-100\n"
        f"  {DOT} {PREFIX}{'8ball':<12} {ARROW}  Bói toán yes/no\n"
        f"  {DOT} {PREFIX}{'rate':<12} {ARROW}  Đánh giá 1-10\n"
        f"  {DOT} {PREFIX}{'rand':<12} {ARROW}  Random số\n"
        f"  {DOT} {PREFIX}{'chon':<12} {ARROW}  Chọn ngẫu nhiên\n"
        f"  {DOT} {PREFIX}{'tuvan':<12} {ARROW}  Tư vấn\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"┏━━━ 🎨 MEDIA & TIỆN ÍCH ━━━┓\n"
        f"  {DOT} {PREFIX}{'anh':<12} {ARROW}  Gửi ảnh local\n"
        f"  {DOT} {PREFIX}{'voice':<12} {ARROW}  Gửi voice\n"
        f"  {DOT} {PREFIX}{'taosticker':<12} {ARROW}  Tạo sticker\n"
        f"  {DOT} {PREFIX}{'stickerlist':<12} {ARROW}  DS sticker\n"
        f"  {DOT} {PREFIX}{'guisticker':<12} {ARROW}  Gửi lại sticker\n"
        f"  {DOT} {PREFIX}{'like':<12} {ARROW}  Buff like Free Fire\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"{INFO} Menu khác:\n"
        f"  {PREFIX}menuad  {ARROW}  Menu nhóm\n"
        f"  {PREFIX}menuvip {ARROW}  Menu Owner"
    )
    send_reply(bot, tid, ttype, t)

# ================== MENU NHÓM ==================

def handle_menuad(bot, tid, ttype):
    t = (
        f"╔══════════════════════════╗\n"
        f"║      🛡️  MENU NHÓM       ║\n"
        f"╚══════════════════════════╝\n"
        f"Prefix hiện tại: `{PREFIX}`\n\n"
        f"┏━━━ 👥 QUẢN LÝ NHÓM ━━━┓\n"
        f"  {DOT} {PREFIX}{'groupinfo':<12} {ARROW}  Xem info nhóm\n"
        f"  {DOT} {PREFIX}{'setname':<12} {ARROW}  Đổi tên nhóm\n"
        f"  {DOT} {PREFIX}{'kick':<12} {ARROW}  Kick TV (@tag)\n"
        f"  {DOT} {PREFIX}{'adduser':<12} {ARROW}  Thêm TV (UID)\n"
        f"  {DOT} {PREFIX}{'promote':<12} {ARROW}  Bổ nhiệm phó nhóm\n"
        f"  {DOT} {PREFIX}{'demote':<12} {ARROW}  Giáng phó nhóm\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"┏━━━ 🔇 MUTE ━━━┓\n"
        f"  {DOT} {PREFIX}{'mute':<12} {ARROW}  Khóa chat (@tag)\n"
        f"  {DOT} {PREFIX}{'muteid':<12} {ARROW}  Khóa chat (UID)\n"
        f"  {DOT} {PREFIX}{'unmute':<12} {ARROW}  Mở khóa\n"
        f"  {DOT} {PREFIX}{'dsmute':<12} {ARROW}  DS mute\n"
        f"  {DOT} {PREFIX}{'mutetime':<12} {ARROW}  Độ trễ thu hồi\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"┏━━━ 🚫 CHỐNG SPAM ━━━┓\n"
        f"  {DOT} {PREFIX}{'antilink':<12} {ARROW}  Chặn link\n"
        f"  {DOT} {PREFIX}{'antiimage':<12} {ARROW}  Chặn ảnh\n"
        f"  {DOT} {PREFIX}{'antivideo':<12} {ARROW}  Chặn video\n"
        f"  {DOT} {PREFIX}{'antifile':<12} {ARROW}  Chặn file\n"
        f"  {DOT} {PREFIX}{'lock':<12} {ARROW}  Khóa nhóm\n"
        f"  {DOT} {PREFIX}{'unlock':<12} {ARROW}  Mở khóa nhóm\n"
        f"  {DOT} {PREFIX}{'settings':<12} {ARROW}  Xem cài đặt\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"{INFO} Menu khác:\n"
        f"  {PREFIX}menu    {ARROW}  Menu thành viên\n"
        f"  {PREFIX}menuvip {ARROW}  Menu Owner"
    )
    send_reply(bot, tid, ttype, t)

# ================== MENU OWNER / VIP ==================

def handle_menuvip(bot, tid, ttype):
    t = (
        f"╔══════════════════════════╗\n"
        f"║     👑  MENU OWNER/VIP   ║\n"
        f"╚══════════════════════════╝\n"
        f"Prefix hiện tại: `{PREFIX}`\n\n"
        f"┏━━━ 👑 QUYỀN ━━━┓\n"
        f"  {DIAMOND} {PREFIX}{'capquyen':<12} {ARROW}  Cấp quyền\n"
        f"  {DIAMOND} {PREFIX}{'thuquyen':<12} {ARROW}  Thu quyền\n"
        f"  {DIAMOND} {PREFIX}{'dsquyen':<12} {ARROW}  DS quyền\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"┏━━━ ⚙️ HỆ THỐNG ━━━┓\n"
        f"  {DIAMOND} {PREFIX}{'sleep':<12} {ARROW}  Bot ngủ\n"
        f"  {DIAMOND} {PREFIX}{'boton':<12} {ARROW}  Đánh thức\n"
        f"  {DIAMOND} {PREFIX}{'botoff':<12} {ARROW}  Tắt bot\n"
        f"  {DIAMOND} {PREFIX}{'setlenh':<12} {ARROW}  Đổi prefix\n"
        f"  {DIAMOND} {PREFIX}{'rs':<12} {ARROW}  Restart bot\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"┏━━━ ⚔️ WAR / SPAM ━━━┓\n"
        f"  {DIAMOND} {PREFIX}{'war':<12} {ARROW}  Spam war (file)\n"
        f"  {DIAMOND} {PREFIX}{'chui':<12} {ARROW}  Chửi user (@tag)\n"
        f"  {DIAMOND} {PREFIX}{'spam':<12} {ARROW}  Spam text/sticker\n"
        f"  {DIAMOND} {PREFIX}{'stop':<12} {ARROW}  Dừng war/chửi/spam\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"┏━━━ 📋 COPY & DEBUG ━━━┓\n"
        f"  {DIAMOND} {PREFIX}{'copy':<12} {ARROW}  Copy user\n"
        f"  {DIAMOND} {PREFIX}{'uncopy':<12} {ARROW}  Ngừng copy\n"
        f"  {DIAMOND} {PREFIX}{'dscopy':<12} {ARROW}  DS copy\n"
        f"  {DIAMOND} {PREFIX}{'debuggroup':<12} {ARROW}  Debug nhóm\n"
        f"  {DIAMOND} {PREFIX}{'debugmem':<12} {ARROW}  In key nhóm\n"
        f"  {DIAMOND} {PREFIX}{'xoasticker':<12} {ARROW}  Xóa sticker\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n\n"
        f"{INFO} Menu khác:\n"
        f"  {PREFIX}menu   {ARROW}  Menu thành viên\n"
        f"  {PREFIX}menuad {ARROW}  Menu nhóm"
    )
    send_reply(bot, tid, ttype, t)

# ================== HỆ THỐNG ==================

def handle_info(bot, tid, ttype):
    status = "💤 Ngủ" if BOT_SLEEPING else f"{GREEN} Hoạt động"
    t = f"ℹ️ THÔNG TIN BOT\n{LINE}\n{ROBOT} Tên: {BOT_NAME}\n🆔 UID: {BOT_OWNER_ID}\n👑 Owner: {BOT_OWNER_ID}\n🔤 Prefix: `{PREFIX}`\n⚡ Trạng thái: {status}\n{LINE}\n"
    t += f"🐍 Python: {platform.python_version()}\n💻 OS: {platform.system()} {platform.release()}\n{LINE}\n"
    t += f"⏱️ Uptime: {format_uptime(time.time() - START_TIME)}\n👥 Users: {len(ALLOWED_USERS)}\n🔇 Muted: {len(MUTED_USERS)}\n📋 Copy: {len(COPY_TARGETS)}\n🏘️ Nhóm: {len(GROUP_SETTINGS)}\n🎨 Sticker: {len(CUSTOM_STICKERS)}\n📅 {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}"
    send_reply(bot, tid, ttype, t)

def handle_ping(bot, tid, ttype):
    s = "💤" if BOT_SLEEPING else f"{GREEN}"
    send_reply(bot, tid, ttype, f"{ROBOT} 🏓 PONG!\n{LINE}\n▸ Trạng thái: {s}")

def handle_uptime(bot, tid, ttype):
    send_reply(bot, tid, ttype, f"{INFO} UPTIME\n{LINE}\n▸ Đã chạy: {format_uptime(time.time() - START_TIME)}")

def handle_test(bot, tid, ttype):
    send_reply(bot, tid, ttype, f"{OK} BOT HOẠT ĐỘNG\n{LINE}\n▸ UID: {BOT_OWNER_ID}")

def handle_sleep(bot, tid, ttype, uid):
    global BOT_SLEEPING
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    if BOT_SLEEPING: send_reply(bot, tid, ttype, f"{WARN} Bot đang ngủ rồi!"); return
    BOT_SLEEPING = True
    send_reply(bot, tid, ttype, f"💤 BOT ĐÃ NGỦ\n▸ Dùng {PREFIX}boton để đánh thức")

def handle_boton(bot, tid, ttype, uid):
    global BOT_SLEEPING
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    if not BOT_SLEEPING: send_reply(bot, tid, ttype, f"{WARN} Bot đang thức rồi!"); return
    BOT_SLEEPING = False
    send_reply(bot, tid, ttype, f"☀️ BOT ĐÃ THỨC\n▸ Gõ {PREFIX}menu để xem menu")

def handle_botoff(bot, tid, ttype, uid):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    send_reply(bot, tid, ttype, f"🛑 BOT ĐANG TẮT...\n👋 Tạm biệt!")
    time.sleep(2); os._exit(0)

# ================== SET PREFIX / RESTART ==================

def handle_setlenh(bot, tid, ttype, uid, ctext):
    global PREFIX
    if not is_owner(uid):
        send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner mới được đổi prefix!"); return

    parts = ctext.split(maxsplit=1)
    if len(parts) < 2:
        send_reply(bot, tid, ttype,
                   f"⚙️ ĐỔI PREFIX\n{LINE}\n"
                   f"▸ Prefix hiện tại: `{PREFIX}`\n"
                   f"▸ Cú pháp: {PREFIX}setlenh <prefix_mới>\n"
                   f"▸ Ví dụ: {PREFIX}setlenh .\n"
                   f"▸ Ràng buộc: 1-3 ký tự, KHÔNG chữ/số, không khoảng trắng")
        return

    new_prefix = parts[1].strip().strip('"').strip("'")

    if not new_prefix:
        send_reply(bot, tid, ttype, f"{FAIL} Prefix không được rỗng!"); return
    if len(new_prefix) > 3:
        send_reply(bot, tid, ttype, f"{FAIL} Prefix tối đa 3 ký tự!"); return
    if " " in new_prefix or "\t" in new_prefix or "\n" in new_prefix:
        send_reply(bot, tid, ttype, f"{FAIL} Prefix không được chứa khoảng trắng!"); return
    if new_prefix.isalnum():
        send_reply(bot, tid, ttype, f"{FAIL} Prefix phải là ký tự đặc biệt!"); return
    if new_prefix == PREFIX:
        send_reply(bot, tid, ttype, f"{WARN} Prefix `{new_prefix}` đang được dùng!"); return

    old_prefix = PREFIX
    PREFIX = new_prefix
    _save_prefix(new_prefix)

    send_reply(bot, tid, ttype,
               f"{OK} ĐÃ ĐỔI PREFIX\n{LINE}\n"
               f"▸ Cũ : `{old_prefix}`\n"
               f"▸ Mới: `{new_prefix}`\n"
               f"▸ Đã lưu vào `{PREFIX_FILE}`\n"
               f"▸ Thử ngay: {new_prefix}menu")


def _do_restart():
    time.sleep(2.5)
    try:
        sys.stdout.flush(); sys.stderr.flush()
    except Exception: pass

    argv = list(sys.argv) if sys.argv else [os.path.abspath(__file__)]
    if not argv or not argv[0].endswith(".py"):
        argv = [os.path.abspath(__file__)] + argv[1:]

    py = sys.executable or shutil.which("python3") or shutil.which("python") or "python3"

    try:
        print(f"[RS] Đang restart: {py} {' '.join(argv)}")
        os.execv(py, [py] + argv)
    except Exception as e:
        print(f"[RS] execv lỗi: {e}")
        try:
            subprocess.Popen([py] + argv, close_fds=True)
            print("[RS] Spawn process mới OK")
        except Exception as e2:
            print(f"[RS] Popen lỗi: {e2}")
        os._exit(0)


def handle_restart(bot, tid, ttype, uid):
    if not is_owner(uid):
        send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return

    for k in list(WAR_RUNNING.keys()):  WAR_RUNNING[k]  = False
    for k in list(CHUI_RUNNING.keys()): CHUI_RUNNING[k] = False
    for k in list(SPAM_RUNNING.keys()): SPAM_RUNNING[k] = False

    send_reply(bot, tid, ttype,
               f"🔄 ĐANG RESTART BOT...\n{LINE}\n"
               f"▸ Prefix giữ nguyên: `{PREFIX}`\n"
               f"▸ Vui lòng đợi 5-10 giây")

    threading.Thread(target=_do_restart, daemon=True, name="RestartBot").start()

# ================== QUYỀN / MUTE ==================

def handle_capquyen(bot, tid, ttype, data, uid, ctext):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}capquyen @user"); return
    if str(target) == str(BOT_OWNER_ID): send_reply(bot, tid, ttype, f"{WARN} Không cần cấp!"); return
    if str(target) in ALLOWED_USERS: send_reply(bot, tid, ttype, f"{WARN} Đã có quyền!"); return
    ALLOWED_USERS[str(target)] = {"granted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "granted_by": str(uid)}
    save_json(PERM_FILE, ALLOWED_USERS)
    send_reply(bot, tid, ttype, f"{OK} ĐÃ CẤP QUYỀN\n▸ User: {target}\n▸ Tổng: {len(ALLOWED_USERS)}")

def handle_thuquyen(bot, tid, ttype, data, uid, ctext):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}thuquyen @user"); return
    if str(target) not in ALLOWED_USERS: send_reply(bot, tid, ttype, f"{WARN} Chưa có quyền!"); return
    del ALLOWED_USERS[str(target)]; save_json(PERM_FILE, ALLOWED_USERS)
    send_reply(bot, tid, ttype, f"🗑️ ĐÃ THU QUYỀN\n▸ User: {target}")

def handle_dsquyen(bot, tid, ttype, uid):
    if not is_user_allowed(uid): send_reply(bot, tid, ttype, f"{LOCK} Không có quyền!"); return
    t = f"👥 DS QUYỀN\n{LINE}\n👑 Owner: {BOT_OWNER_ID}"
    if not ALLOWED_USERS: t += f"\n\n{INFO} Chưa có ai."
    else:
        for i, u in enumerate(ALLOWED_USERS.keys(), 1): t += f"\n{DOT} {i}. {u}"
    send_reply(bot, tid, ttype, t)

def handle_mute(bot, tid, ttype, data, uid, ctext):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}mute @user"); return
    if str(target) in MUTED_USERS: send_reply(bot, tid, ttype, f"{WARN} Đã bị mute!"); return
    MUTED_USERS[str(target)] = {"muted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "muted_by": str(uid), "group_id": str(tid)}
    save_json(MUTE_FILE, MUTED_USERS)
    send_reply(bot, tid, ttype, f"🔇 ĐÃ MUTE\n▸ User: {target}")

def handle_muteid(bot, tid, ttype, data, uid, ctext):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    parts = ctext.split()
    if len(parts) < 2: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}muteid <UID>"); return
    tgt = parts[1].strip()
    if not tgt.isdigit(): send_reply(bot, tid, ttype, f"{FAIL} UID không hợp lệ!"); return
    if str(tgt) in MUTED_USERS: send_reply(bot, tid, ttype, f"{WARN} Đã bị mute!"); return
    MUTED_USERS[str(tgt)] = {"muted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "muted_by": str(uid), "group_id": str(tid)}
    save_json(MUTE_FILE, MUTED_USERS)
    send_reply(bot, tid, ttype, f"🔇 ĐÃ MUTE UID {tgt}")

def handle_unmute(bot, tid, ttype, data, uid, ctext):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}unmute @user"); return
    if str(target) not in MUTED_USERS: send_reply(bot, tid, ttype, f"{WARN} Chưa bị mute!"); return
    del MUTED_USERS[str(target)]; save_json(MUTE_FILE, MUTED_USERS)
    send_reply(bot, tid, ttype, f"🔊 ĐÃ UNMUTE\n▸ User: {target}")

def handle_dsmute(bot, tid, ttype, uid):
    if not is_user_allowed(uid): send_reply(bot, tid, ttype, f"{LOCK} Không có quyền!"); return
    t = f"🔇 DS MUTE\n{LINE}"
    if not MUTED_USERS: t += f"\n\n{INFO} Chưa có ai."
    else:
        for i, u in enumerate(MUTED_USERS.keys(), 1): t += f"\n{DOT} {i}. {u}"
    send_reply(bot, tid, ttype, t)

def handle_checkmute(bot, tid, ttype, data, uid, ctext):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    mentions = extract_mentions(data.get("raw"))
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    t = f"🔍 CHECK MUTE\n{LINE}\n▸ UID mention : {mentions}\n▸ UID extract : {target}\n▸ Trong DS    : {'✅' if target and str(target) in MUTED_USERS else '❌'}\n\n📋 DS ({len(MUTED_USERS)}):\n"
    for i, u in enumerate(MUTED_USERS.keys(), 1): t += f"  {i}. {u}\n"
    send_reply(bot, tid, ttype, t)

def handle_mutetime(bot, tid, ttype, uid, ctext):
    global MUTE_DELETE_DELAY
    if not is_group_admin(bot, tid, uid):
        send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    parts = ctext.split()
    if len(parts) < 2:
        send_reply(bot, tid, ttype,
                   f"⏱️ ĐỘ TRỄ THU HỒI MUTE\n{LINE}\n▸ Hiện tại: {MUTE_DELETE_DELAY}s\n▸ Đổi: {PREFIX}mutetime <giây>")
        return
    try:
        v = float(parts[1].replace(",", "."))
    except ValueError:
        send_reply(bot, tid, ttype, f"{FAIL} Phải là số!"); return
    if v < 0: v = 0
    if v > 60: v = 60
    MUTE_DELETE_DELAY = v
    send_reply(bot, tid, ttype, f"{OK} ĐÃ ĐẶT ĐỘ TRỄ MUTE\n▸ {MUTE_DELETE_DELAY}s")

# ================== DEBUG ==================

def handle_debuggroup(bot, tid, ttype, uid):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    info = None; method_used = None
    for mn in ("fetchGroupInfo", "getGroupInfo", "getGroupInfoById", "get_group_info"):
        if hasattr(bot, mn):
            try:
                info = getattr(bot, mn)(tid); method_used = mn; break
            except Exception as e: print(f"[DEBUG] {mn} lỗi: {e}"); continue
    if info is None: send_reply(bot, tid, ttype, f"{FAIL} Không lấy được info!"); return
    t = f"🔍 DEBUG GROUP\n{LINE}\n▸ Method: `{method_used}`\n▸ Type: `{type(info).__name__}`\n"
    grid = info.get("gridInfoMap") if isinstance(info, dict) else getattr(info, "gridInfoMap", None)
    if grid is None: t += f"{FAIL} Không có gridInfoMap!"; send_reply(bot, tid, ttype, t); return
    if isinstance(grid, dict):
        t += f"▸ Số key: {len(grid)}\n"
        for key, val in list(grid.items())[:1]:
            if isinstance(val, dict):
                t += f"\n▸ Keys ({len(val)}):\n"
                for k in list(val.keys())[:30]: t += f"  • `{k}`\n"
    send_reply(bot, tid, ttype, t)

def handle_debugmem(bot, tid, ttype, uid):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    info = None
    for mn in ("fetchGroupInfo", "getGroupInfo", "get_group_info"):
        if hasattr(bot, mn):
            try:
                info = getattr(bot, mn)(tid); break
            except Exception: continue
    if info is None: send_reply(bot, tid, ttype, f"{FAIL} Không lấy được info!"); return
    grid = info.get("gridInfoMap") if isinstance(info, dict) else getattr(info, "gridInfoMap", None)
    if not grid or not isinstance(grid, dict):
        send_reply(bot, tid, ttype, f"{FAIL} gridInfoMap không phải dict!"); return
    group_data = list(grid.values())[0]
    if isinstance(group_data, dict): keys = list(group_data.keys())
    else: keys = [a for a in dir(group_data) if not a.startswith("_")]
    t = f"📋 KEYS NHÓM ({len(keys)})\n{LINE}\n"
    for k in keys[:40]: t += f"▸ `{k}`\n"
    send_reply(bot, tid, ttype, t)

# ================== WORKERS ==================

def war_worker(bot, tid, ttype, lines, delay):
    try:
        bot_send_nowait(bot, tid, ttype,
                        f"⚔️ BẮT ĐẦU WAR\n▸ Số câu: {len(lines)}\n▸ Delay: {delay}s")
        i = 0
        n = len(lines)
        if n == 0:
            WAR_RUNNING[tid] = False
            return
        eff_delay = max(delay, 0.005)
        while WAR_RUNNING.get(tid):
            try:
                bot_send_nowait(bot, tid, ttype, lines[i % n])
            except Exception as e:
                print(f"[WAR] send err: {e}")
            i += 1
            time.sleep(eff_delay)
        time.sleep(0.4)
        bot_send_nowait(bot, tid, ttype, f"🛑 DỪNG WAR\n▸ Đã gửi: {i} tin")
    except Exception as e:
        print(f"[WAR] Lỗi: {e}")
        WAR_RUNNING[tid] = False

def handle_war(bot, tid, ttype, uid, args):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    if WAR_RUNNING.get(tid): send_reply(bot, tid, ttype, f"{WARN} War đang chạy!\nGõ {PREFIX}stop"); return
    delay = WAR_DELAY_DEFAULT
    if args:
        try:
            delay = float(str(args[0]).replace(",", "."))
            if delay < WAR_DELAY_MIN or delay > WAR_DELAY_MAX: send_reply(bot, tid, ttype, f"{WARN} Delay từ {WAR_DELAY_MIN}-{WAR_DELAY_MAX}s!"); return
        except ValueError: send_reply(bot, tid, ttype, f"{FAIL} Delay không hợp lệ!"); return
    if not os.path.exists(WAR_FILE): send_reply(bot, tid, ttype, f"{FAIL} Không có {WAR_FILE}!"); return
    try:
        with open(WAR_FILE, "r", encoding="utf-8") as f: lines = [l.strip() for l in f if l.strip()]
        if not lines: send_reply(bot, tid, ttype, f"{FAIL} File rỗng!"); return
    except Exception as e: send_reply(bot, tid, ttype, f"{FAIL} Lỗi đọc file: {e}"); return
    WAR_PENDING[tid] = {"delay": delay, "user_id": str(uid), "time": time.time(), "lines": lines}
    t = f"⚠️ XÁC NHẬN WAR\n{LINE}\n▸ Số câu: {len(lines)}\n▸ Delay: {delay}s\n\n{ARROW} yes/ok/có → Bắt đầu\n{ARROW} no/hủy → Hủy\n⏱️ Tự hủy sau {WAR_CONFIRM_TIMEOUT}s"
    send_reply(bot, tid, ttype, t)

def chui_worker(bot, tid, ttype, target_uid, target_name, lines, delay):
    try:
        bot_send_nowait(bot, tid, ttype,
                        f"🔥 BẮT ĐẦU CHỬI\n▸ Target: {target_name} ({target_uid})\n▸ Số câu: {len(lines)}\n▸ Delay: {delay}s")
        i = 0
        n = len(lines)
        if n == 0:
            CHUI_RUNNING[tid] = False
            return
        eff_delay = max(delay, 0.005)
        while CHUI_RUNNING.get(tid):
            try:
                bot_send_mention_nowait(bot, tid, ttype, lines[i % n], target_uid)
            except Exception as e:
                print(f"[CHUI] send err: {e}")
            i += 1
            time.sleep(eff_delay)
        time.sleep(0.4)
        bot_send_nowait(bot, tid, ttype, f"🛑 DỪNG CHỬI\n▸ Đã gửi: {i} tin")
    except Exception as e:
        print(f"[CHUI] Lỗi: {e}")
        CHUI_RUNNING[tid] = False

def handle_chui(bot, tid, ttype, uid, args, ctext, data):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    if CHUI_RUNNING.get(tid): send_reply(bot, tid, ttype, f"{WARN} Đang chửi rồi!\nGõ {PREFIX}stop"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target:
        m = re.search(r'@?(\d{8,})', ctext)
        if m: target = m.group(1)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}chui @user [delay]"); return
    if str(target) == str(BOT_OWNER_ID): send_reply(bot, tid, ttype, f"{WARN} Không thể tự chửi bot!"); return
    target_name = target
    try:
        info = None
        for mn in ("getUserInfo", "fetchUserInfo", "get_user_info"):
            if hasattr(bot, mn):
                try: info = getattr(bot, mn)(target); break
                except Exception: continue
        if info:
            if isinstance(info, dict): target_name = info.get("name") or info.get("displayName") or info.get("zaloName") or target
            else: target_name = getattr(info, "name", None) or getattr(info, "displayName", None) or target
    except Exception: pass
    delay = CHUI_DELAY_DEFAULT
    for p in ctext.split():
        try:
            val = float(p.replace(",", "."))
            if CHUI_DELAY_MIN <= val <= CHUI_DELAY_MAX: delay = val; break
        except ValueError: continue
    if not os.path.exists(CHUI_FILE): send_reply(bot, tid, ttype, f"{FAIL} Không có file {CHUI_FILE}!"); return
    try:
        with open(CHUI_FILE, "r", encoding="utf-8") as f: lines = [l.strip() for l in f if l.strip()]
        if not lines: send_reply(bot, tid, ttype, f"{FAIL} File rỗng!"); return
    except Exception as e: send_reply(bot, tid, ttype, f"{FAIL} Lỗi đọc file: {e}"); return
    CHUI_PENDING[tid] = {"delay": delay, "user_id": str(uid), "time": time.time(), "lines": lines, "target_uid": target, "target_name": target_name}
    t = f"⚠️ XÁC NHẬN CHỬI\n{LINE}\n▸ Target: {target_name} ({target})\n▸ Số câu: {len(lines)}\n▸ Delay: {delay}s\n\n{ARROW} yes/ok/có → Bắt đầu\n{ARROW} no/hủy → Hủy\n⏱️ Tự hủy sau {WAR_CONFIRM_TIMEOUT}s"
    send_reply(bot, tid, ttype, t)

def spam_worker(bot, tid, ttype, content, target_uid, delay, sticker_data=None):
    try:
        if sticker_data:
            head = f"🎨 BẮT ĐẦU SPAM STICKER\n▸ Caption: {content[:100] or '(trống)'}\n▸ Delay: {delay}s"
        else:
            target_str = f" (tag {target_uid})" if target_uid else " (không tag)"
            head = f"📢 BẮT ĐẦU SPAM\n▸ Nội dung: {content[:100]}\n▸ Delay: {delay}s{target_str}"
        bot_send_nowait(bot, tid, ttype, head)

        i = 0
        eff_delay = max(delay, 0.005)
        while SPAM_RUNNING.get(tid):
            try:
                if sticker_data:
                    _send_sticker_with_caption(bot, tid, ttype, sticker_data, content, image_path=sticker_data.get("static_path"))
                elif target_uid:
                    bot_send_mention_nowait(bot, tid, ttype, content, target_uid)
                else:
                    bot_send_nowait(bot, tid, ttype, content)
            except Exception as e:
                print(f"[SPAM] send err: {e}")
            i += 1
            time.sleep(eff_delay)
        time.sleep(0.4)
        bot_send_nowait(bot, tid, ttype, f"🛑 DỪNG SPAM\n▸ Đã gửi: {i} tin")
    except Exception as e:
        print(f"[SPAM] Lỗi: {e}")
        SPAM_RUNNING[tid] = False


def handle_spam(bot, tid, ttype, uid, args, ctext, data):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    if SPAM_RUNNING.get(tid): send_reply(bot, tid, ttype, f"{WARN} Đang spam rồi!\nGõ {PREFIX}stop"); return

    sticker_data = None
    if data:
        sticker_data = _prepare_sticker_from_reply(bot, data)

    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    target_name = None
    if target:
        try:
            info = None
            for mn in ("getUserInfo", "fetchUserInfo", "get_user_info"):
                if hasattr(bot, mn):
                    try: info = getattr(bot, mn)(target); break
                    except Exception: continue
            if info:
                if isinstance(info, dict): target_name = info.get("name") or info.get("displayName") or info.get("zaloName")
                else: target_name = getattr(info, "name", None) or getattr(info, "displayName", None)
        except Exception: pass

    content = ctext
    if content.lower().startswith("spam"): content = content[4:].strip()
    if target: content = content.replace(f"@{target}", "").strip()
    if target_name:
        name_words = [re.escape(w) for w in target_name.split() if w]
        if name_words:
            name_pat = r'\s+'.join(name_words)
            content = re.sub(rf'@{name_pat}\b\s*', '', content, count=1, flags=re.IGNORECASE)
            content = re.sub(rf'^{name_pat}\b\s*', '', content, count=1, flags=re.IGNORECASE)
    if content.startswith("@"):
        content = re.sub(r'^@\S+\s*', '', content, count=1).strip()

    delay = SPAM_DELAY_DEFAULT
    parts = content.split(maxsplit=1)
    if parts:
        try:
            val = float(parts[0].replace(",", "."))
            if SPAM_DELAY_MIN <= val <= SPAM_DELAY_MAX:
                delay = val
                content = parts[1] if len(parts) > 1 else ""
        except ValueError: pass
    content = content.strip()

    if not content and not sticker_data:
        send_reply(bot, tid, ttype,
            f"{FAIL} Thiếu nội dung!\n{LINE}\n"
            f"▸ Text: {PREFIX}spam @user [delay] <nội dung>\n"
            f"▸ Sticker: reply ảnh + {PREFIX}spam [delay] <caption>")
        return

    SPAM_PENDING[tid] = {
        "delay": delay, "user_id": str(uid), "time": time.time(),
        "content": content, "target_uid": target, "sticker_data": sticker_data,
    }

    if sticker_data:
        t = (f"⚠️ XÁC NHẬN SPAM STICKER\n{LINE}\n"
             f"▸ Caption: {content[:200] or '(trống)'}\n"
             f"▸ Delay: {delay}s\n\n"
             f"{ARROW} yes/ok/có → Bắt đầu\n{ARROW} no/hủy → Hủy")
    else:
        target_str = f"Tag @{target}" if target else "Không tag"
        t = (f"⚠️ XÁC NHẬN SPAM\n{LINE}\n"
             f"▸ Target: {target_str}\n"
             f"▸ Delay: {delay}s\n"
             f"▸ Nội dung: {content[:200]}\n\n"
             f"{ARROW} yes/ok/có → Bắt đầu\n{ARROW} no/hủy → Hủy")
    send_reply(bot, tid, ttype, t)

def handle_stop(bot, tid, ttype, uid):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    stopped = []
    if WAR_RUNNING.get(tid): WAR_RUNNING[tid] = False; stopped.append("WAR")
    if CHUI_RUNNING.get(tid): CHUI_RUNNING[tid] = False; stopped.append("CHỬI")
    if SPAM_RUNNING.get(tid): SPAM_RUNNING[tid] = False; stopped.append("SPAM")
    if stopped: send_reply(bot, tid, ttype, f"🛑 ĐÃ DỪNG: {', '.join(stopped)}")
    else: send_reply(bot, tid, ttype, f"{WARN} Không có gì đang chạy!")

def check_war_confirmation(bot, tid, ttype, uid, text):
    if tid in WAR_PENDING:
        p = WAR_PENDING[tid]
        if time.time() - p["time"] > WAR_CONFIRM_TIMEOUT: del WAR_PENDING[tid]
        elif str(uid) == p["user_id"]:
            txt = text.lower().strip()
            if txt in WAR_CONFIRM_WORDS:
                d = p["delay"]; l = p["lines"]; del WAR_PENDING[tid]; WAR_RUNNING[tid] = True
                threading.Thread(target=war_worker, args=(bot, tid, ttype, l, d), daemon=True).start(); return True
            if txt in WAR_CANCEL_WORDS: del WAR_PENDING[tid]; send_reply(bot, tid, ttype, f"❌ Đã hủy war."); return True
            if not text.startswith(PREFIX): return True
    if tid in CHUI_PENDING:
        p = CHUI_PENDING[tid]
        if time.time() - p["time"] > WAR_CONFIRM_TIMEOUT: del CHUI_PENDING[tid]
        elif str(uid) == p["user_id"]:
            txt = text.lower().strip()
            if txt in WAR_CONFIRM_WORDS:
                d = p["delay"]; l = p["lines"]; target = p["target_uid"]; target_name = p["target_name"]
                del CHUI_PENDING[tid]; CHUI_RUNNING[tid] = True
                threading.Thread(target=chui_worker, args=(bot, tid, ttype, target, target_name, l, d), daemon=True).start(); return True
            if txt in WAR_CANCEL_WORDS: del CHUI_PENDING[tid]; send_reply(bot, tid, ttype, f"❌ Đã hủy chửi."); return True
            if not text.startswith(PREFIX): return True
    if tid in SPAM_PENDING:
        p = SPAM_PENDING[tid]
        if time.time() - p["time"] > WAR_CONFIRM_TIMEOUT:
            del SPAM_PENDING[tid]
        elif str(uid) == p["user_id"]:
            txt = text.lower().strip()
            if txt in WAR_CONFIRM_WORDS:
                d = p["delay"]; content = p["content"]; target = p["target_uid"]; sticker_data = p.get("sticker_data")
                del SPAM_PENDING[tid]; SPAM_RUNNING[tid] = True
                threading.Thread(target=spam_worker, args=(bot, tid, ttype, content, target, d, sticker_data), daemon=True).start()
                return True
            if txt in WAR_CANCEL_WORDS:
                del SPAM_PENDING[tid]; send_reply(bot, tid, ttype, f"❌ Đã hủy spam."); return True
            if not text.startswith(PREFIX): return True
    return False

# ================== MEDIA ==================

def handle_anh(bot, tid, ttype, uid, args, ctext):
    if not is_user_allowed(uid): return
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if not args:
        files = []
        try:
            for f in os.listdir(base_dir):
                if f.lower().endswith(IMAGE_EXTS):
                    files.append((f, os.path.getsize(os.path.join(base_dir, f)) / 1024))
        except Exception: pass
        if not files: return
        t = f"🖼️ DANH SÁCH ẢNH ({len(files)})\n{LINE}"
        for i, (f, sz) in enumerate(files[:30], 1): t += f"\n{DOT} {i}. `{f}` ({sz:.1f} KB)"
        if len(files) > 30: t += f"\n... và {len(files)-30} file khác"
        t += f"\n\n{INFO} Dùng: `{PREFIX}anh <tên_file> [caption]`"
        send_reply(bot, tid, ttype, t)
        return

    ctext_after = ctext[len("anh"):].strip()
    all_files = []
    try:
        for f in os.listdir(base_dir):
            if f.lower().endswith(IMAGE_EXTS): all_files.append(f)
    except Exception: pass
    if not all_files: return

    filename = None; remaining = ""
    for f in sorted(all_files, key=len, reverse=True):
        if ctext_after.lower().startswith(f.lower()):
            filename = f; remaining = ctext_after[len(f):].strip(); break
    if not filename:
        first_word = ctext_after.split()[0] if ctext_after.split() else ""
        for f in all_files:
            if first_word.lower() in f.lower():
                filename = f; remaining = ctext_after[len(first_word):].strip(); break
    if not filename: return
    filepath = os.path.join(base_dir, filename)
    if not os.path.exists(filepath): return
    bot_send_image(bot, tid, ttype, filepath, remaining)


def handle_voice(bot, tid, ttype, uid, args, ctext):
    if not is_user_allowed(uid): return
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if not args:
        files = []
        try:
            for f in os.listdir(base_dir):
                if f.lower().endswith(VOICE_EXTS):
                    files.append((f, os.path.getsize(os.path.join(base_dir, f)) / (1024 * 1024)))
        except Exception: pass
        if not files: return
        t = f"🎵 DANH SÁCH NHẠC ({len(files)})\n{LINE}"
        for i, (f, sz) in enumerate(files[:30], 1): t += f"\n{DOT} {i}. `{f}` ({sz:.1f} MB)"
        if len(files) > 30: t += f"\n... và {len(files)-30} file khác"
        t += f"\n\n{INFO} Dùng: `{PREFIX}voice <tên file>`"
        send_reply(bot, tid, ttype, t)
        return

    filename = ctext[len("voice"):].strip()
    filepath = os.path.join(base_dir, filename)
    if not os.path.exists(filepath):
        try:
            for f in os.listdir(base_dir):
                if f.lower().endswith(VOICE_EXTS) and filename.lower() in f.lower():
                    filepath = os.path.join(base_dir, f); break
        except Exception: pass
    if not os.path.exists(filepath): return
    if not filepath.lower().endswith(VOICE_EXTS): return
    if os.path.getsize(filepath) < 5000: return
    url = upload_voice_smart(filepath)
    if not url: return
    bot_send_voice(bot, tid, ttype, url)

def handle_copy(bot, tid, ttype, data, uid, ctext):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}copy @user"); return
    if str(target) in COPY_TARGETS: send_reply(bot, tid, ttype, f"{WARN} Đang copy!"); return
    COPY_TARGETS[str(target)] = {"added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "added_by": str(uid), "msg_map": {}}
    save_json(COPY_FILE, COPY_TARGETS)
    send_reply(bot, tid, ttype, f"📋 ĐÃ BẬT COPY\n▸ User: {target}")

def handle_uncopy(bot, tid, ttype, data, uid, ctext):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}uncopy @user"); return
    if str(target) not in COPY_TARGETS: send_reply(bot, tid, ttype, f"{WARN} Chưa bật copy!"); return
    del COPY_TARGETS[str(target)]; save_json(COPY_FILE, COPY_TARGETS)
    send_reply(bot, tid, ttype, f"📋 ĐÃ TẮT COPY\n▸ User: {target}")

def handle_dscopy(bot, tid, ttype, uid):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    t = f"📋 DS COPY\n{LINE}"
    if not COPY_TARGETS: t += f"\n\n{INFO} Chưa copy ai."
    else:
        for i, u in enumerate(COPY_TARGETS.keys(), 1): t += f"\n{DOT} {i}. {u}"
    send_reply(bot, tid, ttype, t)

def do_copy_message(bot, src_uid, text, tid, ttype, src_mid):
    if not text: return
    try:
        result = bot_send(bot, tid, ttype, text)
        bot_mid = get_msg_id(result) if result else None
        if src_mid and bot_mid:
            COPY_TARGETS.setdefault(str(src_uid), {}).setdefault("msg_map", {})[str(src_mid)] = str(bot_mid)
            save_json(COPY_FILE, COPY_TARGETS)
    except Exception as e: print(f"[COPY] Lỗi: {e}")

def do_undo_copy(bot, src_mid, tid, ttype):
    for uid, info in COPY_TARGETS.items():
        mm = info.get("msg_map", {}) if isinstance(info, dict) else {}
        if str(src_mid) in mm:
            bot_mid = mm[str(src_mid)]
            try:
                fake = {"msgId": bot_mid}
                if Message is not None:
                    try: fake = Message(msgId=bot_mid)
                    except Exception: pass
                delete_message(bot, fake, tid, ttype, author_id=BOT_OWNER_ID)
                del mm[str(src_mid)]; save_json(COPY_FILE, COPY_TARGETS)
            except Exception: pass
            return True
    return False

# ================== NHÓM ==================

def handle_groupinfo(bot, tid, ttype):
    info = None; method_used = None
    for mn in ("fetchGroupInfo", "getGroupInfo", "get_group_info", "getGroupInfoById"):
        if hasattr(bot, mn):
            try:
                info = getattr(bot, mn)(tid); method_used = mn; break
            except Exception: continue

    t = f"👥 THÔNG TIN NHÓM\n{LINE}"
    if info is None:
        t += f"\n{WARN} Không lấy được info!"
        send_reply(bot, tid, ttype, t); return

    grid = None
    if isinstance(info, dict): grid = info.get("gridInfoMap")
    else: grid = getattr(info, "gridInfoMap", None)
    if grid is None:
        t += f"\n{WARN} Không có gridInfoMap!"
        send_reply(bot, tid, ttype, t); return

    group_data = None
    if isinstance(grid, dict) and grid: group_data = list(grid.values())[0]
    elif hasattr(grid, "items"):
        try: group_data = list(grid.items())[0][1]
        except Exception: pass
    else: group_data = grid
    if group_data is None:
        t += f"\n{WARN} Không lấy được GroupDetail!"
        send_reply(bot, tid, ttype, t); return

    def gf(obj, *keys):
        for k in keys:
            try:
                v = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
                if v is not None and v != "": return v
            except Exception: pass
        return None

    name = gf(group_data, "name", "groupName", "group_name") or "?"
    creator = gf(group_data, "creatorId", "creator_id", "creator", "ownerId") or "?"
    desc = gf(group_data, "desc", "description") or "(trống)"
    total = gf(group_data, "totalMember", "memberCount", "total_member", "totalMembers")
    admin_ids = gf(group_data, "adminIds", "admin_ids", "admins") or []
    member_ids = gf(group_data, "memberIds", "member_ids", "members") or []

    t += f"\n▸ Tên nhóm : {name}"
    t += f"\n▸ Nhóm ID  : {tid}"
    t += f"\n▸ Chủ nhóm : {creator}"
    t += f"\n▸ Mô tả    : {str(desc)[:80]}"
    if isinstance(total, int): t += f"\n▸ Tổng TV  : {total}"
    elif member_ids: t += f"\n▸ Tổng TV  : {len(member_ids)}"
    else: t += f"\n▸ Tổng TV  : ?"
    if admin_ids and isinstance(admin_ids, (list, tuple)): t += f"\n▸ Phó nhóm : {len(admin_ids)}"
    t += f"\n▸ Method   : `{method_used}`"

    gs = get_group_settings(tid)
    t += f"\n\n📋 CÀI ĐẶT:"
    t += f"\n▸ Anti-link  : {'✅ BẬT' if gs['antilink'] else '❌ TẮT'}"
    t += f"\n▸ Anti-ảnh   : {'✅ BẬT' if gs['antiimage'] else '❌ TẮT'}"
    t += f"\n▸ Anti-video : {'✅ BẬT' if gs['antivideo'] else '❌ TẮT'}"
    t += f"\n▸ Anti-file  : {'✅ BẬT' if gs['antifile'] else '❌ TẮT'}"
    t += f"\n▸ Lock nhóm  : {'✅ BẬT' if gs['lock'] else '❌ TẮT'}"
    send_reply(bot, tid, ttype, t)

def handle_setname(bot, tid, ttype, uid, ctext):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    parts = ctext.split(maxsplit=1)
    if len(parts) < 2: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}setname <tên mới>"); return
    new_name = parts[1].strip()
    if not new_name: send_reply(bot, tid, ttype, f"{FAIL} Tên rỗng!"); return
    ok = rename_group(bot, tid, new_name)
    send_reply(bot, tid, ttype, f"{OK} ĐÃ ĐỔI TÊN NHÓM\n▸ {new_name}" if ok else f"{FAIL} Không đổi được!")

def handle_kick(bot, tid, ttype, data, uid, ctext):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}kick @user"); return
    if str(target) == str(BOT_OWNER_ID): send_reply(bot, tid, ttype, f"{WARN} Không kick bot!"); return
    ok = kick_user(bot, tid, target)
    send_reply(bot, tid, ttype, f"{OK} ĐÃ KICK\n▸ User: {target}" if ok else f"{FAIL} Không kick được!")

def handle_adduser(bot, tid, ttype, data, uid, ctext):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    m = re.search(r'(\d{8,})', ctext)
    if not m: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}adduser <UID>"); return
    target = m.group(1)
    ok = add_user_to_group(bot, tid, target)
    send_reply(bot, tid, ttype, f"{OK} ĐÃ THÊM\n▸ User: {target}" if ok else f"{FAIL} Không thêm được!")

def handle_promote(bot, tid, ttype, data, uid, ctext):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}promote @user"); return
    ok = promote_admin(bot, tid, target)
    send_reply(bot, tid, ttype, f"{OK} ĐÃ BỔ NHIỆM\n▸ User: {target}" if ok else f"{FAIL} Không bổ nhiệm được!")

def handle_demote(bot, tid, ttype, data, uid, ctext):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    target = extract_target_uid(ctext, data.get("raw"), BOT_OWNER_ID)
    if not target: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}demote @user"); return
    ok = demote_admin(bot, tid, target)
    send_reply(bot, tid, ttype, f"{OK} ĐÃ GIÁNG\n▸ User: {target}" if ok else f"{FAIL} Không giáng được!")

def _toggle(bot, tid, ttype, uid, key, label):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    gs = get_group_settings(tid); gs[key] = not gs[key]; save_group_settings()
    send_reply(bot, tid, ttype, f"⚙️ {label}: {'✅ BẬT' if gs[key] else '❌ TẮT'}")

def handle_antilink(bot, tid, ttype, uid):   _toggle(bot, tid, ttype, uid, "antilink", "Chặn LINK")
def handle_antiimage(bot, tid, ttype, uid):  _toggle(bot, tid, ttype, uid, "antiimage", "Chặn ẢNH")
def handle_antivideo(bot, tid, ttype, uid):  _toggle(bot, tid, ttype, uid, "antivideo", "Chặn VIDEO")
def handle_antifile(bot, tid, ttype, uid):   _toggle(bot, tid, ttype, uid, "antifile", "Chặn FILE")

def handle_lock(bot, tid, ttype, uid):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    gs = get_group_settings(tid); gs["lock"] = not gs["lock"]; save_group_settings()
    if gs["lock"]: send_reply(bot, tid, ttype, f"{LOCK} ĐÃ KHÓA NHÓM\n▸ Chỉ admin gửi được tin")
    else: send_reply(bot, tid, ttype, f"🔓 ĐÃ MỞ KHÓA NHÓM")

def handle_unlock(bot, tid, ttype, uid):
    if not is_group_admin(bot, tid, uid): send_reply(bot, tid, ttype, f"{FAIL} Cần quyền bot hoặc CHỦ/PHÓ NHÓM!"); return
    gs = get_group_settings(tid)
    if not gs["lock"]: send_reply(bot, tid, ttype, f"{WARN} Nhóm đang không khóa!"); return
    gs["lock"] = False; save_group_settings()
    send_reply(bot, tid, ttype, f"🔓 ĐÃ MỞ KHÓA NHÓM")

def handle_settings(bot, tid, ttype):
    gs = get_group_settings(tid)
    t = f"⚙️ CÀI ĐẶT NHÓM\n{LINE}\n"
    t += f"▸ Anti-link  : {'✅ BẬT' if gs['antilink'] else '❌ TẮT'}\n"
    t += f"▸ Anti-ảnh   : {'✅ BẬT' if gs['antiimage'] else '❌ TẮT'}\n"
    t += f"▸ Anti-video : {'✅ BẬT' if gs['antivideo'] else '❌ TẮT'}\n"
    t += f"▸ Anti-file  : {'✅ BẬT' if gs['antifile'] else '❌ TẮT'}\n"
    t += f"▸ Lock nhóm  : {'✅ BẬT' if gs['lock'] else '❌ TẮT'}\n"
    send_reply(bot, tid, ttype, t)

# ================== STICKER HELPERS ==================

def _extract_media_url(data, prefer_video=False):
    if not data: return None
    raw = data.get("raw"); raw_msg = data.get("raw_message")
    def scan_string(obj):
        if not isinstance(obj, str): return None
        x = obj.strip()
        if x.startswith("{") and x.endswith("}"):
            try: return scan(json.loads(x))
            except Exception: pass
        if x.startswith(("http://", "https://")): return x.replace("\\/", "/")
        return None
    def scan(obj, depth=0, seen=None):
        if obj is None or depth > 12: return None
        if seen is None: seen = set()
        oid = id(obj)
        if oid in seen: return None
        seen.add(oid)
        if isinstance(obj, str): return scan_string(obj)
        if isinstance(obj, (int, float, bool, bytes)): return None
        if isinstance(obj, dict):
            for k, v in obj.items():
                u = scan(v, depth + 1, seen)
                if u: return u
            return None
        if isinstance(obj, (list, tuple, set)):
            for v in obj:
                u = scan(v, depth + 1, seen)
                if u: return u
            return None
        try: attrs = [a for a in dir(obj) if not a.startswith("_")]
        except Exception: attrs = []
        for a in attrs:
            try:
                v = getattr(obj, a)
                if callable(v): continue
                u = scan(v, depth + 1, seen)
                if u: return u
            except Exception: pass
        return None
    for src in (raw, raw_msg):
        if src is not None:
            u = scan(src)
            if u: return u
    return None

def _extract_image_url(data): return _extract_media_url(data, prefer_video=False)

_URL_RE = re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE)
_IMG_EXT_RE = re.compile(r'\.(jpg|jpeg|png|gif|webp|bmp|heic)(\?|#|$)', re.IGNORECASE)

def _find_image_url_deep(obj, depth=0, seen=None):
    if obj is None or depth > 12: return None
    if seen is None: seen = set()
    oid = id(obj)
    if oid in seen: return None
    seen.add(oid)
    if isinstance(obj, str):
        for m in _URL_RE.finditer(obj):
            u = m.group(0).rstrip('.,;)]}\'"')
            if _IMG_EXT_RE.search(u): return u
        return None
    if isinstance(obj, (int, float, bool, bytes)): return None
    if isinstance(obj, dict):
        for v in obj.values():
            u = _find_image_url_deep(v, depth + 1, seen)
            if u: return u
        return None
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            u = _find_image_url_deep(v, depth + 1, seen)
            if u: return u
        return None
    try: attrs = vars(obj)
    except Exception: attrs = {}
    if not attrs:
        try: attrs = {a: getattr(obj, a) for a in dir(obj) if not a.startswith('_')}
        except Exception: attrs = {}
    for v in attrs.values():
        if callable(v): continue
        u = _find_image_url_deep(v, depth + 1, seen)
        if u: return u
    return None


def _extract_image_url_from_reply(data):
    if not data: return None
    try:
        u = _extract_image_url(data)
        if u: return u
    except Exception: pass
    for key in ("raw_message", "raw"):
        obj = data.get(key)
        if obj is None: continue
        quote = None
        try:
            quote = obj.get("quote") if isinstance(obj, dict) else getattr(obj, "quote", None)
        except Exception: pass
        if quote:
            u = _find_image_url_deep(quote)
            if u: return u
        u = _find_image_url_deep(obj)
        if u: return u
    return None


def _get_tmp_dir():
    try:
        d = tempfile.gettempdir()
        if d and os.path.isdir(d): return d
    except Exception: pass
    for cand in ("/data/data/com.termux/files/usr/tmp", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tmp"), os.path.expanduser("~")):
        try: os.makedirs(cand, exist_ok=True); return cand
        except Exception: continue
    return os.path.dirname(os.path.abspath(__file__))

def _download_media(url, bot=None, kind="media"):
    if not url: return None
    try: import requests
    except Exception as e: print(f"[DL] import requests lỗi: {e}"); return None
    url = str(url).replace("\\/", "/").strip()
    UA = ("Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36")
    tmp_dir = _get_tmp_dir()
    try:
        r = requests.get(url, timeout=90, allow_redirects=True, headers={"User-Agent": UA, "Referer": "https://chat.zalo.me/"})
        ct = r.headers.get("Content-Type", "").lower()
        size = len(r.content)
        print(f"[DL] HTTP {r.status_code} CT={ct} size={size}")
        if r.status_code != 200 or size < 500: return None
        is_image = "image/" in ct or any(url.lower().split("?",1)[0].endswith(e) for e in (".jpg",".jpeg",".png",".gif",".webp",".bmp"))
        is_video = "video/" in ct or any(url.lower().split("?",1)[0].endswith(e) for e in (".mp4",".mov",".mkv",".webm"))
        if kind == "video" and not is_video: return None
        if kind == "image" and not is_image: return None
        ext = ".jpg"
        if "png" in ct: ext = ".png"
        elif "gif" in ct: ext = ".gif"
        elif "webp" in ct: ext = ".webp"
        elif is_video: ext = ".mp4"
        fp = os.path.join(tmp_dir, f"sticker_src_{int(time.time()*1000)}{ext}")
        with open(fp, "wb") as f: f.write(r.content)
        return fp
    except Exception as e:
        print(f"[DL] Lỗi: {e}")
    return None

def _download_image(url, bot=None): return _download_media(url, bot, kind="image")

def _create_sticker(bot, image_path, is_video=False):
    if not image_path or not os.path.isfile(image_path): return None
    static_path = image_path; animation_path = None
    hosts = (("uguu", upload_to_uguu), ("catbox", upload_to_catbox), ("tmpfiles", upload_to_tmpfiles))
    static_url = None
    for name, uploader in hosts:
        try:
            static_url = uploader(static_path)
            if static_url and str(static_url).startswith(("http://", "https://")): break
        except Exception: pass
    if not static_url: return None
    return {"static_url": str(static_url).strip(), "animation_url": None, "static_path": static_path, "animation_path": None, "type": "static"}

def _get_sticker_size(image_path):
    try:
        from PIL import Image
        with Image.open(image_path) as img: return int(img.width), int(img.height)
    except Exception: return 512, 512

def _send_sticker_now(bot, tid, ttype, sticker, image_path=None):
    method = getattr(bot, "sendCustomSticker", None)
    if not callable(method): return False
    if isinstance(sticker, dict):
        static_url = sticker.get("static_url")
        animation_url = sticker.get("animation_url") or ""
        size_path = sticker.get("animation_path") or sticker.get("static_path") or image_path
    else:
        static_url = str(sticker) if sticker else None
        animation_url = ""; size_path = image_path
    if not static_url: return False
    width, height = _get_sticker_size(size_path)
    calls = [
        lambda: method(static_url, animation_url, tid, ttype, width=width, height=height),
        lambda: method(staticImgUrl=static_url, animationImgUrl=animation_url, thread_id=tid, thread_type=ttype, width=width, height=height),
    ]
    for call in calls:
        try:
            call(); return True
        except Exception: pass
    return False


def _send_sticker_with_caption(bot, tid, ttype, sticker, caption="", image_path=None):
    if not sticker: return False
    method = getattr(bot, "sendCustomSticker", None)
    if not callable(method): return False
    if isinstance(sticker, dict):
        static_url = sticker.get("static_url")
        animation_url = sticker.get("animation_url") or ""
        size_path = sticker.get("animation_path") or sticker.get("static_path") or image_path
    else:
        static_url = str(sticker) if sticker else None
        animation_url = ""; size_path = image_path
    if not static_url: return False
    width, height = _get_sticker_size(size_path)
    cap = str(caption or "")[:1900]
    if cap:
        calls = [
            lambda: method(static_url, animation_url, tid, ttype, width=width, height=height, message=cap),
            lambda: method(static_url, animation_url, tid, ttype, width=width, height=height, caption=cap),
        ]
        for call in calls:
            try:
                call(); return True
            except Exception: pass
    for call in (
        lambda: method(static_url, animation_url, tid, ttype, width=width, height=height),
    ):
        try:
            call(); return True
        except Exception: pass
    return False


def _prepare_sticker_from_reply(bot, data):
    if not data: return None
    reply_obj = data.get("raw_message") or data.get("raw")
    if reply_obj is None: return None
    image_url = None
    try:
        image_url = _extract_image_url_from_reply(data)
    except NameError:
        image_url = _extract_image_url(data)
    if not image_url:
        image_url = _extract_image_url(data)
    if not image_url: return None
    image_path = _download_image(image_url, bot)
    if not image_path or not os.path.exists(image_path): return None
    sticker = _create_sticker(bot, image_path, is_video=False)
    return sticker

# ================== STICKER COMMANDS ==================

def handle_taosticker(bot, tid, ttype, uid, ctext, data):
    if not is_user_allowed(uid): send_reply(bot, tid, ttype, f"{LOCK} Bạn chưa có quyền!"); return
    media_path = None; src_desc = ""
    if data:
        url = _extract_image_url(data)
        if url:
            send_reply(bot, tid, ttype, "🔄 Đang tải ảnh...")
            media_path = _download_image(url, bot)
            src_desc = f"reply ({url[:40]}...)"
    if not media_path:
        parts = ctext.split(maxsplit=1)
        if len(parts) >= 2:
            arg = parts[1].strip()
            if arg.startswith("http"):
                send_reply(bot, tid, ttype, "🔄 Đang tải...")
                media_path = _download_image(arg, bot)
                src_desc = f"url ({arg[:40]}...)"
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                fp = arg if os.path.isabs(arg) else os.path.join(base_dir, arg)
                if os.path.exists(fp):
                    media_path = fp; src_desc = f"file ({arg})"
    if not media_path:
        send_reply(bot, tid, ttype, f"{FAIL} KHÔNG TÌM THẤY ẢNH!")
        return
    send_reply(bot, tid, ttype, "🎨 Đang tạo sticker...")
    sticker = _create_sticker(bot, media_path, is_video=False)
    if not sticker: send_reply(bot, tid, ttype, "❌ Không tạo được sticker."); return
    sent = _send_sticker_now(bot, tid, ttype, sticker)
    if not sent: send_reply(bot, tid, ttype, "❌ Zalo không nhận custom sticker."); return
    key = sticker["static_url"]
    CUSTOM_STICKERS[key] = {"src": src_desc, "created_by": str(uid), "static_url": sticker["static_url"]}
    save_json(STICKER_FILE, CUSTOM_STICKERS)
    send_reply(bot, tid, ttype, f"{OK} ĐÃ TẠO STICKER!")

def handle_guisticker(bot, tid, ttype, uid, ctext):
    if not is_user_allowed(uid): send_reply(bot, tid, ttype, f"{LOCK} Bạn chưa có quyền!"); return
    parts = ctext.split(maxsplit=1)
    if len(parts) < 2: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}guisticker <url>"); return
    sid = parts[1].strip(); info = CUSTOM_STICKERS.get(sid, {})
    if isinstance(info, dict) and info.get("static_url"):
        sticker = {"static_url": info.get("static_url"), "animation_url": None}
    else: sticker = sid
    if _send_sticker_now(bot, tid, ttype, sticker): send_reply(bot, tid, ttype, f"{OK} Đã gửi sticker!")
    else: send_reply(bot, tid, ttype, f"{FAIL} Gửi sticker thất bại!")

def handle_stickerlist(bot, tid, ttype, uid):
    if not is_user_allowed(uid): send_reply(bot, tid, ttype, f"{LOCK} Bạn chưa có quyền!"); return
    if not CUSTOM_STICKERS: send_reply(bot, tid, ttype, f"{INFO} DS sticker trống."); return
    t = f"🎨 DS STICKER ({len(CUSTOM_STICKERS)})\n{LINE}"
    for i, (sid, info) in enumerate(list(CUSTOM_STICKERS.items())[:30], 1):
        t += f"\n{DOT} {i}. `{sid[:30]}...`"
    send_reply(bot, tid, ttype, t)

def handle_xoasticker(bot, tid, ttype, uid, ctext):
    if not is_owner(uid): send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner!"); return
    parts = ctext.split()
    if len(parts) < 2: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}xoasticker <id>"); return
    sid = parts[1].strip()
    if sid not in CUSTOM_STICKERS: send_reply(bot, tid, ttype, f"{WARN} Không tìm thấy!"); return
    del CUSTOM_STICKERS[sid]; save_json(STICKER_FILE, CUSTOM_STICKERS)
    send_reply(bot, tid, ttype, f"🗑️ Đã xóa sticker!")

# ================== MINIGAME ==================

def handle_dice(bot, tid, ttype, uid):
    n = random.randint(1, 6); faces = ["⚀","⚁","⚂","⚃","⚄","⚅"]
    send_reply(bot, tid, ttype, f"🎲 XÚC XẮC\n{LINE}\n▸ Kết quả: {faces[n-1]} {n}")

def handle_coin(bot, tid, ttype, uid):
    send_reply(bot, tid, ttype, f"🪙 LẬT ĐỒNG XU\n{LINE}\n▸ Kết quả: {random.choice(['Ngửa (Heads)', 'Sấp (Tails)'])}")

def handle_daovang(bot, tid, ttype, uid): handle_coin(bot, tid, ttype, uid)

def handle_rps(bot, tid, ttype, uid, ctext):
    parts = ctext.split(maxsplit=1)
    if len(parts) < 2: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}rps <kéo|búa|bao>"); return
    user_choice = parts[1].strip().lower()
    mapping = {"kéo":"kéo","keo":"kéo","búa":"búa","bua":"búa","bao":"bao","báo":"bao"}
    user_choice = mapping.get(user_choice)
    if not user_choice: send_reply(bot, tid, ttype, f"{FAIL} Chỉ chọn: kéo / búa / bao"); return
    bot_choice = random.choice(["kéo", "búa", "bao"]); emoji = {"kéo":"✌️","búa":"✊","bao":"🖐️"}
    if user_choice == bot_choice: result = "HÒA 🤝"
    elif (user_choice == "kéo" and bot_choice == "bao") or (user_choice == "búa" and bot_choice == "kéo") or (user_choice == "bao" and bot_choice == "búa"): result = "BẠN THẮNG 🎉"
    else: result = "BOT THẮNG 🤖"
    t = f"✊ OẰN TÙ TÌ\n{LINE}\n▸ Bạn : {emoji[user_choice]} {user_choice}\n▸ Bot : {emoji[bot_choice]} {bot_choice}\n\n▸ Kết quả: {result}"
    send_reply(bot, tid, ttype, t)

def handle_doanso(bot, tid, ttype, uid, ctext):
    key = f"{tid}:{uid}"; parts = ctext.split(maxsplit=1)
    if len(parts) < 2:
        GAME_STATE[key] = {"game":"doanso","number":random.randint(1,100),"tries":0,"time":time.time()}
        send_reply(bot, tid, ttype, f"🎯 ĐOÁN SỐ 1-100\n{LINE}\n▸ Bot đã chọn 1 số\n▸ Gõ {PREFIX}doanso <số>\n▸ Bạn có 7 lần đoán"); return
    if key not in GAME_STATE or GAME_STATE[key].get("game") != "doanso": send_reply(bot, tid, ttype, f"{WARN} Chưa bắt đầu!"); return
    state = GAME_STATE[key]
    if time.time() - state["time"] > 300: del GAME_STATE[key]; send_reply(bot, tid, ttype, f"{WARN} Hết thời gian!"); return
    try: guess = int(parts[1].strip())
    except ValueError: send_reply(bot, tid, ttype, f"{FAIL} Phải nhập số 1-100"); return
    if guess < 1 or guess > 100: send_reply(bot, tid, ttype, f"{FAIL} Số phải từ 1-100"); return
    state["tries"] += 1; target = state["number"]
    if guess == target: del GAME_STATE[key]; send_reply(bot, tid, ttype, f"🎉 ĐÚNG RỒI!\n▸ Số đúng: {target}\n▸ Đoán đúng sau {state['tries']} lần!")
    elif state["tries"] >= 7: del GAME_STATE[key]; send_reply(bot, tid, ttype, f"💥 THUA RỒI!\n▸ Số đúng: {target}")
    elif guess < target: send_reply(bot, tid, ttype, f"📈 LỚN HƠN {guess}!\n▸ Còn {7-state['tries']} lần")
    else: send_reply(bot, tid, ttype, f"📉 NHỎ HƠN {guess}!\n▸ Còn {7-state['tries']} lần")

def handle_8ball(bot, tid, ttype, uid, ctext):
    parts = ctext.split(maxsplit=1)
    if len(parts) < 2: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}8ball <câu hỏi>"); return
    answers = ["Chắc chắn rồi ✅","Không đâu ❌","Có thể 🤔","Đừng mơ 😂","Có nhé 😊","Không bao giờ 🙅","Hỏi lại sau đi","Chính xác 💯","Không nên 🚫","Nên làm đi 👍"]
    send_reply(bot, tid, ttype, f"🎱 BÓI TOÁN\n{LINE}\n▸ Câu hỏi: {parts[1].strip()}\n▸ Trả lời: {random.choice(answers)}")

def handle_rate(bot, tid, ttype, uid, ctext):
    parts = ctext.split(maxsplit=1)
    if len(parts) < 2: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}rate <nội dung>"); return
    score = random.randint(1, 10); stars = "⭐" * score + "☆" * (10 - score)
    send_reply(bot, tid, ttype, f"📊 ĐÁNH GIÁ\n{LINE}\n▸ Nội dung: {parts[1].strip()}\n▸ Điểm: {score}/10\n{stars}")

def handle_rand(bot, tid, ttype, uid, ctext):
    parts = ctext.split()
    if len(parts) < 3: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}rand <min> <max>"); return
    try: a = int(parts[1]); b = int(parts[2])
    except ValueError: send_reply(bot, tid, ttype, f"{FAIL} Phải là số!"); return
    if a > b: a, b = b, a
    send_reply(bot, tid, ttype, f"🎲 RANDOM\n{LINE}\n▸ Khoảng: {a} - {b}\n▸ Kết quả: {random.randint(a, b)}")

def handle_chon(bot, tid, ttype, uid, ctext):
    parts = ctext.split(maxsplit=1)
    if len(parts) < 2: send_reply(bot, tid, ttype, f"{FAIL} Cú pháp: {PREFIX}chon <a | b | c>"); return
    items = [x.strip() for x in parts[1].split("|") if x.strip()]
    if len(items) < 2: send_reply(bot, tid, ttype, f"{FAIL} Cần ít nhất 2 lựa chọn cách nhau bằng `|`"); return
    pick = random.choice(items)
    t = f"🎯 CHỌN NGẪU NHIÊN\n{LINE}\n"
    for i, it in enumerate(items, 1): t += f"▸ {i}. {it}\n"
    t += f"\n{OK} Kết quả: {pick}"
    send_reply(bot, tid, ttype, t)

def handle_tuvan(bot, tid, ttype, uid):
    advices = ["Hãy tin vào bản thân 💪","Nghỉ ngơi chút đi ☕","Hôm nay tốt để bắt đầu điều mới ✨","Đừng lo, mọi chuyện sẽ ổn 🌈","Hãy nói ra điều bạn nghĩ 💬","Tập trung mục tiêu chính 🎯","Đi ngủ sớm cho khỏe 😴","Học hỏi từ sai lầm 📚","Gọi cho người thân 📞","Uống nhiều nước 💧"]
    send_reply(bot, tid, ttype, f"💡 TƯ VẤN\n{LINE}\n▸ {random.choice(advices)}")

# ================== LIKE FF ==================

def _like_check_limit(author_id):
    if LIKE_DAILY_LIMIT is None or is_owner(author_id) or is_user_allowed(author_id):
        return True
    today = time.strftime("%Y-%m-%d")
    aid = str(author_id)
    entry = LIKE_USAGE_TODAY.get(aid)
    if not entry or entry.get("date") != today:
        entry = {"count": 0, "date": today}
    if entry["count"] >= LIKE_DAILY_LIMIT:
        LIKE_USAGE_TODAY[aid] = entry
        return False
    entry["count"] += 1
    LIKE_USAGE_TODAY[aid] = entry
    return True

def handle_like(bot, tid, ttype, uid, ctext):
    if not is_user_allowed(uid) and not is_owner(uid):
        send_reply(bot, tid, ttype, f"{LOCK} Bạn chưa có quyền!"); return
    parts = ctext.split()
    if len(parts) < 2:
        send_reply(bot, tid, ttype, f"{WARN} BUFF LIKE FF\n{LINE}\n▸ Cú pháp: {PREFIX}like <UID Free Fire>")
        return
    ff_uid = parts[1].strip()
    if not ff_uid.isdigit():
        send_reply(bot, tid, ttype, f"{FAIL} UID chỉ được chứa số."); return
    if not _like_check_limit(uid):
        send_reply(bot, tid, ttype, f"{FAIL} Hết lượt buff hôm nay."); return
    try:
        import requests
        params = {"uid": ff_uid, "key": LIKE_API_KEY}
        response = requests.get(LIKE_API_URL, params=params, timeout=30)
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict) and "Thất bại" in result:
            send_reply(bot, tid, ttype, f"{FAIL} {result['Thất bại']}"); return
        ket_qua = result.get('result') if isinstance(result, dict) else None
        if isinstance(ket_qua, dict):
            api_info = ket_qua.get('API', {}) or {}
            likes_detail = ket_qua.get('Likes Info', {}) or {}
            account_info = ket_qua.get('User Info', {}) or {}
            t = (
                f"🎯 BUFF LIKE FREE FIRE\n{LINE}\n"
                f"👤 Tài khoản:\n"
                f"▸ Tên: {account_info.get('Account Name', 'N/A')}\n"
                f"▸ UID: {account_info.get('Account UID', 'N/A')}\n"
                f"▸ Level: {account_info.get('Level', 'N/A')}\n"
                f"▸ Khu vực: {account_info.get('Region', 'N/A')}\n\n"
                f"❤️ Like:\n"
                f"▸ Trước: {likes_detail.get('Likes Before', 'N/A')}\n"
                f"▸ Thêm: +{likes_detail.get('Likes Added', 'N/A')}\n"
                f"▸ Sau: {likes_detail.get('Likes After', 'N/A')}\n\n"
                f"⚡ API:\n"
                f"▸ Status: {'Thành công' if api_info.get('Success') else 'Thất bại'}\n"
                f"▸ Token dùng: {api_info.get('Tokens Used', 'N/A')}\n"
                f"▸ Token còn: {api_info.get('Tokens Remaining', 'N/A')}\n"
                f"▸ Tốc độ: {api_info.get('speed', 'N/A')}"
            )
            send_reply(bot, tid, ttype, t)
        else:
            send_reply(bot, tid, ttype, f"{FAIL} API trả về dữ liệu không xác định.")
    except Exception as e:
        print(f"💥 Like error: {e}")
        send_reply(bot, tid, ttype, f"{FAIL} Lỗi: {str(e)[:120]}")

# ================== UNKNOWN / ROUTER ==================

def handle_unknown_command(bot, tid, ttype, cmd):
    sug = []
    for k in COMMANDS.keys():
        if abs(len(k) - len(cmd)) <= 2:
            if sum(1 for a, b in zip(cmd, k) if a == b) >= max(1, len(cmd) - 2): sug.append(k)
    t = f"{FAIL} LỆNH KHÔNG TỒN TẠI\n{LINE}\n▸ Bạn gõ: {PREFIX}{cmd}"
    if sug:
        t += f"\n\n{INFO} Có phải bạn muốn?"
        for s in sug[:3]: t += f"\n  {DOT} {PREFIX}{s}  {ARROW}  {COMMANDS[s]}"
    t += f"\n\n✨ Gõ {PREFIX}menu để xem menu."
    send_reply(bot, tid, ttype, t)

def process_command(bot, tid, ttype, data, uid, ctext):
    global BOT_SLEEPING
    parts = ctext.split()
    if not parts: return
    cmd = parts[0].lower(); args = parts[1:]

    if BOT_SLEEPING:
        if cmd == "boton" and is_owner(uid): handle_boton(bot, tid, ttype, uid)
        elif cmd == "boton": send_reply(bot, tid, ttype, f"{FAIL} Chỉ Owner đánh thức!")
        else: print(f"[SLEEP] Bỏ qua: {cmd}")
        return

    if cmd in ("help","menu"): handle_help(bot, tid, ttype); return
    if cmd == "menuad": handle_menuad(bot, tid, ttype); return
    if cmd == "menuvip": handle_menuvip(bot, tid, ttype); return

    if cmd == "info": handle_info(bot, tid, ttype); return
    if cmd == "ping": handle_ping(bot, tid, ttype); return
    if cmd == "uptime": handle_uptime(bot, tid, ttype); return
    if cmd == "test": handle_test(bot, tid, ttype); return

    if cmd == "capquyen": handle_capquyen(bot, tid, ttype, data, uid, ctext); return
    if cmd == "thuquyen": handle_thuquyen(bot, tid, ttype, data, uid, ctext); return
    if cmd == "dsquyen": handle_dsquyen(bot, tid, ttype, uid); return
    if cmd == "sleep": handle_sleep(bot, tid, ttype, uid); return
    if cmd == "boton": handle_boton(bot, tid, ttype, uid); return
    if cmd == "botoff": handle_botoff(bot, tid, ttype, uid); return
    if cmd == "setlenh": handle_setlenh(bot, tid, ttype, uid, ctext); return
    if cmd == "rs": handle_restart(bot, tid, ttype, uid); return
    if cmd == "war": handle_war(bot, tid, ttype, uid, args); return
    if cmd == "chui": handle_chui(bot, tid, ttype, uid, args, ctext, data); return
    if cmd == "spam": handle_spam(bot, tid, ttype, uid, args, ctext, data); return
    if cmd == "anh": handle_anh(bot, tid, ttype, uid, args, ctext); return
    if cmd == "voice": handle_voice(bot, tid, ttype, uid, args, ctext); return
    if cmd == "like": handle_like(bot, tid, ttype, uid, ctext); return
    if cmd == "stop": handle_stop(bot, tid, ttype, uid); return
    if cmd == "copy": handle_copy(bot, tid, ttype, data, uid, ctext); return
    if cmd == "uncopy": handle_uncopy(bot, tid, ttype, data, uid, ctext); return
    if cmd == "dscopy": handle_dscopy(bot, tid, ttype, uid); return

    if cmd == "mute": handle_mute(bot, tid, ttype, data, uid, ctext); return
    if cmd == "muteid": handle_muteid(bot, tid, ttype, data, uid, ctext); return
    if cmd == "unmute": handle_unmute(bot, tid, ttype, data, uid, ctext); return
    if cmd == "dsmute": handle_dsmute(bot, tid, ttype, uid); return
    if cmd == "checkmute": handle_checkmute(bot, tid, ttype, data, uid, ctext); return
    if cmd == "mutetime": handle_mutetime(bot, tid, ttype, uid, ctext); return

    if cmd == "debuggroup": handle_debuggroup(bot, tid, ttype, uid); return
    if cmd == "debugmem": handle_debugmem(bot, tid, ttype, uid); return

    if cmd == "groupinfo": handle_groupinfo(bot, tid, ttype); return
    if cmd == "setname": handle_setname(bot, tid, ttype, uid, ctext); return
    if cmd == "kick": handle_kick(bot, tid, ttype, data, uid, ctext); return
    if cmd == "adduser": handle_adduser(bot, tid, ttype, data, uid, ctext); return
    if cmd == "promote": handle_promote(bot, tid, ttype, data, uid, ctext); return
    if cmd == "demote": handle_demote(bot, tid, ttype, data, uid, ctext); return

    if cmd == "antilink": handle_antilink(bot, tid, ttype, uid); return
    if cmd == "antiimage": handle_antiimage(bot, tid, ttype, uid); return
    if cmd == "antivideo": handle_antivideo(bot, tid, ttype, uid); return
    if cmd == "antifile": handle_antifile(bot, tid, ttype, uid); return
    if cmd == "lock": handle_lock(bot, tid, ttype, uid); return
    if cmd == "unlock": handle_unlock(bot, tid, ttype, uid); return
    if cmd == "settings": handle_settings(bot, tid, ttype); return

    if cmd == "dice": handle_dice(bot, tid, ttype, uid); return
    if cmd == "coin": handle_coin(bot, tid, ttype, uid); return
    if cmd == "daovang": handle_daovang(bot, tid, ttype, uid); return
    if cmd == "rps": handle_rps(bot, tid, ttype, uid, ctext); return
    if cmd == "doanso": handle_doanso(bot, tid, ttype, uid, ctext); return
    if cmd == "8ball": handle_8ball(bot, tid, ttype, uid, ctext); return
    if cmd == "rate": handle_rate(bot, tid, ttype, uid, ctext); return
    if cmd == "rand": handle_rand(bot, tid, ttype, uid, ctext); return
    if cmd == "chon": handle_chon(bot, tid, ttype, uid, ctext); return
    if cmd == "tuvan": handle_tuvan(bot, tid, ttype, uid); return

    if cmd == "taosticker": handle_taosticker(bot, tid, ttype, uid, ctext, data); return
    if cmd == "guisticker": handle_guisticker(bot, tid, ttype, uid, ctext); return
    if cmd in ("stickerlist", "dssticker"): handle_stickerlist(bot, tid, ttype, uid); return
    if cmd == "xoasticker": handle_xoasticker(bot, tid, ttype, uid, ctext); return

    handle_unknown_command(bot, tid, ttype, cmd)

def handle_incoming_message(bot, mid, author_id, message, message_object, tid, ttype):
    text = parse_message_text(message)
    media_type = detect_media_type(message)
    is_media_msg = media_type is not None
    print(f"\n{'=' * 55}\n[IN] author={author_id} tid={tid} ttype={ttype}\n     media={media_type} text={text[:80]!r}")
    if not tid: return
    author_str = str(author_id) if author_id else ""
    is_from_bot = (author_str == str(BOT_OWNER_ID))
    is_from_admin = is_group_admin(bot, tid, author_id) if not is_from_bot else True

    if not is_from_bot:
        muted = None
        if author_str in MUTED_USERS: muted = author_str
        elif not text.startswith(PREFIX):
            for uid in extract_mentions(message_object):
                if str(uid) in MUTED_USERS: muted = str(uid); break
        if muted:
            print(f"     → 🔇 MUTE")
            delayed_delete(bot, message_object, tid, ttype, author_id=author_str); return

    gs = get_group_settings(tid)
    block = False; reason = ""
    if not is_from_bot and not is_from_admin:
        if gs.get("lock"): block = True; reason = "LOCK"
        elif gs.get("antilink") and text and contains_link(text): block = True; reason = "LINK"
        elif gs.get("antiimage") and media_type == "image": block = True; reason = "IMG"
        elif gs.get("antivideo") and media_type == "video": block = True; reason = "VID"
        elif gs.get("antifile") and media_type == "file": block = True; reason = "FILE"
    if block:
        print(f"     → 🚫 {reason}")
        delete_message(bot, message_object, tid, ttype, author_id=author_str)
        return

    if not is_from_bot and author_str in COPY_TARGETS and text and not text.startswith(PREFIX):
        do_copy_message(bot, author_id, text, tid, ttype, get_msg_id(message_object))

    if is_media_msg and not text: return
    if check_war_confirmation(bot, tid, ttype, author_id, text): return
    if not text.startswith(PREFIX): return
    ctext = text[len(PREFIX):].strip()
    if not ctext: return
    print(f"     → ✅ XỬ LÝ: {ctext}")
    data = {"raw": message_object, "raw_message": message}
    try:
        process_command(bot, tid, ttype, data, author_id, ctext)
    except Exception as e:
        print(f"[!] Lỗi: {e}"); import traceback; traceback.print_exc()

def handle_undo_message(bot, mid, author_id, tid, ttype):
    if not tid or not mid: return
    do_undo_copy(bot, mid, tid, ttype)

class ZaloBot(ZaloAPI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    def onMessage(self, mid=None, author_id=None, message=None, message_object=None, thread_id=None, thread_type=ThreadType.USER):
        if author_id is not None and message is not None:
            try: handle_incoming_message(self, mid, author_id, message, message_object, thread_id, thread_type)
            except Exception as e: print(f"[!] Lỗi onMessage: {e}")
        try: return super().onMessage(mid, author_id, message, message_object, thread_id, thread_type)
        except Exception: pass
    def onUndo(self, *args, **kwargs):
        mid = args[0] if len(args) >= 1 else kwargs.get("mid")
        author_id = args[1] if len(args) >= 2 else kwargs.get("author_id")
        tid = args[4] if len(args) >= 5 else kwargs.get("thread_id")
        ttype = args[5] if len(args) >= 6 else kwargs.get("thread_type")
        try: handle_undo_message(self, mid, author_id, tid, ttype)
        except Exception as e: print(f"[!] Lỗi onUndo: {e}")
        try: return super().onUndo(*args, **kwargs)
        except Exception: pass

print("=" * 55); print("🤖 Đang khởi tạo bot Zalo..."); print("=" * 55)
try:
    bot = ZaloBot(phone=None, password=None, imei=IMEI, cookies=COOKIES)
    BOT_OWNER_ID = str(_call(getattr(bot, "uid")))
    print(f"✅ Đăng nhập OK! UID: {BOT_OWNER_ID}")
except Exception as e:
    print(f"❌ Lỗi đăng nhập: {e}"); import traceback; traceback.print_exc(); sys.exit(1)

for attr in ("display_name","name","username","user_name","displayName"):
    v = getattr(bot, attr, None)
    if v:
        v = _call(v)
        if isinstance(v, str) and v: BOT_NAME = v; break

print(f"📛 Tên bot: {BOT_NAME}"); print(f"👑 Owner: {BOT_OWNER_ID}"); print("=" * 55)

_ensure_fast_workers()

if __name__ == "__main__":
    print(f"\n🤖 Bot sẵn sàng! Prefix: '{PREFIX}'")
    print(f"👑 Owner: {BOT_OWNER_ID}")
    print(f"👥 Users: {len(ALLOWED_USERS)} | Muted: {len(MUTED_USERS)}")
    print(f"🎨 Sticker: {len(CUSTOM_STICKERS)}")
    print(f"📋 Menu:  {PREFIX}menu | {PREFIX}menuad | {PREFIX}menuvip")
    print("=" * 55)
    try:
        bot.listen(run_forever=True)
    except TypeError:
        try: bot.listen()
        except KeyboardInterrupt: print("\n👋 Dừng.")
        except Exception as e: print(f"❌ Lỗi: {e}")
    except KeyboardInterrupt: print("\n👋 Dừng.")
    except Exception as e:
        print(f"❌ Lỗi: {e}"); import traceback; traceback.print_exc()