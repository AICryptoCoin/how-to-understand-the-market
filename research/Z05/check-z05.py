#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z05 -- proverka pribora KRASNYM, a ne zelyonym.

Otricatel'nyy verdikt opasnee polozhitel'nogo odnim: dolya vernyh znakov
okolo 0.50 -- eto rovno to, chto vydast SLOMANNYY konveyer. Poetomu prezhde
chem verit' nulyu, nado pokazat', chto pribor voobshche sposoben uvidet' signal
i chto on chitaet znak imenno tak, kak zapisano v spetsifikacii.

Kod nizhe napisan ZANOVO i ne importiruet run.py. Otlichie ot pervoy redakcii
proverki -- v tom, kak daleko ona dohodit:

* **Klassifikator pereschityvaetsya celikom** (blok C): iz syryh ryadov
  sobirayutsya obe osi, zanovo kalibruyutsya porogi theta i zanovo stroyatsya
  pomesyachnye sostoyaniya vo vseh semi konfiguraciyah -- a potom sveryayutsya
  s result.json pobitovo. Pervaya redakciya brala monthly_states gotovymi, to
  est' ne prikasalas' k tomu mestu, gde i reshaetsya ves' vopros: v P10 Centr
  stoit v 263 mesyacah iz 270, porogi nazyvayut kvadrant v 91, i validator
  formy krivoy ubivaet 84 iz nih.
* **Orakuly bloka B stroyatsya NEZAVISIMOY ot ret() dorogoy** -- otdel'naya
  zagruzka cen, svoya karta koncov mesyacev, arifmetika na otnosheniyah vmesto
  logarifmov. Poka orakul stroilsya toy zhe funkciey, kotoruyu potom proveryal,
  lyubaya oshibka, deystvuyushchaya odinakovo na oboih, byla nevidima: i
  global'nyy perevorot znaka dohodnosti, i sdvig cen na odin torgovyy den'
  nazad ostavlyali blok B zelyonym.
* **Kontrol' moshchnosti perenesyon na tu vetv', gde lezhit massa** --
  Centr x SIZE/STYLE/GEO. Ran'she on stoyal na pare GOLD, dayushchey 0.82 %
  nablyudeniy zashchishchaemogo chisla, i pritom v sostoyaniyah, dlya kotoryh
  u GOLD predpisaniya net vovse.

    python check-z05.py          # seti sverh kesha ne trebuet

