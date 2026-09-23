"""Testy harnessu: rejestr prób, katalog uruchomienia, okna M1, pieczęć hold-outu.

Rejestr jest testowany na tymczasowym repozytorium gita — prawdziwy
`trials.jsonl` nie może dostać wpisów z testów, bo zawyżyłby licznik prób.
"""
import datetime as dt
import json
import subprocess

import polars as pl
import pytest
import yaml

from src.data.resample import slice_window
from src.execution.simulator import CostModel, Side, simulate_trade
from src.harness.market import (
    SealedHoldoutError, cost_model_for, load_m1, sealed_range,
)
from src.harness.registry import (
    freeze_commit, frozen_sections, n_runs, n_trials, read_trials, start_run,
)
from src.data.timeaxis import add_business_days

UTC = dt.timezone.utc
PIP = 1e-4
T0 = dt.datetime(2020, 1, 2, 0, 0, tzinfo=UTC)   # czwartek

CFG_TEXT = """\
labels:
  frozen: true
  sl_multiple: 2.0
data:
  splits:
    frozen: true
    sealed_holdout: {start: "2024-01-01", end: "2025-12-31"}
costs:
  min_roundturn_cost_pips: {fx_majors: 1.5, fx_crosses: 2.5}
  slippage_entry_x_spread: 0.5
  slippage_stop_x_spread: 1.0
signal_v1a:
  free_parameters: {donchian_lookback: 55}
"""


# --- repozytorium testowe ---------------------------------------------------

def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                           capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "configs").mkdir(parents=True)
    (r / "configs" / "base.yaml").write_text(CFG_TEXT)
    (r / ".gitignore").write_text("/runs/\n")
    (r / "trials").mkdir(parents=True, exist_ok=True)
    (r / "trials" / "trials.jsonl").write_text("")
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "init")
    return r


# --- rejestr prób -------------------------------------------------------------

def test_start_record_is_written_before_the_body_runs(repo):
    """Próba istnieje od chwili startu, nie od chwili sukcesu."""
    with start_run("test", {"seed": 1}, repo=repo, kind="strategy"):
        recs = read_trials(repo / "trials" / "trials.jsonl")
        assert [r["event"] for r in recs] == ["start"]


def test_failed_run_is_still_a_trial(repo):
    """Wyjątek nie może usunąć próby z licznika — i nie może zostać połknięty."""
    with pytest.raises(ZeroDivisionError):
        with start_run("crash", repo=repo, kind="strategy"):
            1 / 0
    recs = read_trials(repo / "trials" / "trials.jsonl")
    assert [r["event"] for r in recs] == ["start", "end"]
    assert recs[1]["status"] == "error"
    assert "ZeroDivisionError" in recs[1]["error"]
    assert n_trials(repo / "trials" / "trials.jsonl") == 1


def test_interrupted_run_is_still_a_trial(repo):
    with pytest.raises(KeyboardInterrupt):
        with start_run("ctrl-c", repo=repo, kind="strategy"):
            raise KeyboardInterrupt
    recs = read_trials(repo / "trials" / "trials.jsonl")
    assert recs[-1]["status"] == "interrupted"
    assert n_trials(repo / "trials" / "trials.jsonl") == 1


def test_trial_count_is_distinct_started_runs(repo):
    for i in range(3):
        with start_run(f"r{i}", repo=repo, kind="strategy"):
            pass
    assert n_trials(repo / "trials" / "trials.jsonl") == 3
    assert len(read_trials(repo / "trials" / "trials.jsonl")) == 6


def test_registry_is_append_only(repo):
    """Istniejące linie zostają bajt w bajt."""
    path = repo / "trials" / "trials.jsonl"
    path.write_text('{"event": "start", "run_id": "old"}\n')
    before = path.read_bytes()
    with start_run("x", repo=repo, kind="strategy"):
        pass
    assert path.read_bytes().startswith(before)
    assert n_trials(path) == 2


def test_only_strategy_variants_count_toward_n(repo):
    """ADR-029: kontrole i infra są logowane, ale nie są kandydatami na strategię."""
    path = repo / "trials" / "trials.jsonl"
    with start_run("gate0", repo=repo, kind="control"):
        pass
    with start_run("smoke", repo=repo, kind="infra"):
        pass
    with start_run("v1a grid", repo=repo, kind="strategy", n_variants=7):
        pass
    with pytest.raises(RuntimeError):
        with start_run("v1a baseline", repo=repo, kind="strategy"):
            raise RuntimeError
    assert n_trials(path) == 8
    assert n_runs(path) == 4


def test_legacy_entries_without_kind_count_as_strategy(repo):
    path = repo / "trials" / "trials.jsonl"
    path.write_text('{"event": "start", "run_id": "old"}\n')
    with start_run("gate0", repo=repo, kind="control"):
        pass
    assert n_trials(path) == 1


