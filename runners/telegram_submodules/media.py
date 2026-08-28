"""
runners/telegram_submodules/media.py - Telegram Photo, Video & Media Group Delivery
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional
import requests
from . import client


def _make_req(*args, **kwargs):
    th = sys.modules.get("runners.telegram_helper")
    if th and hasattr(th, "make_tg_request"):
        return th.make_tg_request(*args, **kwargs)
    return client.make_tg_request(*args, **kwargs)


def send_photo(chat_id: str, photo_path_or_url: str, caption: str = "", reply_to_message_id: Optional[int] = None, thread_id: Optional[int] = None) -> Dict[str, Any]:
    data = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"}
    if reply_to_message_id: data["reply_to_message_id"] = reply_to_message_id
    if thread_id: data["message_thread_id"] = thread_id

    if isinstance(photo_path_or_url, str) and (photo_path_or_url.startswith("http://") or photo_path_or_url.startswith("https://")):
        data["photo"] = photo_path_or_url
        res = _make_req("sendPhoto", data=data)
        if res.get("ok"): return res
        try:
            r_img = requests.get(photo_path_or_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            if r_img.status_code == 200:
                files = {"photo": ("cover.jpg", r_img.content, "image/jpeg")}
                data_clean = {k: v for k, v in data.items() if k != "photo"}
                return _make_req("sendPhoto", data=data_clean, files=files)
        except Exception: pass
        return res
    elif os.path.exists(photo_path_or_url):
        with open(photo_path_or_url, "rb") as f:
            files = {"photo": (os.path.basename(photo_path_or_url), f, "image/jpeg")}
            return _make_req("sendPhoto", data=data, files=files)
    return {"ok": False, "error": "Invalid photo path or URL"}


def send_video(
    chat_id: str, video_path: str, caption: str = "", thumb_path: Optional[str] = None,
    duration: int = 0, width: int = 0, height: int = 0,
    reply_to_message_id: Optional[int] = None, thread_id: Optional[int] = None,
    supports_streaming: bool = True
) -> Dict[str, Any]:
    if not os.path.exists(video_path) or os.path.getsize(video_path) == 0:
        return {"ok": False, "error": f"Video missing or empty: {video_path}"}
    data = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML", "supports_streaming": "true" if supports_streaming else "false"}
    if reply_to_message_id: data["reply_to_message_id"] = reply_to_message_id
    if thread_id: data["message_thread_id"] = thread_id
    if duration > 0: data["duration"] = int(duration)
    if width > 0 and height > 0: data["width"], data["height"] = int(width), int(height)

    opened = []
    try:
        vf = open(video_path, "rb")
        opened.append(vf)
        files = {"video": (os.path.basename(video_path), vf, "video/mp4")}
        if thumb_path and os.path.exists(thumb_path):
            tf = open(thumb_path, "rb")
            opened.append(tf)
            files["thumbnail"] = (os.path.basename(thumb_path), tf, "image/jpeg")
        return _make_req("sendVideo", data=data, files=files, timeout=300)
    finally:
        for f in opened:
            try: f.close()
            except Exception: pass


def send_media_group(chat_id: str, media_paths: List[str], caption: str = "", reply_to_message_id: Optional[int] = None, thread_id: Optional[int] = None) -> Dict[str, Any]:
    if not media_paths: return {"ok": False, "error": "No media paths provided"}
    media_list, files, opened = [], {}, []
    try:
        for idx, path in enumerate(media_paths[:10]):
            ext = os.path.splitext(path)[1].lower()
            file_key = f"file_{idx}"
            f = open(path, "rb")
            opened.append(f)
            files[file_key] = f
            m_type = "video" if ext in [".mp4", ".mkv", ".mov"] else "photo"
            item = {"type": m_type, "media": f"attach://{file_key}"}
            if idx == 0 and caption: item["caption"], item["parse_mode"] = caption, "HTML"
            media_list.append(item)
        data = {"chat_id": str(chat_id), "media": json.dumps(media_list)}
        if reply_to_message_id: data["reply_to_message_id"] = reply_to_message_id
        if thread_id: data["message_thread_id"] = thread_id
        return _make_req("sendMediaGroup", data=data, files=files, timeout=300)
    finally:
        for f in opened:
            try: f.close()
            except Exception: pass
