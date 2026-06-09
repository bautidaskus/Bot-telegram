from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from src.backup import BACKUP_PREFIX, BACKUP_SUFFIX, create_backup, prune_backups


def _seed_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, valor TEXT)")
    connection.execute("INSERT INTO t (valor) VALUES ('hola')")
    connection.commit()
    connection.close()


def test_create_backup_produces_valid_readable_copy(tmp_path: Path) -> None:
    db_path = tmp_path / "tracker.db"
    _seed_db(db_path)
    backup_dir = tmp_path / "backups"

    target = create_backup(db_path, backup_dir, now=lambda: datetime(2026, 6, 9, 3, 0, 0))

    assert target.name == f"{BACKUP_PREFIX}20260609-030000{BACKUP_SUFFIX}"
    assert target.parent == backup_dir
    copy = sqlite3.connect(target)
    assert copy.execute("SELECT valor FROM t").fetchone() == ("hola",)
    copy.close()


def test_create_backup_captures_uncheckpointed_wal_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "tracker.db"
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, valor TEXT)")
    connection.execute("INSERT INTO t (valor) VALUES ('sin_checkpoint')")
    connection.commit()

    target = create_backup(db_path, tmp_path / "backups", now=lambda: datetime(2026, 6, 9))
    connection.close()

    copy = sqlite3.connect(target)
    assert copy.execute("SELECT valor FROM t").fetchone() == ("sin_checkpoint",)
    copy.close()


def test_prune_removes_only_expired_backups(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    reference = datetime(2026, 6, 9)
    old = backup_dir / f"{BACKUP_PREFIX}old{BACKUP_SUFFIX}"
    recent = backup_dir / f"{BACKUP_PREFIX}recent{BACKUP_SUFFIX}"
    unrelated = backup_dir / "otro.txt"
    for path in (old, recent, unrelated):
        path.write_text("x")
    old_mtime = datetime(2026, 4, 1).timestamp()
    os.utime(old, (old_mtime, old_mtime))

    prune_backups(backup_dir, retention_days=30, reference=reference)

    assert not old.exists()
    assert recent.exists()
    assert unrelated.exists()
