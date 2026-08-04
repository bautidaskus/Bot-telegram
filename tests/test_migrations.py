from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from tests.test_database import EXPECTED_TABLES


def _run_alembic(db_path: Path, *args: str) -> None:
    """Corre un comando de alembic contra `db_path` y falla si no sale limpio."""

    environment = {**os.environ, "DB_PATH": str(db_path)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_alembic_upgrade_head_creates_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "migrated.db"
    env = os.environ | {"DB_PATH": str(db_path)}

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert set(inspect(create_engine(f"sqlite:///{db_path.as_posix()}")).get_table_names()) == (
        EXPECTED_TABLES | {"alembic_version"}
    )

    check_result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
    )
    assert check_result.returncode == 0, check_result.stdout + check_result.stderr


def test_upgrade_drops_finance_and_adds_checkin(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate.db"
    _run_alembic(db_path, "upgrade", "20260608_01")
    with sqlite3.connect(db_path) as connection:
        connection.execute("INSERT INTO gym_sesion (fecha, tipo) VALUES ('2026-08-01', 'push')")
        connection.commit()

    _run_alembic(db_path, "upgrade", "head")

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"transaccion", "peso", "salud"}.isdisjoint(tables)
        assert "checkin" in tables
        columns = {row[1] for row in connection.execute("PRAGMA table_info(gym_sesion)")}
        assert {
            "etiqueta",
            "estado",
            "ejercicio_actual_id",
            "peso_actual",
            "ultima_actividad",
        } <= columns
        assert "tipo" not in columns
        assert connection.execute("SELECT COUNT(*) FROM gym_sesion").fetchone()[0] == 1
