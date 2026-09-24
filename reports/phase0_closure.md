# Faza 0 — raport zamykający

**Data:** 2026-09-24 · **ADR:** ADR-022 · **Licznik prób:** N = 10 z limitu 50
(7 odziedziczonych + 3 warianty T003) · **Testy:** 585

---

## Werdykt

> **W rodzinie trend/momentum, na sześciu majorsach FX, w latach 2016–2021,
> przy horyzoncie 3 dni: brak dowodów na opłacalną przewagę.**
>
> To jest wynik, nie brak wyniku — ale jego siła jest różna dla każdej
> z trzech hipotez i tych różnic nie wolno zacierać.

| Hipoteza | Status | Co wiadomo | Siła |
|---|---|---|---|
| **H01** momentum | `NOT_SUPPORTED` | Dodatnia relacja, jeżeli istnieje, jest **nieopłacalna**: górne ograniczenie **51,03%** trafności wobec progu **51,72%** | **wykluczenie** obszaru, który kogokolwiek interesował |
| **H02** breakout jako stan | `CLOSED` | Ta sama wielkość co `mom_24`: Spearman **+0,832**, `P(mom > 0 \| stan)` = 0,973 | **redundancja** — dziedziczy wynik H01, nie ma własnego |
| **H07** breakout jako zdarzenie | `EXPLORATORY` | **Nietestowalna** na RESEARCH w tej definicji: 726 zdarzeń, n_eff ≤ 843, `FALSIFIED` wymaga 1 317 | **nic** — ani za, ani przeciw |

Trzy hipotezy, trzy różne rodzaje wyniku. Zdanie „trend nie działa" byłoby
nadużyciem: dotyczy wyłącznie H01, i wyłącznie w stronę dodatnią.

---

## H01 — wykluczenie (T003, `20260924T150658Z-8daa11`)

Warstwa A, Spearman `mom_k` ↔ `fwd_atr`, h = 3 d, 130 553 decyzje na komórkę:

| k | Spearman | SE | CI95 |
|---|---|---|---|
| 24 | +0,0070 | 0,01285 | [−0,0186, +0,0322] |
| 120 | −0,0328 | 0,02212 | [−0,0766, +0,0103] |
| 480 | −0,0315 | 0,02268 | [−0,0781, +0,0121] |

Górne ograniczenie ρ = 0,0322 → **51,03%**. Nie `FALSIFIED`, bo dolne końce
przy k = 120 i 480 wychodzą poza ±0,054 — blokuje niewykluczona relacja
**ujemna**. Punktowe oszacowania ujemne **nie są wynikiem** (post-hoc).

Wiarygodność: SE bootstrapu zgodne z rozkładem zerowym M05 do 8%; ramię
postarzone gorsze od cechy prawdziwej we wszystkich komórkach (anomalia
`market-quant` się nie powtórzyła); checklista leakage'u: 17/17. Kontrola
permutacyjna była nieważna (ADR-019), ale werdykt od niej nie zależał.

## H02 — redundancja (M07, `20260924T154152Z-a734c5`)

| Para cech | Spearman |
|---|---|
| `donch_pos_55` ↔ `mom_24` | **+0,832** |
| `donch_pos_55` ↔ `mom_120` | +0,533 |
| `donch_pos_55` ↔ `mom_480` | +0,260 |

Próg 0,70 zadeklarowany przed przebiegiem. Pomiar cecha↔cecha, zero zwrotów
w przód (ADR-020), zero prób.

## H07 — nierozstrzygalność (M08A, `20260924T200939Z-67315c`)

| | Primary | Wszystkie godziny |
|---|---|---|
| zdarzenia | 726 | 1 048 |
| n_eff, górna granica | 843 | 1 217 |
| n_eff, dolna granica (skupiska okien) | 216 | 177 |
| MDE (moc 80%) | 53,08–56,11% | od 52,56% |

`FALSIFIED` nieosiągalne przy każdym modelu zależności; T002 wycofany przed
prerejestracją (ADR-021). **Zwrotów w przód nikt nie obejrzał** — H07 nie
jest ani osłabiona, ani wzmocniona.

---

## Czego faza NIE zbadała

To nie są luki do zamknięcia za wszelką cenę — to granice, poza które wynik
**nie sięga**:

