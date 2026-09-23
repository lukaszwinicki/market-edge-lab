"""Odegranie wejść — jedyna droga od siatki decyzyjnej do wyniku w R.

Siatka mówi, KIEDY zapada decyzja (`research/grid.py`). Ten moduł mówi, co
się dzieje potem: gdzie stoją bariery, jak liczy się ryzyko i co zwraca
symulator. Kierunek przychodzi z zewnątrz, w kolumnie — moduł nie wie i nie
ma prawa wiedzieć, skąd się wziął.

Dzięki temu jedna i ta sama ścieżka obsługuje kontrolę losową, kontrolę
z zasianym błędem i przyszły trial. Gdyby każdy przebieg miał własną pętlę,
różnice między nimi byłyby nie do odróżnienia od różnic w wyniku.

BARIERY I JEDNOSTKA R

SL i TP są wielokrotnościami `atr_d1_14`, odmierzanymi od ceny odniesienia
znanej w momencie decyzji (`ref_price` — zamknięcie ostatniego zamkniętego
bara). Faktyczny dystans stopu liczy symulator od ceny WEJŚCIA, nie od ceny
odniesienia, bo wejście pada po gorszej stronie rynku i z poślizgiem.
Dlatego `risk` w wyniku jest nieco większy od `sl_mult × atr_d1_14` —
i tak ma być.

CZEGO TU NIE MA

Żadnej cechy, żadnego progu, żadnej warstwy portfelowej (ADR-002). Wejście
jest odgrywane dla każdego wiersza, który dostanie — filtrowanie należy do
wywołującego i ma być widoczne w jego kodzie, nie schowane tutaj.
"""

from __future__ import annotations

import polars as pl

from ..data.resample import slice_window
from ..execution.simulator import CostModel, Side, simulate_trade

RESULT_COLS = ("r", "net", "cost", "slippage", "risk", "reason", "exit_ts")


def barriers(ref_price: float, atr: float, side: Side, *,
             sl_mult: float, tp_mult: float) -> tuple[float, float]:
    """(SL, TP) w cenie, odmierzone od ceny odniesienia."""
    if side is Side.LONG:
        return ref_price - sl_mult * atr, ref_price + tp_mult * atr
    return ref_price + sl_mult * atr, ref_price - tp_mult * atr


def simulate_entries(entries: pl.DataFrame, m1: pl.DataFrame, cost: CostModel,
                     *, sl_mult: float, tp_mult: float,
                     side_col: str = "side") -> pl.DataFrame:
    """Odegraj wejścia na barach M1 i dopisz wynik do ich kolumn.

    `entries` musi mieć `ts_decision`, `t1`, `ref_price`, `atr_d1_14`
    i kolumnę kierunku (`side_col`, wartości „long"/„short"). Pozostałe
    kolumny przechodzą bez zmian, żeby dało się je później pogrupować.

    Wiersze, dla których symulator zwraca `None` (brak danych w momencie
    decyzji), **wypadają**. To poprawny wynik, nie błąd — ale jest ich
    zwykle ułamek procenta, więc wywołujący ma obowiązek porównać wysokość
    ramki wejściowej i wyjściowej.
    """
    if entries.is_empty():
        return entries.with_columns(
            [pl.lit(None).alias(c) for c in RESULT_COLS])

    rows = []
    for row in entries.iter_rows(named=True):
        side = Side.LONG if row[side_col] == "long" else Side.SHORT
        sl, tp = barriers(row["ref_price"], row["atr_d1_14"], side,
                          sl_mult=sl_mult, tp_mult=tp_mult)
        window = slice_window(m1, row["ts_decision"], row["t1"])
        res = simulate_trade(side, row["ts_decision"], sl, tp, row["t1"],
                             window, cost)
        if res is None:
            continue
        rows.append({
            **row,
            "r": res.r, "net": res.net, "cost": res.cost,
            "slippage": res.slippage, "risk": res.risk,
            "reason": res.reason.value, "exit_ts": res.exit.time,
        })
    return pl.DataFrame(rows)


def both_directions(entries: pl.DataFrame) -> pl.DataFrame:
    """Zduplikuj wejścia na long i short, zachowując wszystkie kolumny.

    Pod hipotezą zerową rozkład wyniku nie zależy od kierunku, więc para
    long+short z TEGO SAMEGO momentu pozwala policzyć wynik dowolnej reguły
    kierunkowej bez powtarzania symulacji: wystarczy wiedzieć, która strona
    była trafna.
    """
    return pl.concat([
        entries.with_columns(pl.lit(side).alias("side"))
        for side in ("long", "short")
    ])
