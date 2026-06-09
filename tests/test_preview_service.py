from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.bot.preview_service import (
    AmbiguousOperationsError,
    PreviewExpiredError,
    PreviewService,
    PreviewStateError,
)
from src.db.models import Base, Pendiente, Peso, Preview, Salud, Transaccion
from src.db.repositories import WeightAlreadyExistsError
from src.db.session import create_sqlite_engine
from src.domain.schemas import ParserResponse


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "previews.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def parsed_batch() -> ParserResponse:
    return ParserResponse.model_validate(
        {
            "operaciones": [
                {
                    "tipo": "gasto",
                    "confianza": 0.95,
                    "fecha": "ayer",
                    "datos": {"monto": 1500, "categoria": "alimentos"},
                },
                {
                    "tipo": "salud",
                    "confianza": 0.9,
                    "fecha": "hoy",
                    "datos": {"animo": 8},
                },
            ]
        }
    )


def test_create_and_confirm_preview_persists_atomic_batch(
    session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 6, 9, 10, 0)
    with session_factory() as session:
        service = PreviewService(session)
        preview = service.create(
            chat_id=123,
            message_id=456,
            original_text="Gasté 1500 y ánimo 8",
            parsed=parsed_batch(),
            now=now,
        )
        session.commit()

        saved = service.confirm(preview.id, now=now)
        session.commit()

        assert [item.kind for item in saved] == ["gasto", "salud"]
        assert preview.estado == "guardado"
        assert session.query(Transaccion).one().monto == Decimal("1500.00")
        assert session.query(Transaccion).one().fecha == date(2026, 6, 8)
        assert session.query(Salud).one().fecha == date(2026, 6, 9)
        assert session.query(Salud).one().animo == 8


def test_confirm_is_idempotent_after_first_callback(
    session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 6, 9, 10, 0)
    with session_factory() as session:
        service = PreviewService(session)
        preview = service.create(
            chat_id=123,
            message_id=None,
            original_text="Gasté 1500 y ánimo 8",
            parsed=parsed_batch(),
            now=now,
        )
        first = service.confirm(preview.id, now=now)
        session.commit()
        second = service.confirm(preview.id, now=now)
        session.commit()

        assert second == first
        assert session.query(Transaccion).count() == 1
        assert session.query(Salud).count() == 1


def test_cancel_and_correct_require_pending_preview(
    session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 6, 9, 10, 0)
    with session_factory() as session:
        service = PreviewService(session)
        cancelled = service.create(
            chat_id=123,
            message_id=None,
            original_text="Gasté 1500 y ánimo 8",
            parsed=parsed_batch(),
            now=now,
        )
        service.cancel(cancelled.id, now=now)
        session.commit()

        assert cancelled.estado == "cancelado"
        with pytest.raises(PreviewStateError):
            service.correct(cancelled.id, parsed_batch(), now=now)

        editable = service.create(
            chat_id=123,
            message_id=None,
            original_text="Gasté 1500 y ánimo 8",
            parsed=parsed_batch(),
            now=now,
        )
        corrected = service.correct(editable.id, parsed_batch(), now=now)
        session.commit()
        assert corrected.estado == "pendiente"


def test_expire_pending_previews_and_reject_confirmation(
    session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 6, 9, 10, 0)
    with session_factory() as session:
        service = PreviewService(session)
        preview = service.create(
            chat_id=123,
            message_id=None,
            original_text="Gasté 1500 y ánimo 8",
            parsed=parsed_batch(),
            now=now,
        )
        expired_ids = service.expire_pending(now=now + timedelta(minutes=11))
        session.commit()

        assert expired_ids == [preview.id]
        assert preview.estado == "expirado"
        with pytest.raises(PreviewExpiredError):
            service.confirm(
                preview.id,
                now=now + timedelta(minutes=11),
            )


def test_ambiguous_operations_become_pending_without_preview(
    session_factory: sessionmaker[Session],
) -> None:
    parsed = ParserResponse.model_validate(
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
    with session_factory() as session:
        service = PreviewService(session)
        pending = service.store_ambiguity(
            chat_id=123,
            original_text="Anoté 20",
            parsed=parsed,
        )
        session.commit()

        assert pending.sugerencias_json == '["gasto", "ingreso"]'
        assert session.query(Pendiente).count() == 1
        assert session.query(Preview).count() == 0


def test_preview_rejects_ambiguous_or_low_confidence_operations(
    session_factory: sessionmaker[Session],
) -> None:
    parsed = ParserResponse.model_validate(
        {
            "operaciones": [
                {
                    "tipo": "gasto",
                    "confianza": 0.6,
                    "fecha": "hoy",
                    "datos": {"monto": 1500, "categoria": "alimentos"},
                }
            ]
        }
    )
    with session_factory() as session:
        with pytest.raises(AmbiguousOperationsError):
            PreviewService(session).create(
                chat_id=123,
                message_id=None,
                original_text="Anoté 1500",
                parsed=parsed,
                now=datetime(2026, 6, 9, 10, 0),
            )


def test_resolve_ambiguity_returns_reprocessing_context(
    session_factory: sessionmaker[Session],
) -> None:
    parsed = ParserResponse.model_validate(
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
    with session_factory() as session:
        service = PreviewService(session)
        pending = service.store_ambiguity(
            chat_id=123,
            original_text="Anoté 20",
            transcription="Anoté veinte",
            parsed=parsed,
        )
        session.commit()

        loaded = service.get_ambiguity_context(pending.id, hint="gasto")
        assert loaded.original_text == "Anoté 20"
        assert pending.estado == "pendiente"

        context = service.resolve_ambiguity(pending.id, hint="gasto")
        session.commit()

        assert context.original_text == "Anoté 20"
        assert context.transcription == "Anoté veinte"
        assert context.hint == "gasto"
        assert pending.estado == "resuelto"


def test_attach_message_stores_bot_preview_message_id(
    session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 6, 9, 10, 0)
    with session_factory() as session:
        service = PreviewService(session)
        preview = service.create(
            chat_id=123,
            message_id=None,
            original_text="Gasté 1500 y ánimo 8",
            parsed=parsed_batch(),
            now=now,
        )
        service.attach_message(preview.id, 789)
        session.commit()

        assert preview.message_id == 789


def test_confirm_rolls_back_whole_batch_when_operation_fails(
    session_factory: sessionmaker[Session],
) -> None:
    parsed = ParserResponse.model_validate(
        {
            "operaciones": [
                {
                    "tipo": "gasto",
                    "confianza": 0.95,
                    "fecha": "hoy",
                    "datos": {"monto": 1500, "categoria": "alimentos"},
                },
                {
                    "tipo": "peso",
                    "confianza": 0.95,
                    "fecha": "hoy",
                    "datos": {"kg": 78.4},
                },
            ]
        }
    )
    now = datetime(2026, 6, 9, 10, 0)
    with session_factory() as session:
        session.add(Peso(fecha=date(2026, 6, 9), kg=Decimal("79.00")))
        session.commit()
        service = PreviewService(session)
        preview = service.create(
            chat_id=123,
            message_id=None,
            original_text="Gasté 1500 y pesé 78.4",
            parsed=parsed,
            now=now,
        )
        session.commit()

        with pytest.raises(WeightAlreadyExistsError):
            service.confirm(preview.id, now=now)
        session.rollback()

        assert session.query(Transaccion).count() == 0
        assert session.get(Preview, preview.id).estado == "pendiente"
