from zlapi.models import Message, MultiMsgStyle, MessageStyle
import requests
import time

des = {
    'version': "4.3",
    'credits': "Ty Rô",
    'description': "Buff like Free Fire"
}

# ================= CONFIG =================
# Đổi API_URL/API_KEY ở đây khi server đổi, không cần sửa logic bên dưới.
API_URL = "https://likes-9qet.onrender.com/likes"
API_KEY = "ditmoemay"

# Giới hạn lượt buff mỗi user thường/ngày. Đặt None để tắt giới hạn.
DAILY_LIMIT = None


class BuffFFHandler:
    def __init__(self, client):
        self.client = client
        self.usage_today = {}   # {author_id: {"count": int, "date": "YYYY-MM-DD"}}

    # ---------------- UTILS ----------------
    def get_user_name(self, uid):
        try:
            user_info = self.client.fetchUserInfo(uid)
            return user_info.changed_profiles.get(str(uid), {}).get("zaloName", str(uid))
        except Exception:
            return str(uid)

    def _styled_reply(self, name, rest, message_object, thread_id, thread_type, ttl=60000):
        msg = f"{name}\n➜ {rest}"
        styles = MultiMsgStyle([
            MessageStyle(offset=0, length=len(name), style="color", color="#db342e", auto_format=False),
            MessageStyle(offset=0, length=len(name), style="bold", auto_format=False),
        ])
        self.client.replyMessage(Message(text=msg, style=styles), message_object, thread_id, thread_type, ttl=ttl)

    def _react(self, message_object, thread_id, thread_type, emoji):
        try:
            self.client.sendReaction(message_object, emoji, thread_id, thread_type, reactionType=75)
        except Exception:
            pass

    def _is_admin(self, author_id):
        try:
            return str(author_id) in set(map(str, getattr(self.client, "ADMIN", [])))
        except Exception:
            return False

    def _check_and_count_limit(self, author_id):
        """Trả về True nếu còn lượt dùng, False nếu đã hết. Admin luôn True."""
        if DAILY_LIMIT is None or self._is_admin(author_id):
            return True

        today = time.strftime("%Y-%m-%d")
        entry = self.usage_today.get(author_id)

        if not entry or entry.get("date") != today:
            entry = {"count": 0, "date": today}

        if entry["count"] >= DAILY_LIMIT:
            self.usage_today[author_id] = entry
            return False

        entry["count"] += 1
        self.usage_today[author_id] = entry
        return True

    # ---------------- COMMAND ----------------
    def handle_buffff_command(self, message, message_object, thread_id, thread_type, author_id):
        name = self.get_user_name(author_id)
        content = message.strip().split()

        if len(content) < 2:
            self._styled_reply(name, "⚠️ Vui lòng nhập UID Free Fire cần buff like.\nVí dụ: /buffff 123456789",
                                message_object, thread_id, thread_type)
            self._react(message_object, thread_id, thread_type, "⚠️")
            return

        uid = content[1].strip()

        if not uid.isdigit():
            self._styled_reply(name, "❌ UID không hợp lệ! UID chỉ được chứa số.",
                                message_object, thread_id, thread_type)
            self._react(message_object, thread_id, thread_type, "❌")
            return

        if not self._check_and_count_limit(author_id):
            self._styled_reply(name, f"❌ Bạn đã dùng hết lượt buff like hôm nay (giới hạn {DAILY_LIMIT} lượt/ngày).",
                                message_object, thread_id, thread_type)
            self._react(message_object, thread_id, thread_type, "❌")
            return

        try:
            params = {"uid": uid, "key": API_KEY}

            print(f"🔄 Đang gửi request buff like cho UID: {uid}")
            print(f"📡 API URL: {API_URL} | params: {params}")

            self._react(message_object, thread_id, thread_type, "🔄")

            response = requests.get(API_URL, params=params, timeout=30)
            response.raise_for_status()

            result = response.json()
            print(f"✅ API response: {result}")

            # Xử lý các trường hợp lỗi từ API
            if isinstance(result, dict) and "Thất bại" in result:
                self._styled_reply(name, f"❌ {result['Thất bại']}",
                                    message_object, thread_id, thread_type)
                self._react(message_object, thread_id, thread_type, "❌")
                return

            # Xử lý kết quả thành công
            ket_qua = result.get('result') if isinstance(result, dict) else None
            if isinstance(ket_qua, dict):
                api_info = ket_qua.get('API', {})
                likes_detail = ket_qua.get('Likes Info', {})
                account_info = ket_qua.get('User Info', {})

                thanh_cong = api_info.get('Success', False)

                rest = (
                    "🎯 TĂNG LIKE FREE FIRE THÀNH CÔNG\n\n"
                    f"👤 Thông tin tài khoản:\n"
                    f"• Tên: {account_info.get('Account Name', 'N/A')}\n"
                    f"• UID: {account_info.get('Account UID', 'N/A')}\n"
                    f"• Level: {account_info.get('Level', 'N/A')}\n"
                    f"• Khu vực: {account_info.get('Region', 'N/A')}\n\n"
                    f"❤️ Thông tin Like:\n"
                    f"• Like trước: {likes_detail.get('Likes Before', 'N/A')}\n"
                    f"• Like thêm: +{likes_detail.get('Likes Added', 'N/A')}\n"
                    f"• Like sau: {likes_detail.get('Likes After', 'N/A')}\n\n"
                    f"⚡ Thông tin API:\n"
                    f"• Trạng thái: {'Thành công' if thanh_cong else 'Thất bại'}\n"
                    f"• Token đã dùng: {api_info.get('Tokens Used', 'N/A')}\n"
                    f"• Token còn lại: {api_info.get('Tokens Remaining', 'N/A')}\n"
                    f"• Tốc độ: {api_info.get('speed', 'N/A')}"
                )
                self._styled_reply(name, rest, message_object, thread_id, thread_type, ttl=120000)
                self._react(message_object, thread_id, thread_type, "✅")

            else:
                self._styled_reply(name, "❌ API trả về dữ liệu không xác định.",
                                    message_object, thread_id, thread_type)
                self._react(message_object, thread_id, thread_type, "❓")

        except requests.exceptions.Timeout:
            print("⏰ Timeout khi gọi API buff like")
            self._styled_reply(name, "⏰ Hết thời gian chờ phản hồi từ API, vui lòng thử lại.",
                                message_object, thread_id, thread_type)
            self._react(message_object, thread_id, thread_type, "⏰")

        except requests.exceptions.ConnectionError:
            print("🔌 Lỗi kết nối đến API server")
            self._styled_reply(name, "🔌 Không thể kết nối đến API, vui lòng thử lại sau.",
                                message_object, thread_id, thread_type)
            self._react(message_object, thread_id, thread_type, "🔌")

        except requests.exceptions.HTTPError as e:
            print(f"🌐 Lỗi HTTP: {e}")
            self._styled_reply(name, "🌐 Lỗi HTTP khi gọi API.",
                                message_object, thread_id, thread_type)
            self._react(message_object, thread_id, thread_type, "🌐")

        except requests.exceptions.RequestException as e:
            print(f"🚫 Lỗi request: {e}")
            self._styled_reply(name, "🚫 Lỗi khi gửi request đến API.",
                                message_object, thread_id, thread_type)
            self._react(message_object, thread_id, thread_type, "🚫")

        except ValueError as e:
            print(f"📊 Lỗi parse JSON: {e}")
            self._styled_reply(name, "📊 Lỗi xử lý dữ liệu trả về từ API.",
                                message_object, thread_id, thread_type)
            self._react(message_object, thread_id, thread_type, "📊")

        except Exception as e:
            print(f"💥 Lỗi không xác định: {e}")
            self._styled_reply(name, "💥 Đã có lỗi không xác định xảy ra.",
                                message_object, thread_id, thread_type)
            self._react(message_object, thread_id, thread_type, "💥")
