#!/usr/bin/env python3
"""M09 krok B — rozkład zerowy statystyki carry (H04). Kontrola, NIE próba.

PYTANIE (ADR-022)

Czy przy cesze tak trwałej jak różnica stóp statystyka warstwy A ma dość
obserwacji efektywnych, żeby `FALSIFIED` było osiągalne? Wzór M05: cecha
SYNTETYCZNA, prawdziwe `fwd_atr`, prawdziwa siatka.

CECHA NIE JEST LICZONA

Skrypt nie importuje `src/data/rates.py` i nie czyta żadnej stopy. Jedynym
wejściem z H04 są liczby z raportu M09A: φ i σ innowacji per waluta,
korelacja innowacji, rozkład poziomów. Z nich powstają syntetyczne stopy
sześciu walut, a z nich — różnice dla par. Tą drogą surogat dziedziczy
strukturę międzyparową (EURUSD, USDJPY i EURJPY dzielą nogi), której nie
trzeba modelować osobno.

Pod H0 cecha jest niezależna od cen; jedynym źródłem rozrzutu statystyki
jest to, co naprawdę jest w danych: nakładanie okien, trwałość cechy i to,
że sześć par ma w 2016–2021 swoje zrealizowane dryfy. Przy cesze tak trwałej
ten ostatni człon jest groźny (problem regresora trwałego) — i właśnie
dlatego mierzymy go na prawdziwych zwrotach, a nie wzorem.

MODELE TRWAŁOŚCI — nawias, bramka po gorszym

    ar1_measured   φ z M09A per waluta
    random_walk    φ = 1

KALIBRACJA DO GEOMETRII (poprawka po przebiegu `…202431Z-679260`)

Pierwszy przebieg brał σ innowacji wprost z AR(1) dopasowanego do M09A.
Prawdziwa cecha ma trend (cykl Fed 2016–2019), a AR(1) dopasowany do trendu
zaniża σ — surogat miał 0,37–0,39 zmienności w czasie wobec 0,65
prawdziwej, czyli relację identyfikował niemal wyłącznie przekrój sześciu
par. Teraz mnożnik σ i rozrzut poziomów startowych są kalibrowane tak, żeby
surogat odtwarzał OBIE wielkości z M09A, a przebieg odmawia werdyktu, gdy
kalibracja nie trafi w tolerancję.

DWA SE — ADR-019

    (a) rozkład zerowy: cecha losowana, zwroty stałe (wzór M05);
    (b) block bootstrap po dniach na ustalonej ścieżce syntetycznej —
        ta sama metoda, którą T003 liczył przedział ufności.

Przy cesze ergodycznej to jest ta sama wielkość. Przy cesze tak trwałej
mogą się rozjechać: (a) niesie zrealizowane dryfy par (regresor trwały),
(b) — rozrzut zwrotów wokół ustalonej ścieżki cechy. Bramka idzie po
WIĘKSZYM z nich, a iloraz jest raportowany jako zgodność z ADR-019.

Zero przyrządu: cecha iid per wiersz musi dać SE ≈ 1/√n.
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

from src.harness.market import load_h1, require_fresh_bars  # noqa: E402
from src.harness.registry import start_run  # noqa: E402
from src.research.grid import (  # noqa: E402
    decision_grid as build_grid, in_session as session_filter, session_hours,
    with_horizon as add_horizon,
)
from src.validation.bootstrap import block_bootstrap_statistic  # noqa: E402

UTC = dt.timezone.utc

WARMUP_START = dt.datetime(2015, 1, 1, tzinfo=UTC)
FIRST_DECISION = dt.datetime(2016, 1, 1, tzinfo=UTC)
RESEARCH_END = dt.datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC)
H = 3
GRID_LOOKBACK = 480             # ta sama siatka co T003 i M05

M09A_RUN = "20260924T202237Z-ff858a"
KIND = "overnight"              # interbank_3m: UNKNOWN w M09A (brak 2020-04)
FIRST_MONTH = dt.date(2015, 11, 1)   # pierwszy miesiąc widoczny dla decyzji
LAG_MONTHS = 2
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD"]

MODELS = ("ar1_measured", "random_walk")
N_REPS = 400
N_REPS_ZERO = 200
N_PATHS_BOOT = 20               # ścieżek syntetycznych pod bootstrap
BOOT_REPS = 300                 # replikacji bootstrapu na ścieżkę
N_CALIB = 300                   # symulacji na krok kalibracji (bez zwrotów)
CALIB_STEPS = 10
SEED = 20260926

# --- Kryterium, ZADEKLAROWANE PRZED PRZEBIEGIEM ---------------------------
Z_CI = 1.959963984540054
Z_POWER = 0.8416212335729143
BREAKEVEN_ACC = 0.5172          # M04, h = 3 d
RHO_BREAKEVEN = float(np.sin((BREAKEVEN_ACC - 0.5) * np.pi))
# Bramka ADR-022: FALSIFIED osiągalne (1,96·SE < ρ_breakeven), gdzie SE to
# WIĘKSZE z (a) i (b), w GORSZYM z dwóch modeli trwałości. Werdykt tylko
# wtedy, gdy: zero przyrządu SE/(1/√n) w [0,9; 1,1] i surogat odtwarza
# zmienność w czasie ORAZ rozrzut między parami z M09A w granicach ±20%.
ZERO_TOL = (0.9, 1.1)
VALIDITY_TOL = 0.20
ADR019_MAX_RATIO = 1.5


# --------------------------------------------------------------------------
# Czyste funkcje — testowane na danych syntetycznych
# --------------------------------------------------------------------------

def avg_rank(x: np.ndarray) -> np.ndarray:
    """Rangi średnie. Cecha miesięczna ma masowe remisy — rangi z `argsort`
    rozstrzygałyby je kolejnością wierszy, czyli czasem."""
    return pl.Series(x).rank("average").to_numpy().astype(np.float64)


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def psd_chol(c: np.ndarray) -> np.ndarray:
    vals, vecs = np.linalg.eigh(c)
    vals = np.clip(vals, 1e-10, None)
    c = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(c))
    return np.linalg.cholesky(c / np.outer(d, d))


def simulate_rates(rng: np.random.Generator, n_months: int, phi: np.ndarray,
                   sigma: np.ndarray, chol: np.ndarray, level_mean: float,
                   level_sd: float, anchor: float) -> np.ndarray:
    """Syntetyczne stopy (n_months, waluty): AR(1) wokół `anchor`,
    poziom startowy losowany z przekroju, innowacje skorelowane."""
    p = phi.size
    r = np.empty((n_months, p))
    r[0] = level_mean + level_sd * rng.standard_normal(p)
    inno = (rng.standard_normal((n_months, p)) @ chol.T) * sigma
    for t in range(1, n_months):
        r[t] = anchor + phi * (r[t - 1] - anchor) + inno[t]
    return r


def pair_matrix(symbols: list[str], currencies: list[str]) -> np.ndarray:
    """Macierz (pary, waluty): +1 na bazie, −1 na kwotowanej."""
    m = np.zeros((len(symbols), len(currencies)))
    for i, s in enumerate(symbols):
        m[i, currencies.index(s[:3])] += 1
        m[i, currencies.index(s[3:])] -= 1
    return m


def within_sd_rms(carry: np.ndarray) -> float:
    """Zmienność w czasie: średnia kwadratowa odchyleń per para — ta sama
    definicja co `within_pair_sd_rms` w M09A."""
    return float(np.sqrt(np.mean(carry.std(axis=0, ddof=1) ** 2)))


def between_sd(carry: np.ndarray) -> float:
    """Rozrzut między parami: SD średnich par — jak w M09A."""
    return float(carry.mean(axis=0).std(ddof=1))


def geometry_of(rng, n_months, phi, sigma, chol, level_sd, anchor, pm, n_sims
                ) -> tuple[float, float]:
    w, b = [], []
    for _ in range(n_sims):
        c = simulate_rates(rng, n_months, phi, sigma, chol, anchor, level_sd, anchor) @ pm.T
        w.append(within_sd_rms(c))
        b.append(between_sd(c))
    return float(np.median(w)), float(np.median(b))


def calibrate(rng, n_months, phi, sigma, chol, anchor, pm, target_within,
              target_between, *, n_sims=N_CALIB, steps=CALIB_STEPS
              ) -> tuple[float, float, float, float]:
    """Mnożnik σ i SD poziomów startowych, przy których mediana geometrii
    surogatu trafia w cel.

    Odchylenia surogatu od `anchor` są liniowe w (σ, level_sd) ŁĄCZNIE, więc
    obie wielkości geometrii skalują się razem. Wystarczy więc dobrać
    STOSUNEK level_sd/σ bisekcją pod iloraz rozrzut/zmienność, a potem
    przeskalować całość. Sprzężenie jest realne — przy 72 miesiącach sam dryf
    innowacji tworzy rozrzut między parami — i właśnie dlatego nie
    iterujemy obu parametrów osobno.

    Wspólne losowania (jeden seed na każdą ewaluację), żeby bisekcja nie
    goniła szumu. Iloraz poniżej osiągalnego minimum (level_sd = 0) zwraca
    najlepszą możliwą kalibrację — sprawdzenie ważności ją odrzuci.
    Zwraca (mnożnik σ, level_sd, zmienność osiągnięta, rozrzut osiągnięty).
    Nie dotyka zwrotów.
    """
    seed = int(rng.integers(2**31))

    def geo(mult, lsd):
        return geometry_of(np.random.default_rng(seed), n_months, phi, sigma * mult,
                           chol, lsd, anchor, pm, n_sims)

    target_ratio = target_between / target_within
    w0, _ = geo(1.0, 0.0)
    unit = w0                              # skala level_sd porównywalna z σ
    lo, hi = 0.0, 1.0
    while geo(1.0, hi * unit)[1] / geo(1.0, hi * unit)[0] < target_ratio and hi < 1e3:
        hi *= 2
    for _ in range(steps + 10):
        mid = 0.5 * (lo + hi)
        w, b = geo(1.0, mid * unit)
        lo, hi = (mid, hi) if b / w < target_ratio else (lo, mid)
    q = 0.5 * (lo + hi) * unit
    w, b = geo(1.0, q)
    k = target_within / w
    w, b = geo(k, q * k)
    return k, q * k, w, b


def month_index(ts: pl.Series, first_month: dt.date, lag: int) -> np.ndarray:
    """Indeks miesiąca widocznego w chwili decyzji, od `first_month`."""
    y = ts.dt.year().to_numpy().astype(np.int64)
    m = ts.dt.month().to_numpy().astype(np.int64)
    return (y - first_month.year) * 12 + (m - first_month.month) - lag


def decision_numbers(se: float) -> dict:
    mde = (Z_CI + Z_POWER) * se
    half = Z_CI * se
    acc = 0.5 + np.arcsin(min(mde, 1.0)) / np.pi
    return {
        "se": se, "n_eff_implied": 1.0 / se ** 2,
        "mde_acc_pct": 100 * acc,
        "dead_zone_pp": 100 * (acc - BREAKEVEN_ACC),
        "half_ci95": half,
        "falsified_gap_ratio": half / RHO_BREAKEVEN,
        "falsified_reachable": bool(half < RHO_BREAKEVEN),
    }


# --------------------------------------------------------------------------
# Przebieg
# --------------------------------------------------------------------------

def load_params() -> tuple[dict, dict, list[str]]:
    rep = json.loads((ROOT / "runs" / M09A_RUN / "m09a_report.json").read_text(encoding="utf-8"))
    g = rep["kinds"][KIND]
    assert list(g["currency"]["per_currency"]) == CURRENCIES
    return g["currency"], g["pairs"], rep["params"]["symbols"]


def main() -> int:
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    symbols = list(cfg["instruments"]["discovery"])
    require_fresh_bars(symbols, WARMUP_START, RESEARCH_END, cfg)
    g, pairs_a, sym_a = load_params()
    assert sym_a == symbols
    target_w = pairs_a["within_pair_sd_rms"]
    target_b = pairs_a["between_pair_sd_of_means"]
    block_days = cfg["validation"]["bootstrap"]["block_days"]

    phi_meas = np.array([g["per_currency"][c]["phi"] for c in CURRENCIES])
    sigma = np.array([g["per_currency"][c]["sigma_innov"] for c in CURRENCIES])
    chol = psd_chol(np.asarray(g["innovation_corr"]))
    anchor = g["level_pooled_mean"]
    pm = pair_matrix(symbols, CURRENCIES)

    params = {
        "adr": "ADR-022, ADR-019",
        "feature_source": "surogat — stopy NIE sa czytane; parametry z M09A",
        "m09a_run": M09A_RUN, "kind": KIND, "lag_months": LAG_MONTHS,
        "h_business_days": H, "models": list(MODELS), "n_reps": N_REPS,
        "n_paths_boot": N_PATHS_BOOT, "boot_reps": BOOT_REPS,
        "block_days": block_days, "seed": SEED,
        "rho_breakeven": RHO_BREAKEVEN,
        "calibration_targets": {"within_pair_sd_rms": target_w,
                                "between_pair_sd_of_means": target_b},
        "validity_tol": VALIDITY_TOL, "zero_tol": list(ZERO_TOL),
        "gate": "FALSIFIED osiagalne przy max(SE_null, SE_boot) w gorszym modelu",
        "supersedes_invalid_run": "20260924T202431Z-679260",
        "criterion_set_before_run": True,
        "primary_statistic": "spearman(carry, fwd_atr), rangi srednie, pooled, primary",
    }
    with start_run("M09B rozklad zerowy statystyki carry H04, surogat skalibrowany, "
                   "dwa SE (ADR-022, ADR-019)", params, kind="control") as run:
        rng = np.random.default_rng(SEED)
        start_h, end_h = session_hours(cfg)
        fwd_parts, mon_parts, sym_parts, ts_parts = [], [], [], []
        for j, sym in enumerate(symbols):
            h1 = load_h1(sym, WARMUP_START, RESEARCH_END, cfg)
            dec, prices, _ = build_grid(
                h1, first_decision=FIRST_DECISION, lookback_bars=GRID_LOOKBACK,
                atr_period=cfg["volatility"]["atr_period"],
                min_h1_bars=cfg["data"]["d1_boundary"]["min_h1_bars"])
            df = session_filter(add_horizon(dec, prices, H, segment_end=RESEARCH_END),
                                start_h, end_h)
            df = df.filter(pl.col("fwd_atr").is_not_null() & pl.col("fwd_atr").is_not_nan())
            fwd_parts.append(df.get_column("fwd_atr").to_numpy())
            mon_parts.append(month_index(df.get_column("ts_decision"), FIRST_MONTH, LAG_MONTHS))
            sym_parts.append(np.full(df.height, j))
            ts_parts.append(df.get_column("ts_decision"))
            print(f"  {sym}: {df.height} decyzji")
        fwd = np.concatenate(fwd_parts)
        mon = np.concatenate(mon_parts)
        rsym = np.concatenate(sym_parts)
        ts = pl.concat(ts_parts).rename("ts")
        assert mon.min() >= 0, "decyzja widzi miesiąc sprzed okna M09A"
        n_months = int(mon.max()) + 1
        fwd_rank = avg_rank(fwd)
        n = fwd.size

        report: dict = {"params": params, "n_rows": int(n), "n_months": n_months,
                        "se_iid": 1 / np.sqrt(n), "models": {}}

        z = np.array([pearson(avg_rank(rng.standard_normal(n)), fwd_rank)
                      for _ in range(N_REPS_ZERO)])
        zero_ratio = float(z.std(ddof=1) * np.sqrt(n))
        report["zero_check"] = {"se_ratio_to_iid": zero_ratio,
                                "passed": ZERO_TOL[0] <= zero_ratio <= ZERO_TOL[1]}
        print(f"  zero przyrządu: SE / (1/√n) = {zero_ratio:.3f}")

        for model in MODELS:
            phi = phi_meas if model == "ar1_measured" else np.ones_like(phi_meas)
            mult, lsd, got_w, got_b = calibrate(rng, n_months, phi, sigma, chol,
                                                anchor, pm, target_w, target_b)
            sig = sigma * mult
            valid = (abs(got_w / target_w - 1) <= VALIDITY_TOL
                     and abs(got_b / target_b - 1) <= VALIDITY_TOL)
            print(f"  {model}: kalibracja σ×{mult:.2f}, sd poziomów {lsd:.2f} → "
                  f"zmienność {got_w:.2f} (cel {target_w:.2f}), "
                  f"rozrzut {got_b:.2f} (cel {target_b:.2f}) "
                  f"{'OK' if valid else 'POZA TOLERANCJĄ'}")

            def path() -> np.ndarray:
                r = simulate_rates(rng, n_months, phi, sig, chol, anchor, lsd, anchor)
                return (r @ pm.T)[mon, rsym]

            null = np.array([pearson(avg_rank(path()), fwd_rank) for _ in range(N_REPS)])
            se_null = float(null.std(ddof=1))

            boot_se = []
            for i in range(N_PATHS_BOOT):
                feat = path()

                def stat(idx, feat=feat):
                    return pearson(avg_rank(feat[idx]), avg_rank(fwd[idx]))

                boot_se.append(block_bootstrap_statistic(
                    ts, stat, block_days=block_days, n_reps=BOOT_REPS, seed=i).se)
            se_boot = float(np.median(boot_se))
            se_gate = max(se_null, se_boot)
            report["models"][model] = {
                "calibration": {"sigma_mult": mult, "level_sd": lsd,
                                "within_got": got_w, "between_got": got_b,
                                "valid": bool(valid)},
                "se_null": se_null, "se_boot_median": se_boot,
                "se_boot_range": [float(min(boot_se)), float(max(boot_se))],
                "null_to_boot_ratio": se_null / se_boot,
                "adr019_agreement": bool(1 / ADR019_MAX_RATIO
                                         <= se_null / se_boot <= ADR019_MAX_RATIO),
                "gate_se": se_gate,
                **decision_numbers(se_gate),
            }
            e = report["models"][model]
            print(f"  {model:<13} SE null={se_null:.5f}  SE boot={se_boot:.5f} "
                  f"(iloraz {e['null_to_boot_ratio']:.2f})  n_eff={e['n_eff_implied']:.0f}  "
                  f"MDE={e['mde_acc_pct']:.2f}%  martwa strefa {e['dead_zone_pp']:+.2f} pp  "
                  f"FALSIFIED {'osiągalne' if e['falsified_reachable'] else 'NIEOSIĄGALNE'} "
                  f"({e['falsified_gap_ratio']:.2f})")

        worst = min(MODELS, key=lambda m: report["models"][m]["n_eff_implied"])
        all_valid = all(report["models"][m]["calibration"]["valid"] for m in MODELS)
        report["verdict"] = {
            "criterion_set_before_run": True,
            "zero_check_passed": report["zero_check"]["passed"],
            "surrogate_valid": all_valid,
            "worst_model": worst,
            "n_eff_worst": report["models"][worst]["n_eff_implied"],
            "mde_acc_pct_worst": report["models"][worst]["mde_acc_pct"],
            "dead_zone_pp_worst": report["models"][worst]["dead_zone_pp"],
            "falsified_reachable_worst": report["models"][worst]["falsified_reachable"],
            "adr019_agreement_all": all(report["models"][m]["adr019_agreement"] for m in MODELS),
            "gate_passed": bool(report["zero_check"]["passed"] and all_valid
                                and report["models"][worst]["falsified_reachable"]),
        }
        (run.dir / "m09b_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        run.record(**report["verdict"])
        print(json.dumps(report["verdict"], indent=1))
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
