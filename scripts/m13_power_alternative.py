#!/usr/bin/env python3
"""M13 — moc testu T004 pod hipotezą ALTERNATYWNĄ. Świat syntetyczny.

DLACZEGO

M10 zmierzył rozkład statystyki pod H0 i z niego wyliczył próg
wykrywalności T004 (52,98%). Self-test runnera T004 pokazał, że pod H1 SE
z rozkładu zerowego ROŚNIE: przy zasianym ρ ≈ 0,18 z 0,014 do 0,088.
Rozkład zerowy jest warunkowy na zwrotach — gdy zwroty niosą trwały sygnał
cechy, każda losowa cecha trwała też z nimi koreluje. Próg liczony z SE pod
H0 może więc być fikcją. Tu mierzymy moc wprost.

ŻADNYCH PRAWDZIWYCH DANYCH — świat i cecha jak w M10 / self-teście T004.

REGUŁA, ZADEKLAROWANA PRZED PRZEBIEGIEM

* Moc = P(SUPPORTED) przy z = 2,8302, metoda CI z ADR-026 (rozkład zerowy).
* Jeżeli P(SUPPORTED | ρ = 0,12) < 0,50 → T004 NIE zostaje zamrożony.
  ρ = 0,12 to ≈ 53,8% trafności — efekt duży jak na FX.
* Empiryczne MDE80 = najmniejsze ρ z siatki, przy którym moc ≥ 0,80;
  zastępuje w prerejestracji liczbę wyliczoną z SE pod H0.
* Moc bootstrapu raportowana obok — NIE zmienia metody CI (ADR-026).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from m09b_carry_null import CURRENCIES, pair_matrix, psd_chol, simulate_rates  # noqa: E402
from m10_se_coverage import SYMBOLS, decision_rows, month_of, simulate_fwd, time_axis  # noqa: E402
from src.harness.registry import start_run  # noqa: E402
from t004_carry import (  # noqa: E402
    FEATURE, FIRST_MONTH, M09B_RUN, M12_RUN, MODELS, make_null_sd, run_cell,
)

RHO_GRID = (0.0, 0.03, 0.054, 0.08, 0.12, 0.18)
N_WORLDS = 50
REPS = 80
SEED = 20261002
Z_SUP = 2.8302
RHO_BE = 0.05401

# --- Reguła, ZADEKLAROWANA PRZED PRZEBIEGIEM -----------------------------
GATE_RHO = 0.12
GATE_POWER = 0.50
MDE_POWER = 0.80


def main() -> int:
    m12 = json.loads((ROOT / "runs" / M12_RUN / "m09a_report.json").read_text(encoding="utf-8"))
    geom = m12["kinds"]["policy"]["currency"]
    b = json.loads((ROOT / "runs" / M09B_RUN / "m09b_report.json").read_text(encoding="utf-8"))
    calib = {m: b["models"][m]["calibration"] for m in MODELS}
    m05 = json.loads((ROOT / "runs" / "20260924T134703Z-cd0d96" / "m05_report.json")
                     .read_text(encoding="utf-8"))["horizons"]["3"]
    perm = [m05["symbols"].index(s) for s in SYMBOLS]
    chol_ret = psd_chol(np.asarray(m05["rho_matrix"])[np.ix_(perm, perm)])

    ts_h, _ = time_axis()
    rows = decision_rows(ts_h)
    p = len(SYMBOLS)
    mon = np.repeat(month_of(ts_h[rows], FIRST_MONTH, 0), p)
    rsym = np.tile(np.arange(p), rows.size)
    ts = pl.Series("ts_decision", np.repeat(ts_h[rows], p).astype("datetime64[ms]")
                   ).dt.replace_time_zone("UTC")
    phi = np.array([geom["per_currency"][c]["phi"] for c in CURRENCIES])
    sig = np.array([geom["per_currency"][c]["sigma_innov"] for c in CURRENCIES])
    chol_r = psd_chol(np.asarray(geom["innovation_corr"]))
    pm = pair_matrix(SYMBOLS, CURRENCIES)
    null_sd = make_null_sd(mon, rsym, SYMBOLS, geom, calib, reps=REPS, seed=1)

    params = {"data": "WYLACZNIE syntetyczne", "rho_grid": list(RHO_GRID),
              "n_worlds": N_WORLDS, "reps": REPS, "seed": SEED, "z_supported": Z_SUP,
              "gate_rho": GATE_RHO, "gate_power": GATE_POWER, "mde_power": MDE_POWER,
              "criterion_set_before_run": True,
              "inputs": {"m12": M12_RUN, "m09b": M09B_RUN}}
    with start_run("M13 moc testu T004 pod hipoteza alternatywna, swiat syntetyczny",
                   params, kind="control") as run:
        rng = np.random.default_rng(SEED)
        report: dict = {"params": params, "grid": {}}
        for rho_t in RHO_GRID:
            res = {"rho_hat": [], "se_null": [], "se_boot": [],
                   "sup_null": [], "sup_boot": [], "fal_null": []}
            for _ in range(N_WORLDS):
                carry = (simulate_rates(rng, int(mon.max()) + 1, phi,
                                        sig * calib["ar1_measured"]["sigma_mult"], chol_r,
                                        geom["level_pooled_mean"],
                                        calib["ar1_measured"]["level_sd"],
                                        geom["level_pooled_mean"]) @ pm.T)[mon, rsym]
                f0 = simulate_fwd(rng, ts_h.size, chol_ret, "gauss", rows).ravel()
                z = (carry - carry.mean()) / carry.std()
                fwd = rho_t * z * f0.std() + np.sqrt(1 - rho_t ** 2) * f0
                c = run_cell(pl.DataFrame({"ts_decision": ts, FEATURE: carry, "fwd_atr": fwd}),
                             null_sd, z_supported=Z_SUP, rho_breakeven=RHO_BE,
                             block_days=20, boot_reps=REPS, aged=False)
                r = c["spearman"]
                res["rho_hat"].append(r)
                res["se_null"].append(c["se_null"])
                res["se_boot"].append(c["se_boot"])
                res["sup_null"].append(r - Z_SUP * c["se_null"] > 0)
                res["sup_boot"].append(r - Z_SUP * c["se_boot"] > 0)
                res["fal_null"].append(abs(r) + 1.96 * c["se_null"] < RHO_BE)
            e = {"rho_hat_mean": float(np.mean(res["rho_hat"])),
                 "acc_pct": float(50 + 100 * np.arcsin(rho_t) / np.pi),
                 "se_null_median": float(np.median(res["se_null"])),
                 "se_boot_median": float(np.median(res["se_boot"])),
                 "power_null": float(np.mean(res["sup_null"])),
                 "power_boot": float(np.mean(res["sup_boot"])),
                 "p_falsified_null": float(np.mean(res["fal_null"]))}
            report["grid"][str(rho_t)] = e
            print(f"  rho={rho_t:<5} ({e['acc_pct']:.2f}%)  rho_hat={e['rho_hat_mean']:+.4f}  "
                  f"SE_null={e['se_null_median']:.4f}  SE_boot={e['se_boot_median']:.4f}  "
                  f"moc null={e['power_null']:.2f}  moc boot={e['power_boot']:.2f}  "
                  f"P(FALSIFIED)={e['p_falsified_null']:.2f}", flush=True)

        G = report["grid"]
        mde = next((float(k) for k in G if float(k) > 0 and G[k]["power_null"] >= MDE_POWER), None)
        report["verdict"] = {
            "criterion_set_before_run": True,
            "power_null_at_gate": G[str(GATE_RHO)]["power_null"],
            "gate_passed": bool(G[str(GATE_RHO)]["power_null"] >= GATE_POWER),
            "empirical_mde80_rho": mde,
            "empirical_mde80_acc_pct": None if mde is None else float(50 + 100 * np.arcsin(mde) / np.pi),
            "size_null": G["0.0"]["power_null"],
        }
        (run.dir / "m13_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        run.record(**report["verdict"])
        print(json.dumps(report["verdict"], indent=1))
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
