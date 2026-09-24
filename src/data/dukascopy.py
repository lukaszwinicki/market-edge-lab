# PRZENIESIONE z market-quant (ADR-005). Odwolania "ADR-0NN", "PROJECT_SPEC"
# i "SPEC SS" w tym pliku dotycza logu decyzji TAMTEGO projektu, nie tego.
"""Pobieranie i dekodowanie tickowych danych Dukascopy (.bi5).

Format zweryfikowany empirycznie 2026-09-19 na EURUSD 2020-01-02 10h:

    URL     https://datafeed.dukascopy.com/datafeed/{SYM}/{YYYY}/{MM}/{DD}/{HH}h_ticks.bi5
            UWAGA: MM jest indeksowane OD ZERA (styczeń = 00).

    Ciało   LZMA w formacie ALONE (nie XZ), po dekompresji ciąg
            20-bajtowych rekordów big-endian ">IIIff":

                ms      uint32  offset od początku godziny
                ask     uint32  cena w punktach
                bid     uint32  cena w punktach
                ask_vol float32
                bid_vol float32

    Skala   ask/bid * SYMBOL_SCALE[symbol] daje cenę.

Godziny bez handlu (weekendy, święta) zwracają pustą odpowiedź albo 404 —
to NIE jest błąd, tylko brak danych, i musi być odnotowane w manifeście.
"""

from __future__ import annotations

import datetime as dt
import logging
import lzma
import random
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests

log = logging.getLogger(__name__)

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
RECORD = struct.Struct(">IIIff")
RECORD_SIZE = RECORD.size  # 20

# Mnożnik przeliczający punkty na cenę. Pary z JPY mają 3 miejsca po
# przecinku, reszta 5. Wartości poniżej są ZAŁOŻENIEM — weryfikuje je
# PLAUSIBLE_RANGE przy każdym dekodowaniu, więc błąd nie przejdzie cicho.
SYMBOL_SCALE: dict[str, float] = {
    "EURUSD": 1e-5,
    "GBPUSD": 1e-5,
    "AUDUSD": 1e-5,
    "USDCAD": 1e-5,
    "USDJPY": 1e-3,
    "EURJPY": 1e-3,
}

def pip_size(symbol: str) -> float:
    """Wartość jednego pipsa w jednostkach ceny.

    Wyprowadzana ze skali punktu, a nie z osobnej tabeli — dwie tabele
    mogłyby się rozjechać. Kwotowanie jest 5- albo 3-cyfrowe, więc pips
    to zawsze 10 punktów: 1e-4 dla par bez JPY, 1e-2 dla par z JPY.

    Pojęcie „pipsa" nie przenosi się na złoto ani indeksy, więc dla
    instrumentu spoza kohorty funkcja ODMAWIA zamiast zgadywać.
    """
    if symbol not in known_instruments():
        _refuse(symbol, "wartości pipsa")
    return SYMBOL_SCALE[symbol] * 10


# Zakresy prawdopodobnych cen 2015-2026. Celem NIE jest wykrycie anomalii
# rynkowej, tylko złapanie pomyłki o rząd wielkości w skali.
PLAUSIBLE_RANGE: dict[str, tuple[float, float]] = {
    "EURUSD": (0.80, 1.60),
    "GBPUSD": (0.90, 1.90),
    "AUDUSD": (0.50, 1.10),
    "USDCAD": (0.90, 1.70),
    "USDJPY": (70.0, 250.0),
    "EURJPY": (90.0, 250.0),
}

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class UnknownInstrumentError(KeyError):
    """Instrument spoza skalibrowanej kohorty. Dziedziczy po `KeyError`,
    więc nie zmienia zachowania kodu, który go już łapał."""


def known_instruments() -> frozenset[str]:
    """Instrumenty, dla których aparatura zna skalę punktu i zakres ceny.

    To jest JEDYNA lista, wobec której wolno liczyć koszt albo dekodować
    ticki. Kohorta replikacyjna z `base.yaml` (XAUUSD, WTI, SPX500, DAX)
    **nie jest** tu obecna i ma nie być, dopóki nie przejdzie własnej
    kalibracji — patrz `_refuse()`.
    """
    return frozenset(SYMBOL_SCALE) & frozenset(PLAUSIBLE_RANGE)


