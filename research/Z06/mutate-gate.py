#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chto imenno lovit check-rejected-ladder.py -- pokazano KRASNYM.

Gejt, kotoryy na vsyom otvechaet "ok", neotlichim ot gejta, kotoryy nichego ne
proveryaet. Zdes' 23 mutacii: kazhdaya portit odno mesto, i gejt obyazan na ney
upast'. Nemutirovannyy kontrol' obyazan ostavat'sya zelyonym -- bez nego
"vsyo krasnoe" oznachalo by prosto slomannuyu kopiyu.

Kazhdaya mutaciya delaetsya na KOPII dereva vo vremennom kataloge. Rabocheye
derevo ne trogaetsya vovse: v etom proekte uzhe byl sluchay, kogda mutacionnye
agenty isportili obshcheye derevo i "otkazyvalo vsyo".

Otdel'no: mutaciya obyazana DEYSTVITEL'NO chto-to menyat'. Zamena, kotoraya ne
nashla svoyu podstroku, dala by zelyonyy progon i chitalas' by kak "gejt ne
lovit" -- eto lozhnyy vyvod pro sam pribor, a ne pro gejt. Poetomu kazhdaya
pravka sveryaet, chto tekst/znachenie izmenilis', i inache schitaetsya
NEISPRAVNOY mutaciey.

Vsyo v ASCII: konsol' etoy mashiny v cp1251.

    python mutate-gate.py                 # na dereve, gde lezhit sam skript
    python mutate-gate.py --tree PUT      # na drugoy kopii (naprimer, do pravki)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))

FILES = ("check-rejected-ladder.py", "composite.py", "composite.csv",
         "composite-passport.json", "result.json")


class BadMutation(RuntimeError):
    """Mutaciya nichego ne izmenila -- eto defekt stenda, a ne gejta."""


# ---------------------------------------------------------------------------
# Instrumenty pravki. Kazhdyy trebuet, chtoby pravka sostoyalas'.
# ---------------------------------------------------------------------------

def edit_text(path: str, old: str, new: str) -> None:
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    if old not in src:
        raise BadMutation(f"{os.path.basename(path)}: podstroka ne naydena: "
                          f"{old[:60]!r}")
    if old == new:
        raise BadMutation("zamena tozhdestvenna")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(src.replace(old, new, 1))


def edit_json(path: str, keys: list, value: object) -> None:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    node = doc
    for k in keys[:-1]:
        node = node[k]
    was = node.get(keys[-1], "<net>") if isinstance(node, dict) else node[keys[-1]]
    if was == value:
        raise BadMutation(f"{'.'.join(map(str, keys))}: uzhe {value!r}")
    node[keys[-1]] = value
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=True, indent=2)


def drop_json(path: str, keys: list) -> None:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    node = doc
    for k in keys[:-1]:
        node = node[k]
    if keys[-1] not in node:
        raise BadMutation(f"{'.'.join(map(str, keys))}: klyucha i tak net")
    del node[keys[-1]]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=True, indent=2)


def p(root: str, name: str) -> str:
    return os.path.join(root, "Z06", name)


# ---------------------------------------------------------------------------
# Mutacii. Poryadok: sperva te, chto gejt lovil i do pravki (kontrol' togo, chto
# nichego ne slomano), potom tri, kotorye prohodili zelyonymi, potom svoi.
# ---------------------------------------------------------------------------

def m01(r): drop_json(p(r, "result.json"), ["ladder", "rejected"])
def m02(r): edit_json(p(r, "result.json"), ["ladder", "rejected"], False)
def m03(r): edit_json(p(r, "result.json"), ["ladder", "rejected_why"], "vsyo horosho")
def m04(r): edit_text(p(r, "composite.py"),
                      '"rejected_why": ("tau_GDP ne identificiruem: shirina 90% intervala "',
                      '"rejected_why": ("tau_GDP prekrasno identificiruem: shirina "')
