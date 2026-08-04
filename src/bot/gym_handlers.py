"""Handlers de Telegram para la captura de sesiones de gimnasio."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker
from telegram.error import TelegramError

from src.bot.auth import is_authorized
from src.gym.session_service import CanonicalizerProtocol, GymSessionService

INACTIVITY_LIMIT = timedelta(hours=3)


class GymBotHandlers:
    """Traduce mensajes de Telegram a operaciones sobre la sesión abierta."""

    def __init__(
        self,
        *,
        allowed_chat_id: int | None,
        session_factory: sessionmaker[Session],
        canonicalizer: CanonicalizerProtocol,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.allowed_chat_id = allowed_chat_id
        self.session_factory = session_factory
        self.canonicalizer = canonicalizer
        self.now = now

    async def handle_text(self, update: Any, _: Any) -> None:
        """Procesa un mensaje de captura y responde el estado resultante."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        message = update.effective_message
        if message is None or not message.text:
            return
        with self.session_factory() as session:
            reply = self._service(session).handle(message.text)
            session.commit()
        await message.reply_text(reply)

    async def cancelar(self, update: Any, _: Any) -> None:
        """Descarta la sesión abierta sin guardarla."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        with self.session_factory() as session:
            repository = self._service(session).repository
            open_session = repository.get_open_session()
            if open_session is None:
                reply = "No hay ninguna sesión abierta."
            else:
                repository.delete_session(open_session.id)
                reply = "Sesión cancelada, no se guardó nada."
            session.commit()
        await update.effective_message.reply_text(reply)

    async def estado(self, update: Any, _: Any) -> None:
        """Muestra la sesión en curso y cuántas series lleva."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        with self.session_factory() as session:
            open_session = self._service(session).repository.get_open_session()
            if open_session is None:
                reply = "No hay ninguna sesión abierta."
            else:
                reply = (
                    f"Sesión: {open_session.etiqueta}\nSeries registradas: {len(open_session.sets)}"
                )
        await update.effective_message.reply_text(reply)

    async def close_stale_sessions(self, context: Any) -> None:
        """Cierra sesiones sin actividad y avisa al usuario."""

        with self.session_factory() as session:
            closed = self._service(session).close_stale(self.now() - INACTIVITY_LIMIT)
            session.commit()
        if not closed or self.allowed_chat_id is None:
            return
        try:
            await context.bot.send_message(
                chat_id=self.allowed_chat_id,
                text="Cerré la sesión de gimnasio por inactividad y guardé lo registrado.",
            )
        except TelegramError as error:
            logger.warning("No pude avisar el cierre por inactividad: {}", error)

    def _service(self, session: Session) -> GymSessionService:
        return GymSessionService(session, canonicalizer=self.canonicalizer, now=self.now)
