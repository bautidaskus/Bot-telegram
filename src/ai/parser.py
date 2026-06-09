"""Extracción estructurada de operaciones mediante Groq."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from openai import OpenAI
from pydantic import ValidationError

from src.config import Settings
from src.domain.schemas import ParserResponse


class CompletionsProtocol(Protocol):
    """Superficie del endpoint de chat usada por el parser."""

    def create(self, **kwargs: Any) -> Any:
        """Crea una respuesta de chat."""


class ChatProtocol(Protocol):
    """Contenedor del endpoint de completions."""

    completions: CompletionsProtocol


class ClientProtocol(Protocol):
    """Cliente mínimo compatible con OpenAI."""

    chat: ChatProtocol


class ParserError(RuntimeError):
    """Indica que el LLM no produjo una respuesta válida."""


class LLMParser:
    """Convierte lenguaje natural en operaciones tipadas."""

    def __init__(self, *, client: ClientProtocol, model: str, prompt_path: Path) -> None:
        self.client = client
        self.model = model
        self.prompt_template = prompt_path.read_text(encoding="utf-8")

    def parse(self, text: str, exercise_catalog: list[str]) -> ParserResponse:
        """Interpreta un mensaje y reintenta dos veces si la salida no valida."""

        system_prompt = self.prompt_template.format(
            exercise_catalog=", ".join(exercise_catalog) or "(vacío)"
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        last_error = "respuesta desconocida"
        for _ in range(3):
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
            )
            content = completion.choices[0].message.content or ""
            try:
                return ParserResponse.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as error:
                last_error = str(error)
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "La respuesta anterior no valida. Corregila y devolvé únicamente "
                                f"el objeto JSON. Error: {last_error}"
                            ),
                        },
                    ]
                )
        raise ParserError(
            f"El parser no produjo una respuesta válida tras 3 intentos: {last_error}"
        )


def create_groq_parser(
    settings: Settings, prompt_path: Path = Path("prompts/parser.txt")
) -> LLMParser:
    """Construye el parser con el cliente compatible de Groq."""

    client = OpenAI(
        api_key=settings.groq_api_key.get_secret_value(),
        base_url=settings.groq_base_url,
    )
    return LLMParser(client=client, model=settings.groq_llm_model, prompt_path=prompt_path)
