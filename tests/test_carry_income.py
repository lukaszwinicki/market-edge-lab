"""Przychód carry w warstwie B (ADR-026) — na transakcjach wpisanych ręcznie."""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from src.execution.costs import attach_carry, attach_swap, carry_net_column, net_column

UTC = dt.timezone.utc


def _trades(side="long", diff=2.0, entry=dt.datetime(2019, 3, 4, 10, tzinfo=UTC),
            exit_=dt.datetime(2019, 3, 7, 10, tzinfo=UTC)):
    t = pl.DataFrame({"ts_decision": [entry], "exit_ts": [exit_], "ref_price": [1.0],
                      "risk": [0.01], "r": [0.0], "side": [side], "carry": [diff]})
    return attach_swap(t, (0.01,))


def test_long_high_yielder_earns_the_differential():
    """Pon → czw: trzy granice doby, środa potrójna → 5 dni finansowania.
    2% · 5/365 na cenie 1,0 przy ryzyku 0,01 = 0,0274 R."""
    out = attach_carry(_trades(), (0.01,), diff_col="carry")
    assert out["carry_r"][0] == pytest.approx(0.02 * 5 / 365 / 0.01)


def test_short_pays_the_same_differential():
    out = attach_carry(_trades(side="short"), (0.01,), diff_col="carry")
    assert out["carry_r"][0] == pytest.approx(-0.02 * 5 / 365 / 0.01)


def test_carry_net_adds_income_on_top_of_the_full_cost():
    out = attach_carry(_trades(), (0.01,), diff_col="carry")
    assert out[carry_net_column(0.01)][0] == pytest.approx(
        out[net_column(0.01)][0] + out["carry_r"][0])


def test_same_day_round_trip_earns_nothing():
    out = attach_carry(_trades(exit_=dt.datetime(2019, 3, 4, 20, tzinfo=UTC)),
                       (0.01,), diff_col="carry")
    assert out["carry_r"][0] == 0.0


def test_carry_refuses_to_run_before_the_swap_margin():
    t = _trades().drop(net_column(0.01))
    with pytest.raises(ValueError):
        attach_carry(t, (0.01,), diff_col="carry")
