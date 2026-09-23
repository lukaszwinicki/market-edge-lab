# PROGRESS.md — bieżący stan

Log stanu: co zrobiono, gdzie jesteśmy, co dalej, co blokuje.
**Nie jest źródłem prawdy** — w razie sprzeczności wygrywa `DECISIONS.md`.

Ten plik ma zostać krótki (do ~120 linii), żeby dało się go przeczytać
w całości na starcie sesji. Historia zamknięta idzie do archiwum, nie tutaj.

Każdą liczbę sprawdzać komendą, nie brać na wiarę.

---

## Faza 0 — ZAMKNIĘTA (2026-09-23)

Audyt poprzednika, architektura, rejestr hipotez, prerejestracja pierwszego
eksperymentu. **Żaden backtest nie został uruchomiony** — zgodnie z zasadą, że
faza 0 kończy się na prerejestracji.

### Co ustalił audyt `market-quant`

Tamten projekt zamknął się 2026-09-22 odrzuceniem swojej hipotezy i zrobił to
uczciwie: bramki kalibracyjne przeszły, więc wynikowi można wierzyć. **Ale
zakres tego wniosku jest węższy, niż wyglądał** (ADR-001):

| `FACT` | Liczba |
|---|---|
| Sygnał wystąpił na barach | 64 342 (28,7% z 224 420 decyzji) |
| Weszło w transakcję | 889 (1,4% sygnałów) |
| Obserwacji efektywnych | **172** (nakładanie 95,9%) |
| Połowa CI expectancy | 0,067 R |
| Wykrywalna przewaga | wyłącznie ≥0,10 R |

Resztę wyciął silnik ryzyka i portfela: limity ekspozycji walutowej (39 729
barów), otwarta pozycja na parze (10 815), limit portfela (8 854). O tym, który
sygnał stanie się transakcją, decydowała **historia poprzednich transakcji**,
a nie treść hipotezy.

`INFERENCE`: sfalsyfikowano **regułę handlową wraz z warstwą zarządzania
kapitałem**, a nie mechanizmy momentum ani wybicia. Bramka 3, która miała
zmierzyć komponenty osobno, nigdy nie została uruchomiona. A to, co nazwano
wybiciem, odpalało z definicji na ~20% barów — czyli było stanem, nie
zdarzeniem.

### Decyzje założycielskie

ADR-001…009 w `DECISIONS.md`. Najważniejsza: **ADR-002** — pomiar informacji
oddzielony od symulacji strategii, wymuszony architekturą (brak `src/risk/`
w fazie 1).

### Rejestr hipotez

H01 `PREREGISTERED` · H02 `PROPOSED` (zdegradowana, podejrzenie redundancji) ·
H03 `PREREGISTERED` jako warunkowanie · H04 `PROPOSED` (blokada danych) ·
H05 `DEFERRED` · H06 `DEFERRED` · H07 `EXPLORATORY/POST-HOC` (nowa, z audytu).

Świadomie **nie** dodano więcej hipotez — audyt dał ustalenia metodologiczne,
nie nowe mechanizmy (ADR-006).

---

## M01 — ZAMKNIĘTY, PRZECHODZI (2026-09-23)

Aparatura przeniesiona, zweryfikowana i uruchomiona. Świece zbudowane.
**Żaden backtest nadal nie został uruchomiony.**

**Weryfikacja przeniesienia — najważniejszy wynik M01 (`FACT`).** Te same
ticki przez przeniesiony pipeline dają ramki **identyczne co do bitu**
z tymi, które wyprodukował `market-quant` (EURUSD 2015: M1 372 942 bary,
H1 6 226). To mocniejszy dowód niż komplet przechodzących testów — port
niczego nie zmienił, ani w dekoderze, ani w resamplingu.

| Element | Stan |
|---|---|
| Przeniesiono | 11 modułów, ~2 350 linii — `data`, `execution/simulator`, `harness`, statystyka |
| Testy | **173 przechodzą**: 149 przeniesionych + 24 własne na nasze zmiany |
| Świece | 2015–2023, 6 par, 108 partycji, 433 MB |
| Raport jakości | `reports/data_quality.md` — **PRZECHODZI**, luki 0,01–0,02% na parę |
| Odcisk danych | `sha256 = 6b6b3aa4…`, 336 561 plików — `UNKNOWN` z `DATA.md` domknięty |
| Pieczęć 2024–2026 | Działa w loaderze + strażnik w skrypcie budowy |

