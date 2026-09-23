"""Odegranie wejść i złożenie siatka → symulator.

Testy jednostkowe pilnują wyrównania znaczników w punktach, w których jest
ono JAWNE: `test_grid.py` dla siatki, `test_simulator.py` dla okna
transakcji. Tutaj sprawdzamy **złożenie** — bo błąd potrafi powstać na styku
modułów, z których każdy z osobna jest poprawny.

Test `test_edge_is_recovered_only_when_it_lies_inside_the_trade_window`
jest odpowiednikiem M04 w miniaturze: zasiewamy ruch ceny o znanej porze
i żądamy, żeby przyrząd zarobił na nim WTEDY I TYLKO WTEDY, gdy ruch leży
wewnątrz okna transakcji.

Dane syntetyczne: na wymyślonym szeregu wiemy, gdzie jest zysk.
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from src.data.resample import BAR_SCHEMA
from src.execution.simulator import CostModel, ExitReason, Side, simulate_trade
from src.research.entries import barriers, both_directions, simulate_entries

UTC = dt.timezone.utc
PIP = 1e-4
T0 = dt.datetime(2020, 1, 6, 0, tzinfo=UTC)          # poniedziałek
NO_FLOOR = CostModel(pip=PIP, min_roundturn_pips=0.0,
                     entry_slippage_x_spread=0.0, stop_slippage_x_spread=0.0)


def m1_series(closes: list[float], *, start=T0, spread=2 * PIP) -> pl.DataFrame:
    """Bary M1 o zerowym zakresie — cena to pojedyncza liczba na minutę."""
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "ts": start + dt.timedelta(minutes=i),
            "bid_open": c, "bid_high": c, "bid_low": c, "bid_close": c,
            "ask_open": c + spread, "ask_high": c + spread,
            "ask_low": c + spread, "ask_close": c + spread,
            "spread_max": spread, "spread_close": spread, "n_ticks": 10,
        })
    return pl.DataFrame(rows, schema=BAR_SCHEMA)


def entry_frame(ts_list, t1_list, ref=1.1000, atr=0.0020, side="long"):
    """Cena odniesienia to cena Z MOMENTU DECYZJI — jak w siatce, gdzie
    `ref_price` jest zamknięciem ostatniego zamkniętego bara. Podanie tu
    stałej dla wszystkich wejść ustawiłoby bariery wokół nieaktualnej ceny."""
    refs = ref if isinstance(ref, list) else [ref] * len(ts_list)
    return pl.DataFrame(
        {
            "ts_decision": ts_list, "t1": t1_list,
            "ref_price": refs,
            "atr_d1_14": [atr] * len(ts_list),
            "side": [side] * len(ts_list),
        },
        schema={"ts_decision": pl.Datetime("ms", "UTC"),
                "t1": pl.Datetime("ms", "UTC"), "ref_price": pl.Float64,
                "atr_d1_14": pl.Float64, "side": pl.String},
    )


# --- geometria barier ------------------------------------------------------

def test_barriers_are_symmetric_around_the_reference_price():
    sl_l, tp_l = barriers(1.1000, 0.0020, Side.LONG, sl_mult=1.1, tp_mult=2.2)
    sl_s, tp_s = barriers(1.1000, 0.0020, Side.SHORT, sl_mult=1.1, tp_mult=2.2)
    assert sl_l == pytest.approx(1.1000 - 1.1 * 0.0020)
    assert tp_l == pytest.approx(1.1000 + 2.2 * 0.0020)
    assert sl_s == pytest.approx(1.1000 + 1.1 * 0.0020)
    assert tp_s == pytest.approx(1.1000 - 2.2 * 0.0020)


def test_stop_distance_exceeds_the_nominal_multiple_because_entry_is_worse():
    """`risk` liczy się od ceny WEJŚCIA, nie od ceny odniesienia.

    Long wchodzi po ask, czyli powyżej ceny odniesienia, więc do stopu ma
    dalej niż nominalne `sl_mult × atr`. Gdyby było odwrotnie, R byłoby
    zaniżone, a każdy wynik w R — zawyżony.
    """
    m1 = m1_series([1.1000] * 120)
    e = entry_frame([T0], [T0 + dt.timedelta(minutes=100)])
    out = simulate_entries(e, m1, CostModel(pip=PIP), sl_mult=1.1, tp_mult=2.2)
    assert out["risk"][0] > 1.1 * 0.0020


# --- zgodność z bezpośrednim wywołaniem symulatora -------------------------

@pytest.mark.parametrize("side", ["long", "short"])
def test_simulate_entries_matches_a_direct_simulate_trade_call(side):
    """Moduł nie może robić nic ponad to, co zrobiłaby ręczna pętla.

    M03 wołał `simulate_trade` wprost; M04 woła przez ten moduł. Jeżeli
    wyniki się rozjeżdżają, obu przebiegów nie da się porównać.
    """
    closes = [1.1000 + i * 0.5 * PIP for i in range(200)]
    m1 = m1_series(closes)
    t1 = T0 + dt.timedelta(minutes=150)
    e = entry_frame([T0], [t1], side=side)
    got = simulate_entries(e, m1, NO_FLOOR, sl_mult=1.1, tp_mult=2.2)

    s = Side.LONG if side == "long" else Side.SHORT
    sl, tp = barriers(1.1000, 0.0020, s, sl_mult=1.1, tp_mult=2.2)
    want = simulate_trade(s, T0, sl, tp, t1, m1, NO_FLOOR)

    assert got["r"][0] == pytest.approx(want.r)
    assert got["reason"][0] == want.reason.value
    assert got["exit_ts"][0] == want.exit.time


def test_input_columns_are_carried_through():
    m1 = m1_series([1.1000] * 120)
    e = entry_frame([T0], [T0 + dt.timedelta(minutes=100)]).with_columns(
        pl.lit("EURUSD").alias("symbol"), pl.lit(7).alias("rep"))
    out = simulate_entries(e, m1, NO_FLOOR, sl_mult=1.1, tp_mult=2.2)
    assert out["symbol"][0] == "EURUSD" and out["rep"][0] == 7


def test_rows_without_data_at_the_decision_are_dropped_not_zeroed():
    """Brak danych to NO TRADE, nie transakcja z wynikiem zero."""
    m1 = m1_series([1.1000] * 60)
    far = T0 + dt.timedelta(days=5)
    e = entry_frame([T0, far], [T0 + dt.timedelta(minutes=50),
                                far + dt.timedelta(minutes=50)])
    out = simulate_entries(e, m1, NO_FLOOR, sl_mult=1.1, tp_mult=2.2)
    assert out.height == 1
    assert out["ts_decision"][0] == T0


def test_both_directions_duplicates_every_row():
    e = entry_frame([T0, T0 + dt.timedelta(hours=1)],
                    [T0 + dt.timedelta(days=1), T0 + dt.timedelta(days=1)])
    both = both_directions(e.drop("side"))
    assert both.height == 2 * e.height
    assert set(both["side"].to_list()) == {"long", "short"}


# --- złożenie: M04 w miniaturze --------------------------------------------

def test_edge_is_recovered_only_when_it_lies_inside_the_trade_window():
    """Zasiany ruch ceny musi dać zysk WTEDY I TYLKO WTEDY, gdy jest w oknie.

    Cena stoi, po czym o 12:00 skacze w górę o 3 × atr — dość, żeby trafić
    TP przy `tp_mult = 2,2`. Long otwarty przed skokiem ma go w oknie
    i zarabia. Long otwarty PO skoku widzi już tylko płaską cenę i kończy
    na barierze czasowej, czyli na samym koszcie.

    Gdyby przyrząd przesuwał okno o jeden bar w złą stronę, ten test
    wyszedłby odwrotnie — i to jest jedyny sposób, w jaki błąd wyrównania
    na styku modułów daje się złapać bez prawdziwych danych.
    """
    jump_at = 12 * 60                       # 12:00, minuta 720
    closes = [1.1000] * jump_at + [1.1000 + 3 * 0.0020] * 400
    m1 = m1_series(closes)

    before = T0 + dt.timedelta(minutes=jump_at - 60)
    after = T0 + dt.timedelta(minutes=jump_at + 60)
    e = entry_frame([before, after],
                    [before + dt.timedelta(minutes=300),
                     after + dt.timedelta(minutes=300)],
                    ref=[1.1000, 1.1000 + 3 * 0.0020])
    out = simulate_entries(e, m1, NO_FLOOR, sl_mult=1.1, tp_mult=2.2)

    got = {row["ts_decision"]: row for row in out.iter_rows(named=True)}
    assert got[before]["reason"] in (ExitReason.TAKE_PROFIT.value,
                                     ExitReason.GAP_TARGET.value)
    assert got[before]["r"] > 1.5
    assert got[after]["reason"] == ExitReason.TIME_BARRIER.value
    assert got[after]["r"] < 0


def test_a_short_loses_exactly_where_the_long_wins():
    """Ta sama próba, przeciwny kierunek — dowód, że wynik niesie kierunek,
    a nie jakieś stałe obciążenie przyrządu."""
    jump_at = 12 * 60
    closes = [1.1000] * jump_at + [1.1000 + 3 * 0.0020] * 400
    m1 = m1_series(closes)
    before = T0 + dt.timedelta(minutes=jump_at - 60)
    e = both_directions(
        entry_frame([before], [before + dt.timedelta(minutes=300)]).drop("side"))
    out = simulate_entries(e, m1, NO_FLOOR, sl_mult=1.1, tp_mult=2.2)
    by_side = {r["side"]: r for r in out.iter_rows(named=True)}
    assert by_side["long"]["r"] > 1.5
    assert by_side["short"]["r"] < -0.9