Kazhdaya proverka ustroena tak, chtoby padat' na oshibke, a ne prohodit'
na lyuboy realizacii: blok F mutiruet vhody i trebuet KRASNOGO.
"""

from __future__ import annotations

import bisect
import json
import math
import os
import random
import statistics
import sys
from datetime import date, timedelta

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

# =========================================================================== #
# 0. Konstanty. Vzyaty iz HYPOTHESIS.md (sec.2-sec.5), a ne iz run.py:
#    proverka obyazana vosproizvodit' OB'YAVLENNOE pravilo, a ne kod.
# =========================================================================== #

WIN_START, WIN_END = "2004-01-01", "2026-06-30"
WARMUP_START = "2001-01-01"          # sec.3.3: MAD schitaetsya na svoey istorii
CALIB_END = "2014-12-31"             # sec.5
MIN_OBS_DAILY, MIN_OBS_MONTHLY, MIN_OBS_WEEKLY = 250, 24, 104   # sec.11 zap.1
MAD_C, CLIP = 1.4826, 3.0            # sec.3.1
CUTOFF = 0.60                        # sec.3.6
PARALLEL_BP = 0.05                   # sec.4.2
CLAIMS_LAG_DAYS = 5                  # sec.3.5: subbota -> chetverg
Q_GRID = [round(0.20 + 0.02 * i, 2) for i in range(21)]         # sec.5
WIDE_Q = [round(0.20 + 0.02 * i, 2) for i in range(40)]         # 0.20 .. 0.98
MIN_SPELL = 30                       # trebovanie B
CENTER_TARGET = 0.20                 # trebovanie A
WINDOWS = (5, 10, 30)

W_FED = {"us2y": 0.25, "real5": 0.15, "phase": 0.15, "dxy": 0.10}
W_MACRO = {"nahb": 0.13, "permit": 0.13, "comp": 0.10, "claims": 0.12,
           "nof": 0.08, "hggc": 0.04, "clgc": 0.04}
PUB = {"nahb": (0, 16), "permit": (1, 20), "comp": (0, 28), "nof": (0, 21)}

CFG = {"P10": (10, "single", None), "P05": (5, "single", None),
       "P30": (30, "single", None), "VOTE": (10, "vote", None),
       "NOVAL": (10, "off", None),
       "A20": (10, "single", 0.20), "A20NOVAL": (10, "off", 0.20)}

QUAD = {("+", "-"): "I", ("+", "+"): "II", ("-", "-"): "III", ("-", "+"): "IV"}


# --------------------------------------------------------------------------- #
# 0.1 Melkie instrumenty
# --------------------------------------------------------------------------- #

def minus_days(key: str, n: int) -> str:
    """Klyuch 'GGGG-MM-DD' ili 'GGGG-MM' minus n kalendarnyh dney."""
    base = date.fromisoformat(key if len(key) >= 10 else key + "-01")
    return (base - timedelta(days=n)).isoformat()[:len(key)]


def add_m(m: str, k: int) -> str:
    t = int(m[:4]) * 12 + int(m[5:7]) - 1 + k
    return "%04d-%02d" % (t // 12, t % 12 + 1)


def last_dom(m: str) -> int:
    nxt = add_m(m, 1)
    return (date(int(nxt[:4]), int(nxt[5:7]), 1) - timedelta(days=1)).day


def avail(m: str, lag: int, dom: int) -> str:
    tgt = add_m(m, lag)
    return "%s-%02d" % (tgt, min(dom, last_dom(tgt)))


def quantile(xs, q: float) -> float:
    """Linejnaya interpolyaciya po poryadkovym statistikam (sec.5)."""
    if not xs:
        return float("nan")
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    pos = q * (len(ys) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ys) - 1)
    return ys[lo] + (ys[hi] - ys[lo]) * (pos - lo)


def sgn(x: float) -> float:
    return 0.0 if x == 0 else (1.0 if x > 0 else -1.0)


def norm(raw: float, scale: float) -> float:
    z = raw / (MAD_C * scale)
    return max(-CLIP, min(CLIP, z)) / CLIP


def obs(series) -> list[tuple[str, float]]:
    return [(d, float(v)) for d, v in zip(series.dates, series.values)
            if v is not None]


class Step:
    """Ryad s poiskom 'poslednee znachenie ne pozzhe daty'."""

    __slots__ = ("d", "v")

    def __init__(self, pairs) -> None:
        rows = sorted(pairs)
        self.d = [r[0] for r in rows]
        self.v = [r[1] for r in rows]

    def at(self, iso: str):
        i = bisect.bisect_right(self.d, iso) - 1
        return self.v[i] if i >= 0 else None


def mad_scale(keys, vals, years: int, min_obs: int) -> dict[str, float]:
    """MAD prirashcheniy za `years` kalendarnyh let, s tekushchey tochkoy."""
    out: dict[str, float] = {}
    for i, k in enumerate(keys):
        j = bisect.bisect_left(keys, minus_days(k, 365 * years))
        win = vals[j:i + 1]
        if len(win) < min_obs:
            continue
        med = statistics.median(win)
        m = statistics.median([abs(x - med) for x in win])
        if m > 0:
            out[k] = m
    return out


def speed_daily(step: Step, grid, w: int, *, log: bool = False,
                flip: bool = False) -> dict[str, float]:
    raw: dict[str, float] = {}
    for g in grid:
        a, b = step.at(g), step.at(minus_days(g, w))
        if a is None or b is None:
            continue
        if log:
            if a <= 0 or b <= 0:
                continue
            raw[g] = math.log(a) - math.log(b)
        else:
            raw[g] = a - b
    keys = [g for g in grid if g in raw]
    sc = mad_scale(keys, [raw[g] for g in keys], 2, MIN_OBS_DAILY)
    k = -1.0 if flip else 1.0
    return {g: k * norm(raw[g], sc[g]) for g in sc}


def level_monthly(vals: dict[str, float], threshold: float,
                  lag: int = 3) -> dict[str, float]:
    out = {}
    for m in sorted(vals):
        prev = add_m(m, -lag)
        if prev in vals:
            out[m] = 0.6 * sgn(vals[m] - vals[prev]) \
                + 0.4 * sgn(vals[m] - threshold)
    return out


def speed_monthly(vals: dict[str, float], lag: int, *,
                  log: bool) -> dict[str, float]:
    raw = {}
    for m in sorted(vals):
        prev = add_m(m, -lag)
        if prev not in vals:
            continue
        a, b = vals[m], vals[prev]
        if log:
            if a <= 0 or b <= 0:
                continue
            raw[m] = math.log(a) - math.log(b)
        else:
            raw[m] = a - b
    keys = sorted(raw)
    sc = mad_scale(keys, [raw[m] for m in keys], 2, MIN_OBS_MONTHLY)
    return {m: norm(raw[m], sc[m]) for m in sc}


def speed_weekly(pairs, weeks: int, *, flip: bool = False) -> dict[str, float]:
    dates = [p[0] for p in pairs]
    vals = dict(pairs)
    raw = {}
    for i, d in enumerate(dates):
        if i >= weeks:
            raw[d] = vals[d] - vals[dates[i - weeks]]
    keys = sorted(raw)
    sc = mad_scale(keys, [raw[d] for d in keys], 2, MIN_OBS_WEEKLY)
    k = -1.0 if flip else 1.0
    return {d: k * norm(raw[d], sc[d]) for d in sc}


def mean_spell(dates, states) -> float:
    """Srednyaya dlitel'nost' prebyvaniya v odnom SOSTOYANII (ispolnennoe B)."""
    starts = []
    prev = None
    for d, st in zip(dates, states):
        if st != prev:
            starts.append((d, st))
            prev = st
    lens = []
    for i, (d, st) in enumerate(starts):
        nxt = starts[i + 1][0] if i + 1 < len(starts) else \
            (date.fromisoformat(dates[-1]) + timedelta(days=1)).isoformat()
        lens.append(((date.fromisoformat(nxt)
                      - date.fromisoformat(d)).days, st))
    return sum(x[0] for x in lens) / len(lens) if lens else 0.0


def mean_spell_quad(dates, states) -> float:
    """Srednyaya dlitel'nost' prebyvaniya v odnom KVADRANTE (bukva sec.1.4.7)."""
    starts = []
    prev = None
    for d, st in zip(dates, states):
        if st != prev:
            starts.append((d, st))
            prev = st
    lens = []
    for i, (d, st) in enumerate(starts):
        if st in ("CENTER", "ANOMALY"):
            continue
        nxt = starts[i + 1][0] if i + 1 < len(starts) else \
            (date.fromisoformat(dates[-1]) + timedelta(days=1)).isoformat()
        lens.append((date.fromisoformat(nxt) - date.fromisoformat(d)).days)
    return sum(lens) / len(lens) if lens else 0.0


# =========================================================================== #
# 1. Sobstvennaya sborka osey: ot syryh ryadov do sostoyaniya
# =========================================================================== #

print("sborka osey zanovo (sec.3 pred-registracii) ...")
sys.stdout.flush()

_spy = S.yahoo("SPY")
ME: dict[str, str] = {}
for _d, _v in zip(_spy.dates, _spy.values):
    if _v is not None:
        ME[_d[:7]] = _d
_lost = [m for m in MONTHS if ME.get(m) != R["month_end_dates"][m]]
assert not _lost, "koncy mesyacev razoshlis' s otchyotom: %s" % _lost[:5]

GRID = [d for d, v in zip(_spy.dates, _spy.values)
        if v is not None and WIN_START <= d <= WIN_END]
GRID_FULL = [d for d, v in zip(_spy.dates, _spy.values)
             if v is not None and WARMUP_START <= d <= WIN_END]
CALIB = [g for g in GRID if g <= CALIB_END]

_fred = {k: S.fred(v) for k, v in
         {"DGS2": "DGS2", "DGS5": "DGS5", "DGS10": "DGS10", "T5YIE": "T5YIE",
          "PERMIT": "PERMIT", "IC4WSA": "IC4WSA",
          "NOF": "NOFDFSA066MSFRBPHI", "DFEDTAR": "DFEDTAR",
          "DFEDTARU": "DFEDTARU", "DFEDTARL": "DFEDTARL"}.items()}

ST_DGS2 = Step(obs(_fred["DGS2"]))
ST_DGS10 = Step(obs(_fred["DGS10"]))
_d5, _ie = dict(obs(_fred["DGS5"])), dict(obs(_fred["T5YIE"]))
ST_REAL5 = Step((d, _d5[d] - _ie[d]) for d in _d5 if d in _ie)
ST_DXY = Step(obs(S.yahoo("DX-Y.NYB")))
_gc = dict(obs(S.yahoo("GC=F")))
_hg = dict(obs(S.yahoo("HG=F")))
_cl = dict(obs(S.yahoo("CL=F")))
ST_HGGC = Step((d, _hg[d] / _gc[d]) for d in _hg if d in _gc and _gc[d] > 0)
ST_CLGC = Step((d, _cl[d] / _gc[d]) for d in _cl if d in _gc and _gc[d] > 0)

# faza rezhima DKP (sec.3.4)
_tgt = dict(obs(_fred["DFEDTAR"]))
_u, _l = dict(obs(_fred["DFEDTARU"])), dict(obs(_fred["DFEDTARL"]))
for _d in _u:
    if _d in _l:
        _tgt[_d] = (_u[_d] + _l[_d]) / 2.0
ST_TGT = Step(_tgt.items())


def phase_at(iso: str):
    r, r6 = ST_TGT.at(iso), ST_TGT.at(minus_days(iso, 183))
    if r is None or r6 is None:
        return None
    if r > r6:
        return -1.0
    if r < r6:
        return 1.0
    lo = minus_days(iso, 3653)
    hist = [v for d, v in zip(ST_TGT.d, ST_TGT.v) if lo <= d <= iso]
    if len(hist) < MIN_OBS_DAILY:
        return None
    return 1.0 if r <= quantile(hist, 0.40) else -1.0


PHASE = {g: c for g in GRID_FULL if (c := phase_at(g)) is not None}

# mesyachnye i nedel'nye vhody osi MACRO
_nahb = {d[:7]: v for d, v in obs(S.nahb_hmi("t2")["HMI"])}
_permit = {d[:7]: v for d, v in obs(_fred["PERMIT"])}
_nof = {d[:7]: v for d, v in obs(_fred["NOF"])}
_comp = {d[:7]: v for d, v in
         obs(C.ladder_contribution(C.frozen_composite(), C.LADDER_V1))}

MONTHLY = {
    "nahb": level_monthly(_nahb, 50.0),
    "permit": speed_monthly(_permit, 3, log=True),
    "comp": _comp,
    "nof": level_monthly(_nof, 0.0),
}
ST_MONTHLY = {k: Step((avail(m, *PUB[k]), v) for m, v in c.items())
              for k, c in MONTHLY.items()}
# sec.3.5 ob'yavlyaet lag publikacii IC4WSA (subbota -> chetverg, +5 dney),
# no progon ego NE primenyaet -- sm. REPORT sec.11 p.11. Proverka vosproizvodit
# progon, znachit i zdes' laga net; a to, chto ot nego nichego ne menyaetsya,
# ne obeshchaetsya, a schitaetsya kazhdyy raz -- blok C6.
_claims = speed_weekly(obs(_fred["IC4WSA"]), 13, flip=True)
assert {date.fromisoformat(d).weekday() for d in _claims} == {5}
ST_CLAIMS = Step(_claims.items())
ST_CLAIMS_LAGGED = Step(((date.fromisoformat(d)
                          + timedelta(days=CLAIMS_LAG_DAYS)).isoformat(), v)
                        for d, v in _claims.items())

DAILY: dict[int, dict[str, dict[str, float]]] = {}
for _w in WINDOWS:
    DAILY[_w] = {
        "us2y": speed_daily(ST_DGS2, GRID_FULL, _w, flip=True),
        "real5": speed_daily(ST_REAL5, GRID_FULL, _w, flip=True),
        "dxy": speed_daily(ST_DXY, GRID_FULL, _w, log=True, flip=True),
        "hggc": speed_daily(ST_HGGC, GRID_FULL, _w, log=True),
        "clgc": speed_daily(ST_CLGC, GRID_FULL, _w, log=True),
    }


def shape_at(iso: str, w: int):
    a, b = ST_DGS2.at(iso), ST_DGS2.at(minus_days(iso, w))
    c, e = ST_DGS10.at(iso), ST_DGS10.at(minus_days(iso, w))
    if None in (a, b, c, e):
        return None
    dk, dl = a - b, c - e
    dsp = dl - dk
    if abs(dsp) < PARALLEL_BP:
        return "PARALLEL"
    up = (dk + dl) / 2.0 > 0
    if not up:
        return "I" if dsp < 0 else "II"
    return "III" if dsp < 0 else "IV"


SHAPE = {w: {g: s for g in GRID if (s := shape_at(g, w)) is not None}
         for w in WINDOWS}


def shape_vote(iso: str):
    votes = [SHAPE[w].get(iso) for w in WINDOWS]
    votes = [v for v in votes if v is not None]
    if len(votes) < 2:
        return None
    best, n = None, 0
    for v in set(votes):
        k = votes.count(v)
        if k > n:
            best, n = v, k
    return best if n >= 2 else "NOAGREE"


def axis_score(parts, weights, cutoff: float = CUTOFF):
    num = den = 0.0
    for k, w in weights.items():
        c = parts.get(k)
        if c is None:
            continue
        num += w * c
        den += w
    if den == 0 or den < cutoff:
        return None, den
    return num / den, den


def parts_at(iso: str, w: int, *, claims_step: Step = None):
    dc = DAILY[w]
    fed = {"us2y": dc["us2y"].get(iso), "real5": dc["real5"].get(iso),
           "phase": PHASE.get(iso), "dxy": dc["dxy"].get(iso)}
    mac = {"nahb": ST_MONTHLY["nahb"].at(iso),
           "permit": ST_MONTHLY["permit"].at(iso),
           "comp": ST_MONTHLY["comp"].at(iso),
           "claims": (claims_step or ST_CLAIMS).at(iso),
           "nof": ST_MONTHLY["nof"].at(iso),
           "hggc": dc["hggc"].get(iso), "clgc": dc["clgc"].get(iso)}
    return fed, mac


def classify(iso: str, w: int, tf: float, tm: float, validator: str,
             wf=W_FED, wm=W_MACRO, cutoff: float = CUTOFF,
             claims_step: Step = None):
    """(sostoyanie, syroe sostoyanie do predohranitelya)."""
    fp, mp = parts_at(iso, w, claims_step=claims_step)
    sf, _ = axis_score(fp, wf, cutoff)
    sm, _ = axis_score(mp, wm, cutoff)
    if sf is None or sm is None:
        return "ANOMALY", "ANOMALY"
    if abs(sf) < tf or abs(sm) < tm:
        return "CENTER", "CENTER"
    q = QUAD[("+" if sf > 0 else "-", "+" if sm > 0 else "-")]
    if validator == "off":
        return q, q
    sh = shape_vote(iso) if validator == "vote" else SHAPE[w].get(iso)
    if sh is None or sh in ("PARALLEL", "NOAGREE") or sh != q:
        return "CENTER", q
    return q, q


def abs_scores(w: int, wf=W_FED, wm=W_MACRO, cutoff: float = CUTOFF,
               claims_step: Step = None):
    """Raspredeleniya |score| po kazhdoy osi na kalibrovochnom otrezke."""
    f, m = [], []
    for g in CALIB:
        fp, mp = parts_at(g, w, claims_step=claims_step)
        a, _ = axis_score(fp, wf, cutoff)
        b, _ = axis_score(mp, wm, cutoff)
        if a is not None:
            f.append(abs(a))
        if b is not None:
            m.append(abs(b))
    return f, m


def calibrate(w: int, validator: str, force_q=None, **kw):
    """Procedura sec.5: naimen'shee q iz setki, udovletvoryayushchee B."""
    sf, sm = abs_scores(w, **kw)
    rows, chosen = [], None
    for q in Q_GRID:
        tf, tm = quantile(sf, q), quantile(sm, q)
        st = [classify(g, w, tf, tm, validator, **kw)[0] for g in CALIB]
        row = {"q": q, "theta_fed": tf, "theta_macro": tm,
               "spell": mean_spell(CALIB, st),
               "center": sum(1 for x in st if x == "CENTER") / len(st)}
        rows.append(row)
        if force_q is None and chosen is None and row["spell"] >= MIN_SPELL:
            chosen = row
        if force_q is not None and abs(q - force_q) < 1e-9:
            chosen = row
    return chosen or rows[-1], rows


