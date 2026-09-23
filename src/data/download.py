# PRZENIESIONE z market-quant (ADR-005). Odwolania "ADR-0NN", "PROJECT_SPEC"
# i "SPEC SS" w tym pliku dotycza logu decyzji TAMTEGO projektu, nie tego.
"""Wznawialne pobieranie tickowego archiwum Dukascopy.

Decyzje projektowe:

* **Cache surowych .bi5 na dysku.** ~20 kB/godzinę, więc 6 par x 10 lat to
  rzędu 8 GB. Trzymanie surowych plików daje wznawialność i proweniencję:
  Parquet można przebudować bez ponownego pobierania.

* **Godziny bez handlu zapisujemy jako plik zerowej długości.** Bez tego
  każde wznowienie ponawiałoby wszystkie weekendy. Zero-bajtowy plik
  znaczy "sprawdzone, brak danych".

* **Nie zakładamy godzin otwarcia rynku.** Pobieramy każdą godzinę i
  pozwalamy manifestowi *wyprowadzić* rzeczywisty kalendarz handlu.
  Zakodowanie założeń o sesjach po cichu ukryłoby luki w danych.

* **Niska współbieżność.** Feed bywa niestabilny (obserwowano 429, 503
  i connect timeout w odstępie minut), więc cel to przejść raz spokojnie,
  a nie pobrać szybko i dostać bana.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from .dukascopy import cache_path, fetch_hour, hours_between, make_session

log = logging.getLogger(__name__)

UTC = dt.timezone.utc


@dataclass(frozen=True)
class HourResult:
    symbol: str
    hour: str          # ISO 8601 UTC
    status: str        # "ok" | "empty" | "cached" | "failed"
    bytes: int


class Manifest:
    """Append-only JSONL. Jedna linia na pobraną godzinę."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, result: HourResult) -> None:
        line = json.dumps(asdict(result), separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


def download_range(
    symbols: list[str],
    start: dt.datetime,
    end: dt.datetime,
    cache_root: Path,
    manifest_path: Path,
    *,
    workers: int = 4,
    progress_every: int = 500,
) -> dict[str, int]:
    """Pobierz [start, end) dla podanych symboli. Można przerwać i wznowić.

    Zwraca licznik statusów.
    """
    cache_root = Path(cache_root)
    manifest = Manifest(Path(manifest_path))

    # Pliki .part zostają po zabiciu procesu w trakcie zapisu. Nigdy nie są
    # czytane (sprawdzamy istnienie .bi5), ale bez sprzątania narastałyby
    # przy każdym wznowieniu.
    orphans = list(cache_root.rglob("*.bi5.part"))
    for o in orphans:
        o.unlink(missing_ok=True)
    if orphans:
        log.info("Usunięto %d niedokończonych plików .part po poprzednim przebiegu",
                 len(orphans))

    # Kolejność: godzina na zewnątrz, symbol wewnątrz. Dzięki temu w każdym
    # momencie mamy spójny, ciągły przedział dat dla WSZYSTKICH symboli,
    # zamiast jednego kompletnego symbolu i pięciu pustych. Pozwala to
    # rozwijać resampling i raport jakości na częściowym pobraniu.
    jobs = [
        (sym, hour)
        for hour in hours_between(start, end)
        for sym in symbols
    ]
    total = len(jobs)
    log.info("Do pobrania: %d godzin (%d symboli)", total, len(symbols))

    counts = {"ok": 0, "empty": 0, "cached": 0, "failed": 0}
    lock = threading.Lock()
    local = threading.local()

    def session():
        if not hasattr(local, "s"):
            local.s = make_session()
        return local.s

    def work(job) -> HourResult:
        sym, hour = job
        dest = cache_path(cache_root, sym, hour)

        if dest.exists():
            return HourResult(sym, hour.isoformat(), "cached", dest.stat().st_size)

        payload = fetch_hour(session(), sym, hour)
        if payload is None:
            return HourResult(sym, hour.isoformat(), "failed", 0)

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".bi5.part")
        tmp.write_bytes(payload)
        tmp.replace(dest)   # atomowo — przerwanie nie zostawia obciętego pliku

        status = "ok" if payload else "empty"
        return HourResult(sym, hour.isoformat(), status, len(payload))

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, j): j for j in jobs}
        for fut in as_completed(futures):
            res = fut.result()
            manifest.append(res)
            with lock:
                counts[res.status] += 1
                done += 1
                if done % progress_every == 0 or done == total:
                    log.info(
                        "%d/%d (%.1f%%)  ok=%d empty=%d cached=%d failed=%d",
                        done, total, 100 * done / total,
                        counts["ok"], counts["empty"],
                        counts["cached"], counts["failed"],
                    )

    return counts


def failed_hours(manifest_path: Path) -> list[tuple[str, dt.datetime]]:
    """Godziny, które NADAL są nieudane — do ponowienia osobnym przebiegiem.

    Manifest jest append-only, więc ta sama godzina może mieć wiele wpisów
    z kolejnych wznowień. Liczy się wyłącznie ostatni status: godzina, która
    zawiodła w pierwszym przebiegu i udała się w drugim, nie jest nieudana.
    """
    latest: dict[tuple[str, str], str] = {}
    p = Path(manifest_path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            latest[(rec["symbol"], rec["hour"])] = rec["status"]
    return [
        (sym, dt.datetime.fromisoformat(hour))
        for (sym, hour), status in latest.items()
        if status == "failed"
    ]
