from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIConnectionError, OpenAI

from src.ai.parser import LLMCanonicalizer, LLMParser, ParserError, ParserUnavailableError

CANONICALIZER_PROMPT = Path("prompts/canonicalizer.txt")


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


def valid_gym_response() -> str:
    return response_for_exercises(["press_banca"])


def response_for_exercises(names: list[str]) -> str:
    return json.dumps(
        {
            "operaciones": [
                {
                    "tipo": "gym",
                    "confianza": 0.9,
                    "fecha": "hoy",
                    "datos": {
                        "ejercicios": [
                            {"nombre": name, "sets": [{"peso_kg": 80, "reps": 8}]} for name in names
                        ]
                    },
                    "explicacion": "Series registradas",
                }
            ]
        }
    )


def test_parser_uses_json_mode_and_injects_exercise_catalog(tmp_path: Path) -> None:
    prompt_path = tmp_path / "parser.txt"
    prompt_path.write_text("Catálogo:\n{exercise_catalog}", encoding="utf-8")
    client, completions = build_client([valid_gym_response()])
    parser = LLMParser(client=client, model="test-model", prompt_path=prompt_path)

    response = parser.parse("Bench 80 por 8", ["press_banca", "sentadilla"])

    assert response.operaciones[0].tipo == "gym"
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
                    "tipo": "gym",
                    "confianza": 0.9,
                    "fecha": "hoy",
                    "datos": {"ejercicios": [{"nombre": "press_banca", "sets": [{"reps": 0}]}]},
                }
            ]
        }
    )
    client, completions = build_client([invalid, valid_gym_response()])
    parser = LLMParser(client=client, model="test-model", prompt_path=prompt_path)

    response = parser.parse("Bench 80 por 8", [])

    assert response.operaciones[0].tipo == "gym"
    assert len(completions.calls) == 2
    assert "reps" in completions.calls[1]["messages"][-1]["content"]


def test_parser_raises_after_three_invalid_responses(tmp_path: Path) -> None:
    prompt_path = tmp_path / "parser.txt"
    prompt_path.write_text("Catálogo: {exercise_catalog}", encoding="utf-8")
    client, completions = build_client(["not-json", "still-not-json", "{}"])
    parser = LLMParser(client=client, model="test-model", prompt_path=prompt_path)

    with pytest.raises(ParserError, match="3 intentos"):
        parser.parse("Anoté algo", [])

    assert len(completions.calls) == 3


class FlakyCompletions:
    def __init__(self, failures: int, response: str | None) -> None:
        self.failures = failures
        self.response = response
        self.attempts = 0

    def create(self, **_: Any) -> SimpleNamespace:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise APIConnectionError(request=httpx.Request("POST", "https://api.groq.com"))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.response))]
        )


def build_flaky_parser(
    tmp_path: Path, failures: int, response: str | None
) -> tuple[LLMParser, list[float], FlakyCompletions]:
    prompt_path = tmp_path / "parser.txt"
    prompt_path.write_text("Catálogo: {exercise_catalog}", encoding="utf-8")
    completions = FlakyCompletions(failures, response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    sleeps: list[float] = []
    parser = LLMParser(
        client=client,
        model="test-model",
        prompt_path=prompt_path,
        sleep=sleeps.append,
        backoff_base=2.0,
        api_attempts=3,
    )
    return parser, sleeps, completions


def test_parser_recovers_from_transient_errors_with_exponential_backoff(tmp_path: Path) -> None:
    parser, sleeps, completions = build_flaky_parser(tmp_path, 2, valid_gym_response())

    response = parser.parse("Bench 80 por 8", [])

    assert response.operaciones[0].tipo == "gym"
    assert completions.attempts == 3
    assert sleeps == [2.0, 4.0]


def test_parser_raises_unavailable_when_groq_stays_down(tmp_path: Path) -> None:
    parser, sleeps, completions = build_flaky_parser(tmp_path, 5, None)

    with pytest.raises(ParserUnavailableError, match="3 intentos"):
        parser.parse("Bench 80 por 8", [])

    assert completions.attempts == 3
    assert sleeps == [2.0, 4.0]


def test_fixture_contains_at_least_twenty_real_messages() -> None:
    fixture_path = Path("tests/fixtures/mensajes.json")
    messages = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert len(messages) >= 20
    assert all(item["ejercicios"] for item in messages)


def test_parser_validates_every_fixture_with_mocked_responses(tmp_path: Path) -> None:
    messages = json.loads(Path("tests/fixtures/mensajes.json").read_text(encoding="utf-8"))
    prompt_path = tmp_path / "parser.txt"
    prompt_path.write_text("Catálogo: {exercise_catalog}", encoding="utf-8")
    client, completions = build_client(
        [response_for_exercises(item["ejercicios"]) for item in messages]
    )
    parser = LLMParser(client=client, model="test-model", prompt_path=prompt_path)

    parsed_names = [
        [
            exercise.nombre
            for operation in parser.parse(item["texto"], []).operaciones
            for exercise in operation.datos.ejercicios
        ]
        for item in messages
    ]

    assert parsed_names == [item["ejercicios"] for item in messages]
    assert len(completions.calls) == len(messages)


def test_canonicalizer_returns_snake_case_and_group() -> None:
    client, _ = build_client(['{"nombre": "remo_t", "grupo_muscular": "dorsal"}'])
    canonicalizer = LLMCanonicalizer(
        client=client, model="test-model", prompt_path=CANONICALIZER_PROMPT
    )

    assert canonicalizer.canonicalize("remo t") == ("remo_t", "dorsal")


def test_canonicalizer_injects_known_catalog() -> None:
    client, completions = build_client(['{"nombre": "remo_t", "grupo_muscular": null}'])
    canonicalizer = LLMCanonicalizer(
        client=client,
        model="test-model",
        prompt_path=CANONICALIZER_PROMPT,
        catalog=["dominadas", "press_banca"],
    )

    canonicalizer.canonicalize("remo t")

    assert "dominadas, press_banca" in completions.calls[0]["messages"][0]["content"]


def test_canonicalizer_falls_back_to_slug_on_invalid_output() -> None:
    client, _ = build_client(["no soy json"])
    canonicalizer = LLMCanonicalizer(
        client=client, model="test-model", prompt_path=CANONICALIZER_PROMPT
    )

    assert canonicalizer.canonicalize("Remo T") == ("remo_t", None)


def test_canonicalizer_rejects_non_canonical_name() -> None:
    client, _ = build_client(['{"nombre": "Remo T!", "grupo_muscular": "dorsal"}'])
    canonicalizer = LLMCanonicalizer(
        client=client, model="test-model", prompt_path=CANONICALIZER_PROMPT
    )

    assert canonicalizer.canonicalize("remo t") == ("remo_t", None)


def test_canonicalizer_falls_back_when_groq_is_down() -> None:
    completions = FlakyCompletions(failures=99, response=None)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    canonicalizer = LLMCanonicalizer(
        client=client, model="test-model", prompt_path=CANONICALIZER_PROMPT
    )

    assert canonicalizer.canonicalize("remo t") == ("remo_t", None)


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

    response = parser.parse("Hice press banca 80 kilos por 8", [])

    assert response.operaciones[0].tipo == "gym"
