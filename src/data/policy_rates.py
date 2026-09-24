"""Stopy polityki pieniężnej — cecha H04 po ADR-025.

DLACZEGO NIE OECD

Seria OECD dla strefy euro nie istniała point-in-time w 2016–2017 (ADR-025).
Stopa polityki pieniężnej jest znana w chwili ogłoszenia, nie jest
rewidowana i nie ma opóźnienia publikacji — point-in-time wynika z jej
konstrukcji, nie z odtwarzania vintage.

DEFINICJA — jedna dla wszystkich walut

„Stopa polityki sterująca rynkiem overnight", czyli ta, którą zarabia albo
płaci pozycja rolowana przez noc:

    USD  środek przedziału docelowego Fed Funds   FRED DFEDTARU / DFEDTARL
    EUR  stopa depozytowa EBC (DFR)                FRED ECBDFR
         — przy nadpłynności to DFR, nie MRO, wyznacza rynek overnight
    GBP  Bank Rate                                 BoE IADB IUDBEDR
    CAD  docelowa stopa overnight                  BoC Valet V39079
    AUD  cash rate target                          TABELA RĘCZNA (RBA blokuje pobieranie skryptem)
    JPY  stopa od salda polityki BoJ               TABELA RĘCZNA (BoJ nie ma prostego CSV)

Tabele ręczne są krótkie (10 zmian RBA, 1 zmiana BoJ w 2015–2021), każda
pozycja niesie źródło, a M12 sprawdza je niezależnie: średnia miesięczna
musi zgadzać się z serią OECD overnight tej samej waluty.

DOSTĘPNOŚĆ

Decyzja w dniu d widzi wartość z dnia ≤ d − 1 dzień roboczy. Źródła datują
zmianę dniem ogłoszenia (Fed, BoE, BoC) albo dniem wejścia w życie (EBC, RBA,
BoJ) — margines jednego dnia roboczego pokrywa każdą godzinę ogłoszenia
i nie wymaga jej znajomości. Błąd idzie wyłącznie w stronę spóźnienia.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
POLICY_DIR = ROOT / "data" / "rates" / "policy"

FETCH_FROM = dt.date(2014, 6, 1)
FETCH_TO = dt.date(2021, 12, 31)

# (data wejścia w życie, stopa %, źródło). Stan PRZED pierwszą pozycją
# musi być pierwszą pozycją — tabela zaczyna się przed oknem danych.
MANUAL: dict[str, list[tuple[dt.date, float, str]]] = {
    "AUD": [
        (dt.date(2013, 8, 8), 2.50, "RBA, decyzja 2013-08-06"),
        (dt.date(2015, 2, 4), 2.25, "RBA, decyzja 2015-02-03"),
        (dt.date(2015, 5, 6), 2.00, "RBA, decyzja 2015-05-05"),
        (dt.date(2016, 5, 4), 1.75, "RBA, decyzja 2016-05-03"),
        (dt.date(2016, 8, 3), 1.50, "RBA, decyzja 2016-08-02"),
        (dt.date(2019, 6, 5), 1.25, "RBA, decyzja 2019-06-04"),
        (dt.date(2019, 7, 3), 1.00, "RBA, decyzja 2019-07-02"),
        (dt.date(2019, 10, 2), 0.75, "RBA, decyzja 2019-10-01"),
        (dt.date(2020, 3, 4), 0.50, "RBA, decyzja 2020-03-03"),
        (dt.date(2020, 3, 20), 0.25, "RBA, decyzja nadzwyczajna 2020-03-19"),
        (dt.date(2020, 11, 4), 0.10, "RBA, decyzja 2020-11-03"),
    ],
    "JPY": [
        (dt.date(2008, 11, 17), 0.10,
         "BoJ, oprocentowanie nadwyżek rezerw (complementary deposit facility)"),
        (dt.date(2016, 2, 16), -0.10,
         "BoJ, 'QQE with a Negative Interest Rate', ogłoszenie 2016-01-29, "
         "stosowane od okresu rezerwowego 2016-02-16"),
    ],
}

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"
BOE = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
BOC = "https://www.bankofcanada.ca/valet/observations/V39079/csv"


class PolicyRateError(RuntimeError):
    """Brak danych albo niespójność źródła. Nie zgadujemy."""


# --------------------------------------------------------------------------
# Parsowanie — czyste funkcje
# --------------------------------------------------------------------------

def parse_fred(text: str, sid: str) -> pl.DataFrame:
    df = pl.read_csv(io.StringIO(text), infer_schema_length=0)
    if sid not in df.columns:
        raise PolicyRateError(f"FRED: brak kolumny {sid}")
    return df.select(pl.col(df.columns[0]).str.to_date("%Y-%m-%d").alias("date"),
                     pl.col(sid).cast(pl.Float64, strict=False).alias("rate")
                     ).drop_nulls()


def parse_boe(text: str) -> pl.DataFrame:
    df = pl.read_csv(io.StringIO(text), infer_schema_length=0)
    if df.columns != ["DATE", "IUDBEDR"]:
        raise PolicyRateError(f"BoE: nieoczekiwane kolumny {df.columns}")
    return df.select(pl.col("DATE").str.to_date("%d %b %Y").alias("date"),
                     pl.col("IUDBEDR").cast(pl.Float64).alias("rate"))


def parse_boc(text: str) -> pl.DataFrame:
    body = text[text.index('"date"'):] if '"date"' in text else text
    df = pl.read_csv(io.StringIO(body), infer_schema_length=0)
    if "V39079" not in df.columns:
        raise PolicyRateError(f"BoC: brak V39079 w {df.columns}")
    return df.select(pl.col("date").str.to_date("%Y-%m-%d").alias("date"),
                     pl.col("V39079").cast(pl.Float64, strict=False).alias("rate")
                     ).drop_nulls()


def manual_series(ccy: str) -> pl.DataFrame:
    rows = MANUAL[ccy]
    dates = [r[0] for r in rows]
    if dates != sorted(dates):
        raise PolicyRateError(f"{ccy}: tabela ręczna nieposortowana")
    return pl.DataFrame({"date": dates, "rate": [r[1] for r in rows]})


# --------------------------------------------------------------------------
# Pobranie
# --------------------------------------------------------------------------

def fetch_all(dest: Path = POLICY_DIR) -> dict[str, str]:
    """Pobierz cztery źródła automatyczne, zapisz sześć serii. Zwraca sha256."""
    import requests

    ua = {"User-Agent": "market-edge-lab research (non-commercial)"}
    get = lambda url, **p: requests.get(url, params=p, headers=ua, timeout=60)  # noqa: E731

    def fred(sid):
        r = get(FRED, id=sid, cosd=FETCH_FROM.isoformat(), coed=FETCH_TO.isoformat())
        r.raise_for_status()
        return parse_fred(r.text, sid)

    up, lo = fred("DFEDTARU"), fred("DFEDTARL")
    usd = up.join(lo, on="date", suffix="_lo").select(
        "date", ((pl.col("rate") + pl.col("rate_lo")) / 2).alias("rate"))
    r = get(BOE, **{"csv.x": "yes", "Datefrom": FETCH_FROM.strftime("%d/%b/%Y"),
                    "Dateto": FETCH_TO.strftime("%d/%b/%Y"), "SeriesCodes": "IUDBEDR",
                    "CSVF": "TN", "UsingCodes": "Y", "VPD": "Y", "VFD": "N"})
    r.raise_for_status()
    gbp = parse_boe(r.text)
    r = get(BOC, start_date=FETCH_FROM.isoformat(), end_date=FETCH_TO.isoformat())
    r.raise_for_status()
    cad = parse_boc(r.text)

    series = {"USD": usd, "EUR": fred("ECBDFR"), "GBP": gbp, "CAD": cad,
              "AUD": manual_series("AUD"), "JPY": manual_series("JPY")}
    dest.mkdir(parents=True, exist_ok=True)
    shas = {}
    for ccy, df in series.items():
        path = dest / f"{ccy}.parquet"
        df.sort("date").write_parquet(path)
        shas[ccy] = hashlib.sha256(path.read_bytes()).hexdigest()
    return shas


# --------------------------------------------------------------------------
# Odczyt point-in-time
# --------------------------------------------------------------------------

def load_series(ccy: str, root: Path = POLICY_DIR) -> pl.DataFrame:
    path = root / f"{ccy}.parquet"
    if not path.exists():
        raise PolicyRateError(f"brak {path} — uruchom scripts/fetch_policy_rates.py")
    return pl.read_parquet(path).sort("date")


def policy_pit(series: pl.DataFrame, decision_dates: list[dt.date],
               margin_business_days: int = 1) -> np.ndarray:
    """Stopa widoczna w każdej dacie decyzji: ostatnia wartość z dnia
    ≤ d − `margin_business_days` dni roboczych. Brak wcześniejszej → NaN."""
    cut = [np.busday_offset(np.datetime64(d, "D"), -margin_business_days,
                            roll="backward").astype(dt.date) for d in decision_dates]
    q = pl.DataFrame({"i": np.arange(len(cut)), "cutoff": cut}).sort("cutoff")
    out = (q.join_asof(series.rename({"date": "cutoff_src"}), left_on="cutoff",
                       right_on="cutoff_src", strategy="backward")
           .sort("i").get_column("rate"))
    return out.fill_null(np.nan).to_numpy()
