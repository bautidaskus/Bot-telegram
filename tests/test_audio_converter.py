from __future__ import annotations

from pathlib import Path

from src.ai.audio_converter import AudioConverter


def test_converter_creates_non_empty_ogg(tmp_path: Path) -> None:
    target = tmp_path / "converted.ogg"

    result = AudioConverter().convert_to_ogg(Path("tests/fixtures/speech.wav"), target)

    assert result == target
    assert target.stat().st_size > 0
