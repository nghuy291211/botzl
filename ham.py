# -*- coding: utf-8 -*-
import json, os, sys, inspect, time

# ================== IMPORT ZLAPI ==================
try:
    from zlapi import ZaloAPI
except Exception as e:
    print(f"[!] Không import được zlapi: {e}")
    sys.exit(1)

try:
    from zlapi.models import Message, ThreadType
except Exception:
    Message = None
    class ThreadType:
        USER = "User"
        GROUP = "Group"

# ================== ĐỌC CONFIG ==================
CONFIG_FILE = "config.json"
if not os.path.exists(CONFIG_FILE):
    print(f"❌ Không tìm thấy {CONFIG_FILE}!")
    sys.exit(1)

try:
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        _cfg = json.load(f)
except Exception as e:
    print(f"❌ Lỗi đọc {CONFIG_FILE}: {e}")
    sys.exit(1)

IMEI = str(_cfg.get("imei", "")).strip()
COOKIES = _cfg.get("cookies", {})

if not IMEI or IMEI.startswith("DÁN_"):
    print("❌ Chưa điền IMEI trong config.json!"); sys.exit(1)
if not COOKIES or not isinstance(COOKIES, dict):
    print("❌ Chưa điền COOKIES trong config.json!"); sys.exit(1)

print(f"✅ Load config OK | IMEI dài {len(IMEI)} | {len(COOKIES)} cookies")

# ================== PREFIX ==================
PREFIX = "."

# ================== GỬI TIN ==================
def send_text(bot, tid, ttype, text):
    text = str(text)[:1900]
    if Message is None:
        return None
    msg_obj = None
    for kwargs in ({"text": text}, {"description": text}, {"title": text}):
        try:
            msg_obj = Message(**kwargs); break
        except Exception:
            pass
    if msg_obj is None:
        return None
    for mname in ("send", "sendMessage"):
        if not hasattr(bot, mname):
            continue
        try:
            return getattr(bot, mname)(msg_obj, tid, ttype)
        except Exception as e:
            print(f"[SEND] {mname} lỗi: {e}")
    try:
        return bot.send(message=msg_obj, thread_id=tid, thread_type=ttype)
    except Exception as e:
        print(f"[SEND] kw lỗi: {e}")
    return None

# ================== XỬ LÝ TIN NHẮN ==================
def parse_text(message):
    if message is None: return ""
    if isinstance(message, str): return message.strip()
    if isinstance(message, dict):
        for k in ("text", "content", "body", "message"):
            v = message.get(k)
            if isinstance(v, str) and v: return v.strip()
        return ""
    for k in ("text", "content", "body", "message"):
        v = getattr(message, k, None)
        if isinstance(v, str) and v: return v.strip()
    return ""

# ================== LỆNH .ham ==================
def cmd_ham(bot, tid, ttype):
    """Liệt kê tất cả method public của bot + phân nhóm theo chức năng."""

    # Gom tất cả attribute là callable, bỏ qua dunder/private
    all_methods = []
    for name in dir(bot):
        if name.startswith("_"):
            continue
        try:
            attr = getattr(bot, name)
        except Exception:
            continue
        if callable(attr):
            all_methods.append(name)

    all_methods.sort()

    # Phân nhóm theo keyword trong tên hàm
    groups = {
        "📨 Gửi tin / Tin nhắn":     [],
        "🖼️ Ảnh / Video / File":     [],
        "🎨 Sticker / Voice":         [],
        "👥 Nhóm (Group)":            [],
        "👤 Người dùng (User)":       [],
        "🔐 Đăng nhập / Session":     [],
        "⚙️  Khác":                    [],
    }

    def classify(m):
        ml = m.lower()
        if any(k in ml for k in ("sticker", "voice", "audio")):
            return "🎨 Sticker / Voice"
        if any(k in ml for k in ("image", "photo", "video", "file", "attach", "media", "upload")):
            return "🖼️ Ảnh / Video / File"
        if any(k in ml for k in ("group", "member", "admin", "kick", "invite", "join", "leave", "rename", "block")):
            return "👥 Nhóm (Group)"
        if any(k in ml for k in ("user", "friend", "profile", "avatar", "name", "info")):
            return "👤 Người dùng (User)"
        if any(k in ml for k in ("login", "logout", "cookie", "session", "token", "imei", "auth")):
            return "🔐 Đăng nhập / Session"
        if any(k in ml for k in ("send", "message", "msg", "chat", "reply", "undo", "delete", "react")):
            return "📨 Gửi tin / Tin nhắn"
        return "⚙️  Khác"

    for m in all_methods:
        groups[classify(m)].append(m)

    # ----- Gửi header -----
    total = len(all_methods)
    header = (
        f"📋 DANH SÁCH HÀM ZLAPI\n"
        f"─────────────────────────────\n"
        f"▸ Instance: {type(bot).__name__}\n"
        f"▸ Tổng số method public: {total}\n"
        f"▸ Lệnh: {PREFIX}ham"
    )
    send_text(bot, tid, ttype, header)
    time.sleep(0.4)

    # ----- Gửi từng nhóm (mỗi tin ≤ 60 dòng để không bị cắt) -----
    for gname, items in groups.items():
        if not items:
            continue
        chunk = f"\n{gname} ({len(items)})\n─────────────────────────────\n"
        for m in items:
            # Lấy chữ ký hàm (nếu đọc được)
            sig = ""
            try:
                sig = str(inspect.signature(getattr(bot, m)))
                if len(sig) > 80:
                    sig = sig[:77] + "..."
            except Exception:
                sig = "(...)"
            chunk += f"▸ {m}{sig}\n"
            if len(chunk) > 1600:
                send_text(bot, tid, ttype, chunk)
                time.sleep(0.4)
                chunk = ""
        if chunk:
            send_text(bot, tid, ttype, chunk)
            time.sleep(0.4)

    # ----- Gửi footer tổng kết -----
    footer = "✅ Hết danh sách.\n"
    footer += "\n".join(f"▸ {g}: {len(v)}" for g, v in groups.items() if v)
    send_text(bot, tid, ttype, footer)

