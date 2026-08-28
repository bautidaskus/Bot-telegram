from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.db.repositories import CheckinRepository, GymRepository
from src.db.session import create_sqlite_engine
from src.web import create_app
from src.web.queries import DashboardQueries

TODAY = date(2026, 6, 10)


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "web.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def app(session_factory: sessionmaker[Session]) -> Flask:
    application = create_app(session_factory, today=lambda: TODAY)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def test_factory_creates_isolated_apps(session_factory: sessionmaker[Session]) -> None:
    first = create_app(session_factory, today=lambda: TODAY)
    second = create_app(session_factory, today=lambda: date(2026, 6, 11))

    assert first is not second


@pytest.mark.parametrize(
    ("path", "heading"),
    [("/", "Resumen"), ("/gym", "Gimnasio"), ("/checkin", "Check-in")],
)
def test_dashboard_routes_render_navigation(client: FlaskClient, path: str, heading: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert heading in body
    for label in ("Resumen", "Gimnasio", "Check-in"):
        assert label in body


def test_removed_routes_are_gone(client: FlaskClient) -> None:
    assert client.get("/finanzas").status_code == 404
    assert client.get("/salud").status_code == 404


def test_healthz_reports_service_status(client: FlaskClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_empty_database_renders_without_errors(client: FlaskClient) -> None:
    for path in ("/", "/gym", "/checkin"):
        response = client.get(path)

        assert response.status_code == 200
        assert "Sin datos" in response.get_data(as_text=True)


def test_not_found_uses_controlled_error_page(client: FlaskClient) -> None:
    response = client.get("/no-existe")

    assert response.status_code == 404
    assert "Página no encontrada" in response.get_data(as_text=True)


def test_checkin_vs_gym_splits_by_training_day(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = CheckinRepository(session)
        repository.update(date(2026, 6, 9), puntaje_dia=8, estado="completo")
        repository.update(date(2026, 6, 8), puntaje_dia=4, estado="completo")
        GymRepository(session).open_session(
            fecha=date(2026, 6, 9), etiqueta="pull", now=datetime(2026, 6, 9, 19, 0)
        )
        session.commit()

        result = DashboardQueries(session, today=lambda: TODAY).checkin_vs_gym(days=30)

    assert result == {"con_gym": 8.0, "sin_gym": 4.0}


def test_checkin_vs_gym_without_data_returns_none(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        result = DashboardQueries(session, today=lambda: TODAY).checkin_vs_gym(days=30)

    assert result == {"con_gym": None, "sin_gym": None}


def test_checkin_history_is_ordered_and_windowed(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repository = CheckinRepository(session)
        repository.update(date(2026, 6, 9), puntaje_dia=8, animo=7, energia=4)
        repository.update(date(2026, 6, 1), puntaje_dia=5, animo=5, energia=3)
        repository.update(date(2026, 1, 1), puntaje_dia=2)
        session.commit()

        history = DashboardQueries(session, today=lambda: TODAY).checkin_history(days=30)

    assert [item["fecha"] for item in history] == ["2026-06-01", "2026-06-09"]
    assert history[-1]["puntaje"] == 8
