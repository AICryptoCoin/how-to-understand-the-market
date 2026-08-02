#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z05 -- mutacionnyy stend: dokazyvaem, chto proverka KRASNEET.

check-z05.py govorit "54 iz 54". Eto nichego ne znachit, poka ne pokazano,
chto on umeet skazat' "net". Stend nizhe portit KOPII run.py i check-z05.py
vo VREMENNOM kataloge (rabochee derevo ne trogaetsya) i trebuet krasnogo.

Dva klassa mutaciy:

* **mutacii pribora** (`M1`, `M2`) -- portitsya tol'ko check-z05.py;
* **mutacii ob'ekta** (`M3`, `M4`) -- portitsya run.py, result.json
  pereschityvaetsya zanovo (`--quick --no-vintage`), pribor chist libo
  isporchen tak zhe, kak ob'ekt.

`M3` -- glavnaya iz nih: eto OBSHCHIY defekt, odinakovyy v prognone i v
proverke. Sverka s result.json takoy defekt ne lovit v principe, ego lovit
tol'ko nezavisimyy cenovoy marshrut bloka B.

    python mutations.py            # vse mutacii, ~8 minut na progretom keshe
    python mutations.py M3         # odna

Kontrol' `MC` obyazatelen: tot zhe ukorochennyy progon BEZ mutacii dolzhen
ostavat'sya zelyonym, inache krasnoe u M3/M4 spisyvalos' by na `--quick`.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)


def read(p: str) -> str:
    return io.open(p, encoding="utf-8").read()


def write(p: str, s: str) -> str:
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    return p


def repoint(src: str, result_dir: str) -> str:
    """Kopiya zhivyot vne dereva -- _HERE i _RESEARCH nado nazvat' yavno."""
    old = ("_HERE = os.path.dirname(os.path.abspath(__file__))\n"
           "_RESEARCH = os.path.dirname(_HERE)")
    assert old in src, "ne nayden blok putey"
    return src.replace(old, '_HERE = "%s"\n_RESEARCH = "%s"'
                       % (result_dir.replace(os.sep, "/"),
                          RESEARCH.replace(os.sep, "/")), 1)


def in_func(src: str, fname: str, old: str, new: str) -> str:
    """Zamena TOL'KO vnutri tela funkcii: u ret() est' bliznecy."""
    i = src.index("def %s(" % fname)
    j = src.index("\ndef ", i + 1)
    body = src[i:j]
    assert body.count(old) == 1, "%s: %d vhozhdeniy" % (fname, body.count(old))
    return src[:i] + body.replace(old, new, 1) + src[j:]


# --------------------------------------------------------------------------- #
# Mutacii pribora
# --------------------------------------------------------------------------- #

def m_sign_flip(src: str) -> str:
    """Global'nyy perevorot znaka dohodnosti: a - b vmesto b - a."""
    return in_func(src, "ret",
                   "return None if a is None or b is None else b - a",
                   "return None if a is None or b is None else a - b")


def m_stale_anchor(src: str) -> str:
    """Yakor' vhoda ustarel na odin torgovyy den' ('ustarevshaya cena')."""
    src = in_func(src, "ret",
                  "a, b = level(key, ME[m]), level(key, ME[m2])",
                  "a, b = level(key, _MUT_PREV.get(ME[m], ME[m])), "
                  "level(key, ME[m2])")
    inject = ("_MUT_DAYS = sorted({d for s in PX.values() for d in s})\n"
              "_MUT_PREV = {d: _MUT_DAYS[i - 1] "
              "for i, d in enumerate(_MUT_DAYS) if i}\n\n\n")
    i = src.index("def ret(")
    return src[:i] + inject + src[i:]


# --------------------------------------------------------------------------- #
# Mutacii ob'ekta (run.py)
# --------------------------------------------------------------------------- #

