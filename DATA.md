# DATA.md — dane, ograniczenia, checklista leakage'u

Każdą liczbę w tym pliku sprawdzać komendą, nie brać na wiarę.

---

## 1. Ceny — ticki Dukascopy

| Element | Stan |
|---|---|
| Źródło | Dukascopy historical tick, bid + ask |
| Ścieżka | `../market-quant/data/raw/dukascopy` — **READ-ONLY** (ADR-007) |
| Instrumenty | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY |
| Zakres | **2015 → 2026**, kompletny |
| Rozmiar | ~11 GB całość; **6,99 GiB** w segmentach RESEARCH + OOS |
| Strefa czasowa | UTC wszędzie, bez wyjątków |
| **Odcisk 2015–2023** | `sha256 = 6b6b3aa4…a63a0`, **336 561** niepustych plików. Pełny zapis: `reports/tick_fingerprint.json` |

Odcisk liczony z metadanych (ścieżka + rozmiar), nie z zawartości: na podmianę,
przycięcie i dobudowanie plików metadane reagują tak samo, a przepuszczenie 11 GB
przez SHA-256 kosztowałoby kilka minut przy każdym uruchomieniu. Odcisk ma
wykrywać **zmianę zbioru**, nie bronić przed spreparowaniem go bajt po bajcie.
Liczony osobno dla lat 2015–2023, żeby nie zmieniał się od lat zapieczętowanych.

**Zasady twarde.** Bid i ask przechowywane osobno; cena mid nie występuje
nigdzie w systemie. Luki > 60 s w godzinach handlowych zliczane i raportowane.
Sesje wyprowadzane z UTC z jawnym uwzględnieniem **różnych dat przełączenia
DST w USA i UE**.

## 2. Świece

Budujemy do własnego `data/` tego projektu — nie do starego repo.

| | Stan |
|---|---|
| Pipeline | tick → M1 → H1, resampling własny |
| Format | Parquet, partycjonowany po `(instrument, rok)` |
| Zbudowane (M01, 2026-09-23) | **2015–2023**, 6 par, 108 partycji, 433 MB |
| Zakres barów | 2015-01-01 → 2023-12-29 |
| Raport jakości | `reports/data_quality.md` — **PRZECHODZI** |

**Weryfikacja przeniesienia (`FACT`).** Te same ticki przez przeniesiony
pipeline dają ramki **identyczne co do bitu** z tymi, które wyprodukował
`market-quant` — sprawdzone na EURUSD 2015, M1 (372 942 bary) i H1 (6 226).
To mocniejszy dowód poprawności portu niż komplet przechodzących testów.

**Pokrycie zmierzone u nas:**

| Symbol | Bary H1 | Brakujące | Luki % |
|---|---|---|---|
| EURUSD | 56 096 | 4 | 0,01 |
| AUDUSD · EURJPY · USDJPY | 56 094 | 6 | 0,01 |
| USDCAD | 56 092 | 7 | 0,01 |
| GBPUSD | 56 091 | 9 | 0,02 |

Mediana spreadu (pipsy): EURUSD 0,3 · USDJPY 0,4 · EURJPY 0,7 ·
AUDUSD 1,0 · GBPUSD 1,0 · USDCAD 1,1.

**Godziny bez ticków u wszystkich par naraz: 4, wszystkie wyjaśnione.**
Trzy odziedziczone po `market-quant` potwierdzone naszym przebiegiem; czwarta
(`2023-12-24 22:00`) wykryta tutaj, w segmencie OOS, którego tamten projekt
nigdy nie zbudował — ADR-010. Lista akceptacji jest **zamknięta i imienna**,
każda pozycja niesie dowód, a detektor nie został osłabiony. Pilnuje tego
`test_config_accepts_exactly_the_four_audited_hours`.

## 3. Podział segmentów (ADR-004)

| Segment | Zakres | Reguła dostępu |
|---|---|---|
| RESEARCH | 2015-01-01 → 2021-12-31 | Swobodny. **Oglądany wcześniej** — 7 prób `market-quant` |
| OOS | 2022-01-01 → 2023-12-31 | Ograniczone uruchomienia, każde logowane |
| **SEALED** | 2024-01-01 → koniec danych | **Zero dostępu.** Nietknięty także przez poprzednika |

Pieczęć egzekwuje loader, a nie brak plików — ticki dla lat zapieczętowanych
istnieją na dysku. Loader musi rzucać wyjątkiem przy próbie sięgnięcia poza
dozwolony segment. **Do zaimplementowania w fazie 1.**

Rok 2015 jest okresem rozgrzewki cech — bez decyzji. Pierwsze decyzje:
2016-01-01.

## 4. Makro

| Element | Stan |
|---|---|
| Kalendarz wydarzeń | 18 modułów źródeł oficjalnych w `market-quant` (FOMC, ECB, BoE, BoJ, RBA, BoC, BLS, BEA, Eurostat, ONS, StatCan, ABS, Census…) |
| Zawartość | Wyłącznie `(timestamp_utc, waluta, nazwa, ranga)`. **Bez wartości `actual`/`consensus`/`previous`** |
| Stopy | FRED/ALFRED, pokrycie sprawdzane dniami decyzji |
| Dostęp | **Wyłącznie point-in-time**: ALFRED z `realtime_start` = data decyzji, plus margines 1 dnia roboczego na opóźnienie publikacji |
| Status w tym projekcie | Nieprzeniesione. Potrzebne dopiero przy H04 |

**Zakazane:** scraping ForexFactory/Investing.com; jakiekolwiek użycie
`consensus` lub `surprise` — brak darmowego archiwum point-in-time, więc
wartości „historyczne" są w rzeczywistości zrewidowane.

