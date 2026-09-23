"""Testy symulatora egzekucji.

Wszystkie przypadki są syntetyczne i mają odpowiedź znaną Z GÓRY. Na
prawdziwych tickach nie wiadomo, co *powinno* wyjść, więc nie da się nimi
sprawdzić poprawności — widać tylko, że coś zwraca.

Najważniejsze testy to te o kolejności barier: to tam siedzi cichy bias
optymistyczny, który zawyża każdy naiwny backtest.
"""
import datetime as dt

import polars as pl
import pytest

from src.execution.simulator import (
    CostModel, ExitReason, Side, simulate_trade,
)

UTC = dt.timezone.utc
T0 = dt.datetime(2020, 1, 2, 10, 0, tzinfo=UTC)
PIP = 1e-4

# Podłoga wyłączona tam, gdzie testujemy mechanikę barier, żeby koszt
# nie zaciemniał sprawdzanej wielkości.
NO_FLOOR = CostModel(pip=PIP, min_roundturn_pips=0.0,
                     entry_slippage_x_spread=0.0, stop_slippage_x_spread=0.0)


def m1(rows: list[dict]) -> pl.DataFrame:
    """rows: [{min, bid_o, bid_h, bid_l, bid_c, spread}]"""
    out = []
    for r in rows:
        s = r.get("spread", 2 * PIP)
        out.append({
            "ts": T0 + dt.timedelta(minutes=r["min"]),
            "bid_open": r["bid_o"], "bid_high": r["bid_h"],
            "bid_low": r["bid_l"], "bid_close": r["bid_c"],
            "ask_open": r["bid_o"] + s, "ask_high": r["bid_h"] + s,
            "ask_low": r["bid_l"] + s, "ask_close": r["bid_c"] + s,
            "spread_max": s, "spread_close": s,
            "n_ticks": 100,
        })
    return pl.DataFrame(out).with_columns(
        pl.col("ts").cast(pl.Datetime("ms", "UTC")),
        pl.col("n_ticks").cast(pl.UInt32),
    )


def ticks(prices_bid: list[float], spread: float = 2 * PIP) -> pl.DataFrame:
    return pl.DataFrame({
        "ts": [T0 + dt.timedelta(seconds=i) for i in range(len(prices_bid))],
        "bid": prices_bid,
        "ask": [p + spread for p in prices_bid],
    })


FLAT = dict(bid_o=1.1000, bid_h=1.1000, bid_l=1.1000, bid_c=1.1000)


# --- KOLEJNOŚĆ BARIER — rdzeń modułu ----------------------------------------

def test_both_barriers_in_one_bar_resolves_to_stop_without_ticks():
    """Bez ticków kolejność jest NIEZNANA — wariant pesymistyczny, nigdy TP."""
    bars = m1([{"min": 0, **FLAT},
               {"min": 1, "bid_o": 1.1000, "bid_h": 1.1050, "bid_l": 1.0950,
                "bid_c": 1.1000}])
    res = simulate_trade(Side.LONG, T0, sl=1.0960, tp=1.1040,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=NO_FLOOR, load_ticks=None)
    assert res.reason is ExitReason.STOP_LOSS
    assert res.ticks_scanned == 0


def test_both_barriers_resolved_on_ticks_can_give_take_profit():
    """Z tickami kolejność jest ustalana faktycznie — TP przed SL daje TP."""
    bars = m1([{"min": 0, **FLAT},
               {"min": 1, "bid_o": 1.1000, "bid_h": 1.1050, "bid_l": 1.0950,
                "bid_c": 1.1000}])
    # cena najpierw rośnie do TP, dopiero potem spada poniżej SL
    tk = ticks([1.1000, 1.1020, 1.1045, 1.1000, 1.0950])

    res = simulate_trade(Side.LONG, T0, sl=1.0960, tp=1.1040,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=NO_FLOOR,
                         load_ticks=lambda a, b: tk)
    assert res.reason is ExitReason.TAKE_PROFIT
    assert res.ticks_scanned > 0


