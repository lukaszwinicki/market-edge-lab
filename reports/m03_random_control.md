# M03 — kalibracja przyrządu kontrolą losową

**Data:** 2026-09-23 · **Rodzaj:** `control` — **nie liczy się do N**
**Przebieg:** `20260923T175353Z-087adf` · **Licznik po M03:** N = 7, bez zmian.

---

## Werdykt

> **PRZECHODZI przy obu horyzontach.** Przyrząd nakarmiony wejściami bez
> informacji zwraca stratę **równą modelowanemu kosztowi**, istotnie różną
> od zera, i pozostaje ujemny przy koszcie 1×, 2× i 3×.
>
> **Ale modelowany koszt nie jest pełnym kosztem.** Symulator nie zna swapu,
> a przy h = 10 d brakująca marża finansowania jest **większa niż cały
> modelowany koszt**.

Wynik negatywny z tego przyrządu będzie można interpretować — to było
pytanie M03 i odpowiedź jest twierdząca. Kalibracja obowiązuje jednak
dla kosztów, które przyrząd **implementuje**, a nie dla tych, które
prerejestracja **deklarowała**.

---

## Kryteria i wynik

Losowany jest moment wejścia **i** kierunek, niezależnie od siebie; instrument,
okres, godziny, SL, TP, koszty i execution zostają bez zmian
(`validation.random_control`, ziarno 0). 200 replikacji × 500 wejść × 2
horyzonty = **197 847 rozstrzygniętych transakcji**.

| Kryterium | h = 3 d | h = 10 d |
|---|---|---|
| Expectancy | **−0,0248 R** | **−0,0191 R** |
| Błąd standardowy (block bootstrap po dniach, bloki 20 d, 10 000 replikacji) | 0,0051 | 0,0079 |
| t | −4,90 | −2,41 |
| CI95 | [−0,0347; −0,0147] | [−0,0347; −0,0035] |
| Koszt modelowany | 0,0297 R | 0,0169 R |
| **Luka expectancy − (−koszt)** | **+0,0049 R (0,97 SE)** | **−0,0022 R (0,28 SE)** |
| CI95 pod zerem przy 1× / 2× / 3× | ✅ / ✅ / ✅ | ✅ / ✅ / ✅ |
| Transakcji / dni handlowych | 98 955 / 1 562 | 98 892 / 1 555 |

Expectancy zgadza się z kosztem w granicach jednego błędu standardowego przy
obu horyzontach. **To jest cała treść kalibracji:** przyrząd nie generuje
przewagi tam, gdzie jej nie ma, i nie gubi straty, którą powinien pokazać.

Przy 2× i 3× kosztach expectancy spada dokładnie o krotność kosztu
(−0,0545 i −0,0843 przy h = 3 d; różnice 0,0297 i 0,0298 wobec modelowanego
0,0297). Zgodność jest tu z konstrukcji — krotność liczymy analitycznie
z pól `cost` i `slippage`, nie przez powtórzenie symulacji — więc jest
sprawdzeniem arytmetyki, nie niezależnym dowodem.

---

## Wynik, którego nie było w planie: brakujący człon kosztu — `FACT`

`CostModel` w symulatorze zna spread, podłogę detaliczną i poślizg.
**Nie zna swapu.** Prerejestracja T001 deklarowała „swap z osią marży",
a `configs/base.yaml` trzyma `costs.swap.margin_sensitivity`, której
nic nie czytało.

Marża swapu policzona po fakcie (`src/execution/swap.py`, nie wpięta
w symulator), dla rzeczywistych okien trzymania tej próby:

| Marża roczna | h = 3 d | h = 10 d |
|---|---|---|
| 0,5% | 0,0062 R (0,21× koszt modelowany) | 0,0111 R (0,66×) |
| **1,0%** | **0,0124 R (0,42×)** | **0,0223 R (1,32×)** |
| 2,0% | 0,0249 R (0,84×) | 0,0446 R (**2,64×**) |

Przy h = 10 d i marży 1% brakujący koszt jest **o jedną trzecią większy niż
wszystko, co model liczy**. Pełny koszt na transakcję:

| | Modelowany | + marża swapu 1% | Razem |
|---|---|---|---|
| h = 3 d | 0,0297 R | 0,0124 R | **0,0422 R** |
| h = 10 d | 0,0169 R | 0,0223 R | **0,0392 R** |

### Co z tego wynika dla wyboru horyzontu — `INFERENCE`

ADR-009 zakładał, że krótszy horyzont „kupuje moc statystyczną i sprzedaje
wykonalność ekonomiczną", bo ciaśniejszy stop podnosi koszt w jednostkach R
(szacunek: 0,023 R wobec 0,012 R, czyli 1,9×).

Modelowany koszt ten szacunek potwierdza — stosunek wynosi **1,76×**.
Po doliczeniu finansowania stosunek spada do **1,08×**.

**Przewaga kosztowa długiego horyzontu jest artefaktem pominięcia swapu.**
Dłuższe trzymanie oszczędza na spreadzie dokładnie tyle, ile dopłaca
w finansowaniu. Zostaje więc różnica w mocy — a ta, po M02, wypada
trzykrotnie na korzyść h = 3 d (n_eff 1 040 wobec 315).

Przy pełnym koszcie **h = 3 d dominuje h = 10 d na obu osiach naraz**:
ta sama cena za transakcję, trzy razy więcej obserwacji niezależnych.
To jest mocna przesłanka do konstrukcji T003, ale **nie jest decyzją** —
prerejestracja T003 musi ją podjąć jawnie.

