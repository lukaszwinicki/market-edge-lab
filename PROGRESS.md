# PROGRESS.md — bieżący stan

Log stanu: co zrobiono, gdzie jesteśmy, co dalej, co blokuje.
**Nie jest źródłem prawdy** — w razie sprzeczności wygrywa `DECISIONS.md`.

Ten plik ma zostać krótki (do ~120 linii), żeby dało się go przeczytać
w całości na starcie sesji. Historia zamknięta idzie do archiwum, nie tutaj.

Każdą liczbę sprawdzać komendą, nie brać na wiarę.

---

## Faza 0 i M01 — ZAMKNIĘTE (2026-09-23)

Pełny zapis: `EXPERIMENTS.md` (M01) i `DECISIONS.md` (ADR-001…010). Tutaj
tylko to, co trzeba mieć w głowie na starcie sesji.

**Faza 0.** Audyt `market-quant`, architektura, rejestr hipotez, prerejestracja
T001. `INFERENCE` z audytu (ADR-001): poprzednik sfalsyfikował **regułę handlową
wraz z warstwą zarządzania kapitałem**, nie mechanizm momentum — z 64 342
sygnałów w transakcję weszło 889, a obserwacji efektywnych zostało **172**.
Stąd ADR-002: pomiar informacji oddzielony od symulacji strategii, wymuszony
architekturą (brak `src/risk/` w fazie 1).

**M01 — PRZECHODZI.** Te same ticki przez przeniesiony pipeline dają ramki
**identyczne co do bitu** z `market-quant` (EURUSD 2015). Świece 2015–2023,
6 par, 433 MB; raport jakości zdany; odcisk danych `sha256 = 6b6b3aa4…`;
pieczęć 2024–2026 działa. Godzina `2023-12-24 22:00` zaakceptowana jawnie
z dowodem, bez osłabiania detektora (ADR-010).

**Dług M01 — SPŁACONY w M03.** Warstwa etykiet (`triple_barrier.py`) nadal nie
jest przeniesiona i musi powstać przed T003, ale opis długu był pomyłkowy:
dwa testy na brak podglądania przyszłości **nie zależały** od niej — własność
należy do symulatora. Wróciły w M03, w wersji obserwowalnej.

---

## M02 — ZAMKNIĘTY (2026-09-23) → T001 WYCOFANY (ADR-011)

Audyt mocy przed T001 (ADR-009). `20260923T172201Z-fa3731`, rodzaj `control`.
Raport: `reports/m02_power_audit.md`.

| h | n_eff w czasie | P_eff | n_eff łącznie | σ w R | **MDE** | Bramka 0,08 R |
|---|---|---|---|---|---|---|
| 3 d | 3 126 | 2,00 | 1 040 | 0,9165 | **0,0796** | na progu (±0,0018) |
| 10 d | 936 | 2,02 | 315 | 0,9261 | **0,1463** | przekroczona zawsze |

**Bramka: NIEROZSTRZYGNIĘTA** — blokuje tylko przy przekroczeniu na OBU
horyzontach, a h=3d siada dokładnie na progu. **Ale wynik pod bramką
wystarczył**, żeby wycofać T001:

* **σ była dziedziczona, nie mierzona — i 2× za mała** (`FACT`). ADR-009
  implikował 0,455 R (przeskalowana połowa CI poprzednika przez √n).
  Zmierzone: **0,92 R**. n_eff zgadł nieźle, rozrzut pomylił dwukrotnie.
* **Kryteria falsyfikacji T001 były nieosiągalne** (`INFERENCE`). `SUPPORTED`
  wymagałoby średniej > +0,056 R (h=3d) lub **> +0,102 R** (h=10d) przy
  dryfie kosztowym −0,031 R. Między progami zapada `NOT_SUPPORTED` —
  **niezależnie od tego, czy efekt istnieje**, kosztem 6 prób.
* Przy h=10d T001 miałby **mniejszą moc niż eksperyment, który miał poprawić**
  (0,146 R wobec 0,097 R), mimo 1,8× większego n_eff.
* Sesja nie kupuje mocy: „wszystkie godziny" to +72% wierszy i **zero**
  obserwacji niezależnych. Sześć par to ~2 niezależne rynki (|ρ| = 0,40).

