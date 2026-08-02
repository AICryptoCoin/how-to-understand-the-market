#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z27 -- razbor konstrukcii klassifikatora po ogranichitelyam.

Chetyre ogranichitelya (validator formy krivoy, porogi theta, setka, sostav
vhodov) razbirayutsya po otdel'nosti i vsemi sochetaniyami. Meryaetsya
STRUKTURA SOSTOYANIY. Dohodnosti ne otkryvayutsya ni razu -- sm. sec.1
HYPOTHESIS.md i storozha nizhe (_yahoo, _z05, spisok funkciy).

Vsyo pechataemoe -- ASCII: konsol' etoy mashiny v cp1251.

    python run.py            # polnyy progon
    python run.py --quick    # sokrashchyonnaya setka q (otladka koda)

Pred-registraciya -- HYPOTHESIS.md, kommit c482d94, do pervogo raschyota.
"""

from __future__ import annotations

import bisect
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

RESULT: dict[str, Any] = {"task": "Z27", "quick": QUICK}


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

# Cenovye ryady, kotorye RAZRESHENO gruzit': chetyre -- vhody osey po
# sec.1.4.3-1.4.4 speki, pyatyy -- kandidat zameny (variant D4/D5).
# Instrumentom ni odnoy iz 14 par ni odin iz nih ne yavlyaetsya... krome
# treh, kotorye yavlyayutsya i vhodami, i celyami (DXY, GC, CL) -- imenno
# radi ustraneniya etogo peresecheniya i stroyatsya varianty D1..D5.
YAHOO_ALLOWED = {"DX-Y.NYB", "GC=F", "HG=F", "CL=F", "ZQ=F"}
YAHOO_ASKED: list[str] = []

# Instrumenty par, kotorye ZAPRESHCHENO gruzit' vovse.
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
AXIS_WINDOW = 10                 # okno osey vo vseh variantah (sec.6.1)
WINDOWS = (5, 10, 30)

Q_STEP = 0.10 if QUICK else 0.02
Q_GRID = [round(i * Q_STEP, 4) for i in range(int(round(0.60 / Q_STEP)) + 1)]

MIN_SPELL_DAYS = 30              # trebovanie B
CENTER_TARGET = 0.20             # trebovanie A

DEGEN_N = 24                     # n/L>=8 pri L=3, h=1 (Z05 sec.7.2)
S1_MIN = 0.20
S3_MIN_SHARE = 0.05
S4_MIN_PAIRS = 8

QUADS = ("I", "II", "III", "IV")
STATES = ("CENTER", "I", "II", "III", "IV", "ANOMALY")
QUAD_OF = {("+", "-"): "I", ("+", "+"): "II",
           ("-", "-"): "III", ("-", "+"): "IV"}
# Poryadok razresheniya nich'ih pri modal'noy agregacii (sec.6.3):
# pobezhdaet CENTER, esli on sredi liderov; inache I, II, III, IV, ANOMALY.
TIE_ORDER = ("CENTER", "I", "II", "III", "IV", "ANOMALY")


# =========================================================================== #
# 2. Melkie instrumenty (perenos Z05 sec.1)
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

head("Z27 -- razbor konstrukcii klassifikatora po ogranichitelyam")
say("Dohodnosti ne otkryvayutsya. Storozha: _yahoo (belyy spisok simvolov),")
say("_z05 (belyy spisok klyuchey), otsutstvie funkciy s gorizontom.")
say("Setka q: %d uzlov, %.2f .. %.2f (shag %.2f)%s"
    % (len(Q_GRID), Q_GRID[0], Q_GRID[-1], Q_STEP, "  [QUICK]" if QUICK else ""))

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

sub("3.2 Predposylka: lestnica Z06 (ta zhe proverka, chto v Z05)")

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

sub("4.1 Setki (HYPOTHESIS sec.4)")

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
say("  kalibrovochnyy otrezok: %s .. %s, %d dney"
    % (GRID[CALIB_IDX[0]], GRID[CALIB_IDX[-1]], len(CALIB_IDX)))

# Nedel'naya setka: posledniy den' setki v kazhdoy ISO-nedele.
_wk: dict[tuple[int, int], str] = {}
for d in GRID:
    y, w, _ = d2(d).isocalendar()
    _wk[(y, w)] = max(_wk.get((y, w), ""), d)
WEEK_DAYS = sorted(_wk.values())
say("  nedel'naya setka: %d nedel'" % len(WEEK_DAYS))

# Kakie dni / nedeli otnosyatsya k kakomu otchyotnomu mesyacu.
MONTH_SET = set(MONTHS)
DAYS_OF_MONTH: dict[str, list[int]] = {m: [] for m in MONTHS}
for i, d in enumerate(GRID):
    m = mkey(d)
    if m in MONTH_SET:
        DAYS_OF_MONTH[m].append(i)
WEEKS_OF_MONTH: dict[str, list[int]] = {m: [] for m in MONTHS}
for d in WEEK_DAYS:
    m = mkey(d)
    if m in MONTH_SET:
        WEEKS_OF_MONTH[m].append(GRID_IDX[d])
MONTH_END_IDX = {m: GRID_IDX[MONTH_END[m]] for m in MONTHS}
say("  dney v mesyace: min %d, max %d; nedel' v mesyace: min %d, max %d"
    % (min(len(v) for v in DAYS_OF_MONTH.values()),
       max(len(v) for v in DAYS_OF_MONTH.values()),
       min(len(v) for v in WEEKS_OF_MONTH.values()),
       max(len(v) for v in WEEKS_OF_MONTH.values())))

CAL_MONTHS = [m for m in MONTHS if m <= CALIB_END[:7]]
OOS_MONTHS = [m for m in MONTHS if m >= OOS_START[:7]]


# =========================================================================== #
# 5. Vklady vhodov (perenos Z05 sec.4 bez izmeneniya formul)
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

# UMCSENT -- kandidat zameny (sec.6.4). Porog urovnya = mediana ryada na
# KALIBROVOCHNOM otrezke: ni speka, ni priroda indeksa poroga ne dayut,
# a brat' medianu vsego okna znachilo by dat' vhodu znanie budushchego.
_umc = {mkey(d): v for d, v in observed(RAW["UMCSENT"])}
_umc_calib = [v for m, v in _umc.items() if WIN_START[:7] <= m <= CALIB_END[:7]]
UMC_THRESHOLD = median(_umc_calib)
C_UMC = monthly_level(_umc, UMC_THRESHOLD)
say("  NAHB %d | PERMIT %d | kompozit %d | NOF %d | IC4WSA %d nedel'"
    % (len(C_NAHB), len(C_PERMIT), len(C_COMP), len(C_NOF), len(C_CLAIMS)))
say("  UMCSENT: porog urovnya = mediana kalibrovochnogo otrezka = %.2f,"
    " mesyacev vklada %d" % (UMC_THRESHOLD, len(C_UMC)))

_vkl = {}
for _v in C_COMP.values():
    _vkl[round(_v, 4)] = _vkl.get(round(_v, 4), 0) + 1
say("  kontrol' Z06: vklad kompozita po znacheniyam = %s"
    % dict(sorted(_vkl.items(), reverse=True)))
assert _vkl.get(1.0) == 149 and _vkl.get(0.2) == 38 \
    and _vkl.get(-0.2) == 120 and _vkl.get(-1.0) == 83, \
    "vklad kompozita ne vosproizvyol Z06 (149/38/120/83)"

PUB = {"NAHB": (0, 16), "PERMIT": (1, 20), "COMP": (0, 28), "NOF": (0, 21),
       # U. Michigan: predvaritel'naya ocenka ~15-e, final ~konec mesyaca t.
       # Beryotsya konservativno -- konec mesyaca t (lag 0, den' 28), tak zhe
       # kak u kompozita: pozdneyshaya iz dostupnyh publikaciy mesyaca.
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

# Osi vo VSEH variantah schitayutsya na okne 10 (sec.6.1): variant A menyaet
# tol'ko chtenie formy krivoy, no ne okno osey.
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

sub("5.4 Forma krivoy")


def shape_at(iso: str, W: int, *, parallel_rule: bool) -> str | None:
    a, b = ST_DGS2.at(iso), ST_DGS2.at(shift_days(iso, W))
    c, e = ST_DGS10.at(iso), ST_DGS10.at(shift_days(iso, W))
    if None in (a, b, c, e):
        return None
    dk, dl = a - b, c - e
    dspread = dl - dk
    if parallel_rule and abs(dspread) < PARALLEL_BP:
        return "PARALLEL"
    up = (dk + dl) / 2.0 > 0
    if not up and dspread < 0:
        return "I"
    if not up and dspread > 0:
        return "II"
    if up and dspread < 0:
        return "III"
    return "IV"


SHAPE = {W: [shape_at(d, W, parallel_rule=True) for d in GRID] for W in WINDOWS}
SHAPE_NP = {W: [shape_at(d, W, parallel_rule=False) for d in GRID]
            for W in WINDOWS}
for W in WINDOWS:
    cnt: dict[str, int] = {}
    for v in SHAPE[W]:
        cnt[str(v)] = cnt.get(str(v), 0) + 1
    say("  okno %2d dn.: %s" % (W, dict(sorted(cnt.items()))))


# =========================================================================== #
# 6. Sostavy osey (variant D) i predschyot ochkov
# =========================================================================== #

head("6. Sostavy osey (variant D) i predschyot ochkov")

W_FED_BASE = {"us2y": 0.25, "real5": 0.15, "phase": 0.15, "dxy": 0.10}
W_MACRO_BASE = {"nahb": 0.13, "permit": 0.13, "comp": 0.10, "claims": 0.12,
                "nof": 0.08, "hggc": 0.04, "clgc": 0.04}
FULL = 1.00


def _wo(d: dict[str, float], *keys: str) -> dict[str, float]:
    return {k: v for k, v in d.items() if k not in keys}


D_LEVELS: dict[str, dict[str, Any]] = {
    "D0": {"fed": dict(W_FED_BASE), "macro": dict(W_MACRO_BASE),
           "note": "kak est'"},
    "D1": {"fed": dict(W_FED_BASE), "macro": _wo(W_MACRO_BASE, "hggc", "clgc"),
           "note": "bez rynochnyh proksi v MACRO"},
    "D2": {"fed": _wo(W_FED_BASE, "dxy"), "macro": dict(W_MACRO_BASE),
           "note": "bez DXY v FED"},
    "D3": {"fed": _wo(W_FED_BASE, "dxy"), "macro": _wo(W_MACRO_BASE, "hggc", "clgc"),
           "note": "bez proksi i bez DXY (zadanie D-b)"},
    "D4": {"fed": dict(_wo(W_FED_BASE, "dxy"), zq=0.10),
           "macro": dict(_wo(W_MACRO_BASE, "hggc", "clgc"), umcsent=0.06),
           "note": "zamena: ZQ=F 0.10 + UMCSENT 0.06"},
    "D5": {"fed": dict(_wo(W_FED_BASE, "dxy"), zq=0.30),
           "macro": dict(_wo(W_MACRO_BASE, "hggc", "clgc"), umcsent=0.06),
           "note": "zamena: ZQ=F 0.30 (shchedryy) + UMCSENT 0.06"},
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

# SCORE[D] = spiski po indeksu dnya: sf, sm, doli vesa, kvadrant po znakam.
SCORE: dict[str, dict[str, list]] = {}
for dk, dv in D_LEVELS.items():
    sf_l, sm_l, shf_l, shm_l, quad_l = [], [], [], [], []
    for fed_p, mac_p in PARTS:
        sf, shf = axis(fed_p, dv["fed"])
        sm, shm = axis(mac_p, dv["macro"])
        sf_l.append(sf)
        sm_l.append(sm)
        shf_l.append(shf)
        shm_l.append(shm)
        quad_l.append(None if (sf is None or sm is None) else
                      QUAD_OF[("+" if sf > 0 else "-", "+" if sm > 0 else "-")])
    SCORE[dk] = {"sf": sf_l, "sm": sm_l, "share_f": shf_l, "share_m": shm_l,
                 "quad": quad_l}
    _nf = sum(1 for x in sf_l if x is None)
    _nm = sum(1 for x in sm_l if x is None)
    say("  %-3s dney bez osi FED %4d, bez osi MACRO %4d (iz %d)"
        % (dk, _nf, _nm, len(GRID)))


# =========================================================================== #
# 7. Validator (variant A): verdikt zavisit tol'ko ot (A, den'), a ne ot theta
# =========================================================================== #

A_LEVELS = {
    "A0": "kak est': forma na okne 10, nesovpadenie -> Centr",
    "A1": "golosovanie 2 iz 3 (okna 5/10/30), prinimaetsya bez ponizheniya",
    "A2": "lyuboe iz tryoh okon podtverzhdaet",
    "A3": "flag, a ne veto (kvadrant nazyvaetsya vsegda)",
    "A4": "snyat vovse",
    "A5": "veto bez pravila parallel'nogo sdviga (5 b.p.)",
}


def shape_vote(i: int) -> str | None:
    votes = [SHAPE[W][i] for W in WINDOWS]
    votes = [v for v in votes if v is not None]
    if len(votes) < 2:
        return None
    best, n = None, 0
    for v in set(votes):
        k = votes.count(v)
        if k > n:
            best, n = v, k
    return best if n >= 2 else "NOAGREE"


SHAPE_VOTE = [shape_vote(i) for i in range(len(GRID))]


def validator_ok(a: str, i: int, q: str) -> bool:
    if a in ("A3", "A4"):
        return True
    if a == "A0":
        return SHAPE[10][i] == q
    if a == "A5":
        return SHAPE_NP[10][i] == q
    if a == "A1":
        return SHAPE_VOTE[i] == q
    if a == "A2":
        return any(SHAPE[W][i] == q for W in WINDOWS)
    raise AssertionError("neizvestnyy variant A: %s" % a)


# OK[D][A] -- spisok bool po indeksu dnya (kvadrant po znakam podtverzhdyon).
OKV: dict[str, dict[str, list[bool]]] = {}
for dk in D_LEVELS:
    OKV[dk] = {}
    qs = SCORE[dk]["quad"]
    for a in A_LEVELS:
        OKV[dk][a] = [False if q is None else validator_ok(a, i, q)
                      for i, q in enumerate(qs)]


# =========================================================================== #
# 8. Klassifikaciya, spelly, kalibrovka
# =========================================================================== #

BC_LEVELS = {"OR": "Centr, esli hotya by odna os' nizhe theta",
             "AND": "Centr, tol'ko esli obe osi nizhe theta"}
BQ_LEVELS = {
    "Bq_B": "naimen'shiy q, spell po LYUBOMU sostoyaniyu >= 30 dney (Z05)",
    "Bq_A20": "trebovanie A rovno: q = 0.20",
    "Bq_JOINT": "q, dayushchiy fakticheskuyu dolyu Centra blizhe vsego k 0.20",
    "Bq_BQUAD": "naimen'shiy q, spell TOL'KO v kvadrante >= 30 dney",
}
C_LEVELS = {"C_M": "sostoyanie poslednego dnya mesyaca",
            "C_D": "modal'noe sostoyanie dney mesyaca",
            "C_W": "modal'noe sostoyanie nedel' mesyaca"}


def classify_range(dk: str, a: str, bc: str, tf: float, tm: float,
                   idx: Sequence[int]) -> list[str]:
    sc = SCORE[dk]
    sf_l, sm_l, quad_l = sc["sf"], sc["sm"], sc["quad"]
    ok = OKV[dk][a]
    out: list[str] = []
    ap = out.append
    and_mode = (bc == "AND")
    for i in idx:
        sf = sf_l[i]
        sm = sm_l[i]
        if sf is None or sm is None:
            ap("ANOMALY")
            continue
        lo_f = abs(sf) < tf
        lo_m = abs(sm) < tm
        centre = (lo_f and lo_m) if and_mode else (lo_f or lo_m)
        if centre:
            ap("CENTER")
            continue
        ap(quad_l[i] if ok[i] else "CENTER")
    return out


def spells(dates: Sequence[str], states: Sequence[str]) -> list[tuple[str, int]]:
    """(sostoyanie, dlitel'nost' v kalendarnyh dnyah) po neprepyvnym periodam."""
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


CAL_DATES = [GRID[i] for i in CALIB_IDX]


def calibrate(dk: str, a: str, bc: str, bq: str) -> dict[str, Any]:
    sc = SCORE[dk]
    abs_f = [abs(sc["sf"][i]) for i in CALIB_IDX if sc["sf"][i] is not None]
    abs_m = [abs(sc["sm"][i]) for i in CALIB_IDX if sc["sm"][i] is not None]
    if not abs_f or not abs_m:
        return {"q": float("nan"), "theta_fed": float("nan"),
                "theta_macro": float("nan"), "mean_spell_all": 0.0,
                "quad_spell_mean": 0.0, "center_share": float("nan"),
                "grid": [], "no_admissible_q": True,
                "why": "os' ne schitaetsya ni v odin den' (otsechka)"}
    rows = []
    for q in Q_GRID:
        tf, tm = quantile(abs_f, q), quantile(abs_m, q)
        st = classify_range(dk, a, bc, tf, tm, CALIB_IDX)
        rows.append({
            "q": q, "theta_fed": tf, "theta_macro": tm,
            "mean_spell_all": mean_spell_all(CAL_DATES, st),
            "quad_spell_mean": quad_spell_stats(CAL_DATES, st)["mean_days"],
            "center_share": sum(1 for x in st if x == "CENTER") / len(st),
            "quad_share": sum(1 for x in st if x in QUADS) / len(st),
        })
    chosen, no_adm, why = None, False, ""
    if bq == "Bq_A20":
        chosen = min(rows, key=lambda r: abs(r["q"] - 0.20))
        assert abs(chosen["q"] - 0.20) < 1e-9 or QUICK, "q=0.20 net v setke"
    elif bq == "Bq_JOINT":
        chosen = min(rows, key=lambda r: abs(r["center_share"] - CENTER_TARGET))
        if abs(chosen["center_share"] - CENTER_TARGET) > 0.05:
            no_adm, why = True, ("dolya Centra 0.20 nedostizhima: blizhayshee "
                                 "%.4f" % chosen["center_share"])
    elif bq in ("Bq_B", "Bq_BQUAD"):
        fld = "mean_spell_all" if bq == "Bq_B" else "quad_spell_mean"
        ok = [r for r in rows if r[fld] >= MIN_SPELL_DAYS]
        if ok:
            chosen = min(ok, key=lambda r: r["q"])
        else:
            chosen = rows[-1]
            no_adm = True
            why = ("ni odin q iz setki ne dayot %s >= %d; vzyat maksimal'nyy"
                   % (fld, MIN_SPELL_DAYS))
    else:
        raise AssertionError(bq)
    return dict(chosen, grid=rows, no_admissible_q=no_adm, why=why)


# =========================================================================== #
# 9. Kontrol' vosproizvedeniya Z05 (HYPOTHESIS sec.3.3)
# =========================================================================== #

head("9. Kontrol': vosproizvoditsya li Z05 na etom konveyere")

Z05_THETA = _z05("theta")
Z05_STATES = _z05("monthly_states")
Z05_DIST = _z05("state_distribution")
Z05_VAL = _z05("validator_effect")

_p10 = Z05_THETA["P10"]["chosen"]
say("  Z05 P10: q=%.2f theta_fed=%.4f theta_macro=%.4f"
    % (_p10["q"], _p10["theta_fed"], _p10["theta_macro"]))

_daily_p10 = classify_range("D0", "A0", "OR", _p10["theta_fed"],
                            _p10["theta_macro"], range(len(GRID)))
_mine = {m: _daily_p10[MONTH_END_IDX[m]] for m in MONTHS}
_diff = [m for m in MONTHS if _mine[m] != Z05_STATES["P10"][m]]
say("  pri theta Z05: rashozhdeniy pomesyachnyh sostoyaniy s Z05 P10: %d iz %d"
    % (len(_diff), len(MONTHS)))
if _diff:
    for m in _diff[:12]:
        say("    %s  Z27=%s  Z05=%s" % (m, _mine[m], Z05_STATES["P10"][m]))
assert not _diff, "konveyer ne vosproizvyol Z05 P10 -- razbor bessmyslen"

_dist = {}
for m in MONTHS:
    _dist[_mine[m]] = _dist.get(_mine[m], 0) + 1
say("  raspredelenie: %s" % dict(sorted(_dist.items())))
assert _dist == {k: v for k, v in Z05_DIST["P10"].items() if v}, \
    "raspredelenie ne sovpalo s Z05"

# RAW (do predohranitelya) i 84 pogashennyh mesyaca -- pri theta Z05.
_raw_month = {}
for m in MONTHS:
    i = MONTH_END_IDX[m]
    sf, sm = SCORE["D0"]["sf"][i], SCORE["D0"]["sm"][i]
    if sf is None or sm is None:
        _raw_month[m] = "ANOMALY"
    elif abs(sf) < _p10["theta_fed"] or abs(sm) < _p10["theta_macro"]:
        _raw_month[m] = "CENTER"
    else:
        _raw_month[m] = SCORE["D0"]["quad"][i]
_raw_quad = [m for m in MONTHS if _raw_month[m] in QUADS]
KILLED_84 = [m for m in _raw_quad if _mine[m] == "CENTER"]
say("  kvadrant nazvan porogami: %d mesyacev (Z05: %d)"
    % (len(_raw_quad), Z05_VAL["quadrant_named_by_thresholds"]))
say("  pogasheno predohranitelem: %d mesyacev (Z05: %d)"
    % (len(KILLED_84), Z05_VAL["killed_by_shape"]))
assert len(_raw_quad) == Z05_VAL["quadrant_named_by_thresholds"]
assert len(KILLED_84) == Z05_VAL["killed_by_shape"]

_par = {W: sum(1 for m in MONTHS if SHAPE[W][MONTH_END_IDX[m]] == "PARALLEL")
        for W in WINDOWS}
say("  'parallel'nyy sdvig' po oknam: %s (Z05: %s)"
    % (_par, {int(k): v for k, v in Z05_VAL["parallel_months"].items()}))
assert _par == {int(k): v for k, v in Z05_VAL["parallel_months"].items()}

# A20NOVAL: q=0.20, validator snyat -> 176 kvadrantnyh mesyacev.
_a20 = Z05_THETA["A20NOVAL"]["chosen"]
_d_a20 = classify_range("D0", "A4", "OR", _a20["theta_fed"],
                        _a20["theta_macro"], range(len(GRID)))
_n_a20 = sum(1 for m in MONTHS if _d_a20[MONTH_END_IDX[m]] in QUADS)
say("  A20NOVAL: kvadrantnyh mesyacev %d (Z05: 176)" % _n_a20)
assert _n_a20 == 176, "A20NOVAL ne vosproizvedyon"

# VOTE (= nash A1) na theta Z05 VOTE: 13 kvadrantnyh mesyacev.
_vt = Z05_THETA["VOTE"]["chosen"]
_d_vt = classify_range("D0", "A1", "OR", _vt["theta_fed"], _vt["theta_macro"],
                       range(len(GRID)))
_n_vt = sum(1 for m in MONTHS if _d_vt[MONTH_END_IDX[m]] in QUADS)
say("  VOTE (= A1): kvadrantnyh mesyacev %d (Z05: 13)" % _n_vt)
assert _n_vt == 13, "VOTE ne vosproizvedyon -- perenos A1 nevernyy"

say("  VSE KONTROLI PROYDENY: konveyer -- tot zhe, chto v Z05.")
RESULT["z05_reproduction"] = {
    "monthly_states_mismatch": 0, "distribution": _dist,
    "quadrant_named": len(_raw_quad), "killed_by_shape": len(KILLED_84),
    "parallel_months": _par, "a20noval_quadrant_months": _n_a20,
    "vote_quadrant_months": _n_vt,
    "grid_days_window": len(GRID), "grid_days_warmup": len(GRID_FULL)}


# =========================================================================== #
# 10. Pary: n bez cen (HYPOTHESIS sec.5, velichina V6)
# =========================================================================== #

head("10. Pary: vyrozhdennost' vyborki schitaetsya po tablice predpisaniy")

PAIRS = [p for p in _z05("pairs") if p["key"] != "BETA"]
assert len(PAIRS) == 14, "osnovnoe semeystvo obyazano byt' iz 14 par"
say("  par v semeystve: %d; BETA vne semeystva (Z05 sec.6.3)" % len(PAIRS))


def pair_n(dist: dict[str, int]) -> dict[str, int]:
    """n pary = chislo mesyacev, sostoyanie kotoryh imeet dlya neyo znak."""
    return {p["key"]: sum(dist.get(st, 0) for st in p["signs"])
            for p in PAIRS}


_n_base = pair_n(_dist)
say("  kontrol' na bazovoy yacheyke (Z05 P10, tablica sec.4 otchyota Z05):")
_expect = {"SIZE": 270, "STYLE": 268, "GEO": 270, "TECHMAT": 5,
           "DISCSTAP": 2, "CYCNON": 4, "MATFIN": 2, "DUR": 5, "CRED": 4,
           "GOLD": 7, "COMM": 7, "OIL": 2, "USD": 2, "VIX": 2}
_bad = {k: (v, _expect[k]) for k, v in _n_base.items() if v != _expect[k]}
say("    n po param: %s" % _n_base)
say("    rashozhdeniy s tablicey Z05: %d %s" % (len(_bad), _bad or ""))
assert not _bad, "V6 ne vosproizvyol n iz tablicy Z05"
say("  -> n schitaetsya bez edinoy ceny i sovpadaet s Z05 vo vseh 14 strokah.")

say("")
say("  HYPOTHESIS sec.7.4 utverzhdal TOZHDESTVO: S4>=8 <=> Q-II + Q-III >= 24.")
say("  Perebor iskusstvennyh raspredeleniy (arifmetika, ne dannye) proveryaet")
say("  obe storony po otdel'nosti:")
_suff_ok, _nec_ok = True, True
_ce_suff, _ce_nec = None, None
_min_quad_for_s4 = None
for ii in range(0, 121, 3):
    for iii in range(0, 121, 3):
        for i1 in range(0, 121, 3):
            for i4 in range(0, 121, 3):
                cen = 270 - ii - iii - i1 - i4
                if cen < 0:
                    continue
                dd = {"CENTER": cen, "I": i1, "II": ii, "III": iii, "IV": i4}
                n_ok = sum(1 for v in pair_n(dd).values() if v >= DEGEN_N)
                s4 = n_ok >= S4_MIN_PAIRS
                if (ii + iii >= DEGEN_N) and not s4:
                    _suff_ok, _ce_suff = False, (dd, n_ok)
                if s4 and (ii + iii < DEGEN_N) and _ce_nec is None:
                    _nec_ok, _ce_nec = False, (dd, n_ok)
                if s4:
                    tot = i1 + ii + iii + i4
                    if _min_quad_for_s4 is None or tot < _min_quad_for_s4[0]:
                        _min_quad_for_s4 = (tot, dd, n_ok)
say("    DOSTATOCHNOST' (II+III>=24 => S4>=8): %s%s"
    % (_suff_ok, "" if _suff_ok else "  kontrprimer %s -> %d par" % _ce_suff))
say("    NEOBHODIMOST' (S4>=8 => II+III>=24): %s%s"
    % (_nec_ok, "" if _nec_ok else "  kontrprimer %s -> %d par" % _ce_nec))
say("    minimal'noe chislo kvadrantnyh mesyacev, pri kotorom S4>=8: %d %s"
    % (_min_quad_for_s4[0], _min_quad_for_s4[1]))
say("  -> Pred-registraciya oshiblas' v STORONE 'tol'ko togda': dostatochnost'")
say("     derzhitsya, neobhodimost' net. Vyvod o VYPOLNIMOSTI S4 ot etogo ne")
say("     menyaetsya -- on opiralsya imenno na dostatochnost'. Zapis' v sec.11.")
RESULT["s4_sufficiency_holds"] = _suff_ok
RESULT["s4_necessity_holds"] = _nec_ok
RESULT["s4_necessity_counterexample"] = (
    {"dist": _ce_nec[0], "pairs_ok": _ce_nec[1]} if _ce_nec else None)
RESULT["s4_min_quadrant_months"] = {"total": _min_quad_for_s4[0],
                                    "dist": _min_quad_for_s4[1],
                                    "pairs_ok": _min_quad_for_s4[2]}


# =========================================================================== #
# 11. Polnaya setka variantov
# =========================================================================== #

head("11. Polnaya setka variantov")

D_KEYS = list(D_LEVELS)
A_KEYS = list(A_LEVELS)
BQ_KEYS = list(BQ_LEVELS)
BC_KEYS = list(BC_LEVELS)
C_KEYS = list(C_LEVELS)
say("  A(%d) x Bq(%d) x Bc(%d) x C(%d) x D(%d) = %d yacheek; kalibrovok %d"
    % (len(A_KEYS), len(BQ_KEYS), len(BC_KEYS), len(C_KEYS), len(D_KEYS),
       len(A_KEYS) * len(BQ_KEYS) * len(BC_KEYS) * len(C_KEYS) * len(D_KEYS),
       len(A_KEYS) * len(BQ_KEYS) * len(BC_KEYS) * len(D_KEYS)))

TIES = {"C_D": 0, "C_W": 0}


def modal(states: Sequence[str], tag: str) -> str:
    cnt: dict[str, int] = {}
    for s in states:
        cnt[s] = cnt.get(s, 0) + 1
    top = max(cnt.values())
    leaders = [s for s, k in cnt.items() if k == top]
    if len(leaders) > 1:
        TIES[tag] += 1
    for s in TIE_ORDER:
        if s in leaders:
            return s
    return leaders[0]


def to_months(daily: Sequence[str], c: str) -> dict[str, str]:
    if c == "C_M":
        return {m: daily[MONTH_END_IDX[m]] for m in MONTHS}
    if c == "C_D":
        return {m: modal([daily[i] for i in DAYS_OF_MONTH[m]], "C_D")
                for m in MONTHS}
    if c == "C_W":
        return {m: modal([daily[i] for i in WEEKS_OF_MONTH[m]], "C_W")
                for m in MONTHS}
    raise AssertionError(c)


def shape_months(c: str, W: int) -> dict[str, str]:
    """Forma krivoy, agregirovannaya TEM ZHE pravilom, chto i sostoyanie."""
    src = [str(x) for x in SHAPE[W]]
    if c == "C_M":
        return {m: src[MONTH_END_IDX[m]] for m in MONTHS}
    if c == "C_D":
        return {m: modal([src[i] for i in DAYS_OF_MONTH[m]], "C_D")
                for m in MONTHS}
    return {m: modal([src[i] for i in WEEKS_OF_MONTH[m]], "C_W")
            for m in MONTHS}


_SHAPE_M_CACHE: dict[tuple[str, int], dict[str, str]] = {}
for _c in C_KEYS:
    for _W in (10, 30):
        _SHAPE_M_CACHE[(_c, _W)] = shape_months(_c, _W)
TIES = {"C_D": 0, "C_W": 0}       # sbros: schitaem nich'i tol'ko po sostoyaniyam


def coherence(months: dict[str, str], c: str, W: int) -> dict[str, float]:
    """Lift soglasiya nazvannogo kvadranta s nezavisimym chteniem formy."""
    sh = _SHAPE_M_CACHE[(c, W)]
    sel = [m for m in MONTHS if months[m] in QUADS and sh[m] in QUADS]
    if not sel:
        return {"n": 0, "observed": float("nan"), "expected": float("nan"),
                "lift": float("nan")}
    obs = sum(1 for m in sel if months[m] == sh[m]) / len(sel)
    ps = {q: sum(1 for m in sel if months[m] == q) / len(sel) for q in QUADS}
    qs = {q: sum(1 for m in sel if sh[m] == q) / len(sel) for q in QUADS}
    exp = sum(ps[q] * qs[q] for q in QUADS)
    return {"n": len(sel), "observed": obs, "expected": exp,
            "lift": (obs / exp) if exp > 0 else float("nan")}


CELLS: list[dict[str, Any]] = []
CAL_CACHE: dict[tuple[str, str, str, str], dict[str, Any]] = {}
_t = time.time()
for dk in D_KEYS:
    for a in A_KEYS:
        for bc in BC_KEYS:
            for bq in BQ_KEYS:
                th = calibrate(dk, a, bc, bq)
                CAL_CACHE[(dk, a, bc, bq)] = th
                tf, tm = th["theta_fed"], th["theta_macro"]
                if tf != tf or tm != tm:          # NaN -> os' ne schitaetsya
                    daily = ["ANOMALY"] * len(GRID)
                else:
                    daily = classify_range(dk, a, bc, tf, tm, range(len(GRID)))
                qsp = quad_spell_stats(GRID, daily)
                msp = mean_spell_all(GRID, daily)
                dday: dict[str, int] = {}
                for s in daily:
                    dday[s] = dday.get(s, 0) + 1
                q3_any = sum(1 for m in MONTHS
                             if any(daily[i] == "III" for i in DAYS_OF_MONTH[m]))
                for c in C_KEYS:
                    mons = to_months(daily, c)
                    dist: dict[str, int] = {}
                    for m in MONTHS:
                        dist[mons[m]] = dist.get(mons[m], 0) + 1
                    nq = sum(dist.get(q, 0) for q in QUADS)
                    npairs = pair_n(dist)
                    n_ok = sum(1 for v in npairs.values() if v >= DEGEN_N)
                    smallest = (min(dist.get(q, 0) for q in QUADS) / nq
                                if nq else 0.0)
                    coh10 = coherence(mons, c, 10)
                    coh30 = coherence(mons, c, 30)
                    cal_q = sum(1 for m in CAL_MONTHS if mons[m] in QUADS)
                    oos_q = sum(1 for m in OOS_MONTHS if mons[m] in QUADS)
                    s1 = nq / len(MONTHS)
                    S1 = s1 >= S1_MIN
                    S2 = qsp["mean_days"] >= MIN_SPELL_DAYS
                    S3 = (all(dist.get(q, 0) > 0 for q in QUADS)
                          and dist.get("III", 0) >= 1
                          and smallest >= S3_MIN_SHARE)
                    S4 = n_ok >= S4_MIN_PAIRS
                    CELLS.append({
                        "D": dk, "A": a, "Bc": bc, "Bq": bq, "C": c,
                        "q": th["q"], "theta_fed": tf, "theta_macro": tm,
                        "no_admissible_q": th["no_admissible_q"],
                        "why": th["why"],
                        "center_share": dist.get("CENTER", 0) / len(MONTHS),
                        "quad_share": s1,
                        "dist": {k: dist.get(k, 0) for k in STATES},
                        "q3_months": dist.get("III", 0),
                        "q3_any_day_months": q3_any,
                        "anomaly_months": dist.get("ANOMALY", 0),
                        "n_quad_spells": qsp["n_spells"],
                        "quad_spell_mean": qsp["mean_days"],
                        "quad_spell_median": qsp["median_days"],
                        "mean_spell_all_days": msp,
                        "daily_quad_share": sum(dday.get(q, 0) for q in QUADS)
                        / len(GRID),
                        "pairs_n": npairs, "pairs_ok": n_ok,
                        "smallest_quad_share": smallest,
                        "coh10": coh10, "coh30": coh30,
                        "cal_quad": cal_q, "oos_quad": oos_q,
                        "S1": S1, "S2": S2, "S3": S3, "S4": S4,
                        "S5_informative": a in ("A3", "A4"),
                        "S5_lift": coh10["lift"], "S5x_lift": coh30["lift"],
                        "met": int(S1) + int(S2) + int(S3) + int(S4),
                    })
say("  yacheek poscheno: %d za %.1f s" % (len(CELLS), time.time() - _t))
say("  nich'ih pri modal'noy agregacii: C_D %d, C_W %d (iz %d mesyaco-yacheek)"
    % (TIES["C_D"], TIES["C_W"],
       len(MONTHS) * len(CELLS) // len(C_KEYS)))
RESULT["ties"] = dict(TIES)


def cell_key(c: dict[str, Any]) -> str:
    return "%s|%s|%s|%s|%s" % (c["A"], c["Bq"], c["Bc"], c["C"], c["D"])


BY_KEY = {cell_key(c): c for c in CELLS}
BASE = BY_KEY["A0|Bq_B|OR|C_M|D0"]
TASK_CELL = BY_KEY["A3|Bq_JOINT|OR|C_D|D3"]

sub("11.0 Bazovaya yacheyka i yacheyka zadaniya")
for nm, c in (("BAZA  A0|Bq_B|OR|C_M|D0", BASE),
              ("ZADANIE A3|Bq_JOINT|OR|C_D|D3", TASK_CELL)):
    say("  %s" % nm)
    say("    q=%.2f th=(%.4f, %.4f)%s" % (c["q"], c["theta_fed"],
                                          c["theta_macro"],
                                          "  [dopustimogo q net]"
                                          if c["no_admissible_q"] else ""))
    say("    Centr %.3f | kvadranty %.3f | Q-III %d | ANOMALY %d"
        % (c["center_share"], c["quad_share"], c["q3_months"],
           c["anomaly_months"]))
    say("    spellov v kvadrante %d, srednyaya %.1f dn., mediana %.1f dn."
        % (c["n_quad_spells"], c["quad_spell_mean"], c["quad_spell_median"]))
    say("    par ne vyrozhdeno %d/14 | S1=%s S2=%s S3=%s S4=%s"
        % (c["pairs_ok"], c["S1"], c["S2"], c["S3"], c["S4"]))
say("")
say("  Kontrol' pred-registracii: Bq_B na rasshirennoy setke q dal q=%.2f;"
    % BASE["q"])
say("  Z05 (setka s 0.20) dal q=%.2f. Sovpadenie: %s"
    % (_p10["q"], abs(BASE["q"] - _p10["q"]) < 1e-9))
RESULT["bq_b_vs_z05_q"] = {"z27": BASE["q"], "z05": _p10["q"]}

sub("11.1 Tozhdestvo A3 == A4 (ob'yavleno do raschyota)")
_id_bad = []
for a3 in [c for c in CELLS if c["A"] == "A3"]:
    a4 = BY_KEY["A4|%s|%s|%s|%s" % (a3["Bq"], a3["Bc"], a3["C"], a3["D"])]
    if a3["dist"] != a4["dist"]:
        _id_bad.append(cell_key(a3))
say("  yacheek s rashozhdeniem A3 protiv A4: %d" % len(_id_bad))
assert not _id_bad, "A3 i A4 obyazany davat' tozhdestvennoe raspredelenie"
say("  -> flag vmesto veto ne menyaet sostoyanie NI V ODNOY yacheyke.")
RESULT["a3_equals_a4"] = True


# =========================================================================== #
# 12. Marginal'nye tablicy po kazhdomu ogranichitelyu
# =========================================================================== #

head("12. Kazhdyy ogranichitel' po otdel'nosti")


def show(rows: Sequence[dict[str, Any]], title: str,
         label: Callable[[dict[str, Any]], str]) -> None:
    sub(title)
    say("  %-26s %6s %6s %6s %5s %5s %6s %7s %5s %5s  %s"
        % ("variant", "Centr", "kvadr", "ANOM", "Q3", "spel", "sred", "median",
           "par", "Q3d", "S1S2S3S4"))
    for c in rows:
        say("  %-26s %6.3f %6.3f %6d %5d %5d %6.1f %7.1f %5d %5d  %d%d%d%d"
            % (label(c), c["center_share"], c["quad_share"],
               c["anomaly_months"], c["q3_months"], c["n_quad_spells"],
               c["quad_spell_mean"], c["quad_spell_median"], c["pairs_ok"],
               c["q3_any_day_months"],
               c["S1"], c["S2"], c["S3"], c["S4"]))


sub("12.0 Byudzhet molchaniya: kto skol'ko gasit (theta Z05, sostav D0)")
_TF, _TM = _p10["theta_fed"], _p10["theta_macro"]
_named = len(_raw_quad)
_survived = sum(1 for m in MONTHS if _mine[m] in QUADS)
say("  Vsego otchyotnyh mesyacev:                       %3d  (100.0%%)" % len(MONTHS))
say("  Porogi vernuli Centr (kvadrant ne nazvan):       %3d  (%.1f%%)"
    % (len(MONTHS) - _named, 100 * (len(MONTHS) - _named) / len(MONTHS)))
say("  Porogi nazvali kvadrant:                         %3d  (%.1f%%)"
    % (_named, 100 * _named / len(MONTHS)))
say("    iz nih pogashen predohranitelem:               %3d  (%.1f%% ot nazvannyh)"
    % (len(KILLED_84), 100 * len(KILLED_84) / _named))
say("    dozhilo do otchyota:                           %3d  (%.1f%%)"
    % (_survived, 100 * _survived / len(MONTHS)))
say("")
say("  Chto dayot snyatie ogranichitelya PO OTDEL'NOSTI (ostal'nye na meste):")
_budget: dict[str, int] = {}
for nm, a_, tf_, tm_ in (
        ("nichego ne snyato (baza Z05 P10)", "A0", _TF, _TM),
        ("snyat tol'ko validator", "A4", _TF, _TM),
        ("snyato tol'ko pravilo 5 b.p.", "A5", _TF, _TM),
        ("snyaty tol'ko porogi (theta -> 0)", "A0", 0.0, 0.0),
        ("snyaty i porogi, i validator", "A4", 0.0, 0.0)):
    dly = classify_range("D0", a_, "OR", tf_, tm_, range(len(GRID)))
    n = sum(1 for m in MONTHS if dly[MONTH_END_IDX[m]] in QUADS)
    q3 = sum(1 for m in MONTHS if dly[MONTH_END_IDX[m]] == "III")
    sp = quad_spell_stats(GRID, dly)
    _budget[nm] = n
    say("    %-36s kvadrantov %3d (%.1f%%) | Q-III %2d | spell %5.1f dn."
        % (nm, n, 100 * n / len(MONTHS), q3, sp["mean_days"]))
RESULT["silence_budget"] = {
    "months": len(MONTHS), "named_by_thresholds": _named,
    "killed_by_validator": len(KILLED_84), "survived": _survived,
    "by_removal": _budget}

show([BY_KEY["%s|Bq_B|OR|C_M|D0" % a] for a in A_KEYS],
     "12.1 Variant A -- validator, theta perekalibruyutsya (Bq_B, OR, C_M, D0)",
     lambda c: "%s %s" % (c["A"], A_LEVELS[c["A"]][:20]))

sub("12.1-bis Variant A pri FIKSIROVANNOM theta Z05 -- validator izolirovan")
say("  %-26s %6s %6s %5s %5s %6s %7s %5s  %s"
    % ("variant", "Centr", "kvadr", "Q3", "spel", "sred", "median", "par",
       "S1S2S3S4"))
A_FIXED: dict[str, Any] = {}
for a in A_KEYS:
    dly = classify_range("D0", a, "OR", _TF, _TM, range(len(GRID)))
    mons = {m: dly[MONTH_END_IDX[m]] for m in MONTHS}
    dist: dict[str, int] = {}
    for m in MONTHS:
        dist[mons[m]] = dist.get(mons[m], 0) + 1
    nq = sum(dist.get(q, 0) for q in QUADS)
    sp = quad_spell_stats(GRID, dly)
    npk = sum(1 for v in pair_n(dist).values() if v >= DEGEN_N)
    small = (min(dist.get(q, 0) for q in QUADS) / nq) if nq else 0.0
    s1 = nq / len(MONTHS) >= S1_MIN
    s2_ = sp["mean_days"] >= MIN_SPELL_DAYS
    s3_ = (all(dist.get(q, 0) > 0 for q in QUADS) and dist.get("III", 0) >= 1
           and small >= S3_MIN_SHARE)
    s4_ = npk >= S4_MIN_PAIRS
    A_FIXED[a] = {"dist": {k: dist.get(k, 0) for k in STATES},
                  "quad_share": nq / len(MONTHS), "q3": dist.get("III", 0),
                  "spell_mean": sp["mean_days"], "spell_median": sp["median_days"],
                  "n_spells": sp["n_spells"], "pairs_ok": npk,
                  "S1": s1, "S2": s2_, "S3": s3_, "S4": s4_}
    say("  %-26s %6.3f %6.3f %5d %5d %6.1f %7.1f %5d  %d%d%d%d"
        % ("%s %s" % (a, A_LEVELS[a][:22]), dist.get("CENTER", 0) / len(MONTHS),
           nq / len(MONTHS), dist.get("III", 0), sp["n_spells"],
           sp["mean_days"], sp["median_days"], npk, s1, s2_, s3_, s4_))
RESULT["A_at_fixed_z05_theta"] = A_FIXED
show([BY_KEY["A0|%s|%s|C_M|D0" % (bq, bc)] for bq in BQ_KEYS for bc in BC_KEYS],
     "12.2 Variant B -- porogi (A0, C_M, D0)",
     lambda c: "%s / %s" % (c["Bq"], c["Bc"]))
show([BY_KEY["A0|Bq_B|OR|%s|D0" % c] for c in C_KEYS],
     "12.3 Variant C -- setka (A0, Bq_B, OR, D0)",
     lambda c: "%s %s" % (c["C"], C_LEVELS[c["C"]][:20]))
show([BY_KEY["A0|Bq_B|OR|C_M|%s" % d] for d in D_KEYS],
     "12.4 Variant D -- sostav vhodov (A0, Bq_B, OR, C_M)",
     lambda c: "%s %s" % (c["D"], D_LEVELS[c["D"]]["note"][:20]))
show([BY_KEY["A4|Bq_A20|OR|C_M|%s" % d] for d in D_KEYS],
     "12.4-bis Variant D pri snyatom veto i q=0.20 (A4, Bq_A20, OR, C_M)",
     lambda c: "%s %s" % (c["D"], D_LEVELS[c["D"]]["note"][:20]))

sub("12.5 Chto vozvrashchaetsya iz 84 pogashennyh mesyacev (theta Z05 fiksirovan)")
say("  Izolyaciya validatora: theta vzyaty iz bazovoy yacheyki i NE")
say("  perekalibruyutsya, poetomu mnozhestvo 'nazvano porogami' odno i to zhe.")
say("  %-4s %8s %8s   %s" % ("A", "vernulos", "iz 84", "razbivka po kvadrantam"))
V8: dict[str, Any] = {}
_kill_set = set(KILLED_84)
for a in A_KEYS:
    dly = classify_range("D0", a, "OR", _p10["theta_fed"], _p10["theta_macro"],
                         range(len(GRID)))
    back = [m for m in KILLED_84 if dly[MONTH_END_IDX[m]] in QUADS]
    brk: dict[str, int] = {}
    for m in back:
        s = dly[MONTH_END_IDX[m]]
        brk[s] = brk.get(s, 0) + 1
    V8[a] = {"returned": len(back), "of": len(KILLED_84),
             "by_quadrant": brk, "months": back}
    say("  %-4s %8d %8d   %s" % (a, len(back), len(KILLED_84),
                                 dict(sorted(brk.items())) or "-"))
RESULT["v8_returned_of_84"] = {k: {kk: vv for kk, vv in v.items()
                                   if kk != "months"} for k, v in V8.items()}
say("")
say("  Iz kakih kvadrantov sostoyalo mnozhestvo 84 (do predohranitelya):")
_k84: dict[str, int] = {}
for m in KILLED_84:
    _k84[_raw_month[m]] = _k84.get(_raw_month[m], 0) + 1
say("    %s" % dict(sorted(_k84.items())))
say("  Pochemu pogasheny (forma na okne 10 v etih mesyacah):")
_why: dict[str, int] = {}
for m in KILLED_84:
    sh = SHAPE[10][MONTH_END_IDX[m]]
    key = "PARALLEL" if sh == "PARALLEL" else (
        "net formy" if sh is None else "forma=%s" % sh)
    _why[key] = _why.get(key, 0) + 1
say("    %s" % dict(sorted(_why.items())))
RESULT["killed_84_composition"] = {"by_raw_quadrant": _k84, "by_reason": _why}

sub("12.6 Razvyortka po otsechke: ogranichitel' -- otsechka ili sostav?")
say("  %-4s %10s %10s %10s %10s" % ("D", "vesFED", "vesMACRO", "otsechka",
                                    "mesyacev vychislimo"))
CUT_SWEEP: dict[str, Any] = {}
for dk in D_KEYS:
    wf = sum(D_LEVELS[dk]["fed"].values())
    wm = sum(D_LEVELS[dk]["macro"].values())
    CUT_SWEEP[dk] = {}
    for cut in (0.60, 0.55, 0.50):
        n = 0
        for m in MONTHS:
            i = MONTH_END_IDX[m]
            f, _ = axis(PARTS[i][0], D_LEVELS[dk]["fed"], cut)
            mm, _ = axis(PARTS[i][1], D_LEVELS[dk]["macro"], cut)
            if f is not None and mm is not None:
                n += 1
        CUT_SWEEP[dk]["%.2f" % cut] = n
        say("  %-4s %10.2f %10.2f %10.2f %10d" % (dk, wf, wm, cut, n))
RESULT["cutoff_sweep"] = CUT_SWEEP

sub("12.7 Diagnostika vozvrata Q-III")
say("  V skol'kih mesyacah Q-III vypadaet hotya by na odin den' setki --")
say("  eto verhnyaya granica dlya lyuboy agregacii po dnyam.")
say("  %-26s %8s %8s %8s" % ("yacheyka (bez C)", "dney Q3", "mes. any", "mes. C_M"))
for a in A_KEYS:
    for bq in ("Bq_B", "Bq_A20"):
        c = BY_KEY["%s|%s|OR|C_M|D0" % (a, bq)]
        cd = BY_KEY["%s|%s|OR|C_D|D0" % (a, bq)]
        dly = classify_range("D0", a, "OR", c["theta_fed"], c["theta_macro"],
                             range(len(GRID))) \
            if c["theta_fed"] == c["theta_fed"] else ["ANOMALY"] * len(GRID)
        say("  %-26s %8d %8d %8d  (C_D: %d)"
            % ("%s|%s|OR|D0" % (a, bq), sum(1 for x in dly if x == "III"),
               c["q3_any_day_months"], c["q3_months"], cd["q3_months"]))


# =========================================================================== #
# 13. Polnaya tablica i poryadok sravneniya
# =========================================================================== #

head("13. Polnaya tablica 864 yacheek (poryadok -- HYPOTHESIS sec.7.3)")

RANKED = sorted(CELLS, key=lambda c: (-c["met"], -c["pairs_ok"],
                                      -c["quad_share"], cell_key(c)))
say("  %-4s %-26s %6s %6s %5s %5s %6s %7s %5s %6s %6s %s"
    % ("#", "yacheyka A|Bq|Bc|C|D", "Centr", "kvadr", "Q3", "spel", "sred",
       "median", "par", "lift10", "lift30", "S1S2S3S4"))
for i, c in enumerate(RANKED):
    say("  %-4d %-26s %6.3f %6.3f %5d %5d %6.1f %7.1f %5d %6s %6s  %d%d%d%d%s"
        % (i + 1, cell_key(c), c["center_share"], c["quad_share"],
           c["q3_months"], c["n_quad_spells"], c["quad_spell_mean"],
           c["quad_spell_median"], c["pairs_ok"],
           "%.3f" % c["S5_lift"] if c["S5_lift"] == c["S5_lift"] else "-",
           "%.3f" % c["S5x_lift"] if c["S5x_lift"] == c["S5x_lift"] else "-",
           c["S1"], c["S2"], c["S3"], c["S4"],
           "" if c["S5_informative"] else "  (S5 ne inf.)"))

sub("13.1 Skol'ko yacheek berut kazhdyy priznak")
for nm in ("S1", "S2", "S3", "S4"):
    say("  %s: %d iz %d" % (nm, sum(1 for c in CELLS if c[nm]), len(CELLS)))
say("  vseh chetyryoh: %d" % sum(1 for c in CELLS if c["met"] == 4))
say("  tryoh:          %d" % sum(1 for c in CELLS if c["met"] == 3))
say("  dvuh:           %d" % sum(1 for c in CELLS if c["met"] == 2))
say("  odnogo:         %d" % sum(1 for c in CELLS if c["met"] == 1))
say("  ni odnogo:      %d" % sum(1 for c in CELLS if c["met"] == 0))
say("")
_max_spell = max(CELLS, key=lambda c: c["quad_spell_mean"])
say("  Maksimal'naya srednyaya dlitel'nost' spella v kvadrante po VSEY setke:")
say("    %.1f kalendarnyh dney, yacheyka %s (trebuetsya %d)"
    % (_max_spell["quad_spell_mean"], cell_key(_max_spell), MIN_SPELL_DAYS))
_max_q = max(CELLS, key=lambda c: c["quad_share"])
say("  Maksimal'naya dolya kvadrantnyh mesyacev: %.3f, yacheyka %s"
    % (_max_q["quad_share"], cell_key(_max_q)))
_max_q3 = max(CELLS, key=lambda c: c["q3_months"])
say("  Maksimal'noe chislo mesyacev Q-III: %d, yacheyka %s"
    % (_max_q3["q3_months"], cell_key(_max_q3)))
_max_pairs = max(CELLS, key=lambda c: c["pairs_ok"])
say("  Maksimal'noe chislo nevyrozhdennyh par: %d, yacheyka %s"
    % (_max_pairs["pairs_ok"], cell_key(_max_pairs)))
RESULT["envelope"] = {
    "max_quad_spell_mean": {"value": _max_spell["quad_spell_mean"],
                            "cell": cell_key(_max_spell)},
    "max_quad_share": {"value": _max_q["quad_share"], "cell": cell_key(_max_q)},
    "max_q3_months": {"value": _max_q3["q3_months"], "cell": cell_key(_max_q3)},
    "max_pairs_ok": {"value": _max_pairs["pairs_ok"],
                     "cell": cell_key(_max_pairs)},
}

sub("13.2 Vklad kazhdogo ogranichitelya: srednyaya dolya kvadrantov po urovnyu")
for axis_name, keys, getter in (("A", A_KEYS, lambda c: c["A"]),
                                ("Bq", BQ_KEYS, lambda c: c["Bq"]),
                                ("Bc", BC_KEYS, lambda c: c["Bc"]),
                                ("C", C_KEYS, lambda c: c["C"]),
                                ("D", D_KEYS, lambda c: c["D"])):
    say("  %s:" % axis_name)
    for k in keys:
        rows = [c for c in CELLS if getter(c) == k]
        say("    %-9s kvadrantov %.4f | Q-III mes. %5.1f | spell %5.1f dn. | "
            "par %4.1f | S1 %3d/%d"
            % (k, sum(r["quad_share"] for r in rows) / len(rows),
               sum(r["q3_months"] for r in rows) / len(rows),
               sum(r["quad_spell_mean"] for r in rows) / len(rows),
               sum(r["pairs_ok"] for r in rows) / len(rows),
               sum(1 for r in rows if r["S1"]), len(rows)))

sub("13.3 Ustoychivost' S6: kvadranty na kalibrovke protiv hvosta")
say("  %-26s %8s %8s %8s" % ("yacheyka", "kalibr.", "hvost", "otnoshenie"))
for c in RANKED[:20]:
    r = (c["oos_quad"] / len(OOS_MONTHS)) / ((c["cal_quad"] / len(CAL_MONTHS))
                                             or float("inf"))
    say("  %-26s %8d %8d %8s"
        % (cell_key(c), c["cal_quad"], c["oos_quad"],
           "%.2f" % r if c["cal_quad"] else "-"))

sub("13.4 Setka q dlya bazovogo sostava: chto pokazyvayut porogi")
_g = CAL_CACHE[("D0", "A0", "OR", "Bq_B")]["grid"]
say("  A0 (veto vklyucheno), D0, OR:")
say("  %6s %10s %12s %12s %12s %10s" % ("q", "theta_fed", "theta_macro",
                                        "spell vsego", "spell kvadr", "Centr"))
for r in _g[::2]:
    say("  %6.2f %10.4f %12.4f %12.1f %12.1f %10.4f"
        % (r["q"], r["theta_fed"], r["theta_macro"], r["mean_spell_all"],
           r["quad_spell_mean"], r["center_share"]))
_g4 = CAL_CACHE[("D0", "A4", "OR", "Bq_B")]["grid"]
say("  A4 (veto snyato), D0, OR:")
say("  %6s %10s %12s %12s %12s %10s" % ("q", "theta_fed", "theta_macro",
                                        "spell vsego", "spell kvadr", "Centr"))
for r in _g4[::2]:
    say("  %6.2f %10.4f %12.4f %12.1f %12.1f %10.4f"
        % (r["q"], r["theta_fed"], r["theta_macro"], r["mean_spell_all"],
           r["quad_spell_mean"], r["center_share"]))
say("")
say("  Zamok Z05 vosproizvedyon: Centr pri q=0 s veto = %.4f, bez veto = %.4f"
    % (_g[0]["center_share"], _g4[0]["center_share"]))
RESULT["center_at_q0"] = {"with_veto": _g[0]["center_share"],
                          "without_veto": _g4[0]["center_share"]}

sub("13.5 Dostizhima li dolya Centra 0.20 hot' gde-nibud'")
_best = None
for k, th in CAL_CACHE.items():
    for r in th.get("grid", []):
        if _best is None or abs(r["center_share"] - CENTER_TARGET) < \
                abs(_best[1]["center_share"] - CENTER_TARGET):
            _best = (k, r)
say("  Blizhayshaya k 0.20 dolya Centra po VSEM kalibrovkam i vsem q:")
say("    %.4f pri q=%.2f, yacheyka D=%s A=%s Bc=%s"
    % (_best[1]["center_share"], _best[1]["q"], _best[0][0], _best[0][1],
       _best[0][2]))
RESULT["closest_center_to_020"] = {
    "center_share": _best[1]["center_share"], "q": _best[1]["q"],
    "D": _best[0][0], "A": _best[0][1], "Bc": _best[0][2]}

sub("13.5-bis Trebovanie A: gde dolya Centra dejstvitel'no okolo pyatoy chasti")
say("  Yacheyki s dolyey Centra v [0.15 .. 0.25] -- to est' te, gde trebovanie A")
say("  sec.1.4.7 vypolneno po SMYSLU, a ne tol'ko po perceptilyu.")
_bandA = [c for c in CELLS if 0.15 <= c["center_share"] <= 0.25]
say("  takih yacheek: %d iz %d" % (len(_bandA), len(CELLS)))
if _bandA:
    say("  %-26s %6s %6s %5s %6s %7s %5s %6s  %s"
        % ("yacheyka", "Centr", "kvadr", "Q3", "sred", "median", "par",
           "lift10", "S1S2S3S4"))
    for c in sorted(_bandA, key=lambda c: (-c["met"], -c["pairs_ok"]))[:24]:
        say("  %-26s %6.3f %6.3f %5d %6.1f %7.1f %5d %6s  %d%d%d%d"
            % (cell_key(c), c["center_share"], c["quad_share"], c["q3_months"],
               c["quad_spell_mean"], c["quad_spell_median"], c["pairs_ok"],
               "%.3f" % c["S5_lift"] if c["S5_lift"] == c["S5_lift"] else "-",
               c["S1"], c["S2"], c["S3"], c["S4"]))
    _a_by_A: dict[str, int] = {}
    for c in _bandA:
        _a_by_A[c["A"]] = _a_by_A.get(c["A"], 0) + 1
    say("  raspredelenie etih yacheek po variantu A: %s" % dict(sorted(_a_by_A.items())))
RESULT["requirement_A_band"] = {
    "n_cells": len(_bandA),
    "by_A": {a: sum(1 for c in _bandA if c["A"] == a) for a in A_KEYS},
    "cells": [cell_key(c) for c in sorted(_bandA,
                                          key=lambda c: (-c["met"],
                                                         -c["pairs_ok"]))[:40]]}

sub("13.5-ter Kogerentnost' S5 tam, gde ona ne trivial'na (A3 / A4)")
say("  Gde veto vklyucheno, soglasie s formoy ravno edinice PO POSTROENIYU.")
say("  Nizhe -- tol'ko yacheyki bez veto, gde velichina chto-to znachit.")
_inf = [c for c in CELLS if c["S5_informative"] and c["S5_lift"] == c["S5_lift"]]
_l10 = sorted(c["S5_lift"] for c in _inf)
_l30 = sorted(c["S5x_lift"] for c in _inf if c["S5x_lift"] == c["S5x_lift"])
say("  informativnyh yacheek: %d" % len(_inf))
if _l10:
    say("  lift na SVOYOM okne (10):  min %.3f | 25%% %.3f | mediana %.3f | "
        "75%% %.3f | max %.3f" % (_l10[0], quantile(_l10, 0.25),
                                  quantile(_l10, 0.50), quantile(_l10, 0.75),
                                  _l10[-1]))
    say("  dolya yacheek s liftom > 1: %d iz %d (%.1f%%)"
        % (sum(1 for x in _l10 if x > 1), len(_l10),
           100 * sum(1 for x in _l10 if x > 1) / len(_l10)))
if _l30:
    say("  lift na CHUZHOM okne (30): min %.3f | 25%% %.3f | mediana %.3f | "
        "75%% %.3f | max %.3f" % (_l30[0], quantile(_l30, 0.25),
                                  quantile(_l30, 0.50), quantile(_l30, 0.75),
                                  _l30[-1]))
    say("  dolya yacheek s liftom > 1: %d iz %d (%.1f%%)"
        % (sum(1 for x in _l30 if x > 1), len(_l30),
           100 * sum(1 for x in _l30 if x > 1) / len(_l30)))
say("  -> Na SVOYOM okne soglasie vyshe sluchaynogo (mediana lifta vyshe 1),")
say("     no pri smene okna ono pochti ischezaet. To est' forma krivoy nesyot")
say("     ne nol' informacii o kvadrante, no eyo signal slab i priviazan k")
say("     oknu; vetom takoy signal ne obosnovyvaetsya.")
RESULT["coherence_informative"] = {
    "n_cells": len(_inf),
    "lift10": {"min": _l10[0] if _l10 else None,
               "median": quantile(_l10, 0.5) if _l10 else None,
               "max": _l10[-1] if _l10 else None,
               "share_above_1": (sum(1 for x in _l10 if x > 1) / len(_l10))
               if _l10 else None},
    "lift30": {"min": _l30[0] if _l30 else None,
               "median": quantile(_l30, 0.5) if _l30 else None,
               "max": _l30[-1] if _l30 else None,
               "share_above_1": (sum(1 for x in _l30 if x > 1) / len(_l30))
               if _l30 else None}}

sub("13.5-quater Yacheyki bez dopustimogo q")
_noadm = [c for c in CELLS if c["no_admissible_q"]]
_why_cnt: dict[str, int] = {}
for c in _noadm:
    _why_cnt[c["why"][:60]] = _why_cnt.get(c["why"][:60], 0) + 1
say("  yacheek, gde pravilo vybora q ne imeet dopustimogo vyhoda: %d iz %d"
    % (len(_noadm), len(CELLS)))
for k, v in sorted(_why_cnt.items(), key=lambda kv: -kv[1]):
    say("    %4d  %s" % (v, k))
RESULT["no_admissible_q_cells"] = {"n": len(_noadm), "reasons": _why_cnt}

sub("13.6 Doli dostupnogo vesa po sostavam (velichina V5)")
for dk in D_KEYS:
    uf = {}
    um = {}
    for m in MONTHS:
        i = MONTH_END_IDX[m]
        uf[round(SCORE[dk]["share_f"][i], 4)] = \
            uf.get(round(SCORE[dk]["share_f"][i], 4), 0) + 1
        um[round(SCORE[dk]["share_m"][i], 4)] = \
            um.get(round(SCORE[dk]["share_m"][i], 4), 0) + 1
    say("  %-3s FED %s | MACRO %s" % (dk, dict(sorted(uf.items())),
                                      dict(sorted(um.items()))))
RESULT["weight_shares"] = {
    dk: {"fed": sorted({round(SCORE[dk]["share_f"][MONTH_END_IDX[m]], 4)
                        for m in MONTHS}),
         "macro": sorted({round(SCORE[dk]["share_m"][MONTH_END_IDX[m]], 4)
                          for m in MONTHS})} for dk in D_KEYS}


# =========================================================================== #
# 14. Storozha discipliny -- pechat'
# =========================================================================== #

head("14. Storozha discipliny (HYPOTHESIS sec.1.3)")
say("  Simvoly Yahoo, zaproshennye za ves' progon: %s"
    % sorted(set(YAHOO_ASKED)))
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
                        "z05_keys_read": sorted(Z05_READ),
                        "functions": _fns, "suspicious": _susp}


# =========================================================================== #
# 15. Zapis'
# =========================================================================== #

RESULT["levels"] = {"A": A_LEVELS, "Bq": BQ_LEVELS, "Bc": BC_LEVELS,
                    "C": C_LEVELS,
                    "D": {k: {"note": v["note"],
                              "fed": v["fed"], "macro": v["macro"],
                              "fed_weight": sum(v["fed"].values()),
                              "macro_weight": sum(v["macro"].values())}
                          for k, v in D_LEVELS.items()}}
RESULT["criteria_thresholds"] = {"S1_min_quad_share": S1_MIN,
                                 "S2_min_spell_days": MIN_SPELL_DAYS,
                                 "S3_min_smallest_share": S3_MIN_SHARE,
                                 "S4_min_pairs": S4_MIN_PAIRS,
                                 "degenerate_n": DEGEN_N}
RESULT["cells"] = [{k: v for k, v in c.items() if k != "pairs_n"} | {
    "pairs_n": c["pairs_n"]} for c in CELLS]
RESULT["ranked_top"] = [cell_key(c) for c in RANKED[:40]]
RESULT["base_cell"] = cell_key(BASE)
RESULT["task_cell"] = cell_key(TASK_CELL)
RESULT["monthly_states_base"] = {
    m: BASE and to_months(classify_range("D0", "A0", "OR", BASE["theta_fed"],
                                         BASE["theta_macro"],
                                         range(len(GRID))), "C_M")[m]
    for m in MONTHS}
RESULT["umcsent_threshold"] = UMC_THRESHOLD
RESULT["q_grid"] = Q_GRID
RESULT["data_passport"] = {
    k: {"n": len(observed(v)), "first": v.dates[0] if v.dates else None,
        "last": v.dates[-1] if v.dates else None,
        "fetched_at": getattr(v, "fetched_at", "")}
    for k, v in RAW.items() if hasattr(v, "dates")}
RESULT["elapsed_sec"] = round(time.time() - _T0, 1)

with open(os.path.join(_HERE, "result.json"), "w", encoding="utf-8") as fh:
    json.dump(RESULT, fh, ensure_ascii=False, indent=1, default=str)

say("")
say("result.json zapisan; vsego %.1f s" % (time.time() - _T0))
