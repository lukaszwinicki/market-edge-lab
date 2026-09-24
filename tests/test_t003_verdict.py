"""Testy logiki werdyktu T003 — reguł, które rozstrzygają los H01.

Te funkcje zamieniają liczby w status hipotezy. Błąd tutaj nie objawia się
jako wyjątek ani jako dziwna wartość — objawia się jako **zły wniosek
naukowy**, i to taki, który wygląda na policzony. Dlatego reguły są
sprawdzane na przypadkach skonstruowanych ręcznie, z prerejestracji.

Prerejestracja (`configs/t003_momentum.yaml`):

    SUPPORTED      CI > 0 w >=1 komórce po korekcie Holma
                   ORAZ kontrola permutacyjna pobita p < 0,05
    FALSIFIED      CI95 w całości wewnątrz +/- rho_breakeven we WSZYSTKICH
                   komórkach (intersection-union, bez korekty)
    NOT_SUPPORTED  każdy inny wynik, z obowiązkiem podania ograniczenia
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from t003_momentum import PREREG, PREREG_SHA256, holm, verdict  # noqa: E402

RHO_BE = float(np.sin((0.5172 - 0.5) * np.pi))    # 0,05401


def cell(low, high, p=0.001):
    return {"ci_low": low, "ci_high": high, "p_value": p}


# --------------------------------------------------------------------------
# Spójność z zamrożoną prerejestracją
# --------------------------------------------------------------------------

def test_hash_in_the_runner_matches_the_frozen_file():
    import hashlib
    assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA256


def test_breakeven_constant_matches_the_prereg():
    pre = yaml.safe_load(PREREG.read_text(encoding="utf-8"))
    assert pre["falsification"]["breakeven"]["rho_equivalent"] == pytest.approx(
        RHO_BE, abs=1e-5)


def test_prereg_declares_exactly_three_cells():
    pre = yaml.safe_load(PREREG.read_text(encoding="utf-8"))
    assert pre["grid"]["cells"] == 3
    assert len(pre["feature"]["lookbacks_k_bars"]) == 3
    assert pre["grid"]["horizons_business_days"] == [3]


# --------------------------------------------------------------------------
# Holm
# --------------------------------------------------------------------------

def test_holm_is_stricter_than_uncorrected_alpha():
    """p = 0,04 przechodzi bez korekty, nie przechodzi przy trzech testach."""
    assert holm({"a": 0.04, "b": 0.5, "c": 0.9})["a"] is False
    assert holm({"a": 0.01, "b": 0.5, "c": 0.9})["a"] is True


def test_holm_steps_down_and_stops_at_the_first_failure():
    got = holm({"a": 0.001, "b": 0.30, "c": 0.004})
    assert got["a"] is True      # 0,001 <= 0,05/3
    assert got["c"] is True      # 0,004 <= 0,05/2
    assert got["b"] is False     # 0,30 > 0,05


def test_holm_rejects_nothing_when_everything_is_null():
    assert not any(holm({"a": 0.4, "b": 0.6, "c": 0.9}).values())


# --------------------------------------------------------------------------
# FALSIFIED — intersection-union
# --------------------------------------------------------------------------

def test_falsified_needs_every_cell_inside_the_breakeven_band():
    tight = cell(-0.02, 0.02, p=0.7)
    assert verdict({"a": tight, "b": tight, "c": tight}, RHO_BE, False)["status"] == "FALSIFIED"


def test_one_wide_cell_blocks_falsified():
    """Intersection-union: jedna komórka poza pasmem wystarczy, żeby nie orzec."""
    tight, wide = cell(-0.02, 0.02, p=0.7), cell(-0.09, 0.09, p=0.7)
    got = verdict({"a": tight, "b": tight, "c": wide}, RHO_BE, False)
    assert got["status"] == "NOT_SUPPORTED"
    assert got["falsified_rule_met"] is False


def test_ci_touching_the_breakeven_edge_is_not_falsified():
    edge = cell(-RHO_BE, RHO_BE, p=0.7)
    assert verdict({"a": edge}, RHO_BE, False)["status"] == "NOT_SUPPORTED"


def test_a_clearly_negative_relation_is_not_falsified_by_accident():
    """Silnie UJEMNA relacja nie jest „brakiem efektu" — nie wolno jej
    wrzucić do FALSIFIED tylko dlatego, że nie jest dodatnia."""
    neg = cell(-0.30, -0.20, p=0.001)
    got = verdict({"a": neg}, RHO_BE, True)
    assert got["status"] == "NOT_SUPPORTED"


# --------------------------------------------------------------------------
# SUPPORTED — union, z kontrolą
# --------------------------------------------------------------------------

def test_supported_needs_both_the_ci_and_the_control():
    strong = cell(0.10, 0.20, p=0.0001)
    assert verdict({"a": strong}, RHO_BE, True)["status"] == "SUPPORTED"
    # ta sama komórka bez pobitej kontroli permutacyjnej
    assert verdict({"a": strong}, RHO_BE, False)["status"] == "NOT_SUPPORTED"


def test_supported_fails_when_holm_kills_a_borderline_cell():
    borderline = cell(0.001, 0.20, p=0.04)
    noise = cell(-0.05, 0.06, p=0.8)
    got = verdict({"a": borderline, "b": noise, "c": noise}, RHO_BE, True)
    assert got["status"] == "NOT_SUPPORTED"
    assert got["holm_pass"]["a"] is False


def test_one_strong_cell_is_enough_for_supported():
    strong, noise = cell(0.10, 0.20, p=0.0001), cell(-0.05, 0.06, p=0.8)
    got = verdict({"a": strong, "b": noise, "c": noise}, RHO_BE, True)
    assert got["status"] == "SUPPORTED"


def test_supported_wins_over_falsified_when_both_would_fire():
    """Nie może zajść naraz, ale gdyby zaszło, SUPPORTED jest silniejszym
    twierdzeniem i musi mieć pierwszeństwo — reguła ma być deterministyczna."""
    odd = cell(0.001, 0.02, p=0.0001)
    got = verdict({"a": odd}, RHO_BE, True)
    assert got["supported_rule_met"] and got["falsified_rule_met"]
    assert got["status"] == "SUPPORTED"


# --------------------------------------------------------------------------
# Obowiązek podania ograniczenia
# --------------------------------------------------------------------------

def test_every_verdict_carries_an_upper_bound():
    """NOT_SUPPORTED bez ograniczenia nie jest wynikiem (prerejestracja)."""
    got = verdict({"a": cell(-0.05, 0.07, p=0.5)}, RHO_BE, False)
    assert got["status"] == "NOT_SUPPORTED"
    assert got["upper_bound_rho"] == pytest.approx(0.07)
    assert got["upper_bound_acc_pct"] == pytest.approx(52.23, abs=0.02)


def test_upper_bound_is_the_widest_cell_not_the_average():
    got = verdict({"a": cell(-0.05, 0.02, p=0.5), "b": cell(-0.05, 0.11, p=0.5)},
                  RHO_BE, False)
    assert got["upper_bound_rho"] == pytest.approx(0.11)


def test_upper_bound_maps_zero_to_fifty_percent():
    assert verdict({"a": cell(-0.05, 0.0, p=0.5)}, RHO_BE, False)[
        "upper_bound_acc_pct"] == pytest.approx(50.0)


# --------------------------------------------------------------------------
# Osie raportowania, diagnostyka par, raport
# --------------------------------------------------------------------------

import datetime as dt  # noqa: E402

import polars as pl  # noqa: E402

from t003_momentum import (  # noqa: E402
    acc_pct, by_axis, realized_pair_dependence, write_markdown,
)

UTC = dt.timezone.utc


def _obs(n_per_sym=600, syms=("EURUSD", "GBPUSD", "USDJPY")):
    rng = np.random.default_rng(11)
    rows = []
    for s in syms:
        for i in range(n_per_sym):
            rows.append({
                "ts_decision": dt.datetime(2019, 1, 7, 9, tzinfo=UTC) + dt.timedelta(hours=i),
                "symbol": s,
                "year": 2019 + i % 3,
                "vol_regime": ("low", "mid", "high")[i % 3],
                "fwd_atr": float(rng.standard_normal()),
                "mom_24": float(rng.standard_normal()),
            })
    return pl.DataFrame(rows)


def test_acc_pct_anchors():
    assert acc_pct(0.0) == pytest.approx(50.0)
    assert acc_pct(0.05401) == pytest.approx(51.72, abs=0.01)


def test_by_axis_covers_every_level():
    obs = _obs()
    got = by_axis(obs, "mom_24", "symbol", min_n=100)
    assert set(got) == {"EURUSD", "GBPUSD", "USDJPY"}
    assert sum(v["n"] for v in got.values()) == obs.height


def test_by_axis_refuses_a_statistic_on_a_thin_group():
    """Spearman na stu nakładających się oknach to szum, ale w tabeli
    wygląda jak wynik — dlatego ma być None, a nie liczba."""
    got = by_axis(_obs(), "mom_24", "vol_regime", min_n=10_000)
    assert all(v["spearman"] is None for v in got.values())
    assert all(v["n"] > 0 for v in got.values())


def test_by_axis_reports_a_statistic_when_the_group_is_big_enough():
    got = by_axis(_obs(), "mom_24", "symbol", min_n=100)
    assert all(isinstance(v["spearman"], float) for v in got.values())


def test_realized_pair_dependence_is_marked_non_binding():
    got = realized_pair_dependence(_obs(), "mom_24")
    assert got["binding"] is False
    assert "diagnostyka" in got["note"]


def test_p_eff_lands_near_the_pair_count_when_pairs_are_independent():
    """Przy niezależnych parach P_eff siada koło P. MOŻE je przekroczyć —
    szumowe korelacje bywają ujemne, a ujemne kasują wariancję (to samo
    zjawisko, przez które `sign_aligned` wyszedł w M05 optymistyczny)."""
    got = realized_pair_dependence(_obs(n_per_sym=2000), "mom_24")
    assert 2.0 < got["p_eff_realized"] < 6.0
    assert abs(got["mean_offdiag"]) < 0.1


def test_p_eff_drops_below_the_pair_count_when_pairs_move_together():
    """Wspólny czynnik MUSI obniżyć P_eff — inaczej diagnostyka nie mierzy
    tego, co ma mierzyć."""
    rng = np.random.default_rng(3)
    n, syms = 1500, ("A", "B", "C")
    common = rng.standard_normal(n)
    rows = []
    for s in syms:
        idio = rng.standard_normal(n)
        for i in range(n):
            rows.append({
                "ts_decision": dt.datetime(2019, 1, 7, 9, tzinfo=UTC) + dt.timedelta(hours=i),
                "symbol": s,
                "fwd_atr": float(0.9 * common[i] + 0.44 * idio[i]),
                "mom_24": 1.0,
            })
    got = realized_pair_dependence(pl.DataFrame(rows), "mom_24")
    assert got["mean_offdiag"] > 0.5
    assert got["p_eff_realized"] < 2.0


def test_realized_pair_dependence_degrades_instead_of_crashing():
    tiny = _obs(n_per_sym=2)
    got = realized_pair_dependence(tiny, "mom_24")
    assert "note" in got


def test_markdown_states_the_verdict_and_the_bound(tmp_path):
    cells = {"k24": {**cell(-0.02, 0.02, p=0.7), "n_obs": 1000, "spearman": 0.0,
                     "se": 0.01, "m05_consistency": {"m05_se": 0.0139, "ratio": 0.72},
                     "aged_control": {"spearman_aged": -0.01, "diff_aged_minus_true": -0.01,
                                      "in_se": -0.5, "passes": True}}}
    report = {"cells": cells, "verdict": verdict(cells, RHO_BE, False),
              "layer_b": None, "pair_dependence": {}}
    pre = yaml.safe_load(PREREG.read_text(encoding="utf-8"))
    out = tmp_path / "t003.md"
    write_markdown(out, report, pre)
    text = out.read_text(encoding="utf-8")
    assert "FALSIFIED" in text
    assert "Górne ograniczenie" in text
    assert "nieuruchomiona" in text          # warstwa B pominięta
    assert "ADR-003" in text


def test_markdown_reports_layer_b_when_it_ran(tmp_path):
    cells = {"k24": {**cell(0.10, 0.20, p=0.0001), "n_obs": 1000, "spearman": 0.15,
                     "se": 0.01, "m05_consistency": {"m05_se": 0.0139, "ratio": 0.72},
                     "aged_control": {"spearman_aged": 0.05, "diff_aged_minus_true": -0.10,
                                      "in_se": -3.0, "passes": True}}}
    report = {
        "cells": cells, "verdict": verdict(cells, RHO_BE, True),
        "layer_b": {"k24": {"n_played": 900, "per_margin": {
            "0.01": {"expectancy_net_r": 0.03, "ci_low": 0.01, "ci_high": 0.05}}}},
        "pair_dependence": {"k24": {"p_eff_realized": 3.4, "mean_offdiag": 0.2,
                                    "n_days": 1500}},
    }
    pre = yaml.safe_load(PREREG.read_text(encoding="utf-8"))
    out = tmp_path / "t003.md"
    write_markdown(out, report, pre)
    text = out.read_text(encoding="utf-8")
    assert "SUPPORTED" in text
    assert "900 transakcji" in text
    assert "P_eff zrealizowane" in text
    assert "Nie zmienia werdyktu" in text


# --------------------------------------------------------------------------
# Kontrakt kolumn między `pooled` a checklistą leakage'u
# --------------------------------------------------------------------------
# Regresja: `pooled` nie zachowywało `bar_ts`, więc `check_bar_closed` trafiał
# w gałąź „nie da się sprawdzić", szukał deklaracji, nie znajdował jej
# i wywracał przebieg — JUŻ PO zapisaniu wpisu `start`, czyli po zapaleniu
# trzech prób. Do tego najcenniejszy automat na off-by-one przestawał działać.

from t003_momentum import LEAKAGE_DECLARATIONS, pooled  # noqa: E402


def _series_for_pooled():
    n = 40
    ts = [dt.datetime(2019, 6, 3, 9, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(n)]
    df = pl.DataFrame({
        "ts_decision": ts,
        "bar_ts": [t - dt.timedelta(hours=1) for t in ts],
        "t1": [t + dt.timedelta(days=3) for t in ts],
        "symbol": ["EURUSD"] * n,
        "year": [2019] * n,
        "hour": [t.hour for t in ts],
        "vol_regime": ["mid"] * n,
        "vol_pct_252": [0.5] * n,
        "ref_price": [1.1] * n,
        "atr_d1_14": [0.01] * n,
        "fwd_atr": np.linspace(-1, 1, n),
        "mom_24": np.linspace(1, -1, n),
        "aged_mom_24": np.linspace(1, -1, n) * 0.99,
    })
    return {"EURUSD": df}


def test_pooled_keeps_bar_ts_for_the_off_by_one_check():
    out = pooled(_series_for_pooled(), "mom_24", "aged_mom_24")
    assert "bar_ts" in out.columns


def test_pooled_output_lets_the_checklist_verify_bar_closure_automatically():
    """Sedno regresji: pozycja ma wyjść `PASS`, a nie `MANUAL`/`FAIL`."""
    from src.validation.leakage import PASS, Checklist, check_bar_closed
    cl = Checklist()
    check_bar_closed(cl, pooled(_series_for_pooled(), "mom_24", "aged_mom_24"), 3600)
    assert cl.checks[0].key == "bar_closed"
    assert cl.checks[0].status == PASS


def test_bar_closure_is_not_declared_away_in_the_runner():
    """Gdyby `bar_closed` trafiło do deklaracji, checklista przeszłaby,
    a sprawdzenie zniknęłoby po cichu — czyli najgorszy możliwy wariant."""
    assert "bar_closed" not in LEAKAGE_DECLARATIONS


def test_every_declaration_covers_a_real_checklist_item():
    from src.validation.leakage import MANUAL_ITEMS
    assert set(LEAKAGE_DECLARATIONS) == set(MANUAL_ITEMS)


def test_pooled_keeps_everything_layer_b_needs():
    """Warstwa B liczy się na wyniku `pooled`; brak kolumny objawiłby się
    dopiero po godzinach symulacji tickowej."""
    out = pooled(_series_for_pooled(), "mom_24", "aged_mom_24")
    for col in ("ts_decision", "t1", "ref_price", "atr_d1_14", "mom_24"):
        assert col in out.columns
