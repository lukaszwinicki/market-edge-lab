#!/usr/bin/env python3
"""M08 krok A — geometria zdarzeń wybicia (H07). Kontrola, NIE próba. N bez zmian.

PYTANIE

Ile zdarzeń H07 faktycznie ląduje na siatce decyzyjnej, na której T002
miałby mierzyć, i jak bardzo są od siebie zależne w czasie i między parami?
To są dwie niezmierzone wielkości w arytmetyce mocy T002: liczba zdarzeń
(M07 policzył 1 050 na wszystkich godzinach, bez siatki i bez sesji)
i stosunek n_eff/n dla cechy rzadkiej, punktowej.

Kryterium `FALSIFIED` na warstwie A wymaga CI95 wewnątrz ±ρ_breakeven,
czyli n_eff ≥ (1,96 / 0,05401)² ≈ 1 317 (M04). Żadna statystyka zwrotów po
zdarzeniu nie ma więcej informacji niż zdarzeń, więc jeżeli nawet
optymistyczna górna granica n_eff wypada poniżej tej liczby, krok B
(rozkład zerowy z surogatu) nie może zmienić warunku 1 bramki — zmierzy
wyłącznie martwą strefę.

ADR-020 — GRANICA, KTÓREJ TEN SKRYPT NIE MOŻE PRZEKROCZYĆ

H07 nie ma żywej prerejestracji. Skrypt korzysta z wyjątku ADR-020 tak samo
jak M07:

* **nie importuje** warstwy etykiet, wejść ani symulatora;
* **nie dołącza żadnej ceny** z chwili późniejszej niż bar decyzji;
* koniec okna wynikowego liczy wyłącznie jako ZNACZNIK CZASU
  (`add_business_days`), bo od niego zależy nakładanie się okien i odcięcie
  okien przecinających koniec segmentu. To jest geometria kalendarza, nie
  wynik: ta sama kolumna dla każdej decyzji, niezależnie od cechy.

Pilnuje tego `tests/test_m08_event_geometry.py`, czytając źródło.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np
import polars as pl
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.timeaxis import add_business_days  # noqa: E402
from src.features.breakout import attach as attach_breakout  # noqa: E402
from src.harness.market import load_h1, require_fresh_bars  # noqa: E402
from src.harness.registry import start_run  # noqa: E402
from src.research.grid import (  # noqa: E402
    decision_grid, in_session, map_ts, session_hours,
)

UTC = dt.timezone.utc

WARMUP_START = dt.datetime(2015, 1, 1, tzinfo=UTC)
FIRST_DECISION = dt.datetime(2016, 1, 1, tzinfo=UTC)
RESEARCH_END = dt.datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC)

# Definicja zdarzenia — ta sama co w M07, jedna komórka (rekomendacja planu).
DONCH_N = 55
QUIET_BARS = 55
H_BUSINESS_DAYS = 3             # horyzont T003, jedyny po ADR-015
GRID_LOOKBACK = 480             # jak T003 — ta sama siatka, nie jej kopia

# --- Kryterium, ZADEKLAROWANE PRZED PRZEBIEGIEM ---------------------------
RHO_BREAKEVEN = 0.05401         # M04: 51,72% trafności kierunku
Z95 = 1.96
Z_POWER = 0.8416212335729143    # moc 80%, jak MDE w M05 — ta sama definicja progu
N_EFF_FOR_FALSIFIED = (Z95 / RHO_BREAKEVEN) ** 2
# M05, `sign_aligned`: ujemne iloczyny kowariancji dały P_eff 6,97 na 6 par.
# Zmierzone dla cechy GĘSTEJ, nie dla zdarzeń — użyte wyłącznie jako
# optymistyczny mnożnik górnej granicy, nigdy jako wartość.
SIGN_CANCEL_MAX = 6.97 / 6.0
# Reguła: jeżeli n_zdarzeń(primary) * SIGN_CANCEL_MAX < N_EFF_FOR_FALSIFIED,
# warunek 1 bramki (FALSIFIED osiągalne) jest niespełniony przy KAŻDYM
# modelu zależności, a krok B mierzy już tylko martwą strefę.

# Kierunek zdarzenia wyrażony jako kierunek USD: +1 = dolar silniejszy.
USD_SIGN = {"EURUSD": -1, "GBPUSD": -1, "AUDUSD": -1,
            "USDJPY": +1, "USDCAD": +1, "EURJPY": 0}


# --------------------------------------------------------------------------
# Czyste funkcje — testowane na danych syntetycznych
# --------------------------------------------------------------------------

def interval_clusters(starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Rozmiary skupisk okien nakładających się łańcuchowo.

    Okna `[start, end)`; dwa okna należą do jednego skupiska, jeżeli
    łańcuch nakładań je łączy. Liczba skupisk to zachłanne, dolne
    ograniczenie liczby obserwacji niezależnych — ta sama logika co n_eff
    M02 po oknach rozłącznych.
    """
    if starts.size == 0:
        return np.zeros(0, dtype=np.int64)
    order = np.argsort(starts, kind="stable")
    s, e = starts[order], ends[order]
    sizes = []
    cur_end, size = e[0], 1
    for i in range(1, s.size):
        if s[i] < cur_end:
            size += 1
            cur_end = max(cur_end, e[i])
        else:
            sizes.append(size)
            cur_end, size = e[i], 1
    sizes.append(size)
    return np.asarray(sizes, dtype=np.int64)