**`UNKNOWN` odziedziczony:** rentowności 2-letnie nie istnieją w jednej
spójnej definicji dla wszystkich walut koszyka. `market-quant` zszedł na
`interbank_3m` i zawęził uniwersum. Blokuje H04 do czasu własnej pracy
nad danymi.

## 5. Czego nie mamy

| Brak | Skutek |
|---|---|
| **Kohorta replikacyjna: XAUUSD, WTI, S&P 500, DAX** | **Zero bajtów.** Nigdy nie pobrana. Replikacja niemożliwa → żadna hipoteza nie osiągnie `SURVIVED` (ADR-008) |
| Kalendarze sesji dla indeksów | Indeksy nie chodzą 24/5; luki otwarcia są codzienne, nie tygodniowe |
| Model finansowania CFD | W indeksach płaci się **pełną** stawkę, nie różnicę — koszt rzędu całego poszukiwanego efektu |
| Obsługa dywidend CFD | Nieciągłość w serii indeksu cenowego |

## 6. Koszty — model (przeniesienie z `market-quant`, ADR-005)

| Składnik | Model |
|---|---|
| Spread | **Rzeczywisty tickowy bid/ask w momencie fillu.** Nigdy średni, nigdy mid |
| Podłoga kosztu | `max(spread + prowizja, podłoga)`; 1,5 pipsa majors, 2,5 crosses |
| Poślizg — wejście | ≥ 0,5 × spread, niekorzystnie |
| Poślizg — stop | ≥ 1,0 × spread, niekorzystnie. **Asymetria zamierzona**: stop realizuje się wtedy, gdy rynek się porusza |
| Poślizg — TP | 0, ale fill tylko przy pełnym przekroczeniu poziomu |
| Swap | Broker-specific, potrójny w środę. Marża `UNKNOWN` → **obowiązkowa oś wrażliwości** {0,5%, 1%, 2%}, nigdy wartość punktowa |
| Luka weekendowa | Fill po pierwszej dostępnej cenie. **Stopy nie chronią przez lukę** |
| Kolejność barier | **Rozstrzygana na tickach.** Awaryjnie: SL pierwszy. Nigdy optymistycznie |

Raportowanie obowiązkowe: wynik przy **1×, 2× i 3×** kosztach.

## 7. Dwie rozłączne skale zmienności

Mylenie ich degeneruje etykiety — to był ADR-023 poprzednika i obowiązuje tu
bez zmian:

| Skala | Zastosowanie |
|---|---|
| `atr_h1_14` | **Wyłącznie** normalizacja cech |
| `atr_d1_14` | **Wyłącznie** skalowanie barier i jednostka R |

Bariera musi odpowiadać horyzontowi (`bariera ≈ σ√T`). Bariery rzędu
`2 × atr_h1_14` przy horyzoncie wielodniowym zostałyby trafione w ciągu godzin,
bariera czasowa nigdy by nie zadziałała, a etykiety zdegenerowałyby się do
szumu mikrostruktury.

**Doba niepełna wypada z szeregu dziennego.** Sesja niedzielna (3 bary H1)
tworzyłaby własny bar dzienny i zaniżała `atr_d1_14` o ~12% na wszystkich
parach — czyli zaniżała jednostkę R, czyli wszystko. Próg: ≥12 barów H1 na dobę.

---

## 8. Checklista leakage'u — przed KAŻDYM raportowanym wynikiem

Leakage jest błędem krytycznym, nie usterką. Wynik uzyskany z jego pomocą jest
nieważny, a nie „trochę zawyżony".

- [ ] Wszystkie normalizacje w oknie **rozszerzającym**, wyłącznie z przeszłości
- [ ] Żaden `fit()` nie widział danych testowych — w tym skaler, imputer, kalibrator
- [ ] Bar H1 **zamknięty** przed momentem decyzji; użyto `last_closed_bar()`, nie ręcznej arytmetyki na znacznikach
- [ ] Wartości dzienne pochodzą z ostatniej **zamkniętej pełnej** doby (bar o 10:00 nie zna dnia, w którym leży)
- [ ] Symulator fillów nie widzi cen po momencie decyzji
- [ ] Kolejność barier: tickowo albo pesymistycznie, **nigdy optymistycznie**
- [ ] Bid/ask osobno, **nigdzie mid**
- [ ] Makro przez ALFRED z `realtime_start` = data decyzji
- [ ] Granice segmentów (RESEARCH / OOS / SEALED) nieprzekroczone; horyzont mieści się w segmencie
- [ ] Nakładanie etykiet obsłużone: purge + embargo, do testów wchodzi **n_eff**
- [ ] Zbiór instrumentów zamrożony przed przebiegiem
- [ ] Parametry zapisane w YAML z hashem gita **przed** uruchomieniem; drzewo czyste
- [ ] `trials/trials.jsonl` zaktualizowany automatycznie
- [ ] **Żadne wejście do backtestu nie pochodzi od LLM**
- [ ] Kontrola przesuniętych cech przeszła — wynik **nie rośnie**, gdy cechy postarzone o bar

**Uwaga do ostatniego punktu.** W `market-quant` ta kontrola zapaliła się
nietypowo: cechy przesunięte dały wynik **lepszy** niż baseline (−0,0268 vs
−0,0560 R). Tamten projekt wyjaśnił to szumem i miał rację przy swojej mocy
(połowa CI 0,067 R). Przy naszej większej mocy to jest `UNKNOWN` do domknięcia
— krok M04, przed pierwszym eksperymentem.
