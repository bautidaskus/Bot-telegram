"""Creación y configuración de conexiones SQLite."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def create_sqlite_engine(db_path: Path) -> Engine:
    """Crea un engine SQLite configurado para uso local concurrente."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection: sqlite3.Connection, _: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine
