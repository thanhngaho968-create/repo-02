"""
Google Drive API v3 Helper Module for Repo-02.
Supports User OAuth2 (5TB Google One quota attribution for hothihuong113@gmail.com),
Service Account fallback, Exponential Backoff on 429/5xx errors,
and Chunked Resumable Uploads with per-chunk retry and progress tracking.
"""

import os
import io
import sys
import json
import time
import random
import base64
import logging
from typing import Tuple, Optional, Dict, Any

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build, Resource
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_OWNER_EMAIL = "hothihuong113@gmail.com"
DEFAULT_DRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "1AD83FFKXHHc-0NGK4boRv1jCcbUCRJn7")
SCOPES = ["https://www.googleapis.com/auth/drive"]

_drive_service: Optional[Resource] = None


def retry_on_transient_error(func, *args, max_retries: int = 5, backoff_factor: float = 2.0, **kwargs):
    """
    Executes a callable and retries with exponential backoff on HTTP 429 (Rate Limit),
    HTTP 5xx (500, 502, 503, 504), socket/SSL timeouts, and network connection drops.
    """
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err_msg = str(e)
            is_transient = False

            if isinstance(e, HttpError):
                status_code = e.resp.status if hasattr(e, "resp") and hasattr(e.resp, "status") else 0
                if status_code in (429, 500, 502, 503, 504):
                    is_transient = True
            else:
                lower_err = err_msg.lower()
                if any(k in lower_err for k in ["429", "quota", "ratelimit", "503", "502", "500", "504", "timed out", "timeout", "connection reset", "broken pipe"]):
                    is_transient = True

            if is_transient and attempt < max_retries - 1:
                sleep_time = (backoff_factor ** attempt) + random.uniform(1.0, 3.0)
                logger.warning(
                    f"⚠️ [GDrive Transient Error] {err_msg[:120]}... "
                    f"Retrying in {sleep_time:.2f}s (Attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(sleep_time)
            else:
                logger.error(f"❌ [GDrive Error] Unrecoverable exception after {attempt + 1} attempts: {err_msg}")
                raise


def get_drive_service() -> Resource:
    """
    Initializes and returns an authenticated Google Drive v3 service instance.
    Authentication Priority:
      1. GDRIVE_OAUTH_BASE64 environment variable (User OAuth2 -> 5TB quota)
      2. Local user_oauth2.json file
      3. GDRIVE_SA_BASE64 / GDRIVE_SA_JSON environment variable (Service Account)
      4. Local service_account.json file
    """
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    # 1. Primary Method: User OAuth2 (5TB Google One Storage Quota)
    oauth_info = None
    oauth_b64 = os.environ.get("GDRIVE_OAUTH_BASE64", "").strip()
    if oauth_b64:
        try:
            missing_padding = len(oauth_b64) % 4
            if missing_padding:
                oauth_b64 += "=" * (4 - missing_padding)
            oauth_info = json.loads(base64.b64decode(oauth_b64.encode("utf-8")).decode("utf-8"))
        except Exception as e:
            logger.warning(f"Failed to decode GDRIVE_OAUTH_BASE64: {e}")

    if not oauth_info:
        for path in ["user_oauth2.json", "/media/vpsg16gb/HaRiDisk/Telegram_Command_Center/user_oauth2.json"]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        oauth_info = json.load(f)
                    break
                except Exception:
                    pass

    if oauth_info and oauth_info.get("refresh_token"):
        try:
            logger.info("🔑 Authenticating Google Drive with User OAuth2 (5.0 TB Storage Quota)...")
            creds = Credentials(
                token=None,
                refresh_token=oauth_info["refresh_token"],
                token_uri=oauth_info.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=oauth_info["client_id"],
                client_secret=oauth_info["client_secret"],
                scopes=oauth_info.get("scopes", SCOPES),
            )
            creds.refresh(Request())
            _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
            return _drive_service
        except Exception as oe:
            logger.warning(f"OAuth2 authentication build failed ({oe}), falling back to Service Account...")

    # 2. Secondary Fallback: Service Account
    sa_info = None
    sa_b64 = os.environ.get("GDRIVE_SA_BASE64", "").strip()
    if sa_b64:
        try:
            missing_padding = len(sa_b64) % 4
            if missing_padding:
                sa_b64 += "=" * (4 - missing_padding)
            sa_info = json.loads(base64.b64decode(sa_b64.encode("utf-8")).decode("utf-8"))
        except Exception as e:
            logger.warning(f"Failed to decode GDRIVE_SA_BASE64: {e}")

    if not sa_info:
        sa_raw = os.environ.get("GDRIVE_SA_JSON", "").strip()
        if sa_raw:
            try:
                sa_info = json.loads(sa_raw)
            except Exception as e:
                logger.warning(f"Failed to parse GDRIVE_SA_JSON: {e}")

    if not sa_info:
        for path in ["service_account.json", "/media/vpsg16gb/HaRiDisk/Telegram_Command_Center/service_account.json"]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        sa_info = json.load(f)
                    break
                except Exception as e:
                    logger.warning(f"Failed to load {path}: {e}")

    if not sa_info:
        raise ValueError("Missing Google Drive credentials: both GDRIVE_OAUTH_BASE64 and GDRIVE_SA_BASE64 are unavailable.")

    logger.info("🔑 Authenticating Google Drive with Service Account...")
    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _drive_service


def get_or_create_folder(folder_name: str, parent_id: Optional[str] = None, owner_email: Optional[str] = DEFAULT_OWNER_EMAIL) -> Tuple[str, str]:
    """
    Finds existing folder by name under parent_id, or creates a new folder.
    Returns (folder_id, folder_url).
    """
    service = get_drive_service()
    safe_name = folder_name.replace("'", "\\'")

    def _find():
        if parent_id:
            query = f"name = '{safe_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        else:
            query = f"name = '{safe_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"

        res = service.files().list(
            q=query,
            fields="files(id, name, webViewLink)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageSize=1
        ).execute()
        files = res.get("files", [])
        if files:
            f_id = files[0]["id"]
            f_url = files[0].get("webViewLink", f"https://drive.google.com/drive/folders/{f_id}")
            return f_id, f_url
        return None

    existing = retry_on_transient_error(_find)
    if existing:
        return existing

    def _create():
        meta = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            meta["parents"] = [parent_id]

        folder = service.files().create(body=meta, fields="id, webViewLink", supportsAllDrives=True).execute()
        f_id = folder["id"]
        f_url = folder.get("webViewLink", f"https://drive.google.com/drive/folders/{f_id}")

        if owner_email:
            try:
                service.permissions().create(
                    fileId=f_id,
                    body={"type": "user", "role": "writer", "emailAddress": owner_email},
                    sendNotificationEmail=False,
                    supportsAllDrives=True,
                ).execute()
            except Exception as pe:
                logger.debug(f"Permission grant notice: {pe}")

        logger.info(f"📁 Created Google Drive Folder '{folder_name}' (ID: {f_id})")
        return f_id, f_url

    return retry_on_transient_error(_create)


def upload_file_to_drive(
    local_path: str,
    file_name: str,
    parent_folder_id: Optional[str] = None,
    mime_type: str = "video/mp4",
    owner_email: Optional[str] = DEFAULT_OWNER_EMAIL,
    chunk_size_mb: int = 10,
) -> str:
    """
    Uploads a local file to Google Drive using Chunked Resumable Upload with per-chunk
    exponential backoff retry and real-time progress reporting.
    
    Returns webViewLink (str).
    """
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Local file not found: {local_path}")

    file_size = os.path.getsize(local_path)
    target_folder = parent_folder_id or DEFAULT_DRIVE_FOLDER_ID
    service = get_drive_service()

    file_metadata: Dict[str, Any] = {"name": file_name}
    if target_folder:
        file_metadata["parents"] = [target_folder]

    # Chunksize must be a multiple of 256 KB (262144 bytes)
    chunk_bytes = max(256 * 1024, chunk_size_mb * 1024 * 1024)
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True, chunksize=chunk_bytes)

    logger.info(f"☁️ Initializing chunked resumable upload: '{file_name}' ({file_size / (1024*1024):.2f} MB, chunk={chunk_size_mb}MB)...")

    request = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink, webContentLink, size",
        supportsAllDrives=True,
    )

    response = None
    last_logged_progress = -1

    while response is None:
        def _upload_chunk():
            return request.next_chunk()

        status, response = retry_on_transient_error(_upload_chunk, max_retries=6, backoff_factor=2.0)

        if status:
            progress_pct = int(status.progress() * 100)
            if progress_pct >= last_logged_progress + 10 or progress_pct == 100:
                mb_done = status.resumable_progress / (1024 * 1024)
                mb_total = status.total_size / (1024 * 1024) if status.total_size else (file_size / (1024 * 1024))
                logger.info(f"📤 [Upload Progress] '{file_name}': {progress_pct}% ({mb_done:.1f} MB / {mb_total:.1f} MB)")
                last_logged_progress = progress_pct

    file_id = response.get("id")
    web_link = response.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
    logger.info(f"✅ Upload Complete: '{file_name}' -> ID: {file_id}")

    # Ensure permissions if owner_email is specified
    if owner_email:
        try:
            service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": "writer", "emailAddress": owner_email},
                sendNotificationEmail=False,
                supportsAllDrives=True,
            ).execute()
        except Exception as pe:
            logger.debug(f"Permission grant notice: {pe}")

    return web_link


