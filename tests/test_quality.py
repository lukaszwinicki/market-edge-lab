"""Testy raportu jakości danych.

Kluczowy test to `test_detects_feed_outage_across_all_symbols` — broni
przed scenariuszem, w którym awaria feedu zapisuje się jako "brak rynku"
i luka staje się niewidoczna dla backtestu.
"""
import datetime as dt

import polars as pl
import pytest

from pathlib import Path

from src.data.quality import (
    AcceptedOutage, accepted_outages_from, build_report, missing_trading_hours,
    render_markdown, trading_cells,
)

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def bars(hours: list[dt.datetime], spread: float = 3e-5) -> pl.DataFrame:
    n = len(hours)
    return pl.DataFrame({
        "ts": pl.Series(hours, dtype=pl.Datetime("ms", "UTC")),
        "bid_open": [1.1] * n, "bid_high": [1.11] * n,
        "bid_low": [1.09] * n, "bid_close": [1.1] * n,
        "ask_open": [1.1 + spread] * n, "ask_high": [1.11 + spread] * n,
        "ask_low": [1.09 + spread] * n, "ask_close": [1.1 + spread] * n,
        "spread_max": [spread * 2] * n, "spread_close": [spread] * n,
        "n_ticks": pl.Series([1000] * n, dtype=pl.UInt32),
    })


def weekday_hours(start: dt.date, weeks: int) -> list[dt.datetime]:
    """Pon-pt, całą dobę — prosty, regularny kalendarz handlowy."""
    out = []
    for w in range(weeks):
        for d in range(5):                      # pon..pt
            day = start + dt.timedelta(days=7 * w + d)
            out += [dt.datetime(day.year, day.month, day.day, h, tzinfo=UTC)
                    for h in range(24)]
    return out


MONDAY = dt.date(2019, 3, 4)


# --- Kalendarz wyprowadzany z danych ----------------------------------------

def test_trading_calendar_is_derived_not_assumed():
    """Weekendy mają wyjść jako niehandlowe, bo ich w danych nie ma."""
    cells = trading_cells(bars(weekday_hours(MONDAY, 12)))
    trading = cells.filter("is_trading")
    assert set(trading["weekday"].to_list()) == {1, 2, 3, 4, 5}   # pon..pt
    assert cells.filter(pl.col("weekday").is_in([6, 7]))["is_trading"].any() == False


def test_missing_hour_inside_trading_calendar_is_flagged():
    hrs = weekday_hours(MONDAY, 12)
    hole = dt.datetime(2019, 3, 19, 10, tzinfo=UTC)      # wtorek, środek sesji
    kept = [h for h in hrs if h != hole]
    b = bars(kept)
    assert missing_trading_hours(b, trading_cells(b))["ts"].to_list() == [hole]


def test_weekend_absence_is_not_a_gap():
    b = bars(weekday_hours(MONDAY, 12))
    assert missing_trading_hours(b, trading_cells(b)).is_empty()


# --- Wykrywanie awarii feedu — rdzeń modułu ---------------------------------

def test_detects_feed_outage_across_all_symbols():
    """Godzina pusta u WSZYSTKICH par = awaria, nie zamknięcie rynku."""
    hrs = weekday_hours(MONDAY, 12)
    outage = dt.datetime(2019, 3, 19, 10, tzinfo=UTC)
    kept = [h for h in hrs if h != outage]

    rep = build_report({s: bars(kept) for s in ("EURUSD", "GBPUSD", "USDJPY")})

    assert rep.suspected_outages["ts"].to_list() == [outage]
    ok, reasons = rep.passes_gate_0()
    assert not ok and "awarię feedu" in " ".join(reasons)


def test_single_symbol_gap_is_not_an_outage():
    """Luka u jednej pary to problem instrumentu, nie feedu."""
    hrs = weekday_hours(MONDAY, 12)
    hole = dt.datetime(2019, 3, 19, 10, tzinfo=UTC)

    rep = build_report({
        "EURUSD": bars([h for h in hrs if h != hole]),
        "GBPUSD": bars(hrs),
        "USDJPY": bars(hrs),
    })

    assert rep.suspected_outages.is_empty()
    assert rep.per_symbol_gaps.filter(pl.col("symbol") == "EURUSD").height == 1


def _without(hrs, drop):
    drop = set(drop)
    return [h for h in hrs if h not in drop]


def test_christmas_closure_is_not_an_outage():
    """25.12 pusty u wszystkich par to zamknięcie rynku, nie awaria."""
    hrs = weekday_hours(dt.date(2015, 11, 30), 6)          # obejmuje piątek 25.12
    xmas = [dt.datetime(2015, 12, 25, h, tzinfo=UTC) for h in range(8, 21)]
    kept = _without(hrs, xmas)

    rep = build_report({s: bars(kept) for s in ("EURUSD", "GBPUSD", "USDJPY")})

    assert rep.suspected_outages.is_empty()
    assert rep.holiday_closures["ts"].to_list() == xmas
    assert rep.symbol_coverage["missing"].to_list() == [0, 0, 0]
    assert rep.passes_gate_0()[0]
    assert "Zamknięcia świąteczne" in render_markdown(rep)


