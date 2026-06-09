from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.schemas import ParserResponse


def test_parser_response_validates_multiple_operations() -> None:
    response = ParserResponse.model_validate(
        {
            "operaciones": [
                {
                    "tipo": "gasto",
                    "confianza": 0.95,
                    "fecha": "ayer",
                    "datos": {
                        "monto": 1500,
                        "categoria": "alimentos",
                        "metodo_pago": "debito",
                    },
                    "explicacion": "Compra en supermercado",
                },
                {
                    "tipo": "peso",
                    "confianza": 0.99,
                    "fecha": "hoy",
                    "datos": {"kg": 78.4},
                    "explicacion": "Medición corporal",
                },
            ]
        }
    )

    assert len(response.operaciones) == 2
    assert response.operaciones[0].datos.monto == Decimal("1500")
    assert response.operaciones[1].datos.kg == Decimal("78.4")


@pytest.mark.parametrize(
    "operation",
    [
        {
            "tipo": "ingreso",
            "confianza": 0.95,
            "fecha": "hoy",
            "datos": {"monto": 250000, "categoria": "sueldo"},
        },
        {
            "tipo": "gym",
            "confianza": 0.95,
            "fecha": "hoy",
            "datos": {
                "tipo_sesion": "push",
                "ejercicios": [
                    {
                        "nombre": "press_banca",
                        "sets": [{"peso_kg": 80, "reps": 8, "rpe": 8.5}],
                    }
                ],
            },
        },
        {
            "tipo": "salud",
            "confianza": 0.95,
            "fecha": "hoy",
            "datos": {"sueno_horas": 7.5, "animo": 8, "agua_l": 2},
        },
        {
            "tipo": "ambiguo",
            "confianza": 0.4,
            "fecha": "hoy",
            "datos": {"sugerencias": ["gasto", "ingreso"]},
        },
    ],
)
def test_parser_response_accepts_each_remaining_operation_type(
    operation: dict[str, object],
) -> None:
    response = ParserResponse.model_validate({"operaciones": [operation]})

    assert response.operaciones[0].tipo == operation["tipo"]


@pytest.mark.parametrize(
    ("operation", "invalid_field"),
    [
        (
            {
                "tipo": "gasto",
                "confianza": 0.9,
                "fecha": "hoy",
                "datos": {"monto": 0, "categoria": "alimentos"},
            },
            "monto",
        ),
        (
            {
                "tipo": "ingreso",
                "confianza": 0.9,
                "fecha": "hoy",
                "datos": {"monto": 1000, "categoria": "alimentos"},
            },
            "categoria",
        ),
        (
            {
                "tipo": "peso",
                "confianza": 0.9,
                "fecha": "hoy",
                "datos": {"kg": 0},
            },
            "kg",
        ),
        (
            {
                "tipo": "salud",
                "confianza": 0.9,
                "fecha": "hoy",
                "datos": {"animo": 11},
            },
            "animo",
        ),
        (
            {
                "tipo": "gym",
                "confianza": 0.9,
                "fecha": "hoy",
                "datos": {
                    "ejercicios": [
                        {"nombre": "press_banca", "sets": [{"reps": 0}]},
                    ]
                },
            },
            "reps",
        ),
    ],
)
def test_parser_response_rejects_invalid_domain_values(
    operation: dict[str, object], invalid_field: str
) -> None:
    with pytest.raises(ValidationError) as error:
        ParserResponse.model_validate({"operaciones": [operation]})

    assert invalid_field in str(error.value)


def test_ambiguous_operation_requires_suggestions() -> None:
    with pytest.raises(ValidationError, match="sugerencias"):
        ParserResponse.model_validate(
            {
                "operaciones": [
                    {
                        "tipo": "ambiguo",
                        "confianza": 0.4,
                        "fecha": "hoy",
                        "datos": {"sugerencias": []},
                    }
                ]
            }
        )


def test_parser_response_rejects_empty_operations() -> None:
    with pytest.raises(ValidationError, match="operaciones"):
        ParserResponse.model_validate({"operaciones": []})
