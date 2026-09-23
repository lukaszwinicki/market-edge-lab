"""Testy dekodera .bi5 — bez sieci, na danych syntetycznych.

Prawdziwych danych nie da się użyć jako oracle: nie znamy poprawnej
odpowiedzi z góry. Dlatego konstruujemy pliki o znanej zawartości.
"""
import datetime as dt
import lzma
import struct

import numpy as np
import pytest

from src.data.dukascopy import (
    RECORD, ScaleError, bi5_url, cache_path, decode_bi5, hours_between,
)

UTC = dt.timezone.utc
H = dt.datetime(2020, 1, 2, 10, tzinfo=UTC)


def make_bi5(records) -> bytes:
    """records: [(ms, ask_pts, bid_pts, ask_vol, bid_vol)]"""
    raw = b"".join(RECORD.pack(*r) for r in records)
    c = lzma.LZMACompressor(format=lzma.FORMAT_ALONE)
    return c.compress(raw) + c.flush()


# --- URL: miesiąc indeksowany od zera ---------------------------------------

def test_url_month_is_zero_indexed():
    assert bi5_url("EURUSD", H).endswith("/EURUSD/2020/00/02/10h_ticks.bi5")
    grudzien = dt.datetime(2020, 12, 31, 23, tzinfo=UTC)
    assert bi5_url("EURUSD", grudzien).endswith("/EURUSD/2020/11/31/23h_ticks.bi5")


def test_url_requires_timezone():
    with pytest.raises(ValueError):
        bi5_url("EURUSD", dt.datetime(2020, 1, 2, 10))


def test_cache_path_uses_natural_month():
    # ścieżka na dysku jest czytelna dla człowieka, więc miesiąc 1-12
    p = cache_path(dt.datetime and __import__("pathlib").Path("/d"), "EURUSD", H)
    assert p.as_posix() == "/d/EURUSD/2020/01/02/10h_ticks.bi5"


# --- Dekodowanie ------------------------------------------------------------

def test_decode_known_records():
    payload = make_bi5([
        (0,      112033, 112030, 1.76, 1.50),
        (1_460,  112032, 112030, 0.19, 0.94),
        (3_599_999, 111985, 111982, 1.0, 1.0),
    ])
    b = decode_bi5(payload, "EURUSD", H)

    assert len(b) == 3
    assert b.symbol == "EURUSD"
    np.testing.assert_allclose(b.bid, [1.12030, 1.12030, 1.11982])
    np.testing.assert_allclose(b.ask, [1.12033, 1.12032, 1.11985])
    assert b.ts[0] == np.datetime64("2020-01-02T10:00:00.000")
    assert b.ts[2] == np.datetime64("2020-01-02T10:59:59.999")
    assert np.all(b.ask >= b.bid)


def test_decode_jpy_scale():
    # USDJPY ~108 w styczniu 2020; punkty przy skali 1e-3
    payload = make_bi5([(0, 108_255, 108_249, 1.0, 1.0)])
    b = decode_bi5(payload, "USDJPY", H)
    np.testing.assert_allclose(b.bid, [108.249])
    np.testing.assert_allclose(b.ask, [108.255])


def test_wrong_scale_is_caught_loudly():
    """Gdyby USDJPY miało skalę 1e-5, cena wyszłaby ~1.08 zamiast ~108."""
    payload = make_bi5([(0, 108_255, 108_249, 1.0, 1.0)])
    import src.data.dukascopy as d
    orig = d.SYMBOL_SCALE["USDJPY"]
    d.SYMBOL_SCALE["USDJPY"] = 1e-5
    try:
        with pytest.raises(ScaleError, match="zła SYMBOL_SCALE"):
            decode_bi5(payload, "USDJPY", H)
    finally:
        d.SYMBOL_SCALE["USDJPY"] = orig


def test_empty_payload_is_no_data_not_error():
    b = decode_bi5(b"", "EURUSD", H)
    assert len(b) == 0
    assert b.ts.dtype == np.dtype("datetime64[ms]")


def test_truncated_file_raises():
    payload = make_bi5([(0, 112033, 112030, 1.0, 1.0)])
    raw = lzma.decompress(payload, format=lzma.FORMAT_ALONE)[:15]
    c = lzma.LZMACompressor(format=lzma.FORMAT_ALONE)
    with pytest.raises(ValueError, match="nie dzieli się"):
        decode_bi5(c.compress(raw) + c.flush(), "EURUSD", H)


