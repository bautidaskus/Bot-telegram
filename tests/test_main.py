from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from telegram.ext import Application, CallbackQueryHandler, MessageHandler

from src.bot.handlers import BotHandlers
from src.db.models import Base
from src.db.session import create_sqlite_engine
from src.domain.schemas import ParserResponse
from src.main import register_handlers


class UnusedParser:
    def parse(self, text: str, exercise_catalog: list[str]) -> ParserResponse:
        raise AssertionError("El test de wiring no debe ejecutar el parser")


def test_register_handlers_adds_text_and_callback_routes(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "main.db")
    Base.metadata.create_all(engine)
    sessions: sessionmaker[Session] = sessionmaker(engine, expire_on_commit=False)
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=UnusedParser(),
        session_factory=sessions,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    application = Application.builder().token("123456:TEST_TOKEN").build()

    register_handlers(application, handlers)

    registered = application.handlers[0]
    assert len(registered) == 2
    assert isinstance(registered[0], MessageHandler)
    assert isinstance(registered[1], CallbackQueryHandler)
