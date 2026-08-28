"""Resolución de nombres de ejercicios escritos de cualquier forma."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from difflib import get_close_matches


@dataclass(frozen=True)
class CatalogEntry:
    """Ejercicio conocido con sus alias aprendidos."""

    exercise_id: int
    canonical: str
    aliases: list[str]


@dataclass(frozen=True)
class MatchResult:
    """Ejercicio resuelto y, si hubo que aproximar, el alias a aprender."""

    exercise_id: int
    canonical: str
    learned_alias: str | None


def normalize(text: str) -> str:
    """Baja a minúsculas, saca acentos y unifica guiones bajos con espacios."""

    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    without_accents = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(without_accents.replace("_", " ").split())


def match_exercise(
    raw: str, catalog: list[CatalogEntry], cutoff: float = 0.8
) -> MatchResult | None:
    """Resuelve un nombre por coincidencia exacta y, si falla, por distancia de edición."""

    needle = normalize(raw)
    if not needle:
        return None
    index: dict[str, CatalogEntry] = {}
    for entry in catalog:
        index[normalize(entry.canonical)] = entry
        for alias in entry.aliases:
            index.setdefault(normalize(alias), entry)
    if needle in index:
        entry = index[needle]
        return MatchResult(entry.exercise_id, entry.canonical, learned_alias=None)
    approximations = get_close_matches(needle, list(index), n=1, cutoff=cutoff)
    if not approximations:
        return None
    entry = index[approximations[0]]
    return MatchResult(entry.exercise_id, entry.canonical, learned_alias=needle)
