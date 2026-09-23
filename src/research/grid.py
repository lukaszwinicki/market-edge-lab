"""Siatka decyzyjna — KIEDY zapada decyzja, nigdy JAKA.

Moduł odpowiada na jedno pytanie: w których momentach eksperyment mógłby
podjąć decyzję, i kiedy zamyka się okno wynikowe każdej z nich. Nie liczy
żadnej cechy, nie zna kierunku i nie wie, jaka hipoteza go wywołała.

Dlatego może być wspólny dla audytu mocy (M02), kontroli losowej (M03)
i przyszłego trialu — i dlatego musi być wspólny. Dwie kopie tej samej
siatki w dwóch skryptach to dwie różne próby udające jedną.

CECHA OKREŚLONA ≠ CECHA POLICZONA

`decision_grid` sprawdza, czy cecha JEST OKREŚLONA: czy istnieje dość
wcześniejszych barów i czy normalizatory są dodatnie. Wartości ani znaku
nie liczy nikt. Ta granica jest celowa — pomiar geometrii próby nie może
wymagać obejrzenia sygnału, bo obejrzenie sygnału przed prerejestrowanym
uruchomieniem zapala próbę w liczniku DSR.

ZNACZNIKI CZASU

Etykieta bara to POCZĄTEK przedziału, więc bar H1 o etykiecie 09:00 zamyka
się o 10:00 i dopiero wtedy wolno go użyć. Przejście bar → moment decyzji
robi `decision_time_for_bar()`, a powrót przy barierze czasowej —
`last_closed_bar()`. Ręcznej arytmetyki na znacznikach nie ma tu ani razu
i nie może być: to jest najkrótsza droga do look-ahead o jeden bar.
"""

from __future__ import annotations

import datetime as dt

import polars as pl

from ..data.resample import decision_time_for_bar, last_closed_bar
from ..data.timeaxis import add_business_days
from ..features.volatility import atr_d1, atr_h1, attach_atr_d1

UTC = dt.timezone.utc
H1_SECONDS = 3600


def map_ts(col: str, fn) -> pl.Expr:
    """Zastosuj funkcję osi czasu do kolumny znaczników.

    `datetime` Pythona ma rozdzielczość mikrosekundową, bary —
    milisekundową, więc wynik wraca w „us" i jest rzutowany z powrotem.
    Opakowane, bo alternatywą jest arytmetyka na znacznikach wprost
    w wyrażeniu.
    """
    return (
        pl.col(col)
        .map_elements(fn, return_dtype=pl.Datetime("us", "UTC"))
        .cast(pl.Datetime("ms", "UTC"))
    )


def decision_grid(h1: pl.DataFrame, *, first_decision: dt.datetime,
                  lookback_bars: int, atr_period: int, min_h1_bars: int,
                  ) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """Momenty decyzji i ceny odniesienia dla jednej pary.

    `h1` musi obejmować rozgrzewkę: `lookback_bars` barów przed
    `first_decision` plus okno ATR. Zwraca (siatka, ceny H1, diagnostyka).

    Kolumny siatki: `bar_ts` (ostatni bar zamknięty), `ref_price` (jego
    `bid_close` — cena znana w momencie decyzji), `ts_decision`,
    `atr_d1_14`.
    """
    h1 = atr_h1(h1, atr_period)
    d1 = atr_d1(h1, min_h1_bars, atr_period)

    dec = (
        h1.with_row_index("bar_i")
        .select("bar_i", "ts", "bid_close", "atr_h1_14")
        .filter(
            (pl.col("bar_i") >= lookback_bars)
            & pl.col("atr_h1_14").is_not_nan()
            & pl.col("atr_h1_14").is_not_null()
            & (pl.col("atr_h1_14") > 0)
        )
        .with_columns(
            map_ts("ts", lambda t: decision_time_for_bar(t, H1_SECONDS))
            .alias("ts_decision")
        )
        .rename({"ts": "bar_ts", "bid_close": "ref_price"})
        .filter(pl.col("ts_decision") >= first_decision)
    )

    n_before_atr = dec.height
    dec = attach_atr_d1(dec, d1, on="ts_decision").filter(
        pl.col("atr_d1_14").is_not_null()
        & pl.col("atr_d1_14").is_not_nan()
        & (pl.col("atr_d1_14") > 0)
    )

    prices = h1.select(pl.col("ts").alias("px_ts"),
                       pl.col("bid_close").alias("exit_price"))
    diag = {
        "h1_bars_total": h1.height,
        "decisions_feature_defined": n_before_atr,
        "decisions_atr_d1_defined": dec.height,
        "dropped_no_atr_d1": n_before_atr - dec.height,
    }
    return dec, prices, diag


def with_horizon(dec: pl.DataFrame, prices: pl.DataFrame, h: int, *,
                 segment_end: dt.datetime) -> pl.DataFrame:
    """Dołóż barierę czasową `t1`, cenę wyjścia i zwrot w przód.

    Okna wychodzące poza `segment_end` są odcinane. Decyzja z 28.12.2021
    przy h = 10 d rozstrzyga się w styczniu 2022, czyli w segmencie OOS —
    a ten ma reżim ograniczonych uruchomień. Odcięcie jest decyzją
    wywołującego, nie właściwością danych, więc granica jest parametrem.

    `fwd_atr` to zwrot przez okno w jednostkach `atr_d1_14` (target A):
    wielkość bezkierunkowa, policzona z cen, bez udziału jakiejkolwiek cechy.
    """
    out = (
        dec.with_columns(
            map_ts("ts_decision", lambda t: add_business_days(t, h)).alias("t1")
        )
        .filter(pl.col("t1") <= segment_end)
    )
    # Cena wyjścia z ostatniego bara ZAMKNIĘTEGO przed barierą. Bar
    # o etykiecie równej t1 zamyka się godzinę później — użycie go to
    # look-ahead o jeden bar.
    out = (
        out.with_columns(
            map_ts("t1", lambda t: last_closed_bar(t, H1_SECONDS)).alias("exit_bar")
        )
        .sort("exit_bar")
        .join_asof(prices.sort("px_ts"), left_on="exit_bar", right_on="px_ts",
                   strategy="backward")
        .sort("ts_decision")
    )
    return out.with_columns(
        ((pl.col("exit_price") - pl.col("ref_price")) / pl.col("atr_d1_14"))
        .alias("fwd_atr")
    )


def in_session(df: pl.DataFrame, start_hour: int, end_hour: int) -> pl.DataFrame:
    """Decyzje z godzin [start_hour, end_hour) UTC.

    Koniec wyłączny: sesja „08:00–22:00" to 14 decyzji na dobę handlową,
    ostatnia o 21:00. Bar 22:00 zamyka się po sesji.
    """
    hour = pl.col("ts_decision").dt.hour()
    return df.filter((hour >= start_hour) & (hour < end_hour))


def session_hours(cfg: dict) -> tuple[int, int]:
    """Granice sesji primary z konfiguracji, jako godziny całkowite."""
    s = cfg["validation"]["sessions"]["primary"]
    return (int(str(s["start"]).split(":")[0]), int(str(s["end"]).split(":")[0]))
