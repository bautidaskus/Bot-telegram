from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.db.repositories import GymRepository
from src.db.session import create_sqlite_engine
from src.gym.session_service import GymSessionService

NOW = datetime(2026, 8, 4, 19, 0)


class FakeCanonicalizer:
    """Canonizador determinístico que reemplaza al LLM en los tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def canonicalize(self, raw: str) -> tuple[str, str | None]:
        self.calls.append(raw)
        return raw.replace(" ", "_"), "dorsal"


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "service.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _service(session: Session) -> GymSessionService:
    return GymSessionService(session, canonicalizer=FakeCanonicalizer(), now=lambda: NOW)


def test_first_message_opens_session(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        reply = _service(session).handle("espalda biceps")
        session.commit()

        assert "espalda biceps" in reply
        assert GymRepository(session).get_open_session() is not None


def test_full_capture_flow(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("espalda biceps")
        service.handle("dominadas")
        service.handle("7")
        service.handle("6")
        service.handle("remo t 60")
        service.handle("10")
        reply = service.handle("fin")
        session.commit()

        repository = GymRepository(session)
        assert repository.get_open_session() is None
        stored = repository.list_sessions(1)[0]
        assert len(stored.sets) == 3
        assert "2 ejercicios" in reply


def test_sticky_weight_applies_to_bare_reps(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("pull")
        service.handle("remo t 60")
        service.handle("10")
        session.commit()

        stored = GymRepository(session).get_open_session()
        assert stored.sets[0].peso_kg == 60


def test_explicit_set_does_not_change_sticky_weight(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("pull")
        service.handle("remo t 60")
        service.handle("80x5")
        service.handle("10")
        session.commit()

        stored = GymRepository(session).get_open_session()
        assert [item.peso_kg for item in stored.sets] == [80, 60]


def test_undo_removes_last_set(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("pull")
        service.handle("dominadas")
        service.handle("77")
        service.handle("deshacer")
        session.commit()

        assert GymRepository(session).get_open_session().sets == []


def test_reps_without_exercise_are_rejected(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = _service(session)
        service.handle("pull")
        reply = service.handle("7")
        session.commit()

        assert "ejercicio" in reply.lower()
        assert GymRepository(session).get_open_session().sets == []


def test_typo_matches_known_exercise_without_llm(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        canonicalizer = FakeCanonicalizer()
        service = GymSessionService(session, canonicalizer=canonicalizer, now=lambda: NOW)
        service.handle("pull")
        service.handle("dominadas")
        service.handle("dominasas")
        session.commit()

        assert canonicalizer.calls == ["dominadas"]


def test_close_stale_closes_only_inactive(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        service = GymSessionService(
            session, canonicalizer=FakeCanonicalizer(), now=lambda: NOW - timedelta(hours=4)
        )
        service.handle("vieja")
        session.commit()

        closed = GymSessionService(
            session, canonicalizer=FakeCanonicalizer(), now=lambda: NOW
        ).close_stale(NOW - timedelta(hours=3))
        session.commit()

        assert len(closed) == 1
        assert GymRepository(session).get_open_session() is None
