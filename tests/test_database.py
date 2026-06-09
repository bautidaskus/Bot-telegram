from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from src.db.models import (
    Base,
    Ejercicio,
    ErrorLog,
    GymSesion,
    GymSet,
    Pendiente,
    Peso,
    Preview,
    Salud,
    Transaccion,
)
from src.db.session import create_sqlite_engine

EXPECTED_TABLES = {
    "ejercicio",
    "error_log",
    "gym_sesion",
    "gym_set",
    "pendiente",
    "peso",
    "preview",
    "salud",
    "transaccion",
}


def test_sqlite_engine_enables_required_pragmas(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "tracker.db")

    with engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()

    assert foreign_keys == 1
    assert journal_mode == "wal"
    assert busy_timeout == 5000


def test_models_create_all_tables_and_persist_one_row_each(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "tracker.db")
    Base.metadata.create_all(engine)

    session_date = date(2026, 6, 8)
    created_at = datetime(2026, 6, 8, 12, 0)
    with Session(engine) as session:
        transaction = Transaccion(
            fecha=session_date,
            tipo="gasto",
            monto=Decimal("1500.00"),
            moneda="ARS",
            categoria="alimentos",
        )
        gym_session = GymSesion(fecha=session_date, tipo="push")
        exercise = Ejercicio(nombre_canonico="press_banca")
        weight = Peso(fecha=session_date, kg=Decimal("78.40"))
        health = Salud(fecha=session_date, sueno_horas=Decimal("7.50"), animo=8)
        pending = Pendiente(chat_id=123456, mensaje_original="anoté 20")
        preview = Preview(
            id="preview-1",
            chat_id=123456,
            mensaje_original="gasté 1500",
            operaciones_json='{"operaciones": []}',
            estado="pendiente",
            expira_en=created_at + timedelta(minutes=10),
        )
        error = ErrorLog(tipo="test", mensaje="error controlado")
        session.add_all(
            [transaction, gym_session, exercise, weight, health, pending, preview, error]
        )
        session.flush()
        gym_set = GymSet(
            sesion_id=gym_session.id,
            ejercicio_id=exercise.id,
            serie_num=1,
            peso_kg=Decimal("80.00"),
            reps=8,
        )
        session.add(gym_set)
        session.commit()

    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    with Session(engine) as session:
        assert session.query(Transaccion).one().monto == Decimal("1500.00")
        assert session.query(GymSet).one().sesion_id == session.query(GymSesion).one().id
        assert session.query(Ejercicio).one().nombre_canonico == "press_banca"
        assert session.query(Peso).one().kg == Decimal("78.40")
        assert session.query(Salud).one().animo == 8
        assert session.query(Pendiente).one().intentos == 0
        assert session.query(Preview).one().estado == "pendiente"
        assert session.query(ErrorLog).one().tipo == "test"