def _dist(states) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in MONTHS:
        out[states[m]] = out.get(states[m], 0) + 1
    return dict(sorted(out.items()))


def month_states(w: int, tf: float, tm: float, validator: str, **kw):
    out, raw = {}, {}
    for m in MONTHS:
        out[m], raw[m] = classify(ME[m], w, tf, tm, validator, **kw)
    return out, raw


# =========================================================================== #
# 2. Pary. Perepisany zanovo s cheatsheet-spec.md sec.5, a ne vzyaty iz run.py.
# =========================================================================== #

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


def level(key: str, iso: str):
    """Uroven' pary: srednee logarifmov cen dlinnoy nogi minus korotkoy."""
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


def ret(key: str, m: str, h: int):
    m2 = add_m(m, h)
    if m2 not in ME:
        return None
    a, b = level(key, ME[m]), level(key, ME[m2])
    return None if a is None or b is None else b - a


# --------------------------------------------------------------------------- #
# 2.1 NEZAVISIMYY cenovoy marshrut -- tol'ko dlya orakulov bloka B.
#
# Orakul, postroennyy toy zhe funkciey ret(), kotoruyu on potom proveryaet,
# ne proverit nichego: oshibka, deystvuyushchaya odinakovo na orakula i na
# schyot, sokratitsya. Poetomu nizhe -- drugaya zagruzka, drugaya karta koncov
# mesyacev i drugaya arifmetika (proizvedeniya i otnosheniya vmesto summy
# logarifmov). Sovpadenie dvuh marshrutov proveryaetsya otdel'no (B0).
# --------------------------------------------------------------------------- #

