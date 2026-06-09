from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAI

from src.ai.whisper_client import AudioTooLargeError, EmptyTranscriptionError, WhisperClient


class FakeTranscriptions:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text)


def build_client(text: str) -> tuple[SimpleNamespace, FakeTranscriptions]:
    transcriptions = FakeTranscriptions(text)
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=transcriptions))
    return client, transcriptions


def test_transcribe_sends_audio_to_groq_in_spanish(tmp_path: Path) -> None:
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"fake ogg")
    client, transcriptions = build_client("Gasté mil quinientos")
    whisper = WhisperClient(client=client, model="test-whisper")

    text = whisper.transcribe(audio_path)

    assert text == "Gasté mil quinientos"
    call = transcriptions.calls[0]
    assert call["model"] == "test-whisper"
    assert call["language"] == "es"
    assert call["file"].closed is True


def test_transcribe_rejects_file_over_telegram_download_limit(tmp_path: Path) -> None:
    audio_path = tmp_path / "large.ogg"
    with audio_path.open("wb") as audio:
        audio.truncate(20 * 1024 * 1024 + 1)
    client, transcriptions = build_client("unused")

    with pytest.raises(AudioTooLargeError, match="20 MB"):
        WhisperClient(client=client, model="test-whisper").transcribe(audio_path)

    assert transcriptions.calls == []


def test_transcribe_rejects_empty_text(tmp_path: Path) -> None:
    audio_path = tmp_path / "silence.ogg"
    audio_path.write_bytes(b"silence")
    client, _ = build_client("   ")

    with pytest.raises(EmptyTranscriptionError):
        WhisperClient(client=client, model="test-whisper").transcribe(audio_path)


@pytest.mark.live
def test_live_whisper_transcribes_speech_fixture() -> None:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY no configurada")
    whisper = WhisperClient(
        client=OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1"),
        model=os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3"),
    )

    text = whisper.transcribe(Path("tests/fixtures/speech.ogg"))

    assert text
