"""
runners/media_processor_submodules/social_handlers.py - TikTok & Facebook/Instagram Handlers
"""

import html
import logging
import os
import re
import subprocess
import time
from typing import Any, Dict
from urllib.parse import urlparse
import requests
from runners import gdrive_helper, gsheet_helper, telegram_helper
from .parser import (
    FB_IG_FOLDER_ID,
    OWNER_EMAIL,
    RUNNER_REPO,
    get_ytdlp_cmd,
)
from .pinterest_handlers import handle_pinterest

logger = logging.getLogger(__name__)


def handle_tiktok(task: Dict[str, Any], temp_dir: str) -> bool:
    url = task.get("url", "")
    chat_id = task.get("chat_id")
    thread_id = task.get("thread_id")
    status_msg_id = task.get("status_msg_id")
    sheet_row = task.get("sheet_row")
    folder_id = task.get("drive_folder_id", "")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status="Error (Invalid URL Format)", progress="Invalid URL format")
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, "❌ <b>Lỗi tải TikTok:</b> <code>Invalid URL format</code>")
        return False

    title = f"TikTok_{int(time.time())}"
    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, title=title, progress="20% (Đang tải TikTok)")
    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"📥 <b>[Cloud Runner: {RUNNER_REPO}] Đang tải TikTok...</b>\n🔗 <code>{html.escape(url)}</code>")

    v_path, a_path = os.path.join(temp_dir, f"{title}.mp4"), os.path.join(temp_dir, f"{title}.mp3")
    subprocess.run(get_ytdlp_cmd() + ["-o", v_path, url], capture_output=True)
    subprocess.run(get_ytdlp_cmd() + ["-x", "--audio-format", "mp3", "-o", a_path, url], capture_output=True)

    if not os.path.exists(v_path) or os.path.getsize(v_path) == 0:
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status="Error (TikTok Download Failed)", progress="Lỗi tải TikTok")
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, "❌ <b>Không thể tải TikTok. Vui lòng kiểm tra link.</b>")
        return False

    v_link = gdrive_helper.upload_file_to_drive(v_path, f"{title}.mp4", folder_id, mime_type="video/mp4", owner_email=OWNER_EMAIL)
    if os.path.exists(a_path) and os.path.getsize(a_path) > 1024:
        gdrive_helper.upload_file_to_drive(a_path, f"{title}.mp3", folder_id, mime_type="audio/mpeg", owner_email=OWNER_EMAIL)

    if chat_id:
        telegram_helper.send_video(chat_id, v_path, caption=f"📱 <b>TikTok Video:</b>\n🔗 <a href=\"{url}\">Xem Link Gốc</a>\n📁 <a href=\"{v_link}\">Google Drive</a>", thread_id=thread_id)

    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, status="Completed", progress="100%", title=title, drive_link=v_link)
    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"🎉 <b>ĐÃ HOÀN THÀNH TẢI TIKTOK!</b>\n📁 <b>Google Drive:</b> <a href=\"{v_link}\">Mở File MP4</a>")
    return True


def handle_fb_insta(task: Dict[str, Any], temp_dir: str) -> bool:
    url = task.get("url", "")
    chat_id, thread_id, status_msg_id = task.get("chat_id"), task.get("thread_id"), task.get("status_msg_id")
    sheet_row, folder_id = task.get("sheet_row"), FB_IG_FOLDER_ID or task.get("drive_folder_id", "")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status="Error (Invalid URL Format)", progress="Invalid URL format")
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, "❌ <b>Lỗi tải media:</b> <code>Invalid URL format</code>")
        return False

    platform = "Facebook" if "facebook" in url.lower() or "fb." in url.lower() else "Instagram"
    title = f"{platform}_{int(time.time())}"
    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, title=title, progress=f"20% (Đang phân tích {platform})")
    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"🔎 <b>[Cloud Runner: {RUNNER_REPO}] Đang tải {platform}...</b>\n🔗 <code>{html.escape(url)}</code>")

    out_tmpl = os.path.join(temp_dir, f"{title}_%(id)s.%(ext)s")
    subprocess.run(get_ytdlp_cmd() + ["-o", out_tmpl, "--no-playlist", url], capture_output=True)

    downloaded = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.startswith(title) and os.path.getsize(os.path.join(temp_dir, f)) > 0]
    if not downloaded:
        try:
            r = requests.get(url, headers={"User-Agent": "facebookexternalhit/1.1"}, timeout=15)
            og_v = re.search(r'<meta property="og:video" content="([^"]+)"', r.text)
            og_i = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
            if og_v:
                v_f = os.path.join(temp_dir, f"{title}.mp4")
                r_v = requests.get(og_v.group(1).replace("&amp;", "&"), timeout=30)
                if r_v.status_code == 200:
                    with open(v_f, "wb") as f:
                        f.write(r_v.content)
                    downloaded.append(v_f)
            elif og_i:
                i_f = os.path.join(temp_dir, f"{title}.jpg")
                r_i = requests.get(og_i.group(1).replace("&amp;", "&"), timeout=30)
                if r_i.status_code == 200:
                    with open(i_f, "wb") as f:
                        f.write(r_i.content)
                    downloaded.append(i_f)
        except Exception:
            pass

    if not downloaded:
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status=f"Error ({platform} Download Failed)", progress="Không tìm thấy media")
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, f"❌ <b>Không thể tải media {platform}.</b>")
        return False

    uploaded_links = [gdrive_helper.upload_file_to_drive(f_p, os.path.basename(f_p), folder_id, owner_email=OWNER_EMAIL) for f_p in downloaded]
    if chat_id:
        videos = [f for f in downloaded if f.endswith((".mp4", ".mkv", ".mov"))]
        photos = [f for f in downloaded if f.endswith((".jpg", ".jpeg", ".png", ".webp"))]
        caption = f"🎬 <b>{platform} Media:</b>\n🔗 <a href=\"{url}\">Xem Link Gốc</a>"
        for v in videos:
            telegram_helper.send_video(chat_id, v, caption=caption, thread_id=thread_id)
        if len(photos) == 1:
            telegram_helper.send_photo(chat_id, photos[0], caption=caption, thread_id=thread_id)
        elif len(photos) > 1:
            telegram_helper.send_media_group(chat_id, photos, caption=caption, thread_id=thread_id)

    primary_link = uploaded_links[0] if uploaded_links else f"https://drive.google.com/drive/folders/{folder_id}"
    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, status="Completed", progress="100%", title=title, drive_link=primary_link)
    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"🎉 <b>ĐÃ HOÀN THÀNH TẢI {platform.upper()}!</b>\n📁 <b>Google Drive:</b> <a href=\"{primary_link}\">Mở Drive</a>")
    return True
