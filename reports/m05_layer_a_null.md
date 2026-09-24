# M05 — rozkład zerowy metryki głównej warstwy A

**Data:** 2026-09-24 · **ADR:** ADR-015 · **Rodzaj:** `control` — **nie liczy się do N**
**Przebieg:** `20260924T134703Z-cd0d96` · **Licznik po M05:** N = 7, bez zmian.

---

## Werdykt

> **PRZECHODZI, i rozstrzyga pytanie otwarte w ADR-015 na TAK.**
>
> Statystyka relacji warstwy A ma na siatce T003 **n_eff = 1 902 do 5 150**
> zależnie od komórki — wobec 1 042 przyjętych roboczo w ADR-015. Kryterium
> `FALSIFIED` jest **osiągalne we wszystkich trzech komórkach** h = 3 d.
>
> **Prerejestracja T003 może zostać zamrożona z pełną, trójstanową
> przestrzenią wyników.** Martwa strefa spada z **5,61 pp** (warstwa B,
> konstrukcja T001) do **0,33 pp** w najgorszej komórce — siedemnastokrotnie.

---

## Po co ten przebieg

ADR-014 ustalił `P_eff = 2,00` dla **warstwy B** — dla statystyk
uśredniających wynik przemnożony przez znak cechy. ADR-015 przeniósł kryteria
falsyfikacji na **warstwę A**, gdzie zależność międzyparowa jest inną
wielkością: pod H0 kowariancja estymatorów relacji na parach `i` i `j` idzie
jak **iloczyn** `ρ^cecha_ij · ρ^zwrot_ij`, a nie jak `|ρ^zwrot_ij|`.

M02 tego nie mierzył. Przepisanie `P_eff = 2,00` z warstwy B na A byłoby
odziedziczeniem liczby zamiast pomiaru — czyli dokładnie tym, co M02 wykrył
przy σ (dziedziczona 0,455 R wobec zmierzonej 0,92 R) i co kosztowało T001.

## Metoda: cecha zastępcza na prawdziwej siatce

`mom_k` **nie został policzony ani razu.** Cecha jest syntetyczna: różnica
skumulowanych przyrostów losowych na oknie `k`, znormalizowana `√k` — ta sama
postać funkcyjna co `mom_k` pod hipotezą zerową, zbudowana z generatora
liczb, nie z cen. Prawdziwe ceny wchodzą wyłącznie przez `fwd_atr` (target A,
bezkierunkowy — ten sam, na którym M02 liczył macierz korelacji).

Dlatego przebieg jest `control` i N pozostaje 7.

**Dlaczego surogat, a nie wzór zamknięty.** Rozrzut statystyki zależy
jednocześnie od trzech rzeczy: nakładania okien wynikowych, autokorelacji
cechy i korelacji międzyparowej. Wzór istnieje tylko dla obserwacji
niezależnych. Surogat o właściwej autokorelacji, puszczony przez **prawdziwą**
siatkę decyzyjną z **prawdziwymi** zwrotami, odtwarza wszystkie trzy naraz.

**Autokorelacja cechy jest tu krytyczna.** `mom_k` to pod H0 znormalizowana
suma `k` przyrostów, więc jej autokorelacja na lagu ℓ to (1 − ℓ/k)⁺ — przy
k = 480 sąsiednie bary są skorelowane w 99,8%. Surogat z szumu białego
zaniżyłby rozrzut statystyki o rząd wielkości i dałby n_eff wzięte z sufitu.
Pilnuje tego `tests/test_surrogate.py` — z testem negatywnym na szum włącznie.

**Zero przyrządu.** Przy wierszach niezależnych zmierzone SE statystyki musi
wyjść 1/√n. Wychodzi: iloraz 1,001 na 4 000 wierszy i 800 replikacji. Dzięki
temu „inflacja względem iid" mierzy zależność, a nie błąd implementacji.

Metryka główna to **Spearman**, wybrany przed przebiegiem ze względu na
kurtozę `fwd_atr` (4,6 przy h = 3 d, 7,8 przy h = 10 d) — Pearson na takim
ogonie ma rozrzut zależny od kilkunastu obserwacji. Pearson raportowany obok.

## Wynik główny: siatka T003 — `FACT`

Najgorszy z dwóch modeli bramkowych, h = 3 d, 400 replikacji na komórkę.
Próg opłacalności (M04): **51,72%**.

