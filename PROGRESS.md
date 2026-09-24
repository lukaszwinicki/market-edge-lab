# PROGRESS.md — bieżący stan

Log stanu: co zrobiono, gdzie jesteśmy, co dalej, co blokuje.
**Nie jest źródłem prawdy** — w razie sprzeczności wygrywa `DECISIONS.md`.

Ten plik ma zostać krótki, żeby dało się go przeczytać w całości na starcie
sesji. **Narracja zamkniętych kroków żyje w `EXPERIMENTS.md` i `reports/`** —
tutaj zostają tylko liczby, które trzeba mieć w głowie, i to, co otwarte.

Każdą liczbę sprawdzać komendą, nie brać na wiarę.

---

## Gdzie jesteśmy

**Seria kontrolna M01–M06 ZAMKNIĘTA.** Aparatura ma sprawdzone **zero**
(M03), sprawdzone **wzmocnienie** (M04), zmierzony **rozkład zerowy metryki
głównej** (M05) i zero **pełnego** modelu kosztu (M06).

**T003 jest PREREJESTROWANY i ZAMROŻONY** (2026-09-24) —
`configs/t003_momentum.yaml`, `sha256 c832dcdc…`. Pierwszy protokół na
hipotezie, który spełnia wszystkie sześć warunków ADR-011. Nieuruchomiony.

**Licznik prób: N = 7** (odziedziczone, ADR-004). Uruchomionych prób
strategii w tym projekcie: **0**. M01–M06 to kontrole, nie liczą się do N.
T003 doliczy **3** (N → 10), nie 6 jak T001.

**Testy: 379.** **Oba warunki startu T003 zamknięte** (2026-09-24), runner
kompletny wobec prerejestracji (warstwa A i B, osie, diagnostyka par,
`t003.md`, `observations.parquet`) i sprawdzony `--self-test`.
**Następny krok: uruchomienie T003**, N: 7 → 10. Jedyny pozostały krok
i jedyny, który zapala próby.

---

## Seria kontrolna — wynik

| Krok | Wynik | Co ustalił |
|---|---|---|
| **M01** | **PRZECHODZI** | Port `market-quant` daje ramki **identyczne co do bitu**. Świece 2015–2023, 6 par; odcisk `sha256 = 6b6b3aa4…`; pieczęć 2024–2026 działa. Godzina `2023-12-24 22:00` przyjęta z dowodem (ADR-010) |
| **M02** | **NIEROZSTRZYGNIĘTE** → T001 wycofany | Audyt mocy (ADR-009). Bramka nie rozstrzygnęła, ale wynik pod nią wystarczył |
| **M03** | **PRZECHODZI** | Wejścia losowe dają expectancy = −koszt w granicach **1 SE**. Wynikowi negatywnemu będzie można wierzyć |
| **M04** | **PRZECHODZI** | Wzmocnienie poprawne; próg opłacalności **51,72%** trafności kierunku |
| **M05** | **PRZECHODZI** | `n_eff` warstwy A **zmierzone**: 1 902–5 150. `FALSIFIED` osiągalne we wszystkich komórkach T003 |
| **M06** | **PRZECHODZI** | Zero **pełnego** modelu kosztu: **−0,0422 R** (h=3d, marża 1%). Złożenie swapu identyczne co do bitu |

Raporty: `reports/m02_power_audit.md`, `m03_random_control.md`,
`m04_sensitivity.md`, `m05_layer_a_null.md`. Przebiegi:
`20260923T172201Z-fa3731`, `…T175353Z-087adf`, `…T181510Z-963686`,
`20260924T134703Z-cd0d96`, `…T141045Z-c94360`. M06 nie ma osobnego raportu —
jego narracja żyje w ADR-016 i `EXPERIMENTS.md`.

### Liczby, które trzeba mieć w głowie

Siatka T003 — **warstwa A**, h = 3 d, Spearman. Próg opłacalności **51,72%**.
Progi wykrywalności **po korekcie Holma** na 3 komórki — tak, jak działa
kryterium `SUPPORTED`. Bez korekty byłoby 51,24 / 51,86 / 52,05%.

| k | n_eff (zmierzone) | Próg wykrywalności | Martwa strefa | `FALSIFIED` |
|---|---|---|---|---|
| 24 | 5 150 | 51,44% | **−0,28 pp** | osiągalne (0,51) |
| 120 | 2 302 | 52,15% | +0,43 pp | osiągalne (0,76) |
| 480 | 1 902 | 52,36% | +0,64 pp | osiągalne (0,83) |

`FALSIFIED` nie wymaga korekty — wymaga spełnienia we **wszystkich** komórkach
naraz (intersection-union), a taki test kontroluje błąd I rodzaju bez niej.
Liczba w nawiasie to iloraz „połowa CI95 / próg opłacalności": poniżej 1
znaczy, że wynik bliski zera **rozstrzyga**, zamiast wpadać w „nie wiadomo".

Warstwa B, dla porównania i do wyceny ekonomicznej:

| | h = 3 d |
|---|---|
| σ wyniku w R (dla geometrii 1,1/2,2) | 0,9165 |
| Koszt modelowany / **pełny, z marżą swapu 1%** | 0,0297 / **0,0422 R** |
| Zero przyrządu przy pełnym koszcie (M06) | **−0,0373 R**, luka 0,96 SE |
| Próg wykrywalności warstwy B | **57,33%** — **nie jest już instrumentem falsyfikacji** |

---

## Sześć ustaleń, które ukształtowały T003

**1. σ była dziedziczona, nie mierzona — i 2× za mała** (M02, `FACT`).
ADR-009 implikował 0,455 R; zmierzone **0,92 R**. Stąd wycofanie T001
(ADR-011).

**2. Symulator nie zna swapu** (M03, `FACT`; **zamknięte przez ADR-016**).
Przy h=10d brakujący człon to **1,32× cały modelowany koszt**. `INFERENCE`: przewaga kosztowa długiego
horyzontu była **artefaktem pominięcia swapu** — stosunek kosztu h=3d/h=10d
spada z 1,76× do **1,08×**. **h=3d dominuje h=10d na obu osiach.**

**3. Bariery prawie nie wiążą** (M04, `FACT`). Przy doskonałym kierunku 84%
pozycji kończy na barierze czasowej. Ale zmiana geometrii jest **bezwartościowa**
(ADR-014, `FACT`): σ i wzmocnienie skalują się razem, więc usunięcie barier
w całości zmienia próg trafności o **+0,07 pp**, unieważniając przy tym σ z M02
i kalibrację M03/M04.

**4. Martwa strefa brała się z warstwy, nie z geometrii ani z modelu par**
(ADR-015, `INFERENCE` potwierdzony przez M05). Kryteria T001 stały na
expectancy w net R, czyli na warstwie B — wbrew ADR-003, który przypisał
warstwie A „wykrywanie, maksymalna moc". Przeniesienie ich na warstwę A
zwęziło martwą strefę z **5,61 pp do 0,33 pp** w najgorszej komórce.

**5. `P_eff` warstwy A wynosi 3,21, nie 2,00** (M05, `FACT`). Liczba z ADR-014
dotyczy statystyk liniowych w znaku cechy. Dla statystyki relacji kowariancja
idzie jak iloczyn `ρ^cecha · ρ^zwrot`. Zmierzone, nie przeniesione.

**6. „Zrównanie znaków" NIE jest konserwatywne na warstwie A** (M05, `FACT`).
Model, który miał być krańcem pesymistycznym, dał `P_eff ≈ 7,0` — więcej niż
sześć par niezależnych, bo ujemne iloczyny **kasują** wariancję.
`INFERENCE`: przepisanie `P_eff = 2,00` z warstwy B „dla ostrożności" byłoby
założeniem niekonserwatywnym, wyglądającym na ostrożne.

---

## Decyzje z tej fazy

| ADR | Treść |
|---|---|
| **ADR-011** | T001 → `WITHDRAWN`, nigdy nieuruchomiony, **N bez zmian**. Zastępuje go T003. **Każde przyszłe wycofanie wymaga tego samego dowodu** |
| **ADR-012** | Dopóki hipoteza nie ma żywej, zamrożonej prerejestracji, **żaden przebieg nie może dotknąć jej cechy** |
| **ADR-013** | Ramię „wyrocznia postarzona" nie powstało — łamałoby regułę z ADR-012. Reguła zadziałała przeciwko zaleceniu z tego samego ADR-u |
| **ADR-014** | `P_eff = 2,00` dla warstwy B (model implikowany przez **mechanizm H01**, nie ostrożność). **Geometria barier bez zmian** — zmiana warta ≤0,07 pp, kosztuje powtórzenie audytu mocy |
| **ADR-015** | Kryteria falsyfikacji **wracają na warstwę A** — to przywrócenie ADR-003, nie przebudowa. Warstwa B = wycena, nie test. Siatka **3 komórki**, h=10d usunięty. N: 7 → 10 |
| **ADR-016** | Marża swapu **nie wchodzi** do `CostModel` — jest osią, nie punktem. Pełny koszt składa się na wyniku symulacji; M06 potwierdził identyczność co do bitu. Warunek 6 spełniony |
| **ADR-017** | DSR **wreszcie liczony** — `dsr.py` nie był importowany przez nic, mimo że ADR-004 prowadził licznik właśnie dla niego. `V[SR]` jako nawias. Dla T003 **diagnostyka**, nie kryterium; każda przyszła prerejestracja deklaruje deflację przed zamrożeniem |

---

## Następne kroki

| # | Krok | Rozstrzyga |
|---|---|---|
| ~~1–5~~ | ~~**M01–M05** — seria kontrolna~~ | **ZAMKNIĘTA** |
| ~~6~~ | ~~**Prerejestracja T003**~~ | **ZAMROŻONA** 2026-09-24, `sha256 c832dcdc…` |
| ~~7~~ | ~~**Warstwa etykiet**~~ | **GOTOWA** — `src/research/labels.py`, bez treści hipotezy w module |
| ~~8~~ | ~~**Pełny koszt z finansowaniem**~~ | **GOTOWY** — ADR-016 + M06. Swap NIE wchodzi do `CostModel` |
| **9** | **T003 — uruchomienie** ← **TU JESTEŚMY** | **N: 7 → 10.** Pierwsza próba zapalona w tym projekcie. `scripts/t003_momentum.py` gotowy; `--self-test` przechodzi, licznika nie rusza |
| 10 | **T002** — H07 zdarzenie vs H02 stan, redundancja z H01 | Prerejestracja po zamknięciu T003 |

