# market-edge-lab

Laboratorium badawcze. **Nie jest botem, nie jest platformą, nie jest fabryką
backtestów.** Celem jest ustalić, czy istnieją dowody na przewidywalność rynku
i jak mocne są te dowody. „Nie znaleziono przewagi" jest pełnoprawnym wynikiem.

Poprzedni projekt `../market-quant` jest **READ-ONLY** źródłem metodologii, kodu
i wyników. Nie modyfikować, nie importować w locie (ADR-005).

---

## Gdzie jest prawda

| Plik | Rola |
|---|---|
| `DECISIONS.md` | ADR. **Wpisy niezmienne**; zmiana = nowy ADR |
| `HYPOTHESES.md` | Rejestr hipotez, statusy, drzewo zależności |
| `EXPERIMENTS.md` | Indeks trialów |
| `DATA.md` | Dane, ograniczenia, checklista leakage'u |
| `PROGRESS.md` | Bieżący stan. Log, nie źródło prawdy |
| `trials/trials.jsonl` | Append-only, zapis automatyczny przez harness |

W razie sprzeczności wygrywa `DECISIONS.md`. Historia rozmów nie jest źródłem
prawdy — co ma przetrwać, trafia do ADR.

---

## Reguły, których nie wolno złamać

**Falsification-first.** Pytanie brzmi „czy dane każą to odrzucić?", nigdy „jak
sprawić, żeby działało?". Najpierw prosty test, potem robustness, na końcu
złożoność. Jeżeli prosty efekt nie istnieje — nie budujemy na nim ML.

**Pomiar informacji jest oddzielony od symulacji strategii (ADR-002).** Warstwa
ryzyka i portfela NIE wchodzi do testu hipotezy. Wchodzi dopiero wtedy, gdy
efekt przeżył pomiar. W `market-quant` splątanie tych warstw skasowało 98,6%
próby i zostawiło 172 obserwacje efektywne z 64 342 sygnałów.

**Żadne wejście do backtestu nie pochodzi od LLM.** Model, którego dane
treningowe obejmują okres testu, zna wynik. Nie da się tego naprawić promptem
ani zmierzyć. Dotyczy cech, scoringu tekstu i klasyfikacji zdarzeń.

**Każda próba jest logowana.** Próbą jest każdy sprawdzony wariant, nie każde
uruchomienie skryptu. Zapis automatyczny przez harness, bez możliwości
pominięcia. **Licznik startuje od N = 7** — próby odziedziczone po
`market-quant` na tych samych danych (ADR-004).

**Bid i ask osobno, nigdzie mid.** Kolejność barier rozstrzygana tickowo albo
pesymistycznie, nigdy optymistycznie.

**Etykieta bara = początek przedziału.** Bar 09:00 (H1) zamyka się o 10:00.
Decyzja o 10:00 może użyć wyłącznie bara 09:00. Używać `last_closed_bar()`,
nigdy ręcznej arytmetyki na znacznikach czasu.

**Prerejestracja przed backtestem.** Hipoteza, target, universe, okres, cechy,
parametry, execution, koszty, protokół walidacji, metryka główna i kryteria
falsyfikacji — zapisane i zahashowane PRZED uruchomieniem. Zmiana czegokolwiek
po zobaczeniu wyniku to NOWY eksperyment, nie poprawka starego.

**Nie zmieniamy hipotezy po wyniku.** Wynik negatywny → `FALSIFIED` albo
`NOT_SUPPORTED`. Efekt odkryty po fakcie dostaje NOWE ID i etykietę
`EXPLORATORY / POST-HOC` z `origin` wskazującym trial źródłowy. Nie może być
użyty jako retroaktywne potwierdzenie rodzica.

**Segment 2024–2026 jest zapieczętowany.** Zero dostępu do fazy końcowej
walidacji. Segment 2015–2021 był już oglądany — patrz ADR-004.

**Nie mnożymy hipotez, żeby uniknąć wyniku negatywnego.** Nowa hipoteza wymaga
uzasadnienia, dlaczego wnosi informację, której nie wnosi żadna istniejąca.

**SURVIVED ≠ PRODUCTION READY.** Przetrwanie oznacza tylko tyle, że efekt
zasługuje na osobną fazę walidacyjną.

---

## Data rules

Każda informacja musi być dostępna w momencie decyzji. Makro wyłącznie
point-in-time (ALFRED `realtime_start` = data decyzji). Wszystkie normalizacje
w oknie rozszerzającym. Żaden `fit()` nie widzi danych testowych — w tym skaler,
imputer i kalibrator. Czas w UTC wszędzie. Dane niepewne oznaczamy `UNKNOWN`,
nie zgadujemy.

Nakładające się etykiety wymagają **purge + embargo zawsze**, nie „gdy trzeba".
Do testów istotności wchodzi liczba obserwacji efektywnych, nie liczba wierszy.

Przed KAŻDYM raportowanym wynikiem: checklista leakage'u z `DATA.md`.

## Validation rules

Dobór metody zależy od eksperymentu; nie stosujemy metod dlatego, że brzmią
zaawansowanie. Random control jest benchmarkiem nr 1 i zachowuje wszystko poza
timingiem wejścia. Szukamy płaskowyżu, nie szpikulca. Efekt istniejący tylko
przy nierealistycznie niskich kosztach nie jest efektem. Istotność statystyczna
to nie to samo co istotność ekonomiczna — badamy obie.

Przeniesiony kod nie dziedziczy zaufania. Zanim cokolwiek zmierzy, musi przejść
własne testy i własną kalibrację w tym repozytorium (ADR-005).

## Kod

Prosty, deterministyczny, testowalny, modularny. Rozdzielone warstwy: data,
features, labels, execution, research, validation, reporting. Testy symulatora
i cech pisać na danych **syntetycznych** — na prawdziwych tickach nie znasz
poprawnej odpowiedzi, więc nie wiesz, czy kod działa; widzisz tylko, że coś
zwraca.

## Git

Gałąź główna: `main`.

**Commit to jedno zdanie po angielsku — sam temat, bez body.** Body wolno dodać
wyłącznie przy dużej potrzebie, gdy „dlaczego" jest nieodgadywalne z diffa;
w razie wątpliwości body odpada. **Żadnych stopek atrybucyjnych** — ani
`Co-Authored-By`, ani innych.

Prefiksy: `docs:` `feat:` `fix:` `test:` `chore:` `config:`.
Przed commitem `git add -A --dry-run`. Dane nigdy nie wchodzą do gita.

## Token-efficient workflow

Na starcie sesji czytać w tej kolejności i **zatrzymać się, gdy wystarczy**:

1. `CLAUDE.md` (ładuje się sam)
2. `PROGRESS.md`
3. `HYPOTHESES.md` — tylko wpis aktywnej hipotezy, nie cały plik
4. ostatni ADR
5. `EXPERIMENTS.md`
6. dopiero potem kod, dane i pełne raporty — wyłącznie te, których wymaga zadanie

Duże wyniki żyją w `runs/`. W dokumentach głównych tylko podsumowanie, decyzja
i referencja. Nie wklejać długich logów. Nie powtarzać tego, co już zapisane.
Każdą liczbę w notatkach sprawdzać komendą — notatki starzeją się szybciej
niż dysk.
