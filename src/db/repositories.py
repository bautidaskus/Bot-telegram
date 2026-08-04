"""Repositorios de persistencia por dominio."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import Checkin, Ejercicio, GymSesion, GymSet


class GymRepository:
    """Persistencia de sesiones, ejercicios y series."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def open_session(self, *, fecha: date, etiqueta: str, now: datetime) -> GymSesion:
        gym_session = GymSesion(
            fecha=fecha, etiqueta=etiqueta, estado="abierta", ultima_actividad=now
        )
        self.session.add(gym_session)
        self.session.flush()
        return gym_session

    def get_open_session(self) -> GymSesion | None:
        return self.session.scalar(select(GymSesion).where(GymSesion.estado == "abierta"))

    def set_current_exercise(
        self, sesion_id: int, ejercicio_id: int, peso_kg: Decimal | None
    ) -> None:
        gym_session = self.session.get_one(GymSesion, sesion_id)
        gym_session.ejercicio_actual_id = ejercicio_id
        gym_session.peso_actual = peso_kg
        self.session.flush()

    def append_set(
        self,
        *,
        sesion_id: int,
        ejercicio_id: int,
        reps: int,
        peso_kg: Decimal | None,
        now: datetime,
    ) -> GymSet:
        last = self.session.scalar(
            select(func.max(GymSet.serie_num)).where(
                GymSet.sesion_id == sesion_id, GymSet.ejercicio_id == ejercicio_id
            )
        )
        gym_set = GymSet(
            sesion_id=sesion_id,
            ejercicio_id=ejercicio_id,
            serie_num=(last or 0) + 1,
            reps=reps,
            peso_kg=peso_kg,
        )
        self.session.add(gym_set)
        self.session.get_one(GymSesion, sesion_id).ultima_actividad = now
        self.session.flush()
        return gym_set

    def undo_last_set(self, sesion_id: int) -> GymSet | None:
        gym_set = self.session.scalar(
            select(GymSet).where(GymSet.sesion_id == sesion_id).order_by(GymSet.id.desc()).limit(1)
        )
        if gym_set is not None:
            self.session.delete(gym_set)
            self.session.flush()
        return gym_set

    def close_session(self, sesion_id: int, *, now: datetime) -> GymSesion:
        gym_session = self.session.get_one(GymSesion, sesion_id)
        gym_session.estado = "cerrada"
        gym_session.cerrada_en = now
        self.session.flush()
        return gym_session

    def list_stale_open_sessions(self, cutoff: datetime) -> list[GymSesion]:
        statement = select(GymSesion).where(
            GymSesion.estado == "abierta", GymSesion.ultima_actividad < cutoff
        )
        return list(self.session.scalars(statement))

    def get_session(self, session_id: int) -> GymSesion | None:
        return self.session.get(GymSesion, session_id)

    def list_sessions(self, limit: int = 5) -> list[GymSesion]:
        statement = select(GymSesion).order_by(GymSesion.fecha.desc(), GymSesion.id.desc())
        return list(self.session.scalars(statement.limit(limit)))

    def list_exercises(self) -> list[Ejercicio]:
        statement = select(Ejercicio).order_by(Ejercicio.nombre_canonico)
        return list(self.session.scalars(statement))

    def get_or_create_exercise(
        self, canonical_name: str, grupo_muscular: str | None = None
    ) -> Ejercicio:
        exercise = self.session.scalar(
            select(Ejercicio).where(Ejercicio.nombre_canonico == canonical_name)
        )
        if exercise is None:
            exercise = Ejercicio(nombre_canonico=canonical_name, grupo_muscular=grupo_muscular)
            self.session.add(exercise)
            self.session.flush()
        return exercise

    def aliases_for(self, ejercicio_id: int) -> list[str]:
        exercise = self.session.get_one(Ejercicio, ejercicio_id)
        return json.loads(exercise.alias_json) if exercise.alias_json else []

    def add_alias(self, ejercicio_id: int, alias: str) -> None:
        exercise = self.session.get_one(Ejercicio, ejercicio_id)
        aliases = json.loads(exercise.alias_json) if exercise.alias_json else []
        if alias not in aliases:
            aliases.append(alias)
            exercise.alias_json = json.dumps(aliases, ensure_ascii=False)
            self.session.flush()

    def update_session(self, session_id: int, **changes: Any) -> GymSesion:
        gym_session = self.session.get_one(GymSesion, session_id)
        for field, value in changes.items():
            setattr(gym_session, field, value)
        self.session.flush()
        return gym_session

    def delete_session(self, session_id: int) -> None:
        self.session.delete(self.session.get_one(GymSesion, session_id))


class CheckinRepository:
    """Persistencia del registro nocturno, actualizado paso a paso."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(self, fecha: date) -> Checkin:
        checkin = self.session.get(Checkin, fecha)
        if checkin is None:
            checkin = Checkin(fecha=fecha)
            self.session.add(checkin)
            self.session.flush()
        return checkin

    def update(self, fecha: date, **changes: Any) -> Checkin:
        checkin = self.get_or_create(fecha)
        for field, value in changes.items():
            setattr(checkin, field, value)
        self.session.flush()
        return checkin

    def list_recent(self, limit: int = 30) -> list[Checkin]:
        statement = select(Checkin).order_by(Checkin.fecha.desc()).limit(limit)
        return list(self.session.scalars(statement))
