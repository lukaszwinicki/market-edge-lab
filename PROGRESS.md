# PROGRESS.md — bieżący stan

Log stanu: co zrobiono, gdzie jesteśmy, co dalej, co blokuje.
**Nie jest źródłem prawdy** — w razie sprzeczności wygrywa `DECISIONS.md`.

Ten plik ma zostać krótki, żeby dało się go przeczytać w całości na starcie
sesji. **Narracja zamkniętych kroków żyje w `EXPERIMENTS.md` i `reports/`** —
tutaj zostają tylko liczby, które trzeba mieć w głowie, i to, co otwarte.

Każdą liczbę sprawdzać komendą, nie brać na wiarę.

---

## Gdzie jesteśmy

**Seria kontrolna M01–M04 ZAMKNIĘTA.** Aparatura ma sprawdzone **zero**
(M03) i sprawdzone **wzmocnienie** (M04), a oba pomiary zgadzają się do
**0,0007 R**. Pierwszy eksperyment na hipotezie (T001) został **wycofany
przed uruchomieniem** — nie miał mocy osiągnąć własnych kryteriów.

**Licznik prób: N = 7** (odziedziczone, ADR-004). Uruchomionych prób
strategii w tym projekcie: **0**. M01–M04 to kontrole, nie liczą się do N.

**Testy: 264.** **Następny krok: prerejestracja T003** — pierwszy krok,
który nie jest kontrolą.

---

## Seria kontrolna — wynik

| Krok | Wynik | Co ustalił |
|---|---|---|
| **M01** | **PRZECHODZI** | Port `market-quant` daje ramki **identyczne co do bitu**. Świece 2015–2023, 6 par; odcisk `sha256 = 6b6b3aa4…`; pieczęć 2024–2026 działa. Godzina `2023-12-24 22:00` przyjęta z dowodem (ADR-010) |
| **M02** | **NIEROZSTRZYGNIĘTE** → T001 wycofany | Audyt mocy (ADR-009). Bramka nie rozstrzygnęła, ale wynik pod nią wystarczył |
| **M03** | **PRZECHODZI** | Wejścia losowe dają expectancy = −koszt w granicach **1 SE**. Wynikowi negatywnemu będzie można wierzyć |
| **M04** | **PRZECHODZI** | Wzmocnienie poprawne; próg wykrywalności to **57,3% / 61,9%** trafności kierunku |

Raporty: `reports/m02_power_audit.md`, `m03_random_control.md`,
`m04_sensitivity.md`. Przebiegi: `20260923T172201Z-fa3731`,
`…T175353Z-087adf`, `…T181510Z-963686`.

### Liczby, które trzeba mieć w głowie

| | h = 3 d | h = 10 d |
|---|---|---|
| n_eff (konserwatywnie: P_eff ≈ 2) | 1 040 | 315 |
| σ wyniku w R | 0,9165 | 0,9261 |
| **MDE** (moc 80%, α 0,05) | **0,0796 R** | **0,1463 R** |
| Koszt modelowany / + marża swapu 1% | 0,0297 / **0,0422 R** | 0,0169 / **0,0392 R** |
| **Próg opłacalności** (trafność kierunku) | **51,72%** | **51,42%** |
| **Próg wykrywalności** | **57,33%** | **61,91%** |

---

## Cztery ustalenia, które zmieniają plan

**1. σ była dziedziczona, nie mierzona — i 2× za mała** (M02, `FACT`).
ADR-009 implikował 0,455 R przez przeskalowanie połowy CI poprzednika
przez √n. Zmierzone: **0,92 R**. n_eff zgadł nieźle, rozrzut pomylił
dwukrotnie. Stąd wycofanie T001 (ADR-011).

**2. Eksperyment widzi tylko efekty 4–8× większe od najmniejszego
opłacalnego** (M04, `INFERENCE`). Między 51,7% a 57,3% trafności strategia
**naprawdę zarabia**, a pomiar zwróci `NOT_SUPPORTED`. Przy h=10d T001
miałby przy tym mniejszą moc niż eksperyment, który miał poprawić
(0,146 R wobec 0,097 R).

**3. Symulator nie zna swapu** (M03, `FACT`). Przy h=10d i marży 1%
brakujący człon to **1,32× cały modelowany koszt**. `INFERENCE`: przewaga
kosztowa długiego horyzontu była **artefaktem pominięcia swapu** — stosunek
kosztu h=3d/h=10d spada z 1,76× do **1,08×**. Zostaje różnica w mocy, 3× na
korzyść h=3d. **h=3d dominuje h=10d na obu osiach.**

**4. Bariery prawie nie wiążą** (M04, `FACT`). Przy **doskonałym** kierunku
84% pozycji kończy na barierze czasowej; średni |ruch| to **40% dystansu do
TP**. Triple-barrier jest tu w dużej mierze dekoracją — dokłada ryzyko luki
i złożoność, rozstrzygając 16% przypadków.

---

## Decyzje z tej fazy

