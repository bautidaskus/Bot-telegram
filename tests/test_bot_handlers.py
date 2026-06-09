from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.ai.parser import ParserUnavailableError
from src.bot.handlers import BotHandlers
from src.db.models import Base, Pendiente, Preview, Transaccion
from src.db.session import create_sqlite_engine
from src.domain.schemas import ParserResponse


class FakeParser:
    def __init__(self, response: ParserResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, list[str]]] = []

    def parse(self, text: str, exercise_catalog: list[str]) -> ParserResponse:
        self.calls.append((text, exercise_catalog))
        return self.response


class UnavailableParser:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def parse(self, text: str, exercise_catalog: list[str]) -> ParserResponse:
        self.calls.append((text, exercise_catalog))
        raise ParserUnavailableError("Groq no respondió tras 3 intentos")


class FakeMessage:
    def __init__(self, text: str, chat_id: int = 123) -> None:
        self.text = text
        self.chat_id = chat_id
        self.message_id = 456
        self.replies: list[tuple[str, Any]] = []

    async def reply_text(self, text: str, reply_markup: Any = None) -> Any:
        self.replies.append((text, reply_markup))
        return SimpleNamespace(message_id=789)


class FakeCallbackQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = SimpleNamespace(message_id=790)
        self.answers = 0
        self.edits: list[tuple[str, Any]] = []

    async def answer(self) -> None:
        self.answers += 1

    async def edit_message_text(self, text: str, reply_markup: Any = None) -> None:
        self.edits.append((text, reply_markup))


def text_update(text: str, chat_id: int = 123) -> SimpleNamespace:
    message = FakeMessage(text, chat_id)
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=message,
        message=message,
        callback_query=None,
    )


