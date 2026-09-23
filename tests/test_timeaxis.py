"""Oś czasu — arytmetyka dni roboczych.

Moduł jest przeniesiony (ADR-005), a używały go dotąd wyłącznie testy innych
modułów, jako pomocnik. Przeniesiony kod nie dziedziczy zaufania, a bariera
czasowa liczona tą funkcją wyznacza `t1` w audycie mocy — czyli wprost liczbę
obserwacji efektywnych. Tu jest jej własny kontrakt.

Dane syntetyczne: na kalendarzu znamy poprawną odpowiedź.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.data.timeaxis import add_business_days

UTC = dt.timezone.utc

# Środa 2020-01-01. Świadomie Nowy Rok: funkcja NIE zna świąt i nie ma znać
# — patrz docstring modułu. Święta obsługuje symulator brakiem danych.
WED = dt.datetime(2020, 1, 1, 10, 0, tzinfo=UTC)


def test_zero_days_is_identity():
    assert add_business_days(WED, 0) == WED


def test_within_week_moves_by_calendar_days():
    assert add_business_days(WED, 2) == dt.datetime(2020, 1, 3, 10, tzinfo=UTC)


def test_weekend_is_skipped_not_counted():
    # Piątek 3.01 + 1 dzień roboczy = poniedziałek 6.01, nie sobota 4.01.
    fri = dt.datetime(2020, 1, 3, 10, tzinfo=UTC)
    assert add_business_days(fri, 1) == dt.datetime(2020, 1, 6, 10, tzinfo=UTC)


def test_ten_business_days_spans_two_weekends():
    # Środa + 10 dni roboczych = 14 dni kalendarzowych. To jest liczba, od
    # której zależy nakładanie okien wynikowych przy h = 10 d.
    assert add_business_days(WED, 10) == dt.datetime(2020, 1, 15, 10, tzinfo=UTC)


def test_three_business_days_spans_one_weekend_when_started_late_in_week():
    thu = dt.datetime(2020, 1, 2, 10, tzinfo=UTC)
    assert add_business_days(thu, 3) == dt.datetime(2020, 1, 7, 10, tzinfo=UTC)


def test_start_on_weekend_lands_on_business_day():
    # Sobota + 1 = poniedziałek. Wejścia z sesji niedzielnej istnieją,
    # więc punkt startowy w weekendzie nie jest teoretyczny.
    sat = dt.datetime(2020, 1, 4, 22, tzinfo=UTC)
    assert add_business_days(sat, 1) == dt.datetime(2020, 1, 6, 22, tzinfo=UTC)
    sun = dt.datetime(2020, 1, 5, 22, tzinfo=UTC)
    assert add_business_days(sun, 1) == dt.datetime(2020, 1, 6, 22, tzinfo=UTC)


def test_negative_moves_backwards_over_weekend():
    # Okno purge przed grupą testową liczy się tą samą funkcją.
    mon = dt.datetime(2020, 1, 6, 10, tzinfo=UTC)
    assert add_business_days(mon, -1) == dt.datetime(2020, 1, 3, 10, tzinfo=UTC)
    assert add_business_days(mon, -5) == dt.datetime(2019, 12, 30, 10, tzinfo=UTC)


def test_time_of_day_is_preserved():
    t = dt.datetime(2020, 1, 1, 23, 59, 30, tzinfo=UTC)
    assert add_business_days(t, 10).timetz() == t.timetz()


@pytest.mark.parametrize("n", [1, 2, 3, 5, 10, 21])
def test_result_is_always_a_weekday(n):
    for day in range(1, 29):
        t = dt.datetime(2021, 3, day, 12, tzinfo=UTC)
        assert add_business_days(t, n).weekday() < 5


@pytest.mark.parametrize("n", [1, 3, 10])
def test_forward_then_backward_returns_start_for_business_days(n):
    # Odwracalność trzyma dla startów w dni robocze. Dla weekendu nie trzyma
    # i trzymać nie może — sobota i niedziela mapują się na ten sam
    # poniedziałek. Test pilnuje dokładnie tej granicy.
    t = dt.datetime(2021, 3, 10, 12, tzinfo=UTC)          # środa
    assert add_business_days(add_business_days(t, n), -n) == t


def test_weekend_start_is_not_reversible_and_that_is_intended():
    sat = dt.datetime(2021, 3, 13, 12, tzinfo=UTC)
    assert add_business_days(add_business_days(sat, 1), -1) != sat