| Obszar | Dlaczego nie |
|---|---|
| Horyzonty inne niż 3 d | h = 10 d odpadł na koszcie (M03) i mocy (M05); krótsze horyzonty nie mają kalibracji kosztu |
| Relacja **ujemna** (powrót do średniej) | Obserwacja post-hoc z T003; wymagałaby nowego ID i nie potwierdzałaby niczego wstecz |
| Segment OOS 2022–2023 | Ograniczone uruchomienia; zużycie na pomiar odkrywczy spaliłoby go jako walidację |
| Segment 2024–2026 | Zapieczętowany |
| Instrumenty spoza czynnika USD | Jedyne dostępne to kohorta replikacyjna — ADR-018 |
| H03, H04, H05, H06 | Warunkowanie / blokada danych / brak danych / brak komponentów |

---

## Co faza ustaliła o aparaturze

To jest trwalszy wynik niż werdykty — przenosi się na każdą przyszłą hipotezę
na tych danych.

**1. Moc zależy od geometrii cechy, nie od liczby wierszy.**

| Cecha | Wiersze | n_eff | `FALSIFIED` |
|---|---|---|---|
| gęsta, `mom_24` | 130 553 | 5 150 | osiągalne (iloraz 0,51) |
| gęsta, `mom_480` | 130 553 | 1 902 | osiągalne (0,83) |
| rzadka, zdarzenie H07 | 726 | ≤ 843 | **nieosiągalne** (≥ 1,25) |

Próg to n_eff ≈ **1 317** przy obecnym koszcie. Cecha odpalająca na mniej
niż ~1% barów nie ma szans na tym segmencie, zanim ktokolwiek spojrzy na
zwrot.

**2. Dwa razy ta sama lekcja.** M02 (T001) i M08 (T002) wycofały
eksperymenty, które nie mogły zakończyć się `FALSIFIED`. W obu przypadkach
dało się to policzyć **z samej geometrii**, zanim hipoteza dostała plan
trialu. Stąd reguła ADR-022.

**3. Liczby dziedziczone i szacowane były systematycznie optymistyczne.**
σ dziedziczona 2× za mała (M02); `P_eff = 2,00` przeniesione z warstwy B
byłoby niekonserwatywne (M05); „600–700 zdarzeń na parę" było 726 łącznie
(M08). Kierunek błędu za każdym razem ten sam — na korzyść eksperymentu.

**4. Warstwa falsyfikacji decyduje o tym, czy wynik negatywny cokolwiek
znaczy.** Przeniesienie kryteriów z warstwy B na A zwęziło martwą strefę
z 5,61 pp do 0,33 pp (ADR-015). Bez tego T003 skończyłby się
`NOT_SUPPORTED` niezależnie od danych.

**5. Reguły „obecne" nie znaczyły „wykonywane".** Swap nie był znany
symulatorowi (M03); `dsr.py` istniał z testami i nie importował go nikt
(ADR-017); checklista leakage'u była prozą; purge + embargo, wymagane przez
CLAUDE.md „zawsze", nie istniały — był tylko pomiar nakładania. Wszystko to
jest teraz wpięte, aparatura ma testy niezmienników i odmawia instrumentów
nieskalibrowanych (ADR-018).

---

## Stan na zamknięcie

| | |
|---|---|
| N | **10** z 50 — 40 prób w budżecie |
| Segment RESEARCH | oglądany: 7 spojrzeń poprzednika + 3 w T003 |
| OOS / SEALED | nietknięte |
| Długi otwarte | `pbo.py` niewpięty (pierwszy eksperyment z dopasowaniem); kohorta replikacyjna nie istnieje → `SURVIVED` nieosiągalny |

## Jeżeli projekt idzie dalej

Jedyny kandydat o mechanizmie **spoza rodziny trendowej** to **H04 (carry)**.
Zanim dostanie prerejestrację: (1) dane stóp point-in-time dla sześciu walut,
(2) pomiar geometrii cechy według ADR-022 — zero prób. Ryzyko znane z góry:
stopy EUR i JPY przy zerze w 2016–2021 mogą nie dać cesze zmienności.
Jeżeli (2) wypadnie jak M08, H04 zamyka się tak samo, bez wydanej próby.