def _refuse(symbol: str, what: str) -> None:
    """Odmów obsługi instrumentu spoza kohorty — głośno i z instrukcją.

    Cicha odpowiedź jest tu groźniejsza od wyjątku: `is_cross("DAX")`
    zwracało `True`, czyli podłogę kosztu „FX cross" 2,5 pipsa dla indeksu.
    Backtest policzyłby się do końca i zwrócił liczbę bez znaczenia.
    """
    raise UnknownInstrumentError(
        f"{symbol}: brak kalibracji, nie można policzyć {what}. "
        f"Skalibrowane: {sorted(known_instruments())}. "
        "Instrument spoza tej listy wymaga skali punktu, zakresu ceny, "
        "progu doby (`min_h1_bars`) i własnego poziomu kosztu — a zmiana "
        "sekcji `frozen: true` w base.yaml wymaga NOWEGO ADR-u. "
        "Aparatura była kalibrowana na FX (M03, M04); inna klasa aktywów "
        "wymaga powtórzenia obu."
    )


class ScaleError(ValueError):
    """Zdekodowane ceny leżą poza prawdopodobnym zakresem dla symbolu."""


@dataclass(frozen=True)
class TickBlock:
    """Ticki z jednej godziny UTC."""

    symbol: str
    hour: dt.datetime          # początek godziny, tz-aware UTC
    ts: np.ndarray             # datetime64[ms], UTC
    bid: np.ndarray            # float64
    ask: np.ndarray            # float64
    bid_vol: np.ndarray        # float32
    ask_vol: np.ndarray        # float32

    def __len__(self) -> int:
        return len(self.ts)


def bi5_url(symbol: str, hour: dt.datetime) -> str:
    """Zbuduj URL. Miesiąc indeksowany od zera — najczęstszy błąd."""
    if hour.tzinfo is None:
        raise ValueError("hour musi być tz-aware (UTC)")
    h = hour.astimezone(dt.timezone.utc)
    return (
        f"{BASE_URL}/{symbol}/{h.year:04d}/{h.month - 1:02d}/"
        f"{h.day:02d}/{h.hour:02d}h_ticks.bi5"
    )


def cache_path(root: Path, symbol: str, hour: dt.datetime) -> Path:
    h = hour.astimezone(dt.timezone.utc)
    return (
        root / symbol / f"{h.year:04d}" / f"{h.month:02d}"
        / f"{h.day:02d}" / f"{h.hour:02d}h_ticks.bi5"
    )


def decode_bi5(payload: bytes, symbol: str, hour: dt.datetime) -> TickBlock:
    """Zdekoduj surowe ciało .bi5 na TickBlock.

    Pusty payload oznacza godzinę bez handlu i daje pusty TickBlock.
    """
    if symbol not in known_instruments():
        _refuse(symbol, "skali ticków")
    scale = SYMBOL_SCALE[symbol]
    hour = hour.astimezone(dt.timezone.utc)

    if not payload:
        return _empty_block(symbol, hour)

    raw = lzma.decompress(payload, format=lzma.FORMAT_ALONE)
    if len(raw) % RECORD_SIZE:
        raise ValueError(
            f"{symbol} {hour:%Y-%m-%d %H}h: długość {len(raw)} B nie dzieli się "
            f"przez {RECORD_SIZE} — plik uszkodzony"
        )
    n = len(raw) // RECORD_SIZE
    if n == 0:
        return _empty_block(symbol, hour)

    arr = np.frombuffer(
        raw,
        dtype=np.dtype([
            ("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"),
            ("ask_vol", ">f4"), ("bid_vol", ">f4"),
        ]),
        count=n,
    )

    ms = arr["ms"].astype(np.int64)
    if np.any(ms >= 3_600_000):
        raise ValueError(f"{symbol} {hour:%Y-%m-%d %H}h: offset poza godziną")

    hour_ms = np.int64(hour.timestamp() * 1000)
    ts = (hour_ms + ms).astype("datetime64[ms]")

    bid = arr["bid"].astype(np.float64) * scale
    ask = arr["ask"].astype(np.float64) * scale

    lo, hi = PLAUSIBLE_RANGE[symbol]
    med = float(np.median(bid))
    if not (lo <= med <= hi):
        raise ScaleError(
            f"{symbol} {hour:%Y-%m-%d %H}h: mediana bid {med:.5f} poza zakresem "
            f"[{lo}, {hi}] — najprawdopodobniej zła SYMBOL_SCALE"
        )

    return TickBlock(
        symbol=symbol,
        hour=hour,
        ts=ts,
        bid=bid,
        ask=ask,
        bid_vol=arr["bid_vol"].astype(np.float32),
        ask_vol=arr["ask_vol"].astype(np.float32),
    )