_ref_spy = S.yahoo("SPY")
REF_ME: dict[str, str] = {}
for _d, _v in zip(_ref_spy.dates, _ref_spy.values):
    if _v is not None and _d > REF_ME.get(_d[:7], ""):
        REF_ME[_d[:7]] = _d
REF_PX: dict[str, dict[str, float]] = {}
for _sym in SYMS:
    _ser = S.yahoo(_sym)
    REF_PX[_sym] = dict(zip(_ser.dates, _ser.values))


def _ref_basket(day: str, syms):
    acc = 1.0
    for s in syms:
        v = REF_PX[s].get(day)
        if v is None or float(v) <= 0:
            return None
        acc *= float(v)
    return acc ** (1.0 / len(syms))


def ref_dir(key: str, m: str, h: int):
    """Znak dohodnosti pary, poluchennyy NE cherez level()/ret()/ME."""
    lo, sh, _ = SPEC_PAIRS[key]
    d1, d2 = REF_ME.get(m), REF_ME.get(add_m(m, h))
    if d1 is None or d2 is None:
        return None
    a1, a2 = _ref_basket(d1, lo), _ref_basket(d2, lo)
    if a1 is None or a2 is None:
        return None
    if sh:
        b1, b2 = _ref_basket(d1, sh), _ref_basket(d2, sh)
        if b1 is None or b2 is None:
            return None
        a1, a2 = a1 / b1, a2 / b2
    return 1 if a2 > a1 else (-1 if a2 < a1 else 0)