**ADR-011.** T001 → `WITHDRAWN`, nigdy nieuruchomiony, **N pozostaje 7**.
H01 i H03 → `PROPOSED` (hipotezy żyją, protokół nie). Zastępuje je **T003**.
Wycofanie było dopuszczalne, bo M02 nie obejrzał niczego, co dotyczy H01 —
nie liczył `mom_k` ani jego znaku. **Każde przyszłe wycofanie prerejestracji
wymaga tego samego dowodu, zapisanego w ADR.**

---

## M03 — ZAMKNIĘTY, PRZECHODZI (2026-09-23) → ADR-012

Kalibracja przyrządu kontrolą losową. `20260923T175353Z-087adf`, `control`.
Raport: `reports/m03_random_control.md`. 200 replikacji × 500 wejść × 2
horyzonty = **197 847 transakcji**, losowany moment **i** kierunek.

| | h = 3 d | h = 10 d |
|---|---|---|
| Expectancy wejść losowych | **−0,0248 R** (t = −4,90) | **−0,0191 R** (t = −2,41) |
| Koszt modelowany | 0,0297 R | 0,0169 R |
| Luka | +0,0049 R (**0,97 SE**) | −0,0022 R (**0,28 SE**) |
| CI95 < 0 przy 1×/2×/3× | ✅ | ✅ |

**PRZECHODZI.** Przyrząd nie produkuje przewagi tam, gdzie jej nie ma —
wynikowi negatywnemu będzie można wierzyć. O to pytał M03.

**Wynik spoza planu (`FACT`): symulator nie zna swapu.** `CostModel` liczy
spread, podłogę i poślizg; `costs.swap.margin_sensitivity` z configu nie
czytało nic. Przy h=10d i marży 1% brakujący człon to **0,0223 R — 1,32×
cały modelowany koszt**, i więcej niż próg +0,02 R, wobec którego T001 miał
być oceniany.

`INFERENCE`: **przewaga kosztowa długiego horyzontu była artefaktem pominięcia
swapu.** Stosunek kosztu h=3d/h=10d to 1,76× dla kosztu modelowanego,
ale **1,08×** po doliczeniu finansowania. Zostaje różnica w mocy — 3× na
korzyść h=3d. Przy pełnym koszcie **h=3d dominuje h=10d na obu osiach**.

**Do zapamiętania.** Co trzeci–czwarty przebieg 500 wejść **bez informacji**
wychodzi na plus (odchylenie 0,041 R). `effective_sample_size` na ramce ze
wszystkimi parami naraz daje tyle, co dla jednej pary — wymiar przekrojowy
trzeba domnożyć osobno, inaczej n_eff spada dwukrotnie.

**ADR-012 — M04 w postaci z fazy 0 nie może wystartować.** Porównanie
baseline z cechą postarzoną wymaga policzenia `mom_k`, czyli oceny sygnału
H01: (a) czyni z przebiegu `strategy` i dolicza go do N, (b) pokazuje
expectancy H01, **zanim T003 zostanie prerejestrowany**. W planie z fazy 0
było to bezpieczne, bo T001 był zamrożony — **wycofanie T001 usunęło tę
ochronę, a ADR-011 tego nie zauważył.**

M04 zmienia postać: cechy syntetyczne o znanej zawartości informacyjnej
(szum · wyrocznia · wyrocznia postarzona). Nie dotyka `mom_k`, zostaje
`control`, dokłada **kontrolę dodatnią**, której stara postać nie miała.
Porównanie na cesze prawdziwej przechodzi do T003 jako ramię prerejestrowane.

**Reguła ogólna:** dopóki hipoteza nie ma żywej, zamrożonej prerejestracji,
żaden przebieg nie może dotknąć jej cechy — także nazwany kontrolą.

---

## Gdzie jesteśmy

**Faza 1 w toku.** M01 i M03 zamknięte i przechodzą. M02 zamknięty — bramka
nierozstrzygnięta, ale wynik pod nią wystarczył, żeby wycofać T001 (ADR-011).
M04 zablokowany w starej postaci, przeprojektowany (ADR-012).

**Licznik prób: N = 7** (odziedziczone, ADR-004). Uruchomionych prób
strategii w tym projekcie: **0**. M01–M03 były krokami kontrolnymi
i nie liczą się do N.

**Testy: 255** (173 po M01 + 48 w M02 + 34 w M03).

---

## Następne kroki — w tej kolejności

