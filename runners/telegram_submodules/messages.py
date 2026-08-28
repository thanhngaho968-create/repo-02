"""
runners/telegram_submodules/messages.py - Telegram Text & Document Messages
"""

import os
import sys
from typing import Any, Dict, Optional
from . import client


def _make_req(*args, **kwargs):
    th = sys.modules.get("runners.telegram_helper")
    if th and hasattr(th, "make_tg_request"):
        return th.make_tg_request(*args, **kwargs)
    return client.make_tg_request(*args, **kwargs)


def send_message(chat_id: str, text: str, parse_mode: str = "HTML", reply_to_message_id: Optional[int] = None, thread_id: Optional[int] = None) -> Dict[str, Any]:
    data = {"chat_id": str(chat_id), "text": text, "parse_mode": parse_mode}
    if reply_to_message_id: data["reply_to_message_id"] = reply_to_message_id
    if thread_id: data["message_thread_id"] = thread_id

    res = _make_req("sendMessage", data=data)
    if not res.get("ok") and parse_mode:
        data.pop("parse_mode", None)
        return _make_req("sendMessage", data=data)
    return res


def edit_message(chat_id: str, message_id: int, text: str, parse_mode: str = "HTML") -> Dict[str, Any]:
    data = {"chat_id": str(chat_id), "message_id": message_id, "text": text, "parse_mode": parse_mode}
    res = _make_req("editMessageText", data=data)
    if not res.get("ok") and parse_mode:
        data.pop("parse_mode", None)
        return _make_req("editMessageText", data=data)
    return res


def send_document(chat_id: str, document_path: str, caption: str = "", reply_to_message_id: Optional[int] = None, thread_id: Optional[int] = None) -> Dict[str, Any]:
    if not os.path.exists(document_path) or os.path.getsize(document_path) == 0:
        return {"ok": False, "error": f"Document missing or empty: {document_path}"}
    data = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"}
    if reply_to_message_id: data["reply_to_message_id"] = reply_to_message_id
    if thread_id: data["message_thread_id"] = thread_id
    with open(document_path, "rb") as df:
        files = {"document": (os.path.basename(document_path), df, "application/octet-stream")}
        return _make_req("sendDocument", data=data, files=files, timeout=300)
