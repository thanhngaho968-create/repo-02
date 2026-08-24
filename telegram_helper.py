import os
import time
import requests
import json
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# STRICT GATEKEEPER CONSTANTS
FORBIDDEN_CHANNEL_ID = os.environ.get("TARGET_CHANNEL_ID", "-1002244827586").strip()
DISCUSS_CHAT_ID = os.environ.get("DISCUSS_CHAT_ID", "-1002087114535").strip()

CF_RELAY_URL = os.environ.get("CF_RELAY_URL", "https://telegram-command-edge.hothihuong113.workers.dev").strip()
CF_RELAY_SECRET = os.environ.get("CF_RELAY_SECRET", "HaRiSecret_2026_SecureRelay").strip()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

def make_tg_request(method, data=None, files=None, max_retries=5, timeout=300):
    # GATEKEEPER 2: ZERO VIDEO FILES IN CHANNEL BARRIER
    if method == "sendVideo" or (files and ("video" in files or "thumbnail" in files)):
        if data and str(data.get("chat_id", "")).strip() == str(FORBIDDEN_CHANNEL_ID):
            logger.warning(f"🚨 [GATEKEEPER 2 INTERCEPTED] sendVideo to Channel ({FORBIDDEN_CHANNEL_ID}) blocked! Redirected to Discussion Supergroup ({DISCUSS_CHAT_ID}).")
            data["chat_id"] = DISCUSS_CHAT_ID

    for attempt in range(1, max_retries + 1):
        if CF_RELAY_URL:
            base_relay = CF_RELAY_URL.rstrip("/")
            url = f"{base_relay}/relay/{method}"
            headers = {"X-Relay-Secret": CF_RELAY_SECRET} if CF_RELAY_SECRET else {}
            try:
                res = requests.post(url, headers=headers, data=data, files=files, timeout=timeout)
                try:
                    res_json = res.json()
                    if res_json.get("ok"):
                        return res_json
                    
                    err_desc = res_json.get("description", "").lower()
                    if res_json.get("error_code") == 400 and ("message to be replied not found" in err_desc or "reply_to_message" in err_desc):
                        logger.error(f"❌ [GATEKEEPER 3] reply_to_message_id not found in {data.get('chat_id')}! Strictly refusing to dump unthreaded video into group root!")
                        return {"ok": False, "error": "message_to_be_replied_not_found"}

                    if res_json.get("error_code") == 429:
                        retry_after = res_json.get("parameters", {}).get("retry_after", 5)
                        logger.warning(f"Telegram Rate Limit (429). Sleeping {retry_after}s...")
                        time.sleep(retry_after)
                        continue

                    logger.warning(f"[Relay Attempt {attempt}/{max_retries}] API Error on {method}: {res_json}")
                except Exception:
                    if res.status_code == 200:
                        return {"ok": True}
                    logger.warning(f"[Relay Attempt {attempt}/{max_retries}] Non-JSON Response: {res.text[:200]}")
            except Exception as e:
                logger.warning(f"[Relay Attempt {attempt}/{max_retries}] Exception on {method}: {e}")

        if BOT_TOKEN:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
            try:
                res = requests.post(url, data=data, files=files, timeout=timeout)
                try:
                    res_json = res.json()
                    if res_json.get("ok"):
                        return res_json
                    
                    err_desc = res_json.get("description", "").lower()
                    if res_json.get("error_code") == 400 and ("message to be replied not found" in err_desc or "reply_to_message" in err_desc):
                        logger.error(f"❌ [GATEKEEPER 3] reply_to_message_id not found in {data.get('chat_id')}! Strictly refusing to dump unthreaded video into group root!")
                        return {"ok": False, "error": "message_to_be_replied_not_found"}

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

    if isinstance(photo_path_or_url, str) and (photo_path_or_url.startswith("http://") or photo_path_or_url.startswith("https://")):
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

    if str(chat_id).strip() == str(FORBIDDEN_CHANNEL_ID):
        logger.warning(f"🚨 [GATEKEEPER 2 BARRIER] Intercepted send_video to Channel! Forcing chat_id to {DISCUSS_CHAT_ID}")
        chat_id = DISCUSS_CHAT_ID

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
            files["thumbnail"] = (os.path.basename(thumb_path), tf, "image/jpeg")

        return make_tg_request("sendVideo", data=data, files=files)
    finally:
        for f in opened_files:
            try:
                f.close()
            except Exception:
                pass
