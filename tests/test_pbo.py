"""Testy PBO (CSCV) na macierzach syntetycznych o znanej odpowiedzi."""
import numpy as np
import pytest

from src.validation.pbo import pbo_cscv, sharpe_columns


def test_pure_noise_strategies_give_pbo_near_half():
    """Wybór najlepszej z identycznych strategii bez edge'u to rzut monetą OOS."""
    vals = []
    for seed in range(5):
        rng = np.random.default_rng(seed)
        vals.append(pbo_cscv(rng.standard_normal((1000, 20)), n_blocks=10).pbo)
    assert np.mean(vals) == pytest.approx(0.5, abs=0.12)


def test_one_genuinely_better_strategy_gives_low_pbo():
    rng = np.random.default_rng(10)
    m = rng.standard_normal((1000, 20))
    m[:, 7] += 0.3
    res = pbo_cscv(m, n_blocks=10)
    assert res.pbo < 0.05


def test_overfit_selection_gives_high_pbo():
    """Strategie, których forma IS przechodzi w odwrotność OOS
    (mean reversion wyniku), muszą dać PBO > 0.5."""
    rng = np.random.default_rng(11)
    t, n = 1000, 10
    m = rng.standard_normal((t, n)) * 0.5
    # każda strategia ma dobry okres i zły okres o równej sumie; zwycięzca
    # dowolnej połowy wygrywa dzięki swojemu dobremu okresowi, więc w
    # pozostałej połowie trafia na zły
    period = t // n
    for j in range(n):
        m[j * period:(j + 1) * period, j] += 1.0
        other = ((j + n // 2) % n)
        m[other * period:(other + 1) * period, j] -= 1.0
    res = pbo_cscv(m, n_blocks=n)
    assert res.pbo > 0.5


def test_number_of_combinations():
    rng = np.random.default_rng(0)
    res = pbo_cscv(rng.standard_normal((200, 3)), n_blocks=8)
    assert res.n_combinations == 70
    assert len(res.logits) == 70


def test_single_strategy_is_rejected():
    """PBO mierzy proces wyboru — bez wyboru jest nieokreślone."""
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 1)))


def test_odd_blocks_are_rejected():
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 3)), n_blocks=7)


def test_too_short_sample_is_rejected():
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((20, 3)), n_blocks=16)


def test_constant_column_never_wins():
    m = np.column_stack([np.zeros(100), np.random.default_rng(0).standard_normal(100)])
    s = sharpe_columns(m)
    assert s[0] == -np.inf
