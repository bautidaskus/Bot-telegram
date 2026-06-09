from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAI

from src.ai.parser import LLMParser, ParserError


class FakeCompletions:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        content = next(self.responses)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def build_client(responses: list[str]) -> tuple[SimpleNamespace, FakeCompletions]:
    completions = FakeCompletions(responses)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def valid_expense_response() -> str:
    return json.dumps(
        {
            "operaciones": [
                {
                    "tipo": "gasto",
                    "confianza": 0.95,
                    "fecha": "hoy",
                    "datos": {"monto": 1500, "categoria": "alimentos"},
                    "explicacion": "Compra de alimentos",
                }
            ]
        }
    )


def response_for_types(operation_types: list[str]) -> str:
    data_by_type: dict[str, dict[str, Any]] = {
        "gasto": {"monto": 1500, "categoria": "otros"},
        "ingreso": {"monto": 1000, "categoria": "otros"},
        "gym": {"ejercicios": [{"nombre": "ejercicio", "sets": [{"reps": 1}]}]},
        "peso": {"kg": 78},
        "salud": {"animo": 5},
        "ambiguo": {"sugerencias": ["gasto", "ingreso"]},
    }
    return json.dumps(
        {
            "operaciones": [
                {
                    "tipo": operation_type,
                    "confianza": 0.4 if operation_type == "ambiguo" else 0.9,
                    "fecha": "hoy",
                    "datos": data_by_type[operation_type],
                }
                for operation_type in operation_types
            ]
        }
    )


def test_parser_uses_json_mode_and_injects_exercise_catalog(tmp_path: Path) -> None:
    prompt_path = tmp_path / "parser.txt"
    prompt_path.write_text("Catálogo:\n{exercise_catalog}", encoding="utf-8")
    client, completions = build_client([valid_expense_response()])
    parser = LLMParser(client=client, model="test-model", prompt_path=prompt_path)

    response = parser.parse("Gasté 1500 en el súper", ["press_banca", "sentadilla"])

    assert response.operaciones[0].tipo == "gasto"
    call = completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["temperature"] == 0
    assert call["model"] == "test-model"
    assert "press_banca, sentadilla" in call["messages"][0]["content"]


def test_parser_retries_with_validation_error_context(tmp_path: Path) -> None:
    prompt_path = tmp_path / "parser.txt"
    prompt_path.write_text("Catálogo: {exercise_catalog}", encoding="utf-8")
    invalid = json.dumps(
        {
            "operaciones": [
                {
                    "tipo": "peso",
                    "confianza": 0.9,
                    "fecha": "hoy",
                    "datos": {"kg": 500},
                }
            ]
        }
    )
    client, completions = build_client([invalid, valid_expense_response()])
    parser = LLMParser(client=client, model="test-model", prompt_path=prompt_path)

    response = parser.parse("Gasté 1500", [])

    assert response.operaciones[0].tipo == "gasto"
    assert len(completions.calls) == 2
    assert "kg" in completions.calls[1]["messages"][-1]["content"]


def test_parser_raises_after_three_invalid_responses(tmp_path: Path) -> None:
    prompt_path = tmp_path / "parser.txt"
    prompt_path.write_text("Catálogo: {exercise_catalog}", encoding="utf-8")
    client, completions = build_client(["not-json", "still-not-json", "{}"])
    parser = LLMParser(client=client, model="test-model", prompt_path=prompt_path)

    with pytest.raises(ParserError, match="3 intentos"):
        parser.parse("Anoté algo", [])

    assert len(completions.calls) == 3


def test_fixture_contains_at_least_twenty_real_messages() -> None:
    fixture_path = Path("tests/fixtures/mensajes.json")
    messages = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert len(messages) >= 20
    assert {operation for item in messages for operation in item["tipos"]} == {
        "gasto",
        "ingreso",
        "gym",
        "peso",
        "salud",
        "ambiguo",
    }


def test_parser_validates_every_fixture_with_mocked_responses(tmp_path: Path) -> None:
    messages = json.loads(Path("tests/fixtures/mensajes.json").read_text(encoding="utf-8"))
    prompt_path = tmp_path / "parser.txt"
    prompt_path.write_text("Catálogo: {exercise_catalog}", encoding="utf-8")
    client, completions = build_client([response_for_types(item["tipos"]) for item in messages])
    parser = LLMParser(client=client, model="test-model", prompt_path=prompt_path)

    parsed_types = [
        [operation.tipo for operation in parser.parse(item["texto"], []).operaciones]
        for item in messages
    ]

    assert parsed_types == [item["tipos"] for item in messages]
    assert len(completions.calls) == len(messages)


@pytest.mark.live
def test_live_groq_parser_smoke() -> None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY no configurada")
    parser = LLMParser(
        client=OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1"),
        model=os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile"),
        prompt_path=Path("prompts/parser.txt"),
    )

    response = parser.parse("Gasté 1500 pesos en el supermercado", [])

    assert response.operaciones[0].tipo == "gasto"
