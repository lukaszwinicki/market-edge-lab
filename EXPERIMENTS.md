# EXPERIMENTS.md — indeks eksperymentów

Ten plik jest **indeksem**. Szczegóły każdego przebiegu żyją w `runs/<id>/`,
a maszynowy zapis w `trials/trials.jsonl`.

**Seria M** = sprawdzenia aparatury (kontrole). Nie liczą się do N w DSR.
**Seria T** = triale hipotez. Każdy sprawdzony wariant liczy się do N.

**Licznik prób: N = 10** (7 odziedziczonych, ADR-004 + 3 warianty T003).
Uruchomionych prób strategii w tym projekcie: **3**.

---

## Indeks

| ID | Hipoteza | Status | Wynik | Decyzja |
|---|---|---|---|---|
| M01 | — | `CLOSED` | **PRZECHODZI** — port identyczny co do bitu, 173 testy, raport jakości zdany | KEEP |
| M02 | — | `CLOSED` | **NIEROZSTRZYGNIĘTE** — h=10d bramkę przekracza, h=3d siada na progu (0,0796 vs 0,08) | ADR-011: T001 wycofany |
| M03 | — | `CLOSED` | **PRZECHODZI** — expectancy losowych wejść = −koszt w granicach 1 SE; symulator nie zna swapu | KEEP |
| M04 | — | `CLOSED` | **PRZECHODZI** — wzmocnienie poprawne; próg wykrywalności to 57,3% / 61,9% trafności kierunku | KEEP |
| M05 | — | `CLOSED` | **PRZECHODZI** — n_eff warstwy A zmierzone (1 902–5 150); `FALSIFIED` osiągalne we wszystkich komórkach | ADR-015 domknięty |
| M06 | — | `CLOSED` | **PRZECHODZI** — zero pełnego modelu kosztu to −0,0422 R; złożenie swapu identyczne co do bitu | ADR-016 |
| T001 | H01 | `WITHDRAWN` | **nieuruchomiony** — konstrukcja bez mocy na osiągnięcie własnych kryteriów (M02) | ADR-011 |
| M07 | — | `CLOSED` | **ROZSTRZYGA** — H02 redundantna z H01 (ρ = +0,832 z `mom_24`); zdarzenie H07 jest 44–54× rzadsze od stanu | H02 → `CLOSED`; T002 zwęża się do H07 |
| M08 | — | `CLOSED` | **ROZSTRZYGA** — 726 zdarzeń H07 na siatce primary; górna granica n_eff 843 wobec 1 317 potrzebnych do `FALSIFIED` | ADR-021: T002 nie startuje |
| T002 | H07 | `WITHDRAWN` | **nieuruchomiony, bez prerejestracji** — `FALSIFIED` nieosiągalne przy każdym modelu zależności (M08A) | ADR-021 |
| T003 | H01 | `CLOSED` | **`NOT_SUPPORTED`** — relacja nieodróżnialna od zera we wszystkich 3 komórkach; górne ograniczenie **51,03%** trafności | H01 → `NOT_SUPPORTED`; ADR-019 |

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

## M04 — Czułość przyrządu · `CLOSED` · **PRZECHODZI** (ADR-012)

> **Postać z fazy 0 nie wystartowała i nie wystartuje.** Porównanie baseline z cechą
> postarzoną wymaga policzenia `mom_k`, czyli **oceny sygnału H01**. To (a)
> klasyfikuje przebieg jako `strategy` i dolicza go do N, (b) pokazuje
> expectancy H01, zanim T003 zostanie prerejestrowany — a prerejestracja
> pisana po zobaczeniu wyniku nie jest prerejestracją.
>
> W planie z fazy 0 kolejność była bezpieczna, bo T001 był już zamrożony.
> **Wycofanie T001 (ADR-011) usunęło tę ochronę.**
>
> **Nowa postać (ADR-012, skorygowana przez ADR-013):** kierunek ze znaku
> faktycznego zwrotu w oknie — szum (`p`=0,5), wyrocznia (`p`=1,0) i cała
> krzywa między nimi. Ramienia „wyrocznia postarzona" **nie ma**: byłoby
> znakiem zwrotu z przeszłości, czyli cechą momentum, co łamałoby regułę
> z samego ADR-012. Pytanie o przesunięcie o jeden bar przeszło na testy
> syntetyczne. Porównanie na cesze prawdziwej → T003, warunek 5.

