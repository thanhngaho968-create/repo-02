"""
runners/media_processor_submodules/pinterest_handlers.py - Pinterest Media Downloader & Uploader
"""

import html
import logging
import os
import re
import subprocess
import time
from typing import Any, Dict
import requests
from runners import gdrive_helper, gsheet_helper, telegram_helper
from .parser import (
    OWNER_EMAIL,
    PINTEREST_FOLDER_ID,
    RUNNER_REPO,
    get_ytdlp_cmd,
)

logger = logging.getLogger(__name__)


def handle_pinterest(task: Dict[str, Any], temp_dir: str) -> bool:
    url = task["url"]
    chat_id = task["chat_id"]
    thread_id = task["thread_id"]
    status_msg_id = task["status_msg_id"]
    sheet_row = task["sheet_row"]
    folder_id = task["drive_folder_id"] or PINTEREST_FOLDER_ID

    title = f"Pinterest_{int(time.time())}"
    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, title=title, progress="20% (Đang tải Pinterest)")
    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"📌 <b>[Cloud Runner: {RUNNER_REPO}] Đang tải Pinterest...</b>\n🔗 <code>{html.escape(url)}</code>")

    out_tmpl = os.path.join(temp_dir, f"{title}_%(id)s.%(ext)s")
    subprocess.run(get_ytdlp_cmd() + ["-o", out_tmpl, "--no-playlist", url], capture_output=True)

    downloaded = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.startswith(title) and os.path.getsize(os.path.join(temp_dir, f)) > 1024]
    if not downloaded:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(url, headers=headers, timeout=15)
            og_v = re.search(r'<meta property="og:video" content="([^"]+)"', r.text)
            og_i = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
            if og_v:
                v_f = os.path.join(temp_dir, f"{title}.mp4")
                r_v = requests.get(og_v.group(1), headers=headers, timeout=30)
                if r_v.status_code == 200:
                    with open(v_f, "wb") as f:
                        f.write(r_v.content)
                    downloaded.append(v_f)
            elif og_i:
                orig_url = re.sub(r'/\d+x/', '/originals/', og_i.group(1))
                r_i = requests.get(orig_url, headers=headers, timeout=30)
                if r_i.status_code == 200:
                    i_f = os.path.join(temp_dir, f"{title}.jpg")
                    with open(i_f, "wb") as f:
                        f.write(r_i.content)
                    downloaded.append(i_f)
        except Exception as pe:
            logger.warning(f"Pinterest scraper fallback error: {pe}")

    if not downloaded:
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status="Error (Pinterest Download Failed)", progress="Không tìm thấy media Pinterest")
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, f"❌ <b>Không thể tải Pinterest.</b>")
        return False

    uploaded_links = [gdrive_helper.upload_file_to_drive(f_p, os.path.basename(f_p), folder_id, owner_email=OWNER_EMAIL) for f_p in downloaded]
    if chat_id:
        caption = f"📌 <b>Pinterest Media:</b>\n🔗 <a href=\"{url}\">Xem Link Gốc</a>"
        for f in downloaded:
            if f.endswith((".mp4", ".mkv", ".mov")):
                telegram_helper.send_video(chat_id, f, caption=caption, thread_id=thread_id)
            else:
                telegram_helper.send_photo(chat_id, f, caption=caption, thread_id=thread_id)

    primary_link = uploaded_links[0] if uploaded_links else f"https://drive.google.com/drive/folders/{folder_id}"
    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, status="Completed", progress="100%", title=title, drive_link=primary_link)
    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"🎉 <b>ĐÃ HOÀN THÀNH TẢI PINTEREST!</b>\n📁 <b>Google Drive:</b> <a href=\"{primary_link}\">Mở File</a>")
    return True