**Dlaczego swap nie trafił do `CostModel`** (ADR-016). Marża jest **osią**,
nie punktem: prerejestracja wymaga trzech wartości z jednego przebiegu, więc
liczba wpisana w `CostModel` spełniałaby `included: true`, łamiąc
`margin_axis`. Doliczenie po fakcie jest identyczne co do bitu (M06, 197 847
transakcji) i nie unieważnia weryfikacji M01/M03/M04.

---

## Blokery i znane ograniczenia

| Sprawa | Stan |
|---|---|
| **Kohorta replikacyjna nie istnieje** | Zero bajtów dla XAUUSD, WTI, S&P 500, DAX. Replikacja niemożliwa → **żadna hipoteza nie osiągnie `SURVIVED`** w tej fazie (ADR-008). Najwyższy status: `SUPPORTED` |
| **Sześć par to sześć odmian jednego zakładu** | Średnia \|ρ\| = 0,401 na oknie h, 0,389–0,404 na oknach k. Stąd `P_eff` ≈ 3,2, a nie 6. **Jedyna dźwignia ruszająca to o czynnik to instrumenty spoza czynnika USD** — czyli ta sama kohorta replikacyjna, której nie ma. Zdobycie tych danych kupuje H01 więcej mocy niż cokolwiek w prerejestracji |
| **Segment RESEARCH był oglądany** | 7 prób poprzednika na tych samych danych. Poprzeczka DSR startuje podwyższona (ADR-004) |
| ~~Warstwa etykiet~~ | **ZBUDOWANA** 2026-09-24 |
| ~~Swap nie wpięty~~ | **ZAMKNIĘTE** przez ADR-016 — wpięcie do `CostModel` odrzucone jako łamiące oś marży; pełny koszt składa się na wyniku symulacji |
| **T003 nie deklaruje deflacji o próby odziedziczone** | Kryteria uwzględniają wielokrotność **w obrębie** przebiegu (Holm na 3 komórki), nie **między** przebiegami (7 spojrzeń poprzednika). Nie unieważnia T003 — kryteria są spójne i osiągalne — ale DSR wchodzi tam wyłącznie jako diagnostyka (ADR-017). Przyszłe prerejestracje deklarują deflację przed zamrożeniem |
| **`pbo.py` nadal niewpięty** | PBO wymaga macierzy wariantów na podokresach; T003 nic nie dopasowuje, więc nie ma z czego jej zbudować. Należy do pierwszego eksperymentu z dopasowaniem (ADR-017) |
| **Kubełki `vol_regime` nie były w prerejestracji** | Prerejestracja wymienia oś `vol_regime`, nie podając granic. Przyjęte **tercyle**, zadeklarowane w kodzie **przed** uruchomieniem T003 (`VOL_REGIME_EDGES`). Nie wchodzą do żadnego kryterium falsyfikacji — te liczą się na komórce, nie na kubełku |
| **Martwa strefa przy k = 480** | +0,64 pp po korekcie Holma: efekt o trafności między 51,72% a 52,36% będzie realnie opłacalny, a pomiar zwróci `NOT_SUPPORTED`. **Zapisane w prerejestracji przed uruchomieniem**, nie do odkrycia po fakcie |
| **Rentowności 2-letnie** `UNKNOWN` | Brak spójnej definicji dla wszystkich walut. Blokuje H04 |
| **Kontrola przesuniętych cech** `UNKNOWN` | Anomalia poprzednika nadal nierozstrzygnięta na cesze prawdziwej — rozstrzyga ją **ramię kontrolne wewnątrz T003**, z kryterium zapisanym przed uruchomieniem |
| Zależność od ścieżki do ticków | Projekt nie jest samowystarczalny na poziomie danych źródłowych (ADR-007) |

---

## Czego NIE robimy

- **Nie zmieniamy `configs/t003_momentum.yaml`.** Po zamrożeniu każda zmiana
  to nowy eksperyment z nowym ID, nie poprawka T003. Runner sprawdza hash
  i odmawia startu **przed** wpisem do rejestru.
- **Nie ma trybu „próbnego na prawdziwych danych".** Przebieg, który policzył
  statystykę warstwy A na segmencie RESEARCH i został przerwany, JEST próbą —
  zobaczył wynik. Sprawdzanie maszynerii idzie przez `--self-test`
  na danych syntetycznych.
- **Nie dotykamy `mom_k` żadnym przebiegiem poza T003** (ADR-012).
- Nie dodajemy ML — dopóki nie wiadomo, czy istnieje prosty efekt.
- Nie mnożymy hipotez, żeby uniknąć wyniku negatywnego.
- Nie otwieramy segmentu 2024–2026.
- Nie dotykamy `market-quant`.
