from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, GymSesion, Peso, Salud, Transaccion
from src.db.session import create_sqlite_engine
from src.web import create_app


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "views.db")
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


def test_summary_renders_month_cards_and_recent_domains(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                Transaccion(
                    fecha=date(2026, 6, 1),
                    tipo="ingreso",
                    monto=Decimal("100000"),
                    moneda="ARS",
                    categoria="sueldo",
                ),
                Transaccion(
                    fecha=date(2026, 6, 2),
                    tipo="gasto",
                    monto=Decimal("25000"),
                    moneda="ARS",
                    categoria="comida",
                ),
                Peso(fecha=date(2026, 6, 8), kg=Decimal("78.40")),
                Salud(fecha=date(2026, 6, 9), sueno_horas=Decimal("7.50"), animo=8),
                GymSesion(fecha=date(2026, 6, 10), tipo="push"),
            ]
        )

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "100.000,00" in body
    assert "25.000,00" in body
    assert "75.000,00" in body
    assert "78,40 kg" in body
    assert "1 sesión" in body
    assert "Actividad reciente" in body


def test_finances_selects_ars_and_serializes_chart_data(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                finance(date(2026, 6, 1), "ingreso", "3000", "ARS", "sueldo"),
                finance(date(2026, 6, 2), "gasto", "500", "ARS", "comida"),
                finance(date(2026, 6, 2), "gasto", "20", "USD", "software"),
            ]
        )

    response = client.get("/finanzas", query_string={"month": "2026-06"})
    body = response.get_data(as_text=True)
    payload = chart_payload(body)

    assert response.status_code == 200
    assert '<option value="ARS" selected>' in body
    assert "3.000,00" in body
    assert "500,00" in body
    assert payload["daily"][0] == {"date": "2026-06-01", "expenses": 0.0, "income": 3000.0}
    assert payload["categories"] == [{"amount": 500.0, "category": "comida"}]


def test_finances_honors_valid_filters_and_falls_back_from_invalid_ones(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                finance(date(2026, 5, 2), "gasto", "20", "USD", "software"),
                finance(date(2026, 6, 2), "gasto", "500", "ARS", "comida"),
            ]
        )

    valid = client.get("/finanzas?month=2026-05&currency=USD").get_data(as_text=True)
    invalid = client.get("/finanzas?month=nope&currency=EUR").get_data(as_text=True)

    assert 'value="2026-05"' in valid
    assert '<option value="USD" selected>' in valid
    assert "20,00" in valid
    assert 'value="2026-06"' in invalid
    assert '<option value="ARS" selected>' in invalid
    assert "500,00" in invalid


def test_finances_escapes_transaction_content_and_json(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    dangerous = "</script><script>alert(1)</script>"
    with session_factory.begin() as session:
        session.add(
            finance(
                date(2026, 6, 2),
                "gasto",
                "500",
                "ARS",
                dangerous,
                description=dangerous,
            )
        )

    body = client.get("/finanzas").get_data(as_text=True)

    assert dangerous not in body
    assert "&lt;/script&gt;" in body
    assert chart_payload(body)["categories"][0]["category"] == dangerous


def test_finances_empty_state_has_safe_defaults(client: FlaskClient) -> None:
    response = client.get("/finanzas?currency=USD")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'value="2026-06"' in body
    assert "Sin movimientos en este período" in body
    assert chart_payload(body)["categories"] == []


def chart_payload(body: str) -> dict[str, object]:
    match = re.search(
        r'<script id="finance-data" type="application/json">(.*?)</script>', body, re.DOTALL
    )
    assert match is not None
    return json.loads(match.group(1))


def finance(
    day: date,
    kind: str,
    amount: str,
    currency: str,
    category: str,
    *,
    description: str | None = None,
) -> Transaccion:
    return Transaccion(
        fecha=day,
        tipo=kind,
        monto=Decimal(amount),
        moneda=currency,
        categoria=category,
        descripcion=description,
    )
