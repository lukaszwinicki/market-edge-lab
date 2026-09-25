"""M14 — κ dla bootstrapu: reguła i jej części na danych syntetycznych.

κ musi odzyskać znany współczynnik niedoszacowania SE, zbiory kalibracji
i walidacji muszą być rozłączne z konstrukcji, a bramki muszą wymagać
każdego wariantu, nie średniej.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import m14_kappa_bootstrap as m14  # noqa: E402
from m14_kappa_bootstrap import (  # noqa: E402
    RHO_BE, SIZE_STOP, STREAM_CAL, STREAM_H0, STREAM_H1, Z_CI, coverage, falsified,
    gates, kappa_combined, kappa_variant, supported, world_seed,
)

M14 = ROOT / "scripts" / "m14_kappa_bootstrap.py"


def code_only() -> str:
    text = re.sub(r'"""(?:.|\n)*?"""', "", M14.read_text(encoding="utf-8"))
    return "\n".join(l.split("#")[0] for l in text.split("\n"))


@pytest.mark.parametrize("forbidden", [
    "load_h1", "harness.market", "research.grid", "data.rates", "fwd_atr",
    "policy_rates", "dukascopy", "run_cell",
])
def test_m14_touches_no_real_data(forbidden):
    assert forbidden not in code_only(), f"M14 sięga po {forbidden}"


@pytest.mark.parametrize("const", [
    "N_CAL", "N_VAL_H0", "N_VAL_H1", "COVERAGE_TARGET", "COVERAGE_MIN",
    "GATE_RHO", "GATE_POWER", "Z_SUP", "RHO_BE", "SIZE_STOP", "SEED",
])
def test_m14_declares_its_rule_as_constants(const):
    assert re.search(rf"^{const}\s*=", M14.read_text(encoding="utf-8"), re.M)


def test_m14_rule_values_match_the_approved_plan():
    assert (m14.COVERAGE_MIN, m14.GATE_RHO, m14.GATE_POWER) == (0.90, 0.12, 0.50)
    assert (m14.Z_SUP, m14.RHO_BE, m14.SIZE_STOP) == (2.8302, 0.05401, 9)
    assert m14.SEED not in (20260927, 20261002)          # M10, M13
    assert m14.BLOCK_DAYS == 20                           # jak runner T004


def test_kappa_recovers_known_understatement():
    rng = np.random.default_rng(0)
    s = 1.3
    rho = rng.standard_normal(200_000) * s * 0.02
    se = np.full(rho.size, 0.02)
    assert kappa_variant(rho, se) == pytest.approx(s, rel=0.01)


def test_kappa_is_one_for_a_correct_se():
    rng = np.random.default_rng(1)
    rho = rng.standard_normal(200_000) * 0.02
    assert kappa_variant(rho, np.full(rho.size, 0.02)) == pytest.approx(1.0, abs=0.01)


def test_kappa_combined_takes_worst_and_never_narrows():
    assert kappa_combined({"a": 1.05, "b": 1.21, "c": 0.9}) == 1.21
    assert kappa_combined({"a": 0.8, "b": 0.95}) == 1.0


def test_calibration_and_validation_worlds_are_disjoint():
    def first(stream, w):
        return np.random.default_rng(world_seed(stream, 0, 0, w)).standard_normal(4)
    cal = {tuple(first(STREAM_CAL, w)) for w in range(50)}
    val = {tuple(first(s, w)) for s in (STREAM_H0, STREAM_H1) for w in range(50)}
    assert len(cal) == 50 and not cal & val


def test_world_seed_is_deterministic():
    a = np.random.default_rng(world_seed(1, 2, 0, 7)).standard_normal(3)
    b = np.random.default_rng(world_seed(1, 2, 0, 7)).standard_normal(3)
    assert np.array_equal(a, b)


def test_coverage_uses_kappa():
    rho = np.array([0.0, 0.03, 0.05])
    se = np.full(3, 0.02)
    assert coverage(rho, se, 1.0) == pytest.approx(2 / 3)
    assert coverage(rho, se, 1.3) == 1.0


def test_supported_and_falsified_follow_the_verdict_of_t004():
    se = np.array([0.02])
    assert supported(np.array([0.07]), se, 1.0)[0]
    assert not supported(np.array([0.07]), se, 1.3)[0]
    assert falsified(np.array([0.0]), se, 1.0)[0]
    assert not falsified(np.array([0.0]), np.array([0.03]), 1.0)[0]


def _h0(cov, half):
    return {"coverage": cov, "half_ci_median": half}


def test_gates_pass_only_when_every_variant_passes():
    ok = {v: _h0(0.95, 0.05) for v in "abcd"}
    power = {v: 0.8 for v in "abcd"}
    assert gates(ok, power, 3)["m14_passed"]

    one_low_cov = dict(ok, d=_h0(0.89, 0.05))
    assert not gates(one_low_cov, power, 3)["g1_passed"]

    one_low_power = dict(power, c=0.49)
    assert not gates(ok, one_low_power, 3)["g2_passed"]

    one_wide = dict(ok, b=_h0(0.95, RHO_BE))
    r = gates(one_wide, power, 3)
    assert not r["g3_passed"] and not r["m14_passed"]

    assert gates(ok, power, SIZE_STOP)["size_stop"]
    assert not gates(ok, power, SIZE_STOP - 1)["size_stop"]
    assert not gates(ok, power, SIZE_STOP)["m14_passed"]


def test_g3_threshold_matches_adr024():
    # pół-CI < ρ_be ⇔ SE < 0,02756 przy κ = 1 (ADR-024)
    assert RHO_BE / Z_CI == pytest.approx(0.02756, abs=1e-5)
