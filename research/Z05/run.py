#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z05 -- glavnaya zadacha kontura: rabotaet li klassifikator.

Sostoyanie schitaetsya po synthesis/cheatsheet-spec.md (dve osi, chetyre
kvadranta i Centr, predohranitel' formoy krivoy) i proveryaetsya na znak
14 predpisannyh parnyh sdelok vperyod na 1 i 3 mesyaca.

Vsyo pechataemoe -- ASCII: konsol' etoy mashiny v cp1251.

    python run.py            # polnyy progon
    python run.py --quick    # umen'shennyy bootstrap, dlya otladki koda
    python run.py --no-vintage   # bez vetvi VINTAGE-PARTIAL (ona medlennaya)

Pred-registraciya -- HYPOTHESIS.md, zafiksirovana kommitom do pervogo
raschyota. Nomera sekciy nizhe sootvetstvuyut eyo razdelam.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import random
import statistics
import sys
import time
from datetime import date, timedelta
from typing import Any, Callable, Iterable, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
_RESEARCH = os.path.dirname(_HERE)
for _p in (_RESEARCH, os.path.join(_RESEARCH, "Z06")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sources as S            # noqa: E402
import composite as C          # noqa: E402

# =========================================================================== #
# 0. Konstanty pred-registracii
# =========================================================================== #

SEED = 20260802
QUICK = "--quick" in sys.argv
NO_VINTAGE = "--no-vintage" in sys.argv

B_BOOT = 400 if QUICK else 5000

WIN_START = "2004-01-01"        # HYPOTHESIS sec.2.3
WIN_END = "2026-06-30"
WARMUP_START = "2001-01-01"     # razgon dlya dvuhletnego MAD, sec.3.3
CALIB_END = "2014-12-31"        # sec.5: kalibrovka do 2015
OOS_START = "2015-01-01"

MIN_OBS_DAILY = 250             # sec.3.1
MIN_OBS_MONTHLY = 24            # sec.11 zapis' 1 (dva goda v chastote ryada)
MIN_OBS_WEEKLY = 104

CLAIMS_PUB_LAG_DAYS = 5         # sec.3.5: subbota (konec nedeli) -> chetverg

MAD_C = 1.4826
CLIP = 3.0

Q_GRID = [round(0.20 + 0.02 * i, 2) for i in range(21)]   # 0.20 .. 0.60
MIN_SPELL_DAYS = 30             # trebovanie B
CENTER_TARGET = 0.20            # trebovanie A

PARALLEL_BP = 0.05              # sec.4.2: |d spred| < 5 b.p. -> parallel'nyy sdvig

HORIZONS = (1, 3)
BLOCK = {1: 3, 3: 6}            # dlina bloka v mesyacah
DEGEN_RATIO = 8                 # n / L; nizhe -- bootstrap vyrozhdaetsya
HIT_THRESHOLD = 0.55
NULL_RATE = 0.5

COVID_START, COVID_END = "2020-03", "2021-12"
Z25_SPLIT = "2009-12"

FAMILY_F1 = 28                  # 14 par x 2 gorizonta
FAMILY_F2 = 2                   # pul x 2 gorizonta

CUTOFF = 0.60                   # sec.1.4.2 speki

RESULT: dict[str, Any] = {"task": "Z05", "seed": SEED, "quick": QUICK,
                          "b_boot": B_BOOT}

_T0 = time.time()


def say(*parts: Any) -> None:
    txt = " ".join(str(p) for p in parts)
    try:
        print(txt)
    except UnicodeEncodeError:                       # pragma: no cover
        print(txt.encode("ascii", "replace").decode("ascii"))
    sys.stdout.flush()


def head(title: str) -> None:
    say("")
    say("=" * 78)
    say(title)
    say("=" * 78)


def sub(title: str) -> None:
    say("")
    say("-- " + title + " " + "-" * max(0, 74 - len(title)))


# =========================================================================== #
# 1. Melkie instrumenty
# =========================================================================== #

def d2(iso: str) -> date:
    """ISO-data; klyuch mesyaca 'GGGG-MM' chitaetsya kak pervoe chislo."""
    return date.fromisoformat(iso[:10] if len(iso) >= 10 else iso + "-01")


def s2(d: date) -> str:
    return d.isoformat()


def shift_days(iso: str, n: int) -> str:
    return s2(d2(iso) - timedelta(days=n))


def mkey(iso: str) -> str:
    return iso[:7]


def add_months(m: str, k: int) -> str:
    y, mm = int(m[:4]), int(m[5:7])
    t = (y * 12 + mm - 1) + k
    return "%04d-%02d" % (t // 12, t % 12 + 1)


def month_diff(a: str, b: str) -> int:
    return (int(a[:4]) * 12 + int(a[5:7])) - (int(b[:4]) * 12 + int(b[5:7]))


def last_dom(m: str) -> int:
    nxt = add_months(m, 1)
    return (date(int(nxt[:4]), int(nxt[5:7]), 1) - timedelta(days=1)).day


def avail_date(m: str, lag_months: int, dom: int) -> str:
    """Kogda mesyachnoe nablyudenie mesyaca m stanovitsya vidno (sec.3.5)."""
    tgt = add_months(m, lag_months)
    return "%s-%02d" % (tgt, min(dom, last_dom(tgt)))


def median(xs: Sequence[float]) -> float:
    return statistics.median(xs)


def mad(xs: Sequence[float]) -> float:
    m = median(xs)
    return median([abs(x - m) for x in xs])


def quantile(xs: Sequence[float], q: float) -> float:
    if not xs:
        return float("nan")
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    pos = q * (len(ys) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ys) - 1)
    return ys[lo] + (ys[hi] - ys[lo]) * (pos - lo)


def sign(x: float) -> float:
    return 0.0 if x == 0 else (1.0 if x > 0 else -1.0)


def norm_speed(raw: float, scale: float) -> float:
    """sec.1.4.1: clip(raw / (1.4826 * MAD), +-3) / 3."""
    z = raw / (MAD_C * scale)
    return max(-CLIP, min(CLIP, z)) / CLIP


class Step:
    """Ryad s poiskom 'poslednee znachenie ne pozzhe daty'."""

    __slots__ = ("d", "v")

    def __init__(self, pairs: Iterable[tuple[str, float]]) -> None:
        rows = sorted(pairs)
        self.d = [r[0] for r in rows]
        self.v = [r[1] for r in rows]

    def __len__(self) -> int:
        return len(self.d)

    def at(self, iso: str) -> float | None:
        i = bisect.bisect_right(self.d, iso) - 1
        return self.v[i] if i >= 0 else None

    def exact(self, iso: str) -> float | None:
        i = bisect.bisect_left(self.d, iso)
        return self.v[i] if i < len(self.d) and self.d[i] == iso else None


def observed(s: Any) -> list[tuple[str, float]]:
    return [(d, float(v)) for d, v in zip(s.dates, s.values) if v is not None]


# --------------------------------------------------------------------------- #
# Blochnyy bootstrap i Holm
# --------------------------------------------------------------------------- #

def block_draw(n: int, blk: int, rng: random.Random) -> list[int]:
    """Krugovoy blochnyy bootstrap: indeksy dliny n."""
    out: list[int] = []
    while len(out) < n:
        st = rng.randrange(n)
        for k in range(blk):
            out.append((st + k) % n)
            if len(out) >= n:
                break
    return out


def degenerate(n: int, blk: int) -> bool:
    return n < blk * DEGEN_RATIO


def boot_mean(vals: Sequence[float], blk: int, rng: random.Random,
              b: int = B_BOOT) -> list[float]:
    n = len(vals)
    return [sum(vals[i] for i in block_draw(n, blk, rng)) / n for _ in range(b)]


def p_above(draws: Sequence[float], null: float) -> float:
    """p dlya al'ternativy 'dolya vyshe null'."""
    if not draws:
        return float("nan")
    return (1 + sum(1 for x in draws if x <= null)) / (len(draws) + 1)


def p_below(draws: Sequence[float], null: float) -> float:
    if not draws:
        return float("nan")
    return (1 + sum(1 for x in draws if x >= null)) / (len(draws) + 1)


def holm(pvals: dict[str, float], m: int) -> dict[str, float]:
    """Poshagovaya poprava Holma na semeystvo razmera m."""
    items = sorted(pvals.items(), key=lambda kv: (math.inf if kv[1] != kv[1]
                                                  else kv[1]))
    out: dict[str, float] = {}
    run = 0.0
    for i, (k, p) in enumerate(items):
        if p != p:
            out[k] = float("nan")
            continue
        adj = min(1.0, p * (m - i))
        run = max(run, adj)
        out[k] = run
    return out


def n_needed(rate: float, z: float, h: int) -> int:
    """Skol'ko nablyudeniy nuzhno, chtoby dolya rate dala p s porogom z."""
    if rate <= NULL_RATE:
        return -1
    base = (z * 0.5 / (rate - NULL_RATE)) ** 2
    return int(math.ceil(base * (3 if h == 3 else 1)))


Z_HOLM1 = 2.913          # p = 0.05 / 28


# =========================================================================== #
# 2. Zagruzka dannyh
# =========================================================================== #

head("Z05 -- klassifikator: predskazyvaet li sostoyanie znak predpisannyh par")
say("Zerno %d; bootstrap B=%d; quick=%s; vintazhi=%s"
    % (SEED, B_BOOT, QUICK, not NO_VINTAGE))
say("Okno sostoyaniy %s .. %s; kalibrovka do %s; uderzhannyy hvost s %s"
    % (WIN_START, WIN_END, CALIB_END, OOS_START))

sub("2.1 Ryady")

RAW: dict[str, Any] = {}


def load(name: str, fn: Callable[[], Any]) -> Any:
    t = time.time()
    obj = fn()
    RAW[name] = obj
    n = len(observed(obj)) if hasattr(obj, "dates") else -1
    first = obj.dates[0] if getattr(obj, "dates", None) else "?"
    lastd, lastv = (obj.last() or ("?", float("nan"))) if hasattr(obj, "last") \
        else ("?", float("nan"))
    say("  %-14s n=%-6d %s .. %s  last=%-12.4f (%.1fs)"
        % (name, n, first, lastd, lastv, time.time() - t))
    return obj


FRED_IDS = {"DGS2": "DGS2", "DGS5": "DGS5", "DGS10": "DGS10",
            "T5YIE": "T5YIE", "PERMIT": "PERMIT", "IC4WSA": "IC4WSA",
            "NOF": "NOFDFSA066MSFRBPHI", "USREC": "USREC",
            "FEDFUNDS": "FEDFUNDS", "DFEDTAR": "DFEDTAR",
            "DFEDTARU": "DFEDTARU", "DFEDTARL": "DFEDTARL"}
for k, sid in FRED_IDS.items():
    load(k, (lambda s=sid: S.fred(s)))

YAHOO_IDS = ["DX-Y.NYB", "GC=F", "HG=F", "CL=F", "SPY", "IWM", "QQQ", "EFA",
             "EEM", "XLK", "XLB", "XLY", "XLP", "XLE", "XLF", "XLI", "XLV",
             "XLU", "TLT", "SHY", "LQD", "IEF", "SPHB", "SPLV", "^VIX",
             "^SPGSCI"]
for sym in YAHOO_IDS:
    load(sym, (lambda s=sym: S.yahoo(s)))

load("NAHB", lambda: S.nahb_hmi("t2")["HMI"])
load("COMPOSITE", C.frozen_composite)

sub("2.2 Predposylka: lestnica Z06")

_z06 = json.load(open(os.path.join(_RESEARCH, "Z06", "result.json"),
                      encoding="utf-8"))
_lad_bad, _lad_good = _z06["ladder"], _z06["ladder_practical"]
say("  result.json['ladder'].rejected      = %r" % _lad_bad.get("rejected"))
say("  result.json['ladder'].rejected_why  = %s"
    % str(_lad_bad.get("rejected_why"))[:96])
say("  result.json['ladder_practical'] month_counts = %s"
    % _lad_good.get("month_counts"))
assert _lad_bad.get("rejected") is True, "Z06 ladder ne pomechen rejected"
assert _lad_good["month_counts"] == {"1.0": 272, "-1.0": 121}, \
    "ladder_practical: razbienie ne 272 / 121"
assert _lad_good["thresholds"] == C.LADDER_V1["thresholds"], \
    "ladder_practical rashoditsya s composite.LADDER_V1"
_refused = False
try:
    C.ladder_contribution(RAW["COMPOSITE"], _lad_bad)
except C.RejectedLadder:
    _refused = True
say("  vyzov po zabrakovannoy lestnice otkazyvaet: %s" % _refused)
assert _refused, "zabrakovannaya lestnica poschitalas' molcha"
RESULT["precondition"] = {"rejected_flag": True, "refused": True,
                          "ladder_practical_counts": _lad_good["month_counts"]}


# =========================================================================== #
# 3. Setka dat
# =========================================================================== #

sub("3.1 Dnevnaya setka")

_spy = Step(observed(RAW["SPY"]))
GRID = [d for d in _spy.d if WIN_START <= d <= WIN_END]
# Razgon: MAD schitaetsya na dvuh godah sobstvennoy istorii ryada, i eta
# istoriya sushchestvuet DO nachala okna sostoyaniy. Esli stroit' prirashcheniya
# tol'ko na GRID, pervye 250 torgovyh dney okna teryayut vse dnevnye vhody --
# eto artefakt setki, a ne svoystvo speki.
GRID_FULL = [d for d in _spy.d if WARMUP_START <= d <= WIN_END]
say("  torgovyh dney v okne: %d  (%s .. %s)" % (len(GRID), GRID[0], GRID[-1]))
say("  setka postroeniya vhodov (s razgonom): %d  (%s .. %s)"
    % (len(GRID_FULL), GRID_FULL[0], GRID_FULL[-1]))

MONTH_END: dict[str, str] = {}
for d in _spy.d:
    MONTH_END[mkey(d)] = d                      # posledniy torgovyy den' mesyaca
MONTHS = sorted(m for m in MONTH_END if WIN_START[:7] <= m <= WIN_END[:7])
say("  mesyacev sostoyaniy: %d  (%s .. %s)" % (len(MONTHS), MONTHS[0], MONTHS[-1]))
RESULT["window"] = {"grid_days": len(GRID), "months": len(MONTHS),
                    "first": MONTHS[0], "last": MONTHS[-1]}

_usrec = {mkey(d): v for d, v in observed(RAW["USREC"])}
REC_MONTHS = [m for m in MONTHS if _usrec.get(m, 0.0) == 1.0]
say("  recessionnyh mesyacev (USREC): %d" % len(REC_MONTHS))
say("  kovidnyh mesyacev (%s .. %s): %d"
    % (COVID_START, COVID_END,
       sum(1 for m in MONTHS if COVID_START <= m <= COVID_END)))


# =========================================================================== #
# 4. Vklady vhodov
# =========================================================================== #

def rolling_scale(grid: Sequence[str], raw: dict[str, float],
                  years: int, min_obs: int) -> dict[str, float]:
    """MAD prirashcheniy za `years` let, vklyuchaya tekushchuyu tochku."""
    out: dict[str, float] = {}
    keys = [g for g in grid if g in raw]
    vals = [raw[g] for g in keys]
    lo = 0
    for i, g in enumerate(keys):
        cut = s2(d2(g) - timedelta(days=365 * years))[:len(g)]
        while lo < i and keys[lo] < cut:
            lo += 1
        win = vals[lo:i + 1]
        if len(win) < min_obs:
            continue
        m = mad(win)
        if m > 0:
            out[g] = m
    return out


def daily_speed(step: Step, grid: Sequence[str], win_days: int,
                *, log: bool = False, flip: bool = False) -> dict[str, float]:
    """Vhod-skorost' na dnevnoy setke (sec.3.1)."""
    raw: dict[str, float] = {}
    for g in grid:
        a, b = step.at(g), step.at(shift_days(g, win_days))
        if a is None or b is None:
            continue
        if log:
            if a <= 0 or b <= 0:
                continue
            raw[g] = math.log(a) - math.log(b)
        else:
            raw[g] = a - b
    scale = rolling_scale(grid, raw, 2, MIN_OBS_DAILY)
    sgn = -1.0 if flip else 1.0
    return {g: sgn * norm_speed(raw[g], scale[g]) for g in scale}


def monthly_level(vals: dict[str, float], threshold: float,
                  lag: int = 3) -> dict[str, float]:
    """Vhod-uroven', obshchiy sluchay: 0.6*sign(delta_3m) + 0.4*sign(uroven'-porog)."""
    out: dict[str, float] = {}
    for m in sorted(vals):
        prev = add_months(m, -lag)
        if prev not in vals:
            continue
        out[m] = 0.6 * sign(vals[m] - vals[prev]) + 0.4 * sign(vals[m] - threshold)
    return out


def monthly_speed(vals: dict[str, float], lag: int, *, log: bool,
                  flip: bool = False) -> dict[str, float]:
    ms = sorted(vals)
    raw: dict[str, float] = {}
    for m in ms:
        prev = add_months(m, -lag)
        if prev not in vals:
            continue
        a, b = vals[m], vals[prev]
        if log:
            if a <= 0 or b <= 0:
                continue
            raw[m] = math.log(a) - math.log(b)
        else:
            raw[m] = a - b
    scale = rolling_scale(sorted(raw), raw, 2, MIN_OBS_MONTHLY)
    sgn = -1.0 if flip else 1.0
    return {m: sgn * norm_speed(raw[m], scale[m]) for m in scale}


def weekly_speed(pairs: Sequence[tuple[str, float]], weeks: int,
                 *, flip: bool = False) -> dict[str, float]:
    """IC4WSA(t) - IC4WSA(t-13 nedel'); MAD za dva goda (104 nablyudeniya)."""
    dates = [p[0] for p in pairs]
    vals = {p[0]: p[1] for p in pairs}
    raw: dict[str, float] = {}
    for i, d in enumerate(dates):
        if i < weeks:
            continue
        raw[d] = vals[d] - vals[dates[i - weeks]]
    scale = rolling_scale(sorted(raw), raw, 2, MIN_OBS_WEEKLY)
    sgn = -1.0 if flip else 1.0
    return {d: sgn * norm_speed(raw[d], scale[d]) for d in scale}


def to_step_monthly(c: dict[str, float], lag: int, dom: int) -> Step:
    return Step((avail_date(m, lag, dom), v) for m, v in c.items())


sub("4.1 Mesyachnye i nedel'nye vhody")

_nahb = {mkey(d): v for d, v in observed(RAW["NAHB"])}
C_NAHB = monthly_level(_nahb, 50.0)
say("  NAHB (uroven' protiv 50):     mesyacev vklada %d" % len(C_NAHB))

_permit = {mkey(d): v for d, v in observed(RAW["PERMIT"])}
C_PERMIT = monthly_speed(_permit, 3, log=True)
say("  PERMIT (skorost', ln, 3 mes): mesyacev vklada %d" % len(C_PERMIT))

_comp_c = C.ladder_contribution(RAW["COMPOSITE"], C.LADDER_V1)
C_COMP = {mkey(d): v for d, v in observed(_comp_c)}
say("  kompozit Z06 (lestnica):      mesyacev vklada %d" % len(C_COMP))

_nof = {mkey(d): v for d, v in observed(RAW["NOF"])}
C_NOF = monthly_level(_nof, 0.0)
say("  Philly NOF (uroven' vs 0):    mesyacev vklada %d" % len(C_NOF))

C_CLAIMS = weekly_speed(observed(RAW["IC4WSA"]), 13, flip=True)
say("  IC4WSA (skorost', 13 nedel'): nedel' vklada %d" % len(C_CLAIMS))

# sec.3.5 ob'yavlyaet dlya IC4WSA "poslednyaya OPUBLIKOVANNAYA na datu
# sostoyaniya", a nablyudenie datirovano koncom nedeli (subbotoy) i vyhodit
# v chetverg sleduyushchey nedeli -- rovno cherez pyat' dney. Znachit vhod
# vesom 0.12 viden zdes' na pyat' dney ran'she, chem sushchestvuet.
#
# Pravilo NE ispolneno, i eto zapisano v REPORT sec.11 p.11 vmeste s
# izmerennym posledstviem: primenenie laga ne menyaet NI ODNOGO iz 270
# pomesyachnyh sostoyaniy P10, to est' ni odnogo otchyotnogo chisla vetvi
# verdikta. Prichina, po kotoroy ono ostavleno kak est': na eti zhe chisla
# (91 / 84 / 176 / q=0.42) pripayana zadacha Z27 -- ee progon sveryaetsya
# s Z05/result.json assert-ami. Ispravlenie dvigaet obe zadachi srazu i
# poetomu ne moyo delo v odinochku.
#
# Sledstvie proveryaetsya progonom, a ne obeshchaniem: check-z05.py, C6.
_claims_wd = {d2(d).weekday() for d in C_CLAIMS}
assert _claims_wd == {5}, "IC4WSA datirovan ne subbotoy: %s" % sorted(_claims_wd)

PUB = {"NAHB": (0, 16), "PERMIT": (1, 20), "COMP": (0, 28), "NOF": (0, 21)}
ST_NAHB = to_step_monthly(C_NAHB, *PUB["NAHB"])
ST_PERMIT = to_step_monthly(C_PERMIT, *PUB["PERMIT"])
ST_COMP = to_step_monthly(C_COMP, *PUB["COMP"])
ST_NOF = to_step_monthly(C_NOF, *PUB["NOF"])
ST_CLAIMS = Step(C_CLAIMS.items())
say("  lag publikacii IC4WSA: NE PRIMENYON (ob'yavlen v sec.3.5, +%d dney)"
    % CLAIMS_PUB_LAG_DAYS)

sub("4.2 Faza rezhima DKP")

_tgt: dict[str, float] = {}
for d, v in observed(RAW["DFEDTAR"]):
    _tgt[d] = v
_u = dict(observed(RAW["DFEDTARU"]))
_l = dict(observed(RAW["DFEDTARL"]))
for d in _u:
    if d in _l:
        _tgt[d] = (_u[d] + _l[d]) / 2.0
ST_TGT = Step(_tgt.items())
say("  celevaya stavka: %d dney, %s .. %s"
    % (len(ST_TGT), ST_TGT.d[0], ST_TGT.d[-1]))


def phase_c(iso: str) -> float | None:
    r = ST_TGT.at(iso)
    r6 = ST_TGT.at(shift_days(iso, 183))
    if r is None or r6 is None:
        return None
    if r > r6:
        return -1.0
    if r < r6:
        return 1.0
    lo = shift_days(iso, 3653)
    hist = [v for d, v in zip(ST_TGT.d, ST_TGT.v) if lo <= d <= iso]
    if len(hist) < MIN_OBS_DAILY:
        return None
    return 1.0 if r <= quantile(hist, 0.40) else -1.0


C_PHASE = {g: c for g in GRID_FULL if (c := phase_c(g)) is not None}
say("  faza opredelena v %d dnyah iz %d" % (len(C_PHASE), len(GRID_FULL)))
_ph = {}
for g, c in C_PHASE.items():
    _ph[c] = _ph.get(c, 0) + 1
say("  raspredelenie fazy: %s" % {("+1" if k > 0 else "-1"): v
                                  for k, v in sorted(_ph.items(), reverse=True)})

sub("4.3 Dnevnye vhody po tryom oknam")

ST_DGS2 = Step(observed(RAW["DGS2"]))
ST_DGS10 = Step(observed(RAW["DGS10"]))
_d5 = dict(observed(RAW["DGS5"]))
_ie = dict(observed(RAW["T5YIE"]))
ST_REAL5 = Step((d, _d5[d] - _ie[d]) for d in _d5 if d in _ie)
ST_DXY = Step(observed(RAW["DX-Y.NYB"]))
_gc = dict(observed(RAW["GC=F"]))
_hg = dict(observed(RAW["HG=F"]))
_cl = dict(observed(RAW["CL=F"]))
ST_HGGC = Step((d, _hg[d] / _gc[d]) for d in _hg if d in _gc and _gc[d] > 0)
ST_CLGC = Step((d, _cl[d] / _gc[d]) for d in _cl if d in _gc and _gc[d] > 0)
say("  real5Y: %d dney %s .. %s" % (len(ST_REAL5), ST_REAL5.d[0], ST_REAL5.d[-1]))

WINDOWS = (5, 10, 30)
DAILY_C: dict[int, dict[str, dict[str, float]]] = {}
for W in WINDOWS:
    DAILY_C[W] = {
        "us2y": daily_speed(ST_DGS2, GRID_FULL, W, flip=True),
        "real5": daily_speed(ST_REAL5, GRID_FULL, W, flip=True),
        "dxy": daily_speed(ST_DXY, GRID_FULL, W, log=True, flip=True),
        "hggc": daily_speed(ST_HGGC, GRID_FULL, W, log=True),
        "clgc": daily_speed(ST_CLGC, GRID_FULL, W, log=True),
    }
    say("  okno %2d dn.: " % W + ", ".join(
        "%s=%d" % (k, len(v)) for k, v in DAILY_C[W].items()))

sub("4.4 Forma krivoy")


def shape_at(iso: str, W: int) -> str | None:
    a, b = ST_DGS2.at(iso), ST_DGS2.at(shift_days(iso, W))
    c, e = ST_DGS10.at(iso), ST_DGS10.at(shift_days(iso, W))
    if None in (a, b, c, e):
        return None
    dk, dl = a - b, c - e
    dspread = dl - dk
    if abs(dspread) < PARALLEL_BP:
        return "PARALLEL"
    up = (dk + dl) / 2.0 > 0
    if not up and dspread < 0:
        return "I"
    if not up and dspread > 0:
        return "II"
    if up and dspread < 0:
        return "III"
    return "IV"


SHAPE: dict[int, dict[str, str]] = {
    W: {g: s for g in GRID if (s := shape_at(g, W)) is not None}
    for W in WINDOWS}
for W in WINDOWS:
    cnt: dict[str, int] = {}
    for v in SHAPE[W].values():
        cnt[v] = cnt.get(v, 0) + 1
    say("  okno %2d dn.: %s" % (W, dict(sorted(cnt.items()))))


def shape_vote(iso: str) -> str | None:
    votes = [SHAPE[W].get(iso) for W in WINDOWS]
    votes = [v for v in votes if v is not None]
    if len(votes) < 2:
        return None
    best, n = None, 0
    for v in set(votes):
        k = votes.count(v)
        if k > n:
            best, n = v, k
    return best if n >= 2 else "NOAGREE"


# =========================================================================== #
# 5. Svyortka osey
# =========================================================================== #

W_FED = {"us2y": 0.25, "real5": 0.15, "phase": 0.15, "dxy": 0.10}
W_FED_FULL = 1.00
W_MACRO = {"nahb": 0.13, "permit": 0.13, "comp": 0.10, "claims": 0.12,
           "nof": 0.08, "hggc": 0.04, "clgc": 0.04}
W_MACRO_FULL = 1.00


def axis(parts: dict[str, float | None], weights: dict[str, float],
         full: float) -> tuple[float | None, float]:
    num = den = 0.0
    for k, w in weights.items():
        c = parts.get(k)
        if c is None:
            continue
        num += w * c
        den += w
    share = den / full
    if share < CUTOFF or den == 0:
        return None, share
    return num / den, share


def state_parts(iso: str, W: int) -> tuple[dict[str, float | None],
                                           dict[str, float | None]]:
    dc = DAILY_C[W]
    fed = {"us2y": dc["us2y"].get(iso), "real5": dc["real5"].get(iso),
           "phase": C_PHASE.get(iso), "dxy": dc["dxy"].get(iso)}
    mac = {"nahb": ST_NAHB.at(iso), "permit": ST_PERMIT.at(iso),
           "comp": ST_COMP.at(iso), "claims": ST_CLAIMS.at(iso),
           "nof": ST_NOF.at(iso), "hggc": dc["hggc"].get(iso),
           "clgc": dc["clgc"].get(iso)}
    return fed, mac


QUAD_OF = {("+", "-"): "I", ("+", "+"): "II", ("-", "-"): "III", ("-", "+"): "IV"}


def classify(iso: str, W: int, th_fed: float, th_mac: float,
             validator: str) -> tuple[str, dict[str, Any]]:
    fed_p, mac_p = state_parts(iso, W)
    sf, share_f = axis(fed_p, W_FED, W_FED_FULL)
    sm, share_m = axis(mac_p, W_MACRO, W_MACRO_FULL)
    info = {"score_fed": sf, "score_macro": sm,
            "share_fed": share_f, "share_macro": share_m, "raw": None,
            "shape": None}
    if sf is None or sm is None:
        return "ANOMALY", info
    if abs(sf) < th_fed or abs(sm) < th_mac:
        info["raw"] = "CENTER"
        return "CENTER", info
    q = QUAD_OF[("+" if sf > 0 else "-", "+" if sm > 0 else "-")]
    info["raw"] = q
    if validator == "off":
        return q, info
    sh = shape_vote(iso) if validator == "vote" else SHAPE[W].get(iso)
    info["shape"] = sh
    if sh is None or sh in ("PARALLEL", "NOAGREE") or sh != q:
        return "CENTER", info
    return q, info


def build_states(W: int, th_fed: float, th_mac: float, validator: str,
                 dates: Sequence[str]) -> dict[str, tuple[str, dict[str, Any]]]:
    return {g: classify(g, W, th_fed, th_mac, validator) for g in dates}


# =========================================================================== #
# 6. Kalibrovka porogov theta
# =========================================================================== #

head("6. Kalibrovka porogov theta (HYPOTHESIS sec.5)")

CALIB = [g for g in GRID if g <= CALIB_END]
say("Kalibrovochnyy otrezok: %s .. %s, %d torgovyh dney"
    % (CALIB[0], CALIB[-1], len(CALIB)))


def spells(dates: Sequence[str], states: Sequence[str]
           ) -> list[tuple[str, int]]:
    """Nepreryvnye otrezki odnogo sostoyaniya: (sostoyanie, dlina v dnyah)."""
    starts: list[tuple[str, str]] = []
    prev = None
    for d, st in zip(dates, states):
        if st != prev:
            starts.append((d, st))
            prev = st
    tail = s2(d2(dates[-1]) + timedelta(days=1))
    out = []
    for i, (d, st) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else tail
        out.append((st, (d2(end) - d2(d)).days))
    return out


def spell_days(dates: Sequence[str], states: Sequence[str]) -> float:
    """Srednyaya dlitel'nost' po VSEM sostoyaniyam, vklyuchaya Centr.

    Eto ISPOLNENNOE prochtenie trebovaniya B (HYPOTHESIS sec.5: "v odnom
    SOSTOYANII"). Bukva speki sec.1.4.7 govorit "v odnom KVADRANTE" --
    ona schitaetsya otdel'no, spell_days_quad, i ne vypolnima ni pri kakom q.
    """
    lens = [n for _, n in spells(dates, states)]
    return sum(lens) / len(lens) if lens else 0.0


def spell_days_quad(dates: Sequence[str], states: Sequence[str]) -> float:
    """Srednyaya dlitel'nost' prebyvaniya v odnom KVADRANTE (bukva sec.1.4.7)."""
    lens = [n for st, n in spells(dates, states)
            if st not in ("CENTER", "ANOMALY")]
    return sum(lens) / len(lens) if lens else 0.0


def calibrate(W: int, validator: str, force_q: float | None = None
              ) -> dict[str, Any]:
    scores_f, scores_m = [], []
    for g in CALIB:
        fed_p, mac_p = state_parts(g, W)
        sf, _ = axis(fed_p, W_FED, W_FED_FULL)
        sm, _ = axis(mac_p, W_MACRO, W_MACRO_FULL)
        if sf is not None:
            scores_f.append(abs(sf))
        if sm is not None:
            scores_m.append(abs(sm))
    rows = []
    chosen = None
    for q in Q_GRID:
        tf, tm = quantile(scores_f, q), quantile(scores_m, q)
        st = [classify(g, W, tf, tm, validator)[0] for g in CALIB]
        ms = spell_days(CALIB, st)
        centre = sum(1 for x in st if x == "CENTER") / len(st)
        rows.append({"q": q, "theta_fed": tf, "theta_macro": tm,
                     "mean_spell_days": ms,
                     "mean_spell_days_quad": spell_days_quad(CALIB, st),
                     "center_share": centre})
        if force_q is None and chosen is None and ms >= MIN_SPELL_DAYS:
            chosen = rows[-1]
        if force_q is not None and abs(q - force_q) < 1e-9:
            chosen = dict(rows[-1], note="q zadan yavno (trebovanie A rovno)")
    if chosen is None:
        chosen = dict(rows[-1],
                      note="ni odin q iz setki ne dal B; vzyat maksimal'nyy")
    # Granica sverhu: skol'ko vremeni instrument sidit v Centre pri theta = 0,
    # to est' kogda porogi ne gasyat nichego i rabotaet odin predohranitel'.
    st0 = [classify(g, W, 0.0, 0.0, validator)[0] for g in CALIB]
    zero = sum(1 for x in st0 if x == "CENTER") / len(st0)
    return {"grid": rows, "chosen": chosen, "center_share_at_theta0": zero,
            "n_abs_fed": len(scores_f), "n_abs_macro": len(scores_m)}


CONFIGS: dict[str, tuple[int, str, float | None]] = {
    "P10": (10, "single", None), "P05": (5, "single", None),
    "P30": (30, "single", None), "VOTE": (10, "vote", None),
    "NOVAL": (10, "off", None),
    # Chteniya POSLE raschyota (sec.11 zapis' 3): trebovanie A rovno.
    "A20": (10, "single", 0.20), "A20NOVAL": (10, "off", 0.20),
}
POSTHOC = ("A20", "A20NOVAL")

THETA: dict[str, dict[str, Any]] = {}
for name, (W, val, fq) in CONFIGS.items():
    THETA[name] = calibrate(W, val, fq)
    ch = THETA[name]["chosen"]
    say("  %-8s okno=%2d valid=%-6s -> q=%.2f  th_fed=%.4f th_macro=%.4f"
        "  spell=%.1f dn.  Centr=%.1f%%  (Centr pri theta=0: %.1f%%)%s"
        % (name, W, val, ch["q"], ch["theta_fed"], ch["theta_macro"],
           ch["mean_spell_days"], 100 * ch["center_share"],
           100 * THETA[name]["center_share_at_theta0"],
           "  [POSLE RASCHYOTA]" if name in POSTHOC else ""))

sub("6.1 Setka q dlya osnovnoy konfiguracii P10")
say("  %5s %11s %13s %14s %12s" % ("q", "theta_fed", "theta_macro",
                                   "spell, dney", "Centr, %"))
for r in THETA["P10"]["grid"][:11]:
    say("  %5.2f %11.4f %13.4f %14.1f %11.1f"
        % (r["q"], r["theta_fed"], r["theta_macro"], r["mean_spell_days"],
           100 * r["center_share"]))
RESULT["theta"] = {k: {"chosen": v["chosen"], "grid": v["grid"]}
                   for k, v in THETA.items()}

_a = THETA["P10"]["grid"][0]
say("")
say("  Trebovanie A (q=0.20 rovno): Centr = %.1f%% vremeni pri obeshchannyh 20%%"
    % (100 * _a["center_share"]))
say("  -> vnutrennee protivorechie sec.1.4.7 speki, HYPOTHESIS sec.5.1")

sub("6.2 Trebovanie B PO BUKVE speki: 'v odnom KVADRANTE ne men'she mesyaca'")
say("  Ispolneno bylo pereopredelenie (HYPOTHESIS sec.5: 'v odnom SOSTOYANII',")
say("  to est' s Centrom). Nizhe -- bukva sec.1.4.7 na RASSHIRENNOY setke q,")
say("  vplot' do 0.98: est' li u B hot' odin dopustimyy vyhod.")
WIDE_Q = [round(0.20 + 0.02 * i, 2) for i in range(40)]      # 0.20 .. 0.98
_sf_calib = [abs(v) for v in
             (axis(state_parts(g, 10)[0], W_FED, W_FED_FULL)[0] for g in CALIB)
             if v is not None]
_sm_calib = [abs(v) for v in
             (axis(state_parts(g, 10)[1], W_MACRO, W_MACRO_FULL)[0]
              for g in CALIB) if v is not None]
B_LETTER: list[dict[str, Any]] = []
for _q in WIDE_Q:
    _tf, _tm = quantile(_sf_calib, _q), quantile(_sm_calib, _q)
    for _val in ("single", "off"):
        _st = [classify(g, 10, _tf, _tm, _val)[0] for g in CALIB]
        B_LETTER.append({"q": _q, "validator": _val,
                         "spell_quad": spell_days_quad(CALIB, _st),
                         "spell_all": spell_days(CALIB, _st),
                         "n_quad_spells": sum(
                             1 for st, _ in spells(CALIB, _st)
                             if st not in ("CENTER", "ANOMALY"))})
_best_on = max((r for r in B_LETTER if r["validator"] == "single"),
               key=lambda r: r["spell_quad"])
_best_off = max((r for r in B_LETTER if r["validator"] == "off"),
                key=lambda r: r["spell_quad"])
_q020 = [r for r in B_LETTER if r["q"] == 0.20 and r["validator"] == "single"][0]
_qch = [r for r in B_LETTER
        if abs(r["q"] - THETA["P10"]["chosen"]["q"]) < 1e-9
        and r["validator"] == "single"]
say("  q=0.20:            kvadrantnyy spell %.3f dn. (vsyo sostoyaniya %.1f)"
    % (_q020["spell_quad"], _q020["spell_all"]))
if _qch:
    say("  q=%.2f (vybrannyy): kvadrantnyy spell %.3f dn. (vsyo sostoyaniya %.1f)"
        % (_qch[0]["q"], _qch[0]["spell_quad"], _qch[0]["spell_all"]))
say("  MAKSIMUM po setke 0.20..0.98 s predohranitelem:  %.3f dn. pri q=%.2f"
    % (_best_on["spell_quad"], _best_on["q"]))
say("  MAKSIMUM po setke 0.20..0.98 BEZ predohranitelya: %.3f dn. pri q=%.2f"
    % (_best_off["spell_quad"], _best_off["q"]))
say("  trebuetsya %d dn. -> trebovanie B po bukve speki dostizhimo: %s"
    % (MIN_SPELL_DAYS,
       "DA" if max(_best_on["spell_quad"], _best_off["spell_quad"])
       >= MIN_SPELL_DAYS else "NET"))
RESULT["B_letter"] = {
    "grid": B_LETTER,
    "spell_quad_at_q020": _q020["spell_quad"],
    "spell_quad_at_chosen": _qch[0]["spell_quad"] if _qch else None,
    "best_with_validator": {"q": _best_on["q"], "spell": _best_on["spell_quad"]},
    "best_without_validator": {"q": _best_off["q"],
                               "spell": _best_off["spell_quad"]},
    "required": MIN_SPELL_DAYS,
    "B_reachable_at_any_q": max(_best_on["spell_quad"],
                                _best_off["spell_quad"]) >= MIN_SPELL_DAYS,
}


# =========================================================================== #
# 7. Sostoyaniya
# =========================================================================== #

head("7. Sostoyaniya po mesyacam")

STATES: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {}
for name, (W, val, _fq) in CONFIGS.items():
    ch = THETA[name]["chosen"]
    STATES[name] = build_states(W, ch["theta_fed"], ch["theta_macro"], val,
                                [MONTH_END[m] for m in MONTHS])


def state_month(cfg: str, m: str) -> tuple[str, dict[str, Any]]:
    return STATES[cfg][MONTH_END[m]]


def distribution(cfg: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in MONTHS:
        st = state_month(cfg, m)[0]
        out[st] = out.get(st, 0) + 1
    return out


for name in CONFIGS:
    dist = distribution(name)
    tot = sum(dist.values())
    say("  %-6s %s" % (name, "  ".join(
        "%s=%d(%.1f%%)" % (k, v, 100 * v / tot)
        for k, v in sorted(dist.items()))))
RESULT["state_distribution"] = {k: distribution(k) for k in CONFIGS}

sub("7.0 Chto imenno gasit sostoyanie: porogi ili predohranitel'")
_raw_cnt: dict[str, int] = {}
_killed = 0
for m in MONTHS:
    st, info = state_month("P10", m)
    r = info["raw"] or "ANOMALY"
    _raw_cnt[r] = _raw_cnt.get(r, 0) + 1
    if r not in ("CENTER", "ANOMALY") and st == "CENTER":
        _killed += 1
_raw_quad = sum(v for k, v in _raw_cnt.items() if k not in ("CENTER", "ANOMALY"))
say("  do predohranitelya: %s" % dict(sorted(_raw_cnt.items())))
say("  kvadrant nazvan porogami v %d mesyacah iz %d (%.1f%%)"
    % (_raw_quad, len(MONTHS), 100 * _raw_quad / len(MONTHS)))
say("  iz nih predohranitel' formoy krivoy pogasil %d (%.1f%% ot nazvannyh)"
    % (_killed, 100 * _killed / _raw_quad if _raw_quad else 0.0))
_par = {W: sum(1 for m in MONTHS if SHAPE[W].get(MONTH_END[m]) == "PARALLEL")
        for W in WINDOWS}
say("  mesyacev 'parallel'nyy sdvig' (|d spred| < 5 b.p.): %s iz %d"
    % (_par, len(MONTHS)))
RESULT["validator_effect"] = {"raw_state_counts": _raw_cnt,
                              "quadrant_named_by_thresholds": _raw_quad,
                              "killed_by_shape": _killed,
                              "parallel_months": _par}

sub("7.1 Dnevnaya dolya vremeni (osnovnaya konfiguraciya P10)")
_daily_states = build_states(10, THETA["P10"]["chosen"]["theta_fed"],
                             THETA["P10"]["chosen"]["theta_macro"], "single",
                             GRID)
_dd: dict[str, int] = {}
for g in GRID:
    st = _daily_states[g][0]
    _dd[st] = _dd.get(st, 0) + 1
say("  " + "  ".join("%s=%.1f%%" % (k, 100 * v / len(GRID))
                     for k, v in sorted(_dd.items())))
say("  srednyaya dlitel'nost' sostoyaniya na vsyom okne: %.1f kalendarnyh dney"
    % spell_days(GRID, [_daily_states[g][0] for g in GRID]))
RESULT["daily_time_share"] = {k: v / len(GRID) for k, v in _dd.items()}
RESULT["mean_spell_days_full"] = spell_days(
    GRID, [_daily_states[g][0] for g in GRID])

sub("7.2 Dolya dostupnogo vesa po kazhdomu otchyotnomu mesyacu")
_share_rows = []
for m in MONTHS:
    _, info = state_month("P10", m)
    _share_rows.append((m, info["share_fed"], info["share_macro"]))
_uf = sorted({round(r[1], 4) for r in _share_rows})
_um = sorted({round(r[2], 4) for r in _share_rows})
say("  razlichnyh znacheniy doli FED:   %s" % _uf)
say("  razlichnyh znacheniy doli MACRO: %s" % _um)
_bad = [r for r in _share_rows if r[1] < CUTOFF or r[2] < CUTOFF]
say("  mesyacev nizhe otsechki %.2f: %d" % (CUTOFF, len(_bad)))
if _bad:
    for r in _bad[:24]:
        say("    %s fed=%.4f macro=%.4f" % r)
say("  pervye i poslednie tri mesyaca:")
for r in _share_rows[:3] + _share_rows[-3:]:
    say("    %s fed=%.4f macro=%.4f" % r)
RESULT["weight_share_by_month"] = [
    {"month": m, "fed": f, "macro": mm} for m, f, mm in _share_rows]


# =========================================================================== #
# 8. Pary
# =========================================================================== #

head("8. Pary (HYPOTHESIS sec.6)")

PAIRS: list[dict[str, Any]] = [
    {"key": "SIZE", "long": ["SPY"], "short": ["IWM"],
     "signs": {"I": +1, "II": -1, "III": +1, "IV": -1, "CENTER": +1},
     "overlap": ""},
    {"key": "STYLE", "long": ["QQQ"], "short": ["IWM"],
     "signs": {"I": +1, "IV": -1, "CENTER": -1}, "overlap": ""},
    {"key": "GEO", "long": ["EFA"], "short": ["EEM"],
     "signs": {"I": +1, "II": -1, "III": +1, "IV": -1, "CENTER": +1},
     "overlap": ""},
    {"key": "TECHMAT", "long": ["XLK"], "short": ["XLB"],
     "signs": {"I": +1, "IV": -1}, "overlap": ""},
    {"key": "DISCSTAP", "long": ["XLY"], "short": ["XLP"],
     "signs": {"II": +1, "III": -1}, "overlap": ""},
    {"key": "CYCNON", "long": ["XLY", "XLI", "XLB", "XLE"],
     "short": ["XLP", "XLV", "XLU"],
     "signs": {"II": +1, "III": -1, "IV": +1}, "overlap": ""},
    {"key": "MATFIN", "long": ["XLB", "XLF"], "short": ["SPY"],
     "signs": {"IV": +1}, "overlap": ""},
    {"key": "DUR", "long": ["TLT"], "short": ["SHY"],
     "signs": {"I": +1, "III": -1, "IV": -1}, "overlap": ""},
    {"key": "CRED", "long": ["LQD"], "short": ["IEF"],
     "signs": {"II": +1, "III": -1, "IV": -1}, "overlap": ""},
    {"key": "GOLD", "long": ["GC=F"], "short": [],
     "signs": {"I": +1, "II": +1, "III": -1, "IV": -1},
     "overlap": "vhodit v rynochnye proksi osi MACRO (12.5 % dostupnogo vesa)"},
    {"key": "COMM", "long": ["^SPGSCI"], "short": [],
     "signs": {"I": -1, "II": +1, "III": -1, "IV": +1},
     "overlap": "med' i neft' -- rynochnye proksi osi MACRO (12.5 %)"},
    {"key": "OIL", "long": ["CL=F"], "short": [],
     "signs": {"IV": +1},
     "overlap": "neft' -- chislitel' proksi CL/GC osi MACRO"},
    {"key": "USD", "long": ["DX-Y.NYB"], "short": [],
     "signs": {"II": -1, "III": +1},
     "overlap": "DXY -- vhod osi FED (15.4 % dostupnogo vesa)"},
    {"key": "VIX", "long": ["^VIX"], "short": [],
     "signs": {"II": -1, "III": +1}, "overlap": "ne torguemaya poziciya"},
]
PAIR_EXTRA = [
    {"key": "BETA", "long": ["SPHB"], "short": ["SPLV"],
     "signs": {"I": +1, "II": +1, "III": -1, "IV": -1},
     "overlap": "vne semeystva: istoriya s 2011-05 (plan sec.8.2)"},
]
assert len(PAIRS) == 14, "osnovnoe semeystvo obyazano byt' iz 14 par"

PRICE = {sym: Step(observed(RAW[sym])) for sym in YAHOO_IDS}


def basket_log(syms: Sequence[str], iso: str) -> float | None:
    """Ravnyy ves = srednee logarifmov cen (nepreryvnaya rebalansirovka)."""
    acc = 0.0
    for s in syms:
        v = PRICE[s].exact(iso)
        if v is None or v <= 0:
            return None
        acc += math.log(v)
    return acc / len(syms)


def pair_level(p: dict[str, Any], iso: str) -> float | None:
    a = basket_log(p["long"], iso)
    if a is None:
        return None
    if not p["short"]:
        return a
    b = basket_log(p["short"], iso)
    return None if b is None else a - b


def fwd(p: dict[str, Any], m: str, h: int) -> float | None:
    m2 = add_months(m, h)
    if m2 not in MONTH_END:
        return None
    a = pair_level(p, MONTH_END[m])
    b = pair_level(p, MONTH_END[m2])
    return None if a is None or b is None else b - a


for p in PAIRS + PAIR_EXTRA:
    lv = [pair_level(p, MONTH_END[m]) for m in MONTHS]
    ok = [i for i, v in enumerate(lv) if v is not None]
    say("  %-9s %-28s mesyacev s cenoy %3d, s %s"
        % (p["key"], "/".join(["+".join(p["long"]),
                               "+".join(p["short"]) or "cash"]),
           len(ok), MONTHS[ok[0]] if ok else "?"))


# =========================================================================== #
# 9. Popadaniya i testy
# =========================================================================== #

def hits(p: dict[str, Any], cfg: str, h: int, months: Sequence[str],
         state_fn: Callable[[str, str], str]) -> tuple[list[float], int, int]:
    """(spisok 0/1, chislo tochnyh nuley, chislo mesyacev bez predpisaniya)."""
    out: list[float] = []
    zeros = 0
    noprescr = 0
    for m in months:
        st = state_fn(cfg, m)
        want = p["signs"].get(st)
        if want is None:
            noprescr += 1
            continue
        r = fwd(p, m, h)
        if r is None:
            continue
        if r == 0.0:
            zeros += 1
            continue
        out.append(1.0 if sign(r) == want else 0.0)
    return out, zeros, noprescr


def hits_months(p: dict[str, Any], cfg: str, h: int, months: Sequence[str],
                state_fn: Callable[[str, str], str],
                only: str = "all") -> list[tuple[str, float]]:
    out = []
    for m in months:
        st = state_fn(cfg, m)
        if only == "quad" and st in ("CENTER", "ANOMALY"):
            continue
        if only == "center" and st != "CENTER":
            continue
        want = p["signs"].get(st)
        if want is None:
            continue
        r = fwd(p, m, h)
        if r is None or r == 0.0:
            continue
        out.append((m, 1.0 if sign(r) == want else 0.0))
    return out


def pool_accounting(cfg: str, h: int, months: Sequence[str],
                    state_fn: Callable[[str, str], str],
                    only: str = "all") -> dict[str, Any]:
    """Skol'ko par-mesyacev PREDPISANO i skol'ko doshlo do schyota.

    Bez etoy razbivki pul pechataet 'n nablyudeniy' i molchit o tom, chto
    chast' predpisannyh par-mesyacev vypala: u fyuchersa net kotirovki rovno
    v etot den', ili gorizont vyhodit za pravyy kray cen. Raznica malen'kaya
    i imenno poetomu nezametnaya.
    """
    prescribed = counted = 0
    dropped: list[tuple[str, str, str, str]] = []
    for p in PAIRS:
        for m in months:
            st = state_fn(cfg, m)
            if only == "quad" and st in ("CENTER", "ANOMALY"):
                continue
            if only == "center" and st != "CENTER":
                continue
            if p["signs"].get(st) is None:
                continue
            prescribed += 1
            r = fwd(p, m, h)
            if r is None:
                dropped.append((p["key"], m, st, "net ceny"))
            elif r == 0.0:
                dropped.append((p["key"], m, st, "tochnyy nul'"))
            else:
                counted += 1
    return {"prescribed": prescribed, "counted": counted,
            "dropped": len(dropped), "rows": dropped}


def test_series(vals: Sequence[float], h: int,
                rng: random.Random) -> dict[str, Any]:
    n = len(vals)
    blk = BLOCK[h]
    rate = sum(vals) / n if n else float("nan")
    row: dict[str, Any] = {"n": n, "rate": rate, "block": blk,
                           "degenerate": degenerate(n, blk)}
    if n == 0 or degenerate(n, blk):
        row.update({"p_raw": 1.0, "ci90": [float("nan")] * 2,
                    "p_below": float("nan")})
        return row
    draws = boot_mean(vals, blk, rng)
    row["p_raw"] = p_above(draws, NULL_RATE)
    row["p_below"] = p_below(draws, NULL_RATE)
    row["ci90"] = [quantile(draws, 0.05), quantile(draws, 0.95)]
    # kakaya dolya nuzhna byla by pri etom n, chtoby proyti pervyy shag Holma
    row["rate_needed"] = NULL_RATE + Z_HOLM1 * 0.5 / math.sqrt(
        n / (3.0 if h == 3 else 1.0))
    row["can_fire"] = (rate > HIT_THRESHOLD and rate >= row["rate_needed"])
    return row


def pooled(cfg: str, h: int, months: Sequence[str],
           state_fn: Callable[[str, str], str], rng: random.Random,
           pairs: Sequence[dict[str, Any]] = PAIRS,
           only: str = "all") -> dict[str, Any]:
    """Pul po vsem param, bootstrap klasterami po mesyacam."""
    by_month: dict[str, list[float]] = {}
    for p in pairs:
        for m, hit in hits_months(p, cfg, h, months, state_fn, only):
            by_month.setdefault(m, []).append(hit)
    ms = sorted(by_month)
    if not ms:
        return {"n_months": 0, "n_obs": 0, "rate": float("nan"),
                "p_raw": 1.0, "ci90": [float("nan")] * 2, "degenerate": True}
    flat = [x for m in ms for x in by_month[m]]
    rate = sum(flat) / len(flat)
    blk = BLOCK[h]
    row = {"n_months": len(ms), "n_obs": len(flat), "rate": rate, "block": blk,
           "degenerate": degenerate(len(ms), blk)}
    if row["degenerate"]:
        row.update({"p_raw": 1.0, "ci90": [float("nan")] * 2})
        return row
    draws = []
    n = len(ms)
    for _ in range(B_BOOT):
        idx = block_draw(n, blk, rng)
        acc, cnt = 0.0, 0
        for i in idx:
            vs = by_month[ms[i]]
            acc += sum(vs)
            cnt += len(vs)
        draws.append(acc / cnt)
    row["p_raw"] = p_above(draws, NULL_RATE)
    row["p_below"] = p_below(draws, NULL_RATE)
    row["ci90"] = [quantile(draws, 0.05), quantile(draws, 0.95)]
    return row


def st_main(cfg: str, m: str) -> str:
    return state_month(cfg, m)[0]


def run_branch(cfg: str, months: Sequence[str], state_fn, label: str,
               *, verbose: bool = True) -> dict[str, Any]:
    rng = random.Random(SEED)
    per: dict[str, dict[str, Any]] = {}
    raw_p: dict[str, float] = {}
    for p in PAIRS:
        per[p["key"]] = {}
        for h in HORIZONS:
            vals, zeros, nop = hits(p, cfg, h, months, state_fn)
            row = test_series(vals, h, rng)
            row["zeros"] = zeros
            row["months_without_prescription"] = nop
            per[p["key"]]["h%d" % h] = row
            raw_p["%s|h%d" % (p["key"], h)] = row["p_raw"]
    adj = holm(raw_p, FAMILY_F1)
    for k, v in adj.items():
        key, hh = k.split("|")
        per[key][hh]["p_holm"] = v

    pool = {}
    praw = {}
    for h in HORIZONS:
        pool["h%d" % h] = pooled(cfg, h, months, state_fn, rng)
        praw["h%d" % h] = pool["h%d" % h]["p_raw"]
    padj = holm(praw, FAMILY_F2)
    for h in HORIZONS:
        pool["h%d" % h]["p_holm"] = padj["h%d" % h]

    # Razlozhenie pula: on ne odnoroden. Predpisaniya Centra (SIZE, STYLE,
    # GEO -- sec.2.3 speki) est' u treh par i deystvuyut v podavlyayushchem
    # bol'shinstve mesyacev, predpisaniya kvadrantov -- u vseh chetyrnadcati,
    # no tol'ko v redkih. Bez razlozheniya pul izmeryaet ne to, chto kazhetsya.
    decomp = {}
    for grp in ("quad", "center"):
        for h in HORIZONS:
            decomp["%s_h%d" % (grp, h)] = pooled(cfg, h, months, state_fn, rng,
                                                 only=grp)

    extra = {}
    for p in PAIR_EXTRA:
        extra[p["key"]] = {}
        for h in HORIZONS:
            vals, zeros, nop = hits(p, cfg, h, months, state_fn)
            row = test_series(vals, h, rng)
            row["zeros"] = zeros
            extra[p["key"]]["h%d" % h] = row

    n_pass = sum(1 for p in PAIRS
                 if any(per[p["key"]]["h%d" % h]["rate"] > HIT_THRESHOLD
                        and per[p["key"]]["h%d" % h]["p_holm"] < 0.05
                        for h in HORIZONS))
    # Potolok C1 pri fakticheski poluchennyh vyborkah: para, u kotoroy
    # vyrozhdeny OBA gorizonta, poluchaet p = 1.0 po pravilu sec.7.2 pri
    # lyubom ishode dannyh i proyti C1 ne mozhet. Skol'ko par voobshche
    # sposobny -- eto potolok kriteriya "ne men'she 8 par iz 14".
    n_can = sum(1 for p in PAIRS
                if any(not per[p["key"]]["h%d" % h]["degenerate"]
                       for h in HORIZONS))
    acc = {}
    for grp in ("all", "quad", "center"):
        for h in HORIZONS:
            acc["%s_h%d" % (grp, h)] = pool_accounting(cfg, h, months,
                                                       state_fn, grp)
    out = {"label": label, "cfg": cfg, "per_pair": per, "pooled": pool,
           "pooled_decomp": decomp, "extra": extra, "pairs_passed": n_pass,
           "pairs_can_pass": n_can, "accounting": acc,
           "n_months": len(months)}
    if verbose:
        print_branch(out)
    return out


def print_branch(res: dict[str, Any]) -> None:
    say("")
    say("  vetv': %s  (konfiguraciya %s, mesyacev %d)"
        % (res["label"], res["cfg"], res["n_months"]))
    say("  %-9s %26s | %26s | %s"
        % ("para", "gorizont 1 mes.", "gorizont 3 mes.", "peresechenie"))
    say("  %-9s %5s %6s %8s %6s | %5s %6s %8s %6s |"
        % ("", "n", "dolya", "p_Holm", "nado", "n", "dolya", "p_Holm", "nado"))
    for p in PAIRS:
        r1 = res["per_pair"][p["key"]]["h1"]
        r3 = res["per_pair"][p["key"]]["h3"]
        say("  %-9s %5d %6.3f %8.4f %6s | %5d %6.3f %8.4f %6s | %s"
            % (p["key"], r1["n"], r1["rate"], r1["p_holm"],
               ("%.3f" % r1["rate_needed"]) if "rate_needed" in r1 else "vyrozh",
               r3["n"], r3["rate"], r3["p_holm"],
               ("%.3f" % r3["rate_needed"]) if "rate_needed" in r3 else "vyrozh",
               "peresech." if p["overlap"] else ""))
    for p in PAIR_EXTRA:
        r1 = res["extra"][p["key"]]["h1"]
        r3 = res["extra"][p["key"]]["h3"]
        say("  %-9s %5d %6.3f %8s %5s | %5d %6.3f %8s %5s | vne semeystva"
            % (p["key"], r1["n"], r1["rate"], "-", "-",
               r3["n"], r3["rate"], "-", "-"))
    for h in HORIZONS:
        pl = res["pooled"]["h%d" % h]
        say("  PUL h=%d: mesyacev %d, nablyudeniy %d, dolya %.4f, "
            "90%% [%.4f .. %.4f], p_syroy %.4f, p_Holm %.4f"
            % (h, pl["n_months"], pl["n_obs"], pl["rate"],
               pl["ci90"][0], pl["ci90"][1], pl["p_raw"], pl["p_holm"]))
    for grp, nm in (("quad", "tol'ko KVADRANTY"), ("center", "tol'ko CENTR")):
        for h in HORIZONS:
            pl = res["pooled_decomp"]["%s_h%d" % (grp, h)]
            say("    razlozhenie %s h=%d: mesyacev %d, nablyudeniy %d, "
                "dolya %.4f, 90%% [%.4f .. %.4f], p %.4f, vyrozhden=%s"
                % (nm, h, pl["n_months"], pl["n_obs"], pl["rate"],
                   pl["ci90"][0], pl["ci90"][1], pl["p_raw"],
                   pl.get("degenerate")))
    for grp in ("all", "quad", "center"):
        for h in HORIZONS:
            ac = res["accounting"]["%s_h%d" % (grp, h)]
            say("    uchyot %-6s h=%d: predpisano %4d, poschitano %4d, "
                "vypalo %d%s"
                % (grp, h, ac["prescribed"], ac["counted"], ac["dropped"],
                   ("  [" + "; ".join("%s %s %s" % (k, m, why)
                                      for k, m, _s, why in ac["rows"][:6])
                    + ("; ..." if len(ac["rows"]) > 6 else "") + "]")
                   if ac["rows"] else ""))
    say("  par proshlo C1: %d iz 14" % res["pairs_passed"])
    say("  par, sposobnyh proyti C1 (vyborka ne vyrozhdena hotya by na odnom "
        "gorizonte): %d iz 14 pri trebuemyh 8" % res["pairs_can_pass"])


head("9. Osnovnaya vetv': P10, peresmotrennye dannye, kovid VKLYUCHEN")
MAIN = run_branch("P10", MONTHS, st_main, "OSNOVNAYA (kovid vklyuchyon)")
RESULT["main"] = MAIN

head("10. Vtoraya vetv' kovida: kovid ISKLYUCHYON -- schitaetsya POLNOST'YU")
MONTHS_NOCOVID = [m for m in MONTHS if not (COVID_START <= m <= COVID_END)]
say("mesyacev bez kovida: %d (ubrano %d)"
    % (len(MONTHS_NOCOVID), len(MONTHS) - len(MONTHS_NOCOVID)))
NOCOVID = run_branch("P10", MONTHS_NOCOVID, st_main, "KOVID ISKLYUCHYON")
RESULT["nocovid"] = NOCOVID


# =========================================================================== #
# 11. Ustoychivost'
# =========================================================================== #

head("11. Ustoychivost' (HYPOTHESIS sec.9)")

sub("11.1 Konfiguracii: tri okna, golosovanie, bez validatora")
ROBUST: dict[str, Any] = {}
for cfg in ("P05", "P30", "VOTE", "NOVAL"):
    ROBUST[cfg] = run_branch(cfg, MONTHS, st_main, "konfiguraciya " + cfg)
RESULT["robust_cfg"] = ROBUST

sub("11.1-bis Dva chteniya theta POSLE raschyota (sec.11 zapis' 3)")
say("  Trebovaniya A i B sec.1.4.7 nesovmestimy (sm. sec.6 i sec.13-bis).")
say("  Pred-registrirovannyy vybor -- B (konfiguraciya P10, vyshe).")
say("  Zdes' -- vtoroe chtenie: trebovanie A rovno, q=0.20. Verdikt po nemu")
say("  NE vynositsya; ono nuzhno, chtoby kvadrantnye predpisaniya voobshche")
say("  poluchili vyborku, i chtoby vyvod ne opiralsya na odnu tol'ko nehvatku.")
POSTHOC_RES: dict[str, Any] = {}
for cfg in POSTHOC:
    dist = distribution(cfg)
    say("  %-9s sostoyaniya: %s" % (cfg, dict(sorted(dist.items()))))
    POSTHOC_RES[cfg] = run_branch(cfg, MONTHS, st_main,
                                  "POSLE RASCHYOTA " + cfg)
RESULT["posthoc_cfg"] = POSTHOC_RES

sub("11.2 Dva razbieniya vyborki")
SPLITS = {
    "half_early": [m for m in MONTHS if m <= "2015-03"],
    "half_late": [m for m in MONTHS if m > "2015-03"],
    "pre_2009_12": [m for m in MONTHS if m <= Z25_SPLIT],
    "post_2009_12": [m for m in MONTHS if m > Z25_SPLIT],
    "oos_2015": [m for m in MONTHS if m >= OOS_START[:7]],
    "calib_only": [m for m in MONTHS if m <= CALIB_END[:7]],
}
SPLIT_RES: dict[str, Any] = {}
rng_s = random.Random(SEED)
for k, ms in SPLITS.items():
    row = {}
    for h in HORIZONS:
        row["h%d" % h] = pooled("P10", h, ms, st_main, rng_s)
    SPLIT_RES[k] = row
    say("  %-13s mesyacev %3d | h1 dolya %.4f (n_m %3d, p %.4f) | "
        "h3 dolya %.4f (n_m %3d, p %.4f)"
        % (k, len(ms), row["h1"]["rate"], row["h1"]["n_months"],
           row["h1"]["p_raw"], row["h3"]["rate"], row["h3"]["n_months"],
           row["h3"]["p_raw"]))
RESULT["splits"] = SPLIT_RES

sub("11.3 Razrez: recessii protiv rasshireniy (HYPOTHESIS sec.7.4)")
REC_SET = set(REC_MONTHS)
CUTS = {"recession": [m for m in MONTHS if m in REC_SET],
        "expansion": [m for m in MONTHS if m not in REC_SET]}
CUT_RES: dict[str, Any] = {}
rng_c = random.Random(SEED)
for k, ms in CUTS.items():
    row = {}
    for h in HORIZONS:
        row["h%d" % h] = pooled("P10", h, ms, st_main, rng_c)
    CUT_RES[k] = row
    say("  %-10s mesyacev %3d | h1 dolya %.4f n_m=%3d 90%% [%.3f .. %.3f] "
        "vyrozhden=%s | h3 dolya %.4f n_m=%3d"
        % (k, len(ms), row["h1"]["rate"], row["h1"]["n_months"],
           row["h1"]["ci90"][0], row["h1"]["ci90"][1],
           row["h1"]["degenerate"], row["h3"]["rate"], row["h3"]["n_months"]))
say("  Recessionnaya polovina ob'yavlena OPISATEL'NOY do raschyota:")
say("  %d recessionnyh mesyacev < %d (predohranitel' n/L>=8 pri L=3),"
    % (len(REC_MONTHS), BLOCK[1] * DEGEN_RATIO))
say("  znachimost' po ney nedostizhima ni pri kakom ishode.")
RESULT["recession_cut"] = CUT_RES


# =========================================================================== #
# 12. Vetv' VINTAGE-PARTIAL
# =========================================================================== #

head("12. Vetv' VINTAGE-PARTIAL (HYPOTHESIS sec.2.5)")

VINT_SPEC = {"PERMIT": "PERMIT", "IC4WSA": "IC4WSA",
             "NOF": "NOFDFSA066MSFRBPHI"}
VINT_DATES: dict[str, list[str]] = {}
if not NO_VINTAGE:
    for k, sid in VINT_SPEC.items():
        VINT_DATES[k] = S.alfred_vintages(sid)
        say("  %-8s vintazhey %4d, %s .. %s"
            % (k, len(VINT_DATES[k]), VINT_DATES[k][0], VINT_DATES[k][-1]))
say("  BEZ vintazhey voobshche: NAHB (0.13), Richmond i Kansas-City "
    "(paneli kompozita) --")
say("  os' MACRO nevosproizvodima v real'nom vremeni ni v odin mesyac okna.")


def last_vintage(k: str, iso: str) -> str | None:
    vs = VINT_DATES.get(k) or []
    i = bisect.bisect_right(vs, iso) - 1
    return vs[i] if i >= 0 else None


VINT_STATE: dict[str, str] = {}
VINT_DIAG: dict[str, Any] = {"months_with_permit": 0, "months_with_claims": 0,
                             "months_with_nof": 0, "changed": 0,
                             "fetch_failures": []}


def vintage_series(sid: str, vd: str, back_days: int) -> Any | None:
    """Vintazh ili None. Otkaz zapisyvaetsya, a ne gasitsya molcha."""
    for attempt in range(3):
        try:
            return S.alfred(sid, vd,
                            start=s2(d2(vd) - timedelta(days=back_days)))
        except Exception as exc:                    # noqa: BLE001
            if attempt == 2:
                VINT_DIAG["fetch_failures"].append(
                    "%s@%s: %s" % (sid, vd, type(exc).__name__))
                return None
            time.sleep(1.5)
    return None

if not NO_VINTAGE:
    th = THETA["P10"]["chosen"]
    t0 = time.time()
    for i, m in enumerate(MONTHS):
        g = MONTH_END[m]
        parts_fed, parts_mac = state_parts(g, 10)
        # PERMIT
        vd = last_vintage("PERMIT", g)
        s = vintage_series("PERMIT", vd, 2200) if vd else None
        if s is not None:
            vals = {mkey(d): v for d, v in observed(s)}
            cs = monthly_speed(vals, 3, log=True)
            parts_mac["permit"] = to_step_monthly(cs, *PUB["PERMIT"]).at(g)
            VINT_DIAG["months_with_permit"] += 1
        vd = last_vintage("IC4WSA", g)
        s = vintage_series("IC4WSA", vd, 1500) if vd else None
        if s is not None:
            cs = weekly_speed(observed(s), 13, flip=True)
            parts_mac["claims"] = Step(cs.items()).at(g)   # lag: sm. sec.4.1
            VINT_DIAG["months_with_claims"] += 1
        vd = last_vintage("NOF", g)
        s = vintage_series("NOFDFSA066MSFRBPHI", vd, 1500) if vd else None
        if s is not None:
            vals = {mkey(d): v for d, v in observed(s)}
            cs = monthly_level(vals, 0.0)
            parts_mac["nof"] = to_step_monthly(cs, *PUB["NOF"]).at(g)
            VINT_DIAG["months_with_nof"] += 1
        sf, _ = axis(parts_fed, W_FED, W_FED_FULL)
        sm, _ = axis(parts_mac, W_MACRO, W_MACRO_FULL)
        if sf is None or sm is None:
            VINT_STATE[m] = "ANOMALY"
        elif abs(sf) < th["theta_fed"] or abs(sm) < th["theta_macro"]:
            VINT_STATE[m] = "CENTER"
        else:
            q = QUAD_OF[("+" if sf > 0 else "-", "+" if sm > 0 else "-")]
            sh = SHAPE[10].get(g)
            VINT_STATE[m] = q if (sh is not None and sh == q) else "CENTER"
        if VINT_STATE[m] != st_main("P10", m):
            VINT_DIAG["changed"] += 1
        if i % 40 == 0:
            say("    ... %s (%d/%d, %.0fs)" % (m, i + 1, len(MONTHS),
                                               time.time() - t0))
    say("  mesyacev s vintazhem PERMIT %d, IC4WSA %d, NOF %d"
        % (VINT_DIAG["months_with_permit"], VINT_DIAG["months_with_claims"],
           VINT_DIAG["months_with_nof"]))
    say("  sostoyanie izmenilos' v %d mesyacah iz %d"
        % (VINT_DIAG["changed"], len(MONTHS)))

    def st_vint(cfg: str, m: str) -> str:
        return VINT_STATE[m]

    VINT = run_branch("P10", MONTHS, st_vint, "VINTAGE-PARTIAL")
    RESULT["vintage"] = VINT
    RESULT["vintage_diag"] = VINT_DIAG
    RESULT["vintage_dates_span"] = {
        k: {"n": len(v), "first": v[0], "last": v[-1]}
        for k, v in VINT_DATES.items()}
else:
    VINT = None
    say("  propushcheno po --no-vintage")


# =========================================================================== #
# 13. Kriterii i verdikt
# =========================================================================== #

head("13. Kriterii (HYPOTHESIS sec.7.5)")

C1 = MAIN["pairs_passed"] >= 8
C2 = all(MAIN["pooled"]["h%d" % h]["rate"] > HIT_THRESHOLD
         and MAIN["pooled"]["h%d" % h]["p_holm"] < 0.05 for h in HORIZONS)
C3 = all(SPLIT_RES["oos_2015"]["h%d" % h]["rate"] > HIT_THRESHOLD
         for h in HORIZONS)
_c4_cells = []
for cfg in ("P05", "P30"):
    for h in HORIZONS:
        pl = ROBUST[cfg]["pooled"]["h%d" % h]
        _c4_cells.append(("cfg %s h%d" % (cfg, h),
                          pl["rate"] > HIT_THRESHOLD and pl["p_holm"] < 0.05))
for k in ("half_early", "half_late", "pre_2009_12", "post_2009_12"):
    pl = SPLIT_RES[k]["h1"]
    _c4_cells.append(("split %s h1" % k, pl["rate"] > HIT_THRESHOLD))
C4_fail = sum(1 for _, ok in _c4_cells if not ok)
C4 = C4_fail <= 1
_exp = CUT_RES["expansion"]["h1"]
C5 = _exp["rate"] > HIT_THRESHOLD and _exp["p_raw"] < 0.05

for nm, val, note in (
        ("C1 (>=8 par iz 14)", C1,
         "proshlo %d; potolok pri fakticheskih vyborkah %d"
         % (MAIN["pairs_passed"], MAIN["pairs_can_pass"])),
        ("C2 (pul >0.55, Holm<0.05, oba gorizonta)", C2,
         "h1 %.4f p=%.4f; h3 %.4f p=%.4f"
         % (MAIN["pooled"]["h1"]["rate"], MAIN["pooled"]["h1"]["p_holm"],
            MAIN["pooled"]["h3"]["rate"], MAIN["pooled"]["h3"]["p_holm"])),
        ("C3 (vne vyborki 2015+)", C3,
         "h1 %.4f; h3 %.4f" % (SPLIT_RES["oos_2015"]["h1"]["rate"],
                               SPLIT_RES["oos_2015"]["h3"]["rate"])),
        ("C4 (ustoychivost')", C4, "narusheno yacheek %d iz %d"
         % (C4_fail, len(_c4_cells))),
        ("C5 (vne recessiy)", C5,
         "dolya %.4f, p %.4f, n_m %d" % (_exp["rate"], _exp["p_raw"],
                                         _exp["n_months"]))):
    say("  %-42s %s   (%s)" % (nm, "VYPOLNEN" if val else "NE VYPOLNEN", note))

say("")
say("  yacheyki C4:")
for k, ok in _c4_cells:
    say("    %-22s %s" % (k, "ok" if ok else "NET"))

pool_le = all(MAIN["pooled"]["h%d" % h]["rate"] <= HIT_THRESHOLD
              for h in HORIZONS)
if C1 and C2 and C3 and C5 and C4:
    VERDICT = "PODTVERZHDENO"
elif pool_le and MAIN["pairs_passed"] < 3:
    VERDICT = "OPROVERGNUTO"
else:
    VERDICT = "NEOPREDELENO"

# znak oshibki: rabotaet li instrument naoborot
inverted = []
for h in HORIZONS:
    pl = MAIN["pooled"]["h%d" % h]
    if pl.get("p_below", 1.0) < 0.05:
        inverted.append("h%d (dolya %.4f, p_below %.4f)"
                        % (h, pl["rate"], pl["p_below"]))

head("VERDIKT: " + VERDICT)
say("  C1=%s C2=%s C3=%s C4=%s C5=%s" % (C1, C2, C3, C4, C5))
if inverted:
    say("  ZNAK OSHIBKI: dolya znachimo NIZHE 0.5 na %s" % "; ".join(inverted))
else:
    say("  dolya ni na odnom gorizonte ne nizhe 0.5 znachimo")

say("")
say("  Potolok C1 na fakticheskoy konfiguracii: predohranitel' vyrozhdeniya")
say("  (n/L>=8) prohodyat %d pary iz 14 hotya by na odnom gorizonte, a C1"
    % MAIN["pairs_can_pass"])
say("  trebuet vosem'. Znachit C1 ne mog srabotat' ni pri kakom ishode dannyh")
say("  -- ne potomu, chto pary ploho ugadyvayut, a potomu, chto instrument")
say("  nazval kvadrant v %d mesyacah iz %d." % (
    len(MONTHS) - RESULT["state_distribution"]["P10"].get("CENTER", 0)
    - RESULT["state_distribution"]["P10"].get("ANOMALY", 0), len(MONTHS)))

RESULT["criteria"] = {"C1": C1, "C2": C2, "C3": C3, "C4": C4, "C5": C5,
                      "C4_cells": _c4_cells, "C4_failed": C4_fail,
                      "pairs_passed": MAIN["pairs_passed"],
                      "pairs_can_pass": MAIN["pairs_can_pass"],
                      "C1_required": 8,
                      "C1_reachable": MAIN["pairs_can_pass"] >= 8,
                      "inverted": inverted}
RESULT["verdict"] = VERDICT

head("13-bis. Sovmestimy li trebovaniya A i B sec.1.4.7")
_g = THETA["P10"]["grid"]
_a20 = _g[0]
_chosen = THETA["P10"]["chosen"]
say("  A rovno (q=0.20):  Centr %.1f%% pri obeshchannyh 20%%; spell %.1f dn. "
    "pri trebuemyh %d" % (100 * _a20["center_share"],
                          _a20["mean_spell_days"], MIN_SPELL_DAYS))
say("  naimen'shiy q, udovletvoryayushchiy B: %.2f -> Centr %.1f%%"
    % (_chosen["q"], 100 * _chosen["center_share"]))
say("  Centr pri theta = 0 (porogi ne gasyat nichego, rabotaet odin")
say("  predohranitel' formoy krivoy): %.1f%%"
    % (100 * THETA["P10"]["center_share_at_theta0"]))
_A_reachable = THETA["P10"]["center_share_at_theta0"] <= 0.35
say("  -> dolya vremeni v Centre poryadka pyatoy chasti dostizhima pri kakom-")
say("     libo theta: %s" % ("DA" if _A_reachable else "NET"))

# Vtoraya prichina, vnutri odnogo abzaca sec.1.4.7 i BEZ vsyakih dannyh:
# "poryadka pyatoy chasti vremeni v Centre" i "theta = 20-y percentil' |score|
# po kazhdoy osi" nesovmestimy arifmeticheski. Osi kalibruyutsya nezavisimo,
# Centr -- eto ILI, znachit 1 - 0.8*0.8 = 0.36, a ne 0.20.
_PRED_INDEP = 1.0 - (1.0 - CENTER_TARGET) ** 2
_a20_noval = THETA["A20NOVAL"]["chosen"]["center_share"]
say("")
say("  Vtoraya prichina, bez dannyh: osi kalibruyutsya nezavisimo, Centr -- ILI,")
say("  znachit pri 20-m percentile na kazhduyu os' Centr = 1 - 0.8*0.8 = %.2f,"
    % _PRED_INDEP)
say("  a ne %.2f. Dva predlozheniya odnogo abzaca sec.1.4.7 protivorechat"
    % CENTER_TARGET)
say("  drug drugu do vsyakogo izmereniya.")
say("  Izmereno (porogi bez predohranitelya, q=0.20): Centr = %.4f protiv "
    "predskazannyh %.2f" % (_a20_noval, _PRED_INDEP))

RESULT["A_vs_B"] = {
    "center_share_at_q020": _a20["center_share"],
    "spell_at_q020": _a20["mean_spell_days"],
    "q_satisfying_B": _chosen["q"],
    "center_share_at_chosen": _chosen["center_share"],
    "center_share_at_theta0": THETA["P10"]["center_share_at_theta0"],
    "A_reachable_at_any_theta": _A_reachable,
    "center_target": CENTER_TARGET,
    "predicted_center_independent_axes": _PRED_INDEP,
    "center_share_thresholds_only_q020": _a20_noval,
    "B_letter_reachable_at_any_q": RESULT["B_letter"]["B_reachable_at_any_q"],
    "B_letter_best_spell": max(
        RESULT["B_letter"]["best_with_validator"]["spell"],
        RESULT["B_letter"]["best_without_validator"]["spell"]),
    "B_letter_spell_at_q020": RESULT["B_letter"]["spell_quad_at_q020"],
    "B_letter_spell_at_chosen": RESULT["B_letter"]["spell_quad_at_chosen"],
}

RESULT["feasibility"] = {
    "z_holm1": Z_HOLM1,
    "min_boot_p": 1.0 / (B_BOOT + 1),
    "holm_step1_alpha": 0.05 / FAMILY_F1,
    "n_needed": {("h%d_rate%.2f" % (h, r)): n_needed(r, Z_HOLM1, h)
                 for h in HORIZONS
                 for r in (0.58, 0.60, 0.65, 0.70, 0.75, 0.80)},
    "degenerate_floor": {"h1": BLOCK[1] * DEGEN_RATIO,
                         "h3": BLOCK[3] * DEGEN_RATIO},
}

# Pomesyachnye sostoyaniya -- chtoby proverku mozhno bylo napisat' zanovo,
# ne perepisyvaya postroenie osey: nezavisimyy kod beryot otsyuda sostoyanie
# i sam schitaet popadaniya (check-z05.py).
RESULT["monthly_states"] = {
    cfg: {m: state_month(cfg, m)[0] for m in MONTHS} for cfg in CONFIGS}
RESULT["monthly_states"]["RAW_P10"] = {
    m: (state_month("P10", m)[1]["raw"] or "ANOMALY") for m in MONTHS}
if VINT_STATE:
    RESULT["monthly_states"]["VINTAGE"] = dict(VINT_STATE)
RESULT["monthly_scores_P10"] = {
    m: {"fed": state_month("P10", m)[1]["score_fed"],
        "macro": state_month("P10", m)[1]["score_macro"],
        "shape": state_month("P10", m)[1]["shape"]} for m in MONTHS}
RESULT["month_end_dates"] = {m: MONTH_END[m] for m in MONTHS}
RESULT["pairs"] = [{k: p[k] for k in ("key", "long", "short", "signs",
                                      "overlap")} for p in PAIRS + PAIR_EXTRA]

RESULT["elapsed_sec"] = round(time.time() - _T0, 1)
RESULT["data_passport"] = {
    k: {"n": len(observed(v)), "first": v.dates[0] if v.dates else None,
        "last": v.dates[-1] if v.dates else None,
        "fetched_at": getattr(v, "fetched_at", "")}
    for k, v in RAW.items() if hasattr(v, "dates")}

with open(os.path.join(_HERE, "result.json"), "w", encoding="utf-8") as fh:
    json.dump(RESULT, fh, ensure_ascii=False, indent=1, default=str)

say("")
say("result.json zapisan; vsego %.1f s" % (time.time() - _T0))