def r_sign_flip(src: str) -> str:
    """Tot zhe perevorot znaka, no v run.py: OBSHCHIY defekt s priborom."""
    return in_func(src, "fwd",
                   "return None if a is None or b is None else b - a",
                   "return None if a is None or b is None else a - b")


def r_weight(src: str) -> str:
    """Ves vhoda DXY v osi FED: 0.10 -> 0.20."""
    old = 'W_FED = {"us2y": 0.25, "real5": 0.15, "phase": 0.15, "dxy": 0.10}'
    assert old in src
    return src.replace(old, old.replace('"dxy": 0.10', '"dxy": 0.20'), 1)


# name -> (mutaciya run.py ili None, mutaciya pribora ili None, zhdyom krasnogo)
CASES = {
    "M0": (None, None, False),
    "MC": (lambda s: s, None, False),
    "M1": (None, m_sign_flip, True),
    "M2": (None, m_stale_anchor, True),
    "M3": (r_sign_flip, m_sign_flip, True),
    "M4": (r_weight, None, True),
}
TITLE = {
    "M0": "bez mutacii (polnyy result.json)",
    "MC": "kontrol': --quick --no-vintage, bez mutacii",
    "M1": "perevorot znaka dohodnosti V PRIBORE",
    "M2": "cena sdvinuta na torgovyy den' nazad V PRIBORE",
    "M3": "znak perevyornut I v run.py, I v pribore (obshchiy defekt)",
    "M4": "ves DXY 0.10 -> 0.20 v run.py (pribor chist)",
}


def build_result(tmp: str, name: str, mut) -> str:
    """Schitaet svoy result.json mutirovannym run.py; vozvrashchaet katalog."""
    d = os.path.join(tmp, name)
    os.makedirs(d, exist_ok=True)
    p = write(os.path.join(tmp, "run_%s.py" % name),
              mut(repoint(read(os.path.join(HERE, "run.py")), d)))
    r = subprocess.run([sys.executable, p, "--quick", "--no-vintage"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode:
        print((r.stdout or "")[-1500:])
        print((r.stderr or "")[-1500:])
        raise SystemExit("run.py na mutacii %s ne otrabotal" % name)
    return d


def run_checker(tmp: str, name: str, result_dir: str, mut) -> tuple[int, str]:
    src = repoint(read(os.path.join(HERE, "check-z05.py")), result_dir)
    p = write(os.path.join(tmp, "check_%s.py" % name), mut(src) if mut else src)
    r = subprocess.run([sys.executable, p], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    lines = (r.stdout or "").splitlines()
    tail = [x.strip() for x in lines if "proshlo" in x]
    fails = [x.strip().split("  -- ")[0] for x in lines if "PROVAL " in x]
    out = tail[-1] if tail else ((r.stderr or "").strip().splitlines() or
                                 ["(net vyvoda)"])[-1]
    if fails:
        out += " | " + ", ".join(f.replace("PROVAL  ", "") for f in fails[:4])
        if len(fails) > 4:
            out += ", ..."
    return r.returncode, out


def main() -> int:
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    tmp = tempfile.mkdtemp(prefix="z05-mut-")
    print("vremennyy katalog: %s" % tmp)
    bad = []
    try:
        for name, (rmut, cmut, want_red) in CASES.items():
            if only and name not in only:
                continue
            rd = HERE if rmut is None else build_result(tmp, name, rmut)
            code, summary = run_checker(tmp, name, rd, cmut)
            red = bool(code)
            ok = (red == want_red)
            print("  %-7s %-8s %-58s %s"
                  % ("OK" if ok else "PROVAL",
                     "KRASNYY" if red else "zelyonyy", TITLE[name], summary))
            sys.stdout.flush()
            if not ok:
                bad.append(name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("")
    if bad:
        print("PROVAL: mutacii ne dali ozhidaemogo cveta: %s" % ", ".join(bad))
        return 1
    print("vse mutacii dali ozhidaemyy cvet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
