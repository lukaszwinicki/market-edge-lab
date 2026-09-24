"""Testy block bootstrapu po dniach.

Oracle: dla danych o znanej strukturze zależności wiadomo, jaki błąd
standardowy jest poprawny. Bootstrap po transakcjach zaniżałby go przy
korelacji wewnątrz dnia i między dniami — to właśnie ma wychodzić.
"""
import datetime as dt

import numpy as np
import polars as pl
import pytest

from src.data.timeaxis import add_business_days
from src.validation.bootstrap import block_bootstrap_expectancy, daily_totals

UTC = dt.timezone.utc
D0 = dt.datetime(2019, 1, 7, 10, tzinfo=UTC)     # poniedziałek


def trades(r_per_day: list[list[float]]) -> pl.DataFrame:
    ts, r = [], []
    for i, day in enumerate(r_per_day):
        t = add_business_days(D0, i)
        for j, v in enumerate(day):
            ts.append(t + dt.timedelta(minutes=j))
            r.append(v)
    return pl.DataFrame({"ts": pl.Series(ts, dtype=pl.Datetime("ms", "UTC")), "r": r})


# --- Oś dni -----------------------------------------------------------------

def test_empty_business_days_stay_on_the_axis():
    s, n = daily_totals(trades([[1.0], [], [], [2.0, 3.0]]))
    assert n.tolist() == [1, 0, 0, 2]
    assert s.tolist() == [1.0, 0.0, 0.0, 5.0]


def test_weekend_entries_belong_to_monday_session():
    sunday_evening = dt.datetime(2019, 1, 13, 22, tzinfo=UTC)
    df = pl.DataFrame({
        "ts": pl.Series([D0, sunday_evening, sunday_evening + dt.timedelta(hours=12)],
                        dtype=pl.Datetime("ms", "UTC")),
        "r": [1.0, 2.0, 3.0],
    })
    s, n = daily_totals(df)
    assert len(s) == 6                  # pon 7.01 ... pon 14.01, bez sob/nd
    assert n[-1] == 2 and s[-1] == 5.0


# --- Błąd standardowy -------------------------------------------------------

def test_independent_days_give_classical_standard_error():
    rng = np.random.default_rng(0)
    r = rng.standard_normal(1000)
    res = block_bootstrap_expectancy(trades([[v] for v in r]), n_reps=4000, seed=1)
    assert res.expectancy == pytest.approx(r.mean())
    assert res.se == pytest.approx(r.std(ddof=1) / np.sqrt(len(r)), rel=0.12)


def test_same_day_correlation_is_not_counted_as_independent_trades():
    """6 par, wspólny czynnik dnia: efektywnie 1 obserwacja na dzień, nie 6."""
    rng = np.random.default_rng(2)
    days = [list(rng.standard_normal() + 0.1 * rng.standard_normal(6)) for _ in range(600)]
    df = trades(days)
    res = block_bootstrap_expectancy(df, n_reps=4000, seed=3)
    naive = df["r"].std() / np.sqrt(df.height)
    assert res.se > 2 * naive
    assert res.se == pytest.approx(1 / np.sqrt(600), rel=0.15)


def test_blocks_capture_cross_day_dependence():
    """Wynik dnia zależny od 10 poprzednich (nakładające się okna etykiet).
    Bloki 20-dniowe muszą dać większe se niż bloki 1-dniowe."""
    rng = np.random.default_rng(4)
    shocks = rng.standard_normal(1010)
    r = np.convolve(shocks, np.ones(10), mode="valid")[:1000] / np.sqrt(10)
    df = trades([[v] for v in r])
    se20 = block_bootstrap_expectancy(df, block_days=20, n_reps=3000, seed=5).se
    se1 = block_bootstrap_expectancy(df, block_days=1, n_reps=3000, seed=5).se
    assert se20 > 2 * se1


# --- Istotność --------------------------------------------------------------

def test_real_edge_is_significant_and_null_is_not():
    rng = np.random.default_rng(6)
    edge = block_bootstrap_expectancy(
        trades([[v] for v in rng.standard_normal(1500) + 0.3]), n_reps=2000)
    null = block_bootstrap_expectancy(
        trades([[v] for v in rng.standard_normal(1500)]), n_reps=2000)
    assert edge.t_stat > 5 and edge.ci_low > 0
    assert abs(null.t_stat) < 3 and null.ci_low < 0 < null.ci_high


def test_reproducible_with_seed():
    df = trades([[v] for v in np.random.default_rng(7).standard_normal(200)])
    a = block_bootstrap_expectancy(df, n_reps=500, seed=11)
    b = block_bootstrap_expectancy(df, n_reps=500, seed=11)
    assert a == b


