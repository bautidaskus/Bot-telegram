from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.bot.backup_commands import BotBackup


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.documents: list[tuple[bytes, str]] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)

    async def reply_document(self, document: Any, filename: str) -> None:
        self.documents.append((document.read(), filename))


def update(chat_id: int = 123) -> SimpleNamespace:
    message = FakeMessage()
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=message,
    )


def build_backup(tmp_path: Path) -> tuple[BotBackup, Path]:
    db_path = tmp_path / "tracker.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, valor TEXT)")
    connection.execute("INSERT INTO t (valor) VALUES ('dato')")
    connection.commit()
    connection.close()
    service = BotBackup(
        allowed_chat_id=123,
        db_path=db_path,
        backup_dir=tmp_path / "backups",
        now=lambda: datetime(2026, 6, 9, 3, 0, 0),
    )
    return service, tmp_path / "backups"


@pytest.mark.asyncio
async def test_backup_command_creates_file_and_confirms(tmp_path: Path) -> None:
    service, backup_dir = build_backup(tmp_path)
    target = update()

    await service.backup(target, SimpleNamespace())

    created = list(backup_dir.glob("tracker-*.db"))
    assert len(created) == 1
    assert created[0].name in target.effective_message.replies[0]


@pytest.mark.asyncio
async def test_export_command_sends_valid_db_document(tmp_path: Path) -> None:
    service, _ = build_backup(tmp_path)
    target = update()

    await service.export(target, SimpleNamespace())

    payload, filename = target.effective_message.documents[0]
    assert filename == "tracker.db"
    assert payload[:16] == b"SQLite format 3\x00"


@pytest.mark.asyncio
async def test_unauthorized_backup_is_ignored(tmp_path: Path) -> None:
    service, backup_dir = build_backup(tmp_path)
    target = update(chat_id=999)

    await service.backup(target, SimpleNamespace())

    assert target.effective_message.replies == []
    assert not backup_dir.exists()


@pytest.mark.asyncio
async def test_scheduled_backup_swallows_errors(tmp_path: Path) -> None:
    service = BotBackup(
        allowed_chat_id=123,
        db_path=tmp_path / "missing.db",
        backup_dir=tmp_path / "backups",
        now=lambda: datetime(2026, 6, 9),
    )
    (tmp_path / "missing.db").mkdir()

    await service.scheduled_backup(SimpleNamespace())
