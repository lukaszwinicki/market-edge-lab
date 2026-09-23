"""Skale zmienności — `atr_h1_14` i `atr_d1_14`.

`atr_d1_14` wyznacza dystans stopu, czyli jednostkę R, czyli mianownik
każdej liczby raportowanej w R. Błąd tutaj nie daje złego sygnału —
daje poprawny sygnał wyrażony w złej walucie.

Wszystko na danych syntetycznych: na wymyślonym szeregu znamy ATR
z definicji, na prawdziwych świecach tylko widzimy, że coś wraca.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from src.data.resample import BAR_SCHEMA
from src.features.volatility import (
    atr_d1, atr_h1, attach_atr_d1, daily_bars, true_range, wilder_atr,
)

UTC = dt.timezone.utc


def h1_frame(rows: list[tuple[dt.datetime, float, float, float]]) -> pl.DataFrame:
    """Ramka H1 o pełnym schemacie barów; ask = bid + stały spread."""
    ts, hi, lo, cl = zip(*rows) if rows else ([], [], [], [])
    spread = 0.0001
    return pl.DataFrame(
        {
            "ts": list(ts),
            "bid_open": list(cl), "bid_high": list(hi),
            "bid_low": list(lo), "bid_close": list(cl),
            "ask_open": [c + spread for c in cl], "ask_high": [h + spread for h in hi],
            "ask_low": [l + spread for l in lo], "ask_close": [c + spread for c in cl],
            "spread_max": [spread] * len(ts), "spread_close": [spread] * len(ts),
            "n_ticks": [10] * len(ts),
        },
        schema=BAR_SCHEMA,
    )


def flat_hours(n_days: int, hours: int = 24, *, start: dt.datetime | None = None,
               high: float = 1.1010, low: float = 1.0990, close: float = 1.1000):
    """`n_days` dób po `hours` barów o identycznym zakresie."""
    t = start or dt.datetime(2020, 1, 1, tzinfo=UTC)
    rows = []
    for d in range(n_days):
        for h in range(hours):
            rows.append((t + dt.timedelta(days=d, hours=h), high, low, close))
    return rows


# --- true range ------------------------------------------------------------

def test_true_range_first_position_is_undefined():
    tr = true_range(np.array([2.0, 3.0]), np.array([1.0, 2.0]), np.array([1.5, 2.5]))
    assert np.isnan(tr[0])


def test_true_range_uses_previous_close_when_gap_exceeds_bar_range():
    # Bar 1: zakres 0,5, ale poprzednie zamknięcie leży 3,0 niżej.
    tr = true_range(
        high=np.array([1.0, 4.5]), low=np.array([0.5, 4.0]), close=np.array([1.0, 4.2])
    )
    assert tr[1] == pytest.approx(3.5)      # |high - prev_close| = 4,5 - 1,0


# --- Wilder ATR ------------------------------------------------------------

def test_wilder_atr_needs_period_plus_one_bars():
    hi, lo, cl = (np.full(14, 2.0), np.full(14, 1.0), np.full(14, 1.5))
    assert np.isnan(wilder_atr(hi, lo, cl, period=14)).all()


def test_wilder_atr_on_constant_range_equals_that_range():
    n = 40
    hi, lo, cl = np.full(n, 2.0), np.full(n, 1.0), np.full(n, 1.5)
    atr = wilder_atr(hi, lo, cl, period=14)
    assert np.isnan(atr[:14]).all()
    assert atr[14:] == pytest.approx(1.0)


def test_wilder_atr_recursion_matches_definition_after_a_shock():
    n = 20
    hi, lo, cl = np.full(n, 2.0), np.full(n, 1.0), np.full(n, 1.5)
    hi[15] = 11.0                                   # zakres 10,0 zamiast 1,0
    atr = wilder_atr(hi, lo, cl, period=14)
    assert atr[14] == pytest.approx(1.0)
    tr15 = max(11.0 - 1.0, abs(11.0 - 1.5), abs(1.0 - 1.5))
    assert atr[15] == pytest.approx((1.0 * 13 + tr15) / 14)
    assert atr[16] == pytest.approx((atr[15] * 13 + 1.0) / 14)


def test_wilder_atr_does_not_look_ahead():
    """Zmiana bara z przyszłości nie rusza żadnej wcześniejszej wartości.

    To jest test na przyczynowość, nie na wartość. Jego upadek oznacza
    wygładzanie dwustronne albo przesunięcie o zły znak — czyli przeciek.
    """
    n = 40
    hi, lo, cl = np.full(n, 2.0), np.full(n, 1.0), np.full(n, 1.5)
    base = wilder_atr(hi, lo, cl, period=14)
    hi2 = hi.copy()
    hi2[30] = 99.0
    changed = wilder_atr(hi2, lo, cl, period=14)
    assert np.allclose(base[14:30], changed[14:30])
    assert changed[30] > base[30]


# --- seria dzienna ---------------------------------------------------------

def test_daily_bars_aggregate_h1_within_the_utc_day():
    rows = [
        (dt.datetime(2020, 1, 1, h, tzinfo=UTC), 1.10 + h / 1000, 1.09, 1.095 + h / 1000)
        for h in range(24)
    ]
    d1 = daily_bars(h1_frame(rows), min_h1_bars=12)
    assert d1.height == 1
    assert d1["day"][0] == dt.datetime(2020, 1, 1, tzinfo=UTC)
    assert d1["bid_high"][0] == pytest.approx(1.10 + 23 / 1000)
    assert d1["bid_low"][0] == pytest.approx(1.09)
    assert d1["bid_close"][0] == pytest.approx(1.095 + 23 / 1000)
    assert d1["n_h1"][0] == 24


def test_daily_bars_drop_incomplete_days():
    """Sesja niedzielna nie tworzy doby — o to chodzi w `min_h1_bars`."""
    rows = flat_hours(1)                                     # poniedziałek pełny
    rows += [(dt.datetime(2020, 1, 2, h, tzinfo=UTC), 1.1001, 1.1000, 1.1000)
             for h in range(3)]                              # doba z 3 barami
    d1 = daily_bars(h1_frame(rows), min_h1_bars=12)
    assert d1.height == 1
    assert d1["day"].to_list() == [dt.datetime(2020, 1, 1, tzinfo=UTC)]


def test_incomplete_day_does_not_enter_the_atr_recursion():
    """Doba niepełna odpada PRZED wygładzaniem, nie po.

    Gdyby wchodziła, jej zakres bliski zeru zaniżyłby ATR — a ATR to
    dystans stopu, czyli jednostka R.
    """
    rows = flat_hours(30)
    # Trzy doby okrojone do 3 barów o znikomym zakresie.
    rows = [r for r in rows
            if not (r[0].day in (10, 11, 12) and r[0].hour >= 3)]
    for r in rows:
        if r[0].day in (10, 11, 12):
            assert r[0].hour < 3
    d1 = atr_d1(h1_frame(rows), min_h1_bars=12, period=14)
    assert d1.filter(pl.col("day").dt.day().is_in([10, 11, 12])).is_empty()
    good = d1.filter(pl.col("atr_d1_14").is_not_nan())
    assert good["atr_d1_14"].to_numpy() == pytest.approx(0.0020)


def test_atr_d1_on_constant_daily_range():
    d1 = atr_d1(h1_frame(flat_hours(30)), min_h1_bars=12, period=14)
    assert d1.height == 30
    assert np.isnan(d1["atr_d1_14"].to_numpy()[:14]).all()
    assert d1["atr_d1_14"].to_numpy()[14:] == pytest.approx(0.0020)


def test_available_from_is_the_start_of_the_next_day():
    d1 = atr_d1(h1_frame(flat_hours(20)), min_h1_bars=12, period=14)
    row = d1.row(0, named=True)
    assert row["available_from"] == row["day"] + dt.timedelta(days=1)


# --- połączenie z decyzjami: granica przecieku ------------------------------

def test_decision_gets_atr_of_the_last_closed_day():
    """Decyzja o 09:00 dostaje ATR z DNIA POPRZEDNIEGO, nie z dzisiejszego.

    Dzisiejsza doba zamyka się o północy po decyzji. Ten test jest jedynym
    miejscem, w którym ta granica jest sprawdzana wprost.
    """
    rows = flat_hours(20)
    # Doba 20.01 ma zakres 10× większy. Decyzje z 20.01 NIE mogą jej widzieć.
    rows = [(t, 1.1100 if t.day == 20 else h, l, c) for t, h, l, c in rows]
    d1 = atr_d1(h1_frame(rows), min_h1_bars=12, period=14)

    decisions = pl.DataFrame(
        {"ts": [dt.datetime(2020, 1, 20, 9, tzinfo=UTC),
                dt.datetime(2020, 1, 20, 23, tzinfo=UTC),
                dt.datetime(2020, 1, 21, 0, tzinfo=UTC)]},
        schema={"ts": pl.Datetime("ms", "UTC")},
    )
    got = attach_atr_d1(decisions, d1)["atr_d1_14"].to_list()
    before = d1.filter(pl.col("day") == dt.datetime(2020, 1, 19, tzinfo=UTC))["atr_d1_14"][0]
    after = d1.filter(pl.col("day") == dt.datetime(2020, 1, 20, tzinfo=UTC))["atr_d1_14"][0]

    assert got[0] == pytest.approx(before)     # 20.01 09:00 — jeszcze stara wartość
    assert got[1] == pytest.approx(before)     # 20.01 23:00 — wciąż stara
    assert got[2] == pytest.approx(after)      # 21.01 00:00 — doba zamknięta
    assert after > before


def test_decisions_before_warmup_get_null_not_a_seeded_value():
    d1 = atr_d1(h1_frame(flat_hours(30)), min_h1_bars=12, period=14)
    decisions = pl.DataFrame(
        {"ts": [dt.datetime(2020, 1, 5, 9, tzinfo=UTC)]},
        schema={"ts": pl.Datetime("ms", "UTC")},
    )
    assert attach_atr_d1(decisions, d1)["atr_d1_14"][0] is None


# --- atr_h1: druga skala, rozłączna rola -----------------------------------

def test_atr_h1_is_aligned_to_the_bar_label():
    frame = atr_h1(h1_frame(flat_hours(2)), period=14)
    vals = frame["atr_h1_14"].to_numpy()
    assert np.isnan(vals[:14]).all()
    assert vals[14:] == pytest.approx(0.0020)


def test_atr_h1_and_atr_d1_are_different_scales():
    """Ta sama seria, dwie skale. Mylenie ich degeneruje etykiety."""
    rows = flat_hours(30, high=1.1010, low=1.0990, close=1.1000)
    hourly = atr_h1(h1_frame(rows), period=14)["atr_h1_14"].to_numpy()
    daily = atr_d1(h1_frame(rows), min_h1_bars=12, period=14)["atr_d1_14"].to_numpy()
    # Zakres godzinowy i dobowy są tu równe z konstrukcji (bary identyczne),
    # ale serie mają różną długość i różne momenty dostępności — nie wolno
    # ich podstawiać jedna za drugą.
    assert hourly.size == 30 * 24
    assert daily.size == 30


def test_empty_input_does_not_raise():
    empty = pl.DataFrame(schema=BAR_SCHEMA)
    assert daily_bars(empty, 12).is_empty()
    assert atr_d1(empty, 12).is_empty()
    assert atr_h1(empty).is_empty()
