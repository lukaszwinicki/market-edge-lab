"""M15 — skala efektu z mechanizmu: rachunek na liczbach znanych z góry."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from m15_mechanism_scale import h_day_return_sd, implied_rho  # noqa: E402

M15 = ROOT / "scripts" / "m15_mechanism_scale.py"


def test_implied_rho_on_hand_numbers():
    # Δi SD 1 pp, 3 dni, SD zwrotu 1% → 0,01 · 3/252 / 0,01 = 0,0119
    assert implied_rho(1.0, 0.01, 1.0) == pytest.approx(3 / 252)
    assert implied_rho(1.0, 0.01, 2.0) == pytest.approx(2 * 3 / 252)
    assert implied_rho(1.0, 0.01, 0.0) == 0.0


def test_h_day_return_sd_scales_with_sqrt_h_for_iid_returns():
    rng = np.random.default_rng(0)
    close = np.exp(np.cumsum(rng.standard_normal(200_000) * 0.005))
    assert h_day_return_sd(close, 3) == pytest.approx(0.005 * np.sqrt(3), rel=0.02)


def test_m15_never_pairs_the_feature_with_forward_returns():
    code = re.sub(r'"""(?:.|\n)*?"""', "", M15.read_text(encoding="utf-8"))
    for forbidden in ("fwd", "policy_rates", "carry_policy", "unseal"):
        assert forbidden not in code
