from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.bot.commands import BotCommands
from src.db.models import Base, Ejercicio, GymSesion, GymSet
from src.db.repositories import CheckinRepository
from src.db.session import create_sqlite_engine

TODAY = date(2026, 6, 9)


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, reply_markup: Any = None) -> None:
        self.replies.append(text)


def command_update(chat_id: int = 123) -> SimpleNamespace:
    message = FakeMessage()
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=message,
        message=message,
    )


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "commands.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        exercise = Ejercicio(nombre_canonico="press_banca")
        gym_session = GymSesion(
            fecha=TODAY,
            etiqueta="push",
            estado="cerrada",
            duracion_min=60,
            ultima_actividad=datetime(2026, 6, 9, 19, 0),
        )
        session.add_all([exercise, gym_session])
        session.flush()
        session.add(
            GymSet(
                sesion_id=gym_session.id,
                ejercicio_id=exercise.id,
                serie_num=1,
                peso_kg=Decimal("80.00"),
                reps=8,
            )
        )
        session.commit()
    return factory


def build_commands(session_factory: sessionmaker[Session]) -> BotCommands:
    return BotCommands(
        allowed_chat_id=123,
        session_factory=session_factory,
        today=lambda: TODAY,
    )


@pytest.mark.asyncio
async def test_start_and_help_list_available_commands(
    session_factory: sessionmaker[Session],
) -> None:
    commands = build_commands(session_factory)
    start_update = command_update()
    help_update = command_update()

    await commands.start(start_update, SimpleNamespace(args=[]))
    await commands.help(help_update, SimpleNamespace(args=[]))

    assert "Gym Tracker" in start_update.message.replies[0]
    assert "/gym" in start_update.message.replies[0]
    assert "deshacer" in help_update.message.replies[0]
    assert "/editar <tipo> <id>" in help_update.message.replies[0]


@pytest.mark.asyncio
async def test_gym_and_session_commands(session_factory: sessionmaker[Session]) -> None:
    commands = build_commands(session_factory)
    cases = [
        (commands.gym, [], ["push", "press_banca", "80 kg x 8"]),
        (commands.gym, ["press_banca"], ["press_banca", "80 kg", "1RM"]),
        (commands.sessions, ["1"], ["push", "1 series"]),
    ]

    for handler, args, expected_parts in cases:
        update = command_update()
        await handler(update, SimpleNamespace(args=args))
        assert all(part in update.message.replies[0] for part in expected_parts)


@pytest.mark.asyncio
async def test_today_shows_session_and_pending_checkin(
    session_factory: sessionmaker[Session],
) -> None:
    update = command_update()

    await build_commands(session_factory).today(update, SimpleNamespace(args=[]))

    reply = update.message.replies[0]
    assert "Gimnasio: push — 1 series" in reply
    assert "Check-in: pendiente" in reply


@pytest.mark.asyncio
async def test_today_shows_answered_checkin(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        CheckinRepository(session).update(TODAY, puntaje_dia=8, animo=7, estado="completo")
        session.commit()
    update = command_update()

    await build_commands(session_factory).today(update, SimpleNamespace(args=[]))

    assert "Día: 8/10, ánimo 7" in update.message.replies[0]


@pytest.mark.asyncio
async def test_gym_without_data_reports_it(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "empty.db")
    Base.metadata.create_all(engine)
    commands = build_commands(sessionmaker(engine, expire_on_commit=False))
    update = command_update()

    await commands.gym(update, SimpleNamespace(args=[]))

    assert "No hay sesiones" in update.message.replies[0]


@pytest.mark.asyncio
async def test_unauthorized_command_is_ignored(session_factory: sessionmaker[Session]) -> None:
    update = command_update(chat_id=999)

    await build_commands(session_factory).gym(update, SimpleNamespace(args=[]))

    assert update.message.replies == []
