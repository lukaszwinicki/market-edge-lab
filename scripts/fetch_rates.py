#!/usr/bin/env python3
"""Pobranie bieżącego vintage stóp OECD z FRED. Przebieg `infra`, N bez zmian.

Wyłącznie pod pomiar geometrii cechy H04 (ADR-022) — patrz nagłówek
`src/data/rates.py`, dlaczego bieżący vintage nie może wejść do testu.
Odcisk każdego pliku trafia do rejestru, bo FRED rewiduje serie i jutrzejsze
pobranie może dać inne bajty.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.rates import SERIES, fetch_current_vintage  # noqa: E402
from src.harness.registry import start_run  # noqa: E402


def main() -> int:
    ids = sorted({sid for kind in SERIES.values() for sid in kind.values()})
    with start_run("fetch_rates — biezacy vintage OECD z FRED, tylko pod geometrie "
                   "cechy H04 (ADR-022)", {"series": ids, "source": "fredgraph.csv"},
                   kind="infra") as run:
        shas = {}
        for sid in ids:
            path, sha = fetch_current_vintage(sid)
            shas[sid] = sha
            print(f"  {sid}: {sha[:12]}  {path.relative_to(ROOT)}")
        run.record(n_series=len(ids), sha256=shas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
