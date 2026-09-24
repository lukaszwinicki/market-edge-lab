#!/usr/bin/env python3
"""Pobranie stóp polityki pieniężnej (ADR-025, opcja b). Przebieg `infra`, N bez zmian."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.policy_rates import FETCH_FROM, FETCH_TO, MANUAL, fetch_all  # noqa: E402
from src.harness.registry import start_run  # noqa: E402


def main() -> int:
    params = {"from": FETCH_FROM.isoformat(), "to": FETCH_TO.isoformat(),
              "fetched": {"USD": "FRED DFEDTARU/DFEDTARL mid", "EUR": "FRED ECBDFR",
                          "GBP": "BoE IUDBEDR", "CAD": "BoC V39079"},
              "manual": {c: [(d.isoformat(), r, s) for d, r, s in rows]
                         for c, rows in MANUAL.items()}}
    with start_run("fetch_policy_rates — stopy polityki pienieznej, 6 walut (ADR-025)",
                   params, kind="infra") as run:
        shas = fetch_all()
        for c, s in shas.items():
            print(f"  {c}: {s[:12]}")
        run.record(sha256=shas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
