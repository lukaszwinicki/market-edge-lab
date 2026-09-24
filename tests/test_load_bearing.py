"""Testy funkcji nośnych, które audyt pokrycia wskazał jako nietestowane.

ADR-005: przeniesiony kod nie dziedziczy zaufania. Audyt na poziomie funkcji
pokazał, że pokrycie jest dobre, ale kilka funkcji **niosących wynik** nie
miało ani jednego testu w tym repozytorium. Kolejność poniżej jest kolejnością
szkody, jaką wyrządziłby ich cichy błąd:

1. `business_day` — decyduje, do którego dnia należy transakcja w block
   bootstrapie. Od niej zależy KAŻDE CI w projekcie: M03, M06, T003.
   Błąd tutaj przesuwa transakcje między blokami i zmienia każdy błąd
   standardowy, nie zmieniając ani jednej liczby widocznej w raporcie.
2. `block_indices` — wspólne bloki dla dwóch serii. Niezależne losowanie
   zerwałoby korelację dzienną i zawyżyło przedział ufności różnicy.
3. `daily_frames` — wspólna oś dni dla kilku serii. Dwie serie na dwóch
   różnych osiach nie dają się odjąć, a błąd wygląda jak wynik.
4. `is_cross` — wybiera podłogę kosztu 1,5 albo 2,5 pipsa. Jedna litera
   różnicy w nazwie pary zmienia koszt każdej transakcji.
5. `map_ts` — rzutowanie osi czasu w siatce decyzyjnej.
6. `GitState.diff_sha256` — odcisk brudnego drzewa; bez niego dwa różne
   stany kodu mogą zapisać się jako ten sam przebieg.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest
import yaml

from pathlib import Path

from src.data.dukascopy import pip_size
from src.data.resample import last_closed_bar
from src.harness.market import cost_model_for, is_cross
from src.harness.registry import GitState
from src.research.grid import map_ts
from src.validation.bootstrap import (
    block_indices, business_day, daily_frames,
)

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# 1. business_day — oś, na której stoi każdy bootstrap
# --------------------------------------------------------------------------

def _bd(*days: dt.datetime) -> list:
    return business_day(pl.Series(list(days))).to_list()


def test_weekday_entries_keep_their_own_day():
    mon = dt.datetime(2020, 1, 6, 10, tzinfo=UTC)
    fri = dt.datetime(2020, 1, 10, 21, tzinfo=UTC)
    assert _bd(mon, fri) == [dt.date(2020, 1, 6), dt.date(2020, 1, 10)]


def test_sunday_evening_open_belongs_to_monday():
    """FX otwiera się w niedzielę ~22:00 UTC. Ta sesja NIE jest własnym dniem
    — gdyby była, blok 20-dniowy obejmowałby dni, których rynek nie miał."""
    sun = dt.datetime(2020, 1, 5, 22, tzinfo=UTC)
    assert _bd(sun) == [dt.date(2020, 1, 6)]


def test_saturday_also_rolls_forward_to_monday():
    sat = dt.datetime(2020, 1, 4, 3, tzinfo=UTC)
    assert _bd(sat) == [dt.date(2020, 1, 6)]


def test_business_day_never_moves_an_entry_backwards():
    """Przesunięcie wstecz wsadziłoby transakcję w blok, który zamknął się
    przed nią — czyli w przeszłość."""
    rng = np.random.default_rng(0)
    base = dt.datetime(2020, 1, 1, tzinfo=UTC)
    stamps = [base + dt.timedelta(hours=int(h)) for h in rng.integers(0, 24 * 400, 500)]
    got = business_day(pl.Series(stamps)).to_list()
    assert all(d >= s.date() for d, s in zip(got, stamps))


def test_business_day_output_is_never_a_weekend():
    base = dt.datetime(2020, 1, 1, tzinfo=UTC)
    stamps = [base + dt.timedelta(hours=h) for h in range(0, 24 * 60)]
    assert all(d.weekday() < 5 for d in business_day(pl.Series(stamps)).to_list())


def test_business_day_is_idempotent_on_weekdays():
    stamps = [dt.datetime(2020, 1, 6 + i, 12, tzinfo=UTC) for i in range(5)]
    once = business_day(pl.Series(stamps))
    twice = business_day(pl.Series([dt.datetime.combine(d, dt.time(12), UTC)
                                    for d in once.to_list()]))
    assert once.to_list() == twice.to_list()


# --------------------------------------------------------------------------
# 2. block_indices — wspólne bloki dla dwóch serii
# --------------------------------------------------------------------------

def test_block_indices_cover_the_whole_axis_length():
    idx = block_indices(200, 20, 5, np.random.default_rng(0))
    assert idx.shape == (5, 200)
    assert idx.min() >= 0 and idx.max() < 200


def test_blocks_are_contiguous_and_wrap_around():
    """Bloki są kołowe: blok startujący przy końcu osi ma wrócić na początek,
    a nie zostać obcięty — inaczej końcówka próby byłaby niedolosowana."""
    idx = block_indices(50, 10, 200, np.random.default_rng(1))
    row = idx[0]
    for b in range(0, 50, 10):
        block = row[b:b + 10]
        expected = (block[0] + np.arange(10)) % 50
        assert block.tolist() == expected.tolist()
    assert np.isin(np.arange(50), idx).all()


def test_same_seed_gives_the_same_blocks_for_two_series():
    """Własność, dla której funkcja została wydzielona: dwie serie muszą
    dać się przepróbkować TYMI SAMYMI blokami."""
    a = block_indices(120, 20, 50, np.random.default_rng(7))
    b = block_indices(120, 20, 50, np.random.default_rng(7))
    assert np.array_equal(a, b)


def test_block_indices_refuse_an_axis_shorter_than_two_blocks():
    with pytest.raises(ValueError, match="za mało"):
        block_indices(30, 20, 10, np.random.default_rng(0))


# --------------------------------------------------------------------------
# 3. daily_frames — wspólna oś dni
# --------------------------------------------------------------------------

def _trades(days: list[int], values: list[float]) -> pl.DataFrame:
    base = dt.datetime(2020, 1, 6, 10, tzinfo=UTC)
    return pl.DataFrame({"ts": [base + dt.timedelta(days=d) for d in days],
                         "r": values})


def test_daily_frames_put_disjoint_series_on_one_axis():
    """Serie z rozłącznych dni MUSZĄ wylądować na wspólnej osi — inaczej
    nie da się ich odjąć, a wynik odejmowania wygląda sensownie."""
    a = _trades([0, 1], [1.0, 2.0])
    b = _trades([7, 8], [3.0, 4.0])
    days, mat = daily_frames([a, b])
    assert mat.shape == (len(days), 2)
    assert mat[:, 0].sum() == pytest.approx(3.0)
    assert mat[:, 1].sum() == pytest.approx(7.0)


def test_a_day_without_trades_is_zero_not_missing():
    a = _trades([0, 2], [1.0, 1.0])
    days, mat = daily_frames([a])
    assert not np.isnan(mat).any()
    assert mat.sum() == pytest.approx(2.0)


def test_daily_frames_sum_within_a_day():
    a = _trades([0, 0, 0], [1.0, 2.0, 3.0])
    _, mat = daily_frames([a])
    assert mat.sum() == pytest.approx(6.0)


def test_daily_frames_on_all_empty_input():
    empty = pl.DataFrame(schema={"ts": pl.Datetime("ms", "UTC"), "r": pl.Float64})
    days, mat = daily_frames([empty, empty])
    assert days == [] and mat.shape == (0, 2)


# --------------------------------------------------------------------------
# 4. is_cross — wybiera podłogę kosztu
# --------------------------------------------------------------------------

@pytest.mark.parametrize("sym", ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"])
def test_usd_pairs_are_not_crosses(sym):
    assert is_cross(sym) is False


def test_the_only_calibrated_cross_is_classified_as_one():
    assert is_cross("EURJPY") is True


@pytest.mark.parametrize("sym", ["GBPJPY", "EURGBP", "AUDNZD"])
def test_uncalibrated_fx_pairs_are_refused_too(sym):
    """Odmowa nie dotyczy tylko innych klas aktywów. Para FX spoza kohorty
    też nie ma u nas skali punktu — a `"USD" not in symbol` odpowiadało na
    nią równie chętnie jak na `DAX`."""
    from src.data.dukascopy import UnknownInstrumentError
    with pytest.raises(UnknownInstrumentError):
        is_cross(sym)


def test_the_whole_discovery_cohort_is_classified_as_declared():
    """Jedna para w kohorcie jest crossem. Gdyby klasyfikacja się przesunęła,
    koszt każdej transakcji EURJPY zmieniłby się o pips."""
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    crosses = [s for s in cfg["instruments"]["discovery"] if is_cross(s)]
    assert crosses == ["EURJPY"]


def test_cost_floor_follows_the_classification():
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    major = cost_model_for("EURUSD", cfg)
    cross = cost_model_for("EURJPY", cfg)
    assert major.min_roundturn_pips == 1.5
    assert cross.min_roundturn_pips == 2.5
    assert cross.min_roundturn_pips > major.min_roundturn_pips


def test_cost_model_takes_every_number_from_config_not_from_code():
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    cfg["costs"]["slippage_entry_x_spread"] = 0.75
    assert cost_model_for("EURUSD", cfg).entry_slippage_x_spread == 0.75


# --------------------------------------------------------------------------
# 5. map_ts — oś czasu w siatce decyzyjnej
# --------------------------------------------------------------------------

def test_map_ts_applies_the_axis_function_and_keeps_millisecond_dtype():
    ts = [dt.datetime(2020, 3, 2, 9, tzinfo=UTC), dt.datetime(2020, 3, 2, 17, tzinfo=UTC)]
    df = pl.DataFrame({"t1": ts})
    out = df.with_columns(map_ts("t1", lambda t: last_closed_bar(t, 3600)).alias("bar"))
    assert out.schema["bar"] == pl.Datetime("ms", "UTC")
    assert out["bar"].to_list() == [last_closed_bar(t, 3600) for t in ts]


def test_map_ts_does_not_mutate_the_source_column():
    df = pl.DataFrame({"t1": [dt.datetime(2020, 3, 2, 9, tzinfo=UTC)]})
    out = df.with_columns(map_ts("t1", lambda t: t - dt.timedelta(hours=1)).alias("b"))
    assert out["t1"].to_list() == df["t1"].to_list()


# --------------------------------------------------------------------------
# 6. GitState.diff_sha256 — odcisk brudnego drzewa
# --------------------------------------------------------------------------

def test_clean_tree_has_no_diff_hash():
    assert GitState("abc", False, "", []).diff_sha256 is None


def test_dirty_tree_hashes_the_diff():
    g = GitState("abc", True, "diff --git a/x", [])
    assert isinstance(g.diff_sha256, str) and len(g.diff_sha256) == 64


def test_untracked_files_change_the_fingerprint():
    """Nowy plik nie pojawia się w `git diff`. Gdyby nie wchodził do odcisku,
    dwa różne stany kodu zapisałyby się jako ten sam przebieg."""
    a = GitState("abc", True, "same diff", [])
    b = GitState("abc", True, "same diff", ["scripts/new.py"])
    assert a.diff_sha256 != b.diff_sha256


def test_the_fingerprint_is_stable_for_the_same_state():
    a = GitState("abc", True, "d", ["x.py"])
    b = GitState("abc", True, "d", ["x.py"])
    assert a.diff_sha256 == b.diff_sha256


# --------------------------------------------------------------------------
# 7. Odmowa dla instrumentów spoza skalibrowanej kohorty
# --------------------------------------------------------------------------
# Kohorta replikacyjna (XAUUSD, WTI, SPX500, DAX) jest zamrożona w base.yaml,
# ale aparatura jej NIE ZNA: nie ma skali punktu, zakresu ceny ani poziomu
# kosztu. Do 2026-09-24 część funkcji odpowiadała na pytania o te instrumenty
# liczbą — `is_cross("DAX")` zwracało True, czyli podłogę „FX cross" 2,5
# pipsa dla indeksu. Backtest policzyłby się do końca.
#
# Cicha zła odpowiedź jest tu groźniejsza od wyjątku, bo wynik, który się
# policzył, wygląda jak wynik.

from src.data.dukascopy import (  # noqa: E402
    SYMBOL_SCALE, UnknownInstrumentError, decode_bi5, known_instruments,
)

REPLICATION = ("XAUUSD", "WTI", "SPX500", "DAX")


def test_known_instruments_is_exactly_the_fx_discovery_cohort():
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    assert known_instruments() == frozenset(cfg["instruments"]["discovery"])


def test_the_replication_cohort_is_declared_but_not_calibrated():
    """ADR-008 zamroził skład kohorty. Zamrożenie składu to NIE to samo,
    co gotowość aparatury — i ta różnica ma być widoczna."""
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    declared = set(cfg["instruments"]["replication"]["symbols"])
    assert declared == set(REPLICATION)
    assert declared & known_instruments() == set()


@pytest.mark.parametrize("sym", REPLICATION)
def test_pip_size_refuses_an_uncalibrated_instrument(sym):
    with pytest.raises(UnknownInstrumentError):
        pip_size(sym)


@pytest.mark.parametrize("sym", REPLICATION)
def test_is_cross_refuses_instead_of_guessing(sym):
    """Najgroźniejszy z całej grupy: zwracał `True`/`False` bez ostrzeżenia."""
    with pytest.raises(UnknownInstrumentError):
        is_cross(sym)


@pytest.mark.parametrize("sym", REPLICATION)
def test_cost_model_refuses_an_uncalibrated_instrument(sym):
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    with pytest.raises(UnknownInstrumentError):
        cost_model_for(sym, cfg)


def test_tick_decoding_refuses_an_uncalibrated_instrument():
    with pytest.raises(UnknownInstrumentError):
        decode_bi5(b"", "SPX500", dt.datetime(2020, 4, 20, 14, tzinfo=UTC))


def test_the_refusal_says_what_is_missing_and_what_it_would_cost():
    """Komunikat ma prowadzić do decyzji, nie tylko zatrzymywać."""
    with pytest.raises(UnknownInstrumentError) as e:
        pip_size("DAX")
    msg = str(e.value)
    for phrase in ("kalibracji", "min_h1_bars", "ADR", "M03", "M04"):
        assert phrase in msg


def test_the_refusal_is_a_key_error_so_old_handlers_still_work():
    assert issubclass(UnknownInstrumentError, KeyError)


@pytest.mark.parametrize("sym", sorted(SYMBOL_SCALE))
def test_every_calibrated_instrument_still_answers(sym):
    """Odmowa nie może objąć kohorty, na której wszystko dotąd policzono."""
    assert pip_size(sym) > 0
    assert isinstance(is_cross(sym), bool)
