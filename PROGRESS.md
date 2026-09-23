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

**Dług M01, niespłacony.** Warstwa etykiet (`triple_barrier.py`) niesie treść
hipotezy i nie została przeniesiona; razem z nią odpadły **dwa testy na brak
podglądania przyszłości przez symulator**. Ślad imienny w `tests/test_harness.py`.
**Muszą wrócić przed T003** — to warunek, nie drobiazg.

---

## M02 — ZAMKNIĘTY, NIEROZSTRZYGNIĘTY (2026-09-23)

Audyt mocy przed T001 (ADR-009). Przebieg `20260923T172201Z-fa3731`, rodzaj
`control`. Pełny raport: `reports/m02_power_audit.md`. **Żaden backtest nadal
nie został uruchomiony, N = 7 bez zmian.**

| h | n_eff w czasie | P_eff | n_eff łącznie | σ w R | **MDE** | Bramka 0,08 R |
|---|---|---|---|---|---|---|
| 3 d | 3 126 | 2,00 | 1 040 | 0,9165 | **0,0796** | **na progu** |
| 10 d | 936 | 2,02 | 315 | 0,9261 | **0,1463** | przekroczona |

**Werdykt: NIEROZSTRZYGNIĘTE.** ADR-009 blokuje T001 tylko przy przekroczeniu
progu na OBU horyzontach. h=10d przekracza przy każdym założeniu. h=3d siada
dokładnie na progu — różnica 0,0004 R przy błędzie pomiaru ±0,0018 R.

**Najważniejszy wynik M02 (`FACT`). σ była dziedziczona, nie mierzona — i jest
2× za mała.** Tabela szacunków w ADR-009 powstała przez przeskalowanie połowy
CI z `market-quant` przez √n, co implikuje σ = 0,455 R. Zmierzona symulatorem
na 8 000 wejść: **0,92 R** przy obu horyzontach. n_eff ADR-009 zgadł nieźle;
pomylił się o 2× na rozrzucie.

**Wynik ostrzejszy od samej bramki (`INFERENCE`).** Kryteria falsyfikacji T001
były w większości nieosiągalne. `SUPPORTED` wymagałoby średniej > +0,056 R
(h=3d) lub **> +0,102 R** (h=10d), `FALSIFIED` — poniżej −0,036 / −0,082 R.
Między tymi progami zapada `NOT_SUPPORTED`, a dryf kosztowy to już −0,031 R,
więc umiarkowany realny efekt wpada w martwą strefę niemal na pewno. Przy
h=10d T001 miałby przy tym **mniejszą moc niż eksperyment, który miał
poprawić** (0,146 R wobec 0,097 R), mimo 1,8× większego n_eff.

**Co jeszcze wyszło.** Sesja nie kupuje mocy: „wszystkie godziny" dokłada +72%
wierszy i **zero** obserwacji niezależnych. Sześć par zachowuje się jak ~2
niezależne rynki (średnie |ρ| = 0,40, wspólny czynnik USD).

---

## Decyzja po M02 — ADR-011 (2026-09-23)

**T001 wycofany przed uruchomieniem.** Konstrukcja nie ma mocy osiągnąć
własnych kryteriów falsyfikacji, a przy h=10d nie przechodzi bramki ADR-009
przy **żadnym** modelu niezależności par. H01 wraca do `PROPOSED` — hipoteza
żyje, jej protokół nie. Zastępuje go **T003**, którego prerejestracja musi
spełnić cztery warunki z ADR-011 (model par · σ zmierzona dla zadeklarowanej
geometrii · osiągalne progi falsyfikacji · granica okien w OOS).

**N pozostaje 7.** T001 nigdy nie wystartował, rejestr liczy wpisy `start`.

Wycofanie było dopuszczalne, bo M02 nie obejrzał niczego, co dotyczy H01 —
nie liczył `mom_k` ani jego znaku. Gdyby obejrzał, wycofanie prerejestracji
byłoby wyborem kryterium pod wynik. **Każde przyszłe wycofanie wymaga tego
samego dowodu, zapisanego w ADR.**

---

## Gdzie jesteśmy

**Faza 1 w toku.** M01 zamknięty i przechodzi. M02 zamknięty — bramka
nierozstrzygnięta, ale wynik pod nią wystarczył, żeby wycofać T001 (ADR-011).

**Licznik prób: N = 7** (odziedziczone, ADR-004). Uruchomionych prób
strategii w tym projekcie: **0**. M01 i M02 były krokami kontrolnymi
i nie liczą się do N.

**Testy: 221** (173 po M01 + 48 dołożonych w M02).

---

## Następne kroki — w tej kolejności

| # | Krok | Rozstrzyga |
|---|---|---|
| ~~1~~ | ~~**M01** — przeniesienie aparatury, świece, testy, raport jakości~~ | **ZAMKNIĘTY, PRZECHODZI** |
| ~~2~~ | ~~**M02** — audyt mocy~~ | **ZAMKNIĘTY** — T001 wycofany (ADR-011) |
| 3 | **M03** — kalibracja kontrolą losową | Czy wynikowi negatywnemu będzie można wierzyć. **Niezależne od kształtu T003** |
| 4 | **M04** — domknięcie kontroli przesuniętych cech | Otwarte `UNKNOWN` po poprzedniku |
| 5 | **Przeprojektowanie: prerejestracja T003** | Cztery warunki ADR-011. Każda zmiana geometrii barier wymaga **nowego pomiaru mocy**, nie przeliczenia |
| 6 | **T003** — H01 momentum, konstrukcja przeprojektowana | Pytanie, na które `market-quant` nie miał mocy odpowiedzieć |

Kroki M są kontrolami aparatury i **nie liczą się** do N w DSR.

**Przed T003 trzeba dodatkowo:** zbudować warstwę etykiet od nowa (bez
treści hipotezy w module) i przywrócić dwa testy na brak look-ahead.

M03 i M04 nie zależą od tego, jak będzie wyglądał T003 — można je robić
równolegle z przeprojektowaniem.

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
| **Marża swapu** `UNKNOWN` | Jedyna liczba w modelu kosztów bez sparsowanego źródła → obowiązkowa oś wrażliwości zamiast wartości punktowej |
| **Kontrola przesuniętych cech** `UNKNOWN` | U poprzednika dała wynik lepszy od baseline. Wyjaśnione szumem przy ich mocy; do domknięcia w M04 |
| ~~Hash zbioru ticków `UNKNOWN`~~ | **ZAMKNIĘTE w M01** — `sha256 = 6b6b3aa4…`, 336 561 plików |
| Zależność od ścieżki do ticków | Projekt nie jest samowystarczalny na poziomie danych źródłowych (ADR-007) |

---

## Czego NIE robimy

- Nie uruchamiamy backtestu przed M03, M04 i prerejestracją spełniającą ADR-011.
- Nie dodajemy ML — dopóki nie wiadomo, czy istnieje prosty efekt.
- Nie mnożymy hipotez, żeby uniknąć wyniku negatywnego.
- Nie otwieramy segmentu 2024–2026.
- Nie dotykamy `market-quant`.
