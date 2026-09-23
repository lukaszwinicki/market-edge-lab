#!/usr/bin/env python3
"""M03 — kalibracja przyrządu kontrolą losową. Kontrola, NIE próba strategii.

PYTANIE

Czy przyrząd, nakarmiony wejściami bez żadnej informacji, zwraca to, co
powinien: stratę równą kosztowi, istotnie różną od zera. Bez tego wynik
negatywny niczego nie dowodzi — nie da się odróżnić „nie ma przewagi"
od „przyrząd nie potrafi jej pokazać".

CO SIĘ ZMIENIA, A CO ZOSTAJE (config: validation.random_control)

    zostaje  instrument · okres · godziny · SL · TP · koszty · execution
    zmienia  moment wejścia · kierunek

Losowany jest moment I kierunek, niezależnie od siebie. To odróżnia M03 od
pomiaru σ w M02, gdzie z każdego bara wchodziliśmy w OBIE strony przy
zachowanym timingu — tamto mierzyło rozrzut, to mierzy obciążenie.

CZEGO TEN SKRYPT NIE ROBI

Nie liczy `mom_k` ani żadnej cechy. Nie porównuje się z niczym — kontrola
losowa DOPASOWANA LICZBĄ OBSERWACJI do prawdziwego przebiegu jest częścią
tego przebiegu, nie tego skryptu. T001 został wycofany (ADR-011), a T003
nie istnieje, więc porównywać nie ma z czym. Tu kalibrujemy przyrząd.

TRZY KRYTERIA (EXPERIMENTS.md, M03)

1. Expectancy wejść losowych ≈ −koszt modelowany.
2. CI95 leży pod zerem.
3. Wynik ujemny przy koszcie 1×, 2× i 3×.

CZWARTE PYTANIE, KTÓREGO NIE BYŁO W PLANIE

Czy „koszt modelowany" to ten koszt, który obiecała prerejestracja.
`CostModel` nie zna swapu, a prerejestracja T001 deklarowała oś marży
swapu. Skrypt liczy więc osobno, ile ten brakujący człon wynosi —
`src/execution/swap.py`, doliczany po fakcie, bez ruszania symulatora.
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

from src.data.resample import slice_window  # noqa: E402
from src.execution.simulator import Side, simulate_trade  # noqa: E402
from src.execution.swap import swap_margin_r  # noqa: E402
from src.harness.market import (  # noqa: E402
    cost_model_for, load_h1, load_m1, require_fresh_bars,
)
from src.harness.registry import start_run  # noqa: E402
from src.research.grid import (  # noqa: E402
    decision_grid, in_session, session_hours, with_horizon,
)
from src.validation.bootstrap import block_bootstrap_expectancy  # noqa: E402
from src.validation.overlap import effective_sample_size  # noqa: E402

UTC = dt.timezone.utc

WARMUP_START = dt.datetime(2015, 1, 1, tzinfo=UTC)
FIRST_DECISION = dt.datetime(2016, 1, 1, tzinfo=UTC)
RESEARCH_END = dt.datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC)

HORIZONS = (3, 10)
BARRIERS = {3: (1.1, 2.2), 10: (2.0, 4.0)}   # (SL, TP) × atr_d1_14
MOM_LOOKBACK_MAX = 480

DRAWS_PER_REP = 500
COST_MULTIPLIERS = (1, 2, 3)


def load_config() -> dict:
    return yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Losowanie wejść
# --------------------------------------------------------------------------

def draw_entries(pool: pl.DataFrame, reps: int, per_rep: int,
                 rng: np.random.Generator) -> pl.DataFrame:
    """`reps` × `per_rep` wejść: losowy moment (z parą) i losowy kierunek.

    Losujemy ZE ZWRACANIEM w obrębie przebiegu i między przebiegami — każda
    replikacja ma być niezależnym ciągnieniem z tej samej populacji decyzji,
    a nie podziałem jednej puli na kawałki.
    """
    n = reps * per_rep
    idx = rng.integers(0, pool.height, size=n)
    long = rng.random(n) < 0.5
    return (
        pool[idx]
        .with_columns(
            pl.Series("rep", np.repeat(np.arange(reps), per_rep)),
            pl.Series("side", np.where(long, "long", "short")),
        )
    )


def simulate_draws(draws: dict[int, pl.DataFrame], cfg: dict,
                   symbols: list[str]) -> dict[int, pl.DataFrame]:
    """Odegraj wylosowane wejścia. M1 ładowane raz na parę, na oba horyzonty."""
    out: dict[int, list[dict]] = {h: [] for h in draws}
    for sym in symbols:
        m1 = load_m1(sym, FIRST_DECISION, RESEARCH_END, cfg)
        cost = cost_model_for(sym, cfg)
        for h, frame in draws.items():
            sl_mult, tp_mult = BARRIERS[h]
            mine = frame.filter(pl.col("symbol") == sym)
            for row in mine.iter_rows(named=True):
                ref, atr = row["ref_price"], row["atr_d1_14"]
                long = row["side"] == "long"
                sl = ref - sl_mult * atr if long else ref + sl_mult * atr
                tp = ref + tp_mult * atr if long else ref - tp_mult * atr
                window = slice_window(m1, row["ts_decision"], row["t1"])
                res = simulate_trade(Side.LONG if long else Side.SHORT,
                                     row["ts_decision"], sl, tp, row["t1"],
                                     window, cost)
                if res is None:
                    continue
                out[h].append({
                    "rep": row["rep"], "symbol": sym, "side": row["side"],
                    "ts": row["ts_decision"], "t1": row["t1"],
                    "exit_ts": res.exit.time, "reason": res.reason.value,
                    "r": res.r, "net": res.net, "cost": res.cost,
                    "slippage": res.slippage, "risk": res.risk,
                    "ref_price": ref,
                })
        del m1
    return {h: pl.DataFrame(rows) for h, rows in out.items()}


# --------------------------------------------------------------------------
# Przeliczenia kosztowe — z pól, które symulator już raportuje
# --------------------------------------------------------------------------

def with_cost_variants(trades: pl.DataFrame, cfg: dict) -> pl.DataFrame:
    """Dolicz warianty 2×/3× kosztów i marżę swapu.

    Krotność kosztów liczymy analitycznie, a nie przez powtórzenie symulacji:
    `slippage` siedzi w cenach fillów, a `cost` to spread plus dopłata do
    podłogi, więc wynik bez tarcia to `net + cost + slippage`, a wynik przy
    krotności k to `net − (k−1)·(cost + slippage)`.

    PRZYBLIŻENIE. Przy realnie wyższych kosztach fill padałby nieco gdzie
    indziej i bariera mogłaby paść w innym barze. Przeliczenie tego nie
    widzi — tak samo jak nie widziała tego prerejestracja, która o taki
    właśnie raport 1×/2×/3× prosiła.
    """
    friction = pl.col("cost") + pl.col("slippage")
    out = trades.with_columns(
        [(pl.col("net") - (k - 1) * friction).truediv(pl.col("risk")).alias(f"r_{k}x")
         for k in COST_MULTIPLIERS]
        + [(friction / pl.col("risk")).alias("cost_r")]
    )

    margins = cfg["costs"]["swap"]["margin_sensitivity"]
    triple = cfg["costs"]["swap"]["triple_on_wednesday"]
    rows = out.select("ref_price", "risk", "ts", "exit_ts").iter_rows(named=True)
    cached = list(rows)
    for m in margins:
        swap = [swap_margin_r(r["ref_price"], r["risk"], r["ts"], r["exit_ts"], m,
                              triple_on_wednesday=triple) for r in cached]
        out = out.with_columns(pl.Series(f"swap_r_{m}", swap))
    return out


# --------------------------------------------------------------------------
# Statystyka
# --------------------------------------------------------------------------

def calibration(trades: pl.DataFrame, cfg: dict) -> dict:
    """Trzy kryteria M03 plus rachunek brakującego członu kosztu."""
    b = cfg["validation"]["bootstrap"]
    res = {}

    for k in COST_MULTIPLIERS:
        boot = block_bootstrap_expectancy(
            trades, block_days=b["block_days"], n_reps=b["reps"],
            seed=0, value=f"r_{k}x")
        res[f"{k}x"] = {
            "expectancy": boot.expectancy, "se": boot.se, "t_stat": boot.t_stat,
            "ci_low": boot.ci_low, "ci_high": boot.ci_high,
            "ci_below_zero": bool(boot.ci_high < 0),
            "n_trades": boot.n_trades, "n_days": boot.n_days,
        }

    modelled = float(trades["cost_r"].mean())
    exp1 = res["1x"]["expectancy"]
    res["modelled_cost_r"] = modelled
    res["expectancy_minus_negative_cost"] = exp1 + modelled
    res["gap_in_se"] = (exp1 + modelled) / res["1x"]["se"] if res["1x"]["se"] else None

    margins = cfg["costs"]["swap"]["margin_sensitivity"]
    res["swap_margin_r"] = {
        str(m): {
            "mean": float(trades[f"swap_r_{m}"].mean()),
            "vs_modelled_cost": float(trades[f"swap_r_{m}"].mean()) / modelled,
        }
        for m in margins
    }
    res["exit_reasons"] = {
        r["reason"]: round(r["len"] / trades.height, 4)
        for r in trades.group_by("reason").len().sort("len", descending=True).iter_rows(named=True)
    }
    return res


def per_rep_distribution(trades: pl.DataFrame) -> dict:
    """Rozkład expectancy po przebiegach — to, czym T003 będzie się mierzył."""
    per = trades.group_by("rep").agg(pl.col("r_1x").mean().alias("e")).sort("rep")
    e = per["e"].to_numpy()
    return {
        "n_reps": int(per.height),
        "mean": float(e.mean()),
        "sd": float(e.std(ddof=1)),
        "p2_5": float(np.percentile(e, 2.5)),
        "p50": float(np.percentile(e, 50)),
        "p97_5": float(np.percentile(e, 97.5)),
        "share_negative": float((e < 0).mean()),
    }


def main() -> int:
    cfg = load_config()
    symbols = list(cfg["instruments"]["discovery"])
    rc = cfg["validation"]["random_control"]
    reps, seed = int(rc["reps"]), int(rc["seed"])
    require_fresh_bars(symbols, WARMUP_START, RESEARCH_END, cfg)

    params = {
        "purpose": "kalibracja przyrządu, nie porównanie ze strategią",
        "symbols": symbols, "horizons_business_days": list(HORIZONS),
        "barriers_x_atr_d1_14": {str(k): list(v) for k, v in BARRIERS.items()},
        "reps": reps, "draws_per_rep": DRAWS_PER_REP, "seed": seed,
        "cost_multipliers": list(COST_MULTIPLIERS),
        "swap_margins": cfg["costs"]["swap"]["margin_sensitivity"],
        "note_swap": "symulator nie modeluje swapu; marża doliczana po fakcie",
    }

    with start_run("M03 kontrola losowa — kalibracja przyrządu", params,
                   kind="control") as run:
        rng = np.random.default_rng(seed)

        print("Buduję siatkę decyzyjną…")
        pools = {}
        for h in HORIZONS:
            parts = []
            for sym in symbols:
                h1 = load_h1(sym, WARMUP_START, RESEARCH_END, cfg)
                dec, prices, _ = decision_grid(
                    h1, first_decision=FIRST_DECISION, lookback_bars=MOM_LOOKBACK_MAX,
                    atr_period=cfg["volatility"]["atr_period"],
                    min_h1_bars=cfg["data"]["d1_boundary"]["min_h1_bars"])
                full = with_horizon(dec, prices, h, segment_end=RESEARCH_END)
                prim = in_session(full, *session_hours(cfg))
                parts.append(prim.select("ts_decision", "t1", "ref_price", "atr_d1_14")
                             .with_columns(pl.lit(sym).alias("symbol")))
            pools[h] = pl.concat(parts)
            print(f"  h={h}d: populacja {pools[h].height} decyzji")

        draws = {h: draw_entries(pools[h], reps, DRAWS_PER_REP, rng) for h in HORIZONS}
        print(f"Symuluję {reps}×{DRAWS_PER_REP}×{len(HORIZONS)} wejść…")
        simulated = simulate_draws(draws, cfg, symbols)

        report = {"params": params, "horizons": {}}
        for h in HORIZONS:
            trades = with_cost_variants(simulated[h], cfg).sort("ts")
            trades.write_parquet(run.dir / f"m03_trades_h{h}.parquet")

            cal = calibration(trades, cfg)
            dist = per_rep_distribution(trades)
            n_eff = effective_sample_size(trades.select("ts", "t1"))
            report["horizons"][str(h)] = {
                "n_simulated": int(trades.height),
                "n_eff_windows": int(n_eff),
                "calibration": cal,
                "per_rep": dist,
            }
            one = cal["1x"]
            print(f"\n  h={h}d  n={trades.height}  expectancy {one['expectancy']:+.4f} R"
                  f"  CI95 [{one['ci_low']:+.4f}, {one['ci_high']:+.4f}]")
            print(f"        koszt modelowany {cal['modelled_cost_r']:.4f} R,"
                  f"  luka {cal['expectancy_minus_negative_cost']:+.4f} R"
                  f"  ({cal['gap_in_se']:+.2f} SE)")
            for k in COST_MULTIPLIERS:
                c = cal[f"{k}x"]
                print(f"        {k}×: {c['expectancy']:+.4f} R, "
                      f"CI pod zerem: {'TAK' if c['ci_below_zero'] else 'NIE'}")
            sw = cal["swap_margin_r"]["0.01"]
            print(f"        BRAK w modelu — marża swapu 1%: {sw['mean']:.4f} R "
                  f"({sw['vs_modelled_cost']:.2f}× koszt modelowany)")

        verdict = {}
        for h in HORIZONS:
            cal = report["horizons"][str(h)]["calibration"]
            verdict[str(h)] = {
                "expectancy_matches_cost": abs(cal["gap_in_se"]) < 2,
                "ci_below_zero_all_multipliers": all(
                    cal[f"{k}x"]["ci_below_zero"] for k in COST_MULTIPLIERS),
                "negative_at_all_multipliers": all(
                    cal[f"{k}x"]["expectancy"] < 0 for k in COST_MULTIPLIERS),
            }
            verdict[str(h)]["passes"] = all(verdict[str(h)].values())
        report["verdict"] = verdict

        (run.dir / "m03_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        run.record(**{f"h{h}_passes": verdict[str(h)]["passes"] for h in HORIZONS})

        print("\nKryteria M03:")
        for h in HORIZONS:
            v = verdict[str(h)]
            print(f"  h={h}d: expectancy≈−koszt {v['expectancy_matches_cost']} · "
                  f"CI<0 {v['ci_below_zero_all_multipliers']} · "
                  f"ujemne 1/2/3× {v['negative_at_all_multipliers']} "
                  f"→ {'PRZECHODZI' if v['passes'] else 'NIE PRZECHODZI'}")
        print(f"\nArtefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