def verify_file_exists(file_id: str, min_bytes: int = 1024) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Directly queries Google Drive API to verify file existence, valid size, and untrashed status.
    Returns (is_valid: bool, file_obj: dict, message: str).
    """
    service = get_drive_service()

    def _query():
        return service.files().get(
            fileId=file_id,
            fields="id, name, size, trashed, webViewLink, parents, owners",
            supportsAllDrives=True,
        ).execute()

    try:
        file_obj = retry_on_transient_error(_query)
        if not file_obj:
            return False, None, "File object returned empty"
        if file_obj.get("trashed"):
            return False, file_obj, "File is in trash"
        size = int(file_obj.get("size", 0))
        if size < min_bytes:
            return False, file_obj, f"File size too small ({size} bytes < {min_bytes} bytes)"
        return True, file_obj, "File verified successfully"
    except Exception as e:
        return False, None, f"API Exception: {e}"


def get_quota_info() -> Dict[str, Any]:
    """
    Retrieves storage quota details for the authenticated user/service.
    """
    service = get_drive_service()
    def _run():
        return service.about().get(fields="user, storageQuota").execute()
    return retry_on_transient_error(_run)


if __name__ == "__main__":
    print("🧪 Running GDrive Helper Self-Diagnostics...")
    try:
        quota_data = get_quota_info()
        user = quota_data.get("user", {})
        quota = quota_data.get("storageQuota", {})
        limit_tb = int(quota.get("limit", 0)) / (1024**4)
        usage_gb = int(quota.get("usage", 0)) / (1024**3)

        print(f"✅ Authenticated User : {user.get('displayName')} ({user.get('emailAddress')})")
        print(f"📊 Storage Quota     : {usage_gb:.2f} GB used / {limit_tb:.2f} TB total")

        # Test folder resolution
        f_id, f_url = get_or_create_folder("01.Torrent")
        print(f"📁 Target Folder      : {f_id} -> {f_url}")
        print("🎉 GDrive Helper is production-ready!")
    except Exception as ex:
        print(f"❌ Diagnostics failed: {ex}")
        sys.exit(1)
