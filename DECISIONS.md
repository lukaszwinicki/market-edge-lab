# DECISIONS.md — log decyzji metodologicznych (ADR)

**Wpisy są niezmienne.** Zmiana decyzji = nowy ADR, który jawnie unieważnia
poprzedni. Nie edytujemy historii.

Każdy wpis: data · decyzja · powód · alternatywy · konsekwencje.

Ten plik nie duplikuje wyników eksperymentów — te żyją w `runs/`
i `EXPERIMENTS.md`.

---

## ADR-001 — `market-edge-lab` jest nowym projektem; `market-quant` jest źródłem READ-ONLY

**Status:** ACCEPTED · 2026-09-23

**Decyzja.** Nowy projekt, nowe repozytorium, własna historia eksperymentów,
własny rejestr hipotez, własna prerejestracja. `../market-quant` traktujemy
jako źródło wiedzy metodologicznej, kodu i wyników — **nigdy jako źródło
założeń, które należy automatycznie zachować**. Repozytorium to jest
read-only: żadnych modyfikacji, resetów ani operacji destrukcyjnych.

**Powód.** `market-quant` zamknął się 2026-09-22 odrzuceniem swojej hipotezy
(ADR-049 tamtego repo) i sam zapisał, że nowa hipoteza ekonomiczna wymaga
nowego projektu, nowej prerejestracji i nowego licznika prób. Dopisywanie się
do zamkniętego programu badawczego zatarłoby granicę między tym, co zostało
prerejestrowane wcześniej, a tym, co wymyślono po zobaczeniu wyników.

**Ustalenia audytu, na których opiera się ten projekt** (`FACT`, zweryfikowane
w kodzie i artefaktach runu `20260922T200750Z-b57ab5`):

| Ustalenie | Dowód |
|---|---|
| Testowana reguła była koniunkcją `mom_480 > 0 ∧ donch_pos_55 > 0,80` | `src/strategy/v1a.py:145-146` |
| Sygnał wystąpił na 64 342 barach (28,7% z 224 420 decyzji) | log decyzji w `runs/…/v1a.md`; `no_signal` = 159 202 przy priorytecie wg ADR-033 |
| Do transakcji weszło 889 barów — 1,4% sygnałów | tamże, wiersz `enter` |
| Resztę wycięła warstwa ryzyka i portfela | `4_ccy_limit` 39 729 · `6_open_position` 10 815 · `5_portfolio` 8 854 (jako pierwszy powód) |
| Obserwacji efektywnych: 172, nakładanie 95,9% | `metrics.json` |
| Połowa CI expectancy: 0,067 R | `expectancy_ci` = [−0,1225; +0,0119] |
| Bramka 3 (wartość przyrostowa każdego komponentu osobno) **nigdy nie została uruchomiona** | `docs/PROGRESS.md` tamtego repo |
| `donch_pos_55 > 0,80` to zmienna percentylowa — odpala z definicji na ~20% barów | `src/features/technical.py:159-166` |

**Wniosek (`INFERENCE`).** `market-quant` sfalsyfikował **regułę handlową wraz
z jej warstwą zarządzania kapitałem**, a nie mechanizmy momentum czy wybicia.
Ani momentum, ani pozycja w zakresie nie zostały zmierzone osobno.

**Alternatywy.** (a) Uznać temat za zamknięty — odrzucone, bo wniosek nie
obejmuje mechanizmów, tylko jedną ich implementację. (b) Kontynuować w starym
repo — odrzucone, patrz wyżej.

**Konsekwencje.** Projekt ma uzasadnienie badawcze wykraczające poza
powtórzenie odrzuconego pomysłu. Ciężar dowodu nadal spoczywa na hipotezie
o istnieniu przewagi, a prior pozostaje niski.

---

## ADR-002 — Pomiar informacji jest oddzielony od symulacji strategii

**Status:** ACCEPTED · 2026-09-23 · **Decyzja centralna projektu**

**Decyzja.** Test hipotezy mierzy zawartość informacyjną cechy na **wszystkich
kwalifikujących się barach**. Warstwa ryzyka, limity ekspozycji, limity
portfela i reguła „jedna pozycja na instrument" **nie wchodzą do testu
hipotezy**. Wchodzą dopiero wtedy, gdy efekt przeżył pomiar i pytamy, czy da
się nim handlować.

Wymuszamy to architekturą: w fazie 1 katalog `src/risk/` **nie powstaje**.
Nie da się przypadkiem splątać warstw, z których jedna nie istnieje.

**Powód.** W `market-quant` warstwa portfelowa zredukowała 64 342 sygnały do
889 transakcji, a te do 172 obserwacji niezależnych. Selekcja przebiegała
kolejkowo — o tym, który sygnał stanie się transakcją, decydowało to, czy
w danym momencie limit waluty był wolny, a więc **historia poprzednich
transakcji, a nie treść hipotezy**. To jest podwójna szkoda: próba kurczy się
do rozmiaru, przy którym nic się nie wykryje, a to, co zostaje, nie jest
reprezentatywne dla populacji sygnałów.

**Alternatywy.** (a) Zostawić warstwę ryzyka w pomiarze jako „realistyczną" —
odrzucone: realizm wykonania osiąga się symulatorem tickowym, a nie mieszaniem
zarządzania kapitałem do testu statystycznego. (b) Losowo próbkować sygnały do
stałej liczby — odrzucone: wyrzuca informację bez powodu.

**Konsekwencje.** Dwa różne pytania rozstrzygamy osobno i w tej kolejności:
„czy w tej cesze jest informacja?" → „czy da się na niej zarobić po kosztach?".
Wynik „informacja jest, ale nie przeżywa kosztów" jest osobnym, pełnoprawnym
i raportowanym wynikiem. Symulacja portfelowa wróci jako osobna faza
z własną prerejestracją.

---

## ADR-003 — Target: pomiar na zwrocie znormalizowanym, ekonomia na R po kosztach

**Status:** ACCEPTED · 2026-09-23

**Decyzja.** Dwuwarstwowy target:

| Warstwa | Wielkość | Rola |
|---|---|---|
| **A — informacja** | Zwrot w przód przez h barów, znormalizowany `atr_d1_14` | Wykrywanie. Maksymalna moc, brak artefaktów ścieżki |
| **B — ekonomia** | Net R z tickowo symulowanej transakcji triple-barrier | Decyzja. Metryka główna projektu |

Binarny `P(TP przed SL)` schodzi do roli **diagnostyki**, nie targetu głównego.
Krok B uruchamiamy tylko wtedy, gdy krok A pokazał sygnał.

**Powód.** Trzy wady binarnego targetu, udokumentowane w audycie `market-quant`
(`docs/AUDIT_REPORT.md` §3.6), z których dwie pierwsze są tu rozstrzygające:

1. **Splątanie etykiety z cechą.** Jeśli ATR skaluje bariery i jednocześnie
   normalizuje cechy, prawdopodobieństwo trafienia bariery zależy od
   `bariera/σ` — część „predykcji" jest tożsamościowa, nie empiryczna.
2. **Utrata magnitudy.** Etykieta 0/1 wyrzuca informację o sile ruchu, czyli
   dokładnie to, co decyduje o expectancy. Statystycznie to strata mocy przy
   zerowym zysku.
3. Przy RR 1:2 base rate pod błądzeniem losowym to ~33%, a próg opłacalności
   ~34–35% — łatwo pomylić „accuracy 60%" z przewagą, gdy się o tym zapomni.

**Alternatywy.** (a) Zostawić `P(TP przed SL)` jako główny — odrzucone, patrz
wyżej. (b) Użyć wyłącznie zwrotu surowego — odrzucone: bez normalizacji
zmiennością pary i okresy są nieporównywalne, a wynik zdominowałyby epizody
wysokiej zmienności.

**Konsekwencje.** Wykrywanie i wycena są rozdzielone. Jeśli warstwa A jest
zerowa przy wysokiej mocy, warstwa B nie może być dodatnia i zatrzymujemy się
tanio, nie spalając prób.

---

## ADR-004 — Podział danych i licznik prób odziedziczony: N startuje od 7

**Status:** ACCEPTED · 2026-09-23

**Decyzja — podział segmentów:**

| Segment | Zakres | Reguła dostępu |
|---|---|---|
| RESEARCH | 2015-01-01 → 2021-12-31 | Swobodny dostęp. **Oglądany wcześniej** — patrz niżej |
| OOS | 2022-01-01 → 2023-12-31 | Ograniczone uruchomienia, każde logowane |
| **SEALED** | 2024-01-01 → koniec danych (2026) | **Zero dostępu.** Otwierany raz, w fazie końcowej |

**Decyzja — licznik prób:** `n_trials()` startuje od **7**, nie od zera. Do tej
liczby harness dolicza każdy wariant sprawdzony w tym projekcie.

**Powód.** Próbą jest sprawdzony wariant, nie uruchomienie skryptu. Deflated
Sharpe Ratio podnosi poprzeczkę proporcjonalnie do liczby prób, bo przy wielu
próbach najlepsza z nich wypada dobrze także wtedy, gdy wszystkie są
bezwartościowe. `market-quant` uruchomił skrypt strategii **raz**, ale ten
przebieg policzył **siedem wariantów siatki** (baseline, D−, D+, S−, S+, T−, T+)
na tych samych danych 2015–2021, na tych samych parach i w tej samej rodzinie
pomysłów (trend/momentum), z której wychodzi H01 i H02. Pominięcie ich zaniżyłoby
poprzeczkę.

Tamten projekt raportował N = 8, ale sam zapisał w `docs/PROGRESS.md`, że
ósmy wpis to pomyłka księgowa — wpis sprzed ADR-029 bez pola `kind`, faktycznie
kontrola, policzona jako strategia. Zawyżała, więc jej nie poprawiali.
**Nie przenosimy cudzej pomyłki: przenosimy 7.**

**Alternatywy.** (a) Start od zera — odrzucone: te same dane, ta sama rodzina
hipotez, ten sam badacz. (b) Przeniesienie 8 — odrzucone, wiemy, że to błąd.
(c) Porzucenie 2015–2021 i badanie wyłącznie na danych nietkniętych — odrzucone:
zostałyby dwa lata, za mało na cokolwiek, a koszt w postaci ~17% wyższej
poprzeczki DSR jest tańszy niż utrata siedmiu lat danych.

**Konsekwencje.** Poprzeczka dla wyników rośnie o rząd 15–20% względem startu od
zera. Segment 2024–2026 jest naprawdę nietknięty — `market-quant` zapieczętował
go i nigdy nie otworzył, więc zachowuje pełną wartość dowodową.

---

## ADR-005 — Przeniesienie aparatury z `market-quant`: kopia + ponowna weryfikacja

**Status:** ACCEPTED · 2026-09-23

**Decyzja.** Przenosimy do tego repozytorium wyłącznie kod **bez treści
hipotezy**, przez kopię plików. Nie importujemy ze starego repo w czasie
działania. Przeniesiony kod **nie dziedziczy zaufania**: zanim cokolwiek
zmierzy, musi przejść własne testy i własną kalibrację tutaj.

