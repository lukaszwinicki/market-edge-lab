#!/usr/bin/env python
"""Zbuduj bary M1 i H1 z cache ticków i wygeneruj raport jakości.

Przetwarzanie idzie miesiącami, nie całym zakresem naraz: rok ticków
jednego symbolu to rzędu 25 mln rekordów, a bary są maleńkie. Trzymanie
wszystkiego w pamięci nic nie daje poza ryzykiem OOM.

    python scripts/build_bars.py                      # wszystko z cache
    python scripts/build_bars.py --symbols EURUSD     # jeden symbol
    python scripts/build_bars.py --years 2015 2016    # wybrane lata
    python scripts/build_bars.py --no-report          # bez raportu jakości

Można uruchamiać w trakcie pobierania — przetwarza to, co już jest. Obok
każdej partycji ląduje `source.json` z liczbą godzin cache, z których
powstała (`src/data/provenance.py`). Partycja zbudowana z wycinka jest
potem odrzucana przez `require_fresh_bars()` w runnerach, więc niepełny
przebieg nie zamieni się po cichu w niepełny wynik badawczy.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

import polars as pl
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.dukascopy import decode_bi5  # noqa: E402
from src.data.provenance import write_provenance  # noqa: E402
from src.data.quality import (  # noqa: E402
    accepted_outages_from, build_report, render_markdown,
)
from src.data.resample import (  # noqa: E402
    FREQ_H1, FREQ_M1, bars_from_ticks, ticks_to_frame, validate_bars,
)
from src.harness.market import tick_cache  # noqa: E402

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "base.yaml"

log = logging.getLogger("build_bars")


def hour_of(path: Path) -> dt.datetime:
    """Odtwórz godzinę UTC ze ścieżki cache: .../SYM/YYYY/MM/DD/HHh_ticks.bi5"""
    y, m, d = path.parts[-4], path.parts[-3], path.parts[-2]
    return dt.datetime(int(y), int(m), int(d), int(path.stem[:2]), tzinfo=UTC)


def cached_hours(cache: Path, symbol: str) -> dict[tuple[int, int], list[Path]]:
    """Pliki z danymi, pogrupowane po (rok, miesiąc). Puste pomijamy."""
    groups: dict[tuple[int, int], list[Path]] = defaultdict(list)
    for p in (cache / symbol).rglob("*.bi5"):
        if p.stat().st_size == 0:
            continue                      # godzina bez handlu — nie daje bara
        h = hour_of(p)
        groups[(h.year, h.month)].append(p)
    return {k: sorted(v, key=hour_of) for k, v in sorted(groups.items())}


def build_symbol(symbol: str, cache: Path, out: Path, years: set[int] | None) -> pl.DataFrame:
    """Zbuduj bary dla jednego symbolu. Zwraca H1 (do raportu jakości)."""
    months = cached_hours(cache, symbol)
    if years:
        months = {k: v for k, v in months.items() if k[0] in years}
    if not months:
        log.warning("%s: brak danych w cache", symbol)
        return pl.DataFrame()

    by_year_m1: dict[int, list[pl.DataFrame]] = defaultdict(list)
    by_year_h1: dict[int, list[pl.DataFrame]] = defaultdict(list)
    # Proweniencja partycji (patrz `data/provenance.py`): ile niepustych
    # plików cache i ile ticków poszło na dany rok. Liczymy pliki ZANIM
    # cokolwiek odpadnie przy dekodowaniu — to ma odpowiadać na pytanie
    # „z jakiego wycinka cache ta partycja powstała", nie „ile barów wyszło".
    src_files: dict[int, int] = defaultdict(int)
    src_ticks: dict[int, int] = defaultdict(int)
    n_ticks = 0

    for (year, month), paths in months.items():
        src_files[year] += len(paths)
        blocks = [decode_bi5(p.read_bytes(), symbol, hour_of(p)) for p in paths]
        ticks = ticks_to_frame(blocks)
        if ticks.is_empty():
            continue
        n_ticks += ticks.height
        src_ticks[year] += ticks.height
        by_year_m1[year].append(bars_from_ticks(ticks, FREQ_M1))
        by_year_h1[year].append(bars_from_ticks(ticks, FREQ_H1))
        log.debug("%s %04d-%02d: %d ticków", symbol, year, month, ticks.height)

    h1_all = []
    for year in sorted(by_year_m1):
        # Bary graniczne miesiąca trzeba scalić: tick z 31.01 23:59 i z
        # 01.02 00:00 należą do różnych paczek, ale ta sama godzina H1 może
        # się rozciągać przez granicę tylko przy niepełnych danych — mimo to
        # łączymy defensywnie, żeby nie powstały zduplikowane etykiety.
        m1 = _merge(pl.concat(by_year_m1[year]))
        h1 = _merge(pl.concat(by_year_h1[year]))
        validate_bars(m1)
        validate_bars(h1)
        _write(out / "m1", symbol, year, m1, "m1", src_files[year], src_ticks[year])
        _write(out / "h1", symbol, year, h1, "h1", src_files[year], src_ticks[year])
        h1_all.append(h1)
        log.info("%s %d: M1=%d H1=%d barów", symbol, year, m1.height, h1.height)

    log.info("%s: %d ticków -> %d barów H1", symbol, n_ticks,
             sum(h.height for h in h1_all))
    return pl.concat(h1_all) if h1_all else pl.DataFrame()


def _merge(bars: pl.DataFrame) -> pl.DataFrame:
    """Scal bary o tej samej etykiecie (granice paczek) i posortuj."""
    if bars.is_empty() or not bars["ts"].is_duplicated().any():
        return bars.sort("ts")
    return (
        bars.group_by("ts").agg(
            pl.col("bid_open").first(), pl.col("bid_high").max(),
            pl.col("bid_low").min(), pl.col("bid_close").last(),
            pl.col("ask_open").first(), pl.col("ask_high").max(),
            pl.col("ask_low").min(), pl.col("ask_close").last(),
            pl.col("spread_max").max(), pl.col("spread_close").last(),
            pl.col("n_ticks").sum(),
        ).sort("ts").select(bars.columns)
    )


def _write(base: Path, symbol: str, year: int, bars: pl.DataFrame, freq: str,
           n_source_files: int, n_ticks: int) -> None:
    d = base / f"symbol={symbol}" / f"year={year}"
    d.mkdir(parents=True, exist_ok=True)
    bars.write_parquet(d / "bars.parquet", compression="zstd")
    write_provenance(d, symbol=symbol, year=year, freq=freq,
                     n_source_files=n_source_files, n_ticks=n_ticks)


def _cohort_symbols(cfg: dict, cohort: str) -> list[str]:
    """Instrumenty kohorty. Kohorta replikacyjna nie ma danych (ADR-008)."""
    inst = cfg["instruments"]
    if cohort == "replication":
        rep = inst["replication"]
        if not rep.get("available"):
            raise SystemExit(
                "kohorta replikacyjna nie ma danych — ADR-008. Skład jest "
                "zamrożony, pobranie to osobna decyzja: " + ", ".join(rep["symbols"]))
        return list(rep["symbols"])
    return list(inst[cohort])


def _guard_sealed(cfg: dict, years: set[int] | None, allow: bool) -> set[int] | None:
    """Nie buduj świec dla lat zapieczętowanych (ADR-004).

    Pieczęci pilnuje loader i to jest właściwe miejsce — ale obrona w głąb
    jest tu tania. Świeca, która nigdy nie powstała, nie da się wczytać
    nawet przez pomyłkę z `unseal=True`. Surowe ticki zostają nietknięte,
    więc w fazie końcowej wystarczy zbudować je wtedy.
    """
    s = cfg["data"]["splits"]["sealed_holdout"]
    lo = dt.date.fromisoformat(str(s["start"])).year
    hi = dt.date.fromisoformat(str(s["end"])).year
    sealed = set(range(lo, hi + 1))

    if allow:
        log.warning("PIECZĘĆ ZDJĘTA JAWNIE dla lat %s — to jest decyzja, "
                    "nie rutyna", sorted(sealed))
        return years

    if years is None:
        allowed = set(range(2000, lo))
        log.info("Pieczęć: pomijam lata %s (ADR-004)", sorted(sealed))
        return allowed

    blocked = years & sealed
    if blocked:
        raise SystemExit(
            f"lata {sorted(blocked)} są zapieczętowane (ADR-004). Budowa świec "
            f"materializuje dane, których faza 1 nie ma prawa widzieć. "
            f"Świadome otwarcie: --allow-sealed")
    return years


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cohort", default="discovery",
                    choices=["discovery", "replication"])
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--years", nargs="*", type=int)
    ap.add_argument("--cache", type=Path, default=None,
                    help="domyslnie data.tick_cache.path z configu (ADR-007)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "bars")
    ap.add_argument("--report", type=Path,
                    default=ROOT / "reports" / "data_quality.md")
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--report-only", action="store_true",
                    help="nie przebudowuj barów, tylko przelicz raport jakości "
                         "z partycji na dysku (np. po zmianie listy z ADR-045)")
    ap.add_argument("--allow-sealed", action="store_true",
                    help="zbuduj rowniez lata zapieczetowane — TYLKO w fazie "
                         "koncowej walidacji, za swiadoma decyzja")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cache = args.cache or tick_cache(cfg)
    symbols = args.symbols or _cohort_symbols(cfg, args.cohort)
    years = set(args.years) if args.years else None
    years = _guard_sealed(cfg, years, args.allow_sealed)

    h1_by_symbol: dict[str, pl.DataFrame] = {}
    if args.report_only:
        # Raport jest funkcją barów na dysku, nie cache'u ticków, więc da się go
        # przeliczyć bez przebudowy. Świadomie BEZ `require_fresh_bars()`:
        # ten tryb odświeża sam raport, a świeżość partycji pilnuje runner
        # przed przebiegiem (`src/data/provenance.py`).
        for symbol in symbols:
            parts = sorted((args.out / "h1" / f"symbol={symbol}").glob("year=*/bars.parquet"))
            if years:
                parts = [p for p in parts if int(p.parent.name.split("=")[1]) in years]
            if parts:
                h1_by_symbol[symbol] = pl.concat([pl.read_parquet(p) for p in parts]).sort("ts")
                log.info("%s: %d barów H1 z %d partycji", symbol,
                         h1_by_symbol[symbol].height, len(parts))
    else:
        for symbol in symbols:
            h1 = build_symbol(symbol, cache, args.out, years)
            if not h1.is_empty():
                h1_by_symbol[symbol] = h1

    if not h1_by_symbol:
        log.error("Brak barów — czy cache jest pusty (albo partycje nie zbudowane)?")
        return 1

    if args.no_report:
        return 0

    report = build_report(h1_by_symbol)
    # ADR-045: lista ręcznie zaakceptowanych godzin awarii. Raport drukuje ją
    # razem z dowodem, więc odstępstwo od werdyktu detektora jest widoczne.
    accepted = accepted_outages_from(cfg)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_markdown(report, accepted), encoding="utf-8")

    ok, reasons = report.passes_gate_0(accepted=accepted)
    log.info("Raport: %s", args.report)
    log.info("Bramka 0: %s", "PRZECHODZI" if ok else "NIE PRZECHODZI")
    for r in reasons:
        log.warning("  %s", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
