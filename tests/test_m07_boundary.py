"""Granica ADR-020 i cecha `donch_pos` — testy na danych syntetycznych.

ADR-020 otwiera wąski wyjątek od ADR-012: wolno policzyć cechę hipotezy
nieprerejestrowanej, jeśli przebieg jest **strukturalnie niezdolny** spojrzeć
w przód. „Strukturalnie" znaczy: sprawdzalne w źródle, nie obiecane
w komentarzu — bo obietnica w komentarzu to dokładnie to, co ADR-012 odrzucił
przy klasyfikacji `control`/`strategy`.

Pierwsza połowa pilnuje tej granicy. Druga sprawdza samą cechę na ruchach
ceny wpisanych ręcznie, gdzie poprawna odpowiedź jest znana z konstrukcji.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.features.breakout import (
    attach, breakout_event, donch_pos, rolling_range,
)

ROOT = Path(__file__).resolve().parents[1]
M07 = ROOT / "scripts" / "m07_feature_redundancy.py"
UTC = dt.timezone.utc


# --------------------------------------------------------------------------
# Granica ADR-020 — sprawdzana w źródle
# --------------------------------------------------------------------------

def src() -> str:
    return M07.read_text(encoding="utf-8")


def code_only() -> str:
    """Źródło bez docstringów i komentarzy — obietnice się nie liczą."""
    text = re.sub(r'"""(?:.|\n)*?"""', "", src())
    return "\n".join(l.split("#")[0] for l in text.split("\n"))


@pytest.mark.parametrize("forbidden", [
    "research.labels", "research.entries", "execution.simulator",
    "with_horizon", "simulate_trade", "layer_a", "layer_b",
])
def test_m07_does_not_import_anything_that_can_look_forward(forbidden):
    assert forbidden not in code_only(), (
        f"M07 sięga po {forbidden} — to łamie warunek 2 z ADR-020")


@pytest.mark.parametrize("col", ["fwd_atr", "t1", "exit_ts", "exit_price"])
def test_m07_never_touches_a_forward_looking_column(col):
    assert col not in code_only(), (
        f"M07 dotyka kolumny {col} — przebieg patrzy w przód")


def test_m07_declares_the_exception_in_its_run_purpose():
    """Warunek 3 z ADR-020: przebieg ma deklarować, że korzysta z wyjątku."""
    m = re.search(r'start_run\(\s*"([^"]+)"', src())
    assert m, "nie znaleziono wywołania start_run"
    assert "ADR-020" in m.group(1)


def test_m07_logs_itself_as_a_control_not_a_trial():
    assert 'kind="control"' in code_only()
    assert 'kind="strategy"' not in code_only()


def test_m07_declares_its_criterion_as_a_constant_not_a_literal():
    """`HYPOTHESES.md`: kryterium ilościowe ustalone PRZED uruchomieniem."""
    assert re.search(r"^REDUNDANT_ABOVE\s*=\s*0?\.\d+", src(), re.M)
    assert "criterion_set_before_run" in src()


def test_the_labels_layer_still_does_not_know_this_feature():
    """Wyjątek dotyczy M07, nie warstwy etykiet."""
    labels = (ROOT / "src" / "research" / "labels.py").read_text(encoding="utf-8")
    assert "breakout" not in labels
    assert "donch" not in labels


# --------------------------------------------------------------------------
# `rolling_range`
# --------------------------------------------------------------------------

def test_rolling_range_uses_exactly_n_bars_ending_at_t():
    hi = np.array([1.0, 5, 2, 3, 4])
    lo = np.array([0.0, 4, 1, 2, 3])
    h, l = rolling_range(hi, lo, 3)
    assert np.isnan(h[:2]).all()
    assert h[2] == 5 and l[2] == 0        # bary 0..2
    assert h[3] == 5 and l[3] == 1        # bary 1..3
    assert h[4] == 4 and l[4] == 1        # bary 2..4 — piątka wypadła z okna


def test_rolling_range_on_a_series_shorter_than_the_window():
    h, l = rolling_range(np.arange(3.0), np.arange(3.0), 10)
    assert np.isnan(h).all() and np.isnan(l).all()


def test_rolling_range_rejects_a_degenerate_window():
    with pytest.raises(ValueError):
        rolling_range(np.arange(5.0), np.arange(5.0), 1)


# --------------------------------------------------------------------------
# `donch_pos` — stan
# --------------------------------------------------------------------------

def test_close_at_the_top_of_the_range_is_one():
    hi = np.array([10.0, 10, 10]); lo = np.array([0.0, 0, 0])
    assert donch_pos(hi, lo, np.array([0.0, 5, 10]), 3)[2] == pytest.approx(1.0)


def test_close_at_the_bottom_of_the_range_is_zero():
    hi = np.array([10.0, 10, 10]); lo = np.array([0.0, 0, 0])
    assert donch_pos(hi, lo, np.array([10.0, 5, 0]), 3)[2] == pytest.approx(0.0)


def test_close_in_the_middle_is_a_half():
    hi = np.array([10.0, 10, 10]); lo = np.array([0.0, 0, 0])
    assert donch_pos(hi, lo, np.array([0.0, 10, 5]), 3)[2] == pytest.approx(0.5)


def test_a_flat_range_gives_nan_not_a_midpoint():
    """Brak zakresu to brak informacji o pozycji, a nie pozycja środkowa."""
    c = np.full(5, 3.0)
    assert np.isnan(donch_pos(c, c, c, 3)[-1])


def test_donch_pos_stays_inside_the_unit_interval():
    rng = np.random.default_rng(0)
    px = np.cumsum(rng.standard_normal(5000)) + 100
    v = donch_pos(px + 0.5, px - 0.5, px, 55)
    v = v[np.isfinite(v)]
    assert v.min() >= 0.0 and v.max() <= 1.0


def test_the_state_fires_on_roughly_a_fifth_of_bars_by_construction():
    """`HYPOTHESES.md` H07: `donch_pos > 0,80` odpala z definicji na ~20%
    barów. To jest własność percentyla, nie rynku — i dlatego H07 twierdzi,
    że market-quant nie mierzył wybicia w sensie zdarzenia."""
    rng = np.random.default_rng(1)
    px = np.cumsum(rng.standard_normal(40_000)) + 100
    v = donch_pos(px + 0.5, px - 0.5, px, 55)
    v = v[np.isfinite(v)]
    assert 0.10 < (v > 0.80).mean() < 0.40


# --------------------------------------------------------------------------
# `breakout_event` — zdarzenie
# --------------------------------------------------------------------------

def test_a_close_above_the_previous_range_is_an_up_event():
    px = np.array([1.0, 1, 1, 1, 5])
    ev = breakout_event(px + 0.1, px - 0.1, px, 3)
    assert ev[4] == 1


def test_a_close_below_the_previous_range_is_a_down_event():
    px = np.array([5.0, 5, 5, 5, 1])
    ev = breakout_event(px + 0.1, px - 0.1, px, 3)
    assert ev[4] == -1


def test_no_event_while_price_stays_inside():
    px = np.array([1.0, 1.01, 0.99, 1.0, 1.005])
    assert (breakout_event(px + 0.5, px - 0.5, px, 3) == 0).all()


def test_the_range_excludes_the_current_bar():
    """Gdyby zakres obejmował bar bieżący, zamknięcie nigdy nie mogłoby go
    przekroczyć — bo samo by go wyznaczało. Zdarzenie nie istniałoby."""
    px = np.array([1.0, 1, 1, 100.0])
    assert breakout_event(px, px, px, 3)[3] == 1


def test_quiet_bars_collapse_a_run_into_a_single_event():
    """H07 mówi o MOMENCIE wyjścia, nie o stanie przebywania na zewnątrz."""
    # Rampa, nie pojedynczy skok: po skoku zakres natychmiast obejmuje nowy
    # poziom i surowa wersja odpala RAZ — nie byłoby czego zwijać, a test
    # przechodziłby nic nie sprawdzając. Przy rampie każdy bar bije zakres
    # trzech poprzednich, więc surowa wersja odpala wielokrotnie.
    px = np.array([1.0] * 5 + [2.0, 3, 4, 5, 6, 7, 8])
    raw = breakout_event(px + 0.1, px - 0.1, px, 3, quiet_bars=0)
    once = breakout_event(px + 0.1, px - 0.1, px, 3, quiet_bars=5)
    assert (raw != 0).sum() >= 5, "przymiarka nie odpala wielokrotnie"
    assert (once != 0).sum() == 1


def test_the_event_is_far_rarer_than_the_state():
    """Sedno H07: to NIE jest ta sama wielkość pod dwiema nazwami."""
    rng = np.random.default_rng(2)
    px = np.cumsum(rng.standard_normal(40_000)) + 100
    hi, lo = px + 0.5, px - 0.5
    state = donch_pos(hi, lo, px, 55)
    event = breakout_event(hi, lo, px, 55, quiet_bars=55)
    share_state = float(np.nanmean(state > 0.80))
    share_event = float((event != 0).mean())
    assert share_event < share_state / 3


# --------------------------------------------------------------------------
# Wpięcie w ramkę
# --------------------------------------------------------------------------

def _bars(n=300):
    rng = np.random.default_rng(3)
    px = np.cumsum(rng.standard_normal(n)) + 100
    ts = [dt.datetime(2020, 1, 1, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(n)]
    return pl.DataFrame({"ts": pl.Series(ts, dtype=pl.Datetime("ms", "UTC")),
                         "bid_high": px + 0.5, "bid_low": px - 0.5, "bid_close": px})


def test_attach_adds_both_columns_per_lookback():
    out = attach(_bars(), (55,), quiet_bars=55)
    assert "donch_pos_55" in out.columns and "brk_evt_55" in out.columns
    assert out.height == 300


def test_attach_on_an_empty_frame_keeps_the_schema():
    empty = pl.DataFrame(schema={"ts": pl.Datetime("ms", "UTC"),
                                 "bid_high": pl.Float64, "bid_low": pl.Float64,
                                 "bid_close": pl.Float64})
    out = attach(empty, (55,))
    assert "donch_pos_55" in out.columns and out.is_empty()


def test_attach_uses_bid_never_a_midpoint():
    b = _bars(120).with_columns((pl.col("bid_close") + 1.0).alias("ask_close"))
    a = attach(b, (55,))["donch_pos_55"].to_numpy()
    c = attach(b.drop("ask_close"), (55,))["donch_pos_55"].to_numpy()
    assert np.allclose(a, c, equal_nan=True)