def overlap_partners(starts: np.ndarray, ends: np.ndarray, groups: np.ndarray
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Dla każdego okna: ile innych okien z TEJ SAMEJ grupy i z INNYCH grup
    nakłada się z nim w czasie."""
    n = starts.size
    same = np.zeros(n, dtype=np.int64)
    other = np.zeros(n, dtype=np.int64)
    for i in range(n):
        ov = (starts < ends[i]) & (starts[i] < ends)
        ov[i] = False
        same[i] = int((ov & (groups == groups[i])).sum())
        other[i] = int((ov & (groups != groups[i])).sum())
    return same, other


def usd_alignment(starts: np.ndarray, ends: np.ndarray, groups: np.ndarray,
                  usd_dir: np.ndarray) -> dict:
    """Wśród par okien z RÓŻNYCH par walutowych, które się nakładają i obie
    mają nogę USD: jaki udział wskazuje ten sam kierunek dolara.

    Blisko 1 znaczy, że współwystępujące zdarzenia są jednym zakładem na
    czynnik USD, a nie kilkoma niezależnymi obserwacjami.
    """
    n = starts.size
    agree = total = 0
    for i in range(n):
        if usd_dir[i] == 0:
            continue
        j = np.arange(i + 1, n)
        ov = ((starts[j] < ends[i]) & (starts[i] < ends[j])
              & (groups[j] != groups[i]) & (usd_dir[j] != 0))
        total += int(ov.sum())
        agree += int((usd_dir[j][ov] == usd_dir[i]).sum())
    return {"pairs": total, "same_usd_direction": (agree / total) if total else None}


def gate_arithmetic(n: float) -> dict:
    """Połowa CI95 i próg wykrywalności przy n obserwacjach niezależnych.

    Próg wykrywalności to MDE przy mocy 80%, `(z_α + z_β)·SE` — ta sama
    definicja co w M05, żeby liczby dało się zestawić wprost. Osiągalność
    `FALSIFIED` rozstrzyga połowa CI95, nie MDE.

    Mapowanie ρ → trafność zakłada normalność dwuwymiarową, jak w M05;
    służy wyłącznie do wyrażenia progu w jednostce, o której da się mieć
    zdanie.
    """
    if n <= 0:
        return {"n": n, "half_width": None, "detect_acc_pct": None,
                "ratio_to_breakeven": None, "falsified_reachable": False}
    se = 1.0 / math.sqrt(n)
    hw = Z95 * se
    mde = (Z95 + Z_POWER) * se
    return {
        "n": float(n),
        "half_width": hw,
        "mde_rho": mde,
        "detect_acc_pct": 100 * (0.5 + math.asin(min(mde, 1.0)) / math.pi),
        "ratio_to_breakeven": hw / RHO_BREAKEVEN,
        "falsified_reachable": bool(hw < RHO_BREAKEVEN),
    }


# --------------------------------------------------------------------------
# Przebieg
# --------------------------------------------------------------------------

def event_decisions(symbol: str, cfg: dict) -> tuple[pl.DataFrame, int]:
    """Decyzje na siatce T003 w barach, w których odpaliło zdarzenie.

    Zwraca (zdarzenia na siatce, liczba zdarzeń liczona jak w M07 —
    do sprawdzenia zgodności z M07).
    """
    h1 = load_h1(symbol, WARMUP_START, RESEARCH_END, cfg)
    feats = attach_breakout(h1, (DONCH_N,), quiet_bars=QUIET_BARS)
    evt_col = f"brk_evt_{DONCH_N}"
    m07_style = int((feats.filter(pl.col("ts") >= FIRST_DECISION)
                     .get_column(evt_col) != 0).sum())

    dec, _, _ = decision_grid(
        h1, first_decision=FIRST_DECISION, lookback_bars=GRID_LOOKBACK,
        atr_period=cfg["volatility"]["atr_period"],
        min_h1_bars=cfg["data"]["d1_boundary"]["min_h1_bars"])
    dec = (
        dec.select("bar_ts", "ts_decision")
        .join(feats.select(pl.col("ts").alias("bar_ts"), pl.col(evt_col).alias("evt")),
              on="bar_ts", how="left")
        .filter(pl.col("evt").is_not_null() & (pl.col("evt") != 0))
        .with_columns(
            map_ts("ts_decision", lambda t: add_business_days(t, H_BUSINESS_DAYS))
            .alias("window_end"),
            pl.lit(symbol).alias("symbol"),
        )
        # Warunek 4 ADR-011, jak w T003: okno wychodzące poza segment odpada.
        .with_columns((pl.col("window_end") <= RESEARCH_END).alias("inside_segment"))
    )
    return dec, m07_style


def geometry(ev: pl.DataFrame) -> dict:
    """Wszystkie liczby geometrii dla jednego zbioru zdarzeń (wiele par)."""
    s = ev.get_column("ts_decision").dt.epoch("ms").to_numpy()
    e = ev.get_column("window_end").dt.epoch("ms").to_numpy()
    sym = ev.get_column("symbol").to_numpy()
    usd = np.array([USD_SIGN[x] for x in sym]) * ev.get_column("evt").to_numpy()
    same, other = overlap_partners(s, e, sym)
    clusters_all = interval_clusters(s, e)
    per_pair_clusters = {x: int(interval_clusters(s[sym == x], e[sym == x]).size)
                         for x in sorted(set(sym))}
    return {
        "n_events": int(ev.height),
        "per_symbol": {x: int((sym == x).sum()) for x in sorted(set(sym))},
        "per_year": {str(k): int(v) for k, v in
                     ev.group_by(pl.col("ts_decision").dt.year().alias("y"))
                     .len().sort("y").iter_rows()},
        "per_hour": {str(k): int(v) for k, v in
                     ev.group_by(pl.col("ts_decision").dt.hour().alias("hr"))
                     .len().sort("hr").iter_rows()},
        "share_up": float((ev.get_column("evt") > 0).mean()) if ev.height else None,
        "within_pair": {
            "share_with_overlapping_same_pair": float((same > 0).mean()) if same.size else None,
            "clusters_sum_over_pairs": int(sum(per_pair_clusters.values())),
            "clusters_per_pair": per_pair_clusters,
        },
        "cross_pair": {
            "share_with_overlapping_other_pair": float((other > 0).mean()) if other.size else None,
            "mean_other_pair_partners": float(other.mean()) if other.size else None,
            "usd_alignment": usd_alignment(s, e, sym, usd),
        },
        "clusters_all_pairs": {
            "n_clusters": int(clusters_all.size),
            "mean_size": float(clusters_all.mean()) if clusters_all.size else None,
            "max_size": int(clusters_all.max()) if clusters_all.size else None,
        },
    }


def main() -> int:
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    symbols = list(cfg["instruments"]["discovery"])
    require_fresh_bars(symbols, WARMUP_START, RESEARCH_END, cfg)
    start_h, end_h = session_hours(cfg)

    params = {
        "adr": "ADR-020",
        "exception": "ADR-020 — geometria zdarzen, same znaczniki czasu, bez cen po decyzji",
        "donch_n": DONCH_N, "quiet_bars": QUIET_BARS,
        "h_business_days": H_BUSINESS_DAYS, "grid_lookback": GRID_LOOKBACK,
        "session_primary": [start_h, end_h],
        "rho_breakeven": RHO_BREAKEVEN,
        "n_eff_for_falsified": N_EFF_FOR_FALSIFIED,
        "sign_cancel_max": SIGN_CANCEL_MAX,
        "criterion_set_before_run": True,
        "symbols": symbols,
        "looks_forward": False,
    }

    with start_run("M08A geometria zdarzen H07 pod audyt mocy T002 "
                   "(ADR-020, bez spojrzenia w przod)", params, kind="control") as run:
        parts, m07_check = [], {}
        for sym in symbols:
            dec, m07_style = event_decisions(sym, cfg)
            m07_check[sym] = m07_style
            parts.append(dec)
            print(f"  {sym}: {m07_style} zdarzeń jak w M07, {dec.height} na siatce")
        allh = pl.concat(parts).sort("ts_decision")
        allh_in = allh.filter(pl.col("inside_segment"))
        prim = in_session(allh_in, start_h, end_h)

        report: dict = {
            "params": params,
            "m07_consistency": m07_check,
            "dropped_crossing_segment_end": int(allh.height - allh_in.height),
            "primary": geometry(prim),
            "all_hours": geometry(allh_in),
        }

        n_prim = report["primary"]["n_events"]
        n_all = report["all_hours"]["n_events"]
        upper_prim = n_prim * SIGN_CANCEL_MAX
        report["arithmetic"] = {
            "primary_iid": gate_arithmetic(n_prim),
            "primary_upper_bound_sign_cancel": gate_arithmetic(upper_prim),
            "primary_clusters_lower_bound": gate_arithmetic(
                report["primary"]["clusters_all_pairs"]["n_clusters"]),
            "all_hours_iid": gate_arithmetic(n_all),
            "all_hours_upper_bound_sign_cancel": gate_arithmetic(n_all * SIGN_CANCEL_MAX),
        }
        unreachable = upper_prim < N_EFF_FOR_FALSIFIED
        report["verdict"] = {
            "criterion": ("n_primary * SIGN_CANCEL_MAX < N_EFF_FOR_FALSIFIED "
                          "=> FALSIFIED nieosiagalne przy kazdym modelu zaleznosci"),
            "criterion_set_before_run": True,
            "n_events_primary": n_prim,
            "upper_bound_n_eff_primary": upper_prim,
            "n_eff_for_falsified": N_EFF_FOR_FALSIFIED,
            "falsified_unreachable_any_model": bool(unreachable),
            "note": ("Mierzy WYŁĄCZNIE geometrię próby. Nie obejrzał ani jednej "
                     "ceny po decyzji (ADR-020)."),
        }

        (run.dir / "m08a_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        run.record(**{k: v for k, v in report["verdict"].items() if k != "note"})

        print(json.dumps({k: report[k] for k in
                          ("dropped_crossing_segment_end", "arithmetic", "verdict")},
                         indent=1, ensure_ascii=False, default=str))
        for name in ("primary", "all_hours"):
            g = report[name]
            print(f"\n[{name}] n={g['n_events']} per_symbol={g['per_symbol']}")
            print(f"  within_pair={g['within_pair']}")
            print(f"  cross_pair={g['cross_pair']}")
            print(f"  clusters={g['clusters_all_pairs']}")
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
