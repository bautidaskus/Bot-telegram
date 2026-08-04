"""Aplicación de comandos de captura sobre una sesión de gimnasio."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from sqlalchemy.orm import Session

from src.db.models import GymSesion
from src.db.repositories import GymRepository
from src.gym.capture import (
    AddSets,
    FinishSession,
    SwitchExercise,
    UndoLastSet,
    Unrecognized,
    parse_capture_message,
)
from src.gym.matcher import CatalogEntry, match_exercise


class CanonicalizerProtocol(Protocol):
    """Da de alta un ejercicio desconocido a partir de texto libre."""

    def canonicalize(self, raw: str) -> tuple[str, str | None]:
        """Devuelve el nombre snake_case y el grupo muscular inferido."""


class GymSessionService:
    """Orquesta el ciclo de vida de la sesión y la escritura de series."""

    def __init__(
        self,
        session: Session,
        *,
        canonicalizer: CanonicalizerProtocol,
        now: Callable[[], datetime],
    ) -> None:
        self.repository = GymRepository(session)
        self.canonicalizer = canonicalizer
        self.now = now

    def handle(self, text: str) -> str:
        """Procesa un mensaje y devuelve la respuesta a mostrar."""

        open_session = self.repository.get_open_session()
        if open_session is None:
            etiqueta = text.strip()
            self.repository.open_session(fecha=self.now().date(), etiqueta=etiqueta, now=self.now())
            return f"Sesión abierta: {etiqueta}"

        command = parse_capture_message(text)
        if isinstance(command, FinishSession):
            return self._finish(open_session.id)
        if isinstance(command, UndoLastSet):
            removed = self.repository.undo_last_set(open_session.id)
            return "Borré la última serie." if removed else "No hay series para borrar."
        if isinstance(command, SwitchExercise):
            return self._switch(open_session.id, command)
        if isinstance(command, AddSets):
            return self._add_sets(open_session, command)
        return self._fallback(command)

    def close_stale(self, cutoff: datetime) -> list[int]:
        """Cierra las sesiones sin actividad desde `cutoff` y devuelve sus ids."""

        stale = self.repository.list_stale_open_sessions(cutoff)
        for gym_session in stale:
            self.repository.close_session(gym_session.id, now=self.now())
        return [gym_session.id for gym_session in stale]

    def _catalog(self) -> list[CatalogEntry]:
        return [
            CatalogEntry(
                exercise_id=exercise.id,
                canonical=exercise.nombre_canonico,
                aliases=self.repository.aliases_for(exercise.id),
            )
            for exercise in self.repository.list_exercises()
        ]

    def _switch(self, sesion_id: int, command: SwitchExercise) -> str:
        match = match_exercise(command.raw_name, self._catalog())
        if match is None:
            canonical, grupo = self.canonicalizer.canonicalize(command.raw_name)
            exercise = self.repository.get_or_create_exercise(canonical, grupo)
            self.repository.set_current_exercise(sesion_id, exercise.id, command.peso_kg)
            suffix = f" @ {command.peso_kg}kg" if command.peso_kg is not None else ""
            return f"nuevo ejercicio: {canonical}{suffix}"
        if match.learned_alias is not None:
            self.repository.add_alias(match.exercise_id, match.learned_alias)
        self.repository.set_current_exercise(sesion_id, match.exercise_id, command.peso_kg)
        suffix = f" @ {command.peso_kg}kg" if command.peso_kg is not None else " (sin peso)"
        return f"→ {match.canonical}{suffix}"

    def _add_sets(self, open_session: GymSesion, command: AddSets) -> str:
        exercise_id = open_session.ejercicio_actual_id
        if exercise_id is None:
            return "Decime primero qué ejercicio estás haciendo."
        rendered: list[str] = []
        for item in command.sets:
            weight = item.peso_kg if item.peso_kg is not None else open_session.peso_actual
            self.repository.append_set(
                sesion_id=open_session.id,
                ejercicio_id=exercise_id,
                reps=item.reps,
                peso_kg=weight,
                now=self.now(),
            )
            rendered.append(f"{weight:g}x{item.reps}" if weight is not None else str(item.reps))
        name = next(
            item.nombre_canonico
            for item in self.repository.list_exercises()
            if item.id == exercise_id
        )
        return f"{name}: {', '.join(rendered)}"

    def _finish(self, sesion_id: int) -> str:
        closed = self.repository.close_session(sesion_id, now=self.now())
        exercises = {item.ejercicio_id for item in closed.sets}
        return f"Guardado: {len(exercises)} ejercicios, {len(closed.sets)} series."

    def _fallback(self, command: Unrecognized) -> str:
        return f"No entendí «{command.text}». Mandá reps (7), peso (remo t 60) o «fin»."
