"""Configuración de logging con rotación de archivo y secretos enmascarados."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from src.config import Settings

_MASK = "***"


def _mask_secrets(record: dict, secrets: list[str]) -> None:
    message = record["message"]
    for secret in secrets:
        if secret and secret in message:
            message = message.replace(secret, _MASK)
    record["message"] = message


def configure_logging(settings: Settings, *, log_path: Path = Path("logs/tracker.log")) -> None:
    """Enruta loguru a consola y archivo rotado, ocultando los secretos."""

    secrets = [
        settings.telegram_bot_token.get_secret_value(),
        settings.groq_api_key.get_secret_value(),
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.configure(patcher=lambda record: _mask_secrets(record, secrets))
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(
        log_path,
        level=settings.log_level,
        rotation="5 MB",
        retention="30 days",
        encoding="utf-8",
    )