def hits_for(states, h: int, keys=None, flip: bool = False, ret_fn=None):
    fn = ret_fn or ret
    out = []
    for key in (keys or SPEC_PAIRS):
        signs = SPEC_PAIRS[key][2]
        for m in MONTHS:
            want = signs.get(states.get(m, "ANOMALY"))
            if want is None:
                continue
            r = fn(key, m, h)
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

mut = dict(lad_bad)
mut.pop("rejected")
good = C.ladder_contribution(comp, C.LADDER_V1)
bad = C.ladder_contribution(comp, mut)
diff = sum(1 for a, b in zip(good.values, bad.values) if a != b)
check("A4 bez pometki ta zhe lestnica schitaetsya i dayot DRUGOY vklad",
      diff > 0, "rashozhdenie %d mesyacev iz %d" % (diff, len(good.values)))

# =========================================================================== #
head("B. Polozhitel'nyy kontrol': sposoben li pribor uvidet' signal")

# B0: dva marshruta ceny obyazany sovpadat' po znaku vo VSEH mesyacah. Eto
#     i est' to mesto, gde lovyatsya perevorot znaka i ustarevshiy na den'
#     yakor': orakuly nizhe stroyatsya po ref_dir, a schitayutsya po ret().
_agree = _seen = 0
_bad_rows = []
for _k in SPEC_PAIRS:
    for _h in (1, 3):
        for _m in MONTHS:
            r, d = ret(_k, _m, _h), ref_dir(_k, _m, _h)
            if r is None or d is None or r == 0.0 or d == 0:
                continue
            _seen += 1
            if (r > 0) == (d > 0):
                _agree += 1
            elif len(_bad_rows) < 5:
                _bad_rows.append("%s %s h%d" % (_k, _m, _h))
check("B0 nezavisimyy cenovoy marshrut sovpal s ret() vo vseh par-mesyacah",
      _agree == _seen, "sovpalo %d iz %d%s"
      % (_agree, _seen, ("; pervye rashozhdeniya: " + ", ".join(_bad_rows))
         if _bad_rows else ""))

# B1: orakul na pare GOLD. Sostoyanie stroitsya iz BUDUSHCHEGO znaka,
#     poluchennogo NEZAVISIMYM marshrutom.
for h in (1, 3):
    orac = {}
    for m in MONTHS:
        d = ref_dir("GOLD", m, h)
        if d:
            orac[m] = "I" if d > 0 else "III"      # GOLD: +1 v Q-I, -1 v Q-III
    rows = hits_for(orac, h, keys=["GOLD"])
    check("B1.h%d orakul dayot dolyu 1.000" % h, abs(rate(rows) - 1.0) < 1e-12,
          "n=%d dolya=%.4f" % (len(rows), rate(rows)))
    rows_anti = hits_for(orac, h, keys=["GOLD"], flip=True)
    check("B1.h%d antiorakul dayot dolyu 0.000" % h,
          abs(rate(rows_anti)) < 1e-12,
          "n=%d dolya=%.4f" % (len(rows_anti), rate(rows_anti)))

# --------------------------------------------------------------------------- #
# B2-B4: kontrol' na TOY vetvi, gde lezhit massa zashchishchaemogo chisla.
#
# 0.4918 na 93 % sostoit iz predpisaniy CENTRA po tryom param -- SIZE, STYLE,
# GEO (sec.2.3 speki). Kontrol' na pare GOLD kasalsya 0.82 % nablyudeniy i shyol
# po sostoyaniyam, dlya kotoryh u GOLD predpisaniya net vovse. Nizhe -- dvuh-
# sostoyaniyy orakul, u kotorogo odno iz dvuh sostoyaniy vsegda CENTER, tak chto
# rovno te predpisaniya i ta arifmetika, kotorye proizvodyat 0.4918.
# --------------------------------------------------------------------------- #

MASS_KEYS = ["SIZE", "STYLE", "GEO"]
TWO_STATE = {"SIZE": ("CENTER", "IV"),    # (+1, -1)
             "GEO": ("CENTER", "IV"),
             "STYLE": ("I", "CENTER")}
for _k, (_up, _dn) in TWO_STATE.items():
    assert SPEC_PAIRS[_k][2][_up] == 1 and SPEC_PAIRS[_k][2][_dn] == -1


def mass_control(prob: float, rng: random.Random, h: int = 1):
    """Sostoyanie verno v `prob` mesyacev; vozvrashchaet (stroki, dolya Centra)."""
    rows, n_center = [], 0
    for key in MASS_KEYS:
        up, dn = TWO_STATE[key]
        st = {}
        for m in MONTHS:
            d = ref_dir(key, m, h)
            if not d:
                continue
            good, bad = (up, dn) if d > 0 else (dn, up)
            st[m] = good if rng.random() < prob else bad
        got = hits_for(st, h, keys=[key])
        n_center += sum(1 for m, _, _ in got if st.get(m) == "CENTER")
        rows += got
    return rows, n_center


rng = random.Random(SEED)
rows, n_c = mass_control(1.0, rng)
check("B2 orakul na vetvi Centr x SIZE/STYLE/GEO dayot dolyu 1.000",
      abs(rate(rows) - 1.0) < 1e-12,
      "n=%d dolya=%.4f, iz nih v Centre %d (%.0f%%)"
      % (len(rows), rate(rows), n_c, 100.0 * n_c / max(1, len(rows))))
check("B2 kontrol' idyot po TOY zhe masse, chto i zashchishchaemoe chislo",
      len(rows) >= 700 and n_c >= 0.35 * len(rows),
      "nablyudeniy %d protiv %d v pule P10; dolya Centra %.2f"
      % (len(rows), R["main"]["pooled"]["h1"]["n_obs"], n_c / max(1, len(rows))))

