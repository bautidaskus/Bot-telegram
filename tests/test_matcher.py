from __future__ import annotations

import pytest

from src.gym.matcher import CatalogEntry, match_exercise, normalize

CATALOG = [
    CatalogEntry(exercise_id=1, canonical="dominadas", aliases=[]),
    CatalogEntry(exercise_id=2, canonical="remo_unilateral", aliases=["remo uni"]),
    CatalogEntry(exercise_id=3, canonical="press_banca", aliases=[]),
]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Dominadas", "dominadas"),
        ("  DOMINADAS  ", "dominadas"),
        ("press banca", "press banca"),
        ("press_banca", "press banca"),
        ("Bíceps", "biceps"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_exact_match_on_canonical_learns_nothing() -> None:
    result = match_exercise("press banca", CATALOG)
    assert result is not None
    assert (result.exercise_id, result.canonical, result.learned_alias) == (3, "press_banca", None)


def test_exact_match_on_alias() -> None:
    result = match_exercise("remo uni", CATALOG)
    assert result is not None
    assert result.exercise_id == 2
    assert result.learned_alias is None


def test_typo_matches_and_learns_alias() -> None:
    result = match_exercise("dominasas", CATALOG)
    assert result is not None
    assert result.canonical == "dominadas"
    assert result.learned_alias == "dominasas"


def test_unknown_exercise_returns_none() -> None:
    assert match_exercise("remo t", CATALOG) is None


def test_short_unrelated_input_does_not_match() -> None:
    assert match_exercise("curl", CATALOG) is None
