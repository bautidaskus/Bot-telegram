from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.bot.maintenance import BotMaintenance
from src.db.models import Base, Ejercicio, GymSesion, GymSet
from src.db.session import create_sqlite_engine


class FakeMessage:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.replies: list[tuple[str, Any]] = []

    async def reply_text(self, text: str, reply_markup: Any = None) -> None:
        self.replies.append((text, reply_markup))


class FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answers = 0
        self.edits: list[tuple[str, Any]] = []

    async def answer(self) -> None:
        self.answers += 1

    async def edit_message_text(self, text: str, reply_markup: Any = None) -> None:
        self.edits.append((text, reply_markup))


def update_with_message(text: str = "", chat_id: int = 123) -> SimpleNamespace:
    message = FakeMessage(text)
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=message,
        message=message,
        callback_query=None,
    )


def update_with_callback(data: str, chat_id: int = 123) -> SimpleNamespace:
    query = FakeQuery(data)
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=None,
        message=None,
        callback_query=query,
    )


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "maintenance.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        exercise = Ejercicio(id=1, nombre_canonico="press_banca")
        gym_session = GymSesion(
            id=1,
            fecha=date(2026, 6, 9),
            etiqueta="push",
            estado="cerrada",
            ultima_actividad=datetime(2026, 6, 9, 19, 0),
        )
        session.add_all([exercise, gym_session])
        session.flush()
        session.add(
            GymSet(id=1, sesion_id=1, ejercicio_id=1, serie_num=1, peso_kg=Decimal("80.00"), reps=8)
        )
        session.commit()
    return factory


def build_maintenance(session_factory: sessionmaker[Session]) -> BotMaintenance:
    return BotMaintenance(allowed_chat_id=123, session_factory=session_factory)


@pytest.mark.asyncio
async def test_edit_command_field_callback_and_next_text_update_set(
    session_factory: sessionmaker[Session],
) -> None:
    maintenance = build_maintenance(session_factory)
    context = SimpleNamespace(args=["set", "1"], user_data={})
    command_update = update_with_message()

    await maintenance.edit(command_update, context)

    prompt, keyboard = command_update.message.replies[0]
    assert "Elegí el campo" in prompt
    weight_button = next(
        button for row in keyboard.inline_keyboard for button in row if button.text == "peso_kg"
    )
    callback_update = update_with_callback(weight_button.callback_data)
    await maintenance.handle_callback(callback_update, context)
    assert "nuevo valor" in callback_update.callback_query.edits[0][0]

    value_update = update_with_message("82,5")
    handled = await maintenance.handle_edit_value(value_update, context)

    assert handled is True
    assert "Actualizado" in value_update.message.replies[0][0]
    assert context.user_data == {}
    with session_factory() as session:
        assert session.get(GymSet, 1).peso_kg == Decimal("82.50")


@pytest.mark.asyncio
async def test_delete_session_requires_confirmation(
    session_factory: sessionmaker[Session],
) -> None:
    maintenance = build_maintenance(session_factory)
    context = SimpleNamespace(args=["sesion", "1"], user_data={})
    command_update = update_with_message()

    await maintenance.delete(command_update, context)

    prompt, keyboard = command_update.message.replies[0]
    assert "Confirmá" in prompt
    callback_update = update_with_callback(keyboard.inline_keyboard[0][0].callback_data)
    await maintenance.handle_callback(callback_update, context)

    assert callback_update.callback_query.edits[0][0] == "Eliminado"
    with session_factory() as session:
        assert session.get(GymSesion, 1) is None


@pytest.mark.asyncio
async def test_edit_value_returns_false_without_active_dialog(
    session_factory: sessionmaker[Session],
) -> None:
    handled = await build_maintenance(session_factory).handle_edit_value(
        update_with_message("texto normal"),
        SimpleNamespace(args=[], user_data={}),
    )

    assert handled is False


@pytest.mark.asyncio
async def test_invalid_edit_value_does_not_mutate_or_close_dialog(
    session_factory: sessionmaker[Session],
) -> None:
    maintenance = build_maintenance(session_factory)
    context = SimpleNamespace(args=[], user_data={"edit_target": ("set", "1", "reps")})
    update = update_with_message("cero")

    handled = await maintenance.handle_edit_value(update, context)

    assert handled is True
    assert "Valor inválido" in update.message.replies[0][0]
    assert "edit_target" in context.user_data
    with session_factory() as session:
        assert session.get(GymSet, 1).reps == 8


@pytest.mark.asyncio
async def test_unknown_record_type_returns_usage(session_factory: sessionmaker[Session]) -> None:
    update = update_with_message()

    await build_maintenance(session_factory).edit(
        update, SimpleNamespace(args=["transaccion", "1"], user_data={})
    )

    assert "Uso:" in update.message.replies[0][0]


@pytest.mark.asyncio
async def test_unauthorized_maintenance_is_ignored(
    session_factory: sessionmaker[Session],
) -> None:
    update = update_with_message(chat_id=999)

    await build_maintenance(session_factory).edit(
        update,
        SimpleNamespace(args=["sesion", "1"], user_data={}),
    )

    assert update.message.replies == []
