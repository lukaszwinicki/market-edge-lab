# M02 — audyt mocy

**Data:** 2026-09-23 · **ADR:** ADR-009 · **Rodzaj:** `control` — **nie liczy się do N**
**Przebieg:** `20260923T172201Z-fa3731` (pełne artefakty w `runs/<id>/`)
**Licznik po M02:** N = 7, bez zmian.

Uruchomienie odbyło się dwa razy. Pierwsze (`20260923T171835Z-3c880d`) dało
**identyczne liczby** — ziarno jest zapisane, pomiar deterministyczny. Drugie
dokłada licznik barów niejednoznacznych i zamienia binarny werdykt bramki na
trójstanowy. Oba wpisy są w `trials.jsonl`, żaden nie liczy się do N.

---

## Werdykt

> **NIEROZSTRZYGNIĘTE.** Horyzont 10 dni bramkę **przekracza przy każdym
> założeniu** (MDE 0,085–0,146 R). Horyzont 3 dni siada **dokładnie na progu**:
> 0,0796 R przy progu 0,08 R, czyli różnica czterokrotnie mniejsza od własnego
> błędu pomiaru (±0,0018 R).

ADR-009 blokuje T001 tylko wtedy, gdy MDE ≥ 0,08 R przy **obu** horyzontach.
Jeden horyzont musiałby więc bramkę przepuścić — i h = 3 d robi to albo nie
robi, zależnie od tego, jak policzymy niezależność sześciu par. To jest
**decyzja, nie pomiar**, i dlatego M02 jej nie rozstrzyga sam.

| Model niezależności par | MDE h=3d | MDE h=10d | Werdykt |
|---|---|---|---|
| Pary niezależne (P = 6) | 0,0459 **PRZEPUSZCZA** | 0,0848 BLOKUJE | T001 może wystartować |
| Korelacja ze znakiem (P_eff = 4,88) | 0,0515 **PRZEPUSZCZA** | 0,0941 BLOKUJE | T001 może wystartować |
| **Korelacja na \|ρ\| (P_eff = 2,0)** | **0,0796 NIEROZSTRZYGNIĘTE** | 0,1463 BLOKUJE | **nierozstrzygnięte** |

Konwencja mocy — ADR-009 podaje próg 0,08 R, ale nie definiuje, czym jest
„wykrywalna przewaga". Przyjęto: test dwustronny, α = 0,05, **moc 80%**, czyli
MDE = (z₀,₉₇₅ + z₀,₈₀)·σ/√n = 2,8016·σ/√n. Ta konwencja odtwarza liczby
odziedziczone: przy n_eff = 172 i σ = 0,455 daje 0,097 R, a `market-quant`
raportował „wyłącznie ≥ 0,10 R".

---

## Co zmierzono — trzy wielkości, trzy osobne pomiary

Moc zależy od geometrii próby, nie od treści sygnału. Skrypt **nie liczy
`mom_k`** — sprawdza wyłącznie, czy cecha jest OKREŚLONA (480 wcześniejszych
barów, dodatni `atr_h1_14`, dostępny `atr_d1_14`). Wartości ani znaku cechy
nikt nie oglądał, więc pierwsza próba T001 nie została zapalona.

### 1. Nakładanie okien — `FACT`

Siatka decyzyjna T001: 6 par, decyzje 2016-01-01 → 2021-12-31, sesja primary
08:00–22:00 UTC (14 decyzji na dobę handlową). **37 403 decyzje na parę.**

| h | Wierszy (primary) | n_eff | Wierszy na obserwację | `overlap_fraction` |
|---|---|---|---|---|
| 3 d | 130 553 | **3 126** | 41,8 | 1,000 |
| 10 d | 129 965 | **936** | 138,9 | 1,000 |

Rozrzut między parami zerowy: każda para daje 521 (h=3) albo 156 (h=10)
rozłącznych okien — bo n_eff jest funkcją kalendarza, nie rynku. 521 × 3 =
1 563 i 156 × 10 = 1 560 dni roboczych, co zgadza się z długością segmentu.

`overlap_fraction` = 1,000 przy obu horyzontach: **każde** okno wynikowe
zachodzi na następną decyzję. Stąd kolaps 130 tys. → 3 tys.

### 2. Sesja nie kupuje mocy — `FACT`

| h | Sesja | Wierszy | n_eff |
|---|---|---|---|
| 3 d | primary 08–22 | 130 553 | 3 126 |
| 3 d | secondary (wszystkie godziny) | 223 994 | **3 126** |
| 10 d | primary 08–22 | 129 965 | 936 |
| 10 d | secondary (wszystkie godziny) | 222 986 | **936** |

