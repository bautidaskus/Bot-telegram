from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler

from src.bot.backup_commands import BotBackup
from src.bot.checkin import CheckinFlow
from src.bot.commands import BotCommands
from src.bot.gym_handlers import GymBotHandlers
from src.bot.maintenance import BotMaintenance
from src.db.models import Base
from src.db.session import create_sqlite_engine
from src.main import register_handlers

NOW = datetime(2026, 8, 4, 19, 0)


class UnusedCanonicalizer:
    def canonicalize(self, raw: str) -> tuple[str, str | None]:
        raise AssertionError("El test de wiring no debe llamar al LLM")


def build_application(tmp_path: Path) -> Application:
    engine = create_sqlite_engine(tmp_path / "main.db")
    Base.metadata.create_all(engine)
    sessions: sessionmaker[Session] = sessionmaker(engine, expire_on_commit=False)
    gym = GymBotHandlers(
        allowed_chat_id=123,
        session_factory=sessions,
        canonicalizer=UnusedCanonicalizer(),
        now=lambda: NOW,
    )
    checkin = CheckinFlow(allowed_chat_id=123, session_factory=sessions, now=lambda: NOW)
    commands = BotCommands(
        allowed_chat_id=123,
        session_factory=sessions,
        today=lambda: NOW.date(),
    )
    maintenance = BotMaintenance(allowed_chat_id=123, session_factory=sessions)
    backup = BotBackup(
        allowed_chat_id=123,
        db_path=tmp_path / "main.db",
        backup_dir=tmp_path / "backups",
    )
    application = Application.builder().token("123456:TEST_TOKEN").build()
    register_handlers(application, gym, checkin, commands, maintenance, backup)
    return application


def test_registered_commands_are_gym_only(tmp_path: Path) -> None:
    application = build_application(tmp_path)

    registered = {
        command
        for group in application.handlers.values()
        for handler in group
        if isinstance(handler, CommandHandler)
        for command in handler.commands
    }

    assert registered == {
        "start",
        "help",
        "hoy",
        "gym",
        "sesiones",
        "estado",
        "cancelar",
        "editar",
        "borrar",
        "export",
        "backup",
    }


def test_capture_handler_runs_after_the_priority_router(tmp_path: Path) -> None:
    application = build_application(tmp_path)

    default_group = application.handlers[0]
    assert isinstance(application.handlers[-1][0], MessageHandler)
    assert sum(isinstance(handler, CallbackQueryHandler) for handler in default_group) == 2
    assert sum(isinstance(handler, MessageHandler) for handler in default_group) == 1
    assert min(application.handlers) < 0


def test_audio_support_is_gone() -> None:
    assert importlib.util.find_spec("src.ai.whisper_client") is None
    assert importlib.util.find_spec("src.ai.audio_converter") is None
