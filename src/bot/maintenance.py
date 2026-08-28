"""Edición guiada y borrado confirmado de registros."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session, sessionmaker
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.auth import is_authorized
from src.db.models import GymSesion, GymSet

EDITABLE_FIELDS = {
    "sesion": ("fecha", "etiqueta", "duracion_min", "notas"),
    "set": ("peso_kg", "reps", "rpe", "nota"),
}


class MaintenanceError(ValueError):
    """Indica un comando o valor de mantenimiento inválido."""


class BotMaintenance:
    """Gestiona edición y eliminación desde Telegram."""

    def __init__(
        self,
        *,
        allowed_chat_id: int | None,
        session_factory: sessionmaker[Session],
    ) -> None:
        self.allowed_chat_id = allowed_chat_id
        self.session_factory = session_factory

    async def edit(self, update: Any, context: Any) -> None:
        """Presenta los campos editables de un registro."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        try:
            record_type, raw_id = self._parse_target(context.args)
            with self.session_factory() as session:
                self._get_record(session, record_type, raw_id)
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            field,
                            callback_data=_edit_callback(record_type, raw_id, field),
                        )
                    ]
                    for field in EDITABLE_FIELDS[record_type]
                ]
            )
            await update.effective_message.reply_text(
                f"Elegí el campo de {record_type} {raw_id}:", reply_markup=keyboard
            )
        except MaintenanceError as error:
            await update.effective_message.reply_text(str(error))

    async def delete(self, update: Any, context: Any) -> None:
        """Solicita confirmación antes de borrar."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        try:
            record_type, raw_id = self._parse_target(context.args)
            with self.session_factory() as session:
                self._get_record(session, record_type, raw_id)
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Eliminar", callback_data=_delete_callback(record_type, raw_id)
                        ),
                        InlineKeyboardButton("Cancelar", callback_data="m:c"),
                    ]
                ]
            )
            await update.effective_message.reply_text(
                f"Confirmá borrar {record_type} {raw_id}:", reply_markup=keyboard
            )
        except MaintenanceError as error:
            await update.effective_message.reply_text(str(error))

    async def handle_callback(self, update: Any, context: Any) -> None:
        """Procesa selección de campo o confirmación de borrado."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        query = update.callback_query
        if query is None or not query.data:
            return
        await query.answer()
        parts = query.data.split(":")
        if parts == ["m", "c"]:
            await query.edit_message_text("Cancelado")
            return
        if len(parts) == 5 and parts[:2] == ["m", "e"]:
            _, _, record_type, raw_id, field = parts
            if field not in EDITABLE_FIELDS.get(record_type, ()):
                raise MaintenanceError("Campo inválido")
            context.user_data["edit_target"] = (record_type, raw_id, field)
            await query.edit_message_text(f"Mandá el nuevo valor para {field}.")
            return
        if len(parts) == 4 and parts[:2] == ["m", "d"]:
            _, _, record_type, raw_id = parts
            with self.session_factory() as session:
                session.delete(self._get_record(session, record_type, raw_id))
                session.commit()
            await query.edit_message_text("Eliminado")
            return
        raise MaintenanceError("Callback de mantenimiento inválido")

    async def handle_edit_value(self, update: Any, context: Any) -> bool:
        """Aplica el siguiente texto al campo seleccionado."""

        target = context.user_data.get("edit_target")
        if target is None:
            return False
        if not is_authorized(update, self.allowed_chat_id):
            return True
        record_type, raw_id, field = target
        try:
            value = _parse_value(field, update.effective_message.text)
            with self.session_factory() as session:
                record = self._get_record(session, record_type, raw_id)
                setattr(record, field, value)
                session.commit()
            context.user_data.pop("edit_target", None)
            await update.effective_message.reply_text(
                f"Actualizado {record_type} {raw_id}: {field} = {value}"
            )
        except (MaintenanceError, ValueError) as error:
            await update.effective_message.reply_text(f"Valor inválido: {error}")
        return True

    def _parse_target(self, args: list[str]) -> tuple[str, str]:
        if len(args) != 2 or args[0] not in EDITABLE_FIELDS:
            raise MaintenanceError("Uso: /editar|borrar <sesion|set> <id>")
        return args[0], args[1]

    def _get_record(self, session: Session, record_type: str, raw_id: str) -> Any:
        model = GymSesion if record_type == "sesion" else GymSet
        try:
            record = session.get(model, int(raw_id))
        except ValueError as error:
            raise MaintenanceError("ID inválido") from error
        if record is None:
            raise MaintenanceError("Registro no encontrado")
        return record


def _edit_callback(record_type: str, raw_id: str, field: str) -> str:
    return _bounded_callback(f"m:e:{record_type}:{raw_id}:{field}")


def _delete_callback(record_type: str, raw_id: str) -> str:
    return _bounded_callback(f"m:d:{record_type}:{raw_id}")


def _bounded_callback(data: str) -> str:
    if len(data.encode("utf-8")) > 64:
        raise MaintenanceError("Identificador demasiado largo")
    return data


def _parse_value(field: str, raw: str) -> Any:
    value = raw.strip()
    if field == "fecha":
        return date.fromisoformat(value)
    if field in {"peso_kg", "rpe"}:
        try:
            decimal = Decimal(value.replace(",", "."))
        except InvalidOperation as error:
            raise MaintenanceError("se esperaba un número") from error
        if decimal <= 0:
            raise MaintenanceError("el número debe ser positivo")
        if field == "rpe" and not Decimal("1") <= decimal <= Decimal("10"):
            raise MaintenanceError("rpe fuera de rango 1-10")
        return decimal
    if field in {"reps", "duracion_min"}:
        number = int(value)
        if number <= 0:
            raise MaintenanceError("se esperaba un entero positivo")
        return number
    return None if value == "-" else value
