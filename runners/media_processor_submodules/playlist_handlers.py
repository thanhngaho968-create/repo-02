"""
runners/media_processor_submodules/playlist_handlers.py - Playlist & Channel Handlers
"""

import html
import json
import logging
import os
import subprocess
from typing import Any, Dict
from urllib.parse import urlparse
from runners import gdrive_helper, gsheet_helper, telegram_helper
from .error_classifier import classify_media_error
from .parser import (
    OWNER_EMAIL,
    RUNNER_REPO,
    clean_filename,
    get_ytdlp_cmd,
)

logger = logging.getLogger(__name__)


def handle_playlist(task: Dict[str, Any], temp_dir: str) -> bool:
    url = task["url"]
    chat_id, thread_id, status_msg_id = task["chat_id"], task["thread_id"], task["status_msg_id"]
    sheet_row, parent_folder_id = task["sheet_row"], task["drive_folder_id"]

    logger.info(f"📋 Processing playlist: {url}")
    if chat_id and status_msg_id:
        telegram_helper.edit_message(chat_id, status_msg_id, f"⚡ <b>[Cloud Runner: {RUNNER_REPO}] Đang quét danh sách phát...</b>\n🔗 <code>{html.escape(url)}</code>")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status="Error (Invalid URL Format)", progress="Invalid URL format")
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, "❌ <b>Lỗi quét Playlist:</b> <code>Invalid URL format</code>")
        return False

    cmd = get_ytdlp_cmd() + ["--flat-playlist", "-J", url]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = proc.stderr.strip()
        status_label = classify_media_error(err)
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status=status_label, progress=err[:40])
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, f"❌ <b>Lỗi quét Playlist:</b> <code>{html.escape(err[:150])}</code>")
        return False

    pl_data = json.loads(proc.stdout)
    pl_title = clean_filename(pl_data.get("title") or "YouTube_Playlist")
    entries = pl_data.get("entries", [])
    total_count = len(entries)

    if total_count == 0:
        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, status="Completed", progress="0/0 (Playlist rỗng)", title=pl_title)
        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, "⚠️ <b>Playlist rỗng hoặc không có video công khai.</b>")
        return True

    subfolder_name = f"Playlist - {pl_title}"
    subfolder_id, subfolder_link = gdrive_helper.create_drive_folder(subfolder_name, parent_folder_id, owner_email=OWNER_EMAIL)

    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, title=pl_title, status=f"In Progress ({RUNNER_REPO})", progress=f"[0/{total_count}] 0%", drive_link=subfolder_link)

    completed_videos, failed_videos = [], []

    for idx, entry in enumerate(entries, start=1):
        v_id = entry.get("id")
        v_url = entry.get("url") or (f"https://www.youtube.com/watch?v={v_id}" if v_id else "")
        v_raw_title = entry.get("title") or f"Tập {idx}"
        v_title = f"{idx:02d} - {clean_filename(v_raw_title)}"
        pct = int((idx - 1) / total_count * 100)
        progress_str = f"[{idx}/{total_count}] {pct}%"

        if sheet_row:
            gsheet_helper.update_media_task_status(sheet_row, progress=f"{progress_str} - Đang tải tập {idx}")

        if chat_id and status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, f"📥 <b>[Cloud Runner: {RUNNER_REPO}] Đang xử lý Playlist ({progress_str}):</b>\n📋 <b>Playlist:</b> <code>{html.escape(pl_title)}</code>\n🎬 <b>Tập {idx}/{total_count}:</b> <code>{html.escape(v_title)}</code>\n📁 <b>Thư mục Drive:</b> <a href=\"{subfolder_link}\">Mở Thư Mục</a>")

        v_path, a_path = os.path.join(temp_dir, f"{v_title}.mp4"), os.path.join(temp_dir, f"{v_title}.mp3")
        try:
            cmd_v = get_ytdlp_cmd() + [
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "-o", v_path,
                v_url
            ]
            res_v = subprocess.run(cmd_v, capture_output=True, text=True)
            if not os.path.exists(v_path) or os.path.getsize(v_path) == 0:
                failed_videos.append((idx, v_raw_title, res_v.stderr[:60]))
                continue

            gdrive_helper.upload_file_to_drive(v_path, f"{v_title}.mp4", subfolder_id, mime_type="video/mp4", owner_email=OWNER_EMAIL)
            subprocess.run(get_ytdlp_cmd() + ["-x", "--audio-format", "mp3", "-o", a_path, v_url], capture_output=True)
            if os.path.exists(a_path) and os.path.getsize(a_path) > 1024:
                gdrive_helper.upload_file_to_drive(a_path, f"{v_title}.mp3", subfolder_id, mime_type="audio/mpeg", owner_email=OWNER_EMAIL)

            completed_videos.append(v_title)
        except Exception as ve:
            failed_videos.append((idx, v_raw_title, str(ve)[:60]))
        finally:
            for p in [v_path, a_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    final_status = "Completed" if not failed_videos else "Completed (With Warnings)"
    final_progress = f"{len(completed_videos)}/{total_count} (100%)"

    if sheet_row:
        gsheet_helper.update_media_task_status(sheet_row, status=final_status, progress=final_progress, title=pl_title, drive_link=subfolder_link)

    if chat_id:
        summary_msg = f"🎉 <b>ĐÃ HOÀN THÀNH PLAYLIST!</b>\n━━━━━━━━━━━━━━━━━━━━━━\n📋 <b>Playlist:</b> <code>{html.escape(pl_title)}</code>\n📊 <b>Kết quả:</b> <code>{len(completed_videos)}/{total_count} video thành công</code>\n⚙️ <b>Cloud Runner:</b> <code>{html.escape(RUNNER_REPO)}</code>\n📁 <b>Google Drive:</b> <a href=\"{subfolder_link}\">Mở Thư Mục Playlist</a>\n"
        if failed_videos:
            summary_msg += f"\n⚠️ <b>Video không tải được ({len(failed_videos)}):</b>\n"
            for f_idx, f_t, f_err in failed_videos[:5]:
                summary_msg += f"• #{f_idx}: {html.escape(f_t[:30])} (<code>{html.escape(f_err[:30])}</code>)\n"
        if status_msg_id:
            telegram_helper.edit_message(chat_id, status_msg_id, summary_msg)
        else:
            telegram_helper.send_message(chat_id, summary_msg, thread_id=thread_id)

    return True


def handle_channel(task: Dict[str, Any], temp_dir: str) -> bool:
    url = task["url"]
    if not any(url.endswith(x) for x in ["/videos", "/playlists", "/shorts", "/featured"]):
        tab_url = url.rstrip("/") + "/videos"
    else:
        tab_url = url
    task["url"] = tab_url
    return handle_playlist(task, temp_dir)
