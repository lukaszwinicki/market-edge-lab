# EXPERIMENTS.md — indeks eksperymentów

Ten plik jest **indeksem**. Szczegóły każdego przebiegu żyją w `runs/<id>/`,
a maszynowy zapis w `trials/trials.jsonl`.

**Seria M** = sprawdzenia aparatury (kontrole). Nie liczą się do N w DSR.
**Seria T** = triale hipotez. Każdy sprawdzony wariant liczy się do N.

**Licznik prób: N = 7** (odziedziczone, ADR-004). Uruchomionych w tym
projekcie: **0**.

---

## Indeks

| ID | Hipoteza | Status | Wynik | Decyzja |
|---|---|---|---|---|
| M01 | — | `CLOSED` | **PRZECHODZI** — port identyczny co do bitu, 173 testy, raport jakości zdany | KEEP |
| M02 | — | `CLOSED` | **NIEROZSTRZYGNIĘTE** — h=10d bramkę przekracza, h=3d siada na progu (0,0796 vs 0,08) | ADR-011: T001 wycofany |
| M03 | — | `CLOSED` | **PRZECHODZI** — expectancy losowych wejść = −koszt w granicach 1 SE; symulator nie zna swapu | KEEP |
| M04 | — | `BLOCKED` | — | ADR-012: nie może ruszyć przed zamrożeniem prerejestracji T003 |
| T001 | H01 | `WITHDRAWN` | **nieuruchomiony** — konstrukcja bez mocy na osiągnięcie własnych kryteriów (M02) | ADR-011 |
| T002 | H02, H07 | `PLANNED` | — | — |
| T003 | H01 | `PLANNED` | — | zastępuje T001, 6 warunków: ADR-011 + ADR-012 |

---

## M01 — Przeniesienie i weryfikacja aparatury · `CLOSED` · **PRZECHODZI**

**Cel.** Przenieść kod pomiarowy z `market-quant` (ADR-005), zbudować świece
M1/H1 dla segmentów RESEARCH i OOS, uruchomić pełen zestaw testów w tym
repozytorium, wygenerować własny raport jakości danych.

**Kryterium.** Wszystkie testy przechodzą; luki ≤ 0,05% barów H1 na parę;
loader rzuca wyjątkiem przy próbie sięgnięcia do segmentu zapieczętowanego.

**Dlaczego pierwsze.** Przeniesiony kod nie dziedziczy zaufania. Bez działającej
aparatury każdy dalszy wynik jest bezwartościowy.

### Wynik (2026-09-23)

| Kryterium | Wynik |
|---|---|
| Testy przechodzą | ✅ **173** — 149 przeniesionych + 24 własne |
| Luki ≤ 0,05% na parę | ✅ 0,01–0,02% (4–9 barów z 56 100) |
| Pieczęć działa | ✅ loader + strażnik w skrypcie budowy |
| Raport jakości | ✅ **PRZECHODZI** |

**Weryfikacja ponad kryterium.** Te same ticki przez przeniesiony pipeline
dają ramki **identyczne co do bitu** z oryginałem (EURUSD 2015, M1 i H1,
wszystkie 12 kolumn). Port niczego nie zmienił.

**Zbudowano:** 2015–2023, 6 par, 108 partycji, 433 MB.
**Odcisk danych:** `sha256 = 6b6b3aa4…a63a0`, 336 561 niepustych plików.

### Co wyszło po drodze

Raport zgłosił najpierw `NIE PRZECHODZI` — jedna nierozstrzygnięta godzina
bez ticków u wszystkich par: `2023-12-24 22:00`, w segmencie OOS, którego
`market-quant` nigdy nie zbudował. Dowód z rozmiarów plików cache pokazał
zamknięcie rynku (Wigilia w niedzielę), nie awarię feedu. Zaakceptowana
jawnie z dowodem, detektor nietknięty → **ADR-010**.

Trzy godziny odziedziczone po poprzedniku potwierdzone naszym przebiegiem:
detektor wskazał dokładnie je i żadnej innej.

### Dług — SPŁACONY w M03 (2026-09-23)

Warstwa etykiet nie została przeniesiona (niesie treść hipotezy), a razem
z nią odpadły **dwa testy na brak podglądania przyszłości przez symulator**:
`test_simulator_sees_only_the_trade_window` i
`test_windowed_labels_match_simulation_on_full_history`.

