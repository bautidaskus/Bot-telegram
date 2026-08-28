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
                    "tipo": "gym",
                    "confianza": 0.95,
                    "fecha": "ayer",
                    "datos": {
                        "ejercicios": [
                            {"nombre": "press_banca", "sets": [{"peso_kg": 80, "reps": 8}]}
                        ]
                    },
                    "explicacion": "Press de banca",
                },
                {
                    "tipo": "gym",
                    "confianza": 0.99,
                    "fecha": "hoy",
                    "datos": {
                        "duracion_min": 45,
                        "ejercicios": [{"nombre": "dominadas", "sets": [{"reps": 7}, {"reps": 6}]}],
                    },
                },
            ]
        }
    )

    assert len(response.operaciones) == 2
    assert response.operaciones[0].datos.ejercicios[0].sets[0].peso_kg == Decimal("80")
    assert len(response.operaciones[1].datos.ejercicios[0].sets) == 2


@pytest.mark.parametrize(
    ("operation", "invalid_field"),
    [
        (
            {
                "tipo": "gym",
                "confianza": 0.9,
                "fecha": "hoy",
                "datos": {"ejercicios": [{"nombre": "press_banca", "sets": [{"reps": 0}]}]},
            },
            "reps",
        ),
        (
            {
                "tipo": "gym",
                "confianza": 0.9,
                "fecha": "hoy",
                "datos": {"ejercicios": [{"nombre": "Press Banca", "sets": [{"reps": 8}]}]},
            },
            "nombre",
        ),
        (
            {
                "tipo": "gym",
                "confianza": 0.9,
                "fecha": "hoy",
                "datos": {"ejercicios": [{"nombre": "press_banca", "sets": []}]},
            },
            "sets",
        ),
        (
            {
                "tipo": "gym",
                "confianza": 0.9,
                "fecha": "hoy",
                "datos": {
                    "ejercicios": [{"nombre": "press_banca", "sets": [{"reps": 8, "rpe": 12}]}]
                },
            },
            "rpe",
        ),
        (
            {
                "tipo": "gym",
                "confianza": 1.5,
                "fecha": "hoy",
                "datos": {"ejercicios": [{"nombre": "press_banca", "sets": [{"reps": 8}]}]},
            },
            "confianza",
        ),
    ],
)
def test_parser_response_rejects_invalid_domain_values(
    operation: dict[str, object], invalid_field: str
) -> None:
    with pytest.raises(ValidationError) as error:
        ParserResponse.model_validate({"operaciones": [operation]})

    assert invalid_field in str(error.value)


def test_gym_operation_requires_exercises() -> None:
    with pytest.raises(ValidationError, match="ejercicios"):
        ParserResponse.model_validate(
            {
                "operaciones": [
                    {
                        "tipo": "gym",
                        "confianza": 0.9,
                        "fecha": "hoy",
                        "datos": {"ejercicios": []},
                    }
                ]
            }
        )


def test_parser_response_rejects_non_gym_operations() -> None:
    with pytest.raises(ValidationError, match="tipo"):
        ParserResponse.model_validate(
            {
                "operaciones": [
                    {
                        "tipo": "gasto",
                        "confianza": 0.9,
                        "fecha": "hoy",
                        "datos": {"monto": 1500, "categoria": "alimentos"},
                    }
                ]
            }
        )


def test_parser_response_rejects_empty_operations() -> None:
    with pytest.raises(ValidationError, match="operaciones"):
        ParserResponse.model_validate({"operaciones": []})
