"""Extracción estructurada de operaciones mediante Groq."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from pydantic import ValidationError

from src.config import Settings
from src.domain.schemas import ParserResponse

TRANSIENT_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)


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


class ParserUnavailableError(ParserError):
    """Indica que el servicio LLM no respondió tras varios reintentos."""


class LLMParser:
    """Convierte lenguaje natural en operaciones tipadas."""

    def __init__(
        self,
        *,
        client: ClientProtocol,
        model: str,
        prompt_path: Path,
        sleep: Callable[[float], None] = time.sleep,
        backoff_base: float = 2.0,
        api_attempts: int = 3,
    ) -> None:
        self.client = client
        self.model = model
        self.prompt_template = prompt_path.read_text(encoding="utf-8")
        self.sleep = sleep
        self.backoff_base = backoff_base
        self.api_attempts = api_attempts

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
            content = self._complete(messages)
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

    def _complete(self, messages: list[dict[str, str]]) -> str:
        """Llama a Groq reintentando con backoff exponencial ante fallos transitorios."""

        delay = self.backoff_base
        last_error: Exception | None = None
        for attempt in range(self.api_attempts):
            try:
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0,
                )
                return completion.choices[0].message.content or ""
            except TRANSIENT_ERRORS as error:
                last_error = error
                if attempt < self.api_attempts - 1:
                    self.sleep(delay)
                    delay *= 2
        raise ParserUnavailableError(
            f"Groq no respondió tras {self.api_attempts} intentos"
        ) from last_error


def create_groq_parser(
    settings: Settings, prompt_path: Path = Path("prompts/parser.txt")
) -> LLMParser:
    """Construye el parser con el cliente compatible de Groq."""

    client = OpenAI(
        api_key=settings.groq_api_key.get_secret_value(),
        base_url=settings.groq_base_url,
    )
    return LLMParser(client=client, model=settings.groq_llm_model, prompt_path=prompt_path)
