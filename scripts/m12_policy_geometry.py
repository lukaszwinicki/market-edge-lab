#!/usr/bin/env python3
"""M12 — cecha carry ze stóp polityki: weryfikacja źródeł i geometria.

Kontrola, NIE próba. N bez zmian. Wyjątek ADR-020: zero cen.

DWA PYTANIA

1. Czy sześć serii stóp polityki (cztery pobrane, dwie z tabeli ręcznej)
   jest prawdziwe? Sprawdzian niezależny: średnia miesięczna naszej serii
   PIT wobec miesięcznej serii OECD overnight tej samej waluty (bieżący
   vintage — tu wolno, bo porównujemy dwa źródła stóp, nie stopę ze
   zwrotem). Różnica strukturalna (stopa polityki vs stopa rynkowa) ma
   kilka punktów bazowych; błędna pozycja w tabeli ręcznej dałaby 25 pb
   i więcej przez całe miesiące.
2. Geometria cechy (zmienność w czasie, rozrzut między parami, parametry
   AR(1) walut) w formacie raportu M09A — wejście dla M09B i M10.
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

from src.data.policy_rates import load_series, policy_pit  # noqa: E402
from src.data.rates import ar1_fit, load_current_vintage, pair_legs  # noqa: E402
from src.harness.registry import start_run  # noqa: E402

FIRST_DECISION = dt.date(2016, 1, 1)
LAST_DECISION = dt.date(2021, 12, 31)
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD"]

# --- Kryterium weryfikacji źródeł, ZADEKLAROWANE PRZED PRZEBIEGIEM --------
MONTH_DIFF_TOL = 0.20           # pp — powyżej: miesiąc podejrzany
MAX_SUSPECT_MONTHS = 2          # na walutę; zmiana w środku miesiąca tłumaczy 1–2


def business_days() -> list[dt.date]:
    d = np.arange(np.datetime64(FIRST_DECISION),
                  np.datetime64(LAST_DECISION) + np.timedelta64(1, "D"))
    return [x.astype(dt.date) for x in d[np.is_busday(d)]]


def monthly_means(days: list[dt.date], values: dict[str, np.ndarray]) -> pl.DataFrame:
    df = pl.DataFrame({"date": days, **values})
    return (df.group_by(pl.col("date").dt.truncate("1mo").alias("month"))
            .agg([pl.col(c).mean() for c in values]).sort("month"))


def safe_corr(x: np.ndarray) -> np.ndarray:
    """Korelacja przyrostów; waluta bez zmian (JPY) dostaje zera poza
    przekątną zamiast NaN — brak ruchu to brak korelacji, nie błąd."""
    sd = x.std(axis=1)
    c = np.eye(x.shape[0])
    ok = sd > 0
    if ok.sum() >= 2:
        c[np.ix_(ok, ok)] = np.corrcoef(x[ok])
    return c


def main() -> int:
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    symbols = list(cfg["instruments"]["discovery"])
    params = {"adr": "ADR-020, ADR-025",
              "exception": "ADR-020 — stopy polityki, weryfikacja i geometria, bez cen",
              "month_diff_tol": MONTH_DIFF_TOL, "max_suspect_months": MAX_SUSPECT_MONTHS,
              "criterion_set_before_run": True, "symbols": symbols,
              "looks_forward": False}
    with start_run("M12 stopy polityki: weryfikacja zrodel i geometria cechy carry "
                   "(ADR-020, ADR-025, bez spojrzenia w przod)", params, kind="control") as run:
        days = business_days()
        pit = {c: policy_pit(load_series(c), days) for c in CURRENCIES}
        missing = {c: int(np.isnan(v).sum()) for c, v in pit.items()}
        mm = monthly_means(days, pit)

        oecd = load_current_vintage("overnight", CURRENCIES, dt.date(2016, 1, 1),
                                    dt.date(2021, 12, 1))
        check = {}
        for c in CURRENCIES:
            d = mm.get_column(c).to_numpy() - oecd.get_column(c).to_numpy()
            suspect = [str(m) for m, x in zip(mm.get_column("month").to_list(), d)
                       if abs(x) > MONTH_DIFF_TOL]
            check[c] = {"mean_abs_diff": float(np.abs(d).mean()),
                        "max_abs_diff": float(np.abs(d).max()),
                        "mean_diff": float(d.mean()),
                        "suspect_months": suspect,
                        "ok": len(suspect) <= MAX_SUSPECT_MONTHS}

        # Geometria w formacie M09A.
        levels = np.vstack([mm.get_column(c).to_numpy() for c in CURRENCIES])
        per_ccy = {}
        for i, c in enumerate(CURRENCIES):
            x = levels[i]
            phi, sig = (ar1_fit(x) if x.std() > 0 else (1.0, 0.0))
            per_ccy[c] = {"phi": phi, "sigma_innov": sig, "level_first": float(x[0]),
                          "level_mean": float(x.mean()), "level_min": float(x.min()),
                          "level_max": float(x.max())}
        firsts = levels[:, 0]
        currency = {
            "per_currency": per_ccy,
            "innovation_corr": safe_corr(np.diff(levels, axis=1)).round(4).tolist(),
            "level_first_mean": float(firsts.mean()),
            "level_first_sd": float(firsts.std(ddof=1)),
            "level_pooled_mean": float(levels.mean()),
        }
        per_pair, means, within = {}, [], []
        for s in symbols:
            b, q = pair_legs(s)
            x = mm.get_column(b).to_numpy() - mm.get_column(q).to_numpy()
            per_pair[s] = {"mean": float(x.mean()), "sd_over_time": float(x.std(ddof=1)),
                           "min": float(x.min()), "max": float(x.max())}
            means.append(x.mean())
            within.append(x.std(ddof=1))
        w = float(np.sqrt(np.mean(np.square(within))))
        bt = float(np.std(means, ddof=1))
        report = {
            "params": params, "n_days": len(days), "missing_days": missing,
            "source_check": check,
            "kinds": {"policy": {"n_months": mm.height, "currency": currency,
                                 "pairs": {"per_pair": per_pair,
                                           "between_pair_sd_of_means": bt,
                                           "within_pair_sd_rms": w,
                                           "between_to_within": bt / w}}},
            "verdict": {"criterion_set_before_run": True,
                        "sources_ok": all(v["ok"] for v in check.values()),
                        "no_missing_days": not any(missing.values()),
                        "within_pair_sd_rms": w, "between_pair_sd_of_means": bt},
        }
        # M09B czyta `params.symbols` — ten sam kształt co M09A.
        (run.dir / "m09a_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        run.record(**report["verdict"])
        for c, v in check.items():
            print(f"  {c}: |nasza − OECD| śr. {v['mean_abs_diff']:.3f} pp (znak {v['mean_diff']:+.3f}), "
                  f"maks. {v['max_abs_diff']:.3f}, podejrzane mies. {v['suspect_months']} "
                  f"{'OK' if v['ok'] else 'NIE'}")
        for s, v in per_pair.items():
            print(f"  {s}: carry {v['min']:+.2f}…{v['max']:+.2f} (śr. {v['mean']:+.2f}, sd {v['sd_over_time']:.2f})")
        print(json.dumps(report["verdict"], indent=1))
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
