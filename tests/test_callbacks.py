from __future__ import annotations

import pytest

from src.bot.callbacks import (
    CallbackDataError,
    ClarificationCallback,
    PreviewCallback,
    build_clarification_callback,
    build_preview_callback,
    parse_callback,
)


@pytest.mark.parametrize("action", ["guardar", "cancelar", "corregir"])
def test_preview_callback_round_trip_stays_within_telegram_limit(action: str) -> None:
    callback_data = build_preview_callback(action, "12345678-1234-1234-1234-123456789012")

    assert len(callback_data.encode("utf-8")) <= 64
    assert parse_callback(callback_data) == PreviewCallback(
        action=action,
        preview_id="12345678-1234-1234-1234-123456789012",
    )


def test_clarification_callback_round_trip() -> None:
    callback_data = build_clarification_callback(42, "ingreso")

    assert len(callback_data.encode("utf-8")) <= 64
    assert parse_callback(callback_data) == ClarificationCallback(
        pending_id=42,
        hint="ingreso",
    )


@pytest.mark.parametrize("callback_data", ["", "preview:guardar", "unknown:value"])
def test_parse_callback_rejects_invalid_data(callback_data: str) -> None:
    with pytest.raises(CallbackDataError):
        parse_callback(callback_data)
