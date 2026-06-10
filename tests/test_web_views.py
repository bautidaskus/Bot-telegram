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

from src.db.models import Base, Ejercicio, GymSesion, GymSet, Peso, Salud, Transaccion
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


def test_gym_selects_exercise_and_renders_progression_and_loaded_sets(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        bench = Ejercicio(nombre_canonico="press_banca")
        squat = Ejercicio(nombre_canonico="sentadilla")
        training = GymSesion(fecha=date(2026, 6, 8), tipo="push", duracion_min=55)
        session.add_all([bench, squat, training])
        session.flush()
        session.add_all(
            [
                GymSet(
                    sesion=training,
                    ejercicio=bench,
                    serie_num=1,
                    peso_kg=Decimal("80"),
                    reps=8,
                ),
                GymSet(
                    sesion=training,
                    ejercicio=squat,
                    serie_num=2,
                    peso_kg=Decimal("100"),
                    reps=5,
                ),
            ]
        )

    response = client.get("/gym?exercise=press_banca")
    body = response.get_data(as_text=True)
    payload = embedded_payload(body, "gym-data")

    assert response.status_code == 200
    assert '<option value="press_banca" selected>' in body
    assert "80,00 kg × 8" in body
    assert payload["progression"] == [
        {"date": "2026-06-08", "estimated_1rm": 101.33, "max_weight": 80.0}
    ]


def test_gym_invalid_exercise_falls_back_to_first_available(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                Ejercicio(nombre_canonico="sentadilla"),
                Ejercicio(nombre_canonico="press_banca"),
            ]
        )

    body = client.get("/gym?exercise=no-existe").get_data(as_text=True)

    assert '<option value="press_banca" selected>' in body


def test_health_accepts_allowed_period_and_serializes_partial_days(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                Peso(fecha=date(2026, 6, 9), kg=Decimal("78.20")),
                Salud(fecha=date(2026, 6, 10), animo=8, agua_l=Decimal("2.50")),
            ]
        )

    response = client.get("/salud?days=90")
    body = response.get_data(as_text=True)
    payload = embedded_payload(body, "health-data")

    assert response.status_code == 200
    assert '<option value="90" selected>' in body
    assert len(payload["history"]) == 90
    assert payload["history"][-2]["weight"] == 78.2
    assert payload["history"][-1]["weight"] is None
    assert payload["history"][-1]["mood"] == 8
    assert "—" in body


def test_health_invalid_period_falls_back_to_thirty_days(client: FlaskClient) -> None:
    body = client.get("/salud?days=7").get_data(as_text=True)

    assert '<option value="30" selected>' in body
    assert len(embedded_payload(body, "health-data")["history"]) == 30


def chart_payload(body: str) -> dict[str, object]:
    return embedded_payload(body, "finance-data")


def embedded_payload(body: str, element_id: str) -> dict[str, object]:
    match = re.search(
        rf'<script id="{element_id}" type="application/json">(.*?)</script>', body, re.DOTALL
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