**Opis długu był pomyłkowy.** Oryginały szpiegowały, jaką ramkę podaje
symulatorowi `triple_barrier.py`, ale sama własność należy do symulatora —
`simulate_trade` tnie okno samodzielnie (`simulator.py:146`). Oba testy
wróciły w M03 do `tests/test_simulator.py`, bez warstwy etykiet i w wersji
obserwowalnej (psucie cen poza oknem), plus trzeci na domknięcie okna od
strony przeszłości. Warstwa etykiet pozostaje do zbudowania dla T003, ale
**nie blokuje już testów na look-ahead**.

**Decyzja: KEEP.** Aparatura działa i jest zweryfikowana. Przechodzimy do M02.

---

## M02 — Audyt mocy (ADR-009) · `CLOSED` · **NIEROZSTRZYGNIĘTE**

**Cel.** Zmierzyć, ile obserwacji naprawdę niezależnych daje się uzyskać przy
horyzoncie 3 i 10 dni, i jaka z tego wynika najmniejsza wykrywalna przewaga.

**Kryterium — bramka dla T001.** Jeśli najmniejsza wykrywalna przewaga wynosi
**≥ 0,08 R przy obu horyzontach, T001 nie startuje**. Konstrukcję trzeba
przeprojektować i zapisać to nowym ADR.

**Dlaczego przed T001.** Uruchomienie eksperymentu, o którym z góry wiadomo, że
nie wykryje interesującego efektu, spala próbę w liczniku DSR za zero
informacji. Szacunki przed pomiarem: n_eff ~450 przy h=10d, ~1500 przy h=3d.
To są **szacunki, nie pomiary**.

### Wynik (2026-09-23) · `20260923T172201Z-fa3731` · pełny raport: `reports/m02_power_audit.md`

