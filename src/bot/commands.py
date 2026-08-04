"""Comandos de consulta del bot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.bot.auth import is_authorized
from src.db.models import Ejercicio, GymSesion, GymSet
from src.db.repositories import CheckinRepository, GymRepository


class BotCommands:
    """Consultas de solo lectura expuestas como comandos Telegram."""

    def __init__(
        self,
        *,
        allowed_chat_id: int | None,
        session_factory: sessionmaker[Session],
        today: Callable[[], date] = date.today,
    ) -> None:
        self.allowed_chat_id = allowed_chat_id
        self.session_factory = session_factory
        self.today_provider = today

    async def start(self, update: Any, _: Any) -> None:
        """Muestra una introducción breve."""

        await self._reply(
            update,
            "Gym Tracker\n"
            "Mandame el nombre de la sesión para abrirla, después el ejercicio y las reps.\n"
            "Ejemplo: espalda biceps → dominadas → 7 → remo t 60 → 10 → fin\n"
            "Consultas: /hoy /gym /sesiones /estado",
        )

    async def help(self, update: Any, _: Any) -> None:
        """Lista la sintaxis disponible."""

        await self._reply(
            update,
            "Captura:\n"
            "  primer mensaje = etiqueta de la sesión\n"
            "  «remo t 60» fija ejercicio y peso, «10» o «10 8 6» registra series\n"
            "  «60x10» fuerza el peso de una serie, «deshacer» borra la última\n"
            "  «fin» cierra la sesión\n"
            "Comandos:\n"
            "/hoy\n/gym [ejercicio]\n/sesiones [n]\n/estado\n/cancelar\n"
            "/editar <tipo> <id>\n/borrar <tipo> <id>\n/export\n/backup",
        )

    async def gym(self, update: Any, context: Any) -> None:
        """Muestra la última sesión o la progresión de un ejercicio."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        with self.session_factory() as session:
            if context.args:
                text = self._exercise_progress(session, "_".join(context.args).lower())
            else:
                statement = (
                    select(GymSesion)
                    .options(selectinload(GymSesion.sets).selectinload(GymSet.ejercicio))
                    .order_by(GymSesion.fecha.desc(), GymSesion.id.desc())
                    .limit(1)
                )
                text = self._render_gym_session(session.scalar(statement))
        await update.effective_message.reply_text(text)

    async def sessions(self, update: Any, context: Any) -> None:
        """Lista sesiones recientes de gimnasio."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        limit = _bounded_int(context.args[0] if context.args else None, default=5, maximum=30)
        with self.session_factory() as session:
            items = GymRepository(session).list_sessions(limit)
            lines = [
                f"#{item.id} {item.fecha.isoformat()} {item.etiqueta or 'libre'} "
                f"- {len(item.sets)} series"
                for item in items
            ]
        await update.effective_message.reply_text("\n".join(lines) or "No hay sesiones.")

    async def today(self, update: Any, _: Any) -> None:
        """Resume la sesión de gimnasio y el check-in del día."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        target = self.today_provider()
        with self.session_factory() as session:
            sessions = [
                item for item in GymRepository(session).list_sessions(5) if item.fecha == target
            ]
            checkin = CheckinRepository(session).get_or_create(target)
            lines = [f"Hoy {target.isoformat()}"]
            lines.extend(
                f"Gimnasio: {item.etiqueta or 'libre'} — {len(item.sets)} series"
                for item in sessions
            )
            if not sessions:
                lines.append("Gimnasio: sin registro")
            if checkin.puntaje_dia is None:
                lines.append("Check-in: pendiente")
            else:
                lines.append(f"Día: {checkin.puntaje_dia}/10, ánimo {checkin.animo}")
            session.commit()
        await update.effective_message.reply_text("\n".join(lines))

    async def _reply(self, update: Any, text: str) -> None:
        if is_authorized(update, self.allowed_chat_id):
            await update.effective_message.reply_text(text)

    def _exercise_progress(self, session: Session, canonical_name: str) -> str:
        statement = (
            select(GymSesion.fecha, GymSet.peso_kg, GymSet.reps)
            .join(GymSet, GymSet.sesion_id == GymSesion.id)
            .join(Ejercicio, Ejercicio.id == GymSet.ejercicio_id)
            .where(Ejercicio.nombre_canonico == canonical_name)
            .order_by(GymSesion.fecha.desc())
        )
        rows = list(session.execute(statement))
        if not rows:
            return f"No hay datos para {canonical_name}."
        lines = [canonical_name]
        for row in rows:
            one_rm = Decimal(row.peso_kg or 0) * (Decimal(1) + Decimal(row.reps or 0) / 30)
            lines.append(
                f"{row.fecha.isoformat()}: {_decimal(row.peso_kg or 0)} kg x {row.reps or 0} "
                f"- 1RM {_decimal(one_rm)} kg"
            )
        return "\n".join(lines)

    def _render_gym_session(self, gym_session: GymSesion | None) -> str:
        if gym_session is None:
            return "No hay sesiones de gimnasio."
        lines = [
            f"{gym_session.fecha.isoformat()} - {gym_session.etiqueta or 'libre'}"
            + (f" - {gym_session.duracion_min} min" if gym_session.duracion_min else "")
        ]
        lines.extend(
            f"{item.ejercicio.nombre_canonico}: {_decimal(item.peso_kg or 0)} kg x {item.reps or 0}"
            for item in gym_session.sets
        )
        return "\n".join(lines)


def _decimal(value: Decimal | int | float) -> str:
    text = f"{Decimal(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return text.rstrip("0").rstrip(",")


def _bounded_int(raw: str | None, *, default: int, maximum: int) -> int:
    value = int(raw) if raw is not None else default
    return max(1, min(value, maximum))
