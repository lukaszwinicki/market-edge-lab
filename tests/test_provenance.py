"""Proweniencja partycji i wykrywanie barów zbudowanych z wycinka cache.

Test odtwarza konkretną awarię, która wydarzyła się naprawdę: partycja
EURUSD 2019 zbudowana ze 130 godzin próbek dekodera, podczas gdy cache
trzymał 8 754 godziny. Odczyt zwracał 118 barów zamiast ~6 200, bez błędu.
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from src.data.provenance import (
    count_cache_hours, read_provenance, write_provenance,
)
from src.harness.market import (
    StaleBarsError, require_fresh_bars, stale_partitions,
)

UTC = dt.timezone.utc
START = dt.datetime(2019, 1, 1, tzinfo=UTC)
END = dt.datetime(2019, 12, 31, tzinfo=UTC)


def make_cache(root, symbol: str, year: int, n_full: int, n_empty: int = 0):
    """`n_full` niepustych plików .bi5 i `n_empty` zerobajtowych."""
    d = root / symbol / f"{year:04d}" / "03" / "04"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n_full):
        (d / f"{i:02d}h_ticks.bi5").write_bytes(b"\x00" * 16)
    for i in range(n_empty):
        (d / f"e{i:02d}h_ticks.bi5").write_bytes(b"")
    return d


def make_partition(root, symbol: str, year: int, freq: str, *,
                   n_source_files: int | None, n_bars: int = 3):
    """Partycja z `bars.parquet`; `n_source_files=None` = bez `source.json`."""
    d = root / freq / f"symbol={symbol}" / f"year={year}"
    d.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"ts": [dt.datetime(year, 3, 4, h, tzinfo=UTC)
                         for h in range(n_bars)]}).write_parquet(d / "bars.parquet")
    if n_source_files is not None:
        write_provenance(d, symbol=symbol, year=year, freq=freq,
                         n_source_files=n_source_files, n_ticks=100)
    return d


def roots_of(bars):
    return {"m1": bars / "m1", "h1": bars / "h1"}


# --- liczenie godzin w cache -------------------------------------------------

def test_count_cache_hours_skips_empty_files(tmp_path):
    make_cache(tmp_path, "EURUSD", 2019, n_full=5, n_empty=7)
    assert count_cache_hours(tmp_path, "EURUSD", 2019) == 5


def test_count_cache_hours_is_zero_for_missing_year(tmp_path):
    assert count_cache_hours(tmp_path, "EURUSD", 2019) == 0


def test_provenance_roundtrip(tmp_path):
    d = make_partition(tmp_path, "EURUSD", 2019, "m1", n_source_files=42)
    prov = read_provenance(d)
    assert prov["n_source_files"] == 42
    assert prov["symbol"] == "EURUSD" and prov["year"] == 2019
    assert prov["freq"] == "m1"


def test_read_provenance_returns_none_without_manifest(tmp_path):
    d = make_partition(tmp_path, "EURUSD", 2019, "m1", n_source_files=None)
    assert read_provenance(d) is None


# --- wykrywanie nieświeżych partycji ----------------------------------------

def test_partition_built_from_a_slice_is_stale(tmp_path):
    """Dokładnie awaria EURUSD 2019: 130 plików w partycji, 8754 w cache."""
    cache = tmp_path / "cache"
    bars = tmp_path / "bars"
    make_cache(cache, "EURUSD", 2019, n_full=8754)
    make_partition(bars, "EURUSD", 2019, "m1", n_source_files=130)
    make_partition(bars, "EURUSD", 2019, "h1", n_source_files=130)

    bad = stale_partitions(["EURUSD"], START, END, cache=cache, roots=roots_of(bars))
    assert len(bad) == 2
    assert all("130" in b and "8754" in b for b in bad)

    with pytest.raises(StaleBarsError, match="build_bars"):
        require_fresh_bars(["EURUSD"], START, END, cache=cache, roots=roots_of(bars))


def test_partition_from_whole_cache_is_fresh(tmp_path):
    cache = tmp_path / "cache"
    bars = tmp_path / "bars"
    make_cache(cache, "EURUSD", 2019, n_full=8754, n_empty=6)
    make_partition(bars, "EURUSD", 2019, "m1", n_source_files=8754)
    make_partition(bars, "EURUSD", 2019, "h1", n_source_files=8754)

    assert stale_partitions(["EURUSD"], START, END,
                            cache=cache, roots=roots_of(bars)) == []
    require_fresh_bars(["EURUSD"], START, END, cache=cache, roots=roots_of(bars))


def test_missing_partition_with_data_in_cache_is_stale(tmp_path):
    cache = tmp_path / "cache"
    bars = tmp_path / "bars"
    make_cache(cache, "EURUSD", 2019, n_full=100)
    bad = stale_partitions(["EURUSD"], START, END, cache=cache, roots=roots_of(bars))
    assert len(bad) == 2 and all("brak partycji" in b for b in bad)


def test_partition_without_manifest_is_stale(tmp_path):
    """Partycja nieznanego pochodzenia jest odrzucana, nie przyjmowana."""
    cache = tmp_path / "cache"
    bars = tmp_path / "bars"
    make_cache(cache, "EURUSD", 2019, n_full=100)
    make_partition(bars, "EURUSD", 2019, "m1", n_source_files=None)
    make_partition(bars, "EURUSD", 2019, "h1", n_source_files=100)

    bad = stale_partitions(["EURUSD"], START, END, cache=cache, roots=roots_of(bars))
    assert len(bad) == 1 and "source.json" in bad[0]


def test_year_absent_from_cache_is_not_reported(tmp_path):
    """Rok, którego jeszcze nie pobrano, nie jest awarią — po prostu go nie ma."""
    cache = tmp_path / "cache"
    bars = tmp_path / "bars"
    assert stale_partitions(["EURUSD"], START, END,
                            cache=cache, roots=roots_of(bars)) == []


def test_more_files_in_partition_than_in_cache_is_not_stale(tmp_path):
    """Cache bywa przycinany; bary są trwałe. Interesuje nas jeden kierunek."""
    cache = tmp_path / "cache"
    bars = tmp_path / "bars"
    make_cache(cache, "EURUSD", 2019, n_full=10)
    make_partition(bars, "EURUSD", 2019, "m1", n_source_files=8754)
    make_partition(bars, "EURUSD", 2019, "h1", n_source_files=8754)
    assert stale_partitions(["EURUSD"], START, END,
                            cache=cache, roots=roots_of(bars)) == []


def test_checks_every_year_the_range_touches(tmp_path):
    cache = tmp_path / "cache"
    bars = tmp_path / "bars"
    for year in (2019, 2020):
        make_cache(cache, "EURUSD", year, n_full=500)
        make_partition(bars, "EURUSD", year, "m1", n_source_files=500)
        make_partition(bars, "EURUSD", year, "h1", n_source_files=500)
    make_partition(bars, "EURUSD", 2020, "h1", n_source_files=3)   # nadpisuje

    bad = stale_partitions(["EURUSD"], START, dt.datetime(2020, 6, 1, tzinfo=UTC),
                           cache=cache, roots=roots_of(bars))
    assert len(bad) == 1 and "2020 h1" in bad[0]
