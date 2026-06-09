"""Handlers de texto y callbacks del bot."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from sqlalchemy.orm import Session, sessionmaker
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.ai.whisper_client import MAX_AUDIO_BYTES, EmptyTranscriptionError
from src.bot.auth import is_authorized
from src.bot.callbacks import (
    ClarificationCallback,
    PreviewCallback,
    build_clarification_callback,
    build_preview_callback,
    parse_callback,
)
from src.bot.preview_service import PreviewService
from src.db.repositories import GymRepository
from src.domain.schemas import ParserResponse


class ParserProtocol(Protocol):
    """Parser requerido por los handlers."""

    def parse(self, text: str, exercise_catalog: list[str]) -> ParserResponse:
        """Interpreta texto en operaciones."""


class WhisperProtocol(Protocol):
    """Transcriptor requerido por audio."""

    def transcribe(self, audio_path: Path) -> str:
        """Transcribe un archivo local."""


class AudioConverterProtocol(Protocol):
    """Conversor requerido para formatos no OGG."""

    def convert_to_ogg(self, source: Path, target: Path) -> Path:
        """Convierte un archivo a OGG."""


class BotHandlers:
    """Orquesta Telegram, parser y persistencia."""

    def __init__(
        self,
        *,
        allowed_chat_id: int,
        parser: ParserProtocol,
        whisper: WhisperProtocol | None = None,
        audio_converter: AudioConverterProtocol | None = None,
        session_factory: sessionmaker[Session],
        temp_dir: Path | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.allowed_chat_id = allowed_chat_id
        self.parser = parser
        self.whisper = whisper
        self.audio_converter = audio_converter
        self.session_factory = session_factory
        self.temp_dir = temp_dir
        self.now = now

    async def handle_text(self, update: Any, _: Any) -> None:
        """Convierte un mensaje autorizado en preview o aclaración."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        message = update.effective_message
        if message is None or not message.text:
            return
        await self._create_preview_from_text(
            update,
            message.text,
            original_text=message.text,
        )

    async def _create_preview_from_text(
        self,
        update: Any,
        parse_text: str,
        *,
        original_text: str,
        transcription: str | None = None,
        heading: str = "",
    ) -> None:
        message = update.effective_message
        with self.session_factory() as session:
            catalog = [item.nombre_canonico for item in GymRepository(session).list_exercises()]
        parsed = await asyncio.to_thread(self.parser.parse, parse_text, catalog)
        requires_clarification = any(
            operation.tipo == "ambiguo" or operation.confianza < 0.7
            for operation in parsed.operaciones
        )
        if requires_clarification:
            with self.session_factory() as session:
                service = PreviewService(session)
                pending = service.store_ambiguity(
                    chat_id=update.effective_chat.id,
                    original_text=original_text,
                    transcription=transcription,
                    parsed=parsed,
                )
                suggestions = _collect_suggestions(parsed)
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                suggestion,
                                callback_data=build_clarification_callback(pending.id, suggestion),
                            )
                            for suggestion in suggestions
                        ]
                    ]
                )
                session.commit()
            await message.reply_text("Necesito una aclaración:", reply_markup=keyboard)
            return
        with self.session_factory() as session:
            service = PreviewService(session)
            preview = service.create(
                chat_id=update.effective_chat.id,
                message_id=None,
                original_text=original_text,
                transcription=transcription,
                parsed=parsed,
                now=self.now(),
            )
            keyboard = _preview_keyboard(preview.id)
            session.commit()
        sent_message = await message.reply_text(
            heading + _render_preview(parsed), reply_markup=keyboard
        )
        with self.session_factory() as session:
            PreviewService(session).attach_message(preview.id, sent_message.message_id)
            session.commit()

    async def handle_callback(self, update: Any, _: Any) -> None:
        """Ejecuta una acción inline autorizada."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        query = update.callback_query
        if query is None or query.data is None:
            return
        await query.answer()
        callback = parse_callback(query.data)
        if isinstance(callback, ClarificationCallback):
            await self._handle_clarification(query, callback)
            return
        await self._handle_preview_action(query, callback)

    async def handle_audio(self, update: Any, _: Any) -> None:
        """Transcribe voice/audio y crea un preview verificable."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        message = update.effective_message
        media = message.voice or message.audio
        if media is None or self.whisper is None or self.audio_converter is None:
            return
        if media.file_size and media.file_size > MAX_AUDIO_BYTES:
            await message.reply_text("El audio supera el límite de 20 MB.")
            return
        suffix = ".ogg" if message.voice else Path(media.file_name or "audio.bin").suffix
        with TemporaryDirectory(dir=self.temp_dir) as directory:
            source = Path(directory) / f"source{suffix}"
            telegram_file = await media.get_file()
            await telegram_file.download_to_drive(custom_path=source)
            transcription_path = source
            if message.audio:
                transcription_path = await asyncio.to_thread(
                    self.audio_converter.convert_to_ogg, source, Path(directory) / "converted.ogg"
                )
            try:
                transcription = await asyncio.to_thread(self.whisper.transcribe, transcription_path)
            except EmptyTranscriptionError:
                await message.reply_text("No entendí el audio, ¿podés reescribirlo?")
                return
            await self._create_preview_from_text(
                update,
                transcription,
                original_text=transcription,
                transcription=transcription,
                heading=f"Transcripción: {transcription}\n\n",
            )

    async def _handle_preview_action(self, query: Any, callback: PreviewCallback) -> None:
        if callback.action == "corregir":
            await query.edit_message_text(
                "Corrección guiada pendiente. Usá /editar cuando esté disponible."
            )
            return
        with self.session_factory() as session:
            service = PreviewService(session)
            if callback.action == "guardar":
                saved = service.confirm(callback.preview_id, now=self.now())
                session.commit()
                lines = ["Guardado"] + [f"{item.kind}: {item.identifier}" for item in saved]
                response = "\n".join(lines)
            else:
                service.cancel(callback.preview_id, now=self.now())
                session.commit()
                response = "Cancelado"
        await query.edit_message_text(response)

    async def _handle_clarification(self, query: Any, callback: ClarificationCallback) -> None:
        with self.session_factory() as session:
            service = PreviewService(session)
            clarification = service.get_ambiguity_context(callback.pending_id, hint=callback.hint)
            catalog = [item.nombre_canonico for item in GymRepository(session).list_exercises()]
        parse_text = f"{clarification.original_text}\nTipo confirmado: {clarification.hint}"
        parsed = await asyncio.to_thread(self.parser.parse, parse_text, catalog)
        with self.session_factory() as session:
            service = PreviewService(session)
            service.resolve_ambiguity(callback.pending_id, hint=callback.hint)
            preview = service.create(
                chat_id=self.allowed_chat_id,
                message_id=query.message.message_id,
                original_text=clarification.original_text,
                transcription=clarification.transcription,
                parsed=parsed,
                now=self.now(),
            )
            session.commit()
        await query.edit_message_text(
            _render_preview(parsed),
            reply_markup=_preview_keyboard(preview.id),
        )


