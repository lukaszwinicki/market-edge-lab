"""Testy `mom_k` na cenach SYNTETYCZNYCH, o znanej odpowiedzi.

Na prawdziwych tickach nie wiadomo, ile `mom_480` „powinno" wynosić, więc
przebieg, który coś zwraca, nie jest dowodem, że zwraca to, co trzeba.
Tutaj ruch ceny jest wpisany ręcznie i poprawny wynik da się policzyć na
kartce.

Trzy rzeczy do pilnowania:

1. Wartość zgadza się z definicją — łącznie z `sqrt(k)`, bez którego trzy
   komórki siatki T003 mierzyłyby trzy różne rzeczy.
2. Okno sięga dokładnie `k` barów wstecz, ani jednego dalej.
3. Bar bez pełnego okna daje NaN, a nie podstawioną liczbę.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from src.features.momentum import attach_mom, attach_to_decisions, mom
from src.features.volatility import atr_h1

UTC = dt.timezone.utc


def bars(closes, atr=1.0):
    n = len(closes)
    ts = [dt.datetime(2020, 1, 1, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(n)]
    return pl.DataFrame({
        "ts": ts,
        "bid_close": [float(c) for c in closes],
        "atr_h1_14": [float(atr)] * n,
    })


# --------------------------------------------------------------------------
# Definicja
# --------------------------------------------------------------------------

def test_mom_matches_definition_by_hand():
    """Ruch +10 przy ATR 2 i k=4: 10 / (2 * 2) = 2,5."""
    close = np.array([100.0, 101, 102, 103, 110])
    atr = np.full(5, 2.0)
    got = mom(close, atr, 4)
    assert got[4] == pytest.approx(10.0 / (2.0 * np.sqrt(4)))
    assert got[4] == pytest.approx(2.5)


def test_sqrt_k_puts_different_lookbacks_on_one_scale():
    """Błądzenie losowe: `mom_k` ma tę samą skalę dla każdego k.

    Bez dzielenia przez sqrt(k) odchylenie `mom_480` byłoby ~4,5x większe od
    `mom_24`, a siatka T003 porównywałaby nieporównywalne.
    """
    rng = np.random.default_rng(3)
    close = np.cumsum(rng.standard_normal(200_000))
    atr = np.ones(close.size)
    sd = {k: np.nanstd(mom(close, atr, k)) for k in (24, 120, 480)}
    assert max(sd.values()) / min(sd.values()) < 1.1
    # Kontrola negatywna: bez sqrt(k) skala rozjeżdża się o rząd wielkości.
    raw = {k: np.nanstd(close[k:] - close[:-k]) for k in (24, 120, 480)}
    assert raw[480] / raw[24] > 3


def test_direction_of_the_feature_follows_the_move():
    assert mom(np.array([100.0, 105]), np.ones(2), 1)[1] > 0
    assert mom(np.array([100.0, 95]), np.ones(2), 1)[1] < 0
    assert mom(np.array([100.0, 100]), np.ones(2), 1)[1] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Granica okna
# --------------------------------------------------------------------------

def test_window_reaches_exactly_k_bars_back():
    """Skok ceny dokładnie k barów wstecz MUSI być widoczny; k+1 — już nie."""
    k = 5
    close = np.array([100.0] * 20)
    close[10:] = 200.0                      # skok między barem 9 a 10
    atr = np.ones(close.size)
    got = mom(close, atr, k)
    assert got[10 + k - 1] == pytest.approx(100.0 / np.sqrt(k))   # skok w oknie
    assert got[10 + k] == pytest.approx(0.0)                       # wypadł z okna


def test_bars_without_full_lookback_are_nan_not_zero():
    got = mom(np.arange(10, dtype=float), np.ones(10), 4)
    assert np.isnan(got[:4]).all()
    assert not np.isnan(got[4:]).any()


def test_shorter_series_than_k_is_all_nan():
    assert np.isnan(mom(np.arange(3, dtype=float), np.ones(3), 10)).all()


def test_nonpositive_atr_gives_nan_not_infinity():
    """ATR zero to brak skali, nie nieskończona przewaga."""
    close = np.array([100.0, 110.0])
    got = mom(close, np.array([1.0, 0.0]), 1)
    assert np.isnan(got[1])


def test_k_must_be_positive():
    with pytest.raises(ValueError):
        mom(np.arange(5, dtype=float), np.ones(5), 0)


# --------------------------------------------------------------------------
# Wpięcie w ramki
# --------------------------------------------------------------------------

def test_attach_mom_adds_one_column_per_lookback():
    out = attach_mom(bars(range(100)), (2, 5))
    assert "mom_2" in out.columns and "mom_5" in out.columns
    assert out.height == 100


def test_attach_mom_requires_atr():
    with pytest.raises(ValueError, match="atr_h1_14"):
        attach_mom(pl.DataFrame({"ts": [], "bid_close": []}), (5,))


def test_attach_mom_on_empty_frame_keeps_schema():
    empty = pl.DataFrame(schema={"ts": pl.Datetime("ms", "UTC"),
                                 "bid_close": pl.Float64, "atr_h1_14": pl.Float64})
    out = attach_mom(empty, (24,))
    assert "mom_24" in out.columns and out.is_empty()


def test_decisions_get_the_feature_of_their_own_closed_bar():
    """Decyzja dostaje cechę bara, który siatka wskazała — nie sąsiada.

    To jest test na off-by-one: gdyby złączenie było przesunięte o jeden bar,
    decyzja dostałaby cechę bara jeszcze niezamkniętego, czyli podglądałaby
    przyszłość o godzinę.
    """
    # Ścieżka MUSI dawać różne mom_2 na sąsiednich barach — na liniowej
    # rampie cecha jest stała i przesunięcie o bar byłoby niewykrywalne
    # z konstrukcji, czyli test przechodziłby nic nie sprawdzając.
    h1 = bars([100.0, 110, 120, 135, 200])
    per_bar = mom(h1["bid_close"].to_numpy(), h1["atr_h1_14"].to_numpy(), 2)
    assert per_bar[2] != pytest.approx(per_bar[3])

    dec = pl.DataFrame({
        "bar_ts": [h1["ts"][2], h1["ts"][3]],
        "ts_decision": [h1["ts"][3], h1["ts"][4]],
    })
    out = attach_to_decisions(dec, h1, (2,))
    assert out["mom_2"][0] == pytest.approx((120 - 100) / np.sqrt(2))
    assert out["mom_2"][1] == pytest.approx((135 - 110) / np.sqrt(2))
    # Przesunięcie o jeden bar do przodu dałoby cechę bara NIEZAMKNIĘTEGO.
    assert out["mom_2"][0] != pytest.approx(per_bar[3])
    assert out["mom_2"][1] != pytest.approx(per_bar[4])


def test_feature_uses_bid_never_a_midpoint():
    """Zakaz ceny mid jest twardy (base.yaml `forbidden.mid_price`)."""
    h1 = bars([100.0, 110]).with_columns(pl.Series("ask_close", [100.5, 110.5]))
    out = attach_mom(h1, (1,))
    assert out["mom_1"][1] == pytest.approx(10.0)   # z bid, nie z (bid+ask)/2


def test_real_atr_series_does_not_break_the_feature():
    """Złożenie z prawdziwym ATR Wildera — rozgrzewka daje NaN, nie wyjątek."""
    n = 60
    ts = [dt.datetime(2020, 1, 1, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(n)]
    px = np.linspace(100, 110, n)
    h1 = pl.DataFrame({"ts": ts, "bid_high": px + 0.5, "bid_low": px - 0.5,
                       "bid_close": px})
    out = attach_mom(atr_h1(h1, 14), (24,))
    assert out["mom_24"].is_nan().sum() >= 24
    assert out["mom_24"].drop_nans().drop_nulls().len() > 0
