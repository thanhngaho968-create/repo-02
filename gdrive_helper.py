import os
import io
import json
import base64
import time
import random
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_OWNER_EMAIL = "hothihuong113@gmail.com"
DEFAULT_DRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "1AD83FFKXHHc-0NGK4boRv1jCcbUCRJn7")
SCOPES = ["https://www.googleapis.com/auth/drive"]

_drive_service = None

def retry_on_429(func, *args, max_retries=5, backoff_factor=2, **kwargs):
    """
    Executes a function and retries with exponential backoff if a 429/quota error occurs.
    """
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err_msg = str(e)
            is_transient = False
            
            if "429" in err_msg or "quota" in err_msg.lower() or "limit" in err_msg.lower() or "ratelimit" in err_msg.lower():
                is_transient = True
            if hasattr(e, 'resp') and getattr(e.resp, 'status', None) in [429, 500, 502, 503, 504]:
                is_transient = True
            elif hasattr(e, 'response') and getattr(e.response, 'status_code', None) in [429, 500, 502, 503, 504]:
                is_transient = True

            if is_transient and attempt < max_retries - 1:
                sleep_time = (backoff_factor ** attempt) + random.uniform(1.0, 3.0)
                logger.warning(
                    f"⚠️ Google API transient/quota error: {err_msg[:100]}. "
                    f"Retrying in {sleep_time:.2f}s... (Attempt {attempt+1}/{max_retries})"
                )
                time.sleep(sleep_time)
            else:
                raise

def get_drive_service():
    """
    Initializes and returns an authenticated Google Drive v3 service.
    Supports GDRIVE_SA_BASE64 env var, GDRIVE_SA_JSON env var, or local service_account.json.
    """
    global _drive_service
    if _drive_service is not None:
        return _drive_service

    # 1. Primary: User OAuth2 (Consumes from personal 5TB quota, no storageQuotaExceeded error)
    oauth_info = None
    oauth_b64 = os.environ.get("GDRIVE_OAUTH_BASE64", "").strip()
    if oauth_b64:
        try:
            missing_padding = len(oauth_b64) % 4
            if missing_padding:
                oauth_b64 += '=' * (4 - missing_padding)
            oauth_info = json.loads(base64.b64decode(oauth_b64).decode("utf-8"))
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
            from google.oauth2.credentials import Credentials
            logger.info("🔑 Authenticating Google Drive with User OAuth2 (5TB Direct Storage)...")
            creds = Credentials(
                None,
                refresh_token=oauth_info["refresh_token"],
                token_uri=oauth_info.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=oauth_info["client_id"],
                client_secret=oauth_info["client_secret"],
                scopes=oauth_info.get("scopes", SCOPES)
            )
            _drive_service = build("drive", "v3", credentials=creds)
            return _drive_service
        except Exception as oe:
            logger.warning(f"OAuth2 credentials build failed, falling back to Service Account: {oe}")

    # 2. Secondary Fallback: Service Account
    sa_info = None
    sa_b64 = os.environ.get("GDRIVE_SA_BASE64", "").strip()
    if sa_b64:
        try:
            missing_padding = len(sa_b64) % 4
            if missing_padding:
                sa_b64 += '=' * (4 - missing_padding)
            sa_json = base64.b64decode(sa_b64).decode("utf-8")
            sa_info = json.loads(sa_json)
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
        raise ValueError("Missing Google Drive credentials (GDRIVE_OAUTH_BASE64 or GDRIVE_SA_BASE64)")

    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=SCOPES
    )
    _drive_service = build("drive", "v3", credentials=creds)
    return _drive_service

def upload_file_to_drive(local_path, file_name, parent_folder_id=None, mime_type="video/mp4", owner_email=DEFAULT_OWNER_EMAIL):
    """
    Uploads a local file to Google Drive (with resumable multi-MB chunks) and grants permissions.
    Strictly checks and prevents duplicate uploads in the target folder.
    Returns direct webViewLink (str).
    """
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Local file not found: {local_path}")

    target_folder = parent_folder_id or DEFAULT_DRIVE_FOLDER_ID
    service = get_drive_service()

    def _run():
        # DEDUPLICATION CHECK: Check if file with same name already exists
        escaped_name = file_name.replace("'", "\\'")
        q = f"'{target_folder}' in parents and name = '{escaped_name}' and trashed = false"
        res = service.files().list(
            q=q,
            fields="files(id, name, webViewLink, size, trashed)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        existing_files = res.get("files", [])
        if existing_files:
            valid_files = [f for f in existing_files if int(f.get("size", 0)) > 1024 * 100]
            if valid_files:
                primary = valid_files[0]
                logger.info(f"⚡ [DEDUPLICATION SHIELD] File '{file_name}' already exists on GDrive (ID: {primary['id']}). Skipping upload!")
                # Trash redundant duplicate copies if any
                if len(valid_files) > 1:
                    for extra in valid_files[1:]:
                        try:
                            service.files().update(fileId=extra["id"], body={"trashed": True}, supportsAllDrives=True).execute()
                            logger.info(f"🗑️ Cleaned duplicate copy {extra['id']}")
                        except Exception:
                            pass
                return primary.get("webViewLink") or f"https://drive.google.com/file/d/{primary['id']}/view"

        meta = {
            "name": file_name
        }
        if target_folder:
            meta["parents"] = [target_folder]

        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True, chunksize=10*1024*1024)
        file_obj = service.files().create(
            body=meta,
            media_body=media,
            fields="id, name, webViewLink, webContentLink",
            supportsAllDrives=True
        ).execute()

        file_id = file_obj["id"]
        logger.info(f"✅ Uploaded '{file_name}' to GDrive (ID: {file_id})")

        # Share / grant writer permissions
        target_email = owner_email or DEFAULT_OWNER_EMAIL
        if target_email:
            try:
                service.permissions().create(
                    fileId=file_id,
                    body={"type": "user", "role": "writer", "emailAddress": target_email},
                    sendNotificationEmail=False,
                    supportsAllDrives=True
                ).execute()
                logger.info(f"Granted writer access for '{file_name}' to {target_email}")
            except Exception as pe:
                logger.warning(f"Failed granting permissions to {target_email}: {pe}")

        return file_obj.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"

    return retry_on_429(_run)
