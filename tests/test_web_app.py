from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.db.session import create_sqlite_engine
from src.web import create_app


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "web.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def app(session_factory: sessionmaker[Session]) -> Flask:
    application = create_app(session_factory, today=lambda: date(2026, 6, 10))
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


def test_factory_creates_isolated_apps(session_factory: sessionmaker[Session]) -> None:
    first = create_app(session_factory, today=lambda: date(2026, 6, 10))
    second = create_app(session_factory, today=lambda: date(2026, 6, 11))

    assert first is not second


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/", "Resumen"),
        ("/finanzas", "Finanzas"),
        ("/gym", "Gimnasio"),
        ("/salud", "Salud"),
    ],
)
def test_dashboard_routes_render_navigation(client: FlaskClient, path: str, heading: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert heading in response.get_data(as_text=True)
    for label in ("Resumen", "Finanzas", "Gimnasio", "Salud"):
        assert label in response.get_data(as_text=True)


def test_healthz_reports_service_status(client: FlaskClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_empty_database_renders_without_errors(client: FlaskClient) -> None:
    for path in ("/", "/finanzas", "/gym", "/salud"):
        response = client.get(path)

        assert response.status_code == 200
        assert "Sin datos" in response.get_data(as_text=True)


def test_not_found_uses_controlled_error_page(client: FlaskClient) -> None:
    response = client.get("/no-existe")

    assert response.status_code == 404
    assert "Página no encontrada" in response.get_data(as_text=True)
