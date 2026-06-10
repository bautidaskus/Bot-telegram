from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, Ejercicio, GymSesion, GymSet, Peso, Salud, Transaccion
from src.db.session import create_sqlite_engine
from src.web.queries import DashboardQueries


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "queries.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def test_month_summary_keeps_currencies_separate_and_handles_year_boundary(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                transaction(date(2025, 12, 31), "ingreso", "100.00", "ARS", "sueldo"),
                transaction(date(2026, 1, 1), "ingreso", "1000.00", "ARS", "sueldo"),
                transaction(date(2026, 1, 5), "gasto", "250.00", "ARS", "comida"),
                transaction(date(2026, 1, 8), "gasto", "10.00", "USD", "software"),
                transaction(date(2026, 2, 1), "gasto", "99.00", "ARS", "comida"),
            ]
        )

    with session_factory() as session:
        result = DashboardQueries(session).month_summary(date(2026, 1, 15))

    assert result == [
        {"currency": "ARS", "income": 1000.0, "expenses": 250.0, "balance": 750.0},
        {"currency": "USD", "income": 0.0, "expenses": 10.0, "balance": -10.0},
    ]


def test_finance_month_includes_empty_days_categories_and_optional_fields(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                transaction(date(2026, 6, 1), "ingreso", "3000", "ARS", "sueldo"),
                transaction(
                    date(2026, 6, 2),
                    "gasto",
                    "500",
                    "ARS",
                    "comida",
                    description="mercado",
                ),
                transaction(date(2026, 6, 2), "gasto", "100", "ARS", "transporte"),
                transaction(date(2026, 6, 3), "gasto", "20", "USD", "software"),
            ]
        )

    with session_factory() as session:
        result = DashboardQueries(session).finance_month(date(2026, 6, 10), "ARS")

    assert result["available_currencies"] == ["ARS", "USD"]
    assert result["summary"] == {"income": 3000.0, "expenses": 600.0, "balance": 2400.0}
    assert result["daily"][:3] == [
        {"date": "2026-06-01", "income": 3000.0, "expenses": 0.0},
        {"date": "2026-06-02", "income": 0.0, "expenses": 600.0},
        {"date": "2026-06-03", "income": 0.0, "expenses": 0.0},
    ]
    assert result["categories"] == [
        {"category": "comida", "amount": 500.0},
        {"category": "transporte", "amount": 100.0},
    ]
    assert result["transactions"][1]["description"] == "mercado"
    assert result["transactions"][2]["description"] is None


def test_weight_history_uses_calendar_window_and_keeps_days_without_data(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                Peso(fecha=date(2026, 6, 1), kg=Decimal("80.00")),
                Peso(fecha=date(2026, 6, 7), kg=Decimal("79.00")),
                Peso(fecha=date(2026, 6, 8), kg=Decimal("78.00")),
            ]
        )

    with session_factory() as session:
        queries = DashboardQueries(session)
        latest = queries.latest_weight()
        history = queries.health_history(date(2026, 6, 6), date(2026, 6, 8))

    assert latest == {"date": "2026-06-08", "kg": 78.0, "average_7d": 78.5}
    assert [point["date"] for point in history] == ["2026-06-06", "2026-06-07", "2026-06-08"]
    assert history[0]["weight"] is None
    assert history[1]["weight_average_7d"] == 79.5
    assert history[2]["weight_average_7d"] == 78.5


def test_health_averages_ignore_missing_fields_and_history_is_chronological(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                Salud(
                    fecha=date(2026, 6, 8),
                    sueno_horas=Decimal("6.00"),
                    animo=6,
                    energia=None,
                    agua_l=Decimal("2.00"),
                ),
                Salud(
                    fecha=date(2026, 6, 10),
                    sueno_horas=Decimal("8.00"),
                    animo=8,
                    energia=7,
                    agua_l=None,
                ),
            ]
        )

    with session_factory() as session:
        queries = DashboardQueries(session)
        averages = queries.health_averages(date(2026, 6, 10), days=7)
        history = queries.health_history(date(2026, 6, 8), date(2026, 6, 10))

    assert averages == {
        "sleep_hours": 7.0,
        "sleep_quality": None,
        "mood": 7.0,
        "energy": 7.0,
        "water_l": 2.0,
    }
    assert [point["date"] for point in history] == ["2026-06-08", "2026-06-09", "2026-06-10"]
    assert history[1] == {
        "date": "2026-06-09",
        "weight": None,
        "weight_average_7d": None,
        "sleep_hours": None,
        "sleep_quality": None,
        "mood": None,
        "energy": None,
        "water_l": None,
    }


def test_gym_summary_and_progression_are_serialized_before_session_closes(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        bench = Ejercicio(nombre_canonico="press_banca", grupo_muscular="pecho")
        squat = Ejercicio(nombre_canonico="sentadilla", grupo_muscular="piernas")
        first = GymSesion(fecha=date(2026, 6, 1), tipo="push", duracion_min=60)
        second = GymSesion(fecha=date(2026, 6, 8), tipo=None, duracion_min=None)
        session.add_all([bench, squat, first, second])
        session.flush()
        session.add_all(
            [
                GymSet(sesion=first, ejercicio=bench, serie_num=1, peso_kg=Decimal("80"), reps=8),
                GymSet(sesion=first, ejercicio=squat, serie_num=2, peso_kg=None, reps=10),
                GymSet(sesion=second, ejercicio=bench, serie_num=1, peso_kg=Decimal("85"), reps=5),
                GymSet(
                    sesion=second, ejercicio=bench, serie_num=2, peso_kg=Decimal("90"), reps=None
                ),
            ]
        )

    with session_factory() as session:
        queries = DashboardQueries(session)
        summary = queries.gym_summary(date(2026, 6, 1), date(2026, 6, 30), limit=2)
        exercises = queries.exercises()
        progression = queries.exercise_progression("press_banca")

    assert summary["count"] == 2
    assert summary["sessions"][0]["date"] == "2026-06-08"
    assert summary["sessions"][0]["sets"][0]["exercise"] == "press_banca"
    assert summary["sessions"][1]["duration_min"] == 60
    assert exercises == ["press_banca", "sentadilla"]
    assert progression == [
        {"date": "2026-06-01", "max_weight": 80.0, "estimated_1rm": 101.33},
        {"date": "2026-06-08", "max_weight": 90.0, "estimated_1rm": 99.17},
    ]


def test_recent_activity_combines_domains_in_reverse_chronological_order(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                transaction(date(2026, 6, 7), "gasto", "500", "ARS", "comida"),
                Peso(fecha=date(2026, 6, 8), kg=Decimal("78.40")),
                Salud(fecha=date(2026, 6, 9), animo=8),
                GymSesion(fecha=date(2026, 6, 10), tipo="push"),
            ]
        )

    with session_factory() as session:
        activity = DashboardQueries(session).recent_activity(limit=3)

    assert [item["kind"] for item in activity] == ["gym", "health", "weight"]
    assert activity[0]["date"] == "2026-06-10"


def transaction(
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
