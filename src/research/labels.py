"""Warstwa etykiet — od decyzji do obserwacji gotowej do policzenia statystyki.

Składa jedną tabelę obserwacji: co wiedzieliśmy w momencie decyzji (cecha,
osie raportowania) i co się potem stało (target A, target B). Nic więcej.

CZEGO TU NIE MA — I DLACZEGO TO JEST WARUNEK, NIE OZDOBA

Moduł **nie liczy żadnej cechy** i nie importuje `features/momentum.py`.
Wartość cechy przychodzi w kolumnie, jej nazwa jest parametrem, a kierunek
wywodzi się z niej funkcją podaną z zewnątrz. Dzięki temu ta sama ścieżka
obsługuje trial, kontrolę losową i kontrolę permutacyjną — a różnice między
nimi są widoczne w kodzie wywołującego, nie schowane tutaj.

W `market-quant` warstwa etykiet znała hipotezę i to jest powód, dla którego
NIE została przeniesiona (M01, ADR-005). Ta powstała od zera.

DWIE WARSTWY TARGETU (ADR-003)

    A — informacja: `fwd_atr`, zwrot w przód przez h, znormalizowany
        `atr_d1_14`. Bezkierunkowy, bez kosztów, bez barier. To na nim stoją
        kryteria falsyfikacji T003 (ADR-015).
    B — ekonomia: net R z tickowo symulowanej transakcji triple-barrier.
        Kierunkowy, po kosztach. Wycena, nie test.

Target A powstaje w `research/grid.py` razem z barierą czasową, bo jest
własnością siatki, nie etykiety — i tam jest zweryfikowany przez M01–M05.
Ten moduł go nie przelicza; gdyby przeliczał, byłyby dwie definicje jednej
wielkości, a M02 i M05 mierzyłyby coś innego niż T003.

NAKŁADANIE

Okna wynikowe zachodzą na siebie masowo: przy h = 3 d i decyzjach co godzinę
sąsiednie etykiety dzielą prawie cały przedział. To NIE jest usuwane —
usuwanie zabrałoby 97% próby, a ADR-002 mówi, że warstwa doboru obserwacji
nie wchodzi do testu hipotezy. Nakładanie wchodzi do WNIOSKOWANIA, przez
block bootstrap i przez `n_eff`, nie do próby.
"""

from __future__ import annotations

from typing import Callable

import polars as pl

from ..execution.costs import attach_swap
from ..execution.simulator import CostModel
from ..features.volatility import attach_vol_pct, vol_regime
from .entries import simulate_entries

# Kolumny, które musi mieć ramka decyzji wchodząca do tego modułu.
REQUIRED = ("ts_decision", "t1", "ref_price", "atr_d1_14", "bar_ts", "fwd_atr")


def long_short(feature: pl.Expr) -> pl.Expr:
    """Kierunek ze znaku cechy, bez progu.

    Próg jest parametrem swobodnym i nie wchodzi do pierwszego testu
    (prerejestracja T003). Zero idzie na `long` — arbitralnie, ale jawnie
    i deterministycznie; przy cechach ciągłych trafia się to nigdy.
    """
    return pl.when(feature >= 0).then(pl.lit("long")).otherwise(pl.lit("short"))


def with_axes(decisions: pl.DataFrame, d1: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """Dołóż osie raportowania: para, rok, reżim zmienności.

    Kierunek i sesja dokładają się same — pierwszy przy kierunku, druga jest
    już w `ts_decision`. Reżim wymaga serii dziennej, bo percentyl liczy się
    na dobach, nie na godzinach.
    """
    out = attach_vol_pct(decisions, d1, on="ts_decision")
    return out.with_columns(
        pl.lit(symbol).alias("symbol"),
        pl.col("ts_decision").dt.year().alias("year"),
        pl.col("ts_decision").dt.hour().alias("hour"),
        vol_regime().alias("vol_regime"),
    )


def layer_a(decisions: pl.DataFrame, feature_col: str) -> pl.DataFrame:
    """Obserwacje warstwy A: cecha i target A, bez kosztów i bez barier.

    Zostają wyłącznie wiersze, w których OBIE wielkości są określone.
    Wiersz z cechą bez targetu (okno wychodzi poza segment) i wiersz
    z targetem bez cechy (za mało historii) to nie są obserwacje — i nie
    wolno im wejść z podstawioną wartością.
    """
    if feature_col not in decisions.columns:
        raise ValueError(f"brak kolumny cechy {feature_col!r}")
    missing = [c for c in ("fwd_atr",) if c not in decisions.columns]
    if missing:
        raise ValueError(f"brak kolumn targetu A: {missing}")
    f, t = pl.col(feature_col), pl.col("fwd_atr")
    return decisions.filter(
        f.is_not_null() & f.is_not_nan() & t.is_not_null() & t.is_not_nan()
    )


def layer_b(observations: pl.DataFrame, m1: pl.DataFrame, cost: CostModel, *,
            feature_col: str, sl_mult: float, tp_mult: float,
            margins: tuple[float, ...],
            direction: Callable[[pl.Expr], pl.Expr] = long_short,
            ) -> pl.DataFrame:
    """Obserwacje warstwy B: kierunek z cechy, wynik z symulatora tickowego.

    Uruchamiana na wyniku `layer_a`, nie na surowych decyzjach — ADR-003
    mówi, że krok B ma sens tylko tam, gdzie krok A jest określony, a liczenie
    B na innej próbie niż A czyniłoby różnicę A−B nieinterpretowalną.

    `direction` jest parametrem, żeby kontrola permutacyjna i kontrola losowa
    przechodziły tą samą ścieżką co trial. Domyślnie znak cechy.

    `margins` jest **wymagane i bez wartości domyślnej** (ADR-016): pełny
    koszt zawiera człon finansowania, a M03 wykrył jego brak dopiero po tym,
    jak moduł swapu istniał, miał testy i wyglądał na kompletny. Wynik wraca
    z kolumnami `r_net_<marża>`; samo `r` zostaje, żeby dało się zobaczyć,
    ile kosztuje finansowanie.
    """
    sided = observations.with_columns(direction(pl.col(feature_col)).alias("side"))
    played = simulate_entries(sided, m1, cost, sl_mult=sl_mult, tp_mult=tp_mult)
    return attach_swap(played, margins)


def check_required(decisions: pl.DataFrame) -> None:
    """Rzuć, jeżeli ramka nie pochodzi z siatki. Lepiej tu niż w symulatorze."""
    missing = [c for c in REQUIRED if c not in decisions.columns]
    if missing:
        raise ValueError(f"ramka decyzji nie ma kolumn {missing} — "
                         "czy przeszła przez grid.decision_grid + with_horizon?")


def coverage(before: pl.DataFrame, after: pl.DataFrame) -> dict:
    """Ile wierszy odpadło i na jakim kroku.

    `simulate_entries` cicho gubi wiersze bez danych w momencie decyzji, a to
    jest poprawny wynik, nie błąd — pod warunkiem, że ktoś go policzy.
    Raport T003 ma obowiązek podać te liczby; stąd funkcja, a nie komentarz.
    """
    n0, n1 = before.height, after.height
    return {
        "n_in": n0,
        "n_out": n1,
        "dropped": n0 - n1,
        "dropped_share": round((n0 - n1) / n0, 6) if n0 else None,
    }
