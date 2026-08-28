"""Codificación compacta de callbacks inline de Telegram."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

PreviewAction = Literal["guardar", "cancelar", "corregir"]
ClarificationHint = Literal["gasto", "ingreso", "gym", "peso", "salud"]

ACTION_CODES: dict[PreviewAction, str] = {
    "guardar": "g",
    "cancelar": "c",
    "corregir": "e",
}
CODE_ACTIONS = {code: action for action, code in ACTION_CODES.items()}
VALID_HINTS = {"gasto", "ingreso", "gym", "peso", "salud"}
CHECKIN_FIELDS = {"puntaje_dia", "animo", "energia", "hora_acostado", "mejor_del_dia"}


class CallbackDataError(ValueError):
    """Indica que callback_data no cumple el contrato interno."""


@dataclass(frozen=True)
class PreviewCallback:
    """Acción solicitada sobre un preview."""

    action: PreviewAction
    preview_id: str


@dataclass(frozen=True)
class ClarificationCallback:
    """Hint elegido para un mensaje pendiente."""

    pending_id: int
    hint: ClarificationHint


@dataclass(frozen=True)
class CheckinCallback:
    """Respuesta elegida en un paso del check-in."""

    campo: str
    valor: str


def build_checkin_callback(campo: str, valor: str) -> str:
    """Construye callback_data para una respuesta del check-in."""

    if campo not in CHECKIN_FIELDS:
        raise CallbackDataError("Campo de check-in inválido")
    return _check_size(f"k:{campo}:{valor}")


def build_preview_callback(action: PreviewAction, preview_id: str) -> str:
    """Construye callback_data para una acción de preview."""

    try:
        code = ACTION_CODES[action]
        normalized_id = str(UUID(preview_id))
    except (KeyError, ValueError) as error:
        raise CallbackDataError("Acción o preview inválido") from error
    return _check_size(f"p:{code}:{normalized_id}")


def build_clarification_callback(pending_id: int, hint: ClarificationHint) -> str:
    """Construye callback_data para resolver una ambigüedad."""

    if pending_id <= 0 or hint not in VALID_HINTS:
        raise CallbackDataError("Pendiente o hint inválido")
    return _check_size(f"a:{pending_id}:{hint}")


def parse_callback(
    callback_data: str,
) -> PreviewCallback | ClarificationCallback | CheckinCallback:
    """Interpreta callback_data generado por este módulo."""

    parts = callback_data.split(":")
    try:
        if len(parts) == 3 and parts[0] == "k":
            if parts[1] not in CHECKIN_FIELDS:
                raise ValueError
            return CheckinCallback(campo=parts[1], valor=parts[2])
        if len(parts) == 3 and parts[0] == "p":
            action = CODE_ACTIONS[parts[1]]
            preview_id = str(UUID(parts[2]))
            return PreviewCallback(action=action, preview_id=preview_id)
        if len(parts) == 3 and parts[0] == "a":
            pending_id = int(parts[1])
            hint = parts[2]
            if pending_id <= 0 or hint not in VALID_HINTS:
                raise ValueError
            return ClarificationCallback(pending_id=pending_id, hint=hint)
    except (KeyError, ValueError) as error:
        raise CallbackDataError("Callback inválido") from error
    raise CallbackDataError("Callback inválido")


def _check_size(callback_data: str) -> str:
    if len(callback_data.encode("utf-8")) > 64:
        raise CallbackDataError("Callback supera 64 bytes")
    return callback_data