def test_kind_is_required_and_validated_before_anything_is_written(repo):
    path = repo / "trials" / "trials.jsonl"
    with pytest.raises(TypeError):
        with start_run("x", repo=repo):
            pass
    for kwargs in [{"kind": "exploration"},
                   {"kind": "strategy", "n_variants": 0},
                   {"kind": "control", "n_variants": 7}]:
        with pytest.raises(ValueError):
            with start_run("x", repo=repo, **kwargs):
                pass
    assert n_runs(path) == 0
    assert not (repo / "runs").exists()


def test_kind_and_variants_are_in_the_start_record(repo):
    with start_run("grid", repo=repo, kind="strategy", n_variants=7) as run:
        pass
    start = read_trials(repo / "trials" / "trials.jsonl")[0]
    assert (start["kind"], start["n_variants"]) == ("strategy", 7)
    assert json.loads((run.dir / "run.json").read_text())["kind"] == "strategy"


def test_run_dir_holds_config_copy_manifest_and_metrics(repo):
    with start_run("gate0", {"seed": 7}, repo=repo, kind="strategy") as run:
        run.record(mean_r=-0.08, n=np_int(1234))
    d = run.dir
    assert d.parent == repo / "runs"
    assert (d / "base.yaml").read_bytes() == \
        (repo / "configs" / "base.yaml").read_bytes()

    manifest = json.loads((d / "run.json").read_text())
    assert manifest["git_commit"] == git(repo, "rev-parse", "HEAD")
    assert manifest["git_dirty"] is False
    assert manifest["params"] == {"seed": 7}
    assert manifest["config_freeze_commit"] == git(repo, "rev-parse", "HEAD")

    metrics = json.loads((d / "metrics.json").read_text())
    assert metrics["status"] == "ok"
    assert metrics["metrics"] == {"mean_r": -0.08, "n": 1234}
    assert read_trials(repo / "trials" / "trials.jsonl")[-1]["metrics"]["n"] == 1234


def np_int(v):
    import numpy as np
    return np.int64(v)


def test_dirty_tree_is_recorded_with_patch(repo):
    """Wynik z niezacommitowanego kodu musi dać się odtworzyć."""
    (repo / "configs" / "base.yaml").write_text(CFG_TEXT + "# zmiana\n")
    (repo / "new_module.py").write_text("x = 1\n")
    with start_run("dirty", repo=repo, kind="strategy") as run:
        pass
    m = json.loads((run.dir / "run.json").read_text())
    assert m["git_dirty"] is True
    assert m["git_diff_sha256"]
    assert m["git_untracked"] == ["new_module.py"]
    assert "# zmiana" in (run.dir / "diff.patch").read_text()


def test_registry_itself_does_not_make_the_tree_dirty(repo):
    """Po pierwszym uruchomieniu trials.jsonl jest zmieniony — to nie jest
    zmiana kodu i nie może oznaczać każdej kolejnej próby jako brudnej."""
    with start_run("first", repo=repo, kind="strategy"):
        pass
    with start_run("second", repo=repo, kind="strategy") as run:
        pass
    assert json.loads((run.dir / "run.json").read_text())["git_dirty"] is False


def test_frozen_hash_changes_only_with_frozen_sections(repo):
    cfg_path = repo / "configs" / "base.yaml"

    def frozen_hash():
        with start_run("h", repo=repo, kind="strategy") as run:
            pass
        return json.loads((run.dir / "run.json").read_text())["frozen_sha256"]

    h0 = frozen_hash()
    cfg_path.write_text(CFG_TEXT.replace("donchian_lookback: 55", "donchian_lookback: 60"))
    assert frozen_hash() == h0                  # sekcja bez frozen: true
    cfg_path.write_text(CFG_TEXT.replace("sl_multiple: 2.0", "sl_multiple: 2.5"))
    assert frozen_hash() != h0


def test_frozen_sections_finds_nested_flags():
    cfg = yaml.safe_load(CFG_TEXT)
    assert set(frozen_sections(cfg)) == {"labels", "data.splits"}


def test_empty_purpose_is_rejected(repo):
    with pytest.raises(ValueError):
        with start_run("  ", repo=repo, kind="strategy"):
            pass
    assert n_trials(repo / "trials" / "trials.jsonl") == 0


def test_freeze_commit_is_the_commit_that_added_config(repo):
    first = git(repo, "rev-parse", "HEAD")
    (repo / "configs" / "base.yaml").write_text(CFG_TEXT + "# ADR\n")
    git(repo, "commit", "-qam", "change")
    assert freeze_commit(repo, "configs/base.yaml") == first


# --- okna M1 ------------------------------------------------------------------

def bars(n, start=T0, price=1.1000, step=0.0, spread=2 * PIP) -> pl.DataFrame:
    rows = []
    for i in range(n):
        p = price + i * step
        rows.append({
            "ts": start + dt.timedelta(minutes=i),
            "bid_open": p, "bid_high": p + PIP, "bid_low": p - PIP, "bid_close": p,
            "ask_open": p + spread, "ask_high": p + PIP + spread,
            "ask_low": p - PIP + spread, "ask_close": p + spread,
            "spread_max": spread, "spread_close": spread, "n_ticks": 10,
        })
    return pl.DataFrame(rows).with_columns(
        pl.col("ts").cast(pl.Datetime("ms", "UTC")), pl.col("n_ticks").cast(pl.UInt32))


