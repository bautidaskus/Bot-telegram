"""Transcripción de audio mediante Groq Whisper."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from openai import OpenAI

from src.config import Settings

MAX_AUDIO_BYTES = 20 * 1024 * 1024


class TranscriptionsProtocol(Protocol):
    """Endpoint mínimo de transcripciones."""

    def create(self, **kwargs: Any) -> Any:
        """Transcribe un archivo."""


class AudioProtocol(Protocol):
    """Contenedor del endpoint de transcripciones."""

    transcriptions: TranscriptionsProtocol


class WhisperClientProtocol(Protocol):
    """Cliente mínimo compatible con OpenAI."""

    audio: AudioProtocol


class AudioTooLargeError(ValueError):
    """Indica que el archivo supera el límite descargable de Telegram."""


class EmptyTranscriptionError(ValueError):
    """Indica que Whisper no detectó texto útil."""


class WhisperClient:
    """Cliente tipado para transcribir audio en español."""

    def __init__(self, *, client: WhisperClientProtocol, model: str) -> None:
        self.client = client
        self.model = model

    def transcribe(self, audio_path: Path) -> str:
        """Transcribe un archivo local y devuelve texto no vacío."""

        if audio_path.stat().st_size > MAX_AUDIO_BYTES:
            raise AudioTooLargeError("El audio supera el límite de 20 MB")
        with audio_path.open("rb") as audio_file:
            response = self.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file,
                language="es",
            )
        text = response.text.strip()
        if not text:
            raise EmptyTranscriptionError("No se detectó habla en el audio")
        return text


def create_groq_whisper(settings: Settings) -> WhisperClient:
    """Construye el cliente Whisper con configuración Groq."""

    client = OpenAI(
        api_key=settings.groq_api_key.get_secret_value(),
        base_url=settings.groq_base_url,
    )
    return WhisperClient(client=client, model=settings.groq_whisper_model)
