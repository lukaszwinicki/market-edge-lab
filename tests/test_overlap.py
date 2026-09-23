"""Nakładanie okien wynikowych i liczba obserwacji efektywnych.

Moduł jest przeniesiony (ADR-005) i do tej pory nie miał w tym repozytorium
ani jednego testu, a to on podaje mianownik `√n` do każdego przedziału
ufności. Podstawienie `height` zamiast `effective_sample_size` jest —
zgodnie z docstringiem modułu — najtańszym sposobem na wyprodukowanie
przewagi, której nie ma. Dlatego kontrakt jest tu rozpisany jawnie,
razem z granicami, w których funkcja świadomie zaniża wynik.

Dane syntetyczne: na wymyślonych przedziałach znamy poprawną odpowiedź.
"""

from __future__ import annotations

import datetime as dt

import polars as pl

from src.data.timeaxis import add_business_days
from src.validation.overlap import effective_sample_size, overlap_fraction

UTC = dt.timezone.utc
T0 = dt.datetime(2020, 1, 1, tzinfo=UTC)


def windows(spans: list[tuple[int, int]]) -> pl.DataFrame:
    """Ramka (ts, t1) z przedziałów podanych w godzinach od T0."""
    return pl.DataFrame(
        {
            "ts": [T0 + dt.timedelta(hours=a) for a, _ in spans],
            "t1": [T0 + dt.timedelta(hours=b) for _, b in spans],
        },
        schema={"ts": pl.Datetime("ms", "UTC"), "t1": pl.Datetime("ms", "UTC")},
    )


# --- overlap_fraction: diagnostyka, nie filtr -----------------------------

def test_overlap_fraction_is_zero_below_two_labels():
    assert overlap_fraction(windows([])) == 0.0
    assert overlap_fraction(windows([(0, 10)])) == 0.0


def test_overlap_fraction_zero_when_windows_are_disjoint():
    assert overlap_fraction(windows([(0, 1), (1, 2), (2, 3)])) == 0.0


def test_overlap_fraction_one_when_every_window_covers_the_next_label():
    assert overlap_fraction(windows([(0, 10), (1, 11), (2, 12)])) == 1.0


def test_overlap_fraction_counts_pairs_not_labels():
    # Mianownikiem jest liczba SĄSIEDZTW (height - 1), bo ostatnia etykieta
    # nie ma następnej i nie może się na nic nałożyć.
    df = windows([(0, 10), (1, 2), (3, 4), (5, 6)])
    assert overlap_fraction(df) == 1 / 3


def test_overlap_fraction_touching_windows_do_not_overlap():
    # t1 jest końcem WYŁĄCZNYM: okno kończące się dokładnie w momencie
    # następnej decyzji jeszcze się z nią nie nakłada.
    assert overlap_fraction(windows([(0, 5), (5, 10)])) == 0.0


def test_overlap_fraction_sorts_before_measuring():
    assert overlap_fraction(windows([(5, 10), (0, 5)])) == 0.0


# --- effective_sample_size: mianownik testów istotności --------------------

def test_effective_sample_size_empty_is_zero():
    assert effective_sample_size(windows([])) == 0


def test_effective_sample_size_equals_height_when_disjoint():
    df = windows([(0, 1), (1, 2), (2, 3), (3, 4)])
    assert effective_sample_size(df) == df.height == 4


def test_effective_sample_size_collapses_nested_windows_to_one():
    assert effective_sample_size(windows([(0, 100), (1, 2), (3, 4), (5, 6)])) == 1


def test_effective_sample_size_touching_windows_are_independent():
    assert effective_sample_size(windows([(0, 5), (5, 10), (10, 15)])) == 3


def test_effective_sample_size_sorts_before_counting():
    shuffled = windows([(10, 15), (0, 5), (5, 10)])
    assert effective_sample_size(shuffled) == 3


def test_effective_sample_size_is_greedy_by_start_hence_conservative():
    """Zachłanność po CZASIE STARTU daje dolne oszacowanie, nie maksimum.

    Tu istnieją dwa rozłączne przedziały — (1,2) i (3,4) — ale pierwszy
    w porządku czasowym blokuje oba. To jest zachowanie zamierzone
    (docstring modułu): wynik ma być deterministyczny i konserwatywny,
    a nie największy możliwy. Gdyby ten test kiedyś zaczął zwracać 2,
    ktoś podmienił regułę na optymalizującą — i zawyżył moc.
    """
    assert effective_sample_size(windows([(0, 100), (1, 2), (3, 4)])) == 1


def test_effective_sample_size_never_exceeds_height():
    df = windows([(0, 3), (1, 4), (2, 5), (6, 7)])
    assert effective_sample_size(df) <= df.height


# --- obie funkcje razem, na kształcie siatki decyzyjnej T001 ---------------

def test_hourly_grid_with_ten_day_horizon_collapses_by_two_orders():
    """Kształt siatki T001 w miniaturze: decyzje co godzinę, okno 10 dni.

    60 dni roboczych × 14 godzin = 840 etykiet nominalnych. Niezależnych
    jest tyle, ile mieści się kroków co 10 dni roboczych: 6. To jest
    dokładnie ta różnica, dla której istnieje M02 — liczba wierszy nie
    mówi nic o mocy.
    """
    ts, t1 = [], []
    day = dt.datetime(2020, 1, 1, tzinfo=UTC)
    for _ in range(60):
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        for hour in range(8, 22):
            d = day.replace(hour=hour)
            ts.append(d)
            t1.append(add_business_days(d, 10))
        day += dt.timedelta(days=1)

    df = pl.DataFrame(
        {"ts": ts, "t1": t1},
        schema={"ts": pl.Datetime("ms", "UTC"), "t1": pl.Datetime("ms", "UTC")},
    )
    assert df.height == 840
    assert effective_sample_size(df) == 6
    # Prawie każda etykieta nakłada się na następną — stąd 840 → 6.
    assert overlap_fraction(df) > 0.99