**Cel (postać z fazy 0, zachowany jako zapis).** Sprawdzić przy pełnej mocy,
czy cechy postarzone o jeden bar dają wynik **gorszy** niż baseline, jak
powinny.

### Wynik (2026-09-23) · `20260923T181510Z-963686` · raport: `reports/m04_sensitivity.md`

Postać wykonana (ADR-012): kierunek ze **znaku faktycznego zwrotu w oknie**
— z przyszłości, celowo. Żadnej cechy. Dla 30 000 momentów odegrano **obie**
strony, więc cała krzywa `E(p) = p·E[trafna] + (1−p)·E[nietrafna]` wychodzi
z jednego przebiegu.

| | h = 3 d | h = 10 d |
|---|---|---|
| E[trafna] / E[nietrafna] | +0,6858 / −0,7347 R | +0,6772 / −0,7168 R |
| **Próg opłacalności** (E = 0) | **51,72%** | **51,42%** |
| **Próg wykrywalności** (E = MDE z M02) | **57,33%** | **61,91%** |
| Iloraz przewag nad 50% | **4,3×** | **8,4×** |

**Sprawdzenie krzyżowe z M03.** Przy `p = 0,50` M04 musi odtworzyć M03 —
i odtwarza: −0,0245 wobec −0,0248 R (h=3d) i −0,0198 wobec −0,0191 R (h=10d).
**Zgodność do 0,0007 R** przy innych ziarnach, innej strukturze losowania
i innej ścieżce kodu. Najmocniejsze sprawdzenie aparatury po M01.

`INFERENCE`: **eksperyment widzi tylko efekty 4–8× większe od najmniejszego
opłacalnego.** Między 51,7% a 57,3% trafności leży pas, w którym strategia
naprawdę zarabia, a pomiar zwróci `NOT_SUPPORTED`. To ta sama martwa strefa
co w M02, ale w jednostce, o której da się mieć zdanie.

### Drugi wynik: bariery prawie nie wiążą

Przy **doskonałym** kierunku 84% (h=3d) i 83% (h=10d) pozycji kończy na
barierze czasowej; TP pada w 10%, SL w 5%. Średni |ruch| w oknie to **40%
dystansu do TP** przy obu horyzontach — typowy ruch nie sięga nawet stopu.

`INFERENCE`: triple-barrier jest tu w dużej mierze **dekoracją** — dokłada
ryzyko luki i złożoność, rozstrzygając 16% przypadków. Tłumaczy zarazem, czemu
σ z M02 (0,92 R) jest bliska rozrzutowi samego zwrotu: bariery obcinają mało.
Sufit przy wyroczni to +0,686 R wobec ruchu wartego 0,810 R, więc geometria
zamienia **85%** ruchu na wynik — straty na geometrii nie ma, jest tylko
bezczynność. Wejście do warunku 2 i do kierunku „zmiana geometrii" dla T003.

### Czego M04 nie zrobił

Nie policzył `mom_k`. Nie porównał cechy prawdziwej z jej opóźnieniem — to
ramię przechodzi do T003 (warunek 5). Nie doliczał swapu: krzywa jest
w kosztach, które symulator implementuje, a marża przesuwa oba progi w górę.

Pytanie „czy w pipelinie jest przesunięcie o jeden bar" rozstrzygają testy na
danych syntetycznych, nie ten przebieg: `test_grid.py`, `test_volatility.py`,
trzy testy w `test_simulator.py` i złożenie całej ścieżki w
`test_entries.py::test_edge_is_recovered_only_when_it_lies_inside_the_trade_window`.

