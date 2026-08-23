import os
import time
import requests
import json
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CF_RELAY_URL = os.environ.get("CF_RELAY_URL", "").strip()
CF_RELAY_SECRET = os.environ.get("CF_RELAY_SECRET", "").strip()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

def make_tg_request(method, data=None, files=None, max_retries=5, timeout=300):
    """
    Sends request to Telegram API via Cloudflare Relay worker or direct Bot API with automatic retries.
    """
    for attempt in range(1, max_retries + 1):
        # 1. Try Cloudflare Relay Worker if configured
        if CF_RELAY_URL:
            url = f"{CF_RELAY_URL.rstrip('/')}/relay/{method}"
            headers = {"X-Relay-Secret": CF_RELAY_SECRET} if CF_RELAY_SECRET else {}
            try:
                # Note: if files are passed, requests will send multipart/form-data
                res = requests.post(url, headers=headers, data=data, files=files, timeout=timeout)
                if res.status_code == 200:
                    try:
                        return res.json()
                    except Exception:
                        pass
                logger.warning(f"[Relay] Status {res.status_code} on {method}: {res.text[:200]}")
            except Exception as e:
                logger.warning(f"[Relay Attempt {attempt}/{max_retries}] Exception on {method}: {e}")

        # 2. Direct Telegram API fallback
        if BOT_TOKEN:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
            try:
                res = requests.post(url, data=data, files=files, timeout=timeout)
                try:
                    res_json = res.json()
                    if res_json.get("ok"):
                        return res_json
                    # Handle 429 Too Many Requests
                    if res_json.get("error_code") == 429:
                        retry_after = res_json.get("parameters", {}).get("retry_after", 5)
                        logger.warning(f"Telegram Rate Limit (429). Sleeping {retry_after}s...")
                        time.sleep(retry_after)
                        continue
                    logger.warning(f"[Direct TG Attempt {attempt}/{max_retries}] API Error on {method}: {res_json}")
                except Exception:
                    logger.warning(f"[Direct TG Attempt {attempt}/{max_retries}] Non-JSON Response: {res.text[:200]}")
            except Exception as e:
                logger.warning(f"[Direct TG Attempt {attempt}/{max_retries}] Exception on {method}: {e}")

        if attempt < max_retries:
            time.sleep(3 * attempt)

    return {"ok": False, "error": f"Failed {method} after {max_retries} attempts"}

def send_message(chat_id, text, parse_mode="HTML", reply_to_message_id=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id
    return make_tg_request("sendMessage", data=data)

def send_photo(chat_id, photo_path_or_url, caption="", reply_to_message_id=None):
    data = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id

    if isinstance(photo_path_or_url, str) and (photo_path_or_url.startswith("http://" ) or photo_path_or_url.startswith("https://")):
        data["photo"] = photo_path_or_url
        return make_tg_request("sendPhoto", data=data)
    elif os.path.exists(photo_path_or_url):
        f = open(photo_path_or_url, "rb")
        try:
            files = {"photo": (os.path.basename(photo_path_or_url), f, "image/jpeg")}
            return make_tg_request("sendPhoto", data=data, files=files)
        finally:
            f.close()
    return {"ok": False, "error": "Invalid photo path or URL"}

def send_video(chat_id, video_path, caption="", thumb_path=None, duration=0, width=0, height=0, reply_to_message_id=None, supports_streaming=True):
    if not os.path.exists(video_path):
        return {"ok": False, "error": f"Video file not found: {video_path}"}

    data = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "HTML",
        "supports_streaming": "true" if supports_streaming else "false"
    }
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id
    if duration and duration > 0:
        data["duration"] = int(duration)
    if width and height and width > 0 and height > 0:
        data["width"] = int(width)
        data["height"] = int(height)

    opened_files = []
    try:
        vf = open(video_path, "rb")
        opened_files.append(vf)
        files = {
            "video": (os.path.basename(video_path), vf, "video/mp4")
        }
        if thumb_path and os.path.exists(thumb_path):
            tf = open(thumb_path, "rb")
            opened_files.append(tf)
            files["thumbnail"] = ("thumb.jpg", tf, "image/jpeg")
            files["thumb"] = ("thumb.jpg", tf, "image/jpeg")

        return make_tg_request("sendVideo", data=data, files=files)
    finally:
        for f in opened_files:
            try:
                f.close()
            except Exception:
                pass

def send_document(chat_id, doc_path, caption="", thumb_path=None, reply_to_message_id=None):
    if not os.path.exists(doc_path):
        return {"ok": False, "error": f"Document file not found: {doc_path}"}

    data = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "HTML"
    }
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id

    opened_files = []
    try:
        df = open(doc_path, "rb")
        opened_files.append(df)
        files = {"document": (os.path.basename(doc_path), df, "application/octet-stream")}
        if thumb_path and os.path.exists(thumb_path):
            tf = open(thumb_path, "rb")
            opened_files.append(tf)
            files["thumbnail"] = ("thumb.jpg", tf, "image/jpeg")

        return make_tg_request("sendDocument", data=data, files=files)
    finally:
        for f in opened_files:
            try:
                f.close()
            except Exception:
                pass

def send_audio(chat_id, audio_path, caption="", title="", performer="", thumb_path=None, duration=0, reply_to_message_id=None):
    if not os.path.exists(audio_path):
        return {"ok": False, "error": f"Audio file not found: {audio_path}"}

    data = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "HTML",
        "title": title,
        "performer": performer
    }
    if reply_to_message_id:
        data["reply_to_message_id"] = reply_to_message_id
    if duration and duration > 0:
        data["duration"] = int(duration)

    opened_files = []
    try:
        af = open(audio_path, "rb")
        opened_files.append(af)
        files = {"audio": (os.path.basename(audio_path), af, "audio/mpeg")}
        if thumb_path and os.path.exists(thumb_path):
            tf = open(thumb_path, "rb")
            opened_files.append(tf)
            files["thumbnail"] = ("thumb.jpg", tf, "image/jpeg")

        return make_tg_request("sendAudio", data=data, files=files)
    finally:
        for f in opened_files:
            try:
                f.close()
            except Exception:
                pass
