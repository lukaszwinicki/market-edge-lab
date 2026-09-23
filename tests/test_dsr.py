"""Testy PSR/DSR.

Poprawność sprawdzana symulacją: pod H₀ PSR musi być rozkładem
jednostajnym, a SR*₀ musi trafiać w empiryczne maksimum z N prób.
"""
import math

import numpy as np
import pytest

from src.validation.dsr import (
    deflated_sharpe, expected_max_sharpe, moments, probabilistic_sharpe, sharpe,
)


def test_single_trial_has_zero_benchmark():
    assert expected_max_sharpe(1, 0.04) == 0.0


def test_benchmark_grows_with_number_of_trials():
    vals = [expected_max_sharpe(n, 0.01) for n in (2, 10, 50, 500)]
    assert all(a < b for a, b in zip(vals, vals[1:]))


def test_expected_max_sharpe_matches_simulation():
    """SR*₀ ma przybliżać średnie maksimum Sharpe'a z N strategii bez edge'u.

    Tolerancja 1%: zamiana wag γ i 1−γ we wzorze przesuwa wynik o ~2%."""
    rng = np.random.default_rng(0)
    n_trials, n_obs, reps = 50, 250, 2000
    r = rng.standard_normal((reps, n_obs, n_trials))
    srs = r.mean(1) / r.std(1, ddof=1)
    predicted = expected_max_sharpe(n_trials, float(srs.var()))
    assert predicted == pytest.approx(srs.max(1).mean(), rel=0.01)


def test_psr_is_uniform_under_null():
    """Kalibracja: przy prawdziwym SR = 0 odsetek PSR > 0.95 ≈ 5%."""
    rng = np.random.default_rng(1)
    psr = []
    for _ in range(4000):
        r = rng.standard_normal(200)
        psr.append(probabilistic_sharpe(sharpe(r), 0.0, len(r), *moments(r)))
    psr = np.array(psr)
    assert np.mean(psr > 0.95) == pytest.approx(0.05, abs=0.015)
    assert np.mean(psr) == pytest.approx(0.5, abs=0.03)


def test_psr_normal_case_matches_closed_form():
    sr, n = 0.1, 500
    expected = 0.5 * (1 + math.erf(sr * math.sqrt(n - 1) / math.sqrt(1 + sr ** 2 / 2) / math.sqrt(2)))
    assert probabilistic_sharpe(sr, 0.0, n, 0.0, 3.0) == pytest.approx(expected)


def test_negative_skew_and_fat_tails_lower_confidence():
    """Rozkład typu 'dużo małych zysków, rzadka duża strata' — PSR musi spaść."""
    base = probabilistic_sharpe(0.1, 0.0, 300, 0.0, 3.0)
    assert probabilistic_sharpe(0.1, 0.0, 300, -1.5, 3.0) < base
    assert probabilistic_sharpe(0.1, 0.0, 300, 0.0, 9.0) < base


def test_more_trials_deflate_the_same_result():
    rng = np.random.default_rng(2)
    r = rng.standard_normal(500) + 0.15
    one = deflated_sharpe(r, n_trials=1, var_trials_sharpe=0.01)
    many = deflated_sharpe(r, n_trials=50, var_trials_sharpe=0.01)
    assert many.dsr < one.dsr
    assert many.sharpe_benchmark > 0


def test_effective_n_lowers_confidence():
    """Nakładające się transakcje: n_obs = efektywne n, nie liczba wierszy."""
    rng = np.random.default_rng(3)
    r = rng.standard_normal(2000) + 0.05
    nominal = deflated_sharpe(r, 10, 0.002)
    effective = deflated_sharpe(r, 10, 0.002, n_obs=200)
    assert effective.dsr < nominal.dsr


def test_best_of_many_null_strategies_is_not_significant():
    """Sedno DSR: wybranie najlepszej z 100 strategii bez edge'u daje wysoki
    PSR(0), ale DSR musi to zniwelować."""
    rng = np.random.default_rng(4)
    r = rng.standard_normal((250, 100))
    srs = r.mean(0) / r.std(0, ddof=1)
    best = r[:, srs.argmax()]
    assert probabilistic_sharpe(sharpe(best), 0.0, 250, *moments(best)) > 0.95
    res = deflated_sharpe(best, n_trials=100, var_trials_sharpe=float(srs.var(ddof=1)))
    assert res.dsr < 0.95


def test_moments_of_normal_sample():
    rng = np.random.default_rng(5)
    skew, kurt = moments(rng.standard_normal(200_000))
    assert skew == pytest.approx(0.0, abs=0.02)
    assert kurt == pytest.approx(3.0, abs=0.05)


def test_constant_returns_are_rejected():
    with pytest.raises(ValueError):
        sharpe(np.ones(10))
