"""Testy zmian wprowadzonych przy przenoszeniu aparatury (ADR-005).

Przeniesiony kod nie dziedziczy zaufania. Testy z `market-quant` pokrywają
logikę, która się nie zmieniła; ten plik pokrywa to, co zmieniliśmy MY:

  * pieczęć obejmuje 2024-2026, a nie 2024-2025 (ADR-004),
  * ścieżka do ticków pochodzi z konfiguracji i NIE MA wartości domyślnej
    (ADR-007),
  * licznik prób startuje od 7 odziedziczonych (ADR-004),
  * rejestr tworzy katalog `trials/`, zamiast po cichu nie zapisać próby.

Każdy z tych punktów to miejsce, w którym cicha pomyłka daje wynik, który
wygląda poprawnie i nie jest.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest
import yaml

from src.harness.market import (
    SealedHoldoutError, load_h1, load_m1, sealed_range, tick_cache,
    stale_partitions,
)
from src.harness.registry import (
    append_trial, inherited_trials, n_trials, read_trials,
)

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfg():
    return yaml.safe_load((ROOT / "configs" / "base.yaml").read_text())


def bars(ts: list[dt.datetime]) -> pl.DataFrame:
    n = len(ts)
    return pl.DataFrame({
        "ts": pl.Series(ts, dtype=pl.Datetime("ms", "UTC")),
        "bid_open": [1.0] * n, "bid_high": [1.0] * n,
        "bid_low": [1.0] * n, "bid_close": [1.0] * n,
        "ask_open": [1.0] * n, "ask_high": [1.0] * n,
        "ask_low": [1.0] * n, "ask_close": [1.0] * n,
        "spread_max": [0.0] * n, "spread_close": [0.0] * n,
        "n_ticks": [1] * n,
    })


def write_year(root: Path, symbol: str, frame: pl.DataFrame) -> None:
    year = frame["ts"][0].year
    d = root / f"symbol={symbol}" / f"year={year}"
    d.mkdir(parents=True)
    frame.write_parquet(d / "bars.parquet")


# --- pieczęć: nasz podział segmentów, nie ich ------------------------------

def test_seal_covers_2024_through_2026(cfg):
    """ADR-004: pieczęć sięga końca danych, nie 2025 jak u poprzednika."""
    s0, s1 = sealed_range(cfg)
    assert s0 == dt.datetime(2024, 1, 1, tzinfo=UTC)
    # koniec wyłączny: dzień PO 2026-12-31
    assert s1 == dt.datetime(2027, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("start,end", [
    ("2024-01-01", "2024-06-01"),      # w środku
    ("2023-12-01", "2024-02-01"),      # wchodzi od dołu
    ("2026-06-01", "2026-12-31"),      # rok, którego u poprzednika nie było
    ("2023-01-01", "2027-06-01"),      # przekracza w całości
])
def test_sealed_range_is_refused(cfg, tmp_path, start, end):
    s = dt.datetime.fromisoformat(start).replace(tzinfo=UTC)
    e = dt.datetime.fromisoformat(end).replace(tzinfo=UTC)
    with pytest.raises(SealedHoldoutError):
        load_h1("EURUSD", s, e, cfg, root=tmp_path)
    with pytest.raises(SealedHoldoutError):
        load_m1("EURUSD", s, e, cfg, root=tmp_path)


def test_research_and_oos_segments_are_readable(cfg, tmp_path):
    """Segmenty RESEARCH i OOS nie mogą być przypadkiem objęte pieczęcią."""
    write_year(tmp_path, "EURUSD",
               bars([dt.datetime(2021, 6, 1, h, tzinfo=UTC) for h in range(5)]))
    write_year(tmp_path, "EURUSD",
               bars([dt.datetime(2022, 6, 1, h, tzinfo=UTC) for h in range(5)]))

    research = load_h1("EURUSD", dt.datetime(2021, 1, 1, tzinfo=UTC),
                       dt.datetime(2021, 12, 31, tzinfo=UTC), cfg, root=tmp_path)
    oos = load_h1("EURUSD", dt.datetime(2022, 1, 1, tzinfo=UTC),
                  dt.datetime(2023, 12, 31, tzinfo=UTC), cfg, root=tmp_path)
    assert research.height == 5
    assert oos.height == 5


def test_unseal_is_explicit_and_opt_in(cfg, tmp_path):
    """Pieczęć musi dać się zdjąć JAWNIE — inaczej faza końcowa jest niemożliwa."""
    write_year(tmp_path, "EURUSD",
               bars([dt.datetime(2024, 6, 1, h, tzinfo=UTC) for h in range(3)]))
    opened = load_h1("EURUSD", dt.datetime(2024, 1, 1, tzinfo=UTC),
                     dt.datetime(2024, 12, 31, tzinfo=UTC), cfg,
                     root=tmp_path, unseal=True)
    assert opened.height == 3


# --- ścieżka do ticków: z konfiguracji, bez wartości domyślnej -------------

def test_tick_cache_comes_from_config_and_exists(cfg):
    """ADR-007: ticki czytamy ze starego repo, w trybie tylko do odczytu."""
    p = tick_cache(cfg)
    assert p.is_absolute()
    assert p.name == "dukascopy"
    assert "market-quant" in str(p), "ticki mają pochodzić z repo źródłowego"
    assert p.exists(), "katalog ticków nie istnieje — sprawdź data.tick_cache.path"


def test_tick_cache_resolves_relative_path_against_repo_root(tmp_path):
    cfg = {"data": {"tick_cache": {"path": "../elsewhere/ticks"}}}
    assert tick_cache(cfg) == (ROOT / ".." / "elsewhere" / "ticks").resolve()


def test_missing_cache_and_missing_cfg_is_loud_not_silent():
    """Brak ścieżki NIE MOŻE wyglądać jak 'zero godzin w cache'.

    Cicha wartość domyślna wskazująca na nieistniejący katalog dawałaby
    'nie ma czego budować' — czyli raport, że wszystko jest świeże,
    podczas gdy nie zbudowano niczego.
    """
    with pytest.raises(ValueError, match="cfg"):
        stale_partitions(["EURUSD"], dt.datetime(2020, 1, 1, tzinfo=UTC),
                         dt.datetime(2020, 12, 31, tzinfo=UTC))


# --- licznik prób: startuje od 7 odziedziczonych ---------------------------

def test_inherited_trials_is_seven_in_the_real_registry():
    """ADR-004. Liczba żyje w trials.jsonl, żeby była widoczna w danych."""
    assert inherited_trials(ROOT / "trials" / "trials.jsonl") == 7


def test_n_trials_starts_from_inherited_not_from_zero():
    assert n_trials(ROOT / "trials" / "trials.jsonl") == 7


def test_inherited_record_is_not_counted_as_a_run(tmp_path):
    """Wpis odziedziczony nie jest przebiegiem — nie ma pola `event`."""
    p = tmp_path / "trials" / "trials.jsonl"
    append_trial(p, {"kind": "inherited_count", "n_inherited": 7})
    assert inherited_trials(p) == 7
    assert n_trials(p) == 7
    assert read_trials(p)[0]["kind"] == "inherited_count"


def test_own_strategy_variants_add_on_top_of_inherited(tmp_path):
    p = tmp_path / "trials" / "trials.jsonl"
    append_trial(p, {"kind": "inherited_count", "n_inherited": 7})
    append_trial(p, {"event": "start", "run_id": "r1", "kind": "strategy",
                     "n_variants": 6})
    assert n_trials(p) == 13, "7 odziedziczonych + 6 wariantów T001"


def test_controls_and_infra_do_not_count_toward_n(tmp_path):
    """Kroki M są kontrolami aparatury i nie zużywają budżetu prób."""
    p = tmp_path / "trials" / "trials.jsonl"
    append_trial(p, {"kind": "inherited_count", "n_inherited": 7})
    append_trial(p, {"event": "start", "run_id": "m1", "kind": "infra",
                     "n_variants": 1})
    append_trial(p, {"event": "start", "run_id": "m3", "kind": "control",
                     "n_variants": 200})
    assert n_trials(p) == 7


def test_registry_creates_its_directory_rather_than_losing_a_trial(tmp_path):
    """Brakujący katalog nie może być powodem, dla którego próba nie zostaje
    zalogowana — cichy brak wpisu psuje licznik DSR."""
    p = tmp_path / "glebiej" / "trials" / "trials.jsonl"
    assert not p.parent.exists()
    append_trial(p, {"event": "start", "run_id": "r1", "kind": "strategy"})
    assert p.exists()
    assert n_trials(p) == 1


# --- konfiguracja: spójność deklaracji -------------------------------------

def test_discovery_cohort_is_frozen_and_has_six_pairs(cfg):
    inst = cfg["instruments"]
    assert inst["frozen"] is True
    assert len(inst["discovery"]) == 6
    assert "CHF" not in "".join(inst["discovery"])


def test_replication_cohort_is_declared_but_unavailable(cfg):
    """ADR-008: skład zamrożony PRZED wynikami, dane nie istnieją."""
    rep = cfg["instruments"]["replication"]
    assert rep["available"] is False
    assert len(rep["symbols"]) == 4


def test_inherited_trial_count_in_config_matches_registry(cfg):
    """Konfiguracja i rejestr nie mogą się rozjechać co do N."""
    assert cfg["meta"]["inherited_trials"] == \
        inherited_trials(ROOT / "trials" / "trials.jsonl")


def test_risk_layer_inside_hypothesis_test_is_forbidden(cfg):
    """ADR-002 jest decyzją centralną — ma być zapisana maszynowo, nie tylko
    w prozie, żeby dało się ją sprawdzić testem."""
    assert cfg["forbidden"]["risk_layer_inside_hypothesis_test"] is True
    assert cfg["forbidden"]["mid_price"] is True
    assert cfg["forbidden"]["llm_generated_backtest_inputs"] is True


def test_src_risk_does_not_exist_in_phase_1():
    """ADR-002 wymuszony architekturą: nie da się splątać warstwy, której nie ma."""
    assert not (ROOT / "src" / "risk").exists(), \
        "src/risk/ nie powstaje w fazie 1 — patrz ADR-002"


# --- odcisk zbioru ticków ---------------------------------------------------

def _bi5(root: Path, symbol: str, year: int, month: int, day: int, hour: int,
         payload: bytes) -> None:
    d = root / symbol / f"{year:04d}" / f"{month:02d}" / f"{day:02d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{hour:02d}h_ticks.bi5").write_bytes(payload)


def test_fingerprint_is_deterministic_and_counts_only_nonempty(tmp_path):
    from src.data.provenance import cache_fingerprint
    _bi5(tmp_path, "EURUSD", 2015, 1, 5, 9, b"abc")
    _bi5(tmp_path, "EURUSD", 2015, 1, 5, 10, b"")          # godzina bez handlu
    _bi5(tmp_path, "GBPUSD", 2015, 1, 5, 9, b"de")

    a = cache_fingerprint(tmp_path, ["EURUSD", "GBPUSD"])
    b = cache_fingerprint(tmp_path, ["GBPUSD", "EURUSD"])  # inna kolejność wejścia
    assert a["sha256"] == b["sha256"], "odcisk nie może zależeć od kolejności"
    assert a["n_files"] == 2, "pliki zerobajtowe nie wchodzą do odcisku"
    assert a["n_bytes"] == 5


def test_fingerprint_changes_when_data_changes(tmp_path):
    """Podmiana danych pod przebiegiem ma być wykrywalna."""
    from src.data.provenance import cache_fingerprint
    _bi5(tmp_path, "EURUSD", 2015, 1, 5, 9, b"abc")
    before = cache_fingerprint(tmp_path, ["EURUSD"])["sha256"]

    _bi5(tmp_path, "EURUSD", 2015, 1, 5, 9, b"abcd")       # ten sam plik, inny rozmiar
    assert cache_fingerprint(tmp_path, ["EURUSD"])["sha256"] != before

    _bi5(tmp_path, "EURUSD", 2015, 1, 6, 9, b"xy")         # dobudowana godzina
    assert cache_fingerprint(tmp_path, ["EURUSD"])["n_files"] == 2


def test_fingerprint_respects_year_filter(tmp_path):
    """Odcisk segmentu badawczego nie może zmieniać się od lat zapieczętowanych."""
    from src.data.provenance import cache_fingerprint
    _bi5(tmp_path, "EURUSD", 2021, 1, 5, 9, b"abc")
    _bi5(tmp_path, "EURUSD", 2024, 1, 5, 9, b"sealed")

    research = cache_fingerprint(tmp_path, ["EURUSD"], years=range(2015, 2024))
    assert research["n_files"] == 1
    assert research["n_bytes"] == 3
