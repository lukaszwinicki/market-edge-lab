#!/usr/bin/env python3
"""T003 — H01 momentum. PRÓBA, nie kontrola. Zapala 3 warianty (N: 7 → 10).

Wykonuje prerejestrację `configs/t003_momentum.yaml` i nic poza nią. Każda
liczba, która tu zapada, była zadeklarowana przed uruchomieniem; skrypt
sprawdza hash prerejestracji na starcie i odmawia startu, jeśli plik się
zmienił.

DWA TRYBY

    --self-test   pipeline na danych SYNTETYCZNYCH z zasianym efektem.
                  Nie dotyka segmentu RESEARCH, nie loguje próby, nie zapala
                  licznika. Służy do sprawdzenia, że maszyneria odzyskuje
                  efekt, który sama wsadziła.
    (bez flagi)   pełny przebieg na danych. Loguje `kind="strategy"`,
                  `n_variants=3`. **Nieodwracalne.**

DLACZEGO NIE MA TRYBU „PRÓBNEGO NA PRAWDZIWYCH DANYCH"

Rejestr prób liczy wpisy `start`, a nie „przebiegi, które się podobały".
Uruchomienie, które policzyło statystykę warstwy A na segmencie RESEARCH
i zostało przerwane, JEST próbą — zobaczyło wynik. Tryb próbny na prawdziwych
danych byłby więc trzema próbami udającymi zero i dokładnie tym rodzajem
niezalogowanego spojrzenia, przed którym broni się cały projekt.

KOLEJNOŚĆ, KTÓRA MA ZNACZENIE

Ramię kontrolne (cecha postarzona) liczy się w TYM SAMYM przebiegu co wynik
główny. Osobny przebieg spaliłby próbę za diagnostykę (ADR-012), a policzenie
go po obejrzeniu wyniku głównego uczyniłoby z jego kryterium parametr swobodny.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.execution.costs import margins_from_config  # noqa: E402
from src.features.momentum import attach_to_decisions  # noqa: E402
from src.features.volatility import atr_d1, atr_h1, vol_pct  # noqa: E402
from src.harness.market import load_h1, require_fresh_bars  # noqa: E402
from src.harness.registry import start_run  # noqa: E402
from src.research.grid import (  # noqa: E402
    decision_grid as build_grid, in_session as session_filter, session_hours,
    with_horizon as add_horizon,
)
from src.research.labels import layer_a, with_axes  # noqa: E402
from src.validation.bootstrap import block_bootstrap_statistic  # noqa: E402

UTC = dt.timezone.utc
PREREG = ROOT / "configs" / "t003_momentum.yaml"
PREREG_SHA256 = "c832dcdcbbc3f3e467bc18b9c4993c1f07bcb7a3b7a2b7d13aac481959db99b2"

Z_CI = 1.959963984540054


# --------------------------------------------------------------------------
# Statystyki warstwy A
# --------------------------------------------------------------------------

def rank(a: np.ndarray) -> np.ndarray:
    order = a.argsort()
    r = np.empty_like(order, dtype=np.float64)
    r[order] = np.arange(a.size, dtype=np.float64)
    return r


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    den = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / den) if den > 0 else float("nan")


def spearman_fn(feat: np.ndarray, target: np.ndarray):
    """Domknięcie liczące metrykę główną na podzbiorze wierszy."""
    def stat(idx: np.ndarray) -> float:
        return pearson(rank(feat[idx]), rank(target[idx]))
    return stat


def acc_pct(rho: float) -> float:
    """Korelacja → trafność kierunku. Jednostka do czytania, nie do testu."""
    return float(50 + 100 * np.arcsin(np.clip(rho, -1, 1)) / np.pi)


# --------------------------------------------------------------------------
# Osie raportowania (prereg: reporting.axes)
# --------------------------------------------------------------------------

def by_axis(obs: pl.DataFrame, feature_col: str, axis: str,
            min_n: int = 200) -> dict:
    """Metryka główna w rozbiciu na oś. Bez CI — to jest opis, nie test.

    Grupy mniejsze niż `min_n` raportujemy z liczebnością i bez statystyki:
    Spearman na stu obserwacjach nakładających się okien jest szumem, a
    wpisany do tabeli wygląda jak wynik.
    """
    out = {}
    for key, grp in obs.group_by(axis, maintain_order=True):
        name = str(key[0] if isinstance(key, tuple) else key)
        f = grp.get_column(feature_col).to_numpy()
        t = grp.get_column("fwd_atr").to_numpy()
        out[name] = {
            "n": int(grp.height),
            "spearman": pearson(rank(f), rank(t)) if grp.height >= min_n else None,
        }
    return dict(sorted(out.items()))


def realized_pair_dependence(obs: pl.DataFrame, feature_col: str) -> dict:
    """ZREALIZOWANE `E[sign_i·sign_j·ρ_ij]` i wynikające z niego `P_eff`.

    Diagnostyka zadeklarowana w prerejestracji. **Nie może zmienić werdyktu** —
    informuje następny eksperyment, nie ten. Liczona na znaku cechy, czyli na
    wielkości, której M02 z założenia nie mógł zobaczyć (ADR-012).
    """
    wide = None
    for key, grp in obs.group_by("symbol", maintain_order=True):
        sym = str(key[0] if isinstance(key, tuple) else key)
        col = (grp.select(pl.col("ts_decision").dt.date().alias("d"),
                          (pl.col("fwd_atr") * pl.col(feature_col).sign()).alias(sym))
               .group_by("d").agg(pl.col(sym).mean()))
        wide = col if wide is None else wide.join(col, on="d", how="inner")
    wide = wide.sort("d").drop_nulls()
    syms = [c for c in wide.columns if c != "d"]
    if wide.height < len(syms) + 3:
        return {"note": "za mało wspólnych dni", "n_days": int(wide.height)}
    rho = np.corrcoef(wide.select(syms).to_numpy(), rowvar=False)
    p = len(syms)
    off = ~np.eye(p, dtype=bool)
    return {
        "symbols": syms,
        "n_days": int(wide.height),
        "matrix": rho.round(4).tolist(),
        "mean_offdiag": float(rho[off].mean()),
        "p_eff_realized": float(p ** 2 / rho.sum()),
        "p_eff_adr014_assumed": 2.00,
        "binding": False,
        "note": "diagnostyka — nie zmienia werdyktu (ADR-014)",
    }


# --------------------------------------------------------------------------
# Kryteria z prerejestracji
# --------------------------------------------------------------------------

def holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Korekta Holma. Union po komórkach wymaga korekty; intersection nie."""
    order = sorted(pvals, key=lambda k: pvals[k])
    m = len(order)
    out, still = {}, True
    for i, key in enumerate(order):
        thr = alpha / (m - i)
        still = still and pvals[key] <= thr
        out[key] = still
    return out


