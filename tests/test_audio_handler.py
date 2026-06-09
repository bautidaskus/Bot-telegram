from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from src.ai.whisper_client import EmptyTranscriptionError
from src.bot.handlers import BotHandlers
from src.db.models import Base, Preview
from src.db.session import create_sqlite_engine
from src.domain.schemas import ParserResponse


class FakeTelegramFile:
    def __init__(self, content: bytes = b"audio") -> None:
        self.content = content
        self.downloads: list[Path] = []

    async def download_to_drive(self, custom_path: Path) -> None:
        path = Path(custom_path)
        path.write_bytes(self.content)
        self.downloads.append(path)


class FakeVoice:
    file_size = 100
    file_unique_id = "voice-id"

    def __init__(self, telegram_file: FakeTelegramFile) -> None:
        self.telegram_file = telegram_file

    async def get_file(self) -> FakeTelegramFile:
        return self.telegram_file


class FakeAudio(FakeVoice):
    file_name = "nota.wav"
    mime_type = "audio/wav"


class FakeMessage:
    def __init__(self, *, voice: Any = None, audio: Any = None) -> None:
        self.voice = voice
        self.audio = audio
        self.message_id = 456
        self.replies: list[tuple[str, Any]] = []

    async def reply_text(self, text: str, reply_markup: Any = None) -> Any:
        self.replies.append((text, reply_markup))
        return SimpleNamespace(message_id=789)


class FakeWhisper:
    def __init__(self, text: str) -> None:
        self.text = text
        self.paths: list[Path] = []

    def transcribe(self, audio_path: Path) -> str:
        self.paths.append(audio_path)
        return self.text


class EmptyWhisper(FakeWhisper):
    def transcribe(self, audio_path: Path) -> str:
        raise EmptyTranscriptionError("silencio")


class FakeParser:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def parse(self, text: str, exercise_catalog: list[str]) -> ParserResponse:
        self.calls.append(text)
        return ParserResponse.model_validate(
            {
                "operaciones": [
                    {
                        "tipo": "gasto",
                        "confianza": 0.95,
                        "fecha": "hoy",
                        "datos": {"monto": 1500, "categoria": "alimentos"},
                    }
                ]
            }
        )


class FakeConverter:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path]] = []

    def convert_to_ogg(self, source: Path, target: Path) -> Path:
        self.calls.append((source, target))
        target.write_bytes(source.read_bytes())
        return target


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_sqlite_engine(tmp_path / "audio.db")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def audio_update(message: FakeMessage, chat_id: int = 123) -> SimpleNamespace:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        effective_message=message,
        message=message,
    )


@pytest.mark.asyncio
async def test_voice_ogg_transcribes_directly_and_shows_transcription(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    telegram_file = FakeTelegramFile()
    message = FakeMessage(voice=FakeVoice(telegram_file))
    whisper = FakeWhisper("Gasté 1500 en el súper")
    parser = FakeParser()
    converter = FakeConverter()
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=parser,
        whisper=whisper,
        audio_converter=converter,
        session_factory=session_factory,
        temp_dir=tmp_path,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )

    await handlers.handle_audio(audio_update(message), SimpleNamespace())

    assert converter.calls == []
    assert parser.calls == ["Gasté 1500 en el súper"]
    assert "Transcripción: Gasté 1500 en el súper" in message.replies[0][0]
    with session_factory() as session:
        assert session.query(Preview).one().transcripcion == "Gasté 1500 en el súper"


@pytest.mark.asyncio
async def test_audio_file_uses_converter_before_transcription(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    message = FakeMessage(audio=FakeAudio(FakeTelegramFile()))
    whisper = FakeWhisper("Gasté 1500")
    converter = FakeConverter()
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(),
        whisper=whisper,
        audio_converter=converter,
        session_factory=session_factory,
        temp_dir=tmp_path,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )

    await handlers.handle_audio(audio_update(message), SimpleNamespace())

    assert len(converter.calls) == 1
    assert whisper.paths[0].suffix == ".ogg"


@pytest.mark.asyncio
async def test_audio_over_twenty_five_mb_is_rejected_before_download(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    telegram_file = FakeTelegramFile()
    voice = FakeVoice(telegram_file)
    voice.file_size = 25 * 1024 * 1024 + 1
    message = FakeMessage(voice=voice)
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(),
        whisper=FakeWhisper("unused"),
        audio_converter=FakeConverter(),
        session_factory=session_factory,
        temp_dir=tmp_path,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )

    await handlers.handle_audio(audio_update(message), SimpleNamespace())

    assert telegram_file.downloads == []
    assert "25 MB" in message.replies[0][0]


@pytest.mark.asyncio
async def test_silent_audio_returns_clear_message(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    message = FakeMessage(voice=FakeVoice(FakeTelegramFile()))
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(),
        whisper=EmptyWhisper(""),
        audio_converter=FakeConverter(),
        session_factory=session_factory,
        temp_dir=tmp_path,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )

    await handlers.handle_audio(audio_update(message), SimpleNamespace())

    assert "No entendí el audio" in message.replies[0][0]


@pytest.mark.asyncio
async def test_unauthorized_audio_is_ignored_before_download(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    telegram_file = FakeTelegramFile()
    message = FakeMessage(voice=FakeVoice(telegram_file))
    handlers = BotHandlers(
        allowed_chat_id=123,
        parser=FakeParser(),
        whisper=FakeWhisper("unused"),
        audio_converter=FakeConverter(),
        session_factory=session_factory,
        temp_dir=tmp_path,
        now=lambda: datetime(2026, 6, 9, 10, 0),
    )

    await handlers.handle_audio(audio_update(message, chat_id=999), SimpleNamespace())

    assert telegram_file.downloads == []
    assert message.replies == []