# ================== ROUTER ==================
def handle_message(bot, mid, author_id, message, message_object, tid, ttype):
    text = parse_text(message)
    if not text:
        return

    print(f"[IN] tid={tid} ttype={ttype} author={author_id} text={text[:80]!r}")

    if not text.startswith(PREFIX):
        return

    ctext = text[len(PREFIX):].strip()
    if not ctext:
        return

    parts = ctext.split()
    cmd = parts[0].lower()

    print(f"[CMD] .{cmd}")

    if cmd == "ham":
        try:
            cmd_ham(bot, tid, ttype)
        except Exception as e:
            import traceback; traceback.print_exc()
            send_text(bot, tid, ttype, f"❌ Lỗi liệt kê hàm: {e}")
        return

    # Lệnh khác → báo không tồn tại
    send_text(bot, tid, ttype,
              f"❌ Lệnh không tồn tại: {PREFIX}{cmd}\n"
              f"▸ Chỉ có: {PREFIX}ham")

# ================== CLASS BOT ==================
class MyBot(ZaloAPI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def onMessage(self, mid=None, author_id=None, message=None,
                  message_object=None, thread_id=None,
                  thread_type=ThreadType.USER):
        if author_id is not None and message is not None:
            try:
                handle_message(self, mid, author_id, message,
                               message_object, thread_id, thread_type)
            except Exception as e:
                print(f"[!] Lỗi onMessage: {e}")
                import traceback; traceback.print_exc()
        try:
            return super().onMessage(mid, author_id, message,
                                     message_object, thread_id, thread_type)
        except Exception:
            pass

# ================== MAIN ==================
print("=" * 50)
print("🤖 Khởi tạo bot...")
print("=" * 50)

try:
    bot = MyBot(phone=None, password=None, imei=IMEI, cookies=COOKIES)
    BOT_UID = getattr(bot, "uid", None)
    if callable(BOT_UID):
        BOT_UID = BOT_UID()
    print(f"✅ Đăng nhập OK! UID = {BOT_UID}")
except Exception as e:
    print(f"❌ Lỗi đăng nhập: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

# Đếm method public để in ra console luôn
_public_methods = [m for m in dir(bot)
                   if not m.startswith("_") and callable(getattr(bot, m, None))]
print(f"📋 Tổng số method public: {len(_public_methods)}")
print(f"▸ Gõ {PREFIX}ham trong chat để xem chi tiết.")
print("=" * 50)

if __name__ == "__main__":
    try:
        bot.listen(run_forever=True)
    except TypeError:
        try:
            bot.listen()
        except KeyboardInterrupt:
            print("\n👋 Dừng.")
        except Exception as e:
            print(f"❌ Lỗi listen: {e}")
    except KeyboardInterrupt:
        print("\n👋 Dừng.")
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        import traceback; traceback.print_exc()