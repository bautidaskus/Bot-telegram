from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, Checkin, Ejercicio, GymSesion, GymSet
from src.db.session import create_sqlite_engine
from src.web import create_app

TODAY = date(2026, 6, 10)


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "views.db")
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


def training(day: date, etiqueta: str, **kwargs: object) -> GymSesion:
    return GymSesion(
        fecha=day,
        etiqueta=etiqueta,
        estado="cerrada",
        ultima_actividad=datetime.combine(day, datetime.min.time()),
        **kwargs,
    )


def test_summary_renders_gym_count_and_latest_checkin(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                training(TODAY, "push"),
                Checkin(fecha=date(2026, 6, 9), puntaje_dia=8, animo=7, estado="completo"),
            ]
        )

    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "1 sesión" in body
    assert "8/10" in body
    assert "Actividad reciente" in body


def test_summary_contrasts_days_with_and_without_gym(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                training(date(2026, 6, 9), "pull"),
                Checkin(fecha=date(2026, 6, 9), puntaje_dia=9, estado="completo"),
                Checkin(fecha=date(2026, 6, 8), puntaje_dia=5, estado="completo"),
            ]
        )

    body = client.get("/").get_data(as_text=True)

    assert "9,00 vs. 5,00" in body


def test_gym_selects_exercise_and_renders_progression_and_loaded_sets(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        bench = Ejercicio(nombre_canonico="press_banca")
        squat = Ejercicio(nombre_canonico="sentadilla")
        session_row = training(date(2026, 6, 8), "push", duracion_min=55)
        session.add_all([bench, squat, session_row])
        session.flush()
        session.add_all(
            [
                GymSet(
                    sesion=session_row, ejercicio=bench, serie_num=1, peso_kg=Decimal("80"), reps=8
                ),
                GymSet(
                    sesion=session_row, ejercicio=squat, serie_num=2, peso_kg=Decimal("100"), reps=5
                ),
            ]
        )

    response = client.get("/gym?exercise=press_banca")
    body = response.get_data(as_text=True)
    payload = embedded_payload(body, "gym-data")

    assert response.status_code == 200
    assert '<option value="press_banca" selected>' in body
    assert "80,00 kg × 8" in body
    assert "push" in body
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


def test_checkin_accepts_allowed_period_and_serializes_partial_days(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                Checkin(fecha=date(2026, 6, 9), puntaje_dia=8, animo=7, energia=4),
                Checkin(fecha=date(2026, 6, 10), puntaje_dia=6, hora_acostado="23-00"),
            ]
        )

    response = client.get("/checkin?days=90")
    body = response.get_data(as_text=True)
    payload = embedded_payload(body, "checkin-data")

    assert response.status_code == 200
    assert '<option value="90" selected>' in body
    assert [item["fecha"] for item in payload["history"]] == ["2026-06-09", "2026-06-10"]
    assert payload["history"][0]["energia"] == 4
    assert payload["history"][1]["energia"] is None
    assert "23-00" in body
    assert "—" in body


def test_checkin_invalid_period_falls_back_to_thirty_days(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory.begin() as session:
        session.add(Checkin(fecha=date(2026, 4, 1), puntaje_dia=7))

    body = client.get("/checkin?days=7").get_data(as_text=True)

    assert '<option value="30" selected>' in body
    assert embedded_payload(body, "checkin-data")["history"] == []


def test_checkin_escapes_free_text(
    client: FlaskClient, session_factory: sessionmaker[Session]
) -> None:
    dangerous = "</script><script>alert(1)</script>"
    with session_factory.begin() as session:
        session.add(Checkin(fecha=date(2026, 6, 9), puntaje_dia=8, hora_acostado=dangerous))

    body = client.get("/checkin").get_data(as_text=True)

    assert dangerous not in body
    assert "&lt;/script&gt;" in body
    assert embedded_payload(body, "checkin-data")["history"][0]["hora_acostado"] == dangerous


def embedded_payload(body: str, element_id: str) -> dict[str, object]:
    match = re.search(
        rf'<script id="{element_id}" type="application/json">(.*?)</script>', body, re.DOTALL
    )
    assert match is not None
    return json.loads(match.group(1))
