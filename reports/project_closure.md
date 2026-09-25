# market-edge-lab — raport zamykający projekt

**Data:** 2026-09-25 · **Decyzja:** ADR-030 · **Licznik prób: N = 10**
(7 odziedziczonych + 3 z T003) · Dane testowe 2022–2023 i 2024–2026
**nietknięte**.

Raport jest napisany dla osoby, która nie jest quantem. Szczegóły
techniczne: `reports/phase0_closure.md`, `reports/phase1_closure.md`
i ADR-y wymienione niżej.

---

## Odpowiedź na pytanie projektu

Projekt pytał: **czy na głównych parach walutowych da się przewidywać ruch
ceny na tyle dobrze, żeby zarobić po kosztach?**

**Na tych danych — nie znaleźliśmy na to dowodów.** Sześć par (EURUSD,
GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY), lata 2016–2021, horyzont 3 dni.

To jest wynik, nie brak wyniku. Projekt od początku zakładał, że „nie
znaleziono przewagi” jest pełnoprawną odpowiedzią.

| Hipoteza | Co się stało | Po ludzku |
|---|---|---|
| H01 Momentum | `NOT_SUPPORTED` (T003) | Trafność najwyżej 51,03%, a żeby zarobić po kosztach, trzeba 51,72%. Jeśli efekt jest, to za mały |
| H02 Breakout jako stan | `CLOSED` (M07) | To w praktyce to samo co H01, nie było czego osobno badać |
| H07 Breakout jako zdarzenie | nietestowalna (M08A) | Za mało zdarzeń: 726, a do rozstrzygnięcia trzeba równowartości 1 317 niezależnych |
| H04 Carry | nietestowalna (M09–M15) | Efekt, który mechanizm może dać w cenie, jest najwyżej o połowę za mały, żeby się opłacał |

---

## Dlaczego się nie udało — trzy przyczyny

### 1. Rynek jest bardzo trudny — tu nikt nie zawinił

Główne pary walutowe to jeden z najbardziej przeczesanych rynków świata.
Handlują nimi banki z ogromnymi zasobami. Jeżeli istnieje prosta
przewaga, to jest mniejsza niż koszt transakcji — jak moneta, która może
być lekko krzywa, ale nie na tyle, żeby pokryć prowizję kasyna.

### 2. Za mało niezależnych danych — ograniczenie, nie wina

130 tysięcy obserwacji brzmi jak dużo, ale one się w większości
powtarzają: pary walutowe ruszają się razem (wszystkie zależą od dolara),
a stopy procentowe zmieniają się kilka razy w ciągu sześciu lat. W praktyce
to kilkanaście naprawdę niezależnych historii. To jak badanie, czy wyższe
zarobki wydłużają życie, na 130 tysiącach wierszy opisujących dziesięć
rodzin — żadna metoda nie wyciągnie z tego pewnej odpowiedzi.

### 3. Zła kolejność pracy przy carry — błąd, którego dało się uniknąć

Tu straciliśmy najwięcej. Przez sześć kroków kontrolnych (M09–M14)
budowaliśmy coraz dokładniejszą „wagę”, żeby zważyć efekt carry. Każdy
krok znajdował problem, a rekomendacją za każdym razem było obejście
i kolejny pomiar.

Nikt nie zadał na początku najprostszego pytania: **ile ten efekt może
w ogóle ważyć?** Rachunek na jedną linijkę (M15) pokazuje, że nawet
w najbardziej optymistycznym wariancie mechanizmu — gdyby cena waluty
lepiej oprocentowanej rosła dwa razy szybciej, niż wynika z różnicy stóp —
efekt w cenie wynosi **0,029**, a próg opłacalności **0,054**. Zysk carry
żyje głównie w odsetkach, nie w ruchu ceny, a my mierzyliśmy ruch ceny.

Rekomendacje kolejnych kroków pochodziły od asystenta AI prowadzącego
analizę i to on nie zatrzymał się, żeby zapytać, czy pomiar ma sens.
Pytanie „czy to nie jest ratowanie projektu na siłę?” padło od
właściciela projektu — i było trafne.

Wzorzec, który się powtarzał: **szacunki robione przed pomiarem były
osiem razy zbyt optymistyczne.** Za każdym razem pomiar pokazywał gorszy
obraz niż przewidywanie.

---

## Co zadziałało

* **Reguły chroniły przed samooszukaniem.** Kryteria zapisane przed
  pomiarem i zakaz zmieniania ich po wyniku sprawiły, że wyniki „prawie
  dobre” (np. w M14 zabrakło 0,6%) nie zostały naciągnięte do sukcesu.
* **Nie zmarnowano prób.** Trzy triale (T001, T002, T004) zostały wycofane,
  zanim cokolwiek zmierzyły, bo pomiary kontrolne pokazały, że nie mogłyby
  niczego rozstrzygnąć. Licznik prób: 10, z czego 7 odziedziczonych.
* **Dane testowe zostały nietknięte** — lata 2022–2026 nadal mogą posłużyć
  do uczciwego sprawdzenia czegokolwiek w przyszłości.
* **Aparatura jest sprawdzona i zostaje:** symulator z poprawnym kosztem
  (M03, M04, M06), dane o stopach procentowych sześciu banków centralnych
  (M12), przyrząd do liczenia niepewności dla cech zmieniających się
  powoli (M14).

---

## Czego to uczy — kolejność na przyszłość

Zanim zaczniesz mierzyć, policz na kartce, czy efekt w najlepszym razie
byłby wart zachodu. Jeżeli nie — nie ma czego mierzyć. Obowiązująca
kolejność kroków dla każdej przyszłej hipotezy:

1. **Wielkość efektu z mechanizmu** wobec progu opłacalności (ADR-030)
2. **Ile niezależnej informacji niosą dane** (ADR-022)
3. **Czy test ma realną szansę powiedzieć „nie”** — co najmniej 50% (ADR-029)
4. **Czy test ma realną szansę powiedzieć „tak”**, gdy efekt istnieje (ADR-027)
5. Dopiero potem prerejestracja i próba.

## Czego projekt NIE wykluczył

Carry jako strategii miesięcznej zarabiającej na odsetkach (to inne
pytanie, z innymi kosztami). Innych rynków, innych horyzontów i innych
lat. Wynik dotyczy dokładnie tego, co zbadano.