Wariant „wszystkie godziny" dokłada **+72% wierszy i dokładnie zero**
obserwacji niezależnych. Obie sesje są prerejestrowane i obie mają być
raportowane — ale jako pytanie o realizm wykonania, nie o moc. W bilansie
porównań wielokrotnych druga sesja kosztuje, a nie daje.

### 3. Sześć par to nie sześć rynków — `FACT` + `INFERENCE`

Korelacja zwrotów target A na oknach rozłącznych, uśredniona po wszystkich
fazach przerzedzenia (h = 10 d, 1 547 wspólnych dni):

| | EURUSD | GBPUSD | USDJPY | AUDUSD | USDCAD | EURJPY |
|---|---|---|---|---|---|---|
| EURUSD | 1,00 | 0,54 | −0,49 | 0,51 | −0,38 | 0,39 |
| GBPUSD | | 1,00 | −0,06 | 0,51 | −0,48 | 0,45 |
| USDJPY | | | 1,00 | −0,15 | 0,02 | 0,59 |
| AUDUSD | | | | 1,00 | −0,73 | 0,30 |
| USDCAD | | | | | 1,00 | −0,33 |
| EURJPY | | | | | | 1,00 |

Średnia korelacja ze znakiem to zaledwie 0,046 — ale średnia z **wartości
bezwzględnych 0,395**. Dominuje wspólny czynnik USD, a znak zależy tylko od
tego, po której stronie kwotowania siedzi dolar.

`INFERENCE`. To rozróżnienie decyduje o bramce. T001 uśrednia zwroty
**przemnożone przez znak cechy**, a nie zwroty surowe. Gdy dolar się umacnia,
`mom(EURUSD) < 0` i `mom(USDCAD) > 0` — obie pozycje są tym samym zakładem
o USD, a ich wyniki po przemnożeniu przez znak są skorelowane **dodatnio**.
Ujemna korelacja surowych zwrotów przestaje więc pomagać, i właściwą miarą
jest |ρ|:

| Model | P_eff (h=3) | P_eff (h=10) |
|---|---|---|
| Pary niezależne | 6,00 | 6,00 |
| P²/ΣΣρ (ze znakiem) | 4,76 | 4,88 |
| **P²/ΣΣ\|ρ\| (konserwatywnie)** | **2,00** | **2,02** |

Nawiasu nie da się domknąć bez policzenia znaku cechy — a tego M02 świadomie
nie robi. Przedział [2,0; 6,0] jest **matematycznie ciasny**: obejmuje każdy
możliwy proces znaku. Wybór punktu wewnątrz niego jest decyzją, nie pomiarem.

### 4. σ wyniku w R — **najważniejszy wynik M02** — `FACT`