rows, n_c = mass_control(0.60, rng)
p = boot_p(rows, 3)
check("B3 smes' 60/40 na etoy vetvi vosstanovlena",
      abs(rate(rows) - 0.60) < 0.06,
      "n=%d dolya=%.4f (v Centre %d)" % (len(rows), rate(rows), n_c))
check("B3 i otvergaet nulevuyu 0.5 na etom n", p < 0.05,
      "p=%.4f pri n_mesyacev=%d" % (p, len({x[0] for x in rows})))

rows50, n_c50 = mass_control(0.50, rng)
p50 = boot_p(rows50, 3)
check("B4 smes' 50/50 na etoy vetvi nulevuyu NE otvergaet", not (p50 < 0.05),
      "dolya=%.4f p=%.4f n=%d" % (rate(rows50), p50, len(rows50)))

# =========================================================================== #
head("C. Klassifikator pereschitan iz syryh vhodov i sveren s otchyotom")

MY_THETA, MY_STATES, MY_RAW = {}, {}, {}
for name, (w, val, fq) in CFG.items():
    ch, _grid = calibrate(w, val, fq)
    MY_THETA[name] = ch
    MY_STATES[name], MY_RAW[name] = month_states(w, ch["theta_fed"],
                                                 ch["theta_macro"], val)

for name in CFG:
    th, mine = R["theta"][name]["chosen"], MY_THETA[name]
    ok = (abs(th["q"] - mine["q"]) < 1e-9
          and abs(th["theta_fed"] - mine["theta_fed"]) < 5e-5
          and abs(th["theta_macro"] - mine["theta_macro"]) < 5e-5)
    check("C1.%-8s theta sovpal (q, th_fed, th_macro)" % name, ok,
          "moi q=%.2f th=%.4f/%.4f protiv %.2f %.4f/%.4f"
          % (mine["q"], mine["theta_fed"], mine["theta_macro"],
             th["q"], th["theta_fed"], th["theta_macro"]))

for name in CFG:
    theirs = R["monthly_states"][name]
    bad = [m for m in MONTHS if theirs[m] != MY_STATES[name][m]]
    check("C2.%-8s pomesyachnye sostoyaniya sovpali vo vseh %d mesyacah"
          % (name, len(MONTHS)), not bad,
          ("raspredelenie %s" % _dist(MY_STATES[name])) if not bad
          else "rashozhdeniy %d, pervye: %s" % (len(bad), bad[:5]))

check("C3 syroe sostoyanie DO predohranitelya sovpalo (RAW_P10)",
      all(R["monthly_states"]["RAW_P10"][m] == MY_RAW["P10"][m]
          for m in MONTHS),
      "kvadrant nazvan porogami v %d mesyacah iz %d"
      % (sum(1 for m in MONTHS if MY_RAW["P10"][m] not in ("CENTER", "ANOMALY")),
         len(MONTHS)))

_named = [m for m in MONTHS if MY_RAW["P10"][m] not in ("CENTER", "ANOMALY")]
_killed = [m for m in _named if MY_STATES["P10"][m] == "CENTER"]
_ve = R["validator_effect"]
check("C4 vklad predohranitelya formoy krivoy pereschitan",
      len(_named) == _ve["quadrant_named_by_thresholds"]
      and len(_killed) == _ve["killed_by_shape"],
      "nazvano %d (otchyot %d), pogasheno %d (otchyot %d), ostalos' %d"
      % (len(_named), _ve["quadrant_named_by_thresholds"], len(_killed),
         _ve["killed_by_shape"], len(_named) - len(_killed)))

_st0 = [classify(g, 10, 0.0, 0.0, "single")[0] for g in CALIB]
_c0 = sum(1 for x in _st0 if x == "CENTER") / len(_st0)
check("C5 dolya Centra pri theta=0 pereschitana",
      abs(_c0 - R["A_vs_B"]["center_share_at_theta0"]) < 5e-4,
      "moya %.4f protiv %.4f -- odin predohranitel' derzhit %.1f%% vremeni"
      % (_c0, R["A_vs_B"]["center_share_at_theta0"], 100 * _c0))

# C6: ob'yavlennyy sec.3.5 lag publikacii IC4WSA v progone NE ispolnen
# (REPORT sec.11 p.11). Utverzhdenie "eto ne menyaet verdikta" zdes' ne
# povtoryaetsya slovami, a schitaetsya: lag primenyaetsya, vsyo pereschityvaetsya,
# i pomesyachnye sostoyaniya vetvi verdikta obyazany sovpast' do mesyaca.
_lag_kw = {"claims_step": ST_CLAIMS_LAGGED}
_lag_th, _ = calibrate(10, "single", None, **_lag_kw)
_lag_states, _ = month_states(10, _lag_th["theta_fed"], _lag_th["theta_macro"],
                              "single", **_lag_kw)
_lag_diff = [m for m in MONTHS if _lag_states[m] != MY_STATES["P10"][m]]
check("C6 primenenie ob'yavlennogo laga IC4WSA ne dvigaet ni odnogo "
      "sostoyaniya P10", not _lag_diff,
      "theta pri lage q=%.2f (%.4f/%.4f) protiv q=%.2f (%.4f/%.4f); "
      "rashozhdeniy sostoyaniy %d iz %d"
      % (_lag_th["q"], _lag_th["theta_fed"], _lag_th["theta_macro"],
         MY_THETA["P10"]["q"], MY_THETA["P10"]["theta_fed"],
         MY_THETA["P10"]["theta_macro"], len(_lag_diff), len(MONTHS)))

_sf_lag, _sm_lag = abs_scores(10, **_lag_kw)
_lag_a20, _ = month_states(10, quantile(_sf_lag, 0.20), quantile(_sm_lag, 0.20),
                           "off", **_lag_kw)
_lag_quad = sum(1 for m in MONTHS
                if _lag_a20[m] not in ("CENTER", "ANOMALY"))