Progi poniżej są **bez korekty na wielokrotność** — to surowy wynik M05 przy
α = 0,05. Kryterium `SUPPORTED` w T003 wymaga korekty Holma na 3 komórki
(union), co daje **51,44 / 52,15 / 52,36%** i martwą strefę **−0,28 / +0,43 /
+0,64 pp**. Kryterium `FALSIFIED` korekty **nie wymaga**: żąda spełnienia we
wszystkich komórkach naraz, a taki test (intersection-union) kontroluje błąd
I rodzaju na poziomie α bez niej.

| k | n_eff | Próg wykrywalności | Martwa strefa | `FALSIFIED` |
|---|---|---|---|---|
| 24 | 5 150 | 51,24% | **−0,48 pp** | osiągalne (0,51) |
| 120 | 2 302 | 51,86% | +0,14 pp | osiągalne (0,76) |
| 480 | 1 902 | 52,05% | +0,33 pp | osiągalne (0,83) |

Liczba w nawiasie to iloraz „połowa CI95 / próg opłacalności": poniżej 1
oznacza, że przedział ufności mieści się pod progiem, czyli że wynik bliski
zera **rozstrzyga**, zamiast wpadać w „nie wiadomo".

Przy k = 24 martwa strefa jest **ujemna** — eksperyment wykrywa efekty
mniejsze od najmniejszego opłacalnego. To jest reżim, w którym wynik negatywny
naprawdę coś wyklucza.

**Zestawienie z konstrukcją odrzuconą przez ADR-015:**

| h = 3 d, najgorsza komórka | Próg wykrywalności | Martwa strefa |
|---|---|---|
| warstwa B — expectancy w R (T001) | 57,33% | 5,61 pp |
| **warstwa A — Spearman (T003)** | **52,05%** | **0,33 pp** |

## Drugi wynik: `P_eff` warstwy A wynosi 3,2, nie 2,0 — `FACT`

Komórka k = 480, h = 3 d, wszystkie modele:

| Model korelacji międzyparowej | n_eff | `P_eff` implikowane |
|---|---|---|
| `independent` | 3 556 | 6,00 |
| `as_returns_h` | 1 902 | 3,21 |
| `as_returns_k` | 1 912 | 3,23 |
| `sign_aligned` | 4 132 | 6,97 |

Przewidywanie analityczne z macierzy M02 (`P² / ΣΣρ²`) dawało **3,08**.
Zmierzone: **3,21**. Zgodność w granicach, przy czym wiążąca jest liczba
zmierzona.

**Wątpliwość zamknięta pomiarem.** `as_returns_h` bierze korelację zwrotów na
oknie `h`, a cecha jest zwrotem z okna `k` — dla k = 480 to 20 dni wobec
3 dni. Gdyby korelacja międzyparowa rosła z długością okna, model byłby
za łagodny. Zmierzona średnia `|ρ|` na oknach 24 / 120 / 480 barów wynosi
**0,389 / 0,404 / 0,398** — płasko. Stąd `as_returns_k` ≈ `as_returns_h`
(1 912 wobec 1 902) i pytanie odpada.

To nie łamie ADR-012: korelacja zwrotów na oknie `k` liczona jest na zwrotach
**w przód**, maszynerią target A, z innym oknem. Pod stacjonarnością jej
macierz jest macierzą zwrotów wstecz o tej samej długości. Nigdzie nie
powstaje iloczyn okna wstecz z oknem w przód — a dopiero on byłby oceną H01.

## Trzeci wynik: `sign_aligned` jest krańcem OPTYMISTYCZNYM — `FACT`

Model, który miał być pesymistyczny — znak cechy idealnie śledzi czynnik USD,
założenie stojące za `P_eff = 2,00` w ADR-014 — daje `P_eff ≈ 7,0`, czyli
**więcej niż sześć par niezależnych**.

Powód jest strukturalny i przenosi się na każdą statystykę relacji.
Kowariancja estymatorów idzie jak iloczyn `ρ^cecha · ρ^zwrot`. Odwrócenie
znaków **samej cechy**, przy zwrotach zachowujących znaki oryginalne, czyni
część iloczynów **ujemnymi** — a te kasują wariancję, zamiast ją dokładać.

`INFERENCE`: **intuicja „zrównanie znaków jest zawsze konserwatywne" jest
fałszywa dla warstwy A.** Była poprawna dla warstwy B, gdzie statystyka jest
liniowa w znaku cechy. Gdyby `P_eff = 2,00` przepisać z ADR-014 na warstwę A
„dla ostrożności", byłoby to założenie **niekonserwatywne i zarazem błędne** —
i nikt by tego nie zauważył, bo wyglądałoby na ostrożne.

