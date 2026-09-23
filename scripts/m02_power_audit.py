#!/usr/bin/env python3
"""M02 — audyt mocy (ADR-009). Kontrola aparatury, NIE próba strategii.

PYTANIE

Ile obserwacji naprawdę niezależnych daje siatka decyzyjna T001 przy
horyzontach 3 i 10 dni roboczych, i jaka z tego wynika najmniejsza
wykrywalna przewaga. Bramka ADR-009: jeżeli przy OBU horyzontach
wykrywalna przewaga wynosi ≥ 0,08 R, T001 nie startuje.

CZEGO TEN SKRYPT NIE ROBI

Nie liczy `mom_k`. Sprawdza wyłącznie, czy cecha JEST OKREŚLONA (czy istnieje
480 wcześniejszych barów i dodatni `atr_h1_14`) — nigdy jej wartości ani znaku.
Moc zależy od geometrii próby, nie od treści sygnału, a obejrzenie sygnału
przed prerejestrowanym uruchomieniem byłoby zapaleniem pierwszej próby.

Nie jest kontrolą losową (M03). Wejścia long i short z każdego losowanego
bara służą do zmierzenia ROZRZUTU wyniku, nie do oceny timingu.

TRZY WIELKOŚCI, TRZY OSOBNE POMIARY

1. n_eff w czasie — zachłannie po rozłącznych oknach `(ts, t1)`, per para.
   Wąskim gardłem jest nakładanie okien, nie liczba wierszy.
2. n_eff w przekroju par — sześć par to nie sześć niezależnych rynków.
   Liczone z macierzy korelacji jako P² / ΣΣρ, czyli dokładnie tak, jak
   korelacja wchodzi do wariancji średniej.
3. σ wyniku w R — bez niej n_eff nie zamienia się na żadną przewagę.
   Mierzona symulatorem na barach M1, na losowanej podpróbie, w obie strony.

σ NIE JEST DZIEDZICZONA

Szacunki w ADR-009 (0,042 R przy n_eff 450) powstały przez przeskalowanie
połowy CI z `market-quant` przez √n. To zakłada, że σ w R jest taka sama
przy innej geometrii barier i bez warstwy portfelowej. Tego nikt nie
sprawdził — i właśnie dlatego jest M02.
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

from src.data.resample import decision_time_for_bar, last_closed_bar, slice_window  # noqa: E402
from src.data.timeaxis import add_business_days  # noqa: E402
from src.execution.simulator import Side, simulate_trade  # noqa: E402
from src.features.volatility import atr_d1, atr_h1, attach_atr_d1  # noqa: E402
from src.harness.market import (  # noqa: E402
    cost_model_for, load_h1, load_m1, require_fresh_bars,
)
from src.harness.registry import start_run  # noqa: E402
from src.validation.overlap import effective_sample_size, overlap_fraction  # noqa: E402

UTC = dt.timezone.utc
H1_SECONDS = 3600

# --- parametry pomiaru, wszystkie z prerejestracji T001 lub z base.yaml ----

WARMUP_START = dt.datetime(2015, 1, 1, tzinfo=UTC)
FIRST_DECISION = dt.datetime(2016, 1, 1, tzinfo=UTC)
RESEARCH_END = dt.datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC)

HORIZONS = (3, 10)                       # dni robocze
BARRIERS = {3: (1.1, 2.2), 10: (2.0, 4.0)}   # (SL, TP) × atr_d1_14
MOM_LOOKBACK_MAX = 480                   # najdłuższe k z siatki T001

# Godzina decyzji brana do przekroju par. Wewnątrz sesji primary u wszystkich
# par, płynna, i — co ważniejsze — JEDNA dla wszystkich, żeby korelacja
# liczyła się na tym samym momencie, a nie na sześciu różnych.
CROSS_HOUR = 9

SIGMA_SAMPLE = 2000                      # losowanych decyzji na horyzont
SEED = 20260923

# Konwencja mocy. ADR-009 podaje próg 0,08 R, ale nie definiuje, czym jest
# „wykrywalna przewaga". Odtwarzamy konwencję z liczb poprzednika: 0,067 R
# połowy CI → „≥0,10 R" to iloraz 1,43, czyli dokładnie (z_0,975 + z_0,80).
# Test dwustronny, α = 0,05, moc 80%.
Z_CI = 1.959963984540054
Z_POWER = 0.8416212335729143
MDE_FACTOR = Z_CI + Z_POWER

GATE_R = 0.08                            # ADR-009


def load_config() -> dict:
    return yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))


def map_ts(col: str, fn) -> pl.Expr:
    """Zastosuj funkcję osi czasu do kolumny znaczników.

    `datetime` Pythona ma rozdzielczość mikrosekundową, bary — milisekundową,
    więc wynik wraca w „us" i jest rzutowany z powrotem. Opakowane, bo
    alternatywą jest arytmetyka na znacznikach wprost w wyrażeniu, czyli
    dokładnie to, czego zakazuje CLAUDE.md.
    """
    return (
        pl.col(col)
        .map_elements(fn, return_dtype=pl.Datetime("us", "UTC"))
        .cast(pl.Datetime("ms", "UTC"))
    )


# --------------------------------------------------------------------------
# Siatka decyzyjna
# --------------------------------------------------------------------------

def decision_grid(symbol: str, cfg: dict) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """Decyzje T001 dla jednej pary: (siatka, ceny H1, diagnostyka).

    Zwraca wyłącznie momenty decyzji i ceny odniesienia. Żadnej cechy,
    żadnego kierunku — tylko to, KIEDY zapadałaby decyzja.
    """
    period = cfg["volatility"]["atr_period"]
    min_h1 = cfg["data"]["d1_boundary"]["min_h1_bars"]

    h1 = load_h1(symbol, WARMUP_START, RESEARCH_END, cfg)
    h1 = atr_h1(h1, period)
    d1 = atr_d1(h1, min_h1, period)

    dec = (
        h1.with_row_index("bar_i")
        .select("bar_i", "ts", "bid_close", "atr_h1_14")
        .filter(
            (pl.col("bar_i") >= MOM_LOOKBACK_MAX)
            & pl.col("atr_h1_14").is_not_nan()
            & pl.col("atr_h1_14").is_not_null()
            & (pl.col("atr_h1_14") > 0)
        )
        .with_columns(
            map_ts("ts", lambda t: decision_time_for_bar(t, H1_SECONDS))
            .alias("ts_decision")
        )
        .rename({"ts": "bar_ts", "bid_close": "ref_price"})
        .filter(pl.col("ts_decision") >= FIRST_DECISION)
    )

    n_before_atr = dec.height
    dec = attach_atr_d1(dec, d1, on="ts_decision").filter(
        pl.col("atr_d1_14").is_not_null()
        & pl.col("atr_d1_14").is_not_nan()
        & (pl.col("atr_d1_14") > 0)
    )

    prices = h1.select(pl.col("ts").alias("px_ts"), pl.col("bid_close").alias("exit_price"))
    diag = {
        "h1_bars_total": h1.height,
        "decisions_feature_defined": n_before_atr,
        "decisions_atr_d1_defined": dec.height,
        "dropped_no_atr_d1": n_before_atr - dec.height,
    }
    return dec, prices, diag


def with_horizon(dec: pl.DataFrame, prices: pl.DataFrame, h: int) -> pl.DataFrame:
    """Dołóż barierę czasową `t1`, cenę wyjścia i target A.

    Okna wychodzące poza segment RESEARCH są odcinane. Decyzja z 28.12.2021
    przy h = 10 d rozstrzyga się w styczniu 2022, czyli w segmencie OOS —
    a OOS ma reżim ograniczonych uruchomień. Prerejestracja T001 mówi
    „decyzje do 2021-12-31" i tej granicy nie rozstrzyga; tutaj wybieramy
    wariant, który NIE dotyka OOS, i zgłaszamy to jako lukę do domknięcia.
    """
    out = (
        dec.with_columns(
            map_ts("ts_decision", lambda t: add_business_days(t, h)).alias("t1")
        )
        .filter(pl.col("t1") <= RESEARCH_END)
    )
    # Cena wyjścia z ostatniego bara ZAMKNIĘTEGO przed barierą. Bar o etykiecie
    # równej t1 zamyka się dopiero godzinę później — jego użycie to look-ahead.
    out = (
        out.with_columns(
            map_ts("t1", lambda t: last_closed_bar(t, H1_SECONDS)).alias("exit_bar")
        )
        .sort("exit_bar")
        .join_asof(prices.sort("px_ts"), left_on="exit_bar", right_on="px_ts",
                   strategy="backward")
        .sort("ts_decision")
    )
    return out.with_columns(
        ((pl.col("exit_price") - pl.col("ref_price")) / pl.col("atr_d1_14"))
        .alias("fwd_atr")
    )


def in_session(df: pl.DataFrame, cfg: dict) -> pl.DataFrame:
    """Sesja primary: decyzje w [08:00, 22:00) UTC — 14 na dobę handlową."""
    s = cfg["validation"]["sessions"]["primary"]
    start_h = int(str(s["start"]).split(":")[0])
    end_h = int(str(s["end"]).split(":")[0])
    hour = pl.col("ts_decision").dt.hour()
    return df.filter((hour >= start_h) & (hour < end_h))


# --------------------------------------------------------------------------
# 1. n_eff w czasie
# --------------------------------------------------------------------------

def temporal_neff(df: pl.DataFrame) -> dict:
    """Nakładanie i liczba rozłącznych okien dla jednej pary i horyzontu."""
    frame = df.select(pl.col("ts_decision").alias("ts"), "t1")
    n_eff = effective_sample_size(frame)
    return {
        "n_rows": frame.height,
        "overlap_fraction": overlap_fraction(frame),
        "n_eff": n_eff,
        "rows_per_eff": frame.height / n_eff if n_eff else float("nan"),
    }


# --------------------------------------------------------------------------
# 2. n_eff w przekroju par
# --------------------------------------------------------------------------

def cross_sectional(series: dict[str, pl.DataFrame], h: int) -> dict:
    """Efektywna liczba niezależnych par z macierzy korelacji.

    Wchodzą zwroty target A z JEDNEJ godziny decyzyjnej, przerzedzone co `h`
    dni roboczych, żeby korelacja nie liczyła się na oknach nałożonych na
    siebie. Wszystkie `h` przesunięć fazy są uśredniane — inaczej wynik
    zależałby od tego, w którym dniu zaczniemy liczyć.

    UWAGA DO INTERPRETACJI. T001 uśrednia zwroty PRZEMNOŻONE przez znak
    cechy, a tego nie da się zmierzyć bez policzenia cechy. Dlatego obok
    wersji ze znakiem podajemy wersję na |ρ|: jeżeli znaki na parach są
    skorelowane, ujemna korelacja surowych zwrotów przestaje pomagać.
    Wersja na |ρ| jest konserwatywna i to ona idzie do bramki.
    """
    aligned = None
    for sym, df in series.items():
        col = (
            df.filter(pl.col("ts_decision").dt.hour() == CROSS_HOUR)
            .select(pl.col("ts_decision").dt.date().alias("date"),
                    pl.col("fwd_atr").alias(sym))
            .group_by("date").agg(pl.col(sym).first())
        )
        aligned = col if aligned is None else aligned.join(col, on="date", how="inner")

    aligned = aligned.sort("date").drop_nulls()
    symbols = [c for c in aligned.columns if c != "date"]
    mat = aligned.select(symbols).to_numpy()

    # Przerzedzenie co h dni roboczych, uśrednione po wszystkich fazach.
    mats = []
    for phase in range(h):
        sub = mat[phase::h]
        if sub.shape[0] > len(symbols) + 2:
            mats.append(np.corrcoef(sub, rowvar=False))
    rho = np.mean(mats, axis=0)

    p = len(symbols)
    off = ~np.eye(p, dtype=bool)
    return {
        "symbols": symbols,
        "n_aligned_days": int(aligned.height),
        "n_thinned_per_phase": int(mat[0::h].shape[0]),
        "rho_mean_offdiag": float(rho[off].mean()),
        "abs_rho_mean_offdiag": float(np.abs(rho[off]).mean()),
        "rho_matrix": rho.round(4).tolist(),
        "n_eff_pairs_independent": float(p),
        "n_eff_pairs_signed": float(p ** 2 / rho.sum()),
        "n_eff_pairs_abs": float(p ** 2 / np.abs(rho).sum()),
    }


def serial_autocorr(series: dict[str, pl.DataFrame], h: int) -> dict[str, float]:
    """Autokorelacja lag-1 na oknach ROZŁĄCZNYCH.

    Jeżeli jest bliska zeru, zachłanne n_eff nie jest zawyżone. Jeżeli nie —
    nawet rozłączne okna nie są niezależne i moc jest jeszcze mniejsza.
    """
    out = {}
    for sym, df in series.items():
        v = (
            df.filter(pl.col("ts_decision").dt.hour() == CROSS_HOUR)
            .sort("ts_decision")
            .get_column("fwd_atr")
            .to_numpy()
        )
        v = v[~np.isnan(v)][::h]
        out[sym] = float(np.corrcoef(v[:-1], v[1:])[0, 1]) if v.size > 10 else float("nan")
    return out


# --------------------------------------------------------------------------
# 3. σ wyniku w R
# --------------------------------------------------------------------------

def sigma_sample(series: dict[str, pl.DataFrame], cfg: dict, h: int,
                 rng: np.random.Generator) -> pl.DataFrame:
    """Rozrzut wyniku w R, zmierzony symulatorem na losowanej podpróbie.

    Z każdego wylosowanego bara wchodzimy w OBIE strony. Pod hipotezą zerową
    rozkład wyniku nie zależy od kierunku, więc pula long+short jest
    rozkładem wyniku „bez przewagi" — a to jest dokładnie σ, która stoi
    w mianowniku przedziału ufności.

    Bariery: SL i TP z prerejestracji T001, skalowane `atr_d1_14`, liczone
    od ceny odniesienia dostępnej w momencie decyzji.
    """
    sl_mult, tp_mult = BARRIERS[h]
    pool = pl.concat([
        df.select("ts_decision", "t1", "ref_price", "atr_d1_14")
          .with_columns(pl.lit(sym).alias("symbol"))
        for sym, df in series.items()
    ])
    take = min(SIGMA_SAMPLE, pool.height)
    idx = rng.choice(pool.height, size=take, replace=False)
    picked = pool[np.sort(idx)]

    # Ile razy symulator natrafił na bar M1 mieszczący OBIE bariery. Bez ticków
    # rozstrzyga je pesymistycznie (SL), co zaniża wynik i rusza σ. Podstawiamy
    # pustą ramkę — zachowanie identyczne jak przy `load_ticks=None` — żeby
    # policzyć te przypadki zamiast zakładać, że ich nie ma.
    ambiguous = {"n": 0}
    empty_ticks = pl.DataFrame(
        schema={"ts": pl.Datetime("ms", "UTC"), "bid": pl.Float64, "ask": pl.Float64}
    )

    def count_ambiguous(_start, _end):
        ambiguous["n"] += 1
        return empty_ticks

    rows = []
    for sym in sorted(series):
        mine = picked.filter(pl.col("symbol") == sym)
        if mine.is_empty():
            continue
        m1 = load_m1(sym, FIRST_DECISION, RESEARCH_END, cfg)
        cost = cost_model_for(sym, cfg)
        for r in mine.iter_rows(named=True):
            ref, atr = r["ref_price"], r["atr_d1_14"]
            window = slice_window(m1, r["ts_decision"], r["t1"])
            for side in (Side.LONG, Side.SHORT):
                if side is Side.LONG:
                    sl, tp = ref - sl_mult * atr, ref + tp_mult * atr
                else:
                    sl, tp = ref + sl_mult * atr, ref - tp_mult * atr
                res = simulate_trade(side, r["ts_decision"], sl, tp, r["t1"],
                                     window, cost, count_ambiguous)
                rows.append({
                    "symbol": sym, "ts_decision": r["ts_decision"],
                    "side": side.value,
                    "r": None if res is None else res.r,
                    "reason": None if res is None else res.reason.value,
                })
        del m1
    return pl.DataFrame(rows), ambiguous["n"]


def sigma_stats(trades: pl.DataFrame) -> dict:
    ok = trades.filter(pl.col("r").is_not_null())
    r = ok.get_column("r").to_numpy()
    by_reason = (
        ok.group_by("reason").len().sort("len", descending=True)
        .with_columns((pl.col("len") / ok.height).round(4).alias("share"))
    )
    return {
        "n_simulated": trades.height,
        "n_resolved": int(ok.height),
        "no_trade_share": round(1 - ok.height / trades.height, 4) if trades.height else None,
        "sigma_r": float(r.std(ddof=1)),
        "sigma_r_se": float(r.std(ddof=1) / np.sqrt(2 * (r.size - 1))),
        "mean_r": float(r.mean()),
        "sigma_long": float(ok.filter(pl.col("side") == "long")["r"].to_numpy().std(ddof=1)),
        "sigma_short": float(ok.filter(pl.col("side") == "short")["r"].to_numpy().std(ddof=1)),
        "exit_reasons": {row["reason"]: row["share"] for row in by_reason.iter_rows(named=True)},
    }


# --------------------------------------------------------------------------
# Złożenie
# --------------------------------------------------------------------------

def power(sigma: float, n_eff: float) -> dict:
    half_ci = Z_CI * sigma / np.sqrt(n_eff)
    return {
        "n_eff": round(float(n_eff), 1),
        "half_ci_r": round(float(half_ci), 4),
        "mde_r": round(float(MDE_FACTOR * sigma / np.sqrt(n_eff)), 4),
    }


def gate_state(mde: float, rel_se: float) -> str:
    """Stan bramki ADR-009 dla jednego horyzontu, z pasmem nierozstrzygalności.

    MDE jest wielkością MIERZONĄ, nie znaną — jej niepewność bierze się
    z niepewności σ. Porównanie punktowe z progiem 0,08 R zamienia różnicę
    mniejszą od błędu pomiaru w decyzję binarną. Pasmo ±2 błędy standardowe
    jest tu po to, żeby tego nie robić.
    """
    band = 2 * rel_se * mde
    if mde >= GATE_R + band:
        return "BLOKUJE"
    if mde <= GATE_R - band:
        return "PRZEPUSZCZA"
    return "NIEROZSTRZYGNIĘTE"


def overall_gate(states: dict[int, str]) -> str:
    """ADR-009: T001 nie startuje, gdy MDE ≥ 0,08 R przy OBU horyzontach.

    Wystarczy więc jeden horyzont, który PRZEPUSZCZA, żeby T001 mógł
    wystartować — ale „nierozstrzygnięte" nie jest przepustką.
    """
    if all(s == "BLOKUJE" for s in states.values()):
        return "T001 ZABLOKOWANY"
    if any(s == "PRZEPUSZCZA" for s in states.values()):
        return "T001 MOŻE WYSTARTOWAĆ"
    return "NIEROZSTRZYGNIĘTE"


def main() -> int:
    cfg = load_config()
    symbols = list(cfg["instruments"]["discovery"])
    require_fresh_bars(symbols, WARMUP_START, RESEARCH_END, cfg)

    params = {
        "adr": "ADR-009",
        "horizons_business_days": list(HORIZONS),
        "barriers_x_atr_d1_14": {str(k): list(v) for k, v in BARRIERS.items()},
        "symbols": symbols,
        "first_decision": FIRST_DECISION.isoformat(),
        "research_end": RESEARCH_END.isoformat(),
        "mom_lookback_max": MOM_LOOKBACK_MAX,
        "sigma_sample": SIGMA_SAMPLE,
        "seed": SEED,
        "power_convention": {"alpha": 0.05, "two_sided": True, "power": 0.80,
                             "mde_factor": MDE_FACTOR},
        "gate_r": GATE_R,
    }

    with start_run("M02 audyt mocy — n_eff i wykrywalna przewaga (ADR-009)",
                   params, kind="control") as run:
        rng = np.random.default_rng(SEED)
        report: dict = {"params": params, "per_symbol": {}, "horizons": {}}

        grids, prices, diags = {}, {}, {}
        for sym in symbols:
            grids[sym], prices[sym], diags[sym] = decision_grid(sym, cfg)
            print(f"  {sym}: {diags[sym]['decisions_atr_d1_defined']} decyzji")
        report["per_symbol"] = diags

        neff_rows = []
        for h in HORIZONS:
            full = {s: with_horizon(grids[s], prices[s], h) for s in symbols}
            prim = {s: in_session(df, cfg) for s, df in full.items()}

            per_session = {}
            for name, series in (("primary", prim), ("secondary", full)):
                stats = {s: temporal_neff(df) for s, df in series.items()}
                for s, st in stats.items():
                    neff_rows.append({"horizon_d": h, "session": name, "symbol": s, **st})
                per_session[name] = {
                    "n_rows_total": sum(v["n_rows"] for v in stats.values()),
                    "n_eff_sum": sum(v["n_eff"] for v in stats.values()),
                    "n_eff_mean_per_symbol": float(np.mean([v["n_eff"] for v in stats.values()])),
                    "overlap_fraction_mean": float(np.mean([v["overlap_fraction"] for v in stats.values()])),
                }

            cross = cross_sectional(prim, h)
            acf = serial_autocorr(prim, h)
            trades, n_ambiguous = sigma_sample(prim, cfg, h, rng)
            sig = sigma_stats(trades)
            sig["ambiguous_bars"] = n_ambiguous
            sig["ambiguous_share"] = round(n_ambiguous / max(trades.height, 1), 5)
            sig["sigma_rel_se"] = sig["sigma_r_se"] / sig["sigma_r"]
            trades.write_csv(run.dir / f"m02_sigma_sample_h{h}.csv")

            m_bar = per_session["primary"]["n_eff_mean_per_symbol"]
            sigma = sig["sigma_r"]
            models = {
                "pairs_independent": cross["n_eff_pairs_independent"],
                "pairs_signed": cross["n_eff_pairs_signed"],
                "pairs_abs_conservative": cross["n_eff_pairs_abs"],
            }
            pw = {}
            for name, n_pairs in models.items():
                pw[name] = power(sigma, m_bar * n_pairs)
                pw[name]["gate"] = gate_state(pw[name]["mde_r"], sig["sigma_rel_se"])
            report["horizons"][str(h)] = {
                "sessions": per_session,
                "cross_sectional": cross,
                "serial_autocorr_lag1": acf,
                "sigma": sig,
                "power": pw,
            }
            print(f"  h={h}d: σ={sigma:.3f} R, n_eff/para={m_bar:.0f}, "
                  f"par_eff={cross['n_eff_pairs_abs']:.2f}, "
                  f"barów niejednoznacznych {n_ambiguous}")

        pl.DataFrame(neff_rows).write_csv(run.dir / "m02_neff.csv")

        by_model = {}
        for model in ("pairs_independent", "pairs_signed", "pairs_abs_conservative"):
            states = {h: report["horizons"][str(h)]["power"][model]["gate"] for h in HORIZONS}
            by_model[model] = {
                "mde_r": {str(h): report["horizons"][str(h)]["power"][model]["mde_r"]
                          for h in HORIZONS},
                "per_horizon": {str(h): s for h, s in states.items()},
                "verdict": overall_gate(states),
            }
        headline = by_model["pairs_abs_conservative"]
        report["verdict"] = {
            "gate_r": GATE_R,
            "rule": "ADR-009: T001 nie startuje, gdy MDE >= 0,08 R przy OBU horyzontach",
            "headline_model": "pairs_abs_conservative",
            "headline": headline["verdict"],
            "by_pairing_model": by_model,
        }

        (run.dir / "m02_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        run.record(
            mde_r_h3=headline["mde_r"]["3"], mde_r_h10=headline["mde_r"]["10"],
            sigma_r_h3=report["horizons"]["3"]["sigma"]["sigma_r"],
            sigma_r_h10=report["horizons"]["10"]["sigma"]["sigma_r"],
            gate_h3=headline["per_horizon"]["3"], gate_h10=headline["per_horizon"]["10"],
            verdict=headline["verdict"],
        )
        print("\nBramka ADR-009 = %.2f R, konwencja mocy 80%% / α 0,05 dwustronnie" % GATE_R)
        for model, res in by_model.items():
            print(f"  {model:<24} h=3d {res['mde_r']['3']:.4f} ({res['per_horizon']['3']}) · "
                  f"h=10d {res['mde_r']['10']:.4f} ({res['per_horizon']['10']}) "
                  f"→ {res['verdict']}")
        print(f"\nWerdykt (model konserwatywny): {headline['verdict']}")
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
