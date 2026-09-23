# HYPOTHESES.md — rejestr hipotez

Hipotezy są **mechanizmami**, nie wskaźnikami. Wskaźnik może być reprezentacją
mechanizmu; sam z siebie hipotezą nie jest.

**Statusy:** `PROPOSED` · `PREREGISTERED` · `ACTIVE` · `EXPLORATORY` ·
`POST-HOC` · `SUPPORTED` · `NOT_SUPPORTED` · `FALSIFIED` · `SURVIVED` ·
`DEFERRED` · `CLOSED`

Historia statusów jest dopisywana, nigdy nadpisywana.

> **Ograniczenie obowiązujące cały rejestr (ADR-008).** Status `SURVIVED`
> wymaga replikacji na nietkniętej klasie aktywów. Kohorta replikacyjna nie
> została pobrana, więc w tej fazie **żadna hipoteza nie może uzyskać statusu
> `SURVIVED`**. Najwyższy osiągalny status to `SUPPORTED`.

---

## Drzewo zależności

```
[market-quant / V1a — reguła FALSIFIED; mechanizmy NIEZMIERZONE]
 │  koniunkcja mom_480>0 ∧ donch_pos_55>0,80, 172 obs. efektywne, ADR-001
 │
 ├── H01 Momentum ................................. PROPOSED · priorytet 1
 │    │                                              (T001 WITHDRAWN, ADR-011 → T003)
 │    │
 │    ├── oś: reżim zmienności (H03) ............. w protokole H01, nie osobna hipoteza
 │    ├── oś: sesja / godzina .................... w protokole H01
 │    └── oś: kierunek long / short .............. w protokole H01
 │
 ├── H02 Breakout jako STAN ....................... PROPOSED · podejrzenie redundancji z H01
 │    │
 │    └── H07 Breakout jako ZDARZENIE ............ EXPLORATORY / POST-HOC · priorytet 2
 │
 ├── H03 Reżim zmienności ......................... PROPOSED jako warunkowanie
 │                                                   (protokół zniknął z T001, ADR-011)
 ├── H04 Carry / różnica stóp ..................... PROPOSED · blokada danych
 ├── H05 Cross-asset .............................. DEFERRED · brak danych
 └── H06 Kombinacja ............................... DEFERRED · bramka wejścia
```

---

## H01 — Momentum

| Pole | Treść |
|---|---|
| **ID** | H01 |
| **Status** | `PROPOSED` (2026-09-23) — **prerejestracja T001 wycofana przed uruchomieniem, ADR-011**. Hipoteza żyje, jej protokół nie. Nowy protokół: T003 |
| **Typ** | Confirmatory |
| **Mechanizm** | **Under-reaction.** Informacja dyfunduje przez rynek stopniowo — część uczestników reaguje z opóźnieniem (ograniczenia mandatowe, rebalansowanie okresowe, kotwiczenie na cenach odniesienia). Cena dochodzi do nowej wartości w serii kroków, więc zwrot z przeszłości niesie informację o zwrocie przyszłym |
| **Predykcja** | Znormalizowany zwrot z ostatnich k barów ma **dodatnią** relację ze znormalizowanym zwrotem przez kolejne h barów |
| **Target** | A: zwrot w przód przez h, znormalizowany `atr_d1_14`. B: net R z symulacji tickowej (ADR-003) |
| **Universe** | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY |
| **Timeframe** | Sygnał H1; h ∈ {3 dni, 10 dni} |
| **Origin** | Prerejestracja projektu. Mechanizm testowany w `market-quant` **wyłącznie w koniunkcji z H02** i wyłącznie na 172 obserwacjach efektywnych |
| **Parent** | — |
| **Protokół** | **T003 (do prerejestracji)** — zastępuje wycofany T001. Warunki, które musi spełnić: ADR-011. Konstrukcja T001, zachowana w `EXPERIMENTS.md` jako zapis: siatka prerejestrowana: k ∈ {24, 120, 480} × h ∈ {3d, 10d} = 6 komórek, **wszystkie raportowane, bez wyboru najlepszej**. Kierunek = `sign(mom_k)`, bez progu. Pomiar na wszystkich barach z określoną cechą, bez warstwy portfelowej (ADR-002). Osie raportowania: para, rok, kierunek, kubełek `vol_pct_252`, sesja |
| **Kryteria falsyfikacji** | `NOT_SUPPORTED`, gdy CI95 expectancy zawiera 0 we wszystkich sześciu komórkach. `FALSIFIED`, gdy CI95 leży w całości poniżej +0,02 R we wszystkich komórkach. `SUPPORTED`, gdy CI95 > 0 w ≥1 komórce **i** kontrola losowa pobita przy p < 0,05 |
| **Obecne dowody** | Brak własnych. Zewnętrznie: `market-quant` nie wykrył efektu w koniunkcji z H02 przy mocy pozwalającej wykryć wyłącznie przewagę ≥0,10 R. **To nie jest dowód przeciwko H01** — komponent nie był mierzony osobno |
| **Powiązane triale** | T001 `WITHDRAWN` (nigdy nieuruchomiony, ADR-011) · T003 (do prerejestracji) |
| **Następny krok** | **Prerejestracja T003** spełniająca cztery warunki ADR-011. M02 zmierzył, że T001 nie miał mocy osiągnąć własnych kryteriów: wykrywalna przewaga **0,0796 R** (h=3d, próg 0,08 R) i **0,1463 R** (h=10d), a `SUPPORTED` wymagałoby expectancy > +0,056 / +0,102 R przy dryfie kosztowym −0,031 R. Niezależnie od T003: M03, M04, warstwa etykiet, dwa testy na look-ahead. Szczegóły: `reports/m02_power_audit.md` |

