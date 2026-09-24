#!/usr/bin/env python3
"""T004 — H04 carry. PRÓBA, nie kontrola. Zapala 1 wariant (N: 10 → 11).

Wykonuje prerejestrację `configs/t004_carry.yaml` i nic poza nią. Sprawdza
hash prerejestracji na starcie i odmawia startu, jeśli plik się zmienił.

DWA TRYBY

    --self-test   pipeline na świecie SYNTETYCZNYM z M10 (nakładające się
                  okna, korelacja międzyparowa, cecha trwała) — raz bez
                  efektu, raz z efektem zasianym. Nie czyta barów ani stóp,
                  nie loguje próby, nie rusza licznika.
    (bez flagi)   pełny przebieg na danych. Loguje `kind="strategy"`,
                  `n_variants=1`. **Nieodwracalne.**

Tak jak w T003: nie ma trybu „próbnego na prawdziwych danych". Przebieg,
który policzył statystykę na RESEARCH, zobaczył wynik — jest próbą.

CO JEST INNE NIŻ W T003 (ADR-026, ADR-027)

* CI z rozkładu zerowego surogatu zachowującego trwałość, nie z bootstrapu.
  Bootstrap jest raportowany obok, bez wpływu na werdykt.
* Kontrola losowa JEST tym samym surogatem — nie ma osobnego p-value.
* SUPPORTED deflowane Šidákiem po 11 próbach (z = 2,8302); FALSIFIED i górne
  ograniczenie z z = 1,96.
* Warstwa B dokłada kierunkowy przychód carry (`attach_carry`).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from m09b_carry_null import (  # noqa: E402
    CURRENCIES, avg_rank, month_index, pair_matrix, pearson, psd_chol,
    simulate_rates,
)
from src.harness.registry import start_run  # noqa: E402
from src.validation.bootstrap import block_bootstrap_statistic  # noqa: E402

UTC = dt.timezone.utc
PREREG = ROOT / "configs" / "t004_carry.yaml"
PREREG_SHA256 = "PENDING"

M12_RUN = "20260924T212921Z-b1fcdc"
M09B_RUN = "20260924T213027Z-47327e"
FIRST_MONTH = dt.date(2016, 1, 1)
FEATURE = "carry_policy"
AGED = "aged_carry_policy"
MODELS = ("ar1_measured", "random_walk")
Z_CI = 1.959963984540054


# --------------------------------------------------------------------------
# Statystyka i kryteria — czyste funkcje
# --------------------------------------------------------------------------

def spearman(feat: np.ndarray, targ: np.ndarray) -> float:
    return pearson(avg_rank(feat), avg_rank(targ))


def acc_pct(rho: float) -> float:
    return float(50 + 100 * np.arcsin(np.clip(rho, -1, 1)) / np.pi)


def verdict(rho: float, se_null: float, *, z_supported: float,
            rho_breakeven: float) -> dict:
    """SUPPORTED / FALSIFIED / NOT_SUPPORTED wg prerejestracji, bez wyjątków."""
    lo_def = rho - z_supported * se_null
    lo, hi = rho - Z_CI * se_null, rho + Z_CI * se_null
    supported = lo_def > 0
    falsified = (lo > -rho_breakeven) and (hi < rho_breakeven)
    status = "SUPPORTED" if supported else ("FALSIFIED" if falsified else "NOT_SUPPORTED")
    return {
        "status": status,
        "rho": rho, "se_null": se_null,
        "ci95": [lo, hi],
        "ci_low_deflated": lo_def,
        "supported_rule_met": bool(supported),
        "falsified_rule_met": bool(falsified),
        "falsified_reachable_in_run": bool(Z_CI * se_null < rho_breakeven),
        "upper_bound_rho": hi,
        "upper_bound_acc_pct": acc_pct(hi),
    }


def consistency(se: float, band: tuple[float, float]) -> dict:
    return {"se": se, "band": list(band), "passes": bool(band[0] <= se <= band[1])}


# --------------------------------------------------------------------------
# Rozkład zerowy — surogat skalibrowany w M09B na geometrii M12
# --------------------------------------------------------------------------

def make_null_sd(mon: np.ndarray, rsym: np.ndarray, symbols: list[str],
                 geometry: dict, calibration: dict, *, reps: int, seed: int
                 ) -> Callable[[np.ndarray], dict]:
    """Zwraca funkcję: target → SD statystyki pod H0 per model trwałości.

    Cecha syntetyczna: stopy sześciu walut z parametrów M12, skalibrowane
    jak w M09B; zwroty — te, które dostanie funkcja. Stóp nie czyta.
    """
    g = geometry
    phi_meas = np.array([g["per_currency"][c]["phi"] for c in CURRENCIES])
    sigma = np.array([g["per_currency"][c]["sigma_innov"] for c in CURRENCIES])
    chol = psd_chol(np.asarray(g["innovation_corr"]))
    anchor = g["level_pooled_mean"]
    pm = pair_matrix(symbols, CURRENCIES)
    n_months = int(mon.max()) + 1

    def null_sd(targ: np.ndarray) -> dict:
        rng = np.random.default_rng(seed)
        tr = avg_rank(targ)
        out = {}
        for model in MODELS:
            phi = phi_meas if model == "ar1_measured" else np.ones_like(phi_meas)
            sig = sigma * calibration[model]["sigma_mult"]
            lsd = calibration[model]["level_sd"]
            draws = [pearson(avg_rank((simulate_rates(rng, n_months, phi, sig, chol,
                                                      anchor, lsd, anchor) @ pm.T)[mon, rsym]),
                             tr) for _ in range(reps)]
            out[model] = float(np.std(draws, ddof=1))
        return out
    return null_sd


# --------------------------------------------------------------------------
# Komórka
# --------------------------------------------------------------------------

def run_cell(obs: pl.DataFrame, null_sd: Callable[[np.ndarray], dict], *,
             z_supported: float, rho_breakeven: float, block_days: int,
             boot_reps: int, aged: bool = True) -> dict:
    feat = obs.get_column(FEATURE).to_numpy()
    targ = obs.get_column("fwd_atr").to_numpy()
    rho = spearman(feat, targ)

    per_model = null_sd(targ)
    se_null = max(per_model.values())
    ts = obs.get_column("ts_decision").rename("ts")
    boot = block_bootstrap_statistic(
        ts, lambda idx: spearman(feat[idx], targ[idx]),
        block_days=block_days, n_reps=boot_reps, seed=0)

    out = {
        "n_obs": int(obs.height),
        "spearman": rho,
        "pearson": pearson(feat, targ),
        "se_null_per_model": per_model,
        "se_null": se_null,
        "se_boot": boot.se,
        "null_to_boot": se_null / boot.se if boot.se else None,
        "verdict": verdict(rho, se_null, z_supported=z_supported,
                           rho_breakeven=rho_breakeven),
    }
    if aged:
        ag = obs.get_column(AGED).to_numpy()
        ok = ~np.isnan(ag)
        rows = np.flatnonzero(ok)
        diff = block_bootstrap_statistic(
            ts.filter(pl.Series(ok)),
            lambda idx: (spearman(ag[rows[idx]], targ[rows[idx]])
                         - spearman(feat[rows[idx]], targ[rows[idx]])),
            block_days=block_days, n_reps=max(500, boot_reps // 2), seed=0)
        out["aged_control"] = {
            "spearman_aged": spearman(ag[ok], targ[ok]),
            "diff_aged_minus_true": diff.expectancy,
            "se_diff": diff.se,
            "in_se": diff.expectancy / diff.se if diff.se else None,
            "passes": bool(diff.expectancy < 2 * diff.se),
        }
    return out


# --------------------------------------------------------------------------
# Dane
# --------------------------------------------------------------------------

def attach_carry_feature(dec: pl.DataFrame, symbol: str) -> pl.DataFrame:
    """`carry_policy` i ramię postarzone, point-in-time (`policy_pit`)."""
    from src.data.policy_rates import load_series, policy_pit

    base, quote = symbol[:3], symbol[3:]
    days = dec.get_column("ts_decision").dt.date().unique().sort().to_list()
    sb, sq = load_series(base), load_series(quote)
    table = pl.DataFrame({
        "d": days,
        FEATURE: policy_pit(sb, days, 1) - policy_pit(sq, days, 1),
        AGED: policy_pit(sb, days, 6) - policy_pit(sq, days, 6),
    })
    return (dec.with_columns(pl.col("ts_decision").dt.date().alias("d"))
            .join(table, on="d", how="left").drop("d"))


def build_observations(cfg: dict, pre: dict, symbols: list[str], h: int
                       ) -> dict[str, pl.DataFrame]:
    from src.features.volatility import atr_d1, vol_pct
    from src.harness.market import load_h1
    from src.research.grid import decision_grid, with_horizon
    from src.research.labels import with_axes

    warmup = dt.datetime.fromisoformat(pre["sample"]["warmup_from"]).replace(tzinfo=UTC)
    first = dt.datetime.fromisoformat(pre["sample"]["first_decision"]).replace(tzinfo=UTC)
    end = segment_end(pre)
    out = {}
    for sym in symbols:
        h1 = load_h1(sym, warmup, end, cfg)
        dec, prices, _ = decision_grid(
            h1, first_decision=first, lookback_bars=480,
            atr_period=cfg["volatility"]["atr_period"],
            min_h1_bars=cfg["data"]["d1_boundary"]["min_h1_bars"])
        dec = with_horizon(dec, prices, h, segment_end=end)
        dec = attach_carry_feature(dec, sym)
        d1 = vol_pct(atr_d1(h1, cfg["data"]["d1_boundary"]["min_h1_bars"],
                            cfg["volatility"]["atr_period"]),
                     cfg["volatility"]["vol_pct_min_days"])
        out[sym] = with_axes(dec, d1, sym)
    return out


def segment_end(pre: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(pre["sample"]["last_decision_segment_end"]).replace(
        hour=23, minute=59, second=59, tzinfo=UTC)


def pooled(series: dict[str, pl.DataFrame]) -> pl.DataFrame:
    from src.research.labels import layer_a
    keep = ["ts_decision", "bar_ts", "symbol", "year", "hour", "vol_regime",
            "vol_pct_252", "fwd_atr", FEATURE, AGED, "ref_price", "atr_d1_14", "t1"]
    return pl.concat([layer_a(df, FEATURE).select(keep) for df in series.values()])


def by_axis(obs: pl.DataFrame, axis: str, min_n: int = 200) -> dict:
    out = {}
    for key, grp in obs.group_by(axis, maintain_order=True):
        name = str(key[0] if isinstance(key, tuple) else key)
        f, t = grp.get_column(FEATURE).to_numpy(), grp.get_column("fwd_atr").to_numpy()
        out[name] = {"n": int(grp.height),
                     "spearman": spearman(f, t) if grp.height >= min_n and f.std() > 0 else None}
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------
# Warstwa B — tylko przy SUPPORTED
# --------------------------------------------------------------------------

def run_layer_b(obs: pl.DataFrame, cfg: dict, pre: dict, symbols: list[str]) -> dict:
    from src.execution.costs import (
        attach_carry, carry_net_column, margins_from_config, net_column, reportable,
    )
    from src.harness.market import cost_model_for, load_m1
    from src.research.labels import layer_b
    from src.validation.bootstrap import block_bootstrap_expectancy
    from src.validation.deflation import as_report, deflate, live_trial_count

    margins = margins_from_config(cfg)
    b = pre["layer_b"]["barriers"]
    warmup = dt.datetime.fromisoformat(pre["sample"]["warmup_from"]).replace(tzinfo=UTC)
    parts = []
    for sym in symbols:
        mine = obs.filter(pl.col("symbol") == sym)
        if mine.is_empty():
            continue
        m1 = load_m1(sym, warmup, segment_end(pre), cfg)
        played = layer_b(mine, m1, cost_model_for(sym, cfg), feature_col=FEATURE,
                         sl_mult=float(b["sl_x_atr_d1_14"]),
                         tp_mult=float(b["tp_x_atr_d1_14"]), margins=margins)
        parts.append(attach_carry(played, margins, diff_col=FEATURE))
        del m1
    played = pl.concat(parts, how="diagonal")
    reportable(played, margins)
    bs = cfg["validation"]["bootstrap"]
    ts = played.select(pl.col("ts_decision").alias("ts"))["ts"]
    out = {"n_played": int(played.height), "per_margin": {}}
    for m in margins:
        row = {}
        for label, col in (("net", net_column(m)), ("net_carry", carry_net_column(m))):
            bb = block_bootstrap_expectancy(played.with_columns(ts), block_days=bs["block_days"],
                                            n_reps=bs["reps"], seed=0, value=col)
            row[label] = {"expectancy_r": bb.expectancy, "se": bb.se,
                          "ci_low": bb.ci_low, "ci_high": bb.ci_high}
        out["per_margin"][str(m)] = row
    try:
        out["deflation"] = as_report(deflate(
            played.get_column(carry_net_column(margins[1])).to_numpy(),
            live_trial_count(ROOT / "trials" / "trials.jsonl"),
            n_obs=int(pre["layer_a"]["power"]["n_eff"])))
    except ValueError as e:
        out["deflation"] = {"binding": False, "error": str(e)}
    return out


# --------------------------------------------------------------------------
# Checklista leakage'u
# --------------------------------------------------------------------------

LEAKAGE_DECLARATIONS = {
    "expanding_windows":
        "vol_pct_252 w oknie rozszerzającym; cecha nie jest normalizowana — "
        "test_labels.py::test_expanding_percentile_never_looks_forward",
    "no_fit_on_test":
        "NIE DOTYCZY — T004 nie dopasowuje modelu; surogat kalibrowany w M09B "
        "wyłącznie do geometrii cechy, bez zwrotów",
    "daily_from_closed_day":
        "atr_d1_14 i vol_pct_252 z available_from = doba+1; stopa polityki "
        "z dnia ≤ decyzja − 1 dzień roboczy (policy_pit, test_policy_rates.py)",
    "simulator_blind":
        "simulate_trade tnie okno samodzielnie; testy w test_simulator.py",
    "macro_alfred":
        "Stopy polityki point-in-time Z KONSTRUKCJI (nierewidowane, bez opóźnienia "
        "publikacji), margines 1 dnia roboczego; ALFRED zastąpiony ze względu na "
        "brak EUR PIT 2016–2017 (ADR-025, ADR-026); źródła zweryfikowane w M12",
    "purge_embargo":
        "NIE DOTYCZY jako podział — T004 nie dzieli próby. Nakładanie wchodzi do "
        "wnioskowania przez surogat na prawdziwej siatce (M10: pokrycie 0,93–0,97)",
}


def checklist(cfg: dict, run, pre: dict, obs: pl.DataFrame, cell: dict | None):
    from src.validation.leakage import run_checklist
    decl = dict(LEAKAGE_DECLARATIONS)
    if cell is None:
        decl["aged_feature"] = "sprawdzane w checkliście końcowej tego przebiegu"
    first = dt.datetime.fromisoformat(pre["sample"]["first_decision"]).replace(tzinfo=UTC)
    return run_checklist(
        cfg, json.loads((run.dir / "run.json").read_text(encoding="utf-8")),
        ROOT / "trials" / "trials.jsonl", observations=obs,
        segment=(first, segment_end(pre)), n_rows=obs.height,
        n_eff=int(pre["layer_a"]["power"]["n_eff"]),
        cells=None if cell is None else {"T004": cell}, declarations=decl)


# --------------------------------------------------------------------------
# Raport
# --------------------------------------------------------------------------

def write_markdown(path: Path, report: dict, pre: dict) -> None:
    c, v = report["cell"], report["cell"]["verdict"]
    L = [
        "# T004 — H04 carry, warstwa A", "",
        f"**Rodzaj:** `strategy` — **liczy się do N** ({pre['meta']['counter_before']} → "
        f"{pre['meta']['counter_after']}) · **Prerejestracja:** `configs/t004_carry.yaml` "
        f"`sha256 = {PREREG_SHA256[:16]}…`", "", "---", "",
        "## Werdykt", "", f"> **H04 → `{v['status']}`**", ">",
        f"> Spearman **{c['spearman']:+.4f}**, CI95 [{v['ci95'][0]:+.4f}, {v['ci95'][1]:+.4f}] "
        f"(SE z rozkładu zerowego {c['se_null']:.5f}).",
        f"> Górne ograniczenie: **{v['upper_bound_acc_pct']:.2f}%** trafności "
        "(próg opłacalności 51,72%).",
        f"> Dolny koniec po deflacji Šidáka (z = 2,8302): {v['ci_low_deflated']:+.4f}.",
        f"> `FALSIFIED` osiągalne w tym przebiegu: "
        f"{'tak' if v['falsified_reachable_in_run'] else 'NIE — SE powyżej 0,02756'}.", "",
        "Kryteria były ustalone przed uruchomieniem i nie zostały ruszone.", "",
        "## Przyrząd", "",
        "| | SE | pasmo M10 | wynik |", "|---|---|---|---|",
    ]
    for name in ("null", "boot"):
        k = report["consistency"][name]
        L.append(f"| {name} | {k['se']:.5f} | [{k['band'][0]:.5f}, {k['band'][1]:.5f}] | "
                 f"{'OK' if k['passes'] else 'STOP'} |")
    a = c.get("aged_control")
    if a:
        L += ["", "## Ramię postarzone (stopa o tydzień starsza)", "",
              f"Spearman {a['spearman_aged']:+.4f}, różnica {a['diff_aged_minus_true']:+.4f} "
              f"({a['in_se']:+.2f} SE) — **{'PRZECHODZI' if a['passes'] else 'STOP'}**."]
    if report.get("layer_b"):
        L += ["", "## Warstwa B — wycena", ""]
        for m, row in report["layer_b"]["per_margin"].items():
            L.append(f"* marża {m}: netto {row['net']['expectancy_r']:+.4f} R, "
                     f"z przychodem carry **{row['net_carry']['expectancy_r']:+.4f} R** "
                     f"CI [{row['net_carry']['ci_low']:+.4f}, {row['net_carry']['ci_high']:+.4f}]")
    else:
        L += ["", "## Warstwa B — nieuruchomiona", "",
              "Warstwa A bez `SUPPORTED` (ADR-003)."]
    lk = report.get("leakage_checklist")
    if lk:
        L += ["", "## Checklista leakage'u", "",
              f"**{'PRZECHODZI' if lk['passes'] else 'NIE PRZECHODZI'}** — "
              f"{lk['n_checks']} pozycji, {lk['n_failed']} niespełnionych."]
    L += ["", "## Czego ten przebieg nie zrobił", "",
          "* Nie dotknął segmentu OOS ani zapieczętowanego.",
          "* Nie mówi nic o carry na skali miesięcy (prereg: scope_of_result).",
          "* Nie zmienił żadnego kryterium po zobaczeniu wyniku.", ""]
    path.write_text("\n".join(L), encoding="utf-8")


# --------------------------------------------------------------------------
# Samosprawdzenie — świat syntetyczny M10
# --------------------------------------------------------------------------

def self_test() -> int:
    """Czy maszyneria odzyskuje efekt, który sama wsadziła — i tylko wtedy."""
    from m10_se_coverage import (
        SYMBOLS, decision_rows, month_of, simulate_fwd, time_axis,
    )
    m12 = json.loads((ROOT / "runs" / M12_RUN / "m09a_report.json").read_text(encoding="utf-8"))
    geom = m12["kinds"]["policy"]["currency"]
    b = json.loads((ROOT / "runs" / M09B_RUN / "m09b_report.json").read_text(encoding="utf-8"))
    calib = {m: b["models"][m]["calibration"] for m in MODELS}
    m05 = json.loads((ROOT / "runs" / "20260924T134703Z-cd0d96" / "m05_report.json")
                     .read_text(encoding="utf-8"))["horizons"]["3"]
    perm = [m05["symbols"].index(s) for s in SYMBOLS]
    chol_ret = psd_chol(np.asarray(m05["rho_matrix"])[np.ix_(perm, perm)])

    rng = np.random.default_rng(7)
    ts_h, _ = time_axis()
    rows = decision_rows(ts_h)
    p = len(SYMBOLS)
    mon = np.repeat(month_of(ts_h[rows], FIRST_MONTH, 0), p)
    rsym = np.tile(np.arange(p), rows.size)
    ts = pl.Series("ts_decision", np.repeat(ts_h[rows], p).astype("datetime64[ms]")
                   ).dt.replace_time_zone("UTC")

    phi = np.array([geom["per_currency"][c]["phi"] for c in CURRENCIES])
    sig = np.array([geom["per_currency"][c]["sigma_innov"] for c in CURRENCIES])
    carry = (simulate_rates(rng, int(mon.max()) + 1, phi,
                            sig * calib["ar1_measured"]["sigma_mult"],
                            psd_chol(np.asarray(geom["innovation_corr"])),
                            geom["level_pooled_mean"], calib["ar1_measured"]["level_sd"],
                            geom["level_pooled_mean"]) @ pair_matrix(SYMBOLS, CURRENCIES).T
             )[mon, rsym]
    fwd0 = simulate_fwd(rng, ts_h.size, chol_ret, "gauss", rows).ravel()
    null_sd = make_null_sd(mon, rsym, SYMBOLS, geom, calib, reps=150, seed=1)
    kw = dict(z_supported=2.8302, rho_breakeven=0.05401, block_days=20,
              boot_reps=150, aged=False)

    def frame(fwd):
        return pl.DataFrame({"ts_decision": ts, FEATURE: carry, "fwd_atr": fwd})

    print("  zero: cecha trwała bez związku z targetem")
    r0 = run_cell(frame(fwd0), null_sd, **kw)
    v0 = r0["verdict"]
    print(f"    rho={r0['spearman']:+.4f}  SE_null={r0['se_null']:.5f}  "
          f"SE_boot={r0['se_boot']:.5f}  -> {v0['status']}")
    assert v0["status"] != "SUPPORTED", "fałszywe SUPPORTED na zerze"
    assert 0.01236 <= r0["se_null"] <= 0.05084, "SE_null poza pasmem M10"

    print("  wzmocnienie: efekt zasiany (rho ≈ 0,20)")
    z = (carry - carry.mean()) / carry.std()
    fwd1 = 0.20 * z * fwd0.std() + np.sqrt(1 - 0.20 ** 2) * fwd0
    r1 = run_cell(frame(fwd1), null_sd, **kw)
    v1 = r1["verdict"]
    print(f"    rho={r1['spearman']:+.4f}  SE_null={r1['se_null']:.5f}  -> {v1['status']}")
    assert v1["status"] == "SUPPORTED", v1

    print("  werdykt na liczbach wpisanych ręcznie")
    assert verdict(0.0, 0.02, z_supported=2.8302, rho_breakeven=0.05401)["status"] == "FALSIFIED"
    assert verdict(0.0, 0.03, z_supported=2.8302, rho_breakeven=0.05401)["status"] == "NOT_SUPPORTED"
    assert verdict(0.07, 0.02, z_supported=2.8302, rho_breakeven=0.05401)["status"] == "SUPPORTED"
    assert verdict(0.05, 0.02, z_supported=2.8302, rho_breakeven=0.05401)["status"] == "NOT_SUPPORTED"

    print("\nSAMOSPRAWDZENIE PRZESZŁO. Licznik nietknięty, segment RESEARCH nietknięty.")
    return 0


# --------------------------------------------------------------------------
# Przebieg
# --------------------------------------------------------------------------

def check_prereg() -> dict:
    raw = PREREG.read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != PREREG_SHA256:
        raise SystemExit(
            "PREREJESTRACJA ZMIENIONA — start odmówiony.\n"
            f"  oczekiwano {PREREG_SHA256}\n  jest        {got}\n"
            "Zmiana po zamrożeniu to NOWY eksperyment z nowym ID, nie T004.")
    return yaml.safe_load(raw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true",
                    help="pipeline na danych syntetycznych; nie zapala prób")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    from src.harness.market import require_fresh_bars
    from src.research.grid import in_session, session_hours

    pre = check_prereg()
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    symbols = list(pre["sample"]["universe"])
    h = int(pre["grid"]["horizons_business_days"][0])
    fz = pre["falsification"]
    z_sup = float(fz["deflation"]["z_supported"])
    rho_be = float(fz["breakeven"]["rho_equivalent"])
    band = (0.5 * 0.02472, 2.0 * 0.02542)
    warmup = dt.datetime.fromisoformat(pre["sample"]["warmup_from"]).replace(tzinfo=UTC)
    require_fresh_bars(symbols, warmup, segment_end(pre), cfg)

    m12 = json.loads((ROOT / "runs" / M12_RUN / "m09a_report.json").read_text(encoding="utf-8"))
    geom = m12["kinds"]["policy"]["currency"]
    b = json.loads((ROOT / "runs" / M09B_RUN / "m09b_report.json").read_text(encoding="utf-8"))
    calib = {m: b["models"][m]["calibration"] for m in MODELS}

    params = {"prereg": "configs/t004_carry.yaml", "prereg_sha256": PREREG_SHA256,
              "hypothesis": "H04", "cell": f"carry_policy_h{h}", "symbols": symbols,
              "primary_statistic": "spearman(carry_policy, fwd_atr), rangi srednie",
              "ci": "rozklad zerowy surogatu (ADR-026)", "z_supported": z_sup}
    with start_run("T004 H04 carry — warstwa A, 1 komorka", params,
                   kind="strategy", n_variants=1) as run:
        series = build_observations(cfg, pre, symbols, h)
        sh, eh = session_hours(cfg)
        obs = pooled({s: in_session(df, sh, eh) for s, df in series.items()})
        dropped = {s: int(df.get_column(FEATURE).is_null().sum()) for s, df in series.items()}

        checklist(cfg, run, pre, obs, None).raise_if_failed()
        print(f"  checklista wstępna: PRZECHODZI ({obs.height} obserwacji)")

        sym_idx = {s: i for i, s in enumerate(symbols)}
        mon = month_index(obs.get_column("ts_decision"), FIRST_MONTH, 0)
        rsym = np.array([sym_idx[s] for s in obs.get_column("symbol").to_list()])
        null_sd = make_null_sd(mon, rsym, symbols, geom, calib,
                               reps=int(pre["layer_a"]["ci"]["reps_per_model"]),
                               seed=int(pre["layer_a"]["ci"]["surrogate_seed"]))
        cell = run_cell(obs, null_sd, z_supported=z_sup, rho_breakeven=rho_be,
                        block_days=cfg["validation"]["bootstrap"]["block_days"],
                        boot_reps=2000)

        report: dict = {"params": params, "cell": cell, "dropped_no_feature": dropped,
                        "consistency": {"null": consistency(cell["se_null"], band),
                                        "boot": consistency(cell["se_boot"], band)}}
        if not all(k["passes"] for k in report["consistency"].values()):
            raise SystemExit(f"STOP: SE poza pasmem M10 {report['consistency']} — "
                             "prerejestracja nakazuje zatrzymanie, nie interpretację.")
        if not cell["aged_control"]["passes"]:
            raise SystemExit("STOP: cecha postarzona LEPSZA — audyt wyrównania dat.")

        report["axes"] = {ax: by_axis(obs, ax) for ax in ("symbol", "year", "vol_regime")}
        report["axes"]["direction"] = by_axis(
            obs.with_columns(pl.when(pl.col(FEATURE) >= 0).then(pl.lit("long"))
                             .otherwise(pl.lit("short")).alias("direction")), "direction")
        sec = pooled(series)
        report["session_secondary"] = {
            "n": int(sec.height),
            "spearman": spearman(sec.get_column(FEATURE).to_numpy(),
                                 sec.get_column("fwd_atr").to_numpy()),
            "note": "bez CI i bez wpływu na werdykt"}

        report["layer_b"] = (run_layer_b(obs, cfg, pre, symbols)
                             if cell["verdict"]["status"] == "SUPPORTED" else None)

        cl = checklist(cfg, run, pre, obs, cell)
        cl.raise_if_failed()
        report["leakage_checklist"] = cl.as_report()

        pl.concat(list(series.values()), how="diagonal").write_parquet(
            run.dir / "observations.parquet")
        (run.dir / "t004_carry.yaml").write_bytes(PREREG.read_bytes())
        (run.dir / "t004_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        write_markdown(run.dir / "t004.md", report, pre)
        v = cell["verdict"]
        run.record(status=v["status"], rho=v["rho"], se_null=v["se_null"],
                   upper_bound_acc_pct=v["upper_bound_acc_pct"],
                   layer_b_run=report["layer_b"] is not None)
        print(f"\nWERDYKT H04: {v['status']}")
        print(f"rho={v['rho']:+.4f}  CI95=[{v['ci95'][0]:+.4f}, {v['ci95'][1]:+.4f}]  "
              f"górne ograniczenie {v['upper_bound_acc_pct']:.2f}%")
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