**Kontekst.** W `market-quant` ta kontrola dała wynik **lepszy** (−0,0268 vs
−0,0560 R). Tamto wyjaśnienie — szum przy połowie CI 0,067 R — było poprawne
w tamtych warunkach. Przy większej mocy to jest otwarte `UNKNOWN`, a wzrost
wyniku po podaniu cech z przyszłości jest kanonicznym objawem błędu off-by-one.

**Kryterium.** Wynik z cechami przesuniętymi **nie rośnie**. Wzrost → STOP
i audyt wyrównania znaczników czasu przed jakimkolwiek eksperymentem.

---

## M05 — Rozkład zerowy metryki warstwy A · `CLOSED` · **PRZECHODZI**

**Cel.** Zmierzyć, ile obserwacji naprawdę niezależnych ma statystyka relacji
`cecha ↔ fwd_atr` na siatce T003, i czy kryterium `FALSIFIED` jest osiągalne.

**Dlaczego osobny pomiar.** ADR-014 ustalił `P_eff = 2,00` dla warstwy B.
Dla statystyki relacji zależność międzyparowa jest **inną wielkością**: pod H0
kowariancja estymatorów idzie jak iloczyn `ρ^cecha · ρ^zwrot`, nie jak `|ρ|`.
Przepisanie liczby z warstwy B na A byłoby odziedziczeniem zamiast pomiaru —
tym samym błędem, który M02 wykrył przy σ.

### Wynik (2026-09-24) · `20260924T134703Z-cd0d96` · raport: `reports/m05_layer_a_null.md`

`mom_k` **nie został policzony**. Cecha syntetyczna: różnica skumulowanych
przyrostów losowych na oknie `k` — ta sama autokorelacja co `mom_k` pod H0,
zbudowana z generatora. Prawdziwe ceny wchodzą wyłącznie przez `fwd_atr`.

Siatka T003 (h = 3 d, Spearman, gorszy z modeli bramkowych), **bez korekty
na wielokrotność** — po korekcie Holma progi to 51,44 / 52,15 / 52,36%:

| k | n_eff | Próg wykrywalności | Martwa strefa | `FALSIFIED` |
|---|---|---|---|---|
| 24 | 5 150 | 51,24% | **−0,48 pp** | osiągalne (0,51) |
| 120 | 2 302 | 51,86% | +0,14 pp | osiągalne (0,76) |
| 480 | 1 902 | 52,05% | +0,33 pp | osiągalne (0,83) |

**Martwa strefa spada z 5,61 pp (warstwa B) do 0,33 pp** w najgorszej komórce.
Przy k = 24 jest ujemna — eksperyment wykrywa efekty mniejsze od najmniejszego
opłacalnego.

### Cztery ustalenia

1. **`P_eff` warstwy A wynosi 3,21**, nie 2,00 (`FACT`). Przewidywanie
   analityczne z macierzy M02 dawało 3,08. Zmierzone wiąże.
2. **`sign_aligned` jest krańcem OPTYMISTYCZNYM, nie pesymistycznym**
   (`FACT`). Model „znak cechy idealnie śledzi czynnik USD" daje `P_eff ≈ 7,0`,
   czyli więcej niż sześć par niezależnych. Kowariancja idzie jak **iloczyn**
   `ρ^cecha · ρ^zwrot`; odwrócenie znaków samej cechy czyni część iloczynów
   ujemnymi, a te **kasują** wariancję. `INFERENCE`: intuicja „zrównanie
   znaków jest zawsze konserwatywne" jest fałszywa dla warstwy A — i gdyby
   `P_eff = 2,00` przepisać „dla ostrożności", byłoby to założenie
   niekonserwatywne, wyglądające na ostrożne.
3. **h = 10 d odpada także na warstwie A** (`FACT`). Dwie z trzech komórek nie
   mogą zapaść na `FALSIFIED` przy żadnym wyniku (n_eff 1 352 i 700). Decyzja
   ADR-015 była `INFERENCE`; teraz jest pomiarem.
