"""Testy złożenia pełnego modelu kosztu (ADR-016).

Dwie rzeczy do pilnowania:

1. **Dokładność.** Doliczenie swapu po fakcie musi dawać dokładnie to samo,
   co dałoby doliczenie w środku symulatora. Sprawdzane przeciw wartościom
   zapisanym przez M03, które powstały inną ścieżką kodu.
2. **Niemożność pominięcia.** Pominięcie członu finansowania ma być błędem,
   nie przeoczeniem — M03 wykrył brak swapu w module, który miał testy
   i wyglądał na kompletny.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.execution.costs import (
    attach_swap, margins_from_config, net_column, reportable, swap_column,
)
from src.execution.swap import swap_margin_r

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[1]
M03 = ROOT / "runs" / "20260923T175353Z-087adf"


def _trades(n=5, days=3):
    ts = [dt.datetime(2020, 3, 2, 9, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(n)]
    return pl.DataFrame({
        "ts_decision": ts,
        "exit_ts": [t + dt.timedelta(days=days) for t in ts],
        "ref_price": [1.1] * n,
        "risk": [0.01] * n,
        "r": np.linspace(-1.0, 1.0, n),
    })


# --------------------------------------------------------------------------
# Dokładność
# --------------------------------------------------------------------------

def test_attach_swap_matches_the_underlying_formula():
    t = _trades()
    out = attach_swap(t, (0.01,))
    want = [swap_margin_r(1.1, 0.01, a, b, 0.01)
            for a, b in zip(t["ts_decision"], t["exit_ts"])]
    assert out[swap_column(0.01)].to_list() == pytest.approx(want)


def test_net_is_r_minus_swap_and_r_is_left_alone():
    t = _trades()
    out = attach_swap(t, (0.01,))
    assert out["r"].to_list() == pytest.approx(t["r"].to_list())
    assert out[net_column(0.01)].to_list() == pytest.approx(
        (t["r"].to_numpy() - out[swap_column(0.01)].to_numpy()).tolist())


def test_swap_scales_linearly_with_margin():
    out = attach_swap(_trades(), (0.005, 0.01, 0.02))
    a = out[swap_column(0.005)].to_numpy()
    assert out[swap_column(0.01)].to_numpy() == pytest.approx(2 * a)
    assert out[swap_column(0.02)].to_numpy() == pytest.approx(4 * a)


def test_swap_is_a_cost_on_both_sides():
    """Marża jest kosztem, nie kierunkowym punktem swapowym — zawsze dodatnia."""
    out = attach_swap(_trades(), (0.01,))
    assert (out[swap_column(0.01)].to_numpy() > 0).all()


def test_same_day_round_trip_pays_nothing():
    t = _trades(n=2, days=0)
    out = attach_swap(t, (0.02,))
    assert out[swap_column(0.02)].to_list() == pytest.approx([0.0, 0.0])


@pytest.mark.skipif(not M03.exists(), reason="artefakty M03 nieobecne")
@pytest.mark.parametrize("h", [3, 10])
def test_composition_reproduces_m03_stored_values(h):
    """Najmocniejszy test: inna ścieżka kodu, ta sama liczba.

    M03 policzył swap własną pętlą i zapisał go per transakcja. Ten moduł
    liczy go z `TradeResult`. Jeżeli doliczanie po fakcie jest dokładne,
    obie kolumny muszą się zgadzać co do bitu.
    """
    stored = pl.read_parquet(M03 / f"m03_trades_h{h}.parquet").head(3000)
    recomputed = attach_swap(
        stored.drop([c for c in stored.columns if c.startswith("swap_r_")]),
        (0.005, 0.01, 0.02),
        entry_col="ts",
    )
    for m in (0.005, 0.01, 0.02):
        assert recomputed[swap_column(m)].to_numpy() == pytest.approx(
            stored[f"swap_r_{m}"].to_numpy(), abs=1e-12)


# --------------------------------------------------------------------------
# Niemożność pominięcia
# --------------------------------------------------------------------------

def test_empty_margin_axis_is_refused():
    with pytest.raises(ValueError, match="oś marży"):
        attach_swap(_trades(), ())


def test_missing_columns_are_named_not_guessed():
    with pytest.raises(ValueError, match="risk"):
        attach_swap(_trades().drop("risk"), (0.01,))


def test_reportable_refuses_a_frame_without_full_cost():
    t = _trades()
    with pytest.raises(ValueError, match="ADR-016"):
        reportable(t, (0.01,))
    reportable(attach_swap(t, (0.01,)), (0.01,))   # nie rzuca


def test_reportable_catches_a_partially_covered_axis():
    """Dwie marże z trzech to nadal brak — oś jest osią, nie sugestią."""
    t = attach_swap(_trades(), (0.005, 0.01))
    with pytest.raises(ValueError, match="0.02"):
        reportable(t, (0.005, 0.01, 0.02))


def test_margins_come_from_config_and_absence_is_an_error():
    cfg = {"costs": {"swap": {"margin_sensitivity": [0.005, 0.01, 0.02]}}}
    assert margins_from_config(cfg) == (0.005, 0.01, 0.02)
    with pytest.raises(ValueError, match="margin_sensitivity"):
        margins_from_config({"costs": {"swap": {}}})
    with pytest.raises(ValueError, match="pusta"):
        margins_from_config({"costs": {"swap": {"margin_sensitivity": []}}})


def test_project_config_axis_is_the_one_the_prereg_declares():
    import yaml
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    assert margins_from_config(cfg) == (0.005, 0.01, 0.02)


def test_empty_frame_keeps_the_schema():
    empty = _trades(n=0)
    out = attach_swap(empty, (0.01,))
    assert net_column(0.01) in out.columns and out.is_empty()
