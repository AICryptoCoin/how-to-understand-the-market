#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z25 -- ch'yo svoystvo perelom 2009 goda: klass oprosov ili troe sopernikov.

Ves' raschyot zadachi. Kriterii, reestr ryadov, konvenciya datirovki i pravila
resheniya po kazhdomu soperniku zafiksirovany v HYPOTHESIS.md DO etogo progona
(dva kommita: pred-registraciya i dva utochneniya).

Pechat' tol'ko ASCII: konsol' etoy mashiny v cp1251.

    python run.py            # polnyy progon
    python run.py --quick    # umen'shennyy bootstrap, dlya otladki koda

Bai-Perron (Seg / sup_f / bp_partition / bp_bic) i blochnyy bootstrap
perenseny iz Z06/run.py bez izmeneniy logiki -- odin pribor na vse ryady --
i eto edinstvennoe zaimstvovanie koda. Z06 pri etom ne pravitsya.
"""

from __future__ import annotations

import io
import itertools
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
_RESEARCH = os.path.dirname(_HERE)
_Z06 = os.path.join(_RESEARCH, "Z06")
for _p in (_HERE, _Z06, _RESEARCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sources as S          # noqa: E402
import composite as C        # noqa: E402

# ===========================================================================
# Konstanty -- vse iz HYPOTHESIS.md, ni odna ne podobrana po rezultatu
# ===========================================================================

SEED = 20260801
QUICK = "--quick" in sys.argv
B_BOOT = 400 if QUICK else 5000
B_BP = 400 if QUICK else 5000

TRIM = 0.15                 # HYPOTHESIS sec.4.2, kak v Z06
MAX_BREAKS = 5
BLOCK_MAIN_Q = 8            # kvartaly; Z06: 24 mesyaca = 8 kvartalov
BLOCKS_Q = (4, 8, 12)
DEGENERATE_RATIO = 8        # n / L; nizhe -- bootstrap vyrozhdaetsya
MIN_N_REG = 20              # nizhe etogo regressiya bessmyslenna

WIN_START = "1994-01-01"    # 1994Q1 -- pervyy polnyy kvartal kompozita Z06
SPLIT = "2009-10-01"        # 2009Q4 -- pervoe nablyudenie prihodyashchego rezhima
PLACEBO_SPLITS = ("2008-10-01", "2009-10-01", "2010-10-01")

COVID_START = C.COVID_START  # 2020-03-01
COVID_END = C.COVID_END      # 2021-12-01

RESULT: dict[str, Any] = {"task": "Z25", "seed": SEED, "quick": QUICK}
T0 = time.time()

_LOG = io.open(os.path.join(_HERE, "full-run.txt"), "w", encoding="ascii",
               errors="replace", newline="\n")


def say(*parts: Any) -> None:
    line = " ".join(str(p) for p in parts)
    _LOG.write(line + "\n")
    _LOG.flush()
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)


def head(title: str) -> None:
    say("")
    say("=" * 100)
    say(title)
    say("=" * 100)


# ===========================================================================
# Arifmetika (iz Z06/run.py)
# ===========================================================================

def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def sd(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    m = mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (n - 1)) ** 0.5


def pct(xs: Sequence[float], q: float) -> float:
    ys = sorted(xs)
    if not ys:
        return float("nan")
    pos = (len(ys) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ys) - 1)
    frac = pos - lo
    return ys[lo] * (1 - frac) + ys[hi] * frac


def ols(x: Sequence[float], y: Sequence[float]) -> tuple[float, float, float]:
    n = len(x)
    if n < 3:
        return float("nan"), float("nan"), float("nan")
    sx = sum(x); sy = sum(y)
    sxx = sum(v * v for v in x); sxy = sum(a * b for a, b in zip(x, y))
    den = n * sxx - sx * sx
    if den == 0:
        return float("nan"), float("nan"), float("nan")
    beta = (n * sxy - sx * sy) / den
    alpha = (sy - beta * sx) / n
    ssr = sum((b - alpha - beta * a) ** 2 for a, b in zip(x, y))
    return alpha, beta, ssr


def corr(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = mean(x), mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    return num / (dx * dy) if dx and dy else float("nan")


def holm(pvals: dict[str, float], m: int | None = None) -> dict[str, float]:
    """Poprvka Holma na obyavlennoe semeystvo.

    ``m`` -- obyavlennyy razmer semeystva. Esli chast' gipotez ne poschitalas'
    (naprimer para vyrodilas'), poprvka vsyo ravno schitaetsya na obyavlennoe
    chislo: eto konservativno i chestno.
    """
    items = sorted(((k, v) for k, v in pvals.items() if not math.isnan(v)),
                   key=lambda kv: kv[1])
    mm = m if m is not None else len(items)
    out: dict[str, float] = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        adj = min(1.0, (mm - i) * p)
        running = max(running, adj)
        out[k] = running
    for k, v in pvals.items():
        if math.isnan(v):
            out[k] = float("nan")
    return out


# ===========================================================================
# Blochnyy bootstrap (iz Z06/run.py)
# ===========================================================================

def block_index(n: int, blk: int, rng: random.Random) -> list[int]:
    """Krugovoy skol'zyashchiy blok."""
    nb = -(-n // blk)
    idx: list[int] = []
    for _ in range(nb):
        s = rng.randrange(n)
        idx.extend((s + k) % n for k in range(blk))
    return idx[:n]


def degenerate(n: int, blk: int) -> bool:
    return n / blk < DEGENERATE_RATIO


def pick_block(n: int) -> int | None:
    """Naibol'shaya obyavlennaya dlina bloka, prohodyashchaya predohranitel'.

    HYPOTHESIS sec.11, Utochnenie 2: vnutri rezhima L=8 predohranitel' ne
    prohodit (n okolo 60), poetomu beryotsya ladder 12 -> 8 -> 4.
    """
    for blk in sorted(BLOCKS_Q, reverse=True):
        if not degenerate(n, blk):
            return blk
    return None


def two_sided_p(draws: Sequence[float], null: float = 0.0) -> float:
    """Dvustoronniy bootstrap-p po forme (1 + k) / (B + 1)."""
    if not draws:
        return float("nan")
    b = len(draws)
    below = (1 + sum(1 for d in draws if d <= null)) / (b + 1)
    above = (1 + sum(1 for d in draws if d >= null)) / (b + 1)
    return min(1.0, 2 * min(below, above))


def one_sided_p_below(draws: Sequence[float], null: float = 0.0) -> float:
    """p dlya al'ternativy 'statistika men'she null'."""
    if not draws:
        return float("nan")
    return (1 + sum(1 for d in draws if d >= null)) / (len(draws) + 1)


# ===========================================================================
# Bai-Perron (iz Z06/run.py)
# ===========================================================================

class Seg:
    """Prefiksnye summy: SSR lyubogo segmenta za O(1)."""

    def __init__(self, x: Sequence[float], y: Sequence[float]) -> None:
        n = len(x)
        self.n = n
        self.sx = [0.0] * (n + 1); self.sy = [0.0] * (n + 1)
        self.sxx = [0.0] * (n + 1); self.sxy = [0.0] * (n + 1)
        self.syy = [0.0] * (n + 1)
        for i in range(n):
            self.sx[i + 1] = self.sx[i] + x[i]
            self.sy[i + 1] = self.sy[i] + y[i]
            self.sxx[i + 1] = self.sxx[i] + x[i] * x[i]
            self.sxy[i + 1] = self.sxy[i] + x[i] * y[i]
            self.syy[i + 1] = self.syy[i] + y[i] * y[i]

    def fit(self, i: int, j: int) -> tuple[float, float, float]:
        m = j - i + 1
        if m < 3:
            return float("nan"), float("nan"), float("inf")
        Sx = self.sx[j + 1] - self.sx[i]; Sy = self.sy[j + 1] - self.sy[i]
        Sxx = self.sxx[j + 1] - self.sxx[i]; Sxy = self.sxy[j + 1] - self.sxy[i]
        Syy = self.syy[j + 1] - self.syy[i]
        den = m * Sxx - Sx * Sx
        if den <= 1e-12:
            return float("nan"), float("nan"), float("inf")
        b = (m * Sxy - Sx * Sy) / den
        a = (Sy - b * Sx) / m
        ssr = Syy - a * Sy - b * Sxy
        return a, b, max(ssr, 0.0)

    def ssr(self, i: int, j: int) -> float:
        return self.fit(i, j)[2]


def sup_f(seg: Seg, i: int, j: int, hmin: int) -> tuple[float, int]:
    """supF proverki 'odin razryv protiv nulya' vnutri [i..j]."""
    m = j - i + 1
    if m < 2 * hmin + 1:
        return 0.0, -1
    s0 = seg.ssr(i, j)
    best, at = float("inf"), -1
    for t in range(i + hmin - 1, j - hmin + 1):
        s = seg.ssr(i, t) + seg.ssr(t + 1, j)
        if s < best:
            best, at = s, t
    if not math.isfinite(best) or best <= 0 or m - 4 <= 0:
        return 0.0, -1
    f = ((s0 - best) / 2.0) / (best / (m - 4))
    return f, at


def bp_partition(seg: Seg, n: int, hmin: int, mmax: int
                 ) -> tuple[list[list[int]], list[float]]:
    best = [[float("inf")] * n for _ in range(mmax + 1)]
    arg = [[-1] * n for _ in range(mmax + 1)]
    for j in range(hmin - 1, n):
        best[0][j] = seg.ssr(0, j)
    for k in range(1, mmax + 1):
        lo = (k + 1) * hmin - 1
        for j in range(lo, n):
            bv, ba = float("inf"), -1
            for t in range(k * hmin - 1, j - hmin + 1):
                if not math.isfinite(best[k - 1][t]):
                    continue
                v = best[k - 1][t] + seg.ssr(t + 1, j)
                if v < bv:
                    bv, ba = v, t
            best[k][j] = bv
            arg[k][j] = ba
    parts, ssrs = [], []
    for k in range(mmax + 1):
        if not math.isfinite(best[k][n - 1]):
            parts.append([]); ssrs.append(float("inf")); continue
        cuts, j, kk = [], n - 1, k
        while kk > 0:
            t = arg[kk][j]
            cuts.append(t)
            j, kk = t, kk - 1
        parts.append(sorted(cuts))
        ssrs.append(best[k][n - 1])
    return parts, ssrs


def bp_bic(ssr: float, n: int, m: int) -> float:
    if not math.isfinite(ssr) or ssr <= 0:
        return float("inf")
    k = 2 * (m + 1) + m
    return n * math.log(ssr / n) + math.log(n) * k


# ===========================================================================
# Kalendar'
# ===========================================================================

def add_months(iso: str, k: int) -> str:
    y, m = int(iso[:4]), int(iso[5:7])
    t = (y * 12 + (m - 1)) + k
    return f"{t // 12:04d}-{t % 12 + 1:02d}-01"


def month_span(a: str, b: str) -> list[str]:
    out, cur = [], a
    while cur <= b:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def quarter_of(iso: str) -> str:
    m = int(iso[5:7])
    return f"{iso[:4]}-{3 * ((m - 1) // 3) + 1:02d}-01"


def q_label(iso: str) -> str:
    return f"{iso[:4]}Q{(int(iso[5:7]) - 1) // 3 + 1}"


def is_covid_month(iso: str) -> bool:
    return COVID_START <= iso <= COVID_END


def covid_quarter_response(q: str) -> bool:
    """Kvartal'noe nablyudenie kovidnoe, esli kovidnym yavlyaetsya lyuboy mesyac
    okna otklika: ot nachala kvartala q-1 do konca kvartala q (HYPOTHESIS sec.4.6).
    """
    return any(is_covid_month(m)
               for m in month_span(add_months(q, -3), add_months(q, 2)))


def add_quarters(q: str, k: int) -> str:
    return add_months(q, 3 * k)


def q_diff(a: str, b: str) -> int:
    """Skol'ko kvartalov ot b do a."""
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return ((ya * 12 + ma) - (yb * 12 + mb)) // 3


# ===========================================================================
# Zagruzka i preobrazovaniya
# ===========================================================================

def to_month_map(s: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for d, v in zip(s.dates, s.values):
        if v is None:
            continue
        out[d[:8] + "01"] = float(v)
    return out


def sub_to_monthly(s: Any) -> dict[str, float]:
    """Nedel'nyy / dnevnoy ryad -> mesyachnoe srednee."""
    bucket: dict[str, list[float]] = {}
    for d, v in zip(s.dates, s.values):
        if v is None:
            continue
        bucket.setdefault(d[:8] + "01", []).append(float(v))
    return {k: mean(v) for k, v in bucket.items()}


def growth_log(m: dict[str, float], lag: int, scale: float) -> dict[str, float]:
    out: dict[str, float] = {}
    for t, v in m.items():
        p = add_months(t, -lag)
        if p in m and m[p] > 0 and v > 0:
            out[t] = scale * (math.log(v) - math.log(m[p]))
    return out


def diff_lag(m: dict[str, float], lag: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for t, v in m.items():
        p = add_months(t, -lag)
        if p in m:
            out[t] = v - m[p]
    return out


def to_quarter_mean(m: dict[str, float]) -> dict[str, float]:
    """Kvartal beryotsya, tol'ko esli prisutstvuyut vse tri mesyaca (pravilo Z06)."""
    bucket: dict[str, list[float]] = {}
    for t, v in m.items():
        bucket.setdefault(quarter_of(t), []).append(v)
    return {q: mean(v) for q, v in bucket.items() if len(v) == 3}


@dataclass
class Ind:
    key: str
    title: str
    cls: str          # S | H | M
    sector: str       # MFG | HOUSE | CONSUM | BANK | ECON
    typ: str          # D (uroven') | L (temp)
    sign: int
    cluster: str
    native: str       # M | W | D | Q
    load: Callable[[], Any]
    start_hint: str = ""


def _panel(key: str) -> Callable[[], Any]:
    return lambda: C.panel_series(key, "new_orders")


ROSTER: tuple[Ind, ...] = (
    # --- klass S: oprosnye -------------------------------------------------
    # pin='frozen' -- tot samyy ryad, na kotorom poschitan Z06/REPORT.md.
    # Prichina vybora -- HYPOTHESIS.md sec.11, Utochnenie 3.
    Ind("COMP", "Z06 kompozit 5 paneley FRB (new orders, FE), pin=frozen", "S",
        "MFG", "D", +1, "cl_mfg_survey", "M",
        lambda: C.composite("new_orders", method="FE", pin="frozen")),
    # Dlya BAL pina ne sushchestvuet (on tol'ko dlya postavlyaemoy
    # konfiguracii new_orders/FE), poetomu tol'ko zhivaya sborka.
    Ind("COMP_BAL", "Z06 kompozit, sbalansirovannaya panel' (BAL, 2004-06+)",
        "S", "MFG", "D", +1, "cl_mfg_survey", "M",
        lambda: C.composite("new_orders", method="BAL", pin="off")),
    Ind("PHIL", "FRB Philadelphia MBOS: new orders (NOC)", "S", "MFG", "D",
        +1, "cl_mfg_survey", "M", _panel("philly")),
    Ind("RICH", "FRB Richmond: new orders", "S", "MFG", "D",
        +1, "cl_mfg_survey", "M", _panel("richmond")),
    Ind("EMPIRE", "FRB New York Empire State: new orders", "S", "MFG", "D",
        +1, "cl_mfg_survey", "M", _panel("empire")),
    Ind("KC", "FRB Kansas City: volume of new orders", "S", "MFG", "D",
        +1, "cl_mfg_survey", "M", _panel("kansas_city")),
    Ind("DALLAS", "FRB Dallas: growth rate of orders (GROSAMFRBDAL)", "S",
        "MFG", "D", +1, "cl_mfg_survey", "M", _panel("dallas")),
    Ind("NAHB", "NAHB HMI (zastroyshchiki zhil'ya)", "S", "HOUSE", "D",
        +1, "cl_nahb", "M", lambda: S.nahb_hmi("t2")["HMI"]),
    Ind("UMCSENT", "U. Michigan Consumer Sentiment (domohozyaystva)", "S",
        "CONSUM", "D", +1, "cl_umc", "M", lambda: S.fred("UMCSENT")),
    Ind("SLOOS", "SLOOS: netto-dolya uzhestochayushchih C&I (DRTSCILM)", "S",
        "BANK", "D", -1, "cl_sloos", "Q", lambda: S.fred("DRTSCILM")),
    # --- klass H: zhyostkie ------------------------------------------------
    Ind("NEWORDER", "Zakazy: kap. tovary bez aviacii, $ (NEWORDER)", "H",
        "MFG", "L", +1, "cl_orders", "M", lambda: S.fred("NEWORDER")),
    Ind("AMTMNO", "Zakazy obrabatyvayushchey, $ (AMTMNO)", "H", "MFG", "L",
        +1, "cl_orders", "M", lambda: S.fred("AMTMNO")),
    Ind("DGORDER", "Zakazy tovarov dlit. pol'zovaniya, $ (DGORDER)", "H",
        "MFG", "L", +1, "cl_orders", "M", lambda: S.fred("DGORDER")),
    Ind("IPMAN_X", "Vypusk obrabotki (IPMAN)", "H", "MFG", "L",
        +1, "cl_output", "M", lambda: S.fred("IPMAN")),
    Ind("INDPRO", "Vypusk promyshlennosti (INDPRO)", "H", "MFG", "L",
        +1, "cl_output", "M", lambda: S.fred("INDPRO")),
    Ind("PAYEMS", "Zanyatye vne sel'skogo hozyaystva (PAYEMS)", "H", "ECON",
        "L", +1, "cl_pay", "M", lambda: S.fred("PAYEMS")),
    Ind("ICSA", "Pervichnye zayavki (ICSA)", "H", "ECON", "L",
        -1, "cl_claims", "W", lambda: S.fred("ICSA")),
    Ind("ADS", "ADS Business Conditions (FRB Philadelphia)", "H", "ECON", "D",
        +1, "cl_ads", "D", lambda: S.philfed_ads()),
    # --- gruppa M: smeshannye (v klassovyy test NE vhodyat) ----------------
    Ind("CFNAI", "CFNAI (85 indikatorov, est' diffuznye podyndeksy)", "M",
        "ECON", "D", +1, "cl_cfnai", "M", lambda: S.fred("CFNAI")),
    Ind("OECD_CLI", "OECD CLI USA (peresmatrivaetsya nazad)", "M", "ECON",
        "D", +1, "cl_oecd", "M", lambda: S.oecd_cli("USA")),
)

BY_KEY = {i.key: i for i in ROSTER}
PRIMARY = [i for i in ROSTER if i.cls in ("S", "H")]

CLUSTERS_S = ("cl_mfg_survey", "cl_nahb", "cl_umc", "cl_sloos")
CLUSTERS_H = ("cl_orders", "cl_output", "cl_pay", "cl_claims", "cl_ads")

F2_DECLARED = 40            # 20 ryadov x 2 otklika (HYPOTHESIS sec.6.2)
F3_DECLARED = 2
F1_DECLARED = 3


# ===========================================================================
# 0. Pasport dannyh
# ===========================================================================

head("Z25 sec.0 -- PASPORT DANNYH")
say(f"Zerno {SEED}; bootstrap B={B_BOOT} (BP {B_BP}); quick={QUICK}")
say("")

RAW: dict[str, dict[str, float]] = {}
FETCHED: dict[str, str] = {}
say(f"{'klyuch':10s} {'klass':5s} {'sektor':7s} {'tip':3s} {'znak':>4s} "
    f"{'n':>6s}  {'pervoe':10s} {'poslednee':10s}")
for ind in ROSTER:
    s = ind.load()
    if ind.native in ("W", "D"):
        m = sub_to_monthly(s)
    else:
        m = to_month_map(s)
    RAW[ind.key] = m
    FETCHED[ind.key] = getattr(s, "fetched_at", "")
    ks = sorted(m)
    say(f"{ind.key:10s} {ind.cls:5s} {ind.sector:7s} {ind.typ:3s} "
        f"{ind.sign:+4d} {len(m):6d}  {ks[0]:10s} {ks[-1]:10s}")

# --- pin kompozita: na kakoy versii dannyh stoit zadacha ------------------
_pin = C.pin()
say("")
say("Pin kompozita Z06 (versiya dannyh, k kotoroy pripshpilen ryad):")
say(f"  {_pin['version']}, zamorozhen {_pin['frozen_at']}, "
    f"sha256 {_pin['series']['sha256'][:16]}..., sigma_c = "
    f"{_pin['series']['sigma_c']:.4f}")
say(f"  COMP vzyat s pin='frozen' -- eto tot samyy ryad, na kotorom poschitan "
    f"Z06/REPORT.md.")
_live = C.composite("new_orders", method="FE", pin="off")
_lm = to_month_map(_live)
_fm = RAW["COMP"]
_both = sorted(set(_lm) & set(_fm))
_d = [abs(_lm[t] - _fm[t]) for t in _both]
_sigma_live = sd([v for t, v in _lm.items() if not is_covid_month(t)])
say(f"  Zhivaya sborka na segodnya: {len(_lm)} mesyacev protiv "
    f"{len(_fm)} v pine; sigma_c = {_sigma_live:.4f}")
say(f"  Rashozhdenie na obshchih {len(_both)} mesyacah: srednee |d| = "
    f"{mean(_d):.6f}, max |d| = {max(_d):.6f} = {max(_d) / _pin['series']['sigma_c']:.3f} "
    f"sigma_c; izmenilos' znacheniy: {sum(1 for v in _d if v > 1e-9)}")
say("  Prichina rashozhdeniya nazvana v Z06 (kommit 44c3e20): FRB Richmond")
say("  zadnim chislom peresmotrel istoriyu, W_ref sdvinulos'.")
RESULT["pin"] = {"version": _pin["version"], "frozen_at": _pin["frozen_at"],
                 "sha256": _pin["series"]["sha256"],
                 "sigma_c_pinned": _pin["series"]["sigma_c"],
                 "sigma_c_live": _sigma_live, "n_live": len(_lm),
                 "n_pinned": len(_fm), "mean_abs_diff": mean(_d),
                 "max_abs_diff": max(_d),
                 "n_changed": sum(1 for v in _d if v > 1e-9)}

GDPC1 = to_month_map(S.fred("GDPC1"))
IPMAN_RAW = to_month_map(S.fred("IPMAN"))
say("")
say(f"{'GDPC1':10s} otklik   n={len(GDPC1):5d}  "
    f"{min(GDPC1):10s} {max(GDPC1):10s}")
say(f"{'IPMAN':10s} otklik   n={len(IPMAN_RAW):5d}  "
    f"{min(IPMAN_RAW):10s} {max(IPMAN_RAW):10s}")

RESULT["passport"] = {
    k: {"n": len(v), "first": min(v), "last": max(v), "fetched_at": FETCHED[k]}
    for k, v in RAW.items()}


# --- otkliki ---------------------------------------------------------------

def q_growth(monthly_level: dict[str, float]) -> dict[str, float]:
    """Kvartal'nyy godovoy temp: 400*(ln Q_q - ln Q_{q-1}).

    Dlya mesyachnogo ryada kvartal beryotsya srednim po tryom mesyacam;
    dlya kvartal'nogo (GDPC1) mesyachnaya karta uzhe soderzhit odin punkt
    na kvartal, i srednee po odnomu -- on sam.
    """
    by_q: dict[str, list[float]] = {}
    for t, v in monthly_level.items():
        by_q.setdefault(quarter_of(t), []).append(v)
    lvl = {q: mean(v) for q, v in by_q.items()}
    out: dict[str, float] = {}
    for q, v in lvl.items():
        p = add_quarters(q, -1)
        if p in lvl and lvl[p] > 0 and v > 0:
            out[q] = 400.0 * (math.log(v) - math.log(lvl[p]))
    return out


Y_GDP = q_growth(GDPC1)
Y_MFG = q_growth(IPMAN_RAW)
RESPONSES = {"Y_GDP": Y_GDP, "Y_MFG": Y_MFG}


# --- indikatory ------------------------------------------------------------

def build_ind(ind: Ind, form: str = "main") -> dict[str, float]:
    """Kvartal'nyy ryad indikatora do standartizacii.

    form='main'  -- po pravilu tipa (HYPOTHESIS sec.3.1)
    form='alt'   -- protivopolozhnaya forma (HYPOTHESIS sec.11, Utochnenie 1)
    """
    m = RAW[ind.key]
    lag = 1 if ind.native == "Q" else 3
    lag12 = 4 if ind.native == "Q" else 12
    if ind.typ == "D":
        t = m if form == "main" else diff_lag(m, lag)
    else:
        t = (growth_log(m, lag, 400.0 / (lag / 3.0)) if form == "main"
             else growth_log(m, lag12, 100.0))
    t = {k: ind.sign * v for k, v in t.items()}
    if ind.native == "Q":
        return {quarter_of(k): v for k, v in t.items()}
    return to_quarter_mean(t)


IND_Q: dict[str, dict[str, dict[str, float]]] = {
    "main": {i.key: build_ind(i, "main") for i in ROSTER},
    "alt": {i.key: build_ind(i, "alt") for i in ROSTER},
}

# --- obshchee okno ---------------------------------------------------------

win_end_candidates = {}
for ind in PRIMARY:
    q = IND_Q["main"][ind.key]
    win_end_candidates[ind.key] = max(q) if q else "0000-00-00"
win_end_candidates["Y_GDP"] = max(Y_GDP)
win_end_candidates["Y_MFG"] = max(Y_MFG)
WIN_END = min(win_end_candidates.values())
limiter = [k for k, v in win_end_candidates.items() if v == WIN_END]

say("")
say("Obshchee okno (HYPOTHESIS sec.4.1): nachalo obyavleno 1994Q1, konec --")
say("posledniy kvartal, gde est' nablyudeniya u VSEH ryadov osnovnogo reestra.")
say(f"  WIN_START = {q_label(WIN_START)}   WIN_END = {q_label(WIN_END)} "
    f"(ogranichitel': {', '.join(limiter)})")
say(f"  SPLIT = {q_label(SPLIT)} -- pervoe nablyudenie prihodyashchego rezhima")
say(f"  Ozhidanie pred-registracii: 2026Q1 -- "
    f"{'SOVPALO' if q_label(WIN_END) == '2026Q1' else 'NE SOVPALO, vzyato faktichesloe'}")

RESULT["window"] = {"start": WIN_START, "end": WIN_END, "split": SPLIT,
                    "limiter": limiter,
                    "ends": {k: v for k, v in win_end_candidates.items()}}


# ===========================================================================
# Sborka pary (indikator, otklik)
# ===========================================================================

@dataclass
class Pair:
    key: str
    resp: str
    form: str
    drop_covid: bool
    win_start: str
    qs: list[str] = field(default_factory=list)
    x: list[float] = field(default_factory=list)     # z-ocenki
    xraw: list[float] = field(default_factory=list)  # do standartizacii
    y: list[float] = field(default_factory=list)
    mu: float = 0.0
    sdev: float = 1.0


def make_pair(key: str, resp: str, *, form: str = "main", drop_covid: bool = True,
              win_start: str | None = None, win_end: str | None = None,
              y_override: dict[str, float] | None = None) -> Pair:
    ind = BY_KEY[key]
    q = IND_Q[form][key]
    y = y_override if y_override is not None else RESPONSES[resp]
    ws = win_start or WIN_START
    we = win_end or WIN_END
    qs = [t for t in sorted(q)
          if ws <= t <= we and t in y
          and not (drop_covid and covid_quarter_response(t))]
    p = Pair(key=key, resp=resp, form=form, drop_covid=drop_covid, win_start=ws)
    if len(qs) < MIN_N_REG:
        return p
    raw = [q[t] for t in qs]
    p.mu, p.sdev = mean(raw), sd(raw)
    p.qs = qs
    p.xraw = raw
    p.x = [(v - p.mu) / p.sdev for v in raw] if p.sdev else raw
    p.y = [y[t] for t in qs]
    _ = ind
    return p


def split_at(p: Pair, split: str) -> tuple[list[int], list[int]]:
    pre = [i for i, t in enumerate(p.qs) if t < split]
    post = [i for i, t in enumerate(p.qs) if t >= split]
    return pre, post


def regime_stats(p: Pair, idx: Sequence[int]) -> dict[str, Any]:
    xs = [p.x[i] for i in idx]; ys = [p.y[i] for i in idx]
    if len(xs) < 3:
        return {"n": len(xs), "R": float("nan"), "beta": float("nan"),
                "alpha": float("nan"), "sd_x": float("nan"), "sd_y": float("nan")}
    a, b, _ = ols(xs, ys)
    return {"n": len(xs), "R": corr(xs, ys), "beta": b, "alpha": a,
            "sd_x": sd(xs), "sd_y": sd(ys),
            "first": p.qs[idx[0]], "last": p.qs[idx[-1]]}


def fixed_split(p: Pair, split: str = SPLIT) -> dict[str, Any]:
    pre_i, post_i = split_at(p, split)
    pre = regime_stats(p, pre_i)
    post = regime_stats(p, post_i)
    out: dict[str, Any] = {"key": p.key, "resp": p.resp, "form": p.form,
                           "drop_covid": p.drop_covid, "split": split,
                           "n": len(p.qs), "pre": pre, "post": post}
    if pre["n"] >= MIN_N_REG and post["n"] >= MIN_N_REG:
        out["dR"] = post["R"] - pre["R"]
        out["dbeta"] = post["beta"] - pre["beta"]
        out["status"] = "ok"
        # tozhdestvo R = beta * sd_x / sd_y -- razlozhenie v logarifmah
        try:
            lr = math.log(abs(post["R"]) / abs(pre["R"]))
            lb = math.log(abs(post["beta"]) / abs(pre["beta"]))
            lx = math.log(post["sd_x"] / pre["sd_x"])
            ly = math.log(post["sd_y"] / pre["sd_y"])
            out["decomp"] = {"ln_R": lr, "ln_beta": lb, "ln_sdx": lx,
                             "ln_sdy": ly, "residual": lr - (lb + lx - ly)}
            out["R_counterfactual_A"] = (pre["beta"] * pre["sd_x"] / post["sd_y"])
        except (ValueError, ZeroDivisionError):
            out["decomp"] = None
    else:
        out["dR"] = float("nan")
        out["dbeta"] = float("nan")
        out["status"] = "SHORT_REGIME"
    return out


# ===========================================================================
# Bai-Perron po pare
# ===========================================================================

#: Para, v kotoroy indikator i otklik postroeny iz ODNOGO ryada. Eto ne
#: suzhdenie o blizosti ryadov, a tozhdestvo: IPMAN po obe storony regressii.
TAUTOLOGICAL = {("IPMAN_X", "Y_MFG")}
#: Pary, gde ryady iz odnoy semi izmereniy (IP vsey promyshlennosti protiv IP
#: obrabotki). NE isklyuchayutsya -- pomechayutsya, chtoby ih ne chitali kak
#: nezavisimoe svidetel'stvo.
NEAR_TAUTOLOGICAL = {("INDPRO", "Y_MFG")}

COMPOSITION_CHANGES = {
    "COMP": ["2001-07-01", "2004-06-01"],
    "PHIL": [], "RICH": [], "EMPIRE": [], "KC": [], "DALLAS": [],
    "COMP_BAL": [],
}
COMPOSITION_TOL_Q = 2


def bp_analysis(p: Pair, blk: int, seed: int) -> dict[str, Any]:
    n = len(p.x)
    if n < MIN_N_REG:
        return {"status": "SHORT", "n": n}
    hmin = max(4, int(math.ceil(TRIM * n)))
    seg = Seg(p.x, p.y)
    mmax = min(MAX_BREAKS, max(0, n // hmin - 1))
    parts, ssrs = bp_partition(seg, n, hmin, mmax)
    bics = [bp_bic(ssrs[k], n, k) for k in range(mmax + 1)]
    m_bic = min(range(mmax + 1), key=lambda k: bics[k])

    f0, at0 = sup_f(seg, 0, n - 1, hmin)
    a0, b0, _ = ols(p.x, p.y)
    resid = [yy - a0 - b0 * xx for xx, yy in zip(p.x, p.y)]
    rng = random.Random(seed)
    draws = []
    for _ in range(B_BP):
        idx = block_index(n, blk, rng)
        ystar = [a0 + b0 * p.x[i] + resid[j] for i, j in enumerate(idx)]
        f, _ = sup_f(Seg(p.x, ystar), 0, n - 1, hmin)
        draws.append(f)
    crit95 = pct(draws, 0.95)
    pval = (1 + sum(1 for d in draws if d >= f0)) / (len(draws) + 1)

    cuts = parts[m_bic] if m_bic else []
    out: dict[str, Any] = {
        "status": "ok", "n": n, "hmin": hmin, "mmax": mmax, "block": blk,
        "supF": f0, "crit95_boot": crit95, "p_boot": pval,
        "supF_break_start": p.qs[at0 + 1] if 0 <= at0 < n - 1 else None,
        "supF_last_of_old": p.qs[at0] if at0 >= 0 else None,
        "m_bic": m_bic, "bic": bics,
        "breaks_start": [p.qs[t + 1] for t in cuts if t + 1 < n],
        "breaks_last_of_old": [p.qs[t] for t in cuts],
    }
    bounds = [0] + [t + 1 for t in cuts] + [n]
    regimes = []
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1] - 1
        a, b, _ = seg.fit(lo, hi)
        regimes.append({"from": p.qs[lo], "to": p.qs[hi], "n": hi - lo + 1,
                        "alpha": a, "beta": b,
                        "R": corr(p.x[lo:hi + 1], p.y[lo:hi + 1])})
    out["regimes"] = regimes

    # sovpadenie so smenoy sostava
    changes = COMPOSITION_CHANGES.get(p.key, [])
    flags = []
    for brk in out["breaks_start"] + ([out["supF_break_start"]]
                                      if out["supF_break_start"] else []):
        for ch in changes:
            d = abs(q_diff(brk, quarter_of(ch)))
            if d <= COMPOSITION_TOL_Q:
                flags.append({"break": brk, "change": ch, "dist_q": d})
    out["composition_suspect"] = flags
    out["composition_changes_known"] = changes
    return out


# ===========================================================================
# 1. Vosproizvedenie Z06 tem zhe kodom -- proverka, chto pribor tot zhe
# ===========================================================================

head("Z25 sec.1 -- VOSPROIZVEDENIE Z06 (kontrol' pribora)")

p_z06 = make_pair("COMP", "Y_GDP")
say(f"Para COMP -> Y_GDP na obshchem okne: n = {len(p_z06.qs)} "
    f"[{q_label(p_z06.qs[0])} .. {q_label(p_z06.qs[-1])}]  (Z06: n = 120 "
    f"[1994Q1 .. 2026Q1])")
bp_z06 = bp_analysis(p_z06, BLOCK_MAIN_Q, SEED + 1)
say(f"  supF(1|0) = {bp_z06['supF']:.3f}  krit.95% = {bp_z06['crit95_boot']:.3f}"
    f"  p = {bp_z06['p_boot']:.4f}   (Z06: supF 13.531, krit 9.555, p 0.0088)")
say(f"  BIC vybiraet m = {bp_z06['m_bic']}; razryvy (nachalo novogo rezhima): "
    f"{', '.join(q_label(b) for b in bp_z06['breaks_start']) or '-'}")
say(f"  te zhe razryvy v konvencii Z06 (posledniy mesyac starogo rezhima): "
    f"{', '.join(q_label(b) for b in bp_z06['breaks_last_of_old']) or '-'}"
    f"   (Z06 pechatala: 2003Q3, 2009Q3)")
say(f"  {'rezhim':26s} {'n':>4s} {'beta_z':>9s} {'R':>8s} {'beta_raw':>9s}")
sdx_full = sd(p_z06.xraw)
for rg in bp_z06["regimes"]:
    say(f"  {q_label(rg['from']) + ' .. ' + q_label(rg['to']):26s} "
        f"{rg['n']:4d} {rg['beta']:+9.4f} {rg['R']:+8.3f} "
        f"{rg['beta'] / sdx_full:+9.4f}")
say("  Z06 sec.5 pechatala v syryh edinicah kompozita: beta +1.6178 / +2.4378 "
    "/ +0.0867, R +0.566 / +0.873 / +0.040")
RESULT["z06_replication"] = {"pair_n": len(p_z06.qs), "bp": bp_z06,
                             "sd_x_full_raw": sdx_full}


# ===========================================================================
# 2. Svobodnyy poisk razryva po vsemu reestru (semeystvo F2)
# ===========================================================================

head("Z25 sec.2 -- SVOBODNYY POISK RAZRYVA: VES' REESTR, ODIN PRIBOR (F2)")
say("Trim 0.15, do 5 razryvov, bootstrap-kriticheskie znacheniya, blok "
    f"{BLOCK_MAIN_Q} kv.")
say("Data razryva -- PERVOE nablyudenie prihodyashchego rezhima (sec.4.3);")
say("v skobkah -- ta zhe data v konvencii Z06 (poslednee nablyudenie starogo).")
say("")

BP_ALL: dict[str, dict[str, Any]] = {}
F2_P: dict[str, float] = {}
say(f"{'ryad':10s} {'kl':2s} {'otklik':6s} {'n':>4s} {'supF':>8s} {'krit95':>8s} "
    f"{'p':>7s} {'razryv supF':>12s} {'m_BIC':>5s}  razryvy BIC")
seedc = 1000
for ind in ROSTER:
    for resp in ("Y_GDP", "Y_MFG"):
        seedc += 7
        if ind.key == "IPMAN_X" and resp == "Y_MFG":
            say(f"{ind.key:10s} {ind.cls:2s} {resp:6s}  -- propushcheno: "
                f"indikator i otklik postroeny iz odnogo ryada (tavtologiya)")
            BP_ALL[f"{ind.key}|{resp}"] = {"status": "SKIP_TAUTOLOGY"}
            continue
        p = make_pair(ind.key, resp)
        if len(p.qs) < MIN_N_REG:
            say(f"{ind.key:10s} {ind.cls:2s} {resp:6s}  -- korotko (n={len(p.qs)})")
            BP_ALL[f"{ind.key}|{resp}"] = {"status": "SHORT", "n": len(p.qs)}
            continue
        bp = bp_analysis(p, BLOCK_MAIN_Q, SEED + seedc)
        BP_ALL[f"{ind.key}|{resp}"] = bp
        F2_P[f"{ind.key}|{resp}"] = bp["p_boot"]
        brk = q_label(bp["supF_break_start"]) if bp["supF_break_start"] else "-"
        bics = ", ".join(f"{q_label(b)}" for b in bp["breaks_start"]) or "-"
        flag = "  [COMPOSITION_SUSPECT]" if bp["composition_suspect"] else ""
        say(f"{ind.key:10s} {ind.cls:2s} {resp:6s} {bp['n']:4d} {bp['supF']:8.3f} "
            f"{bp['crit95_boot']:8.3f} {bp['p_boot']:7.4f} {brk:>12s} "
            f"{bp['m_bic']:5d}  {bics}{flag}")

F2_HOLM = holm(F2_P, m=F2_DECLARED)
say("")
say(f"Poprvka Holma vnutri F2 na obyavlennye {F2_DECLARED} gipotez "
    f"(poschitano {len(F2_P)}; propushchena tavtologicheskaya para).")
say(f"{'para':22s} {'p syroy':>9s} {'p Holm':>9s}  otvergaet nol'?")
for k in sorted(F2_P, key=lambda z: F2_P[z]):
    say(f"{k:22s} {F2_P[k]:9.4f} {F2_HOLM[k]:9.4f}  "
        f"{'DA' if F2_HOLM[k] < 0.05 else 'net'}")

surv_keys = [f"{i.key}|Y_GDP" for i in ROSTER if i.cls == "S"]
hard_keys = [f"{i.key}|Y_GDP" for i in ROSTER if i.cls == "H"]
s_rej = sum(1 for k in surv_keys if F2_HOLM.get(k, 1.0) < 0.05)
h_rej = sum(1 for k in hard_keys if F2_HOLM.get(k, 1.0) < 0.05)
say("")
say(f"Otklik Y_GDP: supF otverg nol' u {s_rej} iz {len(surv_keys)} oprosnyh "
    f"i u {h_rej} iz {len(hard_keys)} zhyostkih (posle Holma vnutri F2).")
RESULT["F2"] = {"bp": BP_ALL, "p_raw": F2_P, "p_holm": F2_HOLM,
                "declared_size": F2_DECLARED,
                "survey_rejected": s_rej, "hard_rejected": h_rej,
                "survey_n": len(surv_keys), "hard_n": len(hard_keys)}


# ===========================================================================
# 3. Fiksirovannoe razbienie: odna data na vse ryady
# ===========================================================================

head("Z25 sec.3 -- FIKSIROVANNOE RAZBIENIE 2009Q4: ODNA DATA NA VSE RYADY")
say("Naklon beta -- v p.p. godovogo tempa otklika na odno standartnoe")
say("otklonenie indikatora (indikator standartizovan na vsyom okne, sec.3.2).")
say("")


def split_table(resp: str, *, form: str = "main", drop_covid: bool = True,
                split: str = SPLIT, verbose: bool = True) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    if verbose:
        say(f"otklik {resp}, forma {form}, kovid "
            f"{'isklyuchyon' if drop_covid else 'VKLYUCHYON'}, razbienie "
            f"{q_label(split)}")
        say(f"  {'ryad':10s} {'kl':2s} {'n_pre':>5s} {'n_post':>6s} "
            f"{'R_pre':>7s} {'R_post':>7s} {'dR':>7s} {'b_pre':>7s} "
            f"{'b_post':>7s} {'sdx_pre':>7s} {'sdx_post':>8s} "
            f"{'sdy_pre':>7s} {'sdy_post':>8s}")
    for ind in ROSTER:
        if (ind.key, resp) in TAUTOLOGICAL:
            rows[ind.key] = {"status": "SKIP_TAUTOLOGY"}
            if verbose:
                say(f"  {ind.key:10s} {ind.cls:2s} propushcheno: indikator i "
                    f"otklik postroeny iz odnogo ryada")
            continue
        p = make_pair(ind.key, resp, form=form, drop_covid=drop_covid)
        if len(p.qs) < MIN_N_REG:
            rows[ind.key] = {"status": "SHORT", "n": len(p.qs)}
            continue
        fs = fixed_split(p, split)
        rows[ind.key] = fs
        if (ind.key, resp) in NEAR_TAUTOLOGICAL:
            fs["near_tautological"] = True
        if verbose and fs["status"] == "ok":
            say(f"  {ind.key:10s} {ind.cls:2s} {fs['pre']['n']:5d} "
                f"{fs['post']['n']:6d} {fs['pre']['R']:+7.3f} "
                f"{fs['post']['R']:+7.3f} {fs['dR']:+7.3f} "
                f"{fs['pre']['beta']:+7.3f} {fs['post']['beta']:+7.3f} "
                f"{fs['pre']['sd_x']:7.3f} {fs['post']['sd_x']:8.3f} "
                f"{fs['pre']['sd_y']:7.3f} {fs['post']['sd_y']:8.3f}")
        elif verbose:
            say(f"  {ind.key:10s} {ind.cls:2s} {fs['status']} "
                f"(n_pre={fs['pre']['n']}, n_post={fs['post']['n']})")
    return rows


SPLIT_GDP = split_table("Y_GDP")
say("")
SPLIT_MFG = split_table("Y_MFG")
RESULT["fixed_split"] = {"Y_GDP": SPLIT_GDP, "Y_MFG": SPLIT_MFG}


# ===========================================================================
# 4. P1 -- klassovoe razlichie, perestanovka po klasteram
# ===========================================================================

head("Z25 sec.4 -- P1: KLASSOVOE RAZLICHIE (perestanovka po klasteram)")


def cluster_means(rows: dict[str, Any], stat: str = "dR") -> dict[str, float]:
    acc: dict[str, list[float]] = {}
    for ind in PRIMARY:
        r = rows.get(ind.key, {})
        if r.get("status") != "ok":
            continue
        v = r.get(stat)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        acc.setdefault(ind.cluster, []).append(v)
    return {k: mean(v) for k, v in acc.items()}


def class_stat(rows: dict[str, Any], stat: str = "dR") -> dict[str, Any]:
    cm = cluster_means(rows, stat)
    sc = [c for c in CLUSTERS_S if c in cm]
    hc = [c for c in CLUSTERS_H if c in cm]
    if not sc or not hc:
        return {"status": "SHORT", "clusters": cm}
    d_obs = mean([cm[c] for c in sc]) - mean([cm[c] for c in hc])
    allc = sc + hc
    k = len(sc)
    perms = list(itertools.combinations(range(len(allc)), k))
    ds = []
    for comb in perms:
        s_idx = set(comb)
        a = mean([cm[allc[i]] for i in s_idx])
        b = mean([cm[allc[i]] for i in range(len(allc)) if i not in s_idx])
        ds.append(a - b)
    p_one = sum(1 for d in ds if d <= d_obs + 1e-12) / len(ds)
    return {"status": "ok", "clusters": cm, "D": d_obs, "p_one_sided": p_one,
            "n_perm": len(ds), "min_p": 1.0 / len(ds),
            "clusters_S": sc, "clusters_H": hc}


P1 = class_stat(SPLIT_GDP, "dR")
say(f"Statistika D = srednee dR po klasteram S minus po klasteram H, "
    f"otklik Y_GDP.")
say(f"{'klaster':16s} {'klass':6s} {'srednee dR':>11s}   ryady")
for cl in CLUSTERS_S + CLUSTERS_H:
    if cl not in P1["clusters"]:
        continue
    members = [i.key for i in PRIMARY
               if i.cluster == cl and SPLIT_GDP.get(i.key, {}).get("status") == "ok"]
    say(f"{cl:16s} {'S' if cl in CLUSTERS_S else 'H':6s} "
        f"{P1['clusters'][cl]:+11.4f}   {', '.join(members)}")
say("")
say(f"D = {P1['D']:+.4f};  perestanovok {P1['n_perm']} (polnyy perebor), "
    f"odnostoronniy p = {P1['p_one_sided']:.4f}")
say(f"Minimal'no dostizhimyy p pri {len(P1['clusters_S'])} + "
    f"{len(P1['clusters_H'])} klasterah = {P1['min_p']:.4f} "
    f"(zapisano v HYPOTHESIS sec.6.1 DO raschyota)")
RESULT["P1"] = P1


# ===========================================================================
# 5. Sopernik A -- upala dispersiya otklika
# ===========================================================================

head("Z25 sec.5 -- SOPERNIK A: UPALA LI DISPERSIYA OTKLIKA")

fs_comp = SPLIT_GDP["COMP"]
dec = fs_comp["decomp"]
say(f"Otklik Y_GDP na obshchey vyborke: sd_pre = {fs_comp['pre']['sd_y']:.4f} "
    f"p.p., sd_post = {fs_comp['post']['sd_y']:.4f} p.p., "
    f"otnoshenie {fs_comp['post']['sd_y'] / fs_comp['pre']['sd_y']:.4f}")
say("")
say("Tochnoe tozhdestvo R = beta * sd_x / sd_y, razlozhenie v logarifmah:")
say(f"  ln(R_post/R_pre)   = {dec['ln_R']:+.4f}   (vsyo nablyudaemoe izmenenie)")
say(f"  + ln(beta_post/beta_pre) = {dec['ln_beta']:+.4f}   "
    f"({dec['ln_beta'] / dec['ln_R'] * 100:+.1f}% summy) -- SAMA SVYAZ'")
say(f"  + ln(sd_x_post/sd_x_pre) = {dec['ln_sdx']:+.4f}   "
    f"({dec['ln_sdx'] / dec['ln_R'] * 100:+.1f}%) -- dispersiya indikatora")
say(f"  - ln(sd_y_post/sd_y_pre) = {-dec['ln_sdy']:+.4f}   "
    f"({-dec['ln_sdy'] / dec['ln_R'] * 100:+.1f}%) -- DISPERSIYA OTKLIKA (sopernik A)")
say(f"  ostatok tozhdestva      = {dec['residual']:+.2e} (dolzhen byt' nol')")
say("")
say(f"Lineynyy kontrfakt: esli by izmenilas' TOL'KO dispersiya otklika, "
    f"R_post byla by {fs_comp['R_counterfactual_A']:+.4f} vmesto "
    f"nablyudaemoy {fs_comp['post']['R']:+.4f} pri "
    f"R_pre = {fs_comp['pre']['R']:+.4f}")
share_A = -dec["ln_sdy"] / dec["ln_R"]
rule_A = (share_A >= 0.5)
say("")
say(f"PRAVILO sec.5.2: sopernik A obyasnyaet, esli slagaemoe -ln(sd_y) imeet "
    f"tot zhe znak, chto summa, i sostavlyaet >= 50% eyo velichiny.")
say(f"  dolya = {share_A * 100:+.1f}%  ->  sopernik A "
    f"{'OBYASNYAET' if rule_A else 'NE OBYASNYAET'}")
say("")
say("Otdel'no: klassovyy test P1 k soperniku A nevospriimchiv po postroeniyu --")
say("oba klassa regressiruyutsya na ODIN I TOT ZHE otklik na odnoy vyborke,")
say("znachit sd_y v nih bukval'no odno chislo i raznicu mezhdu klassami sozdat'")
say("ne mozhet. Sopernik A sposoben obyasnyat' tol'ko obshchiy uroven' padeniya.")
RESULT["rival_A"] = {"decomp": dec, "share_sdy": share_A, "explains": rule_A,
                     "sd_y_pre": fs_comp["pre"]["sd_y"],
                     "sd_y_post": fs_comp["post"]["sd_y"],
                     "R_counterfactual": fs_comp["R_counterfactual_A"]}

say("")
say("Razlozhenie po vsem ryadam reestra (otklik Y_GDP):")
say(f"  {'ryad':10s} {'kl':2s} {'ln R':>8s} {'ln beta':>8s} {'ln sd_x':>8s} "
    f"{'-ln sd_y':>9s} {'dolya sd_y':>10s}")
dec_all = {}
for ind in ROSTER:
    r = SPLIT_GDP.get(ind.key, {})
    if r.get("status") != "ok" or not r.get("decomp"):
        continue
    d = r["decomp"]
    sh = -d["ln_sdy"] / d["ln_R"] if d["ln_R"] else float("nan")
    dec_all[ind.key] = {"share_sdy": sh, **d}
    say(f"  {ind.key:10s} {ind.cls:2s} {d['ln_R']:+8.4f} {d['ln_beta']:+8.4f} "
        f"{d['ln_sdx']:+8.4f} {-d['ln_sdy']:+9.4f} {sh * 100:+9.1f}%")
RESULT["rival_A"]["all_series"] = dec_all


# ===========================================================================
# 6. Sopernik B -- sektornyy sdvig
# ===========================================================================

head("Z25 sec.6 -- SOPERNIK B: SEKTORNYY SDVIG")

say("Raskladka 'sektor x priroda ryada' po dR (otklik Y_GDP):")
say(f"  {'':22s} {'opros (S)':>26s}   {'zhyostkiy (H)':>26s}")
for sect in ("MFG", "ECON", "HOUSE", "CONSUM", "BANK"):
    ss = [(i.key, SPLIT_GDP[i.key]["dR"]) for i in ROSTER
          if i.sector == sect and i.cls == "S"
          and SPLIT_GDP.get(i.key, {}).get("status") == "ok"]
    hh = [(i.key, SPLIT_GDP[i.key]["dR"]) for i in ROSTER
          if i.sector == sect and i.cls == "H"
          and SPLIT_GDP.get(i.key, {}).get("status") == "ok"]
    if not ss and not hh:
        continue
    s_txt = (f"n={len(ss)} sred.dR={mean([v for _, v in ss]):+.3f}"
             if ss else "-")
    h_txt = (f"n={len(hh)} sred.dR={mean([v for _, v in hh]):+.3f}"
             if hh else "-")
    say(f"  {sect:22s} {s_txt:>26s}   {h_txt:>26s}")

say("")
say("Kompozit protiv dvuh otklikov (odin pribor, odno razbienie):")
for resp, tbl in (("Y_GDP", SPLIT_GDP), ("Y_MFG", SPLIT_MFG)):
    r = tbl["COMP"]
    say(f"  {resp:6s}: R_pre={r['pre']['R']:+.3f} R_post={r['post']['R']:+.3f} "
        f"dR={r['dR']:+.3f}  beta_pre={r['pre']['beta']:+.3f} "
        f"beta_post={r['post']['beta']:+.3f}")

# P2: blochnyy bootstrap raznosti dR(GDP) - dR(MFG), parnyy
p_g = make_pair("COMP", "Y_GDP")
p_m = make_pair("COMP", "Y_MFG")
common_q = [t for t in p_g.qs if t in set(p_m.qs)]
gi = {t: i for i, t in enumerate(p_g.qs)}
mi = {t: i for i, t in enumerate(p_m.qs)}
pre_q = [t for t in common_q if t < SPLIT]
post_q = [t for t in common_q if t >= SPLIT]
blk_pre = pick_block(len(pre_q))
blk_post = pick_block(len(post_q))
say("")
say(f"P2: parnyy blochnyy bootstrap na obshchih kvartalah "
    f"(n_pre={len(pre_q)}, n_post={len(post_q)}).")
say(f"    dlina bloka vnutri rezhima (ladder 12->8->4, predohranitel' n/L>={DEGENERATE_RATIO}): "
    f"pre={blk_pre}, post={blk_post}")


def boot_dR(qs_pre: list[str], qs_post: list[str], idx_map: dict[str, int],
            p: Pair, sel_pre: list[int], sel_post: list[int]) -> float:
    xs = [p.x[idx_map[qs_pre[i]]] for i in sel_pre]
    ys = [p.y[idx_map[qs_pre[i]]] for i in sel_pre]
    r_pre = corr(xs, ys)
    xs2 = [p.x[idx_map[qs_post[i]]] for i in sel_post]
    ys2 = [p.y[idx_map[qs_post[i]]] for i in sel_post]
    r_post = corr(xs2, ys2)
    return r_post - r_pre


rng = random.Random(SEED + 5000)
draws_diff, draws_g, draws_m = [], [], []
if blk_pre and blk_post:
    for _ in range(B_BOOT):
        sp = block_index(len(pre_q), blk_pre, rng)
        sq = block_index(len(post_q), blk_post, rng)
        dg = boot_dR(pre_q, post_q, gi, p_g, sp, sq)
        dm = boot_dR(pre_q, post_q, mi, p_m, sp, sq)
        if math.isnan(dg) or math.isnan(dm):
            continue
        draws_g.append(dg); draws_m.append(dm); draws_diff.append(dg - dm)
    p2 = two_sided_p(draws_diff)
else:
    p2 = float("nan")

dR_g = SPLIT_GDP["COMP"]["dR"]
dR_m = SPLIT_MFG["COMP"]["dR"]
say(f"    dR(Y_GDP) = {dR_g:+.4f}   90% [{pct(draws_g, 0.05):+.4f} .. "
    f"{pct(draws_g, 0.95):+.4f}]")
say(f"    dR(Y_MFG) = {dR_m:+.4f}   90% [{pct(draws_m, 0.05):+.4f} .. "
    f"{pct(draws_m, 0.95):+.4f}]")
say(f"    raznost' dR(GDP)-dR(MFG) = {dR_g - dR_m:+.4f}  90% "
    f"[{pct(draws_diff, 0.05):+.4f} .. {pct(draws_diff, 0.95):+.4f}]  "
    f"dvustoronniy p = {p2:.4f}")

hard_mfg = [i.key for i in ROSTER if i.cls == "H" and i.sector == "MFG"]
hm_dr = [SPLIT_GDP[k]["dR"] for k in hard_mfg
         if SPLIT_GDP.get(k, {}).get("status") == "ok"]
say("")
say(f"Zhyostkie ryady OBRABOTKI protiv Y_GDP: srednee dR = {mean(hm_dr):+.4f} "
    f"({', '.join(f'{k} {SPLIT_GDP[k]['dR']:+.3f}' for k in hard_mfg)})")
say("Sopernik B podderzhan, esli svyaz' kompozita s Y_MFG derzhitsya, a "
    "zhyostkie ryady obrabotki lomayutsya tak zhe, kak oprosy.")
RESULT["rival_B"] = {"dR_gdp": dR_g, "dR_mfg": dR_m, "diff": dR_g - dR_m,
                     "p2": p2, "block_pre": blk_pre, "block_post": blk_post,
                     "ci_diff": [pct(draws_diff, 0.05), pct(draws_diff, 0.95)],
                     "ci_gdp": [pct(draws_g, 0.05), pct(draws_g, 0.95)],
                     "ci_mfg": [pct(draws_m, 0.05), pct(draws_m, 0.95)],
                     "hard_mfg_mean_dR": mean(hm_dr) if hm_dr else None,
                     "hard_mfg": {k: SPLIT_GDP[k]["dR"] for k in hard_mfg
                                  if SPLIT_GDP.get(k, {}).get("status") == "ok"}}


# ===========================================================================
# 7. Sopernik C -- shum izmereniya i sostav paneley
# ===========================================================================

head("Z25 sec.7 -- SOPERNIK C: SHUM IZMERENIYA I SOSTAV PANELEY")

# Ocenka shuma stroitsya iz panel'nyh ryadov, poetomu smeshcheniya i masshtaby
# beryotsya iz ZHIVOY sborki (pin='off'): panel'nye ryady tozhe zhivye, i
# meshat' zamorozhennye koefficienty s peresmotrennymi dannymi nel'zya.
# Sam kompozit COMP pri etom ostayotsya pripshpilennym -- zdes' schitaetsya
# ne on, a otnoshenie shum/signal ego konstrukcii.
comp_series, comp_pp = C.composite_with_passport("new_orders", method="FE",
                                                 pin="off")
panel_z: dict[str, dict[str, float]] = {}
for pk, info in comp_pp.panels.items():
    raw = to_month_map(C.panel_series(pk, "new_orders"))
    mu, sdv, off = info["mu_ref"], info["sd_ref"], info.get("fe_offset", 0.0)
    panel_z[pk] = {t: (v - mu) / sdv - off for t, v in raw.items()}

noise_m: dict[str, float] = {}
kcount: dict[str, int] = {}
for t in sorted({t for z in panel_z.values() for t in z}):
    vals = [z[t] for z in panel_z.values() if t in z]
    kcount[t] = len(vals)
    if len(vals) >= 2:
        noise_m[t] = (sd(vals) ** 2) / len(vals)

# kvartal'naya dispersiya shuma: srednee treh mesyacev, mesyachnyy shum nezavisim
noise_q: dict[str, float] = {}
bucket: dict[str, list[float]] = {}
for t, v in noise_m.items():
    bucket.setdefault(quarter_of(t), []).append(v)
for q, vs in bucket.items():
    if len(vs) == 3:
        noise_q[q] = sum(vs) / 9.0

comp_q_raw = IND_Q["main"]["COMP"]
p_comp = make_pair("COMP", "Y_GDP")
pre_i, post_i = split_at(p_comp, SPLIT)
say("Ocenka dispersii shuma kompozita po RASHOZHDENIYU PANELEY:")
say("  dlya mesyaca s k>=2 panelyami s^2_t -- vyborochnaya dispersiya panel'nyh")
say("  z posle snyatiya smeshcheniy b_j; dispersiya ih srednego = s^2_t/k_t.")
say("  Kvartal: srednee treh mesyacev, mesyachnyy shum polagaetsya nezavisimym.")
say("  var(c) beryotsya u PRIPSHPILENNOGO ryada (imenno ego beta ispravlyaetsya),")
say("  var shuma -- u zhivyh paneley. Drift pina po urovnyu okolo 0.01, to est'")
say("  okolo 1e-4 v dispersii -- na tri poryadka nizhe samoy ocenki shuma.")
say("")
say(f"  {'rezhim':22s} {'n_kv':>5s} {'sr. k':>6s} {'var_shum':>9s} "
    f"{'var(c)':>9s} {'lambda':>7s} {'beta':>8s} {'beta_ispr':>10s} "
    f"{'R':>7s} {'R_ispr':>8s}")
rivalC: dict[str, Any] = {"regimes": {}}
for nm, idx in (("pre  [.. 2009Q3]", pre_i), ("post [2009Q4 ..]", post_i)):
    qs = [p_comp.qs[i] for i in idx]
    nv = [noise_q[q] for q in qs if q in noise_q]
    kk = [mean([kcount[m] for m in month_span(q, add_months(q, 2))
                if m in kcount]) for q in qs]
    craw = [comp_q_raw[q] for q in qs]
    var_c = sd(craw) ** 2
    var_n = mean(nv) if nv else float("nan")
    lam = 1.0 - var_n / var_c
    st = regime_stats(p_comp, idx)
    say(f"  {nm:22s} {len(qs):5d} {mean(kk):6.2f} {var_n:9.4f} {var_c:9.4f} "
        f"{lam:7.4f} {st['beta']:+8.4f} {st['beta'] / lam:+10.4f} "
        f"{st['R']:+7.3f} {st['R'] / math.sqrt(lam):+8.3f}")
    rivalC["regimes"][nm.split()[0]] = {
        "n": len(qs), "mean_k": mean(kk), "var_noise": var_n, "var_c": var_c,
        "lambda": lam, "beta": st["beta"], "beta_corr": st["beta"] / lam,
        "R": st["R"], "R_corr": st["R"] / math.sqrt(lam)}

pre_c = rivalC["regimes"]["pre"]
post_c = rivalC["regimes"]["post"]
ln_b_obs = math.log(abs(post_c["beta"]) / abs(pre_c["beta"]))
ln_b_corr = math.log(abs(post_c["beta_corr"]) / abs(pre_c["beta_corr"]))
removed = 1.0 - ln_b_corr / ln_b_obs
say("")
say(f"Padenie ln(beta) nablyudaemoe = {ln_b_obs:+.4f}, posle popravki na "
    f"oslablenie = {ln_b_corr:+.4f}")
say(f"Popravka ubrala {removed * 100:+.1f}% padeniya "
    f"(pravilo sec.5.4: sopernik C obyasnyaet pri >= 50%)")
rivalC["ln_beta_obs"] = ln_b_obs
rivalC["ln_beta_corr"] = ln_b_corr
rivalC["removed_share"] = removed

# P4: sbalansirovannaya panel'
p_bal = make_pair("COMP_BAL", "Y_GDP")
fs_bal = SPLIT_GDP["COMP_BAL"]
say("")
say("Sbalansirovannaya panel' COMP_BAL (2004-06+, sostav ne menyaetsya vovse):")
if fs_bal.get("status") == "ok":
    say(f"  n_pre={fs_bal['pre']['n']} [{q_label(fs_bal['pre']['first'])} .. "
        f"{q_label(fs_bal['pre']['last'])}], n_post={fs_bal['post']['n']}")
    say(f"  R_pre={fs_bal['pre']['R']:+.4f}  R_post={fs_bal['post']['R']:+.4f}  "
        f"dR={fs_bal['dR']:+.4f}   (u COMP dR={dR_g:+.4f})")
    pre_ib, post_ib = split_at(p_bal, SPLIT)
    bp_b = pick_block(len(pre_ib))
    bq_b = pick_block(len(post_ib))
    rng4 = random.Random(SEED + 6000)
    d4 = []
    if bp_b and bq_b:
        for _ in range(B_BOOT):
            sp = block_index(len(pre_ib), bp_b, rng4)
            sq = block_index(len(post_ib), bq_b, rng4)
            xs = [p_bal.x[pre_ib[i]] for i in sp]; ys = [p_bal.y[pre_ib[i]] for i in sp]
            xs2 = [p_bal.x[post_ib[i]] for i in sq]; ys2 = [p_bal.y[post_ib[i]] for i in sq]
            r1, r2 = corr(xs, ys), corr(xs2, ys2)
            if not (math.isnan(r1) or math.isnan(r2)):
                d4.append(r2 - r1)
        p4 = one_sided_p_below(d4)
        say(f"  blok pre={bp_b}, post={bq_b}; dR 90% [{pct(d4, 0.05):+.4f} .. "
            f"{pct(d4, 0.95):+.4f}]  odnostoronniy p (dR<0) = {p4:.4f}")
    else:
        p4 = float("nan")
        say(f"  BOOTSTRAP_DEGENERATE: n_pre = {len(pre_ib)}, i ni odna "
            f"obyavlennaya dlina bloka ({', '.join(map(str, BLOCKS_Q))}) ne "
            f"prohodit predohranitel' n/L >= {DEGENERATE_RATIO} "
            f"({len(pre_ib)}/4 = {len(pre_ib) / 4:.1f}).")
        say(f"  Eto ROVNO to ogranichenie, kotoroe zapisano v HYPOTHESIS "
            f"sec.10.3 DO raschyota: u COMP_BAL do-rezhim korotkiy, i "
            f"otricatel'nyy rezul'tat na nyom mozhet znachit' nehvatku "
            f"nablyudeniy, a ne otsutstvie pereloma. Gipoteza P4 intervala "
            f"ne poluchaet; tochechnaya ocenka nizhe prinimaetsya kak")
        say(f"  opisanie, a ne kak test.")
    ratio = abs(fs_bal["dR"]) / abs(dR_g) if dR_g else float("nan")
    rule_C2 = (fs_bal["dR"] >= 0) or (ratio < 0.5)
    say(f"  |dR_BAL| / |dR_COMP| = {ratio:.3f}; znak "
        f"{'sohranyon' if fs_bal['dR'] < 0 else 'POTERYAN'}")
    say(f"  PRAVILO sec.5.4 (vtoraya polovina): sopernik C "
        f"{'OBYASNYAET' if rule_C2 else 'NE OBYASNYAET'}")
else:
    p4 = float("nan")
    ratio = float("nan")
    rule_C2 = False
    say(f"  {fs_bal.get('status')}")
rivalC["P4"] = {"p": p4, "dR_bal": fs_bal.get("dR"), "ratio": ratio,
                "rule_bal_explains": rule_C2}
rule_C = (removed >= 0.5) or rule_C2
say("")
say(f"PRAVILO sec.5.4 celikom: sopernik C "
    f"{'OBYASNYAET' if rule_C else 'NE OBYASNYAET'}")
rivalC["explains"] = rule_C
RESULT["rival_C"] = rivalC


# ===========================================================================
# 7-bis. Sopernik D -- sostav rezhima po fazam cikla
#        [IZMERENIE POSLE RASCHYOTA -- v pred-registracii ne obyavleno]
# ===========================================================================

head("Z25 sec.7-bis -- SOPERNIK D: SOSTAV REZHIMA PO FAZAM CIKLA")
say("Etot sopernik v pred-registracii NE obyavlen. On dobavlen posle togo, kak")
say("progon pokazal odinakovoe padenie R u VSEH ryadov, vklyuchaya zhyostkie:")
say("takoy rezul'tat trebuet ob'yasneniya, kotoroe ne razlichaet ryady voobshche.")
say("Nikakoy gipotezy on ne testiruet i v semeystva F1/F2/F3 ne vhodit --")
say("eto izmerenie, i ono nazvano izmereniem.")
say("")

USREC = to_month_map(S.fred("USREC"))
rec_q = {q for q in {quarter_of(t) for t in USREC}
         if any(USREC.get(m, 0.0) > 0 for m in month_span(q, add_months(q, 2)))}


def rec_count(qs: Sequence[str]) -> int:
    return sum(1 for q in qs if q in rec_q)


p_ref = make_pair("COMP", "Y_GDP")
pre_ref = [q for q in p_ref.qs if q < SPLIT]
post_ref = [q for q in p_ref.qs if q >= SPLIT]
p_ref_cv = make_pair("COMP", "Y_GDP", drop_covid=False)
pre_cv = [q for q in p_ref_cv.qs if q < SPLIT]
post_cv = [q for q in p_ref_cv.qs if q >= SPLIT]
say("Skol'ko recessionnyh kvartalov (razmetka NBER, USREC) v kazhdom rezhime:")
say(f"  kovid isklyuchyon: do-rezhim {rec_count(pre_ref)} iz {len(pre_ref)}, "
    f"posle-rezhim {rec_count(post_ref)} iz {len(post_ref)}")
say(f"  kovid vklyuchyon : do-rezhim {rec_count(pre_cv)} iz {len(pre_cv)}, "
    f"posle-rezhim {rec_count(post_cv)} iz {len(post_cv)}")
say("")
say("To est' v osnovnoy vetvi posle-rezhim ne soderzhit NI ODNOY recessii, a")
say("do-rezhim soderzhit dve (2001 i 2007-12). Sravnenie rezhimov okazyvaetsya")
say("sravneniem 's recessiyami' protiv 'bez recessiy'.")
say("")
say("Reshayushchee izmerenie: pereschitat' do-rezhim TOL'KO po kvartalam")
say("rasshireniya. Esli R do-rezhima pri etom padaet do urovnya posle-rezhima,")
say("to razryv opisyvaet sostav rezhima po fazam cikla, a ne vremya.")
say("")
say(f"  {'ryad':10s} {'kl':2s} {'R_pre vsyo':>10s} {'n':>4s} "
    f"{'R_pre rassh.':>12s} {'n':>4s} {'R_post':>8s} {'n':>4s} "
    f"{'dolya':>10s}")
say("  ('dolya' = kakuyu chast' vsego razryva R_pre -> R_post ob'yasnyaet "
    "odno tol'ko vyrezanie recessiy iz do-rezhima)")
rivalD: dict[str, Any] = {"rec_pre": rec_count(pre_ref),
                          "rec_post": rec_count(post_ref),
                          "rec_pre_covid_in": rec_count(pre_cv),
                          "rec_post_covid_in": rec_count(post_cv),
                          "rows": {}}
for ind in ROSTER:
    p = make_pair(ind.key, "Y_GDP")
    if len(p.qs) < MIN_N_REG:
        continue
    pre_i = [i for i, t in enumerate(p.qs) if t < SPLIT]
    post_i = [i for i, t in enumerate(p.qs) if t >= SPLIT]
    exp_i = [i for i in pre_i if p.qs[i] not in rec_q]
    if len(exp_i) < MIN_N_REG or len(post_i) < MIN_N_REG:
        continue
    r_all = corr([p.x[i] for i in pre_i], [p.y[i] for i in pre_i])
    r_exp = corr([p.x[i] for i in exp_i], [p.y[i] for i in exp_i])
    r_post = corr([p.x[i] for i in post_i], [p.y[i] for i in post_i])
    gone = (abs(r_exp - r_post) < abs(r_all - r_post) / 2.0)
    share = ((r_all - r_exp) / (r_all - r_post)) if r_all != r_post else float("nan")
    rivalD["rows"][ind.key] = {"R_pre_all": r_all, "n_pre_all": len(pre_i),
                               "R_pre_exp": r_exp, "n_pre_exp": len(exp_i),
                               "R_post": r_post, "n_post": len(post_i),
                               "mostly_gone": gone, "share": share}
    say(f"  {ind.key:10s} {ind.cls:2s} {r_all:+10.3f} {len(pre_i):4d} "
        f"{r_exp:+12.3f} {len(exp_i):4d} {r_post:+8.3f} {len(post_i):4d} "
        f"{share * 100:+9.1f}%")

rows_d = rivalD["rows"]
gone_n = sum(1 for v in rows_d.values() if v["mostly_gone"])
say("")
say(f"Razryv 'ischezaet bol'she chem napolovinu' pri vyrezanii recessiy iz "
    f"do-rezhima u {gone_n} ryadov iz {len(rows_d)}.")
say(f"Median R_pre po vsem kvartalam = "
    f"{pct([v['R_pre_all'] for v in rows_d.values()], 0.5):+.3f}; "
    f"tol'ko po rasshireniyu = "
    f"{pct([v['R_pre_exp'] for v in rows_d.values()], 0.5):+.3f}; "
    f"posle-rezhim = {pct([v['R_post'] for v in rows_d.values()], 0.5):+.3f}")
RESULT["rival_D"] = rivalD


# ===========================================================================
# 8. Semeystvo F1 i poprvka Holma
# ===========================================================================

head("Z25 sec.8 -- SEMEYSTVO F1 (tri gipotezy) I POPRVKA HOLMA")

F1_P = {"P1_class": P1["p_one_sided"], "P2_rivalB": p2, "P4_rivalC": p4}
F1_HOLM = holm(F1_P, m=F1_DECLARED)
say(f"{'gipoteza':14s} {'p syroy':>9s} {'p Holm':>9s}  vyvod")
for k in ("P1_class", "P2_rivalB", "P4_rivalC"):
    say(f"{k:14s} {F1_P[k]:9.4f} {F1_HOLM[k]:9.4f}  "
        f"{'otvergaet nol' if F1_HOLM[k] < 0.05 else 'NE otvergaet'}")
RESULT["F1"] = {"p_raw": F1_P, "p_holm": F1_HOLM, "declared_size": F1_DECLARED}


# ===========================================================================
# 9. Ustoychivost': setka
# ===========================================================================

head("Z25 sec.9 -- USTOYCHIVOST': SETKA")
say("Tochechnaya ocenka dR ot dliny bloka ne zavisit (blok dvigaet interval),")
say("poetomu setka tochechnyh ocenok stroitsya po pyati osyam bez bloka.")
say("")
say(f"{'kovid':9s} {'forma':6s} {'okno':8s} {'otklik':6s} {'razbienie':10s} "
    f"{'D':>8s} {'p':>7s} {'S<H?':>5s}")
GRID = []
for drop_covid in (True, False):
    for form in ("main", "alt"):
        for window in ("common", "own"):
            for resp in ("Y_GDP", "Y_MFG"):
                for sp in PLACEBO_SPLITS:
                    rows = {}
                    for ind in ROSTER:
                        if (ind.key, resp) in TAUTOLOGICAL:
                            rows[ind.key] = {"status": "SKIP_TAUTOLOGY"}
                            continue
                        ws = (WIN_START if window == "common"
                              else min(IND_Q[form][ind.key] or [WIN_START]))
                        p = make_pair(ind.key, resp, form=form,
                                      drop_covid=drop_covid, win_start=ws)
                        if len(p.qs) < MIN_N_REG:
                            rows[ind.key] = {"status": "SHORT"}
                            continue
                        rows[ind.key] = fixed_split(p, sp)
                    cs = class_stat(rows, "dR")
                    cell = {"covid": "isklyuchyon" if drop_covid else "vklyuchyon",
                            "form": form, "window": window, "resp": resp,
                            "split": sp, "status": cs["status"]}
                    if cs["status"] == "ok":
                        cell["D"] = cs["D"]; cell["p"] = cs["p_one_sided"]
                        say(f"{cell['covid']:9s} {form:6s} {window:8s} {resp:6s} "
                            f"{q_label(sp):10s} {cs['D']:+8.4f} "
                            f"{cs['p_one_sided']:7.4f} "
                            f"{'DA' if cs['D'] < 0 else 'net':>5s}")
                    else:
                        say(f"{cell['covid']:9s} {form:6s} {window:8s} {resp:6s} "
                            f"{q_label(sp):10s}   {cs['status']}")
                    GRID.append(cell)

ok_cells = [c for c in GRID if c["status"] == "ok"]
neg = [c for c in ok_cells if c["D"] < 0]
say("")
say(f"Yacheek vsego {len(GRID)}, schitaemyh {len(ok_cells)}; D < 0 v "
    f"{len(neg)} ({len(neg) / len(ok_cells) * 100:.1f}%)")
say(f"D: mediana {pct([c['D'] for c in ok_cells], 0.5):+.4f}, "
    f"[p05 {pct([c['D'] for c in ok_cells], 0.05):+.4f} .. "
    f"p95 {pct([c['D'] for c in ok_cells], 0.95):+.4f}]")
for ax, vals in (("kovid", ("isklyuchyon", "vklyuchyon")),
                 ("forma", ("main", "alt")),
                 ("okno", ("common", "own")),
                 ("otklik", ("Y_GDP", "Y_MFG")),
                 ("razbienie", PLACEBO_SPLITS)):
    for v in vals:
        f = "split" if ax == "razbienie" else {"kovid": "covid", "forma": "form",
                                               "okno": "window",
                                               "otklik": "resp"}[ax]
        sel = [c for c in ok_cells if c[f] == v]
        if not sel:
            continue
        lbl = q_label(v) if ax == "razbienie" else v
        say(f"  {ax:10s} {lbl:12s} mediana D = "
            f"{pct([c['D'] for c in sel], 0.5):+.4f}, D<0 v "
            f"{sum(1 for c in sel if c['D'] < 0)}/{len(sel)}")
RESULT["grid"] = GRID

# --- mesyachnyy pribor Z06 kak otdel'naya os' ------------------------------
say("")
say("Os' 'chastota pribora': mesyachnyy pribor Z06 (otklik IPMAN, okno vperyod")
say("h=3) na kompozite -- spravochno, v klassovyy test ne vhodit.")


def monthly_pairs_z06(comp: dict[str, float], resp: dict[str, float], h: int
                      ) -> tuple[list[str], list[float], list[float]]:
    ds, xs, ys = [], [], []
    for t in sorted(comp):
        u = add_months(t, h)
        if t not in resp or u not in resp or resp[t] <= 0 or resp[u] <= 0:
            continue
        if any(is_covid_month(m) for m in month_span(t, u)):
            continue
        ds.append(t); xs.append(comp[t])
        ys.append(1200.0 / h * (math.log(resp[u]) - math.log(resp[t])))
    return ds, xs, ys


dm, xm, ym = monthly_pairs_z06(RAW["COMP"], IPMAN_RAW, 3)
pre_m = [i for i, t in enumerate(dm) if t < SPLIT]
post_m = [i for i, t in enumerate(dm) if t >= SPLIT]
r_pre_m = corr([xm[i] for i in pre_m], [ym[i] for i in pre_m])
r_post_m = corr([xm[i] for i in post_m], [ym[i] for i in post_m])
say(f"  n={len(dm)} [{dm[0]} .. {dm[-1]}]; R_pre={r_pre_m:+.4f} "
    f"R_post={r_post_m:+.4f} dR={r_post_m - r_pre_m:+.4f}")
RESULT["monthly_axis"] = {"n": len(dm), "R_pre": r_pre_m, "R_post": r_post_m,
                          "dR": r_post_m - r_pre_m}


# ===========================================================================
# 9-bis. Chetyre izmereniya posle raschyota
#        [ne testy, v semeystva ne vhodyat]
# ===========================================================================

head("Z25 sec.9-bis -- IZMERENIYA POSLE RASCHYOTA (ne testy)")


def ranks(xs: Sequence[float]) -> list[float]:
    """Srednie rangi pri svyazkah: ravenstvo PRISVAIVAETSYA, a ne vychislyaetsya."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = r
        i = j + 1
    return out


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    return corr(ranks(x), ranks(y))


say("A. Rangovaya korrelyaciya (Spirmen) -- neuyazvima k vykidnym 2020 goda.")
say(f"  {'ryad':10s} {'kl':2s} {'bez kovida: pre':>15s} {'post':>7s} {'dRho':>7s} "
    f"{'| s kovidom: pre':>17s} {'post':>7s} {'dRho':>7s}")
rank_rows = {}
for ind in ROSTER:
    row: dict[str, Any] = {}
    for dc, tag in ((True, "no_covid"), (False, "covid")):
        p = make_pair(ind.key, "Y_GDP", drop_covid=dc)
        if len(p.qs) < MIN_N_REG:
            continue
        pi = [i for i, t in enumerate(p.qs) if t < SPLIT]
        qi = [i for i, t in enumerate(p.qs) if t >= SPLIT]
        if len(pi) < MIN_N_REG or len(qi) < MIN_N_REG:
            continue
        r1 = spearman([p.x[i] for i in pi], [p.y[i] for i in pi])
        r2 = spearman([p.x[i] for i in qi], [p.y[i] for i in qi])
        row[tag] = {"pre": r1, "post": r2, "d": r2 - r1}
    if "no_covid" in row and "covid" in row:
        a, b = row["no_covid"], row["covid"]
        say(f"  {ind.key:10s} {ind.cls:2s} {a['pre']:+15.3f} {a['post']:+7.3f} "
            f"{a['d']:+7.3f} {b['pre']:+17.3f} {b['post']:+7.3f} {b['d']:+7.3f}")
    rank_rows[ind.key] = row


def class_stat_from(vals: dict[str, float]) -> dict[str, Any]:
    acc: dict[str, list[float]] = {}
    for ind in PRIMARY:
        if ind.key in vals and not math.isnan(vals[ind.key]):
            acc.setdefault(ind.cluster, []).append(vals[ind.key])
    cm = {k: mean(v) for k, v in acc.items()}
    sc = [c for c in CLUSTERS_S if c in cm]
    hc = [c for c in CLUSTERS_H if c in cm]
    if not sc or not hc:
        return {"status": "SHORT"}
    d_obs = mean([cm[c] for c in sc]) - mean([cm[c] for c in hc])
    allc = sc + hc
    ds = []
    for comb in itertools.combinations(range(len(allc)), len(sc)):
        s_idx = set(comb)
        ds.append(mean([cm[allc[i]] for i in s_idx])
                  - mean([cm[allc[i]] for i in range(len(allc)) if i not in s_idx]))
    return {"status": "ok", "D": d_obs, "clusters": cm,
            "p_one_sided": sum(1 for d in ds if d <= d_obs + 1e-12) / len(ds)}


cs_rank_nc = class_stat_from({k: v["no_covid"]["d"] for k, v in rank_rows.items()
                              if "no_covid" in v})
cs_rank_cv = class_stat_from({k: v["covid"]["d"] for k, v in rank_rows.items()
                              if "covid" in v})
say("")
say(f"  Klassovaya statistika po dRho: bez kovida D = {cs_rank_nc['D']:+.4f} "
    f"(p={cs_rank_nc['p_one_sided']:.4f}); s kovidom D = {cs_rank_cv['D']:+.4f} "
    f"(p={cs_rank_cv['p_one_sided']:.4f})")

say("")
say("B. Rychag kovidnyh kvartalov: R posle-rezhima s kovidom, no bez dvuh")
say("   samyh krupnyh po |otkloneniyu otklika| nablyudeniy.")
say(f"  {'ryad':10s} {'kl':2s} {'R_post s kovidom':>17s} {'bez 2 vybrosov':>15s} "
    f"{'vybroshennye':>22s}")
lev_rows = {}
for ind in ROSTER:
    p = make_pair(ind.key, "Y_GDP", drop_covid=False)
    if len(p.qs) < MIN_N_REG:
        continue
    qi = [i for i, t in enumerate(p.qs) if t >= SPLIT]
    if len(qi) < MIN_N_REG + 2:
        continue
    ys = [p.y[i] for i in qi]
    my = mean(ys)
    drop = sorted(qi, key=lambda i: -abs(p.y[i] - my))[:2]
    keep = [i for i in qi if i not in set(drop)]
    r_full = corr([p.x[i] for i in qi], [p.y[i] for i in qi])
    r_keep = corr([p.x[i] for i in keep], [p.y[i] for i in keep])
    lev_rows[ind.key] = {"R_post_covid": r_full, "R_post_covid_trim2": r_keep,
                         "dropped": [q_label(p.qs[i]) for i in sorted(drop)]}
    say(f"  {ind.key:10s} {ind.cls:2s} {r_full:+17.3f} {r_keep:+15.3f} "
        f"{', '.join(q_label(p.qs[i]) for i in sorted(drop)):>22s}")

say("")
say("C. Otnoshenie sd indikatora mezhdu rezhimami protiv togo zhe u otklika.")
say("   Esli mir zatih, a shum izmereniya ostalsya prezhnim, to u ryada s")
say("   bol'shim shumom sd upadyot MEN'SHE, chem u otklika.")
sdy_ratio = (SPLIT_GDP["COMP"]["post"]["sd_y"] / SPLIT_GDP["COMP"]["pre"]["sd_y"])
say(f"   otnoshenie sd otklika = {sdy_ratio:.4f}")
say(f"  {'ryad':10s} {'kl':2s} {'sdx_post/sdx_pre':>17s} {'/ to zhe u otklika':>19s}")
sdx_rows = {}
for ind in ROSTER:
    r = SPLIT_GDP.get(ind.key, {})
    if r.get("status") != "ok":
        continue
    ratio = r["post"]["sd_x"] / r["pre"]["sd_x"]
    sdx_rows[ind.key] = {"ratio": ratio, "vs_y": ratio / sdy_ratio}
    say(f"  {ind.key:10s} {ind.cls:2s} {ratio:17.4f} {ratio / sdy_ratio:19.4f}")
cs_sdx = class_stat_from({k: v["ratio"] for k, v in sdx_rows.items()})
say(f"   Klassovaya statistika po otnosheniyu sd_x: D = {cs_sdx['D']:+.4f} "
    f"(p odnostoronniy 'S men'she H' = {cs_sdx['p_one_sided']:.4f})")

say("")
say("D. Klassovaya statistika po padeniyu naklona ln(beta_post/beta_pre)")
say("   i po odnim tol'ko ryadam s POLNYM do-rezhimom (n_pre = 63).")
lnb = {}
for ind in ROSTER:
    r = SPLIT_GDP.get(ind.key, {})
    if r.get("status") == "ok" and r.get("decomp"):
        lnb[ind.key] = r["decomp"]["ln_beta"]
cs_lnb = class_stat_from(lnb)
full_pre = {ind.key: SPLIT_GDP[ind.key]["dR"] for ind in ROSTER
            if SPLIT_GDP.get(ind.key, {}).get("status") == "ok"
            and SPLIT_GDP[ind.key]["pre"]["n"] == 63}
cs_full = class_stat_from(full_pre)
say(f"   ln(beta) : D = {cs_lnb['D']:+.4f} (p = {cs_lnb['p_one_sided']:.4f})")
say(f"   dR, tol'ko polnyy do-rezhim ({len(full_pre)} ryadov): "
    f"D = {cs_full['D']:+.4f} (p = {cs_full['p_one_sided']:.4f})")

say("")
say("E. Tot zhe vopros na GODOVOM tempe VVP vmesto kvartal'nogo.")
say("   Esli posle 2009 kvartal'nyy rost VVP stal shumom, kotoryy nichem ne")
say("   otslezhivaetsya, to na chetyryohkvartal'nom roste svyaz' obyazana")
say("   sohranit'sya. Esli ne sohranyaetsya -- delo ne v chastote.")

lvl_gdp = {}
for t, v in GDPC1.items():
    lvl_gdp[quarter_of(t)] = v
Y_GDP4 = {q: 100.0 * (math.log(v) - math.log(lvl_gdp[add_quarters(q, -4)]))
          for q, v in lvl_gdp.items()
          if add_quarters(q, -4) in lvl_gdp and lvl_gdp[add_quarters(q, -4)] > 0
          and v > 0}


def covid_q_h4(q: str) -> bool:
    return any(is_covid_month(m)
               for m in month_span(add_quarters(q, -4), add_months(q, 2)))


say(f"  {'ryad':10s} {'kl':2s} {'n_pre':>5s} {'n_post':>6s} {'R_pre':>8s} "
    f"{'R_post':>8s} {'dR':>8s}   (kvartal'nyy dR dlya sravneniya)")
y4_rows = {}
for ind in ROSTER:
    q = IND_Q["main"][ind.key]
    qs = [t for t in sorted(q) if WIN_START <= t <= WIN_END and t in Y_GDP4
          and not covid_q_h4(t)]
    pre = [t for t in qs if t < SPLIT]
    post = [t for t in qs if t >= SPLIT]
    if len(pre) < MIN_N_REG or len(post) < MIN_N_REG:
        continue
    r1 = corr([q[t] for t in pre], [Y_GDP4[t] for t in pre])
    r2 = corr([q[t] for t in post], [Y_GDP4[t] for t in post])
    y4_rows[ind.key] = {"n_pre": len(pre), "n_post": len(post),
                        "R_pre": r1, "R_post": r2, "dR": r2 - r1}
    say(f"  {ind.key:10s} {ind.cls:2s} {len(pre):5d} {len(post):6d} "
        f"{r1:+8.3f} {r2:+8.3f} {r2 - r1:+8.3f}   "
        f"{SPLIT_GDP[ind.key]['dR']:+8.3f}")
cs_y4 = class_stat_from({k: v["dR"] for k, v in y4_rows.items()})
say(f"   Klassovaya statistika po dR na godovom tempe: D = {cs_y4['D']:+.4f} "
    f"(p = {cs_y4['p_one_sided']:.4f})")
say(f"   Median R_post: kvartal'nyy temp "
    f"{pct([SPLIT_GDP[k]['post']['R'] for k in y4_rows], 0.5):+.3f}, "
    f"godovoy temp {pct([v['R_post'] for v in y4_rows.values()], 0.5):+.3f}")

RESULT["post_hoc"] = {"rank": rank_rows, "rank_class_no_covid": cs_rank_nc,
                      "annual_response": y4_rows, "class_y4": cs_y4,
                      "rank_class_covid": cs_rank_cv, "leverage": lev_rows,
                      "sdx_ratio": sdx_rows, "sd_y_ratio": sdy_ratio,
                      "class_sdx": cs_sdx, "class_lnbeta": cs_lnb,
                      "class_dR_full_pre": cs_full}


# ===========================================================================
# 10. Vintazhi otklika
# ===========================================================================

head("Z25 sec.10 -- VINTAZHI: PERESMATRIVAETSYA TOL'KO OTKLIK")


def fred_vintage_dates(series_id: str) -> list[str]:
    url = ("https://api.stlouisfed.org/fred/series/vintagedates"
           f"?series_id={series_id}&api_key={S._key('FRED_API_KEY')}"
           f"&file_type=json&limit=10000")
    try:
        return json.loads(S.fetch(url, tag="fred-vintages"))["vintage_dates"]
    except Exception as exc:                      # noqa: BLE001
        say(f"  [vintagedates FAIL] {series_id}: {type(exc).__name__} "
            f"{str(exc)[:90].encode('ascii', 'replace').decode()}")
        return []


def alfred(series_id: str, vintage: str) -> dict[str, float] | None:
    url = ("https://alfred.stlouisfed.org/graph/alfredgraph.csv"
           f"?id={series_id}&vintage_date={vintage}")
    try:
        body = S.fetch(url, tag="alfred")
    except Exception as exc:                      # noqa: BLE001
        say(f"  [FAIL] {series_id}@{vintage}: {type(exc).__name__} "
            f"{str(exc)[:90].encode('ascii', 'replace').decode()}")
        return None
    txt = body.decode("utf-8", "replace")
    if txt.lstrip()[:5].lower().startswith("<!do"):
        say(f"  [FAIL] {series_id}@{vintage}: telo -- HTML, ne CSV")
        return None
    out: dict[str, float] = {}
    for line in txt.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            out[parts[0][:8] + "01"] = float(parts[1])
        except ValueError:
            continue
    return out or None


vd = fred_vintage_dates("GDPC1")
say(f"Arhiv GDPC1: {len(vd)} vintazhey, {vd[0] if vd else '-'} .. "
    f"{vd[-1] if vd else '-'}")
say("Pravilo vybora obyavleno v HYPOTHESIS sec.8: pervyy vintazh kazhdogo goda")
say("s 2016 po 2026 (ranee post-rezhim koroche 24 kvartalov).")
chosen = []
for y in range(2016, 2027):
    cand = [v for v in vd if v >= f"{y}-01-01"]
    if cand:
        chosen.append(cand[0])
say("")
say(f"  {'vintazh':12s} {'n_pre':>5s} {'n_post':>6s} {'R_pre':>8s} "
    f"{'R_post':>8s} {'dR':>8s} {'dR peresm.':>11s}")
vint_rows = []
for v in chosen:
    g = alfred("GDPC1", v)
    if not g:
        continue
    yv = q_growth(g)
    last = max(yv)
    pv = make_pair("COMP", "Y_GDP", y_override=yv, win_end=min(last, WIN_END))
    if len(pv.qs) < MIN_N_REG:
        say(f"  {v:12s} korotko (n={len(pv.qs)})")
        continue
    fsv = fixed_split(pv, SPLIT)
    pr = make_pair("COMP", "Y_GDP", win_end=min(last, WIN_END))
    fsr = fixed_split(pr, SPLIT)
    if fsv["status"] != "ok" or fsr["status"] != "ok":
        say(f"  {v:12s} {fsv['status']}")
        continue
    say(f"  {v:12s} {fsv['pre']['n']:5d} {fsv['post']['n']:6d} "
        f"{fsv['pre']['R']:+8.4f} {fsv['post']['R']:+8.4f} {fsv['dR']:+8.4f} "
        f"{fsr['dR']:+11.4f}")
    vint_rows.append({"vintage": v, "n_pre": fsv["pre"]["n"],
                      "n_post": fsv["post"]["n"], "R_pre": fsv["pre"]["R"],
                      "R_post": fsv["post"]["R"], "dR": fsv["dR"],
                      "dR_revised": fsr["dR"]})
if vint_rows:
    ds_ = [r["dR"] for r in vint_rows]
    say("")
    say(f"Razbros dR po vintazham: mediana {pct(ds_, 0.5):+.4f}, "
        f"min {min(ds_):+.4f}, max {max(ds_):+.4f}; na peresmotrennyh dannyh "
        f"{dR_g:+.4f}")
say("")
say("Chego net i ne budet (Z06 sec.8): u Richmond i Kansas City vintazhey NE")
say("sushchestvuet, u ostal'nyh tryoh arhiv FRED s 2014-2016. Pyatipanel'nyy")
say("kompozit v real'nom vremeni nevosproizvodim -- vintazhnaya proverka")
say("samogo indikatora v etoy zadache nevozmozhna v principe.")
RESULT["vintages"] = {"depth": len(vd), "chosen": chosen, "rows": vint_rows}


# ===========================================================================
# 11. Proverka vne vyborki
# ===========================================================================

head("Z25 sec.11 -- PROVERKA VNE VYBORKI")
say("Obuchenie -- pervye 80% nablyudeniy obshchego okna, hvost uderzhan.")
say("Na obuchenii ocenivayutsya dve modeli: do-rezhimnaya i posle-rezhimnaya.")
say("")
say(f"  {'ryad':10s} {'kl':2s} {'n_tr':>5s} {'n_te':>5s} {'RMSE pre':>9s} "
    f"{'RMSE post':>10s}  luchshe")
oos_rows = {}
for ind in ROSTER:
    p = make_pair(ind.key, "Y_GDP")
    if len(p.qs) < MIN_N_REG * 2:
        continue
    ntr = int(round(0.8 * len(p.qs)))
    tr = list(range(ntr)); te = list(range(ntr, len(p.qs)))
    tr_pre = [i for i in tr if p.qs[i] < SPLIT]
    tr_post = [i for i in tr if p.qs[i] >= SPLIT]
    if len(tr_pre) < 10 or len(tr_post) < 10 or len(te) < 8:
        continue
    a1, b1, _ = ols([p.x[i] for i in tr_pre], [p.y[i] for i in tr_pre])
    a2, b2, _ = ols([p.x[i] for i in tr_post], [p.y[i] for i in tr_post])
    r1 = math.sqrt(mean([(p.y[i] - a1 - b1 * p.x[i]) ** 2 for i in te]))
    r2 = math.sqrt(mean([(p.y[i] - a2 - b2 * p.x[i]) ** 2 for i in te]))
    better = "post" if r2 < r1 else "pre"
    oos_rows[ind.key] = {"n_train": ntr, "n_test": len(te), "rmse_pre": r1,
                         "rmse_post": r2, "better": better,
                         "train_last": p.qs[ntr - 1], "test_first": p.qs[ntr]}
    say(f"  {ind.key:10s} {ind.cls:2s} {ntr:5d} {len(te):5d} {r1:9.4f} "
        f"{r2:10.4f}  {better}")
oos_comp = oos_rows.get("COMP", {})
say("")
say(f"KRITERIY sec.9: perelom podtverzhdaetsya vne vyborki, esli u COMP "
    f"posle-rezhimnaya model' daet men'shiy RMSE. Rezul'tat: "
    f"{oos_comp.get('better', '-')}  -> "
    f"{'PODTVERZHDAETSYA' if oos_comp.get('better') == 'post' else 'NE podtverzhdaetsya'}")
RESULT["oos"] = oos_rows


# ===========================================================================
# 12. Rasshirenie klassa: obzory EK (semeystvo F3)
# ===========================================================================

head("Z25 sec.12 -- RASSHIRENIE KLASSA: OBZORY EK (F3)")


def eurostat_one(dataset: str, **filters: str) -> dict[str, float]:
    """Odin ryad Eurostat s PROVERKOY, chto vse izmereniya krome time = 1.

    Grablya, naydennaya razvedkoy (HYPOTHESIS sec.2.3): zapros bez polnogo
    nabora fil'trov otdayot HTTP 200 i pravdopodobnyy ryad, a telom idyot
    PERVAYA po ploskomu indeksu kombinaciya izmereniy, a ne zaproshennaya.
    sources.py pri etom ne pravitsya -- zashchita zhivyot zdes'.
    """
    import urllib.parse
    url = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/"
           f"data/{dataset}?" + urllib.parse.urlencode({"format": "JSON",
                                                        **filters}))
    doc = json.loads(S.fetch(url, tag="eurostat"))
    dims = doc.get("id") or list(doc.get("dimension", {}))
    size = doc.get("size") or []
    for name, sz in zip(dims, size):
        if name != "time" and sz != 1:
            raise ValueError(
                f"eurostat {dataset}: izmerenie {name} imeet razmer {sz}, "
                f"a ne 1 -- otvet smeshivaet kombinacii. Filtry: {filters}")
    times = list(doc["dimension"]["time"]["category"]["index"])
    vals = doc.get("value", {})
    out: dict[str, float] = {}
    for i, t in enumerate(times):
        v = vals.get(str(i)) if isinstance(vals, dict) else (
            vals[i] if i < len(vals) else None)
        if v is None:
            continue
        if "Q" in t:
            y, q = t.split("-Q")
            out[f"{int(y):04d}-{3 * (int(q) - 1) + 1:02d}-01"] = float(v)
        else:
            out[t[:7] + "-01"] = float(v)
    return out


EC_RES: dict[str, Any] = {}
try:
    ea_gdp = eurostat_one("namq_10_gdp", geo="EA20", s_adj="SCA",
                          unit="CLV10_MEUR", na_item="B1GQ")
    y_ea = q_growth(ea_gdp)
    say(f"VVP evrozony (namq_10_gdp, EA20, SCA, CLV10_MEUR, B1GQ): "
        f"n={len(ea_gdp)}, {min(ea_gdp)} .. {max(ea_gdp)}")
    for key, indic in (("EC_ICI", "BS-ICI-BAL"), ("EC_ESI", "BS-ESI-I")):
        m = eurostat_one("ei_bssi_m_r2", geo="EA20", s_adj="SA", indic=indic)
        q = to_quarter_mean(m)
        qs = [t for t in sorted(q) if t in y_ea
              and not covid_quarter_response(t)]
        if len(qs) < MIN_N_REG:
            say(f"{key}: korotko (n={len(qs)})")
            continue
        raw = [q[t] for t in qs]
        mu, sdv = mean(raw), sd(raw)
        p = Pair(key=key, resp="EA_GDP", form="main", drop_covid=True,
                 win_start=qs[0])
        p.qs = qs; p.xraw = raw; p.mu = mu; p.sdev = sdv
        p.x = [(v - mu) / sdv for v in raw]
        p.y = [y_ea[t] for t in qs]
        bp = bp_analysis(p, BLOCK_MAIN_Q, SEED + 8000 + len(key))
        fs = fixed_split(p, SPLIT)
        say("")
        say(f"{key} ({indic}) -> VVP evrozony: n={len(qs)} "
            f"[{q_label(qs[0])} .. {q_label(qs[-1])}], posledniy mesyats "
            f"opros. ryada {max(m)}")
        say(f"  supF={bp['supF']:.3f} krit95={bp['crit95_boot']:.3f} "
            f"p={bp['p_boot']:.4f}  razryv supF="
            f"{q_label(bp['supF_break_start']) if bp['supF_break_start'] else '-'}"
            f"  BIC m={bp['m_bic']} razryvy="
            f"{', '.join(q_label(b) for b in bp['breaks_start']) or '-'}")
        say(f"  fiksirovannoe razbienie 2009Q4: R_pre={fs['pre']['R']:+.4f} "
            f"R_post={fs['post']['R']:+.4f} dR={fs['dR']:+.4f}")
        EC_RES[key] = {"bp": bp, "split": fs, "last_month": max(m)}
except Exception as exc:                          # noqa: BLE001
    say(f"BLOK EK NE POSCHITAN: {type(exc).__name__}: "
        f"{str(exc)[:200].encode('ascii', 'replace').decode()}")
    EC_RES["error"] = f"{type(exc).__name__}"

F3_P = {k: v["bp"]["p_boot"] for k, v in EC_RES.items() if isinstance(v, dict)
        and "bp" in v}
F3_HOLM = holm(F3_P, m=F3_DECLARED) if F3_P else {}
if F3_P:
    say("")
    say(f"Holm vnutri F3 (obyavleno {F3_DECLARED}):")
    for k in F3_P:
        say(f"  {k:10s} p={F3_P[k]:.4f} -> Holm {F3_HOLM[k]:.4f}")
RESULT["F3"] = {"results": EC_RES, "p_raw": F3_P, "p_holm": F3_HOLM}


# ===========================================================================
# 13. Obyedinyonnaya poprvka
# ===========================================================================

head("Z25 sec.13 -- OBYEDINYONNAYA POPRVKA HOLMA NA 45 GIPOTEZ")
UNION = {}
UNION.update({f"F1:{k}": v for k, v in F1_P.items()})
UNION.update({f"F2:{k}": v for k, v in F2_P.items()})
UNION.update({f"F3:{k}": v for k, v in F3_P.items()})
UNION_HOLM = holm(UNION, m=F1_DECLARED + F2_DECLARED + F3_DECLARED)
say(f"Obyavlennyy razmer obyedineniya: "
    f"{F1_DECLARED} + {F2_DECLARED} + {F3_DECLARED} = "
    f"{F1_DECLARED + F2_DECLARED + F3_DECLARED}; poschitano {len(UNION)}.")
say(f"{'gipoteza':26s} {'p syroy':>9s} {'Holm v svoyom':>13s} "
    f"{'Holm obyedin.':>13s}")
own = {**{f"F1:{k}": v for k, v in F1_HOLM.items()},
       **{f"F2:{k}": v for k, v in F2_HOLM.items()},
       **{f"F3:{k}": v for k, v in F3_HOLM.items()}}
for k in sorted(UNION, key=lambda z: UNION[z])[:18]:
    say(f"{k:26s} {UNION[k]:9.4f} {own.get(k, float('nan')):13.4f} "
        f"{UNION_HOLM[k]:13.4f}")
say("...")
changed = [k for k in ("F1:P1_class", "F1:P2_rivalB", "F1:P4_rivalC")
           if (own.get(k, 1) < 0.05) != (UNION_HOLM.get(k, 1) < 0.05)]
say(f"Gipotezy F1, u kotoryh obyedinyonnaya poprvka menyaet vyvod: "
    f"{', '.join(changed) if changed else 'net'}")
RESULT["union_holm"] = {"p_holm": UNION_HOLM, "changed_F1": changed}


# ===========================================================================
# 14. Vetv' 'kovid vklyuchyon' -- polnyy schyot, kak trebuet sec.4.6
# ===========================================================================

head("Z25 sec.14 -- VETV' 'KOVID VKLYUCHYON': POLNYY SCHYOT")
SPLIT_GDP_CV = split_table("Y_GDP", drop_covid=False)
P1_CV = class_stat(SPLIT_GDP_CV, "dR")
say("")
say(f"D = {P1_CV['D']:+.4f}, odnostoronniy p = {P1_CV['p_one_sided']:.4f} "
    f"(pri isklyuchyonnom kovide: D = {P1['D']:+.4f}, p = "
    f"{P1['p_one_sided']:.4f})")
fs_cv = SPLIT_GDP_CV["COMP"]
if fs_cv.get("decomp"):
    d = fs_cv["decomp"]
    say(f"Razlozhenie COMP pri vklyuchyonnom kovide: ln R = {d['ln_R']:+.4f} = "
        f"ln beta {d['ln_beta']:+.4f} + ln sd_x {d['ln_sdx']:+.4f} "
        f"- ln sd_y {d['ln_sdy']:+.4f}; dolya sd_y = "
        f"{-d['ln_sdy'] / d['ln_R'] * 100:+.1f}%")
say(f"sd_y: pre {fs_cv['pre']['sd_y']:.4f}, post {fs_cv['post']['sd_y']:.4f}")
RESULT["covid_included"] = {"P1": P1_CV, "split": SPLIT_GDP_CV}


# ===========================================================================
# 15. Verdikt
# ===========================================================================

head("Z25 sec.15 -- VERDIKT PO PRAVILU HYPOTHESIS sec.6.5")

c1 = (F1_HOLM["P1_class"] < 0.05) and (P1["D"] < 0)
c2 = not rule_A
dR_mfg_neg = (dR_m < 0)
c3 = dR_mfg_neg and (F1_HOLM["P2_rivalB"] >= 0.05 or dR_m < 0)
c4 = (not rule_C) and (not math.isnan(p4)) and (F1_HOLM["P4_rivalC"] < 0.05)
say(f"1. P1: Holm-p = {F1_HOLM['P1_class']:.4f} < 0.05 i D = {P1['D']:+.4f} < 0 "
    f"-> {c1}")
say(f"2. Sopernik A ne obyasnyaet (dolya sd_y = {share_A * 100:+.1f}%) -> {c2}")
say(f"3. Sopernik B otvergnut: dR(Y_MFG) = {dR_m:+.4f} -> {c3}")
say(f"4. Sopernik C ne obyasnyaet i P4 otvergaet nol' (Holm-p = "
    f"{F1_HOLM['P4_rivalC']}) -> {c4}"
    + ("   [P4 ne poschitan: bootstrap vyrozhden, sec.7]"
       if math.isnan(p4) else ""))

s_share = s_rej / max(len(surv_keys), 1)
h_share = h_rej / max(len(hard_keys), 1)
refute_1_literal = (P1["D"] >= 0) or (h_share >= s_share)
vacuous = (s_rej == 0 and h_rej == 0)
refute_2 = rule_A
refute_3 = (dR_m > -0.10) and (mean(hm_dr) < -0.10 if hm_dr else False)
refute_4 = rule_C
refute_1 = refute_1_literal
say("")
say(f"Osnovaniya OPROVERZHENIYA:")
say(f"  1. perelom i u zhyostkih: D >= 0 ({P1['D']:+.4f}) ILI dolya "
    f"otvergnutyh u H ne men'she, chem u S "
    f"({h_rej}/{len(hard_keys)} = {h_share:.3f} protiv "
    f"{s_rej}/{len(surv_keys)} = {s_share:.3f}) -> {refute_1_literal}")
if vacuous:
    say(f"     VNIMANIE: obe doli nulevye -- vtoraya polovina pravila "
        f"srabatyvaet vhollostuyu (0 >= 0), premissa 'perelom nayden u "
        f"zhyostkih' pri etom LOZHNA. Eto defekt operacionalizacii, "
        f"zapisannoy do raschyota; on nazvan v otchyote, a ne obyeden.")
say(f"  2. sopernik A obyasnyaet -> {refute_2}")
say(f"  3. sopernik B podderzhan (svyaz' s Y_MFG derzhitsya, a zhyostkaya "
    f"obrabotka lomaetsya) -> {refute_3}")
say(f"  4. sopernik C obyasnyaet -> {refute_4}")
say("")
say("Otdel'no -- sushchestvo, ne pravilo: srednee dR po klassam.")
sdr = [SPLIT_GDP[i.key]["dR"] for i in ROSTER if i.cls == "S"
       and SPLIT_GDP.get(i.key, {}).get("status") == "ok"]
hdr = [SPLIT_GDP[i.key]["dR"] for i in ROSTER if i.cls == "H"
       and SPLIT_GDP.get(i.key, {}).get("status") == "ok"]
say(f"  oprosnye (n={len(sdr)}): srednee {mean(sdr):+.4f}, razmah "
    f"[{min(sdr):+.4f} .. {max(sdr):+.4f}]")
say(f"  zhyostkie (n={len(hdr)}): srednee {mean(hdr):+.4f}, razmah "
    f"[{min(hdr):+.4f} .. {max(hdr):+.4f}]")
RESULT["class_means_dR"] = {"survey": sdr, "hard": hdr,
                            "mean_survey": mean(sdr), "mean_hard": mean(hdr)}

if all((c1, c2, c3, c4)):
    VERDICT = "PODTVERZHDENO"
elif any((refute_1, refute_2, refute_3, refute_4)):
    VERDICT = "OPROVERGNUTO"
else:
    VERDICT = "NEOPREDELENO"
say("")
say(f"VERDIKT: {VERDICT}")
RESULT["verdict"] = {
    "verdict": VERDICT,
    "confirm": {"c1": c1, "c2": c2, "c3": c3, "c4": c4},
    "refute": {"r1": refute_1, "r2": refute_2, "r3": refute_3, "r4": refute_4},
}

RESULT["elapsed_sec"] = time.time() - T0


def _json_safe(o: Any) -> Any:
    """NaN/Infinity -> null.

    json.dump pishet ih kak golye tokeny NaN/Infinity, kotorye Python
    prochtyot, a strogiy parser (lyuboy drugoy yazyk, jq, onlayn-validator) --
    net. Fail, kotoryy chitaetsya tol'ko svoim zhe kodom, dlya pereproverki
    chuzhim kodom bespolezen.
    """
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o


with open(os.path.join(_HERE, "result.json"), "w", encoding="utf-8") as fh:
    json.dump(_json_safe(RESULT), fh, ensure_ascii=False, indent=1, default=str)
say("")
say(f"Gotovo za {time.time() - T0:.1f} s. result.json zapisan.")
_LOG.close()
