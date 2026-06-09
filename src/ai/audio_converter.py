"""Conversión de audio para formatos no aceptados directamente."""

from __future__ import annotations

from pathlib import Path

from pydub import AudioSegment


class AudioConverter:
    """Convierte archivos a OGG usando ffmpeg mediante pydub."""

    def convert_to_ogg(self, source: Path, target: Path) -> Path:
        """Convierte source a OGG/Opus y devuelve el destino."""

        AudioSegment.from_file(source).export(target, format="ogg", codec="libopus")
        return target
