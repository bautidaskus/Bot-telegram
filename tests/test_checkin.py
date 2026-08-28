from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.bot.callbacks import CheckinCallback, build_checkin_callback, parse_callback
from src.bot.checkin import STEPS, CheckinFlow
from src.db.models import Base
from src.db.repositories import CheckinRepository
from src.db.session import create_sqlite_engine

NOW = datetime(2026, 8, 4, 22, 0)
CHAT_ID = 123


class FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.edits: list[str] = []
        self.message = type("Message", (), {"message_id": 1})()

    async def answer(self) -> None:
        return None

    async def edit_message_text(self, text: str, **_: object) -> None:
        self.edits.append(text)


class FakeCallbackUpdate:
    def __init__(self, data: str, chat_id: int = CHAT_ID) -> None:
        self.callback_query = FakeQuery(data)
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("User", (), {"id": chat_id})()
        self.effective_message = None


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_: object) -> object:
        self.replies.append(text)
        return self


class FakeTextUpdate:
    def __init__(self, text: str, chat_id: int = CHAT_ID) -> None:
        self.effective_message = FakeMessage(text)
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("User", (), {"id": chat_id})()


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, chat_id: int, text: str, **_: object) -> object:
        self.sent.append(text)
        return type("Message", (), {"message_id": len(self.sent)})()


def _context() -> object:
    return type("Context", (), {"bot": FakeBot()})()


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "checkin.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _flow(session_factory: sessionmaker[Session]) -> CheckinFlow:
    return CheckinFlow(allowed_chat_id=CHAT_ID, session_factory=session_factory, now=lambda: NOW)


def test_callback_roundtrip() -> None:
    assert parse_callback(build_checkin_callback("puntaje_dia", "8")) == CheckinCallback(
        campo="puntaje_dia", valor="8"
    )


def test_steps_cover_every_question() -> None:
    assert [step.campo for step in STEPS] == [
        "puntaje_dia",
        "animo",
        "energia",
        "hora_acostado",
        "mejor_del_dia",
    ]


@pytest.mark.asyncio
async def test_prompt_creates_pending_checkin(session_factory: sessionmaker[Session]) -> None:
    context = _context()
    await _flow(session_factory).send_prompt(context)

    with session_factory() as session:
        assert CheckinRepository(session).get_or_create(NOW.date()).estado == "pendiente"
    assert context.bot.sent


@pytest.mark.asyncio
async def test_answers_persist_incrementally(session_factory: sessionmaker[Session]) -> None:
    flow = _flow(session_factory)
    await flow.handle_callback(FakeCallbackUpdate(build_checkin_callback("puntaje_dia", "8")), None)
    update = FakeCallbackUpdate(build_checkin_callback("animo", "6"))
    await flow.handle_callback(update, None)

    with session_factory() as session:
        stored = CheckinRepository(session).get_or_create(NOW.date())
        assert (stored.puntaje_dia, stored.animo) == (8, 6)
        assert stored.estado == "pendiente"
    assert "energ" in update.callback_query.edits[-1].lower()


@pytest.mark.asyncio
async def test_unauthorized_callback_is_ignored(session_factory: sessionmaker[Session]) -> None:
    update = FakeCallbackUpdate(build_checkin_callback("puntaje_dia", "8"), chat_id=999)
    await _flow(session_factory).handle_callback(update, None)

    with session_factory() as session:
        assert CheckinRepository(session).get_or_create(NOW.date()).puntaje_dia is None


@pytest.mark.asyncio
async def test_skipping_last_step_completes(session_factory: sessionmaker[Session]) -> None:
    flow = _flow(session_factory)
    skip = FakeCallbackUpdate(build_checkin_callback("mejor_del_dia", "-"))
    await flow.handle_callback(skip, None)

    with session_factory() as session:
        stored = CheckinRepository(session).get_or_create(NOW.date())
        assert stored.estado == "completo"
        assert stored.mejor_del_dia is None


@pytest.mark.asyncio
async def test_free_text_is_captured_only_after_choosing_to_write(
    session_factory: sessionmaker[Session],
) -> None:
    flow = _flow(session_factory)
    ignored = FakeTextUpdate("dominadas")
    assert await flow.handle_free_text(ignored, None) is False

    write = FakeCallbackUpdate(build_checkin_callback("mejor_del_dia", "w"))
    await flow.handle_callback(write, None)
    update = FakeTextUpdate("entrené con un amigo")
    assert await flow.handle_free_text(update, None) is True

    with session_factory() as session:
        stored = CheckinRepository(session).get_or_create(NOW.date())
        assert stored.mejor_del_dia == "entrené con un amigo"
        assert stored.estado == "completo"


@pytest.mark.asyncio
async def test_reminder_only_when_pending(session_factory: sessionmaker[Session]) -> None:
    flow = _flow(session_factory)
    context = _context()
    await flow.send_reminder(context)
    assert context.bot.sent

    with session_factory() as session:
        CheckinRepository(session).update(NOW.date(), estado="completo")
        session.commit()

    quiet = _context()
    await flow.send_reminder(quiet)
    assert quiet.bot.sent == []
