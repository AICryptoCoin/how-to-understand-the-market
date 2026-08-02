#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zabrakovannaya lestnica obyazana PADAT', a postavlyaemaya -- byt' proverena.

Zachem otdel'nyy skript. V ``result.json`` klyuch s samym ochevidnym imenem --
``ladder`` -- nesyot ZABRAKOVANNUYU lestnicu po tau_GDP (porog -1.6806,
razbienie 382/11), a postavlyaemaya lezhit ryadom v ``ladder_practical``.
Do 2026-08-02 pometki ``rejected`` v ``result.json`` ne bylo vovse, i vyzov
``ladder_contribution(series, result['ladder'])`` otrabatyval bez edinoy
oshibki: on tiho otdaval vklad po zabrakovannomu porogu. Sleduyushchaya
zadacha (Z05) beryot lestnicu imenno iz artefaktov Z06.

Sekcii 7-8 dobavleny 2026-08-02 po itogam priyomki. Ves' gejt do togo byl
postroen vokrug togo, chtoby ne vzyali BRAK, i sovsem ne zashchishchal to, chto
beryot Z05 VMESTO braka: podmena poroga vnutri ``ladder_practical`` prohodila
zelyonoy, kak i podmena ``month_counts`` i ``version`` u zabrakovannoy.

Chisla sekcii 7-8 pereschityvayutsya IZ RYADA (``composite.csv``, svoim
chteniem) i sveryayutsya s tremya nezavisimymi mestami -- kod
(``composite.LADDER_V1``), pasport, artefakt. Sverka chisla s samim soboy
(``steps[0][0]`` protiv ``thresholds[0]``) dokazyvaet tol'ko to, chto ono
zapisano dvazhdy, poetomu takaya sverka zdes' est', no ne odna.

Proverka postroena KRASNYM, a ne zelyonym: kazhdyy shag libo lovit otkaz,
libo pokazyvaet, chto bez pometki tot zhe vyzov prohodit i dayot DRUGOE chislo.
Zelyonyy progon, v kotorom nichego ne padalo by, dokazyval by tol'ko to, chto
kod zapuskaetsya.

Vsyo v ASCII: konsol' etoy mashiny v cp1251.

    python check-rejected-ladder.py       # 21 proverka, seti ne trebuet
    python mutate-gate.py                 # 23 mutacii: chto etot gejt lovit
    python check-ladder-worlds.py         # pometka braka v drugih mirah
