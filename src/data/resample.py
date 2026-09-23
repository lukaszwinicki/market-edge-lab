# PRZENIESIONE z market-quant (ADR-005). Odwolania "ADR-0NN", "PROJECT_SPEC"
# i "SPEC SS" w tym pliku dotycza logu decyzji TAMTEGO projektu, nie tego.
"""Agregacja ticków do barów M1 i H1.

KONWENCJA ETYKIETOWANIA — źródło klasycznego look-ahead, więc wprost:

    Bar o etykiecie T obejmuje ticki z przedziału [T, T + okres).
    Bar o etykiecie 09:00 (H1) zamyka się dopiero o 10:00:00.

    Decyzja podejmowana "na zamknięciu świecy H1 o 10:00" może więc
    korzystać WYŁĄCZNIE z bara o etykiecie 09:00 i wcześniejszych.
    Użycie bara 10:00 oznacza czytanie przyszłości.

    Pomocnik `last_closed_bar()` zwraca poprawną etykietę dla danego
    momentu decyzji — używać go zamiast ręcznej arytmetyki.

ZASADY:

* Bid i ask agregowane **osobno**. Cena mid nie powstaje nigdzie.
* Okresy bez ticków **nie dają bara**. Bez wypełniania, bez interpolacji,
  bez bara zerowego — luka ma pozostać widoczna dla raportu jakości.
* `spread_max` jest ważniejszy od średniej: koszt ponosi się w najgorszym
  momencie bara, nie w typowym.
* Wolumen Dukascopy jest pominięty świadomie. W spot FX nie istnieje
  prawdziwy wolumen — brokerzy raportują licznik ticków własnego feedu,
  nieporównywalny między źródłami. `n_ticks` pełni rolę proxy płynności.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl

from .dukascopy import TickBlock

UTC = dt.timezone.utc

# Kolejność kolumn w wynikowych barach — stała, żeby Parquet z różnych
# przebiegów dawał się łączyć bez niespodzianek.
BAR_SCHEMA: dict[str, pl.DataType] = {
    "ts": pl.Datetime("ms", "UTC"),
    "bid_open": pl.Float64,
    "bid_high": pl.Float64,
    "bid_low": pl.Float64,
    "bid_close": pl.Float64,
    "ask_open": pl.Float64,
    "ask_high": pl.Float64,
    "ask_low": pl.Float64,
    "ask_close": pl.Float64,
    "spread_max": pl.Float64,
    "spread_close": pl.Float64,
    "n_ticks": pl.UInt32,
}

FREQ_M1 = "1m"
FREQ_H1 = "1h"


def ticks_to_frame(blocks: list[TickBlock]) -> pl.DataFrame:
    """Złóż bloki godzinowe w jedną ramkę ticków, posortowaną po czasie."""
    blocks = [b for b in blocks if len(b)]
    if not blocks:
        return pl.DataFrame(
            schema={"ts": pl.Datetime("ms", "UTC"), "bid": pl.Float64, "ask": pl.Float64}
        )

    df = pl.DataFrame({
        "ts": np.concatenate([b.ts for b in blocks]),
        "bid": np.concatenate([b.bid for b in blocks]),
        "ask": np.concatenate([b.ask for b in blocks]),
    }).with_columns(pl.col("ts").cast(pl.Datetime("ms")).dt.replace_time_zone("UTC"))

    # Ticki bywają duplikowane co do milisekundy; sortowanie stabilne
    # zachowuje kolejność z pliku, która jest kolejnością rynkową.
    return df.sort("ts", maintain_order=True)


def bars_from_ticks(ticks: pl.DataFrame, freq: str) -> pl.DataFrame:
    """Zagreguj ticki do barów o zadanym okresie.

    Okresy bez ticków są pomijane — luka zostaje luką.
    """
    if ticks.is_empty():
        return pl.DataFrame(schema=BAR_SCHEMA)

    bars = (
        ticks.with_columns((pl.col("ask") - pl.col("bid")).alias("spread"))
        .group_by_dynamic("ts", every=freq, closed="left", label="left")
        .agg(
            pl.col("bid").first().alias("bid_open"),
            pl.col("bid").max().alias("bid_high"),
            pl.col("bid").min().alias("bid_low"),
            pl.col("bid").last().alias("bid_close"),
            pl.col("ask").first().alias("ask_open"),
            pl.col("ask").max().alias("ask_high"),
            pl.col("ask").min().alias("ask_low"),
            pl.col("ask").last().alias("ask_close"),
            pl.col("spread").max().alias("spread_max"),
            pl.col("spread").last().alias("spread_close"),
            pl.len().cast(pl.UInt32).alias("n_ticks"),
        )
        .sort("ts")
    )
    return bars.select(list(BAR_SCHEMA))


def aggregate_bars(bars: pl.DataFrame, freq: str) -> pl.DataFrame:
    """Zagreguj gotowe bary do dłuższego okresu (np. M1 -> H1).

    Wynik jest identyczny z agregacją prosto z ticków — pilnuje tego test
    `test_h1_from_m1_equals_h1_from_ticks`.
    """
    if bars.is_empty():
        return pl.DataFrame(schema=BAR_SCHEMA)

    out = (
        bars.sort("ts")
        .group_by_dynamic("ts", every=freq, closed="left", label="left")
        .agg(
            pl.col("bid_open").first(),
            pl.col("bid_high").max(),
            pl.col("bid_low").min(),
            pl.col("bid_close").last(),
            pl.col("ask_open").first(),
            pl.col("ask_high").max(),
            pl.col("ask_low").min(),
            pl.col("ask_close").last(),
            pl.col("spread_max").max(),
            pl.col("spread_close").last(),
            pl.col("n_ticks").sum(),
        )
        .sort("ts")
    )
    return out.select(list(BAR_SCHEMA))


def last_closed_bar(decision_time: dt.datetime, freq_seconds: int) -> dt.datetime:
    """Etykieta ostatniego bara ZAMKNIĘTEGO przed momentem decyzji.

    Jedyny poprawny sposób wyboru bara do podjęcia decyzji. Ręczna
    arytmetyka na znacznikach czasu jest w tym miejscu głównym źródłem
    look-ahead, więc cały kod sygnału ma korzystać z tej funkcji.

        >>> last_closed_bar(dt.datetime(2020,1,2,10,0, tzinfo=UTC), 3600)
        datetime.datetime(2020, 1, 2, 9, 0, tzinfo=datetime.timezone.utc)

    O 10:00:00 bar 10:00 dopiero się zaczyna — ostatni kompletny to 09:00.
    """
    if decision_time.tzinfo is None:
        raise ValueError("decision_time musi być tz-aware (UTC)")
    t = decision_time.astimezone(UTC)
    epoch = int(t.timestamp())
    start_of_current = epoch - (epoch % freq_seconds)
    return dt.datetime.fromtimestamp(start_of_current - freq_seconds, tz=UTC)


def decision_time_for_bar(bar_label: dt.datetime, freq_seconds: int) -> dt.datetime:
    """Najwcześniejszy moment decyzji, w którym bar `bar_label` jest zamknięty.

    Odwrotność `last_closed_bar()`: bar 09:00 (H1) -> decyzja 10:00.
    Gwarantuje `last_closed_bar(decision_time_for_bar(t, f), f) == t`.
    """
    if bar_label.tzinfo is None:
        raise ValueError("bar_label musi być tz-aware (UTC)")
    epoch = int(bar_label.astimezone(UTC).timestamp())
    if epoch % freq_seconds:
        raise ValueError(f"{bar_label} nie jest etykietą bara o okresie {freq_seconds}s")
    return dt.datetime.fromtimestamp(epoch + freq_seconds, tz=UTC)


def slice_window(bars: pl.DataFrame, start: dt.datetime, end: dt.datetime) -> pl.DataFrame:
    """Bary o etykiecie w [start, end], obie granice włącznie.

    Wyszukiwanie binarne zamiast `filter`: filtr przechodzi całą ramkę,
    a przy latach M1 (miliony wierszy) × tysiącach transakcji × setkach
    powtórzeń kontroli losowej to dominujący koszt. `bars` MUSI być
    posortowane po `ts` — wynik to widok (slice), bez kopiowania.
    """
    ts = bars.get_column("ts")
    i = ts.search_sorted(start, side="left")
    j = ts.search_sorted(end, side="right")
    return bars.slice(i, max(0, j - i))


def validate_bars(bars: pl.DataFrame) -> None:
    """Niezmienniki, których naruszenie oznacza błąd w pipeline, nie na rynku."""
    if bars.is_empty():
        return

    if bars["ts"].is_duplicated().any():
        raise ValueError("zduplikowane etykiety barów")
    if not bars["ts"].is_sorted():
        raise ValueError("bary nie są posortowane po czasie")

    checks = {
        "ask < bid (spread ujemny)": (pl.col("ask_close") < pl.col("bid_close")),
        "bid_high < bid_low": (pl.col("bid_high") < pl.col("bid_low")),
        "ask_high < ask_low": (pl.col("ask_high") < pl.col("ask_low")),
        "bid_open poza [low, high]": (
            (pl.col("bid_open") > pl.col("bid_high")) | (pl.col("bid_open") < pl.col("bid_low"))
        ),
        "bid_close poza [low, high]": (
            (pl.col("bid_close") > pl.col("bid_high")) | (pl.col("bid_close") < pl.col("bid_low"))
        ),
        "n_ticks == 0": (pl.col("n_ticks") == 0),
    }
    for label, expr in checks.items():
        n = bars.filter(expr).height
        if n:
            raise ValueError(f"{n} barów narusza niezmiennik: {label}")