### Skala wobec progów T001

Kryterium `FALSIFIED` w T001 brzmiało „CI95 w całości poniżej **+0,02 R**".
Brakująca marża swapu przy h = 10 d to **0,0223 R** — więcej niż cały próg.
Gdyby T001 wystartował, jego expectancy byłaby zawyżona o wielkość
przekraczającą granicę, wobec której miała być oceniana.

---

## Diagnostyka

**Powody wyjścia** — zgodne z M02 co do ułamka procenta, co potwierdza,
że obie próby opisują tę samą mechanikę:

| | czas | SL | TP | luka przez SL | luka przez TP | brak danych |
|---|---|---|---|---|---|---|
| h = 3 d | 63,8% | 30,3% | 5,3% | 0,45% | 0,09% | 0,01% |
| h = 10 d | 63,4% | 30,5% | 5,4% | 0,57% | 0,18% | 0,01% |

**Rozkład po przebiegach.** Expectancy pojedynczego przebiegu 500 transakcji:
odchylenie 0,041 R, przedział [−0,097; +0,063] przy h = 3 d. **Ujemnych jest
75% przebiegów przy h = 3 d i 67% przy h = 10 d** — czyli co trzeci–czwarty
przebieg wejść całkowicie pozbawionych informacji wychodzi na plus. To jest
rozkład, względem którego T003 będzie musiał się wykazać, i powód, dla
którego pojedyncza dodatnia liczba nie znaczy nic.

**Pułapka w liczeniu n_eff — do zapamiętania.** `effective_sample_size`
policzone na ramce z **wszystkimi parami naraz** zwróciło 521 (h = 3 d)
i 156 (h = 10 d) — czyli dokładnie tyle, ile M02 zmierzył dla **jednej**
pary. Zachłanne szukanie rozłącznych okien działa na jednej osi czasu, więc
pary nałożone na siebie w kalendarzu nie dokładają nic. Wymiar przekrojowy
trzeba domnożyć osobno (M02: ×2,0 konserwatywnie). Użycie tej liczby wprost
zaniżyłoby n_eff dwukrotnie.

---

## Czego M03 NIE zrobił

**To nie jest kontrola losowa dopasowana liczbą obserwacji do przebiegu
strategii.** Taka kontrola jest częścią przebiegu, z którym się porównuje —
a T001 został wycofany (ADR-011), T003 nie istnieje, więc porównywać nie ma
z czym. M03 kalibruje przyrząd; porównanie należy do T003.

**Nie liczył żadnej cechy.** `mom_k` nie został policzony ani razu.

**Nie wpiął swapu w symulator.** `src/execution/swap.py` stoi obok i liczy
po fakcie, tak samo jak przeliczenie 2×/3×. Symulator jest przeniesiony
i zweryfikowany co do bitu (M01); dokładanie mu członu kosztu unieważniłoby
tę weryfikację. Wpięcie jest zadaniem T003 i wymaga powtórzenia kalibracji.

**Przybliżenia, które trzeba znać.** Krotność kosztów liczona analitycznie
nie przesuwa fillów ani nie zmienia, w którym barze pada bariera. Granica
rolowania swapu przyjęta o północy UTC zamiast o 17:00 w Nowym Jorku —
wystarczy do rzędu wielkości, nie wystarczy do rozliczenia pozycji.

---

## Dług M01 — SPŁACONY

Dwa testy na brak podglądania przyszłości przez symulator **wróciły**, i to
bez warstwy etykiet. Opis długu był pomyłkowy: oryginały z `market-quant`
szpiegowały, jaką ramkę podaje symulatorowi `triple_barrier.py`, ale sama
własność należy do symulatora — `simulate_trade` tnie okno samodzielnie
(`slice_window`, `simulator.py:146`).

Przywrócone wersje sprawdzają ją **obserwowalnie**: psują ceny poza oknem
i żądają, żeby wynik nie drgnął. Szpieg pilnował, co symulator *dostał*;
to pilnuje, czego *użył*.

| Test | Co sprawdza |
|---|---|
| `test_simulator_sees_only_the_trade_window` | Ceny po barierze czasowej nie zmieniają wyniku |
| `test_simulator_ignores_bars_before_the_decision` | Ceny sprzed decyzji też nie — okno domknięte z obu stron |
| `test_windowed_labels_match_simulation_on_full_history` | Wycięcie okna przed wywołaniem nie zmienia wyniku |

Każdy przebiega 150–300 losowych ścieżek na stronę, z pokryciem więcej niż
jednego powodu wyjścia.

---

## Co M03 dołożył do aparatury

| Moduł | Stan |
|---|---|
| `src/research/grid.py` | **nowy** — siatka decyzyjna wyjęta z M02, wspólna dla wszystkich przebiegów; 12 testów |
| `src/execution/swap.py` | **nowy** — marża swapu, rolowanie potrójne w środę; 16 testów |
| `tests/test_simulator.py` | **+6 testów** — dług M01 spłacony |
| `scripts/m03_random_control.py` | **nowy** — kontrola losowa przez `start_run(kind="control")` |

M02 został przepięty na `src/research/grid.py` i **powtórzony**
(`20260923T174821Z-db3956`): raport JSON, `m02_neff.csv` i obie próbki σ
wyszły **identyczne** z przebiegiem sprzed przeniesienia. Przeniesienie kodu
niczego nie zmieniło — sprawdzone, nie założone.

Testy po M03: **255** (221 + 34).