def verdict(cells: dict, rho_breakeven: float, control_ok: bool) -> dict:
    """SUPPORTED / FALSIFIED / NOT_SUPPORTED wg prerejestracji, bez wyjątków."""
    pvals = {k: v["p_value"] for k, v in cells.items()}
    holm_pass = holm(pvals)

    supported = control_ok and any(
        holm_pass[k] and cells[k]["ci_low"] > 0 for k in cells)
    falsified = all(
        cells[k]["ci_low"] > -rho_breakeven and cells[k]["ci_high"] < rho_breakeven
        for k in cells)

    if supported:
        status = "SUPPORTED"
    elif falsified:
        status = "FALSIFIED"
    else:
        status = "NOT_SUPPORTED"

    upper = max(v["ci_high"] for v in cells.values())
    return {
        "status": status,
        "holm_pass": holm_pass,
        "supported_rule_met": bool(supported),
        "falsified_rule_met": bool(falsified),
        "random_control_beaten": bool(control_ok),
        "upper_bound_rho": float(upper),
        "upper_bound_acc_pct": float(50 + 100 * np.arcsin(np.clip(upper, -1, 1)) / np.pi),
    }


# --------------------------------------------------------------------------
# Przebieg jednej komórki
# --------------------------------------------------------------------------

def run_cell(obs: pl.DataFrame, feature_col: str, cfg: dict, *,
             n_perm: int, perm_seed: int, aged_col: str | None) -> dict:
    """Metryka główna, CI, kontrola permutacyjna i ramię postarzone."""
    b = cfg["validation"]["bootstrap"]
    feat = obs.get_column(feature_col).to_numpy()
    targ = obs.get_column("fwd_atr").to_numpy()
    stat = spearman_fn(feat, targ)
    all_rows = np.arange(obs.height)

    boot = block_bootstrap_statistic(
        obs.get_column("ts_decision").rename("ts"), stat,
        block_days=b["block_days"], n_reps=b["reps"], seed=0)

    # Kontrola permutacyjna: zachowuje wszystko poza przyporządkowaniem
    # cechy do momentu. Permutacja w obrębie pary, jak deklaruje prereg.
    rng = np.random.default_rng(perm_seed)
    sym = obs.get_column("symbol").to_numpy()
    groups = [np.flatnonzero(sym == s) for s in np.unique(sym)]
    null = np.empty(n_perm)
    for i in range(n_perm):
        shuffled = feat.copy()
        for g in groups:
            shuffled[g] = feat[rng.permutation(g)]
        null[i] = pearson(rank(shuffled), rank(targ))
    point = boot.expectancy
    p_value = float((np.abs(null) >= abs(point)).mean())

    out = {
        "n_obs": int(obs.height),
        "spearman": point,
        "pearson": pearson(feat, targ),
        "se": boot.se,
        "ci_low": boot.ci_low,
        "ci_high": boot.ci_high,
        "n_days": boot.n_days,
        "permutation": {
            "n_reps": n_perm, "seed": perm_seed,
            "null_sd": float(null.std(ddof=1)),
            "p_value": p_value,
        },
        "p_value": p_value,
    }

    if aged_col is not None:
        aged = obs.get_column(aged_col).to_numpy()
        ok = ~np.isnan(aged)
        aged_stat = pearson(rank(aged[ok]), rank(targ[ok]))
        # SE różnicy na TYCH SAMYCH blokach — para, nie dwa niezależne przebiegi.
        diff_fn = lambda idx: (pearson(rank(aged[idx]), rank(targ[idx]))  # noqa: E731
                               - pearson(rank(feat[idx]), rank(targ[idx])))
        diff_boot = block_bootstrap_statistic(
            obs.filter(pl.Series(ok)).get_column("ts_decision").rename("ts"),
            lambda idx: diff_fn(np.flatnonzero(ok)[idx]),
            block_days=b["block_days"], n_reps=max(1000, b["reps"] // 10), seed=0)
        out["aged_control"] = {
            "spearman_aged": aged_stat,
            "diff_aged_minus_true": diff_boot.expectancy,
            "se_diff": diff_boot.se,
            "in_se": diff_boot.expectancy / diff_boot.se if diff_boot.se else None,
            # Kryterium ustalone PRZED uruchomieniem: cecha postarzona nie
            # może być LEPSZA. Wzrost -> STOP i audyt wyrównania.
            "passes": bool(diff_boot.expectancy < 2 * diff_boot.se),
        }
    return out


# --------------------------------------------------------------------------
# Warstwa B — wycena, bramkowana sygnałem z warstwy A (ADR-003, ADR-015)
# --------------------------------------------------------------------------

def run_layer_b(obs: pl.DataFrame, feature_col: str, cfg: dict, pre: dict,
                margins: tuple[float, ...], symbols: list[str],
                ) -> tuple[dict, pl.DataFrame]:
    """Expectancy w net R po PEŁNYM koszcie, per marża, z CI.

    Uruchamiana wyłącznie tam, gdzie warstwa A pokazała sygnał. ADR-003:
    „jeśli warstwa A jest zerowa przy wysokiej mocy, warstwa B nie może być
    dodatnia i zatrzymujemy się tanio, nie spalając prób".
    """
    from src.execution.costs import net_column, reportable
    from src.harness.market import cost_model_for, load_m1
    from src.research.labels import layer_b
    from src.validation.bootstrap import block_bootstrap_expectancy

    b = pre["layer_b"]["barriers"]
    warmup = dt.datetime.fromisoformat(pre["sample"]["warmup_from"]).replace(tzinfo=UTC)
    end = dt.datetime.fromisoformat(
        pre["sample"]["last_decision_segment_end"]).replace(
        hour=23, minute=59, second=59, tzinfo=UTC)

    parts = []
    for sym in symbols:
        mine = obs.filter(pl.col("symbol") == sym)
        if mine.is_empty():
            continue
        m1 = load_m1(sym, warmup, end, cfg)
        parts.append(layer_b(
            mine, m1, cost_model_for(sym, cfg), feature_col=feature_col,
            sl_mult=float(b["sl_x_atr_d1_14"]), tp_mult=float(b["tp_x_atr_d1_14"]),
            margins=margins))
        del m1
    played = pl.concat(parts, how="diagonal")
    reportable(played, margins)

    bs = cfg["validation"]["bootstrap"]
    out = {
        "n_in": int(obs.height),
        "n_played": int(played.height),
        "dropped": int(obs.height - played.height),
        "exit_reasons": {r["reason"]: round(r["len"] / played.height, 4)
                         for r in played.group_by("reason").len().iter_rows(named=True)},
        "per_margin": {},
    }
    ts_col = played.select(pl.col("ts_decision").alias("ts"))
    for m in margins:
        boot = block_bootstrap_expectancy(
            played.with_columns(ts_col["ts"]), block_days=bs["block_days"],
            n_reps=bs["reps"], seed=0, value=net_column(m))
        out["per_margin"][str(m)] = {
            "expectancy_net_r": boot.expectancy, "se": boot.se,
            "ci_low": boot.ci_low, "ci_high": boot.ci_high,
            "beats_zero": bool(boot.ci_low > 0),
        }

    # Deflacja o liczbę prób (ADR-004, ADR-017). DIAGNOSTYKA — nie zmienia
    # werdyktu, bo kryteria T003 zamrożono przed tym modułem. Może wyłącznie
    # osłabić odczyt wyniku pozytywnego, nigdy go wzmocnić.
    from src.validation.deflation import as_report, deflate, live_trial_count
    n_eff = int(pre["layer_a"]["power"]["n_eff_measured"][feature_col.split("_")[1]])
    try:
        out["deflation"] = as_report(deflate(
            played.get_column(net_column(margins[1])).to_numpy(),
            live_trial_count(ROOT / "trials" / "trials.jsonl"),
            n_obs=n_eff))
    except ValueError as e:
        out["deflation"] = {"binding": False, "error": str(e)}
    return out, played


def a_minus_b(cell_a: dict, res_b: dict, margin: float) -> dict:
    """Ile kosztują bariery i koszty — różnica A vs B (prereg, ADR-014).

    Warstwa A mierzy informację w jednostce korelacji, B wynik w R; nie da
    się ich odjąć wprost. Porównujemy więc PRZEZ TRAFNOŚĆ KIERUNKU: ile
    procent trafności implikuje zmierzona relacja, i ile trafności trzeba,
    żeby warstwa B wyszła na zero.
    """
    implied = acc_pct(cell_a["spearman"])
    return {
        "layer_a_implied_acc_pct": implied,
        "breakeven_acc_pct": 51.72,
        "margin_reported": margin,
        "surplus_pp": implied - 51.72,
        "note": ("Dodatni nadmiar znaczy, że informacja przeżywa pełny koszt; "
                 "ujemny — że istnieje, ale nie pokrywa barier i kosztów."),
    }


# --------------------------------------------------------------------------
# Dane
# --------------------------------------------------------------------------

def build_observations(cfg: dict, pre: dict, symbols: list[str], h: int,
                       lookbacks: tuple[int, ...]) -> dict[str, pl.DataFrame]:
    """Siatka + cecha + osie, per para. Target A liczy siatka (grid.py)."""
    warmup = dt.datetime.fromisoformat(pre["sample"]["warmup_from"]).replace(tzinfo=UTC)
    first = dt.datetime.fromisoformat(pre["sample"]["first_decision"]).replace(tzinfo=UTC)
    end = dt.datetime.fromisoformat(
        pre["sample"]["last_decision_segment_end"]).replace(
        hour=23, minute=59, second=59, tzinfo=UTC)

    out = {}
    for sym in symbols:
        h1 = load_h1(sym, warmup, end, cfg)
        dec, prices, _ = build_grid(
            h1, first_decision=first, lookback_bars=max(lookbacks),
            atr_period=cfg["volatility"]["atr_period"],
            min_h1_bars=cfg["data"]["d1_boundary"]["min_h1_bars"])
        # `segment_end` odcina okna wychodzące poza segment — warunek 4.
        dec = add_horizon(dec, prices, h, segment_end=end)

        h1a = atr_h1(h1, cfg["volatility"]["atr_period"])
        dec = attach_to_decisions(dec, h1a, lookbacks)
        # Ramię postarzone: cecha bara o jeden WCZEŚNIEJSZEGO niż dopuszcza siatka.
        prev = h1a.select(pl.col("ts").shift(-1).alias("bar_ts"), pl.col("ts").alias("prev_ts"))
        dec = dec.join(prev, on="bar_ts", how="left")
        aged = attach_to_decisions(
            dec.select(pl.col("prev_ts").alias("bar_ts")), h1a, lookbacks
        ).select([pl.col(f"mom_{k}").alias(f"aged_mom_{k}") for k in lookbacks])
        dec = pl.concat([dec, aged], how="horizontal")

        d1 = vol_pct(atr_d1(h1, cfg["data"]["d1_boundary"]["min_h1_bars"],
                            cfg["volatility"]["atr_period"]),
                     cfg["volatility"]["vol_pct_min_days"])
        out[sym] = with_axes(dec, d1, sym)
    return out


def pooled(series: dict[str, pl.DataFrame], feature_col: str,
           aged_col: str) -> pl.DataFrame:
    keep = ["ts_decision", "symbol", "year", "hour", "vol_regime", "vol_pct_252",
            "fwd_atr", feature_col, aged_col, "ref_price", "atr_d1_14", "t1"]
    return pl.concat([layer_a(df, feature_col).select(keep) for df in series.values()])


# --------------------------------------------------------------------------
# Samosprawdzenie na danych syntetycznych
# --------------------------------------------------------------------------

def write_markdown(path: Path, report: dict, pre: dict) -> None:
    """`t003.md` — raport, który da się przeczytać bez odpalania niczego."""
    v = report["verdict"]
    L = [
        "# T003 — H01 momentum, warstwa A",
        "",
        f"**Data:** {dt.datetime.now(UTC).date()} · **Rodzaj:** `strategy` — "
        f"**liczy się do N** ({pre['meta']['counter_before']} → "
        f"{pre['meta']['counter_after']})",
        f"**Prerejestracja:** `configs/t003_momentum.yaml` · "
        f"`sha256 = {PREREG_SHA256[:16]}…`",
        "",
        "---", "",
        "## Werdykt", "",
        f"> **H01 → `{v['status']}`**", ">",
        f"> Górne ograniczenie na efekt: **{v['upper_bound_acc_pct']:.2f}%** "
        f"trafności kierunku (próg opłacalności 51,72%).",
        "",
        "Kryteria były ustalone przed uruchomieniem i nie zostały ruszone.",
        "", "## Komórki siatki", "",
        "| k | n | Spearman | CI95 | p (permutacja) | Holm |",
        "|---|---|---|---|---|---|",
    ]
    for name, c in report["cells"].items():
        L.append(
            f"| {name} | {c['n_obs']} | {c['spearman']:+.4f} | "
            f"[{c['ci_low']:+.4f}, {c['ci_high']:+.4f}] | {c['p_value']:.4f} | "
            f"{'przechodzi' if v['holm_pass'].get(name) else 'nie'} |")

    L += ["", "## Ramię kontrolne — cecha postarzona o jeden bar", "",
          "Kryterium ustalone przed uruchomieniem: cecha postarzona **nie może "
          "być lepsza**. Wzrost = kanoniczny objaw błędu off-by-one.", "",
          "| k | Spearman postarzony | Różnica | w SE | Wynik |",
          "|---|---|---|---|---|"]
    for name, c in report["cells"].items():
        a = c.get("aged_control")
        if a:
            L.append(f"| {name} | {a['spearman_aged']:+.4f} | "
                     f"{a['diff_aged_minus_true']:+.4f} | {a['in_se']:+.2f} | "
                     f"{'PRZECHODZI' if a['passes'] else 'STOP'} |")

    L += ["", "## Sprawdzenie krzyżowe z M05", "",
          "SE z block bootstrapu wobec SE zmierzonego surogatem. Rozjazd "
          "powyżej 25% zatrzymuje przebieg bez raportowania wyniku.", "",
          "| k | SE tutaj | SE z M05 | iloraz |", "|---|---|---|---|"]
    for name, c in report["cells"].items():
        m = c["m05_consistency"]
        L.append(f"| {name} | {c['se']:.5f} | {m['m05_se']:.5f} | {m['ratio']:.3f} |")

    if report.get("layer_b"):
        L += ["", "## Warstwa B — wycena ekonomiczna", "",
              "Nie jest instrumentem falsyfikacji (ADR-015). Pełny koszt "
              "zawiera człon finansowania (ADR-016).", ""]
        for name, lb in report["layer_b"].items():
            if "skipped" in lb:
                L.append(f"* **{name}** — pominięta: {lb['skipped']}")
                continue
            L.append(f"* **{name}** — {lb['n_played']} transakcji")
            for m, e in lb["per_margin"].items():
                L.append(f"  * marża {m}: expectancy **{e['expectancy_net_r']:+.4f} R** "
                         f"CI [{e['ci_low']:+.4f}, {e['ci_high']:+.4f}]")
            d = lb.get("deflation") or {}
            if "dsr_bracket" in d:
                L.append(f"  * deflacja o **N = {d['n_trials']}** prób: DSR "
                         f"{d['dsr_bracket'][1]:.3f}–{d['dsr_bracket'][0]:.3f} "
                         f"(nawias `V[SR]`), przeżywa oba końce: "
                         f"{'tak' if d['survives_both_ends'] else 'NIE'}. "
                         f"Diagnostyka — nie zmienia werdyktu (ADR-017).")
    else:
        L += ["", "## Warstwa B — nieuruchomiona", "",
              "Warstwa A nie pokazała sygnału w żadnej komórce, więc pełny "
              "przebieg B nie został uruchomiony (ADR-003: zatrzymujemy się "
              "tanio, nie spalając prób). Zero przyrządu przy pełnym koszcie "
              "to −0,0422 R (M06)."]

    pd = report.get("pair_dependence") or {}
    rows = [(n, d) for n, d in pd.items() if "p_eff_realized" in d]
    if rows:
        L += ["", "## Zrealizowana zależność par — diagnostyka", "",
              "**Nie zmienia werdyktu** — informuje następny eksperyment "
              "(ADR-014). Założone w ADR-014: `P_eff = 2,00`.", "",
              "| k | P_eff zrealizowane | średnia poza przekątną | dni |",
              "|---|---|---|---|"]
        for n, d in rows:
            L.append(f"| {n} | {d['p_eff_realized']:.2f} | "
                     f"{d['mean_offdiag']:+.3f} | {d['n_days']} |")

    lk = report.get("leakage_checklist")
    if lk:
        L += ["", "## Checklista leakage'u (`DATA.md` §8)", "",
              f"**{'PRZECHODZI' if lk['passes'] else 'NIE PRZECHODZI'}** — "
              f"{lk['n_checks']} pozycji, {lk['n_failed']} niespełnionych. "
              "Pozycja niesprawdzalna kodem bez jawnej deklaracji liczy się "
              "jako niepowodzenie.", "",
              "| Pozycja | Stan |", "|---|---|"]
        for c in lk["checks"]:
            L.append(f"| {c['item']} | `{c['status']}` |")

    L += ["", "## Czego ten przebieg nie zrobił", "",
          "* Nie dotknął segmentu OOS ani zapieczętowanego.",
          "* Nie wybrał najlepszej komórki — wszystkie trzy są raportowane.",
          "* Nie zmienił żadnego kryterium po zobaczeniu wyniku.", ""]
    path.write_text("\n".join(L), encoding="utf-8")


def self_test() -> int:
    """Czy maszyneria odzyskuje efekt, który sama wsadziła — i tylko wtedy.

    Na prawdziwych danych poprawna odpowiedź nie jest znana, więc przebieg,
    który coś zwraca, nie jest dowodem, że zwraca to, co trzeba. Tu jest.
    """
    rng = np.random.default_rng(0)
    n_days, per_day, k = 400, 8, 24
    n = n_days * per_day
    ts, d = [], dt.datetime(2019, 1, 7, 8, tzinfo=UTC)
    while len(ts) < n:
        if d.weekday() < 5:
            ts += [d + dt.timedelta(hours=j) for j in range(per_day)]
        d += dt.timedelta(days=1)
    ts = ts[:n]

    print("  zero: cecha bez związku z targetem")
    feat = rng.standard_normal(n)
    targ = rng.standard_normal(n)
    obs = pl.DataFrame({"ts_decision": ts, "symbol": ["SYN"] * n,
                        "fwd_atr": targ, "feat": feat, "aged": np.full(n, np.nan)})
    cfg = {"validation": {"bootstrap": {"block_days": 20, "reps": 300}}}
    r0 = run_cell(obs, "feat", cfg, n_perm=200, perm_seed=1, aged_col=None)
    print(f"    spearman={r0['spearman']:+.4f}  CI=[{r0['ci_low']:+.4f},"
          f"{r0['ci_high']:+.4f}]  p={r0['p_value']:.3f}")
    assert r0["ci_low"] < 0 < r0["ci_high"], "zero poza CI — przyrząd kłamie"
    assert r0["p_value"] > 0.05, "kontrola permutacyjna odrzuca prawdziwe zero"

    print("  wzmocnienie: efekt wsadzony celowo")
    targ2 = 0.25 * feat + np.sqrt(1 - 0.25 ** 2) * rng.standard_normal(n)
    obs2 = obs.with_columns(pl.Series("fwd_atr", targ2))
    r1 = run_cell(obs2, "feat", cfg, n_perm=200, perm_seed=1, aged_col=None)
    print(f"    spearman={r1['spearman']:+.4f}  CI=[{r1['ci_low']:+.4f},"
          f"{r1['ci_high']:+.4f}]  p={r1['p_value']:.3f}")
    assert r1["ci_low"] > 0, "wsadzony efekt nie został odzyskany"
    assert r1["p_value"] < 0.05, "kontrola permutacyjna nie widzi efektu"

    print("  werdykt na zerze i na efekcie")
    rho_be = float(np.sin((0.5172 - 0.5) * np.pi))
    v0 = verdict({"k24": r0}, rho_be, control_ok=r0["p_value"] < 0.05)
    v1 = verdict({"k24": r1}, rho_be, control_ok=r1["p_value"] < 0.05)
    print(f"    zero -> {v0['status']}   efekt -> {v1['status']}")
    assert v1["status"] == "SUPPORTED", v1
    assert v0["status"] in ("FALSIFIED", "NOT_SUPPORTED"), v0
    assert k  # k jest tu tylko dokumentacyjnie

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
            "Zmiana po zamrożeniu to NOWY eksperyment z nowym ID, nie T003.")
    return yaml.safe_load(raw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true",
                    help="pipeline na danych syntetycznych; nie zapala prób")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    pre = check_prereg()
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    symbols = list(pre["sample"]["universe"])
    lookbacks = tuple(pre["feature"]["lookbacks_k_bars"])
    h = int(pre["grid"]["horizons_business_days"][0])
    rho_be = float(pre["falsification"]["breakeven"]["rho_equivalent"])
    m05_se = {k: float(v) for k, v in
              pre["layer_a"]["ci"]["consistency_check_vs_m05"]["m05_se_spearman"].items()}
    margins = margins_from_config(cfg)

    warmup = dt.datetime.fromisoformat(pre["sample"]["warmup_from"]).replace(tzinfo=UTC)
    end = dt.datetime.fromisoformat(
        pre["sample"]["last_decision_segment_end"]).replace(
        hour=23, minute=59, second=59, tzinfo=UTC)
    require_fresh_bars(symbols, warmup, end, cfg)

    params = {
        "prereg": "configs/t003_momentum.yaml",
        "prereg_sha256": PREREG_SHA256,
        "hypothesis": "H01",
        "cells": [f"k{k}_h{h}" for k in lookbacks],
        "symbols": symbols,
        "margins": list(margins),
        "primary_statistic": "spearman(mom_k, fwd_atr)",
    }

    with start_run("T003 H01 momentum — warstwa A, 3 komorki",
                   params, kind="strategy", n_variants=len(lookbacks)) as run:
        series = build_observations(cfg, pre, symbols, h, lookbacks)
        start_h, end_h = session_hours(cfg)

        report: dict = {"params": params, "cells": {}}
        cells = {}
        for k in lookbacks:
            obs = pooled({s: session_filter(df, start_h, end_h)
                          for s, df in series.items()},
                         f"mom_{k}", f"aged_mom_{k}")
            res = run_cell(obs, f"mom_{k}", cfg,
                           n_perm=int(pre["random_control"]["reps"]),
                           perm_seed=int(pre["random_control"]["seed"]),
                           aged_col=f"aged_mom_{k}")

            # Sprawdzenie krzyżowe z M05, zadeklarowane przed uruchomieniem.
            ratio = res["se"] / m05_se[str(k)]
            res["m05_consistency"] = {"m05_se": m05_se[str(k)], "ratio": ratio,
                                      "passes": bool(0.75 <= ratio <= 1.25)}
            if not res["m05_consistency"]["passes"]:
                raise SystemExit(
                    f"STOP: SE komorki k={k} rozjezdza sie z M05 o {abs(1-ratio):.0%} "
                    "(prog 25%). Jedno z dwoch zle mierzy — prerejestracja "
                    "nakazuje zatrzymanie, nie interpretacje.")
            if not res["aged_control"]["passes"]:
                raise SystemExit(
                    f"STOP: cecha postarzona jest LEPSZA w komorce k={k} "
                    f"({res['aged_control']['in_se']:+.2f} SE). Kanoniczny objaw "
                    "bledu off-by-one — audyt wyrownania przed raportowaniem.")

            cells[f"k{k}"] = res
            report["cells"][f"k{k}"] = res
            print(f"  k={k:<4} rho={res['spearman']:+.4f} "
                  f"CI=[{res['ci_low']:+.4f},{res['ci_high']:+.4f}] "
                  f"p={res['p_value']:.4f} n={res['n_obs']}")

        control_ok = any(v["p_value"] < 0.05 for v in cells.values())
        report["verdict"] = verdict(cells, rho_be, control_ok)

        # Sesja secondary — prerejestracja wymaga OBU. Raportowana jako
        # pytanie o realizm wykonania, nie o moc (M02: zero nowych obserwacji
        # niezależnych), więc bez CI i bez wpływu na werdykt.
        report["session_secondary"] = {
            f"k{k}": {
                "n": int(o.height),
                "spearman": pearson(rank(o.get_column(f"mom_{k}").to_numpy()),
                                    rank(o.get_column("fwd_atr").to_numpy())),
            }
            for k in lookbacks
            for o in [pooled(series, f"mom_{k}", f"aged_mom_{k}")]
        }
        report["session_secondary"]["note"] = (
            "bez CI i bez wpływu na werdykt — M02 zmierzył, że druga sesja "
            "dokłada +72% wierszy i zero obserwacji niezależnych")

        # Osie raportowania — dla KAŻDEJ komórki (prereg: all_cells_reported).
        # Wybranie jednej komórki po najwyższej statystyce byłoby doborem
        # po zobaczeniu wyniku, nawet gdyby służył tylko opisowi.
        report["axes"], report["pair_dependence"] = {}, {}
        for k in lookbacks:
            fc = f"mom_{k}"
            o = pooled({s: session_filter(df, start_h, end_h)
                        for s, df in series.items()}, fc, f"aged_mom_{k}")
            report["axes"][f"k{k}"] = {
                "instrument": by_axis(o, fc, "symbol"),
                "year": by_axis(o, fc, "year"),
                "vol_regime": by_axis(o, fc, "vol_regime"),
                "direction": by_axis(
                    o.with_columns(pl.when(pl.col(fc) >= 0).then(pl.lit("long"))
                                   .otherwise(pl.lit("short")).alias("direction")),
                    fc, "direction"),
            }
            report["pair_dependence"][f"k{k}"] = realized_pair_dependence(o, fc)

        # Warstwa B — wyłącznie tam, gdzie A pokazała sygnał (ADR-003).
        report["layer_b"] = {}
        signalled = [c for c in cells
                     if report["verdict"]["holm_pass"].get(c) and cells[c]["ci_low"] > 0]
        if not signalled:
            report["layer_b"] = None
            print("  warstwa B: POMINIĘTA — warstwa A bez sygnału (ADR-003)")
        else:
            for c in signalled:
                k = c[1:]
                obs = pooled({s: session_filter(df, start_h, end_h)
                              for s, df in series.items()},
                             f"mom_{k}", f"aged_mom_{k}")
                res_b, played = run_layer_b(obs, f"mom_{k}", cfg, pre, margins, symbols)
                res_b["a_minus_b"] = a_minus_b(cells[c], res_b, margins[1])
                report["layer_b"][c] = res_b
                played.write_parquet(run.dir / f"observations_{c}.parquet")
                print(f"  warstwa B {c}: {res_b['n_played']} transakcji")

        # CHECKLISTA LEAKAGE'U (DATA.md §8) — przed zapisaniem czegokolwiek.
        # CLAUDE.md: przed KAŻDYM raportowanym wynikiem. Pozycje, których nie
        # da się sprawdzić z artefaktów, są zadeklarowane tutaj imiennie —
        # milczenie jest w tym module traktowane jak niepowodzenie.
        from src.validation.leakage import run_checklist
        worst = min(cells, key=lambda c: cells[c]["n_obs"])
        obs_check = pooled({s: session_filter(df, start_h, end_h)
                            for s, df in series.items()},
                           f"mom_{worst[1:]}", f"aged_mom_{worst[1:]}")
        checklist = run_checklist(
            cfg, json.loads((run.dir / "run.json").read_text(encoding="utf-8")),
            ROOT / "trials" / "trials.jsonl",
            observations=obs_check,
            segment=(dt.datetime.fromisoformat(
                pre["sample"]["first_decision"]).replace(tzinfo=UTC), end),
            n_rows=cells[worst]["n_obs"],
            n_eff=int(pre["layer_a"]["power"]["n_eff_measured"][worst[1:]]),
            cells=cells,
            declarations={
                "expanding_windows":
                    "vol_pct_252 w oknie rozszerzającym; atr Wildera przyczynowy — "
                    "test_labels.py::test_expanding_percentile_never_looks_forward",
                "no_fit_on_test":
                    "NIE DOTYCZY — T003 nie dopasowuje modelu, brak fit() w całej "
                    "ścieżce (prereg: layer_a, statystyka opisowa relacji)",
                "daily_from_closed_day":
                    "atr_d1_14 i vol_pct_252 łączone przez available_from = doba+1, "
                    "join_asof zamiast arytmetyki — test_volatility.py, test_labels.py",
                "simulator_blind":
                    "simulate_trade tnie okno samodzielnie; trzy testy na brak "
                    "podglądania w test_simulator.py (dług M01 spłacony w M03)",
                "macro_alfred":
                    "NIE DOTYCZY — T003 nie używa danych makro (prereg: feature = mom_k)",
                "purge_embargo":
                    "NIE DOTYCZY jako podział — T003 nie dzieli próby ani nie "
                    "dopasowuje modelu. Nakładanie wchodzi do WNIOSKOWANIA: block "
                    "bootstrap po dniu i n_eff zmierzone w M05, nie liczba wierszy",
            })
        checklist.raise_if_failed()
        report["leakage_checklist"] = checklist.as_report()
        print(f"  checklista leakage'u: {checklist.as_report()['n_checks']} pozycji, "
              f"{'PRZECHODZI' if checklist.passes else 'NIE PRZECHODZI'}")

        # Artefakty wymagane przez prerejestrację. `observations.parquet` to
        # WSZYSTKIE decyzje ze wszystkimi cechami i osiami — jedna komórka
        # byłaby wyborem, a trzy pliki utrudniałyby odtworzenie.
        pl.concat(list(series.values()), how="diagonal").write_parquet(
            run.dir / "observations.parquet")
        (run.dir / "t003_momentum.yaml").write_bytes(PREREG.read_bytes())
        (run.dir / "t003_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        write_markdown(run.dir / "t003.md", report, pre)

        run.record(status=report["verdict"]["status"],
                   upper_bound_acc_pct=report["verdict"]["upper_bound_acc_pct"],
                   layer_b_run=bool(signalled))
        print(f"\nWERDYKT H01: {report['verdict']['status']}")
        print(f"Gorne ograniczenie: {report['verdict']['upper_bound_acc_pct']:.2f}% trafnosci")
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
