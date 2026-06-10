"""Consultas serializables y de solo lectura para el dashboard."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.db.models import Ejercicio, GymSesion, GymSet, Peso, Salud, Transaccion


class DashboardQueries:
    def __init__(self, session: Session) -> None:
        self.session = session

    def month_summary(self, month: date) -> list[dict[str, Any]]:
        start, end = month_bounds(month)
        transactions = self.session.scalars(
            select(Transaccion)
            .where(Transaccion.fecha >= start, Transaccion.fecha < end)
            .order_by(Transaccion.moneda, Transaccion.fecha, Transaccion.id)
        ).all()
        totals: dict[str, dict[str, Decimal]] = defaultdict(
            lambda: {"income": Decimal(), "expenses": Decimal()}
        )
        for transaction in transactions:
            key = "income" if transaction.tipo == "ingreso" else "expenses"
            totals[transaction.moneda][key] += transaction.monto
        return [
            {
                "currency": currency,
                "income": number(values["income"]),
                "expenses": number(values["expenses"]),
                "balance": number(values["income"] - values["expenses"]),
            }
            for currency, values in sorted(totals.items())
        ]

    def finance_month(self, month: date, currency: str) -> dict[str, Any]:
        start, end = month_bounds(month)
        all_transactions = self.session.scalars(
            select(Transaccion)
            .where(Transaccion.fecha >= start, Transaccion.fecha < end)
            .order_by(Transaccion.fecha, Transaccion.id)
        ).all()
        available_currencies = sorted({item.moneda for item in all_transactions})
        transactions = [item for item in all_transactions if item.moneda == currency]
        income = sum((item.monto for item in transactions if item.tipo == "ingreso"), Decimal())
        expenses = sum((item.monto for item in transactions if item.tipo == "gasto"), Decimal())
        daily_totals: dict[date, dict[str, Decimal]] = defaultdict(
            lambda: {"income": Decimal(), "expenses": Decimal()}
        )
        category_totals: dict[str, Decimal] = defaultdict(Decimal)
        for item in transactions:
            key = "income" if item.tipo == "ingreso" else "expenses"
            daily_totals[item.fecha][key] += item.monto
            if item.tipo == "gasto":
                category_totals[item.categoria] += item.monto

        return {
            "available_currencies": available_currencies,
            "summary": {
                "income": number(income),
                "expenses": number(expenses),
                "balance": number(income - expenses),
            },
            "daily": [
                {
                    "date": day.isoformat(),
                    "income": number(daily_totals[day]["income"]),
                    "expenses": number(daily_totals[day]["expenses"]),
                }
                for day in date_range(start, end - timedelta(days=1))
            ],
            "categories": [
                {"category": category, "amount": number(amount)}
                for category, amount in sorted(
                    category_totals.items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "transactions": [serialize_transaction(item) for item in transactions],
        }

    def latest_weight(self) -> dict[str, Any] | None:
        latest = self.session.scalar(select(Peso).order_by(Peso.fecha.desc()).limit(1))
        if latest is None:
            return None
        window_start = latest.fecha - timedelta(days=6)
        measurements = self.session.scalars(
            select(Peso).where(Peso.fecha >= window_start, Peso.fecha <= latest.fecha)
        ).all()
        average = sum((item.kg for item in measurements), Decimal()) / len(measurements)
        return {
            "date": latest.fecha.isoformat(),
            "kg": number(latest.kg),
            "average_7d": number(average),
        }

    def health_averages(self, today: date, *, days: int = 7) -> dict[str, float | None]:
        start = today - timedelta(days=days - 1)
        records = self.session.scalars(
            select(Salud).where(Salud.fecha >= start, Salud.fecha <= today)
        ).all()
        fields = {
            "sleep_hours": "sueno_horas",
            "sleep_quality": "sueno_calidad",
            "mood": "animo",
            "energy": "energia",
            "water_l": "agua_l",
        }
        return {
            output: average([getattr(record, source) for record in records])
            for output, source in fields.items()
        }

    def health_history(self, start: date, end: date) -> list[dict[str, Any]]:
        weight_start = start - timedelta(days=6)
        weights = self.session.scalars(
            select(Peso).where(Peso.fecha >= weight_start, Peso.fecha <= end).order_by(Peso.fecha)
        ).all()
        health_records = self.session.scalars(
            select(Salud).where(Salud.fecha >= start, Salud.fecha <= end).order_by(Salud.fecha)
        ).all()
        weights_by_date = {item.fecha: item for item in weights}
        health_by_date = {item.fecha: item for item in health_records}
        history: list[dict[str, Any]] = []
        for day in date_range(start, end):
            weight = weights_by_date.get(day)
            health = health_by_date.get(day)
            window_start = day - timedelta(days=6)
            window_values = [item.kg for item in weights if window_start <= item.fecha <= day]
            history.append(
                {
                    "date": day.isoformat(),
                    "weight": number(weight.kg) if weight else None,
                    "weight_average_7d": average(window_values),
                    "sleep_hours": number(health.sueno_horas)
                    if health and health.sueno_horas is not None
                    else None,
                    "sleep_quality": health.sueno_calidad if health else None,
                    "mood": health.animo if health else None,
                    "energy": health.energia if health else None,
                    "water_l": number(health.agua_l)
                    if health and health.agua_l is not None
                    else None,
                }
            )
        return history

    def gym_summary(self, start: date, end: date, *, limit: int = 5) -> dict[str, Any]:
        statement = (
            select(GymSesion)
            .where(GymSesion.fecha >= start, GymSesion.fecha <= end)
            .options(selectinload(GymSesion.sets).selectinload(GymSet.ejercicio))
            .order_by(GymSesion.fecha.desc(), GymSesion.id.desc())
        )
        sessions = self.session.scalars(statement).all()
        return {
            "count": len(sessions),
            "sessions": [serialize_gym_session(item) for item in sessions[:limit]],
        }

    def exercises(self) -> list[str]:
        return list(
            self.session.scalars(
                select(Ejercicio.nombre_canonico).order_by(Ejercicio.nombre_canonico)
            ).all()
        )

    def exercise_progression(self, exercise: str) -> list[dict[str, Any]]:
        sets = self.session.execute(
            select(GymSet, GymSesion.fecha)
            .join(GymSet.sesion)
            .join(GymSet.ejercicio)
            .where(Ejercicio.nombre_canonico == exercise)
            .order_by(GymSesion.fecha, GymSet.serie_num, GymSet.id)
        ).all()
        grouped: dict[date, list[GymSet]] = defaultdict(list)
        for gym_set, session_date in sets:
            grouped[session_date].append(gym_set)
        progression = []
        for session_date, session_sets in grouped.items():
            weights = [item.peso_kg for item in session_sets if item.peso_kg is not None]
            estimates = [
                item.peso_kg * (Decimal(1) + Decimal(item.reps) / Decimal(30))
                for item in session_sets
                if item.peso_kg is not None and item.reps is not None
            ]
            progression.append(
                {
                    "date": session_date.isoformat(),
                    "max_weight": number(max(weights)) if weights else None,
                    "estimated_1rm": number(max(estimates)) if estimates else None,
                }
            )
        return progression

    def recent_activity(self, *, limit: int = 8) -> list[dict[str, Any]]:
        transactions = self.session.scalars(
            select(Transaccion)
            .order_by(Transaccion.fecha.desc(), Transaccion.id.desc())
            .limit(limit)
        ).all()
        gym_sessions = self.session.scalars(
            select(GymSesion).order_by(GymSesion.fecha.desc(), GymSesion.id.desc()).limit(limit)
        ).all()
        weights = self.session.scalars(
            select(Peso).order_by(Peso.fecha.desc(), Peso.id.desc()).limit(limit)
        ).all()
        health_records = self.session.scalars(
            select(Salud).order_by(Salud.fecha.desc()).limit(limit)
        ).all()
        activity = [
            {
                "date": item.fecha.isoformat(),
                "kind": "finance",
                "title": "Ingreso" if item.tipo == "ingreso" else "Gasto",
                "detail": f"{number(item.monto):.2f} {item.moneda} · {item.categoria}",
                "order": item.id,
            }
            for item in transactions
        ]
        activity.extend(
            {
                "date": item.fecha.isoformat(),
                "kind": "gym",
                "title": "Sesión de gimnasio",
                "detail": item.tipo or "Sin tipo",
                "order": item.id,
            }
            for item in gym_sessions
        )
        activity.extend(
            {
                "date": item.fecha.isoformat(),
                "kind": "weight",
                "title": "Peso",
                "detail": f"{number(item.kg):.2f} kg",
                "order": item.id,
            }
            for item in weights
        )
        activity.extend(
            {
                "date": item.fecha.isoformat(),
                "kind": "health",
                "title": "Salud",
                "detail": health_detail(item),
                "order": 0,
            }
            for item in health_records
        )
        activity.sort(key=lambda item: (item["date"], item["order"]), reverse=True)
        for item in activity:
            item.pop("order")
        return activity[:limit]


def month_bounds(value: date) -> tuple[date, date]:
    start = value.replace(day=1)
    if start.month == 12:
        return start, date(start.year + 1, 1, 1)
    return start, date(start.year, start.month + 1, 1)


def date_range(start: date, end: date):  # type: ignore[no-untyped-def]
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def average(values: list[Any]) -> float | None:
    present = [Decimal(str(value)) for value in values if value is not None]
    if not present:
        return None
    return number(sum(present, Decimal()) / len(present))


def number(value: Decimal) -> float:
    return round(float(value), 2)


def serialize_transaction(item: Transaccion) -> dict[str, Any]:
    return {
        "id": item.id,
        "date": item.fecha.isoformat(),
        "kind": item.tipo,
        "amount": number(item.monto),
        "currency": item.moneda,
        "category": item.categoria,
        "description": item.descripcion,
        "payment_method": item.metodo_pago,
    }


def serialize_gym_session(item: GymSesion) -> dict[str, Any]:
    sets = sorted(item.sets, key=lambda gym_set: (gym_set.serie_num, gym_set.id))
    return {
        "id": item.id,
        "date": item.fecha.isoformat(),
        "kind": item.tipo,
        "duration_min": item.duracion_min,
        "notes": item.notas,
        "sets": [
            {
                "exercise": gym_set.ejercicio.nombre_canonico,
                "set_number": gym_set.serie_num,
                "weight_kg": number(gym_set.peso_kg) if gym_set.peso_kg is not None else None,
                "reps": gym_set.reps,
                "rpe": number(gym_set.rpe) if gym_set.rpe is not None else None,
                "note": gym_set.nota,
            }
            for gym_set in sets
        ],
    }


def health_detail(item: Salud) -> str:
    values = []
    if item.animo is not None:
        values.append(f"Ánimo {item.animo}/10")
    if item.energia is not None:
        values.append(f"Energía {item.energia}/10")
    if item.sueno_horas is not None:
        values.append(f"Sueño {number(item.sueno_horas):.2f} h")
    return " · ".join(values) or "Registro diario"
