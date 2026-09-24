#!/usr/bin/env python3
"""M10 — które SE pokrywa prawdę przy cesze trwałej? Świat syntetyczny.

PYTANIE (ADR-023)

M09B zmierzył dla cechy carry dwa SE statystyki warstwy A i dostał rozjazd
1,7× — ponad limit ADR-019:

    (a) rozkład zerowy: cecha losowana, zwroty ustalone (wzór M05);
    (b) block bootstrap po dniach: obie ustalone, przepróbkowane bloki dni.

Oba są warunkowe na JEDNEJ realizacji. Na prawdziwych danych nie da się
sprawdzić, który trafia, bo nie znamy prawdziwego rozrzutu. W świecie
syntetycznym znamy: losujemy setki niezależnych par (cecha, zwroty) pod H0
i SD statystyki po światach JEST prawdziwym SE.

ŻADNYCH PRAWDZIWYCH DANYCH

Skrypt nie czyta barów, ticków ani stóp. Z przebiegów wcześniejszych bierze
wyłącznie liczby: macierz korelacji zwrotów 3-dniowych (M05) i parametry
skalibrowanego surogatu (M09A, M09B). Wynik nie może więc powiedzieć nic
o H04 — tylko o przyrządzie.

ŚWIAT

Oś: godziny dni roboczych, decyzje 2016–2021 w sesji primary (08–22 UTC).
Zwroty: przyrosty godzinowe o korelacji międzyparowej z M05; `fwd` = suma
72 kolejnych godzin roboczych (3 dni) — nakładanie okien jak w danych.
Dwa modele zwrotów: `gauss` oraz `stochvol` (wspólny czynnik zmienności,
log-AR(1) dzienny, φ = 0,98 — klastrowanie i grube ogony). Cecha: surogat
carry w obu modelach trwałości, skalibrowany w M09B.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from m09b_carry_null import (  # noqa: E402
    CURRENCIES, avg_rank, decision_numbers, pair_matrix, pearson, psd_chol,
    simulate_rates,
)
from src.harness.registry import start_run  # noqa: E402
from src.validation.bootstrap import block_bootstrap_statistic  # noqa: E402

UTC = dt.timezone.utc

M05_RUN = "20260924T134703Z-cd0d96"
M09A_RUN = "20260924T202237Z-ff858a"
M09B_RUN = "20260924T202826Z-a64090"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY"]

FIRST_DAY = np.datetime64("2016-01-04")
N_DAYS = 6 * 252
HOURS = 24
H_HOURS = 72                    # 3 dni robocze
SESSION = (8, 22)
FIRST_MONTH = dt.date(2015, 11, 1)
LAG_MONTHS = 2
BLOCK_DAYS = 20                 # base.yaml, jak T003

FEATURE_MODELS = ("ar1_measured", "random_walk")
RETURN_MODELS = ("gauss", "stochvol")
SV_PHI, SV_SIGMA = 0.98, 0.10   # log-zmienność dzienna

N_WORLDS_TRUE = 400             # prawdziwe SD
N_WORLDS_EST = 40               # światy, w których liczymy oba estymatory
N_REPS_EST = 100                # replikacji każdego estymatora na świat
SEED = 20260927

# --- Reguła, ZADEKLAROWANA PRZED PRZEBIEGIEM -----------------------------
# Estymator jest WAŻNY, gdy we WSZYSTKICH czterech wariantach świata:
#   * średnia wariancja estymowana / prawdziwa wariancja ∈ [0,80; 1,25]
#   * pokrycie |ρ̂| ≤ 1,96·SE w światach estymacji ≥ 0,90
# T004 liczy CI estymatorem ważnym (przy dwóch ważnych: bootstrap, jak T003).
# Żaden ważny → prerejestracja H04 zablokowana.
# Niezależnie: n_eff z PRAWDZIWEGO SD w najgorszym wariancie musi zostawiać
# `FALSIFIED` osiągalne — inaczej bramka M09B była fałszywie pozytywna.
VAR_RATIO_TOL = (0.80, 1.25)
COVERAGE_MIN = 0.90


# --------------------------------------------------------------------------
# Świat — czyste funkcje
# --------------------------------------------------------------------------

def time_axis() -> tuple[np.ndarray, np.ndarray]:
    """(znaczniki godzin roboczych jako datetime64[h], dni robocze)."""
    days = np.busday_offset(FIRST_DAY, np.arange(N_DAYS), roll="forward")
    ts = (days.astype("datetime64[h]")[:, None]
          + np.arange(HOURS).astype("timedelta64[h]")[None, :]).ravel()
    return ts, days


def decision_rows(ts: np.ndarray) -> np.ndarray:
    """Indeksy godzin z decyzją: sesja primary i pełne okno w przód."""
    hour = (ts - ts.astype("datetime64[D]")).astype(np.int64)
    idx = np.flatnonzero((hour >= SESSION[0]) & (hour < SESSION[1]))
    return idx[idx + H_HOURS < ts.size]


def month_of(ts: np.ndarray) -> np.ndarray:
    m = ts.astype("datetime64[M]").astype(np.int64)           # miesiące od 1970
    first = (FIRST_MONTH.year - 1970) * 12 + FIRST_MONTH.month - 1
    return m - first - LAG_MONTHS


def simulate_fwd(rng: np.random.Generator, n_hours: int, chol: np.ndarray,
                 model: str, rows: np.ndarray) -> np.ndarray:
    """Zwroty w przód (wiersze decyzji, pary): suma `H_HOURS` przyrostów."""
    p = chol.shape[0]
    inc = rng.standard_normal((n_hours, p)) @ chol.T
    if model == "stochvol":
        n_d = n_hours // HOURS
        lv = np.empty(n_d)
        lv[0] = rng.standard_normal() * SV_SIGMA / np.sqrt(1 - SV_PHI ** 2)
        e = rng.standard_normal(n_d) * SV_SIGMA
        for d in range(1, n_d):
            lv[d] = SV_PHI * lv[d - 1] + e[d]
        inc *= np.exp(np.repeat(lv, HOURS))[:, None]
    elif model != "gauss":
        raise ValueError(model)
    cum = np.vstack([np.zeros((1, p)), np.cumsum(inc, axis=0)])
    return cum[rows + H_HOURS] - cum[rows]


def spearman(feat: np.ndarray, fwd: np.ndarray) -> float:
    return pearson(avg_rank(feat), avg_rank(fwd))


def estimator_verdict(true_sd: float, se_est: np.ndarray, stats: np.ndarray) -> dict:
    """Skalibrowanie i pokrycie jednego estymatora w jednym wariancie świata."""
    var_ratio = float(np.mean(se_est ** 2) / true_sd ** 2)
    coverage = float(np.mean(np.abs(stats) <= 1.959963984540054 * se_est))
    return {
        "var_ratio": var_ratio,
        "se_ratio": float(np.sqrt(var_ratio)),
        "se_est_cv": float(se_est.std(ddof=1) / se_est.mean()),
        "coverage": coverage,
        "valid": bool(VAR_RATIO_TOL[0] <= var_ratio <= VAR_RATIO_TOL[1]
                      and coverage >= COVERAGE_MIN),
    }


# --------------------------------------------------------------------------
# Przebieg
# --------------------------------------------------------------------------

def load_inputs():
    m05 = json.loads((ROOT / "runs" / M05_RUN / "m05_report.json").read_text(encoding="utf-8"))
    r = m05["horizons"]["3"]
    order = r["symbols"]
    rho_sorted = np.asarray(r["rho_matrix"])
    perm = [order.index(s) for s in SYMBOLS]
    rho = rho_sorted[np.ix_(perm, perm)]
    a = json.loads((ROOT / "runs" / M09A_RUN / "m09a_report.json").read_text(encoding="utf-8"))
    g = a["kinds"]["overnight"]["currency"]
    b = json.loads((ROOT / "runs" / M09B_RUN / "m09b_report.json").read_text(encoding="utf-8"))
    return rho, g, {m: b["models"][m]["calibration"] for m in FEATURE_MODELS}


def main() -> int:
    rho, g, calib = load_inputs()
    chol_ret = psd_chol(rho)
    phi_meas = np.array([g["per_currency"][c]["phi"] for c in CURRENCIES])
    sigma = np.array([g["per_currency"][c]["sigma_innov"] for c in CURRENCIES])
    chol_rates = psd_chol(np.asarray(g["innovation_corr"]))
    anchor = g["level_pooled_mean"]
    pm = pair_matrix(SYMBOLS, CURRENCIES)

    ts_h, _ = time_axis()
    rows = decision_rows(ts_h)
    mon_rows = month_of(ts_h[rows])
    assert mon_rows.min() >= 0
    n_months = int(mon_rows.max()) + 1
    p = len(SYMBOLS)
    mon = np.tile(mon_rows[:, None], (1, p)).ravel()
    rsym = np.tile(np.arange(p)[None, :], (rows.size, 1)).ravel()
    ts_rows = pl.Series("ts", np.repeat(ts_h[rows], p).astype("datetime64[ms]")
                        ).dt.replace_time_zone("UTC")

    params = {
        "adr": "ADR-023, ADR-019",
        "data": "WYLACZNIE syntetyczne — zadne bary, ticki ani stopy",
        "inputs": {"m05_run": M05_RUN, "m09a_run": M09A_RUN, "m09b_run": M09B_RUN},
        "n_rows": int(rows.size * p), "n_months": n_months,
        "feature_models": list(FEATURE_MODELS), "return_models": list(RETURN_MODELS),
        "n_worlds_true": N_WORLDS_TRUE, "n_worlds_est": N_WORLDS_EST,
        "n_reps_est": N_REPS_EST, "block_days": BLOCK_DAYS, "seed": SEED,
        "var_ratio_tol": list(VAR_RATIO_TOL), "coverage_min": COVERAGE_MIN,
        "criterion_set_before_run": True,
    }
    with start_run("M10 pokrycie SE przy cesze trwalej, swiat syntetyczny (ADR-023, ADR-019)",
                   params, kind="control") as run:
        rng = np.random.default_rng(SEED)
        report: dict = {"params": params, "variants": {}}

        for fm in FEATURE_MODELS:
            phi = phi_meas if fm == "ar1_measured" else np.ones_like(phi_meas)
            sig = sigma * calib[fm]["sigma_mult"]
            lsd = calib[fm]["level_sd"]

            def feature() -> np.ndarray:
                r = simulate_rates(rng, n_months, phi, sig, chol_rates, anchor, lsd, anchor)
                return (r @ pm.T)[mon, rsym]

            for rm in RETURN_MODELS:
                def fwd() -> np.ndarray:
                    return simulate_fwd(rng, ts_h.size, chol_ret, rm, rows).ravel()

                true_stats = np.array([spearman(feature(), fwd())
                                       for _ in range(N_WORLDS_TRUE)])
                true_sd = float(true_stats.std(ddof=1))

                st, se_null, se_boot = [], [], []
                for w in range(N_WORLDS_EST):
                    f, y = feature(), fwd()
                    st.append(spearman(f, y))
                    yr = avg_rank(y)
                    se_null.append(float(np.std(
                        [pearson(avg_rank(feature()), yr) for _ in range(N_REPS_EST)], ddof=1)))
                    se_boot.append(block_bootstrap_statistic(
                        ts_rows, lambda idx, f=f, y=y: spearman(f[idx], y[idx]),
                        block_days=BLOCK_DAYS, n_reps=N_REPS_EST, seed=w).se)
                st, se_null, se_boot = map(np.asarray, (st, se_null, se_boot))

                key = f"{fm}/{rm}"
                report["variants"][key] = {
                    "true_sd": true_sd,
                    "true": decision_numbers(true_sd),
                    "null": estimator_verdict(true_sd, se_null, st),
                    "boot": estimator_verdict(true_sd, se_boot, st),
                }
                v = report["variants"][key]
                print(f"  {key:<24} prawdziwe SD={true_sd:.5f} (n_eff {v['true']['n_eff_implied']:.0f}, "
                      f"FALSIFIED {'osiągalne' if v['true']['falsified_reachable'] else 'NIE'}) | "
                      f"null: SE×{v['null']['se_ratio']:.2f} pokr. {v['null']['coverage']:.2f} "
                      f"cv {v['null']['se_est_cv']:.2f} | "
                      f"boot: SE×{v['boot']['se_ratio']:.2f} pokr. {v['boot']['coverage']:.2f} "
                      f"cv {v['boot']['se_est_cv']:.2f}")

        V = report["variants"]
        null_ok = all(v["null"]["valid"] for v in V.values())
        boot_ok = all(v["boot"]["valid"] for v in V.values())
        worst = min(V, key=lambda k: V[k]["true"]["n_eff_implied"])
        chosen = "boot" if boot_ok else ("null" if null_ok else None)
        report["verdict"] = {
            "criterion_set_before_run": True,
            "null_valid_all": null_ok,
            "boot_valid_all": boot_ok,
            "ci_method_for_t004": chosen,
            "worst_variant": worst,
            "true_n_eff_worst": V[worst]["true"]["n_eff_implied"],
            "true_mde_acc_pct_worst": V[worst]["true"]["mde_acc_pct"],
            "falsified_reachable_true_worst": V[worst]["true"]["falsified_reachable"],
            "prereg_unblocked": bool(chosen is not None
                                     and V[worst]["true"]["falsified_reachable"]),
        }
        (run.dir / "m10_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        run.record(**report["verdict"])
        print(json.dumps(report["verdict"], indent=1))
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