**Co M01 wykrył, czego poprzednik nie mógł.** Raport zgłosił najpierw
`NIE PRZECHODZI`: godzina `2023-12-24 22:00` bez ticków u wszystkich sześciu
par. Leży w segmencie OOS, którego `market-quant` nigdy nie zbudował.
Dowód z rozmiarów plików cache pokazał zamknięcie rynku, nie awarię feedu —
Wigilia wypadła w niedzielę, ten sam wzorzec co odziedziczona godzina z 2017 r.
Zaakceptowana jawnie, z dowodem, bez osłabiania detektora: **ADR-010**.

Trzy godziny odziedziczone po `market-quant` zostały potwierdzone naszym
własnym przebiegiem — detektor wskazał dokładnie je i żadnej innej.

**Dług zaciągnięty świadomie.** Warstwa etykiet (`triple_barrier.py`) niesie
treść hipotezy i nie została przeniesiona. Razem z nią odpadły **dwa testy
na brak podglądania przyszłości przez symulator**. Ślad imienny jest
w `tests/test_harness.py`. **Muszą wrócić przed T001** — to warunek, nie
drobiazg.

---

## Gdzie jesteśmy

**Faza 1 w toku.** M01 zamknięty. Następny krok: M02.

**Licznik prób: N = 7** (odziedziczone, ADR-004). Uruchomionych prób
strategii w tym projekcie: **0**. M01 był krokiem infrastrukturalnym
i nie liczy się do N.

---

## Następne kroki — w tej kolejności

| # | Krok | Rozstrzyga |
|---|---|---|
| ~~1~~ | ~~**M01** — przeniesienie aparatury, świece, testy, raport jakości~~ | **ZAMKNIĘTY, PRZECHODZI** |
| 2 | **M02** — audyt mocy | **Czy T001 ma w ogóle sens.** Bramka: przy wykrywalnej przewadze ≥0,08 R T001 nie startuje |
| 3 | **M03** — kalibracja kontrolą losową | Czy wynikowi negatywnemu będzie można wierzyć |
| 4 | **M04** — domknięcie kontroli przesuniętych cech | Otwarte `UNKNOWN` po poprzedniku |
| 5 | **T001** — H01 momentum, pomiar na wszystkich barach | Pytanie, na które `market-quant` nie miał mocy odpowiedzieć |

Kroki M są kontrolami aparatury i **nie liczą się** do N w DSR.

**Przed T001 trzeba dodatkowo:** zbudować warstwę etykiet od nowa (bez
treści hipotezy w module) i przywrócić dwa testy na brak look-ahead.

---

## Blokery i znane ograniczenia

| Sprawa | Stan |
|---|---|
| **Kohorta replikacyjna nie istnieje** | Zero bajtów dla XAUUSD, WTI, S&P 500, DAX. Replikacja niemożliwa → **żadna hipoteza nie osiągnie `SURVIVED`** w tej fazie (ADR-008). Najwyższy status: `SUPPORTED` |
| **Segment RESEARCH był oglądany** | 7 prób poprzednika na tych samych danych. Poprzeczka DSR startuje podwyższona (ADR-004) |
| **Moc pozostanie ograniczona** | Wąskim gardłem jest nakładanie okien, nie liczba wierszy. Szacunek: n_eff ~450 przy h=10d, ~1500 przy h=3d. Do zmierzenia w M02 |
| **Rentowności 2-letnie** `UNKNOWN` | Brak spójnej definicji dla wszystkich walut. Blokuje H04 |
| **Marża swapu** `UNKNOWN` | Jedyna liczba w modelu kosztów bez sparsowanego źródła → obowiązkowa oś wrażliwości zamiast wartości punktowej |
| **Kontrola przesuniętych cech** `UNKNOWN` | U poprzednika dała wynik lepszy od baseline. Wyjaśnione szumem przy ich mocy; do domknięcia w M04 |
| **Hash zbioru ticków** `UNKNOWN` | Do policzenia w M01. Bez niego nie wykryjemy podmiany danych pod przebiegiem |
| Zależność od ścieżki do ticków | Projekt nie jest samowystarczalny na poziomie danych źródłowych (ADR-007) |

---

## Czego NIE robimy

- Nie uruchamiamy backtestu przed M01–M04.
- Nie dodajemy ML — dopóki nie wiadomo, czy istnieje prosty efekt.
- Nie mnożymy hipotez, żeby uniknąć wyniku negatywnego.
- Nie otwieramy segmentu 2024–2026.
- Nie dotykamy `market-quant`.