| Przenosimy (aparatura) | Nie przenosimy (treść hipotezy) |
|---|---|
| `execution/simulator.py`, `execution/financing.py` | reguła V1a |
| `data/dukascopy.py`, `download.py`, `resample.py`, `quality.py` | zestaw sześciu cech jako zestaw |
| `validation/*` — bootstrap, DSR, PBO, CPCV, kontrole | silnik ryzyka i portfela |
| `harness/registry.py`, `data/provenance.py` | horyzont 10 dni, okno godzinowe, geometria barier |
| technika liczenia cech bez podglądania przyszłości | `strategy/runner.py` w obecnej postaci |

**Powód.** Aparatura pomiarowa nie zawiera hipotezy — działa tak samo
niezależnie od tego, co mierzymy. Napisanie jej od nowa dałoby kod **mniej**
wiarygodny, nie bardziej: obecny ma za sobą 489 funkcji testowych i, co
ważniejsze, **dowód empiryczny z bramki 0** — losowe wejścia dawały
expectancy −0,0106 R przy modelowanym koszcie 0,0116 R, czyli symulator nie
podgląda przyszłości.

Symulator egzekucji jest modułem, w którym błędy są **niewidoczne**: gdy
w jednej świecy cena dotknęła i stopa, i celu, z OHLC nie da się ustalić
kolejności, a naiwna implementacja zakłada kolejność korzystną i po cichu
zawyża każdy wynik. Obecny schodzi do ticków, a przy ich braku wybiera wariant
pesymistyczny.

**Alternatywy.** (a) Pisać od zera — odrzucone: 2–3 tygodnie na kod o gorzej
udowodnionej poprawności. (b) Importować ze starego repo jako biblioteki —
odrzucone: wynik zależałby od repozytorium zadeklarowanego jako read-only,
które może się przenieść lub zmienić; odtwarzalność wymaga samowystarczalności.

**Konsekwencje.** Faza 1 zaczyna się od przeniesienia i weryfikacji, a nie od
pomiaru. Trzy kroki kontrolne przed pierwszym eksperymentem: pełen zestaw
testów, kalibracja kontrolą losową (M03) oraz domknięcie otwartego pytania
tamtego projektu o cechy przesunięte w przyszłość (M04).

---

## ADR-006 — Zakres hipotez w fazie 0: bez mnożenia bytów

**Status:** ACCEPTED · 2026-09-23

**Decyzja.** Rejestr startuje z H01–H06 z prerejestracji plus **jedną** nową
hipotezą, H07. Osie „momentum × zmienność", „per sesja" i „long vs short"
**nie są osobnymi hipotezami** — są wymiarami raportowania prerejestrowanymi
wewnątrz protokołu H01. H05 i H06 startują jako `DEFERRED`.

**Powód.** Audyt `market-quant` wyprodukował ustalenia **metodologiczne**
(splątanie warstw, brak mocy, nieprzetestowane komponenty), a nie nowe
mechanizmy rynkowe. Dokładanie hipotez dlatego, że poprzednia nie zadziałała,
jest wzorcowym sposobem, w jaki program badawczy przestaje móc zakończyć się
wynikiem negatywnym.

H07 jest wyjątkiem, bo wynika z **faktu**, nie z potrzeby: to, co
`market-quant` nazwał wybiciem, odpalało z definicji na ~20% barów, więc było
stanem trwałym. Mechanizm wybicia jako **zdarzenia** nie został dotknięty.

Osie warunkujące muszą być prerejestrowane **przed** wynikiem H01. Wprowadzone
po zobaczeniu wyniku negatywnego byłyby klasycznym ratunkiem post-hoc —
dokładnie tym, czego zakazuje reguła „nie zmieniamy hipotezy po wyniku".

**Alternatywy.** (a) Dodać hipotezy o asymetrii kierunkowej i o horyzoncie jako
osobne pozycje — odrzucone: pierwsza jest osią raportowania, druga parametrem
wewnątrz H01, a obie zwiększyłyby licznik prób bez nowej informacji.

**Konsekwencje.** Siedem pozycji w rejestrze, z czego dwie aktywne. Program da
się zamknąć wynikiem „nie znaleziono stabilnego efektu" — i to jest cecha,
nie wada.

---

## ADR-007 — Dostęp do danych tickowych bez duplikacji i bez zapisu do starego repo

**Status:** ACCEPTED · 2026-09-23

**Decyzja.** Surowe ticki Dukascopy (11 GB, 6 par, 2015–2026) czytamy ze
skonfigurowanej ścieżki `../market-quant/data/raw/dukascopy` **w trybie tylko
do odczytu**. Świece M1 i H1 budujemy do własnego `data/` tego projektu.
Ścieżka jest parametrem konfiguracji, nie stałą w kodzie.

**Powód.** Duplikowanie 11 GB jest marnotrawstwem, a zapisywanie czegokolwiek
do `market-quant` łamie ADR-001. Surowe ticki są danymi źródłowymi, nie
wytworem tamtego projektu — nie niosą żadnych jego założeń.

**Alternatywy.** (a) Kopia 11 GB — odrzucone, koszt bez korzyści.
(b) Ponowne pobranie z Dukascopy — odrzucone: dni transferu po to, by uzyskać
te same pliki.

**Konsekwencje.** Projekt nie jest w pełni samowystarczalny na poziomie danych
źródłowych — wymaga obecności katalogu z tickami albo ponownego pobrania.
Zapisujemy to jako znane ograniczenie w `DATA.md` razem z hashem zbioru, żeby
dało się wykryć podmianę.

---

## ADR-008 — Kohorta replikacyjna nie istnieje; replikacja jest odłożona jawnie

**Status:** ACCEPTED · 2026-09-23

**Decyzja.** Replikacja na XAUUSD, WTI, S&P 500 i DAX jest **odłożona**, a jej
brak zapisany jako znane ograniczenie. Nie pobieramy tych danych, dopóki nie
wiemy, czy jest co replikować. Skład kohorty replikacyjnej jest jednak
**zamrożony już teraz**, przed jakimkolwiek wynikiem.

**Powód.** `market-quant` nigdy nie pobrał tych danych — nie istnieje ani jeden
bajt. Pobranie plus kalendarze sesji per instrument, obsługa dywidend CFD,
model finansowania pełną stawką i osobny raport jakości to tygodnie pracy.
Wydawanie ich, zanim wiemy, czy jakikolwiek efekt przetrwał pomiar, jest złą
kolejnością priorytetów.

Skład zamrażamy teraz, bo wybór instrumentów replikacyjnych **po** zobaczeniu
wyników jest selection bias — dokładnie tym, przed czym replikacja ma chronić.

**Alternatywy.** (a) Pobrać od razu — odrzucone, patrz wyżej. (b) Zostawić
skład otwarty — odrzucone, patrz wyżej.

**Konsekwencje.** Żadna hipoteza nie może w tej fazie uzyskać statusu
`SURVIVED`, bo replikacja na nietkniętej klasie aktywów jest jego warunkiem.
Najwyższy osiągalny status to `SUPPORTED`. Zapisane wprost w `HYPOTHESES.md`.

---

## ADR-009 — Audyt mocy przed pierwszym eksperymentem

**Status:** ACCEPTED · 2026-09-23

**Decyzja.** Przed uruchomieniem T001 wykonujemy krok **M02**: pomiar, ile
obserwacji naprawdę niezależnych daje się uzyskać przy horyzoncie 3 i 10 dni,
oraz jaka jest wynikająca z tego najmniejsza wykrywalna przewaga. Wynik M02
jest warunkiem uruchomienia T001. M02 jest kontrolą, nie liczy się do N.

**Powód.** Wzrost z 889 transakcji do ~64 000 barów **nie przekłada się na
proporcjonalny wzrost mocy** — wąskim gardłem jest nakładanie okien wynikowych,
nie liczba wierszy. Szacunek przed pomiarem:

| | `market-quant` | h = 10 dni | h = 3 dni |
|---|---|---|---|
| n_eff (szacunek) | 172 | ~450 | ~1500 |
| Połowa CI (szacunek) | 0,067 R | ~0,042 R | ~0,023 R |
| Wykrywalna przewaga | ≥0,10 R | ~0,06 R | ~0,035 R |

To są **szacunki, nie pomiary** — stąd M02. Uruchomienie eksperymentu, o którym
z góry wiadomo, że nie ma mocy wykryć interesującego efektu, spala próbę
w liczniku DSR za zero informacji. To był kosztowny błąd poprzednika, choć
nienazwany tam wprost.

**Kryterium.** Jeśli M02 pokaże najmniejszą wykrywalną przewagę ≥ 0,08 R przy
obu horyzontach, T001 **nie startuje** — konstrukcję trzeba przeprojektować
i zapisać to nowym ADR.

**Konsekwencje.** Krótszy horyzont kupuje moc statystyczną i sprzedaje
wykonalność ekonomiczną: mniejszy stop oznacza wyższy koszt w jednostkach R
(rzędu 0,023 R zamiast 0,012 R na transakcję) przy ~3× większej częstotliwości.
Dlatego oba horyzonty są prerejestrowane i oba raportowane — wybór jednego
z góry byłby założeniem, nie wynikiem.

---

## ADR-010 — Akceptacja godziny 2023-12-24 22:00 jako zamknięcia rynku, nie awarii feedu

**Status:** ACCEPTED · 2026-09-23 · **Wykryte w:** M01

**Decyzja.** Godzina `2023-12-24T22:00Z` trafia na zamkniętą listę
`data.quality.accepted_outages` wraz z dowodem. Detektor **nie jest
osłabiany** — nadal ją wykrywa, a raport jakości drukuje ją razem
z uzasadnieniem.

**Kontekst.** Raport jakości M01 zgłosił `NIE PRZECHODZI`: jedna godzina bez
ticków u wszystkich sześciu par naraz, w dniu, który wyprowadzony kalendarz
uznaje za handlowy. Trzy godziny odziedziczone po `market-quant` zostały
potwierdzone naszym własnym przebiegiem. Czwarta leży w segmencie OOS
2022-2023, którego tamten projekt nigdy nie zbudował — dlatego jej nie znał.

**Dowód (`FACT`, odczytany z rozmiarów plików cache):**

| Obserwacja | Wartość |
|---|---|
| 2023-12-24 | **niedziela** — Wigilia w dniu otwarcia tygodnia FX |
| Blok 17:00–22:00 | 0 B na wszystkich 6 parach |
| Pliki `.bi5` dla tych godzin | **istnieją i są puste** — downloader sprawdził i nie znalazł ticków |
| 23:00 | 34–468 B, handel śladowy |
| 25.12 00:00 | 380–1 902 B |
| Normalne obroty | dopiero 26.12 (5–18 kB) |
| Piątek 22.12 22:00 | 0 B na 6 parach — zwykłe zamknięcie tygodnia |

