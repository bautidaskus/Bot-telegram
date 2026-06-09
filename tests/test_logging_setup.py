from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.config import Settings
from src.logging_setup import configure_logging


def _settings() -> Settings:
    return Settings(
        telegram_bot_token="super-secret-token",
        allowed_chat_id=1,
        groq_api_key="groq-secret-key",
    )


def test_logging_writes_to_rotated_file_and_masks_secrets(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "tracker.log"
    try:
        configure_logging(_settings(), log_path=log_path)
        logger.info("token={} y key={}", "super-secret-token", "groq-secret-key")
    finally:
        logger.remove()

    contents = log_path.read_text(encoding="utf-8")
    assert "super-secret-token" not in contents
    assert "groq-secret-key" not in contents
    assert "***" in contents