4. **Nakładające się bary dokładają informację** (`FACT`). Zachłanne n_eff
   z M02 (3 126) jest dolnym ograniczeniem: przy parach niezależnych statystyka
   na wszystkich 130 553 wierszach daje 3 556. Zysk skromny i rosnący przy
   krótszym `k`. Nie zmienia to niczego w M02 — tam mierzono inną wielkość.

**Wątpliwość zamknięta pomiarem.** Cecha jest zwrotem z okna `k`, a nie `h`;
gdyby korelacja międzyparowa rosła z długością okna, model bramkowy byłby za
łagodny. Zmierzona średnia `|ρ|` na oknach 24 / 120 / 480 barów: **0,389 /
0,404 / 0,398** — płasko, więc `as_returns_k` ≈ `as_returns_h`.

### Czego M05 nie zrobił

Nie policzył `mom_k` w żadnym wariancie. Nie mierzył mocy pod hipotezą
alternatywną. Nie rozstrzygał wyboru między Spearmanem a Pearsonem — ten
zapadł przed przebiegiem, z kurtozy. Nie dotknął OOS ani segmentu
zapieczętowanego. Testy: **281** (264 + 17, `tests/test_surrogate.py`).

---

## M06 — Zero przyrządu po doliczeniu finansowania · `CLOSED` · **PRZECHODZI**

**Cel.** Ustalić expectancy wejść losowych po **pełnym** koszcie — spread,
podłoga, poślizg i marża swapu — czyli liczbę, wobec której mierzy się
warstwa B T003. Dotąd znane było zero modelu niepełnego.

**Bez nowej symulacji.** Przebieg czyta artefakty M03. Koszt finansowania
zależy wyłącznie od ceny, dystansu stopu i czasów wejścia/wyjścia, a te są
zapisane; powtórzenie symulacji dałoby te same transakcje przy tym samym
ziarnie, nie kupując ani jednej nowej obserwacji.

### Wynik (2026-09-24) · `20260924T141045Z-c94360`

| h | marża | E[net] | pełny koszt | luka | w SE |
|---|---|---|---|---|---|
| 3 d | 1,0% | −0,0373 | 0,0422 | +0,0049 | **+0,96** |
| 10 d | 1,0% | −0,0414 | 0,0392 | −0,0022 | **−0,27** |

**Złożenie identyczne co do bitu.** `execution/costs.py` liczy swap
z `TradeResult`, M03 liczył go własną pętlą; na 197 847 transakcjach
`max_abs_diff = 0` przy każdej z trzech marż. To uzasadnia ADR-016:
doliczenie po fakcie nie traci dokładności.

**Luka kalibracji jest niezmiennicza względem marży** (`FACT`) — +0,00490 R
przy 0,5%, 1% i 2% jednakowo. To tożsamość, nie pomiar: swap odejmuje się od
obu stron równania naraz. Zapisane, żeby niezmienniczości nie wziąć za
potwierdzenie.

**Konwencja SE nie jest szczegółem** (`FACT`). Block bootstrap po dniu daje
SE = 0,00507; naiwne SE po transakcjach 0,00290, czyli **1,75× za wąsko** —
i zamieniłoby lukę 0,96 SE w 1,69 SE, czyli przejście w niepowodzenie.

### Czego M06 nie zrobił

Nie uruchomił symulatora. Nie policzył `mom_k`. Nie odkrył, że kalibracja
przechodzi po doliczeniu swapu — to wynikało z tożsamości i było wiadome
przed przebiegiem; treścią M06 jest zapisane zero i sprawdzenie złożenia.

---

## M07 — Redundancja cech H01↔H02 · `CLOSED` · **ROZSTRZYGA**

**Cel.** Czy `donch_pos` (H02) pyta o to samo co `mom_k` (H01)? Rozstrzygnięcie
**przed** prerejestracją T002, za zero prób.

