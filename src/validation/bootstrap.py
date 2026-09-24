# PRZENIESIONE z market-quant (ADR-005). Odwolania "ADR-0NN", "PROJECT_SPEC"
# i "SPEC SS" w tym pliku dotycza logu decyzji TAMTEGO projektu, nie tego.
"""Block bootstrap expectancy po dniach (PROJECT_SPEC §6 pooling, §10.2 #6).

JEDNOSTKA: DZIEŃ, NIE TRANSAKCJA

Transakcje z tego samego dnia na sześciu parach dzielą czynnik USD i są
skorelowane; transakcje z sąsiednich dni dzielą okno wynikowe (~99%
nakładania). Bootstrap po obserwacjach traktowałby je jako niezależne
i zaniżałby błąd standardowy. Losujemy więc bloki `block_days` kolejnych
dni roboczych (kołowo) i w nich wszystkie transakcje wszystkich par.

Dni bez transakcji zostają w osi — blok 20 dni znaczy 20 dni kalendarza
handlowego, nie 20 dni z sygnałem.

Wejścia z weekendu (FX otwiera się w niedzielę ~22:00 UTC) należą do
sesji poniedziałkowej i są do niej przypisywane.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import polars as pl


@dataclass(frozen=True)
class BootstrapResult:
    expectancy: float        # średnie R na transakcję w oryginalnej próbie
    se: float                # odchylenie bootstrapowe
    t_stat: float            # expectancy / se
    ci_low: float            # percentylowy przedział 95%
    ci_high: float
    n_trades: int
    n_days: int
    n_reps: int


def business_day(ts: pl.Series) -> pl.Series:
    """Dzień roboczy, do którego liczy się wejście; weekend → poniedziałek.

    Blok bootstrapu to dzień, a sobota i niedziela nie mają własnych dni —
    wejście z weekendu należy do najbliższego poniedziałku. Ta sama oś
    musi obowiązywać wszędzie, gdzie porównujemy serie dzienne, więc
    reguła siedzi w jednym miejscu.
    """
    day = ts.dt.date()
    wd = day.dt.weekday()                       # 1 = pon ... 7 = nd
    return (pl.DataFrame({"d": day, "wd": wd})
            .select(pl.when(pl.col("wd") >= 6)
                    .then(pl.col("d") + pl.duration(days=8 - pl.col("wd")))
                    .otherwise(pl.col("d")).alias("d"))["d"])


def daily_totals(trades: pl.DataFrame, value: str = "r") -> tuple[np.ndarray, np.ndarray]:
    """(suma wartości, liczba transakcji) dla każdego dnia roboczego od
    pierwszego do ostatniego wejścia; dni puste = (0, 0)."""
    day = business_day(trades["ts"])
    per_day = (pl.DataFrame({"d": day, "v": trades[value]})
               .group_by("d").agg(pl.col("v").sum().alias("s"), pl.len().alias("n")))
    axis = pl.date_range(day.min(), day.max(), "1d", eager=True)
    axis = axis.filter(axis.dt.weekday() <= 5).alias("d").to_frame()
    full = axis.join(per_day, on="d", how="left").fill_null(0).sort("d")
    return full["s"].to_numpy().astype(float), full["n"].to_numpy().astype(float)


def daily_frames(frames: list[pl.DataFrame], value: str = "r"
                 ) -> tuple[list[dt.date], np.ndarray]:
    """(oś dni, macierz T × N): suma `value` na dzień, WSPÓLNA oś dla wszystkich.

    `daily_totals` buduje oś z własnego minimum i maksimum każdej ramki, więc
    dwie serie policzone osobno leżą na dwóch różnych osiach i nie da się ich
    odjąć. Tu oś jest sumą dni występujących w którejkolwiek ramce; dzień bez
    transakcji danej serii to zero, nie brak.
    """
    per_frame = []
    for f in frames:
        if f.height:
            per_frame.append(pl.DataFrame({"d": business_day(f["ts"]), "v": f[value]})
                             .group_by("d").agg(pl.col("v").sum().alias("s")))
        else:
            per_frame.append(pl.DataFrame(schema={"d": pl.Date, "s": pl.Float64}))

    days = sorted({d for f in per_frame for d in f["d"].to_list()})
    if not days:
        return [], np.zeros((0, len(frames)))
    axis = pl.DataFrame({"d": pl.Series(days, dtype=pl.Date)})
    cols = [axis.join(f, on="d", how="left").fill_null(0.0)["s"].to_numpy()
            for f in per_frame]
    return days, np.column_stack(cols).astype(float)


def block_indices(n_days: int, block_days: int, n_reps: int,
                  rng: np.random.Generator) -> np.ndarray:
    """Indeksy dni dla `n_reps` replikacji bootstrapu blokowego (kołowego).

    Wydzielone z `block_bootstrap_expectancy`, żeby dwie serie dało się
    przepróbkować TYMI SAMYMI blokami. Niezależne losowanie zerwałoby
    korelację dzienną między nimi — a przy porównaniu strategii z koszykiem
    (te same pary, te same dni) to ona decyduje o szerokości przedziału
    ufności różnicy (ADR-040 pkt 3).
    """
    if n_days < 2 * block_days:
        raise ValueError(f"{n_days} dni to za mało na bloki po {block_days}")
    n_blocks = -(-n_days // block_days)
    offsets = np.arange(block_days)
    starts = rng.integers(0, n_days, size=(n_reps, n_blocks))
    return ((starts[:, :, None] + offsets) % n_days).reshape(n_reps, -1)[:, :n_days]


def block_bootstrap_expectancy(trades: pl.DataFrame, block_days: int = 20,
                               n_reps: int = 10_000, seed: int = 0,
                               value: str = "r", chunk: int = 1000) -> BootstrapResult:
    if trades.height < 2:
        raise ValueError("za mało transakcji")
    sums, counts = daily_totals(trades, value)
    d = len(sums)
    if d < 2 * block_days:
        raise ValueError(f"{d} dni to za mało na bloki po {block_days}")

    rng = np.random.default_rng(seed)
    n_blocks = -(-d // block_days)
    offsets = np.arange(block_days)
    stats = np.empty(n_reps)
    for lo in range(0, n_reps, chunk):
        k = min(chunk, n_reps - lo)
        starts = rng.integers(0, d, size=(k, n_blocks))
        idx = ((starts[:, :, None] + offsets) % d).reshape(k, -1)[:, :d]
        n = counts[idx].sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            stats[lo:lo + k] = sums[idx].sum(axis=1) / n

    stats = stats[~np.isnan(stats)]
    exp = float(sums.sum() / counts.sum())
    se = float(stats.std(ddof=1))
    lo_ci, hi_ci = np.percentile(stats, [2.5, 97.5])
    return BootstrapResult(
        expectancy=exp, se=se, t_stat=exp / se if se > 0 else float("nan"),
        ci_low=float(lo_ci), ci_high=float(hi_ci),
        n_trades=int(counts.sum()), n_days=d, n_reps=len(stats),
    )


def day_row_groups(ts: pl.Series) -> tuple[list[dt.date], np.ndarray, np.ndarray]:
    """Wiersze pogrupowane po dniu roboczym, w postaci płaskiej.

    Zwraca (oś dni, `order`, `starts`), gdzie `order` to indeksy wierszy
    posortowane po dniu, a `starts` ma `len(days)+1` pozycji i wyznacza
    zakresy. Postać płaska, bo bootstrap losuje dni dziesięć tysięcy razy
    i lista tablic byłaby wąskim gardłem.
    """
    day = business_day(ts)
    codes = day.to_frame("d").with_row_index("i").sort("d")
    days = codes["d"].unique(maintain_order=True).to_list()
    order = codes["i"].to_numpy()
    counts = codes.group_by("d", maintain_order=True).len()["len"].to_numpy()
    starts = np.zeros(len(days) + 1, dtype=np.int64)
    np.cumsum(counts, out=starts[1:])
    return days, order, starts


def block_bootstrap_statistic(ts: pl.Series, stat_fn, block_days: int = 20,
                              n_reps: int = 10_000, seed: int = 0,
                              ) -> BootstrapResult:
    """Block bootstrap DOWOLNEJ statystyki, nie tylko średniej.

    `block_bootstrap_expectancy` sumuje po dniach, bo średnia jest liniowa —
    dla statystyki rangowej (Spearman) to nie działa: rangi liczą się na całej
    przepróbkowanej próbie, a nie sumują się po dniach. Tu więc losujemy bloki
    dni, sklejamy ICH WIERSZE i liczymy statystykę od nowa na każdej replikacji.

    `stat_fn(idx)` dostaje indeksy wierszy oryginalnej ramki i zwraca liczbę.
    Jednostka bloku jest ta sama co wszędzie: dzień roboczy, bo transakcje
    z sąsiednich dni dzielą okno wynikowe.
    """
    days, order, starts = day_row_groups(ts)
    d = len(days)
    if d < 2 * block_days:
        raise ValueError(f"{d} dni to za mało na bloki po {block_days}")

    rng = np.random.default_rng(seed)
    idx_days = block_indices(d, block_days, n_reps, rng)
    stats = np.empty(n_reps)
    for rep in range(n_reps):
        picked = idx_days[rep]
        rows = np.concatenate([order[starts[j]:starts[j + 1]] for j in picked])
        stats[rep] = stat_fn(rows)

    stats = stats[~np.isnan(stats)]
    point = float(stat_fn(np.arange(ts.len())))
    se = float(stats.std(ddof=1))
    lo_ci, hi_ci = np.percentile(stats, [2.5, 97.5])
    return BootstrapResult(
        expectancy=point, se=se, t_stat=point / se if se > 0 else float("nan"),
        ci_low=float(lo_ci), ci_high=float(hi_ci),
        n_trades=int(ts.len()), n_days=d, n_reps=len(stats),
    )