def test_long_gap_touching_holiday_is_still_an_outage():
    """Awaria nie może się schować za świętem: blok > limitu zostaje awarią."""
    hrs = weekday_hours(dt.date(2015, 11, 30), 6)
    gap = [dt.datetime(2015, 12, 23, 0, tzinfo=UTC) + dt.timedelta(hours=i)
           for i in range(72)]                              # 23.12 – 25.12
    kept = _without(hrs, gap)

    rep = build_report({s: bars(kept) for s in ("EURUSD", "GBPUSD", "USDJPY")})

    assert rep.holiday_closures.is_empty()
    assert rep.suspected_outages.height == 72
    assert not rep.passes_gate_0()[0]


def test_non_holiday_outage_unaffected_by_holiday_rule():
    hrs = weekday_hours(dt.date(2015, 11, 30), 6)
    outage = dt.datetime(2015, 12, 16, 10, tzinfo=UTC)
    rep = build_report({s: bars(_without(hrs, [outage]))
                        for s in ("EURUSD", "GBPUSD", "USDJPY")})
    assert rep.suspected_outages["ts"].to_list() == [outage]


# --- Kryterium Bramki 0 -----------------------------------------------------

def test_gate_0_fails_when_two_symbols_exceed_gap_budget():
    hrs = weekday_hours(MONDAY, 10)
    few = hrs[:len(hrs) // 2]        # połowa brakuje => ~50% luk
    rep = build_report({"EURUSD": bars(few), "GBPUSD": bars(few), "USDJPY": bars(hrs)})
    ok, reasons = rep.passes_gate_0(max_gap_pct=5.0)
    assert not ok
    assert any("luki >" in r for r in reasons)


def test_gate_0_passes_on_clean_data():
    hrs = weekday_hours(MONDAY, 6)
    rep = build_report({s: bars(hrs) for s in ("EURUSD", "GBPUSD", "USDJPY")})
    ok, reasons = rep.passes_gate_0()
    assert ok, reasons


def test_invariant_violation_fails_gate_0():
    hrs = weekday_hours(MONDAY, 12)
    broken = bars(hrs).with_columns(pl.lit(1.0).alias("ask_close"))   # ask < bid
    rep = build_report({"EURUSD": broken, "GBPUSD": bars(hrs), "USDJPY": bars(hrs)})
    ok, reasons = rep.passes_gate_0()
    assert not ok and any("niezmienn" in r for r in reasons)


# --- Ręczna akceptacja godzin awarii (ADR-045) ------------------------------

def _outage_report(outage: dt.datetime, weeks: int = 12):
    hrs = weekday_hours(MONDAY, weeks)
    return build_report({s: bars(_without(hrs, [outage]))
                         for s in ("EURUSD", "GBPUSD", "USDJPY")})


def _accept(ts: dt.datetime) -> AcceptedOutage:
    return AcceptedOutage(ts=ts, reason="sprawdzone ręcznie",
                          evidence="otoczenie: dane przed i po", accepted_on="2026-09-21")


def test_accepted_outage_does_not_block_gate_0():
    outage = dt.datetime(2019, 3, 19, 10, tzinfo=UTC)
    rep = _outage_report(outage)

    assert not rep.passes_gate_0()[0], "bez listy akceptacji ma nadal blokować"
    ok, reasons = rep.passes_gate_0(accepted=[_accept(outage)])
    assert ok, reasons


def test_detector_is_not_weakened_by_acceptance():
    """Zaakceptowana godzina nadal JEST wykrywana — lista zmienia werdykt, nie detekcję."""
    outage = dt.datetime(2019, 3, 19, 10, tzinfo=UTC)
    rep = _outage_report(outage)

    rep.passes_gate_0(accepted=[_accept(outage)])

    assert rep.suspected_outages["ts"].to_list() == [outage]


def test_outage_outside_the_accept_list_still_blocks():
    """Rdzeń ADR-045: akceptacja jest punktowa, nie hurtowa."""
    hrs = weekday_hours(MONDAY, 12)
    known = dt.datetime(2019, 3, 19, 10, tzinfo=UTC)
    new = dt.datetime(2019, 4, 2, 14, tzinfo=UTC)
    rep = build_report({s: bars(_without(hrs, [known, new]))
                        for s in ("EURUSD", "GBPUSD", "USDJPY")})

    ok, reasons = rep.passes_gate_0(accepted=[_accept(known)])

    assert not ok
    assert any("awarię feedu" in r for r in reasons)
    outstanding, matched, unmatched = rep.partition_outages([_accept(known)])
    assert outstanding == [new]
    assert [a.ts for a in matched] == [known]
    assert unmatched == []


def test_accept_entry_matching_nothing_is_reported_not_silent():
    """Literówka w dacie nie może zniknąć — lista ma opisywać dane."""
    outage = dt.datetime(2019, 3, 19, 10, tzinfo=UTC)
    typo = dt.datetime(2019, 3, 19, 11, tzinfo=UTC)      # godzina obok
    rep = _outage_report(outage)

    ok, _ = rep.passes_gate_0(accepted=[_accept(typo)])
    outstanding, matched, unmatched = rep.partition_outages([_accept(typo)])

    assert not ok, "prawdziwa awaria musi nadal blokować przy literówce"
    assert outstanding == [outage] and matched == []
    assert [a.ts for a in unmatched] == [typo]
    assert "nie odpowiada" in render_markdown(rep, [_accept(typo)])


def test_report_prints_acceptance_with_evidence():
    outage = dt.datetime(2019, 3, 19, 10, tzinfo=UTC)
    rep = _outage_report(outage)

    md = render_markdown(rep, [_accept(outage)])

    assert "Bramka 0: **PRZECHODZI**" in md
    assert "Zaakceptowane ręcznie (ADR-045)" in md
    assert "otoczenie: dane przed i po" in md       # dowód, nie tylko data
    assert "2026-09-21" in md
    assert "2019-03-19 10:00" in md


def test_accepted_outages_from_config_requires_all_four_fields():
    full = {"hour_utc": "2016-09-02T18:00:00+00:00", "reason": "r",
            "evidence": "e", "accepted_on": "2026-09-21"}
    cfg = {"data": {"quality": {"accepted_outages": [full]}}}
    got = accepted_outages_from(cfg)
    assert got == [AcceptedOutage(dt.datetime(2016, 9, 2, 18, tzinfo=UTC),
                                  "r", "e", "2026-09-21")]

    for field in ("reason", "evidence", "accepted_on", "hour_utc"):
        broken = {k: v for k, v in full.items() if k != field}
        with pytest.raises(ValueError, match="ADR-045|brak pól"):
            accepted_outages_from({"data": {"quality": {"accepted_outages": [broken]}}})

    with pytest.raises(ValueError, match="strefy"):
        accepted_outages_from({"data": {"quality": {"accepted_outages": [
            {**full, "hour_utc": "2016-09-02T18:00:00"}]}}})


def test_missing_accept_list_accepts_nothing():
    """Brak sekcji w configu znaczy „nic nie zaakceptowano”, nie „wszystko OK”."""
    outage = dt.datetime(2019, 3, 19, 10, tzinfo=UTC)
    rep = _outage_report(outage)

    assert accepted_outages_from({}) == []
    assert accepted_outages_from({"data": {"quality": {}}}) == []
    assert not rep.passes_gate_0(accepted=accepted_outages_from({}))[0]


def test_config_accepts_exactly_the_three_audited_hours():
    """Pozycje z ADR-045 muszą odpowiadać temu, co wskazał detektor na 2015-2021."""
    import yaml
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text())
    got = {a.ts for a in accepted_outages_from(cfg)}
    assert got == {
        dt.datetime(2016, 9, 2, 18, tzinfo=UTC),
        dt.datetime(2017, 12, 24, 22, tzinfo=UTC),
        dt.datetime(2019, 5, 26, 22, tzinfo=UTC),
    }
    for a in accepted_outages_from(cfg):
        assert a.evidence.strip() and a.reason.strip() and a.accepted_on == "2026-09-21"


