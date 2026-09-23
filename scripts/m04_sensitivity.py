#!/usr/bin/env python3
"""M04 — kontrola czułości przyrządu (ADR-012). Kontrola, NIE próba strategii.

PYTANIE

M03 pokazał, że przyrząd wskazuje ZERO tam, gdzie nie ma informacji. Nie
pokazał, czy poprawnie wskazuje NIEZERO tam, gdzie informacja jest. Przyrząd
zepsuty na głucho przeszedłby M03 wzorowo.

M04 mierzy więc wzmocnienie, nie zero: **jakiej trafności kierunku odpowiada
jaka expectancy w R**.

DLACZEGO TO NIE JEST M04 Z FAZY 0

Pierwotny M04 porównywał `mom_k` z `mom_k` postarzonym o jeden bar. To wymaga
policzenia cechy, czyli oceny sygnału H01 — a H01 nie ma żywej prerejestracji
(T001 wycofany, ADR-011). Przebieg pokazałby expectancy H01, zanim T003
zostanie zamrożony, i skaziłby jego prerejestrację nieodwracalnie. Patrz
ADR-012.

Tutaj kierunek pochodzi ze **znaku faktycznego zwrotu w oknie transakcji** —
czyli z przyszłości, celowo i jawnie. To nie jest żadna cecha i nie da się
z tego wyczytać niczego o momentum.

SZTUCZKA, KTÓRA CZYNI TO TANIM

Dla każdego wylosowanego momentu odgrywamy OBIE strony. Znając wynik strony
trafnej i nietrafnej, expectancy reguły o trafności `p` liczy się wprost:

    E(p) = p · E[trafna] + (1 − p) · E[nietrafna]

Cała krzywa czułości wychodzi więc z jednego przebiegu, bez symulowania
każdego `p` osobno. Wartość `p = 0,5` musi odtworzyć wynik M03 — i to jest
niezależne sprawdzenie obu przebiegów naraz.

CO Z TEGO WYNIKA

Odwrócenie krzywej odpowiada na pytanie, którego M02 nie umiał postawić
w zrozumiałych jednostkach: **ilu procent trafności kierunku wymaga
przewaga na granicy wykrywalności.** „0,08 R" nic nie mówi intuicji;
„trzeba trafiać 56% kierunków" mówi wszystko.
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

from src.harness.market import (  # noqa: E402
    cost_model_for, load_h1, load_m1, require_fresh_bars,
)
from src.harness.registry import start_run  # noqa: E402
from src.research.entries import both_directions, simulate_entries  # noqa: E402
from src.research.grid import (  # noqa: E402
    decision_grid, in_session, session_hours, with_horizon,
)
from src.validation.bootstrap import block_bootstrap_expectancy  # noqa: E402

UTC = dt.timezone.utc

WARMUP_START = dt.datetime(2015, 1, 1, tzinfo=UTC)
FIRST_DECISION = dt.datetime(2016, 1, 1, tzinfo=UTC)
RESEARCH_END = dt.datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC)

HORIZONS = (3, 10)
BARRIERS = {3: (1.1, 2.2), 10: (2.0, 4.0)}
MOM_LOOKBACK_MAX = 480

DRAWS = 30_000
SEED = 20260924

ACCURACY_GRID = (0.50, 0.52, 0.55, 0.60, 0.70, 0.85, 1.00)

# Najmniejsza wykrywalna przewaga z M02, model konserwatywny (`20260923T172201Z-fa3731`).
MDE_FROM_M02 = {3: 0.0796, 10: 0.1463}

# Expectancy wejść losowych z M03 (`20260923T175353Z-087adf`) — punkt,
# w którym M04 przy p = 0,5 musi wylądować.
M03_EXPECTANCY = {3: -0.0248, 10: -0.0191}


def load_config() -> dict:
    return yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))


def build_pool(cfg: dict, symbols: list[str], h: int) -> pl.DataFrame:
    parts = []
    for sym in symbols:
        h1 = load_h1(sym, WARMUP_START, RESEARCH_END, cfg)
        dec, prices, _ = decision_grid(
            h1, first_decision=FIRST_DECISION, lookback_bars=MOM_LOOKBACK_MAX,
            atr_period=cfg["volatility"]["atr_period"],
            min_h1_bars=cfg["data"]["d1_boundary"]["min_h1_bars"])
        full = with_horizon(dec, prices, h, segment_end=RESEARCH_END)
        prim = in_session(full, *session_hours(cfg))
        parts.append(
            prim.select("ts_decision", "t1", "ref_price", "atr_d1_14", "fwd_atr")
                .with_columns(pl.lit(sym).alias("symbol")))
    pool = pl.concat(parts)
    # Zwrot musi być określony i niezerowy — bez znaku nie ma „strony trafnej".
    return pool.filter(
        pl.col("fwd_atr").is_not_null() & pl.col("fwd_atr").is_not_nan()
        & (pl.col("fwd_atr") != 0)
    )


def run_horizon(cfg: dict, symbols: list[str], h: int,
                rng: np.random.Generator) -> tuple[pl.DataFrame, dict]:
    """Odegraj obie strony z wylosowanych momentów i sparuj je po wejściu."""
    pool = build_pool(cfg, symbols, h)
    idx = rng.choice(pool.height, size=min(DRAWS, pool.height), replace=False)
    picked = pool[np.sort(idx)].with_row_index("entry_id")

    sl_mult, tp_mult = BARRIERS[h]
    done = []
    for sym in symbols:
        mine = picked.filter(pl.col("symbol") == sym)
        if mine.is_empty():
            continue
        m1 = load_m1(sym, FIRST_DECISION, RESEARCH_END, cfg)
        done.append(simulate_entries(both_directions(mine), m1,
                                     cost_model_for(sym, cfg),
                                     sl_mult=sl_mult, tp_mult=tp_mult))
        del m1
    trades = pl.concat(done)

    # Para long/short z tego samego momentu. Wejścia, dla których jedna strona
    # nie ma danych, wypadają w całości — inaczej „trafna" i „nietrafna"
    # liczyłyby się na różnych próbach.
    paired = (
        trades.pivot(on="side", index="entry_id", values="r")
        .drop_nulls(["long", "short"])
        .join(picked.select("entry_id", "symbol", "ts_decision", "t1", "fwd_atr"),
              on="entry_id")
        .with_columns(
            pl.when(pl.col("fwd_atr") > 0).then(pl.col("long"))
              .otherwise(pl.col("short")).alias("r_correct"),
            pl.when(pl.col("fwd_atr") > 0).then(pl.col("short"))
              .otherwise(pl.col("long")).alias("r_wrong"),
        )
        .rename({"ts_decision": "ts"})
    )
    reasons = (
        trades.join(picked.select("entry_id", "fwd_atr"), on="entry_id")
        .filter(((pl.col("fwd_atr") > 0) & (pl.col("side") == "long"))
                | ((pl.col("fwd_atr") < 0) & (pl.col("side") == "short")))
        .group_by("reason").len().sort("len", descending=True)
    )
    diag = {
        "pool": int(pool.height),
        "drawn": int(picked.height),
        "paired": int(paired.height),
        "oracle_exit_reasons": {r["reason"]: round(r["len"] / paired.height, 4)
                                for r in reasons.iter_rows(named=True)},
        "mean_abs_fwd_atr": float(paired["fwd_atr"].abs().mean()),
    }
    return paired, diag


def curve(paired: pl.DataFrame, cfg: dict, h: int) -> dict:
    """Expectancy w funkcji trafności kierunku, z przedziałami ufności.

    Dla danego `p` liczymy expectancy WARUNKOWĄ względem rzutu monetą:
    `p·r_trafna + (1−p)·r_nietrafna` na każde wejście. To jest ta sama
    średnia co przy faktycznym losowaniu kierunku, ale bez wariancji
    samego rzutu — węższy przedział opisuje więc niepewność POMIARU,
    nie niepewność pojedynczego przebiegu.
    """
    b = cfg["validation"]["bootstrap"]
    out = {}
    for p in ACCURACY_GRID:
        frame = paired.with_columns(
            (p * pl.col("r_correct") + (1 - p) * pl.col("r_wrong")).alias("r_p")
        )
        boot = block_bootstrap_expectancy(frame, block_days=b["block_days"],
                                          n_reps=b["reps"], seed=0, value="r_p")
        out[f"{p:.2f}"] = {
            "expectancy": boot.expectancy, "se": boot.se,
            "ci_low": boot.ci_low, "ci_high": boot.ci_high,
        }
    return out


def invert(e_correct: float, e_wrong: float, target: float) -> float:
    """Trafność `p`, przy której expectancy osiąga `target`."""
    span = e_correct - e_wrong
    return float("nan") if span == 0 else (target - e_wrong) / span


def main() -> int:
    cfg = load_config()
    symbols = list(cfg["instruments"]["discovery"])
    require_fresh_bars(symbols, WARMUP_START, RESEARCH_END, cfg)

    params = {
        "adr": "ADR-012",
        "purpose": "czułość przyrządu: trafność kierunku → expectancy w R",
        "direction_source": "znak faktycznego zwrotu w oknie transakcji "
                            "(przyszłość, celowo); ŻADNEJ cechy",
        "symbols": symbols, "horizons_business_days": list(HORIZONS),
        "barriers_x_atr_d1_14": {str(k): list(v) for k, v in BARRIERS.items()},
        "draws": DRAWS, "seed": SEED,
        "accuracy_grid": list(ACCURACY_GRID),
        "mde_from_m02": MDE_FROM_M02,
    }

    with start_run("M04 czułość przyrządu — krzywa trafność→expectancy (ADR-012)",
                   params, kind="control") as run:
        rng = np.random.default_rng(SEED)
        report = {"params": params, "horizons": {}}

        for h in HORIZONS:
            print(f"h={h}d: buduję populację i odgrywam obie strony…")
            paired, diag = run_horizon(cfg, symbols, h, rng)
            paired.write_parquet(run.dir / f"m04_paired_h{h}.parquet")

            ec = float(paired["r_correct"].mean())
            ew = float(paired["r_wrong"].mean())
            c = curve(paired, cfg, h)

            break_even = invert(ec, ew, 0.0)
            at_mde = invert(ec, ew, MDE_FROM_M02[h])
            noise = c["0.50"]["expectancy"]
            report["horizons"][str(h)] = {
                "diagnostics": diag,
                "e_correct": ec, "e_wrong": ew,
                "curve": c,
                "break_even_accuracy": break_even,
                "accuracy_at_mde": at_mde,
                "m03_expectancy": M03_EXPECTANCY[h],
                "m03_agreement": noise - M03_EXPECTANCY[h],
                "max_expectancy_perfect_foresight": c["1.00"]["expectancy"],
                # Ile z faktycznego ruchu bariery zamieniają na wynik: ruch
                # w jednostkach R to |fwd_atr| / sl_mult, bo R ≈ sl_mult × atr.
                "move_in_r_units": diag["mean_abs_fwd_atr"] / BARRIERS[h][0],
            }
            print(f"  trafna {ec:+.4f} R · nietrafna {ew:+.4f} R")
            print(f"  p=0,50 → {noise:+.4f} R (M03: {M03_EXPECTANCY[h]:+.4f}, "
                  f"różnica {noise - M03_EXPECTANCY[h]:+.4f})")
            print(f"  p=1,00 → {c['1.00']['expectancy']:+.4f} R "
                  f"(ruch bez barier: {report['horizons'][str(h)]['move_in_r_units']:.3f} R)")
            print(f"  próg opłacalności: p = {break_even:.4f}")
            print(f"  trafność dająca MDE {MDE_FROM_M02[h]:.4f} R: p = {at_mde:.4f}")

        (run.dir / "m04_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        run.record(**{
            f"h{h}_break_even_accuracy": report["horizons"][str(h)]["break_even_accuracy"]
            for h in HORIZONS
        }, **{
            f"h{h}_accuracy_at_mde": report["horizons"][str(h)]["accuracy_at_mde"]
            for h in HORIZONS
        })
        print(f"\nArtefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
