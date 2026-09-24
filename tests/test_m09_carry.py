"""M09 — dane stóp, geometria carry i surogat. Dane syntetyczne.

Trzy granice pilnowane w źródle:

* M09A (geometria cechy) nie czyta żadnej ceny — wyjątek ADR-020;
* M09B (surogat) nie czyta żadnej stopy — cecha H04 nie jest w nim liczona;
* warstwa etykiet i skrypt trialu nie importują bieżącego vintage, który
  zawiera rewizje nieznane w dniu decyzji.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import sys
from pathlib import Path

import numpy as np
import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from m09b_carry_null import (  # noqa: E402
    RHO_BREAKEVEN, avg_rank, decision_numbers, month_index, pair_matrix,
    simulate_rates,
)
from src.data.rates import (  # noqa: E402
    MissingRatesError, ar1_fit, load_current_vintage, month_range,
    pair_carry, pair_legs, parse_fredgraph_csv,
)

UTC = dt.timezone.utc
M09A = ROOT / "scripts" / "m09_carry_geometry.py"
M09B = ROOT / "scripts" / "m09b_carry_null.py"


def code_only(path: Path) -> str:
    text = re.sub(r'"""(?:.|\n)*?"""', "", path.read_text(encoding="utf-8"))
    return "\n".join(l.split("#")[0] for l in text.split("\n"))


# --------------------------------------------------------------------------
# Granice
# --------------------------------------------------------------------------

@pytest.mark.parametrize("forbidden", [
    "research.grid", "research.labels", "research.entries", "execution.simulator",
    "harness.market", "load_h1", "with_horizon", "fwd_atr", "bid_", "ask_",
])
def test_m09a_never_touches_a_price(forbidden):
    assert forbidden not in code_only(M09A), f"M09A sięga po {forbidden} (ADR-020)"


@pytest.mark.parametrize("forbidden", [
    "data.rates", "fredgraph", "current_vintage", "IRSTCI", "IR3TIB",
    "pair_carry", "load_current_vintage",
])
def test_m09b_never_reads_a_rate(forbidden):
    """M09B zestawia cechę ze zwrotem — więc cecha musi być syntetyczna."""
    assert forbidden not in code_only(M09B), f"M09B sięga po {forbidden}"


@pytest.mark.parametrize("path", [M09A, M09B])
def test_m09_runs_are_controls(path):
    assert 'kind="control"' in code_only(path)
    assert 'kind="strategy"' not in code_only(path)


def test_m09a_declares_the_adr_020_exception():
    m = re.search(r'start_run\(\s*"([^"]+)"', M09A.read_text(encoding="utf-8"))
    assert m and "ADR-020" in m.group(1)


def test_m09b_declares_its_gate_before_the_run():
    src = M09B.read_text(encoding="utf-8")
    assert re.search(r"^BREAKEVEN_ACC\s*=\s*0\.5172", src, re.M)
    assert "criterion_set_before_run" in src


@pytest.mark.parametrize("rel", ["src/research/labels.py", "scripts/t003_momentum.py"])
def test_current_vintage_does_not_reach_any_test_path(rel):
    assert "rates" not in code_only(ROOT / rel)


# --------------------------------------------------------------------------
# `src/data/rates.py`
# --------------------------------------------------------------------------

def test_parse_keeps_missing_values_as_null_not_zero():
    txt = "observation_date,X\n2020-03-01,0.5\n2020-04-01,\n2020-05-01,.\n"
    df = parse_fredgraph_csv(txt, "X")
    assert df.get_column("value").to_list() == [0.5, None, None]
    assert df.get_column("month").to_list()[0] == dt.date(2020, 3, 1)


def test_parse_rejects_a_csv_for_another_series():
    with pytest.raises(MissingRatesError):
        parse_fredgraph_csv("observation_date,Y\n2020-03-01,0.5\n", "X")


def test_month_range_crosses_a_year_boundary():
    assert month_range(dt.date(2020, 11, 1), dt.date(2021, 2, 1)) == [
        dt.date(2020, 11, 1), dt.date(2020, 12, 1), dt.date(2021, 1, 1), dt.date(2021, 2, 1)]


def _write(root: Path, sid: str, rows: list[tuple[str, str]]):
    root.mkdir(parents=True, exist_ok=True)
    body = "observation_date," + sid + "\n" + "".join(f"{d},{v}\n" for d, v in rows)
    (root / f"{sid}.csv").write_text(body, encoding="utf-8")


def test_loader_refuses_a_hole_instead_of_interpolating(tmp_path):
    _write(tmp_path, "IRSTCI01USM156N", [("2020-03-01", "1"), ("2020-04-01", ""),
                                         ("2020-05-01", "1")])
    with pytest.raises(MissingRatesError):
        load_current_vintage("overnight", ["USD"], dt.date(2020, 3, 1),
                             dt.date(2020, 5, 1), root=tmp_path)


def test_loader_refuses_a_missing_month(tmp_path):
    _write(tmp_path, "IRSTCI01USM156N", [("2020-03-01", "1"), ("2020-05-01", "1")])
    with pytest.raises(MissingRatesError):
        load_current_vintage("overnight", ["USD"], dt.date(2020, 3, 1),
                             dt.date(2020, 5, 1), root=tmp_path)


def test_loader_refuses_a_missing_file(tmp_path):
    with pytest.raises(MissingRatesError):
        load_current_vintage("overnight", ["USD"], dt.date(2020, 3, 1),
                             dt.date(2020, 5, 1), root=tmp_path)


def test_loader_builds_one_column_per_currency(tmp_path):
    _write(tmp_path, "IRSTCI01USM156N", [("2020-03-01", "1.5"), ("2020-04-01", "1.0")])
    _write(tmp_path, "IRSTCI01JPM156N", [("2020-03-01", "-0.1"), ("2020-04-01", "-0.1")])
    df = load_current_vintage("overnight", ["USD", "JPY"], dt.date(2020, 3, 1),
                              dt.date(2020, 4, 1), root=tmp_path)
    assert df.columns == ["month", "USD", "JPY"]
    assert pair_carry(df, "USDJPY").tolist() == pytest.approx([1.6, 1.1])


def test_carry_sign_is_base_minus_quote():
    df = pl.DataFrame({"EUR": [-0.5], "USD": [2.0]})
    assert pair_carry(df, "EURUSD")[0] == pytest.approx(-2.5)


@pytest.mark.parametrize("bad", ["DAX", "SPX500", "EURUSDX", "EUR/US"])
def test_pair_legs_refuses_what_is_not_an_fx_pair(bad):
    with pytest.raises(ValueError):
        pair_legs(bad)


def test_ar1_fit_recovers_a_known_persistence():
    rng = np.random.default_rng(0)
    x = np.zeros(20_000)
    for t in range(1, x.size):
        x[t] = 0.9 * x[t - 1] + 0.1 * rng.standard_normal()
    phi, sig = ar1_fit(x)
    assert phi == pytest.approx(0.9, abs=0.01)
    assert sig == pytest.approx(0.1, rel=0.03)


# --------------------------------------------------------------------------
# M09B — czyste funkcje
# --------------------------------------------------------------------------

def test_avg_rank_gives_ties_the_same_rank():
    assert avg_rank(np.array([3.0, 1.0, 3.0, 2.0])).tolist() == [3.5, 1.0, 3.5, 2.0]


def test_pair_matrix_shares_legs_between_pairs():
    m = pair_matrix(["EURUSD", "USDJPY", "EURJPY"], ["USD", "EUR", "JPY"])
    # EURJPY = EURUSD + USDJPY w różnicach stóp
    assert np.allclose(m[0] + m[1], m[2])


def test_month_index_maps_the_first_decision_to_the_first_visible_month():
    ts = pl.Series([dt.datetime(2016, 1, 4, 9, tzinfo=UTC),
                    dt.datetime(2021, 12, 30, 20, tzinfo=UTC)])
    assert month_index(ts, dt.date(2015, 11, 1), 2).tolist() == [0, 71]


def _sim(phi, n=4000, seed=1):
    rng = np.random.default_rng(seed)
    return simulate_rates(rng, n, np.full(2, phi), np.full(2, 0.1), np.eye(2),
                          level_mean=1.0, level_sd=0.0, anchor=1.0)


def test_surrogate_with_unit_phi_is_a_random_walk():
    r = _sim(1.0)
    d = np.diff(r[:, 0])
    assert d.std() == pytest.approx(0.1, rel=0.05)
    assert abs(np.corrcoef(d[1:], d[:-1])[0, 1]) < 0.05


def test_surrogate_with_measured_phi_reverts_to_the_anchor():
    phi, _ = ar1_fit(_sim(0.8)[:, 0])
    assert phi == pytest.approx(0.8, abs=0.03)


def test_surrogate_innovations_carry_the_declared_correlation():
    rng = np.random.default_rng(2)
    chol = np.linalg.cholesky(np.array([[1.0, 0.7], [0.7, 1.0]]))
    r = simulate_rates(rng, 20_000, np.ones(2), np.ones(2), chol, 0.0, 0.0, 0.0)
    d = np.diff(r, axis=0)
    assert np.corrcoef(d.T)[0, 1] == pytest.approx(0.7, abs=0.02)


def test_decision_numbers_reproduce_m05():
    """M05, k = 480: n_eff 1 902 → MDE 52,05%, iloraz 0,83."""
    e = decision_numbers(1 / math.sqrt(1902))
    assert e["mde_acc_pct"] == pytest.approx(52.05, abs=0.01)
    assert e["falsified_gap_ratio"] == pytest.approx(0.83, abs=0.01)
    assert RHO_BREAKEVEN == pytest.approx(0.05401, abs=1e-5)


def test_calibration_hits_both_geometry_targets():
    """Kalibracja ma trafić w zmienność w czasie I rozrzut między parami —
    pierwszy przebieg M09B trafiał w żadne z nich i nikt tego nie sprawdzał."""
    from m09b_carry_null import calibrate
    rng = np.random.default_rng(3)
    ccy = ["USD", "EUR", "JPY"]
    pm = pair_matrix(["EURUSD", "USDJPY", "EURJPY"], ccy)
    mult, lsd, w, b = calibrate(rng, 72, np.full(3, 0.97), np.full(3, 0.05),
                                np.eye(3), 0.5, pm, 0.65, 0.81, n_sims=200, steps=8)
    assert w == pytest.approx(0.65, rel=0.1)
    assert b == pytest.approx(0.81, rel=0.1)
    # iloraz 0,81/0,65 leży powyżej tego, co daje sam dryf innowacji,
    # więc potrzebny jest dodatni rozrzut poziomów startowych
    assert lsd > 0 and mult > 0


# --------------------------------------------------------------------------
# Point-in-time (ALFRED)
# --------------------------------------------------------------------------

from src.data.rates import parse_alfred_csv, pit_last_value  # noqa: E402


def test_alfred_parse_requires_the_vintage_it_asked_for():
    txt = "observation_date,X_20160104\n2015-11-01,0.1\n2015-12-01,0.2\n"
    df = parse_alfred_csv(txt, "X", dt.date(2016, 1, 4))
    assert df.get_column("value").to_list() == [0.1, 0.2]
    with pytest.raises(MissingRatesError):
        parse_alfred_csv(txt, "X", dt.date(2016, 1, 11))


def _vintages():
    rows = [
        # vintage 2016-01-04: grudzień już jest
        (dt.date(2016, 1, 4), dt.date(2015, 11, 1), 0.10),
        (dt.date(2016, 1, 4), dt.date(2015, 12, 1), 0.20),
        # vintage 2016-02-08: grudzień zrewidowany, doszedł styczeń
        (dt.date(2016, 2, 8), dt.date(2015, 12, 1), 0.25),
        (dt.date(2016, 2, 8), dt.date(2016, 1, 1), 0.30),
    ]
    return pl.DataFrame(rows, schema=["vintage_date", "month", "value"], orient="row")


def test_pit_never_uses_a_vintage_published_on_the_decision_day():
    """Margines 1 dnia roboczego: vintage z poniedziałku widzi dopiero
    wtorek. W poniedziałek decyzja nie ma jeszcze niczego."""
    out = pit_last_value(_vintages(), [dt.date(2016, 1, 4), dt.date(2016, 1, 5)])
    assert out.get_column("value").to_list() == [None, 0.20]


def test_pit_uses_the_value_as_published_not_as_revised():
    out = pit_last_value(_vintages(), [dt.date(2016, 2, 5)])
    assert out.get_column("value").to_list() == [0.20]          # nie 0,25
    assert out.get_column("month").to_list() == [dt.date(2015, 12, 1)]


def test_pit_moves_to_the_new_month_only_after_its_vintage():
    out = pit_last_value(_vintages(), [dt.date(2016, 2, 8), dt.date(2016, 2, 9)])
    assert out.get_column("month").to_list() == [dt.date(2015, 12, 1), dt.date(2016, 1, 1)]


def test_pit_margin_skips_the_weekend():
    """Decyzja w poniedziałek 2016-02-15: dzień roboczy wcześniej to piątek
    2016-02-12, więc vintage z 2016-02-08 jest widoczny."""
    out = pit_last_value(_vintages(), [dt.date(2016, 2, 15)])
    assert out.get_column("value").to_list() == [0.30]
