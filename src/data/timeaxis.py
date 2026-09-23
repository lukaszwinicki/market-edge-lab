# PRZENIESIONE z market-quant (ADR-005), z src/labels/triple_barrier.py.
"""Oś czasu — arytmetyka dni roboczych.

Funkcja mieszkała w module etykiet, ale nie ma z etykietami nic wspólnego:
nie zna hipotezy, targetu ani geometrii barier. Używa jej bariera czasowa,
okno purge w walidacji krzyżowej i audyt mocy. Dlatego dostaje neutralny dom.
"""

from __future__ import annotations

import datetime as dt


def add_business_days(t: dt.datetime, n: int) -> dt.datetime:
    """Przesuń o n dni roboczych, pomijając soboty i niedziele.

    Świadomie bez kalendarza świąt: rynek FX w święta bywa otwarty, a
    zakodowanie listy świąt wprowadziłoby założenie, którego nie chcemy.
    Brak danych i tak obsługuje symulator (`ExitReason.NO_DATA`).
    Ujemne n przesuwa wstecz — tego wymaga okno purge przed grupą testową.
    """
    out = t
    step = dt.timedelta(days=1 if n >= 0 else -1)
    left = abs(n)
    while left > 0:
        out += step
        if out.weekday() < 5:
            left -= 1
    return out
