from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.bot.commands import BotCommands
from src.db.models import Base, Ejercicio, GymSesion, GymSet, Peso, Salud, Transaccion
from src.db.session import create_sqlite_engine


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
        session.add_all(
            [
                Transaccion(
                    fecha=date(2026, 6, 9),
                    tipo="gasto",
                    monto=Decimal("1500.00"),
                    moneda="ARS",
                    categoria="alimentos",
                    descripcion="supermercado",
                ),
                Transaccion(
                    fecha=date(2026, 6, 8),
                    tipo="ingreso",
                    monto=Decimal("10000.00"),
                    moneda="ARS",
                    categoria="freelance",
                ),
                Transaccion(
                    fecha=date(2026, 5, 20),
                    tipo="ingreso",
                    monto=Decimal("5000.00"),
                    moneda="ARS",
                    categoria="venta",
                ),
                Peso(fecha=date(2026, 6, 9), kg=Decimal("78.40")),
                Peso(fecha=date(2026, 6, 8), kg=Decimal("78.70")),
                Salud(
                    fecha=date(2026, 6, 9),
                    sueno_horas=Decimal("7.50"),
                    animo=8,
                    energia=7,
                    agua_l=Decimal("2.00"),
                ),
            ]
        )
        exercise = Ejercicio(nombre_canonico="press_banca")
        gym_session = GymSesion(fecha=date(2026, 6, 9), tipo="push", duracion_min=60)
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
        today=lambda: date(2026, 6, 9),
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

    assert "Personal Tracker" in start_update.message.replies[0]
    assert "/balance" in start_update.message.replies[0]
    assert "/editar <tipo> <id>" in help_update.message.replies[0]
    assert "/borrar <tipo> <id>" in help_update.message.replies[0]


@pytest.mark.asyncio
async def test_finance_commands_format_balance_categories_income_and_recent(
    session_factory: sessionmaker[Session],
) -> None:
    commands = build_commands(session_factory)
    cases = [
        (commands.balance, [], ["Ingresos: $10.000", "Gastos: $1.500", "Balance: $8.500"]),
        (commands.gastos, [], ["alimentos", "$1.500"]),
        (commands.ingresos, [], ["freelance", "$10.000"]),
        (commands.ingresos, ["5", "2026"], ["venta", "$5.000"]),
        (commands.ultimos, ["1"], ["supermercado", "$1.500"]),
    ]

    for handler, args, expected_parts in cases:
        update = command_update()
        await handler(update, SimpleNamespace(args=args))
        assert all(part in update.message.replies[0] for part in expected_parts)


@pytest.mark.asyncio
async def test_gym_weight_health_and_today_commands(
    session_factory: sessionmaker[Session],
) -> None:
    commands = build_commands(session_factory)
    cases = [
        (commands.gym, [], ["push", "press_banca", "80 kg x 8"]),
        (commands.gym, ["press_banca"], ["press_banca", "80 kg", "1RM"]),
        (commands.sessions, ["1"], ["push", "60 min"]),
        (commands.weight, [], ["78,4 kg", "Media móvil 7 días", "78,55 kg", "Tendencia"]),
        (commands.weight, ["historial"], ["78,4 kg", "78,7 kg"]),
        (commands.health, [], ["Sueño", "7,5 h", "Ánimo", "8"]),
        (commands.today, [], ["Gastos", "$1.500", "Peso", "78,4 kg", "Salud"]),
    ]

    for handler, args, expected_parts in cases:
        update = command_update()
        await handler(update, SimpleNamespace(args=args))
        assert all(part in update.message.replies[0] for part in expected_parts)


@pytest.mark.asyncio
async def test_unauthorized_command_is_ignored(
    session_factory: sessionmaker[Session],
) -> None:
    update = command_update(chat_id=999)

    await build_commands(session_factory).balance(update, SimpleNamespace(args=[]))

    assert update.message.replies == []


@pytest.mark.asyncio
async def test_invalid_command_arguments_return_usage(
    session_factory: sessionmaker[Session],
) -> None:
    update = command_update()

    await build_commands(session_factory).balance(update, SimpleNamespace(args=["13"]))

    assert "Uso:" in update.message.replies[0]