def test_slice_window_bounds_are_inclusive():
    m1 = bars(100)
    w = slice_window(m1, T0 + dt.timedelta(minutes=10), T0 + dt.timedelta(minutes=20))
    assert w.height == 11
    assert w["ts"][0] == T0 + dt.timedelta(minutes=10)
    assert w["ts"][-1] == T0 + dt.timedelta(minutes=20)


def test_slice_window_between_bars_and_outside_data():
    m1 = bars(10)
    half = dt.timedelta(seconds=30)
    w = slice_window(m1, T0 + half, T0 + 3 * dt.timedelta(minutes=1) + half)
    assert w["ts"].to_list() == [T0 + dt.timedelta(minutes=i) for i in (1, 2, 3)]
    assert slice_window(m1, T0 - dt.timedelta(days=2), T0 - dt.timedelta(days=1)).is_empty()
    assert slice_window(m1, T0 + dt.timedelta(days=1), T0 + dt.timedelta(days=2)).is_empty()
    assert slice_window(m1, T0 + dt.timedelta(minutes=5), T0).is_empty()


# USUNIETE PRZY PRZENOSZENIU (ADR-005) — do przywrocenia razem z warstwa etykiet:
#   test_simulator_sees_only_the_trade_window
#   test_windowed_labels_match_simulation_on_full_history
# Oba testuja BRAK PODGLADANIA PRZYSZLOSCI przez symulator i sa wymagane
# przed pierwszym eksperymentem. Zalezne od src/labels/triple_barrier.py,
# ktory niesie tresc hipotezy i dlatego nie zostal przeniesiony.
# Slad w PROGRESS.md, sekcja M01.

# --- dane: pieczęć hold-outu i partycje ---------------------------------------

@pytest.fixture
def cfg():
    return yaml.safe_load(CFG_TEXT)


def write_year(root, symbol, frame):
    year = frame["ts"][0].year
    d = root / f"symbol={symbol}" / f"year={year}"
    d.mkdir(parents=True)
    frame.write_parquet(d / "bars.parquet")


def test_sealed_holdout_cannot_be_read(tmp_path, cfg):
    for start, end in [
        (dt.datetime(2024, 3, 1, tzinfo=UTC), dt.datetime(2024, 4, 1, tzinfo=UTC)),
        (dt.datetime(2023, 12, 28, tzinfo=UTC), dt.datetime(2024, 1, 11, tzinfo=UTC)),
        (dt.datetime(2025, 12, 31, 23, 59, tzinfo=UTC), dt.datetime(2026, 2, 1, tzinfo=UTC)),
    ]:
        with pytest.raises(SealedHoldoutError):
            load_m1("EURUSD", start, end, cfg, root=tmp_path)


def test_ranges_touching_holdout_edges_from_outside_are_allowed(tmp_path, cfg):
    s0, s1 = sealed_range(cfg)
    load_m1("EURUSD", s0 - dt.timedelta(days=30), s0 - dt.timedelta(minutes=1),
            cfg, root=tmp_path)
    load_m1("EURUSD", s1, s1 + dt.timedelta(days=30), cfg, root=tmp_path)


def test_unseal_opens_holdout(tmp_path, cfg):
    out = load_m1("EURUSD", dt.datetime(2024, 3, 1, tzinfo=UTC),
                  dt.datetime(2024, 4, 1, tzinfo=UTC), cfg, root=tmp_path, unseal=True)
    assert out.is_empty()


def test_load_m1_spans_year_partitions(tmp_path, cfg):
    dec = bars(60, start=dt.datetime(2019, 12, 31, 23, 30, tzinfo=UTC))
    write_year(tmp_path, "EURUSD", dec.filter(pl.col("ts").dt.year() == 2019))
    write_year(tmp_path, "EURUSD", dec.filter(pl.col("ts").dt.year() == 2020))
    out = load_m1("EURUSD", dt.datetime(2019, 12, 31, 23, 50, tzinfo=UTC),
                  dt.datetime(2020, 1, 1, 0, 10, tzinfo=UTC), cfg, root=tmp_path)
    assert out.height == 21
    assert out["ts"].is_sorted()


def test_naive_datetimes_are_rejected(tmp_path, cfg):
    with pytest.raises(ValueError):
        load_m1("EURUSD", dt.datetime(2020, 1, 1), dt.datetime(2020, 2, 1), cfg, root=tmp_path)


# --- koszty z konfiguracji ----------------------------------------------------

def test_cost_model_uses_cross_floor_and_jpy_pip(cfg):
    eurjpy = cost_model_for("EURJPY", cfg)
    assert eurjpy.min_roundturn_pips == 2.5
    assert eurjpy.pip == pytest.approx(0.01)
    usdjpy = cost_model_for("USDJPY", cfg)
    assert usdjpy.min_roundturn_pips == 1.5
    eurusd = cost_model_for("EURUSD", cfg)
    assert eurusd.pip == pytest.approx(1e-4)
    assert eurusd.stop_slippage_x_spread == 1.0