Symulator tickowy na barach M1, po 2 000 losowanych decyzji na horyzont,
wejście w **obie** strony z każdej (pod hipotezą zerową rozkład wyniku nie
zależy od kierunku, więc pula long+short jest rozkładem „bez przewagi").
Bariery z prerejestracji T001, ziarno 20260923.

| | h = 3 d | h = 10 d |
|---|---|---|
| Symulacji | 4 000 | 4 000 |
| Rozstrzygniętych | 3 952 | 3 960 |
| **σ w R** | **0,9165 ± 0,0103** | **0,9261 ± 0,0104** |
| σ long / short | 0,912 / 0,921 | 0,924 / 0,928 |
| Średnie R (dryf kosztowy) | −0,0308 | −0,0098 |
| Barów niejednoznacznych | **0** | **0** |

**σ była dziedziczona, nie mierzona.** Tabela szacunków w ADR-009 powstała
przez przeskalowanie połowy CI z `market-quant` przez √n — co odpowiada
σ = 0,455 R przy obu horyzontach (0,042·√450/1,96 = 0,4546;
0,023·√1500/1,96 = 0,4545). Sam `market-quant` implikuje σ = 0,448
(0,067·√172/1,96). **Zmierzona σ jest dwa razy większa: 0,92 R.**

To jest dokładnie ten błąd, przed którym ADR-009 ostrzegał we własnym
uzasadnieniu („to są szacunki, nie pomiary") — tyle że siedział on nie
w n_eff, tylko w σ. n_eff ADR-009 zgadł nieźle (~450 przy h=10 wobec
zmierzonych 315–761; ~1500 przy h=3 wobec 1 040–2 482). Pomylił się o 2×
na rozrzucie.

`INFERENCE`. σ = 0,92 R przy obu horyzontach, mimo trzykrotnie różnej długości
okna, potwierdza, że skalowanie barier przez σ√T działa zgodnie z zamiarem:
jednostka R rośnie razem z horyzontem i rozrzut w R zostaje stały.

---

## Konsekwencja, której nie było w planie

**Przy h = 10 d T001 miałby mniejszą moc niż eksperyment, który miał poprawić.**

| | `market-quant` | T001 h=10d (konserwatywnie) |
|---|---|---|
| n_eff | 172 | 315 |
| σ w R | 0,448 (implikowana) | 0,926 (zmierzona) |
| MDE | 0,097 R | **0,146 R** |

1,8× więcej obserwacji efektywnych zostało z nadmiarem skasowane przez 2×
większy rozrzut. Usunięcie warstwy portfelowej (ADR-002) odblokowało próbę, ale
odblokowało też pełny rozrzut wyniku — ta warstwa wcześniej go dławiła, razem
z 98,6% próby.

Ile brakuje do progu 0,08 R przy zmierzonej σ:

| h | n_eff potrzebne | n_eff dostępne (konserw.) | Brakuje |
|---|---|---|---|
| 3 d | 1 030 | 1 040 | ×0,99 — **na styk** |
| 10 d | 1 052 | 315 | **×3,3** |

---

## Kryteria falsyfikacji T001 są w większości nieosiągalne — `INFERENCE`

ADR-009 pytał, czy T001 ma moc wykryć interesujący efekt. Odpowiedź ostrzejsza
od samej bramki wychodzi z zestawienia zmierzonej połowy CI z **prerejestrowanymi
kryteriami** T001: `FALSIFIED` gdy całe CI95 leży poniżej +0,02 R, `SUPPORTED`
gdy CI95 > 0 i kontrola losowa pobita.

| h | Model par | Połowa CI | `FALSIFIED` wymaga | `SUPPORTED` wymaga | Martwa strefa → `NOT_SUPPORTED` |
|---|---|---|---|---|---|
| 3 d | niezależne | 0,0321 | średnia < −0,012 R | średnia > +0,032 R | szerokość 0,064 R |
| 3 d | **konserwatywnie** | 0,0557 | średnia < **−0,036 R** | średnia > **+0,056 R** | **szerokość 0,091 R** |
| 10 d | niezależne | 0,0593 | średnia < −0,039 R | średnia > +0,059 R | szerokość 0,099 R |
| 10 d | **konserwatywnie** | 0,1024 | średnia < **−0,082 R** | średnia > **+0,102 R** | **szerokość 0,185 R** |

Każdy prawdziwy efekt leżący wewnątrz martwej strefy daje `NOT_SUPPORTED` —
wynik, który nie rozstrzyga niczego i kosztuje **6 prób** w liczniku DSR
(N: 7 → 13). Dla porównania: sam dryf kosztowy to −0,031 R przy h = 3 d,
więc umiarkowany, ale realny efekt momentum wyląduje w tej strefie niemal
na pewno.

Przy h = 10 d, konserwatywnie, `SUPPORTED` wymagałoby zmierzonej expectancy
**powyżej +0,10 R netto** — czyli dokładnie tego progu, którego `market-quant`
nie potrafił przekroczyć i który uznano tam za zbyt wysoki, żeby wynikowi
przypisać znaczenie.

`INFERENCE`. T001 w obecnej konstrukcji jest eksperymentem, którego
najprawdopodobniejszym wynikiem jest `NOT_SUPPORTED` niezależnie od tego, czy
efekt istnieje. To jest dokładnie ten scenariusz, przed którym ADR-009 miał
chronić — „uruchomienie eksperymentu, o którym z góry wiadomo, że nie ma mocy
wykryć interesującego efektu, spala próbę w liczniku DSR za zero informacji".
Bramka 0,08 R wychwyciła go tylko przy h = 10 d, i to o włos.

---

## Diagnostyka aparatury

**Bary niejednoznaczne: 0 z 8 000 symulacji.** Symulator ani razu nie musiał
rozstrzygać pesymistycznie — przy barierach oddalonych o 3,3 (h=3) i 6,0
(h=10) dziennych ATR jeden bar M1 nie mieści obu. σ nie jest skażona
pesymizmem zastępczym, a brak ticków w tym pomiarze niczego nie zmienia.

**Powody wyjścia** (h = 10 d): bariera czasowa 62,9%, SL 30,9%, TP 5,5%,
luka przez SL 0,5%, luka przez TP 0,2%. Geometria 1:2 z barierą czasową
oznacza, że większość pozycji **umiera na czasie**, nie na barierze cenowej.

**Dryf kosztowy** −0,031 R (h=3) i −0,0098 R (h=10) na transakcję. ADR-009
szacował 0,023 i 0,012 — h = 3 d wychodzi o ~35% drożej niż zakładano.
Uwaga: to jest **górne ograniczenie** kosztu, nie koszt — pula long+short ma
zerową oczekiwaną wartość brutto tylko w przybliżeniu. **To nie jest kontrola
losowa.** M03 nadal jest konieczne.

**Autokorelacja lag-1 na oknach rozłącznych** — sprawdzenie, czy zachłanne
n_eff nie jest zawyżone:

| | EURUSD | GBPUSD | USDJPY | AUDUSD | USDCAD | EURJPY |
|---|---|---|---|---|---|---|
| h = 3 d | 0,021 | 0,037 | 0,019 | 0,021 | −0,055 | −0,055 |
| h = 10 d | −0,122 | −0,132 | −0,070 | −0,079 | 0,036 | −0,116 |

Przy h = 3 d praktycznie zero — rozłączne okna są niezależne i n_eff nie jest
zawyżone. Przy h = 10 d autokorelacja jest **ujemna** na czterech parach, co
działa na korzyść precyzji, więc n_eff pozostaje konserwatywne.

> ⚠️ Ujemna autokorelacja zwrotów 10-dniowych **nie jest dowodem przeciwko
> H01** i nie wolno jej tak użyć. To diagnostyka aparatury policzona na
> zwrotach surowych, bez cechy i bez kierunku. Gdyby ktoś chciał to badać,
> wymaga to NOWEGO ID hipotezy z etykietą `EXPLORATORY / POST-HOC`
> i `origin` wskazującym ten przebieg — nigdy retroaktywnego doczytania
> do H01.

---

## Luka w prerejestracji T001, wykryta po drodze

Prerejestracja mówi „decyzje 2016-01-01 → **2021-12-31**", ale nie rozstrzyga,
co się dzieje z oknami, które z tego wychodzą. Decyzja z 28.12.2021 przy
h = 10 d rozstrzyga się w **styczniu 2022**, czyli w segmencie OOS, a OOS ma
reżim ograniczonych i logowanych uruchomień.

M02 wybrał wariant, który OOS **nie dotyka**: odcięte są decyzje, których `t1`
wypada po 2021-12-31. Kosztuje to 98 decyzji na parę przy h = 10 d (21 661
wobec 21 759 przy h = 3 d), czyli 0,45% próby — na n_eff nie wpływa.

**To nie jest rozstrzygnięcie, tylko wybór na potrzeby kontroli.** T001 musi
zadeklarować to jawnie w prerejestracji przed uruchomieniem, bo po zobaczeniu
wyniku będzie już parametrem swobodnym.

---

## Czego M02 NIE rozstrzyga

1. **Który model niezależności par obowiązuje.** Nawias [2,0; 6,0] jest
   domknięty matematycznie, ale wybór punktu w środku to decyzja — i to ona,
   a nie żaden pomiar, przesądza o bramce przy h = 3 d.
2. **Czy przyrząd w ogóle potrafi pokazać przewagę.** To jest M03. Dryf
   kosztowy zmierzony tutaj nie jest kontrolą losową.
3. **Czy kontrola przesuniętych cech zachowuje się poprawnie.** To jest M04.
4. **Czy 0,08 R to właściwy próg.** ADR-009 podaje liczbę bez uzasadnienia
   ekonomicznego. Przy zmierzonej σ próg 0,08 R wymaga n_eff ≈ 1 030 —
   co segment RESEARCH daje tylko przy h = 3 d i tylko przy optymistycznym
   liczeniu par.

## Dług niezmieniony

Warstwa etykiet i **dwa testy na brak podglądania przyszłości przez
symulator** nadal są warunkiem startu T001. M02 ich nie spłacił i nie
udawał, że spłaca — liczył rozrzut wyniku, nie etykiety.

## Co M02 dołożył do aparatury

| Moduł | Stan |
|---|---|
| `src/features/volatility.py` | **nowy** — `atr_h1_14` i `atr_d1_14`, granica dobowa przez `available_from`, 16 testów |
| `tests/test_overlap.py` | **nowy** — 14 testów; moduł przeniesiony nie miał w tym repo ani jednego (ADR-005) |
| `tests/test_timeaxis.py` | **nowy** — 18 testów; używany dotąd wyłącznie jako pomocnik cudzych testów |
| `scripts/m02_power_audit.py` | **nowy** — cały pomiar, przez `start_run(kind="control")` |

Testy po M02: **221** (173 + 48).
