import pytest

from bluegrass.research.sums import (
    build_root_sums_board,
    build_sums_board,
    digit_sum,
    root_sum,
)


# --- pure math ---

def test_digit_sum_basic() -> None:
    assert digit_sum("123") == 6
    assert digit_sum("000") == 0
    assert digit_sum("999") == 27


def test_digit_sum_leading_zeros() -> None:
    assert digit_sum("007") == 7
    assert digit_sum("012") == 3


def test_root_sum_zero() -> None:
    assert root_sum("000") == 0


def test_root_sum_multiples_of_nine_become_nine() -> None:
    assert root_sum("999") == 9   # 27 % 9 == 0 → 9
    assert root_sum("900") == 9   # 9 % 9 == 0 → 9
    assert root_sum("360") == 9   # 9 % 9 == 0 → 9


def test_root_sum_non_multiple() -> None:
    assert root_sum("123") == 6   # 6 % 9 == 6
    assert root_sum("456") == 6   # 15 % 9 == 6


def test_root_sum_full_range() -> None:
    for i in range(1000):
        val = str(i).zfill(3)
        rs = root_sum(val)
        assert 0 <= rs <= 9, f"root_sum({val!r}) = {rs} out of 0-9 range"


# --- board builders against real baseline data ---

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_sums_board_non_empty(session: str) -> None:
    assert len(build_sums_board(session)) > 0


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_sums_board_sorted_descending(session: str) -> None:
    board = build_sums_board(session)
    ds = [r["draws_since"] for r in board]
    assert ds == sorted(ds, reverse=True)


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_sums_board_values_in_pick3_range(session: str) -> None:
    board = build_sums_board(session)
    assert all(0 <= int(r["value"]) <= 27 for r in board)


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_root_sums_board_non_empty(session: str) -> None:
    assert len(build_root_sums_board(session)) > 0


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_root_sums_board_values_in_range(session: str) -> None:
    board = build_root_sums_board(session)
    assert all(0 <= int(r["value"]) <= 9 for r in board)


def test_sums_board_limit() -> None:
    assert len(build_sums_board("Midday", limit=5)) == 5


def test_root_sums_board_limit() -> None:
    assert len(build_root_sums_board("Night", limit=3)) == 3


def test_sums_board_entry_shape() -> None:
    row = build_sums_board("Evening", limit=1)[0]
    assert row["family"] == "sum"
    assert "value" in row
    assert "draws_since" in row
    assert "last_seen" in row
    assert row["session"] == "Evening"


def test_root_sums_board_entry_shape() -> None:
    row = build_root_sums_board("Midday", limit=1)[0]
    assert row["family"] == "root_sum"
    assert row["session"] == "Midday"
