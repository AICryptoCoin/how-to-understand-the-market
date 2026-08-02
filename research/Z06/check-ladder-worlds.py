#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pometka braka obyazana zaviset' ot POROGA, a ne ot nalichiya zameny.

Zachem otdel'nyy skript. Do 2026-08-02 run.py stavil ``rejected`` vnutri
``if RESULT["ladder_practical"]``, a prakticheskaya lestnica sushchestvuet
tol'ko esli planku identificiruemosti proshyol hotya by odin porog. To est'
vopros "goden li porog" byl podmenyon voprosom "nashlos' li chem ego zamenit'".
Na segodnyashnih dannyh eto sovpadalo sluchayno, i po odnomu progonu defekt ne
viden vovse: nuzhno posmotret' na DRUGIE miry.

Kak ustroeno. Kusok run.py sec.8 (ot ``ci_rec = BOOT_R[BLOCK_MAIN]`` do
zagolovka sec.9) i kusok sec.12 (vygruzka) vyrezayutsya iz fayla VERBATIM i
ispolnyayutsya v podgotovlennom prostranstve imyon. Menyaetsya TOL'KO vhod --
bootstrap-intervaly, iz kotoryh schitaetsya planka. Ryad, pasport i sam
composite.py -- nastoyashchie. Vygruzka idyot vo VREMENNYY katalog, tak chto
artefakty Z06 skript ne trogaet.

Chetyre mira:

  A  kak v deystvitel'nosti  -- identificiruem tol'ko tau_REC;
  B  ni odin porog ne identificiruem  -- zameny NET;
  C  identificiruemy vse tri;
  D  identificiruem tol'ko tau_GDP -- porog samoy lestnicy goden.

V mire B pometka obyazana stoyat' (i v postavku ne dolzhno uyti nichego), v
mirah C i D -- NE dolzhna. Otdel'no sveryaetsya, chto v mire A chisla
sovpadayut s uzhe lezhashchim result.json pobukvenno: inache pravka run.py
potrebovala by pereschyota Z06.

Vsyo v ASCII: konsol' etoy mashiny v cp1251.

    python check-ladder-worlds.py                # svoyo derevo
    python check-ladder-worlds.py --tree PUT     # drugaya kopiya (do pravki)
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import time
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--tree", default=_HERE,
                help="katalog Z06 (po umolchaniyu -- svoy)")
