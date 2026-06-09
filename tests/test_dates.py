from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.utils.dates import DateParseError, parse_spanish_date

NOW = datetime(2026, 6, 8, 9, 0, tzinfo=ZoneInfo("America/Argentina/Buenos_Aires"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("hoy", date(2026, 6, 8)),
        ("ayer", date(2026, 6, 7)),
        ("anteayer", date(2026, 6, 6)),
        ("lunes", date(2026, 6, 1)),
        ("07/06", date(2026, 6, 7)),
        ("2026-05-31", date(2026, 5, 31)),
    ],
)
def test_parse_spanish_date_resolves_relative_and_explicit_dates(raw: str, expected: date) -> None:
    assert parse_spanish_date(raw, now=NOW) == expected


def test_parse_spanish_date_rejects_unparseable_value() -> None:
    with pytest.raises(DateParseError, match="No se pudo interpretar"):
        parse_spanish_date("cuando pinte", now=NOW)
