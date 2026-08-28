from __future__ import annotations

from decimal import Decimal

import pytest

from src.gym.capture import (
    AddSets,
    FinishSession,
    SetInput,
    SwitchExercise,
    UndoLastSet,
    Unrecognized,
    parse_capture_message,
)


@pytest.mark.parametrize("text", ["fin", "FIN", "listo", "terminé", "terminar"])
def test_finish_keywords(text: str) -> None:
    assert parse_capture_message(text) == FinishSession()


@pytest.mark.parametrize("text", ["deshacer", "borrar", "Deshacer"])
def test_undo_keywords(text: str) -> None:
    assert parse_capture_message(text) == UndoLastSet()


def test_single_number_is_one_set_at_current_weight() -> None:
    assert parse_capture_message("7") == AddSets([SetInput(reps=7, peso_kg=None)])


@pytest.mark.parametrize("text", ["10 8 6", "10,8,6", "10, 8, 6"])
def test_multiple_numbers_are_multiple_sets(text: str) -> None:
    expected = AddSets(
        [
            SetInput(reps=10, peso_kg=None),
            SetInput(reps=8, peso_kg=None),
            SetInput(reps=6, peso_kg=None),
        ]
    )
    assert parse_capture_message(text) == expected


def test_explicit_weight_by_reps() -> None:
    assert parse_capture_message("60x10") == AddSets([SetInput(reps=10, peso_kg=Decimal("60"))])


def test_mixed_explicit_and_bare_sets() -> None:
    assert parse_capture_message("60x10 8") == AddSets(
        [SetInput(reps=10, peso_kg=Decimal("60")), SetInput(reps=8, peso_kg=None)]
    )


def test_exercise_with_trailing_weight() -> None:
    assert parse_capture_message("remo t 60") == SwitchExercise(
        raw_name="remo t", peso_kg=Decimal("60")
    )


def test_exercise_with_decimal_weight() -> None:
    assert parse_capture_message("press banca 62.5") == SwitchExercise(
        raw_name="press banca", peso_kg=Decimal("62.5")
    )


def test_exercise_without_weight() -> None:
    assert parse_capture_message("dominadas") == SwitchExercise(raw_name="dominadas", peso_kg=None)


def test_prose_with_interleaved_numbers_is_unrecognized() -> None:
    assert parse_capture_message("hice 3 series de 10 con 60") == Unrecognized(
        "hice 3 series de 10 con 60"
    )


def test_decimal_weight_with_comma_in_set() -> None:
    assert parse_capture_message("62,5x10") == AddSets([SetInput(reps=10, peso_kg=Decimal("62.5"))])


def test_decimal_weight_with_comma_in_mixed_sets() -> None:
    assert parse_capture_message("62,5x10 8") == AddSets(
        [SetInput(reps=10, peso_kg=Decimal("62.5")), SetInput(reps=8, peso_kg=None)]
    )


def test_exercise_with_decimal_weight_comma() -> None:
    assert parse_capture_message("press banca 62,5") == SwitchExercise(
        raw_name="press banca", peso_kg=Decimal("62.5")
    )


def test_empty_message_is_unrecognized() -> None:
    assert parse_capture_message("   ") == Unrecognized("   ")
