from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import Settings

CONFIG_ENV_VARS = (
    "TELEGRAM_BOT_TOKEN",
    "ALLOWED_CHAT_ID",
    "GROQ_API_KEY",
    "TIMEZONE",
    "DEFAULT_CURRENCY",
    "DB_PATH",
)


def clear_config_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in CONFIG_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)


def test_settings_load_required_values_and_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_config_environment(monkeypatch)
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


def test_settings_allow_empty_chat_id_for_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_config_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=test-token\nALLOWED_CHAT_ID=\nGROQ_API_KEY=test-key\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.allowed_chat_id is None


def test_settings_reject_missing_required_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_config_environment(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)


def test_env_example_contains_valid_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_environment(monkeypatch)

    settings = Settings(
        _env_file=Path(".env.example"),
        telegram_bot_token="test-token",
        allowed_chat_id=123456,
        groq_api_key="test-key",
    )

    assert settings.groq_llm_model == "llama-3.3-70b-versatile"
    assert settings.groq_whisper_model == "whisper-large-v3"
    assert settings.db_path == Path("data/tracker.db")
    assert settings.backup_retention_days == 30
    assert settings.backup_daily_hour == 3