**Wniosek (`INFERENCE`).** Rynek stał, feed nie padł. To ten sam wzorzec co
odziedziczona pozycja `2017-12-24T22:00Z`: Wigilia wypadająca w niedzielę
opóźnia otwarcie tygodnia. Rozróżnienie opiera się na tym, że pliki istnieją
i są puste — nieudane pobranie zostawia brak pliku, nie plik zerobajtowy.

**Alternatywy.** (a) Poszerzyć kalendarz świąt o regułę „Wigilia w niedzielę"
— odrzucone: dokładanie logiki na podstawie jednej obserwacji, a kalendarz
jest celowo minimalny, żeby każdy inny brak danych pozostał podejrzany.
(b) Wyłączyć detektor dla grudnia — odrzucone: to wyciszenie, nie decyzja.
(c) Zostawić bramkę jako niezdaną — odrzucone: raport zgłaszałby znany,
wyjaśniony stan i z czasem przestałby cokolwiek znaczyć.

**Konsekwencje.** Lista akceptacji jest zamknięta i imienna; test
`test_config_accepts_exactly_the_four_audited_hours` pilnuje, żeby nie dało
się jej rozszerzyć w celu uciszenia raportu. Każda pozycja musi nieść dowód
i datę — akceptacja bez dowodu jest wyciszeniem detektora pod inną nazwą.

**Do zapamiętania przy odpieczętowaniu segmentu 2024-2026.** Dane z tamtych
lat nie przeszły jeszcze przez detektor. Wigilia wypada w niedzielę także
w 2028 r.; w samym segmencie zapieczętowanym należy spodziewać się własnych,
jeszcze nieznanych pozycji. Każda wymaga tego samego trybu: dowód, ADR, wpis.

---

## ADR-011 — T001 w prerejestrowanej postaci nie startuje; konstrukcja wymaga przeprojektowania

**Status:** ACCEPTED · 2026-09-23 · **Wykryte w:** M02 · **Zastępuje:** tabelę
szacunków w ADR-009 (sama decyzja ADR-009 pozostaje w mocy)

**Decyzja.** Prerejestracja T001 zostaje **wycofana przed uruchomieniem**.
H01 traci żywą prerejestrację i wraca do statusu `PROPOSED`. Eksperyment
zastępczy dostaje **nowe ID (T003)** i nie wolno go uruchomić, dopóki jego
prerejestracja nie spełni czterech warunków wymienionych niżej.

Wycofana prerejestracja **zostaje w `EXPERIMENTS.md`** w całości, oznaczona
`WITHDRAWN`. Nie jest usuwana ani edytowana.

**Powód.** M02 (`20260923T172201Z-fa3731`) zmierzył to, co ADR-009 kazał
zmierzyć, i wynik nie mieści się w przewidzianym przez ADR-009 schemacie
dwóch odpowiedzi.

Bramka ADR-009 czytana dosłownie daje **nierozstrzygnięcie**: blokuje tylko
przy MDE ≥ 0,08 R na obu horyzontach, a h = 3 d siada na 0,0796 R przy
własnym błędzie pomiaru ±0,0018 R.

Wiążący jest natomiast argument, który w ADR-009 nie został przewidziany
i który **trzyma przy każdym modelu niezależności par**:

| `FACT` z M02 | h = 3 d | h = 10 d |
|---|---|---|
| σ wyniku w R (zmierzona, 8 000 wejść) | 0,9165 ± 0,0103 | 0,9261 ± 0,0104 |
| σ założona w ADR-009 (dziedziczona) | 0,455 | 0,455 |
| MDE przy parach **niezależnych** (najkorzystniej) | 0,0459 | **0,0848** |
| MDE konserwatywnie (P_eff = 2,0) | 0,0796 | 0,1463 |
| `SUPPORTED` wymaga średniej powyżej | +0,032…+0,056 R | +0,059…+0,102 R |
| `FALSIFIED` wymaga średniej poniżej | −0,012…−0,036 R | −0,039…−0,082 R |

Trzy ustalenia, każde wystarczające samo:

1. **σ była dziedziczona, nie mierzona, i jest dwa razy za mała.** Tabela
   ADR-009 powstała przez przeskalowanie połowy CI `market-quant` przez √n,
   co implikuje σ = 0,455 R przy obu horyzontach. Zmierzona: 0,92 R. n_eff
   ADR-009 oszacował nieźle; pomylił się na rozrzucie.
2. **Horyzont 10 dni nie przechodzi bramki przy ŻADNYM modelu par** — nawet
   przy założeniu sześciu niezależnych rynków MDE wynosi 0,0848 R. T001
   miałby tam **mniejszą moc niż eksperyment, który miał poprawić**
   (0,146 R konserwatywnie wobec 0,097 R `market-quant`), mimo 1,8× większej
   liczby obserwacji efektywnych.
3. **Kryteria falsyfikacji T001 są w większości nieosiągalne.** Między progiem
   `FALSIFIED` a progiem `SUPPORTED` leży martwa strefa szerokości 0,064 R
   (h=3 d, najkorzystniej) do 0,185 R (h=10 d, konserwatywnie), w której
   zapada `NOT_SUPPORTED`. Sam dryf kosztowy to −0,031 R przy h = 3 d, więc
   umiarkowany, ale realny efekt trafia w tę strefę niemal na pewno.

`INFERENCE`. T001 w prerejestrowanej postaci jest eksperymentem, którego
najprawdopodobniejszym wynikiem jest `NOT_SUPPORTED` **niezależnie od tego,
czy efekt istnieje** — kosztem sześciu prób (N: 7 → 13). To jest dokładnie
scenariusz, przed którym ADR-009 miał chronić.

**Alternatywy.**

(a) *Uruchomić T001 wyłącznie przy h = 3 d, przyjmując model korelacji ze
znakiem (P_eff = 4,88).* Odrzucone: model nie został zmierzony, a przy
momentum na uniwersum zdominowanym przez czynnik USD jest prawdopodobnie zbyt
optymistyczny — gdy dolar się umacnia, `mom(EURUSD) < 0` i `mom(USDCAD) > 0`
są tym samym zakładem. Poza tym martwa strefa zostaje szeroka na 0,064 R
nawet w tym wariancie.

(b) *Obniżyć próg 0,08 R.* Odrzucone bez dyskusji: próg był prerejestrowany
w ADR-009, a zmiana po zobaczeniu 0,0796 to modyfikacja kryterium pod wynik.

(c) *Rozszerzyć M02 o pomiar korelacji zwrotów przemnożonych przez znak cechy.*
Odrzucone na tym etapie: wymaga policzenia `sign(mom_k)` przed prerejestrowanym
uruchomieniem, a nawet domknięcie nawiasu [2,0; 6,0] po najkorzystniejszej
stronie nie ratuje h = 10 d ani nie zwęża martwej strefy poniżej 0,064 R.
Pomiar zostaje jako możliwy do wznowienia, gdy przeprojektowana konstrukcja
będzie od niego faktycznie zależeć.

(d) *Uruchomić T001 bez zmian i przyjąć `NOT_SUPPORTED` jako prawdopodobny
wynik.* Odrzucone: „nie znaleziono przewagi" jest pełnoprawnym wynikiem tylko
wtedy, gdy przyrząd miał szansę ją zobaczyć. Tutaj nie ma, a próby liczą się
do DSR niezależnie od tego, czego dowiodły.

**Warunki, które musi spełnić prerejestracja T003.**

1. **Deklaracja modelu niezależności par**, jawna i uzasadniona, wraz z liczbą
   P_eff wchodzącą do obliczenia mocy. Milczenie w tej sprawie nie jest już
   dopuszczalne — M02 pokazał, że to wybór wart czynnika 1,7 na MDE.
2. **Wyliczenie mocy z σ ZMIERZONEJ dla zadeklarowanej geometrii barier**,
   nie odziedziczonej i nie przeskalowanej. σ zależy od geometrii, więc każda
   zmiana SL/TP unieważnia poprzedni pomiar i wymaga nowego.
3. **Wykazanie, że progi falsyfikacji są osiągalne** przy tej mocy: martwa
   strefa musi być wypisana w prerejestracji razem z uzasadnieniem, dlaczego
   efekt o interesującej wielkości w nią nie wpada.
4. **Rozstrzygnięcie granicy okien wychodzących poza segment.** Prerejestracja
   T001 mówiła „decyzje do 2021-12-31" i nie mówiła, co z `t1` w styczniu 2022,
   czyli w OOS. M02 przyjął wariant nietykający OOS (−98 decyzji na parę).

**Zabezpieczenie przed obchodzeniem prerejestracji.** Wycofanie T001 jest
dopuszczalne wyłącznie dlatego, że **nie zaobserwowano niczego, co dotyczy
H01**: M02 był kontrolą `control`, nie liczył `mom_k` ani jego znaku, sprawdzał
wyłącznie, czy cecha jest określona. Gdyby jakakolwiek wielkość zależna od
treści hipotezy została obejrzana, wycofanie prerejestracji byłoby wyborem
kryterium pod wynik i nie wolno by go było wykonać. Każde przyszłe wycofanie
prerejestracji wymaga tego samego dowodu, zapisanego w ADR.

**Konsekwencje.**

* T001 → `WITHDRAWN`, nieuruchomiony. **N pozostaje 7** — rejestr liczy wpisy
  `start`, a takiego nie było.
* H01 → `PROPOSED`. Hipoteza żyje, jej protokół nie.
* Tabela szacunków w ADR-009 przestaje być podstawą czegokolwiek. Sam ADR-009
  — wymóg audytu mocy przed eksperymentem — zostaje w mocy i właśnie zadziałał.
* M03 i M04 pozostają konieczne i nie zależą od kształtu T003.
* Dług M01 (warstwa etykiet, dwa testy na look-ahead) jest niezmieniony.

---

## ADR-012 — M04 nie może wystartować przed zamrożeniem prerejestracji T003; zmienia postać na test z zasianym błędem

**Status:** ACCEPTED · 2026-09-23 · **Wykryte w:** M03 · **Konsekwencja:** ADR-011

**Decyzja.** Dwie rzeczy naraz:

1. **M04 w postaci zaplanowanej w fazie 0 nie może zostać uruchomiony**,
   dopóki prerejestracja T003 nie jest zamrożona i zahashowana.
2. **M04 zmienia postać**: zamiast porównywać `mom_k` z `mom_k` postarzonym
   o jeden bar, sprawdza przyrząd na **cechach syntetycznych o znanej
   zawartości informacyjnej**. Porównanie na cesze prawdziwej przenosi się
   do wnętrza T003 jako prerejestrowane ramię kontrolne.

**Powód — punkt 1.** M04 miał porównać wynik baseline z wynikiem cech
postarzonych o jeden bar. Baseline to `mom_k` puszczony przez symulator,
czyli **ocena sygnału H01**. Z tego płyną dwie konsekwencje, z których
druga jest nieodwracalna:

* Rejestr prób klasyfikuje takie uruchomienie jako `strategy`, nie `control`
  — „kontrola, która ocenia sygnał, jest przebiegiem `strategy` niezależnie
  od celu" (`harness/registry.py`, reguła odziedziczona z ADR-029). M04
  liczyłby się więc do N, wbrew założeniu „seria M nie liczy się do N".
* M04 pokazałby expectancy H01 **zanim T003 zostanie prerejestrowany**.
  Prerejestracja pisana po zobaczeniu wyniku nie jest prerejestracją.

**Czego nie zauważył ADR-011.** W planie z fazy 0 kolejność M04 → T001 była
bezpieczna, bo T001 był już prerejestrowany i zamrożony — zobaczenie wyniku
nie mogło zmienić deklaracji, która już istniała. **Wycofanie T001 usunęło
tę ochronę.** Od momentu, w którym H01 nie ma żywej prerejestracji, każdy
przebieg dotykający `mom_k` skaża przyszłą prerejestrację. ADR-011 tego nie
zapisał; ADR-012 to domyka.

**Powód — punkt 2.** Pytanie M04 brzmi „czy w pipelinie jest przesunięcie
o jeden bar", a nie „czy momentum działa". Konstrukcja z fazy 0 mieszała
te dwa pytania: porównywała dwa warianty cechy, której zawartość
informacyjna jest **nieznana**, więc oczekiwany kierunek różnicy też był
nieznany. Dlatego anomalia u poprzednika (wynik z cechami postarzonymi
**lepszy**: −0,0268 wobec −0,0560 R) nie dała się rozstrzygnąć i została
odłożona jako szum.

Na cechach syntetycznych oczekiwany kierunek jest znany **z konstrukcji**:

| Ramię | Cecha | Wynik, który MUSI wyjść |
|---|---|---|
| szum | kierunek z ziarna, zero informacji z cen | ≈ −koszt (to samo co M03) |
| wyrocznia | kierunek = znak faktycznego zwrotu przez okno | silnie dodatni |
| wyrocznia postarzona | ta sama, ale z okna zamkniętego przed decyzją | ≈ −koszt |

Ramię „wyrocznia" jest **kontrolą dodatnią**: dowodzi, że przyrząd w ogóle
potrafi zobaczyć informację, gdy ta jest. Konstrukcja z fazy 0 takiej kontroli
nie miała — sprawdzała tylko, czy przyrząd czegoś NIE widzi, a to spełnia
również przyrząd zepsuty na głucho.

**Alternatywy.**

(a) *Uruchomić M04 jak zaplanowano i przyjąć, że liczy się do N.* Odrzucone:
koszt w liczniku byłby najmniejszym problemem. Skażenia prerejestracji T003
nie da się cofnąć ani zmierzyć.

(b) *Uruchomić M04 po zamrożeniu prerejestracji T003, w postaci z fazy 0.*
Odrzucone jako krok osobny, przyjęte jako **ramię wewnątrz T003**: jeśli
cecha i tak musi być policzona, osobny przebieg wyłącznie po to, żeby ją
porównać z jej własnym opóźnieniem, spala próbę za diagnostykę, która
należy do przebiegu głównego.

(c) *Zrezygnować z M04, skoro testy jednostkowe na wyrównanie znaczników już
istnieją* (`test_grid.py`, `test_volatility.py`, trzy testy w
`test_simulator.py` przywrócone w M03). Odrzucone: testy jednostkowe pilnują
punktów, w których wyrównanie jest **jawne**. M04 pilnuje **złożenia** —
i tylko on może wykryć błąd powstały na styku modułów, z których każdy
z osobna jest poprawny.

**Konsekwencje.**

* M04 → `BLOCKED`, z warunkiem odblokowania: zamrożona prerejestracja T003
  **albo** przejście na postać z cechami syntetycznymi. Ta druga droga jest
  otwarta od zaraz, bo nie dotyka `mom_k`.
* M04 w nowej postaci pozostaje `control` i **nie liczy się do N**. Gdyby
  kiedykolwiek wrócił do porównywania cech prawdziwych, staje się `strategy`.
* Porównanie „cecha vs cecha postarzona" staje się **obowiązkowym ramieniem
  prerejestracji T003**, z kryterium zapisanym przed uruchomieniem. To piąty
  warunek T003, obok czterech z ADR-011.
* Reguła ogólna, szersza niż M04: **dopóki hipoteza nie ma żywej, zamrożonej
  prerejestracji, żaden przebieg nie może dotknąć jej cechy** — także
  przebieg nazwany kontrolą. Klasyfikacja `control`/`strategy` idzie za tym,
  co przebieg ogląda, nie za tym, po co go uruchomiono.

---

## ADR-013 — M04 bez ramienia „wyrocznia postarzona"; pytanie o wyrównanie przechodzi na dane syntetyczne

**Status:** ACCEPTED · 2026-09-23 · **Wykryte w:** implementacji M04
· **Koryguje:** ADR-012 (tabela ramion)

**Decyzja.** M04 został uruchomiony z **dwoma** skrajnymi ramionami —
szum (`p = 0,5`) i wyrocznia (`p = 1,0`) — plus pełną krzywą pośrednią.
Ramię **„wyrocznia postarzona" nie powstało**. Pytanie o przesunięcie
o jeden bar przechodzi w całości na testy na danych syntetycznych.

**Powód.** ADR-012 definiował ramię postarzone jako „ta sama wyrocznia, ale
z okna zamkniętego przed decyzją". Przy implementacji okazało się, że to jest
**znak zwrotu z przeszłości**, czyli cecha momentum. Przy h = 3 d byłby to
niemal dokładnie `mom_72`. Uruchomienie takiego ramienia łamałoby regułę
ogólną zapisaną w tym samym ADR-012: *dopóki hipoteza nie ma żywej,
zamrożonej prerejestracji, żaden przebieg nie może dotknąć jej cechy*.

ADR-012 był więc wewnętrznie sprzeczny: zakazywał w konkluzji tego, co
zalecał w tabeli. Sprzeczność wyszła dopiero przy pisaniu kodu.

**Czym zastąpiono.** Dwiema rzeczami, razem mocniejszymi od usuniętego
ramienia:

1. **Krzywa czułości zamiast trzeciego punktu.** Odegranie obu stron z tego
   samego momentu daje `E(p)` dla dowolnego `p` bez dodatkowych symulacji.
   Zamiast trzech punktów mamy funkcję — i dwa progi, które z niej wynikają
   (opłacalności i wykrywalności).
2. **Wyrównanie znaczników na danych syntetycznych**, gdzie poprawna
   odpowiedź jest znana z konstrukcji, a nie zgadywana z rynku:
   `test_grid.py` (cena odniesienia, cena wyjścia), `test_volatility.py`
   (granica dobowa ATR), `test_simulator.py` (okno transakcji, trzy testy),
   `test_entries.py` (złożenie całej ścieżki na zasianym ruchu ceny).

**Dlaczego to lepsze miejsce na to pytanie.** Przebieg na prawdziwych danych
odpowiada „czy wynik wyszedł inny", a nie „czy wyrównanie jest poprawne" —
różnicę trzeba dopiero interpretować, i to właśnie dlatego anomalia
u poprzednika (wynik z cechami postarzonymi **lepszy**: −0,0268 wobec
−0,0560 R) nigdy nie została rozstrzygnięta. Na danych syntetycznych
przesunięcie o jeden bar daje odpowiedź **przeciwną**, nie „nieco inną",
a test biegnie przy każdym uruchomieniu pakietu, nie raz.

**Alternatywy.** (a) *Zbudować ramię postarzone z cechy niebędącej momentum.*
Odrzucone: każda reguła kierunkowa zbudowana z przeszłych cen jest jakąś
cechą, a wybieranie „takiej, która nie wygląda jak H01" to dokładnie ten
rodzaj uznaniowości, którego projekt ma unikać. (b) *Uruchomić ramię
postarzone i uznać, że `mom_72` to nie `mom_24/120/480`.* Odrzucone: ta sama
postać funkcyjna, ta sama rodzina, a ocena „to wystarczająco inna cecha"
byłaby wyłącznie moją.

**Konsekwencje.** Reguła ogólna z ADR-012 zostaje bez zmian i właśnie
zadziałała przeciwko zaleceniu z tego samego ADR-u — to jest zachowanie
pożądane. Ramię „cecha vs cecha postarzona" pozostaje **warunkiem 5
prerejestracji T003**, gdzie cecha i tak musi być policzona.

---

## ADR-014 — Model niezależności par dla warstwy B i geometria barier T003: P_eff = 2,00, geometria bez zmian

**Status:** ACCEPTED · 2026-09-24 · **Rozstrzyga:** warunki 1 i 2
prerejestracji T003 (ADR-011) · **Opiera się na:** M02, M04

**Decyzja.** Dwie wartości, obie zamrożone przed prerejestracją T003:

1. **Model niezależności par: `P_eff = 2,00`** — model na `|ρ|`
   (`P² / ΣΣ|ρ_ij|`, zmierzony w M02). Dotyczy **warstwy B**, czyli każdej
   statystyki uśredniającej wynik przemnożony przez znak cechy.
2. **Geometria barier bez zmian**: SL/TP = 1,1 / 2,2 × `atr_d1_14` przy
   h = 3 d, 2,0 / 4,0 przy h = 10 d — dokładnie ta, dla której M02 zmierzył σ,
   a M03 i M04 skalibrowały przyrząd.

**Powód — punkt 1.** Nawias [2,0; 6,0] rozstrzyga się na pytaniu, czy znak
`mom_k` jest skorelowany z czynnikiem USD. Model ze znakiem (`P_eff = 4,76`)
zakłada, że nie jest. **Mechanizm H01 zakłada, że jest**: informacja, która
dyfunduje przez majorsy FX, to w przeważającej części dolar, a wtedy
`mom(EURUSD) < 0` i `mom(USDCAD) > 0` są jednym zakładem, nie dwoma. Przy
średniej `ρ` = 0,052 i średniej `|ρ|` = 0,401 to nie jest różnica niuansowa.

Model na `|ρ|` nie jest więc pesymistycznym krańcem nawiasu — jest modelem
**implikowanym przez testowaną hipotezę**. Wybranie 4,76 byłoby przyjęciem
założenia sprzecznego z H01 po to, żeby H01 przeszło własną bramkę.

Cena decyzji jest przy tym mniejsza, niż sugeruje czynnik 1,7 na MDE, bo
wiążący jest próg trafności kierunku, nie sama liczba w R:

| P_eff | MDE (h = 3 d) | Próg wykrywalności |
|---|---|---|
| 2,00 | 0,0795 R | 57,33% |
| 4,76 | 0,0516 R | 55,35% |
| 6,00 | 0,0459 R | 54,95% |

Próg opłacalności to 51,72%. **Oba krańce nawiasu leżą poza pasmem, w którym
może leżeć realna przewaga momentum** — nawias wart 1,7× na MDE jest wart zero
na werdykcie. To przestaje być wyborem, który cokolwiek kupuje.