# --- Renderowanie -----------------------------------------------------------

def test_markdown_states_verdict_and_spread():
    hrs = weekday_hours(MONDAY, 6)
    md = render_markdown(build_report({s: bars(hrs) for s in ("EURUSD", "GBPUSD")}))
    assert "Bramka 0: **PRZECHODZI**" in md
    assert "| EURUSD |" in md
    assert "0.30" in md          # spread 3e-5 => 0.30 pipsa


def test_truncated_series_is_reported_as_gaps_not_as_clean():
    """Symbol, którego dane urywają się wcześniej, nie może wyglądać idealnie."""
    hrs = weekday_hours(MONDAY, 12)
    rep = build_report({
        "EURUSD": bars(hrs[:len(hrs)//2]),    # urwane w połowie zakresu
        "GBPUSD": bars(hrs),
        "USDJPY": bars(hrs),
    })
    eur = rep.symbol_coverage.filter(pl.col("symbol") == "EURUSD").row(0, named=True)
    assert eur["gap_pct"] > 40, f"obcięcie niewykryte: {eur['gap_pct']:.1f}%"
    gbp = rep.symbol_coverage.filter(pl.col("symbol") == "GBPUSD").row(0, named=True)
    assert gbp["gap_pct"] == pytest.approx(0.0)
