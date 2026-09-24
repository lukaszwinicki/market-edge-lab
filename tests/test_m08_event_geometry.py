"""M08 krok A — granica ADR-020 i geometria zdarzeń, na danych syntetycznych.

Pierwsza połowa pilnuje, że skrypt jest strukturalnie niezdolny spojrzeć
w przód: nie importuje warstwy etykiet ani symulatora i nie dotyka żadnej
ceny po decyzji. Koniec okna wynikowego wolno mu policzyć wyłącznie jako
znacznik czasu. Druga połowa sprawdza funkcje czyste na przykładach, dla
których poprawna odpowiedź wynika z konstrukcji.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
M08 = ROOT / "scripts" / "m08_event_geometry.py"
sys.path.insert(0, str(ROOT / "scripts"))

from m08_event_geometry import (  # noqa: E402
    N_EFF_FOR_FALSIFIED, RHO_BREAKEVEN, gate_arithmetic, interval_clusters,
    overlap_partners, usd_alignment,
)


def src() -> str:
    return M08.read_text(encoding="utf-8")


def code_only() -> str:
    """Źródło bez docstringów i komentarzy — obietnice się nie liczą."""
    text = re.sub(r'"""(?:.|\n)*?"""', "", src())
    return "\n".join(l.split("#")[0] for l in text.split("\n"))


# --------------------------------------------------------------------------
# Granica ADR-020 — sprawdzana w źródle
# --------------------------------------------------------------------------

@pytest.mark.parametrize("forbidden", [
    "research.labels", "research.entries", "execution.simulator",
    "with_horizon", "simulate_trade", "layer_a", "layer_b", "join_asof",
])
def test_m08_does_not_import_anything_that_can_look_forward(forbidden):
    assert forbidden not in code_only(), (
        f"M08 sięga po {forbidden} — to łamie warunek 2 z ADR-020")


@pytest.mark.parametrize("col", ["fwd_atr", "t1", "exit_", "ref_price",
                                 "bid_close", "ask_close"])
def test_m08_never_touches_a_price_or_a_forward_column(col):
    """Zdarzenie liczy `breakout.attach`; skrypt nie czyta żadnej ceny sam.
    Tym bardziej ceny po decyzji."""
    assert not re.search(rf"\b{re.escape(col)}", code_only()), (
        f"M08 dotyka {col}")


def test_m08_discards_the_price_frame_returned_by_the_grid():
    """`decision_grid` zwraca obok siatki ramkę cen do wyjścia. M08 ma ją
    wyrzucić w miejscu wywołania, nie trzymać pod nazwą."""
    assert re.search(r"dec,\s*_,\s*_\s*=\s*decision_grid", code_only())


def test_m08_declares_the_exception_in_its_run_purpose():
    m = re.search(r'start_run\(\s*"([^"]+)"', src())
    assert m and "ADR-020" in (m.group(1) + src()[m.end():m.end() + 80])


def test_m08_logs_itself_as_a_control_not_a_trial():
    assert 'kind="control"' in code_only()
    assert 'kind="strategy"' not in code_only()


def test_m08_declares_its_criterion_as_constants():
    assert re.search(r"^RHO_BREAKEVEN\s*=\s*0\.05401", src(), re.M)
    assert re.search(r"^SIGN_CANCEL_MAX\s*=", src(), re.M)
    assert "criterion_set_before_run" in src()


def test_the_labels_layer_still_does_not_know_the_breakout_feature():
    labels = (ROOT / "src" / "research" / "labels.py").read_text(encoding="utf-8")
    assert "breakout" not in labels and "brk_evt" not in labels


# --------------------------------------------------------------------------
# `interval_clusters`
# --------------------------------------------------------------------------

def test_disjoint_windows_are_separate_clusters():
    s = np.array([0, 10, 20]); e = np.array([5, 15, 25])
    assert interval_clusters(s, e).tolist() == [1, 1, 1]


def test_touching_windows_do_not_overlap():
    """Okna półotwarte: koniec jednego równy początkowi drugiego to brak
    nakładania."""
    s = np.array([0, 5]); e = np.array([5, 10])
    assert interval_clusters(s, e).tolist() == [1, 1]


def test_a_chain_of_overlaps_is_one_cluster_even_if_ends_do_not_meet():
    s = np.array([0, 4, 8]); e = np.array([5, 9, 13])
    assert interval_clusters(s, e).tolist() == [3]


def test_a_long_window_swallows_later_short_ones():
    s = np.array([0, 2, 7, 30]); e = np.array([20, 3, 8, 31])
    assert interval_clusters(s, e).tolist() == [3, 1]


def test_clusters_ignore_input_order():
    s = np.array([8, 0, 4]); e = np.array([13, 5, 9])
    assert interval_clusters(s, e).tolist() == [3]


def test_clusters_of_nothing():
    assert interval_clusters(np.array([]), np.array([])).size == 0


# --------------------------------------------------------------------------
# `overlap_partners` i `usd_alignment`
# --------------------------------------------------------------------------

def test_overlap_partners_split_same_and_other_group():
    s = np.array([0, 3, 4, 50]); e = np.array([10, 13, 14, 60])
    g = np.array(["A", "A", "B", "B"])
    same, other = overlap_partners(s, e, g)
    assert same.tolist() == [1, 1, 0, 0]
    assert other.tolist() == [1, 1, 2, 0]


def test_usd_alignment_counts_only_cross_pair_overlaps_with_a_usd_leg():
    s = np.array([0, 1, 2, 3]); e = np.array([10, 10, 10, 10])
    g = np.array(["EURUSD", "USDJPY", "EURJPY", "EURUSD"])
    usd = np.array([+1, +1, 0, -1])
    out = usd_alignment(s, e, g, usd)
    # pary z nogą USD, różne symbole: (0,1) zgodne, (1,3) niezgodne;
    # (0,3) to ten sam symbol, EURJPY nie ma nogi USD.
    assert out["pairs"] == 2
    assert out["same_usd_direction"] == pytest.approx(0.5)


def test_usd_alignment_without_pairs_is_none_not_zero():
    out = usd_alignment(np.array([0]), np.array([1]), np.array(["EURUSD"]),
                        np.array([1]))
    assert out == {"pairs": 0, "same_usd_direction": None}


# --------------------------------------------------------------------------
# Arytmetyka bramki
# --------------------------------------------------------------------------

def test_the_falsified_boundary_sits_where_the_half_width_equals_breakeven():
    assert N_EFF_FOR_FALSIFIED == pytest.approx((1.96 / RHO_BREAKEVEN) ** 2)
    assert gate_arithmetic(N_EFF_FOR_FALSIFIED * 1.01)["falsified_reachable"]
    assert not gate_arithmetic(N_EFF_FOR_FALSIFIED * 0.99)["falsified_reachable"]


def test_gate_arithmetic_reproduces_the_m05_mapping():
    """M05, k = 24: n_eff 5 150 → próg wykrywalności 51,24%."""
    assert gate_arithmetic(5150)["detect_acc_pct"] == pytest.approx(51.24, abs=0.01)


def test_gate_arithmetic_on_an_empty_sample_is_unreachable_not_a_crash():
    out = gate_arithmetic(0)
    assert out["falsified_reachable"] is False and out["half_width"] is None


def test_half_width_scales_as_inverse_root_n():
    a, b = gate_arithmetic(400), gate_arithmetic(1600)
    assert a["half_width"] / b["half_width"] == pytest.approx(2.0)
    assert a["half_width"] == pytest.approx(1.96 / math.sqrt(400))
