"""Autorización single-user del bot."""

from __future__ import annotations

from typing import Any

from loguru import logger


def is_authorized(update: Any, allowed_chat_id: int | None) -> bool:
    """Valida el chat efectivo y registra intentos no autorizados."""

    chat = update.effective_chat
    authorized = allowed_chat_id is not None and chat is not None and chat.id == allowed_chat_id
    if not authorized and chat is not None:
        logger.warning("chat_id no autorizado: {}. Agregalo a ALLOWED_CHAT_ID si sos vos.", chat.id)
    return authorized
