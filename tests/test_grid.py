"""Siatka decyzyjna — KIEDY zapada decyzja i kiedy zamyka się jej okno.

Ten moduł jest wspólny dla M02, M03 i przyszłego trialu, więc błąd w nim
skaża wszystko naraz. Dwa testy są tu ważniejsze od reszty i oba dotyczą
przesunięcia o JEDEN bar:

  * cena odniesienia pochodzi z bara ZAMKNIĘTEGO przed decyzją,
  * cena wyjścia pochodzi z bara ZAMKNIĘTEGO przed barierą czasową.

Jeden bar w złą stronę to look-ahead, którego nie widać w żadnym wyniku —
widać tylko, że wynik jest lepszy.

Dane syntetyczne: ceny są ustawione tak, żeby poprawna odpowiedź była
znana z konstrukcji.
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from src.data.resample import BAR_SCHEMA
from src.research.grid import decision_grid, in_session, session_hours, with_horizon

UTC = dt.timezone.utc
SPREAD = 0.0001
HIGH, LOW = 1.1010, 1.0990          # stały zakres → atr_d1 = 0,0020 dokładnie


def h1_frame(rows: list[tuple[dt.datetime, float]]) -> pl.DataFrame:
    """Bary H1 o stałym zakresie; zmienia się wyłącznie `bid_close`."""
    ts = [t for t, _ in rows]
    cl = [c for _, c in rows]
    return pl.DataFrame(
        {
            "ts": ts,
            "bid_open": cl, "bid_high": [HIGH] * len(ts),
            "bid_low": [LOW] * len(ts), "bid_close": cl,
            "ask_open": [c + SPREAD for c in cl], "ask_high": [HIGH + SPREAD] * len(ts),
            "ask_low": [LOW + SPREAD] * len(ts), "ask_close": [c + SPREAD for c in cl],
            "spread_max": [SPREAD] * len(ts), "spread_close": [SPREAD] * len(ts),
            "n_ticks": [10] * len(ts),
        },
        schema=BAR_SCHEMA,
    )


def series(n_days: int, close=lambda i: 1.1000, start=dt.datetime(2020, 1, 1, tzinfo=UTC)):
    """`n_days` pełnych dób po 24 bary; `close(i)` po numerze bara."""
    rows, i = [], 0
    for d in range(n_days):
        for h in range(24):
            rows.append((start + dt.timedelta(days=d, hours=h), close(i)))
            i += 1
    return rows


def build(rows, *, first_decision, lookback=3, period=2, min_h1=12):
    return decision_grid(h1_frame(rows), first_decision=first_decision,
                         lookback_bars=lookback, atr_period=period,
                         min_h1_bars=min_h1)


# --- momenty decyzji -------------------------------------------------------

def test_decision_time_is_one_hour_after_the_bar_label():
    """Bar 09:00 zamyka się o 10:00 — decyzja zapada wtedy, nie wcześniej."""
    dec, _, _ = build(series(10), first_decision=dt.datetime(2020, 1, 5, tzinfo=UTC))
    row = dec.row(0, named=True)
    assert row["ts_decision"] == row["bar_ts"] + dt.timedelta(hours=1)
    assert (dec["ts_decision"] - dec["bar_ts"]).unique().to_list() == [
        dt.timedelta(hours=1)
    ]


def test_reference_price_comes_from_the_closed_bar_not_the_current_one():
    """Najważniejszy test modułu: cena odniesienia nie może być z przyszłości.

    `bid_close` skacze na barze o etykiecie 2020-01-06 09:00. Decyzja
    o 09:00 tego dnia widzi jeszcze bar 08:00, czyli cenę SPRZED skoku.
    Decyzja o 10:00 widzi bar 09:00, czyli cenę po skoku.
    """
    jump_bar = dt.datetime(2020, 1, 6, 9, tzinfo=UTC)
    rows = [(t, 9.0 if t == jump_bar else 1.1000) for t, _ in series(10)]
    dec, _, _ = build(rows, first_decision=dt.datetime(2020, 1, 5, tzinfo=UTC))

    at_09 = dec.filter(pl.col("ts_decision") == jump_bar)
    at_10 = dec.filter(pl.col("ts_decision") == jump_bar + dt.timedelta(hours=1))
    assert at_09["ref_price"][0] == pytest.approx(1.1000)
    assert at_10["ref_price"][0] == pytest.approx(9.0)


def test_decisions_before_first_decision_are_dropped():
    first = dt.datetime(2020, 1, 6, tzinfo=UTC)
    dec, _, _ = build(series(12), first_decision=first)
    assert dec["ts_decision"].min() >= first


def test_lookback_requirement_drops_the_earliest_bars():
    """Cecha nieokreślona = brak decyzji. Liczymy, czy JEST określona."""
    rows = series(12)
    early = dt.datetime(2020, 1, 1, tzinfo=UTC)
    dec, _, diag = build(rows, first_decision=early, lookback=100)
    # 100 barów rozgrzewki odpada, a dodatkowo ATR H1 potrzebuje swojego okna.
    assert dec["bar_ts"].min() >= rows[100][0]
    assert diag["h1_bars_total"] == len(rows)


def test_rows_without_defined_atr_d1_are_dropped():
    """Decyzje z okresu, w którym ATR dzienny jeszcze nie istnieje, odpadają."""
    dec, _, diag = build(series(12), first_decision=dt.datetime(2020, 1, 1, tzinfo=UTC),
                         period=5)
    assert diag["decisions_atr_d1_defined"] < diag["decisions_feature_defined"]
    assert dec["atr_d1_14"].is_not_null().all()
    assert (dec["atr_d1_14"] > 0).all()


# --- bariera czasowa i okno wynikowe ---------------------------------------

def test_time_barrier_uses_business_days():
    dec, prices, _ = build(series(30), first_decision=dt.datetime(2020, 1, 6, tzinfo=UTC))
    out = with_horizon(dec, prices, 3, segment_end=dt.datetime(2020, 2, 1, tzinfo=UTC))
    row = out.row(0, named=True)
    # 2020-01-06 to poniedziałek; +3 dni robocze = czwartek 09.01.
    assert row["ts_decision"] == dt.datetime(2020, 1, 6, 0, tzinfo=UTC)
    assert row["t1"] == dt.datetime(2020, 1, 9, 0, tzinfo=UTC)


def test_exit_price_comes_from_the_bar_closed_before_the_barrier():
    """Drugi test na przesunięcie o jeden bar — tym razem na wyjściu.

    `bid_close` skacze dokładnie na barze o etykiecie równej `t1`. Ten bar
    zamyka się godzinę PO barierze, więc okno nie ma prawa go zobaczyć.
    """
    dec, prices, _ = build(series(30), first_decision=dt.datetime(2020, 1, 6, tzinfo=UTC))
    out = with_horizon(dec, prices, 3, segment_end=dt.datetime(2020, 2, 1, tzinfo=UTC))
    t1 = out["t1"][0]

    rows = [(t, 9.0 if t == t1 else 1.1000) for t, _ in series(30)]
    dec2, prices2, _ = build(rows, first_decision=dt.datetime(2020, 1, 6, tzinfo=UTC))
    out2 = with_horizon(dec2, prices2, 3, segment_end=dt.datetime(2020, 2, 1, tzinfo=UTC))

    first = out2.filter(pl.col("t1") == t1).row(0, named=True)
    assert first["exit_bar"] == t1 - dt.timedelta(hours=1)
    assert first["exit_price"] == pytest.approx(1.1000)   # skok niewidoczny


def test_windows_past_the_segment_end_are_cut():
    dec, prices, _ = build(series(40), first_decision=dt.datetime(2020, 1, 6, tzinfo=UTC))
    end = dt.datetime(2020, 1, 20, tzinfo=UTC)
    out = with_horizon(dec, prices, 10, segment_end=end)
    assert out["t1"].max() <= end
    assert out.height < dec.height


def test_forward_return_is_expressed_in_atr_units():
    """`fwd_atr` = (wyjście − odniesienie) / atr_d1_14, z dokładnymi liczbami.

    Przy stałym zakresie dobowym `atr_d1_14` wynosi dokładnie 0,0020,
    więc wartość da się sprawdzić na kalkulatorze, a nie tylko „że wraca".
    """
    dec, prices, _ = build(series(30), first_decision=dt.datetime(2020, 1, 6, tzinfo=UTC))
    out = with_horizon(dec, prices, 3, segment_end=dt.datetime(2020, 2, 1, tzinfo=UTC))
    row = out.row(0, named=True)
    assert row["atr_d1_14"] == pytest.approx(0.0020)
    expected = (row["exit_price"] - row["ref_price"]) / 0.0020
    assert row["fwd_atr"] == pytest.approx(expected)
    assert row["fwd_atr"] == pytest.approx(0.0)      # cena płaska → zero


def test_forward_return_sign_follows_the_price():
    up = [(t, 1.1000 + i * 1e-6) for i, (t, _) in enumerate(series(30))]
    dec, prices, _ = build(up, first_decision=dt.datetime(2020, 1, 6, tzinfo=UTC))
    out = with_horizon(dec, prices, 3, segment_end=dt.datetime(2020, 2, 1, tzinfo=UTC))
    assert (out["fwd_atr"] > 0).all()


# --- sesja -----------------------------------------------------------------

def test_session_end_hour_is_exclusive():
    dec, _, _ = build(series(20), first_decision=dt.datetime(2020, 1, 6, tzinfo=UTC))
    prim = in_session(dec, 8, 22)
    hours = sorted(prim["ts_decision"].dt.hour().unique().to_list())
    assert hours == list(range(8, 22))
    assert 22 not in hours


def test_session_hours_read_from_config():
    cfg = {"validation": {"sessions": {"primary": {"start": "08:00", "end": "22:00"}}}}
    assert session_hours(cfg) == (8, 22)