Konwencja mocy przyjęta w M02, bo ADR-009 jej nie podaje: α = 0,05 dwustronnie,
**moc 80%**, MDE = 2,8016·σ/√n_eff. Odtwarza liczby odziedziczone (n_eff 172,
σ 0,455 → 0,097 R wobec raportowanego „≥0,10 R").

| h | n_eff w czasie (6 par) | P_eff | n_eff łącznie | σ w R | **MDE** |
|---|---|---|---|---|---|
| 3 d | 3 126 | 2,00 | 1 040 | 0,9165 | **0,0796** |
| 10 d | 936 | 2,02 | 315 | 0,9261 | **0,1463** |

**Werdykt: NIEROZSTRZYGNIĘTE.** h=10d przekracza bramkę przy każdym założeniu
(0,085–0,146 R). h=3d siada na progu — różnica 0,0004 R przy błędzie pomiaru
±0,0018 R. Bramka ADR-009 wymaga przekroczenia przy OBU horyzontach, więc
wszystko zależy od h=3d, a ten zależy od modelu niezależności par:
**[2,0; 6,0]** to nawias ciasny matematycznie, ale wybór punktu w nim jest
decyzją, nie pomiarem. → wymaga nowego ADR przed T001.

### Trzy ustalenia, których nie było w planie

1. **σ była dziedziczona, nie mierzona** — i jest 2× za mała. Tabela ADR-009
   implikuje σ = 0,455 R (przeskalowana połowa CI `market-quant` przez √n).
   Zmierzone: **0,92 R** przy obu horyzontach. n_eff ADR-009 zgadł nieźle,
   rozrzut pomylił dwukrotnie.
2. **Przy h=10d T001 miałby mniejszą moc niż `market-quant`** — 0,146 R wobec
   0,097 R, mimo 1,8× większego n_eff. Usunięcie warstwy portfelowej (ADR-002)
   odblokowało próbę i zarazem pełny rozrzut wyniku.
3. **Sesja nie kupuje mocy.** Wariant „wszystkie godziny" dokłada +72% wierszy
   i **zero** obserwacji niezależnych (3 126 → 3 126). Oba warianty zostają
   prerejestrowane, ale jako pytanie o realizm, nie o moc — w bilansie
   porównań wielokrotnych druga sesja wyłącznie kosztuje.

### Wynik ostrzejszy od samej bramki

**Kryteria falsyfikacji T001 są w większości nieosiągalne.** Zestawienie
zmierzonej połowy CI z prerejestrowanymi progami (`FALSIFIED` < +0,02 R,
`SUPPORTED` > 0) daje martwą strefę, w której zapada `NOT_SUPPORTED`:

| h | Połowa CI (konserw.) | `FALSIFIED` wymaga | `SUPPORTED` wymaga | Martwa strefa |
|---|---|---|---|---|
| 3 d | 0,0557 | średnia < −0,036 R | średnia > +0,056 R | 0,091 R |
| 10 d | 0,1024 | średnia < −0,082 R | średnia > +0,102 R | 0,185 R |

Dryf kosztowy to −0,031 R (h=3d), więc umiarkowany realny efekt wyląduje
w martwej strefie niemal na pewno. Przy h=10d `SUPPORTED` wymagałoby
expectancy **> +0,10 R netto** — progu, którego `market-quant` nie przekroczył
i który uznano tam za zbyt wysoki. `INFERENCE`: najprawdopodobniejszym wynikiem
T001 w obecnej konstrukcji jest `NOT_SUPPORTED` **niezależnie od tego, czy
efekt istnieje** — kosztem 6 prób (N: 7 → 13).

### Luka w prerejestracji T001, wykryta po drodze

„Decyzje do 2021-12-31" nie rozstrzyga, co z oknami wychodzącymi poza segment:
przy h=10d decyzja z 28.12.2021 rozstrzyga się w styczniu 2022, czyli w OOS.
M02 przyjął wariant nietykający OOS (−98 decyzji na parę, 0,45% próby, bez
wpływu na n_eff). **T001 musi to zadeklarować jawnie przed uruchomieniem** —
po zobaczeniu wyniku będzie to parametr swobodny.

### Czego M02 nie zrobił

Nie liczył `mom_k` — wyłącznie sprawdzał, czy cecha jest **określona**. Żadna
próba nie została zapalona, N = 7 bez zmian. Dryf kosztowy (−0,031 R przy h=3d,
−0,0098 R przy h=10d) **nie jest kontrolą losową** — M03 pozostaje konieczne.
Dług warstwy etykiet i dwóch testów na look-ahead jest niezmieniony.

---

## M03 — Kalibracja przyrządu kontrolą losową · `CLOSED` · **PRZECHODZI**

**Cel.** Odpowiednik bramek 0 i 1 poprzednika: losowe wejścia przy identycznej
mechanice muszą dać expectancy ≈ −koszt, a strata musi być istotna.

**Kryterium.** Expectancy losowych wejść mieści się w przedziale wokół
modelowanego kosztu; CI95 leży pod zerem; wynik ujemny przy koszcie 1×, 2×, 3×.

**Dlaczego konieczne.** Bez tego wynik negatywny niczego nie dowodzi — nie da
się odróżnić „nie ma przewagi" od „przyrząd nie potrafi jej pokazać". To jest
element, który sprawił, że wynikowi `market-quant` można wierzyć.

### Wynik (2026-09-23) · `20260923T175353Z-087adf` · raport: `reports/m03_random_control.md`

200 replikacji × 500 wejść × 2 horyzonty = **197 847 transakcji**. Losowany
moment **i** kierunek, niezależnie od siebie.

| | h = 3 d | h = 10 d |
|---|---|---|
| Expectancy | **−0,0248 R** (t = −4,90) | **−0,0191 R** (t = −2,41) |
| CI95 | [−0,0347; −0,0147] | [−0,0347; −0,0035] |
| Koszt modelowany | 0,0297 R | 0,0169 R |
| Luka | +0,0049 R (**0,97 SE**) | −0,0022 R (**0,28 SE**) |
| CI95 < 0 przy 1×/2×/3× | ✅ | ✅ |

**PRZECHODZI.** Expectancy zgadza się z kosztem w granicach jednego błędu
standardowego. Przyrząd nie produkuje przewagi tam, gdzie jej nie ma.

### Wynik, którego nie było w planie: symulator nie zna swapu

`CostModel` implementuje spread, podłogę i poślizg. **Swapu nie ma wcale**,
choć prerejestracja T001 deklarowała oś marży, a config trzyma
`costs.swap.margin_sensitivity`, której nic nie czytało.

| Marża roczna | h = 3 d | h = 10 d |
|---|---|---|
| 1,0% | 0,0124 R (0,42× koszt modelowany) | **0,0223 R (1,32×)** |
| 2,0% | 0,0249 R (0,84×) | 0,0446 R (**2,64×**) |

Przy h = 10 d brakujący człon jest **większy niż cały modelowany koszt** —
i większy niż próg +0,02 R, wobec którego T001 miał być oceniany.

`INFERENCE`: **przewaga kosztowa długiego horyzontu jest artefaktem pominięcia
swapu.** Stosunek kosztu h=3d/h=10d wynosi 1,76× dla kosztu modelowanego
(zgodnie z szacunkiem ADR-009: 1,9×), ale **1,08×** po doliczeniu
finansowania. Skoro cena za transakcję wyrównuje się, zostaje różnica w mocy —
trzykrotna na korzyść h = 3 d (M02: n_eff 1 040 wobec 315). Przy pełnym
koszcie **h = 3 d dominuje h = 10 d na obu osiach**. Przesłanka do T003,
nie decyzja.

### Diagnostyka warta zapamiętania

**Co trzeci–czwarty przebieg bez informacji wychodzi na plus.** Expectancy
pojedynczego przebiegu 500 transakcji ma odchylenie 0,041 R; ujemnych jest
75% (h=3d) i 67% (h=10d). To jest rozkład, względem którego T003 musi się
wykazać.

**Pułapka `effective_sample_size`.** Policzone na ramce ze wszystkimi parami
naraz dało 521 i 156 — tyle, ile M02 zmierzył dla JEDNEJ pary. Zachłanne
szukanie rozłącznych okien działa na jednej osi czasu; wymiar przekrojowy
trzeba domnożyć osobno. Użycie wprost zaniża n_eff dwukrotnie.

### Czego M03 nie zrobił

Nie jest kontrolą dopasowaną liczbą obserwacji do przebiegu strategii — taka
należy do przebiegu, z którym się porównuje, a porównywać nie ma z czym.
Nie liczył żadnej cechy. Nie wpiął swapu w symulator: to zadanie T003
i wymaga powtórzenia kalibracji.

**Dług M01 spłacony** — trzy testy na brak podglądania przyszłości wróciły do
`tests/test_simulator.py`, bez warstwy etykiet. Opis długu był pomyłkowy:
własność należy do symulatora, nie do `triple_barrier.py`.

---

## M04 — Domknięcie kontroli przesuniętych cech · `BLOCKED` (ADR-012)

> **Postać z fazy 0 nie może wystartować.** Porównanie baseline z cechą
> postarzoną wymaga policzenia `mom_k`, czyli **oceny sygnału H01**. To (a)
> klasyfikuje przebieg jako `strategy` i dolicza go do N, (b) pokazuje
> expectancy H01, zanim T003 zostanie prerejestrowany — a prerejestracja
> pisana po zobaczeniu wyniku nie jest prerejestracją.
>
> W planie z fazy 0 kolejność była bezpieczna, bo T001 był już zamrożony.
> **Wycofanie T001 (ADR-011) usunęło tę ochronę.**
>
> **Nowa postać (ADR-012):** cechy syntetyczne o znanej zawartości
> informacyjnej — szum, wyrocznia, wyrocznia postarzona. Nie dotyka `mom_k`,
> zostaje `control`, może ruszyć od zaraz. Porównanie na cesze prawdziwej
> przenosi się do T003 jako prerejestrowane ramię kontrolne.

**Cel (postać z fazy 0, zachowany jako zapis).** Sprawdzić przy pełnej mocy,
czy cechy postarzone o jeden bar dają wynik **gorszy** niż baseline, jak
powinny.

**Kontekst.** W `market-quant` ta kontrola dała wynik **lepszy** (−0,0268 vs
−0,0560 R). Tamto wyjaśnienie — szum przy połowie CI 0,067 R — było poprawne
w tamtych warunkach. Przy większej mocy to jest otwarte `UNKNOWN`, a wzrost
wyniku po podaniu cech z przyszłości jest kanonicznym objawem błędu off-by-one.

**Kryterium.** Wynik z cechami przesuniętymi **nie rośnie**. Wzrost → STOP
i audyt wyrównania znaczników czasu przed jakimkolwiek eksperymentem.

---

## T001 — H01 Momentum, pomiar na wszystkich barach · `WITHDRAWN`

**Status:** `WITHDRAWN` (2026-09-23, **ADR-011**) · **nigdy nieuruchomiony**
· **N bez zmian** — rejestr liczy wpisy `start`, a takiego nie było

**Dlaczego wycofana.** M02 zmierzył, że ta konstrukcja nie ma mocy osiągnąć
własnych kryteriów falsyfikacji. Przy h=10d MDE wynosi 0,085–0,146 R — bramki
ADR-009 nie przechodzi przy **żadnym** modelu niezależności par, a `SUPPORTED`
wymagałoby expectancy powyżej +0,10 R netto. Między progiem `FALSIFIED`
a progiem `SUPPORTED` leży martwa strefa szerokości 0,064–0,185 R, w której
zapada `NOT_SUPPORTED`. Najprawdopodobniejszym wynikiem było więc
`NOT_SUPPORTED` niezależnie od tego, czy efekt istnieje — kosztem 6 prób.

**Wycofanie było dopuszczalne**, bo M02 nie zaobserwował niczego, co dotyczy
H01: nie liczył `mom_k` ani jego znaku, tylko czy cecha jest określona. Gdyby
obejrzał cokolwiek zależnego od treści hipotezy, wycofanie prerejestracji
byłoby wyborem kryterium pod wynik. Patrz ADR-011, sekcja o zabezpieczeniu.

**Zastąpiona przez:** T003, którego prerejestracja musi spełnić cztery warunki
z ADR-011.

Prerejestracja poniżej zostaje **w niezmienionej postaci**, jako zapis tego,
co było zadeklarowane. Nie jest edytowana.

### Prerejestracja (wycofana, niezmieniona)

| Pole | Wartość |
|---|---|
| Mechanizm | Under-reaction — informacja dyfunduje stopniowo |
| Universe | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY |
| Okres | Rozgrzewka 2015; **decyzje 2016-01-01 → 2021-12-31** |
| Cecha | `mom_k = (close − close[−k]) / (atr_h1_14 × √k)`, k ∈ {24, 120, 480} barów |
| Horyzont | h ∈ {3 dni robocze, 10 dni roboczych} |
| Siatka | 3 × 2 = **6 komórek, wszystkie raportowane** |
| Kierunek | `sign(mom_k)`, bez progu. Próg jest parametrem swobodnym i nie wchodzi do pierwszego testu |
| Target A | Zwrot w przód przez h, znormalizowany `atr_d1_14` |
| Target B | Net R z symulacji tickowej. SL/TP skalowane `σ√T`: h=10d → 2,0/4,0 × `atr_d1_14`; h=3d → 1,1/2,2 × `atr_d1_14` |
| Próbka | **Wszystkie bary z określoną cechą.** Zero filtrów portfelowych (ADR-002) |
| Execution | Symulator tickowy: bid/ask osobno, kolejność barier tickowo lub pesymistycznie, luki po cenie otwarcia |
| Koszty | Spread tickowy, podłoga 1,5/2,5 pipsa, poślizg 0,5× wejście i 1,0× stop, swap z osią marży. Raport 1×/2×/3× |
| Godziny | **Primary: 08:00–22:00** (baseline operacyjny). **Secondary: wszystkie godziny.** Oba prerejestrowane, oba raportowane |
| Kontrola losowa | Identyczne instrumenty, okres, godziny, SL/TP, koszty, sizing, execution i **liczba obserwacji**. Różnica: losowy timing i kierunek. ≥200 powtórzeń, ziarno zapisane |
| Nakładanie | Block bootstrap po dniu, bloki 20-dniowe, 10 000 replikacji. Do testów wchodzi **n_eff** |
| Walidacja | Brak dopasowania modelu → CPCV zbędne. To jest zaleta konstrukcji, nie brak |
| Metryka główna | Expectancy w R netto, per komórka, z CI95 |
| Osie raportowania | Para · rok · kierunek long/short · kubełek `vol_pct_252` (H03) · sesja |
| Licznik | N: 7 → **13** |

### Kryteria falsyfikacji — ustalone przed uruchomieniem

| Wynik | Wniosek |
|---|---|
| CI95 zawiera 0 we wszystkich 6 komórkach | H01 → `NOT_SUPPORTED` |
| CI95 w całości poniżej +0,02 R we wszystkich komórkach | H01 → `FALSIFIED` |
| CI95 > 0 w ≥1 komórce **i** kontrola losowa pobita p < 0,05 | H01 → `SUPPORTED`, przechodzi do robustness |
| Target A dodatni, target B ujemny | Informacja istnieje, nie przeżywa kosztów — osobny, raportowany wynik |

### Oczekiwane artefakty

`runs/<id>/`: `t001.md`, `metrics.json`, `observations.parquet`, kopia
zamrożonego configu, hash gita, hash danych, diff drzewa. Wpis w
`trials/trials.jsonl`. Aktualizacja `HYPOTHESES.md`, `EXPERIMENTS.md`,
`PROGRESS.md`.

---

## T002 — H07 zdarzenie vs H02 stan, plus redundancja z H01

**Status:** `PLANNED` · prerejestracja po zamknięciu T001

**Cel.** Trzy pytania w jednym przebiegu, bo dzielą aparaturę i próbę:

1. Czy `donch_pos` (stan) wnosi informację ponad `mom_k`? → rozstrzyga los H02
2. Czy zdarzenie wybicia różni się od stanu po kontroli na momentum? → H07
3. Jaka jest faktyczna korelacja i pokrycie obu cech? → domyka lukę pomiarową
   `market-quant`, który nigdy nie zmierzył redundancji składników koniunkcji

**Warunek.** Kryterium ilościowe „wnosi informację ponad" musi być ustalone
w prerejestracji **przed** uruchomieniem, nie po zobaczeniu rozrzutu.

---

## T003 — H01 Momentum, konstrukcja przeprojektowana po M02

**Status:** `PLANNED` — **nieprerejestrowany**. Zastępuje T001 (ADR-011).

**Cel.** To samo pytanie co T001: czy `mom_k` niesie informację o zwrocie
w przód, mierzone na wszystkich barach, bez warstwy portfelowej (ADR-002).
Zmienia się wyłącznie konstrukcja pomiaru — mechanizm i hipoteza zostają.

**Czego nie wolno odziedziczyć po T001.** Prerejestracja T003 musi spełnić
sześć warunków, zanim cokolwiek zostanie uruchomione — cztery z ADR-011,
dwa dołożone po M03 (ADR-012 i pomiar kosztu):

| # | Warunek | Dlaczego |
|---|---|---|
| 1 | Jawna deklaracja modelu niezależności par i liczby P_eff | M02: wybór w nawiasie [2,0; 6,0] jest wart czynnika 1,7 na MDE |
| 2 | Moc wyliczona z σ **zmierzonej** dla zadeklarowanej geometrii barier | σ zależy od geometrii; dziedziczona była 2× za mała |
| 3 | Wykazanie, że progi falsyfikacji są osiągalne — martwa strefa wypisana | Inaczej `NOT_SUPPORTED` zapada niezależnie od tego, czy efekt istnieje |
| 4 | Rozstrzygnięcie granicy okien wychodzących poza segment | T001 tego nie mówił; po wyniku byłby to parametr swobodny |
| 5 | **Ramię kontrolne: cecha vs cecha postarzona o jeden bar**, z kryterium ustalonym przed uruchomieniem | ADR-012 — dawne M04; osobny przebieg spaliłby próbę za diagnostykę przebiegu głównego |
| 6 | **Model kosztu z członem swapu**, albo jawne uzasadnienie pominięcia | M03: przy h=10d brakująca marża to 1,32× cały modelowany koszt |

**Kierunki przeprojektowania — do rozważenia, nic nie przesądzone.**
Rezygnacja z h = 10 d: nie przechodzi bramki przy żadnym modelu par, a po
M03 traci też jedyną przewagę, jaką miał — po doliczeniu swapu kosztuje na
transakcję tyle samo co h = 3 d (0,0392 wobec 0,0422 R), dając 3× mniej
obserwacji niezależnych.
Zmiana geometrii barier — przy obecnej TP pada w 5,5% przypadków, a 63%
pozycji umiera na barierze czasowej, co jest rozrzutem wydanym bez
informacji. Urealnienie progu +0,02 R w kryterium `FALSIFIED`. Każdy
z tych wariantów zmienia σ i wymaga **nowego pomiaru mocy**, nie
przeliczenia istniejącego.

**Warunek startu.** ~~M03~~ (PRZECHODZI), ~~testy na look-ahead~~ (spłacone
w M03), M04 w nowej postaci (ADR-012), warstwa etykiet, prerejestracja
spełniająca sześć warunków powyżej.
