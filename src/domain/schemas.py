"""Schemas validados para la salida estructurada del parser."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

from src.domain.catalogo import (
    CATEGORIAS_GASTO,
    CATEGORIAS_INGRESO,
    METODOS_PAGO,
    TIPOS_SESION,
)


class Schema(BaseModel):
    """Base estricta para datos producidos por el LLM."""

    model_config = ConfigDict(extra="forbid")


class FinanceData(Schema):
    """Datos comunes de una operación financiera."""

    monto: Decimal = Field(gt=0)
    categoria: str
    descripcion: str | None = None
    metodo_pago: str | None = None
    moneda: str = Field(default="ARS", min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_payment_method(self) -> FinanceData:
        if self.metodo_pago is not None and self.metodo_pago not in METODOS_PAGO:
            raise ValueError("metodo_pago no reconocido")
        return self


class GastoData(FinanceData):
    """Datos de un gasto."""

    @model_validator(mode="after")
    def validate_category(self) -> GastoData:
        if self.categoria not in CATEGORIAS_GASTO:
            raise ValueError("categoria de gasto no reconocida")
        return self


class IngresoData(FinanceData):
    """Datos de un ingreso."""

    @model_validator(mode="after")
    def validate_category(self) -> IngresoData:
        if self.categoria not in CATEGORIAS_INGRESO:
            raise ValueError("categoria de ingreso no reconocida")
        return self


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

    tipo_sesion: str | None = None
    duracion_min: PositiveInt | None = None
    notas: str | None = None
    ejercicios: list[GymExerciseData] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_session_type(self) -> GymData:
        if self.tipo_sesion is not None and self.tipo_sesion not in TIPOS_SESION:
            raise ValueError("tipo_sesion no reconocido")
        return self


class PesoData(Schema):
    """Datos de peso corporal."""

    kg: Decimal = Field(ge=30, le=300)
    nota: str | None = None


class SaludData(Schema):
    """Datos diarios de salud."""

    sueno_horas: Decimal | None = Field(default=None, ge=1, le=16)
    sueno_calidad: int | None = Field(default=None, ge=1, le=10)
    animo: int | None = Field(default=None, ge=1, le=10)
    energia: int | None = Field(default=None, ge=1, le=10)
    agua_l: Decimal | None = Field(default=None, gt=0)
    nota: str | None = None

    @model_validator(mode="after")
    def require_metric(self) -> SaludData:
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("salud requiere al menos un dato")
        return self


class AmbiguoData(Schema):
    """Opciones propuestas para una entrada ambigua."""

    sugerencias: list[Literal["gasto", "ingreso", "gym", "peso", "salud"]] = Field(min_length=1)


class Operation(Schema):
    """Campos comunes de una operación extraída."""

    confianza: float = Field(ge=0, le=1)
    fecha: str = Field(min_length=1)
    explicacion: str | None = None


class GastoOperation(Operation):
    """Operación de gasto."""

    tipo: Literal["gasto"]
    datos: GastoData


class IngresoOperation(Operation):
    """Operación de ingreso."""

    tipo: Literal["ingreso"]
    datos: IngresoData


class GymOperation(Operation):
    """Operación de gimnasio."""

    tipo: Literal["gym"]
    datos: GymData


class PesoOperation(Operation):
    """Operación de peso corporal."""

    tipo: Literal["peso"]
    datos: PesoData


class SaludOperation(Operation):
    """Operación de salud."""

    tipo: Literal["salud"]
    datos: SaludData


class AmbiguoOperation(Operation):
    """Operación que necesita aclaración."""

    tipo: Literal["ambiguo"]
    datos: AmbiguoData


ParsedOperation = Annotated[
    GastoOperation
    | IngresoOperation
    | GymOperation
    | PesoOperation
    | SaludOperation
    | AmbiguoOperation,
    Field(discriminator="tipo"),
]


class ParserResponse(Schema):
    """Respuesta completa producida por el parser."""

    operaciones: list[ParsedOperation] = Field(min_length=1)
