#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z05 -- proverka pribora KRASNYM, a ne zelyonym.

Otricatel'nyy verdikt opasnee polozhitel'nogo odnim: dolya vernyh znakov
okolo 0.50 -- eto rovno to, chto vydast SLOMANNYY konveyer. Poetomu prezhde
chem verit' nulyu, nado pokazat', chto pribor voobshche sposoben uvidet' signal
i chto on chitaet znak imenno tak, kak zapisano v spetsifikacii.

Kod nizhe napisan ZANOVO i ne importiruet run.py: on beryot iz result.json
tol'ko pomesyachnye sostoyaniya i sam schitaet popadaniya, bootstrap i doli.
Sovpadenie s otchyotom -- eto sovpadenie dvuh nezavisimyh realizaciy.

    python check-z05.py          # 10 proverok, seti ne trebuet (kesh)

Kazhdaya proverka ustroena tak, chtoby padat' na oshibke, a ne prohodit'
na lyuboy realizacii.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_RESEARCH = os.path.dirname(_HERE)
for _p in (_RESEARCH, os.path.join(_RESEARCH, "Z06")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sources as S            # noqa: E402
import composite as C          # noqa: E402

SEED = 20260802
B = 2000
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("  %-7s %s%s" % ("OK" if ok else "PROVAL", name,
                           ("  -- " + detail) if detail else ""))
    sys.stdout.flush()


def head(t: str) -> None:
    print("")
    print("=" * 74)
    print(t)
    print("=" * 74)


R = json.load(open(os.path.join(_HERE, "result.json"), encoding="utf-8"))
MONTHS = sorted(R["month_end_dates"])

# Koncy mesyacev stroyatsya ZANOVO iz SPY, a ne berutsya iz result.json.
# Prichina ne v nezavisimosti radi nezavisimosti: mesyacy-CELI gorizonta
# lezhat ZA pravym krayem okna sostoyaniy (dlya sostoyaniya 2026-06 pri h=1
# cel' -- 2026-07). Pervaya redakciya etoy proverki brala kartu mesyacev iz
# result.json, gde tol'ko okno sostoyaniy, i molcha teryala poslednie mesyacy:
# eyo pul dal 0.4900 protiv 0.4918 v otchyote. Rashozhdenie okazalos' defektom
# proverki, i imenno tak ono i bylo naydeno -- proverkoy.
_spy = S.yahoo("SPY")
ME: dict[str, str] = {}
for _d, _v in zip(_spy.dates, _spy.values):
    if _v is not None:
        ME[_d[:7]] = _d
_lost = [m for m in MONTHS if ME.get(m) != R["month_end_dates"][m]]
assert not _lost, "koncy mesyacev razoshlis' s otchyotom: %s" % _lost[:5]

# --------------------------------------------------------------------------- #
# Pary perepisany zanovo s cheatsheet-spec.md sec.5, a ne vzyaty iz run.py.
# --------------------------------------------------------------------------- #

SPEC_PAIRS = {
    "SIZE": (["SPY"], ["IWM"], {"I": 1, "II": -1, "III": 1, "IV": -1, "CENTER": 1}),
    "STYLE": (["QQQ"], ["IWM"], {"I": 1, "IV": -1, "CENTER": -1}),
    "GEO": (["EFA"], ["EEM"], {"I": 1, "II": -1, "III": 1, "IV": -1, "CENTER": 1}),
    "TECHMAT": (["XLK"], ["XLB"], {"I": 1, "IV": -1}),
    "DISCSTAP": (["XLY"], ["XLP"], {"II": 1, "III": -1}),
    "CYCNON": (["XLY", "XLI", "XLB", "XLE"], ["XLP", "XLV", "XLU"],
               {"II": 1, "III": -1, "IV": 1}),
    "MATFIN": (["XLB", "XLF"], ["SPY"], {"IV": 1}),
    "DUR": (["TLT"], ["SHY"], {"I": 1, "III": -1, "IV": -1}),
    "CRED": (["LQD"], ["IEF"], {"II": 1, "III": -1, "IV": -1}),
    "GOLD": (["GC=F"], [], {"I": 1, "II": 1, "III": -1, "IV": -1}),
    "COMM": (["^SPGSCI"], [], {"I": -1, "II": 1, "III": -1, "IV": 1}),
    "OIL": (["CL=F"], [], {"IV": 1}),
    "USD": (["DX-Y.NYB"], [], {"II": -1, "III": 1}),
    "VIX": (["^VIX"], [], {"II": -1, "III": 1}),
}

SYMS = sorted({s for lo, sh, _ in SPEC_PAIRS.values() for s in lo + sh})
PX: dict[str, dict[str, float]] = {}
for sym in SYMS:
    ser = S.yahoo(sym)
    PX[sym] = {d: float(v) for d, v in zip(ser.dates, ser.values)
               if v is not None and v > 0}


def level(key: str, iso: str) -> float | None:
    lo, sh, _ = SPEC_PAIRS[key]
    try:
        a = sum(math.log(PX[s][iso]) for s in lo) / len(lo)
    except KeyError:
        return None
    if not sh:
        return a
    try:
        b = sum(math.log(PX[s][iso]) for s in sh) / len(sh)
    except KeyError:
        return None
    return a - b


def add_m(m: str, k: int) -> str:
    t = int(m[:4]) * 12 + int(m[5:7]) - 1 + k
    return "%04d-%02d" % (t // 12, t % 12 + 1)


def ret(key: str, m: str, h: int) -> float | None:
    m2 = add_m(m, h)
    if m2 not in ME:
        return None
    a, b = level(key, ME[m]), level(key, ME[m2])
    return None if a is None or b is None else b - a


def hits_for(states: dict[str, str], h: int, keys=None,
             flip: bool = False) -> list[tuple[str, str, float]]:
    out = []
    for key in (keys or SPEC_PAIRS):
        signs = SPEC_PAIRS[key][2]
        for m in MONTHS:
            want = signs.get(states.get(m, "ANOMALY"))
            if want is None:
                continue
            r = ret(key, m, h)
            if r is None or r == 0.0:
                continue
            if flip:
                want = -want
            out.append((m, key, 1.0 if (r > 0) == (want > 0) else 0.0))
    return out


def rate(rows) -> float:
    return sum(x[2] for x in rows) / len(rows) if rows else float("nan")


def boot_p(rows, blk: int, seed: int = SEED) -> float:
    """Klasternyy blochnyy bootstrap po mesyacam, nulevaya 0.5."""
    by: dict[str, list[float]] = {}
    for m, _, v in rows:
        by.setdefault(m, []).append(v)
    ms = sorted(by)
    n = len(ms)
    if n < blk * 8:
        return float("nan")
    rng = random.Random(seed)
    ge = 0
    for _ in range(B):
        acc = cnt = 0.0
        i = 0
        while i < n:
            st = rng.randrange(n)
            for k in range(blk):
                if i >= n:
                    break
                vs = by[ms[(st + k) % n]]
                acc += sum(vs)
                cnt += len(vs)
                i += 1
        if acc / cnt <= 0.5:
            ge += 1
    return (1 + ge) / (B + 1)


# =========================================================================== #
head("A. Predposylka Z06: zabrakovannaya lestnica obyazana padat'")

lad_bad = json.load(open(os.path.join(_RESEARCH, "Z06", "result.json"),
                         encoding="utf-8"))["ladder"]
check("A1 result.json['ladder'] nesyot rejected=true",
      lad_bad.get("rejected") is True)
check("A2 rejected_why zapolnen i nazyvaet tau_GDP",
      "tau_GDP" in str(lad_bad.get("rejected_why", "")))
comp = C.frozen_composite()
try:
    C.ladder_contribution(comp, lad_bad)
    check("A3 vyzov po zabrakovannoy lestnice OTKAZYVAET", False,
          "vyzov otrabotal molcha")
except C.RejectedLadder as e:
    check("A3 vyzov po zabrakovannoy lestnice OTKAZYVAET",
          "ladder_practical" in str(e), "soobshchenie nazyvaet zamenu")

# mutaciya: snyat' pometku s KOPII -- vklad obyazan poyavit'sya i otlichat'sya
mut = dict(lad_bad)
mut.pop("rejected")
good = C.ladder_contribution(comp, C.LADDER_V1)
bad = C.ladder_contribution(comp, mut)
diff = sum(1 for a, b in zip(good.values, bad.values) if a != b)
check("A4 bez pometki ta zhe lestnica schitaetsya i dayot DRUGOY vklad",
      diff > 0, "rashozhdenie %d mesyacev iz %d" % (diff, len(good.values)))

# =========================================================================== #
head("B. Polozhitel'nyy kontrol': sposoben li pribor uvidet' signal")

# B1: orakul. Sostoyanie stroitsya iz BUDUSHCHEGO znaka odnoy pary (GOLD):
#     kvadrant vybiraetsya tak, chtoby predpisanie sovpalo s faktom.
for h in (1, 3):
    orac: dict[str, str] = {}
    for m in MONTHS:
        r = ret("GOLD", m, h)
        if r is None:
            continue
        orac[m] = "I" if r > 0 else "III"      # GOLD: +1 v Q-I, -1 v Q-III
    rows = hits_for(orac, h, keys=["GOLD"])
    check("B1.h%d orakul dayot dolyu 1.000" % h, abs(rate(rows) - 1.0) < 1e-12,
          "n=%d dolya=%.4f" % (len(rows), rate(rows)))
    rows_anti = hits_for(orac, h, keys=["GOLD"], flip=True)
    check("B1.h%d antiorakul dayot dolyu 0.000" % h,
          abs(rate(rows_anti)) < 1e-12,
          "n=%d dolya=%.4f" % (len(rows_anti), rate(rows_anti)))

# B2: moshchnost'. Sostoyanie verno v 60 % mesyacev, sluchayno v ostal'nyh.
#     Pribor obyazan vosstanovit' ~0.60 I otvergnut' nulevuyu -- inache
#     ob'yavlennaya v HYPOTHESIS sec.7.3 moshchnost' na etoy vyborke lozhna.
rng = random.Random(SEED)
mix: dict[str, str] = {}
for m in MONTHS:
    r = ret("GOLD", m, 1)
    if r is None:
        continue
    true_q = "I" if r > 0 else "III"
    wrong_q = "III" if r > 0 else "I"
    mix[m] = true_q if rng.random() < 0.60 else wrong_q
rows = hits_for(mix, 1, keys=["GOLD"])
p = boot_p(rows, 3)
check("B2 smes' 60/40 vosstanovlena", abs(rate(rows) - 0.60) < 0.06,
      "n=%d dolya=%.4f" % (len(rows), rate(rows)))
check("B2 i otvergaet nulevuyu 0.5 na etom n", p < 0.05,
      "p=%.4f pri n_mesyacev=%d" % (p, len({x[0] for x in rows})))

# B3: smes' 50/50 NE dolzhna otvergat'sya -- inache pribor lozhno-polozhitelen
mix50: dict[str, str] = {}
for m in MONTHS:
    r = ret("GOLD", m, 1)
    if r is None:
        continue
    mix50[m] = rng.choice(["I", "III"])
rows50 = hits_for(mix50, 1, keys=["GOLD"])
p50 = boot_p(rows50, 3)
check("B3 smes' 50/50 nulevuyu NE otvergaet", not (p50 < 0.05),
      "dolya=%.4f p=%.4f" % (rate(rows50), p50))

# =========================================================================== #
head("C. Nezavisimyy pereschyot zayavlennyh chisel")

for cfg, hkey in (("P10", "main"), ("A20NOVAL", None)):
    states = R["monthly_states"][cfg]
    for h in (1, 3):
        rows = hits_for(states, h)
        mine = rate(rows)
        if hkey:
            theirs = R["main"]["pooled"]["h%d" % h]["rate"]
        else:
            theirs = R["posthoc_cfg"][cfg]["pooled"]["h%d" % h]["rate"]
        check("C.%s h%d pul sovpal s otchyotom" % (cfg, h),
              abs(mine - theirs) < 5e-4,
              "moy %.4f protiv %.4f" % (mine, theirs))

# C2: razlozhenie -- tol'ko kvadranty
states = R["monthly_states"]["A20NOVAL"]
quad_states = {m: s for m, s in states.items() if s not in ("CENTER", "ANOMALY")}
rows = hits_for(quad_states, 1)
theirs = R["posthoc_cfg"]["A20NOVAL"]["pooled_decomp"]["quad_h1"]["rate"]
check("C.razlozhenie 'tol'ko kvadranty' sovpalo", abs(rate(rows) - theirs) < 5e-4,
      "moy %.4f protiv %.4f, n=%d" % (rate(rows), theirs, len(rows)))

# C3: simmetriya znaka -- perevyornutye predpisaniya dayut rovno 1 - p
rows_f = hits_for(states, 1, flip=True)
check("C.perevyornutye predpisaniya dayut 1 - dolya",
      abs(rate(rows_f) - (1.0 - rate(hits_for(states, 1)))) < 1e-12,
      "%.4f protiv %.4f" % (rate(rows_f), 1.0 - rate(hits_for(states, 1))))

# =========================================================================== #
head("D. Nesovmestimost' trebovaniy A i B sec.1.4.7")

ab = R["A_vs_B"]
check("D1 pri q=0.20 trebovanie B ne vypolneno",
      ab["spell_at_q020"] < 30,
      "spell %.1f dn." % ab["spell_at_q020"])
check("D2 pri naimen'shem q, dayushchem B, A narusheno gruboy",
      ab["center_share_at_chosen"] > 3 * 0.20,
      "Centr %.1f%%" % (100 * ab["center_share_at_chosen"]))
check("D3 A nedostizhimo ni pri kakom theta (granica pri theta=0)",
      ab["A_reachable_at_any_theta"] is False,
      "Centr pri theta=0: %.1f%%" % (100 * ab["center_share_at_theta0"]))

# =========================================================================== #
head("E. Sama proverka C -- gate ili ukrashenie: mutiruem i zhdyom KRASNOGO")

# Proverka "moyo chislo sovpalo s otchyotom" bespolezna, esli ona sovpadaet
# pri LYUBYH vhodnyh dannyh. Nizhe dve mutacii; kazhdaya obyazana slomat' C.

base = R["posthoc_cfg"]["A20NOVAL"]["pooled"]["h1"]["rate"]

# E1: peremeshat' sostoyaniya po mesyacam (sostav sostoyaniy tot zhe, poryadok
#     drugoy) -- svyaz' s budushchim znakom obyazana ischeznut'.
st = dict(R["monthly_states"]["A20NOVAL"])
keys = sorted(st)
vals = [st[k] for k in keys]
random.Random(1).shuffle(vals)
shuffled = dict(zip(keys, vals))
r_shuf = rate(hits_for(shuffled, 1))
check("E1 peremeshannye sostoyaniya lomayut sovpadenie",
      abs(r_shuf - base) >= 5e-4,
      "peremeshano %.4f protiv otchyota %.4f" % (r_shuf, base))

# E2: podmenit' odin predpisannyy znak (GOLD v Q-I: +1 -> -1).
saved = SPEC_PAIRS["GOLD"][2]["I"]
SPEC_PAIRS["GOLD"][2]["I"] = -saved
r_mut = rate(hits_for(R["monthly_states"]["A20NOVAL"], 1))
SPEC_PAIRS["GOLD"][2]["I"] = saved
check("E2 podmena odnogo znaka v tablice lomaet sovpadenie",
      abs(r_mut - base) >= 5e-4,
      "s podmenoy %.4f protiv otchyota %.4f" % (r_mut, base))

# E3: sdvinut' gorizont na mesyac -- dolya obyazana izmenit'sya.
r_h3 = rate(hits_for(R["monthly_states"]["A20NOVAL"], 3))
check("E3 drugoy gorizont dayot druguyu dolyu", abs(r_h3 - base) >= 5e-4,
      "h3 %.4f protiv h1 %.4f" % (r_h3, base))

# =========================================================================== #
head("ITOG")
print("  proshlo %d, provaleno %d" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("    PROVAL: %s" % f)
sys.exit(1 if FAIL else 0)