def test_ticks_confirm_stop_when_stop_comes_first():
    bars = m1([{"min": 0, **FLAT},
               {"min": 1, "bid_o": 1.1000, "bid_h": 1.1050, "bid_l": 1.0950,
                "bid_c": 1.1000}])
    tk = ticks([1.1000, 1.0955, 1.1045])   # SL pierwszy

    res = simulate_trade(Side.LONG, T0, sl=1.0960, tp=1.1040,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=NO_FLOOR, load_ticks=lambda a, b: tk)
    assert res.reason is ExitReason.STOP_LOSS


# --- STRONY RYNKU: long na bidzie, short na asku ----------------------------

def test_long_stop_triggers_on_bid_not_ask():
    """Long wychodzi po bidzie — szeroki spread nie chroni przed stopem."""
    bars = m1([{"min": 0, **FLAT},
               {"min": 1, "bid_o": 1.1000, "bid_h": 1.1000, "bid_l": 1.0950,
                "bid_c": 1.0960, "spread": 10 * PIP}])
    res = simulate_trade(Side.LONG, T0, sl=1.0970, tp=1.2000,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.STOP_LOSS


def test_spread_spike_stops_short_intrabar_but_leaves_long_untouched():
    """Rdzeń asymetrii: ta sama świeca, dwa przeciwne wyniki.

    Bid stoi w miejscu, ask rośnie przez rozszerzenie spreadu. Short ma
    stop na asku i wylatuje; long ma stop na bidzie i nie jest ruszony.
    Backtest na cenach mid nie widzi tego w ogóle.
    """
    bar = {"min": 1, "bid_o": 1.1000, "bid_h": 1.1015, "bid_l": 1.1000,
           "bid_c": 1.1000, "spread": 10 * PIP}      # ask: 1.1010 -> 1.1025
    bars = m1([{"min": 0, **FLAT}, bar])
    kw = dict(time_barrier=T0 + dt.timedelta(minutes=5), m1=bars, cost=NO_FLOOR)

    short = simulate_trade(Side.SHORT, T0, sl=1.1020, tp=1.0900, **kw)
    long_ = simulate_trade(Side.LONG, T0, sl=1.0980, tp=1.1200, **kw)

    assert short.reason is ExitReason.STOP_LOSS, "skok spreadu nie ruszył shorta"
    assert long_.reason is not ExitReason.STOP_LOSS, "long nie powinien być ruszony"


def test_spread_gap_beyond_stop_fills_at_market_not_at_stop_level():
    """Gdy spread rozjedzie się ponad stop JUŻ NA OTWARCIU bara, nie ma
    fillu po poziomie stopu — jest po cenie rynkowej, czyli gorzej."""
    bars = m1([{"min": 0, **FLAT},
               {"min": 1, "bid_o": 1.1000, "bid_h": 1.1000, "bid_l": 1.1000,
                "bid_c": 1.1000, "spread": 30 * PIP}])     # ask_open = 1.1030
    res = simulate_trade(Side.SHORT, T0, sl=1.1020, tp=1.0900,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.GAP_STOP
    assert res.exit.price == pytest.approx(1.1030)    # ask_open, nie poziom stopu
    assert res.r < -1.0, "luka spreadowa nie może dawać straty <= 1 R"


# --- LUKI -------------------------------------------------------------------

def test_gap_through_stop_fills_at_open_not_at_stop_level():
    """Stop nie chroni przez lukę — strata przekracza 1 R."""
    bars = m1([{"min": 0, **FLAT},
               {"min": 1, "bid_o": 1.0800, "bid_h": 1.0810, "bid_l": 1.0790,
                "bid_c": 1.0800}])
    res = simulate_trade(Side.LONG, T0, sl=1.0950, tp=1.1100,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.GAP_STOP
    assert res.exit.price == pytest.approx(1.0800)     # cena otwarcia
    assert res.r < -1.0, f"luka dała tylko {res.r:.2f} R — stop jakby chronił"


def test_gap_through_target_fills_at_open_too():
    bars = m1([{"min": 0, **FLAT},
               {"min": 1, "bid_o": 1.1200, "bid_h": 1.1210, "bid_l": 1.1190,
                "bid_c": 1.1200}])
    res = simulate_trade(Side.LONG, T0, sl=1.0950, tp=1.1100,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.GAP_TARGET
    assert res.exit.price == pytest.approx(1.1200)


# --- BARIERA CZASOWA --------------------------------------------------------

def test_time_barrier_exits_at_last_close():
    bars = m1([{"min": i, **FLAT} for i in range(6)])
    tb = T0 + dt.timedelta(minutes=5)
    res = simulate_trade(Side.LONG, T0, sl=1.0900, tp=1.1100,
                         time_barrier=tb, m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.TIME_BARRIER
    assert res.exit.price == pytest.approx(1.1000)


def test_missing_data_is_flagged_not_silently_treated_as_time_exit():
    """Urwane dane to inny wynik niż dotrwanie do bariery czasowej."""
    bars = m1([{"min": i, **FLAT} for i in range(2)])
    res = simulate_trade(Side.LONG, T0, sl=1.0900, tp=1.1100,
                         time_barrier=T0 + dt.timedelta(hours=5),
                         m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.NO_DATA


def at(t: dt.datetime) -> int:
    """Minuty od T0 — dla helpera `m1`."""
    return int((t - T0).total_seconds() // 60)


def test_sunday_entry_with_barrier_after_friday_close_is_a_time_exit():
    """ADR-026: niedziela 22:00 + 10 dni rob. = piątek 22:00; latem ostatni
    bar tygodnia to 20:59, więc rynek jest już zamknięty."""
    from src.data.timeaxis import add_business_days
    sun = dt.datetime(2020, 7, 5, 22, 0, tzinfo=UTC)
    tb = add_business_days(sun, 10)
    assert tb == dt.datetime(2020, 7, 17, 22, 0, tzinfo=UTC)
    fri_close = dt.datetime(2020, 7, 17, 20, 59, tzinfo=UTC)
    last = dict(bid_o=1.1010, bid_h=1.1010, bid_l=1.1010, bid_c=1.1010, spread=5 * PIP)
    bars = m1([{"min": at(sun), **FLAT}, {"min": at(sun) + 1, **FLAT},
               {"min": at(fri_close) - 1, **FLAT}, {"min": at(fri_close), **last}])
    res = simulate_trade(Side.LONG, sun, sl=1.0900, tp=1.1100,
                         time_barrier=tb, m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.TIME_BARRIER
    assert res.exit.time == fri_close
    assert res.exit.price == pytest.approx(1.1010)
    assert res.exit.spread == pytest.approx(5 * PIP)


def test_short_time_exit_after_close_uses_ask():
    fri_close = dt.datetime(2020, 1, 3, 20, 59, tzinfo=UTC)
    bars = m1([{"min": 0, **FLAT}, {"min": at(fri_close), **FLAT}])
    res = simulate_trade(Side.SHORT, T0, sl=1.1100, tp=1.0900,
                         time_barrier=dt.datetime(2020, 1, 3, 22, 0, tzinfo=UTC),
                         m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.TIME_BARRIER
    assert res.exit.price == pytest.approx(1.1000 + 2 * PIP)


def test_friday_outage_before_close_is_still_no_data():
    """Dane urwane w piątek o 10:00 to awaria, nie weekend."""
    bars = m1([{"min": 0, **FLAT}, {"min": at(dt.datetime(2020, 1, 3, 10, tzinfo=UTC)), **FLAT}])
    res = simulate_trade(Side.LONG, T0, sl=1.0900, tp=1.1100,
                         time_barrier=dt.datetime(2020, 1, 3, 22, 0, tzinfo=UTC),
                         m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.NO_DATA


def test_missing_monday_after_weekend_is_no_data():
    fri_close = dt.datetime(2020, 1, 3, 20, 59, tzinfo=UTC)
    bars = m1([{"min": 0, **FLAT}, {"min": at(fri_close), **FLAT}])
    res = simulate_trade(Side.LONG, T0, sl=1.0900, tp=1.1100,
                         time_barrier=dt.datetime(2020, 1, 6, 10, 0, tzinfo=UTC),
                         m1=bars, cost=NO_FLOOR)
    assert res.reason is ExitReason.NO_DATA


@pytest.mark.parametrize("start, end, closed", [
    # weekend
    ((2020, 1, 3, 21, 0), (2020, 1, 5, 21, 0), True),
    ((2020, 1, 3, 21, 0), (2020, 1, 3, 22, 0), True),
    ((2020, 1, 3, 12, 0), (2020, 1, 3, 22, 0), False),      # piątek w sesji
    ((2020, 1, 3, 21, 0), (2020, 1, 6, 9, 0), False),       # poniedziałek rano
    ((2020, 1, 3, 21, 0), (2020, 1, 6, 0, 0), True),        # do północy niedziela/pon.
    ((2020, 1, 1, 23, 0), (2020, 1, 2, 1, 0), False),       # czwartek w nocy
    # święta
    ((2020, 12, 24, 18, 0), (2020, 12, 25, 22, 0), True),   # wigilia (czw.) → 25.12
    ((2020, 12, 24, 10, 0), (2020, 12, 25, 22, 0), False),  # wigilia rano to sesja
    ((2020, 12, 24, 18, 0), (2020, 12, 28, 10, 0), False),  # poniedziałek 28.12 handlowy
    ((2021, 12, 24, 18, 0), (2021, 12, 26, 12, 0), True),   # wigilia w piątek
    ((2020, 12, 31, 18, 0), (2021, 1, 1, 23, 0), True),     # sylwester → 1.01
])
def test_market_closed_between(start, end, closed):
    from src.execution.simulator import market_closed_between
    assert market_closed_between(dt.datetime(*start, tzinfo=UTC),
                                 dt.datetime(*end, tzinfo=UTC)) is closed


def test_no_data_at_decision_time_returns_none():
    bars = m1([{"min": 30, **FLAT}])
    assert simulate_trade(Side.LONG, T0, sl=1.09, tp=1.11,
                          time_barrier=T0 + dt.timedelta(hours=1),
                          m1=bars, cost=NO_FLOOR) is None


# --- KOSZTY -----------------------------------------------------------------

def test_cost_floor_applies_when_real_spread_is_tighter():
    """Surowy spread Dukascopy jest węższy niż detaliczny — ADR-024."""
    cost = CostModel(pip=PIP, min_roundturn_pips=1.5,
                     entry_slippage_x_spread=0.0, stop_slippage_x_spread=0.0)
    bars = m1([{"min": i, **FLAT, "spread": 0.3 * PIP} for i in range(6)])
    res = simulate_trade(Side.LONG, T0, sl=1.0900, tp=1.1100,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=cost)
    assert res.cost == pytest.approx(1.5 * PIP)        # podłoga, nie 0.3


@pytest.mark.parametrize("spread_pips", [0.3, 4.0])
def test_spread_is_charged_once_not_twice(spread_pips):
    """Płaski rynek: jedyną stratą jest efektywny koszt max(spread, podłoga).

    Spread siedzi już w cenach fillów (wejście po ask, wyjście po bid);
    odjęcie go drugi raz w `cost` zawyżało koszt o cały spread."""
    cost = CostModel(pip=PIP, min_roundturn_pips=1.5,
                     entry_slippage_x_spread=0.0, stop_slippage_x_spread=0.0)
    bars = m1([{"min": i, **FLAT, "spread": spread_pips * PIP} for i in range(6)])
    res = simulate_trade(Side.LONG, T0, sl=1.0900, tp=1.1100,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=cost)
    effective = max(spread_pips, 1.5) * PIP
    assert res.net == pytest.approx(-effective)
    assert res.cost == pytest.approx(effective)


def test_stop_slippage_is_adverse_and_in_the_price():
    cost = CostModel(pip=PIP, min_roundturn_pips=0.0,
                     entry_slippage_x_spread=0.0, stop_slippage_x_spread=1.0)
    bars = m1([{"min": 0, **FLAT},
               {"min": 1, "bid_o": 1.1000, "bid_h": 1.1000, "bid_l": 1.0940,
                "bid_c": 1.0950, "spread": 2 * PIP}])
    res = simulate_trade(Side.LONG, T0, sl=1.0950, tp=1.1100,
                         time_barrier=T0 + dt.timedelta(minutes=5),
                         m1=bars, cost=cost)
    # fill poniżej poziomu stopu o pełny spread
    assert res.exit.price == pytest.approx(1.0950 - 2 * PIP)


def test_entry_is_at_ask_for_long_and_bid_for_short():
    bars = m1([{"min": i, **FLAT, "spread": 4 * PIP} for i in range(6)])
    kw = dict(time_barrier=T0 + dt.timedelta(minutes=5), m1=bars, cost=NO_FLOOR)
    lo = simulate_trade(Side.LONG, T0, sl=1.0900, tp=1.1100, **kw)
    sh = simulate_trade(Side.SHORT, T0, sl=1.1100, tp=1.0900, **kw)
    assert lo.entry.price == pytest.approx(1.1000 + 4 * PIP)   # ask
    assert sh.entry.price == pytest.approx(1.1000)             # bid


# --- WYSZUKIWANIE PIERWSZEJ BARIERY (wektorowe) -----------------------------
#
# `_first_event` zastąpiło pętlę po barach; jedyne, co ma robić, to wskazać
# TEN SAM bar, który wskazałby naiwny skan. Sprawdzane na losowych ścieżkach,
# bo tu nie chodzi o znaną z góry odpowiedź, tylko o równoważność dwóch
# implementacji tego samego warunku.


def _naive_first_event(side, window, sl, tp):
    long = side is Side.LONG
    lo_col, hi_col, op_col = ("bid_low", "bid_high", "bid_open") if long else \
                             ("ask_low", "ask_high", "ask_open")
    for i, bar in enumerate(window.iter_rows(named=True)):
        op, lo, hi = bar[op_col], bar[lo_col], bar[hi_col]
        if long and (op <= sl or op >= tp or lo <= sl or hi >= tp):
            return i
        if not long and (op >= sl or op <= tp or hi >= sl or lo <= tp):
            return i
    return None


def _random_walk(rng, n: int) -> list[dict]:
    """Bary M1 z lukami: otwarcie potrafi wypaść poza zakres poprzedniego bara."""
    rows, price = [], 1.1000
    for i in range(n):
        price += rng.normal(0, 3 * PIP)
        hi = price + abs(rng.normal(0, 2 * PIP))
        lo = price - abs(rng.normal(0, 2 * PIP))
        rows.append({"min": i, "bid_o": price, "bid_h": hi, "bid_l": lo,
                     "bid_c": price + rng.normal(0, PIP), "spread": 2 * PIP})
    return rows


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_vectorised_first_event_matches_a_naive_scan(side):
    import numpy as np

    from src.execution.simulator import _first_event

    rng = np.random.default_rng(20260920)
    checked = set()
    for _ in range(200):
        window = m1(_random_walk(rng, 40))
        entry = 1.1000
        dist = rng.uniform(2, 30) * PIP
        sl, tp = (entry - dist, entry + dist) if side is Side.LONG else \
                 (entry + dist, entry - dist)
        got, want = _first_event(side, window, sl, tp), _naive_first_event(side, window, sl, tp)
        assert got == want
        checked.add(want is None)
    assert checked == {True, False}, "losowanie ma dawać i trafienia, i brak trafień"


def test_unsorted_bars_are_rejected_instead_of_silently_mis_sliced():
    bars = m1([{"min": 0, **FLAT}, {"min": 2, **FLAT}, {"min": 1, **FLAT}])
    with pytest.raises(ValueError, match="posortowane"):
        simulate_trade(Side.LONG, T0, sl=1.0900, tp=1.1100,
                       time_barrier=T0 + dt.timedelta(minutes=5), m1=bars, cost=NO_FLOOR)


# --- BRAK PODGLĄDANIA PRZYSZŁOŚCI -------------------------------------------
#
# PRZYWRÓCONE (dług M01). Oryginały w `market-quant` szpiegowały, jaką ramkę
# warstwa etykiet podaje symulatorowi, więc zależały od `triple_barrier.py`,
# którego nie przenieśliśmy — i razem z nim wypadły z pakietu.
#
# Tutaj ta sama własność jest sprawdzana OBSERWOWALNIE: psujemy ceny poza
# oknem transakcji i żądamy, żeby wynik nie drgnął. To jest mocniejsze niż
# podglądanie wywołania — szpieg pilnuje, co dostał symulator, a to pilnuje,
# czego symulator UŻYŁ. `simulate_trade` tnie okno sam (`slice_window`), więc
# własność należy do niego, nie do warstwy etykiet.

PRICE_COLS = ("bid_open", "bid_high", "bid_low", "bid_close",
              "ask_open", "ask_high", "ask_low", "ask_close")


def _corrupt(bars: pl.DataFrame, *, after=None, before=None,
             value: float = 77.0) -> pl.DataFrame:
    """Zastąp ceny poza oknem wartością absurdalną, zachowując oś czasu."""
    cond = None
    if after is not None:
        cond = pl.col("ts") > after
    if before is not None:
        c = pl.col("ts") < before
        cond = c if cond is None else (cond | c)
    return bars.with_columns(
        [pl.when(cond).then(pl.lit(value)).otherwise(pl.col(c)).alias(c)
         for c in PRICE_COLS]
    )


def _sweep(side, rng, n=150, bars_per_case=120, barrier_minutes=60):
    """Losowe przebiegi z pokryciem różnych powodów wyjścia."""
    for _ in range(n):
        bars = m1(_random_walk(rng, bars_per_case))
        dist = rng.uniform(2, 40) * PIP
        entry = 1.1000
        sl, tp = (entry - dist, entry + dist) if side is Side.LONG else \
                 (entry + dist, entry - dist)
        yield bars, sl, tp, T0 + dt.timedelta(minutes=barrier_minutes)


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_simulator_sees_only_the_trade_window(side):
    """Ceny PO barierze czasowej nie mogą wpłynąć na nic.

    Upadek tego testu oznacza, że wynik zależy od przyszłości — czyli
    backtest zna odpowiedź, zanim ją policzy.
    """
    import numpy as np
    rng = np.random.default_rng(20260923)
    reasons = set()
    for bars, sl, tp, t1 in _sweep(side, rng):
        base = simulate_trade(side, T0, sl, tp, t1, bars, NO_FLOOR)
        blind = simulate_trade(side, T0, sl, tp, t1, _corrupt(bars, after=t1), NO_FLOOR)
        assert base == blind
        reasons.add(base.reason)
    assert len(reasons) >= 2, "przebieg ma pokryć więcej niż jeden powód wyjścia"


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_simulator_ignores_bars_before_the_decision(side):
    """Historia sprzed decyzji też nie ma prawa wejść do wyniku.

    Symetryczna strona tej samej własności: okno jest domknięte z obu stron.
    """
    import numpy as np
    rng = np.random.default_rng(20260924)
    # Decyzja 15 minut po początku ramki: bary wcześniejsze istnieją, ale
    # leżą poza oknem i nie mają prawa niczego zmienić.
    decision = T0 + dt.timedelta(minutes=15)
    for bars, sl, tp, t1 in _sweep(side, rng, n=80):
        base = simulate_trade(side, decision, sl, tp, t1, bars, NO_FLOOR)
        blind = simulate_trade(side, decision, sl, tp, t1,
                               _corrupt(bars, before=decision), NO_FLOOR)
        assert base == blind


@pytest.mark.parametrize("side", [Side.LONG, Side.SHORT])
def test_windowed_labels_match_simulation_on_full_history(side):
    """Wycięcie okna przed wywołaniem nie zmienia wyniku, tylko koszt obliczeń.

    Skrypty badawcze (M02, M03) tną M1 do `[decyzja, bariera]` zanim wołają
    symulator. Gdyby to wycięcie cokolwiek zmieniało, wyniki z tych skryptów
    nie byłyby porównywalne z przebiegiem na pełnej historii.
    """
    import numpy as np
    from src.data.resample import slice_window
    rng = np.random.default_rng(20260925)
    reasons = set()
    for bars, sl, tp, t1 in _sweep(side, rng):
        full = simulate_trade(side, T0, sl, tp, t1, bars, NO_FLOOR)
        windowed = simulate_trade(side, T0, sl, tp, t1,
                                  slice_window(bars, T0, t1), NO_FLOOR)
        assert full == windowed
        reasons.add(full.reason)
    assert len(reasons) >= 2