_base_quad = sum(1 for m in MONTHS
                 if MY_STATES["A20NOVAL"][m] not in ("CENTER", "ANOMALY"))
check("C6-bis pri lage sdvigaetsya tol'ko posthoc-konfiguraciya A20NOVAL",
      _lag_quad != _base_quad,
      "kvadrantnyh mesyacev pri lage %d protiv %d bez nego"
      % (_lag_quad, _base_quad))

# =========================================================================== #
head("D. Nezavisimyy pereschyot zayavlennyh doley")

for cfg, src in (("P10", "main"), ("A20NOVAL", None)):
    for h in (1, 3):
        rows = hits_for(MY_STATES[cfg], h)
        mine = rate(rows)
        theirs = (R["main"] if src else R["posthoc_cfg"][cfg])["pooled"][
            "h%d" % h]["rate"]
        check("D.%s h%d pul sovpal s otchyotom" % (cfg, h),
              abs(mine - theirs) < 5e-4,
              "moy %.4f protiv %.4f (n=%d)" % (mine, theirs, len(rows)))

for cfg, grp, src in (("A20NOVAL", "quad", "posthoc_cfg"),
                      ("P10", "center", "main")):
    states = MY_STATES[cfg]
    if grp == "quad":
        sub = {m: s for m, s in states.items()
               if s not in ("CENTER", "ANOMALY")}
        theirs = R["posthoc_cfg"][cfg]["pooled_decomp"]["quad_h1"]
    else:
        sub = {m: s for m, s in states.items() if s == "CENTER"}
        theirs = R["main"]["pooled_decomp"]["center_h1"]
    rows = hits_for(sub, 1)
    check("D.razlozhenie %s/%s sovpalo" % (cfg, grp),
          abs(rate(rows) - theirs["rate"]) < 5e-4 and len(rows) == theirs["n_obs"],
          "moy %.4f na n=%d protiv %.4f na n=%d"
          % (rate(rows), len(rows), theirs["rate"], theirs["n_obs"]))

rows_f = hits_for(MY_STATES["A20NOVAL"], 1, flip=True)
check("D.perevyornutye predpisaniya dayut 1 - dolya",
      abs(rate(rows_f) - (1.0 - rate(hits_for(MY_STATES["A20NOVAL"], 1))))
      < 1e-12,
      "%.4f protiv %.4f" % (rate(rows_f),
                            1.0 - rate(hits_for(MY_STATES["A20NOVAL"], 1))))

# D5: predpisano protiv poschitano. Pul pechataet chislo nablyudeniy i molchit
#     o tom, chto chast' predpisannyh par-mesyacev vypala.
_pres = _cnt = 0
_drop = []
for _k in SPEC_PAIRS:
    for _m in MONTHS:
        s = MY_STATES["A20NOVAL"][_m]
        if s in ("CENTER", "ANOMALY") or SPEC_PAIRS[_k][2].get(s) is None:
            continue
        _pres += 1
        r = ret(_k, _m, 1)
        if r is None:
            _drop.append("%s %s net ceny" % (_k, _m))
        elif r == 0.0:
            _drop.append("%s %s tochnyy nul'" % (_k, _m))
        else:
            _cnt += 1
_acc = R["posthoc_cfg"]["A20NOVAL"]["accounting"]["quad_h1"]
check("D5 uchyot 'predpisano protiv poschitano' sovpal s otchyotom",
      _pres == _acc["prescribed"] and _cnt == _acc["counted"],
      "predpisano %d, poschitano %d, vypalo %d [%s]"
      % (_pres, _cnt, len(_drop), "; ".join(_drop[:6])))

# =========================================================================== #
head("E. Trebovaniya A i B sec.1.4.7: oba bez dopustimogo vyhoda")

ab = R["A_vs_B"]
_g020 = [r for r in calibrate(10, "single", 0.20)[1] if r["q"] == 0.20][0]
check("E1 pri q=0.20 trebovanie B (ispolnennoe chtenie) ne vypolneno",
      _g020["spell"] < MIN_SPELL,
      "spell %.1f dn. pri trebuemyh %d" % (_g020["spell"], MIN_SPELL))
check("E2 pri naimen'shem q, dayushchem B, A narusheno grubo",
      MY_THETA["P10"]["center"] > 3 * CENTER_TARGET,
      "Centr %.1f%% pri obeshchannyh %.0f%%"
      % (100 * MY_THETA["P10"]["center"], 100 * CENTER_TARGET))
check("E3 A nedostizhimo ni pri kakom theta (granica pri theta=0)",
      _c0 > 3 * CENTER_TARGET and ab["A_reachable_at_any_theta"] is False,
      "Centr pri theta=0: %.1f%%" % (100 * _c0))

# E4: trebovanie B PO BUKVE speki -- "v odnom KVADRANTE ne men'she mesyaca".
#     Ispolneno bylo pereopredelenie ("v odnom SOSTOYANII", to est' s Centrom).
_sf, _sm = abs_scores(10)
_best = (0.0, None, None)
for _q in WIDE_Q:
    _tf, _tm = quantile(_sf, _q), quantile(_sm, _q)
    for _val in ("single", "off"):
        _st = [classify(g, 10, _tf, _tm, _val)[0] for g in CALIB]
        _sp = mean_spell_quad(CALIB, _st)
        if _sp > _best[0]:
            _best = (_sp, _q, _val)
check("E4 trebovanie B PO BUKVE speki nedostizhimo ni pri kakom q",
      _best[0] < MIN_SPELL,
      "maksimum %.3f dn. (q=%.2f, validator=%s) pri trebuemyh %d na setke "
      "0.20..0.98" % (_best[0], _best[1], _best[2], MIN_SPELL))

# E5: vtoraya prichina nedostizhimosti A -- arifmeticheskaya, bez dannyh.
_pred = 1.0 - (1.0 - CENTER_TARGET) ** 2
check("E5 pri nezavisimyh osyah 20-y percentil' dayot Centr 0.36, a ne 0.20",
      abs(MY_THETA["A20NOVAL"]["center"] - _pred) < 0.05,
      "predskazano %.2f, izmereno (porogi bez predohranitelya) %.4f"
      % (_pred, MY_THETA["A20NOVAL"]["center"]))

