"""Interpretación de fechas en español."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import dateparser


class DateParseError(ValueError):
    """Indica que una fecha de usuario no pudo interpretarse."""


def parse_spanish_date(
    raw: str,
    *,
    now: datetime | None = None,
    timezone: str = "America/Argentina/Buenos_Aires",
) -> date:
    """Convierte una fecha natural en español a fecha calendario."""

    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m"):
        try:
            parsed_explicit = datetime.strptime(raw, date_format)
        except ValueError:
            continue
        if date_format == "%d/%m":
            reference_year = (now or datetime.now(ZoneInfo(timezone))).year
            parsed_explicit = parsed_explicit.replace(year=reference_year)
        return parsed_explicit.date()

    reference = now or datetime.now(ZoneInfo(timezone))
    parsed = dateparser.parse(
        raw,
        languages=["es"],
        settings={
            "TIMEZONE": timezone,
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DATES_FROM": "past",
            "RELATIVE_BASE": reference.replace(tzinfo=None),
        },
    )
    if parsed is None:
        raise DateParseError(f"No se pudo interpretar la fecha: {raw}")
    return parsed.date()
