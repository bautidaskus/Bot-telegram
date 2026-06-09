"""Comandos de consulta y mantenimiento del bot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from src.bot.auth import is_authorized
from src.db.models import Ejercicio, GymSesion, GymSet, Peso, Salud, Transaccion


class BotCommands:
    """Consultas de solo lectura expuestas como comandos Telegram."""

    def __init__(
        self,
        *,
        allowed_chat_id: int,
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
            "Personal Tracker\n"
            "Mandame texto o audio para registrar datos.\n"
            "Consultas: /hoy /balance /gastos /ingresos /gym /peso /salud",
        )

    async def help(self, update: Any, _: Any) -> None:
        """Lista la sintaxis disponible."""

        await self._reply(
            update,
            "/balance [mes] [año]\n/gastos [categoria]\n/ingresos [mes] [año]\n"
            "/ultimos [n]\n/gym [ejercicio]\n/sesiones [n]\n/peso [historial]\n"
            "/salud\n/hoy\n/editar <tipo> <id>\n/borrar <tipo> <id>",
        )

    async def balance(self, update: Any, context: Any) -> None:
        """Resume ingresos, gastos y balance mensual."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        try:
            month, year = self._month_year(context.args)
        except (ValueError, IndexError):
            await update.effective_message.reply_text("Uso: /balance [mes] [año]")
            return
        with self.session_factory() as session:
            income = self._finance_total(session, "ingreso", month, year)
            expenses = self._finance_total(session, "gasto", month, year)
        await update.effective_message.reply_text(
            f"Balance {month:02d}/{year}\nIngresos: {_money(income)}\n"
            f"Gastos: {_money(expenses)}\nBalance: {_money(income - expenses)}"
        )

    async def gastos(self, update: Any, context: Any) -> None:
        """Agrupa gastos por categoría o detalla una categoría."""

        await self._finance_breakdown(update, context, "gasto")

    async def ingresos(self, update: Any, context: Any) -> None:
        """Agrupa ingresos del mes solicitado."""

        await self._finance_breakdown(update, context, "ingreso")

    async def ultimos(self, update: Any, context: Any) -> None:
        """Lista las últimas transacciones."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        limit = _bounded_int(context.args[0] if context.args else None, default=5, maximum=50)
        statement = select(Transaccion).order_by(Transaccion.fecha.desc(), Transaccion.id.desc())
        with self.session_factory() as session:
            transactions = list(session.scalars(statement.limit(limit)))
        lines = [
            f"#{item.id} {item.fecha.isoformat()} {item.tipo}: {_money(item.monto)} "
            f"{item.categoria} {item.descripcion or ''}".rstrip()
            for item in transactions
        ]
        await update.effective_message.reply_text("\n".join(lines) or "No hay transacciones.")

    async def gym(self, update: Any, context: Any) -> None:
        """Muestra la última sesión o progresión de un ejercicio."""

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
                gym_session = session.scalar(statement)
                text = self._render_gym_session(gym_session)
        await update.effective_message.reply_text(text)

    async def sessions(self, update: Any, context: Any) -> None:
        """Lista sesiones recientes de gimnasio."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        limit = _bounded_int(context.args[0] if context.args else None, default=5, maximum=30)
        statement = select(GymSesion).order_by(GymSesion.fecha.desc(), GymSesion.id.desc())
        with self.session_factory() as session:
            items = list(session.scalars(statement.limit(limit)))
        lines = [
            f"#{item.id} {item.fecha.isoformat()} {item.tipo or 'libre'}"
            + (f" - {item.duracion_min} min" if item.duracion_min else "")
            for item in items
        ]
        await update.effective_message.reply_text("\n".join(lines) or "No hay sesiones.")

    async def weight(self, update: Any, context: Any) -> None:
        """Muestra peso actual, tendencia o historial."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        statement = select(Peso).order_by(Peso.fecha.desc()).limit(30)
        with self.session_factory() as session:
            weights = list(session.scalars(statement))
        if not weights:
            text = "No hay registros de peso."
        elif context.args and context.args[0].lower() == "historial":
            text = "\n".join(
                f"{item.fecha.isoformat()}: {_decimal(item.kg)} kg" for item in weights
            )
        else:
            latest = weights[0]
            baseline = weights[-1]
            trend = latest.kg - baseline.kg
            moving_average = sum(
                item.kg for item in weights if item.fecha >= latest.fecha - timedelta(days=6)
            )
            moving_count = sum(
                1 for item in weights if item.fecha >= latest.fecha - timedelta(days=6)
            )
            text = (
                f"Peso: {_decimal(latest.kg)} kg ({latest.fecha.isoformat()})\n"
                f"Media móvil 7 días: {_decimal(moving_average / moving_count)} kg\n"
                f"Tendencia: {trend:+.2f} kg"
            )
        await update.effective_message.reply_text(text)

    async def health(self, update: Any, _: Any) -> None:
        """Calcula promedios de salud de los últimos siete días."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        since = self.today_provider() - timedelta(days=6)
        statement = select(Salud).where(Salud.fecha >= since)
        with self.session_factory() as session:
            items = list(session.scalars(statement))
        if not items:
            await update.effective_message.reply_text("No hay registros de salud.")
            return
        parts = ["Salud últimos 7 días"]
        for label, field, suffix in (
            ("Sueño", "sueno_horas", " h"),
            ("Ánimo", "animo", ""),
            ("Energía", "energia", ""),
            ("Agua", "agua_l", " l"),
        ):
            values = [getattr(item, field) for item in items if getattr(item, field) is not None]
            if values:
                average = sum(Decimal(value) for value in values) / len(values)
                parts.append(f"{label}: {_decimal(average)}{suffix}")
        await update.effective_message.reply_text("\n".join(parts))

    async def today(self, update: Any, _: Any) -> None:
        """Resume todos los dominios para la fecha actual."""

        if not is_authorized(update, self.allowed_chat_id):
            return
        target = self.today_provider()
        with self.session_factory() as session:
            expenses = session.scalar(
                select(func.coalesce(func.sum(Transaccion.monto), 0)).where(
                    Transaccion.fecha == target, Transaccion.tipo == "gasto"
                )
            )
            income = session.scalar(
                select(func.coalesce(func.sum(Transaccion.monto), 0)).where(
                    Transaccion.fecha == target, Transaccion.tipo == "ingreso"
                )
            )
            weight = session.scalar(select(Peso).where(Peso.fecha == target))
            health = session.get(Salud, target)
            gym_count = session.scalar(
                select(func.count(GymSesion.id)).where(GymSesion.fecha == target)
            )
        lines = [
            f"Hoy {target.isoformat()}",
            f"Gastos: {_money(expenses)}",
            f"Ingresos: {_money(income)}",
            f"Gym: {gym_count or 0} sesión(es)",
            f"Peso: {_decimal(weight.kg)} kg" if weight else "Peso: sin registro",
            "Salud: registrada" if health else "Salud: sin registro",
        ]
        await update.effective_message.reply_text("\n".join(lines))

    async def _reply(self, update: Any, text: str) -> None:
        if is_authorized(update, self.allowed_chat_id):
            await update.effective_message.reply_text(text)

    def _month_year(self, args: list[str]) -> tuple[int, int]:
        current = self.today_provider()
        month = int(args[0]) if args else current.month
        year = int(args[1]) if len(args) > 1 else current.year
        if not 1 <= month <= 12:
            raise ValueError("mes inválido")
        return month, year

    def _finance_total(self, session: Session, kind: str, month: int, year: int) -> Decimal:
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
        value = session.scalar(
            select(func.coalesce(func.sum(Transaccion.monto), 0)).where(
                Transaccion.tipo == kind,
                Transaccion.fecha >= start,
                Transaccion.fecha < end,
            )
        )
        return Decimal(value)

    async def _finance_breakdown(self, update: Any, context: Any, kind: str) -> None:
        if not is_authorized(update, self.allowed_chat_id):
            return
        current = self.today_provider()
        category = context.args[0].lower() if context.args and kind == "gasto" else None
        try:
            month, year = (
                self._month_year(context.args)
                if kind == "ingreso"
                else (current.month, current.year)
            )
        except (ValueError, IndexError):
            await update.effective_message.reply_text("Uso: /ingresos [mes] [año]")
            return
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
        statement = (
            select(Transaccion.categoria, func.sum(Transaccion.monto))
            .where(
                Transaccion.tipo == kind,
                Transaccion.fecha >= start,
                Transaccion.fecha < end,
            )
            .group_by(Transaccion.categoria)
            .order_by(func.sum(Transaccion.monto).desc())
        )
        if category:
            statement = statement.where(Transaccion.categoria == category)
        with self.session_factory() as session:
            rows = list(session.execute(statement))
        lines = [f"{row.categoria}: {_money(row[1])}" for row in rows]
        await update.effective_message.reply_text("\n".join(lines) or "No hay movimientos.")

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
            f"{gym_session.fecha.isoformat()} - {gym_session.tipo or 'libre'}"
            + (f" - {gym_session.duracion_min} min" if gym_session.duracion_min else "")
        ]
        lines.extend(
            f"{item.ejercicio.nombre_canonico}: {_decimal(item.peso_kg or 0)} kg x {item.reps or 0}"
            for item in gym_session.sets
        )
        return "\n".join(lines)


def _money(value: Decimal | int | float) -> str:
    return f"${_decimal(Decimal(value))}"


def _decimal(value: Decimal | int | float) -> str:
    text = f"{Decimal(value):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return text.rstrip("0").rstrip(",")


def _bounded_int(raw: str | None, *, default: int, maximum: int) -> int:
    value = int(raw) if raw is not None else default
    return max(1, min(value, maximum))
