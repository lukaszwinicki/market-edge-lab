#!/usr/bin/env python3
"""M06 — zero przyrządu po doliczeniu finansowania (ADR-016). Kontrola, NIE próba.

PYTANIE

Jakie jest expectancy wejść losowych po PEŁNYM koszcie — spread, podłoga,
poślizg **i marża swapu** — i czy przyrząd nadal ma poprawne zero.

CO TU JEST NOWEGO, A CO NIE

Kalibracja M03 brzmiała: expectancy wejść losowych = −koszt, w granicach
1 SE. Po doliczeniu członu finansowania **reszta tej kalibracji się nie
zmienia**, i to nie jest wynik empiryczny, tylko tożsamość: swap odejmuje
się od obu stron równania naraz. Ten przebieg tego NIE odkrywa — on to
pokazuje i zapisuje, żeby nikt nie próbował tego mierzyć drugi raz.

Nowe jest co innego, i to jest właściwa treść M06:

1. **Zero pełnego modelu kosztu** — liczba, wobec której warstwa B T003
   będzie się mierzyć. Dotąd znane było zero modelu NIEPEŁNEGO.
2. **Sprawdzenie złożenia** — `execution/costs.py` liczy swap z `TradeResult`,
   M03 liczył go własną pętlą. Obie liczby muszą być identyczne.
3. **SE w konwencji projektu** — block bootstrap po dniu, nie naiwne SE.
   Różnica jest 1,75×, więc konwencja nie jest szczegółem.

BEZ NOWEJ SYMULACJI

Przebieg czyta artefakty M03 i nie rusza symulatora. Koszt finansowania
zależy wyłącznie od ceny, dystansu stopu i czasów wejścia/wyjścia, a te są
zapisane. Powtórzenie symulacji dałoby te same transakcje przy tym samym
ziarnie i kosztowało godzinę — nie kupując ani jednej nowej obserwacji.
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

from src.execution.costs import (  # noqa: E402
    attach_swap, margins_from_config, net_column, reportable, swap_column,
)
from src.harness.registry import start_run  # noqa: E402
from src.validation.bootstrap import block_bootstrap_expectancy  # noqa: E402

M03_RUN = "20260923T175353Z-087adf"
HORIZONS = (3, 10)
SE_TOLERANCE = 1.0          # kryterium M03: |luka| < 1 SE


def load_config() -> dict:
    return yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))


def recompose(trades: pl.DataFrame, margins: tuple[float, ...]) -> pl.DataFrame:
    """Policz swap od nowa, naszym modułem, na tych samych transakcjach."""
    stripped = trades.drop([c for c in trades.columns if c.startswith("swap_r_")])
    return attach_swap(stripped, margins, entry_col="ts")


def composition_check(stored: pl.DataFrame, fresh: pl.DataFrame,
                      margins: tuple[float, ...]) -> dict:
    """Czy złożenie po fakcie odtwarza liczby M03 co do bitu."""
    out = {}
    for m in margins:
        a = stored[f"swap_r_{m}"].to_numpy()
        b = fresh[swap_column(m)].to_numpy()
        out[str(m)] = {
            "max_abs_diff": float(np.abs(a - b).max()),
            "identical": bool(np.array_equal(a, b)),
        }
    return out


def calibration(trades: pl.DataFrame, cfg: dict, margins: tuple[float, ...]) -> dict:
    """Zero przyrządu przy pełnym koszcie, per marża, konwencją projektu."""
    b = cfg["validation"]["bootstrap"]
    reportable(trades, margins)
    modelled = float(trades["cost_r"].mean())

    out = {"modelled_cost_r": modelled, "per_margin": {}}
    for m in margins:
        boot = block_bootstrap_expectancy(
            trades, block_days=b["block_days"], n_reps=b["reps"],
            seed=0, value=net_column(m))
        swap_mean = float(trades[swap_column(m)].mean())
        full = modelled + swap_mean
        gap = boot.expectancy + full
        out["per_margin"][str(m)] = {
            "expectancy_net": boot.expectancy,
            "se": boot.se,
            "ci_low": boot.ci_low,
            "ci_high": boot.ci_high,
            "swap_r_mean": swap_mean,
            "swap_over_modelled": swap_mean / modelled if modelled else None,
            "full_cost_r": full,
            "gap": gap,
            "gap_in_se": gap / boot.se if boot.se else None,
            "passes": bool(abs(gap / boot.se) < SE_TOLERANCE) if boot.se else None,
            "n_trades": boot.n_trades,
            "n_days": boot.n_days,
        }
    return out


def main() -> int:
    cfg = load_config()
    margins = margins_from_config(cfg)
    src = ROOT / "runs" / M03_RUN
    if not src.exists():
        raise SystemExit(f"brak artefaktow M03: {src}")

    params = {
        "adr": "ADR-016",
        "source_run": M03_RUN,
        "margins": list(margins),
        "horizons_business_days": list(HORIZONS),
        "se_convention": "block bootstrap po dniu (validation.bootstrap)",
        "se_tolerance": SE_TOLERANCE,
        "new_simulation": False,
    }

    with start_run("M06 zero przyrzadu po doliczeniu finansowania (ADR-016)",
                   params, kind="control") as run:
        report: dict = {"params": params, "horizons": {}}

        for h in HORIZONS:
            stored = pl.read_parquet(src / f"m03_trades_h{h}.parquet")
            fresh = recompose(stored, margins)
            comp = composition_check(stored, fresh, margins)
            cal = calibration(fresh, cfg, margins)

            # Tożsamość, nie pomiar: luka kalibracji nie zależy od marży.
            gaps = [v["gap"] for v in cal["per_margin"].values()]
            cal["gap_invariant_to_margin"] = bool(
                max(gaps) - min(gaps) < 1e-9)

            report["horizons"][str(h)] = {"composition": comp, "calibration": cal}
            print(f"  h={h}d  n={stored.height}  zlozenie identyczne: "
                  f"{all(v['identical'] for v in comp.values())}")
            for m in margins:
                e = cal["per_margin"][str(m)]
                print(f"    marza {m:<6} E[net]={e['expectancy_net']:+.5f}  "
                      f"pelny koszt={e['full_cost_r']:.5f}  "
                      f"luka={e['gap']:+.5f} ({e['gap_in_se']:+.2f} SE)  "
                      f"{'PRZECHODZI' if e['passes'] else 'NIE PRZECHODZI'}")

        passes = all(v["passes"] for h in HORIZONS
                     for v in report["horizons"][str(h)]["calibration"]["per_margin"].values())
        identical = all(v["identical"] for h in HORIZONS
                        for v in report["horizons"][str(h)]["composition"].values())
        report["verdict"] = {
            "composition_bit_identical": identical,
            "calibration_passes_all_margins": passes,
            "headline": "PRZECHODZI" if (passes and identical) else "NIE PRZECHODZI",
        }

        (run.dir / "m06_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        run.record(**report["verdict"])
        print(f"\nWerdykt: {report['verdict']['headline']}")
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
