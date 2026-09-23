"""Marża swapu — człon kosztu, którego symulator nie zna.

Prerejestracja obiecywała oś wrażliwości na marżę swapu, a model kosztów
w symulatorze nie ma jej wcale. Zanim policzymy, ile ten brak kosztuje,
funkcja licząca musi mieć własny kontrakt — inaczej „brakujący koszt to
0,023 R" byłoby liczbą bez pokrycia.

Wszystko na kalendarzu syntetycznym: dni tygodnia znamy z definicji.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.execution.swap import financing_days, swap_margin_cost, swap_margin_r

UTC = dt.timezone.utc

MON = dt.datetime(2020, 1, 6, 12, tzinfo=UTC)      # poniedziałek
TUE = dt.datetime(2020, 1, 7, 12, tzinfo=UTC)
WED = dt.datetime(2020, 1, 8, 12, tzinfo=UTC)
THU = dt.datetime(2020, 1, 9, 12, tzinfo=UTC)
FRI = dt.datetime(2020, 1, 10, 12, tzinfo=UTC)
SAT = dt.datetime(2020, 1, 11, 12, tzinfo=UTC)
SUN = dt.datetime(2020, 1, 12, 12, tzinfo=UTC)
NEXT_MON = dt.datetime(2020, 1, 13, 12, tzinfo=UTC)


# --- liczenie rolowań ------------------------------------------------------

def test_intraday_position_pays_nothing():
    """23 godziny w obrębie doby to zero rolowań — liczy się granica, nie czas."""
    a = dt.datetime(2020, 1, 6, 0, 30, tzinfo=UTC)
    b = dt.datetime(2020, 1, 6, 23, 30, tzinfo=UTC)
    assert financing_days(a, b) == 0


def test_single_overnight_is_one_day():
    assert financing_days(MON, TUE) == 1


def test_wednesday_rolls_triple():
    """Środa → czwartek przenosi rozliczenie przez weekend, stąd 3×."""
    assert financing_days(WED, THU) == 3


def test_wednesday_triple_can_be_switched_off():
    assert financing_days(WED, THU, triple_on_wednesday=False) == 1


def test_weekend_does_not_roll():
    """Sobota i niedziela nie rolują — rynek stoi."""
    assert financing_days(FRI, SAT) == 1        # piątek się kończy, to się liczy
    assert financing_days(SAT, SUN) == 0
    assert financing_days(SAT, NEXT_MON) == 0


def test_friday_to_monday_costs_one_day():
    """Weekend nie jest darmowy w sensie kalendarza, ale rolowania są dwa
    zerowe — finansowanie weekendu siedzi w potrójnej środzie."""
    assert financing_days(FRI, NEXT_MON) == 1


def test_full_week_costs_seven_days():
    """1+1+3+1+1+0+0 = 7. Jeżeli ta suma się rozjedzie, model rolowania
    przestaje być spójny z kalendarzem i wszystkie koszty są złe."""
    assert financing_days(MON, NEXT_MON) == 7


def test_full_week_without_triple_costs_five():
    assert financing_days(MON, NEXT_MON, triple_on_wednesday=False) == 5


def test_ten_business_days_spans_two_wednesdays():
    # 06.01 → 20.01 to dwa pełne tygodnie.
    assert financing_days(MON, dt.datetime(2020, 1, 20, 12, tzinfo=UTC)) == 14


def test_requires_timezone_and_ordering():
    with pytest.raises(ValueError):
        financing_days(dt.datetime(2020, 1, 6, 12), TUE)
    with pytest.raises(ValueError):
        financing_days(TUE, MON)


# --- przeliczenie na cenę i na R -------------------------------------------

def test_cost_is_linear_in_margin_and_days():
    a = swap_margin_cost(1.1000, MON, TUE, 0.01)
    b = swap_margin_cost(1.1000, MON, TUE, 0.02)
    assert b == pytest.approx(2 * a)
    week = swap_margin_cost(1.1000, MON, NEXT_MON, 0.01)
    assert week == pytest.approx(7 * a)


def test_cost_matches_the_formula():
    got = swap_margin_cost(1.1000, MON, TUE, 0.01)
    assert got == pytest.approx(1.1000 * 0.01 * 1 / 365)


def test_cost_is_never_negative():
    assert swap_margin_cost(1.1000, MON, MON, 0.02) == 0.0
    with pytest.raises(ValueError):
        swap_margin_cost(1.1000, MON, TUE, -0.01)


def test_r_units_scale_inversely_with_stop_distance():
    """Ten sam koszt boli dwa razy mocniej przy dwa razy ciaśniejszym stopie.

    To jest powód, dla którego krótszy horyzont nie jest darmowy: mniejszy
    dystans stopu podnosi KAŻDY koszt wyrażony w R.
    """
    wide = swap_margin_r(1.1000, 0.0184, MON, NEXT_MON, 0.01)
    tight = swap_margin_r(1.1000, 0.0092, MON, NEXT_MON, 0.01)
    assert tight == pytest.approx(2 * wide)


def test_r_units_match_hand_calculation():
    """Rząd wielkości, który M03 ma zgłosić — policzony ręcznie.

    EURUSD ~1,10, stop 2,0 × atr_d1_14 ≈ 0,0184, trzymane 14 dni
    finansowania przy marży 1% rocznie.
    """
    got = swap_margin_r(1.1000, 0.0184, MON, dt.datetime(2020, 1, 20, 12, tzinfo=UTC), 0.01)
    expected = 1.1000 * 0.01 * 14 / 365 / 0.0184
    assert got == pytest.approx(expected)
    assert got == pytest.approx(0.0229, abs=5e-4)


def test_zero_stop_distance_is_an_error_not_infinity():
    with pytest.raises(ValueError):
        swap_margin_r(1.1000, 0.0, MON, TUE, 0.01)