| ADR | Treść |
|---|---|
| **ADR-011** | T001 → `WITHDRAWN`, nigdy nieuruchomiony, **N bez zmian**. H01 i H03 → `PROPOSED` — hipotezy żyją, protokół nie. Zastępuje je **T003**. Wycofanie było dopuszczalne, bo M02 nie obejrzał niczego, co dotyczy H01. **Każde przyszłe wycofanie wymaga tego samego dowodu** |
| **ADR-012** | M04 w postaci z fazy 0 nie wystartuje: wymagałby policzenia `mom_k`, czyli oceny sygnału bez żywej prerejestracji. W planie z fazy 0 było to bezpieczne, bo T001 był zamrożony — **wycofanie T001 usunęło tę ochronę, a ADR-011 tego nie zauważył**. Reguła ogólna: **dopóki hipoteza nie ma żywej, zamrożonej prerejestracji, żaden przebieg nie może dotknąć jej cechy** |
| **ADR-013** | Ramię „wyrocznia postarzona" z ADR-012 nie powstało — byłoby znakiem zwrotu z przeszłości, czyli cechą momentum, co łamałoby regułę z tego samego ADR-012. Pytanie o przesunięcie o jeden bar przeszło na testy syntetyczne |

---

## Następne kroki

| # | Krok | Rozstrzyga |
|---|---|---|
| ~~1–4~~ | ~~**M01–M04** — seria kontrolna~~ | **ZAMKNIĘTA** |
| **5** | **Prerejestracja T003** ← **TU JESTEŚMY** | Sześć warunków (niżej). Każda zmiana geometrii barier wymaga **nowego pomiaru mocy**, nie przeliczenia |
| 6 | **T003** — H01 momentum, konstrukcja przeprojektowana | Pytanie, na które `market-quant` nie miał mocy odpowiedzieć |
| 7 | **T002** — H07 zdarzenie vs H02 stan, redundancja z H01 | Prerejestracja po zamknięciu T003 |

**Sześć warunków prerejestracji T003** (ADR-011 + ADR-012, szczegóły
w `EXPERIMENTS.md`): model niezależności par · σ zmierzona dla zadeklarowanej
geometrii · osiągalne progi falsyfikacji · granica okien w OOS · ramię
„cecha vs cecha postarzona" · model kosztu ze swapem.

**Przed T003 trzeba dodatkowo:** zbudować warstwę etykiet od nowa, bez treści
hipotezy w module. Nic poza tym już nie blokuje — seria kontrolna zamknięta,
testy na look-ahead spłacone w M03.

---

## Blokery i znane ograniczenia

| Sprawa | Stan |
|---|---|
| **Kohorta replikacyjna nie istnieje** | Zero bajtów dla XAUUSD, WTI, S&P 500, DAX. Replikacja niemożliwa → **żadna hipoteza nie osiągnie `SURVIVED`** w tej fazie (ADR-008). Najwyższy status: `SUPPORTED` |
| **Segment RESEARCH był oglądany** | 7 prób poprzednika na tych samych danych. Poprzeczka DSR startuje podwyższona (ADR-004) |
| **Moc jest za mała przy h=10d** | MDE 0,085–0,146 R — bramki nie przechodzi przy żadnym modelu par. Wąskim gardłem okazała się σ, nie samo nakładanie okien |
| **Model niezależności par nierozstrzygnięty** | Nawias [2,0; 6,0] ciasny matematycznie, ale wybór punktu to **decyzja**, warta czynnika 1,7 na MDE. Warunek 1 dla T003 |
| **Swap nie jest wpięty w symulator** | `src/execution/swap.py` liczy po fakcie i ma testy, ale `CostModel` go nie zna. Wpięcie wymaga **powtórzenia kalibracji M03**. Warunek 6 dla T003 |
| **Granica okien wychodzących w OOS** | M02 przyjął wariant nietykający OOS. Do jawnej deklaracji. Warunek 4 dla T003 |
| **Warstwa etykiet nie istnieje** | Nie została przeniesiona, bo niesie treść hipotezy. Musi powstać przed T003 |
| **Rentowności 2-letnie** `UNKNOWN` | Brak spójnej definicji dla wszystkich walut. Blokuje H04 |
| **Kontrola przesuniętych cech** `UNKNOWN` | Anomalia poprzednika (wynik z cechami postarzonymi lepszy) **nadal nierozstrzygnięta na cesze prawdziwej** — przechodzi do T003 jako warunek 5 |
| Zależność od ścieżki do ticków | Projekt nie jest samowystarczalny na poziomie danych źródłowych (ADR-007) |

---

## Czego NIE robimy

- Nie uruchamiamy backtestu przed prerejestracją spełniającą ADR-011 + ADR-012.
- **Nie dotykamy `mom_k` żadnym przebiegiem**, dopóki T003 nie jest zamrożony (ADR-012).
- Nie dodajemy ML — dopóki nie wiadomo, czy istnieje prosty efekt.
- Nie mnożymy hipotez, żeby uniknąć wyniku negatywnego.
- Nie otwieramy segmentu 2024–2026.
- Nie dotykamy `market-quant`.