def callback_update(data: str, chat_id: int = 123) -> SimpleNamespace:
    query = FakeCallbackQuery(data)
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=None,
        message=None,
        callback_query=query,
    )


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "bot.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def expense_response() -> ParserResponse:
    return ParserResponse.model_validate(
        {
            "operaciones": [
                {
                    "tipo": "gasto",
                    "confianza": 0.95,
                    "fecha": "hoy",
                    "datos": {"monto": 1500, "categoria": "alimentos"},
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_unauthorized_text_is_ignored(
    session_factory: sessionmaker[Session],
) -> None:
    parser = FakeParser(expense_response())
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=parser,
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    update = text_update("Gasté 1500", chat_id=999)

    await handlers.handle_text(update, SimpleNamespace())

    assert parser.calls == []
    assert update.message.replies == []


@pytest.mark.asyncio
async def test_unauthorized_callback_is_ignored(
    session_factory: sessionmaker[Session],
) -> None:
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(expense_response()),
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    update = callback_update("invalid", chat_id=999)

    await handlers.handle_callback(update, SimpleNamespace())

    assert update.callback_query.answers == 0
    assert update.callback_query.edits == []


@pytest.mark.asyncio
async def test_authorized_text_creates_preview_with_buttons(
    session_factory: sessionmaker[Session],
) -> None:
    parser = FakeParser(expense_response())
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=parser,
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    update = text_update("Gasté 1500")

    await handlers.handle_text(update, SimpleNamespace())

    assert parser.calls == [("Gasté 1500", [])]
    reply_text, keyboard = update.message.replies[0]
    assert "Gasto" in reply_text
    assert "1.500" in reply_text
    assert [button.text for button in keyboard.inline_keyboard[0]] == [
        "Guardar",
        "Cancelar",
        "Corregir",
    ]
    with session_factory() as session:
        preview = session.query(Preview).one()
        assert preview.message_id == 789


@pytest.mark.asyncio
async def test_preview_warns_about_future_date(
    session_factory: sessionmaker[Session],
) -> None:
    parser = FakeParser(
        ParserResponse.model_validate(
            {
                "operaciones": [
                    {
                        "tipo": "gasto",
                        "confianza": 0.95,
                        "fecha": "2026-12-25",
                        "datos": {"monto": 1500, "categoria": "alimentos"},
                    }
                ]
            }
        )
    )
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=parser,
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    update = text_update("Gasté 1500 el 25/12")

    await handlers.handle_text(update, SimpleNamespace())

    reply_text = update.message.replies[0][0]
    assert "fecha futura: 2026-12-25" in reply_text
    assert "Revisá antes de guardar" in reply_text


@pytest.mark.asyncio
async def test_preview_warns_about_weight_and_sleep_out_of_range(
    session_factory: sessionmaker[Session],
) -> None:
    parser = FakeParser(
        ParserResponse.model_validate(
            {
                "operaciones": [
                    {
                        "tipo": "peso",
                        "confianza": 0.95,
                        "fecha": "hoy",
                        "datos": {"kg": 12},
                    },
                    {
                        "tipo": "salud",
                        "confianza": 0.95,
                        "fecha": "hoy",
                        "datos": {"sueno_horas": 20},
                    },
                ]
            }
        )
    )
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=parser,
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    update = text_update("Pesé 12 y dormí 20 horas")

    await handlers.handle_text(update, SimpleNamespace())

    reply_text = update.message.replies[0][0]
    assert "peso fuera de rango habitual: 12 kg" in reply_text
    assert "sueño fuera de rango habitual: 20 h" in reply_text


@pytest.mark.asyncio
async def test_in_range_preview_has_no_warnings(
    session_factory: sessionmaker[Session],
) -> None:
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(expense_response()),
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    update = text_update("Gasté 1500")

    await handlers.handle_text(update, SimpleNamespace())

    assert "Revisá antes de guardar" not in update.message.replies[0][0]


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


@pytest.mark.asyncio
async def test_accumulated_messages_are_throttled_to_one_per_second(
    session_factory: sessionmaker[Session],
) -> None:
    clock = FakeClock()
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(expense_response()),
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
        throttle_interval=1.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    for _ in range(3):
        await handlers.handle_text(text_update("Gasté 1500"), SimpleNamespace())

    assert clock.sleeps == [1.0, 1.0]


@pytest.mark.asyncio
async def test_unauthorized_message_is_not_throttled(
    session_factory: sessionmaker[Session],
) -> None:
    clock = FakeClock()
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(expense_response()),
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    await handlers.handle_text(text_update("Gasté 1500", chat_id=999), SimpleNamespace())

    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_groq_unavailable_stores_pending_and_notifies(
    session_factory: sessionmaker[Session],
) -> None:
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=UnavailableParser(),
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    update = text_update("Gasté 1500")

    await handlers.handle_text(update, SimpleNamespace())

    reply_text = update.message.replies[0][0]
    assert "no está disponible" in reply_text
    assert "pendiente" in reply_text
    with session_factory() as session:
        pending = session.query(Pendiente).one()
        assert pending.mensaje_original == "Gasté 1500"
        assert pending.chat_id == 123
        assert session.query(Preview).count() == 0


@pytest.mark.asyncio
async def test_ambiguous_text_creates_clarification_buttons(
    session_factory: sessionmaker[Session],
) -> None:
    parser = FakeParser(
        ParserResponse.model_validate(
            {
                "operaciones": [
                    {
                        "tipo": "ambiguo",
                        "confianza": 0.4,
                        "fecha": "hoy",
                        "datos": {"sugerencias": ["gasto", "ingreso"]},
                    }
                ]
            }
        )
    )
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=parser,
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    update = text_update("Anoté 20")

    await handlers.handle_text(update, SimpleNamespace())

    reply_text, keyboard = update.message.replies[0]
    assert "aclaración" in reply_text
    assert [button.text for button in keyboard.inline_keyboard[0]] == ["gasto", "ingreso"]


@pytest.mark.asyncio
async def test_save_callback_persists_preview(
    session_factory: sessionmaker[Session],
) -> None:
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(expense_response()),
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    message_update = text_update("Gasté 1500")
    await handlers.handle_text(message_update, SimpleNamespace())
    callback_data = message_update.message.replies[0][1].inline_keyboard[0][0].callback_data
    update = callback_update(callback_data)

    await handlers.handle_callback(update, SimpleNamespace())

    assert update.callback_query.answers == 1
    assert "Guardado" in update.callback_query.edits[0][0]
    with session_factory() as session:
        assert session.query(Transaccion).one().fecha == date(2026, 6, 9)


@pytest.mark.asyncio
async def test_cancel_callback_discards_preview(
    session_factory: sessionmaker[Session],
) -> None:
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(expense_response()),
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    message_update = text_update("Gasté 1500")
    await handlers.handle_text(message_update, SimpleNamespace())
    callback_data = message_update.message.replies[0][1].inline_keyboard[0][1].callback_data
    update = callback_update(callback_data)

    await handlers.handle_callback(update, SimpleNamespace())

    assert update.callback_query.edits[0][0] == "Cancelado"
    with session_factory() as session:
        assert session.query(Preview).one().estado == "cancelado"
        assert session.query(Transaccion).count() == 0


@pytest.mark.asyncio
async def test_clarification_callback_reprocesses_with_hint(
    session_factory: sessionmaker[Session],
) -> None:
    ambiguous = ParserResponse.model_validate(
        {
            "operaciones": [
                {
                    "tipo": "ambiguo",
                    "confianza": 0.4,
                    "fecha": "hoy",
                    "datos": {"sugerencias": ["gasto", "ingreso"]},
                }
            ]
        }
    )
    parser = FakeParser(ambiguous)
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=parser,
        session_factory=session_factory,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )
    message_update = text_update("Anoté 20")
    await handlers.handle_text(message_update, SimpleNamespace())
    parser.response = expense_response()
    callback_data = message_update.message.replies[0][1].inline_keyboard[0][0].callback_data
    update = callback_update(callback_data)

    await handlers.handle_callback(update, SimpleNamespace())

    assert parser.calls[-1][0] == "Anoté 20\nTipo confirmado: gasto"
    reply_text, keyboard = update.callback_query.edits[0]
    assert "Gasto" in reply_text
    assert keyboard.inline_keyboard[0][0].text == "Guardar"
    with session_factory() as session:
        assert session.query(Preview).one().message_id == 790
