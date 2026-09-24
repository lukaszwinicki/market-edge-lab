"""`mom_k` — cecha hipotezy H01. Jedyne miejsce, w którym powstaje.

Moduł NIESIE TREŚĆ HIPOTEZY i to jest celowe: skoro musi gdzieś mieszkać,
mieszka osobno, pod własną nazwą, żeby dało się zobaczyć, co go importuje.
Warstwa etykiet (`research/labels.py`) nie importuje go ani razu — dostaje
wartość cechy w kolumnie i nie wie, skąd pochodzi.

ADR-012

Do 2026-09-24 policzenie tej cechy było ZAKAZANE: dopóki H01 nie miała
żywej, zamrożonej prerejestracji, każdy przebieg dotykający `mom_k`
pokazywałby wynik hipotezy przed jej prerejestracją. Zakaz wygasł wraz
z zamrożeniem T003 (`configs/t003_momentum.yaml`, `sha256 c832dcdc…`).

DEFINICJA

    mom_k = (close - close[-k]) / (atr_h1_14 * sqrt(k))

Dzielnik ma dwa człony i oba są konieczne. `atr_h1_14` sprowadza pary
i okresy do wspólnej skali — bez tego wynik zdominowałyby epizody wysokiej
zmienności (ADR-003). `sqrt(k)` sprowadza do wspólnej skali RÓŻNE k: zwrot
z błądzenia losowego rośnie jak pierwiastek z długości okna, więc bez tego
`mom_480` byłby systematycznie większy od `mom_24` i trzy komórki siatki
mierzyłyby trzy różne rzeczy.

`atr_h1_14`, nie `atr_d1_14` — skale są rozłączne i zamrożone
(`volatility.frozen`): `atr_h1_14` normalizuje WYŁĄCZNIE cechy, `atr_d1_14`
wyznacza WYŁĄCZNIE bariery i jednostkę R.

BRAK PODGLĄDANIA PRZYSZŁOŚCI

Cecha liczy się na barach ZAMKNIĘTYCH: bar o etykiecie `t` zamyka się
o `t + 1h`, więc decyzja podejmowana o `t + 1h` może go użyć, a decyzja
o `t` już nie. Za tę granicę odpowiada siatka (`research/grid.py`), która
dla każdej decyzji podaje `bar_ts` ostatniego zamkniętego bara. Ten moduł
liczy cechę PER BAR i nie zna momentów decyzji — dzięki temu nie ma tu
arytmetyki na znacznikach, którą można by pomylić.
"""

from __future__ import annotations

import numpy as np
import polars as pl


def mom(close: np.ndarray, atr_h1: np.ndarray, k: int) -> np.ndarray:
    """`mom_k` dla jednej serii. Pierwsze `k` pozycji to NaN.

    Nie „0", nie „wartość pierwszego bara" — NaN. Bar bez pełnego okna
    wstecz nie ma określonej cechy i ma wypaść z próby, a nie wejść do niej
    z podstawioną liczbą.
    """
    if k < 1:
        raise ValueError(f"k musi być dodatnie, jest {k}")
    out = np.full(close.size, np.nan)
    if close.size <= k:
        return out
    diff = close[k:] - close[:-k]
    denom = atr_h1[k:] * np.sqrt(k)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[k:] = np.where(denom > 0, diff / denom, np.nan)
    return out


def attach_mom(h1: pl.DataFrame, lookbacks: tuple[int, ...], *,
               close_col: str = "bid_close") -> pl.DataFrame:
    """Dopisz kolumnę `mom_<k>` dla każdego `k` do ramki barów H1.

    `h1` musi mieć już `atr_h1_14` (patrz `features/volatility.atr_h1`).
    Strona BID, jak przy ATR — nigdzie nie uśredniamy bid z ask.
    """
    if "atr_h1_14" not in h1.columns:
        raise ValueError("h1 musi mieć atr_h1_14 — uruchom atr_h1() najpierw")
    h1 = h1.sort("ts")
    if h1.is_empty():
        return h1.with_columns(
            [pl.lit(None, dtype=pl.Float64).alias(f"mom_{k}") for k in lookbacks])
    close = h1.get_column(close_col).to_numpy()
    atr = h1.get_column("atr_h1_14").to_numpy()
    return h1.with_columns(
        [pl.Series(f"mom_{k}", mom(close, atr, k)) for k in lookbacks])


def attach_to_decisions(decisions: pl.DataFrame, h1: pl.DataFrame,
                        lookbacks: tuple[int, ...], *,
                        bar_col: str = "bar_ts") -> pl.DataFrame:
    """Dołącz cechy do decyzji po znaczniku OSTATNIEGO ZAMKNIĘTEGO bara.

    Złączenie jest równościowe po `bar_ts`, nie `join_asof` po czasie decyzji:
    siatka już rozstrzygnęła, który bar wolno użyć, a powtórzenie tego
    rozstrzygnięcia tutaj byłoby drugą kopią tej samej reguły — i pierwszym
    miejscem, w którym obie mogłyby się rozejść.
    """
    cols = [f"mom_{k}" for k in lookbacks]
    feats = attach_mom(h1, lookbacks).select(["ts", *cols])
    return decisions.join(feats, left_on=bar_col, right_on="ts", how="left")
