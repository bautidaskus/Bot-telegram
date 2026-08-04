"""Configuración central de la aplicación."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Carga y valida la configuración desde variables de entorno."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    telegram_bot_token: SecretStr
    # None habilita el modo descubrimiento: el bot ignora mensajes y loguea el chat_id (spec §11).
    allowed_chat_id: int | None = None
    groq_api_key: SecretStr
    groq_llm_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    timezone: str = "America/Argentina/Buenos_Aires"
    db_path: Path = Path("data/tracker.db")
    log_level: str = "INFO"

    backup_dir: Path = Path("data/backups")
    backup_retention_days: int = 30
    backup_daily_hour: int = 3


@lru_cache
def get_settings() -> Settings:
    """Devuelve una única instancia validada de configuración."""

    return Settings()
