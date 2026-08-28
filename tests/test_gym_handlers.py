from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.bot.gym_handlers import GymBotHandlers
from src.db.models import Base
from src.db.repositories import GymRepository
from src.db.session import create_sqlite_engine

NOW = datetime(2026, 8, 4, 19, 0)
CHAT_ID = 123


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_: object) -> object:
        self.replies.append(text)
        return self


class FakeUpdate:
    def __init__(self, text: str, chat_id: int = CHAT_ID) -> None:
        self.effective_message = FakeMessage(text)
        self.effective_chat = type("Chat", (), {"id": chat_id})()
        self.effective_user = type("User", (), {"id": chat_id})()


class FakeCanonicalizer:
    def canonicalize(self, raw: str) -> tuple[str, str | None]:
        return raw.replace(" ", "_"), None


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_: object) -> None:
        self.sent.append((chat_id, text))


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "handlers.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _handlers(session_factory: sessionmaker[Session], now: datetime = NOW) -> GymBotHandlers:
    return GymBotHandlers(
        allowed_chat_id=CHAT_ID,
        session_factory=session_factory,
        canonicalizer=FakeCanonicalizer(),
        now=lambda: now,
    )


@pytest.mark.asyncio
async def test_unauthorized_chat_is_ignored(session_factory: sessionmaker[Session]) -> None:
    update = FakeUpdate("espalda biceps", chat_id=999)
    await _handlers(session_factory).handle_text(update, None)

    assert update.effective_message.replies == []
    with session_factory() as session:
        assert GymRepository(session).get_open_session() is None


@pytest.mark.asyncio
async def test_capture_flow_replies_and_persists(session_factory: sessionmaker[Session]) -> None:
    handlers = _handlers(session_factory)
    for text in ["espalda biceps", "dominadas", "7"]:
        update = FakeUpdate(text)
        await handlers.handle_text(update, None)

    assert update.effective_message.replies
    with session_factory() as session:
        assert len(GymRepository(session).get_open_session().sets) == 1


@pytest.mark.asyncio
async def test_cancelar_discards_open_session(session_factory: sessionmaker[Session]) -> None:
    handlers = _handlers(session_factory)
    await handlers.handle_text(FakeUpdate("pull"), None)
    update = FakeUpdate("/cancelar")
    await handlers.cancelar(update, None)

    with session_factory() as session:
        assert GymRepository(session).get_open_session() is None
    assert "cancel" in update.effective_message.replies[-1].lower()


@pytest.mark.asyncio
async def test_estado_reports_open_session(session_factory: sessionmaker[Session]) -> None:
    handlers = _handlers(session_factory)
    for text in ["pull", "dominadas", "7"]:
        await handlers.handle_text(FakeUpdate(text), None)
    update = FakeUpdate("/estado")
    await handlers.estado(update, None)

    reply = update.effective_message.replies[-1]
    assert "pull" in reply
    assert "1" in reply


@pytest.mark.asyncio
async def test_estado_without_session(session_factory: sessionmaker[Session]) -> None:
    update = FakeUpdate("/estado")
    await _handlers(session_factory).estado(update, None)

    assert "no hay" in update.effective_message.replies[-1].lower()


@pytest.mark.asyncio
async def test_stale_session_is_closed_and_notified(
    session_factory: sessionmaker[Session],
) -> None:
    old = _handlers(session_factory, now=NOW - timedelta(hours=4))
    await old.handle_text(FakeUpdate("pull"), None)

    context = type("Context", (), {"bot": FakeBot()})()
    await _handlers(session_factory).close_stale_sessions(context)

    with session_factory() as session:
        assert GymRepository(session).get_open_session() is None
    assert context.bot.sent[0][0] == CHAT_ID


@pytest.mark.asyncio
async def test_active_session_is_not_closed(session_factory: sessionmaker[Session]) -> None:
    handlers = _handlers(session_factory)
    await handlers.handle_text(FakeUpdate("pull"), None)

    context = type("Context", (), {"bot": FakeBot()})()
    await handlers.close_stale_sessions(context)

    with session_factory() as session:
        assert GymRepository(session).get_open_session() is not None
    assert context.bot.sent == []