"""

from __future__ import annotations

import copy
import csv
import dataclasses
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import composite as C  # noqa: E402

RESULT_PATH = os.path.join(_HERE, "result.json")
CSV_PATH = os.path.join(_HERE, "composite.csv")
PASSPORT_PATH = os.path.join(_HERE, "composite-passport.json")

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


def csv_rows() -> list[tuple[str, float, str]]:
    """composite.csv SVOIM chteniem: data, uroven', kolonka L_step kak v fayle.

    Namerenno ne cherez ``composite._frozen_rows``: proverka postavlyaemoy
    lestnicy ne dolzhna opirat'sya tol'ko na tot zhe kod, kotoryy eyo i
    podstavlyaet.
    """
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        return [(r["date"], float(r["composite"]), r["L_step"])
                for r in csv.DictReader(fh)]


def main() -> int:
    with open(RESULT_PATH, encoding="utf-8") as fh:
        result = json.load(fh)
    with open(PASSPORT_PATH, encoding="utf-8") as fh:
        passport = json.load(fh)

    # Imenno tak eyo i voz'myot tot, kto ne chital pasport: po korotkomu imeni.
    lad = result["ladder"]
    prac = result["ladder_practical"]
    if not isinstance(prac, dict) or not prac.get("steps"):
        print("PROVAL 0. result.json -> 'ladder_practical' pust ili ne slovar':")
        print(f"         {prac!r}")
        print("         Postavlyat' v Z05 nechego, ostal'nye proverki "
              "bespredmetny.")
        return 1
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

    # Otkaz obyazan vydavat'sya DO pervogo znacheniya, a ne po hodu scheta.
    # Raznica vidna rovno v odnom sluchae -- i imenno on opasen: ryad koroche
    # delta_months ne dayot ni odnogo mesyaca, i lenivaya proverka (tol'ko
    # vnutri level_step) vernula by PUSTOY ryad bez edinoy oshibki. Eto i est'
    # "ryad, kotoryy vyglyadit gotovym" iz dokstringi ladder_contribution.
    short = dataclasses.replace(series, dates=series.dates[:2],
                                values=series.values[:2])
    try:
        empty = C.ladder_contribution(short, result["ladder"])
        check("2c. otkaz do pervogo znacheniya, a ne po hodu scheta", False,
              f"ryad iz 2 tochek proshyol molcha i vernul {len(empty.dates)} "
              f"mesyacev -- proverka lenivaya, ona zhivyot tol'ko v level_step")
    except C.RejectedLadder:
        check("2c. otkaz do pervogo znacheniya, a ne po hodu scheta", True,
              "ryad iz 2 tochek (koroche delta_months) tozhe otkaz, a ne pustoy "
              "rezul'tat")

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

    # =======================================================================
    # 7. POSTAVLYAEMAYA lestnica -- ta samaya, kotoruyu Z05 podstavit v svyortku
    # =======================================================================
    # Ves' gejt vyshe postroen vokrug togo, chtoby ne vzyali brak. Sam predmet
    # postavki do 2026-08-02 ne proveryalsya nichem: podmena poroga vnutri
    # 'ladder_practical' prohodila zelyonoy, a eto EDINSTVENNAYA kopiya togo,
    # chto uhodit dal'she.
    rows = csv_rows()
    n_rows = len(rows)
    tau = prac["steps"][0][0]

    print("")
    check("7. 'ladder_practical' pometki rejected NE nesyot",
          not prac.get("rejected"),
          f"rejected = {prac.get('rejected')!r}")

    check("7a. steps i thresholds vnutri artefakta soglasovany",
          list(prac.get("thresholds", [])) == [tau]
          and prac["steps"][1][1] == tau,
          f"steps -> {prac['steps']};  thresholds -> {prac.get('thresholds')}")

    check("7b. porog sovpadaet s composite.LADDER_V1 (artefakt <-> kod)",
          list(prac.get("thresholds", [])) == list(C.LADDER_V1["thresholds"])
          and prac["steps"] == C.LADDER_V1["steps"]
          and prac.get("version") == C.LADDER_V1["version"],
          f"artefakt {prac.get('version')} {prac.get('thresholds')}\n"
          f"kod      {C.LADDER_V1['version']} {C.LADDER_V1['thresholds']}")

    pp_lad = passport.get("ladder") or {}
    check("7c. porog sovpadaet s pasportom (artefakt <-> composite-passport.json)",
          list(pp_lad.get("thresholds", [])) == [tau]
          and pp_lad.get("steps") == prac["steps"]
          and (passport.get("pin") or {}).get("ladder_thresholds") == [tau],
          f"pasport -> ladder {pp_lad.get('thresholds')}, "
          f"pin.ladder_thresholds "
          f"{(passport.get('pin') or {}).get('ladder_thresholds')}")

    # Kolonka L_step -- eto lestnica, uzhe primenyonnaya k ryadu. Pereschityvaem
    # eyo iz artefakta stroka v stroku: lyubaya podmena poroga, kotoraya menyaet
    # hot' odin mesyac, vylezet zdes'.
    off = [(d, got, want) for d, v, got in rows
           if (want := f"{C.level_step(v, prac):+.1f}") != got]
    check("7d. kolonka L_step v composite.csv pereschityvaetsya iz artefakta",
          not off,
          f"rashozhdenie na {len(off)} strokah iz {n_rows}"
          + (f", pervoe {off[0][0]}: v fayle {off[0][1]}, po artefaktu "
             f"{off[0][2]}" if off else ""))

    # Podmena, kotoraya ne sdvinula ni odnogo mesyaca, kolonkoy ne lovitsya.
    # Eyo lovit vilka: porog obyazan lezhat' mezhdu sosednimi nablyudeniyami
    # ryada. Oba chisla vilki poscheitany IZ RYADA, a ne vzyaty iz lestnicy.
    below = [v for _, v, L in rows if L == "-1.0"]
    above = [v for _, v, L in rows if L == "+1.0"]
    check("7e. porog zazhat sosednimi nablyudeniyami ryada",
          bool(below) and bool(above) and max(below) <= tau < min(above),
          f"vilka iz ryada ({max(below):+.6f} .. {min(above):+.6f}), "
          f"shirina {min(above) - max(below):.6f}; porog {tau:+.16f}")

    # Razbienie -- tozhe iz ryada, pryamym schyotom, bez level_step.
    n_hi = sum(1 for _, v, _ in rows if v > tau)
    want_counts = {"1.0": n_hi, "-1.0": n_rows - n_hi}
    check("7f. razbienie 272 / 121 pereschitano iz ryada",
          {str(k): v for k, v in prac.get("month_counts", {}).items()}
          == want_counts
          and want_counts == {"1.0": len(above), "-1.0": len(below)},
          f"po ryadu {want_counts}, po kolonke L_step "
          f"{{'1.0': {len(above)}, '-1.0': {len(below)}}}, "
          f"v artefakte {prac.get('month_counts')}")

    # =======================================================================
    # 8. Zabrakovannaya: eyo CHISLA tozhe nikto ne sveryal
    # =======================================================================
    # Pometka na ney byla, a chisla pod pometkoy -- lyubye. Podmena
    # 'month_counts' i 'version' prohodila zelyonoy.
    tau_bad = lad["steps"][0][0]
    n_hi_bad = sum(1 for _, v, _ in rows if v > tau_bad)
    want_bad = {"1.0": n_hi_bad, "-1.0": n_rows - n_hi_bad}

    print("")
    check("8. razbienie zabrakovannoy pereschitano iz ryada",
          {str(k): v for k, v in lad.get("month_counts", {}).items()} == want_bad,
          f"po ryadu {want_bad}, v artefakte {lad.get('month_counts')}")

    # Tekst prichiny obyazan nesti TE ZHE chisla: inache pometka govorit odno,
    # a dannye -- drugoe. Eto lovit soglasovannuyu podmenu i artefakta, i
    # konstanty v composite.py (proverka 1a ih tol'ko sravnivaet drug s drugom).
    why = lad.get("rejected_why") or ""
    split = f"{want_bad['1.0']} / {want_bad['-1.0']}"
    split_pct = (f"({want_bad['1.0'] / n_rows * 100:.1f}% / "
                 f"{want_bad['-1.0'] / n_rows * 100:.1f}%)")
    check("8a. rejected_why nesyot imenno eto razbienie",
          split in why and split_pct in why,
          f"zhdyom '{split}' i '{split_pct}'")

    const_bad = C.LADDER_PREREG_REJECTED_TAU_GDP
    pp_bad = passport.get("ladder_prereg_rejected_tau_GDP") or {}
    check("8b. version/steps/tau sovpadayut v tryoh mestah",
          lad.get("version") == const_bad["version"] == pp_bad.get("version")
          and lad.get("steps") == const_bad["steps"] == pp_bad.get("steps")
          and lad.get("tau") == const_bad["tau"] == pp_bad.get("tau"),
          f"result.json {lad.get('version')} {lad['steps'][0][0]!r}\n"
          f"composite.py {const_bad['version']} {const_bad['steps'][0][0]!r}\n"
          f"pasport      {pp_bad.get('version')} "
          f"{(pp_bad.get('steps') or [[None]])[0][0]!r}")

    check("8c. dve lestnicy dejstvitel'no raznye -- inache gejt bespredmeten",
          tau != tau_bad and want_bad != want_counts,
          f"postavlyaemaya {tau:+.4f} {want_counts}; "
          f"zabrakovannaya {tau_bad:+.4f} {want_bad}")

    print("")
    print(f"proshlo {_passed}, provaleno {_failed}")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
