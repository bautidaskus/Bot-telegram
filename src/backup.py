"""Copias de seguridad consistentes de la base SQLite."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

BACKUP_PREFIX = "tracker-"
BACKUP_SUFFIX = ".db"


def create_backup(
    db_path: Path,
    backup_dir: Path,
    *,
    now: Callable[[], datetime] = datetime.now,
    retention_days: int = 30,
) -> Path:
    """Genera un snapshot consistente de la base y purga los vencidos.

    Usa la API ``sqlite3.Connection.backup`` para copiar incluso con WAL activo
    y registros sin checkpointear. Devuelve la ruta del archivo creado.
    """

    backup_dir.mkdir(parents=True, exist_ok=True)
    moment = now()
    target = backup_dir / f"{BACKUP_PREFIX}{moment.strftime('%Y%m%d-%H%M%S')}{BACKUP_SUFFIX}"
    with sqlite3.connect(db_path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    prune_backups(backup_dir, retention_days=retention_days, reference=moment)
    return target


def prune_backups(backup_dir: Path, *, retention_days: int, reference: datetime) -> None:
    """Elimina los backups más viejos que ``retention_days`` según su mtime."""

    if retention_days <= 0:
        return
    cutoff = (reference - timedelta(days=retention_days)).timestamp()
    for path in backup_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
