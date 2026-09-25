# Faza 1 — raport zamykający (H04, carry)

**Data:** 2026-09-25 · **Decyzja:** ADR-028 · **Licznik prób: N = 10** — ta
faza nie zapaliła ani jednej próby. Wszystkie przebiegi to `control` albo
`infra`.

---

## Werdykt

**H04 jest nietestowalna przy h = 3 d na segmencie RESEARCH (2016–2021).**
Status zostaje `PROPOSED`. T004 wycofany przed zamrożeniem.

To nie jest wynik o carry. Cecha H04 **nigdy nie została zestawiona z żadnym
zwrotem**. Wynik dotyczy przyrządu: przy tej cesze i tym horyzoncie nie da się
zbudować testu, który mógłby zakończyć się `FALSIFIED` z rozsądnym
prawdopodobieństwem. Test, który może powiedzieć tylko „tak” albo „nie
wiadomo”, nie jest falsyfikacją, a jego uruchomienie kosztowałoby próbę.

---

## Łańcuch, który do tego doprowadził

| Krok | Przebieg | Co ustalił |
|---|---|---|
| M09 | `20260924T202826Z-a64090` | Geometria: n_eff 1 870–2 344 z jednej realizacji; dwa SE rozjeżdżają się 1,7× |
| M10 | `20260924T203841Z-ad7ab7` | Prawdziwe SD ze świata syntetycznego: n_eff 1 472, o 21% mniej niż w M09 |
| M11 | `20260924T211756Z-2329f2` | EUR bez wartości point-in-time w 2016–2017 w serii OECD |
| M12 | `20260924T212921Z-b1fcdc` | Cecha ze stóp polityki, zweryfikowana wobec OECD; n_eff 1 547, iloraz 0,92 |
| M13 | `20260924T215452Z-2744d2` | CI z rozkładu zerowego: sufit mocy ~0,3 |
| M14 | `20260925T174148Z-1aa5cf` | Bootstrap × κ: pokrycie i moc są, osiągalnego `FALSIFIED` nie ma |

Trzy metody CI, każda zmierzona na świecie syntetycznym:

| Metoda | Pokrycie pod H0 | Moc przy ρ = 0,12 | `FALSIFIED` osiągalne |
|---|---|---|---|
| rozkład zerowy surogatu (M10, M13) | ✓ | ✗ 0,24 | granicznie |
| block bootstrap (M10) | ✗ 0,85 w jednym wariancie | ✓ 0,98 | tak |
| bootstrap × κ = 1,141 (M14) | ✓ 0,950–0,965 | ✓ 0,89–0,99 | ✗ pół-CI 0,05435 > 0,05401 |

---

## Główne ustalenie: iloraz < 1 nie wystarcza

Bramka ADR-022 pyta, czy połowa CI95 mieści się w progu opłacalności
(iloraz < 1). H04 miała iloraz 0,92 i przechodziła. Ale `FALSIFIED` wymaga,
żeby **cały** przedział ρ̂ ± pół-CI zmieścił się w ±0,05401, czyli
|ρ̂| < 0,05401 − pół-CI. Przy ilorazie 0,88–0,95 to jest |ρ̂| < ~0,003–0,006.

Nawet przyrząd idealny, z CI z prawdziwego SD i bez szumu estymatora, daje
pod ρ = 0 prawdopodobieństwo `FALSIFIED` równe **9–21%**. M14 zmierzył
8–14% dla metody faktycznie dostępnej. Pod H0 T004 skończyłby się
`NOT_SUPPORTED` w 86–92% przypadków.

**Propozycja do decyzji** (nie przyjęta, ADR-028): bramka ADR-022 powinna
wymagać P(`FALSIFIED` | ρ = 0) ≥ ustalony próg, liczonego z prawdziwego SD,
zamiast samego ilorazu.

---

## Co zostaje z tej fazy

* **Cecha** — `src/data/policy_rates.py`: stopy polityki sześciu banków
  centralnych, point-in-time z konstrukcji, zweryfikowane wobec OECD.
* **Przychód carry w warstwie B** — `attach_carry` w `src/execution/costs.py`.
* **Przyrząd dla cech trwałych** — `scripts/m14_kappa_bootstrap.py`:
  κ-bootstrap ma poprawne pokrycie i moc ~0,9 przy ρ = 0,12. Problemem H04
  jest geometria, nie przyrząd.
* **Szkic prerejestracji** `configs/t004_carry.yaml` i runner
  `scripts/t004_carry.py` — niezamrożone, hash `PENDING`.

---

## Czego faza NIE zbadała

Innych horyzontów (dłuższy h zmniejsza n_eff — M05: h = 10 d traci
`FALSIFIED`), innych instrumentów, carry jako strategii miesięcznej
(`scope_of_result` w szkicu T004) ani segmentów OOS 2022–2023
i 2024–2026 — oba nietknięte.

## Jeżeli H04 ma wrócić

Potrzebny jest pomiar o większej liczbie **niezależnych epizodów stóp**,
nie inna metoda CI. Każdy taki plan przechodzi najpierw bramkę geometrii
(ADR-022) i pomiar P(`FALSIFIED` | ρ = 0) na świecie syntetycznym, zanim
powstanie prerejestracja.