def _preview_keyboard(preview_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Guardar", callback_data=build_preview_callback("guardar", preview_id)
                ),
                InlineKeyboardButton(
                    "Cancelar", callback_data=build_preview_callback("cancelar", preview_id)
                ),
                InlineKeyboardButton(
                    "Corregir", callback_data=build_preview_callback("corregir", preview_id)
                ),
            ]
        ]
    )


def _render_preview(parsed: ParserResponse) -> str:
    lines = ["Esto fue lo que entendí:"]
    for index, operation in enumerate(parsed.operaciones, start=1):
        data = operation.datos.model_dump(exclude_none=True)
        if operation.tipo in {"gasto", "ingreso"}:
            amount = _format_decimal(data["monto"])
            lines.append(f"{index}. {operation.tipo.title()}: ${amount} ({data['categoria']})")
        elif operation.tipo == "peso":
            lines.append(f"{index}. Peso: {_format_decimal(data['kg'])} kg")
        elif operation.tipo == "salud":
            lines.append(f"{index}. Salud: {data}")
        else:
            lines.append(f"{index}. {operation.tipo.title()}: {data}")
    return "\n".join(lines)


def _format_decimal(value: Decimal) -> str:
    return (
        f"{value:,.2f}".replace(",", "_")
        .replace(".", ",")
        .replace("_", ".")
        .rstrip("0")
        .rstrip(",")
    )


def _collect_suggestions(parsed: ParserResponse) -> list[Any]:
    suggestions: list[Any] = []
    for operation in parsed.operaciones:
        if operation.tipo == "ambiguo":
            suggestions.extend(operation.datos.sugerencias)
        elif operation.confianza < 0.7:
            suggestions.append(operation.tipo)
    return list(dict.fromkeys(suggestions))
