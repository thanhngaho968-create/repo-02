"""
runners/telegram_helper.py - Telegram Bot API Helper for Cloud Runners
"""

import logging
from runners.telegram_submodules.client import (
    DEFAULT_CC_TOKEN,
    NWL_FORBIDDEN_PREFIX,
    CF_RELAY_URL,
    CF_RELAY_SECRET,
    BOT_TOKEN,
    make_tg_request,
)
from runners.telegram_submodules.messages import (
    send_message,
    edit_message,
    send_document,
)
from runners.telegram_submodules.media import (
    send_photo,
    send_video,
    send_media_group,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CC_TOKEN",
    "NWL_FORBIDDEN_PREFIX",
    "CF_RELAY_URL",
    "CF_RELAY_SECRET",
    "BOT_TOKEN",
    "make_tg_request",
    "send_message",
    "edit_message",
    "send_document",
    "send_photo",
    "send_video",
    "send_media_group",
]
