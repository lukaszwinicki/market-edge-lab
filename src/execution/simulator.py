# PRZENIESIONE z market-quant (ADR-005). Odwolania "ADR-0NN", "PROJECT_SPEC"
# i "SPEC SS" w tym pliku dotycza logu decyzji TAMTEGO projektu, nie tego.
"""Symulator egzekucji — najważniejszy moduł projektu.

Asymetria, która uzasadnia priorytet: błąd w signal engine daje zły sygnał,
który zobaczysz w wynikach. Błąd tutaj daje **fałszywą pewność, że zły
sygnał jest dobry** — i nie zobaczysz go nigdy.

STRONY RYNKU

    Long:   wejście po ASK, wyjście po BID.
            SL trafiony gdy BID spadnie do poziomu.
            TP trafiony gdy BID wzrośnie do poziomu.

    Short:  wejście po BID, wyjście po ASK.
            SL trafiony gdy ASK wzrośnie do poziomu.
            TP trafiony gdy ASK spadnie do poziomu.

Z tego wynika asymetria rozszerzeń spreadu: skok spreadu rozjeżdża bid
i ask w przeciwne strony, więc ta sama szpilka wyrzuca długą pozycję
i nie rusza krótkiej (albo odwrotnie). Backtest na cenach mid tego nie
widzi w ogóle.

KOLEJNOŚĆ BARIER

Gdy w jednym barze cena dotyka SL i TP, z OHLC **nie da się** ustalić,
co nastąpiło pierwsze. Naiwna implementacja zakłada korzystną kolejność
i daje cichy, systematyczny bias optymistyczny.

Rozstrzygamy dwustopniowo:

1. Przebieg zgrubny po barach M1. Jeśli w danym barze osiągalna jest
   tylko jedna bariera — odpowiedź jest jednoznaczna, ticki niepotrzebne.
2. Dopiero gdy obie bariery mieszczą się w zakresie tego samego bara M1,
   schodzimy do ticków i ustalamy kolejność faktycznie.

Gdy ticki są niedostępne, stosujemy wariant PESYMISTYCZNY (SL pierwszy).
Nigdy optymistyczny.

LUKI

Jeśli bar otwiera się już za barierą (luka weekendowa, wznowienie po
przerwie), fill następuje po cenie OTWARCIA, a nie po poziomie bariery.
Stop nie chroni przez lukę — to jest realna strata ponad zakładane ryzyko.

BARIERA CZASOWA W CZASIE ZAMKNIĘTEGO RYNKU (ADR-026)

Wejście w niedzielę wieczorem + 10 dni roboczych = piątek wieczorem, już
po zamknięciu. Brak barów przed barierą, bo rynek był zamknięty, to wynik
ZNANY: wyjście po zamknięciu ostatniego bara. `NO_DATA` zostaje tylko dla
braków w czasie, gdy rynek powinien działać — awarie mają być widoczne.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Callable

import numpy as np
import polars as pl

from ..data.quality import MARKET_HOLIDAYS
from ..data.resample import slice_window

UTC = dt.timezone.utc


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


class ExitReason(str, Enum):
    STOP_LOSS = "sl"
    TAKE_PROFIT = "tp"
    TIME_BARRIER = "time"
    GAP_STOP = "gap_sl"          # luka przeskoczyła stop — strata > 1 R
    GAP_TARGET = "gap_tp"
    NO_DATA = "no_data"          # brak danych do końca horyzontu


@dataclass(frozen=True)
class CostModel:
    """Koszty transakcyjne. Broker-agnostyczny — patrz ADR-024."""

    pip: float
    min_roundturn_pips: float = 1.5      # podłoga detaliczna
    entry_slippage_x_spread: float = 0.5
    stop_slippage_x_spread: float = 1.0  # asymetryczne: stop realizuje się w ruchu

    @property
    def floor(self) -> float:
        return self.min_roundturn_pips * self.pip


@dataclass(frozen=True)
class Fill:
    time: dt.datetime
    price: float
    spread: float


@dataclass(frozen=True)
class TradeResult:
    side: Side
    entry: Fill
    exit: Fill
    reason: ExitReason
    gross: float          # wynik z cen fillów — już po spreadzie i poślizgu
    cost: float           # efektywny koszt max(spread, podłoga); poślizg jest w cenie
    net: float            # gross - dopłata do podłogi (spread NIE drugi raz)
    risk: float           # |entry_intent - sl|, mianownik dla R
    ticks_scanned: int    # 0 = rozstrzygnięte na barach, >0 = schodziliśmy do ticków
    slippage: float = 0.0  # poślizg zawarty w cenach fillów, wejście + wyjście

    @property
    def r(self) -> float:
        return self.net / self.risk if self.risk else 0.0


def simulate_trade(
    side: Side,
    decision_time: dt.datetime,
    sl: float,
    tp: float,
    time_barrier: dt.datetime,
    m1: pl.DataFrame,
    cost: CostModel,
    load_ticks: Callable[[dt.datetime, dt.datetime], pl.DataFrame] | None = None,
) -> TradeResult | None:
    """Odegraj jedną transakcję na barach M1, schodząc do ticków gdy trzeba.

    `m1` musi obejmować przedział [decision_time, time_barrier].
    `load_ticks(start, end)` jest wołane WYŁĄCZNIE dla barów niejednoznacznych.
    Zwraca None, gdy w momencie decyzji nie ma danych — to poprawny wynik
    (NO TRADE), nie błąd.
    """
    # Wycinek przez wyszukiwanie binarne: `filter` przechodziłby całe okno
    # (~14 tys. barów M1) przy KAŻDEJ transakcji — po wektoryzacji barier
    # to był dominujący koszt. Wyszukiwanie binarne na nieposortowanych barach
    # dałoby cichy błędny wycinek, więc sprawdzamy (0,005 ms na 14 tys. barów).
    if not m1.get_column("ts").is_sorted():
        raise ValueError("bary M1 muszą być posortowane po ts")
    window = slice_window(m1, decision_time, time_barrier)
    if window.is_empty():
        return None

    first = window.row(0, named=True)
    if first["ts"] > decision_time + dt.timedelta(minutes=1):
        return None   # brak danych w momencie decyzji

    entry = _entry_fill(side, first, cost)
    risk = abs(entry.price - sl)
    if risk <= 0:
        raise ValueError("dystans stopu równy zeru")

    ex_fill, reason, scanned = _find_exit(
        side, window, sl, tp, time_barrier, cost, load_ticks
    )

    gross = (ex_fill.price - entry.price) if side is Side.LONG else (entry.price - ex_fill.price)
    implied, top_up = _costs(entry, ex_fill, cost)

    return TradeResult(
        side=side, entry=entry, exit=ex_fill, reason=reason,
        gross=gross, cost=implied + top_up, net=gross - top_up,
        risk=risk, ticks_scanned=scanned,
        slippage=_slippage(reason, entry, ex_fill, cost),
    )


def _slippage(reason: ExitReason, entry: Fill, exit_: Fill, cost: CostModel) -> float:
    """Poślizg zawarty w cenach fillów, w jednostkach ceny.

    Raportowany osobno WYŁĄCZNIE po to, żeby dało się przeliczyć wynik przy
    2× i 3× kosztach (§9). Od `gross` nie odejmujemy go tu drugi raz — on
    już siedzi w cenie (`_entry_fill`, `_stop_fill`).

    Wyjście ma poślizg tylko na stopie. TP wymaga pełnego przekroczenia
    poziomu, a luka rozlicza się po cenie otwarcia, która sama jest już
    gorsza od bariery — dokładanie tam poślizgu byłoby liczeniem dwa razy.
    """
    at_entry = cost.entry_slippage_x_spread * entry.spread
    at_exit = (cost.stop_slippage_x_spread * exit_.spread
               if reason is ExitReason.STOP_LOSS else 0.0)
    return at_entry + at_exit


def _entry_fill(side: Side, bar: dict, cost: CostModel) -> Fill:
    """Wejście po otwarciu pierwszego bara, po niekorzystnej stronie rynku."""
    spread = bar["ask_open"] - bar["bid_open"]
    slip = cost.entry_slippage_x_spread * spread
    price = bar["ask_open"] + slip if side is Side.LONG else bar["bid_open"] - slip
    return Fill(time=bar["ts"], price=price, spread=spread)


def _first_event(side: Side, window: pl.DataFrame, sl: float, tp: float) -> int | None:
    """Indeks pierwszego bara dotykającego którejkolwiek bariery albo None.

    Szukanie wektorowe: pętla Pythona po ~14 tys. barów M1 była wąskim
    gardłem (ok. 30 ms na transakcję). Warunki są te same co przy
    rozstrzyganiu bara — patrz `_find_exit`; tu tylko ustalamy, KTÓRY bar
    jest pierwszy, bo dopiero on wymaga cen i ewentualnie ticków.
    """
    long = side is Side.LONG
    lo_col, hi_col, op_col = ("bid_low", "bid_high", "bid_open") if long else \
                             ("ask_low", "ask_high", "ask_open")
    op = window.get_column(op_col).to_numpy()
    lo = window.get_column(lo_col).to_numpy()
    hi = window.get_column(hi_col).to_numpy()
    if long:
        event = (op <= sl) | (op >= tp) | (lo <= sl) | (hi >= tp)
    else:
        event = (op >= sl) | (op <= tp) | (hi >= sl) | (lo <= tp)
    hit = np.flatnonzero(event)
    return int(hit[0]) if hit.size else None


def _find_exit(side, window, sl, tp, time_barrier, cost, load_ticks):
    """Pierwsza dotknięta bariera. Zwraca (Fill, ExitReason, liczba_ticków)."""
    long = side is Side.LONG
    # Kolumny, po których pada decyzja — patrz nagłówek modułu.
    lo_col, hi_col, op_col = ("bid_low", "bid_high", "bid_open") if long else \
                             ("ask_low", "ask_high", "ask_open")

    i = _first_event(side, window, sl, tp)
    if i is not None:
        bar = window.row(i, named=True)
        op, lo, hi = bar[op_col], bar[lo_col], bar[hi_col]
        spread = bar["spread_max"]

        # --- luka: bar otwiera się już za barierą -------------------------
        # Luka: fill po cenie OTWARCIA, nie po poziomie bariery. Stop nie
        # chroni przez lukę — strata przekracza zakładane 1 R i tak ma być.
        if (op <= sl) if long else (op >= sl):
            return Fill(bar["ts"], op, spread), ExitReason.GAP_STOP, 0
        if (op >= tp) if long else (op <= tp):
            return Fill(bar["ts"], op, spread), ExitReason.GAP_TARGET, 0

        hit_sl = lo <= sl if long else hi >= sl
        hit_tp = hi >= tp if long else lo <= tp

        if hit_sl and hit_tp:
            # Niejednoznaczne — dopiero tutaj ticki mają sens.
            resolved, scanned = _resolve_on_ticks(
                side, bar, sl, tp, load_ticks
            )
            if resolved is ExitReason.TAKE_PROFIT:
                return Fill(bar["ts"], tp, spread), resolved, scanned
            return _stop_fill(side, bar["ts"], sl, spread, cost), resolved, scanned

        if hit_sl:
            return _stop_fill(side, bar["ts"], sl, spread, cost), ExitReason.STOP_LOSS, 0
        return Fill(bar["ts"], tp, spread), ExitReason.TAKE_PROFIT, 0

    # --- bariera czasowa ---------------------------------------------------
    last = window.row(-1, named=True)
    if (last["ts"] < time_barrier - dt.timedelta(minutes=1)
            and not market_closed_between(last["ts"] + dt.timedelta(minutes=1), time_barrier)):
        reason = ExitReason.NO_DATA
    else:
        reason = ExitReason.TIME_BARRIER
    close_col = "bid_close" if long else "ask_close"
    return Fill(last["ts"], last[close_col], last["spread_close"]), reason, 0


# Najwcześniejszy moment, od którego brak barów w piątek (wigilię, sylwestra)
# może być zamknięciem, a nie awarią. Piątek: NY 17:00 = 21:00/22:00 UTC,
# w wigilię i sylwestra rynek kończy wcześniej (NY ~13:00 = 18:00 UTC).
# Godzina tolerancji na cienki handel przed zamknięciem.
FRIDAY_TAIL_FROM = dt.time(20, 0)
EVE_TAIL_FROM = dt.time(17, 0)


def _closed_day(d: dt.date) -> bool:
    return d.weekday() >= 5 or (d.month, d.day) in MARKET_HOLIDAYS


def _closes_after(t: dt.datetime) -> bool:
    """Brak barów od `t` do północy to zamknięcie rynku, nie awaria."""
    d = t.date()
    if _closed_day(d):
        return True
    nxt = d + dt.timedelta(days=1)
    if (nxt.month, nxt.day) in MARKET_HOLIDAYS:        # wigilia, sylwester
        return t.time() >= EVE_TAIL_FROM
    return d.weekday() == 4 and t.time() >= FRIDAY_TAIL_FROM


def market_closed_between(start: dt.datetime, end: dt.datetime) -> bool:
    """Czy CAŁY przedział [start, end) wypada w zamknięciu rynku.

    Zamknięcie = weekend oraz 25.12 i 1.01, łącznie z ogonem dnia przed
    nimi (piątek od 20:00 UTC, wigilia i sylwester od 17:00). Kalendarz celowo
    minimalny — ten sam co w raporcie jakości; każdy inny brak danych
    jest podejrzany.
    """
    first, last = start.date(), end.date()
    if not _closes_after(start):
        return False
    d = first + dt.timedelta(days=1)
    while d <= last:
        # Dzień bariery: zamknięty, albo bariera wypada tuż o północy
        # otwierającej ten dzień (przedział kończy się przed nim).
        if not _closed_day(d) and not (d == last and end.time() == dt.time(0)):
            return False
        d += dt.timedelta(days=1)
    return True


def _stop_fill(side: Side, ts, level: float, spread: float, cost: CostModel) -> Fill:
    """Fill na stopie — poślizg w cenie, zawsze w niekorzystną stronę.

    Stop realizuje się dokładnie wtedy, gdy rynek się porusza, więc poślizg
    jest asymetryczny: na stopie zawsze przeciw nam, na TP nigdy za nas.
    Poślizg wchodzi w CENĘ, nie w koszt — inaczej byłby liczony dwa razy.
    """
    slip = cost.stop_slippage_x_spread * spread
    price = level - slip if side is Side.LONG else level + slip
    return Fill(ts, price, spread)


def _resolve_on_ticks(side, bar, sl, tp, load_ticks) -> tuple[ExitReason, int]:
    """Ustal, która bariera padła pierwsza. Bez ticków — pesymistycznie."""
    if load_ticks is None:
        return ExitReason.STOP_LOSS, 0

    start = bar["ts"]
    ticks = load_ticks(start, start + dt.timedelta(minutes=1))
    if ticks.is_empty():
        return ExitReason.STOP_LOSS, 0

    long = side is Side.LONG
    col = "bid" if long else "ask"
    px = ticks[col].to_numpy()

    for p in px:
        if long:
            if p <= sl:
                return ExitReason.STOP_LOSS, len(px)
            if p >= tp:
                return ExitReason.TAKE_PROFIT, len(px)
        else:
            if p >= sl:
                return ExitReason.STOP_LOSS, len(px)
            if p <= tp:
                return ExitReason.TAKE_PROFIT, len(px)

    # Ticki nie potwierdziły żadnej bariery mimo zakresu bara — pesymistycznie.
    return ExitReason.STOP_LOSS, len(px)


def _costs(entry: Fill, exit_: Fill, cost: CostModel) -> tuple[float, float]:
    """(spread zawarty w cenach fillów, dopłata do podłogi detalicznej).

    Ceny fillów już zawierają spread (wejście po gorszej stronie, wyjście
    po gorszej stronie), więc `gross` jest już po spreadzie — od wyniku
    odejmujemy WYŁĄCZNIE dopłatę. Implikowany spread to pół spreadu
    z wejścia plus pół z wyjścia. Poślizg też siedzi w cenie fillu
    (`_stop_fill`) i nie jest tu doliczany.

    Efektywny koszt (ADR-024) = implied + dopłata = max(implied, podłoga).
    Podłoga wiąże na majorsach prawie zawsze.
    """
    implied = 0.5 * entry.spread + 0.5 * exit_.spread
    return implied, max(0.0, cost.floor - implied)
