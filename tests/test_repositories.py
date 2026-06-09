from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, GymSet, Transaccion
from src.db.repositories import (
    FinanceRepository,
    GymRepository,
    HealthRepository,
    WeightAlreadyExistsError,
    WeightRepository,
)
from src.db.session import create_sqlite_engine


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "repository.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_finance_repository_crud(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = FinanceRepository(session)
        created = repository.create(
            fecha=date(2026, 6, 8),
            tipo="gasto",
            monto=Decimal("1500.00"),
            categoria="alimentos",
            descripcion="supermercado",
        )
        session.commit()

        assert repository.get(created.id) is created
        assert repository.list_recent(1) == [created]

        updated = repository.update(created.id, monto=Decimal("1800.00"))
        session.commit()
        assert updated.monto == Decimal("1800.00")

        repository.delete(created.id)
        session.commit()
        assert repository.get(created.id) is None


def test_weight_requires_explicit_replace(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = WeightRepository(session)
        original = repository.save(date(2026, 6, 8), Decimal("78.40"))
        session.commit()

        with pytest.raises(WeightAlreadyExistsError):
            repository.save(date(2026, 6, 8), Decimal("78.10"))
        session.rollback()

        replaced = repository.save(date(2026, 6, 8), Decimal("78.10"), replace=True)
        session.commit()

        assert replaced.id == original.id
        assert replaced.kg == Decimal("78.10")
        repository.delete(original.id)
        session.commit()
        assert repository.get(original.id) is None


def test_health_upsert_preserves_unspecified_fields(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        repository = HealthRepository(session)
        repository.upsert(date(2026, 6, 8), sueno_horas=Decimal("7.50"), animo=7)
        session.commit()

        health = repository.upsert(date(2026, 6, 8), agua_l=Decimal("2.00"))
        session.commit()

        assert health.sueno_horas == Decimal("7.50")
        assert health.animo == 7
        assert health.agua_l == Decimal("2.00")
        repository.delete(date(2026, 6, 8))
        session.commit()
        assert repository.get(date(2026, 6, 8)) is None


def test_gym_creates_exercise_once_and_cascades_sets(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        first = repository.create_session(
            fecha=date(2026, 6, 8),
            tipo="push",
            exercises=[
                {
                    "nombre": "press_banca",
                    "sets": [
                        {"peso_kg": Decimal("80.00"), "reps": 8},
                        {"peso_kg": Decimal("80.00"), "reps": 6},
                    ],
                }
            ],
        )
        second = repository.create_session(
            fecha=date(2026, 6, 9),
            tipo="push",
            exercises=[
                {
                    "nombre": "press_banca",
                    "sets": [{"peso_kg": Decimal("82.50"), "reps": 6}],
                }
            ],
        )
        session.commit()

        assert first.sets[0].ejercicio_id == second.sets[0].ejercicio_id
        assert len(repository.list_exercises()) == 1
        updated = repository.update_session(first.id, duracion_min=60, notas="buena sesión")
        session.commit()
        assert updated.duracion_min == 60
        assert repository.get_session(first.id) is updated
        assert repository.list_sessions(2) == [second, first]
        repository.delete_session(first.id)
        session.commit()
        assert session.query(GymSet).filter_by(sesion_id=first.id).count() == 0


def test_transaction_rolls_back_whole_batch_on_failure(
    session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(RuntimeError, match="operación inválida"):
        with session_factory.begin() as session:
            FinanceRepository(session).create(
                fecha=date(2026, 6, 8),
                tipo="gasto",
                monto=Decimal("1500.00"),
                categoria="alimentos",
            )
            raise RuntimeError("operación inválida")

    with session_factory() as session:
        assert session.query(Transaccion).count() == 0
