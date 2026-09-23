# PRZENIESIONE z market-quant (ADR-005), z src/labels/triple_barrier.py.
"""Nakładanie okien wynikowych i efektywna liczebność próby.

Dlaczego to jest osobny moduł, a nie szczegół modułu etykiet: to jest
wielkość, od której zależy, czy eksperyment w ogóle ma prawo cokolwiek
wykryć. Obie funkcje operują wyłącznie na przedziałach `(ts, t1)` — nie
wiedzą, jaka hipoteza je wygenerowała, i nie muszą wiedzieć.

KONTEKST LICZBOWY (`market-quant`, run `20260922T200750Z-b57ab5`)

    889 transakcji  →  nakładanie 95,9%  →  172 obserwacje efektywne

Do testów istotności wchodzi liczba z prawej strony, nie z lewej. Różnica
bywa rzędu wielkości i decyduje o tym, jak mały efekt jest jeszcze
wykrywalny. Podstawienie `height` zamiast `effective_sample_size` jest
najtańszym znanym sposobem na wyprodukowanie przewagi, której nie ma.
"""

from __future__ import annotations

import polars as pl


def overlap_fraction(labels: pl.DataFrame) -> float:
    """Udział etykiet, których okno wynikowe zachodzi na następną etykietę.

    Diagnostyka, nie filtr. Wartość bliska 1 oznacza, że nominalna liczba
    obserwacji jest wielokrotnie większa od efektywnej — i że bez purge
    z embargo każdy wynik walidacji będzie zawyżony.

    Wymaga kolumn `ts` (moment decyzji) i `t1` (koniec okna wynikowego).
    """
    if labels.height < 2:
        return 0.0
    df = labels.sort("ts")
    overlapping = df.select(
        (pl.col("t1") > pl.col("ts").shift(-1)).sum()
    ).item()
    return overlapping / (df.height - 1)


def effective_sample_size(labels: pl.DataFrame) -> int:
    """Liczba NIENAKŁADAJĄCYCH SIĘ etykiet — zachłannie od najwcześniejszej.

    To jest liczba, którą należy podstawiać do testów istotności, a nie
    `labels.height`.

    Zachłanność jest świadoma i konserwatywna: daje dolne oszacowanie
    liczby niezależnych obserwacji przy tym porządku czasowym. Nie jest to
    maksymalny zbiór rozłącznych przedziałów w sensie kombinatorycznym,
    ale jest deterministyczna i nie zależy od kolejności losowania.
    """
    if labels.is_empty():
        return 0
    n, last_end = 0, None
    for ts, t1 in labels.sort("ts").select("ts", "t1").iter_rows():
        if last_end is None or ts >= last_end:
            n += 1
            last_end = t1
    return n
