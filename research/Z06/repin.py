#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Peresborka postavlyaemyh artefaktov Z06: composite.csv i composite-passport.json.

Zachem otdel'nyy skript, a ne progon run.py. run.py -- eto PERESCHYOT VSEY
ZADACHI: on zanovo tyanet dannye, zanovo schitaet porogi, bootstrap, Bai-Perrona
i perepisyvaet result.json. Chisla REPORT.md posle takogo progona otnosyatsya
uzhe k drugoy versii dannyh. Zdes' zhe nuzhno bylo drugoe: ne trogaya ni odnogo
znacheniya ryada, privesti artefakty v sootvetstvie s tem, chto v postavku
dejstvitel'no uhodit, i pripshpilit' ryad k versii dannyh.

Chto delaet rezhim po umolchaniyu (--relabel, on zhe bez argumentov):

  1. composite.csv -- kolonka L_step pereschityvaetsya po POSTAVLYAEMOY lestnice
     (LADDER_V1, dvuhstupenchataya po linii recessii tau_REC = -0.2004).
     Do etogo tam lezhala ZABRAKOVANNAYA lestnica po tau_GDP = -1.6806: ona
     rashodilas' s postavlyaemoy na 110 mesyacah iz 390. Kolonki date,
     composite, sigma_units, n_panels, panels perenosyatsya BAYT V BAYT.
  2. composite-passport.json:
       "ladder"                          -> postavlyaemaya (byla zabrakovannaya);
       "ladder_prereg_rejected_tau_GDP"  -> zabrakovannaya, pod imenem, kotoroe
                                            po oshibke ne voz'myosh';
       "pin"                             -> privyazka k versii dannyh.

Rezhim --rebuild -- eto uzhe drugoe: sobrat' ryad zanovo iz zhivyh istochnikov
i pripshpilit'sya k NIM. Posle nego chisla REPORT.md k artefaktam ne otnosyatsya,
i eto pechataetsya pryamym tekstom.

