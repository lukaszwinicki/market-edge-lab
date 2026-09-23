# PRZENIESIONE z market-quant (ADR-005). Odwolania "ADR-0NN", "PROJECT_SPEC"
# i "SPEC SS" w tym pliku dotycza logu decyzji TAMTEGO projektu, nie tego.
"""Probabilistic i Deflated Sharpe Ratio (Bailey & López de Prado 2012, 2014).

PSR(SR*) — prawdopodobieństwo, że prawdziwy Sharpe przekracza SR*, przy
zaobserwowanym SR̂ z n obserwacji o skośności γ3 i kurtozie γ4:

    PSR = Φ( (SR̂ − SR*) √(n − 1) / √(1 − γ3·SR̂ + (γ4 − 1)/4 · SR̂²) )

DSR — PSR liczone względem SR*₀, czyli OCZEKIWANEGO MAKSIMUM Sharpe'a
z N prób o zerowym prawdziwym Sharpe'ie:

    SR*₀ = √V[SR] · ( (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) )

gdzie γ = stała Eulera-Mascheroniego, V[SR] = wariancja Sharpe'ów między
próbami. N i V[SR] pochodzą z `trials.jsonl` — dlatego licznik prób musi być
prawdziwy. Zaniżone N daje zaniżone SR*₀ i zawyżone DSR.

JEDNOSTKI

Wszystko w jednostkach jednej obserwacji (np. na transakcję), bez
annualizacji. SR̂, V[SR] i n muszą dotyczyć tej samej jednostki.

LICZBA OBSERWACJI

Przy etykietach nakładających się w ~99% `n` = liczba wierszy zawyża
statystykę o rząd wielkości. Podawaj `n_obs` = `effective_sample_size`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


@dataclass(frozen=True)
class DSRResult:
    sharpe: float            # SR̂ na obserwację
    sharpe_benchmark: float  # SR*₀ — oczekiwane maksimum z N prób zerowych
    dsr: float               # P(prawdziwy SR > SR*₀) ∈ [0, 1]
    n_obs: int
    n_trials: int
    skew: float
    kurtosis: float          # nie-nadwyżkowa (normalny = 3)


def sharpe(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    sd = r.std(ddof=1)
    if not sd > 0:
        raise ValueError("zerowe odchylenie — Sharpe nieokreślony")
    return float(r.mean() / sd)


def moments(returns: np.ndarray) -> tuple[float, float]:
    """(skośność, kurtoza nie-nadwyżkowa), estymatory momentów."""
    r = np.asarray(returns, dtype=float)
    z = (r - r.mean()) / r.std(ddof=0)
    return float((z ** 3).mean()), float((z ** 4).mean())


def probabilistic_sharpe(sr: float, sr_benchmark: float, n_obs: int,
                         skew: float = 0.0, kurtosis: float = 3.0) -> float:
    if n_obs < 2:
        raise ValueError("PSR wymaga n_obs >= 2")
    var = 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr ** 2
    if var <= 0:
        raise ValueError("nieujemna wariancja estymatora wymagana — sprawdź momenty")
    return _N.cdf((sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(var))


def expected_max_sharpe(n_trials: int, var_trials_sharpe: float) -> float:
    """SR*₀: oczekiwane maksimum Sharpe'a z n_trials prób bez edge'u."""
    if n_trials < 1:
        raise ValueError("n_trials >= 1")
    if var_trials_sharpe < 0:
        raise ValueError("wariancja nie może być ujemna")
    if n_trials == 1:
        return 0.0
    z1 = _N.inv_cdf(1.0 - 1.0 / n_trials)
    z2 = _N.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_trials_sharpe) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(returns: np.ndarray, n_trials: int, var_trials_sharpe: float,
                    n_obs: int | None = None) -> DSRResult:
    """DSR dla serii zwrotów wybranej strategii.

    `n_obs` — efektywna liczba obserwacji; domyślnie len(returns), co przy
    nakładających się transakcjach jest optymistyczne.
    """
    r = np.asarray(returns, dtype=float)
    sr = sharpe(r)
    skew, kurt = moments(r)
    n = len(r) if n_obs is None else n_obs
    sr0 = expected_max_sharpe(n_trials, var_trials_sharpe)
    return DSRResult(
        sharpe=sr, sharpe_benchmark=sr0,
        dsr=probabilistic_sharpe(sr, sr0, n, skew, kurt),
        n_obs=n, n_trials=n_trials, skew=skew, kurtosis=kurt,
    )
