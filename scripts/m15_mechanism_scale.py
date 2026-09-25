#!/usr/bin/env python3
"""M15 — jak duży efekt w warstwie A może w ogóle dać mechanizm carry?

PYTANIE (ADR-030)

M09–M14 mierzyły precyzję przyrządu. Nikt nie policzył, ile waży to, co
przyrząd ma zważyć. Carry zarabia na różnicy stóp: przy dryfie ceny równym
`m` × różnica stóp oczekiwany zwrot na h dni to m · Δi · h / 252, a jego
relacja z ceną to ρ ≈ SD(dryfu) / SD(zwrotu h-dniowego). Porównujemy to
z progiem opłacalności ρ_be = 0,05401.

m = 1 to pełna różnica stóp w cenie; klasyczne ujęcie (kurs = błądzenie
losowe) daje m = 0 — wtedy zysk carry siedzi wyłącznie w odsetkach, czyli
w warstwie B. m = 2 to skrajna anomalia UIP (Fama β = −1).

DANE: geometria cechy z M12 (bez zwrotów) i zmienność dzienna sześciu par
z RESEARCH 2016–2021 (bez cechy, bez zwrotów w przód — segment oglądany
w T003). Cecha NIE jest zestawiana ze zwrotem. `INFERENCE`: dryf liniowy,
Pearson jako przybliżenie Spearmana.
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

from src.harness.market import load_h1  # noqa: E402
from src.harness.registry import start_run  # noqa: E402

UTC = dt.timezone.utc
M12_RUN = "20260924T212921Z-b1fcdc"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY"]
START = dt.datetime(2016, 1, 1, tzinfo=UTC)
END = dt.datetime(2021, 12, 31, tzinfo=UTC)
H_DAYS = 3
YEAR_DAYS = 252
RHO_BE = 0.05401
DRIFT_MULTIPLIERS = (0.5, 1.0, 2.0)

# --- Reguła, ZADEKLAROWANA PRZED PRZEBIEGIEM -----------------------------
# Hipoteza jest mierzalna w warstwie A tylko wtedy, gdy ρ przewidywane przy
# m = 2 (skrajny, ale udokumentowany przypadek) sięga progu opłacalności.
GATE_MULTIPLIER = 2.0


def implied_rho(feature_sd_pp: float, ret_sd: float, multiplier: float,
                h_days: int = H_DAYS) -> float:
    """ρ ≈ SD dryfu / SD zwrotu; dryf = m · Δi[pp] / 100 · h / 252."""
    return multiplier * feature_sd_pp / 100 * h_days / YEAR_DAYS / ret_sd


def h_day_return_sd(close: np.ndarray, h_days: int = H_DAYS) -> float:
    """SD sumy h kolejnych dziennych zwrotów logarytmicznych."""
    lr = np.diff(np.log(close))
    return float(np.convolve(lr, np.ones(h_days), "valid").std())


def main() -> int:
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    g = json.loads((ROOT / "runs" / M12_RUN / "m09a_report.json")
                   .read_text(encoding="utf-8"))["kinds"]["policy"]["pairs"]
    feature_sd = float(np.hypot(g["between_pair_sd_of_means"], g["within_pair_sd_rms"]))
    params = {"adr": "ADR-030", "m12_run": M12_RUN, "symbols": SYMBOLS,
              "segment": "RESEARCH 2016-2021, zmiennosc bez cechy", "h_days": H_DAYS,
              "rho_breakeven": RHO_BE, "drift_multipliers": list(DRIFT_MULTIPLIERS),
              "gate_multiplier": GATE_MULTIPLIER, "criterion_set_before_run": True}
    with start_run("M15 skala efektu przewidywana przez mechanizm carry (ADR-030)",
                   params, kind="control") as run:
        per_pair = {}
        for s in SYMBOLS:
            df = load_h1(s, START, END, cfg)
            daily = (df.group_by_dynamic(df.columns[0], every="1d")
                     .agg(pl.col("bid_close").last()).drop_nulls())
            per_pair[s] = h_day_return_sd(daily["bid_close"].to_numpy())
        ret_sd = float(np.sqrt(np.mean(np.square(list(per_pair.values())))))
        rho = {str(m): implied_rho(feature_sd, ret_sd, m) for m in DRIFT_MULTIPLIERS}
        verdict = {
            "criterion_set_before_run": True,
            "feature_sd_pp": feature_sd, "ret_sd_h": ret_sd,
            "implied_rho": rho,
            "rho_at_gate_over_breakeven": rho[str(GATE_MULTIPLIER)] / RHO_BE,
            "layer_a_can_reach_breakeven": bool(rho[str(GATE_MULTIPLIER)] >= RHO_BE),
        }
        report = {"params": params, "ret_sd_per_pair": per_pair, "verdict": verdict}
        (run.dir / "m15_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        run.record(**{k: v for k, v in verdict.items() if k != "implied_rho"},
                   implied_rho_m2=rho[str(GATE_MULTIPLIER)])
        print(json.dumps(report, indent=1, ensure_ascii=False))
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
