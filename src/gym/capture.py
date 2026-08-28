"""Traducción de un mensaje suelto a un comando de captura, sin tocar la base."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

FINISH_WORDS = {"fin", "listo", "termine", "terminé", "terminar", "fin."}
UNDO_WORDS = {"deshacer", "borrar", "undo"}
_SET_PATTERN = re.compile(r"^(?:(\d+(?:[.,]\d+)?)[x*])?(\d+)$")


@dataclass(frozen=True)
class SetInput:
    """Serie a registrar; `peso_kg` en None usa el peso vigente del ejercicio."""

    reps: int
    peso_kg: Decimal | None


@dataclass(frozen=True)
class FinishSession:
    """Cierra la sesión abierta."""


@dataclass(frozen=True)
class UndoLastSet:
    """Elimina la última serie registrada."""


@dataclass(frozen=True)
class AddSets:
    """Agrega una o más series al ejercicio actual."""

    sets: list[SetInput]


@dataclass(frozen=True)
class SwitchExercise:
    """Cambia el ejercicio actual y opcionalmente fija su peso."""

    raw_name: str
    peso_kg: Decimal | None


@dataclass(frozen=True)
class Unrecognized:
    """Mensaje que el router determinístico no supo interpretar."""

    text: str


CaptureCommand = FinishSession | UndoLastSet | AddSets | SwitchExercise | Unrecognized


def parse_capture_message(text: str) -> CaptureCommand:
    """Interpreta un mensaje dentro de una sesión abierta."""

    stripped = text.strip()
    lowered = stripped.lower()
    if lowered in FINISH_WORDS:
        return FinishSession()
    if lowered in UNDO_WORDS:
        return UndoLastSet()
    tokens = lowered.split()
    if not tokens:
        return Unrecognized(text)

    sets = _parse_sets(tokens)
    if sets is not None:
        return AddSets(sets)

    weight = _parse_decimal(tokens[-1])
    if weight is not None:
        name_tokens = tokens[:-1]
        if name_tokens and all(token.isalpha() for token in name_tokens):
            return SwitchExercise(raw_name=" ".join(name_tokens), peso_kg=weight)
        return Unrecognized(text)
    if all(token.isalpha() for token in tokens):
        return SwitchExercise(raw_name=" ".join(tokens), peso_kg=None)
    return Unrecognized(text)


def _parse_sets(tokens: list[str]) -> list[SetInput] | None:
    """Devuelve las series si todos los tokens son `reps` o `pesoxreps`."""

    parsed: list[SetInput] = []
    for token in tokens:
        match = _SET_PATTERN.match(token)
        if match is not None:
            weight = _parse_decimal(match.group(1)) if match.group(1) else None
            parsed.append(SetInput(reps=int(match.group(2)), peso_kg=weight))
        elif "," in token:
            parts = [p for p in token.split(",") if p]
            if not all(part.isdigit() for part in parts):
                return None
            for part in parts:
                parsed.append(SetInput(reps=int(part), peso_kg=None))
        else:
            return None
    return parsed


def _parse_decimal(token: str | None) -> Decimal | None:
    if token is None:
        return None
    try:
        return Decimal(token.replace(",", "."))
    except InvalidOperation:
        return None
