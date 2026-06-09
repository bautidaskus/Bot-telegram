"""Repositorios de persistencia por dominio."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Ejercicio, GymSesion, GymSet, Peso, Salud, Transaccion


class WeightAlreadyExistsError(ValueError):
    """Indica que ya existe un peso para la fecha solicitada."""


class FinanceRepository:
    """CRUD de transacciones financieras."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        fecha: date,
        tipo: str,
        monto: Decimal,
        categoria: str,
        moneda: str = "ARS",
        descripcion: str | None = None,
        metodo_pago: str | None = None,
        mensaje_original: str | None = None,
    ) -> Transaccion:
        transaction = Transaccion(
            fecha=fecha,
            tipo=tipo,
            monto=monto,
            moneda=moneda,
            categoria=categoria,
            descripcion=descripcion,
            metodo_pago=metodo_pago,
            mensaje_original=mensaje_original,
        )
        self.session.add(transaction)
        self.session.flush()
        return transaction

    def get(self, transaction_id: int) -> Transaccion | None:
        return self.session.get(Transaccion, transaction_id)

    def list_recent(self, limit: int = 5) -> list[Transaccion]:
        statement = select(Transaccion).order_by(Transaccion.fecha.desc(), Transaccion.id.desc())
        return list(self.session.scalars(statement.limit(limit)))

    def update(self, transaction_id: int, **changes: Any) -> Transaccion:
        transaction = self.session.get_one(Transaccion, transaction_id)
        for field, value in changes.items():
            setattr(transaction, field, value)
        self.session.flush()
        return transaction

    def delete(self, transaction_id: int) -> None:
        transaction = self.session.get_one(Transaccion, transaction_id)
        self.session.delete(transaction)


class WeightRepository:
    """Persistencia de mediciones de peso."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        fecha: date,
        kg: Decimal,
        *,
        nota: str | None = None,
        replace: bool = False,
    ) -> Peso:
        weight = self.session.scalar(select(Peso).where(Peso.fecha == fecha))
        if weight is not None and not replace:
            raise WeightAlreadyExistsError(f"Ya existe un peso para {fecha.isoformat()}")
        if weight is None:
            weight = Peso(fecha=fecha, kg=kg, nota=nota)
            self.session.add(weight)
        else:
            weight.kg = kg
            weight.nota = nota
        self.session.flush()
        return weight

    def get(self, weight_id: int) -> Peso | None:
        return self.session.get(Peso, weight_id)

    def list_recent(self, limit: int = 30) -> list[Peso]:
        statement = select(Peso).order_by(Peso.fecha.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def delete(self, weight_id: int) -> None:
        self.session.delete(self.session.get_one(Peso, weight_id))


class HealthRepository:
    """Persistencia diaria de salud mediante UPSERT semántico."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, fecha: date, **changes: Any) -> Salud:
        health = self.session.get(Salud, fecha)
        if health is None:
            health = Salud(fecha=fecha, **changes)
            self.session.add(health)
        else:
            for field, value in changes.items():
                setattr(health, field, value)
        self.session.flush()
        return health

    def get(self, fecha: date) -> Salud | None:
        return self.session.get(Salud, fecha)

    def list_recent(self, limit: int = 7) -> list[Salud]:
        statement = select(Salud).order_by(Salud.fecha.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def delete(self, fecha: date) -> None:
        self.session.delete(self.session.get_one(Salud, fecha))


class GymRepository:
    """Persistencia de sesiones, ejercicios y series."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(
        self,
        *,
        fecha: date,
        exercises: list[dict[str, Any]],
        tipo: str | None = None,
        duracion_min: int | None = None,
        notas: str | None = None,
        mensaje_original: str | None = None,
    ) -> GymSesion:
        gym_session = GymSesion(
            fecha=fecha,
            tipo=tipo,
            duracion_min=duracion_min,
            notas=notas,
            mensaje_original=mensaje_original,
        )
        self.session.add(gym_session)
        self.session.flush()
        for exercise_data in exercises:
            exercise = self._get_or_create_exercise(exercise_data["nombre"])
            for series_number, set_data in enumerate(exercise_data["sets"], start=1):
                self.session.add(
                    GymSet(
                        sesion_id=gym_session.id,
                        ejercicio_id=exercise.id,
                        serie_num=series_number,
                        **set_data,
                    )
                )
        self.session.flush()
        self.session.refresh(gym_session)
        return gym_session

    def get_session(self, session_id: int) -> GymSesion | None:
        return self.session.get(GymSesion, session_id)

    def list_sessions(self, limit: int = 5) -> list[GymSesion]:
        statement = select(GymSesion).order_by(GymSesion.fecha.desc(), GymSesion.id.desc())
        return list(self.session.scalars(statement.limit(limit)))

    def list_exercises(self) -> list[Ejercicio]:
        statement = select(Ejercicio).order_by(Ejercicio.nombre_canonico)
        return list(self.session.scalars(statement))

    def update_session(self, session_id: int, **changes: Any) -> GymSesion:
        gym_session = self.session.get_one(GymSesion, session_id)
        for field, value in changes.items():
            setattr(gym_session, field, value)
        self.session.flush()
        return gym_session

    def delete_session(self, session_id: int) -> None:
        self.session.delete(self.session.get_one(GymSesion, session_id))

    def _get_or_create_exercise(self, canonical_name: str) -> Ejercicio:
        exercise = self.session.scalar(
            select(Ejercicio).where(Ejercicio.nombre_canonico == canonical_name)
        )
        if exercise is None:
            exercise = Ejercicio(nombre_canonico=canonical_name)
            self.session.add(exercise)
            self.session.flush()
        return exercise
