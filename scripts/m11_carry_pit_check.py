#!/usr/bin/env python3
"""M11 — cecha carry point-in-time wobec bieżącego vintage. Kontrola, N bez zmian.

PYTANIE

M09A i M10 skalibrowano na bieżącym vintage z przybliżonym opóźnieniem
2 miesięcy. T004 użyje cechy point-in-time z ALFRED. Czy to ta sama cecha?
Trzy liczby:

* różnica PIT − bieżący vintage w dniach decyzji (rewizje + faktyczne
  opóźnienie publikacji);
* geometria PIT (zmienność w czasie, rozrzut między parami) wobec M09A —
  jeżeli odbiega o więcej niż tolerancja kalibracji M09B (±20%), moc z M10
  nie dotyczy cechy, którą zmierzy T004;
* dni decyzji bez żadnego dostępnego vintage.

ADR-020: skrypt nie czyta ŻADNEJ ceny. Dni decyzji to dni robocze kalendarza,
nie siatka barów.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.rates import (  # noqa: E402
    ALFRED_DIR, SERIES, load_current_vintage, pair_legs, pit_last_value,
)
from src.harness.registry import start_run  # noqa: E402

FIRST_DECISION = dt.date(2016, 1, 1)
LAST_DECISION = dt.date(2021, 12, 31)
M09A_RUN = "20260924T202237Z-ff858a"
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD"]
LAG_MONTHS_M09 = 2
GEOMETRY_TOL = 0.20             # ta sama tolerancja co kalibracja M09B


def business_days() -> list[dt.date]:
    d = np.arange(np.datetime64(FIRST_DECISION), np.datetime64(LAST_DECISION) + np.timedelta64(1, "D"))
    return [x.astype(dt.date) for x in d[np.is_busday(d)]]


def pit_rates(days: list[dt.date]) -> tuple[pl.DataFrame, dict]:
    frame = pl.DataFrame({"decision_date": days})
    info = {}
    for c in CURRENCIES:
        sid = SERIES["overnight"][c]
        v = pl.read_parquet(ALFRED_DIR / f"{sid}.parquet")
        p = pit_last_value(v, days)
        lag = ((pl.col("decision_date").dt.year() * 12 + pl.col("decision_date").dt.month())
               - (pl.col("month").dt.year() * 12 + pl.col("month").dt.month()))
        p = p.with_columns(lag.alias("lag"))
        info[c] = {"missing_days": int(p.get_column("value").null_count()),
                   "lag_months": {str(k): int(n) for k, n in
                                  p.drop_nulls("lag").group_by("lag").len().sort("lag").iter_rows()}}
        frame = frame.join(p.select("decision_date", pl.col("value").alias(c)),
                           on="decision_date", how="left")
    return frame, info


def current_rates(days: list[dt.date]) -> pl.DataFrame:
    rates = load_current_vintage("overnight", CURRENCIES, dt.date(2015, 1, 1),
                                 dt.date(2021, 12, 1))
    months = {m: i for i, m in enumerate(rates.get_column("month").to_list())}
    idx = []
    for d in days:
        y, m = d.year, d.month - LAG_MONTHS_M09
        while m <= 0:
            y, m = y - 1, m + 12
        idx.append(months[dt.date(y, m, 1)])
    return rates[idx].drop("month").with_columns(pl.Series("decision_date", days))


def carry(frame: pl.DataFrame, symbol: str) -> np.ndarray:
    b, q = pair_legs(symbol)
    return (frame.get_column(b) - frame.get_column(q)).to_numpy()


def main() -> int:
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    symbols = list(cfg["instruments"]["discovery"])
    m09a = json.loads((ROOT / "runs" / M09A_RUN / "m09a_report.json").read_text(encoding="utf-8"))
    target = m09a["kinds"]["overnight"]["pairs"]
    params = {"adr": "ADR-020, ADR-023, ADR-024",
              "exception": "ADR-020 — cecha carry PIT vs biezacy vintage, bez cen",
              "decision_days": [FIRST_DECISION.isoformat(), LAST_DECISION.isoformat()],
              "geometry_tol": GEOMETRY_TOL, "criterion_set_before_run": True,
              "looks_forward": False}
    with start_run("M11 cecha carry point-in-time vs biezacy vintage (ADR-020, bez "
                   "spojrzenia w przod)", params, kind="control") as run:
        days = business_days()
        pit, info = pit_rates(days)
        cur = current_rates(days)
        complete = pit.drop_nulls()
        report: dict = {"params": params, "n_days": len(days),
                        "n_days_complete": complete.height, "currency": info, "pairs": {}}
        cur_c = cur.filter(pl.col("decision_date").is_in(complete.get_column("decision_date")
                                                         .implode()))
        within, means = [], []
        for s in symbols:
            a, b = carry(complete, s), carry(cur_c, s)
            within.append(a.std(ddof=1))
            means.append(a.mean())
            report["pairs"][s] = {
                "mean_abs_diff_pit_vs_current": float(np.abs(a - b).mean()),
                "max_abs_diff": float(np.abs(a - b).max()),
                "corr_pit_current": float(np.corrcoef(a, b)[0, 1]),
                "sd_pit": float(a.std(ddof=1)),
            }
        w = float(np.sqrt(np.mean(np.square(within))))
        bt = float(np.std(means, ddof=1))
        report["geometry"] = {
            "within_pit": w, "within_m09a": target["within_pair_sd_rms"],
            "between_pit": bt, "between_m09a": target["between_pair_sd_of_means"],
        }
        ok_w = abs(w / target["within_pair_sd_rms"] - 1) <= GEOMETRY_TOL
        ok_b = abs(bt / target["between_pair_sd_of_means"] - 1) <= GEOMETRY_TOL
        report["verdict"] = {
            "criterion_set_before_run": True,
            "within_ok": bool(ok_w), "between_ok": bool(ok_b),
            "m10_power_applies": bool(ok_w and ok_b),
            "days_without_vintage": len(days) - complete.height,
        }
        (run.dir / "m11_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        run.record(**report["verdict"])
        for c, v in info.items():
            print(f"  {c}: braki {v['missing_days']} dni, opóźnienie (mies.) {v['lag_months']}")
        for s, v in report["pairs"].items():
            print(f"  {s}: |PIT − bieżący| śr. {v['mean_abs_diff_pit_vs_current']:.3f} pp, "
                  f"maks. {v['max_abs_diff']:.3f}, korelacja {v['corr_pit_current']:.4f}")
        print(json.dumps({**report["geometry"], **report["verdict"]}, indent=1))
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