def test_offset_beyond_hour_raises():
    payload = make_bi5([(3_600_000, 112033, 112030, 1.0, 1.0)])
    with pytest.raises(ValueError, match="poza godziną"):
        decode_bi5(payload, "EURUSD", H)


# --- Iterator godzin --------------------------------------------------------

def test_hours_between_is_half_open():
    hs = list(hours_between(H, H + dt.timedelta(hours=3)))
    assert len(hs) == 3
    assert hs[0] == H and hs[-1] == H + dt.timedelta(hours=2)


def test_hours_between_truncates_to_full_hour():
    start = dt.datetime(2020, 1, 2, 10, 37, 12, tzinfo=UTC)
    assert next(iter(hours_between(start, start + dt.timedelta(hours=1)))) == H


# --- Kolejność zadań w pobieraniu -------------------------------------------

def test_download_jobs_interleave_symbols_by_hour(monkeypatch, tmp_path):
    """Po częściowym pobraniu chcemy spójny przedział dat dla WSZYSTKICH
    symboli, a nie jednego kompletnego symbolu i reszty pustej."""
    import src.data.download as dl

    seen = []
    monkeypatch.setattr(dl, "fetch_hour", lambda s, sym, hour, **kw: seen.append((sym, hour)) or b"")

    dl.download_range(
        ["EURUSD", "GBPUSD", "USDJPY"],
        H, H + dt.timedelta(hours=2),
        tmp_path / "cache", tmp_path / "m.jsonl",
        workers=1, progress_every=10**9,
    )

    assert len(seen) == 6
    # pierwsze trzy zadania to ta sama godzina, trzy różne symbole
    assert {s for s, _ in seen[:3]} == {"EURUSD", "GBPUSD", "USDJPY"}
    assert {h for _, h in seen[:3]} == {H}
    assert {h for _, h in seen[3:]} == {H + dt.timedelta(hours=1)}


# --- Wznawialność -----------------------------------------------------------

def test_failed_hours_uses_last_status_not_first(tmp_path):
    """Godzina, która zawiodła, a przy wznowieniu się udała, nie jest nieudana."""
    import json
    from src.data.download import failed_hours
    m = tmp_path / "m.jsonl"
    m.write_text("\n".join(json.dumps(r) for r in [
        {"symbol": "EURUSD", "hour": "2020-01-02T10:00:00+00:00", "status": "failed", "bytes": 0},
        {"symbol": "EURUSD", "hour": "2020-01-02T10:00:00+00:00", "status": "ok", "bytes": 100},
        {"symbol": "GBPUSD", "hour": "2020-01-02T11:00:00+00:00", "status": "failed", "bytes": 0},
    ]) + "\n")
    assert failed_hours(m) == [("GBPUSD", dt.datetime(2020, 1, 2, 11, tzinfo=UTC))]


def test_orphan_part_files_are_cleaned(monkeypatch, tmp_path):
    """Zabicie procesu w trakcie zapisu zostawia .part — musi zniknąć."""
    import src.data.download as dl
    cache = tmp_path / "cache"
    orphan = cache / "EURUSD" / "2020" / "01" / "02" / "10h_ticks.bi5.part"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"niedokonczone")

    monkeypatch.setattr(dl, "fetch_hour", lambda *a, **k: b"")
    dl.download_range(["EURUSD"], H, H + dt.timedelta(hours=1),
                      cache, tmp_path / "m.jsonl", workers=1, progress_every=10**9)

    assert not orphan.exists()


def test_existing_files_are_never_refetched(monkeypatch, tmp_path):
    """Rdzeń wznawialności: to, co jest w cache, nie rusza sieci."""
    import src.data.download as dl
    cache = tmp_path / "cache"

    calls = []
    monkeypatch.setattr(dl, "fetch_hour", lambda s, sym, hour, **k: calls.append(hour) or b"x")

    rng = (H, H + dt.timedelta(hours=3))
    first = dl.download_range(["EURUSD"], *rng, cache, tmp_path / "m.jsonl",
                              workers=1, progress_every=10**9)
    second = dl.download_range(["EURUSD"], *rng, cache, tmp_path / "m.jsonl",
                               workers=1, progress_every=10**9)

    assert first == {"ok": 3, "empty": 0, "cached": 0, "failed": 0}
    assert second == {"ok": 0, "empty": 0, "cached": 3, "failed": 0}
    assert len(calls) == 3        # drugi przebieg nie dotknął sieci
