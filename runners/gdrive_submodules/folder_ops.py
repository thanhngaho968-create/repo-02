"""
runners/gdrive_submodules/folder_ops.py - Google Drive Folder Find and Creation
"""

import logging
import sys
from typing import Optional, Tuple
from . import auth

logger = logging.getLogger(__name__)


def _get_service():
    gh = sys.modules.get("runners.gdrive_helper")
    if gh and hasattr(gh, "get_drive_service"):
        return gh.get_drive_service()
    return auth.get_drive_service()


def find_drive_folder(folder_name: str, parent_id: Optional[str] = None) -> Optional[Tuple[str, str]]:
    def _run():
        service = _get_service()
        safe_name = folder_name.replace("'", "\\'")
        query = f"mimeType='application/vnd.google-apps.folder' and name='{safe_name}' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        res = service.files().list(
            q=query, fields="files(id, name, webViewLink)", pageSize=1,
            supportsAllDrives=True, includeItemsFromAllDrives=True
        ).execute()
        files = res.get("files", [])
        if files:
            f_id = files[0]["id"]
            return f_id, files[0].get("webViewLink") or f"https://drive.google.com/drive/folders/{f_id}"
        return None

    return auth.retry_on_429(_run)


def create_drive_folder(folder_name: str, parent_id: Optional[str] = None, owner_email: str = auth.DEFAULT_OWNER_EMAIL) -> Tuple[str, str]:
    existing = find_drive_folder(folder_name, parent_id)
    if existing:
        logger.info(f"📁 Reusing existing Google Drive folder '{folder_name}' (ID: {existing[0]})")
        return existing

    def _run():
        service = _get_service()
        meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id: meta["parents"] = [parent_id]

        folder = service.files().create(body=meta, fields="id, name, webViewLink", supportsAllDrives=True).execute()
        folder_id = folder.get("id")
        folder_link = folder.get("webViewLink") or f"https://drive.google.com/drive/folders/{folder_id}"
        logger.info(f"📁 Created new Google Drive folder '{folder_name}' (ID: {folder_id})")

        target_email = owner_email or auth.DEFAULT_OWNER_EMAIL
        if target_email:
            try:
                service.permissions().create(
                    fileId=folder_id,
                    body={"type": "user", "role": "writer", "emailAddress": target_email},
                    sendNotificationEmail=False,
                    supportsAllDrives=True
                ).execute()
            except Exception as pe:
                logger.warning(f"Permission grant warning for folder '{folder_name}': {pe}")

        return folder_id, folder_link

    return auth.retry_on_429(_run)
