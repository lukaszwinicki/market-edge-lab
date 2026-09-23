"""Skale zmienności — jedyne miejsce, w którym powstają `atr_h1_14` i `atr_d1_14`.

Konfiguracja zamroziła obie (`volatility.frozen: true`) i rozdzieliła im
role: `atr_h1_14` normalizuje WYŁĄCZNIE cechy, `atr_d1_14` wyznacza WYŁĄCZNIE
bariery i jednostkę R. Pomylenie skal degeneruje etykiety do szumu
mikrostruktury, dlatego mieszkają obok siebie i mają rozłączne nazwy.

Moduł nie zna żadnej hipotezy. Liczy zmienność, nie sygnał — i dlatego może
powstać przed warstwą etykiet, nie po niej.

BRAK PODGLĄDANIA PRZYSZŁOŚCI

Wilder ATR jest przyczynowy z definicji: wartość w barze `t` zależy wyłącznie
od barów do `t` włącznie. Dzienna granica przyczynowa nie jest — bar D1 dnia,
w którym zapada decyzja, zamyka się dopiero o północy PO niej. Dlatego każdy
dzienny bar dostaje `available_from` = początek NASTĘPNEJ doby, a decyzje
łączą się z serią dzienną przez `join_asof` po tej kolumnie, nie po dacie.
Ręczna arytmetyka na znacznikach jest tu najkrótszą drogą do cichego
przecieku — ten sam powód, dla którego istnieje `last_closed_bar()`.

STRONA RYNKU

ATR jest miarą zakresu, nie ceną wykonania, więc liczymy go w całości po
stronie BID. To spełnia zakaz ceny mid (nigdzie nie uśredniamy bid z ask)
i daje jedną, spójną serię zamiast dwóch prawie identycznych.

DOBA NIEPEŁNA

Doba z mniej niż `min_h1_bars` barami H1 wypada z serii dziennej w całości
(`data.d1_boundary.min_h1_bars`). Bez tego sesja niedzielna — trzy bary —
tworzy własny bar dzienny o zakresie bliskim zeru i zaniża `atr_d1_14`
o kilkanaście procent, czyli zaniża jednostkę R, czyli wszystko.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl

UTC = dt.timezone.utc


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """True range. Pozycja 0 to NaN — bez poprzedniego zamknięcia nie istnieje."""
    tr = np.full(high.shape, np.nan, dtype=float)
    if high.size < 2:
        return tr
    prev = close[:-1]
    tr[1:] = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)),
    )
    return tr


def wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               period: int = 14) -> np.ndarray:
    """ATR Wildera. NaN, dopóki nie ma pełnego okna rozgrzewki.

    Zasiew to średnia z pierwszych `period` prawdziwych zakresów, potem
    wygładzanie rekurencyjne. Pierwsza wartość określona pada w indeksie
    `period` i wymaga `period + 1` barów — bo TR w indeksie 0 nie istnieje.
    """
    if period < 1:
        raise ValueError("period musi być dodatni")
    n = high.size
    atr = np.full(n, np.nan, dtype=float)
    if n <= period:
        return atr

    tr = true_range(high, low, close)
    if np.isnan(tr[1:period + 1]).any():
        return atr
    atr[period] = tr[1:period + 1].mean()
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def atr_h1(h1: pl.DataFrame, period: int = 14) -> pl.DataFrame:
    """`atr_h1_14` w skali bara H1 — normalizator CECH, nie barier.

    Wartość w barze o etykiecie T jest policzona z barów do T włącznie,
    więc wolno jej użyć decyzji podejmowanej po zamknięciu bara T.
    """
    if h1.is_empty():
        return h1.with_columns(pl.lit(None, dtype=pl.Float64).alias("atr_h1_14"))
    atr = wilder_atr(
        h1.get_column("bid_high").to_numpy(),
        h1.get_column("bid_low").to_numpy(),
        h1.get_column("bid_close").to_numpy(),
        period,
    )
    return h1.with_columns(pl.Series("atr_h1_14", atr))


def daily_bars(h1: pl.DataFrame, min_h1_bars: int) -> pl.DataFrame:
    """Seria dzienna z barów H1, granica doby 00:00 UTC.

    Doby niepełne odpadają PRZED liczeniem ATR, nie po — inaczej wchodzą
    w rekurencję Wildera i skażają wszystkie kolejne wartości.
    """
    if h1.is_empty():
        return pl.DataFrame(
            schema={"day": pl.Datetime("ms", "UTC"), "bid_high": pl.Float64,
                    "bid_low": pl.Float64, "bid_close": pl.Float64,
                    "n_h1": pl.UInt32}
        )
    return (
        h1.sort("ts")
        .group_by_dynamic("ts", every="1d", closed="left", label="left")
        .agg(
            pl.col("bid_high").max(),
            pl.col("bid_low").min(),
            pl.col("bid_close").last(),
            pl.len().cast(pl.UInt32).alias("n_h1"),
        )
        .filter(pl.col("n_h1") >= min_h1_bars)
        .rename({"ts": "day"})
    )


def atr_d1(h1: pl.DataFrame, min_h1_bars: int, period: int = 14) -> pl.DataFrame:
    """`atr_d1_14` z kolumną `available_from` — skaler BARIER i jednostka R.

    `available_from` to moment, od którego wartość wolno znać: początek doby
    następującej po tej, z której pochodzi. Kolumna istnieje po to, żeby
    połączenie z decyzjami było `join_asof`, a nie odejmowaniem dni.
    """
    d1 = daily_bars(h1, min_h1_bars)
    if d1.is_empty():
        return d1.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("atr_d1_14"),
            pl.lit(None, dtype=pl.Datetime("ms", "UTC")).alias("available_from"),
        )
    atr = wilder_atr(
        d1.get_column("bid_high").to_numpy(),
        d1.get_column("bid_low").to_numpy(),
        d1.get_column("bid_close").to_numpy(),
        period,
    )
    return d1.with_columns(
        pl.Series("atr_d1_14", atr),
        (pl.col("day") + pl.duration(days=1)).alias("available_from"),
    )


def attach_atr_d1(decisions: pl.DataFrame, d1: pl.DataFrame, *,
                  on: str = "ts") -> pl.DataFrame:
    """Dołącz do decyzji `atr_d1_14` z ostatniej doby ZAMKNIĘTEJ przed nimi.

    Decyzja o 2020-03-10 09:00 dostaje ATR doby 2020-03-09, bo doba 2020-03-10
    zamyka się dopiero o 2020-03-11 00:00. Za granicę odpowiada wyłącznie
    `available_from` z `atr_d1()`.
    """
    if decisions.is_empty():
        return decisions.with_columns(pl.lit(None, dtype=pl.Float64).alias("atr_d1_14"))
    # NaN, nie null: seria powstaje z numpy, więc `drop_nulls` by jej nie
    # ruszyło i rozgrzewka Wildera wyciekłaby do decyzji jako NaN.
    usable = (
        d1.filter(pl.col("atr_d1_14").is_not_null() & pl.col("atr_d1_14").is_not_nan())
        .select("available_from", "atr_d1_14")
        .sort("available_from")
    )
    if usable.is_empty():
        return decisions.with_columns(pl.lit(None, dtype=pl.Float64).alias("atr_d1_14"))
    return (
        decisions.sort(on)
        .join_asof(usable, left_on=on, right_on="available_from", strategy="backward")
        .drop("available_from")
    )
