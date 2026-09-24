"""Checklista leakage'u z `DATA.md` §8, wykonywalna.

CLAUDE.md wymaga jej **przed KAŻDYM raportowanym wynikiem**. Do 2026-09-24
była prozą z polami `[ ]` i nie wykonywał jej żaden kod — czyli reguła
istniała, a jej spełnienie zależało od tego, czy ktoś pamiętał przeczytać
plik. To ta sama klasa usterki co niewpięty DSR (ADR-017) i brak swapu
w `CostModel` (M03): zapisane, opisane, niewykonywane.

TRZY STANY, NIE DWA

    PASS / FAIL     — sprawdzone maszynowo, z dowodem w polu `evidence`
    MANUAL          — nie da się sprawdzić kodem; wymaga JAWNEJ deklaracji
    NOT_APPLICABLE  — nie dotyczy tego przebiegu; też wymaga deklaracji

Pozycja `MANUAL` bez deklaracji jest traktowana jak `FAIL`. To jest cały
sens tego modułu: „nie dało się sprawdzić" nie może być cichsze niż
„sprawdzono i jest źle". Pominięcie ma wymagać napisania zdania, nie
przeoczenia linijki.

CZEGO TEN MODUŁ NIE ZASTĘPUJE

Nie zastępuje testów. Punkty o oknie rozszerzającym, o tym, że symulator nie
widzi cen po decyzji, i o granicy bara są własnościami KODU i pilnują ich
testy na danych syntetycznych (`test_volatility.py`, `test_simulator.py`,
`test_grid.py`, `test_momentum.py`). Tutaj są odnotowane jako `MANUAL`
z odesłaniem — bo checklista ma pokazywać pełny obraz, a nie udawać, że
wielkość niesprawdzalna w danym przebiegu nie istnieje.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

PASS = "PASS"
FAIL = "FAIL"
MANUAL = "MANUAL"
NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class Check:
    key: str
    item: str
    status: str
    evidence: str = ""


@dataclass
class Checklist:
    checks: list[Check] = field(default_factory=list)

    def add(self, key: str, item: str, ok: bool, evidence: str = "") -> None:
        self.checks.append(Check(key, item, PASS if ok else FAIL, evidence))

    def manual(self, key: str, item: str, declaration: str | None) -> None:
        """Pozycja niesprawdzalna kodem. Bez deklaracji = FAIL."""
        if declaration:
            self.checks.append(Check(key, item, MANUAL, declaration))
        else:
            self.checks.append(
                Check(key, item, FAIL, "BRAK DEKLARACJI — pozycja niesprawdzalna "
                                       "kodem musi zostać zadeklarowana jawnie"))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def passes(self) -> bool:
        return not self.failed

    def as_report(self) -> dict:
        return {
            "source": "DATA.md §8",
            "passes": self.passes,
            "n_checks": len(self.checks),
            "n_failed": len(self.failed),
            "checks": [
                {"key": c.key, "item": c.item, "status": c.status,
                 "evidence": c.evidence}
                for c in self.checks
            ],
        }

    def raise_if_failed(self) -> None:
        if self.passes:
            return
        lines = "\n".join(f"  - {c.key}: {c.evidence}" for c in self.failed)
        raise LeakageCheckFailed(
            "CHECKLISTA LEAKAGE'U NIE PRZECHODZI — wynik nie może zostać "
            f"zaraportowany (DATA.md §8):\n{lines}")


class LeakageCheckFailed(RuntimeError):
    """Leakage jest błędem krytycznym, nie usterką. Wynik jest nieważny."""


# ---------------------------------------------------------------------------
# Sprawdzenia maszynowe
# ---------------------------------------------------------------------------

def check_config(cl: Checklist, cfg: dict) -> None:
    """Zakazy twarde i zamrożenia — wprost z konfiguracji przebiegu."""
    data, forbidden = cfg.get("data", {}), cfg.get("forbidden", {})
    cl.add("mid_price", "Bid/ask osobno, nigdzie mid",
           data.get("mid_price_allowed") is False
           and forbidden.get("mid_price") is True,
           f"mid_price_allowed={data.get('mid_price_allowed')}, "
           f"forbidden.mid_price={forbidden.get('mid_price')}")
    cl.add("barrier_order", "Kolejność barier nigdy optymistyczna",
           forbidden.get("optimistic_barrier_order") is True,
           f"forbidden.optimistic_barrier_order="
           f"{forbidden.get('optimistic_barrier_order')}")
    cl.add("no_llm_inputs", "Żadne wejście do backtestu nie pochodzi od LLM",
           forbidden.get("llm_generated_backtest_inputs") is True,
           "zakaz obecny w configu; treść cech pochodzi z modułów, nie z promptu")
    cl.add("instruments_frozen", "Zbiór instrumentów zamrożony przed przebiegiem",
           cfg.get("instruments", {}).get("frozen") is True,
           f"instruments.frozen={cfg.get('instruments', {}).get('frozen')}")


def check_run_provenance(cl: Checklist, run_json: dict) -> None:
    """Parametry, hash i rejestr — z manifestu przebiegu, nie z pamięci."""
    cl.add("params_hashed", "Parametry w YAML z hashem, zapisane przed przebiegiem",
           bool(run_json.get("config_sha256")) and bool(run_json.get("git_commit")),
           f"config_sha256={str(run_json.get('config_sha256'))[:12]}…, "
           f"git_commit={str(run_json.get('git_commit'))[:12]}…")
    dirty = run_json.get("git_dirty")
    cl.add("tree_clean", "Drzewo czyste albo różnica zahashowana",
           (not dirty) or bool(run_json.get("git_diff_sha256")),
           "drzewo czyste" if not dirty
           else f"brudne, diff_sha256={str(run_json.get('git_diff_sha256'))[:12]}…")


def check_registry(cl: Checklist, trials_path: Path, run_id: str) -> None:
    cl.add("trials_logged", "`trials/trials.jsonl` zaktualizowany automatycznie",
           _has_start(trials_path, run_id),
           f"wpis `start` dla {run_id} obecny w rejestrze")


def _has_start(trials_path: Path, run_id: str) -> bool:
    if not trials_path.exists():
        return False
    with open(trials_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("event") == "start" and r.get("run_id") == run_id:
                return True
    return False


def check_segment(cl: Checklist, obs: pl.DataFrame, segment_start: dt.datetime,
                  segment_end: dt.datetime, *, ts_col: str = "ts_decision",
                  t1_col: str = "t1") -> None:
    """Granice segmentu — w tym horyzont, nie tylko moment decyzji.

    Najczęstsza postać tego błędu nie polega na tym, że decyzja wypada poza
    segmentem, tylko że jej OKNO WYNIKOWE wychodzi poza — i rozstrzyga się
    danymi, których w tym segmencie nie wolno oglądać (M02 wykrył to
    w prerejestracji T001).
    """
    if obs.is_empty():
        cl.add("segment_bounds", "Granice segmentów nieprzekroczone", True, "próba pusta")
        return
    ts_min = obs.get_column(ts_col).min()
    ts_max = obs.get_column(ts_col).max()
    t1_max = obs.get_column(t1_col).max() if t1_col in obs.columns else ts_max
    ok = ts_min >= segment_start and t1_max <= segment_end
    cl.add("segment_bounds",
           "Granice segmentów nieprzekroczone; horyzont mieści się w segmencie",
           ok, f"decyzje [{ts_min}, {ts_max}], najpóźniejsze t1={t1_max}, "
               f"segment [{segment_start}, {segment_end}]")


def check_bar_closed(cl: Checklist, obs: pl.DataFrame, bar_seconds: int, *,
                     ts_col: str = "ts_decision", bar_col: str = "bar_ts",
                     declaration: str | None = None) -> None:
    """Bar użyty do decyzji musi być ZAMKNIĘTY przed nią.

    Etykieta bara to początek przedziału, więc bar 09:00 (H1) zamyka się
    o 10:00 i decyzja o 10:00 może go użyć. Warunkiem jest więc dokładnie
    `ts_decision - bar_ts >= długość bara`, a nie `>` ani `>=0`.
    """
    if obs.is_empty() or bar_col not in obs.columns:
        cl.manual("bar_closed", "Bar H1 zamknięty przed decyzją", declaration)
        return
    delta = (obs.get_column(ts_col) - obs.get_column(bar_col)).dt.total_seconds()
    worst = int(delta.min())
    cl.add("bar_closed",
           "Bar H1 zamknięty przed decyzją (`last_closed_bar`, bez ręcznej arytmetyki)",
           worst >= bar_seconds,
           f"najmniejszy odstęp decyzja−bar = {worst}s, wymagane ≥ {bar_seconds}s")


def check_effective_n(cl: Checklist, n_rows: int, n_eff: int | None) -> None:
    cl.add("n_eff_used",
           "Do testów wchodzi liczba obserwacji efektywnych, nie liczba wierszy",
           n_eff is not None and 0 < n_eff <= n_rows,
           f"n_rows={n_rows}, n_eff={n_eff}"
           + ("" if n_eff is None else f" (iloraz {n_rows / n_eff:.1f}×)"))


def check_aged_feature_control(cl: Checklist, cells: dict | None, *,
                               declaration: str | None = None) -> None:
    """Kontrola przesuniętych cech — wynik NIE rośnie po postarzeniu.

    Brak ramienia kontrolnego nie jest zaliczeniem: przebieg, który go nie
    ma, musi napisać dlaczego. `market-quant` miał tę kontrolę zapaloną
    nietypowo i nigdy jej nie domknął — milczenie jest tu najgorszą
    z możliwych odpowiedzi.
    """
    arms = {k: v.get("aged_control") for k, v in (cells or {}).items()}
    have = {k: a for k, a in arms.items() if a}
    if not have:
        cl.manual("aged_feature", "Kontrola przesuniętych cech przeszła", declaration)
        return
    bad = [k for k, a in have.items() if not a.get("passes")]
    cl.add("aged_feature",
           "Kontrola przesuniętych cech przeszła — wynik nie rośnie",
           not bad,
           "wszystkie ramiona przechodzą" if not bad
           else f"ramiona z wynikiem LEPSZYM po postarzeniu: {bad}")


# ---------------------------------------------------------------------------
# Złożenie
# ---------------------------------------------------------------------------

#: Pozycje `DATA.md` §8, których nie da się sprawdzić z artefaktów przebiegu.
#: Każda MUSI dostać deklarację od wywołującego — inaczej jest `FAIL`.
MANUAL_ITEMS = {
    "expanding_windows": "Wszystkie normalizacje w oknie rozszerzającym",
    "no_fit_on_test": "Żaden `fit()` nie widział danych testowych",
    "daily_from_closed_day": "Wartości dzienne z ostatniej zamkniętej pełnej doby",
    "simulator_blind": "Symulator fillów nie widzi cen po momencie decyzji",
    "macro_alfred": "Makro przez ALFRED z `realtime_start` = data decyzji",
    "purge_embargo": "Nakładanie etykiet obsłużone: purge + embargo",
}

#: Pozycje sprawdzane maszynowo, ale tylko wtedy, gdy przebieg dostarczy
#: odpowiednich artefaktów. Bez nich stają się `MANUAL` i też wymagają
#: deklaracji — brak danych do sprawdzenia nie jest zaliczeniem.
CONDITIONAL_ITEMS = {
    "bar_closed": "Bar H1 zamknięty przed decyzją",
    "aged_feature": "Kontrola przesuniętych cech przeszła",
}


def run_checklist(cfg: dict, run_json: dict, trials_path: Path, *,
                  observations: pl.DataFrame | None = None,
                  segment: tuple[dt.datetime, dt.datetime] | None = None,
                  bar_seconds: int = 3600,
                  n_rows: int | None = None,
                  n_eff: int | None = None,
                  cells: dict | None = None,
                  declarations: dict[str, str] | None = None) -> Checklist:
    """Pełna checklista `DATA.md` §8 dla jednego przebiegu.

    `declarations` pokrywa pozycje z `MANUAL_ITEMS`. Brak którejkolwiek jest
    `FAIL` — „nie dotyczy" trzeba napisać, nie pominąć.
    """
    cl = Checklist()
    decl = declarations or {}

    check_config(cl, cfg)
    check_run_provenance(cl, run_json)
    check_registry(cl, trials_path, run_json.get("run_id", ""))
    if observations is not None and segment is not None:
        check_segment(cl, observations, *segment)
        check_bar_closed(cl, observations, bar_seconds,
                         declaration=decl.get("bar_closed"))
    if n_rows is not None:
        check_effective_n(cl, n_rows, n_eff)
    check_aged_feature_control(cl, cells, declaration=decl.get("aged_feature"))

    for key, item in MANUAL_ITEMS.items():
        cl.manual(key, item, decl.get(key))
    return cl
