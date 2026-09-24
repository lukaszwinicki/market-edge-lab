#!/usr/bin/env python3
"""M05 — rozkład zerowy metryki głównej warstwy A (ADR-015). Kontrola, NIE próba.

PYTANIE

Ile obserwacji naprawdę niezależnych ma statystyka relacji `cecha ↔ fwd_atr`
policzona na siatce decyzyjnej T003, i czy kryterium `FALSIFIED` jest przy tym
osiągalne.

ADR-014 ustalił `P_eff = 2,00` dla warstwy B — dla statystyk uśredniających
wynik PRZEMNOŻONY przez znak cechy. Dla statystyki relacji zależność
międzyparowa jest inną wielkością: pod H0 kowariancja estymatorów na parach
`i` i `j` idzie jak iloczyn `ρ^cecha_ij · ρ^zwrot_ij`, a nie jak
`|ρ^zwrot_ij|`. M02 tego nie mierzył. Przeniesienie liczby z warstwy B na A
byłoby odziedziczeniem zamiast pomiaru — czyli dokładnie tym błędem, który
M02 wykrył przy σ i który kosztował T001.

CZEGO TEN SKRYPT NIE ROBI

Nie liczy `mom_k` i nie dotyka ani jednej prawdziwej ceny po stronie CECHY.
Cecha jest **zastępcza**: syntetyczne błądzenie losowe o tej samej
autokorelacji co `mom_k` pod H0, zbudowane z liczb z generatora. Prawdziwe
ceny wchodzą wyłącznie przez `fwd_atr` (target A, bezkierunkowy, ten sam,
którego M02 użył do macierzy korelacji).

Dzięki temu przebieg jest `control`: nie ocenia sygnału H01, więc N bez zmian.

DLACZEGO CECHA ZASTĘPCZA, A NIE WZÓR ANALITYCZNY

Rozrzut statystyki zależy jednocześnie od trzech rzeczy: nakładania okien
wynikowych, autokorelacji cechy i korelacji międzyparowej. Wzór zamknięty
istnieje tylko dla obserwacji niezależnych. Cecha zastępcza o właściwej
autokorelacji, puszczona przez PRAWDZIWĄ siatkę decyzyjną z PRAWDZIWYMI
zwrotami, odtwarza wszystkie trzy naraz i daje SE zmierzone, nie założone.

AUTOKORELACJA CECHY MA ZNACZENIE

`mom_k = (close − close[−k]) / (atr·√k)` to pod H0 znormalizowana suma `k`
przyrostów. Jej autokorelacja na lagu ℓ to (1 − ℓ/k)⁺ — przy k = 480 sąsiednie
bary są skorelowane w 99,8%. Cecha zastępcza z szumu białego zaniżyłaby
rozrzut statystyki o rząd wielkości i dałaby n_eff wzięte z sufitu. Dlatego
surogat jest budowany jako różnica syntetycznego błądzenia, nie jako szum.

CZTERY MODELE KORELACJI MIĘDZYPAROWEJ — NAWIAS, NIE PUNKT

    independent    — cechy par niezależne                        (kraniec górny)
    as_returns_h   — przyrosty cechy o korelacji zwrotów na oknie `h`
    as_returns_k   — przyrosty cechy o korelacji zwrotów na oknie `k`
                     (model fizycznie właściwy: `mom_k` JEST zwrotem
                      z okna `k`, więc jego korelacja międzyparowa jest
                      korelacją zwrotów o tej długości, nie o długości `h`)
    sign_aligned   — ten sam moduł korelacji, wszystkie znaki zgodne

WAŻNE: `sign_aligned` NIE jest krańcem pesymistycznym dla warstwy A —
pomiar pokazał, że implikuje `P_eff` ≈ 7, czyli WIĘCEJ niż sześć par
niezależnych. Powód jest strukturalny: pod H0 kowariancja estymatorów relacji
na parach `i` i `j` idzie jak ILOCZYN `ρ^cecha_ij · ρ^zwrot_ij`. Odwrócenie
znaków samej cechy, przy zwrotach zachowujących znaki oryginalne, czyni część
iloczynów UJEMNYMI — a te kasują wariancję, zamiast ją dokładać. Model jest
zachowany w raporcie jako zapis tego ustalenia, nie jako kandydat na bramkę.

Krańcem pesymistycznym jest zgodność znaków cechy ze znakami zwrotów, czyli
`as_returns_*`. Bramka idzie po gorszym z `as_returns_h` i `as_returns_k`.

DLACZEGO `as_returns_k` NIE ŁAMIE ADR-012

Korelacja międzyparowa zwrotów na oknie `k` jest własnością CEN, nie hipotezy.
Liczona jest na zwrotach W PRZÓD o długości `k` — tą samą maszynerią co target
A, wyłącznie z innym oknem. Pod stacjonarnością jej macierz korelacji jest tą
samą macierzą co dla zwrotów wstecz o tej samej długości, i to czyni ją
poprawnym substytutem dla `ρ^cecha`. Nigdzie nie powstaje iloczyn okna wstecz
z oknem w przód — a dopiero on byłby oceną sygnału H01.
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
from src.validation.overlap import effective_sample_size  # noqa: E402

UTC = dt.timezone.utc

# --- parametry, wszystkie z base.yaml albo z ADR-015 -----------------------

WARMUP_START = dt.datetime(2015, 1, 1, tzinfo=UTC)
FIRST_DECISION = dt.datetime(2016, 1, 1, tzinfo=UTC)
RESEARCH_END = dt.datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC)

HORIZONS = (3, 10)              # h=10d raportowany dla zapisu — ADR-015 go usuwa
LOOKBACKS = (24, 120, 480)      # k z siatki T003
MOM_LOOKBACK_MAX = 480

MODELS = ("independent", "as_returns_h", "as_returns_k", "sign_aligned")
GATE_MODELS = ("as_returns_h", "as_returns_k")   # bramka idzie po gorszym
N_REPS = 400                    # replikacji surogatu na (model, k, h)
SEED = 20260924

# Konwencja mocy — identyczna jak w M02, żeby liczby dało się zestawiać.
Z_CI = 1.959963984540054
Z_POWER = 0.8416212335729143
MDE_FACTOR = Z_CI + Z_POWER

# Progi opłacalności z M04 (E = 0 na krzywej czułości), per horyzont.
BREAKEVEN_ACC = {3: 0.5172, 10: 0.5142}


def load_config() -> dict:
    return yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Siatka i oś czasu wspólna dla par
# --------------------------------------------------------------------------

def decision_grid(symbol: str, cfg: dict):
    h1 = load_h1(symbol, WARMUP_START, RESEARCH_END, cfg)
    return build_grid(
        h1,
        first_decision=FIRST_DECISION,
        lookback_bars=MOM_LOOKBACK_MAX,
        atr_period=cfg["volatility"]["atr_period"],
        min_h1_bars=cfg["data"]["d1_boundary"]["min_h1_bars"],
    )


def hour_index(ts: np.ndarray, origin: dt.datetime) -> np.ndarray:
    """Godziny od `origin` — wspólna oś dla wszystkich par.

    Czynnik wspólny musi być dzielony w tej samej godzinie ZEGAROWEJ, nie
    w tym samym wierszu ramki: pary mają różne siatki i różną liczbę barów.
    """
    o = np.datetime64(origin.replace(tzinfo=None), "h")
    return (ts.astype("datetime64[h]") - o).astype(np.int64)


# --------------------------------------------------------------------------
# Korelacja zwrotów — baza dla modeli surogatu
# --------------------------------------------------------------------------

def return_corr(series: dict[str, pl.DataFrame], h: int, order: list[str],
                cross_hour: int = 9) -> np.ndarray:
    """Macierz korelacji target A na oknach rozłącznych, jak w M02.

    Ta sama konstrukcja co `cross_sectional` w M02: jedna godzina decyzyjna,
    przerzedzenie co `h` dni roboczych, uśrednienie po wszystkich fazach.
    Powtórzona tutaj, bo M05 potrzebuje jej dla własnej siatki i musi być
    odporny na to, że M02 liczył ją na innym zbiorze wierszy.

    Kolejność wierszy i kolumn wymusza `order` — macierz indeksuje te same
    pary co wektor cech surogatu, a kolejność w konfiguracji nie jest
    alfabetyczna.
    """
    aligned = None
    for sym in order:
        df = series[sym]
        col = (
            df.filter(pl.col("ts_decision").dt.hour() == cross_hour)
            .select(pl.col("ts_decision").dt.date().alias("date"),
                    pl.col("fwd_atr").alias(sym))
            .group_by("date").agg(pl.col(sym).first())
        )
        aligned = col if aligned is None else aligned.join(col, on="date", how="inner")
    aligned = aligned.sort("date").drop_nulls()
    mat = aligned.select(order).to_numpy()

    mats = []
    for phase in range(h):
        sub = mat[phase::h]
        if sub.shape[0] > len(order) + 2:
            mats.append(np.corrcoef(sub, rowvar=False))
    return np.mean(mats, axis=0)


def bar_return_corr(grids: dict[str, pl.DataFrame], prices: dict[str, pl.DataFrame],
                    k: int, order: list[str]) -> np.ndarray:
    """Korelacja międzyparowa zwrotów na oknie `k` BARÓW, znormalizowanych ATR.

    Ta sama wielkość co `return_corr`, tylko okno liczone w barach H1, a nie
    w dniach roboczych — bo `mom_k` obejmuje `k` barów. Zwroty są liczone
    W PRZÓD, tą samą maszynerią co target A; pod stacjonarnością macierz
    korelacji zwrotów wstecz o tej samej długości jest ta sama. Żaden iloczyn
    okna wstecz z oknem w przód nie powstaje (ADR-012).
    """
    series = {}
    for sym in order:
        px = prices[sym].sort("px_ts")
        close = px.get_column("exit_price").to_numpy()
        pos = (
            grids[sym].select("bar_ts", "atr_d1_14")
            .join(px.with_row_index("i"), left_on="bar_ts", right_on="px_ts", how="inner")
        )
        i = pos.get_column("i").to_numpy()
        atr = pos.get_column("atr_d1_14").to_numpy()
        ok = i + k < close.size
        series[sym] = pl.DataFrame({
            "bar_ts": pos.get_column("bar_ts").to_numpy()[ok],
            sym: (close[i[ok] + k] - close[i[ok]]) / atr[ok],
        })

    aligned = None
    for sym in order:
        aligned = series[sym] if aligned is None else aligned.join(
            series[sym], on="bar_ts", how="inner")
    aligned = aligned.sort("bar_ts").drop_nulls()
    mat = aligned.select(order).to_numpy()

    mats = []
    for phase in range(k):
        sub = mat[phase::k]
        if sub.shape[0] > len(order) + 2:
            mats.append(np.corrcoef(sub, rowvar=False))
    return np.mean(mats, axis=0)


def model_corr(name: str, rho_h: np.ndarray, rho_k: np.ndarray) -> np.ndarray:
    """Macierz korelacji przyrostów cechy zastępczej dla danego modelu."""
    p = rho_h.shape[0]
    rho = rho_h
    if name == "independent":
        return np.eye(p)
    if name == "as_returns_h":
        return rho_h
    if name == "as_returns_k":
        return rho_k
    if name == "sign_aligned":
        # Znaki pierwszego wektora własnego = strona kwotowania względem USD,
        # odczytana z danych, nie wpisana z ręki. D·R·D jest PSD.
        _, vecs = np.linalg.eigh(rho)
        s = np.sign(vecs[:, -1])
        s[s == 0] = 1.0
        return np.outer(s, s) * rho
    raise ValueError(name)


def psd_chol(c: np.ndarray) -> np.ndarray:
    """Cholesky z podłogą na wartościach własnych — macierze z uśredniania faz
    bywają numerycznie wskaźnikowo ujemne o 1e-16."""
    vals, vecs = np.linalg.eigh(c)
    vals = np.clip(vals, 1e-10, None)
    c = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(c))
    c = c / np.outer(d, d)
    return np.linalg.cholesky(c)


# --------------------------------------------------------------------------
# Statystyki warstwy A i B
# --------------------------------------------------------------------------

def _rank(x: np.ndarray) -> np.ndarray:
    order = x.argsort()
    r = np.empty_like(order, dtype=np.float64)
    r[order] = np.arange(x.size, dtype=np.float64)
    return r


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def statistics(feat: np.ndarray, fwd: np.ndarray, fwd_rank: np.ndarray) -> dict:
    """Trzy statystyki z jednej replikacji.

    `spearman` — metryka główna warstwy A (ADR-015). Rangowa, bo kurtoza
                 `fwd_atr` to 4,6 (h=3d) i 7,8 (h=10d); Pearson na takim
                 ogonie ma rozrzut zależny od kilkunastu obserwacji.
    `pearson`  — ta sama relacja bez rang, raportowana obok.
    `signed`   — warstwa B w miniaturze: średnia `sign(cecha)·fwd_atr`.
                 Jest tu po to, żeby M05 odtworzył `P_eff = 2,00` z ADR-014
                 w modelu `sign_aligned` — sprawdzenie krzyżowe, nie wynik.
    """
    return {
        "spearman": _pearson(_rank(feat), fwd_rank),
        "pearson": _pearson(feat, fwd),
        "signed": float(np.sign(feat).dot(fwd) / fwd.size),
    }


# --------------------------------------------------------------------------
# Przeliczenie SE na wielkości decyzyjne
# --------------------------------------------------------------------------

def acc_from_rho(rho: float) -> float:
    """Trafność kierunku odpowiadająca korelacji, przy normalności dwuwymiarowej.

    P(zgodność znaków) = 1/2 + arcsin(ρ)/π. Mapowanie jest przybliżone dla
    rozkładów z grubym ogonem i służy WYŁĄCZNIE do wyrażenia progów
    w jednostce, o której da się mieć zdanie — nie wchodzi do żadnego testu.
    """
    return 0.5 + np.arcsin(np.clip(rho, -1, 1)) / np.pi


def decision_numbers(se: float, h: int) -> dict:
    """Z SE statystyki: MDE, n_eff, osiągalność kryterium równoważności."""
    mde = MDE_FACTOR * se
    half_ci = Z_CI * se
    be_acc = BREAKEVEN_ACC[h]
    rho_be = float(np.sin((be_acc - 0.5) * np.pi))
    return {
        "se": round(se, 6),
        "n_eff_implied": round(float(1.0 / se ** 2), 1),
        "mde_rho": round(float(mde), 5),
        "mde_acc_pct": round(float(acc_from_rho(mde)) * 100, 2),
        "half_ci95": round(float(half_ci), 5),
        "rho_breakeven": round(rho_be, 5),
        "breakeven_acc_pct": round(be_acc * 100, 2),
        "dead_zone_pp": round((float(acc_from_rho(mde)) - be_acc) * 100, 2),
        # FALSIFIED jako równoważność: CI95 w całości wewnątrz ±rho_breakeven
        "falsified_reachable": bool(half_ci < rho_be),
        "falsified_gap_ratio": round(float(half_ci / rho_be), 4),
        "n_eff_needed_for_falsified": round(float((Z_CI / rho_be) ** 2), 1),
    }


# --------------------------------------------------------------------------
# Przebieg
# --------------------------------------------------------------------------

def run_horizon(series: dict[str, pl.DataFrame], h: int, rng: np.random.Generator,
                rho_k_by_lookback: dict[int, np.ndarray]) -> dict:
    symbols = sorted(series)
    rho = return_corr(series, h, symbols)

    # Wiersze wchodzące do statystyki: wszystkie decyzje sesji primary
    # z określonym targetem. Pooling po parach — tak, jak liczyłby T003.
    fwd_parts, idx_parts, sym_of_row = [], [], []
    for j, sym in enumerate(symbols):
        df = series[sym].filter(pl.col("fwd_atr").is_not_null()
                                & pl.col("fwd_atr").is_not_nan())
        fwd_parts.append(df.get_column("fwd_atr").to_numpy())
        idx_parts.append(hour_index(df.get_column("bar_ts").to_numpy(), WARMUP_START))
        sym_of_row.append(np.full(df.height, j, dtype=np.int64))

    fwd = np.concatenate(fwd_parts)
    bar_idx = np.concatenate(idx_parts)
    row_sym = np.concatenate(sym_of_row)
    fwd_rank = _rank(fwd)

    n_rows = fwd.size
    t_max = int(bar_idx.max()) + 1
    p = len(symbols)

    # n_eff zachłanne z M02, dla zestawienia — liczone na tych samych wierszach.
    neff_greedy = sum(
        effective_sample_size(
            series[s].filter(pl.col("fwd_atr").is_not_null())
                     .select(pl.col("ts_decision").alias("ts"), "t1")
        )
        for s in symbols
    )

    out: dict = {
        "n_rows_pooled": int(n_rows),
        "n_eff_greedy_disjoint_sum": int(neff_greedy),
        "se_iid_if_rows_independent": round(float(1 / np.sqrt(n_rows)), 6),
        "rho_matrix": rho.round(4).tolist(),
        "symbols": symbols,
        "models": {},
    }

    for model in MODELS:
        out["models"][model] = {"lookbacks": {}}
        for k in LOOKBACKS:
            # `as_returns_k` ma inną macierz dla każdego k — reszta modeli
            # tę samą, ale Cholesky liczymy w pętli i tak, bo jest darmowy.
            cm = model_corr(model, rho, rho_k_by_lookback[k])
            chol = psd_chol(cm)
            draws = {"spearman": [], "pearson": [], "signed": []}
            for _ in range(N_REPS):
                # Syntetyczne błądzenie losowe: przyrosty o zadanej korelacji
                # międzyparowej, skumulowane. Cecha = różnica na oknie k,
                # czyli ta sama postać funkcyjna co `mom_k` pod H0.
                inno = rng.standard_normal((t_max + k, p)) @ chol.T
                walk = np.cumsum(inno, axis=0)
                surrogate = (walk[k:] - walk[:-k]) / np.sqrt(k)   # (t_max, p)
                feat = surrogate[bar_idx, row_sym]
                for name, val in statistics(feat, fwd, fwd_rank).items():
                    draws[name].append(val)

            entry = {"corr_matrix": (chol @ chol.T).round(4).tolist()}
            for name, vals in draws.items():
                v = np.asarray(vals)
                se = float(v.std(ddof=1))
                entry[name] = {
                    "mean": round(float(v.mean()), 6),
                    "inflation_vs_iid": round(float(se * np.sqrt(n_rows)), 3),
                    **decision_numbers(se, h),
                }
            out["models"][model]["lookbacks"][str(k)] = entry
            print(f"    {model:<13} k={k:<4} "
                  f"spearman SE={entry['spearman']['se']:.5f} "
                  f"n_eff={entry['spearman']['n_eff_implied']:.0f} "
                  f"prog={entry['spearman']['mde_acc_pct']:.2f}% "
                  f"FALSIFIED={'TAK' if entry['spearman']['falsified_reachable'] else 'NIE'}")
    return out


def main() -> int:
    cfg = load_config()
    symbols = list(cfg["instruments"]["discovery"])
    require_fresh_bars(symbols, WARMUP_START, RESEARCH_END, cfg)

    params = {
        "adr": "ADR-015",
        "purpose": "rozklad zerowy metryki glownej warstwy A",
        "horizons_business_days": list(HORIZONS),
        "lookbacks_k": list(LOOKBACKS),
        "surrogate_models": list(MODELS),
        "n_reps": N_REPS,
        "seed": SEED,
        "symbols": symbols,
        "first_decision": FIRST_DECISION.isoformat(),
        "research_end": RESEARCH_END.isoformat(),
        "power_convention": {"alpha": 0.05, "two_sided": True, "power": 0.80,
                             "mde_factor": MDE_FACTOR},
        "primary_statistic": "spearman",
        "feature_source": "surrogate random walk — mom_k NIE jest liczone",
    }

    with start_run("M05 rozklad zerowy warstwy A — n_eff statystyki relacji (ADR-015)",
                   params, kind="control") as run:
        rng = np.random.default_rng(SEED)
        report: dict = {"params": params, "per_symbol": {}, "horizons": {}}

        grids, prices, diags = {}, {}, {}
        for sym in symbols:
            grids[sym], prices[sym], diags[sym] = decision_grid(sym, cfg)
            print(f"  {sym}: {diags[sym]['decisions_atr_d1_defined']} decyzji")
        report["per_symbol"] = diags

        sorted_syms = sorted(symbols)
        rho_k = {k: bar_return_corr(grids, prices, k, sorted_syms) for k in LOOKBACKS}
        report["rho_k_matrices"] = {
            str(k): {"symbols": sorted_syms, "matrix": m.round(4).tolist(),
                     "mean_abs_offdiag": round(float(np.abs(m[~np.eye(len(m), dtype=bool)]).mean()), 4)}
            for k, m in rho_k.items()
        }
        for k, m in rho_k.items():
            print(f"  korelacja zwrotow na oknie k={k} barow: "
                  f"srednia |rho| = {report['rho_k_matrices'][str(k)]['mean_abs_offdiag']:.4f}")

        for h in HORIZONS:
            print(f"  h={h}d:")
            full = {s: add_horizon(grids[s], prices[s], h, segment_end=RESEARCH_END)
                    for s in symbols}
            prim = {s: session_filter(df, *session_hours(cfg)) for s, df in full.items()}
            report["horizons"][str(h)] = run_horizon(prim, h, rng, rho_k)

        # Bramka: najgorsza komórka siatki T003 w najgorszym modelu bramkowym.
        cells = {}
        for h in HORIZONS:
            for k in LOOKBACKS:
                e = min(
                    (report["horizons"][str(h)]["models"][m]["lookbacks"][str(k)]["spearman"]
                     for m in GATE_MODELS),
                    key=lambda d: d["n_eff_implied"],
                )
                cells[f"h{h}_k{k}"] = e
        t003 = {c: e for c, e in cells.items() if c.startswith("h3_")}
        worst_cell = min(t003, key=lambda c: t003[c]["n_eff_implied"])
        report["verdict"] = {
            "statistic": "spearman (metryka glowna warstwy A)",
            "gate_models": list(GATE_MODELS),
            "rule": "bramka po NAJGORSZEJ komorce siatki T003 (h=3d, k in {24,120,480})",
            "worst_cell": worst_cell,
            "n_eff_worst_cell": t003[worst_cell]["n_eff_implied"],
            "detect_acc_pct_worst_cell": t003[worst_cell]["mde_acc_pct"],
            "dead_zone_pp_worst_cell": t003[worst_cell]["dead_zone_pp"],
            "falsified_reachable_all_cells": all(e["falsified_reachable"] for e in t003.values()),
            "per_cell": {c: {"n_eff": e["n_eff_implied"], "detect_acc_pct": e["mde_acc_pct"],
                             "dead_zone_pp": e["dead_zone_pp"],
                             "falsified_reachable": e["falsified_reachable"]}
                         for c, e in cells.items()},
        }

        (run.dir / "m05_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        run.record(**report["verdict"])

        print("\nSiatka T003 (h=3d, spearman, gorszy z modeli bramkowych):")
        for k in LOOKBACKS:
            e = cells[f"h3_k{k}"]
            print(f"  k={k:<4} n_eff={e['n_eff_implied']:>7.0f}  "
                  f"prog wykrywalnosci {e['mde_acc_pct']:.2f}%  "
                  f"martwa strefa {e['dead_zone_pp']:+.2f} pp  "
                  f"FALSIFIED {'osiagalne' if e['falsified_reachable'] else 'NIEOSIAGALNE'} "
                  f"(polowa CI / prog oplacalnosci = {e['falsified_gap_ratio']:.2f})")
        print("\nh=10d, dla zapisu (ADR-015 usuwa ten horyzont):")
        for k in LOOKBACKS:
            e = cells[f"h10_k{k}"]
            print(f"  k={k:<4} n_eff={e['n_eff_implied']:>7.0f}  "
                  f"prog {e['mde_acc_pct']:.2f}%  "
                  f"FALSIFIED {'osiagalne' if e['falsified_reachable'] else 'NIEOSIAGALNE'}")
        print("\nModele korelacji miedzyparowej, komorka k=480, h=3d:")
        for m in MODELS:
            e = report["horizons"]["3"]["models"][m]["lookbacks"]["480"]["spearman"]
            base = report["horizons"]["3"]["models"]["independent"]["lookbacks"]["480"]["spearman"]
            print(f"  {m:<14} n_eff={e['n_eff_implied']:>7.0f}  "
                  f"P_eff implikowane={6*e['n_eff_implied']/base['n_eff_implied']:.2f}")
        print(f"\nArtefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
