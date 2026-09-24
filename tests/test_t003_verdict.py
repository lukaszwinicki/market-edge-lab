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
