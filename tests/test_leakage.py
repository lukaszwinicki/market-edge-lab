"""Testy wykonywalnej checklisty leakage'u (`DATA.md` §8).

Checklista ma jedną własność, bez której jest gorsza niż jej brak: **nie
wolno jej przejść przez przeoczenie**. Pozycja, której nie da się sprawdzić
kodem, musi wymagać napisania zdania — inaczej „nie sprawdzono" byłoby
cichsze niż „sprawdzono i jest źle", a raport i tak wyszedłby z pieczątką.

Dlatego większość testów poniżej to próby OSZUKANIA checklisty, nie próby
przejścia jej.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import polars as pl
import pytest
import yaml

from src.validation.leakage import (
    CONDITIONAL_ITEMS, FAIL, MANUAL, MANUAL_ITEMS, PASS, Checklist, LeakageCheckFailed,
    check_aged_feature_control, check_bar_closed, check_config,
    check_effective_n, check_registry, check_run_provenance, check_segment,
    run_checklist,
)

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[1]
SEG = (dt.datetime(2016, 1, 1, tzinfo=UTC), dt.datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC))


@pytest.fixture
def cfg():
    return yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def run_json():
    return {"run_id": "R1", "config_sha256": "a" * 64, "git_commit": "b" * 40,
            "git_dirty": False, "git_diff_sha256": None}


@pytest.fixture
def trials(tmp_path):
    p = tmp_path / "trials.jsonl"
    p.write_text(json.dumps({"event": "start", "run_id": "R1", "kind": "strategy"}) + "\n",
                 encoding="utf-8")
    return p


def obs(n=10, bar_gap_h=1, first=dt.datetime(2017, 5, 2, 10, tzinfo=UTC), horizon_d=3):
    ts = [first + dt.timedelta(hours=i) for i in range(n)]
    return pl.DataFrame({
        "ts_decision": ts,
        "bar_ts": [t - dt.timedelta(hours=bar_gap_h) for t in ts],
        "t1": [t + dt.timedelta(days=horizon_d) for t in ts],
    })


#: Deklaracje pokrywające wszystkie pozycje niesprawdzalne maszynowo.
ALL_DECL = {k: "ok" for k in list(MANUAL_ITEMS) + list(CONDITIONAL_ITEMS)}


def status_of(cl: Checklist, key: str) -> str:
    return next(c.status for c in cl.checks if c.key == key)


# --------------------------------------------------------------------------
# Nie da się przejść przez przeoczenie
# --------------------------------------------------------------------------

def test_a_manual_item_without_a_declaration_is_a_failure(cfg, run_json, trials):
    cl = run_checklist(cfg, run_json, trials, declarations={})
    assert not cl.passes
    assert {c.key for c in cl.failed} == set(MANUAL_ITEMS) | {"aged_feature"}


def test_declaring_every_manual_item_lets_the_checklist_pass(cfg, run_json, trials):
    cl = run_checklist(cfg, run_json, trials,
                       declarations=ALL_DECL)
    assert cl.passes
    assert all(status_of(cl, k) == MANUAL for k in MANUAL_ITEMS)


def test_one_missing_declaration_is_enough_to_block(cfg, run_json, trials):
    decl = dict(ALL_DECL)          # kopia: pop na module psułby inne testy
    decl.pop("purge_embargo")
    cl = run_checklist(cfg, run_json, trials, declarations=decl)
    assert not cl.passes
    assert [c.key for c in cl.failed] == ["purge_embargo"]


def test_an_empty_declaration_string_does_not_count(cfg, run_json, trials):
    cl = run_checklist(cfg, run_json, trials,
                       declarations={k: "" for k in ALL_DECL})
    assert not cl.passes


def test_failure_raises_and_names_every_offending_item(cfg, run_json, trials):
    cl = run_checklist(cfg, run_json, trials, declarations={})
    with pytest.raises(LeakageCheckFailed) as e:
        cl.raise_if_failed()
    for key in MANUAL_ITEMS:
        assert key in str(e.value)
    assert "aged_feature" in str(e.value)


def test_a_passing_checklist_does_not_raise(cfg, run_json, trials):
    run_checklist(cfg, run_json, trials,
                  declarations=ALL_DECL).raise_if_failed()


# --------------------------------------------------------------------------
# Zakazy twarde z konfiguracji
# --------------------------------------------------------------------------

def test_the_project_config_satisfies_every_hard_ban(cfg):
    cl = Checklist()
    check_config(cl, cfg)
    assert cl.passes, [c.evidence for c in cl.failed]


def test_allowing_mid_price_fails_the_checklist(cfg):
    cfg["data"]["mid_price_allowed"] = True
    cl = Checklist()
    check_config(cl, cfg)
    assert status_of(cl, "mid_price") == FAIL


def test_dropping_the_barrier_order_ban_fails(cfg):
    cfg["forbidden"]["optimistic_barrier_order"] = False
    cl = Checklist()
    check_config(cl, cfg)
    assert status_of(cl, "barrier_order") == FAIL


def test_unfreezing_the_instrument_set_fails(cfg):
    cfg["instruments"]["frozen"] = False
    cl = Checklist()
    check_config(cl, cfg)
    assert status_of(cl, "instruments_frozen") == FAIL


def test_dropping_the_llm_ban_fails(cfg):
    cfg["forbidden"]["llm_generated_backtest_inputs"] = False
    cl = Checklist()
    check_config(cl, cfg)
    assert status_of(cl, "no_llm_inputs") == FAIL


# --------------------------------------------------------------------------
# Proweniencja przebiegu
# --------------------------------------------------------------------------

def test_a_dirty_tree_passes_only_with_a_diff_hash(run_json):
    run_json["git_dirty"] = True
    cl = Checklist()
    check_run_provenance(cl, run_json)
    assert status_of(cl, "tree_clean") == FAIL

    run_json["git_diff_sha256"] = "c" * 64
    cl2 = Checklist()
    check_run_provenance(cl2, run_json)
    assert status_of(cl2, "tree_clean") == PASS


def test_a_run_without_a_config_hash_fails(run_json):
    run_json["config_sha256"] = None
    cl = Checklist()
    check_run_provenance(cl, run_json)
    assert status_of(cl, "params_hashed") == FAIL


def test_a_run_missing_from_the_register_fails(trials):
    cl = Checklist()
    check_registry(cl, trials, "NIE_MA_TAKIEGO")
    assert status_of(cl, "trials_logged") == FAIL


def test_a_missing_register_file_fails(tmp_path):
    cl = Checklist()
    check_registry(cl, tmp_path / "nie_ma.jsonl", "R1")
    assert status_of(cl, "trials_logged") == FAIL


# --------------------------------------------------------------------------
# Granice segmentu — łącznie z horyzontem
# --------------------------------------------------------------------------

def test_decisions_inside_the_segment_pass():
    cl = Checklist()
    check_segment(cl, obs(), *SEG)
    assert status_of(cl, "segment_bounds") == PASS


def test_a_window_reaching_past_the_segment_fails():
    """Najczęstsza postać tego błędu: decyzja jest w segmencie, a jej OKNO
    WYNIKOWE rozstrzyga się już poza nim. M02 wykrył dokładnie to
    w prerejestracji T001."""
    late = obs(n=3, first=dt.datetime(2021, 12, 29, 10, tzinfo=UTC), horizon_d=10)
    cl = Checklist()
    check_segment(cl, late, *SEG)
    assert status_of(cl, "segment_bounds") == FAIL
    assert "t1" in cl.failed[0].evidence


def test_a_decision_before_the_segment_fails():
    early = obs(n=3, first=dt.datetime(2015, 6, 1, 10, tzinfo=UTC))
    cl = Checklist()
    check_segment(cl, early, *SEG)
    assert status_of(cl, "segment_bounds") == FAIL


def test_an_empty_sample_is_not_a_boundary_violation():
    cl = Checklist()
    check_segment(cl, obs(n=0), *SEG)
    assert status_of(cl, "segment_bounds") == PASS


# --------------------------------------------------------------------------
# Bar zamknięty przed decyzją
# --------------------------------------------------------------------------

def test_a_full_bar_of_distance_passes():
    cl = Checklist()
    check_bar_closed(cl, obs(bar_gap_h=1), 3600)
    assert status_of(cl, "bar_closed") == PASS


def test_using_the_bar_of_the_decision_hour_fails():
    """Bar o etykiecie równej momentowi decyzji zamyka się dopiero godzinę
    później — to jest look-ahead o jeden bar."""
    cl = Checklist()
    check_bar_closed(cl, obs(bar_gap_h=0), 3600)
    assert status_of(cl, "bar_closed") == FAIL


def test_a_single_offending_row_fails_the_whole_sample():
    good = obs(n=50, bar_gap_h=1)
    bad = good.with_columns(
        pl.when(pl.int_range(pl.len()) == 7)
        .then(pl.col("ts_decision"))
        .otherwise(pl.col("bar_ts")).alias("bar_ts"))
    cl = Checklist()
    check_bar_closed(cl, bad, 3600)
    assert status_of(cl, "bar_closed") == FAIL


def test_missing_bar_column_becomes_an_undeclared_manual_item():
    cl = Checklist()
    check_bar_closed(cl, obs().drop("bar_ts"), 3600)
    assert status_of(cl, "bar_closed") in (MANUAL, FAIL)


# --------------------------------------------------------------------------
# n_eff zamiast liczby wierszy
# --------------------------------------------------------------------------

def test_effective_sample_smaller_than_rows_passes():
    cl = Checklist()
    check_effective_n(cl, 130_000, 1902)
    assert status_of(cl, "n_eff_used") == PASS
    assert "68.3×" in cl.checks[0].evidence


def test_a_missing_effective_sample_fails():
    cl = Checklist()
    check_effective_n(cl, 130_000, None)
    assert status_of(cl, "n_eff_used") == FAIL


def test_an_effective_sample_larger_than_the_rows_fails():
    """Podstawienie `height` zamiast n_eff jest najtańszym sposobem na
    wyprodukowanie przewagi, której nie ma — a n_eff > n_rows to znak,
    że ktoś podstawił nie tę liczbę."""
    cl = Checklist()
    check_effective_n(cl, 1000, 5000)
    assert status_of(cl, "n_eff_used") == FAIL


# --------------------------------------------------------------------------
# Kontrola przesuniętych cech
# --------------------------------------------------------------------------

def test_aged_feature_control_passes_when_every_arm_passes():
    cells = {"k24": {"aged_control": {"passes": True}},
             "k120": {"aged_control": {"passes": True}}}
    cl = Checklist()
    check_aged_feature_control(cl, cells)
    assert status_of(cl, "aged_feature") == PASS


def test_one_arm_better_after_ageing_fails_and_is_named():
    cells = {"k24": {"aged_control": {"passes": True}},
             "k480": {"aged_control": {"passes": False}}}
    cl = Checklist()
    check_aged_feature_control(cl, cells)
    assert status_of(cl, "aged_feature") == FAIL
    assert "k480" in cl.failed[0].evidence


def test_no_control_arm_at_all_is_an_undeclared_manual_item():
    """Brak ramienia nie jest zaliczeniem — trzeba napisać dlaczego."""
    cl = Checklist()
    check_aged_feature_control(cl, None)
    assert status_of(cl, "aged_feature") == FAIL

    declared = Checklist()
    check_aged_feature_control(declared, None,
                               declaration="M05: przebieg kontrolny bez cechy")
    assert status_of(declared, "aged_feature") == MANUAL


# --------------------------------------------------------------------------
# Postać raportowa
# --------------------------------------------------------------------------

def test_report_carries_every_item_and_the_verdict(cfg, run_json, trials):
    cl = run_checklist(cfg, run_json, trials, observations=obs(), segment=SEG,
                       n_rows=1000, n_eff=100, cells={"k24": {"aged_control": {"passes": True}}},
                       declarations=ALL_DECL)
    rep = cl.as_report()
    assert rep["passes"] is True
    assert rep["n_failed"] == 0
    assert rep["source"] == "DATA.md §8"
    assert len(rep["checks"]) == rep["n_checks"]
    assert all(c["evidence"] for c in rep["checks"])


def test_every_manual_item_in_the_module_exists_in_data_md():
    """Checklista w kodzie nie może się rozjechać z prozą w `DATA.md`."""
    text = (ROOT / "DATA.md").read_text(encoding="utf-8")
    section = text.split("## 8.")[1]
    for phrase in ("rozszerzającym", "fit()", "zamkniętej pełnej",
                   "nie widzi cen", "ALFRED", "purge + embargo"):
        assert phrase in section
