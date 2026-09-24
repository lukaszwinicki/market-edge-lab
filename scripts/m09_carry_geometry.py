#!/usr/bin/env python3
"""M09 krok A — geometria cechy carry (H04). Kontrola, NIE próba. N bez zmian.

PYTANIE (ADR-022)

Zanim H04 dostanie plan trialu: jak trwała, jak zmienna i jak skorelowana
między walutami jest różnica stóp? Te liczby parametryzują surogat kroku B
(`m09b_carry_null.py`), który mierzy n_eff i osiągalność `FALSIFIED`.

Znane ryzyko z góry: stopy EUR i JPY stały przy zerze w 2016–2021. Jeżeli
cecha prawie się nie rusza, relację identyfikuje wyłącznie przekrój sześciu
par — i to jest pytanie o moc, nie o wynik.

ADR-020 — GRANICA

H04 nie ma żywej prerejestracji. Skrypt:

* nie importuje siatki decyzyjnej, warstwy etykiet ani symulatora;
* nie czyta ŻADNEJ ceny — ani barów, ani ticków;
* liczy wyłącznie statystyki cechy na niej samej.

Dane: bieżący vintage (`src/data/rates.py`) — dopuszczalny WYŁĄCZNIE do
geometrii. Pilnuje tego `tests/test_m09_carry.py`, czytając źródło.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.rates import (  # noqa: E402
    SERIES, MissingRatesError, ar1_fit, load_current_vintage, pair_carry,
)
from src.harness.registry import start_run  # noqa: E402

LOAD_FROM = dt.date(2015, 1, 1)
LOAD_TO = dt.date(2021, 12, 1)
# Miesiące widoczne dla decyzji 2016-01 … 2021-12 przy opóźnieniu 2 miesięcy.
VISIBLE_FROM = dt.date(2015, 11, 1)
VISIBLE_TO = dt.date(2021, 10, 1)
LAG_MONTHS = 2
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD"]
KINDS = ("overnight", "interbank_3m")


def sign_changes(x: np.ndarray) -> int:
    s = np.sign(x)
    s = s[s != 0]
    return int((s[1:] != s[:-1]).sum())


def currency_params(rates, window: slice) -> dict:
    """Parametry surogatu na poziomie waluty: φ, σ innowacji, korelacja
    innowacji, rozkład poziomów w pierwszym widocznym miesiącu."""
    out, resid = {}, []
    for c in CURRENCIES:
        x = rates.get_column(c).to_numpy()[window]
        phi, sig = ar1_fit(x)
        out[c] = {"phi": phi, "sigma_innov": sig, "level_first": float(x[0]),
                  "level_mean": float(x.mean()), "level_min": float(x.min()),
                  "level_max": float(x.max())}
        resid.append(np.diff(x))
    corr = np.corrcoef(np.vstack(resid))
    firsts = np.array([out[c]["level_first"] for c in CURRENCIES])
    return {
        "per_currency": out,
        "innovation_corr": corr.round(4).tolist(),
        "level_first_mean": float(firsts.mean()),
        "level_first_sd": float(firsts.std(ddof=1)),
        "level_pooled_mean": float(np.mean([out[c]["level_mean"] for c in CURRENCIES])),
    }


def pair_geometry(rates, symbols: list[str], window: slice) -> dict:
    per, means, within = {}, [], []
    for s in symbols:
        x = pair_carry(rates, s)[window]
        phi, sig = ar1_fit(x)
        per[s] = {"mean": float(x.mean()), "sd_over_time": float(x.std(ddof=1)),
                  "min": float(x.min()), "max": float(x.max()),
                  "sign_changes": sign_changes(x),
                  "share_positive": float((x > 0).mean()),
                  "phi": phi, "sigma_innov": sig,
                  "range": float(x.max() - x.min())}
        means.append(x.mean())
        within.append(x.std(ddof=1))
    between = float(np.std(means, ddof=1))
    within_rms = float(np.sqrt(np.mean(np.square(within))))
    return {
        "per_pair": per,
        "between_pair_sd_of_means": between,
        "within_pair_sd_rms": within_rms,
        "between_to_within": between / within_rms if within_rms > 0 else None,
    }


def main() -> int:
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    symbols = list(cfg["instruments"]["discovery"])
    params = {
        "adr": "ADR-020, ADR-022",
        "exception": "ADR-020 — geometria cechy carry, bez cen i bez zwrotow w przod",
        "vintage": "current (tylko geometria)",
        "series": {k: SERIES[k] for k in KINDS},
        "visible_months": [VISIBLE_FROM.isoformat(), VISIBLE_TO.isoformat()],
        "lag_months": LAG_MONTHS,
        "symbols": symbols,
        "looks_forward": False,
    }
    with start_run("M09A geometria cechy carry H04 pod audyt mocy (ADR-020, ADR-022, "
                   "bez spojrzenia w przod)", params, kind="control") as run:
        report: dict = {"params": params, "kinds": {}}
        for kind in KINDS:
            try:
                rates = load_current_vintage(kind, CURRENCIES, LOAD_FROM, LOAD_TO)
            except MissingRatesError as e:
                # Luka w danych nie jest interpolowana — seria wypada jako UNKNOWN.
                report["kinds"][kind] = {"status": "UNKNOWN", "reason": str(e)}
                print(f"\n[{kind}] UNKNOWN — {e}")
                continue
            months = rates.get_column("month").to_list()
            w = slice(months.index(VISIBLE_FROM), months.index(VISIBLE_TO) + 1)
            report["kinds"][kind] = {
                "n_months": w.stop - w.start,
                "currency": currency_params(rates, w),
                "pairs": pair_geometry(rates, symbols, w),
            }
            g = report["kinds"][kind]
            print(f"\n[{kind}] {g['n_months']} miesięcy widocznych")
            for c, v in g["currency"]["per_currency"].items():
                print(f"  {c}: poziom {v['level_min']:+.2f}…{v['level_max']:+.2f}  "
                      f"phi={v['phi']:.3f}  sigma={v['sigma_innov']:.3f}")
            for s, v in g["pairs"]["per_pair"].items():
                print(f"  {s}: carry {v['min']:+.2f}…{v['max']:+.2f} (śr. {v['mean']:+.2f}, "
                      f"sd {v['sd_over_time']:.2f})  zmian znaku {v['sign_changes']}  "
                      f"phi={v['phi']:.3f}")
            print(f"  przekrój/czas: sd średnich {g['pairs']['between_pair_sd_of_means']:.2f} "
                  f"/ sd w czasie {g['pairs']['within_pair_sd_rms']:.2f}")

        (run.dir / "m09a_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        run.record(**{f"{k}_between_to_within": report["kinds"][k]["pairs"]["between_to_within"]
                      for k in KINDS if "pairs" in report["kinds"][k]})
        print(f"\nArtefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