def test_too_short_sample_is_rejected():
    with pytest.raises(ValueError):
        block_bootstrap_expectancy(trades([[1.0], [2.0]] * 10), block_days=20)


# --------------------------------------------------------------------------
# Bootstrap dowolnej statystyki (dla Spearmana warstwy A, T003)
# --------------------------------------------------------------------------

from src.validation.bootstrap import (  # noqa: E402
    block_bootstrap_statistic, day_row_groups,
)


def _hourly(n_days: int, per_day: int) -> pl.Series:
    out = []
    d = D0
    while len(out) < n_days * per_day:
        if d.weekday() < 5:
            out += [d + dt.timedelta(hours=h) for h in range(per_day)]
        d += dt.timedelta(days=1)
    return pl.Series(out[:n_days * per_day])


def _rank(a):
    o = a.argsort()
    r = np.empty_like(o, dtype=float)
    r[o] = np.arange(a.size)
    return r


def _spearman_of(x, y):
    def stat(idx):
        a, b = _rank(x[idx]), _rank(y[idx])
        a, b = a - a.mean(), b - b.mean()
        den = np.sqrt((a * a).sum() * (b * b).sum())
        return float((a * b).sum() / den) if den > 0 else np.nan
    return stat


def test_day_row_groups_partitions_every_row_exactly_once():
    ts = _hourly(50, 8)
    days, order, starts = day_row_groups(ts)
    assert starts[0] == 0 and starts[-1] == ts.len()
    assert sorted(order.tolist()) == list(range(ts.len()))
    assert len(days) == 50


def test_day_row_groups_keeps_each_day_contiguous():
    ts = _hourly(30, 4)
    days, order, starts = day_row_groups(ts)
    for j in range(len(days)):
        rows = order[starts[j]:starts[j + 1]]
        assert len(rows) == 4


def test_statistic_bootstrap_point_estimate_is_the_full_sample():
    rng = np.random.default_rng(1)
    ts = _hourly(120, 6)
    x, y = rng.standard_normal(ts.len()), rng.standard_normal(ts.len())
    stat = _spearman_of(x, y)
    res = block_bootstrap_statistic(ts, stat, n_reps=200, seed=0)
    assert res.expectancy == pytest.approx(stat(np.arange(ts.len())))


def test_independent_rows_give_se_near_one_over_sqrt_n():
    """Kalibracja: bez zależności wewnątrz dnia SE ma siadać koło 1/sqrt(n)."""
    rng = np.random.default_rng(2)
    ts = _hourly(300, 6)
    n = ts.len()
    x, y = rng.standard_normal(n), rng.standard_normal(n)
    res = block_bootstrap_statistic(ts, _spearman_of(x, y), n_reps=400, seed=0)
    assert res.se * np.sqrt(n) == pytest.approx(1.0, abs=0.35)


def test_within_day_dependence_widens_the_interval():
    """Wiersze powielone w obrębie dnia nie dokładają informacji.

    Ta sama para (x, y) powtórzona 6 razy dziennie daje 6x więcej wierszy
    i tę samą treść. Bootstrap po dniach MUSI to zobaczyć: SE nie ma prawa
    spaść jak 1/sqrt(6).
    """
    rng = np.random.default_rng(3)
    n_days, per_day = 300, 6
    ts = _hourly(n_days, per_day)
    base_x, base_y = rng.standard_normal(n_days), rng.standard_normal(n_days)
    x = np.repeat(base_x, per_day)
    y = np.repeat(base_y, per_day)
    res = block_bootstrap_statistic(ts, _spearman_of(x, y), n_reps=400, seed=0)
    naive = 1 / np.sqrt(n_days * per_day)
    assert res.se > 2.0 * naive


def test_statistic_bootstrap_rejects_too_few_days():
    ts = _hourly(10, 4)
    x = np.arange(ts.len(), dtype=float)
    with pytest.raises(ValueError, match="za mało"):
        block_bootstrap_statistic(ts, _spearman_of(x, x), block_days=20, n_reps=10)


def test_statistic_bootstrap_is_deterministic_given_the_seed():
    rng = np.random.default_rng(4)
    ts = _hourly(120, 4)
    x, y = rng.standard_normal(ts.len()), rng.standard_normal(ts.len())
    a = block_bootstrap_statistic(ts, _spearman_of(x, y), n_reps=100, seed=7)
    b = block_bootstrap_statistic(ts, _spearman_of(x, y), n_reps=100, seed=7)
    assert (a.se, a.ci_low, a.ci_high) == (b.se, b.ci_low, b.ci_high)
