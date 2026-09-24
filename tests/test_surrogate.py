"""Testy maszynerii surogatu z M05 — na danych syntetycznych.

Cały wynik M05 stoi na jednym założeniu: cecha zastępcza ma tę samą strukturę
zależności co `mom_k` pod H0. Jeżeli to nieprawda, zmierzone n_eff jest
fikcją — a przy tym fikcją wyglądającą wiarygodnie, bo skrypt i tak coś
zwróci. Dlatego sprawdzamy to na procesach o ZNANEJ odpowiedzi, nie na rynku.

Trzy rzeczy, które muszą być prawdziwe:

1. Autokorelacja surogatu to (1 − ℓ/k)⁺ — tyle, ile ma znormalizowana różnica
   błądzenia losowego na oknie k, czyli `mom_k` przy braku efektu.
2. Kalibracja SE: przy wierszach niezależnych zmierzone SE statystyki musi
   wyjść 1/√n. Bez tego „inflacja względem iid" nie mierzy zależności, tylko
   błąd implementacji.
3. Korelacja międzyparowa surogatu odtwarza zadaną macierz.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from m05_layer_a_null import (  # noqa: E402
    _pearson, _rank, acc_from_rho, decision_numbers, model_corr, psd_chol,
    statistics,
)


def surrogate(rng, t, k, chol):
    """Ten sam wzór co w M05: różnica skumulowanych przyrostów na oknie k."""
    inno = rng.standard_normal((t + k, chol.shape[0])) @ chol.T
    walk = np.cumsum(inno, axis=0)
    return (walk[k:] - walk[:-k]) / np.sqrt(k)


# --------------------------------------------------------------------------
# 1. Autokorelacja cechy zastępczej
# --------------------------------------------------------------------------

@pytest.mark.parametrize("k", [24, 120, 480])
def test_surrogate_autocorrelation_matches_overlapping_window(k):
    """(1 − ℓ/k)⁺ — dokładnie autokorelacja `mom_k` pod błądzeniem losowym."""
    rng = np.random.default_rng(7)
    f = surrogate(rng, 300_000, k, np.eye(1))[:, 0]
    for lag in (1, k // 4, k // 2, k - 1):
        got = np.corrcoef(f[:-lag], f[lag:])[0, 1]
        assert got == pytest.approx(1 - lag / k, abs=0.02)


@pytest.mark.parametrize("k", [24, 120])
def test_surrogate_decorrelates_beyond_window(k):
    """Poza oknem okna są rozłączne, więc korelacja znika.

    Tolerancja idzie z liczby okien ROZŁĄCZNYCH (n/k), nie z liczby próbek:
    przy k = 120 na 300 000 barów jest ich 2 500, więc samo SE korelacji to
    0,02. Stała tolerancja udawałaby tu dokładność, której nie ma.
    """
    rng = np.random.default_rng(8)
    n = 300_000
    f = surrogate(rng, n, k, np.eye(1))[:, 0]
    tol = 4 / np.sqrt(n / k)
    for lag in (k, 2 * k):
        assert abs(np.corrcoef(f[:-lag], f[lag:])[0, 1]) < tol


def test_white_noise_feature_would_understate_dependence():
    """Kontrola negatywna: szum biały NIE odtwarza autokorelacji `mom_k`.

    Gdyby M05 użył szumu zamiast różnicy błądzenia, rozrzut statystyki byłby
    zaniżony, a n_eff wzięte z sufitu. Ten test pilnuje, żeby różnica między
    jednym a drugim pozostała widoczna, a nie została uznana za szczegół.
    """
    rng = np.random.default_rng(9)
    white = rng.standard_normal(200_000)
    assert abs(np.corrcoef(white[:-1], white[1:])[0, 1]) < 0.01
    f = surrogate(rng, 200_000, 120, np.eye(1))[:, 0]
    assert np.corrcoef(f[:-1], f[1:])[0, 1] > 0.98


# --------------------------------------------------------------------------
# 2. Kalibracja SE statystyk
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stat", ["spearman", "pearson"])
def test_se_equals_one_over_sqrt_n_for_independent_rows(stat):
    """Przy wierszach niezależnych SE = 1/√n. To jest zero przyrządu M05."""
    rng = np.random.default_rng(11)
    n, reps = 3000, 800
    fwd = rng.standard_normal(n)
    fr = _rank(fwd)
    vals = [statistics(rng.standard_normal(n), fwd, fr)[stat] for _ in range(reps)]
    se = float(np.std(vals, ddof=1))
    assert se * np.sqrt(n) == pytest.approx(1.0, abs=0.06)


def test_statistics_are_centred_under_null():
    """Pod H0 wszystkie trzy statystyki mają wartość oczekiwaną zero."""
    rng = np.random.default_rng(12)
    n, reps = 2000, 500
    fwd = rng.standard_normal(n)
    fr = _rank(fwd)
    draws = [statistics(rng.standard_normal(n), fwd, fr) for _ in range(reps)]
    for name in ("spearman", "pearson", "signed"):
        v = np.array([d[name] for d in draws])
        assert abs(v.mean()) < 3 * v.std(ddof=1) / np.sqrt(reps)


def test_dependent_rows_inflate_se_above_iid():
    """Wiersze z cechą autoskorelowaną MUSZĄ dać SE większe niż 1/√n.

    Kierunek, nie wartość: jeżeli inflacja wychodzi ≤ 1, to znaczy, że
    zależność gdzieś zniknęła po drodze.
    """
    rng = np.random.default_rng(13)
    n, reps, k = 4000, 300, 200
    fwd = np.cumsum(rng.standard_normal(n + 5))[5:] - np.cumsum(rng.standard_normal(n + 5))[:-5]
    fr = _rank(fwd)
    vals = [statistics(surrogate(rng, n, k, np.eye(1))[:, 0], fwd, fr)["spearman"]
            for _ in range(reps)]
    assert float(np.std(vals, ddof=1)) * np.sqrt(n) > 1.5


# --------------------------------------------------------------------------
# 3. Struktura międzyparowa
# --------------------------------------------------------------------------

def test_surrogate_reproduces_requested_cross_pair_correlation():
    rng = np.random.default_rng(14)
    target = np.array([[1.0, 0.6, -0.3],
                       [0.6, 1.0, -0.5],
                       [-0.3, -0.5, 1.0]])
    f = surrogate(rng, 200_000, 60, psd_chol(target))
    got = np.corrcoef(f, rowvar=False)
    assert np.abs(got - target).max() < 0.03


def test_sign_aligned_flips_all_off_diagonals_positive():
    rho = np.array([[1.0, 0.5, -0.5],
                    [0.5, 1.0, -0.6],
                    [-0.5, -0.6, 1.0]])
    s = model_corr("sign_aligned", rho, rho)
    off = ~np.eye(3, dtype=bool)
    assert (s[off] > 0).all()
    assert np.abs(s[off]) == pytest.approx(np.abs(rho[off]))


def test_model_corr_selects_the_right_matrix_per_model():
    a = np.eye(3)
    b = np.full((3, 3), 0.4) + 0.6 * np.eye(3)
    assert np.allclose(model_corr("independent", b, b), np.eye(3))
    assert np.allclose(model_corr("as_returns_h", a, b), a)
    assert np.allclose(model_corr("as_returns_k", a, b), b)


def test_psd_chol_survives_slightly_indefinite_input():
    """Uśrednianie po fazach potrafi dać wartość własną −1e-16."""
    c = np.array([[1.0, 0.9, 0.9],
                  [0.9, 1.0, 0.9],
                  [0.9, 0.9, 1.0]])
    c[0, 1] = c[1, 0] = 1.0 + 1e-12
    chol = psd_chol(c)
    assert np.isfinite(chol).all()
    assert np.diag(chol @ chol.T) == pytest.approx(np.ones(3))


# --------------------------------------------------------------------------
# 4. Przeliczenie na wielkości decyzyjne
# --------------------------------------------------------------------------

def test_acc_from_rho_anchors():
    assert acc_from_rho(0.0) == pytest.approx(0.5)
    # Próg opłacalności h=3d z M04 odpowiada rho ≈ 0,054.
    assert acc_from_rho(0.05401) == pytest.approx(0.5172, abs=1e-4)


def test_falsified_reachable_flips_at_the_right_n():
    """Kryterium równoważności: połowa CI95 musi zmieścić się pod progiem
    opłacalności. Przy n tuż poniżej progu ma być nieosiągalne, tuż powyżej —
    osiągalne. Granica nie może zależeć od tego, kto ją czyta."""
    rho_be = float(np.sin((0.5172 - 0.5) * np.pi))
    n_needed = (1.959963984540054 / rho_be) ** 2
    assert not decision_numbers(1 / np.sqrt(n_needed * 0.95), 3)["falsified_reachable"]
    assert decision_numbers(1 / np.sqrt(n_needed * 1.05), 3)["falsified_reachable"]


def test_decision_numbers_reports_n_eff_consistent_with_se():
    d = decision_numbers(1 / np.sqrt(1902), 3)
    assert d["n_eff_implied"] == pytest.approx(1902, rel=1e-3)
    assert d["mde_acc_pct"] > d["breakeven_acc_pct"]
