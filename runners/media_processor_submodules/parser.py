"""
runners/media_processor_submodules/parser.py - Payload & String Utilities
"""

import base64
import json
import logging
import os
import re
import shutil
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

DEFAULT_DRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "1kQGnr2q4rXJ3hUKZvocFLMdpsoDBp2m4")
DEFAULT_YOUTUBE_FOLDER_ID = "12vTx3-0p3hqenmwjIv2ACWcZh9ArOnQC"
TIKTOK_FOLDER_ID = "1uWtFeNQcXeOEFIn8zGO0c6rBRZrJg__r"
FACEBOOK_FOLDER_ID = "11xqKBlkpu2WXJxZeKSWfIHOwIhX5tUkv"
INSTAGRAM_FOLDER_ID = "1GUDJdrUOmP7LuFK274vqmToQr2GAONc2"
PINTEREST_FOLDER_ID = "1GUDJdrUOmP7LuFK274vqmToQr2GAONc2"
FB_IG_FOLDER_ID = "1GUDJdrUOmP7LuFK274vqmToQr2GAONc2"
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "hothihuong113@gmail.com")
RUNNER_REPO = os.environ.get("RUNNER_REPO") or os.environ.get("GITHUB_REPOSITORY") or "Cloud Runner"


def clean_filename(name: str) -> str:
    """Sanitizes strings for safe filenames."""
    if not name:
        return "media_file"
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return cleaned[:100] if len(cleaned) > 100 else cleaned


def format_bytes(size: int) -> str:
    """Formats raw bytes into human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def get_ytdlp_cmd() -> List[str]:
    """Constructs robust yt-dlp command line options with modern bypass and multi-threading."""
    ytdlp_bin = os.path.expanduser("~/.local/bin/yt-dlp")
    if not os.path.exists(ytdlp_bin):
        ytdlp_bin = "yt-dlp"

    base = [
        ytdlp_bin,
        "--no-check-certificates",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "--extractor-args", "youtube:player_client=android,web,mweb,ios,tv_embedded;player_skip=configs,webpage",
        "--retries", "5",
        "--fragment-retries", "10",
        "--file-access-retries", "5",
        "--no-warnings"
    ]
    if shutil.which("aria2c"):
        base.extend(["--downloader", "aria2c", "--downloader-args", "aria2c:-s 8 -x 8 -k 1M --max-connection-per-server=8"])
    if os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 0:
        base.extend(["--cookies", "cookies.txt"])
    return base


def parse_task_payload() -> Dict[str, Any]:
    """Parses task payload from environment variables or JSON."""
    raw_payload = os.environ.get("TASK_PAYLOAD", "").strip()
    payload = {}
    if raw_payload:
        try:
            payload = json.loads(raw_payload)
        except Exception:
            try:
                b64_data = raw_payload
                missing_padding = len(b64_data) % 4
                if missing_padding:
                    b64_data += '=' * (4 - missing_padding)
                decoded = base64.b64decode(b64_data).decode("utf-8")
                payload = json.loads(decoded)
            except Exception as e:
                logger.warning(f"Could not parse TASK_PAYLOAD: {e}")

    task_id = payload.get("task_id") or os.environ.get("TASK_ID", f"task_media_{int(time.time())}")
    cmd = payload.get("cmd") or os.environ.get("CMD", "/wf3")
    media_type = payload.get("media_type") or os.environ.get("MEDIA_TYPE", "single")
    url = payload.get("url") or os.environ.get("URL", "")
    title = payload.get("title") or os.environ.get("TITLE", "")
    chat_id = payload.get("chat_id") or os.environ.get("CHAT_ID", "")
    thread_id = payload.get("thread_id") or os.environ.get("THREAD_ID")
    status_msg_id = payload.get("status_msg_id") or os.environ.get("STATUS_MSG_ID")
    sheet_row = payload.get("sheet_row") or os.environ.get("SHEET_ROW")
    drive_folder_id = payload.get("drive_folder_id") or os.environ.get("DRIVE_FOLDER_ID") or DEFAULT_DRIVE_FOLDER_ID
    fmt = payload.get("format") or os.environ.get("FORMAT", "mp4+mp3")

    return {
        "task_id": task_id,
        "cmd": str(cmd).strip().lower(),
        "media_type": str(media_type).strip().lower(),
        "url": str(url).strip(),
        "title": str(title).strip(),
        "chat_id": str(chat_id).strip() if chat_id else "",
        "thread_id": int(thread_id) if thread_id else None,
        "status_msg_id": int(status_msg_id) if status_msg_id else None,
        "sheet_row": int(sheet_row) if sheet_row else None,
        "drive_folder_id": str(drive_folder_id).strip(),
        "format": str(fmt).strip()
    }
