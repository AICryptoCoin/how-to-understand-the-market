#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z26 -- kalibrovka (q, kappa) konstrukcii klassifikatora v2.

Vopros odin: SUSHCHESTVUET LI para (q, kappa), pri kotoroy konstrukciya v2
odnovremenno beryot trebovanie A (dolya vremeni v Centre v polose
[0.15 .. 0.25]) i trebovanie B (srednyaya dlitel'nost' nepreryvnogo prebyvaniya
v odnom kvadrante ne men'she 30 kalendarnyh dney).

Konfiguraciya fiksirovana spekoy (sec.2 HYPOTHESIS.md): veto formy snyato,
Centr cherez "ILI", sostav vhodov D4, otchyotnaya setka C_M, okno 2004-2026.
Novoe protiv Z27 -- gisterezis sec.1.4.10 speki.

Dohodnosti ne otkryvayutsya ni razu -- sm. sec.1 HYPOTHESIS.md i storozha nizhe
(_yahoo, _z05, skan imyon funkciy).

Vsyo pechataemoe -- ASCII: konsol' etoy mashiny v cp1251.

    python run.py            # polnyy progon
    python run.py --quick    # sokrashchyonnaya setka (otladka koda)

Pred-registraciya -- HYPOTHESIS.md, kommit 1673308, do pervogo raschyota.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import os
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

import sources as _S           # noqa: E402
import composite as C          # noqa: E402

QUICK = "--quick" in sys.argv
_T0 = time.time()

# Kontrol'noe slovo poiskovyh progonov (HYPOTHESIS sec.8): zavedomo
# prisutstvuet v vyvode, ishchetsya bez uchyota registra.
KONTROL_WORD = "KONTROL-SLOVO-Z26"

RESULT: dict[str, Any] = {"task": "Z26"}


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
# 0. STOROZHA DISCIPLINY (HYPOTHESIS sec.1.3)
# =========================================================================== #

# ZQ=F -- edinstvennyy cenovoy ryad SOBSTVENNOY konstrukcii v2 (slot
# terminal'noy stavki, ves 0.10). Ostal'nye chetyre nuzhny ISKLYUCHITEL'NO dlya
# kontrolya vosproizvedeniya Z05 (sostav D0): pravilo neperesecheniya sec.1.4.11
# vyvelo ih iz svyortki v2.
YAHOO_ALLOWED = {"DX-Y.NYB", "GC=F", "HG=F", "CL=F", "ZQ=F"}
YAHOO_V2_ONLY = {"ZQ=F"}
YAHOO_ASKED: list[str] = []

# Instrumenty chetyrnadcati par -- gruzit' zapreshcheno vovse.
YAHOO_FORBIDDEN = {
    "SPY", "IWM", "QQQ", "EFA", "EEM", "XLK", "XLB", "XLY", "XLP", "XLE",
    "XLF", "XLI", "XLV", "XLU", "TLT", "SHY", "LQD", "IEF", "^VIX",
    "^SPGSCI", "SPHB", "SPLV", "^GSPC", "^RUT"}

# Klyuchi Z05/result.json, kotorye RAZRESHENO chitat'. Vsyo ostal'noe --
# rezul'tat po dohodnostyam.
Z05_ALLOWED = {"month_end_dates", "pairs", "monthly_states",
               "state_distribution", "validator_effect", "theta", "window"}
Z05_READ: list[str] = []


def _yahoo(symbol: str):
    assert symbol not in YAHOO_FORBIDDEN, \
        "STOROZH: instrument pary '%s' gruzit' zapreshcheno (sec.1.2)" % symbol
    assert symbol in YAHOO_ALLOWED, \
        "STOROZH: simvol '%s' ne v belom spiske (sec.1.3)" % symbol
    YAHOO_ASKED.append(symbol)
    return _S.yahoo(symbol)


_Z05_RAW: dict[str, Any] | None = None


def _z05(key: str) -> Any:
    """Edinstvennyy put' k Z05/result.json: tol'ko belyy spisok klyuchey."""
    global _Z05_RAW
    assert key in Z05_ALLOWED, \
        "STOROZH: klyuch Z05 '%s' soderzhit rezul'tat po dohodnostyam" % key
    if _Z05_RAW is None:
        with open(os.path.join(_RESEARCH, "Z05", "result.json"),
                  encoding="utf-8") as fh:
            _Z05_RAW = json.load(fh)
    if key not in Z05_READ:
        Z05_READ.append(key)
    return _Z05_RAW[key]


# =========================================================================== #
# 1. Konstanty
# =========================================================================== #

WIN_START = "2004-01-01"
WIN_END = "2026-06-30"
WARMUP_START = "2001-01-01"
CALIB_END = "2014-12-31"
OOS_START = "2015-01-01"

MIN_OBS_DAILY = 250
MIN_OBS_MONTHLY = 24
MIN_OBS_WEEKLY = 104

MAD_C = 1.4826
CLIP = 3.0
CUTOFF = 0.60
PARALLEL_BP = 0.05
AXIS_WINDOW = 10                 # okno osey (sec.1.4.6, Z27 sec.6.1)
WINDOWS = (5, 10, 30)

# --- SETKA (q, kappa): HYPOTHESIS sec.4, ob'yavlena do raschyota ------------ #
Q_STEP = 0.10 if QUICK else 0.02
Q_GRID = [round(i * Q_STEP, 4) for i in range(int(round(0.90 / Q_STEP)) + 1)]
K_GRID = ([1.00, 0.50, 0.10] if QUICK else
          [1.00, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.05])

# Setka q predshestvennicy (kontrol' 9): Z05 / Z27, 0.00 .. 0.60 shag 0.02.
Q_GRID_Z27 = [round(i * 0.02, 4) for i in range(31)]

REQ_A_LO, REQ_A_HI = 0.15, 0.25          # trebovanie A, sec.1.4.7-bis
REQ_B_DAYS = 30                          # trebovanie B, sec.1.4.7-bis
DEGEN_N = 24                             # n/L>=8 pri L=3, h=1 (Z05 sec.7.2)
MIN_EVENTS_FOR_QUARTILES = 5             # HYPOTHESIS sec.7.3

QUADS = ("I", "II", "III", "IV")
STATES = ("CENTER", "I", "II", "III", "IV", "ANOMALY")
QUAD_OF = {("+", "-"): "I", ("+", "+"): "II",
           ("-", "-"): "III", ("-", "+"): "IV"}

FLAGS = ("STRONG", "WEAK", "CONTRADICTS", "NO_INFO", "TWIST", "NO_STATE")
FLAG_RU = {"STRONG": "podtverzhdena/sil'naya",
           "WEAK": "podtverzhdena/slabaya",
           "CONTRADICTS": "protivorechit",
           "NO_INFO": "net informacii",
           "TWIST": "tvist",
           "NO_STATE": "net sostoyaniya dlya sverki"}


# =========================================================================== #
# 2. Melkie instrumenty (perenos Z27 sec.2 bez izmeneniy)
# =========================================================================== #

def d2(iso: str) -> date:
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


def last_dom(m: str) -> int:
    nxt = add_months(m, 1)
    return (date(int(nxt[:4]), int(nxt[5:7]), 1) - timedelta(days=1)).day


def avail_date(m: str, lag_months: int, dom: int) -> str:
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
    z = raw / (MAD_C * scale)
    return max(-CLIP, min(CLIP, z)) / CLIP


class Step:
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


def observed(s: Any) -> list[tuple[str, float]]:
    return [(d, float(v)) for d, v in zip(s.dates, s.values) if v is not None]


# =========================================================================== #
# 3. Zagruzka
# =========================================================================== #

head("Z26 -- kalibrovka (q, kappa) konstrukcii klassifikatora v2")
say(KONTROL_WORD)
say("Vopros: sushchestvuet li para (q, kappa), berushchaya A i B odnovremenno.")
say("Dohodnosti ne otkryvayutsya. Storozha: _yahoo (belyy spisok simvolov),")
say("_z05 (belyy spisok klyuchey), skan imyon funkciy modulya.")
say("Setka: q %d uzlov (%.2f .. %.2f, shag %.2f) x kappa %d uzlov = %d yacheek%s"
    % (len(Q_GRID), Q_GRID[0], Q_GRID[-1], Q_STEP, len(K_GRID),
       len(Q_GRID) * len(K_GRID), "  [QUICK]" if QUICK else ""))

sub("3.1 Ryady")

RAW: dict[str, Any] = {}


def load(name: str, fn: Callable[[], Any]) -> Any:
    t = time.time()
    obj = fn()
    RAW[name] = obj
    n = len(observed(obj)) if hasattr(obj, "dates") else -1
    first = obj.dates[0] if getattr(obj, "dates", None) else "?"
    lastd = obj.dates[-1] if getattr(obj, "dates", None) else "?"
    say("  %-12s n=%-6d %s .. %s  (%.1fs)"
        % (name, n, first, lastd, time.time() - t))
    return obj


FRED_IDS = {"DGS2": "DGS2", "DGS5": "DGS5", "DGS10": "DGS10",
            "T5YIE": "T5YIE", "PERMIT": "PERMIT", "IC4WSA": "IC4WSA",
            "NOF": "NOFDFSA066MSFRBPHI", "FEDFUNDS": "FEDFUNDS",
            "DFEDTAR": "DFEDTAR", "DFEDTARU": "DFEDTARU",
            "DFEDTARL": "DFEDTARL", "UMCSENT": "UMCSENT"}
for _k, _sid in FRED_IDS.items():
    load(_k, (lambda s=_sid: _S.fred(s)))

for _sym in ("DX-Y.NYB", "GC=F", "HG=F", "CL=F", "ZQ=F"):
    load(_sym, (lambda s=_sym: _yahoo(s)))

load("NAHB", lambda: _S.nahb_hmi("t2")["HMI"])
load("COMPOSITE", C.frozen_composite)

sub("3.2 Predposylka: lestnica Z06 (ta zhe proverka, chto v Z05 i Z27)")

_z06 = json.load(open(os.path.join(_RESEARCH, "Z06", "result.json"),
                      encoding="utf-8"))
_lad_bad, _lad_good = _z06["ladder"], _z06["ladder_practical"]
say("  ladder.rejected = %r" % _lad_bad.get("rejected"))
say("  ladder_practical month_counts = %s" % _lad_good.get("month_counts"))
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


# =========================================================================== #
# 4. Setki dat
# =========================================================================== #

sub("4.1 Setki (HYPOTHESIS sec.1.3, kalendar' -- iz DGS10, ne iz cen)")

MONTH_END: dict[str, str] = dict(_z05("month_end_dates"))
MONTHS = sorted(MONTH_END)
say("  mesyacev iz Z05/result.json['month_end_dates']: %d  (%s .. %s)"
    % (len(MONTHS), MONTHS[0], MONTHS[-1]))
assert len(MONTHS) == 270, "okno Z05 obyazano byt' 270 mesyacev"

_dgs10_dates = [d for d, _ in observed(RAW["DGS10"])]
GRID_FULL = sorted(set(d for d in _dgs10_dates
                       if WARMUP_START <= d <= WIN_END) | set(MONTH_END.values()))
GRID = [d for d in GRID_FULL if WIN_START <= d <= WIN_END]
_missing = [m for m, d in MONTH_END.items() if d not in set(GRID)]
say("  dnevnaya setka (DGS10 + koncy mesyacev): razgon %d dney, okno %d dney"
    % (len(GRID_FULL), len(GRID)))
say("  koncov mesyacev Z05 vne setki: %d" % len(_missing))
assert not _missing, "koncy mesyacev obyazany lezhat' na dnevnoy setke"

GRID_IDX = {d: i for i, d in enumerate(GRID)}
CALIB_IDX = [i for i, d in enumerate(GRID) if d <= CALIB_END]
CAL_DATES = [GRID[i] for i in CALIB_IDX]
MONTH_END_IDX = {m: GRID_IDX[MONTH_END[m]] for m in MONTHS}
CAL_MONTHS = [m for m in MONTHS if m <= CALIB_END[:7]]
OOS_MONTHS = [m for m in MONTHS if m >= OOS_START[:7]]
WINDOW_CAL_DAYS = (d2(WIN_END) - d2(WIN_START)).days + 1
say("  kalibrovochnyy otrezok (tol'ko dlya kontrolya 9): %s .. %s, %d dney"
    % (GRID[CALIB_IDX[0]], GRID[CALIB_IDX[-1]], len(CALIB_IDX)))
say("  okno v kalendarnyh dnyah: %d" % WINDOW_CAL_DAYS)


# =========================================================================== #
# 5. Vklady vhodov (perenos Z27 sec.5 bez izmeneniya formul)
# =========================================================================== #

def rolling_scale(grid: Sequence[str], raw: dict[str, float],
                  years: int, min_obs: int) -> dict[str, float]:
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


sub("5.1 Mesyachnye i nedel'nye vhody")

_nahb = {mkey(d): v for d, v in observed(RAW["NAHB"])}
C_NAHB = monthly_level(_nahb, 50.0)
_permit = {mkey(d): v for d, v in observed(RAW["PERMIT"])}
C_PERMIT = monthly_speed(_permit, 3, log=True)
_comp_c = C.ladder_contribution(RAW["COMPOSITE"], C.LADDER_V1)
C_COMP = {mkey(d): v for d, v in observed(_comp_c)}
_nof = {mkey(d): v for d, v in observed(RAW["NOF"])}
C_NOF = monthly_level(_nof, 0.0)
C_CLAIMS = weekly_speed(observed(RAW["IC4WSA"]), 13, flip=True)

# UMCSENT: porog urovnya = mediana ryada na KALIBROVOCHNOM otrezke (Z27
# sec.6.4). Eto NE svobodnyy parametr zadachi (HYPOTHESIS sec.2).
_umc = {mkey(d): v for d, v in observed(RAW["UMCSENT"])}
_umc_calib = [v for m, v in _umc.items() if WIN_START[:7] <= m <= CALIB_END[:7]]
UMC_THRESHOLD = median(_umc_calib)
C_UMC = monthly_level(_umc, UMC_THRESHOLD)
say("  NAHB %d | PERMIT %d | kompozit %d | NOF %d | IC4WSA %d nedel'"
    % (len(C_NAHB), len(C_PERMIT), len(C_COMP), len(C_NOF), len(C_CLAIMS)))
say("  UMCSENT: porog urovnya = mediana kalibrovochnogo otrezka = %.2f,"
    " mesyacev vklada %d" % (UMC_THRESHOLD, len(C_UMC)))

_vkl: dict[float, int] = {}
for _v in C_COMP.values():
    _vkl[round(_v, 4)] = _vkl.get(round(_v, 4), 0) + 1
say("  KONTROL 8 (Z06): vklad kompozita po znacheniyam = %s"
    % dict(sorted(_vkl.items(), reverse=True)))
assert _vkl.get(1.0) == 149 and _vkl.get(0.2) == 38 \
    and _vkl.get(-0.2) == 120 and _vkl.get(-1.0) == 83, \
    "vklad kompozita ne vosproizvyol Z06 (149/38/120/83)"

PUB = {"NAHB": (0, 16), "PERMIT": (1, 20), "COMP": (0, 28), "NOF": (0, 21),
       "UMC": (0, 28)}
ST_NAHB = to_step_monthly(C_NAHB, *PUB["NAHB"])
ST_PERMIT = to_step_monthly(C_PERMIT, *PUB["PERMIT"])
ST_COMP = to_step_monthly(C_COMP, *PUB["COMP"])
ST_NOF = to_step_monthly(C_NOF, *PUB["NOF"])
ST_UMC = to_step_monthly(C_UMC, *PUB["UMC"])
ST_CLAIMS = Step(C_CLAIMS.items())

sub("5.2 Faza rezhima DKP")

_tgt: dict[str, float] = {}
for d, v in observed(RAW["DFEDTAR"]):
    _tgt[d] = v
_u = dict(observed(RAW["DFEDTARU"]))
_l = dict(observed(RAW["DFEDTARL"]))
for d in _u:
    if d in _l:
        _tgt[d] = (_u[d] + _l[d]) / 2.0
ST_TGT = Step(_tgt.items())


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

sub("5.3 Dnevnye vhody")

ST_DGS2 = Step(observed(RAW["DGS2"]))
ST_DGS10 = Step(observed(RAW["DGS10"]))
_d5 = dict(observed(RAW["DGS5"]))
_ie = dict(observed(RAW["T5YIE"]))
ST_REAL5 = Step((d, _d5[d] - _ie[d]) for d in _d5 if d in _ie)
ST_DXY = Step(observed(RAW["DX-Y.NYB"]))
ST_ZQ = Step(observed(RAW["ZQ=F"]))
_gc = dict(observed(RAW["GC=F"]))
_hg = dict(observed(RAW["HG=F"]))
_cl = dict(observed(RAW["CL=F"]))
ST_HGGC = Step((d, _hg[d] / _gc[d]) for d in _hg if d in _gc and _gc[d] > 0)
ST_CLGC = Step((d, _cl[d] / _gc[d]) for d in _cl if d in _gc and _gc[d] > 0)

DC = {
    "us2y": daily_speed(ST_DGS2, GRID_FULL, AXIS_WINDOW, flip=True),
    "real5": daily_speed(ST_REAL5, GRID_FULL, AXIS_WINDOW, flip=True),
    "dxy": daily_speed(ST_DXY, GRID_FULL, AXIS_WINDOW, log=True, flip=True),
    # ZQ=F: cena f'yuchersa vverh = ozhidaemaya stavka vniz = myagche -> "+"
    "zq": daily_speed(ST_ZQ, GRID_FULL, AXIS_WINDOW, log=True),
    "hggc": daily_speed(ST_HGGC, GRID_FULL, AXIS_WINDOW, log=True),
    "clgc": daily_speed(ST_CLGC, GRID_FULL, AXIS_WINDOW, log=True),
}
say("  okno %d dn.: %s" % (AXIS_WINDOW,
                           ", ".join("%s=%d" % (k, len(v))
                                     for k, v in DC.items())))

sub("5.4 Forma krivoy (perenos Z27 + vetka TWIST, HYPOTHESIS sec.6)")


def shape_at(iso: str, W: int, *, parallel_rule: bool,
             twist_rule: bool) -> str | None:
    a, b = ST_DGS2.at(iso), ST_DGS2.at(shift_days(iso, W))
    c, e = ST_DGS10.at(iso), ST_DGS10.at(shift_days(iso, W))
    if None in (a, b, c, e):
        return None
    dk, dl = a - b, c - e
    dspread = dl - dk
    if parallel_rule and abs(dspread) < PARALLEL_BP:
        return "PARALLEL"
    if twist_rule and dk != 0.0 and dl != 0.0 and (dk > 0) != (dl > 0):
        return "TWIST"                      # R24-R27 raznoznakovyy tvist ne kroyut
    up = (dk + dl) / 2.0 > 0
    if not up and dspread < 0:
        return "I"
    if not up and dspread > 0:
        return "II"
    if up and dspread < 0:
        return "III"
    return "IV"


# SHAPE / SHAPE_NP -- CHTENIE Z27 (bez tvista): tol'ko ono uchastvuet v kontrole
# vosproizvedeniya Z05, gde vetki tvista ne bylo.
SHAPE = {W: [shape_at(d, W, parallel_rule=True, twist_rule=False) for d in GRID]
         for W in WINDOWS}
SHAPE_NP = {W: [shape_at(d, W, parallel_rule=False, twist_rule=False)
                for d in GRID] for W in WINDOWS}
# SHAPE_V2 -- chtenie v2 (s vetkoy tvista): tol'ko ono idyot vo FLAG.
SHAPE_V2 = {W: [shape_at(d, W, parallel_rule=True, twist_rule=True)
                for d in GRID] for W in WINDOWS}
for W in WINDOWS:
    cnt: dict[str, int] = {}
    for v in SHAPE_V2[W]:
        cnt[str(v)] = cnt.get(str(v), 0) + 1
    say("  okno %2d dn. (chtenie v2): %s" % (W, dict(sorted(cnt.items()))))


def shape_vote(src: dict[int, list], i: int) -> tuple[str | None, int]:
    votes = [src[W][i] for W in WINDOWS]
    votes = [v for v in votes if v is not None]
    if len(votes) < 2:
        return None, 0
    best, n = None, 0
    for v in set(votes):
        k = votes.count(v)
        if k > n:
            best, n = v, k
    return (best, n) if n >= 2 else ("NOAGREE", n)


SHAPE_VOTE_Z27 = [shape_vote(SHAPE, i)[0] for i in range(len(GRID))]
VOTE_V2 = [shape_vote(SHAPE_V2, i) for i in range(len(GRID))]


# =========================================================================== #
# 6. Sostavy osey: D0 (kontrol' Z05) i D4 (konstrukciya v2)
# =========================================================================== #

head("6. Sostavy osey: D0 -- kontrol' predshestvennicy, D4 -- konstrukciya v2")

W_FED_BASE = {"us2y": 0.25, "real5": 0.15, "phase": 0.15, "dxy": 0.10}
W_MACRO_BASE = {"nahb": 0.13, "permit": 0.13, "comp": 0.10, "claims": 0.12,
                "nof": 0.08, "hggc": 0.04, "clgc": 0.04}
FULL = 1.00


def _wo(d: dict[str, float], *keys: str) -> dict[str, float]:
    return {k: v for k, v in d.items() if k not in keys}


D_LEVELS: dict[str, dict[str, Any]] = {
    "D0": {"fed": dict(W_FED_BASE), "macro": dict(W_MACRO_BASE),
           "note": "sostav Z05/Z27 -- tol'ko dlya kontrolya vosproizvedeniya"},
    "D4": {"fed": dict(_wo(W_FED_BASE, "dxy"), zq=0.10),
           "macro": dict(_wo(W_MACRO_BASE, "hggc", "clgc"), umcsent=0.06),
           "note": "konstrukciya v2 (sec.1.4.3, sec.1.4.4, sec.1.4.11)"},
}
for _k, _v in D_LEVELS.items():
    say("  %-3s fed=%.2f (%s)  macro=%.2f (%s)  -- %s"
        % (_k, sum(_v["fed"].values()), "+".join(sorted(_v["fed"])),
           sum(_v["macro"].values()), "+".join(sorted(_v["macro"])),
           _v["note"]))


def parts_at(iso: str) -> tuple[dict[str, float | None], dict[str, float | None]]:
    fed = {"us2y": DC["us2y"].get(iso), "real5": DC["real5"].get(iso),
           "phase": C_PHASE.get(iso), "dxy": DC["dxy"].get(iso),
           "zq": DC["zq"].get(iso)}
    mac = {"nahb": ST_NAHB.at(iso), "permit": ST_PERMIT.at(iso),
           "comp": ST_COMP.at(iso), "claims": ST_CLAIMS.at(iso),
           "nof": ST_NOF.at(iso), "hggc": DC["hggc"].get(iso),
           "clgc": DC["clgc"].get(iso), "umcsent": ST_UMC.at(iso)}
    return fed, mac


def axis(parts: dict[str, float | None], weights: dict[str, float],
         cutoff: float = CUTOFF) -> tuple[float | None, float]:
    num = den = 0.0
    for k, w in weights.items():
        c = parts.get(k)
        if c is None:
            continue
        num += w * c
        den += w
    share = den / FULL
    if share < cutoff or den == 0:
        return None, share
    return num / den, share


PARTS = [parts_at(d) for d in GRID]

SCORE: dict[str, dict[str, list]] = {}
for dk, dv in D_LEVELS.items():
    sf_l, sm_l, shf_l, shm_l = [], [], [], []
    for fed_p, mac_p in PARTS:
        sf, shf = axis(fed_p, dv["fed"])
        sm, shm = axis(mac_p, dv["macro"])
        sf_l.append(sf)
        sm_l.append(sm)
        shf_l.append(shf)
        shm_l.append(shm)
    SCORE[dk] = {"sf": sf_l, "sm": sm_l, "share_f": shf_l, "share_m": shm_l}
    _nf = sum(1 for x in sf_l if x is None)
    _nm = sum(1 for x in sm_l if x is None)
    say("  %-3s dney bez osi FED %4d, bez osi MACRO %4d (iz %d)"
        % (dk, _nf, _nm, len(GRID)))

ABS_F = [abs(x) for x in SCORE["D4"]["sf"] if x is not None]
ABS_M = [abs(x) for x in SCORE["D4"]["sm"] if x is not None]
say("  D4: |score| FED  n=%d  min=%.6f  max=%.6f" % (len(ABS_F), min(ABS_F), max(ABS_F)))
say("  D4: |score| MACRO n=%d  min=%.6f  max=%.6f" % (len(ABS_M), min(ABS_M), max(ABS_M)))
_zero_f = sum(1 for x in ABS_F if x == 0.0)
_zero_m = sum(1 for x in ABS_M if x == 0.0)
say("  dney s |score| rovno 0: FED %d, MACRO %d (vazhno dlya kontrolya kappa=1)"
    % (_zero_f, _zero_m))


# =========================================================================== #
# 7. Gisterezis (sec.1.4.10) i klassifikaciya (sec.1.4.12)
# =========================================================================== #

def hyst_signs(scores: Sequence[float | None], theta_hi: float,
               theta_lo: float) -> list[int | None]:
    """Znak osi po sec.1.4.10. None -- os' ne schitaetsya, pamyat' sohranyaetsya."""
    out: list[int | None] = []
    ap = out.append
    s = 0
    for x in scores:
        if x is None:
            ap(None)                       # ANOMALY; pamyat' ne trogaem
            continue
        if s == 0:
            if x >= theta_hi:
                s = 1
            elif x <= -theta_hi:
                s = -1
            else:
                s = 0
        elif s == 1:
            if x <= -theta_hi:             # pereskok cherez vsyu myortvuyu zonu
                s = -1
            elif x < theta_lo:
                s = 0
            else:
                s = 1
        else:
            if x >= theta_hi:              # pereskok cherez vsyu myortvuyu zonu
                s = 1
            elif x > -theta_lo:
                s = 0
            else:
                s = -1
        ap(s)
    return out


def memoryless_signs(scores: Sequence[float | None],
                     theta: float) -> list[int | None]:
    """Pravilo Z05: |score| < theta -> 0, inache znak score."""
    out: list[int | None] = []
    for x in scores:
        if x is None:
            out.append(None)
        elif abs(x) < theta:
            out.append(0)
        else:
            out.append(1 if x > 0 else -1)
    return out


def states_of(sf: Sequence[int | None], sm: Sequence[int | None],
              ok: Sequence[bool] | None = None) -> list[str]:
    """Centr cherez ILI (sec.1.4.12 p.4). ok -- veto validatora (tol'ko Z05)."""
    out: list[str] = []
    ap = out.append
    for i in range(len(sf)):
        a, b = sf[i], sm[i]
        if a is None or b is None:
            ap("ANOMALY")
            continue
        if a == 0 or b == 0:
            ap("CENTER")
            continue
        q = QUAD_OF[("+" if a > 0 else "-", "+" if b > 0 else "-")]
        ap(q if (ok is None or ok[i]) else "CENTER")
    return out


def spells(dates: Sequence[str], states: Sequence[str]) -> list[tuple[str, int]]:
    """(sostoyanie, dlitel'nost' v kalendarnyh dnyah) po nepreryvnym periodam."""
    out: list[tuple[str, int]] = []
    if not states:
        return out
    start = 0
    for i in range(1, len(states) + 1):
        if i == len(states) or states[i] != states[start]:
            end = dates[i] if i < len(states) else \
                s2(d2(dates[-1]) + timedelta(days=1))
            out.append((states[start], (d2(end) - d2(dates[start])).days))
            start = i
    return out


def mean_spell_all(dates, states) -> float:
    sp = spells(dates, states)
    return sum(x[1] for x in sp) / len(sp) if sp else 0.0


def quad_spell_stats(dates, states) -> dict[str, float]:
    sp = [x for x in spells(dates, states) if x[0] in QUADS]
    if not sp:
        return {"n_spells": 0, "mean_days": 0.0, "median_days": 0.0}
    lens = [x[1] for x in sp]
    return {"n_spells": len(sp), "mean_days": sum(lens) / len(lens),
            "median_days": float(median(lens))}


def reversal_delays(base: Sequence[int | None], test: Sequence[int | None],
                    dates: Sequence[str]) -> tuple[list[int], list[int]]:
    """Zaderzhka na razvorotah v kalendarnyh dnyah. Dve mery, obe pechatayutsya.

    Razvorot -- den', v kotoryy put' pri kappa=1 vpervye prinimaet -v posle v;
    eti dni odinakovy pri vseh kappa (vhod v znak trebuet |score| >= theta_hi
    iz lyubogo sostoyaniya).

    LAST (HYPOTHESIS sec.5.1, PRED-REGISTRIROVANNAYA, osnovnaya): schitaetsya ot
      POSLEDNEGO utverzhdeniya znaka v pri kappa=1. Nizhnyaya, konservativnaya
      ocenka sdviga.
    FIRST (soprovozhdayushchaya, sec.11 zapis' 2): schitaetsya ot PERVOGO otkaza
      ot znaka v pri kappa=1 vnutri togo zhe epizoda. Verhnyaya ocenka: skol'ko
      lishnih dney os' derzhit znak, kotoryy bezpamyatnoe pravilo uzhe otpustilo.
    """
    nz = [i for i in range(len(base)) if base[i] not in (None, 0)]
    last_out: list[int] = []
    first_out: list[int] = []
    if not nz:
        return last_out, first_out
    # Epizody: gruppy podryad idushchih nenulevyh dney s odnim znakom.
    eps: list[tuple[int, int, int]] = []          # (i_start, i_end, v)
    st = nz[0]
    for k in range(1, len(nz) + 1):
        if k == len(nz) or base[nz[k]] != base[st]:
            eps.append((st, nz[k - 1], base[st]))
            if k < len(nz):
                st = nz[k]
    for e in range(len(eps) - 1):
        i_start, i_end, v = eps[e]
        i_next = eps[e + 1][0]
        if eps[e + 1][2] == v:                    # ne razvorot
            continue
        # --- mera LAST ---
        a_k = i_end
        for j in range(i_next - 1, i_end, -1):
            if test[j] == v:
                a_k = j
                break
        last_out.append((d2(dates[a_k + 1]) - d2(dates[i_end + 1])).days)
        # --- mera FIRST ---
        f1 = i_next
        for j in range(i_start + 1, i_next):
            if base[j] != v:
                f1 = j
                break
        fk = i_next
        for j in range(i_start + 1, i_next):
            if test[j] != v:
                fk = j
                break
        first_out.append((d2(dates[fk]) - d2(dates[f1])).days)
    return last_out, first_out


def flag_of(vote: tuple[str | None, int], state: str) -> str:
    """Pyatiznachnyy flag uverennosti + shestoe znachenie (HYPOTHESIS sec.6)."""
    if state in ("CENTER", "ANOMALY"):
        return "NO_STATE"
    val, n = vote
    if val is None:
        return "NO_INFO"
    if val == "PARALLEL":
        return "NO_INFO"
    if val == "TWIST":
        return "TWIST"
    if val == "NOAGREE":
        return "CONTRADICTS"
    if val != state:
        return "CONTRADICTS"
    return "STRONG" if n == 3 else "WEAK"


PAIRS = [p for p in _z05("pairs") if p["key"] != "BETA"]
assert len(PAIRS) == 14, "osnovnoe semeystvo obyazano byt' iz 14 par"


def pair_n(dist: dict[str, int]) -> dict[str, int]:
    """n pary = chislo mesyacev, sostoyanie kotoryh imeet dlya neyo znak."""
    return {p["key"]: sum(dist.get(st, 0) for st in p["signs"]) for p in PAIRS}


# =========================================================================== #
# 8. Devyat' kontroley vosproizvedeniya (HYPOTHESIS sec.3.3)
# =========================================================================== #

head("8. Kontroli vosproizvedeniya: konveyer -- tot zhe, chto v Z05 i Z27")
say(KONTROL_WORD)

Z05_THETA = _z05("theta")
Z05_STATES = _z05("monthly_states")
Z05_DIST = _z05("state_distribution")
Z05_VAL = _z05("validator_effect")

_p10 = Z05_THETA["P10"]["chosen"]
_TF, _TM = _p10["theta_fed"], _p10["theta_macro"]
say("  Z05 P10: q=%.2f theta_fed=%.4f theta_macro=%.4f"
    % (_p10["q"], _TF, _TM))


def validator_ok_list(a: str) -> list[bool]:
    """Veto validatora Z05/Z27 po dnyam, dlya kvadranta, nazvannogo znakami."""
    out: list[bool] = []
    quads_by_sign = []
    for i in range(len(GRID)):
        sf, sm = SCORE["D0"]["sf"][i], SCORE["D0"]["sm"][i]
        if sf is None or sm is None:
            quads_by_sign.append(None)
        else:
            quads_by_sign.append(
                QUAD_OF[("+" if sf > 0 else "-", "+" if sm > 0 else "-")])
    for i, q in enumerate(quads_by_sign):
        if q is None:
            out.append(False)
        elif a == "A0":
            out.append(SHAPE[10][i] == q)
        elif a == "A1":
            out.append(SHAPE_VOTE_Z27[i] == q)
        elif a == "A4":
            out.append(True)
        elif a == "A5":
            out.append(SHAPE_NP[10][i] == q)
        else:
            raise AssertionError(a)
    return out


OK_A0 = validator_ok_list("A0")
OK_A1 = validator_ok_list("A1")
OK_A4 = validator_ok_list("A4")


def classify_z05(theta_f: float, theta_m: float, ok: Sequence[bool] | None,
                 kappa: float) -> list[str]:
    """Sostoyaniya v konfiguracii Z05, no CHEREZ KOD GISTEREZISA."""
    sf = hyst_signs(SCORE["D0"]["sf"], theta_f, kappa * theta_f)
    sm = hyst_signs(SCORE["D0"]["sm"], theta_m, kappa * theta_m)
    return states_of(sf, sm, ok)


sub("8.1 KONTROL 1 (novyy, sec.1.4.7-bis): pri kappa=1 -- Z05 vo vseh 270 mes.")
_daily_p10 = classify_z05(_TF, _TM, OK_A0, 1.0)
_mine = {m: _daily_p10[MONTH_END_IDX[m]] for m in MONTHS}
_diff = [m for m in MONTHS if _mine[m] != Z05_STATES["P10"][m]]
say("  rashozhdeniy pomesyachnyh sostoyaniy s Z05 P10: %d iz %d"
    % (len(_diff), len(MONTHS)))
if _diff:
    say("  POMESYACHNO (mesyac / Z26 / Z05):")
    for m in _diff:
        say("    %s  Z26=%-8s Z05=%s" % (m, _mine[m], Z05_STATES["P10"][m]))
assert not _diff, ("konstrukciya pri kappa=1 ne vosproizvela Z05 -- progon "
                   "ne sostoyalsya (HYPOTHESIS sec.3.3)")
say("  -> gisterezis pri kappa=1 tozhdestven pravilu Z05 na otchyotnoy setke.")

sub("8.1-bis Sil'naya forma: kappa=1 == bezpamyatnoe pravilo na VSEY setke")
say("  HYPOTHESIS sec.3.3 nazval edinstvennoe teoreticheski vozmozhnoe")
say("  rashozhdenie zaranee: den', gde score rovno nol' pri theta_hi rovno nol'")
say("  (znak nulya). Nizhe -- OBE versii kontrolya: pred-registrirovannaya")
say("  strogaya i suzhennaya (sec.11 zapis' 1).")
_strong_all: list[tuple[str, bool]] = []
for _q in Q_GRID:
    for _dk, _fld in (("D4", "sf"), ("D4", "sm"), ("D0", "sf"), ("D0", "sm")):
        _abs = [abs(x) for x in SCORE[_dk][_fld] if x is not None]
        _th = quantile(_abs, _q)
        _h = hyst_signs(SCORE[_dk][_fld], _th, 1.0 * _th)
        _m = memoryless_signs(SCORE[_dk][_fld], _th)
        for _i in range(len(GRID)):
            if _h[_i] != _m[_i]:
                _degen = (SCORE[_dk][_fld][_i] == 0.0 and _th == 0.0)
                _strong_all.append((
                    "q=%.2f %s.%s %s score=%r theta=%r h=%r m=%r"
                    % (_q, _dk, _fld, GRID[_i], SCORE[_dk][_fld][_i], _th,
                       _h[_i], _m[_i]), _degen))
_strong_degen = [r for r, dg in _strong_all if dg]
_strong_core = [r for r, dg in _strong_all if not dg]
say("  uzlov q provereno: %d; dney na uzel: %d x 4 ryada"
    % (len(Q_GRID), len(GRID)))
say("  (a) STROGAYA versiya (pred-registrirovannaya): rashozhdeniy %d"
    % len(_strong_all))
for _s, _dg in _strong_all[:20]:
    say("      %s   %s" % (_s, "znak nulya pri theta=0" if _dg else "SUSHCHESTVENNOE"))
say("  (b) iz nih vyrozhdennyh 'znak nulya pri theta_hi=0': %d" % len(_strong_degen))
say("  (v) SUSHCHESTVENNYH rashozhdeniy: %d" % len(_strong_core))
for _s in _strong_core[:20]:
    say("      " + _s)
if _strong_degen:
    say("  Diagnostika vyrozhdennogo dnya (vklady osi FED sostava D4):")
    for _rec in _strong_degen[:3]:
        _dd = _rec.split()[2]
        _ii = GRID_IDX[_dd]
        say("    %s  chasti = %s" % (_dd, {k: (round(v, 6) if v is not None
                                               else None)
                                           for k, v in PARTS[_ii][0].items()}))
        say("    %s  score_FED = %r pri vesah %s"
            % (_dd, SCORE["D4"]["sf"][_ii], D_LEVELS["D4"]["fed"]))
assert not _strong_core, ("pri kappa=1 gisterezis obyazan sovpadat' s pravilom "
                          "Z05 podnevno vezde, krome znaka nulya pri theta=0 "
                          "(HYPOTHESIS sec.3.3, sec.11 zapis' 1)")

sub("8.2 KONTROLI 2-7 (perenos Z27 sec.2)")
_dist: dict[str, int] = {}
for m in MONTHS:
    _dist[_mine[m]] = _dist.get(_mine[m], 0) + 1
say("  KONTROL 2 raspredelenie: %s" % dict(sorted(_dist.items())))
assert _dist == {k: v for k, v in Z05_DIST["P10"].items() if v}, \
    "raspredelenie ne sovpalo s Z05"

_raw_month: dict[str, str] = {}
for m in MONTHS:
    i = MONTH_END_IDX[m]
    sf, sm = SCORE["D0"]["sf"][i], SCORE["D0"]["sm"][i]
    if sf is None or sm is None:
        _raw_month[m] = "ANOMALY"
    elif abs(sf) < _TF or abs(sm) < _TM:
        _raw_month[m] = "CENTER"
    else:
        _raw_month[m] = QUAD_OF[("+" if sf > 0 else "-", "+" if sm > 0 else "-")]
_raw_quad = [m for m in MONTHS if _raw_month[m] in QUADS]
KILLED_84 = [m for m in _raw_quad if _mine[m] == "CENTER"]
say("  KONTROL 3 kvadrant nazvan porogami: %d (Z05: %d)"
    % (len(_raw_quad), Z05_VAL["quadrant_named_by_thresholds"]))
say("  KONTROL 4 pogasheno predohranitelem: %d (Z05: %d)"
    % (len(KILLED_84), Z05_VAL["killed_by_shape"]))
assert len(_raw_quad) == Z05_VAL["quadrant_named_by_thresholds"]
assert len(KILLED_84) == Z05_VAL["killed_by_shape"]

_par = {W: sum(1 for m in MONTHS if SHAPE[W][MONTH_END_IDX[m]] == "PARALLEL")
        for W in WINDOWS}
say("  KONTROL 5 'parallel'nyy sdvig' po oknam: %s (Z05: %s)"
    % (_par, {int(k): v for k, v in Z05_VAL["parallel_months"].items()}))
assert _par == {int(k): v for k, v in Z05_VAL["parallel_months"].items()}

_a20 = Z05_THETA["A20NOVAL"]["chosen"]
_d_a20 = classify_z05(_a20["theta_fed"], _a20["theta_macro"], OK_A4, 1.0)
_n_a20 = sum(1 for m in MONTHS if _d_a20[MONTH_END_IDX[m]] in QUADS)
say("  KONTROL 6 A20NOVAL: kvadrantnyh mesyacev %d (Z05: 176)" % _n_a20)
assert _n_a20 == 176, "A20NOVAL ne vosproizvedyon"

_vt = Z05_THETA["VOTE"]["chosen"]
_d_vt = classify_z05(_vt["theta_fed"], _vt["theta_macro"], OK_A1, 1.0)
_n_vt = sum(1 for m in MONTHS if _d_vt[MONTH_END_IDX[m]] in QUADS)
say("  KONTROL 7 VOTE: kvadrantnyh mesyacev %d (Z05: 13)" % _n_vt)
assert _n_vt == 13, "VOTE ne vosproizvedyon"

sub("8.3 KONTROL 9 (sverh vos'mi): pravilo Bq_B dayot q = 0.42")
_abs_f_cal = [abs(SCORE["D0"]["sf"][i]) for i in CALIB_IDX
              if SCORE["D0"]["sf"][i] is not None]
_abs_m_cal = [abs(SCORE["D0"]["sm"][i]) for i in CALIB_IDX
              if SCORE["D0"]["sm"][i] is not None]
_bqb_q = None
for _q in Q_GRID_Z27:
    _tf, _tm = quantile(_abs_f_cal, _q), quantile(_abs_m_cal, _q)
    _st = [classify_z05(_tf, _tm, OK_A0, 1.0)[i] for i in CALIB_IDX]
    if mean_spell_all(CAL_DATES, _st) >= 30.0:
        _bqb_q = _q
        break
say("  Bq_B na setke 0.00..0.60 shag 0.02 dayot q = %s (Z05: 0.42)" % _bqb_q)
assert _bqb_q is not None and abs(_bqb_q - 0.42) < 1e-9, \
    "pravilo vybora q ne vosproizvelo Z05"

say("")
say("  VSE DEVYAT' KONTROLEY PROYDENY.")
RESULT["reproduction"] = {
    "kappa1_monthly_mismatch": 0,
    "kappa1_vs_memoryless_strict": len(_strong_all),
    "kappa1_vs_memoryless_degenerate": _strong_degen,
    "kappa1_vs_memoryless_substantive": len(_strong_core),
    "distribution": _dist,
    "quadrant_named": len(_raw_quad),
    "killed_by_shape": len(KILLED_84),
    "parallel_months": _par,
    "a20noval_quadrant_months": _n_a20,
    "vote_quadrant_months": _n_vt,
    "composite_contribution": {str(k): v for k, v in sorted(_vkl.items())},
    "bq_b_q": _bqb_q,
    "grid_days_window": len(GRID), "grid_days_warmup": len(GRID_FULL)}
RESULT["z05_control_monthly_states"] = {m: _mine[m] for m in MONTHS}


# =========================================================================== #
# 9. Setka (q, kappa)
# =========================================================================== #

head("9. Setka (q, kappa): %d x %d = %d yacheek"
     % (len(Q_GRID), len(K_GRID), len(Q_GRID) * len(K_GRID)))
say(KONTROL_WORD)
say("  theta_hi = kvantil' q ot |score| na VSYOM okne (sec.1.4.7-bis);")
say("  theta_lo = kappa * theta_hi; Centr cherez ILI; veto snyato; setka C_M.")

SF4 = SCORE["D4"]["sf"]
SM4 = SCORE["D4"]["sm"]
_t = time.time()
CELLS: list[dict[str, Any]] = []
BASE_SIGNS: dict[float, tuple[list, list]] = {}

for q in Q_GRID:
    th_f = quantile(ABS_F, q)
    th_m = quantile(ABS_M, q)
    base_f = hyst_signs(SF4, th_f, th_f)
    base_m = hyst_signs(SM4, th_m, th_m)
    BASE_SIGNS[q] = (base_f, base_m)
    for kap in K_GRID:
        sf_s = hyst_signs(SF4, th_f, kap * th_f)
        sm_s = hyst_signs(SM4, th_m, kap * th_m)
        daily = states_of(sf_s, sm_s, None)
        mons = {m: daily[MONTH_END_IDX[m]] for m in MONTHS}
        dist: dict[str, int] = {}
        for m in MONTHS:
            dist[mons[m]] = dist.get(mons[m], 0) + 1
        nq = sum(dist.get(x, 0) for x in QUADS)
        qsp = quad_spell_stats(GRID, daily)
        _lf, _ff = reversal_delays(base_f, sf_s, GRID)
        _lm, _fm = reversal_delays(base_m, sm_s, GRID)
        dly = sorted(_lf + _lm)
        dly2 = sorted(_ff + _fm)
        dly_sorted = dly
        npk = sum(1 for v in pair_n(dist).values() if v >= DEGEN_N)
        held = sum(1 for i in range(len(GRID))
                   if sf_s[i] != base_f[i] or sm_s[i] != base_m[i])
        dday: dict[str, int] = {}
        for s in daily:
            dday[s] = dday.get(s, 0) + 1
        fl: dict[str, int] = {k: 0 for k in FLAGS}
        for m in MONTHS:
            fl[flag_of(VOTE_V2[MONTH_END_IDX[m]], mons[m])] += 1
        cal_q = sum(1 for m in CAL_MONTHS if mons[m] in QUADS)
        oos_q = sum(1 for m in OOS_MONTHS if mons[m] in QUADS)
        centre = dist.get("CENTER", 0) / len(MONTHS)
        CELLS.append({
            "q": q, "kappa": kap, "theta_fed": th_f, "theta_macro": th_m,
            "center_share": centre,
            "center_months": dist.get("CENTER", 0),
            "quad_share": nq / len(MONTHS),
            "dist": {k: dist.get(k, 0) for k in STATES},
            "anomaly_months": dist.get("ANOMALY", 0),
            "daily_center_share": dday.get("CENTER", 0) / len(GRID),
            "daily_quad_share": sum(dday.get(x, 0) for x in QUADS) / len(GRID),
            "n_quad_spells": qsp["n_spells"],
            "quad_spell_mean": qsp["mean_days"],
            "quad_spell_median": qsp["median_days"],
            "pairs_ok": npk,
            "pairs_n": pair_n(dist),
            "delay_n": len(dly),
            "delay_median": float(median(dly)) if dly else 0.0,
            "delay_q25": quantile(dly_sorted, 0.25) if dly else 0.0,
            "delay_q75": quantile(dly_sorted, 0.75) if dly else 0.0,
            "delay_max": max(dly) if dly else 0,
            "delay_mean": (sum(dly) / len(dly)) if dly else 0.0,
            "hold_median": float(median(dly2)) if dly2 else 0.0,
            "hold_q25": quantile(dly2, 0.25) if dly2 else 0.0,
            "hold_q75": quantile(dly2, 0.75) if dly2 else 0.0,
            "hold_max": max(dly2) if dly2 else 0,
            "hold_mean": (sum(dly2) / len(dly2)) if dly2 else 0.0,
            "held_days_share": held / len(GRID),
            "flags": fl,
            "cal_quad": cal_q, "oos_quad": oos_q,
            "req_A": REQ_A_LO <= centre <= REQ_A_HI,
            "req_B": qsp["mean_days"] >= REQ_B_DAYS,
        })
say("  poscheno %d yacheek za %.1f s" % (len(CELLS), time.time() - _t))

BY_QK = {(c["q"], c["kappa"]): c for c in CELLS}

sub("9.1 Polnaya tablica po VSEY ob'yavlennoy setke")
say("  Kolonki: Centr -- dolya otchyotnyh mesyacev v Centre (trebovanie A);")
say("  kvadr -- dolya kvadrantnyh mesyacev; C/I/II/III/IV -- raspredelenie po")
say("  pyati sostoyaniyam; sred/med -- dlitel'nost' spella v kvadrante, dney")
say("  (trebovanie B: sred >= 30); par -- iz 14 s n >= 24; zaderzhka na")
say("  razvorotah v kalendarnyh dnyah, DVE mery (sm. sec.11.1): LAST --")
say("  pred-registrirovannaya (ot poslednego utverzhdeniya znaka pri kappa=1),")
say("  HOLD -- ot pervogo otkaza ot znaka pri kappa=1; obe mediana/maksimum.")
say("  AB -- vzyaty li trebovaniya.")
say("")
say("  %5s %5s %8s %8s %6s %5s %5s %5s %5s %5s %7s %7s %4s"
    " %7s %7s %7s %7s %6s %3s"
    % ("q", "kappa", "th_fed", "th_mac", "Centr", "C", "I", "II", "III", "IV",
       "sred", "med", "par", "LASTmed", "LASTmax", "HOLDmed", "HOLDmax",
       "n_razv", "AB"))
for c in CELLS:
    d = c["dist"]
    say("  %5.2f %5.2f %8.4f %8.4f %6.3f %5d %5d %5d %5d %5d %7.1f %7.1f %4d"
        " %7.1f %7d %7.1f %7d %6d %3s"
        % (c["q"], c["kappa"], c["theta_fed"], c["theta_macro"],
           c["center_share"], d["CENTER"], d["I"], d["II"], d["III"], d["IV"],
           c["quad_spell_mean"], c["quad_spell_median"], c["pairs_ok"],
           c["delay_median"], c["delay_max"], c["hold_median"], c["hold_max"],
           c["delay_n"],
           ("A" if c["req_A"] else "-") + ("B" if c["req_B"] else "-")))

sub("9.2 Matrica doli Centra (stroki -- q, stolbcy -- kappa)")
say("  %5s " % "q" + " ".join("%6.2f" % k for k in K_GRID))
for q in Q_GRID:
    say("  %5.2f " % q + " ".join("%6.3f" % BY_QK[(q, k)]["center_share"]
                                  for k in K_GRID))

sub("9.3 Matrica sredney dlitel'nosti spella v kvadrante, dney")
say("  %5s " % "q" + " ".join("%6.2f" % k for k in K_GRID))
for q in Q_GRID:
    say("  %5.2f " % q + " ".join("%6.1f" % BY_QK[(q, k)]["quad_spell_mean"]
                                  for k in K_GRID))

sub("9.4 Matrica: A / B / AB / '.' (nichego)")
say("  %5s " % "q" + " ".join("%4.2f" % k for k in K_GRID))
for q in Q_GRID:
    row = []
    for k in K_GRID:
        c = BY_QK[(q, k)]
        row.append("AB" if (c["req_A"] and c["req_B"]) else
                   ("A" if c["req_A"] else ("B" if c["req_B"] else ".")))
    say("  %5.2f " % q + " ".join("%4s" % x for x in row))


# =========================================================================== #
# 10. Otvet na glavnyy vopros
# =========================================================================== #

head("10. Sushchestvuet li para (q, kappa), berushchaya A i B odnovremenno")
say(KONTROL_WORD)

A_SET = [c for c in CELLS if c["req_A"]]
B_SET = [c for c in CELLS if c["req_B"]]
AB_SET = [c for c in CELLS if c["req_A"] and c["req_B"]]

say("  yacheek vsego:                      %4d" % len(CELLS))
say("  udovletvoryayut trebovaniyu A:      %4d" % len(A_SET))
say("  udovletvoryayut trebovaniyu B:      %4d" % len(B_SET))
say("  udovletvoryayut oboim (A i B):      %4d" % len(AB_SET))
say("")
if AB_SET:
    say("  MNOZHESTVO RESHENIY NEPUSTO.")
else:
    say("  MNOZHESTVO RESHENIY PUSTO.")

sub("10.1 Forma svyazi: gde lezhat A-dopustimye i B-dopustimye")
say("  A-dopustimye po kappa (dlya kazhdogo kappa -- diapazon q):")
for k in K_GRID:
    qs = [c["q"] for c in A_SET if c["kappa"] == k]
    say("    kappa=%.2f  %s" % (k, ("q %.2f .. %.2f, uzlov %d"
                                    % (min(qs), max(qs), len(qs)))
                                if qs else "net ni odnogo uzla"))
say("  B-dopustimye po kappa:")
for k in K_GRID:
    qs = [c["q"] for c in B_SET if c["kappa"] == k]
    say("    kappa=%.2f  %s" % (k, ("q %.2f .. %.2f, uzlov %d"
                                    % (min(qs), max(qs), len(qs)))
                                if qs else "net ni odnogo uzla"))

sub("10.2 Naskol'ko nedostizhimo to, chto nedostizhimo")
_best_B_in_A = max(A_SET, key=lambda c: c["quad_spell_mean"]) if A_SET else None
if _best_B_in_A:
    say("  Maksimum sredney dlitel'nosti spella SREDI A-dopustimyh:")
    say("    %.1f dnya pri q=%.2f kappa=%.2f (trebuetsya %d; nedobor %.1f dnya,"
        " to est' v %.2f raza)"
        % (_best_B_in_A["quad_spell_mean"], _best_B_in_A["q"],
           _best_B_in_A["kappa"], REQ_B_DAYS,
           REQ_B_DAYS - _best_B_in_A["quad_spell_mean"],
           REQ_B_DAYS / _best_B_in_A["quad_spell_mean"]
           if _best_B_in_A["quad_spell_mean"] else float("inf")))
_max_spell = max(CELLS, key=lambda c: c["quad_spell_mean"])
say("  Maksimum sredney dlitel'nosti spella po VSEY setke:")
say("    %.1f dnya pri q=%.2f kappa=%.2f (dolya Centra tam %.3f)"
    % (_max_spell["quad_spell_mean"], _max_spell["q"], _max_spell["kappa"],
       _max_spell["center_share"]))
if B_SET:
    _cs = sorted(c["center_share"] for c in B_SET)
    say("  Dolya Centra sredi B-dopustimyh: min %.3f, mediana %.3f, max %.3f"
        % (_cs[0], median(_cs), _cs[-1]))
    _near = min(B_SET, key=lambda c: min(abs(c["center_share"] - REQ_A_LO),
                                         abs(c["center_share"] - REQ_A_HI)))
    say("    blizhayshaya k polose [%.2f .. %.2f]: %.3f pri q=%.2f kappa=%.2f"
        % (REQ_A_LO, REQ_A_HI, _near["center_share"], _near["q"],
           _near["kappa"]))

sub("10.3 Predel konstrukcii pri theta_lo -> 0 (GRANICA, a NE uzel setki)")
say("  Zachem. Setka ob'yavlena do raschyota i ne rasshiryaetsya (sec.9 zap.1).")
say("  No vopros 'a ne zakroet li razryv eshchyo men'shiy kappa' ostalsya by")
say("  otkrytym. On zakryvaetsya ne rasshireniem poiska, a GRANICEY: pri")
say("  theta_lo -> 0 os' otpuskaet znak tol'ko pri perehode score cherez nol' --")
say("  eto predel togo, chto gisterezis voobshche mozhet sdelat'. kappa = 0")
say("  RESHENIEM BYT' NE MOZHET: sec.1.4.10 trebuet kappa iz (0, 1]. Nizhe --")
say("  verhnyaya granica, a ne kandidat. (sec.11 zapis' 3)")
LIMIT_ROWS: list[dict[str, Any]] = []
for q in Q_GRID:
    th_f = quantile(ABS_F, q)
    th_m = quantile(ABS_M, q)
    sf_s = hyst_signs(SF4, th_f, 0.0)
    sm_s = hyst_signs(SM4, th_m, 0.0)
    daily = states_of(sf_s, sm_s, None)
    mons = {m: daily[MONTH_END_IDX[m]] for m in MONTHS}
    dist = {}
    for m in MONTHS:
        dist[mons[m]] = dist.get(mons[m], 0) + 1
    qsp = quad_spell_stats(GRID, daily)
    LIMIT_ROWS.append({"q": q, "center_share": dist.get("CENTER", 0) / len(MONTHS),
                       "quad_spell_mean": qsp["mean_days"],
                       "n_quad_spells": qsp["n_spells"]})
_lim_A = [r for r in LIMIT_ROWS if REQ_A_LO <= r["center_share"] <= REQ_A_HI]
_lim_best = max(_lim_A, key=lambda r: r["quad_spell_mean"]) if _lim_A else None
_lim_max = max(LIMIT_ROWS, key=lambda r: r["quad_spell_mean"])
say("  %6s %8s %8s %8s" % ("q", "Centr", "spell", "spellov"))
for r in LIMIT_ROWS:
    if REQ_A_LO - 0.06 <= r["center_share"] <= REQ_A_HI + 0.06:
        say("  %6.2f %8.3f %8.1f %8d%s"
            % (r["q"], r["center_share"], r["quad_spell_mean"],
               r["n_quad_spells"],
               "   <- v polose A" if REQ_A_LO <= r["center_share"] <= REQ_A_HI
               else ""))
if _lim_best:
    say("  V PREDELE maksimum spella sredi A-dopustimyh: %.1f dnya pri q=%.2f"
        % (_lim_best["quad_spell_mean"], _lim_best["q"]))
    say("  Trebuetsya %d. Nedobor v predele: %.1f dnya (v %.2f raza)."
        % (REQ_B_DAYS, REQ_B_DAYS - _lim_best["quad_spell_mean"],
           REQ_B_DAYS / _lim_best["quad_spell_mean"]))
    say("  -> Razryv ne zakryvaetsya NIKAKIM kappa: dazhe v nedostizhimom"
        " predele.")
say("  V PREDELE maksimum spella po vsem q: %.1f pri q=%.2f (Centr %.3f)"
    % (_lim_max["quad_spell_mean"], _lim_max["q"], _lim_max["center_share"]))
RESULT["theta_lo_zero_limit"] = {
    "rows": LIMIT_ROWS,
    "best_within_A": _lim_best,
    "max_overall": _lim_max,
    "note": "kappa=0 ne dopustim (sec.1.4.10: kappa iz (0,1]); eto granica"}

sub("10.4 Vybor vnutri mnozhestva resheniy (pravilo HYPOTHESIS sec.7.2)")
if AB_SET:
    CHOSEN = sorted(AB_SET, key=lambda c: (-c["kappa"],
                                           abs(c["center_share"] - 0.20),
                                           c["q"]))[0]
    CHOSEN_KIND = "reshenie"
    say("  Pravilo: maksimal'nyy kappa; pri ravenstve -- dolya Centra blizhe k")
    say("  0.20; pri ravenstve -- naimen'shiy q. Ob'yavleno do raschyota.")
else:
    say("  Mnozhestvo pusto -> beryotsya OPORNAYA yacheyka (sec.7.2): ta, chto")
    say("  maksimiziruet srednyuyu dlitel'nost' spella sredi A-dopustimyh.")
    pool = A_SET if A_SET else CELLS
    CHOSEN = sorted(pool, key=lambda c: (-c["quad_spell_mean"], -c["kappa"],
                                         abs(c["center_share"] - 0.20),
                                         c["q"]))[0]
    CHOSEN_KIND = "opornaya yacheyka (mnozhestvo resheniy pusto)"
say("  Vybrano (%s): q=%.2f kappa=%.2f" % (CHOSEN_KIND, CHOSEN["q"],
                                           CHOSEN["kappa"]))


# =========================================================================== #
# 11. Podrobnyy razbor vybrannoy (opornoy) yacheyki
# =========================================================================== #

head("11. Podrobnyy razbor: q=%.2f kappa=%.2f" % (CHOSEN["q"], CHOSEN["kappa"]))
say(KONTROL_WORD)

_q, _kap = CHOSEN["q"], CHOSEN["kappa"]
_thf, _thm = CHOSEN["theta_fed"], CHOSEN["theta_macro"]
_sf_s = hyst_signs(SF4, _thf, _kap * _thf)
_sm_s = hyst_signs(SM4, _thm, _kap * _thm)
_daily = states_of(_sf_s, _sm_s, None)
_mons = {m: _daily[MONTH_END_IDX[m]] for m in MONTHS}
_base_f, _base_m = BASE_SIGNS[_q]

say("  theta_hi = (%.4f, %.4f), theta_lo = (%.4f, %.4f)"
    % (_thf, _thm, _kap * _thf, _kap * _thm))
say("  Centr %.4f (%d mes.) | kvadranty %.4f | ANOMALY %d"
    % (CHOSEN["center_share"], CHOSEN["center_months"], CHOSEN["quad_share"],
       CHOSEN["anomaly_months"]))
say("  raspredelenie: %s" % {k: CHOSEN["dist"][k] for k in STATES})
say("  spellov v kvadrante %d, srednyaya %.2f dn., mediana %.1f dn."
    % (CHOSEN["n_quad_spells"], CHOSEN["quad_spell_mean"],
       CHOSEN["quad_spell_median"]))
say("  trebovanie A (%.2f..%.2f): %s | trebovanie B (>=%d dn.): %s"
    % (REQ_A_LO, REQ_A_HI, "VZYATO" if CHOSEN["req_A"] else "NE VZYATO",
       REQ_B_DAYS, "VZYATO" if CHOSEN["req_B"] else "NE VZYATO"))
say("  par s n >= 24: %d iz 14; n po param: %s"
    % (CHOSEN["pairs_ok"], CHOSEN["pairs_n"]))
say("  ustoychivost': kvadrantnyh mes. 2004-2014 %d/%d, 2015-2026 %d/%d"
    % (CHOSEN["cal_quad"], len(CAL_MONTHS), CHOSEN["oos_quad"],
       len(OOS_MONTHS)))

sub("11.1 Zaderzhka na razvorotah -- raspredelenie, obe mery")
_dl_f, _hd_f = reversal_delays(_base_f, _sf_s, GRID)
_dl_m, _hd_m = reversal_delays(_base_m, _sm_s, GRID)
_dl = sorted(_dl_f + _dl_m)
_hd = sorted(_hd_f + _hd_m)
say("  razvorotov: os' FED %d, os' MACRO %d, vsego %d"
    % (len(_dl_f), len(_dl_m), len(_dl)))
if len(_dl) < MIN_EVENTS_FOR_QUARTILES:
    say("  VNIMANIE: sobytiy men'she %d -- raspredelenie iz %d tochek"
        " raspredeleniem ne yavlyaetsya (HYPOTHESIS sec.7.3)"
        % (MIN_EVENTS_FOR_QUARTILES, len(_dl)))
for _nm, _arr in (("LAST (pred-registrirovannaya, sec.5.1)", _dl),
                  ("HOLD (soprovozhdayushchaya, sec.11 zap.2)", _hd)):
    if not _arr:
        continue
    say("  %s:" % _nm)
    say("    min %d | 25%% %.1f | mediana %.1f | 75%% %.1f | max %d |"
        " srednee %.1f"
        % (_arr[0], quantile(_arr, 0.25), quantile(_arr, 0.50),
           quantile(_arr, 0.75), _arr[-1], sum(_arr) / len(_arr)))
    _hist: dict[str, int] = {}
    for x in _arr:
        b = ("0" if x == 0 else "1-7" if x <= 7 else "8-30" if x <= 30 else
             "31-90" if x <= 90 else "91-365" if x <= 365 else "366+")
        _hist[b] = _hist.get(b, 0) + 1
    say("    gistogramma: %s" % dict(sorted(_hist.items())))
say("  dolya dney, gde znak osi otlichaetsya ot kappa=1: %.4f"
    % CHOSEN["held_days_share"])

sub("11.2 Zaderzhka po vsey setke: cena trebovaniya B")
say("  Stroki: vse B-dopustimye, vse A-dopustimye i ves' sloy kappa=1.")
say("  %5s %5s %3s %7s %7s %7s %7s %7s %6s"
    % ("q", "kappa", "AB", "spell", "LASTmed", "LAST75", "HOLDmed", "HOLDmax",
       "n"))
for c in CELLS:
    if c["req_B"] or c["req_A"] or c["kappa"] == 1.00:
        say("  %5.2f %5.2f %3s %7.1f %7.1f %7.1f %7.1f %7d %6d"
            % (c["q"], c["kappa"],
               ("A" if c["req_A"] else "-") + ("B" if c["req_B"] else "-"),
               c["quad_spell_mean"], c["delay_median"], c["delay_q75"],
               c["hold_median"], c["hold_max"], c["delay_n"]))

sub("11.3 Flag uverennosti")
say("  (a) struktura golosovaniya po 270 mesyacam -- ot (q, kappa) NE zavisit:")
_vote_dist: dict[str, int] = {}
for m in MONTHS:
    v, n = VOTE_V2[MONTH_END_IDX[m]]
    key = "%s/%d" % (v, n) if v is not None else "None/0"
    _vote_dist[key] = _vote_dist.get(key, 0) + 1
say("      %s" % dict(sorted(_vote_dist.items())))
say("  (b) pyatiznachnyy flag na vybrannoy yacheyke:")
_fl = CHOSEN["flags"]
for k in FLAGS:
    say("      %-28s %4d  (%.3f)  -- %s"
        % (k, _fl[k], _fl[k] / len(MONTHS), FLAG_RU[k]))
_named = len(MONTHS) - _fl["NO_STATE"]
if _named:
    say("      sredi %d mesyacev s nazvannym kvadrantom: podtverzhdena"
        " (sil'naya+slabaya) %d (%.3f), protivorechit %d (%.3f)"
        % (_named, _fl["STRONG"] + _fl["WEAK"],
           (_fl["STRONG"] + _fl["WEAK"]) / _named,
           _fl["CONTRADICTS"], _fl["CONTRADICTS"] / _named))
say("  (v) lift soglasiya na vybrannoy yacheyke -- chtoby dolya 'podtverzhdena'")
say("      byla chitaema: nablyudyonnaya dolya sovpadeniy protiv ozhidaniya pri")
say("      nezavisimosti, na mesyacah, gde I sostoyanie, I golosovanie nazyvayut")
say("      kvadrant.")
_sel = [m for m in MONTHS
        if _mons[m] in QUADS and VOTE_V2[MONTH_END_IDX[m]][0] in QUADS]
if _sel:
    _obs = sum(1 for m in _sel
               if _mons[m] == VOTE_V2[MONTH_END_IDX[m]][0]) / len(_sel)
    _ps = {x: sum(1 for m in _sel if _mons[m] == x) / len(_sel) for x in QUADS}
    _qs = {x: sum(1 for m in _sel
                  if VOTE_V2[MONTH_END_IDX[m]][0] == x) / len(_sel)
           for x in QUADS}
    _exp = sum(_ps[x] * _qs[x] for x in QUADS)
    say("      mesyacev v sverke %d | nablyudeno %.3f | ozhidanie %.3f |"
        " lift %.3f" % (len(_sel), _obs, _exp,
                        (_obs / _exp) if _exp > 0 else float("nan")))
    say("      raspredelenie sostoyaniy %s protiv formy %s"
        % ({x: round(_ps[x], 3) for x in QUADS},
           {x: round(_qs[x], 3) for x in QUADS}))
    RESULT["chosen_shape_coherence"] = {
        "n": len(_sel), "observed": _obs, "expected": _exp,
        "lift": (_obs / _exp) if _exp > 0 else None}
say("  (g) flag po vsem A-dopustimym yacheykam (razbros doli 'podtverzhdena'):")
if A_SET:
    _sh = sorted((c["flags"]["STRONG"] + c["flags"]["WEAK"]) /
                 max(1, len(MONTHS) - c["flags"]["NO_STATE"]) for c in A_SET)
    say("      min %.3f | mediana %.3f | max %.3f (po %d yacheykam)"
        % (_sh[0], median(_sh), _sh[-1], len(_sh)))

sub("11.4 Pomesyachnye sostoyaniya vybrannoy yacheyki (pervye i poslednie 12)")
_ms = [(m, _mons[m]) for m in MONTHS]
for m, st in _ms[:12] + [("...", "...")] + _ms[-12:]:
    say("    %-8s %s" % (m, st))


# =========================================================================== #
# 12. Storozha discipliny -- pechat'
# =========================================================================== #

head("12. Storozha discipliny (HYPOTHESIS sec.1.3)")
say(KONTROL_WORD)
say("  Simvoly Yahoo, zaproshennye za ves' progon: %s" % sorted(set(YAHOO_ASKED)))
say("  Iz nih v svyortke v2 uchastvuet: %s" % sorted(YAHOO_V2_ONLY))
say("  Ostal'nye chetyre -- tol'ko dlya kontrolya vosproizvedeniya Z05 (D0).")
assert set(YAHOO_ASKED) <= YAHOO_ALLOWED
assert not (set(YAHOO_ASKED) & YAHOO_FORBIDDEN)
say("  Instrumentov par vne belogo spiska zaprosheno: 0")
say("  Klyuchi Z05/result.json, prochitannye za progon: %s" % sorted(Z05_READ))
assert set(Z05_READ) <= Z05_ALLOWED
say("  Zapreshchyonnyh klyuchey prochitano: 0")
_fns = sorted(k for k, v in list(globals().items()) if callable(v)
              and getattr(v, "__module__", None) == "__main__")
say("  Funkcii, opredelyonnye v module (%d):" % len(_fns))
say("    " + ", ".join(_fns))
_susp = [f for f in _fns if any(w in f.lower()
                                for w in ("fwd", "forward", "return", "ret_",
                                          "pnl", "price"))]
say("  Iz nih s priznakami raschyota dohodnosti: %d %s" % (len(_susp), _susp))
assert not _susp, "v module poyavilas' funkciya s priznakami dohodnosti"
RESULT["discipline"] = {"yahoo_asked": sorted(set(YAHOO_ASKED)),
                        "yahoo_in_v2": sorted(YAHOO_V2_ONLY),
                        "z05_keys_read": sorted(Z05_READ),
                        "functions": _fns, "suspicious": _susp}


# =========================================================================== #
# 13. Zapis'
# =========================================================================== #

RESULT["config"] = {
    "window": {"first": MONTHS[0], "last": MONTHS[-1], "months": len(MONTHS),
               "grid_days": len(GRID), "calendar_days": WINDOW_CAL_DAYS},
    "composition": {k: {"note": v["note"], "fed": v["fed"], "macro": v["macro"],
                        "fed_weight": round(sum(v["fed"].values()), 10),
                        "macro_weight": round(sum(v["macro"].values()), 10)}
                    for k, v in D_LEVELS.items()},
    "cutoff": CUTOFF, "axis_window": AXIS_WINDOW, "shape_windows": list(WINDOWS),
    "parallel_bp": PARALLEL_BP, "umcsent_threshold": UMC_THRESHOLD,
    "requirement_A": [REQ_A_LO, REQ_A_HI], "requirement_B_days": REQ_B_DAYS,
    "degenerate_n": DEGEN_N,
    "q_grid": Q_GRID, "kappa_grid": K_GRID}
RESULT["cells"] = CELLS
RESULT["answer"] = {
    "solution_set_empty": not AB_SET,
    "n_cells": len(CELLS), "n_A": len(A_SET), "n_B": len(B_SET),
    "n_AB": len(AB_SET),
    "AB_cells": [[c["q"], c["kappa"]] for c in AB_SET],
    "A_cells": [[c["q"], c["kappa"]] for c in A_SET],
    "B_cells": [[c["q"], c["kappa"]] for c in B_SET],
    "chosen": {"kind": CHOSEN_KIND, "q": CHOSEN["q"], "kappa": CHOSEN["kappa"]},
    "max_spell_within_A": ({"q": _best_B_in_A["q"],
                            "kappa": _best_B_in_A["kappa"],
                            "quad_spell_mean": _best_B_in_A["quad_spell_mean"]}
                           if _best_B_in_A else None),
    "max_spell_overall": {"q": _max_spell["q"], "kappa": _max_spell["kappa"],
                          "quad_spell_mean": _max_spell["quad_spell_mean"],
                          "center_share": _max_spell["center_share"]}}
RESULT["chosen_cell"] = CHOSEN
RESULT["chosen_monthly_states"] = _mons
RESULT["chosen_monthly_flags"] = {
    m: flag_of(VOTE_V2[MONTH_END_IDX[m]], _mons[m]) for m in MONTHS}
RESULT["chosen_delays"] = {"last_fed": _dl_f, "last_macro": _dl_m,
                           "hold_fed": _hd_f, "hold_macro": _hd_m}
RESULT["vote_structure_270"] = _vote_dist
RESULT["monthly_shape_vote"] = {
    m: {"value": VOTE_V2[MONTH_END_IDX[m]][0],
        "windows_agreed": VOTE_V2[MONTH_END_IDX[m]][1]} for m in MONTHS}
RESULT["data_passport"] = {
    k: {"n": len(observed(v)), "first": v.dates[0] if v.dates else None,
        "last": v.dates[-1] if v.dates else None}
    for k, v in RAW.items() if hasattr(v, "dates")}

_payload = json.dumps(RESULT, ensure_ascii=False, indent=1, sort_keys=True,
                      default=str)
with open(os.path.join(_HERE, "result.json"), "w", encoding="utf-8",
          newline="\n") as fh:
    fh.write(_payload)

say("")
say("result.json zapisan; sha256 = %s"
    % hashlib.sha256(_payload.encode("utf-8")).hexdigest())
say("Vremeni na progon: %.1f s (v result.json vremya NE pishetsya --"
    " trebovanie pobitovogo determinizma)" % (time.time() - _T0))
say(KONTROL_WORD + " -- konec progona")
