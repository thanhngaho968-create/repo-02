"""
runners/media_processor_submodules/video_handlers.py - Single Video & Playlist Handlers
"""

import html
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict
from runners import gdrive_helper, gsheet_helper, telegram_helper
from . import error_classifier
from .parser import (
    OWNER_EMAIL,
    RUNNER_REPO,
    clean_filename,
    get_ytdlp_cmd,
)
from .playlist_handlers import handle_channel, handle_playlist

logger = logging.getLogger(__name__)


def _get_media_info(url: str):
    mp = sys.modules.get("runners.media_processor")
    if mp and hasattr(mp, "get_media_info"):
        return mp.get_media_info(url)
    return error_classifier.get_media_info(url)


def _classify_error(err: str):
    mp = sys.modules.get("runners.media_processor")
    if mp and hasattr(mp, "classify_media_error"):
        return mp.classify_media_error(err)
    return error_classifier.classify_media_error(err)


def handle_single_video(task: Dict[str, Any], temp_dir: str) -> bool:
    url = task["url"]
    chat_id, thread_id, status_msg_id = task.get("chat_id"), task.get("thread_id"), task.get("status_msg_id")
    sheet_row, folder_id = task.get("sheet_row"), task.get("drive_folder_id", "")

    logger.info(f"🎬 Processing single video: {url}")
    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"⚡ <b>[Cloud Runner: {RUNNER_REPO}] Đang phân tích video...</b>\n🔗 <code>{html.escape(url)}</code>")

    info, err = _get_media_info(url)
    if err:
        status_label = _classify_error(err)
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status=status_label, progress="Lỗi trích xuất thông tin")
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, f"❌ <b>LỖI TẢI VIDEO ({RUNNER_REPO}):</b>\n<code>{html.escape(err[:200])}</code>\nTrạng thái: <code>{status_label}</code>")
        return False

    title = clean_filename((info and info.get("title")) or task.get("title") or f"Video_{int(time.time())}")
    uploader = (info and (info.get("uploader") or info.get("channel"))) or ""

    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, title=title, progress="10% (Đang tải MP4 & MP3)")
    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"📥 <b>[Cloud Runner: {RUNNER_REPO}] Đang tải video & xuất MP3:</b>\n🎬 <b>Tiêu đề:</b> <code>{html.escape(title)}</code>\n📊 <b>Tiến độ:</b> <code>10% (Tải MP4 & MP3...)</code>")

    v_path, a_path = os.path.join(temp_dir, f"{title}.mp4"), os.path.join(temp_dir, f"{title}.mp3")
    cmd_v = get_ytdlp_cmd() + [
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", v_path,
        url
    ]
    proc_v = subprocess.run(cmd_v, capture_output=True, text=True)

    if not os.path.exists(v_path) or os.path.getsize(v_path) == 0:
        err_v = proc_v.stderr or "yt-dlp failed to download MP4"
        status_label = _classify_error(err_v)
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status=status_label, progress=err_v[:50])
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, f"❌ <b>Lỗi tải MP4:</b> <code>{html.escape(err_v[:150])}</code>")
        return False

    cmd_a = get_ytdlp_cmd() + ["-x", "--audio-format", "mp3", "--audio-quality", "0", "-o", a_path, url]
    subprocess.run(cmd_a, capture_output=True)

    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"☁️ <b>[Cloud Runner: {RUNNER_REPO}] Đang tải lên Google Drive (5TB OAuth2)...</b>\n🎬 <b>Tiêu đề:</b> <code>{html.escape(title)}</code>\n📊 <b>Tiến độ:</b> <code>70% (Đang upload...)</code>")

    v_link = gdrive_helper.upload_file_to_drive(v_path, f"{title}.mp4", folder_id, mime_type="video/mp4", owner_email=OWNER_EMAIL)
    a_link = gdrive_helper.upload_file_to_drive(a_path, f"{title}.mp3", folder_id, mime_type="audio/mpeg", owner_email=OWNER_EMAIL) if os.path.exists(a_path) and os.path.getsize(a_path) > 0 else None
    primary_link = v_link or a_link or f"https://drive.google.com/drive/folders/{folder_id}"

    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, status="Completed", progress="100%", title=title, drive_link=primary_link)

    if chat_id:
        final_msg = f"🎉 <b>ĐÃ HOÀN THÀNH TẢI VIDEO!</b>\n━━━━━━━━━━━━━━━━━━━━━━\n🎬 <b>Tiêu đề:</b> <code>{html.escape(title)}</code>\n👤 <b>Kênh:</b> <code>{html.escape(uploader)}</code>\n⚙️ <b>Thực thi bởi:</b> <code>{html.escape(RUNNER_REPO)}</code>\n📁 <b>Google Drive MP4:</b> <a href=\"{v_link}\">Mở Video MP4</a>\n"
        if a_link:
            final_msg += f"🎵 <b>Google Drive MP3:</b> <a href=\"{a_link}\">Mở Audio MP3</a>\n"
        if status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, final_msg)
        else:
            telegram_helper.send_message(chat_id, final_msg, thread_id=thread_id)

    logger.info(f"✅ Completed single video task: {title}")
    return True