**Powód — punkt 2.** M04 pokazał, że przy obecnej geometrii bariery
rozstrzygają 16% przypadków, a średni |ruch| to 40% dystansu do TP. Nasuwa się
wniosek, że geometrię trzeba zmienić. **Pomiar mówi, że nie warto.** Policzone
na `runs/20260923T181510Z-963686/m04_paired_h3.parquet`, czyli bez nowego
przebiegu: bariery obcinają σ i wzmocnienie `G = E[trafna] − E[nietrafna]`
w tym samym tempie, więc iloraz `σ/G` — jedyna wielkość, która wchodzi do progu
trafności — jest niezmiennikiem geometrii:

| h = 3 d | G | σ | σ/G | Δ progu trafności |
|---|---|---|---|---|
| obecna geometria | 1,4205 | 0,9121 | 0,6421 | — |
| **bariery usunięte w całości** | 1,6193 | 1,0528 | 0,6502 | **+0,07 pp** |
| bariery usunięte, h = 10 d | 1,5977 | 1,0671 | 0,6679 | +0,20 pp |

Cała zmiana geometrii — aż do jej zniesienia — jest warta **siódmą część
punktu procentowego** trafności, i to na niekorzyść. Za to unieważnia σ z M02
i kalibrację M03/M04 (zgodność 0,0007 R), czyli wymusza powtórzenie audytu
mocy. Najgorszy możliwy stosunek kosztu do zysku.

**Trzy argumenty dopinają punkt 2.**

* **Wariant bez barier już jest w prerejestracji** — to target A (ADR-003).
  Nie trzeba zmieniać geometrii, żeby go dostać; wchodzi tym samym przebiegiem.
* **Geometria barier JEST warstwą ryzyka.** Strojenie jej pod wykrywalność to
  dobór warstwy ryzyka tak, żeby test hipotezy przeszedł — dokładnie to, co
  zakazuje ADR-002 i co w `market-quant` skasowało 98,6% próby.
* M04 ustalił, że **straty na geometrii nie ma, jest bezczynność**. W pomiarze
  na wszystkich barach (ADR-002) bezczynność nie kosztuje nic — nie ma
  kapitału, który by stał.

**Alternatywy.** (a) *`P_eff = 4,76`, bo nawias jest domknięty i punkt środkowy
jest neutralny.* Odrzucone: nie jest neutralny, jest sprzeczny z mechanizmem
H01, a jego jedyną obserwowalną konsekwencją byłoby przejście bramki.
(b) *Zmierzyć znak cechy i domknąć nawias.* Odrzucone: to policzenie `mom_k`,
zakazane przez ADR-012 do czasu zamrożenia T003. (c) *Rozluźnić bariery do
3,0/6,0 × ATR, żeby przestały wiązać.* Odrzucone: pomiar wyżej pokazuje, że
kraniec tego kierunku — brak barier — daje +0,07 pp. (d) *Zacieśnić bariery,
żeby wiązały częściej.* Odrzucone bez pomiaru, świadomie: wymagałoby nowego
przebiegu symulatora, a dwa zmierzone punkty odległe o 85% obcięcia ruchu dają
`σ/G` różniące się o 1%. Gdyby zacieśnienie miało kiedyś wrócić, wraca jako
osobny ADR z własnym pomiarem, nie jako poprawka do tego.

**Konsekwencje.**

* Warunek 2 prerejestracji T003 jest spełniony **bez nowego pomiaru σ** —
  zadeklarowana geometria jest tą, dla której σ zmierzono.
* Prerejestracja T003 raportuje **różnicę A − B jako pomiar tego, co bariery
  kosztują**. Martwy parametr zamienia się w liczbę, zamiast zostać białą plamą.
* Przebieg T003 raportuje **zrealizowane** `E[sign_i·sign_j·ρ_ij]` i wynikające
  z niego P_eff jako diagnostykę, która **nie może zmienić werdyktu**.
  Informuje następny eksperyment, nie ten.
* `P_eff = 2,00` jest wyprowadzone dla statystyk mnożonych przez znak.
  **Nie przenosi się automatycznie na warstwę A** — patrz ADR-015.

---

## ADR-015 — Kryteria falsyfikacji T003 wracają na warstwę A; warstwa B jest wyceną, nie testem

**Status:** ACCEPTED · 2026-09-24 · **Przywraca:** ADR-003
· **Koryguje:** konstrukcję odziedziczoną po T001 · **Rozstrzyga:** warunek 3
prerejestracji T003 (ADR-011)

**Decyzja.** Trzy rzeczy:

1. **Kryteria falsyfikacji T003 stoją na warstwie A** — na relacji między
   `mom_k` a zwrotem w przód znormalizowanym `atr_d1_14`. Metryka główna jest
   statystyką tej relacji, nie expectancy w net R.
2. **Warstwa B — net R z symulacji tickowej — jest raportowana zawsze**, ze
   wszystkimi osiami i mnożnikami kosztu, ale jako **wycena ekonomiczna**,
   nie jako instrument falsyfikacji. Uruchamiana zgodnie z ADR-003: pełny
   przebieg B tylko tam, gdzie A pokazała sygnał.
3. **Siatka T003 to 3 komórki, nie 6**: k ∈ {24, 120, 480} × h = **3 d**.
   Horyzont 10 d wypada. N: 7 → **10**.

**Powód — punkt 1. To nie jest przebudowa, to przywrócenie ADR-003.**
ADR-003 przydzielił warstwom role jednoznacznie: A to *„Wykrywanie. Maksymalna
moc"*, B to *„Decyzja"*, i zapisał wprost: *„Krok B uruchamiamy tylko wtedy,
gdy krok A pokazał sygnał"* oraz *„jeśli warstwa A jest zerowa przy wysokiej
mocy, warstwa B nie może być dodatnia i zatrzymujemy się tanio, nie spalając
prób"*.

Prerejestracja T001 postawiła **wszystkie** kryteria falsyfikacji na expectancy
w net R, czyli na warstwie B. T003 odziedziczył to bez zmiany. To jest
odwrócenie ADR-003 — a w razie sprzeczności wygrywa `DECISIONS.md`.

**To odwrócenie JEST źródłem martwej strefy.** Nie geometria, nie model par:

| h = 3 d, P_eff = 2,00 | próg wykrywalności | martwa strefa |
|---|---|---|
| warstwa B — expectancy w R (konstrukcja T001) | 57,33% | **5,61 pp** |
| **warstwa A — relacja `mom_k` ↔ `fwd_atr`** | **≈ 52,8%** | **≈ 1,05 pp** |

Mechanizm straty jest ten sam, który ADR-003 §2 zarzucił targetowi binarnemu —
*„etykieta 0/1 wyrzuca informację o sile ruchu (…) statystycznie to strata mocy
przy zerowym zysku"* — tyle że ADR-003 nie zauważył, że **expectancy po znaku
ma tę samą wadę w połowie**: `sign(mom_k)` wyrzuca magnitudę cechy, a bariery
i koszty wyrzucają magnitudę wyniku. Warstwa A zachowuje obie.

**Kryteria stają się TRUDNIEJSZE do przejścia, nie łatwiejsze.** To jest
zabezpieczenie, bez którego ta decyzja byłaby doborem kryterium pod wynik.
Przy warstwie B `NOT_SUPPORTED` zapadało niezależnie od tego, czy efekt
istnieje — był to wynik domyślny. Przy warstwie A `NOT_SUPPORTED` zaczyna
wykluczać większość pasma, w którym przewaga momentum mogłaby realnie leżeć.
Zmiana podnosi cenę wyniku negatywnego, zamiast ją obniżać.

**Dopuszczalność.** T003 **nie jest prerejestrowany i nigdy nie ruszył**.
Żaden przebieg nie dotknął `mom_k` (ADR-012 tego pilnuje, ADR-013 wymusił to
przeciwko własnemu zaleceniu ADR-012). Nie oglądano więc niczego, co dotyczy
H01 — to ten sam warunek, który ADR-011 postawił wycofaniu T001, i jest
spełniony tak samo.

**Powód — punkt 3.** Ustalenie 3 z M03: po doliczeniu swapu h = 10 d kosztuje
na transakcję tyle samo co h = 3 d (0,0392 wobec 0,0422 R), dając 3× mniej
obserwacji niezależnych. Przewaga kosztowa długiego horyzontu była artefaktem
pominięcia swapu. Na warstwie A h = 10 d też nie ma szans: próg wykrywalności
**55,07%** wobec 52,77% przy h = 3 d. Trzy komórki na gwarantowany
`NOT_SUPPORTED` to spalenie trzech prób za zero informacji — dokładnie ten
rachunek, który ADR-011 przeprowadził dla T001.

**Czego ta decyzja NIE rozstrzyga.** `P_eff = 2,00` z ADR-014 było wyprowadzone
dla statystyk mnożonych przez znak. Dla statystyki relacji zależność
międzyparowa jest **inną wielkością**: pod H0 kowariancja estymatorów na parach
`i` i `j` idzie jak iloczyn `ρ^cecha_ij · ρ^zwrot_ij`, a nie jak `|ρ^zwrot_ij|`.
Przeliczone na macierzy z M02 daje to `P_eff` w przedziale **[2,00; 6,00]**
z wartością oczekiwaną **3,08** przy `ρ^cecha = ρ^zwrot`. **M02 tego nie
mierzył.** Przyjęcie 3,08 na oko byłoby powtórzeniem błędu, który M02 wykrył
przy σ — odziedziczeniem liczby zamiast jej pomiaru, co kosztowało T001.

Stąd **M05: pomiar rozkładu zerowego metryki głównej warstwy A** na
rzeczywistej siatce decyzyjnej, cechami zastępczymi bez treści hipotezy
(`kind = control`, `mom_k` nietknięty). Prerejestracja T003 nie może zostać
zamrożona przed M05.

M05 rozstrzyga też osiągalność `FALSIFIED`. Kryterium równoważności — CI95
w całości wewnątrz ±ρ odpowiadającego progowi opłacalności — wymaga
`n_eff ≈ 1 317`; przy `n_eff = 1 042` brakuje **12% na połowie CI**. To nie
jest „strukturalnie nieosiągalne" jak w T001, tylko *blisko*: jeśli M05
zmierzy dla warstwy A `n_eff` choćby 1,3× większe, `FALSIFIED` wraca do
zasięgu i T003 odzyskuje pełną trójstanową przestrzeń wyników. Jeśli nie —
prerejestracja **deklaruje to wprost**, a produktem T003 jest ograniczenie
górne, nie werdykt trójstanowy.

