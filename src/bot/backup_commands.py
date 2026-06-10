"""Comandos de backup y exportación de la base."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from src.backup import create_backup
from src.bot.auth import is_authorized


class BotBackup:
    """Expone respaldo manual, exportación y job nocturno."""

    def __init__(
        self,
        *,
        allowed_chat_id: int | None,
        db_path: Path,
        backup_dir: Path,
        retention_days: int = 30,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.allowed_chat_id = allowed_chat_id
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.retention_days = retention_days
        self.now = now

    async def backup(self, update: Any, _: Any) -> None:
        """Fuerza un backup manual y responde con la ruta generada."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        target = await self._run_backup()
        await update.effective_message.reply_text(f"Backup creado: {target.name}")

    async def export(self, update: Any, _: Any) -> None:
        """Envía un snapshot consistente de la base como adjunto."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        target = await self._run_backup()
        with target.open("rb") as document:
            await update.effective_message.reply_document(document=document, filename="tracker.db")

    async def scheduled_backup(self, _: Any) -> None:
        """Callback del job nocturno; nunca propaga errores al scheduler."""

        try:
            target = await self._run_backup()
            logger.info("Backup nocturno creado: {}", target.name)
        except (OSError, sqlite3.Error) as error:
            logger.error("Backup nocturno falló: {}", error)

    async def _run_backup(self) -> Path:
        return await asyncio.to_thread(
            create_backup,
            self.db_path,
            self.backup_dir,
            now=self.now,
            retention_days=self.retention_days,
        )
