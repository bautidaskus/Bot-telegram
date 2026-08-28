"""Check-in nocturno respondido con taps sobre un único mensaje."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from src.bot.auth import is_authorized
from src.bot.callbacks import CheckinCallback, build_checkin_callback, parse_callback
from src.db.repositories import CheckinRepository

SKIP = "-"
WRITE = "w"


@dataclass(frozen=True)
class Step:
    """Una pregunta del check-in y sus opciones."""

    campo: str
    pregunta: str
    opciones: list[str]


STEPS = [
    Step("puntaje_dia", "¿Qué puntaje le das al día?", [str(n) for n in range(1, 11)]),
    Step("animo", "¿Cómo estuvo tu ánimo?", [str(n) for n in range(1, 11)]),
    Step("energia", "¿Y tu energía?", [str(n) for n in range(1, 6)]),
    Step(
        "hora_acostado",
        "¿A qué hora te acostaste anoche?",
        ["<22", "22-23", "23-00", "00-01", "01-02", "+02"],
    ),
    Step("mejor_del_dia", "Lo mejor del día (opcional)", [WRITE, SKIP]),
]
NUMERIC_FIELDS = {"puntaje_dia", "animo", "energia"}


class CheckinFlow:
    """Envía, avanza y persiste el check-in nocturno."""

    def __init__(
        self,
        *,
        allowed_chat_id: int | None,
        session_factory: sessionmaker[Session],
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.allowed_chat_id = allowed_chat_id
        self.session_factory = session_factory
        self.now = now
        self._awaiting_text = False

    async def send_prompt(self, context: Any) -> None:
        """Abre el check-in del día con la primera pregunta."""

        if self.allowed_chat_id is None:
            return
        with self.session_factory() as session:
            CheckinRepository(session).get_or_create(self.now().date())
            session.commit()
        await self._send(context, STEPS[0])

    async def send_reminder(self, context: Any) -> None:
        """Reenvía el check-in solo si sigue pendiente."""

        if self.allowed_chat_id is None:
            return
        with self.session_factory() as session:
            pending = CheckinRepository(session).get_or_create(self.now().date()).estado
            session.commit()
        if pending == "pendiente":
            await self._send(context, STEPS[0], prefix="Te quedó pendiente el check-in.\n")

    async def handle_callback(self, update: Any, _: Any) -> None:
        """Guarda la respuesta y edita el mensaje con la pregunta siguiente."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        query = update.callback_query
        callback = parse_callback(query.data)
        if not isinstance(callback, CheckinCallback):
            return
        await query.answer()
        self._store(callback)
        index = next(i for i, step in enumerate(STEPS) if step.campo == callback.campo)
        if self._awaiting_text:
            await query.edit_message_text("Contame: ¿qué fue lo mejor del día?")
            return
        if index + 1 < len(STEPS):
            step = STEPS[index + 1]
            await query.edit_message_text(step.pregunta, reply_markup=_keyboard(step))
            return
        await query.edit_message_text("Listo, gracias. Buenas noches.")

    async def handle_free_text(self, update: Any, _: Any) -> bool:
        """Consume el texto libre del último paso; devuelve True si lo tomó."""

        if not self._awaiting_text or not is_authorized(update, self.allowed_chat_id):
            return False
        self._awaiting_text = False
        with self.session_factory() as session:
            CheckinRepository(session).update(
                self.now().date(),
                mejor_del_dia=update.effective_message.text,
                estado="completo",
            )
            session.commit()
        await update.effective_message.reply_text("Anotado. Buenas noches.")
        return True

    def _store(self, callback: CheckinCallback) -> None:
        if callback.campo == "mejor_del_dia":
            if callback.valor == WRITE:
                self._awaiting_text = True
                return
            changes: dict[str, Any] = {"estado": "completo"}
        elif callback.campo in NUMERIC_FIELDS:
            changes = {callback.campo: int(callback.valor)}
        else:
            changes = {callback.campo: callback.valor}
        with self.session_factory() as session:
            CheckinRepository(session).update(self.now().date(), **changes)
            session.commit()

    async def _send(self, context: Any, step: Step, prefix: str = "") -> None:
        try:
            await context.bot.send_message(
                chat_id=self.allowed_chat_id,
                text=prefix + step.pregunta,
                reply_markup=_keyboard(step),
            )
        except TelegramError as error:
            logger.warning("No pude mandar el check-in: {}", error)


def _keyboard(step: Step) -> InlineKeyboardMarkup:
    if step.campo == "mejor_del_dia":
        labels = {WRITE: "Escribir", SKIP: "Saltear"}
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        labels[option], callback_data=build_checkin_callback(step.campo, option)
                    )
                    for option in step.opciones
                ]
            ]
        )
    buttons = [
        InlineKeyboardButton(option, callback_data=build_checkin_callback(step.campo, option))
        for option in step.opciones
    ]
    return InlineKeyboardMarkup([buttons[index : index + 5] for index in range(0, len(buttons), 5)])
