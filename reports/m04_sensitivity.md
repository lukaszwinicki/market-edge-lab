# M04 — czułość przyrządu: trafność kierunku → expectancy

**Data:** 2026-09-23 · **ADR:** ADR-012 · **Rodzaj:** `control` — **nie liczy się do N**
**Przebieg:** `20260923T181510Z-963686` · **Licznik po M04:** N = 7, bez zmian.

---

## Werdykt

> **PRZECHODZI.** Przyrząd ma poprawne zero (M03) **i** poprawne wzmocnienie:
> odtwarza expectancy zgodną z zadaną trafnością kierunku, liniowo i z wąskim
> przedziałem. Dwa niezależne przebiegi zgadzają się co do **0,0007 R**.
>
> I daje liczbę, której brakowało od M02: **żeby efekt był opłacalny,
> wystarczy trafiać 51,7% kierunków. Żeby dało się go WYKRYĆ, trzeba trafiać
> 57,3% (h = 3 d) albo 61,9% (h = 10 d).**

---

## Dlaczego to nie jest M04 z fazy 0

Pierwotny M04 porównywał `mom_k` z `mom_k` postarzonym o jeden bar. To wymaga
policzenia cechy, czyli **oceny sygnału H01** — a H01 nie ma żywej
prerejestracji (T001 wycofany, ADR-011). Przebieg pokazałby expectancy H01,
zanim T003 zostanie zamrożony, i skaziłby jego prerejestrację nieodwracalnie.
Pełne uzasadnienie: **ADR-012**.

Tutaj kierunek pochodzi ze **znaku faktycznego zwrotu w oknie transakcji** —
z przyszłości, celowo i jawnie. To nie jest żadna cecha i nie da się z tego
wyczytać niczego o momentum. `mom_k` nie został policzony ani razu.

**Stara postać miała też wadę merytoryczną.** Sprawdzała wyłącznie, czy
przyrząd czegoś NIE widzi — a to spełnia również przyrząd zepsuty na głucho.
Brakowało **kontroli dodatniej**. M03 zmierzył zero, M04 mierzy wzmocnienie.

---

## Metoda: cała krzywa z jednego przebiegu

Dla każdego z 30 000 wylosowanych momentów odgrywamy **obie strony**. Znając
wynik strony trafnej i nietrafnej, expectancy reguły o trafności `p` wychodzi
wprost z liniowości:

    E(p) = p · E[trafna] + (1 − p) · E[nietrafna]

Nie trzeba więc symulować każdego `p` osobno. Przedziały ufności liczone są
na expectancy **warunkowej względem rzutu monetą** (`p·r_trafna +
(1−p)·r_nietrafna` na wejście), czyli bez wariancji samego rzutu — opisują
niepewność POMIARU, nie rozrzut pojedynczego przebiegu.

| | h = 3 d | h = 10 d |
|---|---|---|
| Populacja decyzji | 130 500 | 129 933 |
| Wylosowanych | 30 000 | 30 000 |
| Sparowanych (obie strony z danymi) | 29 716 | 29 655 |
| **E[trafna]** | **+0,6858 R** | **+0,6772 R** |
| **E[nietrafna]** | **−0,7347 R** | **−0,7168 R** |

---

## Krzywa czułości

| Trafność `p` | h = 3 d | CI95 | h = 10 d | CI95 |
|---|---|---|---|---|
| 0,50 | −0,0245 | [−0,0328; −0,0153] | −0,0198 | [−0,0335; −0,0059] |
| 0,52 | +0,0039 | [−0,0049; +0,0137] | +0,0081 | [−0,0066; +0,0228] |
| 0,55 | +0,0466 | [+0,0368; +0,0572] | +0,0499 | [+0,0339; +0,0661] |
| 0,60 | +0,1176 | [+0,1063; +0,1300] | +0,1196 | [+0,1012; +0,1381] |
| 0,70 | +0,2596 | [+0,2448; +0,2756] | +0,2590 | [+0,2354; +0,2827] |
| 0,85 | +0,4727 | [+0,4523; +0,4943] | +0,4681 | [+0,4363; +0,5003] |
| 1,00 | +0,6858 | [+0,6595; +0,7131] | +0,6772 | [+0,6368; +0,7176] |

**Sprawdzenie krzyżowe z M03 — `FACT`.** Przy `p = 0,50` kierunek jest
bez informacji, więc M04 musi odtworzyć wynik M03:

| | M04 (`p` = 0,50) | M03 | Różnica |
|---|---|---|---|
| h = 3 d | −0,0245 R | −0,0248 R | **+0,0003 R** |
| h = 10 d | −0,0198 R | −0,0191 R | **−0,0007 R** |

To są **dwa niezależne przebiegi**: inne ziarna, inna struktura losowania
(M03 losował kierunek monetą, M04 odgrywa obie strony), inna ścieżka kodu
(M03 ma własną pętlę, M04 idzie przez `src/research/entries.py`). Zgodność
do 0,0007 R jest najmocniejszym sprawdzeniem aparatury, jakie mamy po M01.

---

## Wynik główny: dwa progi, które dzieli czynnik 4–8 — `FACT` + `INFERENCE`