# =========================================================================== #
head("F. Mutacii: kazhdaya proverka obyazana KRASNET'")

# --- F1-F3: gate li blok D --------------------------------------------------
base = R["posthoc_cfg"]["A20NOVAL"]["pooled"]["h1"]["rate"]

st = dict(MY_STATES["A20NOVAL"])
keys = sorted(st)
vals = [st[k] for k in keys]
random.Random(1).shuffle(vals)
r_shuf = rate(hits_for(dict(zip(keys, vals)), 1))
check("F1 peremeshannye sostoyaniya lomayut sovpadenie",
      abs(r_shuf - base) >= 5e-4,
      "peremeshano %.4f protiv otchyota %.4f" % (r_shuf, base))

saved = SPEC_PAIRS["GOLD"][2]["I"]
SPEC_PAIRS["GOLD"][2]["I"] = -saved
r_mut = rate(hits_for(MY_STATES["A20NOVAL"], 1))
SPEC_PAIRS["GOLD"][2]["I"] = saved
check("F2 podmena odnogo znaka v tablice lomaet sovpadenie",
      abs(r_mut - base) >= 5e-4,
      "s podmenoy %.4f protiv otchyota %.4f" % (r_mut, base))

r_h3 = rate(hits_for(MY_STATES["A20NOVAL"], 3))
check("F3 drugoy gorizont dayot druguyu dolyu", abs(r_h3 - base) >= 5e-4,
      "h3 %.4f protiv h1 %.4f" % (r_h3, base))

# --- F4-F5: gate li blok B (perevorot znaka i ustarevshiy yakor') -----------


def ret_flipped(key, m, h):
    r = ret(key, m, h)
    return None if r is None else -r


_prev_day = {}
_all_days = sorted({d for s in PX.values() for d in s})
for _i, _d in enumerate(_all_days):
    if _i:
        _prev_day[_d] = _all_days[_i - 1]


def ret_stale(key, m, h):
    """Yakor' vhoda vzyat na den' ran'she -- klass defekta 'ustarevshaya cena'."""
    m2 = add_m(m, h)
    if m2 not in ME:
        return None
    a = level(key, _prev_day.get(ME[m], ME[m]))
    b = level(key, ME[m2])
    return None if a is None or b is None else b - a


_or = {}
for _m in MONTHS:
    _d = ref_dir("GOLD", _m, 1)
    if _d:
        _or[_m] = "I" if _d > 0 else "III"
_r_flip = rate(hits_for(_or, 1, keys=["GOLD"], ret_fn=ret_flipped))
check("F4 perevorot znaka dohodnosti delaet blok B krasnym",
      abs(_r_flip - 1.0) > 1e-9,
      "orakul dal by %.4f vmesto 1.0000" % _r_flip)
_r_stale = rate(hits_for(_or, 1, keys=["GOLD"], ret_fn=ret_stale))
check("F5 sdvig ceny na odin torgovyy den' delaet blok B krasnym",
      abs(_r_stale - 1.0) > 1e-9,
      "orakul dal by %.4f vmesto 1.0000" % _r_stale)

# --- F6-F9: gate li blok C (pereschyot klassifikatora) ----------------------


_w_mut = dict(W_FED, dxy=0.20)
_n = sum(1 for m in MONTHS
         if month_states(10, MY_THETA["P10"]["theta_fed"],
                         MY_THETA["P10"]["theta_macro"], "single",
                         wf=_w_mut)[0][m] != MY_STATES["P10"][m])
check("F6 podmena vesa vhoda dxy (0.10 -> 0.20) lomaet sverku sostoyaniy",
      _n > 0, "rashozhdeniy %d mesyacev iz %d" % (_n, len(MONTHS)))

_claims_noflip = Step((d, -v) for d, v in _claims.items())
_ch = calibrate(10, "single", None, claims_step=_claims_noflip)[0]
_n = sum(1 for m in MONTHS
         if month_states(10, _ch["theta_fed"], _ch["theta_macro"], "single",
                         claims_step=_claims_noflip)[0][m]
         != MY_STATES["P10"][m])
check("F7 neperevyornutyy znak vhoda IC4WSA lomaet sverku sostoyaniy",
      _n > 0, "rashozhdeniy %d mesyacev iz %d" % (_n, len(MONTHS)))

_n = sum(1 for m in MONTHS if MY_STATES["NOVAL"][m] != MY_STATES["P10"][m])
check("F8 vyklyuchennyy predohranitel' formoy krivoy lomaet sverku",
      _n > 0, "rashozhdeniy %d mesyacev iz %d" % (_n, len(MONTHS)))

_n = sum(1 for m in MONTHS
         if month_states(10, MY_THETA["P10"]["theta_fed"] + 0.02,
                         MY_THETA["P10"]["theta_macro"] + 0.02,
                         "single")[0][m] != MY_STATES["P10"][m])
check("F9 sdvig theta na +0.02 lomaet sverku sostoyaniy",
      _n > 0, "rashozhdeniy %d mesyacev iz %d" % (_n, len(MONTHS)))

_n = sum(1 for m in MONTHS
         if month_states(10, MY_THETA["P10"]["theta_fed"],
                         MY_THETA["P10"]["theta_macro"], "single",
                         cutoff=0.70)[0][m] != MY_STATES["P10"][m])
check("F10 otsechka 0.60 -> 0.70 delaet obe osi neschitaemymi",
      _n > 0, "rashozhdeniy %d mesyacev iz %d (dostupnyy ves 0.65/0.64)"
      % (_n, len(MONTHS)))

# =========================================================================== #
head("ITOG")
print("  proshlo %d, provaleno %d" % (len(PASS), len(FAIL)))
for f in FAIL:
    print("    PROVAL: %s" % f)
sys.exit(1 if FAIL else 0)