def _empty_block(symbol: str, hour: dt.datetime) -> TickBlock:
    return TickBlock(
        symbol=symbol,
        hour=hour,
        ts=np.empty(0, dtype="datetime64[ms]"),
        bid=np.empty(0, dtype=np.float64),
        ask=np.empty(0, dtype=np.float64),
        bid_vol=np.empty(0, dtype=np.float32),
        ask_vol=np.empty(0, dtype=np.float32),
    )


def make_session(user_agent: str = "market-quant-research/0.1") -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept-Encoding": "identity"})
    return s


def fetch_hour(
    session: requests.Session,
    symbol: str,
    hour: dt.datetime,
    *,
    max_attempts: int = 8,
    connect_timeout: float = 15.0,
    read_timeout: float = 60.0,
    base_backoff: float = 2.0,
    max_backoff: float = 300.0,
) -> bytes | None:
    """Pobierz jedną godzinę. Zwraca ciało, b"" dla braku danych, None gdy nie udało się.

    Feed bywa niestabilny — obserwowano naprzemiennie 200, 429, 503
    i connect timeout w odstępie minut. Stąd agresywny backoff.
    """
    url = bi5_url(symbol, hour)

    for attempt in range(1, max_attempts + 1):
        try:
            r = session.get(url, timeout=(connect_timeout, read_timeout))
        except (requests.Timeout, requests.ConnectionError) as exc:
            wait = _backoff(attempt, base_backoff, max_backoff)
            log.warning("%s %s: %s — ponawiam za %.0fs (%d/%d)",
                        symbol, hour, type(exc).__name__, wait, attempt, max_attempts)
            time.sleep(wait)
            continue

        if r.status_code == 200:
            return r.content
        if r.status_code == 404:
            return b""  # brak danych, nie błąd
        if r.status_code in RETRYABLE_STATUS:
            wait = _retry_after(r) or _backoff(attempt, base_backoff, max_backoff)
            log.warning("%s %s: HTTP %d — ponawiam za %.0fs (%d/%d)",
                        symbol, hour, r.status_code, wait, attempt, max_attempts)
            time.sleep(wait)
            continue

        log.error("%s %s: HTTP %d — nie ponawiam", symbol, hour, r.status_code)
        return None

    log.error("%s %s: wyczerpano %d prób", symbol, hour, max_attempts)
    return None


def _backoff(attempt: int, base: float, cap: float) -> float:
    """Wykładniczy backoff z jitterem, żeby nie synchronizować ponowień."""
    return min(cap, base * (2 ** (attempt - 1))) * (0.5 + random.random())


def _retry_after(r: requests.Response) -> float | None:
    raw = r.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def hours_between(start: dt.datetime, end: dt.datetime):
    """Kolejne pełne godziny UTC w [start, end)."""
    cur = start.astimezone(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = end.astimezone(dt.timezone.utc)
    step = dt.timedelta(hours=1)
    while cur < end:
        yield cur
        cur += step
