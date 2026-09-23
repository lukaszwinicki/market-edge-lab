# Raport jakości danych

> Wygenerowano: 2026-09-23 16:52 UTC
> Bramka 0: **PRZECHODZI**

## Pokrycie

| Symbol | Bary H1 | Oczekiwane | Brakujące | Luki % | Od | Do |
|---|---|---|---|---|---|---|
| AUDUSD | 56,094 | 56,100 | 6 | 0.01 | 2015-01-01 | 2023-12-29 |
| EURJPY | 56,094 | 56,100 | 6 | 0.01 | 2015-01-01 | 2023-12-29 |
| EURUSD | 56,096 | 56,100 | 4 | 0.01 | 2015-01-01 | 2023-12-29 |
| GBPUSD | 56,091 | 56,100 | 9 | 0.02 | 2015-01-01 | 2023-12-29 |
| USDCAD | 56,092 | 56,099 | 7 | 0.01 | 2015-01-01 | 2023-12-29 |
| USDJPY | 56,094 | 56,100 | 6 | 0.01 | 2015-01-01 | 2023-12-29 |

## Spread (w pipsach)

| Symbol | close mediana | close p95 | max mediana | max p95 | max zaobserwowany | ticki/bar |
|---|---|---|---|---|---|---|
| AUDUSD | 1.00 | 2.40 | 1.40 | 5.90 | 35.00 | 2,716 |
| EURJPY | 0.70 | 3.00 | 1.20 | 8.50 | 37.50 | 6,010 |
| EURUSD | 0.30 | 1.20 | 0.60 | 3.80 | 34.40 | 3,689 |
| GBPUSD | 1.00 | 3.50 | 1.50 | 8.50 | 40.00 | 3,877 |
| USDCAD | 1.10 | 3.20 | 1.60 | 7.40 | 35.00 | 3,028 |
| USDJPY | 0.40 | 1.60 | 0.80 | 5.20 | 35.00 | 3,298 |

## Podejrzenie awarii feedu

Wykryto 4, wszystkie zaakceptowane ręcznie — patrz sekcja niżej. Brak godzin nierozstrzygniętych.

## Zaakceptowane ręcznie (ADR-045)

**4 godzin** wykrytych przez detektor i zaakceptowanych jawnie w `data.quality.accepted_outages`. Detektor NIE został osłabiony — każda z tych godzin nadal jest wykrywana.

| Godzina UTC | Powód | Dowód | Zaakceptowano |
|---|---|---|---|
| 2016-09-02 18:00 | awaria feedu Dukascopy wewnatrz dnia handlowego, ~1-2 h | 17:00 = 4,5-8,9 kB (zapadniete ~10x), 18:00 = 0 na 6 parach, 19:00 = 20-40 kB; 1 bar H1 z 43 634 na pare | 2026-09-21 |
| 2017-12-24 22:00 | opoznione otwarcie tygodnia (Wigilia) — rynek stal, nie awaria | caly blok 18:00-22:00 = 0 na 6 parach, dane wracaja o 23:00 (0,5-1,7 kB); brak barow w kazdym zrodle | 2026-09-21 |
| 2019-05-26 22:00 | opoznione otwarcie tygodnia — poniedzialek 27.05.2019 to Memorial Day i UK spring bank holiday | blok 18:00-22:00 = 0 na 6 parach, 23:00 = 0-53 B, 00:00 = 6-34 kB | 2026-09-21 |
| 2023-12-24 22:00 | opoznione otwarcie tygodnia — Wigilia 24.12.2023 wypadla w niedziele, rynek stal; nie awaria feedu | blok 17:00-22:00 = 0 B na 6 parach, pliki ISTNIEJA i sa puste (downloader sprawdzil, nie zawiodl); 23:00 = 34-468 B (handel sladowy), 25.12 00:00 = 380-1902 B, normalne obroty dopiero 26.12 (5-18 kB). Piatek 22.12 22:00 = 0 na 6 parach, czyli zwykle zamkniecie tygodnia | 2026-09-23 |

## Zamknięcia świąteczne

Godziny puste u wszystkich par w blokach dotykających 25.12 albo 1.01 (≤ 36 h). Nie liczone jako luki ani awarie.

| Data | Godzin |
|---|---|
| 2015-12-25 | 13 |
| 2015-12-31 | 2 |
| 2016-01-01 | 21 |
| 2017-12-25 | 14 |
| 2017-12-31 | 2 |
| 2018-01-01 | 22 |
| 2018-12-25 | 14 |
| 2018-12-31 | 1 |
| 2019-01-01 | 22 |
| 2019-12-25 | 14 |
| 2019-12-31 | 2 |
| 2020-01-01 | 22 |
| 2020-12-25 | 13 |
| 2020-12-31 | 2 |
| 2021-01-01 | 21 |
| 2023-12-25 | 14 |

## Komórki niejednoznaczne

Pokrycie między 20% a 80% — ani stabilnie handlowe, ani zamknięte. Typowo granica DST (otwarcie niedzielne przesuwa się między 21:00 a 22:00 UTC), ale systematyczna awaria wygląda tak samo.

| Symbol | Dzień tyg. | Godz. UTC | Pokrycie |
|---|---|---|---|
| AUDUSD | 5 | 21 | 34% |
| AUDUSD | 7 | 21 | 65% |
| EURJPY | 5 | 21 | 34% |
| EURJPY | 7 | 21 | 65% |
| EURUSD | 5 | 21 | 34% |
| EURUSD | 7 | 21 | 65% |
| GBPUSD | 5 | 21 | 34% |
| GBPUSD | 7 | 21 | 65% |
| USDCAD | 5 | 21 | 34% |
| USDCAD | 7 | 21 | 65% |
| USDJPY | 5 | 21 | 34% |
| USDJPY | 7 | 21 | 65% |
