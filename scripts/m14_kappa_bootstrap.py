#!/usr/bin/env python3
"""M14 — bootstrap skalibrowany współczynnikiem κ. Świat syntetyczny.

PYTANIE (ADR-027, opcja a)

Rozkład zerowy surogatu ma sufit mocy ~0,3 (M13). Bootstrap bloków ma moc,
ale w M10 odpadł na pokryciu pod H0 (0,85 w jednym wariancie). Czy
bootstrap z SE powiększonym o κ — dobranym na jednym zbiorze światów —
ma na DRUGIM, niezależnym zbiorze jednocześnie pokrycie pod H0, moc pod H1
i osiągalne `FALSIFIED`?

ŻADNYCH PRAWDZIWYCH DANYCH — świat i cecha jak w M10, efekt zasiany jak
w M13. Wynik mówi o przyrządzie, nie o H04.

REGUŁA, ZADEKLAROWANA PRZED PRZEBIEGIEM (stałe niżej, zatwierdzone
2026-09-25 przed napisaniem kodu)

* Kalibracja (strumień 0): κ_v = q₀,₉₅(|ρ̂ / SE_boot|) / 1,96 w każdym
  z 4 wariantów; κ = max(1, max_v κ_v). Nigdy nie zwężamy bootstrapu.
* Walidacja na światach nowych (strumienie 1 i 2), κ zamrożone:
  G1  pokrycie P(|ρ̂| ≤ 1,96·κ·SE_boot | H0) ≥ 0,90 w KAŻDYM wariancie;
  G2  moc P(ρ̂ − 2,8302·κ·SE_boot > 0 | ρ = 0,12) ≥ 0,50 w KAŻDYM wariancie;
  G3  1,96·κ·mediana(SE_boot | H0) < 0,05401 w KAŻDYM wariancie
      (ADR-022: `FALSIFIED` musi być osiągalne);
  STOP liczba fałszywych SUPPORTED pod H0 (wszystkie warianty) ≥ 9
      (nominalnie ~3,7 na 1600; p < 0,01 z rozkładu dwumianowego).
* Jeden przebieg. Brak powtórzeń i dokładania światów (ADR-026 alt. c).

SE_boot liczony tą samą funkcją co runner T004 (bloki 20 dni), ale z 200
replikacjami zamiast 2000. Szum Monte Carlo pogrubia ogony |ρ̂/SE_boot|,
więc κ wychodzi lekko zawyżone: bezpieczne dla G1, lekko na niekorzyść G3.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from multiprocessing import Pool
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")   # przed numpy: 10 procesów, nie 10×12 wątków

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from m09b_carry_null import CURRENCIES, pair_matrix, psd_chol, simulate_rates  # noqa: E402
from m10_se_coverage import (  # noqa: E402
    FEATURE_MODELS, RETURN_MODELS, SYMBOLS, decision_rows, load_inputs, month_of,
    simulate_fwd, spearman, time_axis,
)
from src.harness.registry import start_run  # noqa: E402
from src.validation.bootstrap import block_bootstrap_statistic  # noqa: E402

M12_RUN = "20260924T212921Z-b1fcdc"
M09B_RUN = "20260924T213027Z-47327e"
KIND = "policy"
FIRST_MONTH = "2016-01-01"
LAG_MONTHS = 0

VARIANTS = tuple(f"{fm}/{rm}" for fm in FEATURE_MODELS for rm in RETURN_MODELS)
Z_CI = 1.959963984540054
BLOCK_DAYS = 20
BOOT_REPS = 200
SEED = 20261010
N_WORKERS = 10

# --- Reguła, ZADEKLAROWANA PRZED PRZEBIEGIEM -----------------------------
STREAM_CAL, STREAM_H0, STREAM_H1 = 0, 1, 2
N_CAL = 400
N_VAL_H0 = 400
N_VAL_H1 = 150
RHO_GRID_H1 = (0.054, 0.08, 0.12, 0.18)
COVERAGE_TARGET = 0.95
COVERAGE_MIN = 0.90
GATE_RHO = 0.12
GATE_POWER = 0.50
MDE_POWER = 0.80
Z_SUP = 2.8302
RHO_BE = 0.05401
SIZE_STOP = 9


# --------------------------------------------------------------------------
# Reguła — czyste funkcje
# --------------------------------------------------------------------------

def world_seed(stream: int, variant: int, rho_idx: int, world: int) -> np.random.SeedSequence:
    """Seed świata: rozłączny między strumieniami z konstrukcji (spawn_key)."""
    return np.random.SeedSequence(SEED, spawn_key=(stream, variant, rho_idx, world))


def kappa_variant(rho_hat: np.ndarray, se: np.ndarray, q: float = COVERAGE_TARGET) -> float:
    """κ, przy którym |ρ̂| ≤ 1,96·κ·SE w ułamku `q` światów."""
    return float(np.quantile(np.abs(rho_hat / se), q) / Z_CI)


def kappa_combined(per_variant: dict[str, float]) -> float:
    return float(max(1.0, max(per_variant.values())))


def coverage(rho_hat: np.ndarray, se: np.ndarray, kappa: float, rho_true: float = 0.0) -> float:
    return float(np.mean(np.abs(rho_hat - rho_true) <= Z_CI * kappa * se))


def supported(rho_hat: np.ndarray, se: np.ndarray, kappa: float) -> np.ndarray:
    return rho_hat - Z_SUP * kappa * se > 0


def falsified(rho_hat: np.ndarray, se: np.ndarray, kappa: float) -> np.ndarray:
    half = Z_CI * kappa * se
    return (rho_hat - half > -RHO_BE) & (rho_hat + half < RHO_BE)


def gates(h0: dict[str, dict], h1_gate: dict[str, float], size_count: int) -> dict:
    """h0[v] = {coverage, se_median}; h1_gate[v] = moc przy GATE_RHO."""
    g1 = {v: h0[v]["coverage"] >= COVERAGE_MIN for v in h0}
    g2 = {v: h1_gate[v] >= GATE_POWER for v in h1_gate}
    g3 = {v: h0[v]["half_ci_median"] < RHO_BE for v in h0}
    stop = size_count >= SIZE_STOP
    return {
        "g1_coverage": g1, "g1_passed": all(g1.values()),
        "g2_power": g2, "g2_passed": all(g2.values()),
        "g3_falsified_reachable": g3, "g3_passed": all(g3.values()),
        "size_false_supported": size_count, "size_stop": stop,
        "m14_passed": bool(all(g1.values()) and all(g2.values())
                           and all(g3.values()) and not stop),
    }


# --------------------------------------------------------------------------
# Świat — jeden świat na zadanie, równolegle
# --------------------------------------------------------------------------

_CTX: dict = {}


def _init(m09a_run: str, m09b_run: str) -> None:
    rho, g, calib = load_inputs(m09a_run, m09b_run, KIND)
    ts_h, _ = time_axis()
    rows = decision_rows(ts_h)
    p = len(SYMBOLS)
    mon_rows = month_of(ts_h[rows], dt.date.fromisoformat(FIRST_MONTH), LAG_MONTHS)
    _CTX.update(
        chol_ret=psd_chol(rho), calib=calib, n_hours=ts_h.size, rows=rows,
        phi=np.array([g["per_currency"][c]["phi"] for c in CURRENCIES]),
        sigma=np.array([g["per_currency"][c]["sigma_innov"] for c in CURRENCIES]),
        chol_rates=psd_chol(np.asarray(g["innovation_corr"])),
        anchor=g["level_pooled_mean"], pm=pair_matrix(SYMBOLS, CURRENCIES),
        n_months=int(mon_rows.max()) + 1,
        mon=np.repeat(mon_rows, p), rsym=np.tile(np.arange(p), rows.size),
        ts=pl.Series("ts", np.repeat(ts_h[rows], p).astype("datetime64[ms]")
                     ).dt.replace_time_zone("UTC"),
    )


def one_world(task: tuple[int, int, int, float, int]) -> tuple[float, float]:
    """(ρ̂, SE_boot) w jednym świecie wariantu `variant` z zasianym ρ."""
    stream, v, ri, rho_t, w = task
    c = _CTX
    fm, rm = VARIANTS[v].split("/")
    rng = np.random.default_rng(world_seed(stream, v, ri, w))
    phi = c["phi"] if fm == "ar1_measured" else np.ones_like(c["phi"])
    cal = c["calib"][fm]
    carry = (simulate_rates(rng, c["n_months"], phi, c["sigma"] * cal["sigma_mult"],
                            c["chol_rates"], c["anchor"], cal["level_sd"], c["anchor"])
             @ c["pm"].T)[c["mon"], c["rsym"]]
    y = simulate_fwd(rng, c["n_hours"], c["chol_ret"], rm, c["rows"]).ravel()
    if rho_t:
        z = (carry - carry.mean()) / carry.std()
        y = rho_t * z * y.std() + np.sqrt(1 - rho_t ** 2) * y
    boot = block_bootstrap_statistic(
        c["ts"], lambda idx: spearman(carry[idx], y[idx]), block_days=BLOCK_DAYS,
        n_reps=BOOT_REPS, seed=int(rng.integers(2 ** 32)))
    return boot.expectancy, boot.se


def run_set(pool: Pool, stream: int, rho_grid: tuple[float, ...], n: int) -> dict:
    tasks = [(stream, v, ri, r, w) for v in range(len(VARIANTS))
             for ri, r in enumerate(rho_grid) for w in range(n)]
    res = np.asarray(pool.map(one_world, tasks, chunksize=4)).reshape(
        len(VARIANTS), len(rho_grid), n, 2)
    return {VARIANTS[v]: {r: (res[v, ri, :, 0], res[v, ri, :, 1])
                          for ri, r in enumerate(rho_grid)} for v in range(len(VARIANTS))}


# --------------------------------------------------------------------------
# Przebieg
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m09a-run", default=M12_RUN)
    ap.add_argument("--m09b-run", default=M09B_RUN)
    args = ap.parse_args(argv)

    params = {
        "adr": "ADR-027 opcja (a)", "data": "WYLACZNIE syntetyczne",
        "inputs": {"m12_run": args.m09a_run, "m09b_run": args.m09b_run},
        "kind": KIND, "variants": list(VARIANTS), "seed": SEED,
        "streams": {"cal": STREAM_CAL, "h0": STREAM_H0, "h1": STREAM_H1},
        "n_cal": N_CAL, "n_val_h0": N_VAL_H0, "n_val_h1": N_VAL_H1,
        "rho_grid_h1": list(RHO_GRID_H1), "boot_reps": BOOT_REPS, "block_days": BLOCK_DAYS,
        "coverage_target": COVERAGE_TARGET, "coverage_min": COVERAGE_MIN,
        "gate_rho": GATE_RHO, "gate_power": GATE_POWER, "mde_power": MDE_POWER,
        "z_supported": Z_SUP, "rho_breakeven": RHO_BE, "size_stop": SIZE_STOP,
        "criterion_set_before_run": True,
    }
    with start_run("M14 bootstrap skalibrowany kappa: pokrycie, moc, osiagalnosc FALSIFIED "
                   "(ADR-027)", params, kind="control") as run, \
            Pool(N_WORKERS, initializer=_init, initargs=(args.m09a_run, args.m09b_run)) as pool:
        report: dict = {"params": params}

        cal = run_set(pool, STREAM_CAL, (0.0,), N_CAL)
        k_var = {v: kappa_variant(*cal[v][0.0]) for v in VARIANTS}
        kappa = kappa_combined(k_var)
        report["calibration"] = {v: {"kappa": k_var[v],
                                     "se_boot_median": float(np.median(cal[v][0.0][1])),
                                     "true_sd": float(np.std(cal[v][0.0][0], ddof=1))}
                                 for v in VARIANTS}
        report["kappa"] = kappa
        print(f"  κ per wariant: { {v: round(k, 4) for v, k in k_var.items()} } → κ = {kappa:.4f}",
              flush=True)

        h0s = run_set(pool, STREAM_H0, (0.0,), N_VAL_H0)
        h0, size_count = {}, 0
        for v in VARIANTS:
            r, se = h0s[v][0.0]
            fp = int(supported(r, se, kappa).sum())
            size_count += fp
            true_sd = float(np.std(r, ddof=1))
            h0[v] = {"coverage": coverage(r, se, kappa),
                     "coverage_raw_boot": coverage(r, se, 1.0),
                     "true_sd": true_sd,
                     "se_median": float(np.median(se)),
                     "kse_to_true": float(kappa * np.median(se) / true_sd),
                     "half_ci_median": float(Z_CI * kappa * np.median(se)),
                     "p_falsified": float(falsified(r, se, kappa).mean()),
                     "false_supported": fp}
            print(f"  H0 {v:<24} pokrycie {h0[v]['coverage']:.3f} (surowy boot "
                  f"{h0[v]['coverage_raw_boot']:.3f})  SD {true_sd:.5f}  "
                  f"κ·SE/SD {h0[v]['kse_to_true']:.2f}  pół-CI {h0[v]['half_ci_median']:.5f}  "
                  f"P(FALS) {h0[v]['p_falsified']:.2f}  fałsz. SUP {fp}", flush=True)
        report["validation_h0"] = h0

        h1s = run_set(pool, STREAM_H1, RHO_GRID_H1, N_VAL_H1)
        h1: dict = {}
        for v in VARIANTS:
            h1[v] = {}
            for rt in RHO_GRID_H1:
                r, se = h1s[v][rt]
                h1[v][str(rt)] = {"power": float(supported(r, se, kappa).mean()),
                                  "acc_pct": float(50 + 100 * np.arcsin(rt) / np.pi),
                                  "rho_hat_mean": float(r.mean()),
                                  "se_boot_median": float(np.median(se)),
                                  "coverage_at_truth": coverage(r, se, kappa, rt)}
            print(f"  H1 {v:<24} moc: " + "  ".join(
                f"ρ={k} {e['power']:.2f}" for k, e in h1[v].items()), flush=True)
        report["validation_h1"] = h1

        min_power = {str(rt): min(h1[v][str(rt)]["power"] for v in VARIANTS)
                     for rt in RHO_GRID_H1}
        mde = next((float(k) for k in min_power if min_power[k] >= MDE_POWER), None)
        verdict = gates(h0, {v: h1[v][str(GATE_RHO)]["power"] for v in VARIANTS}, size_count)
        verdict.update({
            "criterion_set_before_run": True, "kappa": kappa,
            "power_min_over_variants": min_power,
            "empirical_mde80_rho_worst": mde,
            "empirical_mde80_acc_pct_worst":
                None if mde is None else float(50 + 100 * np.arcsin(mde) / np.pi),
        })
        report["verdict"] = verdict
        (run.dir / "m14_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        run.record(kappa=kappa, m14_passed=verdict["m14_passed"],
                   g1_passed=verdict["g1_passed"], g2_passed=verdict["g2_passed"],
                   g3_passed=verdict["g3_passed"], size_false_supported=size_count,
                   empirical_mde80_rho_worst=mde, criterion_set_before_run=True)
        print(json.dumps(verdict, indent=1))
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
