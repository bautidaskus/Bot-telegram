from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, GymSesion
from src.db.session import create_sqlite_engine
from src.web import create_app


class TrackingSession(Session):
    closed_sessions: list[int] = []

    def close(self) -> None:
        TrackingSession.closed_sessions.append(id(self))
        super().close()


class BrokenSession(TrackingSession):
    def scalars(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("detalle interno sensible")


def test_each_request_closes_its_session(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "sessions.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=TrackingSession, expire_on_commit=False)
    TrackingSession.closed_sessions.clear()
    client = create_app(factory, today=lambda: date(2026, 6, 10)).test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert len(TrackingSession.closed_sessions) == 1


def test_session_closes_and_error_is_controlled_when_query_fails(tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
    engine = create_sqlite_engine(tmp_path / "broken.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=BrokenSession, expire_on_commit=False)
    TrackingSession.closed_sessions.clear()
    app = create_app(factory, today=lambda: date(2026, 6, 10))
    app.config.update(TESTING=False)

    with caplog.at_level(logging.ERROR):
        response = app.test_client().get("/")

    body = response.get_data(as_text=True)
    assert response.status_code == 500
    assert "No pudimos cargar el dashboard" in body
    assert "detalle interno sensible" not in body
    assert len(TrackingSession.closed_sessions) == 1
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_missing_database_schema_returns_controlled_error(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "missing-schema.db")
    factory = sessionmaker(engine, expire_on_commit=False)
    app = create_app(factory, today=lambda: date(2026, 6, 10))
    app.config.update(TESTING=False)

    response = app.test_client().get("/checkin")

    assert response.status_code == 500
    assert "No pudimos cargar el dashboard" in response.get_data(as_text=True)
    assert "no such table" not in response.get_data(as_text=True)


def test_outdated_schema_returns_controlled_error(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "outdated.db")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE gym_sesion (id INTEGER PRIMARY KEY)"))
    factory = sessionmaker(engine, expire_on_commit=False)
    app = create_app(factory, today=lambda: date(2026, 6, 10))
    app.config.update(TESTING=False)

    response = app.test_client().get("/")

    assert response.status_code == 500
    assert "No pudimos cargar el dashboard" in response.get_data(as_text=True)
    assert "no such column" not in response.get_data(as_text=True)


def test_web_read_completes_while_bot_write_transaction_is_open(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "concurrent.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    write_started = threading.Event()
    allow_commit = threading.Event()

    def write_transaction() -> None:
        with factory() as session:
            session.add(
                GymSesion(
                    fecha=date(2026, 6, 10),
                    etiqueta="push",
                    estado="cerrada",
                    ultima_actividad=datetime(2026, 6, 10, 19, 0),
                )
            )
            session.flush()
            write_started.set()
            assert allow_commit.wait(timeout=5)
            session.commit()

    writer = threading.Thread(target=write_transaction)
    writer.start()
    assert write_started.wait(timeout=5)

    try:
        response = create_app(factory, today=lambda: date(2026, 6, 10)).test_client().get("/gym")
    finally:
        allow_commit.set()
        writer.join(timeout=5)

    assert response.status_code == 200
    assert not writer.is_alive()
    with factory() as session:
        assert session.query(GymSesion).count() == 1
