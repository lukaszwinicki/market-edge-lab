"""Stopy procentowe — miesięczne serie OECD z FRED, pod H04 (carry).

DWA RODZAJE DOSTĘPU I TYLKO JEDEN JEST TU ZBUDOWANY

    bieżący vintage   to, co FRED pokazuje DZIŚ. Zawiera rewizje, których
                      w dniu decyzji nie było. Wolno go użyć WYŁĄCZNIE do
                      pomiaru geometrii cechy (ADR-022): trwałości,
                      zmienności, korelacji między walutami. Rewizja stopy
                      rzędu kilku punktów bazowych nie zmienia żadnej z nich.
    point-in-time     ALFRED z `realtime_start` = data decyzji (DATA.md §4).
                      Wymagany do KAŻDEGO zestawienia cechy ze zwrotem.
                      Jeszcze nie istnieje.

Dlatego dane bieżącego vintage leżą w `data/rates/current_vintage/`, a nazwa
katalogu i funkcji niesie to ograniczenie — test pilnuje, że warstwa etykiet
i skrypty trialu tego modułu nie importują.

WYBÓR SERII

Rentowności 2-letnie nie istnieją na FRED dla pięciu z sześciu walut
(`market-quant:reports/rates_coverage.md` — raport tamtego repo). Jedyne
serie jednorodne dla całego koszyka to miesięczne serie OECD MEI:
`overnight` (IRSTCI01, stopa natychmiastowa / call money) i `interbank_3m`
(IR3TIB01). Obie w procentach rocznie, średnia z miesiąca, data = pierwszy
dzień miesiąca.

DOSTĘPNOŚĆ

Średnia z miesiąca M jest znana najwcześniej po jego końcu, a OECD publikuje
z opóźnieniem. Do geometrii przyjmujemy, że wartość miesiąca M jest dostępna
od pierwszego dnia miesiąca M + `lag_months` (domyślnie 2). Faktyczne
opóźnienie ustali ALFRED; tu jest tylko przybliżenie, które nie wpływa na
trwałość ani zmienność cechy.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
CURRENT_VINTAGE_DIR = ROOT / "data" / "rates" / "current_vintage"

SERIES: dict[str, dict[str, str]] = {
    "overnight": {
        "USD": "IRSTCI01USM156N", "EUR": "IRSTCI01EZM156N",
        "GBP": "IRSTCI01GBM156N", "JPY": "IRSTCI01JPM156N",
        "AUD": "IRSTCI01AUM156N", "CAD": "IRSTCI01CAM156N",
    },
    "interbank_3m": {
        "USD": "IR3TIB01USM156N", "EUR": "IR3TIB01EZM156N",
        "GBP": "IR3TIB01GBM156N", "JPY": "IR3TIB01JPM156N",
        "AUD": "IR3TIB01AUM156N", "CAD": "IR3TIB01CAM156N",
    },
}

FREDGRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv"


class MissingRatesError(RuntimeError):
    """Brak serii albo miesiąca. Nie zgadujemy — CLAUDE.md: `UNKNOWN`."""


def parse_fredgraph_csv(text: str, series_id: str) -> pl.DataFrame:
    """CSV z `fredgraph.csv` → (month: Date, value: Float64).

    Braki FRED oznacza kropką; zostają nullami, nie zerami.
    """
    df = pl.read_csv(io.StringIO(text), infer_schema_length=0)
    date_col = df.columns[0]
    if series_id not in df.columns:
        raise MissingRatesError(f"CSV nie ma kolumny {series_id}: {df.columns}")
    return df.select(
        pl.col(date_col).str.to_date("%Y-%m-%d").alias("month"),
        pl.when(pl.col(series_id) == ".").then(None)
        .otherwise(pl.col(series_id)).cast(pl.Float64).alias("value"),
    )


def fetch_current_vintage(series_id: str, dest_dir: Path = CURRENT_VINTAGE_DIR,
                          *, timeout: float = 60.0) -> tuple[Path, str]:
    """Pobierz bieżący vintage jednej serii. Zwraca (ścieżka, sha256 pliku).

    Bez klucza API — `fredgraph.csv` jest publiczny.
    """
    import requests

    r = requests.get(FREDGRAPH, params={"id": series_id}, timeout=timeout)
    r.raise_for_status()
    parse_fredgraph_csv(r.text, series_id)          # odrzuć śmieci przed zapisem
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"{series_id}.csv"
    path.write_bytes(r.content)
    return path, hashlib.sha256(r.content).hexdigest()


def load_current_vintage(kind: str, currencies: list[str], start: dt.date,
                         end: dt.date, root: Path = CURRENT_VINTAGE_DIR
                         ) -> pl.DataFrame:
    """Szeroka ramka: `month` + jedna kolumna na walutę, miesiące [start, end].

    Brak pliku, brak miesiąca albo null w zakresie → `MissingRatesError`.
    """
    frame = None
    for ccy in currencies:
        sid = SERIES[kind][ccy]
        path = root / f"{sid}.csv"
        if not path.exists():
            raise MissingRatesError(f"brak {path} — uruchom scripts/fetch_rates.py")
        s = (parse_fredgraph_csv(path.read_text(encoding="utf-8"), sid)
             .filter((pl.col("month") >= start) & (pl.col("month") <= end))
             .rename({"value": ccy}))
        frame = s if frame is None else frame.join(s, on="month", how="full",
                                                   coalesce=True)
    frame = frame.sort("month")
    expected = month_range(start, end)
    got = frame.get_column("month").to_list()
    if got != expected:
        missing = sorted(set(expected) - set(got))
        raise MissingRatesError(f"{kind}: brak miesięcy {missing[:5]}…")
    nulls = {c: frame.get_column(c).null_count() for c in currencies}
    if any(nulls.values()):
        raise MissingRatesError(f"{kind}: nulle w zakresie {nulls}")
    return frame


def month_range(start: dt.date, end: dt.date) -> list[dt.date]:
    """Pierwsze dni miesięcy od `start` do `end` włącznie."""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(dt.date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def pair_legs(symbol: str) -> tuple[str, str]:
    """`EURUSD` → (`EUR`, `USD`). Tylko sześcioznakowe pary FX."""
    if len(symbol) != 6 or not symbol.isalpha():
        raise ValueError(f"nie para FX: {symbol!r}")
    return symbol[:3], symbol[3:]


def pair_carry(rates: pl.DataFrame, symbol: str) -> np.ndarray:
    """Różnica stóp `base − quote`, w punktach procentowych, per miesiąc.

    Dodatnia = waluta bazowa wyżej oprocentowana. H04 przewiduje dodatnią
    relację z przyszłym zwrotem pary.
    """
    base, quote = pair_legs(symbol)
    return (rates.get_column(base) - rates.get_column(quote)).to_numpy()


def ar1_fit(x: np.ndarray) -> tuple[float, float]:
    """(φ, σ innowacji) z OLS `x[t] = c + φ·x[t-1] + e`."""
    if x.size < 3:
        raise ValueError("za mało punktów na AR(1)")
    a, b = x[:-1], x[1:]
    A = np.column_stack([np.ones_like(a), a])
    coef, *_ = np.linalg.lstsq(A, b, rcond=None)
    resid = b - A @ coef
    return float(coef[1]), float(resid.std(ddof=2))


# --------------------------------------------------------------------------
# Point-in-time — ALFRED
# --------------------------------------------------------------------------
#
# `alfredgraph.csv?id=X&vintage_date=D` oddaje serię w postaci, w jakiej
# istniała w dniu D — bez klucza API. Pobieramy vintage z każdego poniedziałku:
# informacja może się spóźnić o najwyżej 6 dni (kierunek ostrożny), nigdy
# nie przychodzi z przyszłości. Decyzja w dniu d widzi wyłącznie vintage
# z datą ≤ d − 1 dzień roboczy (DATA.md §4: margines na godzinę publikacji).

ALFRED_DIR = ROOT / "data" / "rates" / "alfred"
ALFREDGRAPH = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"


def parse_alfred_csv(text: str, series_id: str, vintage: dt.date) -> pl.DataFrame:
    """CSV vintage → (vintage_date, month, value). Kolumna nazywa się
    `<id>_<YYYYMMDD>`; inna data w nazwie niż zamówiona = odmowa."""
    df = pl.read_csv(io.StringIO(text), infer_schema_length=0)
    want = f"{series_id}_{vintage:%Y%m%d}"
    if want not in df.columns:
        raise MissingRatesError(f"vintage {vintage} serii {series_id}: kolumny {df.columns}")
    return df.select(
        pl.lit(vintage).alias("vintage_date"),
        pl.col(df.columns[0]).str.to_date("%Y-%m-%d").alias("month"),
        pl.when(pl.col(want).is_in([".", ""])).then(None)
        .otherwise(pl.col(want)).cast(pl.Float64).alias("value"),
    )


def pit_last_value(vintages: pl.DataFrame, decision_dates: list[dt.date],
                   margin_business_days: int = 1) -> pl.DataFrame:
    """Dla każdej daty decyzji: najnowszy miesiąc i jego wartość w ostatnim
    vintage opublikowanym co najmniej `margin_business_days` dni roboczych
    wcześniej. Brak takiego vintage → null (UNKNOWN), nie zgadywanie.

    `vintages`: (vintage_date, month, value), wiele vintage naraz.
    """
    last = (vintages.drop_nulls("value")
            .group_by("vintage_date")
            .agg(pl.col("month").max().alias("month"),
                 pl.col("value").sort_by("month").last().alias("value"))
            .sort("vintage_date"))
    cut = [np.busday_offset(np.datetime64(d, "D"), -margin_business_days,
                            roll="backward").astype(dt.date) for d in decision_dates]
    q = pl.DataFrame({"decision_date": decision_dates, "cutoff": cut}).sort("cutoff")
    return (q.join_asof(last, left_on="cutoff", right_on="vintage_date",
                        strategy="backward")
            .sort("decision_date"))