Krańcem pesymistycznym jest zgodność znaków cechy ze znakami zwrotów, czyli
`as_returns_*`. Bramka idzie po gorszym z dwóch i to jest zapisane w skrypcie,
nie w komentarzu.

## Czwarty wynik: h = 10 d odpada także na warstwie A — `FACT`

ADR-015 usunął h = 10 d na podstawie kosztu (M03) i mocy warstwy B. Warstwa A
potwierdza to niezależnie:

| k | n_eff | Próg wykrywalności | `FALSIFIED` |
|---|---|---|---|
| 24 | 4 814 | 51,29% | osiągalne |
| 120 | 1 352 | 52,43% | **NIEOSIĄGALNE** |
| 480 | 700 | 53,31% | **NIEOSIĄGALNE** |

Dwie z trzech komórek nie mogą zapaść na `FALSIFIED` przy żadnym wyniku.
Decyzja ADR-015 była wcześniej `INFERENCE`; teraz jest pomiarem.

## Piąty wynik: nakładające się bary dokładają informację — `FACT`

M02 liczył n_eff zachłannie, po oknach rozłącznych: **3 126** w czasie na
sześć par. M05 liczy rozrzut statystyki na **wszystkich** 130 553 wierszach
sesji primary i przy parach niezależnych dostaje **3 556** (k = 480).

`INFERENCE`: okna nakładające się nie są bezwartościowe — zachłanne n_eff jest
dolnym ograniczeniem, nie wartością. Zysk jest jednak skromny (+14% przy
k = 480) i rośnie przy krótszym `k` (11 503 przy k = 24, bo cecha jest wtedy
mniej autoskorelowana). **To nie zmienia niczego w M02** — tam wielkością
mierzoną była liczba obserwacji wchodzących do testu expectancy, nie rozrzut
statystyki rangowej.

## Czego M05 NIE zrobił

- **Nie policzył `mom_k`.** Ani razu, w żadnym wariancie. Cecha była
  syntetyczna w każdej z 400 replikacji każdej z 24 komórek.
- **Nie zmierzył mocy pod hipotezą alternatywną.** Rozkład zerowy daje SE
  i stąd MDE; kształt rozkładu przy istniejącym efekcie to inna wielkość
  i T003 jej nie potrzebuje.
- **Nie rozstrzygnął, czy Spearman jest lepszy od Pearsona.** Wybór zapadł
  przed przebiegiem, z kurtozy. Wybieranie statystyki po obejrzeniu, która ma
  ciaśniejszy rozkład zerowy, byłoby doborem przyrządu pod wynik.
- **Nie dotknął segmentu OOS ani zapieczętowanego.**
- Mapowanie `ρ → trafność kierunku` zakłada normalność dwuwymiarową i służy
  wyłącznie do wyrażenia progów w jednostce, o której da się mieć zdanie.
  **Nie wchodzi do żadnego testu.**

## Co M05 dołożył do aparatury

| Moduł | Stan |
|---|---|
| `scripts/m05_layer_a_null.py` | **nowy** — cały pomiar, przez `start_run(kind="control")` |
| `tests/test_surrogate.py` | **nowy** — 17 testów: autokorelacja surogatu, zero przyrządu, struktura międzyparowa, granica osiągalności `FALSIFIED` |

Testy po M05: **281** (264 + 17).

## Ślad przebiegów

Trzy wpisy `start` w rejestrze, wszystkie `control`:

| Przebieg | Status | Co to było |
|---|---|---|
| `…T134044Z-f65ac2` | `error` | Kolejność kolumn macierzy szła za configiem, wiersze za `sorted` |
| `…T134117Z-a6d355` | `ok` | Zestaw modeli z `sign_aligned` jako rzekomym krańcem pesymistycznym |
| `…T134703Z-cd0d96` | `ok` | **Wynik raportowany** — modele bramkowe poprawione, `as_returns_k` dołożony |

Przebieg drugi jest w rejestrze mimo że został zastąpiony — nie dlatego, że
coś zmierzył, tylko dlatego, że rejestr nie ma trybu „to się nie liczyło".
Przy `control` nie rusza N; gdyby to był `strategy`, kosztowałby próbę i tak
powinien.