**Autoryzacja.** ADR-012 zakazuje liczenia cechy hipotezy bez żywej
prerejestracji. **ADR-020** otwiera wąski wyjątek: pomiar cecha↔cecha,
strukturalnie niezdolny spojrzeć w przód. Skrypt nie importuje warstwy
etykiet ani symulatora i nie dotyka kolumn `fwd_atr`/`t1`; pilnuje tego
`tests/test_m07_boundary.py`, czytając źródło.

### Wynik (2026-09-24) · `20260924T154152Z-a734c5` · `control`, N bez zmian

| Para cech | Spearman | `P(mom > 0 \| donch_pos > 0,80)` |
|---|---|---|
| `donch_pos_55` ↔ **`mom_24`** | **+0,832** | **0,973** |
| `donch_pos_55` ↔ `mom_120` | +0,533 | 0,796 |
| `donch_pos_55` ↔ `mom_480` | +0,260 | 0,630 |

**H02 → `CLOSED`.** Próg 0,70 zadeklarowany przed przebiegiem; zmierzone
0,832. Przy `P = 0,973` stan Donchiana jest niemal deterministyczną funkcją
znaku krótkiego momentum — wynik odporny na wybór progu.

**Dokument mylił się w szczególe** (`FACT`). `HYPOTHESES.md` podejrzewał
redundancję z **`mom_480`** („jeśli cena jest w górnych 20% zakresu, `mom_480
> 0` jest niemal pewne"). Zmierzone: ρ = +0,260, `P` = 0,630 — **nie jest
niemal pewne**. Redundancja jest z `mom_24`. Podejrzenie było słuszne co do
istoty, błędne co do okna, i nikt by tego nie zauważył bez pomiaru.

### Drugi wynik: H07 nie jest H02 — `FACT`

| | Stan (`donch_pos > 0,80`) | Zdarzenie wybicia |
|---|---|---|
| udział barów | 21,5–25,0% | **0,45–0,49%** |
| iloraz | | **44–54× rzadziej** |

Spójnie na wszystkich sześciu parach. `HYPOTHESES.md` H07 twierdził, że
*„cokolwiek market-quant zmierzył, nie było wybiciem w sensie zdarzenia"* —
teraz to jest zmierzone, nie deklarowane.

### Czego M07 nie zrobił

**Nie obejrzał ani jednego zwrotu w przód.** Nie mówi więc nic o przewadze
H02 ani H07 — wyłącznie o tym, czy pytają o to samo. Wniosek „H02 nie ma
przewagi, bo H01 jej nie miał" jest `INFERENCE` i **nie jest wynikiem M07**.

---

## M08 — Audyt mocy T002 (H07) · `CLOSED` · **ROZSTRZYGA**

**Cel.** Czy H07 ma dość zdarzeń, żeby `FALSIFIED` było osiągalne na
warstwie A? Rozstrzygnięcie **przed** prerejestracją T002, za zero prób.
Autoryzacja: wyjątek ADR-020, jak M07 — skrypt liczy wyłącznie znaczniki
czasu, nie czyta żadnej ceny po decyzji; pilnuje tego
`tests/test_m08_event_geometry.py`, czytając źródło.

Zaplanowany w dwóch krokach: A (geometria zdarzeń) i B (rozkład zerowy
z surogatu, wzór M05). **B nie został uruchomiony** — A rozstrzygnął warunek,
którego B nie mógł zmienić (ADR-021).

### Wynik kroku A (2026-09-24) · `20260924T200939Z-67315c` · `control`, N bez zmian

Zgodność z M07 co do sztuki na wszystkich parach (176 / 167 / 172 / 168 /
184 / 183). Okna przecinające koniec segmentu: 2 odrzucone.

| | Primary (siatka T003) | Wszystkie godziny |
|---|---|---|
| zdarzenia | **726** (95–136 na parę) | 1 048 |
| z oknem nakładającym się na tej samej parze | 5,8% | 8,8% |
| z oknem nakładającym się na **innej** parze | **91,3%** | 97,3% |
| zgodność kierunku USD w nakładaniach | 56,9% | 57,7% |
| skupiska okien (dolna granica niezależnych) | 216 | 177 |
| górna granica n_eff (×6,97/6 z M05) | **843** | 1 217 |

Potrzebne do `FALSIFIED`: **n_eff ≥ 1 317**. Nieosiągalne w każdej kolumnie.
MDE przy mocy 80%: 53,08% (primary, granica optymistyczna) do 56,11%
(skupiska), wobec progu opłacalności 51,72%.

**Zdarzenia skupiają się w sesji** (`FACT`): primary to 58% godzin, ale 69%
zdarzeń. Mimo to przesłanka „600–700 na parę" była błędna — to 726 **łącznie**.

**Zdarzenia nie są jednym zakładem na USD** (`FACT`): nakładają się niemal
zawsze, ale kierunek dolara zgadza się w 57% par — niewiele ponad losowe.
Prawdziwe n_eff leży między 216 a 843; krok B by je zawęził, ale obie
granice leżą poniżej 1 317.

### Czego M08 nie zrobił

**Nie obejrzał ani jednego zwrotu w przód** — nie mówi nic o tym, czy H07
ma przewagę. Mówi wyłącznie, że na RESEARCH w tej definicji nie da się tego
rozstrzygnąć w stronę `FALSIFIED`. Nie zmierzył martwej strefy dokładnie
(to byłby krok B) i nie badał innych `N` ani `quiet_bars`.

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

**Status:** `WITHDRAWN` (2026-09-24, **ADR-021**) · nigdy nieprerejestrowany,
N bez zmian. M07 zawęził zakres do samego H07; M08A wykazał, że `FALSIFIED`
jest nieosiągalne przy każdym modelu zależności. Treść planu poniżej zostaje
bez zmian.

**Pierwotny status:** `PLANNED` · prerejestracja po zamknięciu T001

**Cel.** Trzy pytania w jednym przebiegu, bo dzielą aparaturę i próbę:

1. Czy `donch_pos` (stan) wnosi informację ponad `mom_k`? → rozstrzyga los H02
2. Czy zdarzenie wybicia różni się od stanu po kontroli na momentum? → H07
3. Jaka jest faktyczna korelacja i pokrycie obu cech? → domyka lukę pomiarową
   `market-quant`, który nigdy nie zmierzył redundancji składników koniunkcji

**Warunek.** Kryterium ilościowe „wnosi informację ponad" musi być ustalone
w prerejestracji **przed** uruchomieniem, nie po zobaczeniu rozrzutu.

---

## T003 — H01 Momentum, konstrukcja przeprojektowana · `PREREGISTERED`

**Status:** `PREREGISTERED` (2026-09-24) · **nieuruchomiony** · N bez zmian
**Prerejestracja:** `configs/t003_momentum.yaml`
`sha256 = c832dcdcbbc3f3e467bc18b9c4993c1f07bcb7a3b7a2b7d13aac481959db99b2`
`frozen_sha256 = 012cd9ccfba411fd58e3d41c7d6de8f0153a0b64714e0aa24d8a5a57f68696c3`

**Cel.** To samo pytanie co T001: czy `mom_k` niesie informację o zwrocie
w przód, mierzone na wszystkich barach, bez warstwy portfelowej (ADR-002).
Mechanizm i hipoteza bez zmian; zmienia się **warstwa, na której stoi
falsyfikacja**, i rozmiar siatki.

### Sześć warunków ADR-011 — stan

| # | Warunek | Stan | Gdzie rozstrzygnięty |
|---|---|---|---|
| 1 | Model niezależności par i `P_eff` | **spełniony** | ADR-014 (warstwa B: 2,00) + M05 (warstwa A: **3,21 zmierzone**) |
| 2 | σ zmierzona dla zadeklarowanej geometrii | **spełniony** | ADR-014 — geometria bez zmian, σ = 0,9165 z M02 dotyczy dokładnie jej |
| 3 | Progi falsyfikacji osiągalne, martwa strefa wypisana | **spełniony** | ADR-015 + M05 — `FALSIFIED` osiągalne we wszystkich 3 komórkach |
| 4 | Granica okien wychodzących poza segment | **spełniony** | prerejestracja, `windows_crossing_segment_end: drop` |
| 5 | Ramię „cecha vs cecha postarzona", kryterium przed uruchomieniem | **spełniony** | prerejestracja, `control_aged_feature` |
| 6 | Model kosztu ze swapem | **zadeklarowany, niewpięty** | prerejestracja — wiąże **wyłącznie warstwę B** |

### Co się zmieniło wobec T001

| | T001 (`WITHDRAWN`) | T003 |
|---|---|---|
| Instrument falsyfikacji | expectancy w net R (**warstwa B**) | Spearman `mom_k` ↔ `fwd_atr` (**warstwa A**) |
| Siatka | 3 × 2 = 6 komórek | 3 × 1 = **3 komórki**, h = 3 d |
| Próg wykrywalności | 57,33% trafności | **51,24–52,36%** |
| Martwa strefa | 5,61 pp | **−0,28 do +0,64 pp** |
| `FALSIFIED` | nieosiągalne | **osiągalne w każdej komórce** |
| `n_eff` | 1 040, wyliczone | **1 902–5 150, zmierzone** (M05) |
| Licznik | N: 7 → 13 | N: 7 → **10** |

Przesunięcie na warstwę A **nie jest złagodzeniem kryteriów** — ADR-015.
Przy warstwie B `NOT_SUPPORTED` zapadało niezależnie od tego, czy efekt
istnieje. Przy warstwie A wynik negatywny zaczyna wykluczać większość pasma,
w którym przewaga momentum mogłaby realnie leżeć. Cena wyniku negatywnego
rośnie, nie spada.

### Kryteria falsyfikacji — zamrożone

Próg opłacalności (M04): **51,72% trafności**, czyli `ρ = 0,05401`.

| Wynik | Reguła | Wielokrotność |
|---|---|---|
| `SUPPORTED` | CI > 0 w ≥1 komórce **i** kontrola permutacyjna pobita p < 0,05 | Holm na 3 komórki — union wymaga korekty |
| `FALSIFIED` | CI95 w całości wewnątrz ±0,05401 we **wszystkich** komórkach | bez korekty — intersection-union kontroluje błąd I rodzaju bez niej |
| `NOT_SUPPORTED` | każdy inny wynik | raport **musi** podać górne ograniczenie na efekt |

### Warunki startu — dwa niespełnione

### Warunki startu — ZAMKNIĘTE 2026-09-24

| Co | Stan |
|---|---|
| **Warstwa etykiet** bez treści hipotezy w module | `src/research/labels.py` — nie importuje cechy, nazwa cechy jest parametrem; pilnuje tego test w źródle |
| **Pełny koszt z członem finansowania** | `src/execution/costs.py` + **ADR-016** — swap NIE wchodzi do `CostModel`, bo marża jest osią, nie punktem. M06: złożenie identyczne co do bitu |

Powstały przy okazji: `src/features/momentum.py` (`mom_k`, dopuszczone
dopiero po zamrożeniu T003 — ADR-012) i `vol_pct_252` jako oś raportowania
H03. Testy: **327**.

**T003 nie ma już blokerów.** Zostaje samo uruchomienie, N: 7 → 10.

---

## Wynik T003 (2026-09-24) · `20260924T150658Z-8daa11` · **N: 7 → 10**

**Werdykt: `NOT_SUPPORTED`.** Czas przebiegu 355 s. Checklista leakage'u:
17 pozycji, 0 niespełnionych. Warstwa B **nie uruchomiona** — warstwa A nie
pokazała sygnału (ADR-003: „zatrzymujemy się tanio, nie spalając prób").

| k | Spearman | CI95 | n | SE tutaj / M05 |
|---|---|---|---|---|
| 24 | **+0,0070** | [−0,0186, +0,0322] | 130 553 | 0,01285 / 0,01393 (0,92) |
| 120 | **−0,0328** | [−0,0766, +0,0103] | 130 553 | 0,02212 / 0,02084 (1,06) |
| 480 | **−0,0315** | [−0,0781, +0,0121] | 130 553 | 0,02268 / 0,02293 (0,99) |

**Górne ograniczenie: 51,03% trafności kierunku** — czyli **0,69 pp PONIŻEJ
progu opłacalności 51,72%** (M04). Dodatnia relacja momentum, jeżeli istnieje,
jest za mała, żeby pokryć koszty.

**Dlaczego nie `FALSIFIED`.** Kryterium wymaga CI w całości wewnątrz ±0,054
we wszystkich komórkach. Przy k = 120 i k = 480 **dolny** koniec (−0,077,
−0,078) wychodzi poza pasmo. Blokuje więc nie możliwa przewaga dodatnia, tylko
niewykluczona relacja **ujemna**.

### Trzy rzeczy, które przebieg potwierdził

1. **Przedziały ufności są wiarygodne** (`FACT`). Sprawdzenie krzyżowe
   z M05 przeszło we wszystkich komórkach — ilorazy 0,923 / 1,062 / 0,989
   przy progu 25%. Rozrzut zmierzony surogatem i rozrzut zmierzony
   bootstrapem na prawdziwej cesze zgadzają się do 8%.
2. **Ramię kontrolne przeszło** (`FACT`). Cecha postarzona o bar jest
   **gorsza** od prawdziwej we wszystkich komórkach (−1,50 / −1,88 / −0,19 SE).
   Anomalia `market-quant` — gdzie postarzone cechy dawały wynik LEPSZY —
   **nie powtórzyła się**. `UNKNOWN` z ADR-004 domknięte.
3. **`P_eff` warstwy A zmierzone na prawdziwej cesze**: 3,09 / 3,18 / 3,40
   wobec 3,21 przewidzianego przez M05. Diagnostyka, nie kryterium (ADR-014).

### Czego wynikowi NIE wolno przypisać

Punktowe oszacowania przy k = 120 i k = 480 są **ujemne**, co wyglądałoby na
powrót do średniej. **To nie jest wynik T003.** Hipoteza przewidywała relację
dodatnią; znak przeciwny zaobserwowany po fakcie wymaga NOWEGO ID
i etykiety `EXPLORATORY / POST-HOC` z `origin` wskazującym ten trial, i nie
może być retroaktywnym potwierdzeniem czegokolwiek (CLAUDE.md).

Oba CI zawierają zero, więc dane nie każą odrzucić ani momentum, ani jego
braku — mówią tylko, że **jeżeli efekt dodatni istnieje, jest nieopłacalny**.

### Wada wykryta w trakcie: kontrola permutacyjna (ADR-019)

`p = 0,0120 / 0,0000 / 0,0000` **jest bez wartości dowodowej**. Permutacja
rozbija autokorelację cechy, więc jej rozkład zerowy ma SD 0,0028 ≈
`1/√130 553` — rozrzut iid, 4,5–8,3× za wąski. Werdyktu to nie zmienia:
`SUPPORTED` wymagał koniunkcji z CI > 0, a ta nie zaszła. Wada jest
antykonserwatywna — mogła dać fałszywe `SUPPORTED`, nie fałszywe
`NOT_SUPPORTED`. Szczegóły i reguła na przyszłość: **ADR-019**.

---

## Zmiana prerejestracji po zamrożeniu

Nie ma takiej procedury. Zmiana czegokolwiek w `configs/t003_momentum.yaml`
po tym wpisie to **nowy eksperyment z nowym ID**, a nie poprawka T003 —
niezależnie od tego, jak drobna. Hash wyżej jest po to, żeby dało się to
sprawdzić, a nie żeby w to wierzyć.
