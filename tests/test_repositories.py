from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, GymSet
from src.db.repositories import CheckinRepository, GymRepository
from src.db.session import create_sqlite_engine

NOW = datetime(2026, 8, 4, 19, 0)


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "repository.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_open_session_is_unique_and_findable(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        opened = repository.open_session(fecha=NOW.date(), etiqueta="espalda biceps", now=NOW)
        session.commit()

        assert opened.estado == "abierta"
        assert repository.get_open_session() is opened


def test_append_and_undo_sets(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        gym_session = repository.open_session(fecha=NOW.date(), etiqueta="pull", now=NOW)
        exercise = repository.get_or_create_exercise("dominadas")
        session.commit()

        first = repository.append_set(
            sesion_id=gym_session.id, ejercicio_id=exercise.id, reps=7, peso_kg=None, now=NOW
        )
        second = repository.append_set(
            sesion_id=gym_session.id, ejercicio_id=exercise.id, reps=6, peso_kg=None, now=NOW
        )
        session.commit()

        assert (first.serie_num, second.serie_num) == (1, 2)
        assert repository.undo_last_set(gym_session.id) is not None
        session.commit()
        remaining = session.scalars(select(GymSet).where(GymSet.sesion_id == gym_session.id)).all()
        assert len(remaining) == 1


def test_last_weight_for_returns_most_recent_set(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        gym_session = repository.open_session(fecha=NOW.date(), etiqueta="pull", now=NOW)
        exercise = repository.get_or_create_exercise("remo_t")
        session.commit()

        assert repository.last_weight_for(gym_session.id, exercise.id) is None

        repository.append_set(
            sesion_id=gym_session.id, ejercicio_id=exercise.id, reps=10, peso_kg=60, now=NOW
        )
        repository.append_set(
            sesion_id=gym_session.id, ejercicio_id=exercise.id, reps=8, peso_kg=65, now=NOW
        )
        session.commit()

        assert repository.last_weight_for(gym_session.id, exercise.id) == 65


def test_undo_on_empty_session_returns_none(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        gym_session = repository.open_session(fecha=NOW.date(), etiqueta="pull", now=NOW)
        session.commit()

        assert repository.undo_last_set(gym_session.id) is None


def test_stale_sessions_only_include_inactive_open_ones(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        stale = repository.open_session(
            fecha=NOW.date(), etiqueta="vieja", now=NOW - timedelta(hours=4)
        )
        session.commit()
        cutoff = NOW - timedelta(hours=3)

        assert repository.list_stale_open_sessions(cutoff) == [stale]

        repository.close_session(stale.id, now=NOW)
        session.commit()
        assert repository.list_stale_open_sessions(cutoff) == []


def test_aliases_accumulate_without_duplicates(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = GymRepository(session)
        exercise = repository.get_or_create_exercise("dominadas")
        session.commit()

        repository.add_alias(exercise.id, "dominasas")
        repository.add_alias(exercise.id, "dominasas")
        session.commit()

        assert repository.aliases_for(exercise.id) == ["dominasas"]


def test_checkin_partial_updates_persist(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = CheckinRepository(session)
        repository.get_or_create(NOW.date())
        session.commit()

        repository.update(NOW.date(), puntaje_dia=8)
        session.commit()
        repository.update(NOW.date(), animo=6, estado="completo")
        session.commit()

        stored = repository.get_or_create(NOW.date())
        assert (stored.puntaje_dia, stored.animo, stored.estado) == (8, 6, "completo")