| # | Krok | Rozstrzyga |
|---|---|---|
| ~~1~~ | ~~**M01** — przeniesienie aparatury, świece, testy, raport jakości~~ | **ZAMKNIĘTY, PRZECHODZI** |
| ~~2~~ | ~~**M02** — audyt mocy~~ | **ZAMKNIĘTY** — T001 wycofany (ADR-011) |
| ~~3~~ | ~~**M03** — kalibracja kontrolą losową~~ | **ZAMKNIĘTY, PRZECHODZI** — i wykrył brak swapu w modelu kosztów |
| 4 | **M04** — test z zasianym błędem (ADR-012) | Czy przyrząd widzi informację, gdy ta JEST, i milczy, gdy jej nie ma. Nie dotyka `mom_k` |
| 5 | **Prerejestracja T003** | Sześć warunków: ADR-011 + ADR-012. Każda zmiana geometrii barier wymaga **nowego pomiaru mocy**, nie przeliczenia |
| 6 | **T003** — H01 momentum, konstrukcja przeprojektowana | Pytanie, na które `market-quant` nie miał mocy odpowiedzieć |

Kroki M są kontrolami aparatury i **nie liczą się** do N w DSR.

**Przed T003 trzeba dodatkowo:** zbudować warstwę etykiet od nowa (bez
treści hipotezy w module). ~~Przywrócić dwa testy na look-ahead~~ — spłacone
w M03.

M04 w nowej postaci nie zależy od kształtu T003 i może iść równolegle
z prerejestracją.

---

## Blokery i znane ograniczenia

| Sprawa | Stan |
|---|---|
| **Kohorta replikacyjna nie istnieje** | Zero bajtów dla XAUUSD, WTI, S&P 500, DAX. Replikacja niemożliwa → **żadna hipoteza nie osiągnie `SURVIVED`** w tej fazie (ADR-008). Najwyższy status: `SUPPORTED` |
| **Segment RESEARCH był oglądany** | 7 prób poprzednika na tych samych danych. Poprzeczka DSR startuje podwyższona (ADR-004) |
| **Moc jest za mała przy h=10d** | **ZMIERZONE w M02.** MDE 0,085–0,146 R — bramki nie przechodzi przy żadnym modelu par, gorzej niż 0,097 R `market-quant`. Wąskim gardłem okazała się σ (0,92 R zamiast dziedziczonych 0,455), nie samo nakładanie okien |
| **Model niezależności par nierozstrzygnięty** | Nawias [2,0; 6,0] ciasny matematycznie, ale wybór punktu to decyzja. Wart czynnika 1,7 na MDE. **T003 musi go zadeklarować jawnie** (ADR-011, warunek 1) |
| **Granica okien wychodzących w OOS** | T001 mówił „decyzje do 2021-12-31" i nie rozstrzygał, co z `t1` w styczniu 2022. M02 przyjął wariant nietykający OOS. **T003 musi to zadeklarować** (ADR-011, warunek 4) |
| **Rentowności 2-letnie** `UNKNOWN` | Brak spójnej definicji dla wszystkich walut. Blokuje H04 |
| **Marża swapu** `UNKNOWN`, ale **ZMIERZONA CO DO SKALI** | **M03: symulatora nie ma jej wcale.** Przy h=10d i marży 1% to 0,0223 R, czyli 1,32× cały modelowany koszt. Oś wrażliwości istnieje (`src/execution/swap.py`), ale **nie jest wpięta w symulator** — warunek 6 dla T003 |
| **Kontrola przesuniętych cech** `UNKNOWN` | U poprzednika dała wynik lepszy od baseline. Wyjaśnione szumem przy ich mocy; do domknięcia w M04 |
| ~~Hash zbioru ticków `UNKNOWN`~~ | **ZAMKNIĘTE w M01** — `sha256 = 6b6b3aa4…`, 336 561 plików |
| Zależność od ścieżki do ticków | Projekt nie jest samowystarczalny na poziomie danych źródłowych (ADR-007) |

---

## Czego NIE robimy

- Nie uruchamiamy backtestu przed M04 i prerejestracją spełniającą ADR-011 + ADR-012.
- **Nie dotykamy `mom_k` żadnym przebiegiem**, dopóki T003 nie jest zamrożony (ADR-012).
- Nie dodajemy ML — dopóki nie wiadomo, czy istnieje prosty efekt.
- Nie mnożymy hipotez, żeby uniknąć wyniku negatywnego.
- Nie otwieramy segmentu 2024–2026.
- Nie dotykamy `market-quant`.
