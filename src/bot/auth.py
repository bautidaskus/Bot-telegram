"""Autorización single-user del bot."""

from __future__ import annotations

from typing import Any

from loguru import logger


def is_authorized(update: Any, allowed_chat_id: int) -> bool:
    """Valida el chat efectivo y registra intentos no autorizados."""

    chat = update.effective_chat
    authorized = chat is not None and chat.id == allowed_chat_id
    if not authorized and chat is not None:
        logger.warning("chat_id no autorizado: {}", chat.id)
    return authorized
