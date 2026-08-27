#!/usr/bin/env python3
"""
runners/media_processor.py - Unified Media Processing Engine for Cloud Runners
"""

import logging
import os
import shutil
import sys
from runners.media_processor_submodules.parser import (
    DEFAULT_DRIVE_FOLDER_ID,
    DEFAULT_YOUTUBE_FOLDER_ID,
    TIKTOK_FOLDER_ID,
    FACEBOOK_FOLDER_ID,
    INSTAGRAM_FOLDER_ID,
    PINTEREST_FOLDER_ID,
    FB_IG_FOLDER_ID,
    OWNER_EMAIL,
    RUNNER_REPO,
    clean_filename,
    format_bytes,
    get_ytdlp_cmd,
    parse_task_payload,
)
from runners.media_processor_submodules.error_classifier import (
    check_for_auth_block,
    classify_media_error,
    get_media_info,
)
from runners.media_processor_submodules.video_handlers import (
    handle_single_video,
    handle_playlist,
    handle_channel,
)
from runners.media_processor_submodules.social_handlers import (
    handle_tiktok,
    handle_fb_insta,
    handle_pinterest,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [MediaProcessor] %(message)s")

__all__ = [
    "DEFAULT_DRIVE_FOLDER_ID",
    "DEFAULT_YOUTUBE_FOLDER_ID",
    "TIKTOK_FOLDER_ID",
    "FACEBOOK_FOLDER_ID",
    "INSTAGRAM_FOLDER_ID",
    "PINTEREST_FOLDER_ID",
    "FB_IG_FOLDER_ID",
    "OWNER_EMAIL",
    "RUNNER_REPO",
    "clean_filename",
    "format_bytes",
    "get_ytdlp_cmd",
    "parse_task_payload",
    "check_for_auth_block",
    "classify_media_error",
    "get_media_info",
    "handle_single_video",
    "handle_playlist",
    "handle_channel",
    "handle_tiktok",
    "handle_fb_insta",
    "handle_pinterest",
    "main",
]


def main():
    logger.info("🚀 Media Processor Cloud Runner initialized.")
    task = parse_task_payload()
    logger.info(f"Task Config: id={task['task_id']}, cmd={task['cmd']}, type={task['media_type']}, url={task['url']}")

    if not task["url"]:
        logger.error("❌ No URL provided in task payload!")
        sys.exit(1)

    temp_dir = os.path.join(os.getcwd(), f"temp_{task['task_id']}")
    os.makedirs(temp_dir, exist_ok=True)

    success = False
    try:
        cmd = task["cmd"]
        m_type = task["media_type"]
        url_l = task["url"].lower()

        if m_type == "pinterest" or "pinterest.com" in url_l or "pin.it" in url_l:
            success = handle_pinterest(task, temp_dir)
        elif cmd == "/wf4" or m_type == "tiktok" or "tiktok.com" in url_l:
            success = handle_tiktok(task, temp_dir)
        elif cmd == "/wf6" or m_type in ["fb_insta", "facebook", "instagram"] or any(d in url_l for d in ["facebook.com", "fb.watch", "instagram.com"]):
            success = handle_fb_insta(task, temp_dir)
        elif cmd == "/wf1" or m_type == "channel":
            success = handle_channel(task, temp_dir)
        elif cmd == "/wf2" or m_type == "playlist":
            success = handle_playlist(task, temp_dir)
        elif cmd == "/wf3" or m_type == "single":
            success = handle_single_video(task, temp_dir)
        else:
            logger.warning(f"Unrecognized command {cmd}, defaulting to single video...")
            success = handle_single_video(task, temp_dir)
    except Exception as e:
        logger.error(f"💥 Unhandled exception in media processor: {e}", exc_info=True)
        try:
            from runners import gsheet_helper
            if task.get("sheet_row"):
                gsheet_helper.update_media_task_status(task["sheet_row"], status=f"Error ({str(e)[:40]})", progress="Lỗi thực thi Cloud Runner")
        except Exception:
            pass
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    logger.info(f"🏁 Media Processor completed with status={'SUCCESS' if success else 'FAILED'}")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
