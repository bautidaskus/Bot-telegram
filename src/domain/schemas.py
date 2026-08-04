"""Schemas validados para la salida estructurada del parser."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class Schema(BaseModel):
    """Base estricta para datos producidos por el LLM."""

    model_config = ConfigDict(extra="forbid")


class GymSetData(Schema):
    """Serie detectada en un mensaje de gimnasio."""

    peso_kg: Decimal | None = Field(default=None, gt=0)
    reps: PositiveInt | None = None
    rpe: Decimal | None = Field(default=None, ge=1, le=10)
    nota: str | None = None


class GymExerciseData(Schema):
    """Ejercicio canónico con sus series."""

    nombre: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    sets: list[GymSetData] = Field(min_length=1)


class GymData(Schema):
    """Datos de una sesión de gimnasio."""

    duracion_min: PositiveInt | None = None
    notas: str | None = None
    ejercicios: list[GymExerciseData] = Field(min_length=1)


class Operation(Schema):
    """Campos comunes de una operación extraída."""

    confianza: float = Field(ge=0, le=1)
    fecha: str = Field(min_length=1)
    explicacion: str | None = None


class GymOperation(Operation):
    """Operación de gimnasio."""

    tipo: Literal["gym"]
    datos: GymData


ParsedOperation = Annotated[GymOperation, Field(discriminator="tipo")]


class ParserResponse(Schema):
    """Respuesta completa producida por el parser."""

    operaciones: list[ParsedOperation] = Field(min_length=1)
