"""Testy purge i embargo — na przedziałach skonstruowanych ręcznie.

Purge ma jedną własność, której brak nie objawia się niczym widocznym:
model uczy się na etykietach dzielących okno wynikowe ze zbiorem testowym,
metryka rośnie, a przyczyną jest konstrukcja etykiet, nie sygnał. Dlatego
przedziały są tu wypisane z palca, a poprawna odpowiedź policzona na kartce.

Granice, które muszą trzymać:

* przedziały są PÓŁOTWARTE — styk końcem do początku nie jest nakładaniem;
* purge działa w OBIE strony w czasie, nie tylko wstecz;
* embargo dotyczy wyłącznie tego, co PO teście;
* `n_splits` bloków jest ciągłych w czasie, nie losowych.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from src.validation.overlap import (
    effective_sample_size, embargo_mask, merge_intervals, overlaps_any,
    purge_and_embargo, purge_mask, purge_report, purged_splits,
)

UTC = dt.timezone.utc
T0 = dt.datetime(2020, 1, 6, tzinfo=UTC)          # poniedziałek
H = dt.timedelta(hours=1)


def lab(spans: list[tuple[int, int]]) -> pl.DataFrame:
    """Etykiety z par (godzina startu, godzina końca) liczonych od T0."""
    return pl.DataFrame({
        "ts": [T0 + a * H for a, _ in spans],
        "t1": [T0 + b * H for _, b in spans],
    })


# --------------------------------------------------------------------------
# Scalanie przedziałów
# --------------------------------------------------------------------------

def test_merge_joins_touching_and_overlapping_intervals():
    s = np.array([0, 2, 5, 6]);  e = np.array([3, 4, 7, 9])
    ms, me = merge_intervals(s, e)
    assert ms.tolist() == [0, 5] and me.tolist() == [4, 9]


def test_merge_keeps_disjoint_intervals_apart():
    ms, me = merge_intervals(np.array([0, 10]), np.array([2, 12]))
    assert ms.tolist() == [0, 10] and me.tolist() == [2, 12]


def test_merge_is_order_independent():
    a = merge_intervals(np.array([5, 0]), np.array([7, 3]))
    b = merge_intervals(np.array([0, 5]), np.array([3, 7]))
    assert a[0].tolist() == b[0].tolist() and a[1].tolist() == b[1].tolist()


def test_merge_on_empty_input():
    ms, me = merge_intervals(np.array([]), np.array([]))
    assert ms.size == 0 and me.size == 0


# --------------------------------------------------------------------------
# Nakładanie — półotwartość
# --------------------------------------------------------------------------

def test_touching_end_to_start_is_not_an_overlap():
    """Etykieta kończąca się dokładnie wtedy, gdy testowa się zaczyna, nie
    widziała ani jednego bara z jej okna — nie wolno jej wyrzucić."""
    train, test = lab([(0, 10)]), lab([(10, 20)])
    assert purge_mask(train, test).tolist() == [True]


def test_one_hour_of_shared_window_is_an_overlap():
    train, test = lab([(0, 11)]), lab([(10, 20)])
    assert purge_mask(train, test).tolist() == [False]


def test_overlaps_any_on_empty_sides():
    z = np.array([], dtype="datetime64[ms]")
    assert overlaps_any(z, z, z, z).tolist() == []
    a = np.array([np.datetime64("2020-01-01")])
    assert overlaps_any(a, a, z, z).tolist() == [False]


# --------------------------------------------------------------------------
# Purge działa w obie strony
# --------------------------------------------------------------------------

def test_purge_removes_labels_that_start_before_and_run_into_the_test():
    train = lab([(0, 5), (8, 12), (30, 35)])
    test = lab([(10, 20)])
    assert purge_mask(train, test).tolist() == [True, False, True]


def test_purge_removes_labels_that_start_inside_the_test_window():
    """Etykieta późniejsza niż test też musi odpaść, jeśli okna się kryją.

    To jest strona, o której najłatwiej zapomnieć: purge kojarzy się
    z przeszłością, a nakładanie jest symetryczne.
    """
    train = lab([(15, 25)])
    test = lab([(10, 20)])
    assert purge_mask(train, test).tolist() == [False]


def test_purge_handles_several_disjoint_test_blocks():
    train = lab([(0, 2), (11, 13), (25, 27), (41, 43)])
    test = lab([(10, 20), (40, 50)])
    assert purge_mask(train, test).tolist() == [True, False, True, False]


def test_purge_on_empty_train_returns_empty_mask():
    assert purge_mask(lab([]), lab([(1, 2)])).size == 0


# --------------------------------------------------------------------------
# Embargo
# --------------------------------------------------------------------------

def test_embargo_drops_only_what_follows_the_test():
    train = lab([(5, 6), (21, 22), (30, 31)])
    test = lab([(10, 20)])
    keep = embargo_mask(train, test, dt.timedelta(hours=5))
    assert keep.tolist() == [True, False, True]     # 21 w [20,25), 30 poza


def test_embargo_boundary_is_half_open():
    train = lab([(20, 21), (25, 26)])
    test = lab([(10, 20)])
    keep = embargo_mask(train, test, dt.timedelta(hours=5))
    assert keep.tolist() == [False, True]           # 20 wchodzi, 25 już nie


def test_zero_embargo_removes_nothing():
    train = lab([(20, 21), (21, 22)])
    keep = embargo_mask(train, test=lab([(10, 20)]), embargo=dt.timedelta(0))
    assert keep.all()


def test_embargo_applies_after_every_test_block():
    train = lab([(21, 22), (51, 52), (80, 81)])
    test = lab([(10, 20), (40, 50)])
    keep = embargo_mask(train, test, dt.timedelta(hours=5))
    assert keep.tolist() == [False, False, True]


def test_embargo_does_not_touch_what_precedes_the_test():
    train = lab([(5, 6)])
    assert embargo_mask(train, lab([(10, 20)]), dt.timedelta(hours=50)).all()


# --------------------------------------------------------------------------
# Złożenie
# --------------------------------------------------------------------------

def test_purge_and_embargo_compose():
    train = lab([(0, 5), (8, 12), (21, 22), (40, 41)])
    test = lab([(10, 20)])
    out = purge_and_embargo(train, test, dt.timedelta(hours=5))
    assert out.height == 2                                    # zostają (0,5) i (40,41)
    assert out.get_column("ts").to_list() == [T0, T0 + 40 * H]


def test_heavily_overlapping_labels_lose_most_of_the_training_set():
    """Przy nakładaniu bliskim 1 purge kasuje większość treningu.

    To jest POPRAWNY wynik, nie usterka — i dokładnie ta liczba, która
    w `market-quant` zrobiła z 889 transakcji 172 obserwacje efektywne.
    """
    spans = [(i, i + 72) for i in range(0, 400)]              # okna 72 h co 1 h
    labels = lab(spans)
    test = labels[150:200]
    rest = pl.concat([labels[:150], labels[200:]])
    kept = purge_and_embargo(rest, test, dt.timedelta(hours=24))
    assert kept.height < rest.height * 0.7
    rep = purge_report(rest, kept, test)
    assert rep["removed"] == rest.height - kept.height
    assert 0 < rep["removed_share"] < 1


# --------------------------------------------------------------------------
# Podział
# --------------------------------------------------------------------------

def test_splits_are_contiguous_in_time():
    """Losowy k-fold miesza przeszłość z przyszłością jeszcze przed purge
    i żaden purge tego nie naprawia."""
    labels = lab([(i, i + 2) for i in range(0, 100)])
    for _, test in purged_splits(labels, 5, dt.timedelta(0)):
        ts = test.get_column("ts").to_list()
        assert ts == sorted(ts)
        span = (max(ts) - min(ts)) / H
        assert span == len(ts) - 1              # blok ciągły, bez dziur


def test_every_row_is_in_test_exactly_once():
    labels = lab([(i, i + 2) for i in range(0, 100)])
    seen = []
    for _, test in purged_splits(labels, 5, dt.timedelta(0)):
        seen += test.get_column("ts").to_list()
    assert sorted(seen) == sorted(labels.get_column("ts").to_list())
    assert len(seen) == len(set(seen))


def test_train_never_shares_a_window_with_its_own_test():
    """Własność, dla której cały moduł istnieje."""
    labels = lab([(i, i + 30) for i in range(0, 200)])
    for train, test in purged_splits(labels, 4, dt.timedelta(hours=10)):
        assert not overlaps_any(
            train.get_column("ts").to_numpy(), train.get_column("t1").to_numpy(),
            test.get_column("ts").to_numpy(), test.get_column("t1").to_numpy()).any()


def test_splits_reject_a_degenerate_request():
    with pytest.raises(ValueError):
        list(purged_splits(lab([(0, 1)]), 1, dt.timedelta(0)))


def test_report_counts_effective_not_nominal_test_size():
    labels = lab([(i, i + 30) for i in range(0, 120)])
    train, test = next(iter(purged_splits(labels, 4, dt.timedelta(hours=10))))
    rep = purge_report(labels, train, test)
    assert rep["n_test_effective"] == effective_sample_size(test)
    assert rep["n_test_effective"] < rep["n_test"]
