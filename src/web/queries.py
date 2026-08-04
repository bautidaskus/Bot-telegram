"""Consultas serializables y de solo lectura para el dashboard."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.db.models import Checkin, Ejercicio, GymSesion, GymSet


class DashboardQueries:
    def __init__(self, session: Session, today: Callable[[], date] = date.today) -> None:
        self.session = session
        self.today = today

    def checkin_history(self, days: int = 30) -> list[dict[str, Any]]:
        """Serie diaria de puntaje, ánimo y energía."""

        cutoff = self.today() - timedelta(days=days)
        statement = select(Checkin).where(Checkin.fecha >= cutoff).order_by(Checkin.fecha)
        return [
            {
                "fecha": item.fecha.isoformat(),
                "puntaje": item.puntaje_dia,
                "animo": item.animo,
                "energia": item.energia,
                "hora_acostado": item.hora_acostado,
            }
            for item in self.session.scalars(statement)
        ]

    def checkin_vs_gym(self, days: int = 30) -> dict[str, float | None]:
        """Puntaje promedio del día en jornadas con y sin entrenamiento."""

        cutoff = self.today() - timedelta(days=days)
        trained = set(
            self.session.scalars(select(GymSesion.fecha).where(GymSesion.fecha >= cutoff))
        )
        scores: dict[str, list[int]] = {"con_gym": [], "sin_gym": []}
        statement = select(Checkin).where(Checkin.fecha >= cutoff, Checkin.puntaje_dia.is_not(None))
        for item in self.session.scalars(statement):
            key = "con_gym" if item.fecha in trained else "sin_gym"
            scores[key].append(item.puntaje_dia)
        return {
            key: (round(sum(values) / len(values), 2) if values else None)
            for key, values in scores.items()
        }

    def latest_checkin(self) -> dict[str, Any] | None:
        """Último check-in respondido, para la portada."""

        statement = (
            select(Checkin)
            .where(Checkin.puntaje_dia.is_not(None))
            .order_by(Checkin.fecha.desc())
            .limit(1)
        )
        latest = self.session.scalar(statement)
        if latest is None:
            return None
        return {
            "fecha": latest.fecha.isoformat(),
            "puntaje": latest.puntaje_dia,
            "animo": latest.animo,
            "energia": latest.energia,
        }

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
        gym_sessions = self.session.scalars(
            select(GymSesion)
            .options(selectinload(GymSesion.sets))
            .order_by(GymSesion.fecha.desc(), GymSesion.id.desc())
            .limit(limit)
        ).all()
        checkins = self.session.scalars(
            select(Checkin)
            .where(Checkin.puntaje_dia.is_not(None))
            .order_by(Checkin.fecha.desc())
            .limit(limit)
        ).all()
        activity = [
            {
                "date": item.fecha.isoformat(),
                "kind": "gym",
                "title": item.etiqueta or "Sesión de gimnasio",
                "detail": f"{len(item.sets)} series",
                "order": item.id,
            }
            for item in gym_sessions
        ]
        activity.extend(
            {
                "date": item.fecha.isoformat(),
                "kind": "checkin",
                "title": "Check-in",
                "detail": checkin_detail(item),
                "order": 0,
            }
            for item in checkins
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


def date_range(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def number(value: Decimal) -> float:
    return round(float(value), 2)


def serialize_gym_session(item: GymSesion) -> dict[str, Any]:
    sets = sorted(item.sets, key=lambda gym_set: (gym_set.serie_num, gym_set.id))
    return {
        "id": item.id,
        "date": item.fecha.isoformat(),
        "label": item.etiqueta,
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


def checkin_detail(item: Checkin) -> str:
    values = [f"Día {item.puntaje_dia}/10"]
    if item.animo is not None:
        values.append(f"Ánimo {item.animo}/10")
    if item.energia is not None:
        values.append(f"Energía {item.energia}/5")
    return " · ".join(values)
