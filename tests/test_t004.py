"""Runner T004 — kryteria i granice, na liczbach wpisanych ręcznie."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from t004_carry import consistency, verdict  # noqa: E402

T004 = ROOT / "scripts" / "t004_carry.py"
KW = dict(z_supported=2.8302, rho_breakeven=0.05401)


def test_supported_needs_the_deflated_lower_bound_above_zero():
    assert verdict(0.06, 0.02, **KW)["status"] == "SUPPORTED"      # 0,06 − 2,83·0,02 > 0
    assert verdict(0.05, 0.02, **KW)["status"] == "NOT_SUPPORTED"  # CI95 > 0, po deflacji nie


def test_falsified_uses_the_undeflated_ci():
    v = verdict(0.0, 0.02, **KW)
    assert v["status"] == "FALSIFIED" and v["falsified_reachable_in_run"]


def test_falsified_is_unreachable_when_the_se_is_too_wide():
    v = verdict(0.0, 0.03, **KW)
    assert v["status"] == "NOT_SUPPORTED" and not v["falsified_reachable_in_run"]


def test_a_negative_relation_is_never_supported():
    assert verdict(-0.2, 0.02, **KW)["status"] == "NOT_SUPPORTED"


def test_upper_bound_is_reported_in_accuracy_units():
    v = verdict(0.0, 0.02, **KW)
    assert v["upper_bound_acc_pct"] == pytest.approx(50 + 100 * __import__("math").asin(0.0392) / 3.141592653589793, abs=0.01)


def test_consistency_band_is_inclusive():
    assert consistency(0.01236, (0.01236, 0.05084))["passes"]
    assert not consistency(0.06, (0.01236, 0.05084))["passes"]


def _code():
    text = re.sub(r'"""(?:.|\n)*?"""', "", T004.read_text(encoding="utf-8"))
    return "\n".join(l.split("#")[0] for l in text.split("\n"))


@pytest.mark.parametrize("forbidden", ["data.rates", "current_vintage", "ALFRED_DIR", "pit_last_value"])
def test_t004_never_uses_the_oecd_series(forbidden):
    """Cecha T004 to stopy polityki (ADR-026). OECD/ALFRED nie może wrócić tylnymi drzwiami."""
    assert forbidden not in _code()


def test_t004_logs_itself_as_a_single_trial():
    assert 'kind="strategy", n_variants=1' in _code()
