from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base, Checkin, Ejercicio, GymSesion, GymSet
from src.db.session import create_sqlite_engine
from src.web.queries import DashboardQueries

TODAY = date(2026, 6, 10)


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "queries.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def training(day: date, etiqueta: str | None, **kwargs: object) -> GymSesion:
    return GymSesion(
        fecha=day,
        etiqueta=etiqueta,
        estado="cerrada",
        ultima_actividad=datetime.combine(day, datetime.min.time()),
        **kwargs,
    )


def queries(session: Session) -> DashboardQueries:
    return DashboardQueries(session, today=lambda: TODAY)


def test_checkin_history_serializes_every_answered_field(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                Checkin(
                    fecha=date(2026, 6, 9),
                    puntaje_dia=8,
                    animo=7,
                    energia=4,
                    hora_acostado="23-00",
                ),
                Checkin(fecha=date(2026, 6, 10), puntaje_dia=6),
            ]
        )

    with session_factory() as session:
        history = queries(session).checkin_history(days=30)

    assert history[0] == {
        "fecha": "2026-06-09",
        "puntaje": 8,
        "animo": 7,
        "energia": 4,
        "hora_acostado": "23-00",
    }
    assert history[1]["animo"] is None


def test_checkin_history_excludes_days_outside_the_window(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                Checkin(fecha=date(2026, 6, 9), puntaje_dia=8),
                Checkin(fecha=date(2026, 4, 1), puntaje_dia=3),
            ]
        )

    with session_factory() as session:
        history = queries(session).checkin_history(days=30)

    assert [item["fecha"] for item in history] == ["2026-06-09"]


def test_checkin_vs_gym_averages_each_group(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                training(date(2026, 6, 9), "pull"),
                training(date(2026, 6, 7), "push"),
                Checkin(fecha=date(2026, 6, 9), puntaje_dia=9),
                Checkin(fecha=date(2026, 6, 7), puntaje_dia=7),
                Checkin(fecha=date(2026, 6, 8), puntaje_dia=5),
                Checkin(fecha=date(2026, 6, 6), puntaje_dia=4),
            ]
        )

    with session_factory() as session:
        result = queries(session).checkin_vs_gym(days=30)

    assert result == {"con_gym": 8.0, "sin_gym": 4.5}


def test_checkin_vs_gym_ignores_unanswered_days(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                training(date(2026, 6, 9), "pull"),
                Checkin(fecha=date(2026, 6, 9), puntaje_dia=9),
                Checkin(fecha=date(2026, 6, 8), puntaje_dia=None),
            ]
        )

    with session_factory() as session:
        result = queries(session).checkin_vs_gym(days=30)

    assert result == {"con_gym": 9.0, "sin_gym": None}


def test_latest_checkin_skips_unanswered_ones(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        session.add_all(
            [
                Checkin(fecha=date(2026, 6, 10), puntaje_dia=None),
                Checkin(fecha=date(2026, 6, 9), puntaje_dia=8, animo=7, energia=3),
            ]
        )

    with session_factory() as session:
        latest = queries(session).latest_checkin()

    assert latest == {"fecha": "2026-06-09", "puntaje": 8, "animo": 7, "energia": 3}


def test_latest_checkin_without_data_is_none(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        assert queries(session).latest_checkin() is None


def test_gym_summary_and_progression_are_serialized_before_session_closes(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        bench = Ejercicio(nombre_canonico="press_banca", grupo_muscular="pecho")
        squat = Ejercicio(nombre_canonico="sentadilla", grupo_muscular="piernas")
        first = training(date(2026, 6, 1), "push", duracion_min=60)
        second = training(date(2026, 6, 8), None, duracion_min=None)
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
        dashboard = queries(session)
        summary = dashboard.gym_summary(date(2026, 6, 1), date(2026, 6, 30), limit=2)
        exercises = dashboard.exercises()
        progression = dashboard.exercise_progression("press_banca")

    assert summary["count"] == 2
    assert summary["sessions"][0]["date"] == "2026-06-08"
    assert summary["sessions"][0]["sets"][0]["exercise"] == "press_banca"
    assert summary["sessions"][1]["label"] == "push"
    assert summary["sessions"][1]["duration_min"] == 60
    assert exercises == ["press_banca", "sentadilla"]
    assert progression == [
        {"date": "2026-06-01", "max_weight": 80.0, "estimated_1rm": 101.33},
        {"date": "2026-06-08", "max_weight": 90.0, "estimated_1rm": 99.17},
    ]


def test_recent_activity_combines_sessions_and_checkins_newest_first(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        bench = Ejercicio(nombre_canonico="press_banca")
        session_row = training(date(2026, 6, 10), "push")
        session.add_all([bench, session_row])
        session.flush()
        session.add_all(
            [
                GymSet(sesion=session_row, ejercicio=bench, serie_num=1, reps=8),
                Checkin(fecha=date(2026, 6, 9), puntaje_dia=8, animo=7, energia=3),
                Checkin(fecha=date(2026, 6, 8), puntaje_dia=6),
            ]
        )

    with session_factory() as session:
        activity = queries(session).recent_activity(limit=3)

    assert [item["kind"] for item in activity] == ["gym", "checkin", "checkin"]
    assert activity[0] == {
        "date": "2026-06-10",
        "kind": "gym",
        "title": "push",
        "detail": "1 series",
    }
    assert activity[1]["detail"] == "Día 8/10 · Ánimo 7/10 · Energía 3/5"