**Uwaga do siatki.** Mechanizm under-reaction nie wskazuje jednej skali
czasowej, więc pojedyncze k byłoby arbitralne. Trzy wartości są prerejestrowane
i raportowane w całości. Wybór najlepszej po fakcie byłby nowym eksperymentem,
nie wynikiem H01.

---

## H02 — Breakout jako stan

| Pole | Treść |
|---|---|
| **ID** | H02 |
| **Status** | `PROPOSED` — zdegradowana względem prerejestracji wyjściowej |
| **Typ** | Confirmatory |
| **Mechanizm** | Położenie ceny w górnej części niedawnego zakresu zapowiada kontynuację ruchu |
| **Predykcja** | Zwroty warunkowane wysoką pozycją w zakresie są dodatnie ponad to, co wyjaśnia samo momentum |
| **Problem — powód degradacji** | **Podejrzenie redundancji z H01.** Jeśli cena jest w górnych 20% zakresu 55 barów, `mom_480 > 0` jest niemal pewne — obie cechy mierzą prawdopodobnie ten sam stan trendowy. Redundancja nigdy nie została zmierzona. Dodatkowo: to, co `market-quant` faktycznie testował, było w dużej części właśnie tym stanem |
| **Warunek reaktywacji** | H02 dostaje własny trial **tylko wtedy**, gdy pomiar wykaże, że wnosi informację ponad H01 (kryterium ilościowe ustalone w protokole T002 przed uruchomieniem). W przeciwnym razie → `CLOSED` jako redundantna |
| **Origin** | Prerejestracja projektu |
| **Powiązane triale** | T002 (zaplanowany) — mierzy redundancję razem z H07 |
| **Następny krok** | Pomiar redundancji z H01 w T002 |

---

## H03 — Reżim zmienności

