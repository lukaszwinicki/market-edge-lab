"""Marża swapu — koszt finansowania pozycji przetrzymanej przez noc.

CZEGO TU NIE MA I DLACZEGO

Punkt swapowy ma dwa składniki: różnicę stóp procentowych (kierunkową —
long waluty wyżej oprocentowanej dostaje, short płaci) oraz **marżę
brokera**, która jest kosztem po OBU stronach. Ten moduł liczy wyłącznie
marżę.

Powód jest metodologiczny: różnica stóp jest sygnałem, nie kosztem — to
jest treść hipotezy H04. Wpuszczenie jej do modelu kosztów oznaczałoby
wmieszanie hipotezy w aparaturę pomiarową. Marża jest kosztem czystym,
symetrycznym i obowiązuje niezależnie od tego, w którą stronę wchodzimy.

MODUŁ NIE JEST WPIĘTY W SYMULATOR

`CostModel` w `execution/simulator.py` nie zna swapu i nie został zmieniony.
Koszt finansowania dolicza się po fakcie, tak samo jak przelicza się wynik
przy 2× i 3× kosztach — z pól, które `TradeResult` już raportuje. Symulator
jest przeniesiony i zweryfikowany co do bitu; dokładanie mu członu kosztu
unieważniłoby tę weryfikację.

ROLOWANIE

Za każdą przekroczoną granicę doby liczy się jeden dzień finansowania,
z dwoma wyjątkami:

* **środa liczy się potrójnie** — spot rozlicza się T+2, więc rolowanie
  ze środy na czwartek przenosi rozliczenie z piątku na poniedziałek
  i obejmuje weekend (`costs.swap.triple_on_wednesday`);
* **sobota i niedziela nie rolują** — rynek stoi, a finansowanie tych dni
  siedzi już w potrójnej środzie.

Pełny tydzień kosztuje więc 7 dni: 1+1+3+1+1+0+0.

PRZYBLIŻENIE, KTÓRE TRZEBA ZNAĆ

Granicę rolowania przyjmujemy o północy UTC, a faktyczne rolowanie
następuje o 17:00 w Nowym Jorku (21:00/22:00 UTC). Dla pozycji
wielodniowej przesuwa to co najwyżej jeden dzień finansowania na
krańcach okna — wystarczy do oszacowania rzędu wielkości kosztu,
nie wystarczy do rozliczenia rzeczywistej pozycji.
"""

from __future__ import annotations

import datetime as dt

DAYS_IN_YEAR = 365.0
WEDNESDAY = 2


def financing_days(entry: dt.datetime, exit_: dt.datetime, *,
                   triple_on_wednesday: bool = True) -> int:
    """Liczba dni finansowania naliczonych między wejściem a wyjściem.

    Liczymy granice doby przekroczone przez pozycję, nie długość okna:
    pozycja otwarta i zamknięta tego samego dnia nie płaci nic, choćby
    trwała 23 godziny.
    """
    if entry.tzinfo is None or exit_.tzinfo is None:
        raise ValueError("znaczniki muszą być tz-aware (UTC)")
    if exit_ < entry:
        raise ValueError("wyjście przed wejściem")

    total = 0
    day = entry.date()
    while day < exit_.date():
        # `day` właśnie się kończy — to ona decyduje o stawce rolowania.
        if day.weekday() < 5:
            total += 3 if (triple_on_wednesday and day.weekday() == WEDNESDAY) else 1
        day += dt.timedelta(days=1)
    return total


def swap_margin_cost(price: float, entry: dt.datetime, exit_: dt.datetime,
                     margin_annual: float, *,
                     triple_on_wednesday: bool = True) -> float:
    """Koszt marży swapu w jednostkach CENY, zawsze dodatni.

    `margin_annual` to roczna marża brokera ponad stopę międzybankową
    (`costs.swap.margin_sensitivity`), naliczana od wartości pozycji.
    """
    if margin_annual < 0:
        raise ValueError("marża nie może być ujemna")
    days = financing_days(entry, exit_, triple_on_wednesday=triple_on_wednesday)
    return price * margin_annual * days / DAYS_IN_YEAR


def swap_margin_r(price: float, risk: float, entry: dt.datetime,
                  exit_: dt.datetime, margin_annual: float, *,
                  triple_on_wednesday: bool = True) -> float:
    """Koszt marży swapu w jednostkach R, czyli w tej samej walucie co wynik.

    `risk` to dystans stopu — ten sam mianownik, którego używa
    `TradeResult.r`. Dzięki temu wynik da się od siebie odjąć wprost.
    """
    if risk <= 0:
        raise ValueError("dystans stopu musi być dodatni")
    return swap_margin_cost(price, entry, exit_, margin_annual,
                            triple_on_wednesday=triple_on_wednesday) / risk
