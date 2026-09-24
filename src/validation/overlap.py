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

import datetime as dt

import numpy as np
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


# ---------------------------------------------------------------------------
# Purge + embargo
# ---------------------------------------------------------------------------
# CLAUDE.md: nakładające się etykiety wymagają purge + embargo **zawsze**, nie
# „gdy trzeba". Powód jest w liczbie wyżej: przy nakładaniu 95,9% niemal każda
# etykieta treningowa dzieli okno wynikowe z jakąś etykietą testową. Model
# uczony na takim zbiorze widzi przyszłość swojego zbioru testowego — nie
# przez błąd w kodzie, tylko przez samą konstrukcję etykiet.
#
# PURGE usuwa z treningu etykiety, których okno wynikowe zachodzi na okno
# którejkolwiek etykiety testowej. EMBARGO usuwa dodatkowo te, które zaczynają
# się tuż PO zbiorze testowym: okna już się nie nakładają, ale szereg jest
# autoskorelowany i sąsiedztwo samo w sobie niesie informację.
#
# Oba są tu funkcjami na przedziałach, nie metodą klasy walidatora — żeby dało
# się je wywołać z każdego schematu podziału i żeby nie dało się ich pominąć
# „bo akurat ten schemat ich nie ma".


def merge_intervals(starts: np.ndarray, ends: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Suma przedziałów jako rozłączne, posortowane przedziały.

    Bez scalania sprawdzenie nakładania byłoby O(n_train × n_test); po
    scaleniu jest O(log m) na zapytanie. Przy 130 tys. wierszy to różnica
    między sekundami a godzinami, więc nie jest to optymalizacja przedwczesna.
    """
    if starts.size == 0:
        return starts, ends
    order = np.argsort(starts, kind="stable")
    s, e = starts[order], ends[order]
    keep_s, keep_e = [s[0]], [e[0]]
    for i in range(1, s.size):
        if s[i] <= keep_e[-1]:
            if e[i] > keep_e[-1]:
                keep_e[-1] = e[i]
        else:
            keep_s.append(s[i])
            keep_e.append(e[i])
    return np.array(keep_s), np.array(keep_e)


def overlaps_any(ts: np.ndarray, t1: np.ndarray,
                 other_ts: np.ndarray, other_t1: np.ndarray) -> np.ndarray:
    """Maska: które przedziały `[ts, t1)` zachodzą na którykolwiek z drugich.

    Przedziały są półotwarte, więc styk końcem do początku NIE jest
    nakładaniem: etykieta kończąca się dokładnie wtedy, gdy zaczyna się
    testowa, nie widziała ani jednego bara z jej okna.
    """
    if ts.size == 0 or other_ts.size == 0:
        return np.zeros(ts.size, dtype=bool)
    ms, me = merge_intervals(other_ts, other_t1)
    # Ile scalonych przedziałów zaczyna się PRZED końcem zapytania.
    idx = np.searchsorted(ms, t1, side="left")
    prefix_max_end = np.maximum.accumulate(me)
    out = np.zeros(ts.size, dtype=bool)
    nz = idx > 0
    out[nz] = prefix_max_end[idx[nz] - 1] > ts[nz]
    return out


def purge_mask(train: pl.DataFrame, test: pl.DataFrame) -> np.ndarray:
    """Maska wierszy treningowych, które WOLNO zostawić (purge).

    Odpada każdy wiersz, którego okno wynikowe zachodzi na okno którejkolwiek
    etykiety testowej — niezależnie od tego, czy leży przed, czy po niej.
    """
    if train.is_empty():
        return np.zeros(0, dtype=bool)
    return ~overlaps_any(
        train.get_column("ts").to_numpy(), train.get_column("t1").to_numpy(),
        test.get_column("ts").to_numpy(), test.get_column("t1").to_numpy())


def embargo_mask(train: pl.DataFrame, test: pl.DataFrame,
                 embargo: dt.timedelta) -> np.ndarray:
    """Maska wierszy treningowych, które WOLNO zostawić (embargo).

    Odpada wiersz zaczynający się w `[koniec bloku testowego, +embargo)`.
    Embargo dotyczy wyłącznie tego, co następuje PO teście: to, co przed,
    załatwia purge.

    `embargo = 0` zwraca same `True` — i jest to wybór, który trzeba podjąć
    świadomie, a nie domyślny.
    """
    if train.is_empty():
        return np.zeros(0, dtype=bool)
    keep = np.ones(train.height, dtype=bool)
    if embargo <= dt.timedelta(0) or test.is_empty():
        return keep
    ts = train.get_column("ts").to_numpy()
    # Bloki testowe jako rozłączne przedziały — embargo liczy się od końca
    # każdego z nich osobno, bo przy CPCV bloków bywa kilka.
    ms, me = merge_intervals(test.get_column("ts").to_numpy(),
                             test.get_column("t1").to_numpy())
    delta = np.timedelta64(int(embargo.total_seconds() * 1000), "ms")
    for end in me:
        keep &= ~((ts >= end) & (ts < end + delta))
    return keep


def purge_and_embargo(train: pl.DataFrame, test: pl.DataFrame,
                      embargo: dt.timedelta) -> pl.DataFrame:
    """Trening po purge i embargo. Jedyna droga, którą wolno budować trening.

    `embargo` jest argumentem **bez wartości domyślnej** celowo: „zero" ma być
    decyzją zapisaną w wywołaniu, a nie skutkiem tego, że ktoś nie wiedział,
    że taki parametr istnieje.
    """
    if train.is_empty():
        return train
    return train.filter(pl.Series(purge_mask(train, test)
                                  & embargo_mask(train, test, embargo)))


def purged_splits(labels: pl.DataFrame, n_splits: int, embargo: dt.timedelta):
    """Podział na `n_splits` bloków czasowych z purge i embargo.

    Bloki są **ciągłe w czasie**, nie losowe: losowy k-fold na szeregu
    czasowym miesza przeszłość z przyszłością jeszcze przed purge i żaden
    purge tego nie naprawia.

    Zwraca pary `(train, test)`. Wywołujący dostaje ramki, nie indeksy —
    indeksy kuszą, żeby „na chwilę" sięgnąć do pełnego zbioru.
    """
    if n_splits < 2:
        raise ValueError("n_splits >= 2")
    df = labels.sort("ts")
    bounds = np.linspace(0, df.height, n_splits + 1).astype(int)
    for i in range(n_splits):
        lo, hi = bounds[i], bounds[i + 1]
        if hi <= lo:
            continue
        test = df[lo:hi]
        rest = pl.concat([df[:lo], df[hi:]]) if lo or hi < df.height else df[:0]
        yield purge_and_embargo(rest, test, embargo), test


def purge_report(before: pl.DataFrame, after: pl.DataFrame, test: pl.DataFrame) -> dict:
    """Ile purge i embargo zabrały. Raportowane obowiązkowo.

    Przy nakładaniu bliskim 1 purge potrafi skasować większość treningu —
    i to jest poprawny wynik, ale taki, o którym trzeba wiedzieć przed
    czytaniem metryki, a nie po.
    """
    n0, n1 = before.height, after.height
    return {
        "n_train_before": n0,
        "n_train_after": n1,
        "removed": n0 - n1,
        "removed_share": round((n0 - n1) / n0, 6) if n0 else None,
        "n_test": test.height,
        "n_test_effective": effective_sample_size(test),
    }