def m05(r): edit_text(p(r, "composite.py"),
                      "    if not ladder.get(\"rejected\") or allow_rejected:\n        return",
                      "    if True:\n        return")
def m06(r): edit_text(p(r, "composite.py"),
                      '    """Uroven\' kompozita -> L (analog chetyryoh stupeney sec.1.4.1)."""\n'
                      "    _refuse_rejected(ladder, allow_rejected)",
                      '    """Uroven\' kompozita -> L (analog chetyryoh stupeney sec.1.4.1)."""')
def m07(r): edit_text(p(r, "composite.py"),
                      "    _refuse_rejected(ladder, allow_rejected)\n"
                      "    vals = {d: v for d, v in zip(series.dates, series.values)",
                      "    vals = {d: v for d, v in zip(series.dates, series.values)")
def m08(r):
    """Iz soobshcheniya ubrany OBA upominaniya 'ladder_practical'.

    Odnogo malo: imya vstrechaetsya v tekste dvazhdy, i pravka odnogo mesta
    ostavlyaet vtoroe -- takaya mutaciya prohodit zelyonoy, no dokazyvaet ne
    slabost' gejta, a nebrezhnost' stenda.
    """
    edit_text(p(r, "composite.py"),
              "  brat' nado POSTAVLYAEMUYU: result.json -> 'ladder_practical'\\n",
              "  brat' nado druguyu lestnicu\\n")
    edit_text(p(r, "composite.py"),
              "  a postavlyaemaya lezhit v 'ladder_practical'. Imenno poetomu zdes' ",
              "  a postavlyaemaya lezhit ryadom. Imenno poetomu zdes' ")


def m09(r):
    """Iz soobshcheniya ubrano nazvanie poroga -- i iz teksta, i iz prichiny."""
    edit_text(p(r, "composite.py"),
              "ZABRAKOVANNAYA lestnica po tau_GDP, v postavku ona ne vhodit.\\n",
              "ZABRAKOVANNAYA lestnica, v postavku ona ne vhodit.\\n")
    edit_text(p(r, "composite.py"),
              'f"  pochemu zabrakovana: {why}\\n"',
              'f"  pochemu zabrakovana: prichina est\'\\n"')
def m10(r): edit_text(p(r, "composite.py"),
                      "    if not ladder.get(\"rejected\") or allow_rejected:\n        return",
                      "    if not ladder.get(\"rejected\"):\n        return")


# --- Tri, kotorye do pravki prohodili ZELYoNYMI ----------------------------

def m11(r):
    """Podmena poroga vnutri postavlyaemoy lestnicy -- edinstvennoy kopii."""
    edit_json(p(r, "result.json"), ["ladder_practical", "steps"],
              [[-0.5, None, 1.0], [None, -0.5, -1.0]])


def m12(r):
    edit_json(p(r, "result.json"), ["ladder", "month_counts"],
              {"1.0": 200, "-1.0": 193})


def m13(r):
    edit_json(p(r, "result.json"), ["ladder", "version"], "Z06-v1-practical")


# --- Svoi sverh etogo ------------------------------------------------------

def m14(r):
    """Porog podmenyon TOL'KO v thresholds; steps ostavleny."""
    edit_json(p(r, "result.json"), ["ladder_practical", "thresholds"], [-0.5])


def m15(r):
    edit_json(p(r, "result.json"), ["ladder_practical", "month_counts"],
              {"1.0": 300, "-1.0": 93})


def m16(r):
    """Porog uehal v KODE (composite.LADDER_V1), a v artefaktah staryy."""
    edit_text(p(r, "composite.py"),
              '    "thresholds": [-0.2004379668757319],\n'
              '    "tau": {"tau_REC": -0.2004379668757319},',
              '    "thresholds": [-0.2500000000000000],\n'
              '    "tau": {"tau_REC": -0.2500000000000000},')


