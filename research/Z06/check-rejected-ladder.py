#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zabrakovannaya lestnica obyazana PADAT', a ne schitat'sya molcha.

Zachem otdel'nyy skript. V ``result.json`` klyuch s samym ochevidnym imenem --
``ladder`` -- nesyot ZABRAKOVANNUYU lestnicu po tau_GDP (porog -1.6806,
razbienie 382/11), a postavlyaemaya lezhit ryadom v ``ladder_practical``.
Do 2026-08-02 pometki ``rejected`` v ``result.json`` ne bylo vovse, i vyzov
``ladder_contribution(series, result['ladder'])`` otrabatyval bez edinoy
oshibki: on tiho otdaval vklad po zabrakovannomu porogu. Sleduyushchaya
zadacha (Z05) beryot lestnicu imenno iz artefaktov Z06.

Proverka postroena KRASNYM, a ne zelyonym: kazhdyy shag libo lovit otkaz,
libo pokazyvaet, chto bez pometki tot zhe vyzov prohodit i dayot DRUGOE chislo.
Zelyonyy progon, v kotorom nichego ne padalo by, dokazyval by tol'ko to, chto
kod zapuskaetsya.

Vsyo v ASCII: konsol' etoy mashiny v cp1251.

    python check-rejected-ladder.py       # 9 proverok, seti ne trebuet
"""

from __future__ import annotations

import copy
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import composite as C  # noqa: E402

RESULT_PATH = os.path.join(_HERE, "result.json")

_passed = 0
_failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    if ok:
        _passed += 1
        print(f"  OK   {name}")
    else:
        _failed += 1
        print(f"  PROVAL {name}")
    if detail:
        for line in detail.splitlines():
            print(f"         {line}")


def main() -> int:
    with open(RESULT_PATH, encoding="utf-8") as fh:
        result = json.load(fh)

    # Imenno tak eyo i voz'myot tot, kto ne chital pasport: po korotkomu imeni.
    lad = result["ladder"]
    prac = result["ladder_practical"]
    series = C.composite(pin="frozen")

    print("=" * 78)
    print("Zabrakovannaya lestnica: proverka otkaza")
    print("=" * 78)
    print(f"result.json -> 'ladder'           : {lad['version']}, porog "
          f"{lad['steps'][0][0]:+.4f}, mesyacev {lad['month_counts']}")
    print(f"result.json -> 'ladder_practical' : {prac['version']}, porog "
          f"{prac['steps'][0][0]:+.4f}, mesyacev {prac['month_counts']}")
    print(f"ryad: {len(series.dates)} mesyacev "
          f"{series.dates[0]} .. {series.dates[-1]} (pin='frozen', bez seti)")
    print("")

    # --- 1. Pometka lezhit V DANNYH, a ne tol'ko v kode ---------------------
    check("1. result.json -> 'ladder' nesyot rejected=true",
          lad.get("rejected") is True,
          f"rejected = {lad.get('rejected')!r}")
    check("1a. i nesyot prichinu, sovpadayushchuyu s composite.py",
          lad.get("rejected_why")
          == C.LADDER_PREREG_REJECTED_TAU_GDP["rejected_why"],
          f"result.json: {lad.get('rejected_why')!r}")

    # --- 2. Glavnaya mutaciya: vzyat' lestnicu po imeni i poschitat' vklad --
    try:
        C.ladder_contribution(series, result["ladder"])
        check("2. ladder_contribution(series, result['ladder']) padaet",
              False, "vyzov OTRABOTAL -- eto tot samyy tihiy brak")
        msg = ""
    except C.RejectedLadder as exc:
        msg = str(exc)
        check("2. ladder_contribution(series, result['ladder']) padaet", True)
    except Exception as exc:                          # noqa: BLE001
        msg = ""
        check("2. ladder_contribution(series, result['ladder']) padaet",
              False, f"upal, no ne tem: {type(exc).__name__}: {exc}")

    check("2a. soobshchenie nazyvaet 'ladder_practical'",
          "ladder_practical" in msg,
          "soobshchenie:\n" + "\n".join("  " + s for s in msg.splitlines())
          if msg else "soobshcheniya net")
    check("2b. soobshchenie nazyvaet prichinu brakovki (tau_GDP)",
          "tau_GDP" in msg)

    # --- 3. To zhe u level_step: otkaz do pervogo chisla --------------------
    try:
        C.level_step(0.0, result["ladder"])
        check("3. level_step(0.0, result['ladder']) padaet", False,
              "vyzov OTRABOTAL")
    except C.RejectedLadder:
        check("3. level_step(0.0, result['ladder']) padaet", True)

    # --- 4. Otricatel'nyy kontrol': postavlyaemaya schitaetsya ------------
    good = C.ladder_contribution(series, result["ladder_practical"])
    check("4. ladder_contribution na 'ladder_practical' schitaetsya",
          len(good.dates) == len(series.dates) - 3,
          f"{len(good.dates)} mesyacev vklada iz {len(series.dates)} ryada "
          f"(pervye 3 bez Delta_3m)")

    # --- 5. Mutaciya-kontrol' zhivosti proverki ---------------------------
    # Gejt dokazyvaetsya KRASNYM: snimaem pometku s KOPII i pokazyvaem, chto
    # bez neyo tot zhe vyzov prohodit -- i daet DRUGOE chislo. Esli by chisla
    # sovpali, gejt ne zashchishchal by nichego.
    mutated = copy.deepcopy(result["ladder"])
    mutated.pop("rejected", None)
    silent = C.ladder_contribution(series, mutated)
    sv = dict(zip(silent.dates, silent.values))
    gv = dict(zip(good.dates, good.values))
    diff = [d for d in gv if sv.get(d) != gv[d]]
    check("5. bez pometki tot zhe vyzov prohodit i dayot DRUGOY vklad",
          len(diff) > 0,
          f"rashozhdenie na {len(diff)} mesyacah iz {len(gv)}; "
          f"pervoe {diff[0] if diff else '-'} "
          f"(zabrakovannaya {sv.get(diff[0]) if diff else '-'}, "
          f"postavlyaemaya {gv.get(diff[0]) if diff else '-'})")

    # --- 6. Yavnaya dver' rabotaet i vedyot rovno tuda zhe ----------------
    forced = C.ladder_contribution(series, result["ladder"],
                                   allow_rejected=True)
    fv = dict(zip(forced.dates, forced.values))
    check("6. allow_rejected=True otdayot rovno to zhe, chto snyatie pometki",
          fv == sv,
          "dver' odna, i ona yavnaya")

    print("")
    print(f"proshlo {_passed}, provaleno {_failed}")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
