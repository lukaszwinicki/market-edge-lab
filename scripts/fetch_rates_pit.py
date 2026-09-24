#!/usr/bin/env python3
"""Pobranie vintage point-in-time z ALFRED. Przebieg `infra`, N bez zmian.

Vintage z każdego poniedziałku od 2015-12-28 do 2021-12-27 dla sześciu serii
`overnight` (ADR-023). Zapytanie, które mimo ponowień nie zwróci danych, NIE
jest wypełniane — zostaje policzone i zapisane jako brak; loader bierze wtedy
wcześniejszy vintage (informacja starsza, nigdy nowsza).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import sys
import time
from pathlib import Path

import polars as pl
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.rates import (  # noqa: E402
    ALFRED_DIR, ALFREDGRAPH, SERIES, MissingRatesError, parse_alfred_csv,
)
from src.harness.registry import start_run  # noqa: E402

FIRST = dt.date(2015, 12, 28)
LAST = dt.date(2021, 12, 27)
KEEP_FROM = dt.date(2014, 1, 1)     # historia w każdym vintage — wystarczy ogon
RETRIES = 4
PAUSE_S = 0.25


def mondays() -> list[dt.date]:
    out, d = [], FIRST
    while d <= LAST:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def fetch(session: requests.Session, sid: str, day: dt.date) -> pl.DataFrame | None:
    for attempt in range(RETRIES):
        try:
            r = session.get(ALFREDGRAPH, params={"id": sid, "vintage_date": day.isoformat()},
                            timeout=60)
            if r.ok and r.text.strip():
                return parse_alfred_csv(r.text, sid, day).filter(pl.col("month") >= KEEP_FROM)
        except (requests.RequestException, MissingRatesError):
            pass
        time.sleep(PAUSE_S * 4 * (attempt + 1))
    return None


def main() -> int:
    days = mondays()
    ids = list(SERIES["overnight"].values())
    params = {"series": ids, "first": FIRST.isoformat(), "last": LAST.isoformat(),
              "n_vintages_per_series": len(days), "source": "alfredgraph.csv"}
    with start_run("fetch_rates_pit — vintage ALFRED co tydzien, overnight (ADR-023)",
                   params, kind="infra") as run:
        ALFRED_DIR.mkdir(parents=True, exist_ok=True)
        session = requests.Session()
        summary = {}
        for sid in ids:
            parts, missing, empty = [], [], []
            for day in days:
                df = fetch(session, sid, day)
                if df is None:
                    missing.append(day.isoformat())
                elif df.drop_nulls("value").is_empty():
                    # Vintage istnieje, ale nie ma ani jednej obserwacji od
                    # KEEP_FROM — seria nie była wtedy aktualizowana (EUR przed
                    # 2018-01: koniec na 2013-12, ADR-025). To nie jest „pobrany".
                    empty.append(day.isoformat())
                else:
                    parts.append(df)
                time.sleep(PAUSE_S)
            out = pl.concat(parts)
            path = ALFRED_DIR / f"{sid}.parquet"
            out.write_parquet(path)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            summary[sid] = {"vintages": len(parts), "missing": missing,
                            "empty_in_window": empty, "sha256": sha}
            print(f"  {sid}: {len(parts)}/{len(days)} vintage z danymi, braki {len(missing)}, "
                  f"puste w oknie {len(empty)}, {sha[:12]}")
        run.record(series=summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
