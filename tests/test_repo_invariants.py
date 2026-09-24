"""Niezmienniki repozytorium — czy notatki zgadzają się z dyskiem.

CLAUDE.md: *„Każdą liczbę w notatkach sprawdzać komendą — notatki starzeją
się szybciej niż dysk."* To była instrukcja dla człowieka, wykonywana wtedy,
gdy ktoś pamiętał. Tutaj jest wykonywana przy każdym `pytest`.

Rozjazd dokumentu z dyskiem nie objawia się błędem. Objawia się tym, że
następna sesja czyta `PROGRESS.md`, bierze z niego liczbę i buduje na niej
decyzję — a liczba jest sprzed trzech commitów. Cały projekt stoi na tym, że
`DECISIONS.md` i `HYPOTHESES.md` są źródłem prawdy; test poniżej sprawdza, że
nadal nim są.

Testy celowo dotykają PLIKÓW WERSJONOWANYCH, nie katalogu `runs/` — ten jest
w `.gitignore`, więc na świeżym klonie nie istnieje, a niezmiennik ma trzymać
także tam.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("PROGRESS.md", "EXPERIMENTS.md", "HYPOTHESES.md", "DECISIONS.md",
        "DATA.md", "README.md")


def doc(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def all_docs() -> dict[str, str]:
    return {n: doc(n) for n in DOCS}


def _section_around(text: str, pos: int) -> str:
    """Sekcja `##`, w której leży dana pozycja — przypisanie do `market-quant`
    bywa w nagłówku albo w pierwszym akapicie, nie tuż obok identyfikatora."""
    start = text.rfind("\n## ", 0, pos)
    end = text.find("\n## ", pos)
    return text[max(start, 0):end if end != -1 else len(text)]


def trials() -> list[dict]:
    p = ROOT / "trials" / "trials.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


# --------------------------------------------------------------------------
# Licznik prób
# --------------------------------------------------------------------------

def test_documented_trial_count_matches_the_register():
    """N jest liczbą, od której zależy poprzeczka DSR (ADR-004, ADR-017).
    Rozjazd między dokumentem a rejestrem zaniża ją albo zawyża po cichu."""
    sys.path.insert(0, str(ROOT))
    from src.harness.registry import n_trials
    live = n_trials(ROOT / "trials" / "trials.jsonl")
    for name in ("PROGRESS.md", "EXPERIMENTS.md"):
        found = {int(m) for m in re.findall(r"N = (\d+)\b", doc(name))}
        assert found, f"{name} nie podaje N w ogóle"
        assert live in found, f"{name} podaje N={found}, rejestr mówi {live}"


def test_inherited_count_in_config_matches_adr_004():
    cfg = yaml.safe_load((ROOT / "configs" / "base.yaml").read_text(encoding="utf-8"))
    assert cfg["meta"]["inherited_trials"] == 7
    assert "ADR-004" in doc("DECISIONS.md")


def test_the_register_carries_the_inherited_count_as_data():
    """ADR-004: liczba ma być widoczna w danych, nie tylko w konfiguracji."""
    assert any(r.get("kind") == "inherited_count" and r.get("n_inherited") == 7
               for r in trials())


# --------------------------------------------------------------------------
# Przebiegi
# --------------------------------------------------------------------------

def test_every_started_run_has_an_end_entry():
    """Przebieg bez `end` to przebieg, który zniknął w połowie — a rejestr
    ma pokazywać także te, które się wywróciły."""
    starts = {r["run_id"] for r in trials() if r.get("event") == "start"}
    ends = {r["run_id"] for r in trials() if r.get("event") == "end"}
    assert starts - ends == set()


def test_every_run_id_quoted_in_docs_exists_or_is_attributed_elsewhere():
    """Cytowany identyfikator musi dać się sprawdzić. Jeżeli pochodzi
    z `market-quant`, musi to być napisane obok — inaczej czytelnik uzna go
    za nasz i nie znajdzie go w rejestrze."""
    known = {r["run_id"] for r in trials() if r.get("event") == "start"}
    for name, text in all_docs().items():
        for m in re.finditer(r"\b20\d{6}T\d{6}Z-[0-9a-f]{6}\b", text):
            rid = m.group(0)
            if rid in known:
                continue
            context = _section_around(text, m.start())
            assert "market-quant" in context, (
                f"{name}: run_id {rid} nie jest w rejestrze i nie jest "
                "przypisany do market-quant")


def test_no_run_directory_is_referenced_that_the_register_does_not_know():
    """`runs/` jest w .gitignore, więc rejestr — nie katalog — jest źródłem."""
    known = {r["run_id"] for r in trials() if r.get("event") == "start"}
    for d in (ROOT / "runs").glob("*"):
        if d.is_dir():
            assert d.name in known, f"katalog {d.name} bez wpisu w rejestrze"


# --------------------------------------------------------------------------
# Prerejestracja T003
# --------------------------------------------------------------------------

def test_the_preregistration_hash_quoted_in_docs_matches_the_file():
    """Hash jest po to, żeby dało się sprawdzić, a nie żeby w niego wierzyć."""
    actual = hashlib.sha256(
        (ROOT / "configs" / "t003_momentum.yaml").read_bytes()).hexdigest()
    quoted = set()
    for text in all_docs().values():
        quoted |= set(re.findall(r"\b([0-9a-f]{8,64})…?", text))
    prefixes = {q for q in quoted if actual.startswith(q)}
    assert prefixes, "żaden dokument nie cytuje hasha prerejestracji"
    for text in all_docs().values():
        for m in re.findall(r"sha256[ =]+`?([0-9a-f]{8,64})", text):
            if len(m) >= 8 and m[:8] == actual[:8]:
                assert actual.startswith(m), "cytowany hash rozjeżdża się z plikiem"


def test_the_runner_and_the_docs_agree_on_the_preregistration_hash():
    sys.path.insert(0, str(ROOT / "scripts"))
    from t003_momentum import PREREG, PREREG_SHA256
    assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA256
    assert PREREG_SHA256 in doc("EXPERIMENTS.md")


# --------------------------------------------------------------------------
# ADR
# --------------------------------------------------------------------------

def test_adr_numbering_is_contiguous_and_unique():
    nums = [int(n) for n in re.findall(r"^## ADR-(\d+)", doc("DECISIONS.md"), re.M)]
    assert nums == sorted(nums), "ADR-y nie są w kolejności"
    assert len(nums) == len(set(nums)), "zduplikowany numer ADR"
    assert nums == list(range(1, len(nums) + 1)), f"dziura w numeracji: {nums}"


def test_every_adr_referenced_anywhere_actually_exists():
    """Odwołanie do nieistniejącego ADR-u jest gorsze niż jego brak —
    wygląda jak uzasadnienie."""
    defined = {int(n) for n in re.findall(r"^## ADR-(\d+)", doc("DECISIONS.md"), re.M)}
    texts = dict(all_docs())
    for p in list((ROOT / "src").rglob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        texts[str(p)] = p.read_text(encoding="utf-8")
    for name, text in texts.items():
        for n in {int(x) for x in re.findall(r"ADR-(\d{3})", text)}:
            if n in defined:
                continue
            if name.endswith(".py") and "PRZENIESIONE z market-quant" in text:
                continue          # te odwołania dotyczą logu TAMTEGO projektu
            # Numer spoza naszego zakresu wolno cytować tylko z przypisaniem.
            near = " ".join(_section_around(text, m.start())
                            for m in re.finditer(rf"ADR-{n:03d}", text))
            attributed = any(w in near for w in
                             ("market-quant", "tamtego repo", "poprzednik"))
            assert attributed, (
                f"{name}: odwołanie do nieistniejącego ADR-{n:03d} bez przypisania")


def test_adr_entries_keep_the_required_fields():
    """Każdy wpis: data · decyzja · powód · alternatywy · konsekwencje."""
    body = doc("DECISIONS.md")
    blocks = re.split(r"^## ADR-\d+", body, flags=re.M)[1:]
    for i, b in enumerate(blocks, start=1):
        assert "**Status:**" in b, f"ADR-{i:03d} bez statusu i daty"
        assert "**Decyzja" in b, f"ADR-{i:03d} bez pola Decyzja"
        # Nagłówek DECISIONS.md wymienia „powód", ale ADR-010 uzasadnia przez
        # Kontekst + Dowód + Wniosek. Wpisy ADR są NIEZMIENNE, więc to test
        # dopasowuje się do nich, a nie odwrotnie — sprawdzamy, że
        # uzasadnienie JEST, nie jak zostało nazwane.
        assert any(w in b for w in ("Powód", "Kontekst", "Dowód", "Wniosek")), \
            f"ADR-{i:03d} bez jakiegokolwiek uzasadnienia"


# --------------------------------------------------------------------------
# Spójność indeksów i plików
# --------------------------------------------------------------------------

def test_every_report_referenced_in_docs_exists_on_disk():
    for name, text in all_docs().items():
        for rel in set(re.findall(r"(?<!market-quant:)`?\b(reports/[\w./-]+\.md)`?", text)):
            assert (ROOT / rel).exists(), f"{name} odsyła do nieistniejącego {rel}"


def test_every_config_referenced_in_docs_exists_on_disk():
    for name, text in all_docs().items():
        for rel in set(re.findall(r"`(configs/[\w./-]+\.ya?ml)`", text)):
            assert (ROOT / rel).exists(), f"{name} odsyła do nieistniejącego {rel}"


def test_every_source_file_referenced_in_docs_exists_on_disk():
    for name, text in all_docs().items():
        for rel in set(re.findall(r"`(src/[\w./-]+\.py|scripts/[\w./-]+\.py|tests/[\w./-]+\.py)`", text)):
            assert (ROOT / rel).exists(), f"{name} odsyła do nieistniejącego {rel}"


def test_experiments_index_lists_every_control_step_that_has_runs():
    """Każdy krok serii M, który cokolwiek uruchomił, musi być w indeksie."""
    purposes = " ".join(r.get("purpose", "") for r in trials() if r.get("event") == "start")
    index = doc("EXPERIMENTS.md").split("## M01")[0]
    for step in sorted(set(re.findall(r"\b(M0\d)\b", purposes))):
        assert f"| {step} |" in index, f"{step} ma przebiegi, ale nie ma wiersza w indeksie"


def test_hypothesis_status_log_uses_declared_statuses_only():
    text = doc("HYPOTHESES.md")
    declared = set(re.findall(r"`([A-Z][A-Z_-]+)`", text.split("Historia statusów")[0]))
    log = text.split("## Log zmian statusów")[1]
    used = set(re.findall(r"`([A-Z][A-Z_-]+)`", log))
    assert used <= declared, f"statusy spoza listy: {used - declared}"


# --------------------------------------------------------------------------
# Liczba testów
# --------------------------------------------------------------------------

def test_documented_test_count_matches_the_suite():
    """`PROGRESS.md` podaje liczbę testów. Jeżeli ma ją podawać, ma się
    zgadzać — inaczej jest ozdobą, która z każdym commitem kłamie bardziej."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(ROOT / "tests")],
        capture_output=True, text=True, cwd=ROOT)
    m = re.search(r"(\d+) tests? collected", out.stdout)
    if not m:
        pytest.skip("nie udało się zebrać testów podprocesem")
    collected = int(m.group(1))
    documented = {int(x) for x in re.findall(r"Testy: \*?\*?(\d+)", doc("PROGRESS.md"))}
    assert documented, "PROGRESS.md nie podaje liczby testów"
    assert collected in documented, (
        f"PROGRESS.md mówi {documented}, zebrano {collected}")