def m17(r):
    """Odna stroka kolonki L_step perevyornuta: ryad tot zhe, lestnica drugaya."""
    path = p(r, "composite.csv")
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\r\n").endswith(",+1.0"):
            lines[i] = line.replace(",+1.0", ",-1.0")
            break
    else:
        raise BadMutation("v composite.csv net ni odnoy stroki s +1.0")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(lines))


def m18(r):
    """V pasport vernuli ZABRAKOVANNUYU lestnicu -- odna stroka, kak i bylo."""
    path = p(r, "composite-passport.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["ladder"] = doc["ladder_prereg_rejected_tau_GDP"]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=True, indent=2)


def m19(r):
    edit_json(p(r, "result.json"), ["ladder_practical"], None)


def m20(r):
    edit_json(p(r, "result.json"), ["ladder_practical", "version"], "Z06-v1")


def m21(r):
    """Porog sdvinut VNUTRI vilki: ni odin mesyac ne pomenyal stupen'.

    Samaya tihaya iz vsekh: kolonka L_step sovpadyot stroka v stroku, razbienie
    ostanetsya 272/121. Na etom ryade raznicy net -- a na sleduyushchem budet.
    """
    edit_json(p(r, "result.json"), ["ladder_practical", "steps"],
              [[-0.2, None, 1.0], [None, -0.2, -1.0]])
    edit_json(p(r, "result.json"), ["ladder_practical", "thresholds"], [-0.2])


def m22(r):
    """Soglasovannaya podmena: chisla prichiny pravleny I v artefakte, I v kode.

    Proverka 1a sravnivaet ih drug s drugom i takuyu podmenu propustit -- eyo
    lovit tol'ko sverka s pereschitannym iz ryada razbieniem.
    """
    old = ("delit istoriyu 382 / 11 (97.2% / 2.8%)")
    new = ("delit istoriyu 300 / 93 (76.3% / 23.7%)")
    edit_text(p(r, "composite.py"), old, new)
    with open(p(r, "result.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    if old not in doc["ladder"]["rejected_why"]:
        raise BadMutation("result.json: v rejected_why net ozhidaemoy podstroki")
    doc["ladder"]["rejected_why"] = doc["ladder"]["rejected_why"].replace(old, new)
    with open(p(r, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=True, indent=2)


def m23(r):
    """Podmena poroga u samoy zabrakovannoy lestnicy."""
    edit_json(p(r, "result.json"), ["ladder", "steps"],
              [[-3.0, None, 1.0], [None, -3.0, -1.0]])


MUTATIONS = [
    (1, "result.json: u 'ladder' ubran klyuch rejected", m01),
    (2, "result.json: rejected = false", m02),
    (3, "result.json: rejected_why zamenen tekstom", m03),
    (4, "composite.py: rejected_why v konstante zamenen", m04),
    (5, "composite.py: _refuse_rejected nichego ne proveryaet", m05),
    (6, "composite.py: level_step bol'she ne zovyot _refuse_rejected", m06),
    (7, "composite.py: ladder_contribution ne zovyot _refuse_rejected", m07),
    (8, "composite.py: iz soobshcheniya ubrano 'ladder_practical'", m08),
    (9, "composite.py: iz soobshcheniya ubrano 'tau_GDP'", m09),
    (10, "composite.py: dver' allow_rejected zavarena", m10),
    (11, "result.json: PODMENA POROGA v ladder_practical (steps)", m11),
    (12, "result.json: month_counts zabrakovannoy zameneny", m12),
    (13, "result.json: version zabrakovannoy zamenena", m13),
    (14, "result.json: podmena tol'ko v ladder_practical.thresholds", m14),
    (15, "result.json: month_counts postavlyaemoy zameneny", m15),
    (16, "composite.py: porog LADDER_V1 uehal, artefakty starye", m16),
    (17, "composite.csv: odna stroka kolonki L_step perevyornuta", m17),
    (18, "pasport: v 'ladder' vernuli zabrakovannuyu", m18),
    (19, "result.json: ladder_practical = null", m19),
    (20, "result.json: version postavlyaemoy zamenena", m20),
    (21, "result.json: porog sdvinut VNUTRI vilki (mesyacy ne menyayutsya)", m21),
    (22, "soglasovanno: chisla prichiny pravleny i v kode, i v artefakte", m22),
    (23, "result.json: podmena poroga u samoy zabrakovannoy", m23),
]


# ---------------------------------------------------------------------------

def prepare(tree: str, dest: str) -> str:
    """Kopiya dereva: Z06/ i sources.py ryadom (composite.py importiruet ego)."""
    os.makedirs(os.path.join(dest, "Z06"), exist_ok=True)
    for name in FILES:
        shutil.copy2(os.path.join(tree, name), os.path.join(dest, "Z06", name))
    shutil.copy2(os.path.join(os.path.dirname(tree), "sources.py"),
                 os.path.join(dest, "sources.py"))
    return dest


def run_gate(root: str) -> tuple[int, str]:
    res = subprocess.run(
        [sys.executable, "check-rejected-ladder.py"],
        cwd=os.path.join(root, "Z06"), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    out = (res.stdout or "") + (res.stderr or "")
    tail = ""
    for line in out.splitlines():
        if line.startswith("proshlo "):
            tail = line
    if not tail:
        last = [ln for ln in out.splitlines() if ln.strip()]
        tail = ("upal: " + last[-1][:70]) if last else "net vyvoda"
    return res.returncode, tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default=_HERE,
                    help="katalog Z06, kotoryy proveryaem (po umolchaniyu -- svoy)")
    args = ap.parse_args()
    tree = os.path.abspath(args.tree)

    print("=" * 78)
    print("Mutacionnyy progon gejta zabrakovannoy lestnicy")
    print("=" * 78)
    print(f"derevo: {tree}")

    tmp = tempfile.mkdtemp(prefix="z06-mut-")
    print(f"kopii:  {tmp}")
    print("")

    # Kontrol' pervym: bez nego krasnyy progon nichego ne znachit.
    ctl = prepare(tree, os.path.join(tmp, "control"))
    code, tail = run_gate(ctl)
    ctl_green = code == 0
    print(f"KONTROL' (bez mutacii): kod {code}, {tail} -> "
          f"{'ZELYoNYY' if ctl_green else 'KRASNYY -- kopiya slomana!'}")
    print("")

    print(f"{'N':>3}  {'chto isporcheno':<62} {'gejt'}")
    print("-" * 78)
    caught, missed, broken = 0, [], []
    for num, title, fn in MUTATIONS:
        root = prepare(tree, os.path.join(tmp, f"m{num:02d}"))
        try:
            fn(root)
        except BadMutation as exc:
            broken.append((num, str(exc)))
            print(f"{num:>3}  {title:<62} MUTACIYA NE PRIMENILAS'")
            print(f"     {exc}")
            continue
        code, tail = run_gate(root)
        if code:
            caught += 1
            print(f"{num:>3}  {title:<62} LOVIT  ({tail})")
        else:
            missed.append((num, title))
            print(f"{num:>3}  {title:<62} PROPUSK ({tail})")

    print("-" * 78)
    print(f"lovit {caught} iz {len(MUTATIONS)}; propuskaet {len(missed)}; "
          f"neispravnyh mutaciy {len(broken)}")
    for num, title in missed:
        print(f"  PROPUSK {num}: {title}")
    for num, why in broken:
        print(f"  NEISPRAVNA {num}: {why}")
    if not ctl_green:
        print("  KONTROL' KRASNYY: rezul'taty vyshe nichego ne znachat")
    print("")
    print(f"kopii ostavleny dlya razbora: {tmp}")
    return 0 if (ctl_green and not missed and not broken) else 1


if __name__ == "__main__":
    raise SystemExit(main())