| | h = 3 d | h = 10 d |
|---|---|---|
| **Próg opłacalności** (E = 0) | **51,72%** | **51,42%** |
| **Próg wykrywalności** (E = MDE z M02) | **57,33%** | **61,91%** |
| Przewaga nad rzutem monetą: opłacalna | 1,72 pp | 1,42 pp |
| Przewaga nad rzutem monetą: wykrywalna | 7,33 pp | 11,91 pp |
| **Iloraz** | **4,3×** | **8,4×** |

`INFERENCE`. **Eksperyment widzi tylko efekty od czterech do ośmiu razy
większe od najmniejszego, który byłby opłacalny.** Między 51,7% a 57,3%
trafności (h = 3 d) leży pas, w którym strategia **naprawdę zarabia**,
a pomiar tego nie pokaże — zwróci `NOT_SUPPORTED`.

To jest ta sama martwa strefa, którą M02 policzył w R (0,064–0,185 R), ale
wyrażona w jednostce, o której da się mieć zdanie. „0,08 R" nie mówi intuicji
nic. „Trzeba trafiać 57% kierunków przez trzy dni" mówi wszystko — i pozwala
zapytać wprost, czy taki efekt jest w ogóle wiarygodny dla płynnych par FX.

**M04 tej odpowiedzi nie udziela i nie ma prawa.** Ocena, jaka trafność jest
prawdopodobna dla mechanizmu under-reaction, jest założeniem ekonomicznym
i należy do prerejestracji T003, gdzie musi paść **przed** uruchomieniem.

---

## Drugi wynik: bariery prawie nie działają — `FACT`

Przy **doskonałej** znajomości kierunku 84% pozycji (h = 3 d) i 83%
(h = 10 d) i tak kończy na **barierze czasowej**. TP pada w 10%, SL w 5%.

Powód jest w liczbach:

| | Średni \|ruch\| w oknie | SL | TP | Ruch jako % dystansu do TP |
|---|---|---|---|---|
| h = 3 d | 0,891 × `atr_d1_14` | 1,1 | 2,2 | **40%** |
| h = 10 d | 1,598 × `atr_d1_14` | 2,0 | 4,0 | **40%** |

Typowy ruch nie sięga nawet dystansu do **stopu**, nie mówiąc o TP. Bariery
są ustawione tak szeroko, że w praktyce nie wiążą — transakcja sprowadza się
do „trzymaj h dni i wyjdź po rynku".

`INFERENCE`. Konstrukcja triple-barrier jest tu w dużej mierze **dekoracją**:
dokłada ryzyko luki, pesymistyczne rozstrzyganie i złożoność, a rozstrzyga
16% przypadków. Jednocześnie tłumaczy, dlaczego σ zmierzona w M02 (0,92 R)
jest bliska rozrzutowi samego zwrotu przeskalowanego przez `sl_mult` —
bariery obcinają niewiele.

**Sufit przy doskonałej wyroczni** to +0,686 R (h = 3 d), przy ruchu wartym
0,810 R bez barier — geometria zamienia więc **85%** ruchu na wynik. Straty
na samej geometrii nie ma; problem jest w tym, że bariery nie robią tego,
po co je wprowadzono.

To jest wejście do warunku 2 i kierunku „zmiana geometrii" dla T003:
albo zacieśnić bariery do miejsca, w którym wiążą, albo z nich zrezygnować
na rzecz jawnego wyjścia czasowego i nie udawać, że się je ma. **Każdy
z tych wariantów zmienia σ i wymaga nowego pomiaru mocy.**

---

## Czego M04 NIE zrobił

* **Nie policzył `mom_k`** ani żadnej cechy. Żadna próba nie została
  zapalona, N = 7 bez zmian.
* **Nie rozstrzygnął, czy w pipelinie jest przesunięcie o jeden bar.**
  Odpowiada za to zestaw testów na danych syntetycznych, gdzie poprawna
  odpowiedź jest znana z konstrukcji: `test_grid.py` (cena odniesienia
  i cena wyjścia), `test_volatility.py` (granica dobowa ATR),
  `test_simulator.py` (okno transakcji, trzy testy przywrócone w M03)
  i **`test_entries.py::test_edge_is_recovered_only_when_it_lies_inside_the_trade_window`**
  — złożenie całej ścieżki na zasianym ruchu ceny o znanej porze.
* **Nie porównał cechy prawdziwej z jej opóźnieniem.** To ramię przechodzi
  do wnętrza T003 jako prerejestrowane (ADR-012, warunek 5).
* **Nie doliczał swapu.** Krzywa jest w kosztach, które symulator
  implementuje. Marża swapu (M03: 0,0124 R przy h = 3 d, 0,0223 R przy
  h = 10 d) przesuwa oba progi w górę — o ile dokładnie, policzy T003
  z wpiętym członem kosztu.

---

## Co M04 dołożył do aparatury

| Moduł | Stan |
|---|---|
| `src/research/entries.py` | **nowy** — jedyna droga od siatki do wyniku w R; kierunek przychodzi z zewnątrz, moduł nie wie skąd |
| `tests/test_entries.py` | **nowy** — 9 testów, w tym złożenie siatka → symulator na zasianym ruchu ceny |
| `scripts/m04_sensitivity.py` | **nowy** — krzywa czułości przez `start_run(kind="control")` |

Testy po M04: **264**.
