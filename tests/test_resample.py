"""Testy agregacji ticków do barów.

Na prawdziwych tickach nie znamy poprawnej odpowiedzi, więc oracle jest
syntetyczny: konstruujemy serie o znanej z góry agregacji.
"""
import datetime as dt

import numpy as np
import polars as pl
import pytest

from src.data.dukascopy import TickBlock
from src.data.resample import (
    FREQ_H1, FREQ_M1, aggregate_bars, bars_from_ticks, decision_time_for_bar,
    last_closed_bar, ticks_to_frame, validate_bars,
)

UTC = dt.timezone.utc
H = dt.datetime(2020, 1, 2, 10, tzinfo=UTC)


def block(offsets_s, bids, asks, symbol="EURUSD", hour=H) -> TickBlock:
    base = np.datetime64(hour.replace(tzinfo=None), "ms")
    ts = base + np.array(offsets_s, dtype="timedelta64[s]").astype("timedelta64[ms]")
    n = len(offsets_s)
    return TickBlock(
        symbol=symbol, hour=hour, ts=ts,
        bid=np.asarray(bids, dtype=np.float64),
        ask=np.asarray(asks, dtype=np.float64),
        bid_vol=np.ones(n, np.float32), ask_vol=np.ones(n, np.float32),
    )


# --- Konwencja etykietowania — najważniejsze w całym module -----------------

def test_bar_label_is_start_of_interval():
    """Bar 10:00 obejmuje [10:00, 10:01), a nie (09:59, 10:00]."""
    t = ticks_to_frame([block([0, 30, 59, 60], [1.1] * 4, [1.2] * 4)])
    bars = bars_from_ticks(t, FREQ_M1)
    assert bars["ts"].to_list() == [
        dt.datetime(2020, 1, 2, 10, 0, tzinfo=UTC),
        dt.datetime(2020, 1, 2, 10, 1, tzinfo=UTC),
    ]
    assert bars["n_ticks"].to_list() == [3, 1]   # tick o 60s idzie do kolejnego bara


def test_last_closed_bar_h1():
    """O 10:00:00 bar 10:00 dopiero się zaczyna — ostatni kompletny to 09:00."""
    assert last_closed_bar(H, 3600) == dt.datetime(2020, 1, 2, 9, tzinfo=UTC)


def test_last_closed_bar_mid_interval():
    t = dt.datetime(2020, 1, 2, 10, 37, 12, tzinfo=UTC)
    assert last_closed_bar(t, 3600) == dt.datetime(2020, 1, 2, 9, tzinfo=UTC)
    assert last_closed_bar(t, 60) == dt.datetime(2020, 1, 2, 10, 36, tzinfo=UTC)


def test_last_closed_bar_requires_timezone():
    with pytest.raises(ValueError):
        last_closed_bar(dt.datetime(2020, 1, 2, 10), 3600)


def test_decision_time_is_inverse_of_last_closed_bar():
    """Bar 09:00 pozwala decydować najwcześniej o 10:00, nie o 09:00."""
    bar = dt.datetime(2020, 1, 2, 9, tzinfo=UTC)
    assert decision_time_for_bar(bar, 3600) == H
    for h in range(0, 48, 7):
        t = bar + dt.timedelta(hours=h)
        assert last_closed_bar(decision_time_for_bar(t, 3600), 3600) == t


def test_decision_time_rejects_non_bar_label():
    with pytest.raises(ValueError):
        decision_time_for_bar(dt.datetime(2020, 1, 2, 9, 30, tzinfo=UTC), 3600)


# --- OHLC -------------------------------------------------------------------

def test_ohlc_values_are_exact():
    t = ticks_to_frame([block(
        [0, 10, 20, 30],
        [1.1000, 1.1050, 1.0950, 1.1020],
        [1.1002, 1.1053, 1.0951, 1.1023],
    )])
    b = bars_from_ticks(t, FREQ_M1).row(0, named=True)
    assert b["bid_open"] == 1.1000
    assert b["bid_high"] == 1.1050
    assert b["bid_low"] == 1.0950
    assert b["bid_close"] == 1.1020
    assert b["ask_open"] == 1.1002
    assert b["ask_close"] == 1.1023
    assert b["n_ticks"] == 4


def test_bid_and_ask_aggregated_independently():
    """Ask nie może być wyprowadzany z bida ani ze średniej."""
    t = ticks_to_frame([block([0, 10], [1.1000, 1.1000], [1.1002, 1.1009])])
    b = bars_from_ticks(t, FREQ_M1).row(0, named=True)
    assert b["bid_high"] == b["bid_low"] == 1.1000     # bid się nie ruszył
    assert b["ask_high"] == 1.1009 and b["ask_low"] == 1.1002


