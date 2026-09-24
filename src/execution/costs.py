"""Złożenie pełnego modelu kosztu — symulator plus finansowanie.

`CostModel` w `execution/simulator.py` zna spread, podłogę i poślizg. Nie zna
marży swapu i **nie ma jej znać** (ADR-016). Ten moduł dokłada brakujący człon
na wyniku symulacji, i jest jedynym miejscem, w którym wynik warstwy B
zamienia się w liczbę nadającą się do raportowania.

DLACZEGO PO FAKCIE, A NIE W `CostModel`

Trzy powody, każdy wystarczający:

1. **Marża jest OSIĄ, nie punktem.** Prerejestracja T003 wymaga trzech
   wartości (0,5% / 1% / 2%) z jednego przebiegu. Wartość wpisana w
   `CostModel` wymusiłaby trzy symulacje tej samej próby i trzy różne wyniki
   `TradeResult`, z których dwa byłyby do wyrzucenia.
2. **Dokładność jest identyczna.** Koszt finansowania zależy wyłącznie od
   ceny, dystansu stopu i czasów wejścia/wyjścia — wszystkie są w
   `TradeResult`. Odjęcie po fakcie daje tę samą liczbę co odjęcie w środku,
   co do bitu.
3. **Symulator jest zweryfikowany co do bitu** wobec `market-quant` (M01)
   i skalibrowany przez M03 i M04. Dołożenie mu członu kosztu unieważnia obie
   weryfikacje w zamian za nic.

CZEGO TEN MODUŁ PILNUJE

Nie da się dostać net R warstwy B bez podania marży. Nie ma wartości
domyślnej i nie ma funkcji zwracającej „wynik bez swapu" — bo M03 pokazał,
że pominięty człon jest wart 0,42× całego modelowanego kosztu przy h = 3 d
i 1,32× przy h = 10 d. Pominięcie ma wymagać skasowania kolumny, nie
zapomnienia o niej.
"""

from __future__ import annotations

import polars as pl

from .swap import swap_margin_r

SWAP_PREFIX = "swap_r_"
NET_PREFIX = "r_net_"


def swap_column(margin: float) -> str:
    return f"{SWAP_PREFIX}{margin}"


def net_column(margin: float) -> str:
    return f"{NET_PREFIX}{margin}"


def attach_swap(trades: pl.DataFrame, margins: tuple[float, ...], *,
                triple_on_wednesday: bool = True,
                price_col: str = "ref_price", entry_col: str = "ts_decision",
                exit_col: str = "exit_ts") -> pl.DataFrame:
    """Dołóż `swap_r_<m>` i `r_net_<m>` dla każdej marży z osi.

    `r_net_<m> = r - swap_r_<m>` — wynik po PEŁNYM koszcie. Kolumna `r`
    zostaje nietknięta, żeby dało się zobaczyć, ile kosztuje samo
    finansowanie; raportowaniu podlega `r_net_<m>`.
    """
    if not margins:
        raise ValueError("oś marży nie może być pusta — patrz ADR-016")
    for col in (price_col, entry_col, exit_col, "risk", "r"):
        if col not in trades.columns:
            raise ValueError(f"brak kolumny {col!r} wymaganej do policzenia swapu")
    if trades.is_empty():
        return trades.with_columns([
            pl.lit(None, dtype=pl.Float64).alias(c)
            for m in margins for c in (swap_column(m), net_column(m))
        ])

    price = trades.get_column(price_col).to_list()
    risk = trades.get_column("risk").to_list()
    entry = trades.get_column(entry_col).to_list()
    exit_ = trades.get_column(exit_col).to_list()

    out = trades
    for m in margins:
        vals = [
            swap_margin_r(p, k, a, b, m, triple_on_wednesday=triple_on_wednesday)
            for p, k, a, b in zip(price, risk, entry, exit_)
        ]
        out = out.with_columns(pl.Series(swap_column(m), vals))
        out = out.with_columns(
            (pl.col("r") - pl.col(swap_column(m))).alias(net_column(m)))
    return out


def margins_from_config(cfg: dict) -> tuple[float, ...]:
    """Oś marży z konfiguracji. Brak sekcji to błąd, nie pusta oś."""
    try:
        margins = cfg["costs"]["swap"]["margin_sensitivity"]
    except KeyError as e:
        raise ValueError("konfiguracja nie ma costs.swap.margin_sensitivity") from e
    if not margins:
        raise ValueError("oś marży jest pusta")
    return tuple(float(m) for m in margins)


def reportable(trades: pl.DataFrame, margins: tuple[float, ...]) -> None:
    """Rzuć, jeżeli ramka nie nadaje się do raportowania z warstwy B.

    Wołane przez raportujący kod PRZED policzeniem czegokolwiek. Istnieje po
    to, żeby pominięcie swapu było błędem, a nie przeoczeniem — M03 wykrył je
    w gotowym module, który miał testy i wyglądał na kompletny.
    """
    missing = [net_column(m) for m in margins
               if net_column(m) not in trades.columns]
    if missing:
        raise ValueError(
            f"brak kolumn net po pełnym koszcie: {missing}. "
            "Warstwa B nie może raportować wyniku bez członu finansowania "
            "(ADR-016) — uruchom attach_swap().")
