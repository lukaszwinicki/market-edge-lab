#!/usr/bin/env python3
"""M07 — redundancja cech H01 i H02. Kontrola, NIE próba. N bez zmian.

PYTANIE

Ile informacji `donch_pos` (H02, stan) dokłada ponad `mom_k` (H01)? I czy
zdarzenie wybicia (H07) jest tą samą wielkością co stan, czy inną?

DLACZEGO TO NIE JEST T002

`HYPOTHESES.md` stawia redundancję jako **warunek reaktywacji H02**: hipoteza
dostaje własny trial tylko wtedy, gdy pomiar wykaże, że wnosi informację
ponad H01. Po T003 pytanie zrobiło się ostre — `mom_k` nie niesie opłacalnej
informacji, więc jeżeli `donch_pos` jest z nim silnie skorelowany, T002
w dużej części powtórzy T003 za cenę kolejnych prób przy N = 10.

Rozstrzygnięcie tego PRZED prerejestracją kosztuje zero prób.

ADR-020 — GRANICA, KTÓREJ TEN SKRYPT NIE MOŻE PRZEKROCZYĆ

H02 i H07 nie mają żywej prerejestracji, więc ADR-012 domyślnie zakazuje
liczenia ich cechy. ADR-020 otwiera wąski wyjątek pod trzema warunkami,
z których drugi jest tu najważniejszy: przebieg musi być **strukturalnie
niezdolny** spojrzeć w przód.

Dlatego ten skrypt:

* **nie importuje** `research/labels.py`, `research/entries.py`
  ani `execution/simulator.py`;
* **nie woła** `with_horizon` i nie tworzy kolumn `t1` ani `fwd_atr`;
* liczy wyłącznie statystyki **cecha↔cecha** na tych samych barach.

Pilnuje tego `tests/test_m07_boundary.py`, czytając źródło — nie obietnica
w komentarzu. Pierwsze zestawienie `donch_pos` z czymkolwiek patrzącym
w przód jest przebiegiem `strategy` i wymaga prerejestracji.

CZEGO TEN PRZEBIEG NIE ROZSTRZYGA

Nie mówi, czy H02 ma przewagę — nie może, bo nie ogląda ani jednego zwrotu
w przód. Mówi wyłącznie, **czy pyta o to samo, co H01**.
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

from src.features.breakout import attach as attach_breakout  # noqa: E402
from src.features.momentum import attach_mom  # noqa: E402
from src.features.volatility import atr_h1  # noqa: E402
from src.harness.market import load_h1, require_fresh_bars  # noqa: E402
from src.harness.registry import start_run  # noqa: E402

UTC = dt.timezone.utc

WARMUP_START = dt.datetime(2015, 1, 1, tzinfo=UTC)
FIRST_DECISION = dt.datetime(2016, 1, 1, tzinfo=UTC)
RESEARCH_END = dt.datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC)

MOM_K = (24, 120, 480)          # siatka T003
DONCH_N = (55,)                 # zakres z market-quant (ADR-001)
STATE_THRESHOLD = 0.80          # próg „stanu" z market-quant
QUIET_BARS = 55                 # zdarzenie = pierwsze wyjście po okresie ciszy

# Próg decyzyjny, ZADEKLAROWANY PRZED PRZEBIEGIEM.
# `HYPOTHESES.md` wymaga „kryterium ilościowego ustalonego przed
# uruchomieniem, nie po zobaczeniu rozrzutu".
REDUNDANT_ABOVE = 0.70          # |rho| Spearmana stan↔momentum


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


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    return pearson(rank(a), rank(b))


def features_for(symbol: str, cfg: dict) -> pl.DataFrame:
    """Bary H1 z obiema cechami. Żadnego okna w przód, żadnej etykiety."""
    h1 = load_h1(symbol, WARMUP_START, RESEARCH_END, cfg)
    h1 = atr_h1(h1, cfg["volatility"]["atr_period"])
    h1 = attach_mom(h1, MOM_K)
    h1 = attach_breakout(h1, DONCH_N, quiet_bars=QUIET_BARS)
    return h1.filter(pl.col("ts") >= FIRST_DECISION)


def overlap_stats(state: np.ndarray, mom: np.ndarray) -> dict:
    """Ile razy stan i znak momentum mówią to samo.

    Sedno podejrzenia z `HYPOTHESES.md`: *„jeśli cena jest w górnych 20%
    zakresu 55 barów, `mom_480 > 0` jest niemal pewne"*. Tu jest liczba.
    """
    hot = state > STATE_THRESHOLD
    up = mom > 0
    ok = np.isfinite(state) & np.isfinite(mom)
    hot, up = hot[ok], up[ok]
    n = hot.size
    return {
        "n": int(n),
        "share_state_hot": float(hot.mean()),
        "share_mom_up": float(up.mean()),
        "p_mom_up_given_state_hot": float(up[hot].mean()) if hot.any() else None,
        "p_mom_up_given_state_cold": float(up[~hot].mean()) if (~hot).any() else None,
        "agreement": float((hot == up).mean()),
    }


def main() -> int:
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    symbols = list(cfg["instruments"]["discovery"])
    require_fresh_bars(symbols, WARMUP_START, RESEARCH_END, cfg)

    params = {
        "adr": "ADR-020",
        "exception": "ADR-020 — pomiar cecha<->cecha, bez spojrzenia w przod",
        "mom_k": list(MOM_K),
        "donch_n": list(DONCH_N),
        "state_threshold": STATE_THRESHOLD,
        "quiet_bars": QUIET_BARS,
        "redundant_above": REDUNDANT_ABOVE,
        "symbols": symbols,
        "looks_forward": False,
    }

    with start_run("M07 redundancja cech H01<->H02 (ADR-020, bez spojrzenia w przod)",
                   params, kind="control") as run:
        report: dict = {"params": params, "per_symbol": {}}
        pooled: dict[str, list[np.ndarray]] = {}

        for sym in symbols:
            f = features_for(sym, cfg)
            entry: dict = {"n_bars": f.height, "spearman": {}, "overlap": {},
                           "event": {}}
            for n in DONCH_N:
                st = f.get_column(f"donch_pos_{n}").to_numpy()
                ev = f.get_column(f"brk_evt_{n}").to_numpy()
                for k in MOM_K:
                    mo = f.get_column(f"mom_{k}").to_numpy()
                    ok = np.isfinite(st) & np.isfinite(mo)
                    entry["spearman"][f"donch{n}_vs_mom{k}"] = spearman(st[ok], mo[ok])
                    entry["overlap"][f"donch{n}_vs_mom{k}"] = overlap_stats(st, mo)
                    pooled.setdefault(f"donch{n}_vs_mom{k}", []).append(
                        np.column_stack([st[ok], mo[ok]]))
                fired = ev != 0
                entry["event"][f"n{n}"] = {
                    "share_bars_event": float(fired.mean()),
                    "share_bars_state_hot": float(
                        np.nanmean(st > STATE_THRESHOLD)),
                    "events_total": int(fired.sum()),
                }
            report["per_symbol"][sym] = entry
            print(f"  {sym}: {f.height} barów, "
                  f"rho(donch55, mom480)={entry['spearman']['donch55_vs_mom480']:+.3f}")
            del f

        report["pooled_spearman"] = {}
        for key, parts in pooled.items():
            m = np.vstack(parts)
            report["pooled_spearman"][key] = spearman(m[:, 0], m[:, 1])

        worst = max(abs(v) for v in report["pooled_spearman"].values())
        report["verdict"] = {
            "criterion": f"|rho| > {REDUNDANT_ABOVE} => H02 redundantna z H01",
            "criterion_set_before_run": True,
            "max_abs_spearman": worst,
            "h02_redundant": bool(worst > REDUNDANT_ABOVE),
            "note": ("Mierzy WYŁĄCZNIE, czy H02 pyta o to samo co H01. "
                     "NIE mówi nic o przewadze żadnej z nich — przebieg nie "
                     "obejrzał ani jednego zwrotu w przód (ADR-020)."),
        }

        (run.dir / "m07_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        run.record(**{k: v for k, v in report["verdict"].items() if k != "note"})

        print("\nSpearman pooled (stan vs momentum):")
        for key, v in sorted(report["pooled_spearman"].items()):
            print(f"  {key:<24} {v:+.4f}")
        ev = report["per_symbol"][symbols[0]]["event"]["n55"]
        print(f"\nZdarzenie vs stan (na {symbols[0]}): "
              f"zdarzenie na {ev['share_bars_event']:.2%} barów, "
              f"stan na {ev['share_bars_state_hot']:.2%}")
        print(f"\nWerdykt: H02 {'REDUNDANTNA' if report['verdict']['h02_redundant'] else 'NIE jest redundantna'} "
              f"z H01 (|rho|max = {worst:.3f}, próg {REDUNDANT_ABOVE})")
        print(f"Artefakty: {run.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
