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
 ├── H01 Momentum ........................... NOT_SUPPORTED (T003)
 │    │                                        gorne ograniczenie 51,03% trafnosci
 │    │
 │    ├── oś: reżim zmienności (H03) ............. w protokole H01, nie osobna hipoteza
 │    ├── oś: sesja / godzina .................... w protokole H01
 │    └── oś: kierunek long / short .............. w protokole H01
 │
 ├── H02 Breakout jako STAN ....................... PROPOSED · podejrzenie redundancji z H01
 │    │
 │    └── H07 Breakout jako ZDARZENIE ............ EXPLORATORY / POST-HOC · priorytet 2
 │
 ├── H03 Reżim zmienności .................... PREREGISTERED jako warunkowanie
 │                                            (oś raportowania w T003)
 ├── H04 Carry / różnica stóp ..................... PROPOSED · blokada danych
 ├── H05 Cross-asset .............................. DEFERRED · brak danych
 └── H06 Kombinacja ............................... DEFERRED · bramka wejścia
```

---

## H01 — Momentum

| Pole | Treść |
|---|---|
| **ID** | H01 |
| **Status** | **`NOT_SUPPORTED`** (2026-09-24) — T003 zamknięty. Relacja nieodróżnialna od zera we wszystkich 3 komórkach; **górne ograniczenie 51,03%** trafności, czyli 0,69 pp **poniżej** progu opłacalności |
| **Typ** | Confirmatory |
| **Mechanizm** | **Under-reaction.** Informacja dyfunduje przez rynek stopniowo — część uczestników reaguje z opóźnieniem (ograniczenia mandatowe, rebalansowanie okresowe, kotwiczenie na cenach odniesienia). Cena dochodzi do nowej wartości w serii kroków, więc zwrot z przeszłości niesie informację o zwrocie przyszłym |
| **Predykcja** | Znormalizowany zwrot z ostatnich k barów ma **dodatnią** relację ze znormalizowanym zwrotem przez kolejne h barów |
| **Target** | A: zwrot w przód przez h, znormalizowany `atr_d1_14`. B: net R z symulacji tickowej (ADR-003) |
| **Universe** | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY |
| **Timeframe** | Sygnał H1; **h = 3 dni**. h = 10 d usunięty przez ADR-015 — zdominowany na koszcie (M03) i na mocy (M02, M05) |
| **Origin** | Prerejestracja projektu. Mechanizm testowany w `market-quant` **wyłącznie w koniunkcji z H02** i wyłącznie na 172 obserwacjach efektywnych |
| **Parent** | — |
| **Protokół** | **T003, ZAMROŻONY** 2026-09-24 — `configs/t003_momentum.yaml`, `sha256 c832dcdc…`. Siatka: k ∈ {24, 120, 480} × h = 3 d = **3 komórki**, wszystkie raportowane, bez wyboru najlepszej. Falsyfikacja stoi na **warstwie A** (ADR-015): Spearman `mom_k` ↔ `fwd_atr`, pooled po parach. Warstwa B (net R, kierunek `sign(mom_k)` bez progu) raportowana jako wycena, nie jako test. Pomiar na wszystkich barach z określoną cechą, bez warstwy portfelowej (ADR-002). Osie: para, rok, kierunek, kubełek `vol_pct_252`, sesja |
| **Kryteria falsyfikacji** | Na warstwie A, próg opłacalności 51,72% trafności = `ρ 0,05401` (M04). `SUPPORTED`: CI > 0 w ≥1 komórce po korekcie Holma **i** kontrola permutacyjna pobita p < 0,05. `FALSIFIED`: CI95 w całości wewnątrz ±0,05401 we **wszystkich** komórkach (intersection-union, bez korekty). `NOT_SUPPORTED`: każdy inny wynik — raport **musi** podać górne ograniczenie na efekt. Osiągalność zmierzona w M05, nie założona |
| **Obecne dowody** | **Własne, T003**: Spearman(`mom_k`, `fwd_atr`) = +0,0070 / −0,0328 / −0,0315 dla k = 24/120/480, CI95 zawiera zero w każdej komórce. Mechanizm **nie został obalony**, ale **dodatnia relacja o wartości ekonomicznej została wykluczona**: górny koniec najszerszego CI to 51,03% trafności przy progu opłacalności 51,72%. Kontrola cech postarzonych przeszła. Zewnętrznie: `market-quant` nie mierzył tego komponentu osobno |
| **Powiązane triale** | T001 `WITHDRAWN` (nigdy nieuruchomiony, ADR-011) · **T003 `CLOSED`** (`20260924T150658Z-8daa11`, N: 7 → 10) |
| **Następny krok** | **Żaden na H01 w tej fazie.** Mechanizm pozostaje niewykluczony, ale jego dodatnia postać jest nieopłacalna przy tej mocy, a powtórzenie na tym samym segmencie nie dołoży informacji. Ewentualny powrót wymaga albo nowego segmentu, albo instrumentów spoza czynnika USD (ADR-018 — nie kohorty replikacyjnej) |

**Uwaga do siatki.** Mechanizm under-reaction nie wskazuje jednej skali
czasowej, więc pojedyncze k byłoby arbitralne. Trzy wartości są prerejestrowane
i raportowane w całości. Wybór najlepszej po fakcie byłby nowym eksperymentem,
nie wynikiem H01.

**Uwaga do mocy.** Trzy komórki mają **różną** moc: n_eff spada z 5 150
(k = 24) do 1 902 (k = 480), bo dłuższe okno cechy to silniejsza
autokorelacja. Martwa strefa rośnie odpowiednio z −0,28 pp do +0,64 pp.
Komórka k = 480 jest najsłabsza i to ona wyznacza, co T003 potrafi wykluczyć.

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
| **Status** | `PREREGISTERED` (2026-09-24) **jako zmienna warunkująca**, nie jako sygnał — wróciła jako oś raportowania w zamrożonej prerejestracji T003 (`reporting.axes`), po tym jak wycofanie T001 (ADR-011) zabrało jej protokół razem z nim |
| **Typ** | Conditioning |
| **Mechanizm** | Skuteczność efektów kierunkowych zależy od reżimu zmienności: w reżimach spokojnych trendy utrzymują się dłużej, w reżimach wysokiej zmienności dominuje szum i skoki, a koszty rosną |
| **Predykcja** | Expectancy H01 (i H07) różni się istotnie między kubełkami `vol_pct_252` |
| **Reprezentacja** | Percentyl `atr_d1_14` w oknie rozszerzającym ≥252 dni. **Nigdy jako sygnał kierunkowy** — ATR nie ma kierunku |
| **Dlaczego nie jest osobną hipotezą** | Gdyby wprowadzić ją dopiero po negatywnym wyniku H01, byłaby ratunkiem post-hoc („momentum działa, tylko przy innej zmienności"). Dlatego jest prerejestrowana **wewnątrz** protokołu H01 i raportowana dla **wszystkich** kubełków, nie tylko dla korzystnego |
| **Kryteria falsyfikacji** | `NOT_SUPPORTED`, gdy rozrzut expectancy między kubełkami mieści się w CI pomiaru |
| **Origin** | Prerejestracja projektu; rola doprecyzowana w ADR-006 |
| **Powiązane triale** | T001 `WITHDRAWN` (była jego osią raportowania) · **T003 `PREREGISTERED`** (oś `vol_regime`) |

---

## H04 — Carry / różnica stóp

| Pole | Treść |
|---|---|
| **ID** | H04 |
| **Status** | `PROPOSED` — zablokowana dostępnością danych |
| **Typ** | Confirmatory |
| **Mechanizm** | **Naruszenie parytetu stóp procentowych (UIP).** Waluty o wyższej stopie nie deprecjonują się tyle, ile implikuje różnica stóp; premia jest wynagrodzeniem za ryzyko gwałtownego odwrócenia. Najmocniejszy prior ekonomiczny w całym rejestrze |
| **Predykcja** | Różnica rentowności 2-letnich ma dodatnią relację z przyszłym zwrotem pary |
| **Problem — dane** | `UNKNOWN`. Rentowności 2-letnie nie są dostępne w jednej spójnej definicji dla wszystkich walut koszyka — `market-quant` zszedł na `interbank_3m` i zawęził uniwersum (ADR-038 **tamtego repo**, `market-quant:reports/yield2y_sources.md` — ścieżka w `market-quant`, nie u nas). Wymaga własnej pracy nad danymi point-in-time |
| **Problem — horyzont** | Mechanizm działa na skali miesięcy, a operacyjna preferencja projektu to 2–3 dni. To napięcie trzeba rozstrzygnąć **w protokole, przed testem**, a nie tłumaczyć nim wynik po fakcie |
| **Kryteria falsyfikacji** | Do ustalenia w prerejestracji trialu |
| **Origin** | Prerejestracja projektu |
| **Następny krok** | Po T003/T002 (T001 `WITHDRAWN`, ADR-011). Najpierw praca nad danymi point-in-time, potem prerejestracja |

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
| 2026-09-24 | H01 | `PROPOSED` → `PREREGISTERED` | **T003 zamrożony** (`configs/t003_momentum.yaml`, `sha256 c832dcdc…`). Sześć warunków ADR-011 spełnione: ADR-014 (P_eff, geometria), ADR-015 (falsyfikacja na warstwie A, siatka 3 komórki), M05 (n_eff zmierzone, `FALSIFIED` osiągalne) |
| 2026-09-24 | H03 | `PROPOSED` → `PREREGISTERED` | Wróciła jako oś raportowania `vol_regime` w zamrożonej prerejestracji T003. Nadal warunkowanie, nie sygnał |
| 2026-09-24 | H01 | `PREREGISTERED` → `NOT_SUPPORTED` | **T003 zamknięty** (`20260924T150658Z-8daa11`, N: 7 → 10). CI95 zawiera zero we wszystkich 3 komórkach. Nie `FALSIFIED`, bo dolny koniec CI przy k = 120 i 480 wychodzi poza pasmo progu opłacalności — blokuje to niewykluczona relacja **ujemna**, nie dodatnia |
