"""Deflacja wyniku o liczbę prób — wpięcie DSR w rejestr (ADR-004, ADR-017).

ADR-004 ustanowił `N = 7` odziedziczonych prób po to, żeby **poprzeczka DSR
startowała podwyższona**. Sam DSR nie był jednak liczony nigdzie: `dsr.py`
przyszedł z portem (ADR-005) i do 2026-09-24 nie importował go żaden moduł
ani żaden skrypt. Ten moduł to naprawia.

CZEGO BRAKOWAŁO I DLACZEGO TO NIE BYŁO SAMO PODŁĄCZENIE

`deflated_sharpe()` potrzebuje dwóch liczb spoza serii zwrotów:

    N        — liczba prób. Jest w `trials.jsonl` i jest prawdziwa.
    V[SR]    — wariancja Sharpe'ów MIĘDZY próbami. **Nie istnieje.**

Dla 7 prób odziedziczonych po `market-quant` nie mamy ich Sharpe'ów —
mamy tylko liczbę (ADR-004). Wariancji między próbami nie da się więc
zmierzyć, a podstawienie jednej liczby byłoby zgadywaniem przebranym za
pomiar. Dlatego, tak jak ADR-014 potraktował `P_eff`, podajemy **nawias**:

    dolny   V[SR] z rozrzutu Sharpe'ów komórek FAKTYCZNIE uruchomionych.
            Zaniża, bo komórek jest mniej niż prób i są do siebie podobne.
    górny   V[SR] z wariancji samego ESTYMATORA Sharpe'a przy tej próbie.
            Zawyża, bo traktuje szum estymacji jak rozrzut między próbami.

Prawdziwa wartość leży między nimi. Raportujemy oba końce i DSR dla obu.

TO JEST DIAGNOSTYKA, NIE TEST

DSR **nie może zmienić werdyktu T003** — kryteria tej prerejestracji były
zamrożone przed tym modułem i mówią o korekcie Holma na trzy komórki, nie
o deflacji o próby odziedziczone. Zmiana kryteriów po zamrożeniu to nowy
eksperyment, nie poprawka. Deflacja może wyłącznie **osłabić** odczyt wyniku
pozytywnego, nigdy go wzmocnić — i w tę stronę wolno ją raportować.

Przyszłe prerejestracje mają deklarować deflację PRZED zamrożeniem (ADR-017).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .dsr import DSRResult, deflated_sharpe, sharpe


@dataclass(frozen=True)
class DeflationBracket:
    """Nawias `V[SR]` i DSR na obu jego końcach."""
    n_trials: int
    n_obs: int
    sharpe: float
    var_low: float
    var_high: float
    dsr_low: DSRResult       # przy DOLNYM V[SR] — deflacja słabsza
    dsr_high: DSRResult      # przy GÓRNYM V[SR] — deflacja mocniejsza
    binding: bool = False

    @property
    def survives_both_ends(self) -> bool:
        """Czy wynik przeżywa deflację także przy mocniejszym końcu nawiasu."""
        return self.dsr_low.dsr > 0.95 and self.dsr_high.dsr > 0.95


def var_sharpe_estimator(sr: float, n_obs: int, skew: float = 0.0,
                         kurtosis: float = 3.0) -> float:
    """Wariancja ESTYMATORA Sharpe'a — górny koniec nawiasu.

    Wzór Lo (2002) z poprawką na wyższe momenty, w jednostce obserwacji:

        V[SR̂] = (1 − γ3·SR̂ + (γ4 − 1)/4 · SR̂²) / (n − 1)

    Używamy go jako GÓRNEGO końca, bo rozrzut estymatora jednej strategii
    jest zwykle większy niż rozrzut prawdziwych Sharpe'ów między wariantami
    tej samej rodziny hipotez.
    """
    if n_obs < 2:
        raise ValueError("n_obs >= 2")
    num = 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr
    return max(float(num) / (n_obs - 1), 0.0)


def var_sharpe_across_cells(cell_returns: dict[str, np.ndarray]) -> float:
    """Wariancja Sharpe'ów między komórkami — dolny koniec nawiasu.

    Zero przy jednej komórce: bez rozrzutu nie ma czego deflować, i tak ma
    być — `expected_max_sharpe` zwróci wtedy 0, czyli brak poprzeczki.
    To jest zaniżenie i jest jawne.
    """
    if len(cell_returns) < 2:
        return 0.0
    srs = np.array([sharpe(np.asarray(r, dtype=float)) for r in cell_returns.values()])
    return float(srs.var(ddof=1))


def deflate(returns: np.ndarray, n_trials: int, *, n_obs: int,
            cell_returns: dict[str, np.ndarray] | None = None,
            ) -> DeflationBracket:
    """DSR na obu końcach nawiasu `V[SR]`.

    `n_obs` to liczba obserwacji EFEKTYWNYCH, nie wierszy — przy etykietach
    nakładających się w ~99% ta druga zawyża statystykę o rząd wielkości.
    """
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        raise ValueError("za mało zwrotów")
    sr = sharpe(r)
    from .dsr import moments
    skew, kurt = moments(r)

    var_low = var_sharpe_across_cells(cell_returns or {})
    var_high = var_sharpe_estimator(sr, n_obs, skew, kurt)
    if var_low > var_high:
        var_low, var_high = var_high, var_low

    return DeflationBracket(
        n_trials=n_trials, n_obs=n_obs, sharpe=sr,
        var_low=var_low, var_high=var_high,
        dsr_low=deflated_sharpe(r, n_trials, var_low, n_obs=n_obs),
        dsr_high=deflated_sharpe(r, n_trials, var_high, n_obs=n_obs),
    )


def live_trial_count(trials_path: Path) -> int:
    """N z rejestru, nie z konfiguracji i nie z pamięci.

    Zaniżone N daje zaniżone `SR*₀` i zawyżone DSR — czyli wynik wygląda
    lepiej, niż jest. Dlatego liczba pochodzi z pliku, który rośnie sam.
    """
    from ..harness.registry import n_trials
    return n_trials(trials_path)


def as_report(br: DeflationBracket) -> dict:
    """Postać do `metrics.json` / raportu, z jawnym „nie wiąże"."""
    return {
        "binding": False,
        "note": ("diagnostyka — NIE zmienia werdyktu T003; kryteria zamrożone "
                 "przed tym modułem mówią o korekcie Holma na 3 komórki "
                 "(ADR-017)"),
        "n_trials": br.n_trials,
        "n_obs_effective": br.n_obs,
        "sharpe_per_obs": br.sharpe,
        "var_sharpe_bracket": [br.var_low, br.var_high],
        "sharpe_benchmark_bracket": [br.dsr_low.sharpe_benchmark,
                                     br.dsr_high.sharpe_benchmark],
        "dsr_bracket": [br.dsr_low.dsr, br.dsr_high.dsr],
        "survives_both_ends": br.survives_both_ends,
    }
