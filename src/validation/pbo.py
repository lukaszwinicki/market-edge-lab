# PRZENIESIONE z market-quant (ADR-005). Odwolania "ADR-0NN", "PROJECT_SPEC"
# i "SPEC SS" w tym pliku dotycza logu decyzji TAMTEGO projektu, nie tego.
"""Probability of Backtest Overfitting metodą CSCV (Bailey et al. 2017).

Wejście: macierz M (T × N) — T okresów (np. dni), N wariantów strategii
(np. siatka wrażliwości wokół {55, 2.0, 4.0}). Wiersze dzielone są na S
ciągłych bloków. Dla każdej z C(S, S/2) kombinacji połowa bloków jest IS,
reszta OOS:

  1. n* = wariant najlepszy IS,
  2. ω  = względna pozycja n* w rankingu OOS, rank / (N + 1),
  3. λ  = ln(ω / (1 − ω)).

PBO = P(λ ≤ 0) — odsetek kombinacji, w których zwycięzca IS wypada OOS
poniżej mediany. Próg bramki 2: ≤ 0,30.

PBO mierzy PROCES WYBORU, nie jedną strategię. Przy N = 1 nie ma wyboru
i PBO jest nieokreślone — dlatego wymagane N ≥ 2.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from math import comb
from typing import Callable

import numpy as np


@dataclass(frozen=True)
class PBOResult:
    pbo: float
    logits: np.ndarray          # λ dla każdej kombinacji
    n_combinations: int
    n_strategies: int


def sharpe_columns(m: np.ndarray) -> np.ndarray:
    """Sharpe per kolumna; kolumna o zerowej zmienności dostaje −inf."""
    sd = m.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = m.mean(axis=0) / sd
    return np.where(sd > 0, out, -np.inf)


def pbo_cscv(perf: np.ndarray, n_blocks: int = 16,
             metric: Callable[[np.ndarray], np.ndarray] = sharpe_columns) -> PBOResult:
    m = np.asarray(perf, dtype=float)
    if m.ndim != 2:
        raise ValueError("perf musi być macierzą T × N")
    t, n = m.shape
    if n < 2:
        raise ValueError("PBO wymaga co najmniej 2 wariantów")
    if n_blocks < 2 or n_blocks % 2:
        raise ValueError("n_blocks musi być parzyste i >= 2")
    if t < 2 * n_blocks:
        raise ValueError(f"{t} okresów to za mało na {n_blocks} bloków")

    blocks = np.array_split(np.arange(t), n_blocks)
    logits = []
    for is_blocks in itertools.combinations(range(n_blocks), n_blocks // 2):
        is_mask = np.zeros(t, dtype=bool)
        for b in is_blocks:
            is_mask[blocks[b]] = True
        best = int(np.argmax(metric(m[is_mask])))
        oos = metric(m[~is_mask])
        # ranking 1..N rosnąco; remisy dostają średnią pozycję
        rank = np.sum(oos < oos[best]) + (np.sum(oos == oos[best]) + 1) / 2
        w = rank / (n + 1)
        logits.append(np.log(w / (1 - w)))

    lam = np.array(logits)
    return PBOResult(pbo=float(np.mean(lam <= 0)), logits=lam,
                     n_combinations=comb(n_blocks, n_blocks // 2), n_strategies=n)