Z06 = os.path.abspath(ap.parse_args().tree)
RESEARCH = os.path.dirname(Z06)
for _p in (Z06, RESEARCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import composite as C  # noqa: E402

with open(os.path.join(Z06, "run.py"), encoding="utf-8") as _fh:
    RUN_SRC = _fh.read()

# Markery narochno privyazany k stroke koda: esli run.py perestroyat, skript
# upadyot na .index, a ne prodolzhit tiho proveryat' pustotu.
SEC8 = RUN_SRC[
    RUN_SRC.index("ci_rec = BOOT_R[BLOCK_MAIN]"):
    RUN_SRC.index("\n# ==========================================================="
                  "================\n# 9. Vintazhi")]

_S12 = "if LADDER_SHIP is None:\n    # Postavlyaemoy lestnicy net"
if _S12 not in RUN_SRC:                       # derevo do pravki
    _S12 = 'csv_path = os.path.join(_HERE, "composite.csv")'
SEC12 = RUN_SRC[RUN_SRC.index(_S12):RUN_SRC.index('RESULT["elapsed_sec"]')]

# --- nastoyashchiy ryad i pasport, bez seti --------------------------------
MAIN_S, MAIN_PP = C.composite_with_passport(pin="frozen")
CMAIN = dict(zip(MAIN_S.dates, MAIN_S.values))
SIGMA_C = MAIN_PP.sigma_c

TAU = {"tau_MFG": -0.3180357578644856, "tau_GDP": -1.6805696557314669,
       "tau_REC": -0.2004379668757319}
REAL_CI = {                                   # iz result.json -> ladder.ci90
    "tau_MFG": [-1.3494127499915503, 0.07142946351669625],    # 1.66 sigma_c
    "tau_GDP": [-4.4515009516002, -0.9576694400597762],       # 4.07 sigma_c
    "tau_REC": [-0.5612663139635263, -0.18912377672497938],   # 0.43 sigma_c
}


def narrow(name: str) -> list[float]:
    """Interval shiriny 0.5 sigma_c -- planku prohodit."""
    return [TAU[name] - 0.25 * SIGMA_C, TAU[name] + 0.25 * SIGMA_C]


def wide(name: str) -> list[float]:
    """Interval shiriny 4 sigma_c -- planku ne prohodit."""
    return [TAU[name] - 2.0 * SIGMA_C, TAU[name] + 2.0 * SIGMA_C]


WORLDS = [
    ("A. kak v deystvitel'nosti (identificiruem tol'ko tau_REC)", REAL_CI),
    ("B. NI ODIN porog ne identificiruem -- zameny NET",
     {k: wide(k) for k in TAU}),
    ("C. identificiruemy VSE tri", {k: narrow(k) for k in TAU}),
    ("D. identificiruem tol'ko tau_GDP -- porog lestnicy goden",
     {"tau_MFG": wide("tau_MFG"), "tau_GDP": narrow("tau_GDP"),
      "tau_REC": wide("tau_REC")}),
]


def run_world(ci90: dict[str, list[float]]) -> dict[str, Any]:
    ci = {k: {"status": "ok", "tau_lo90": v[0], "tau_hi90": v[1]}
          for k, v in ci90.items()}
    ns: dict[str, Any] = {
        "Any": Any, "C": C, "json": json, "os": os, "time": time,
        "BOOT_R": {24: ci["tau_REC"]}, "BOOT_M": {24: ci["tau_MFG"]},
        "BLOCK_MAIN": 24, "CI": ci["tau_GDP"],
        "CI_LO": ci["tau_GDP"]["tau_lo90"], "CI_HI": ci["tau_GDP"]["tau_hi90"],
        "SIGMA_C": SIGMA_C, "BASE_MAIN": "new_orders", "METHOD_MAIN": "FE",
        "SEED": 20260728, "main_s": MAIN_S, "main_pp": MAIN_PP, "CMAIN": CMAIN,
        "tau_MFG": TAU["tau_MFG"], "tau_GDP": TAU["tau_GDP"],
        "tau_REC": TAU["tau_REC"],
        "RESULT": {}, "say": lambda *p: print(*p, file=io.StringIO()),
    }
    exec(compile(SEC8, "<run.py sec.8>", "exec"), ns)

    tmp = tempfile.mkdtemp(prefix="z06-vygruzka-")
    ns["_HERE"] = tmp
    ns["RESULT"]["data"] = {}
    try:
        exec(compile(SEC12, "<run.py sec.12>", "exec"), ns)
        ns["_err"] = ""
    except Exception as exc:                                   # noqa: BLE001
        ns["_err"] = f"{type(exc).__name__}: {exc}"
    ns["_written"] = sorted(os.listdir(tmp))
    return ns


def main() -> int:
    print("=" * 78)
    print("Pometka braka pod podstavlennoy plankoy identificiruemosti")
    print("=" * 78)
    print(f"derevo: {Z06}")
    print(f"vyrezano iz run.py verbatim: sec.8 {SEC8.count(chr(10)) + 1} strok, "
          f"vygruzka {SEC12.count(chr(10)) + 1} strok")

    bad = 0
    for title, ci90 in WORLDS:
        ns = run_world(ci90)
        lad, prac, ship = (ns["RESULT"]["ladder"],
                           ns["RESULT"]["ladder_practical"], ns["LADDER_SHIP"])
        print("")
        print("-" * 78)
        print(title)
        print(f"  ladder_practical : "
              + (f"{prac['version']}, porog {prac['thresholds'][0]:+.4f}"
                 if prac else "NET (None)"))
        print(f"  ladder.rejected  : {lad.get('rejected')!r}")
        print(f"  V POSTAVKU       : "
              + (ship["version"] if ship else "NICHEGO (None)"))
        print(f"  zapisano faylov  : {ns['_written'] or 'NI ODNOGO'}"
              + (f"  [vygruzka upala: {ns['_err']}]" if ns["_err"] else ""))

        # Chego zhdyom: porog, po kotoromu lestnica rezhet -- eto tau_GDP.
        goden = ci90["tau_GDP"][1] - ci90["tau_GDP"][0] < SIGMA_C
        want = not goden
        got = bool(lad.get("rejected"))
        ok = got == want
        bad += not ok
        print(f"  -> tau_GDP goden: {goden}; zhdyom rejected={want}, "
              f"poluchili {got}: {'OK' if ok else 'PROVAL'}")

        try:
            C.level_step(0.0, lad)
            silent = True
            print("  -> level_step(0.0, result['ladder']): poschitalos' MOLCHA")
        except C.RejectedLadder:
            silent = False
            print("  -> level_step(0.0, result['ladder']): otkaz RejectedLadder")
        if silent and want:
            print("  -> PROVAL: zabrakovannaya lestnica schitaetsya molcha")
            bad += 1
        if ship is None and ns["_written"]:
            print("  -> PROVAL: postavlyat' nechego, a fayly zapisany")
            bad += 1
        if ship is not None and ship.get("rejected"):
            print("  -> PROVAL: v postavku uhodit lestnica s pometkoy rejected")
            bad += 1

    # Mir A obyazan sovpadat' s uzhe lezhashchim artefaktom pobukvenno: inache
    # pravka run.py -- eto pereschyot Z06, a ego nikto ne razreshal.
    print("")
    print("-" * 78)
    ns = run_world(REAL_CI)
    with open(os.path.join(Z06, "result.json"), encoding="utf-8") as fh:
        have = json.load(fh)
    same = {
        "rejected_why": ns["RESULT"]["ladder"]["rejected_why"]
        == have["ladder"]["rejected_why"],
        "ladder.month_counts": ns["RESULT"]["ladder"]["month_counts"]
        == have["ladder"]["month_counts"],
        "ladder_practical.steps": ns["RESULT"]["ladder_practical"]["steps"]
        == have["ladder_practical"]["steps"],
    }
    print("Mir A protiv lezhashchego result.json (pereschyota Z06 byt' ne dolzhno):")
    for k, v in same.items():
        print(f"  {k:24s} sovpadaet: {v}")
    if not all(same.values()):
        bad += 1

    print("")
    print("ITOG: " + ("VSE MIRY VEDUT SEBYA VERNO" if not bad
                      else f"{bad} PROVALOV"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
