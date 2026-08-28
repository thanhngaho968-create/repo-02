"""
runners/gdrive_submodules/auth.py - Google Drive Authentication & 429 Retry Decorator
"""

import base64
import json
import logging
import os
import random
import sys
import time
from typing import Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
import vault_config

logger = logging.getLogger(__name__)

DEFAULT_OWNER_EMAIL = "hothihuong113@gmail.com"
DEFAULT_DRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "1kQGnr2q4rXJ3hUKZvocFLMdpsoDBp2m4")
SCOPES = ["https://www.googleapis.com/auth/drive"]

_drive_service = None


def retry_on_429(func, *args, max_retries=5, backoff_factor=2, **kwargs):
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err_msg = str(e)
            is_transient = any(k in err_msg.lower() for k in ["429", "quota", "limit", "ratelimit", "userate", "backenderror"])
            if hasattr(e, 'resp') and getattr(e.resp, 'status', None) in [429, 500, 502, 503, 504]:
                is_transient = True
            elif hasattr(e, 'response') and getattr(e.response, 'status_code', None) in [429, 500, 502, 503, 504]:
                is_transient = True

            if is_transient and attempt < max_retries - 1:
                sleep_time = (backoff_factor ** attempt) + random.uniform(1.0, 3.0)
                logger.warning(f"⚠️ Google API transient error: {err_msg[:120]}. Retrying in {sleep_time:.2f}s...")
                time.sleep(sleep_time)
            else:
                raise


def get_drive_service():
    global _drive_service
    gh = sys.modules.get("runners.gdrive_helper")
    builder = getattr(gh, "build", build)
    if gh and hasattr(gh, "_drive_service") and gh._drive_service is None:
        _drive_service = None
    if _drive_service is not None:
        return _drive_service

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
        paths = ["user_oauth2.json", "/media/vpsg16gb/HaRiDisk/Telegram_Command_Center/user_oauth2.json"]
        v_oauth = vault_config.get_google_user_oauth_path()
        if v_oauth: paths.insert(0, v_oauth)
        for path in paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        oauth_info = json.load(f)
                    break
                except Exception: pass

    if oauth_info and oauth_info.get("refresh_token"):
        try:
            from google.oauth2.credentials import Credentials
            import google.auth.transport.requests
            logger.info("🔑 Initializing Google Drive User OAuth2...")
            creds = Credentials(
                None, refresh_token=oauth_info["refresh_token"],
                token_uri=oauth_info.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=oauth_info["client_id"], client_secret=oauth_info["client_secret"],
                scopes=oauth_info.get("scopes", SCOPES)
            )
            req = google.auth.transport.requests.Request()
            creds.refresh(req)
            _drive_service = builder("drive", "v3", credentials=creds)
            if gh and hasattr(gh, "_drive_service"):
                gh._drive_service = _drive_service
            return _drive_service
        except Exception as oe:
            logger.warning(f"⚠️ User OAuth2 refresh failed ({oe}), falling back to Service Account...")

    sa_info = None
    sa_b64 = os.environ.get("GDRIVE_SA_BASE64", "").strip()
    if sa_b64:
        try:
            missing_padding = len(sa_b64) % 4
            if missing_padding: sa_b64 += '=' * (4 - missing_padding)
            sa_info = json.loads(base64.b64decode(sa_b64).decode("utf-8"))
        except Exception as e:
            logger.warning(f"Failed to decode GDRIVE_SA_BASE64: {e}")

    if not sa_info:
        paths = ["service_account.json", "/media/vpsg16gb/HaRiDisk/Telegram_Command_Center/service_account.json"]
        v_sa = vault_config.get_google_service_account_path()
        if v_sa: paths.insert(0, v_sa)
        for path in paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        sa_info = json.load(f)
                    break
                except Exception: pass

    if not sa_info:
        raise ValueError("Missing Google Drive credentials")

    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    _drive_service = builder("drive", "v3", credentials=creds)
    if gh and hasattr(gh, "_drive_service"):
        gh._drive_service = _drive_service
    return _drive_service
