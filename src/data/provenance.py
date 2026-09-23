# PRZENIESIONE z market-quant (ADR-005). Odwolania "ADR-0NN", "PROJECT_SPEC"
# i "SPEC SS" w tym pliku dotycza logu decyzji TAMTEGO projektu, nie tego.
"""Proweniencja partycji barów — z czego dana partycja została zbudowana.

PO CO

`data/bars/{freq}/symbol=X/year=Y/bars.parquet` powstaje z plików cache
`data/raw/dukascopy/X/Y/...`. Nic w samym Parquecie nie mówi, ILE plików
źródłowych poszło na jego budowę. Skutek zaobserwowany w praktyce:
partycja EURUSD 2019 zbudowana ze 130 godzin próbek dekodera miała 118
barów H1, podczas gdy cache trzymał już 8 754 godziny. Odczyt takiej
partycji zwracał 118 barów zamiast ~6 200 — bez błędu, bez ostrzeżenia,
z poprawnym schematem i sensownie wyglądającymi cenami.

To jest dokładnie ta klasa awarii, przed którą broni się reszta projektu:
cicha zła odpowiedź jest gorsza niż wyjątek. Wynik policzony na 2% roku
wygląda jak wynik, a nie jak awaria.

JAK

Obok każdego `bars.parquet` leży `source.json` z liczbą NIEPUSTYCH plików
`.bi5`, które poszły na tę partycję. Weryfikacja (`require_fresh_bars`
w `harness/market.py`) porównuje ją z tym, co cache trzyma teraz.

Liczymy pliki, nie ticki: rozmiar pliku zależy od obrotu, a liczba godzin
jest twarda i tania do policzenia. Pliki zerobajtowe (godziny bez handlu)
pomijamy po obu stronach — downloader zapisuje je jako znacznik „sprawdzone,
pusto", a baru nie dają.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

UTC = dt.timezone.utc

SOURCE_MANIFEST = "source.json"


def write_provenance(partition: Path, *, symbol: str, year: int, freq: str,
                     n_source_files: int, n_ticks: int) -> None:
    """Zapisz `source.json` obok `bars.parquet`."""
    (partition / SOURCE_MANIFEST).write_text(json.dumps({
        "symbol": symbol,
        "year": year,
        "freq": freq,
        "n_source_files": n_source_files,
        "n_ticks": n_ticks,
        "built_utc": dt.datetime.now(UTC).isoformat(timespec="seconds"),
    }, indent=2), encoding="utf-8")


def read_provenance(partition: Path) -> dict | None:
    """Zawartość `source.json` albo None, gdy partycja go nie ma."""
    path = partition / SOURCE_MANIFEST
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def count_cache_hours(cache: Path, symbol: str, year: int) -> int:
    """Niepuste pliki `.bi5` w cache dla (symbol, rok).

    Ta sama reguła pomijania pustych co w `build_bars.cached_hours` — inaczej
    porównanie dawałoby fałszywe alarmy na każdym weekendzie.
    """
    root = cache / symbol / f"{year:04d}"
    if not root.is_dir():
        return 0
    return sum(1 for p in root.rglob("*.bi5") if p.stat().st_size > 0)
