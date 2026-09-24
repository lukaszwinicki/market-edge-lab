# PRZENIESIONE z market-quant (ADR-005). Odwolania "ADR-0NN", "PROJECT_SPEC"
# i "SPEC SS" w tym pliku dotycza logu decyzji TAMTEGO projektu, nie tego.
"""Dane i koszty dla harnessu — jedyna droga od Parquetu do symulatora.

PIECZĘĆ HOLD-OUTU

Hold-out 2024-2026 jest otwierany dokładnie raz, w fazie końcowej walidacji.
Pilnujemy tego w miejscu, przez które przechodzi każdy odczyt: zakres
dotykający `data.splits.sealed_holdout` jest odrzucany, chyba że wywołujący
jawnie poda `unseal=True`. Dotyczy to też transakcji z końca 2023 r., których
horyzont sięga w styczeń 2024 — ich rozstrzygnięcie to już ceny z hold-outu.

Pieczęci pilnuje TEN KOD, a nie brak plików: surowe ticki dla lat
zapieczętowanych leżą na dysku i dałoby się z nich zbudować świece.

ŹRÓDŁO TICKÓW JEST TYLKO DO ODCZYTU (ADR-007)

Surowe ticki żyją w repozytorium `market-quant`, które jest read-only.
Ścieżka pochodzi z konfiguracji (`data.tick_cache.path`), nie z kodu —
gdy dane się przeniosą, zmienia się config. Świece budujemy do własnego
`data/` tego projektu i tylko tam zapisujemy.

ŚWIEŻOŚĆ PARTYCJI

`require_fresh_bars()` sprawdza, czy partycje barów zostały zbudowane
z całego cache, który jest teraz na dysku. Wołać PRZED liczeniem
czegokolwiek — dokładnie tak jak `require_coverage()` dla kalendarza.
Powód i tryb awarii: `data/provenance.py`.

Sprawdzenie jest OSOBNE, nie wbudowane w `load_m1`. Partycja zbudowana
w trakcie pobierania jest poprawna jako dane, tylko niekompletna jako
próba badawcza — i to runner, nie funkcja odczytu, wie, czy właśnie
liczy wynik do raportu, czy ogląda dane.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

from ..data.dukascopy import known_instruments, pip_size
from ..data.provenance import count_cache_hours, read_provenance
from ..data.resample import BAR_SCHEMA
from ..execution.simulator import CostModel

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parents[2]
BARS_M1 = ROOT / "data" / "bars" / "m1"
BARS_H1 = ROOT / "data" / "bars" / "h1"


def tick_cache(cfg: dict) -> Path:
    """Katalog surowych ticków, TYLKO DO ODCZYTU (ADR-007).

    Świadomie nie ma tu wartości domyślnej. Domyślna ścieżka wskazująca
    na nieistniejący katalog dawałaby ciche „zero godzin w cache", a to
    w `stale_partitions()` wygląda identycznie jak „nie ma czego budować".
    Brak konfiguracji ma być głośny.
    """
    path = cfg["data"]["tick_cache"]["path"]
    p = Path(path)
    return p if p.is_absolute() else (ROOT / p).resolve()


class SealedHoldoutError(RuntimeError):
    """Próba odczytu zapieczętowanego hold-outu przed fazą końcową."""


class StaleBarsError(RuntimeError):
    """Partycja barów nie odpowiada temu, co jest w cache ticków."""


def sealed_range(cfg: dict) -> tuple[dt.datetime, dt.datetime]:
    """[początek, koniec) hold-outu. Koniec wyłączny: dzień po `end`."""
    s = cfg["data"]["splits"]["sealed_holdout"]
    start = dt.datetime.fromisoformat(str(s["start"])).replace(tzinfo=UTC)
    end = dt.datetime.fromisoformat(str(s["end"])).replace(tzinfo=UTC)
    return start, end + dt.timedelta(days=1)


def load_m1(symbol: str, start: dt.datetime, end: dt.datetime, cfg: dict, *,
            root: Path = BARS_M1, unseal: bool = False) -> pl.DataFrame:
    """Bary M1 symbolu o etykiecie w [start, end], posortowane po `ts`.

    Czyta tylko partycje lat, które zakres obejmuje.
    """
    return _load_bars(symbol, start, end, cfg, root, unseal)


def load_h1(symbol: str, start: dt.datetime, end: dt.datetime, cfg: dict, *,
            root: Path = BARS_H1, unseal: bool = False) -> pl.DataFrame:
    """Bary H1 — ta sama pieczęć co M1. Cechy liczone z hold-outu to też
    odczyt hold-outu."""
    return _load_bars(symbol, start, end, cfg, root, unseal)


def _load_bars(symbol: str, start: dt.datetime, end: dt.datetime, cfg: dict,
               root: Path, unseal: bool) -> pl.DataFrame:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start i end muszą być tz-aware (UTC)")
    s0, s1 = sealed_range(cfg)
    if not unseal and start < s1 and end >= s0:
        raise SealedHoldoutError(
            f"{symbol} [{start:%Y-%m-%d}, {end:%Y-%m-%d}] dotyka hold-outu "
            f"[{s0:%Y-%m-%d}, {s1:%Y-%m-%d}) — zapieczętowany do bramki 4")

    files = [p for y in range(start.year, end.year + 1)
             if (p := root / f"symbol={symbol}" / f"year={y}" / "bars.parquet").exists()]
    if not files:
        return pl.DataFrame(schema=BAR_SCHEMA)
    return (
        pl.scan_parquet(files, hive_partitioning=False)
        .filter(pl.col("ts").is_between(start, end, closed="both"))
        .sort("ts")
        .collect()
    )


def stale_partitions(symbols: list[str], start: dt.datetime, end: dt.datetime,
                     cfg: dict | None = None, *, cache: Path | None = None,
                     roots: dict[str, Path] | None = None) -> list[str]:
    """Opisy partycji, które nie odpowiadają cache'owi ticków.

    Partycja jest nieświeża, gdy dla (symbol, rok) w cache są NIEPUSTE pliki,
    a partycja: nie istnieje, nie ma `source.json`, albo została zbudowana
    z mniejszej liczby plików, niż cache trzyma teraz.

    Więcej plików w partycji niż w cache to nie awaria — cache bywa
    przycinany, a bary są trwałe. Interesuje nas wyłącznie kierunek
    „bary powstały z wycinka".
    """
    if cache is None:
        if cfg is None:
            raise ValueError("podaj `cfg` albo jawnie `cache` — ścieżka do "
                             "ticków nie ma wartości domyślnej (ADR-007)")
        cache = tick_cache(cfg)
    roots = roots or {"m1": BARS_M1, "h1": BARS_H1}
    out: list[str] = []
    for symbol in symbols:
        for year in range(start.year, end.year + 1):
            have = count_cache_hours(cache, symbol, year)
            if not have:
                continue            # nic w cache za ten rok — nie ma co budować
            for freq, root in sorted(roots.items()):
                part = root / f"symbol={symbol}" / f"year={year}"
                if not (part / "bars.parquet").exists():
                    out.append(f"{symbol} {year} {freq}: brak partycji, "
                               f"a cache ma {have} godzin")
                    continue
                prov = read_provenance(part)
                if prov is None:
                    out.append(f"{symbol} {year} {freq}: partycja bez "
                               f"source.json — nieznane pochodzenie")
                elif prov["n_source_files"] < have:
                    out.append(f"{symbol} {year} {freq}: zbudowana z "
                               f"{prov['n_source_files']} godzin, cache ma {have}")
    return out


def require_fresh_bars(symbols: list[str], start: dt.datetime, end: dt.datetime,
                       cfg: dict | None = None, *, cache: Path | None = None,
                       roots: dict[str, Path] | None = None) -> None:
    """Rzuć `StaleBarsError`, jeżeli którakolwiek partycja jest nieświeża.

    Wołane przez runnery przed liczeniem wyniku. Naprawa to zawsze
    `python scripts/build_bars.py`.
    """
    bad = stale_partitions(symbols, start, end, cfg, cache=cache, roots=roots)
    if bad:
        raise StaleBarsError(
            "partycje barów nie odpowiadają cache ticków — uruchom "
            "scripts/build_bars.py:\n  " + "\n  ".join(bad))


def is_cross(symbol: str) -> bool:
    """Para bez USD. Podłoga kosztu dla crossów jest wyższa (ADR-024).

    Pytanie „czy to cross" ma sens WYŁĄCZNIE dla FX. Reguła `"USD" not in
    symbol` odpowiadała na nie także dla `DAX` (True) i `XAUUSD` (False),
    dając indeksowi podłogę „FX cross" 2,5 pipsa — liczbę bez znaczenia,
    zwróconą bez ostrzeżenia. Dlatego teraz odmawia.
    """
    if symbol not in known_instruments():
        from ..data.dukascopy import _refuse
        _refuse(symbol, "klasyfikacji major/cross")
    return "USD" not in symbol


def cost_model_for(symbol: str, cfg: dict) -> CostModel:
    """Model kosztów symbolu wprost z konfiguracji — bez wartości w kodzie."""
    c = cfg["costs"]
    floor = c["min_roundturn_cost_pips"]["fx_crosses" if is_cross(symbol) else "fx_majors"]
    return CostModel(
        pip=pip_size(symbol),
        min_roundturn_pips=floor,
        entry_slippage_x_spread=c["slippage_entry_x_spread"],
        stop_slippage_x_spread=c["slippage_stop_x_spread"],
    )