def test_spread_max_is_worst_case_not_average():
    t = ticks_to_frame([block([0, 10, 20], [1.1, 1.1, 1.1], [1.1002, 1.1050, 1.1003])])
    b = bars_from_ticks(t, FREQ_M1).row(0, named=True)
    assert b["spread_max"] == pytest.approx(0.0050)     # najgorszy moment
    assert b["spread_close"] == pytest.approx(0.0003)   # a nie ostatni


# --- Luki -------------------------------------------------------------------

def test_gaps_produce_no_bar_not_a_filled_one():
    """Brak ticków = brak bara. Żadnego wypełniania ani bara zerowego."""
    t = ticks_to_frame([block([0, 180], [1.1, 1.2], [1.11, 1.21])])
    bars = bars_from_ticks(t, FREQ_M1)
    assert bars.height == 2
    assert bars["ts"].to_list() == [
        dt.datetime(2020, 1, 2, 10, 0, tzinfo=UTC),
        dt.datetime(2020, 1, 2, 10, 3, tzinfo=UTC),
    ]   # minuty 10:01 i 10:02 po prostu nie istnieją


def test_empty_input_gives_empty_frame_with_schema():
    bars = bars_from_ticks(ticks_to_frame([]), FREQ_M1)
    assert bars.is_empty()
    assert bars.columns[:3] == ["ts", "bid_open", "bid_high"]


# --- Niezmiennik agregacji --------------------------------------------------

def test_h1_from_m1_equals_h1_from_ticks():
    """M1 -> H1 musi dać dokładnie to samo, co ticki -> H1."""
    rng = np.random.default_rng(42)
    offs = np.sort(rng.choice(3600, size=2000, replace=False))
    bid = 1.10 + rng.normal(0, 0.001, len(offs))
    t = ticks_to_frame([block(offs.tolist(), bid, bid + rng.uniform(1e-5, 5e-5, len(offs)))])

    direct = bars_from_ticks(t, FREQ_H1)
    via_m1 = aggregate_bars(bars_from_ticks(t, FREQ_M1), FREQ_H1)

    assert direct.equals(via_m1)


# --- Walidacja --------------------------------------------------------------

def test_validate_rejects_negative_spread():
    bars = bars_from_ticks(ticks_to_frame([block([0], [1.1005], [1.1000])]), FREQ_M1)
    with pytest.raises(ValueError, match="spread ujemny"):
        validate_bars(bars)


def test_validate_accepts_clean_bars():
    t = ticks_to_frame([block([0, 10, 20], [1.1000, 1.1050, 1.1020],
                              [1.1002, 1.1053, 1.1023])])
    validate_bars(bars_from_ticks(t, FREQ_M1))   # nie rzuca


def test_validate_rejects_duplicate_labels():
    bars = pl.DataFrame({
        "ts": [dt.datetime(2020, 1, 2, 10, tzinfo=UTC)] * 2,
        "bid_open": [1.1, 1.1], "bid_high": [1.1, 1.1], "bid_low": [1.1, 1.1],
        "bid_close": [1.1, 1.1], "ask_open": [1.2, 1.2], "ask_high": [1.2, 1.2],
        "ask_low": [1.2, 1.2], "ask_close": [1.2, 1.2],
        "spread_max": [0.1, 0.1], "spread_close": [0.1, 0.1],
        "n_ticks": pl.Series([1, 1], dtype=pl.UInt32),
    })
    with pytest.raises(ValueError, match="zduplikowane"):
        validate_bars(bars)


# --- Jednostki: pips zależy od symbolu --------------------------------------

def test_pip_size_differs_for_jpy_pairs():
    """Sztywne 1e-4 dawało dla EURJPY 'spread 90 pipsów' zamiast 0.9."""
    from src.data.dukascopy import pip_size
    assert pip_size("EURUSD") == pytest.approx(1e-4)
    assert pip_size("GBPUSD") == pytest.approx(1e-4)
    assert pip_size("USDJPY") == pytest.approx(1e-2)
    assert pip_size("EURJPY") == pytest.approx(1e-2)


def test_typical_spreads_land_in_plausible_pip_range():
    from src.data.dukascopy import pip_size
    assert 0.2 <= 0.00003 / pip_size("EURUSD") <= 0.5     # 0.3 pipsa
    assert 0.5 <= 0.009 / pip_size("EURJPY") <= 1.5       # 0.9 pipsa