| Pole | Treść |
|---|---|
| **ID** | H03 |
| **Status** | `PROPOSED` **jako zmienna warunkująca**, nie jako sygnał — była prerejestrowana **wewnątrz** protokołu T001, więc wycofanie T001 (ADR-011) zabrało jej protokół razem z nim. Musi wrócić jako oś raportowania w prerejestracji T003 |
| **Typ** | Conditioning |
| **Mechanizm** | Skuteczność efektów kierunkowych zależy od reżimu zmienności: w reżimach spokojnych trendy utrzymują się dłużej, w reżimach wysokiej zmienności dominuje szum i skoki, a koszty rosną |
| **Predykcja** | Expectancy H01 (i H07) różni się istotnie między kubełkami `vol_pct_252` |
| **Reprezentacja** | Percentyl `atr_d1_14` w oknie rozszerzającym ≥252 dni. **Nigdy jako sygnał kierunkowy** — ATR nie ma kierunku |
| **Dlaczego nie jest osobną hipotezą** | Gdyby wprowadzić ją dopiero po negatywnym wyniku H01, byłaby ratunkiem post-hoc („momentum działa, tylko przy innej zmienności"). Dlatego jest prerejestrowana **wewnątrz** protokołu H01 i raportowana dla **wszystkich** kubełków, nie tylko dla korzystnego |
| **Kryteria falsyfikacji** | `NOT_SUPPORTED`, gdy rozrzut expectancy między kubełkami mieści się w CI pomiaru |
| **Origin** | Prerejestracja projektu; rola doprecyzowana w ADR-006 |
| **Powiązane triale** | T001 `WITHDRAWN` (była jego osią raportowania) · T003 (do prerejestracji) |

---

## H04 — Carry / różnica stóp

| Pole | Treść |
|---|---|
| **ID** | H04 |
| **Status** | `PROPOSED` — zablokowana dostępnością danych |
| **Typ** | Confirmatory |
| **Mechanizm** | **Naruszenie parytetu stóp procentowych (UIP).** Waluty o wyższej stopie nie deprecjonują się tyle, ile implikuje różnica stóp; premia jest wynagrodzeniem za ryzyko gwałtownego odwrócenia. Najmocniejszy prior ekonomiczny w całym rejestrze |
| **Predykcja** | Różnica rentowności 2-letnich ma dodatnią relację z przyszłym zwrotem pary |
| **Problem — dane** | `UNKNOWN`. Rentowności 2-letnie nie są dostępne w jednej spójnej definicji dla wszystkich walut koszyka — `market-quant` zszedł na `interbank_3m` i zawęził uniwersum (ADR-038 tamtego repo, `reports/yield2y_sources.md`). Wymaga własnej pracy nad danymi point-in-time |
| **Problem — horyzont** | Mechanizm działa na skali miesięcy, a operacyjna preferencja projektu to 2–3 dni. To napięcie trzeba rozstrzygnąć **w protokole, przed testem**, a nie tłumaczyć nim wynik po fakcie |
| **Kryteria falsyfikacji** | Do ustalenia w prerejestracji trialu |
| **Origin** | Prerejestracja projektu |
| **Następny krok** | Po T001/T002. Najpierw praca nad danymi, potem prerejestracja |

---

## H05 — Cross-asset

| Pole | Treść |
|---|---|
| **ID** | H05 |
| **Status** | `DEFERRED` |
| **Typ** | Exploratory |
| **Mechanizm** | Informacja z innych klas aktywów (akcje, stopy, surowce) wycenia się w nich wcześniej niż w kursie walutowym |
| **Problem** | Najsłabiej zdefiniowana z całej szóstki — „czy informacje pomagają" nie jest falsyfikowalne bez uszczegółowienia, który przepływ informacji i w którą stronę. Jednocześnie **najdroższa**: wymaga danych, których nie posiadamy (ADR-008) |
| **Warunek odblokowania** | Uszczegółowienie mechanizmu do konkretnej, falsyfikowalnej relacji **oraz** decyzja o pobraniu danych. Oba warunki muszą być spełnione |
| **Origin** | Prerejestracja projektu |

---

## H06 — Kombinacja

| Pole | Treść |
|---|---|
| **ID** | H06 |
| **Status** | `DEFERRED` — z jawną bramką wejścia |
| **Typ** | Confirmatory |
| **Mechanizm** | Połączenie niezależnych efektów niesie informację ponad sumę składników |
| **Bramka wejścia** | H06 wolno otworzyć **wyłącznie wtedy**, gdy co najmniej dwa komponenty mają zmierzony, niezerowy efekt własny. Zakaz jest twardy |
| **Powód bramki** | Kombinowanie słabych składników jest najpopularniejszym sposobem wyprodukowania przewagi, której nie ma: rośnie liczba stopni swobody, a każdy z nich jest okazją do dopasowania się do szumu. `market-quant` testował koniunkcję **przed** zmierzeniem komponentów i przez to nie mógł przypisać wyniku żadnemu z nich |
| **Origin** | Prerejestracja projektu |

---

## H07 — Breakout jako ZDARZENIE

| Pole | Treść |
|---|---|
| **ID** | H07 |
| **Status** | `EXPLORATORY` / `POST-HOC` (2026-09-23) |
| **Typ** | Exploratory |
| **Origin** | **Audyt `market-quant`** — reguła V1a i log decyzji runu `20260922T200750Z-b57ab5`. Powstała po zobaczeniu tamtych wyników i jest tak oznaczona |
| **Parent** | H02 (rozszczepienie), **nie** H01 |
| **Mechanizm** | Informacja, jeśli istnieje, siedzi w **przejściu** do nowego ekstremum: w momencie przełamania zakresu część uczestników jest zmuszona do reakcji (realizacja stopów, rekalibracja pozycji, wymuszone domknięcia). To jest zdarzenie o ograniczonym czasie trwania, nie stan |
| **Predykcja** | Zwroty warunkowane zdarzeniem (pierwsze zamknięcie poza zakresem N barów po okresie przebywania wewnątrz) różnią się od zwrotów warunkowanych stanem (`donch_pos > 0,80`), i to w sposób niewyjaśniony przez samo momentum |
| **Target** | Identyczny jak w H01 — porównywalność jest celem konstrukcji |
| **Uzasadnienie nowości** | `FACT`: `donch_pos_55 > 0,80` to zmienna percentylowa i odpala **z definicji na ~20% wszystkich barów**. Cokolwiek `market-quant` zmierzył, nie było wybiciem w sensie zdarzenia. Ten mechanizm nie był dotknięty przez żaden eksperyment |
| **Kryteria falsyfikacji** | `NOT_SUPPORTED`, gdy zwroty po zdarzeniu są nieodróżnialne od zwrotów w stanie po kontroli na momentum. Również `NOT_SUPPORTED`, gdy różnica istnieje, ale znika po kosztach — wtedy raportowana jako efekt bez wartości ekonomicznej |
| **Ograniczenie interpretacyjne** | Wynik H07 **nie może** być użyty jako retroaktywne potwierdzenie H02 ani H01. Hipoteza powstała po wyniku i jej dowody mają niższą wagę niż dowody z testu prerejestrowanego |
| **Powiązane triale** | T002 (zaplanowany) |
| **Następny krok** | Po T001 |

---

## Log zmian statusów

| Data | ID | Zmiana | Powód |
|---|---|---|---|
| 2026-09-23 | H01 | — → `PREREGISTERED` | Prerejestracja T001 |
| 2026-09-23 | H02 | — → `PROPOSED` (degradacja) | Podejrzenie redundancji z H01, ADR-006 |
| 2026-09-23 | H03 | — → `PREREGISTERED` jako warunkowanie | ADR-006 |
| 2026-09-23 | H04 | — → `PROPOSED` | Blokada danych |
| 2026-09-23 | H05 | — → `DEFERRED` | Brak danych + mechanizm niedookreślony, ADR-008 |
| 2026-09-23 | H06 | — → `DEFERRED` | Bramka: ≥2 komponenty z efektem |
| 2026-09-23 | H07 | — → `EXPLORATORY`/`POST-HOC` | Audyt `market-quant`, ADR-006 |
| 2026-09-23 | H01 | `PREREGISTERED` → `PROPOSED` | **ADR-011** — prerejestracja T001 wycofana przed uruchomieniem po M02. Hipoteza nietknięta, protokół wycofany |
| 2026-09-23 | H03 | `PREREGISTERED` → `PROPOSED` | **ADR-011** — była prerejestrowana wewnątrz protokołu T001, zniknęła razem z nim |
