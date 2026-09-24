"""Testy deflacji o liczbę prób — na danych syntetycznych o znanej odpowiedzi.

Deflacja ma jeden kierunek, który musi być prawdziwy zawsze: **więcej prób
nigdy nie może poprawić wyniku**. Błąd w tę stronę nie objawia się wyjątkiem —
objawia się tym, że przeszukany wynik wygląda na odkryty.

Sprawdzamy więc monotoniczności i granice, a nie konkretne wartości: DSR
zależy od wzoru Baileya i López de Prado, który jest już sprawdzony
w `test_dsr.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.validation.deflation import (
    DeflationBracket, as_report, deflate, live_trial_count,
    var_sharpe_across_cells, var_sharpe_estimator,
)
from src.validation.dsr import expected_max_sharpe, sharpe


def rets(mean, n=2000, sd=1.0, seed=0):
    rng = np.random.default_rng(seed)
    return rng.standard_normal(n) * sd + mean


# --------------------------------------------------------------------------
# Kierunek, który musi być prawdziwy zawsze
# --------------------------------------------------------------------------

def test_more_trials_never_improves_the_result():
    r = rets(0.05)
    a = deflate(r, n_trials=1, n_obs=2000)
    b = deflate(r, n_trials=10, n_obs=2000)
    c = deflate(r, n_trials=100, n_obs=2000)
    assert a.dsr_high.dsr >= b.dsr_high.dsr >= c.dsr_high.dsr


def test_benchmark_rises_with_the_number_of_trials():
    assert expected_max_sharpe(1, 0.01) == 0.0
    assert expected_max_sharpe(7, 0.01) < expected_max_sharpe(50, 0.01)


def test_a_wider_variance_bracket_deflates_harder():
    """Górny koniec nawiasu ma dawać DSR nie wyższe niż dolny."""
    br = deflate(rets(0.05), n_trials=10, n_obs=2000)
    assert br.var_high >= br.var_low
    assert br.dsr_high.dsr <= br.dsr_low.dsr


def test_fewer_effective_observations_deflate_harder():
    """n_obs = liczba wierszy przy 99% nakładania zawyża statystykę."""
    r = rets(0.05, n=5000)
    optimistic = deflate(r, n_trials=10, n_obs=5000)
    honest = deflate(r, n_trials=10, n_obs=500)
    assert honest.dsr_high.dsr < optimistic.dsr_high.dsr


def test_a_strategy_with_no_edge_does_not_survive_deflation():
    br = deflate(rets(0.0, seed=3), n_trials=10, n_obs=2000)
    assert not br.survives_both_ends


def test_a_very_strong_edge_survives_both_ends():
    br = deflate(rets(0.30, seed=4), n_trials=10, n_obs=2000)
    assert br.survives_both_ends


# --------------------------------------------------------------------------
# Nawias V[SR]
# --------------------------------------------------------------------------

def test_single_cell_gives_zero_lower_variance_and_no_hurdle():
    """Bez rozrzutu między komórkami nie ma czego deflować — i to ma być
    widoczne jako zero, nie zgadnięte."""
    assert var_sharpe_across_cells({"a": rets(0.1)}) == 0.0
    assert var_sharpe_across_cells({}) == 0.0
    assert expected_max_sharpe(10, 0.0) == 0.0


def test_cell_variance_grows_when_cells_disagree():
    same = {"a": rets(0.1, seed=1), "b": rets(0.1, seed=2), "c": rets(0.1, seed=3)}
    spread = {"a": rets(-0.1, seed=1), "b": rets(0.1, seed=2), "c": rets(0.4, seed=3)}
    assert var_sharpe_across_cells(spread) > var_sharpe_across_cells(same)


def test_estimator_variance_shrinks_with_sample_size():
    assert var_sharpe_estimator(0.1, 100) > var_sharpe_estimator(0.1, 10_000)


def test_estimator_variance_is_never_negative():
    assert var_sharpe_estimator(2.0, 50, skew=5.0, kurtosis=3.0) >= 0.0


def test_estimator_variance_rejects_a_degenerate_sample():
    with pytest.raises(ValueError):
        var_sharpe_estimator(0.1, 1)


def test_bracket_is_ordered_even_if_the_ends_come_out_swapped():
    br = deflate(rets(0.05), n_trials=5, n_obs=2000,
                 cell_returns={"a": rets(0.05, seed=1), "b": rets(0.06, seed=2)})
    assert br.var_low <= br.var_high


# --------------------------------------------------------------------------
# Wpięcie w rejestr
# --------------------------------------------------------------------------

def test_trial_count_comes_from_the_register_not_from_config(tmp_path):
    """Zaniżone N zawyża DSR, więc liczba ma pochodzić z pliku, który rośnie
    sam — nie z konfiguracji, którą da się zapomnieć zaktualizować."""
    p = tmp_path / "trials.jsonl"
    rows = [
        {"kind": "inherited_count", "n_inherited": 7},
        {"event": "start", "run_id": "a", "kind": "control", "n_variants": 1},
        {"event": "start", "run_id": "b", "kind": "strategy", "n_variants": 3},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert live_trial_count(p) == 10          # 7 odziedziczonych + 3 warianty


def test_live_count_on_the_real_register_is_the_documented_one():
    n = live_trial_count(Path(__file__).resolve().parents[1] / "trials" / "trials.jsonl")
    assert n >= 7                              # ADR-004; rośnie po T003


# --------------------------------------------------------------------------
# Postać raportowa
# --------------------------------------------------------------------------

def test_report_is_marked_non_binding():
    rep = as_report(deflate(rets(0.2), n_trials=10, n_obs=2000))
    assert rep["binding"] is False
    assert "NIE zmienia werdyktu" in rep["note"]


def test_report_carries_both_ends_of_every_bracket():
    rep = as_report(deflate(rets(0.2), n_trials=10, n_obs=2000))
    for key in ("var_sharpe_bracket", "sharpe_benchmark_bracket", "dsr_bracket"):
        assert len(rep[key]) == 2
    assert rep["dsr_bracket"][0] >= rep["dsr_bracket"][1]


def test_report_states_the_effective_sample_not_the_row_count():
    rep = as_report(deflate(rets(0.2, n=5000), n_trials=10, n_obs=500))
    assert rep["n_obs_effective"] == 500


def test_deflate_refuses_a_degenerate_series():
    with pytest.raises(ValueError, match="za mało"):
        deflate(np.array([0.1]), n_trials=5, n_obs=2)
