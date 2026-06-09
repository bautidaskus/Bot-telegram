from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.bot.maintenance import BotMaintenance
from src.db.models import Base, Salud, Transaccion
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
        session.add(
            Transaccion(
                id=1,
                fecha=date(2026, 6, 9),
                tipo="gasto",
                monto=Decimal("1500.00"),
                moneda="ARS",
                categoria="alimentos",
            )
        )
        session.add(Salud(fecha=date(2026, 6, 9), animo=8))
        session.commit()
    return factory


def build_maintenance(session_factory: sessionmaker[Session]) -> BotMaintenance:
    return BotMaintenance(
        allowed_chat_id=123,
        session_factory=session_factory,
    )


@pytest.mark.asyncio
async def test_edit_command_field_callback_and_next_text_update_transaction(
    session_factory: sessionmaker[Session],
) -> None:
    maintenance = build_maintenance(session_factory)
    context = SimpleNamespace(args=["transaccion", "1"], user_data={})
    command_update = update_with_message()

    await maintenance.edit(command_update, context)

    prompt, keyboard = command_update.message.replies[0]
    assert "Elegí el campo" in prompt
    amount_button = next(
        button for row in keyboard.inline_keyboard for button in row if button.text == "monto"
    )
    callback_update = update_with_callback(amount_button.callback_data)
    await maintenance.handle_callback(callback_update, context)
    assert "nuevo valor" in callback_update.callback_query.edits[0][0]

    value_update = update_with_message("1800,50")
    handled = await maintenance.handle_edit_value(value_update, context)

    assert handled is True
    assert "Actualizado" in value_update.message.replies[0][0]
    assert context.user_data == {}
    with session_factory() as session:
        assert session.get(Transaccion, 1).monto == Decimal("1800.50")


@pytest.mark.asyncio
async def test_delete_requires_confirmation_and_supports_health_date_id(
    session_factory: sessionmaker[Session],
) -> None:
    maintenance = build_maintenance(session_factory)
    context = SimpleNamespace(args=["salud", "2026-06-09"], user_data={})
    command_update = update_with_message()

    await maintenance.delete(command_update, context)

    prompt, keyboard = command_update.message.replies[0]
    assert "Confirmá" in prompt
    callback_data = keyboard.inline_keyboard[0][0].callback_data
    callback_update = update_with_callback(callback_data)
    await maintenance.handle_callback(callback_update, context)

    assert callback_update.callback_query.edits[0][0] == "Eliminado"
    with session_factory() as session:
        assert session.get(Salud, date(2026, 6, 9)) is None


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
    context = SimpleNamespace(args=[], user_data={"edit_target": ("transaccion", "1", "categoria")})
    update = update_with_message("categoria_inexistente")

    handled = await maintenance.handle_edit_value(update, context)

    assert handled is True
    assert "Valor inválido" in update.message.replies[0][0]
    assert "edit_target" in context.user_data
    with session_factory() as session:
        assert session.get(Transaccion, 1).categoria == "alimentos"


@pytest.mark.asyncio
async def test_unauthorized_maintenance_is_ignored(
    session_factory: sessionmaker[Session],
) -> None:
    update = update_with_message(chat_id=999)

    await build_maintenance(session_factory).edit(
        update,
        SimpleNamespace(args=["transaccion", "1"], user_data={}),
    )

    assert update.message.replies == []
