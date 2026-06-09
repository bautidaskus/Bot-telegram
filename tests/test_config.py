from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings


def test_settings_load_required_values_and_defaults(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=test-token\nALLOWED_CHAT_ID=123456\nGROQ_API_KEY=test-key\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.telegram_bot_token.get_secret_value() == "test-token"
    assert settings.allowed_chat_id == 123456
    assert settings.groq_api_key.get_secret_value() == "test-key"
    assert settings.timezone == "America/Argentina/Buenos_Aires"
    assert settings.default_currency == "ARS"
    assert settings.db_path == Path("data/tracker.db")


def test_settings_reject_missing_required_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)
