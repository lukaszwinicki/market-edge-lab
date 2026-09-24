"""`donch_pos` — cecha hipotez H02 (stan) i H07 (zdarzenie).

Moduł NIESIE TREŚĆ HIPOTEZY, tak samo jak `momentum.py`, i z tego samego
powodu mieszka osobno pod własną nazwą: żeby dało się zobaczyć, co go
importuje. Warstwa etykiet nie importuje go ani razu.

ADR-012 I ADR-020

H02 i H07 **nie mają żywej prerejestracji**, więc ADR-012 domyślnie zakazuje
liczenia tej cechy. ADR-020 otwiera wąski wyjątek: wolno ją policzyć
wyłącznie w przebiegu, który **nie tworzy żadnej statystyki parującej ją
z wielkością patrzącą w przód** i jest do tego strukturalnie niezdolny.
Pierwsze zestawienie `donch_pos` z jakimkolwiek zwrotem w przód jest
przebiegiem `strategy` i wymaga prerejestracji.

DWIE RÓŻNE RZECZY POD JEDNĄ NAZWĄ

    STAN (H02)      `donch_pos` — gdzie cena stoi w zakresie N barów.
                    Zmienna ciągła w [0, 1], z definicji przekracza 0,80
                    na ~20% barów.
    ZDARZENIE (H07) pierwsze zamknięcie poza zakresem po okresie przebywania
                    wewnątrz. Rzadkie, punktowe, i NIE jest tym samym.

`market-quant` testował wyłącznie stan (`donch_pos_55 > 0,80`) i nazywał to
wybiciem. `HYPOTHESES.md` H07: *„cokolwiek market-quant zmierzył, nie było
wybiciem w sensie zdarzenia"*. Obie postacie są tu, bo ich rozróżnienie jest
treścią H07 — ale liczone są osobno i nigdy nie mieszane.

BRAK PODGLĄDANIA PRZYSZŁOŚCI

Zakres liczy się z barów ZAMKNIĘTYCH do `t` włącznie, przy czym bar `t`
wchodzi do zakresu — tak samo jak własne zamknięcie. Okno `N` barów
kończące się na `t` jest w całości przeszłością wobec decyzji podejmowanej
o `t + 1h`; za tę granicę odpowiada siatka (`research/grid.py`), nie ten
moduł. Tutaj nie ma arytmetyki na znacznikach ani razu.
"""

from __future__ import annotations

import numpy as np
import polars as pl


def rolling_range(high: np.ndarray, low: np.ndarray, n: int
                  ) -> tuple[np.ndarray, np.ndarray]:
    """(najwyższy szczyt, najniższy dołek) z `n` barów kończących się na `t`.

    Pierwsze `n-1` pozycji to NaN — zakres z niepełnego okna nie jest
    zakresem, a podstawienie czegokolwiek byłoby zgadywaniem.
    """
    if n < 2:
        raise ValueError(f"n musi być >= 2, jest {n}")
    m = high.size
    hi = np.full(m, np.nan)
    lo = np.full(m, np.nan)
    if m < n:
        return hi, lo
    # Widok przesuwny: O(m*n) pamięciowo bez kopii, wystarczające przy m ~ 40k.
    hw = np.lib.stride_tricks.sliding_window_view(high, n)
    lw = np.lib.stride_tricks.sliding_window_view(low, n)
    hi[n - 1:] = hw.max(axis=1)
    lo[n - 1:] = lw.min(axis=1)
    return hi, lo


def donch_pos(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int
              ) -> np.ndarray:
    """Pozycja zamknięcia w zakresie `n` barów, w [0, 1].

    `0` = zamknięcie na dołku okna, `1` = na szczycie. Zakres zerowy (cena
    stała przez całe okno) daje NaN, nie 0,5 — brak zakresu to brak
    informacji o pozycji, a nie pozycja środkowa.
    """
    hi, lo = rolling_range(high, low, n)
    width = hi - lo
    out = np.full(close.size, np.nan)
    ok = np.isfinite(width) & (width > 0)
    out[ok] = (close[ok] - lo[ok]) / width[ok]
    return out


def breakout_event(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                   n: int, *, quiet_bars: int = 0) -> np.ndarray:
    """ZDARZENIE wybicia: pierwsze zamknięcie poza zakresem `n` POPRZEDNICH
    barów, opcjonalnie po `quiet_bars` barach przebywania wewnątrz.

    Zwraca `+1` (wybicie w górę), `-1` (w dół), `0` (brak). To jest inna
    wielkość niż `donch_pos` i sednem H07 jest właśnie ta różnica: stan
    odpala na ~20% barów z definicji percentyla, zdarzenie jest rzadkie.

    Zakres liczony jest z barów POPRZEDZAJĄCYCH `t`, nie włącznie — inaczej
    zamknięcie nigdy nie mogłoby go przekroczyć, bo samo by go wyznaczało.
    """
    hi, lo = rolling_range(high, low, n)
    prev_hi = np.roll(hi, 1)
    prev_lo = np.roll(lo, 1)
    prev_hi[0] = np.nan
    prev_lo[0] = np.nan

    out = np.zeros(close.size, dtype=np.int8)
    up = np.isfinite(prev_hi) & (close > prev_hi)
    dn = np.isfinite(prev_lo) & (close < prev_lo)
    out[up] = 1
    out[dn] = -1

    if quiet_bars > 0:
        # Zdarzeniem jest PIERWSZE wyjście: wybicie poprzedzone `quiet_bars`
        # barami bez wybicia. Bez tego seria zamknięć poza zakresem liczyłaby
        # się jako wiele zdarzeń, a H07 mówi o momencie, nie o stanie.
        fired = out != 0
        keep = np.zeros_like(fired)
        for i in np.flatnonzero(fired):
            lo_i = max(0, i - quiet_bars)
            if not fired[lo_i:i].any():
                keep[i] = True
        out[~keep] = 0
    return out


def attach(h1: pl.DataFrame, lookbacks: tuple[int, ...], *,
           quiet_bars: int = 0) -> pl.DataFrame:
    """Dopisz `donch_pos_<n>` i `brk_evt_<n>` dla każdego `n`.

    Strona BID, jak przy ATR i `mom_k` — nigdzie nie uśredniamy bid z ask.
    """
    h1 = h1.sort("ts")
    if h1.is_empty():
        return h1.with_columns(
            [pl.lit(None, dtype=pl.Float64).alias(f"donch_pos_{n}") for n in lookbacks]
            + [pl.lit(None, dtype=pl.Int8).alias(f"brk_evt_{n}") for n in lookbacks])
    hi = h1.get_column("bid_high").to_numpy()
    lo = h1.get_column("bid_low").to_numpy()
    cl = h1.get_column("bid_close").to_numpy()
    cols = []
    for n in lookbacks:
        cols.append(pl.Series(f"donch_pos_{n}", donch_pos(hi, lo, cl, n)))
        cols.append(pl.Series(f"brk_evt_{n}",
                              breakout_event(hi, lo, cl, n, quiet_bars=quiet_bars)))
    return h1.with_columns(cols)
