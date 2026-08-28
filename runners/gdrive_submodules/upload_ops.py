"""
runners/gdrive_submodules/upload_ops.py - Google Drive Resumable Upload Operations
"""

import logging
import os
import sys
from typing import Optional
from googleapiclient.http import MediaFileUpload
from . import auth

logger = logging.getLogger(__name__)


def _get_service():
    gh = sys.modules.get("runners.gdrive_helper")
    if gh and hasattr(gh, "get_drive_service"):
        return gh.get_drive_service()
    return auth.get_drive_service()


def upload_file_to_drive(
    local_path: str,
    file_name: str,
    parent_folder_id: Optional[str] = None,
    mime_type: Optional[str] = None,
    owner_email: str = auth.DEFAULT_OWNER_EMAIL
) -> str:
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Local file not found: {local_path}")

    target_folder = parent_folder_id or auth.DEFAULT_DRIVE_FOLDER_ID
    service = _get_service()

    if not mime_type:
        ext = os.path.splitext(file_name)[1].lower()
        mime_map = {
            ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"
        }
        mime_type = mime_map.get(ext, "application/octet-stream")

    def _run():
        nonlocal service
        escaped_name = file_name.replace("'", "\\'")
        q = f"'{target_folder}' in parents and name = '{escaped_name}' and trashed = false"
        try:
            res = service.files().list(
                q=q, fields="files(id, name, webViewLink, size, trashed)",
                supportsAllDrives=True, includeItemsFromAllDrives=True
            ).execute()
        except Exception:
            service = _get_service()
            res = service.files().list(
                q=q, fields="files(id, name, webViewLink, size, trashed)",
                supportsAllDrives=True, includeItemsFromAllDrives=True
            ).execute()

        existing_files = res.get("files", [])
        if existing_files:
            valid_files = [f for f in existing_files if int(f.get("size", 0)) > 1024 * 50]
            if valid_files:
                primary = valid_files[0]
                logger.info(f"⚡ [DEDUPLICATION SHIELD] File '{file_name}' already exists on GDrive (ID: {primary['id']}). Skipping upload!")
                return primary.get("webViewLink") or f"https://drive.google.com/file/d/{primary['id']}/view"

        meta = {"name": file_name}
        if target_folder:
            meta["parents"] = [target_folder]

        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True, chunksize=10 * 1024 * 1024)
        file_obj = service.files().create(body=meta, media_body=media, fields="id, name, webViewLink", supportsAllDrives=True).execute()

        file_id = file_obj["id"]
        logger.info(f"✅ Uploaded '{file_name}' to GDrive (ID: {file_id})")

        target_email = owner_email or auth.DEFAULT_OWNER_EMAIL
        if target_email:
            try:
                service.permissions().create(
                    fileId=file_id,
                    body={"type": "user", "role": "writer", "emailAddress": target_email},
                    sendNotificationEmail=False,
                    supportsAllDrives=True
                ).execute()
            except Exception as pe:
                logger.warning(f"Permission grant warning for '{file_name}': {pe}")

        return file_obj.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"

    return auth.retry_on_429(_run)
