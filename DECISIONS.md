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
