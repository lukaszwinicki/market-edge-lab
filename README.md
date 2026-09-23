# market-edge-lab

Laboratorium badawcze do ustalenia, czy w danych rynkowych istnieją **mierzalne,
stabilne efekty predykcyjne** — i jak mocne są dowody na ich istnienie.

To nie jest bot tradingowy ani platforma. Produktem jest **liczba z przedziałem
ufności i decyzja badawcza**, nie działający system.

> Wynik „nie znaleziono przewagi, oto z jaką mocą to zmierzyliśmy" jest
> sukcesem projektu. Wynik „mamy ładny wykres equity" nie jest.

---

## Skąd się wziął ten projekt

Poprzednik, `market-quant`, był aparaturą do rozstrzygnięcia jednej hipotezy:
czy istnieje prosta reguła swingowa na sześciu głównych parach FX o dodatnim
expectancy po kosztach. Zakończył się 2026-09-22 **odrzuceniem tej hipotezy**
(ADR-049 tamtego repo) i zrobił to uczciwie — bramki kalibracyjne przeszły,
więc wynikowi można wierzyć.

Audyt tamtego projektu (patrz `DECISIONS.md` ADR-001) pokazał jednak, że
**zakres tego wniosku jest węższy, niż wyglądał**:

| Ustalenie | Liczba |
|---|---|
| Barów, na których sygnał wystąpił | 64 342 (28,7% decyzji) |
| Barów, które weszły w transakcję | 889 (1,4% sygnałów) |
| Obserwacji naprawdę niezależnych | **172** |
| Połowa przedziału ufności | 0,067 R |

Resztę wyciął silnik ryzyka i portfela — limity ekspozycji walutowej, limit
portfela, zasada „jedna pozycja na parę". Zmierzono więc **regułę razem z jej
warstwą zarządzania kapitałem**, a nie zawartość informacyjną sygnału. Przy
takiej mocy dało się wykryć wyłącznie przewagę ≥ 0,10 R.

Do tego reguła była koniunkcją dwóch warunków, których nigdy nie zmierzono
osobno, a to, co nazwano „wybiciem", odpalało z definicji na ~20% wszystkich
barów — czyli było stanem trwałym, nie zdarzeniem.

**Dlatego ten projekt istnieje** i dlatego jego centralną poprawką jest
oddzielenie pomiaru informacji od symulacji strategii (ADR-002).

---

## Zasady

1. Hipotezy są **mechanizmami**, nie listą wskaźników.
2. Każdą hipotezę próbujemy **obalić**, nie uratować.
3. Kontrola losowa jest benchmarkiem numer jeden.
4. Ticki są źródłem prawdy o wykonaniu zleceń.
5. Nie używamy informacji z przyszłości. Nigdy.
6. Odkrycie po fakcie dostaje nowe ID i etykietę `POST-HOC`.
7. Koszty, swap i poślizg są częścią hipotezy ekonomicznej, nie dodatkiem.
8. Wynik w R po kosztach znaczy więcej niż saldo konta.
9. `SURVIVED` nie znaczy `PRODUCTION READY`.
10. Liczy się jakość dowodu, nie liczba strategii.

Pełny zestaw reguł: `CLAUDE.md`.

---

## Stan

**Faza 0 zamknięta** — audyt poprzednika, architektura, rejestr hipotez,
prerejestracja pierwszego eksperymentu.

**Żaden backtest nie został uruchomiony.** Licznik prób: 7 (odziedziczone).

Co dalej i co blokuje: `PROGRESS.md`.

---

## Struktura

```
CLAUDE.md          konstytucja projektu
PROGRESS.md        bieżący stan
HYPOTHESES.md      rejestr hipotez + drzewo zależności
DECISIONS.md       ADR — decyzje metodologiczne, wpisy niezmienne
EXPERIMENTS.md     indeks trialów
DATA.md            dane, ograniczenia, checklista leakage'u
trials/            trials.jsonl, append-only
```

Katalogi `src/`, `tests/`, `configs/`, `runs/` powstają wtedy, gdy są potrzebne.

## Uruchamianie

Nic jeszcze nie ma do uruchomienia. Faza 1 zaczyna się od przeniesienia
i **ponownej weryfikacji** aparatury pomiarowej z `market-quant` — przeniesiony
kod nie dziedziczy zaufania (ADR-005).