**Alternatywy.** (a) *Zostawić warstwę B jako test i uruchomić T003 na
3 komórkach.* Odrzucone: ograniczenie „momentum daje mniej niż 57,3%
trafności" nie wyklucza niczego, co ktokolwiek twierdził, a jego cena to trzy
próby. Byłoby to też pierwsze złamanie reguły, którą ADR-011 ustanowił dzień
wcześniej. (b) *Obniżyć próg `FALSIFIED` do osiągalnego przy warstwie B
δ ≈ 0,06 R.* Odrzucone: oznaczałoby nazywanie realnej przewagi 53% trafności
„falsyfikacją" — fałszywy negatyw przebrany za wniosek, gorszy niż
`NOT_SUPPORTED`. (c) *Dołożyć segment OOS 2022–2023, żeby kupić n_eff.*
Odrzucone: +33% `n_eff` to +0,8 pp na progu, za cenę jedynego segmentu
zostawionego na walidację. Zły kurs. (d) *Porzucić H01.* Odrzucone: H01 nigdy
nie było zmierzone osobno — `market-quant` mierzył je wyłącznie w koniunkcji
z H02, na 172 obserwacjach efektywnych. Brak pomiaru to nie jest dowód.

**Konsekwencje.**

* Warunek 3 prerejestracji T003 przechodzi na M05; bez niego nie ma zamrożenia.
* Warstwa B kosztuje **zero prób** w scenariuszu zerowym — tak, jak ADR-003
  to zaprojektował („zatrzymujemy się tanio").
* Ograniczenie najgłębsze **nie jest statystyczne**: sześć majorsów przy
  średniej `|ρ|` = 0,401 to sześć odmian jednego zakładu o dolara, i stąd
  `P_eff` bliskie 2, a nie 6. Jedyna dźwignia ruszająca to o czynnik to
  instrumenty spoza czynnika USD — kohorta replikacyjna z ADR-008, która ma
  zero bajtów. **Zdobycie tych danych kupuje H01 więcej mocy niż cokolwiek,
  co da się zapisać w prerejestracji**, i przy okazji odblokowuje `SURVIVED`.

---

## ADR-016 — Marża swapu nie wchodzi do `CostModel`; pełny koszt składa się na wyniku symulacji

**Status:** ACCEPTED · 2026-09-24 · **Zmienia:** warunek 6 prerejestracji T003
(ADR-011) w części dotyczącej sposobu wpięcia · **Opiera się na:** M03, M06

**Decyzja.** Człon finansowania **nie zostaje wpięty w `CostModel`**. Pełny
koszt składa się w `src/execution/costs.py`, na gotowym `TradeResult`, przez
całą oś marży naraz. `research/labels.py::layer_b` wymaga osi marży jako
argumentu **bez wartości domyślnej**, a `costs.reportable()` rzuca wyjątkiem
na ramce bez kolumn `r_net_<marża>`.

**Powód.** PROGRESS i nota w prerejestracji T003 zapowiadały „wpięcie swapu
w `CostModel` + powtórzenie kalibracji M03". Przy implementacji okazało się,
że wpięcie jest **niewykonalne bez złamania prerejestracji**, a przy tym
niepotrzebne:

1. **Marża jest osią, nie punktem.** Prerejestracja T003 (`layer_b.costs.swap.
   margin_axis`) wymaga trzech wartości — 0,5% / 1% / 2% — z jednego
   przebiegu. Liczba wpisana w `CostModel` wymusiłaby trzy symulacje tej samej
   próby. Wpięcie realizowałoby więc `included: true` kosztem `margin_axis`,
   czyli spełniało jedną deklarację, łamiąc drugą.
2. **Dokładność jest identyczna, i to jest zmierzone.** Koszt finansowania
   zależy wyłącznie od ceny, dystansu stopu i czasów wejścia/wyjścia — wszystkie
   są w `TradeResult`. M06 policzył swap z `TradeResult` i porównał
   z wartościami, które M03 policzył własną pętlą, na 197 847 transakcjach:
   **identyczne co do bitu**, `max_abs_diff = 0` przy każdej z trzech marż.
3. **Symulator jest zweryfikowany co do bitu** wobec `market-quant` (M01)
   i skalibrowany przez M03 oraz M04 (zgodność 0,0007 R). Dołożenie mu członu
   kosztu unieważnia obie weryfikacje w zamian za zero dokładności.

**Czego to NIE zmienia w prerejestracji.** Wiążąca treść warunku 6 brzmi
`included: true` plus oś marży, i jest spełniona co do joty: **żadna liczba
warstwy B nie może powstać bez członu finansowania**, bo `layer_b` nie ma
domyślnej marży, a raportowanie bez kolumn net rzuca wyjątkiem. Zmienia się
wyłącznie to, co nota w prerejestracji mówiła o SPOSOBIE — a nota opisywała
przewidywaną implementację, nie deklarację metodologiczną.

**Wynik M06** (`20260924T141045Z-c94360`, `control`, N bez zmian). Zero
przyrządu przy **pełnym** koszcie, block bootstrap po dniu:

| h | marża | E[net] | pełny koszt | luka | w SE |
|---|---|---|---|---|---|
| 3 d | 1,0% | −0,0373 | 0,0422 | +0,0049 | +0,96 |
| 10 d | 1,0% | −0,0414 | 0,0392 | −0,0022 | −0,27 |

**Luka kalibracji jest niezmiennicza względem marży** — +0,00490 R przy
0,5%, 1% i 2% jednakowo. To nie jest wynik empiryczny, tylko tożsamość: swap
odejmuje się od obu stron równania naraz. Zapisane wprost, żeby nikt nie
próbował mierzyć tego drugi raz i nie wziął niezmienniczości za potwierdzenie.

**Konwencja SE ma znaczenie.** M06 używa block bootstrapu po dniu
(`validation.bootstrap`), tak jak M03. Naiwne SE po transakcjach dałoby
0,00290 zamiast 0,00507 — **1,75× za wąsko** — i zamieniłoby lukę 0,96 SE
w lukę 1,69 SE, czyli przejście w niepowodzenie. Nakładanie okien wynikowych
nie jest szczegółem raportowania.

**Alternatywy.** (a) *Wpiąć jedną marżę (1%) i zrezygnować z osi.* Odrzucone:
łamie prerejestrację, a M03 pokazał, że wynik zależny od wartości punktowej
marży jest nieważny — stąd oś, a nie punkt. (b) *Wpiąć oś, zwracając trzy
wyniki z symulatora.* Odrzucone: `TradeResult` przestaje być wynikiem jednej
transakcji, a M01/M03/M04 tracą weryfikację. (c) *Zostawić jak było, bo M03
i tak liczył swap.* Odrzucone: M03 liczył go z konwencji, nie z przymusu —
a brak swapu został wykryty w module, który miał testy i wyglądał na
kompletny. Pominięcie ma wymagać skasowania kolumny, nie zapomnienia o niej.

**Konsekwencje.**

* Warunek 6 prerejestracji T003 jest **spełniony**. Oba warunki startu T003
  zamknięte; zostaje samo uruchomienie.
* `M06` nie jest nową symulacją i nie mógł nią być: te same transakcje przy
  tym samym ziarnie, o godzinę dłużej, bez jednej nowej obserwacji.
* Zero, wobec którego mierzy się warstwa B T003, to **−0,0422 R** (h = 3 d,
  marża 1%), nie −0,0297 R modelu niepełnego.

---

## ADR-017 — DSR wpięty jako diagnostyka z nawiasem `V[SR]`; deflacja deklarowana przed zamrożeniem

**Status:** ACCEPTED · 2026-09-24 · **Wykonuje:** ADR-004 · **Wykryte w:**
audycie modułów walidacji

**Decyzja.** Trzy rzeczy:

1. **DSR jest liczony** — `src/validation/deflation.py` wpina `dsr.py` w rejestr
   prób. `N` pochodzi z `trials.jsonl`, nie z konfiguracji.
2. **`V[SR]` jest nawiasem, nie punktem**, a raport podaje DSR na obu końcach.
3. **Dla T003 deflacja jest DIAGNOSTYKĄ i nie zmienia werdyktu.** Dla każdej
   przyszłej prerejestracji deflacja musi być zadeklarowana **przed**
   zamrożeniem.

**Powód — punkt 1.** ADR-004 ustanowił `N = 7` odziedziczonych prób
z uzasadnieniem, że „poprzeczka DSR startuje podwyższona". Poprzeczka nie
startowała wcale: `dsr.py` i `pbo.py` przyszły z portem (ADR-005) i do
2026-09-24 **nie importował ich żaden moduł ani żaden skrypt**. Licznik był
prawdziwy i pilnowany, a wielkość, dla której go prowadzono, nie była liczona.
To jest ta sama klasa usterki co brak swapu w `CostModel` (M03): moduł
istniał, miał testy i wyglądał na wpięty.

**Powód — punkt 2.** `deflated_sharpe()` potrzebuje `V[SR]` — wariancji
Sharpe'ów **między próbami**. Dla 7 prób odziedziczonych mamy liczbę, nie
mamy ich Sharpe'ów (ADR-004 przeniósł licznik, nie wyniki). Wariancji nie da
się więc zmierzyć, a podstawienie jednej liczby byłoby zgadywaniem przebranym
za pomiar — dokładnie tym, co M02 wykrył przy σ. Stąd nawias, jak przy `P_eff`
w ADR-014:

| Koniec | Skąd | Kierunek błędu |
|---|---|---|
| dolny | rozrzut Sharpe'ów komórek faktycznie uruchomionych | **zaniża** — komórek jest mniej niż prób i są do siebie podobne |
| górny | wariancja samego estymatora Sharpe'a (Lo 2002, z wyższymi momentami) | **zawyża** — traktuje szum estymacji jak rozrzut między próbami |

Raportujemy oba i pytanie „czy wynik przeżywa **oba** końce".

**Powód — punkt 3.** Kryteria falsyfikacji T003 zostały zamrożone
(`sha256 c832dcdc…`) **przed** powstaniem tego modułu i mówią o korekcie Holma
na trzy komórki, nie o deflacji o próby odziedziczone. Dopisanie deflacji do
kryteriów po zamrożeniu byłoby zmianą prerejestracji, czyli nowym
eksperymentem — niezależnie od tego, że zmiana idzie w stronę **surowszą**.

Deflacja może wyłącznie **osłabić** odczyt wyniku pozytywnego, nigdy go
wzmocnić, i w tę stronę wolno ją raportować obok werdyktu. Gdyby T003 wyszedł
`SUPPORTED`, a DSR nie przeżywał obu końców nawiasu, raport ma to pokazać —
i to jest cała różnica między „diagnostyka" a „nie liczymy tego".

**Luka, którą to odsłania.** Prerejestracja T003 **nie deklaruje deflacji**,
choć ADR-004 zapowiadał podwyższoną poprzeczkę. Nie unieważnia to T003:
kryteria są wewnętrznie spójne, osiągalne (M05) i uwzględniają wielokrotność
w obrębie przebiegu (Holm na 3 komórki). Nie uwzględniają wielokrotności
**między przebiegami** — 7 spojrzeń poprzednika na ten sam segment. Stąd
reguła ogólna: **każda przyszła prerejestracja deklaruje deflację przed
zamrożeniem**, tak jak deklaruje model niezależności par i osiągalność progów.

**Alternatywy.** (a) *Zmienić kryteria T003 i dołożyć deflację.* Odrzucone:
zmiana po zamrożeniu to nowy eksperyment, a reguła nie ma wyjątku „gdy zmiana
jest surowsza" — taki wyjątek jest furtką, bo surowość ocenia się po wyniku.
(b) *Podstawić `V[SR]` z literatury.* Odrzucone: to nie jest wielkość
uniwersalna, zależy od rodziny wariantów. (c) *Nie liczyć DSR, skoro warstwa
A nie jest Sharpe'em.* Odrzucone: warstwa B **jest** serią zwrotów i to na
niej stoi wycena; brak deflacji tam oznaczałby, że jedyna liczba nadająca się
do decyzji ekonomicznej jest nieskorygowana o 10 spojrzeń.

**Konsekwencje.**

* DSR liczy się wyłącznie tam, gdzie uruchomiono warstwę B — czyli tam, gdzie
  warstwa A pokazała sygnał (ADR-003). Przy wyniku zerowym nie ma Sharpe'a
  i nie ma czego deflować.
* `n_obs` do DSR to **liczba obserwacji efektywnych** z M05, nie liczba
  wierszy. Przy nakładaniu ~99% ta druga zawyżyłaby statystykę o rząd
  wielkości.
* `pbo.py` nadal nie jest wpięty. PBO wymaga macierzy wyników wielu wariantów
  na wielu podokresach, a T003 raportuje trzy komórki bez dopasowania modelu
  — nie ma z czego jej zbudować. Wpięcie należy do pierwszego eksperymentu,
  który będzie cokolwiek dopasowywał, i ma być zadeklarowane w jego
  prerejestracji.

---

## ADR-018 — Kohorta replikacyjna zostaje kohortą replikacyjną; aparatura odmawia instrumentów nieskalibrowanych

**Status:** ACCEPTED · 2026-09-24 · **Potwierdza:** ADR-008
· **Prostuje uwagę w:** ADR-015 (sekcja Konsekwencje)

**Decyzja.** Dwie rzeczy:

1. **XAUUSD, WTI, SPX500 i DAX pozostają wyłącznie kohortą replikacyjną.**
   Nie wchodzą do pomiaru odkrywczego, nawet gdyby podniosły `P_eff`.
2. **Aparatura odmawia obsługi instrumentu spoza skalibrowanej kohorty** —
   `pip_size`, `is_cross`, `cost_model_for` i `decode_bi5` rzucają
   `UnknownInstrumentError` zamiast zwracać liczbę.

**Powód — punkt 1.** ADR-015 zapisał w Konsekwencjach uwagę, że zdobycie tych
danych „kupuje H01 więcej mocy niż cokolwiek, co da się zapisać
w prerejestracji". Uwaga jest **wewnętrznie sprzeczna z ADR-008**, a sprzeczności
nie dało się zauważyć, dopóki nikt nie zapytał, jak konkretnie miałoby to
działać.

`P_eff` rośnie wyłącznie wtedy, gdy instrument wejdzie do **pomiaru
odkrywczego** — czyli do tej samej średniej, w której siedzi sześć par. Ale
ADR-008 zamroził te cztery instrumenty jako kohortę **replikacyjną**, właśnie
po to, żeby pozostały nietknięte: *„wybór instrumentów replikacyjnych po
zobaczeniu wyników jest selection bias"*.

**Nie da się mieć obu naraz.** Albo podnoszą moc odkrywania i przestają być
kohortą replikacyjną — wtedy `SURVIVED` staje się nieosiągalny na zawsze,
nie tylko w tej fazie — albo zostają nietknięte i nie robią nic dla mocy T003.
ADR-015 obiecywał jedno i drugie.

Rozstrzygamy na rzecz ADR-008. Powód jest asymetrią kosztu: moc odkrywania da
się odzyskać innym eksperymentem, a **spalonej kohorty replikacyjnej nie da
się odtworzyć** — raz obejrzana, jest obejrzana. `SUPPORTED` bez replikacji
jest wynikiem częściowym; `SURVIVED` bez nietkniętej kohorty jest niemożliwy.

**Powód — punkt 2.** Skład kohorty był zamrożony, ale aparatura jej **nie
znała** — i odpowiadała na pytania o nią liczbami bez znaczenia:

| Wywołanie | Zwracało | Znaczenie |
|---|---|---|
| `is_cross("DAX")` | `True` | podłoga kosztu „FX cross" 2,5 pipsa dla indeksu |
| `is_cross("XAUUSD")` | `False` | podłoga „FX major" 1,5 pipsa dla złota |
| `pip_size("SPX500")` | `KeyError` | goły wyjątek bez instrukcji |

Pierwsze dwa są groźniejsze od trzeciego: **backtest policzyłby się do końca
i zwrócił wynik**. Reguła `"USD" not in symbol` odpowiada na pytanie „czy to
cross" dla każdego łańcucha znaków, także dla `DAX`, `GBPJPY` i `KOT`.

**Czego brakuje tym instrumentom** (i co musi powstać, zanim wejdą): skala
punktu, zakres wiarygodnej ceny, próg pełnej doby (`min_h1_bars: 12` jest
skalibrowane pod FX 24/5 — przy krótszej sesji **każda** doba wypadałaby
z serii dziennej i próba wyszłaby pusta **bez błędu**), własny poziom kosztu
zamiast `fx_majors`/`fx_crosses`, oraz mapowanie naszych etykiet na kody
feedu (`WTI`, `SPX500`, `DAX` to etykiety z `base.yaml`, nie kody Dukascopy).

**Powtórzenie kalibracji.** Aparatura ma zmierzone zero (M03) i wzmocnienie
(M04) **na FX**. ADR-005 mówi, że przeniesiony kod nie dziedziczy zaufania;
to samo dotyczy przyrządu przeniesionego na inną klasę aktywów. Zanim
cokolwiek zostanie zreplikowane, M03 i M04 muszą zostać powtórzone per klasa.
Replikacja jest **fazą**, nie uruchomieniem skryptu z inną listą symboli.

**Alternatywy.** (a) *Dołożyć kohortę do pomiaru odkrywczego, bo moc jest teraz,
a replikacja kiedyś.* Odrzucone: patrz asymetria kosztu wyżej. (b) *Zostawić
ciche odpowiedzi i po prostu nie wołać tych funkcji dla nieskalibrowanych
instrumentów.* Odrzucone: „nie wołać" jest konwencją, a konwencje w tym
projekcie już trzy razy okazały się niewykonywane (swap, DSR, checklista
leakage'u). (c) *Zmienić `is_cross` tak, by zwracała `None`.* Odrzucone:
`None` przechodzi dalej i wybucha później, w gorszym miejscu.

**Konsekwencje.**

* `known_instruments()` jest jedyną listą, wobec której wolno liczyć koszt
  albo dekodować ticki; test pilnuje, że jest równa `instruments.discovery`.
* Odmowa dotyczy także **par FX spoza kohorty** (`GBPJPY`, `EURGBP`, …) —
  ich skali też nie znamy.
* `UnknownInstrumentError` dziedziczy po `KeyError`, więc nie zmienia
  zachowania kodu, który już łapał `KeyError`.
* Zmiana roli kohorty wymaga **nowego ADR-u**, który jawnie unieważni ten.
  Nie wystarczy edycja `base.yaml`.

---

## ADR-019 — Kontrola permutacyjna T003 nie jest ważnym rozkładem zerowym dla statystyki rangowej

**Status:** ACCEPTED · 2026-09-24 · **Wykryte w:** T003
(`20260924T150658Z-8daa11`) · **Nie zmienia:** werdyktu T003

**Decyzja.** `p`-wartości kontroli permutacyjnej w raporcie T003 zostają
oznaczone jako **bez wartości dowodowej**; werdykt T003 opiera się wyłącznie
na przedziałach ufności i **nie jest przeliczany**. Każda przyszła
prerejestracja deklarująca kontrolę dla statystyki relacji musi deklarować
kontrolę **zachowującą autokorelację cechy** oraz zgodność jej rozrzutu
z rozrzutem bootstrapu.

**Powód (`FACT`).** Kontrola permutacyjna zadeklarowana w prerejestracji
T003 — „permutacja cechy względem targetu, w obrębie pary" — daje rozkład
zerowy **4,5 do 8,3 razy zbyt wąski**:

| k | SD permutacji | SE block bootstrapu | Surogat M05 | Ile razy za wąsko |
|---|---|---|---|---|
| 24 | 0,00283 | 0,01285 | 0,01393 | **4,5×** |
| 120 | 0,00266 | 0,02212 | 0,02084 | **8,3×** |
| 480 | 0,00290 | 0,02268 | 0,02293 | **7,8×** |

`1/√130 553 = 0,00277`. Rozrzut permutacji jest więc **dokładnie rozrzutem
iid** — permutacja rozbija nie tylko związek cechy z targetem, ale też
**autokorelację samej cechy**. `mom_480` ma na sąsiednich barach korelację
99,8%; po przetasowaniu nie ma jej wcale.

To jest ta sama pułapka, przed którą ostrzegał M05 we własnym module:
*„Cecha zastępcza z szumu białego zaniżyłaby rozrzut statystyki o rząd
wielkości i dałaby n_eff wzięte z sufitu."* M05 uniknął jej, budując surogat
o właściwej autokorelacji. Prerejestracja T003 wpadła w nią, bo deklarowała
kontrolę w kategoriach warstwy B („zachowuje wszystko poza timingiem"), gdzie
statystyka jest liniowa i przetasowanie działa.

**Dlaczego to NIE zmienia werdyktu T003.** Kryterium `SUPPORTED` wymaga
**koniunkcji**: CI > 0 po korekcie Holma **i** pobitej kontroli. Kontrola
została „pobita" (p = 0,0120 / 0,0000 / 0,0000) właśnie dlatego, że jest za
wąska — ale **CI nie przekroczyło zera w żadnej komórce**, więc koniunkcja
i tak nie zaszła. Wada działa wyłącznie w stronę **antykonserwatywną**: mogła
wyprodukować fałszywe `SUPPORTED`, nie mogła wyprodukować fałszywego
`NOT_SUPPORTED`. Werdykt stoi.

Gdyby CI wyszło dodatnie, ten sam wynik byłby **nieważny** — i nie dałoby się
tego naprawić po fakcie, bo kryterium było zamrożone.

**Czego nie robimy.** Nie poprawiamy prerejestracji T003 i nie przeliczamy
jego werdyktu. Wpis jest zamknięty, kryteria były zamrożone przed
uruchomieniem, a zmiana po zobaczeniu wyniku — nawet w stronę surowszą — jest
tym, czego cały projekt zakazuje (por. ADR-017, ten sam argument).

**Reguła na przyszłość.** Każda prerejestracja deklarująca kontrolę
permutacyjną dla statystyki **relacji** musi zadeklarować kontrolę
**zachowującą autokorelację cechy**. Poprawną konstrukcję ma już M05:
surogat jako różnica skumulowanych przyrostów na oknie `k`, o korelacji
międzyparowej z modelu bramkowego. Prerejestracja ma też **zadeklarować
zgodność rozrzutu kontroli z rozrzutem bootstrapu** — rozjazd o czynnik
większy niż ~1,5 oznacza, że jedno z dwóch mierzy nie to, co trzeba.

**Alternatywy.** (a) *Uznać p-wartości za ważne i raportować je bez
zastrzeżenia.* Odrzucone: `p = 0,0000` przy CI zawierającym zero to nie
wynik, to sprzeczność, i czytelnik ma prawo ją zobaczyć nazwaną.
(b) *Usunąć p-wartości z raportu.* Odrzucone: zostały policzone w przebiegu
i ich usunięcie byłoby retuszem. Zostają, oznaczone jako nieważne.
(c) *Powtórzyć T003 z poprawną kontrolą.* Odrzucone **na teraz**: to nowy
eksperyment z nowym ID i kolejnymi trzema próbami, a werdykt `NOT_SUPPORTED`
jest od niego niezależny.

**Konsekwencje.**

* Pole `random_control_beaten: true` w raporcie T003 jest **bez wartości
  dowodowej**. Werdykt opiera się wyłącznie na przedziałach ufności.
* Sprawdzenie krzyżowe bootstrap ↔ M05 przeszło we wszystkich komórkach
  (ilorazy 0,923 / 1,062 / 0,989), więc **przedziały ufności są wiarygodne** —
  wada dotyczy wyłącznie kontroli permutacyjnej.
* `pbo.py` nadal niewpięty (ADR-017); przy okazji następnej prerejestracji
  warto rozstrzygnąć oba długi naraz.

---

## ADR-020 — Wąski wyjątek od ADR-012: pomiar cecha↔cecha, strukturalnie niezdolny spojrzeć w przód

**Status:** ACCEPTED · 2026-09-24 · **Zawęża:** ADR-012 · **Umożliwia:** M07

**Decyzja.** Wolno policzyć cechę hipotezy **nieprerejestrowanej** wyłącznie
wtedy, gdy przebieg spełnia **wszystkie trzy** warunki:

1. **Nie tworzy żadnej statystyki** parującej cechę z wielkością patrzącą
   w przód — ani zwrotu, ani etykiety, ani wyniku transakcji.
2. Jest **strukturalnie niezdolny** to zrobić: nie importuje warstwy etykiet
   ani symulatora, nie woła `with_horizon`, nie dotyka kolumn `fwd_atr`,
   `t1`, `exit_*`. Pilnuje tego test czytający źródło, nie obietnica.
3. Jest zalogowany jako `control` i **deklaruje w `purpose`**, że korzysta
   z tego wyjątku.

**Powód.** ADR-012 zakazuje dotykania cechy hipotezy bez żywej prerejestracji
— *„także przebieg nazwany kontrolą. Klasyfikacja `control`/`strategy` idzie
za tym, co przebieg ogląda, nie za tym, po co go uruchomiono."* Reguła jest
słuszna i właśnie udowodniła swoją wartość: ADR-013 zadziałał przeciwko
zaleceniu ADR-012, a T003 wystartował z nietkniętą cechą.

Ale reguła jest **szersza niż mechanizm, przed którym chroni**. Szkoda polega
na **zobaczeniu wyniku hipotezy przed jej prerejestracją** — bo prerejestracja
pisana po wyniku nie jest prerejestracją. Wynik hipotezy powstaje dopiero
w zestawieniu cechy z przyszłością. **Korelacja dwóch cech ze sobą nie jest
wynikiem żadnej z nich**: jest własnością geometrii szeregu cen i nie da się
z niej wyprowadzić expectancy ani jednej.

**Dlaczego to jest potrzebne teraz.** `HYPOTHESES.md` od początku podejrzewa
H02 o **redundancję z H01** — jeśli cena jest w górnych 20% zakresu 55 barów,
`mom_480 > 0` jest niemal pewne. Redundancji **nikt nigdy nie zmierzył**:
`market-quant` testował koniunkcję obu, nie mierząc składników osobno, i to
jest luka pomiarowa, którą T002 ma domknąć.

Po T003 pytanie zrobiło się ostre. `mom_k` nie niesie opłacalnej informacji.
Jeżeli `donch_pos` jest z nim silnie skorelowany, **T002 w dużej części
powtórzy T003** — przy N = 10 z limitu 50 i podwyższonej poprzeczce DSR.
Rozstrzygnięcie tego **przed** prerejestracją kosztuje zero prób;
rozstrzygnięcie **w środku** T002 kosztuje próby za pytanie, które dało się
zadać za darmo.

**Precedens.** M02 rozstrzygnął, czy T001 ma sens, mierząc geometrię próby —
i to zadecydowało o wycofaniu T001 (ADR-011). Różnica jest jedna: M02
sprawdzał wyłącznie, czy cecha jest **określona**, nie licząc wartości.
M07 policzy wartości. Ten ADR nazywa tę różnicę zamiast ją przemilczeć,
i kompensuje ją warunkiem 2 — zakazem strukturalnym, nie deklaratywnym.

**Alternatywy.** (a) *Zmierzyć redundancję wewnątrz T002.* Odrzucone: płaci
próbami za pytanie rozstrzygalne za darmo, a przy wysokiej redundancji te
próby byłyby wydane na powtórzenie T003. (b) *Nie mierzyć wcale i uruchomić
T002 w pełnej postaci.* Odrzucone: `HYPOTHESES.md` stawia redundancję jako
**warunek reaktywacji H02**, więc bez pomiaru H02 nie ma jak przejść ani do
trialu, ani do `CLOSED`. (c) *Rozszerzyć wyjątek na „kontrole, które nie
oceniają sygnału".* Odrzucone: to jest sformułowanie deklaratywne, czyli
dokładnie to, co ADR-012 odrzucił. Wyjątek ma być sprawdzalny w źródle.

**Konsekwencje.**

* Wyjątek dotyczy **wyłącznie** pomiaru cecha↔cecha. Pierwsze zestawienie
  `donch_pos` z czymkolwiek patrzącym w przód jest przebiegiem `strategy`
  i wymaga żywej prerejestracji.
* `src/features/breakout.py` powstaje jako moduł **niosący treść hipotezy**,
  obok `momentum.py` — żeby dało się zobaczyć, co go importuje.
* Reguła ogólna ADR-012 zostaje w mocy w pozostałym zakresie.

---

## ADR-021 — T002 nie startuje: H07 w obecnej definicji nie ma mocy na `FALSIFIED`

**Status:** ACCEPTED · 2026-09-24 · **Wykryte w:** M08A
(`20260924T200939Z-67315c`) · **Precedens:** ADR-011 · **N bez zmian**

**Decyzja.** T002 (H07, zdarzenie wybicia `N = 55`, `quiet_bars = 55`,
h = 3 d, warstwa A) **nie dostaje prerejestracji i nie startuje**. H07 zostaje
`EXPLORATORY` / `POST-HOC`, bez zmiany statusu, z adnotacją, że w tej definicji
jest nietestowalna na segmencie RESEARCH. Krok B audytu (rozkład zerowy
z surogatu) **nie jest uruchamiany**.

**Powód (`FACT`, M08A).** `FALSIFIED` na warstwie A wymaga CI95 wewnątrz
±0,05401 (M04), czyli **n_eff ≥ 1 317**. Żadna statystyka zwrotów po zdarzeniu
nie ma więcej informacji niż zdarzeń, a zdarzeń jest:

| Próba | Zdarzenia | Górna granica n_eff (×6,97/6, M05) | Połowa CI / próg | MDE (moc 80%) |
|---|---|---|---|---|
| siatka T003, sesja primary | **726** | 843 | 1,25 | 53,08% |
| wszystkie godziny | 1 048 | 1 217 | 1,04 | 52,56% |
| skupiska okien (dolna granica) | 216 | — | 2,47 | 56,11% |

Próg opłacalności: **51,72%**. `FALSIFIED` jest nieosiągalne **w każdym
wierszu**, także w najbardziej optymistycznym. Do osiągalności potrzebny byłby
mnożnik n_eff/n = **1,81**; najwyższy zmierzony w projekcie (M05,
`sign_aligned`, cecha gęsta) to 1,16. Kryterium zostało zapisane w skrypcie
jako stałe **przed** przebiegiem.

Przebieg liczył wyłącznie znaczniki czasu zdarzeń (ADR-020). Żadna cena po
decyzji nie została odczytana, więc wycofanie nie jest wyborem kryterium pod
wynik — to jest ten sam dowód, którego ADR-011 wymaga od każdego wycofania.

**Dlaczego krok B nie jest potrzebny.** Surogat mierzy n_eff, a n_eff jest
ograniczone liczbą zdarzeń z góry. Krok B mógłby wyłącznie doprecyzować
martwą strefę w przedziale 53,1–56,1% — ta nie zmienia werdyktu bramki,
bo warunek 1 (osiągalność `FALSIFIED`) jest już niespełniony. Uruchomienie
go byłoby pomiarem bez decyzji.

**Pomyłki w szacunku przed pomiarem**, zapisane, bo obie szły w stronę
optymistyczną: (1) „600–700 zdarzeń na parę" to w rzeczywistości **726 na
wszystkich parach razem** (95–136 na parę); (2) plan audytu podawał jako próg
wykrywalności połowę CI zamiast MDE przy mocy 80% — M05 używa MDE, test
w `tests/test_m08_event_geometry.py` to wykrył i przywiązał definicję do M05.

**Alternatywy.** (a) *Wszystkie godziny zamiast primary.* Odrzucone
pomiarem: 1 217 < 1 317 nawet w granicy optymistycznej, a koszt poza
08–22 UTC nie jest skalibrowany (M03, M04). (b) *Dołożyć segment OOS
2022–2023.* Odrzucone: primary daje wtedy ~1 124, poniżej progu; jedynie
wszystkie godziny + OOS (~1 623) przekraczają go w granicy optymistycznej —
za cenę spalenia OOS na pomiar odkrywczy i nieskalibrowanego kosztu.
(c) *Krótszy zakres `N` albo krótsze `quiet_bars`.* Więcej zdarzeń, ale to
**inna definicja** zdarzenia, dobrana dla mocy, nie z mechanizmu. Wymaga
nowego ADR z uzasadnieniem z mechanizmu (CLAUDE.md: nie mnożymy hipotez, żeby
uniknąć wyniku negatywnego). (d) *Uruchomić T002 mimo to.* Odrzucone: próba
z gwarantowanym `NOT_SUPPORTED` kosztuje N i nic nie wyklucza — ADR-011.

**Konsekwencje.**

* N = 10, bez zmian. Wpis `T002` w `EXPERIMENTS.md` → `WITHDRAWN` przed
  prerejestracją.
* Po M07 i M08A rejestr nie ma żadnej hipotezy gotowej do trialu na
  obecnych danych. Kolejny krok jest decyzją o fazie, nie pomiarem.
* Deklaracje z ADR-017 (deflacja) i ADR-019 (kontrola zachowująca
  autokorelację) nie zostały wykonane, bo nie powstała prerejestracja.
  Obowiązują następną.
