"""
runners/telegram_submodules/client.py - Telegram Client & Cloudflare Edge Relay
"""

import json
import logging
import os
import time
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger(__name__)

NWL_FORBIDDEN_PREFIX = "8944836049"

CF_RELAY_URL = os.environ.get("CF_RELAY_URL", "https://telegram-command-edge.hari-edge.workers.dev").strip()
CF_RELAY_SECRET = os.environ.get("CF_RELAY_SECRET", "HaRiSecret_2026_SecureRelay").strip()

RAW_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not RAW_BOT_TOKEN:
    try:
        import vault_config
        RAW_BOT_TOKEN = vault_config.get_telegram_config().get("bot_token", "").strip()
    except Exception:
        RAW_BOT_TOKEN = ""

_clean_tok = RAW_BOT_TOKEN
if _clean_tok.lower().startswith("bot"):
    _clean_tok = _clean_tok[3:].strip()

if _clean_tok.startswith(NWL_FORBIDDEN_PREFIX) or (NWL_FORBIDDEN_PREFIX in _clean_tok):
    logger.warning("🚨 [ANTI CROSS-CONTAMINATION] Blocked NWL token in TelegramHelper!")
    BOT_TOKEN = ""
else:
    BOT_TOKEN = _clean_tok


def make_tg_request(method: str, data: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Any]] = None, max_retries: int = 5, timeout: int = 120) -> Dict[str, Any]:
    """Executes Telegram API request via Cloudflare Relay with Direct API fallback."""
    for attempt in range(1, max_retries + 1):
        if CF_RELAY_URL:
            base_relay = CF_RELAY_URL.rstrip("/")
            url = f"{base_relay}/relay/{method}"
            headers = {"X-Relay-Secret": CF_RELAY_SECRET} if CF_RELAY_SECRET else {}
            try:
                res = requests.post(url, headers=headers, data=data, files=files, timeout=timeout)
                try:
                    res_json = res.json()
                    if res_json.get("ok"):
                        return res_json
                    if res_json.get("error_code") == 429:
                        retry_after = res_json.get("parameters", {}).get("retry_after", 5)
                        logger.warning(f"Telegram 429 Rate Limit. Sleeping {retry_after + 2}s...")
                        time.sleep(retry_after + 2)
                        continue
                    if res_json.get("error_code") == 400:
                        return res_json
                except Exception:
                    if res.status_code == 200:
                        return {"ok": True}
            except Exception as e:
                logger.warning(f"[Relay Attempt {attempt}/{max_retries}] Connection Error: {e}")

        if BOT_TOKEN:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
            try:
                res = requests.post(url, data=data, files=files, timeout=timeout)
                try:
                    res_json = res.json()
                    if res_json.get("ok"):
                        return res_json
                    if res_json.get("error_code") == 429:
                        retry_after = res_json.get("parameters", {}).get("retry_after", 5)
                        logger.warning(f"Direct TG 429 Rate Limit. Sleeping {retry_after + 2}s...")
                        time.sleep(retry_after + 2)
                        continue
                    if res_json.get("error_code") == 400:
                        return res_json
                except Exception:
                    if res.status_code == 200:
                        return {"ok": True}
            except Exception as e:
                logger.warning(f"[Direct TG Attempt {attempt}/{max_retries}] Connection Error: {e}")

        if attempt < max_retries:
            time.sleep(attempt * 2)

    return {"ok": False, "error": f"Failed {method} after {max_retries} attempts"}
