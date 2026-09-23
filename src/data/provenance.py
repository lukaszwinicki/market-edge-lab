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


# --- odcisk zbioru ticków ---------------------------------------------------
#
# Ticki leżą w repozytorium, którego ten projekt nie kontroluje (ADR-007).
# Bez odcisku podmiana albo doszlifowanie danych pod spodem byłoby niewidoczne,
# a wyniki przestałyby być odtwarzalne — przy czym NIC by o tym nie krzyknęło.
#
# Liczymy odcisk z METADANYCH (ścieżka + rozmiar), nie z zawartości: 11 GB
# przez SHA-256 to kilka minut przy każdym uruchomieniu, a na podmianę,
# przycięcie albo dobudowanie plików metadane reagują tak samo. Odcisk ma
# wykrywać zmianę zbioru, nie bronić przed spreparowaniem go bajt po bajcie.

def cache_fingerprint(cache: Path, symbols: list[str],
                      years: range | None = None) -> dict:
    """Odcisk cache ticków: liczba plików, sumaryczny rozmiar, hash manifestu.

    Deterministyczny — ta sama zawartość katalogu daje ten sam hash,
    niezależnie od kolejności obchodzenia systemu plików.
    """
    import hashlib

    lines: list[str] = []
    per_symbol: dict[str, dict] = {}
    total_files = total_bytes = 0

    for symbol in sorted(symbols):
        root = cache / symbol
        files = 0
        size = 0
        for p in sorted(root.rglob("*.bi5")) if root.is_dir() else []:
            n = p.stat().st_size
            if n == 0:
                continue                      # godzina bez handlu — znacznik
            if years is not None and int(p.parts[-4]) not in years:
                continue
            lines.append(f"{p.relative_to(cache).as_posix()}:{n}")
            files += 1
            size += n
        per_symbol[symbol] = {"n_files": files, "n_bytes": size}
        total_files += files
        total_bytes += size

    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    return {
        "sha256": digest,
        "n_files": total_files,
        "n_bytes": total_bytes,
        "per_symbol": per_symbol,
        "years": [min(years), max(years)] if years is not None else None,
    }
