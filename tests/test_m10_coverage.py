"""M10 — świat syntetyczny do pomiaru pokrycia SE.

Świat musi mieć te własności, o które pyta M10: nakładające się okna
w przód, korelację międzyparową i klastrowanie zmienności. Jeżeli ich nie
ma, pokrycie zmierzone w nim nie mówi nic o danych prawdziwych.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from m10_se_coverage import (  # noqa: E402
    H_HOURS, decision_rows, estimator_verdict, month_of, simulate_fwd, time_axis,
)

M10 = ROOT / "scripts" / "m10_se_coverage.py"


def code_only() -> str:
    text = re.sub(r'"""(?:.|\n)*?"""', "", M10.read_text(encoding="utf-8"))
    return "\n".join(l.split("#")[0] for l in text.split("\n"))


@pytest.mark.parametrize("forbidden", [
    "load_h1", "harness.market", "research.grid", "data.rates", "fwd_atr",
    "current_vintage", "dukascopy",
])
def test_m10_touches_no_real_data(forbidden):
    assert forbidden not in code_only(), f"M10 sięga po {forbidden}"


def test_m10_declares_its_rule_before_the_run():
    src = M10.read_text(encoding="utf-8")
    assert re.search(r"^VAR_RATIO_TOL\s*=", src, re.M)
    assert re.search(r"^COVERAGE_MIN\s*=", src, re.M)
    assert "criterion_set_before_run" in src


def test_time_axis_has_only_business_days():
    ts, days = time_axis()
    wd = ((days.astype("datetime64[D]").astype(np.int64) + 3) % 7)   # 0 = pon
    assert (wd < 5).all()
    assert ts.size == days.size * 24


def test_decision_rows_stay_in_session_and_keep_a_full_window():
    ts, _ = time_axis()
    rows = decision_rows(ts)
    hour = (ts[rows] - ts[rows].astype("datetime64[D]")).astype(np.int64)
    assert hour.min() == 8 and hour.max() == 21
    assert rows.max() + H_HOURS < ts.size


def test_first_decision_sees_the_first_visible_month():
    ts, _ = time_axis()
    rows = decision_rows(ts)
    assert month_of(ts[rows[:1]])[0] == 0


def _fwd(model, seed=0, rho=0.6):
    ts, _ = time_axis()
    rows = decision_rows(ts)
    chol = np.linalg.cholesky(np.array([[1.0, rho], [rho, 1.0]]))
    return simulate_fwd(np.random.default_rng(seed), ts.size, chol, model, rows), rows


def test_forward_windows_overlap_like_the_real_grid():
    """Sąsiednie decyzje dzielą 71 z 72 godzin; decyzje o dobę i dalej
    od siebie — coraz mniej, aż do zera po trzech dniach."""
    y, rows = _fwd("gauss")
    a = y[:, 0]
    assert np.corrcoef(a[1:], a[:-1])[0, 1] > 0.95
    day_later = np.searchsorted(rows, rows + 72)
    ok = day_later < rows.size
    far = np.corrcoef(a[ok], a[day_later[ok]])[0, 1]
    assert abs(far) < 0.05


def test_forward_returns_carry_the_cross_pair_correlation():
    y, _ = _fwd("gauss", rho=0.6)
    assert np.corrcoef(y[:, 0], y[:, 1])[0, 1] == pytest.approx(0.6, abs=0.03)


def test_stochvol_makes_tails_fatter_than_gauss():
    def kurt(x):
        x = x - x.mean()
        return float((x ** 4).mean() / (x ** 2).mean() ** 2)
    g, _ = _fwd("gauss", seed=1)
    s, _ = _fwd("stochvol", seed=1)
    assert kurt(s[::72, 0]) > kurt(g[::72, 0]) + 0.2


def test_unknown_return_model_is_refused():
    with pytest.raises(ValueError):
        _fwd("garch")


def test_estimator_verdict_on_a_calibrated_estimator():
    rng = np.random.default_rng(0)
    stats = rng.standard_normal(4000) * 0.02
    v = estimator_verdict(0.02, np.full(4000, 0.02), stats)
    assert v["var_ratio"] == pytest.approx(1.0)
    assert v["coverage"] == pytest.approx(0.95, abs=0.01)
    assert v["valid"]


def test_estimator_verdict_rejects_a_too_narrow_estimator():
    rng = np.random.default_rng(1)
    stats = rng.standard_normal(4000) * 0.02
    v = estimator_verdict(0.02, np.full(4000, 0.012), stats)
    assert not v["valid"] and v["coverage"] < 0.90


# --------------------------------------------------------------------------
# M11 — granica ADR-020
# --------------------------------------------------------------------------

M11 = ROOT / "scripts" / "m11_carry_pit_check.py"


@pytest.mark.parametrize("forbidden", [
    "load_h1", "harness.market", "research.grid", "research.labels",
    "fwd_atr", "with_horizon", "bid_", "ask_",
])
def test_m11_never_reads_a_price(forbidden):
    text = re.sub(r'"""(?:.|\n)*?"""', "", M11.read_text(encoding="utf-8"))
    code = "\n".join(l.split("#")[0] for l in text.split("\n"))
    assert forbidden not in code, f"M11 sięga po {forbidden} (ADR-020)"


def test_m11_is_a_control_declaring_the_exception():
    src = M11.read_text(encoding="utf-8")
    assert 'kind="control"' in src and "ADR-020" in src
