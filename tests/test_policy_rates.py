"""Stopy polityki (ADR-025) — parsowanie, tabele ręczne, point-in-time. Dane syntetyczne."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.data.policy_rates import (
    MANUAL, PolicyRateError, manual_series, parse_boc, parse_boe, parse_fred,
    policy_pit,
)

ROOT = Path(__file__).resolve().parents[1]
M12 = ROOT / "scripts" / "m12_policy_geometry.py"


def test_fred_parser_drops_missing_values():
    df = parse_fred("observation_date,X\n2016-01-01,0.5\n2016-01-02,.\n", "X")
    assert df.height == 1 and df["rate"][0] == 0.5


def test_boe_parser_reads_the_iadb_date_format():
    df = parse_boe("DATE,IUDBEDR\n04 Aug 2016,0.25\n")
    assert df["date"][0] == dt.date(2016, 8, 4) and df["rate"][0] == 0.25


def test_boe_parser_refuses_another_series():
    with pytest.raises(PolicyRateError):
        parse_boe("DATE,XYZ\n04 Aug 2016,0.25\n")


def test_boc_parser_skips_the_valet_preamble():
    text = '"TERMS AND CONDITIONS"\n"x"\n\n"OBSERVATIONS"\n"date","V39079"\n"2017-07-12","0.75"\n'
    df = parse_boc(text)
    assert df["date"][0] == dt.date(2017, 7, 12) and df["rate"][0] == 0.75


@pytest.mark.parametrize("ccy", sorted(MANUAL))
def test_manual_tables_are_sorted_sourced_and_start_before_the_data(ccy):
    rows = MANUAL[ccy]
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)
    assert all(r[2].strip() for r in rows), "pozycja bez źródła"
    assert rows[0][0] < dt.date(2015, 1, 1)


def test_manual_rba_path_matches_the_known_2020_emergency_cut():
    s = manual_series("AUD")
    assert s.filter(pl.col("date") == dt.date(2020, 3, 20))["rate"][0] == 0.25


def _series():
    return pl.DataFrame({"date": [dt.date(2016, 3, 9), dt.date(2016, 3, 16)],
                         "rate": [0.0, -0.4]})


def test_pit_does_not_see_a_change_on_its_own_date():
    """Margines 1 dnia roboczego: zmiana datowana 16.03 widoczna od 17.03."""
    v = policy_pit(_series(), [dt.date(2016, 3, 16), dt.date(2016, 3, 17)])
    assert v.tolist() == [0.0, -0.4]


def test_pit_before_any_data_is_nan_not_zero():
    v = policy_pit(_series(), [dt.date(2016, 3, 9)])
    assert np.isnan(v[0])


def test_pit_keeps_the_input_order():
    d = [dt.date(2016, 3, 21), dt.date(2016, 3, 11)]
    assert policy_pit(_series(), d).tolist() == [-0.4, 0.0]


@pytest.mark.parametrize("forbidden", [
    "load_h1", "harness.market", "research.grid", "research.labels",
    "fwd_atr", "with_horizon", "bid_", "ask_",
])
def test_m12_never_reads_a_price(forbidden):
    text = re.sub(r'"""(?:.|\n)*?"""', "", M12.read_text(encoding="utf-8"))
    code = "\n".join(l.split("#")[0] for l in text.split("\n"))
    assert forbidden not in code


def test_m12_declares_its_source_check_before_the_run():
    src = M12.read_text(encoding="utf-8")
    assert re.search(r"^MONTH_DIFF_TOL\s*=", src, re.M)
    assert re.search(r"^MAX_SUSPECT_MONTHS\s*=", src, re.M)
    assert 'kind="control"' in src
