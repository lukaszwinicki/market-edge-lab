"""Testy warstwy etykiet i reżimu zmienności — na danych syntetycznych.

Warstwa etykiet ma jeden warunek, którego nie widać w wyniku: **nie zna
hipotezy**. Wynik bez tej własności wygląda identycznie, więc jest tu
sprawdzana wprost, importem, a nie przez oglądanie liczb.

Reszta to granice: percentyl w oknie rozszerzającym nie może zaglądać
w przód, a obserwacja bez cechy albo bez targetu nie może wejść do próby
z podstawioną wartością.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.features.volatility import (
    VOL_REGIME_EDGES, attach_vol_pct, expanding_percentile, vol_pct, vol_regime,
)
from src.research.labels import (
    check_required, coverage, layer_a, long_short, with_axes,
)

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# Warunek ADR: moduł nie zna hipotezy
# --------------------------------------------------------------------------

def test_labels_module_does_not_import_the_hypothesis_feature():
    """Warunek startu T003: „warstwa etykiet bez treści hipotezy w module".

    Sprawdzane w źródle, bo żadna wartość zwracana tego nie pokaże.
    """
    src = (ROOT / "src" / "research" / "labels.py").read_text(encoding="utf-8")
    assert "momentum" not in src.replace("features/momentum.py", "")
    assert "mom_" not in src


def test_labels_module_takes_the_feature_column_by_name():
    """Nazwa cechy jest parametrem — inaczej moduł zna hipotezę przez nazwę."""
    dec = _decisions(feature=[1.0, -1.0], fwd=[0.5, -0.5])
    out = layer_a(dec.rename({"feat": "cokolwiek"}), "cokolwiek")
    assert out.height == 2


# --------------------------------------------------------------------------
# Percentyl w oknie rozszerzającym
# --------------------------------------------------------------------------

def test_expanding_percentile_never_looks_forward():
    """Wartość w pozycji i nie może zależeć od niczego po i.

    Test przez zmianę ogona: dopisanie ekstremum na końcu nie ma prawa
    ruszyć ani jednej wcześniejszej pozycji.
    """
    rng = np.random.default_rng(5)
    x = rng.random(500)
    a = expanding_percentile(x, 100)
    b = expanding_percentile(np.concatenate([x, [999.0]]), 100)
    assert np.allclose(a, b[:-1], equal_nan=True)


def test_expanding_percentile_needs_min_obs():
    x = np.arange(10, dtype=float)
    got = expanding_percentile(x, 5)
    assert np.isnan(got[:4]).all()
    assert not np.isnan(got[4:]).any()


def test_expanding_percentile_bounds():
    rng = np.random.default_rng(6)
    got = expanding_percentile(rng.random(1000), 252)
    ok = got[~np.isnan(got)]
    assert (ok > 0).all() and (ok <= 1.0).all()


def test_monotone_series_sits_at_the_extremes():
    assert expanding_percentile(np.arange(300, dtype=float), 252)[-1] == pytest.approx(1.0)
    falling = expanding_percentile(np.arange(300, 0, -1, dtype=float), 252)
    assert falling[-1] < 0.01


def test_vol_pct_inherits_available_from_and_never_leaks_same_day():
    """Percentyl dnia d jest znany od d+1, tak samo jak `atr_d1_14`.

    Decyzja z dnia d nie może dostać percentyla dnia d — użyłaby ATR doby,
    która zamyka się po niej.
    """
    days = [dt.datetime(2020, 1, 1, tzinfo=UTC) + dt.timedelta(days=i) for i in range(400)]
    # ATR MUSI być niemonotoniczny: na serii rosnącej percentyl wynosi 1,0
    # każdego dnia, więc przeciek o dobę nie zmieniłby ani jednej liczby
    # i test przechodziłby nic nie sprawdzając.
    rng = np.random.default_rng(17)
    d1 = pl.DataFrame({
        "day": days,
        "atr_d1_14": rng.random(400) + 0.5,
    }).with_columns((pl.col("day") + pl.duration(days=1)).alias("available_from"))
    withpct = vol_pct(d1, min_days=252)
    assert withpct["vol_pct_252"][299] != pytest.approx(withpct["vol_pct_252"][300])

    dec = pl.DataFrame({"ts": [days[300] + dt.timedelta(hours=9)]})
    out = attach_vol_pct(dec, withpct, on="ts")
    # dostaje percentyl doby 299, nie 300
    assert out["vol_pct_252"][0] == pytest.approx(withpct["vol_pct_252"][299])
    assert out["vol_pct_252"][0] != pytest.approx(withpct["vol_pct_252"][300])


# --------------------------------------------------------------------------
# Kubełki reżimu
# --------------------------------------------------------------------------

def test_vol_regime_buckets_at_declared_edges():
    lo, hi = VOL_REGIME_EDGES
    df = pl.DataFrame({"vol_pct_252": [0.0, lo - 1e-9, lo, hi - 1e-9, hi, 1.0]})
    got = df.with_columns(vol_regime().alias("r"))["r"].to_list()
    assert got == ["low", "low", "mid", "mid", "high", "high"]


def test_vol_regime_marks_unknown_instead_of_guessing():
    df = pl.DataFrame({"vol_pct_252": [None, float("nan")]}, strict=False)
    assert df.with_columns(vol_regime().alias("r"))["r"].to_list() == ["UNKNOWN"] * 2


# --------------------------------------------------------------------------
# Warstwa A
# --------------------------------------------------------------------------

def _decisions(feature, fwd):
    n = len(feature)
    ts = [dt.datetime(2020, 3, 2, 9, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(n)]
    return pl.DataFrame({
        "ts_decision": ts,
        "bar_ts": [t - dt.timedelta(hours=1) for t in ts],
        "t1": [t + dt.timedelta(days=3) for t in ts],
        "ref_price": [100.0] * n,
        "atr_d1_14": [1.0] * n,
        "feat": feature,
        "fwd_atr": fwd,
    }, strict=False)


def test_layer_a_drops_rows_missing_either_side():
    dec = _decisions(feature=[1.0, None, 3.0, float("nan")],
                     fwd=[0.5, 0.5, None, 0.5])
    out = layer_a(dec, "feat")
    assert out.height == 1
    assert out["feat"][0] == pytest.approx(1.0)


def test_layer_a_keeps_every_other_column():
    dec = _decisions(feature=[1.0], fwd=[0.5])
    out = layer_a(dec, "feat")
    assert set(dec.columns) <= set(out.columns)


def test_layer_a_rejects_a_missing_feature_column():
    with pytest.raises(ValueError, match="cechy"):
        layer_a(_decisions([1.0], [0.5]), "nie_ma_takiej")


def test_layer_a_rejects_a_frame_without_target():
    with pytest.raises(ValueError, match="targetu A"):
        layer_a(_decisions([1.0], [0.5]).drop("fwd_atr"), "feat")


def test_check_required_names_what_is_missing():
    with pytest.raises(ValueError, match="ref_price"):
        check_required(_decisions([1.0], [0.5]).drop("ref_price"))


# --------------------------------------------------------------------------
# Kierunek
# --------------------------------------------------------------------------

def test_long_short_has_no_threshold():
    df = pl.DataFrame({"f": [-5.0, -1e-12, 0.0, 1e-12, 5.0]})
    got = df.with_columns(long_short(pl.col("f")).alias("side"))["side"].to_list()
    assert got == ["short", "short", "long", "long", "long"]


# --------------------------------------------------------------------------
# Osie i pokrycie
# --------------------------------------------------------------------------

def test_with_axes_adds_every_reporting_axis():
    days = [dt.datetime(2020, 1, 1, tzinfo=UTC) + dt.timedelta(days=i) for i in range(400)]
    d1 = vol_pct(pl.DataFrame({
        "day": days, "atr_d1_14": np.linspace(1.0, 2.0, 400),
    }).with_columns((pl.col("day") + pl.duration(days=1)).alias("available_from")))

    dec = _decisions([1.0, -1.0], [0.5, -0.5]).with_columns(
        pl.Series("ts_decision", [days[300] + dt.timedelta(hours=9),
                                  days[301] + dt.timedelta(hours=14)]))
    out = with_axes(dec, d1, "EURUSD")
    for col in ("symbol", "year", "hour", "vol_regime", "vol_pct_252"):
        assert col in out.columns
    assert out["symbol"].to_list() == ["EURUSD"] * 2
    assert out["hour"].to_list() == [9, 14]


def test_coverage_counts_what_the_simulator_silently_dropped():
    before = _decisions([1.0] * 10, [0.5] * 10)
    after = before.head(7)
    got = coverage(before, after)
    assert got == {"n_in": 10, "n_out": 7, "dropped": 3, "dropped_share": 0.3}


def test_coverage_survives_an_empty_input():
    empty = _decisions([], [])
    assert coverage(empty, empty)["dropped_share"] is None