Vsyo v ASCII: konsol' etoy mashiny v cp1251.
"""

from __future__ import annotations

import csv
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import composite as C  # noqa: E402


CSV_COLUMNS = ["date", "composite", "sigma_units", "n_panels", "panels", "L_step"]


def _read_csv() -> list[dict[str, str]]:
    with open(C.CSV_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit(f"{C.CSV_PATH}: fayl pust")
    missing = [c for c in CSV_COLUMNS if c not in rows[0]]
    if missing:
        raise SystemExit(f"{C.CSV_PATH}: net kolonok {missing}")
    return rows


def _write_csv(rows: list[dict[str, str]]) -> None:
    with open(C.CSV_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(CSV_COLUMNS) + "\n")
        for r in rows:
            fh.write(f"{r['date']},{r['composite']},{r['sigma_units']},"
                     f"{r['n_panels']},\"{r['panels']}\",{r['L_step']}\n")


def _pin_block(*, frozen_at: str, w_ref: tuple[str, str],
               panels: dict[str, dict], dates: list[str], values: list[float],
               sigma_c: float, fetched_at: str, note: str) -> dict:
    return {
        "version": "Z06-pin-v1",
        "frozen_at": frozen_at,
        "note": note,
        "config": dict(C.PINNED_CONFIG),
        "w_ref": {"start": w_ref[0], "end": w_ref[1]},
        "panels": {k: {"last": v["last"], "n": v["n"], "n_ref": v["n_ref"],
                       "mu_ref": v["mu_ref"], "sd_ref": v["sd_ref"]}
                   for k, v in sorted(panels.items())},
        "series": {
            "file": os.path.basename(C.CSV_PATH),
            "first": dates[0],
            "last": dates[-1],
            "n": len(dates),
            "sigma_c": sigma_c,
            "fetched_at": fetched_at,
            "value_format": C.VALUE_FORMAT,
            "sha256": C.series_digest(dates, values),
        },
        "ladder_version": C.LADDER_V1["version"],
        "ladder_thresholds": list(C.LADDER_V1["thresholds"]),
        "policy": (
            "composite(pin='check') sveryaet zhivuyu sborku s etim blokom i pri "
            "rashozhdenii otkazyvaet, nazyvaya izmenivsheesya. Sverka znacheniy "
            "idyot v tochnosti value_format: polnoy tochnosti u zafiksirovannogo "
            "ryada net -- v fayl on lyog uzhe okruglyonnym. pin='frozen' otdayot "
            "ryad iz fayla bez seti, pin='off' -- zhivuyu sborku bez sverki."
        ),
    }


def relabel() -> None:
    """Postavlyaemaya lestnica v artefakty + pin. Ryad ne peresobiraetsya."""
    rows = _read_csv()
    dates = [r["date"] for r in rows]
    values = [float(r["composite"]) for r in rows]

    # Kontrol': fayl zapisan v toy tochnosti, kotoruyu pin i sveryaet.
    bad = [d for d, r in zip(dates, rows)
           if C.VALUE_FORMAT % float(r["composite"]) != r["composite"]]
    if bad:
        raise SystemExit(
            f"composite.csv zapisan ne v {C.VALUE_FORMAT}: {len(bad)} strok, "
            f"pervaya {bad[0]}. Pin na takom fayle stroit' nel'zya")

    old_steps = {r["date"]: r["L_step"] for r in rows}
    changed = 0
    for r in rows:
        L = C.level_step(float(r["composite"]), C.LADDER_V1)
        r["L_step"] = f"{L:+.1f}"
        if r["L_step"] != old_steps[r["date"]]:
            changed += 1
    _write_csv(rows)
    print(f"composite.csv: {len(rows)} strok, kolonka L_step pereschitana po "
          f"{C.LADDER_V1['version']}")
    print(f"  rashozhdenie s prezhney (zabrakovannoy po tau_GDP) lestnicey: "
          f"{changed} mesyacev iz {len(rows)}")

    with open(C.PASSPORT_PATH, encoding="utf-8") as fh:
        pp = json.load(fh)
    pp["ladder"] = C.LADDER_V1
    pp["ladder_prereg_rejected_tau_GDP"] = C.LADDER_PREREG_REJECTED_TAU_GDP
    pp["pin"] = _pin_block(
        frozen_at="2026-07-28",
        w_ref=(pp["w_ref"]["start"], pp["w_ref"]["end"]),
        panels=pp["panels"], dates=dates, values=values,
        sigma_c=pp["sigma_c"], fetched_at=pp["fetched_at"],
        note=("progon Z06 ot 2026-07-28, zerno 20260728; imenno na etom ryade "
              "poschitan REPORT.md"),
    )
    with open(C.PASSPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(pp, fh, ensure_ascii=True, indent=2)
    print(f"composite-passport.json: ladder = {pp['ladder']['version']}, "
          f"zabrakovannaya -> klyuch 'ladder_prereg_rejected_tau_GDP'")
    print(f"  pin: W_ref [{pp['pin']['w_ref']['start']} .. "
          f"{pp['pin']['w_ref']['end']}], sha256 ryada "
          f"{pp['pin']['series']['sha256'][:16]}...")
    for k, v in pp["pin"]["panels"].items():
        print(f"    {k:14s} poslednyaya tochka {v['last']}  n={v['n']}")


def rebuild(frozen_at: str) -> None:
    """Peresobrat' ryad iz zhivyh istochnikov i pripshpilit'sya k nim."""
    print("VNIMANIE: --rebuild menyaet SAM RYAD. Chisla REPORT.md poschitany na")
    print("prezhney versii dannyh i k novym artefaktam ne otnosyatsya. Chestnyy")
    print("put' posle etogo -- pereschyot vsey zadachi (python run.py).")
    print("")
    s, pp = C.composite_with_passport(pin="off")
    sigma = pp.sigma_c
    rows = []
    for d, v in zip(s.dates, s.values):
        mem = pp.membership[d]
        rows.append({"date": d, "composite": C.VALUE_FORMAT % v,
                     "sigma_units": C.VALUE_FORMAT % (v / sigma),
                     "n_panels": str(len(mem)), "panels": "|".join(mem),
                     "L_step": f"{C.level_step(v, C.LADDER_V1):+.1f}"})
    _write_csv(rows)
    print(f"composite.csv: {len(rows)} strok peresobrano zanovo")

    out = pp.to_dict()
    out["ladder"] = C.LADDER_V1
    out["ladder_prereg_rejected_tau_GDP"] = C.LADDER_PREREG_REJECTED_TAU_GDP
    out["built_by"] = "Z06/repin.py --rebuild"
    dates = [r["date"] for r in rows]
    values = [float(r["composite"]) for r in rows]
    out["pin"] = _pin_block(
        frozen_at=frozen_at, w_ref=pp.w_ref, panels=pp.panels,
        dates=dates, values=values, sigma_c=sigma, fetched_at=pp.fetched_at,
        note="peresobrano repin.py --rebuild; REPORT.md k etoy versii ne otnositsya",
    )
    with open(C.PASSPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=True, indent=2)
    print(f"composite-passport.json: pin perepisan na {frozen_at}, sha256 "
          f"{out['pin']['series']['sha256'][:16]}...")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--rebuild" in args:
        rest = [a for a in args if a != "--rebuild"]
        if len(rest) != 1:
            raise SystemExit(
                "python repin.py --rebuild YYYY-MM-DD\n"
                "  data nuzhna yavno: pin dolzhen nesti datu versii dannyh, a\n"
                "  vzyat' eyo iz sistemnyh chasov znachilo by sdelat' progon\n"
                "  nevosproizvodimym")
        rebuild(rest[0])
    else:
        relabel()
