"""
runners/media_processor_submodules/error_classifier.py - Error Detection & Metadata Probing
"""

import json
import logging
import subprocess
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse
from .parser import get_ytdlp_cmd

logger = logging.getLogger(__name__)


def check_for_auth_block(error_str: str) -> Optional[str]:
    """Detects authentication, login, bot-detection, rate-limiting, or cookie barriers."""
    err_lower = (error_str or "").lower()
    if any(k in err_lower for k in [
        "sign in to confirm your age", "confirm your age", "age-restricted", "age restricted"
    ]):
        return "Need Auth/Cookie (Age-Restricted Video)"
    if any(k in err_lower for k in [
        "members-only", "join this channel", "members only",
        "this video is available to this channel's members", "available to channel's members", "available to channel members",
        "available to this channel's members"
    ]):
        return "Need Auth/Cookie (Members-Only Video)"
    if any(k in err_lower for k in [
        "private video", "this video is private", "login required", "requires authentication",
        "sign in if you've been granted access", "sign in if you have been granted access"
    ]):
        return "Need Auth/Cookie (Private Video)"
    if any(k in err_lower for k in [
        "bot detection", "sign in to confirm you're not a bot", "sign in to confirm you are not a bot", "captcha",
        "confirm you're not a bot", "confirm you are not a bot"
    ]):
        return "Need Auth/Cookie (Bot Detection Block)"
    if any(k in err_lower for k in [
        "http error 429", "http 429", "429: too many requests", "429 too many requests", "too many requests"
    ]):
        return "Need Auth/Cookie (HTTP 429 Too Many Requests)"
    if any(k in err_lower for k in [
        "--cookies-from-browser", "--cookies", "cookie", "cookies"
    ]):
        return "Need Auth/Cookie (Cookie Required)"
    if "http error 403" in err_lower or "403 forbidden" in err_lower or "http 403" in err_lower:
        return "Need Auth/Cookie (HTTP 403 Forbidden)"
    return None


def classify_media_error(error_str: str) -> str:
    """Classifies error strings into standardized labels."""
    if not error_str:
        return "Error (Unknown Failure)"
    if error_str.startswith("Error (") or error_str.startswith("Need Auth/Cookie"):
        return error_str

    auth_label = check_for_auth_block(error_str)
    if auth_label:
        return auth_label

    err_lower = error_str.lower()
    if any(k in err_lower for k in [
        "video unavailable", "unavailable video", "video is unavailable", "is unavailable", "unavailable"
    ]):
        return "Error (Video Unavailable)"
    if any(k in err_lower for k in [
        "this video has been removed", "video has been removed", "has been removed", "removed by the user"
    ]):
        return "Error (Video Removed)"
    if any(k in err_lower for k in [
        "copyright", "dmca", "copyright claim", "copyright infringement"
    ]):
        return "Error (Copyright / DMCA)"
    if any(k in err_lower for k in [
        "invalid url", "unsupported url", "is not a valid url", "invalid url format", "not a valid url"
    ]):
        return "Error (Invalid URL Format)"

    clean_err = error_str.strip()
    if clean_err.startswith("ERROR:"):
        clean_err = clean_err[6:].strip()
    if len(clean_err) > 40:
        clean_err = clean_err[:40] + "..."
    return f"Error ({clean_err})"


def get_media_info(url: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Inspects media info JSON without downloading."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, "Error (Invalid URL Format)"

    cmd = get_ytdlp_cmd() + ["--dump-json", "--flat-playlist", url]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or "Unknown error fetching media info"
        auth_err = check_for_auth_block(err_msg)
        if auth_err:
            return None, auth_err
        return None, classify_media_error(err_msg)

    lines = [l.strip() for l in proc.stdout.strip().split("\n") if l.strip()]
    if not lines:
        return None, "Error (Empty metadata response)"

    try:
        if len(lines) == 1:
            return json.loads(lines[0]), None
        else:
            return {"entries": [json.loads(l) for l in lines]}, None
    except Exception as e:
        return None, str(e)
