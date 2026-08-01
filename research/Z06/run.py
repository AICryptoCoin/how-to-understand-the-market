#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z06 -- kalibrovka linii nulevogo rosta kompozita-zamenitelya ISM.

Ves' raschyot zadachi. Kriterii i konstrukciya zafiksirovany v HYPOTHESIS.md
DO etogo progona; zdes' oni tol'ko schitayutsya.

Pechat' tol'ko ASCII: konsol' etoy mashiny v cp1251.

    python run.py            # polnyy prognon
    python run.py --quick    # umen'shennyy bootstrap, dlya otladki koda
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from typing import Any, Callable, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
_RESEARCH = os.path.dirname(_HERE)
for _p in (_HERE, _RESEARCH):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sources as S          # noqa: E402
import composite as C        # noqa: E402

SEED = 20260728
QUICK = "--quick" in sys.argv
B_BOOT = 500 if QUICK else 5000
B_BP = 500 if QUICK else 5000
BLOCK_MAIN = 24
BLOCKS = (12, 24, 36)
H_MAIN = 3
HORIZONS = (3, 6, 12)
BASE_MAIN = "new_orders"
METHOD_MAIN = "FE"
TRIM = 0.15
MAX_BREAKS = 5
MIN_N_CELL = 20          # nizhe etogo regressiya bessmyslenna (sm. HYPOTHESIS sec.10)
DEGENERATE_RATIO = 8     # n / L_blk; nizhe -- bootstrap vyrozhdaetsya

RESULT: dict[str, Any] = {"task": "Z06", "seed": SEED, "quick": QUICK}
T0 = time.time()


def say(*parts: Any) -> None:
    line = " ".join(str(p) for p in parts)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:                      # strahovka ot cp1251
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)


def head(title: str) -> None:
    say("")
    say("=" * 100)
    say(title)
    say("=" * 100)


# ===========================================================================
# Arifmetika
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
    """Percentil' po linejnoj interpolyacii (tip 7, kak u numpy po umolchaniyu)."""
    ys = sorted(xs)
    if not ys:
        return float("nan")
    pos = (len(ys) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(ys) - 1)
    frac = pos - lo
    return ys[lo] * (1 - frac) + ys[hi] * frac


def ols(x: Sequence[float], y: Sequence[float]) -> tuple[float, float, float]:
    """(alpha, beta, SSR) dlya y = alpha + beta*x."""
    n = len(x)
    sx = sum(x); sy = sum(y)
    sxx = sum(v * v for v in x); sxy = sum(a * b for a, b in zip(x, y))
    den = n * sxx - sx * sx
    if den == 0:
        return float("nan"), float("nan"), float("nan")
    beta = (n * sxy - sx * sy) / den
    alpha = (sy - beta * sx) / n
    ssr = sum((b - alpha - beta * a) ** 2 for a, b in zip(x, y))
    return alpha, beta, ssr


def tau_of(x: Sequence[float], y: Sequence[float]) -> float:
    a, b, _ = ols(x, y)
    if not b or math.isnan(b):
        return float("nan")
    return -a / b


def corr(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = mean(x), mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    return num / (dx * dy) if dx and dy else float("nan")


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Poprvka Holma na obyavlennoe semeystvo."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out: dict[str, float] = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)
        out[k] = running
    return out


# ===========================================================================
# Blochnyy bootstrap
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


def boot(stat: Callable[[list[int]], Any], n: int, blk: int, *,
         reps: int, seed: int) -> list[Any]:
    rng = random.Random(seed)
    out = []
    for _ in range(reps):
        v = stat(block_index(n, blk, rng))
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            out.append(v)
    return out


def two_sided_p(draws: Sequence[float], null: float = 0.0) -> float:
    """Dvustoronniy bootstrap-p po forme (1 + k) / (B + 1).

    Delenie prosto na B dalo by rovnyy nol', kotoryy chitaetsya kak
    'nevozmozhno', a ne kak 'menshe 1/B' -- eto raznye utverzhdeniya.
    """
    if not draws:
        return float("nan")
    b = len(draws)
    below = (1 + sum(1 for d in draws if d <= null)) / (b + 1)
    above = (1 + sum(1 for d in draws if d >= null)) / (b + 1)
    return min(1.0, 2 * min(below, above))


def blk_q(blk_months: int) -> int:
    """Dlina bloka dlya KVARTAL'NOGO ryada.

    Pred-registraciya (HYPOTHESIS sec.6) zadayot dlinu bloka v MESYACAH:
    L_blk = 24 mesyaca. Dlya kvartal'nogo otklika eto 8 kvartalov, a ne 24 --
    24 kvartala eto shest' let, i pri n_kv okolo 120 blochnyy bootstrap
    vyrozhdaetsya (n/L = 5 pri trebuemyh 8). Eto tochnoe prochtenie
    pred-registrirovannogo pravila, a ne ego izmenenie.
    """
    return max(2, blk_months // 3)


# ===========================================================================
# Kalendar' i otkliki
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


def to_map(s: S.Series) -> dict[str, float]:
    return {d[:8] + "01": float(v) for d, v in zip(s.dates, s.values) if v is not None}


def covid_window(t: str, h: int) -> bool:
    """Nablyudenie kovidnoe, esli kovidnym yavlyaetsya lyuboy mesyac ego okna.

    Rost, poschitannyy PO kovidnym mesyacam, i sam kovidnoe nablyudenie --
    inache pravilo isklyucheniya vypuskalo by 2019-12 s oknom, konchayushchimsya
    v aprele 2020 goda.
    """
    return any(C.is_covid(m) for m in month_span(t, add_months(t, h)))


def quarter_of(iso: str) -> str:
    m = int(iso[5:7])
    return f"{iso[:4]}-{3 * ((m - 1) // 3) + 1:02d}-01"


def monthly_pairs(comp: dict[str, float], resp: dict[str, float], h: int,
                  *, drop_covid: bool, start: str | None = None,
                  end: str | None = None) -> tuple[list[str], list[float], list[float]]:
    """(daty, c, g) dlya g_t = (1200/h)*(ln R_{t+h} - ln R_t) -- okno VPERYOD."""
    ds, xs, ys = [], [], []
    for t in sorted(comp):
        if start and t < start:
            continue
        if end and t > end:
            continue
        u = add_months(t, h)
        if t not in resp or u not in resp:
            continue
        if resp[t] <= 0 or resp[u] <= 0:
            continue
        if drop_covid and covid_window(t, h):
            continue
        ds.append(t)
        xs.append(comp[t])
        ys.append(1200.0 / h * (math.log(resp[u]) - math.log(resp[t])))
    return ds, xs, ys


def quarterly_pairs(comp: dict[str, float], gdp: dict[str, float], h: int,
                    *, drop_covid: bool, start: str | None = None,
                    end: str | None = None) -> tuple[list[str], list[float], list[float]]:
    """Kvartal'nyy otklik. h=3 -> sovremennyy kvartal (q protiv q-1),
    h=6 -> srednegodovoy rost za q..q+1, h=12 -> za q..q+3."""
    by_q: dict[str, list[float]] = {}
    for t, v in comp.items():
        by_q.setdefault(quarter_of(t), []).append(v)
    cq = {q: mean(v) for q, v in by_q.items() if len(v) == 3}
    k = h // 3                       # skol'ko kvartalov vperyod sverh tekushchego
    ds, xs, ys = [], [], []
    for q in sorted(cq):
        if start and q < start:
            continue
        if end and q > end:
            continue
        prev = add_months(q, -3)
        last = add_months(q, 3 * (k - 1))
        if prev not in gdp or last not in gdp:
            continue
        if gdp[prev] <= 0 or gdp[last] <= 0:
            continue
        if drop_covid and any(C.is_covid(m)
                              for m in month_span(prev, add_months(last, 2))):
            continue
        ds.append(q)
        xs.append(cq[q])
        ys.append(400.0 / k * (math.log(gdp[last]) - math.log(gdp[prev])))
    return ds, xs, ys


# ===========================================================================
# Bai-Perron
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
    """Dinamicheskoe programmirovanie: luchshie razbieniya na 1..mmax+1 segment."""
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
# AUC / Yuden
# ===========================================================================

def auc_recession(cvals: Sequence[float], rec: Sequence[int]) -> float:
    """AUC dlya 'nizkiy kompozit -> recessiya'. Svyazki -- po 0.5."""
    pos = [c for c, r in zip(cvals, rec) if r == 1]
    neg = [c for c, r in zip(cvals, rec) if r == 0]
    if not pos or not neg:
        return float("nan")
    tot = 0.0
    for p in pos:
        for q in neg:
            tot += 1.0 if p < q else (0.5 if p == q else 0.0)
    return tot / (len(pos) * len(neg))


def youden(cvals: Sequence[float], rec: Sequence[int]) -> tuple[float, float]:
    pos = [c for c, r in zip(cvals, rec) if r == 1]
    neg = [c for c, r in zip(cvals, rec) if r == 0]
    if not pos or not neg:
        return float("nan"), float("nan")
    cand = sorted(set(cvals))
    mids = [(a + b) / 2 for a, b in zip(cand, cand[1:])] or cand
    bj, bt = -2.0, float("nan")
    for t in mids:
        tpr = sum(1 for c in pos if c <= t) / len(pos)
        fpr = sum(1 for c in neg if c <= t) / len(neg)
        if tpr - fpr > bj:
            bj, bt = tpr - fpr, t
    return bt, bj


# ===========================================================================
# 0. Pasport dannyh
# ===========================================================================

head("Z06 sec.0 -- PASPORT DANNYH")

say(f"zerno={SEED}  B_boot={B_BOOT}  B_bp={B_BP}  blok={BLOCK_MAIN}  h={H_MAIN}")
say(f"kovidnoe pravilo: {C.COVID_START} .. {C.COVID_END} (doslovno iz Z01)")
say(f"osnovnoe okno kompozita: {C.PRIMARY_START} ..;  obshchee okno masshtaba: {C.W_REF_START} ..")
say("")

RESP: dict[str, S.Series] = {}
for sid in ("IPMAN", "INDPRO", "GDPC1", "USREC", "CFNAI"):
    RESP[sid] = S.fred(sid)
    say(f"  {RESP[sid].describe()}")

IPMAN = to_map(RESP["IPMAN"])
INDPRO = to_map(RESP["INDPRO"])
GDPC1 = to_map(RESP["GDPC1"])
USREC = {d: int(v) for d, v in to_map(RESP["USREC"]).items()}
CFNAI = to_map(RESP["CFNAI"])

RESULT["data"] = {sid: {"n": len(s.observed), "first": s.first()[0], "last": s.last()[0],
                        "fetched_at": s.fetched_at, "source": s.source}
                  for sid, s in RESP.items()}

# ===========================================================================
# 1. Kompozit
# ===========================================================================

head("Z06 sec.1 -- KOMPOZIT: KONSTRUKCIYA I DIAGNOSTIKA SOSTAVA")

COMP: dict[tuple[str, str, bool], S.Series] = {}
PASS: dict[tuple[str, str, bool], C.Passport] = {}
for base in C.BASES:
    for meth in ("FE", "CHAIN", "BAL"):
        for dc in (True, False):
            # pin='off' zdes' ne poblazhka, a rol' etogo fayla: run.py --
            # PERESCHYOT zadachi, on pin i perezapisyvaet. Sverka s prezhney
            # versiey dannyh -- zabota potrebitelya ryada (Z05), a ne raschyota.
            s, pp = C.composite_with_passport(base, method=meth, drop_covid=dc,
                                              pin="off")
            COMP[(base, meth, dc)] = s
            PASS[(base, meth, dc)] = pp

main_s = COMP[(BASE_MAIN, METHOD_MAIN, True)]
main_pp = PASS[(BASE_MAIN, METHOD_MAIN, True)]
CMAIN = to_map(main_s)
SIGMA_C = main_pp.sigma_c

say(f"osnovnoy: {main_s.describe()}")
say(f"sigma_c = {SIGMA_C:.4f}  (edinica, v kotoroy privodyatsya vse porogi)")
say("")
say("Smeshcheniya paneley b_j (FE, normirovka sum=0) i ih rol':")
say(f"  {'panel':14s} {'kolonka':52s} {'n':>5s} {'b_j':>8s} {'mu_ref':>8s} {'sd_ref':>7s}")
for k, info in sorted(main_pp.panels.items()):
    say(f"  {k:14s} {str(info['column'])[:52]:52s} {info['n']:5d} "
        f"{info.get('fe_offset', float('nan')):+8.4f} {info['mu_ref']:+8.3f} {info['sd_ref']:7.3f}")

say("")
say("Smena sostava po mesyacam (lovushka nomer 1 iz zadaniya):")
prev_set: list[str] = []
comp_changes = []
for d in main_s.dates:
    cur = main_pp.membership[d]
    if cur != prev_set:
        comp_changes.append({"date": d, "panels": cur})
        say(f"  {d}: {len(cur)} paneley -> {', '.join(cur)}")
        prev_set = cur
RESULT["composition_changes"] = comp_changes

# Vneshniy kontrol' CFNAI
both = [d for d in main_s.dates if d in CFNAI and not C.is_covid(d)]
r_cfnai = corr([CMAIN[d] for d in both], [CFNAI[d] for d in both])
say("")
say(f"Vneshniy kontrol': corr(kompozit, CFNAI) = {r_cfnai:+.4f} na n={len(both)} "
    f"[{both[0]} .. {both[-1]}]  (v kalibrovku poroga ne vhodit)")
RESULT["cfnai_control"] = {"corr": r_cfnai, "n": len(both)}

# Soglasie konstrukciy mezhdu soboy
say("")
say("Soglasie tryoh konstrukciy na obshchih mesyacah (esli FE i CHAIN rashodyatsya --")
say("obrabotka sostava i est' istochnik raznicy):")
for meth in ("CHAIN", "BAL"):
    o = COMP[(BASE_MAIN, meth, True)]
    om = to_map(o)
    sh = [d for d in main_s.dates if d in om]
    say(f"  FE vs {meth:5s}: corr={corr([CMAIN[d] for d in sh], [om[d] for d in sh]):+.4f} "
        f"na n={len(sh)}, sr.|raznica|={mean([abs(CMAIN[d] - om[d]) for d in sh]):.4f}")

RESULT["composite"] = {
    "series_id": main_s.series_id, "n": len(main_s.dates),
    "first": main_s.dates[0], "last": main_s.dates[-1],
    "sigma_c": SIGMA_C, "w_ref": list(main_pp.w_ref),
    "panels": main_pp.panels,
}

# ===========================================================================
# 2. Osnovnaya specifikaciya: tochechnye ocenki
# ===========================================================================

head("Z06 sec.2 -- OSNOVNAYA SPECIFIKACIYA: TRI POROGA")

d_m, x_m, y_m = monthly_pairs(CMAIN, IPMAN, H_MAIN, drop_covid=True)
a_m, b_m, _ = ols(x_m, y_m)
tau_MFG = -a_m / b_m
say(f"tau_MFG (analog 50, otklik IPMAN, h={H_MAIN} mes. vperyod):")
say(f"  n={len(x_m)} [{d_m[0]} .. {d_m[-1]}]  alpha={a_m:+.4f}  beta={b_m:+.4f}"
    f"  R={corr(x_m, y_m):+.4f}")
say(f"  tau_MFG = {tau_MFG:+.4f}  = {tau_MFG / SIGMA_C:+.4f} sigma_c")

d_q, x_q, y_q = quarterly_pairs(CMAIN, GDPC1, H_MAIN, drop_covid=True)
a_q, b_q, _ = ols(x_q, y_q)
tau_GDP = -a_q / b_q
say("")
say(f"tau_GDP (analog 52.7 dlya New Orders, otklik GDPC1, tekushchiy kvartal):")
say(f"  n={len(x_q)} [{d_q[0]} .. {d_q[-1]}]  alpha={a_q:+.4f}  beta={b_q:+.4f}"
    f"  R={corr(x_q, y_q):+.4f}")
say(f"  tau_GDP = {tau_GDP:+.4f}  = {tau_GDP / SIGMA_C:+.4f} sigma_c")

d_r = [d for d in main_s.dates if d in USREC and not C.is_covid(d)]
x_r = [CMAIN[d] for d in d_r]
r_r = [USREC[d] for d in d_r]
tau_REC, j_rec = youden(x_r, r_r)
auc = auc_recession(x_r, r_r)
say("")
say(f"tau_REC (analog 43.5, Yuden protiv USREC):")
say(f"  n={len(x_r)} [{d_r[0]} .. {d_r[-1]}]  mesyacev recessii={sum(r_r)}"
    f"  AUC={auc:.4f}")
say(f"  tau_REC = {tau_REC:+.4f}  = {tau_REC / SIGMA_C:+.4f} sigma_c   J={j_rec:.4f}")

# Vtoraya, tozhe pred-registrirovannaya ocenka tau_REC
rec_q = [q for q in d_q if USREC.get(q, 0) == 1]
g_rec = [y for q, y in zip(d_q, y_q) if USREC.get(q, 0) == 1]
tau_REC_alt = float("nan")
if g_rec:
    med = sorted(g_rec)[len(g_rec) // 2]
    tau_REC_alt = (med - a_q) / b_q
    say(f"  vtoraya ocenka (uroven', dayushchiy medianu rosta VVP v kvartalah recessii "
        f"= {med:+.3f}%): tau = {tau_REC_alt:+.4f} = {tau_REC_alt / SIGMA_C:+.4f} sigma_c "
        f"(n_kv={len(g_rec)})")

say("")
say("Gde kazhdyy porog lezhit v sobstvennom raspredelenii kompozita --")
say("porog v dalyokom hvoste eto ekstrapolyaciya, a ne tochka razdeleniya:")
all_c = sorted(CMAIN[d] for d in main_s.dates if not C.is_covid(d))
tail_share = {}
for nm, tv in (("tau_MFG", tau_MFG), ("tau_GDP", tau_GDP), ("tau_REC", tau_REC)):
    below = sum(1 for v in all_c if v <= tv)
    tail_share[nm] = below / len(all_c)
    say(f"  {nm}: {tv:+.4f} = {tv / SIGMA_C:+.3f} sigma_c; nizhe nego "
        f"{below:3d} mesyacev iz {len(all_c)} ({below / len(all_c) * 100:.1f}%)")

RESULT["tail_share"] = tail_share
RESULT["primary"] = {
    "tau_MFG": {"value": tau_MFG, "sigma": tau_MFG / SIGMA_C, "alpha": a_m, "beta": b_m,
                "n": len(x_m), "R": corr(x_m, y_m), "first": d_m[0], "last": d_m[-1]},
    "tau_GDP": {"value": tau_GDP, "sigma": tau_GDP / SIGMA_C, "alpha": a_q, "beta": b_q,
                "n": len(x_q), "R": corr(x_q, y_q), "first": d_q[0], "last": d_q[-1]},
    "tau_REC": {"value": tau_REC, "sigma": tau_REC / SIGMA_C, "J": j_rec, "auc": auc,
                "n": len(x_r), "n_rec": sum(r_r), "alt": tau_REC_alt},
}

# ===========================================================================
# 3. Blochnyy bootstrap
# ===========================================================================

head("Z06 sec.3 -- BLOCHNYY BOOTSTRAP: INTERVALY I p")


def boot_reg(xs: list[float], ys: list[float], blk: int, seed: int
             ) -> dict[str, Any]:
    n = len(xs)
    if degenerate(n, blk):
        return {"status": "BOOTSTRAP_DEGENERATE", "n": n, "block": blk,
                "ratio": n / blk}
    taus, betas, diffs = [], [], []

    def one(idx: list[int]) -> float:
        bx = [xs[i] for i in idx]; by = [ys[i] for i in idx]
        a, b, _ = ols(bx, by)
        if not b or math.isnan(b):
            return float("nan")
        t = -a / b
        hi = [v for v, c in zip(by, bx) if c > t]
        lo = [v for v, c in zip(by, bx) if c <= t]
        taus.append(t); betas.append(b)
        # Razyorst' po storonam poroga mozhno tol'ko togda, kogda obe storony
        # nepusty. Rozygrysh, v kotorom tau ushyol za kray oblaka, storony ne
        # dayot -- i v spisok raznic ne popadaet. Poetomu diff_p schitaetsya po
        # USECHYONNOMU chislu povtoreniy, i otbrasyvayutsya sistematicheski
        # samye kraynie rozygryshi. Chislo ostavshihsya -- diff_n nizhe; ono
        # PECHATAETSYA ryadom s p, chtoby p ne chitalsya kak obychnyy
        # bootstrap-nyy po B povtoreniyam.
        if hi and lo:
            diffs.append(mean(hi) - mean(lo))
        return b

    boot(one, n, blk, reps=B_BOOT, seed=seed)
    return {
        "status": "ok", "n": n, "block": blk, "reps": len(taus),
        "tau_lo90": pct(taus, 0.05), "tau_hi90": pct(taus, 0.95),
        "tau_lo95": pct(taus, 0.025), "tau_hi95": pct(taus, 0.975),
        "tau_median": pct(taus, 0.5),
        "beta_p": two_sided_p(betas), "beta_lo90": pct(betas, 0.05),
        "beta_hi90": pct(betas, 0.95),
        "diff_p": two_sided_p(diffs), "diff_median": pct(diffs, 0.5),
        "diff_n": len(diffs),
    }


BOOT_M = {blk: boot_reg(x_m, y_m, blk, SEED + blk) for blk in BLOCKS}
BOOT_Q = {blk: boot_reg(x_q, y_q, blk_q(blk), SEED + 100 + blk) for blk in BLOCKS}

say("tau_MFG (IPMAN):")
for blk in BLOCKS:
    r = BOOT_M[blk]
    if r["status"] != "ok":
        say(f"  blok={blk:2d}: {r['status']} (n/L = {r['ratio']:.1f} < {DEGENERATE_RATIO})")
        continue
    say(f"  blok={blk:2d}: tau 90% [{r['tau_lo90']:+.4f} .. {r['tau_hi90']:+.4f}] "
        f"shirina={r['tau_hi90'] - r['tau_lo90']:.4f} ({(r['tau_hi90'] - r['tau_lo90']) / SIGMA_C:.3f} sigma_c)"
        f"  beta_p={r['beta_p']:.4f}  diff_p={r['diff_p']:.4f}"
        f" (po {r['diff_n']} rozygryshah iz {B_BOOT})")

say("")
say("tau_GDP (GDPC1). Dlina bloka pred-registrirovana v MESYACAH, ryad kvartal'nyy,")
say("poetomu 24 mes. = 8 kvartalov (sm. blk_q): 24 KVARTALA dali by n/L = "
    f"{len(x_q) / 24:.1f} i vyrozhdennyy bootstrap.")
for blk in BLOCKS:
    r = BOOT_Q[blk]
    if r["status"] != "ok":
        say(f"  blok={blk:2d} mes. ({blk_q(blk)} kv.): {r['status']} "
            f"(n/L = {r['ratio']:.1f} < {DEGENERATE_RATIO})")
        continue
    say(f"  blok={blk:2d} mes. ({blk_q(blk):2d} kv., n/L={r['n'] / r['block']:.1f}): "
        f"tau 90% [{r['tau_lo90']:+.4f} .. {r['tau_hi90']:+.4f}] "
        f"shirina={r['tau_hi90'] - r['tau_lo90']:.4f} ({(r['tau_hi90'] - r['tau_lo90']) / SIGMA_C:.3f} sigma_c)"
        f"  beta_p={r['beta_p']:.4f}  diff_p={r['diff_p']:.4f}"
        f" (po {r['diff_n']} rozygryshah iz {B_BOOT})")

# tau_REC bootstrap
def boot_rec(blk: int, seed: int) -> dict[str, Any]:
    n = len(x_r)
    if degenerate(n, blk):
        return {"status": "BOOTSTRAP_DEGENERATE", "n": n, "block": blk, "ratio": n / blk}
    taus, aucs = [], []

    def one(idx: list[int]) -> float:
        bx = [x_r[i] for i in idx]; br = [r_r[i] for i in idx]
        if not (0 < sum(br) < len(br)):
            return float("nan")
        t, _ = youden(bx, br)
        if math.isnan(t):
            return float("nan")
        taus.append(t)
        a = auc_recession(bx, br)
        if not math.isnan(a):
            aucs.append(a)
        return t

    boot(one, n, blk, reps=B_BOOT if not QUICK else 200, seed=seed)
    return {"status": "ok", "n": n, "block": blk, "reps": len(taus),
            "tau_lo90": pct(taus, 0.05), "tau_hi90": pct(taus, 0.95),
            "tau_median": pct(taus, 0.5),
            "auc_p": two_sided_p([a - 0.5 for a in aucs]),
            "auc_lo90": pct(aucs, 0.05), "auc_hi90": pct(aucs, 0.95)}


BOOT_R = {blk: boot_rec(blk, SEED + 200 + blk) for blk in BLOCKS}
say("")
say("tau_REC (Yuden protiv USREC):")
for blk in BLOCKS:
    r = BOOT_R[blk]
    if r["status"] != "ok":
        say(f"  blok={blk:2d}: {r['status']}")
        continue
    say(f"  blok={blk:2d}: tau 90% [{r['tau_lo90']:+.4f} .. {r['tau_hi90']:+.4f}] "
        f"shirina={r['tau_hi90'] - r['tau_lo90']:.4f} ({(r['tau_hi90'] - r['tau_lo90']) / SIGMA_C:.3f} sigma_c)"
        f"  AUC 90% [{r['auc_lo90']:.3f} .. {r['auc_hi90']:.3f}] p={r['auc_p']:.4f}")

RESULT["bootstrap"] = {"tau_MFG": BOOT_M, "tau_GDP": BOOT_Q, "tau_REC": BOOT_R}

CI = BOOT_Q[BLOCK_MAIN]
if CI["status"] != "ok":
    fallback = next((b for b in sorted(BLOCKS, reverse=True)
                     if BOOT_Q[b]["status"] == "ok"), None)
    if fallback is None:
        raise SystemExit("tau_GDP: bootstrap vyrozhden na vseh dlinah bloka -- "
                         "intervala net, zadacha ne schitaetsya")
    say("")
    say(f"VNIMANIE: osnovnaya dlina bloka dala vyrozhdennyy bootstrap; interval "
        f"vzyat pri bloke {fallback} mes. Eto zapisano v otchyot.")
    CI = BOOT_Q[fallback]
CI_LO, CI_HI = CI["tau_lo90"], CI["tau_hi90"]
say("")
say(f"Rabochiy interval tau_GDP (90%): [{CI_LO:+.4f} .. {CI_HI:+.4f}], "
    f"shirina {CI_HI - CI_LO:.4f} = {(CI_HI - CI_LO) / SIGMA_C:.3f} sigma_c")

# ===========================================================================
# 4. Kriterii C1 i C2, poprvka Holma
# ===========================================================================

head("Z06 sec.4 -- KRITERII C1 (identificiruemost') I C2 (razdelenie)")

praw = {
    "H1_beta_IPMAN": BOOT_M[BLOCK_MAIN]["beta_p"],
    "H2_beta_GDPC1": BOOT_Q[BLOCK_MAIN]["beta_p"],
    "H3_sep_IPMAN": BOOT_M[BLOCK_MAIN]["diff_p"],
    "H4_sep_GDPC1": BOOT_Q[BLOCK_MAIN]["diff_p"],
    "H5_auc_USREC": BOOT_R[BLOCK_MAIN]["auc_p"],
}
padj = holm(praw)
say(f"{'gipoteza':16s} {'p syroy':>10s} {'p Holm':>10s}  vyvod")
for k in ("H1_beta_IPMAN", "H2_beta_GDPC1", "H3_sep_IPMAN", "H4_sep_GDPC1", "H5_auc_USREC"):
    say(f"{k:16s} {praw[k]:10.4f} {padj[k]:10.4f}  "
        f"{'otvergaet nol' if padj[k] < 0.05 else 'NE otvergaet'}")

# p dlya H3/H4 -- ne obychnyy bootstrap-nyy po B povtoreniyam: rozygrysh, gde
# porog ushyol za kray oblaka, storon ne dayot i v spisok raznic ne popadaet.
# Chislo effektivnyh povtoreniy pechataetsya ryadom, chtoby usechenie bylo vidno.
say("")
say(f"H3/H4 schitany po USECHYONNOMU chislu povtoreniy (razyorst' po storonam "
    f"poroga mozhno")
say(f"tol'ko kogda obe storony nepusty; otbrasyvayutsya samye kraynie rozygryshi):")
say(f"  H3_sep_IPMAN: {BOOT_M[BLOCK_MAIN]['diff_n']} iz {B_BOOT} "
    f"({(1 - BOOT_M[BLOCK_MAIN]['diff_n'] / B_BOOT) * 100:.1f}% otbrosheno)")
say(f"  H4_sep_GDPC1: {BOOT_Q[BLOCK_MAIN]['diff_n']} iz {B_BOOT} "
    f"({(1 - BOOT_Q[BLOCK_MAIN]['diff_n'] / B_BOOT) * 100:.1f}% otbrosheno)")
RESULT["criteria_diff_n"] = {
    "B": B_BOOT,
    "H3_sep_IPMAN": BOOT_M[BLOCK_MAIN]["diff_n"],
    "H4_sep_GDPC1": BOOT_Q[BLOCK_MAIN]["diff_n"],
}

ci_width = CI_HI - CI_LO
c1 = (padj["H1_beta_IPMAN"] < 0.05 and padj["H2_beta_GDPC1"] < 0.05
      and ci_width < 1.0 * SIGMA_C)
c2 = padj["H3_sep_IPMAN"] < 0.05 and padj["H4_sep_GDPC1"] < 0.05
say("")
say(f"C1: beta znachimy v oboih regressiyah = "
    f"{padj['H1_beta_IPMAN'] < 0.05 and padj['H2_beta_GDPC1'] < 0.05}; "
    f"shirina 90% intervala tau_GDP = {ci_width:.4f} protiv 1.0*sigma_c = {SIGMA_C:.4f} "
    f"-> {'UZHE' if ci_width < SIGMA_C else 'SHIRE'}")
say(f"C1 = {'PROYDEN' if c1 else 'PROVALEN'}")
say(f"C2 = {'PROYDEN' if c2 else 'PROVALEN'}   "
    f"(raznica srednih: IPMAN {BOOT_M[BLOCK_MAIN]['diff_median']:+.3f} p.p., "
    f"GDPC1 {BOOT_Q[BLOCK_MAIN]['diff_median']:+.3f} p.p.)")

RESULT["criteria"] = {"p_raw": praw, "p_holm": padj, "C1": c1, "C2": c2,
                      "ci_width": ci_width, "sigma_c": SIGMA_C}

# ===========================================================================
# 5. Bai-Perron (C3)
# ===========================================================================

head("Z06 sec.5 -- BAI-PERRON: USTOYCHIVOST' SVYAZI VO VREMENI (C3)")


def bp_analysis(ds: list[str], xs: list[float], ys: list[float], blk: int,
                seed: int, label: str) -> dict[str, Any]:
    n = len(xs)
    hmin = max(4, int(math.ceil(TRIM * n)))
    seg = Seg(xs, ys)
    mmax = min(MAX_BREAKS, max(0, n // hmin - 1))
    parts, ssrs = bp_partition(seg, n, hmin, mmax)
    bics = [bp_bic(ssrs[k], n, k) for k in range(mmax + 1)]
    m_bic = min(range(mmax + 1), key=lambda k: bics[k])

    f0, at0 = sup_f(seg, 0, n - 1, hmin)
    a0, b0, _ = ols(xs, ys)
    resid = [y - a0 - b0 * x for x, y in zip(xs, ys)]
    rng = random.Random(seed)
    reps = B_BP if not QUICK else 300
    draws = []
    for _ in range(reps):
        idx = block_index(n, blk, rng)
        ystar = [a0 + b0 * xs[i] + resid[j] for i, j in enumerate(idx)]
        f, _ = sup_f(Seg(xs, ystar), 0, n - 1, hmin)
        draws.append(f)
    crit95 = pct(draws, 0.95)
    pval = sum(1 for d in draws if d >= f0) / len(draws)

    out: dict[str, Any] = {
        "label": label, "n": n, "hmin": hmin, "mmax": mmax,
        "supF_0v1": f0, "supF_at": ds[at0] if at0 >= 0 else None,
        "crit95_boot": crit95, "p_boot": pval,
        "bic": bics, "m_bic": m_bic,
        "breaks_bic": [ds[t] for t in parts[m_bic]] if m_bic else [],
    }

    # tau po rezhimam pri vybrannom chisle razryvov
    cuts = parts[m_bic] if m_bic else []
    bounds = [0] + [t + 1 for t in cuts] + [n]
    regimes = []
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1] - 1
        a, b, _ = seg.fit(lo, hi)
        t = -a / b if b else float("nan")
        regimes.append({"from": ds[lo], "to": ds[hi], "n": hi - lo + 1,
                        "alpha": a, "beta": b, "tau": t,
                        "R": corr(xs[lo:hi + 1], ys[lo:hi + 1])})
    out["regimes"] = regimes

    # posledovatel'nyy supF(2|1) pri odnom razryve
    if mmax >= 2 and parts[1]:
        t1 = parts[1][0]
        f_left, _ = sup_f(seg, 0, t1, hmin)
        f_right, _ = sup_f(seg, t1 + 1, n - 1, hmin)
        out["supF_1v2"] = max(f_left, f_right)
        out["break1"] = ds[t1]
    return out


BP_M = bp_analysis(d_m, x_m, y_m, BLOCK_MAIN, SEED + 300, "IPMAN")
BP_Q = bp_analysis(d_q, x_q, y_q, blk_q(BLOCK_MAIN), SEED + 400, "GDPC1")

for bp in (BP_M, BP_Q):
    say(f"[{bp['label']}] n={bp['n']} min.segment={bp['hmin']} max razryvov={bp['mmax']}")
    say(f"  supF(1|0) = {bp['supF_0v1']:.3f}  bootstrap-krit.95% = {bp['crit95_boot']:.3f}"
        f"  p = {bp['p_boot']:.4f}"
        f"  -> {'RAZRYV EST' if bp['p_boot'] < 0.05 else 'razryva net'}"
        + (f"  (kandidat {bp['supF_at']})" if bp["supF_at"] else ""))
    say(f"  BIC po chislu razryvov: " +
        "  ".join(f"m={k}:{v:.1f}" for k, v in enumerate(bp["bic"])))
    say(f"  BIC vybiraet m = {bp['m_bic']}"
        + (f", razryvy: {', '.join(bp['breaks_bic'])}" if bp["breaks_bic"] else ""))
    if "supF_1v2" in bp:
        say(f"  supF(2|1) = {bp['supF_1v2']:.3f} (pri razryve {bp['break1']})")
    for rg in bp["regimes"]:
        say(f"    rezhim {rg['from']} .. {rg['to']} (n={rg['n']:3d}): "
            f"alpha={rg['alpha']:+.4f} beta={rg['beta']:+.4f} R={rg['R']:+.3f} "
            f"tau={rg['tau']:+.4f} = {rg['tau'] / SIGMA_C:+.3f} sigma_c")
    say("")

# C3: net razryva libo tau kazhdogo rezhima vnutri 90% intervala polnoy vyborki
def c3_ok(bp: dict[str, Any]) -> bool:
    if bp["p_boot"] >= 0.05 and bp["m_bic"] == 0:
        return True
    return all(CI_LO <= rg["tau"] <= CI_HI for rg in bp["regimes"])


c3 = c3_ok(BP_Q)
say(f"Interval polnoy vyborki dlya tau_GDP: [{CI_LO:+.4f} .. {CI_HI:+.4f}]")
say(f"C3 = {'PROYDEN' if c3 else 'PROVALEN'} (schitaetsya po GDPC1, k kotoromu otnositsya tau_GDP)")
say(f"    spravochno po IPMAN: C3 = {'PROYDEN' if c3_ok(BP_M) else 'PROVALEN'}")

RESULT["bai_perron"] = {"IPMAN": BP_M, "GDPC1": BP_Q, "C3": c3,
                        "C3_ipman": c3_ok(BP_M)}

# ===========================================================================
# 6. Vne vyborki (C4)
# ===========================================================================

head("Z06 sec.6 -- PROVERKA VNE VYBORKI (C4)")


def oos(ds: list[str], xs: list[float], ys: list[float], label: str) -> dict[str, Any]:
    n = len(xs)
    cut = int(n * 0.8)
    a, b, _ = ols(xs[:cut], ys[:cut])
    t_tr = -a / b if b else float("nan")
    hits = 0
    total = 0
    for x, y in zip(xs[cut:], ys[cut:]):
        if y == 0:
            continue
        pred = 1 if x > t_tr else -1
        act = 1 if y > 0 else -1
        hits += int(pred == act)
        total += 1
    rate = hits / total if total else float("nan")
    a_te, b_te, _ = ols(xs[cut:], ys[cut:])
    t_te = -a_te / b_te if b_te else float("nan")
    return {"label": label, "n_train": cut, "n_test": n - cut,
            "train_from": ds[0], "train_to": ds[cut - 1],
            "test_from": ds[cut], "test_to": ds[-1],
            "tau_train": t_tr, "tau_test": t_te,
            "hit_rate": rate, "hits": hits, "total": total}


OOS_M = oos(d_m, x_m, y_m, "IPMAN")
OOS_Q = oos(d_q, x_q, y_q, "GDPC1")
for o in (OOS_M, OOS_Q):
    say(f"[{o['label']}] obuchenie {o['train_from']}..{o['train_to']} (n={o['n_train']}), "
        f"hvost {o['test_from']}..{o['test_to']} (n={o['n_test']})")
    say(f"  tau_obuchenie = {o['tau_train']:+.4f}   tau_hvost = {o['tau_test']:+.4f}")
    say(f"  dolya vernyh znakov na hvoste = {o['hit_rate'] * 100:.1f}% "
        f"({o['hits']}/{o['total']})")

c4 = (OOS_Q["hit_rate"] > 0.5 and CI_LO <= OOS_Q["tau_train"] <= CI_HI)
say("")
say(f"C4 = {'PROYDEN' if c4 else 'PROVALEN'}: dolya znakov {OOS_Q['hit_rate'] * 100:.1f}% > 50% "
    f"-> {OOS_Q['hit_rate'] > 0.5}; tau obucheniya v intervale -> "
    f"{CI_LO <= OOS_Q['tau_train'] <= CI_HI}")
RESULT["oos"] = {"IPMAN": OOS_M, "GDPC1": OOS_Q, "C4": c4}

# ===========================================================================
# 7. Setka ustoychivosti (C5)
# ===========================================================================

head("Z06 sec.7 -- SETKA USTOYCHIVOSTI: 486 YACHEEK (C5)")

SPLITS = {
    "full": (None, None),
    "1993-2007": (None, "2007-12-01"),
    "2008-2026": ("2008-01-01", None),
}

grid: list[dict[str, Any]] = []
for base in C.BASES:
    for meth in ("FE", "CHAIN", "BAL"):
        for dc in (True, False):
            cm = to_map(COMP[(base, meth, dc)])
            for h in HORIZONS:
                for sname, (s0, s1) in SPLITS.items():
                    dq, xq, yq = quarterly_pairs(cm, GDPC1, h, drop_covid=dc,
                                                 start=s0, end=s1)
                    t = tau_of(xq, yq) if len(xq) >= 3 else float("nan")
                    for blk in BLOCKS:
                        grid.append({
                            "base": base, "method": meth, "drop_covid": dc,
                            "h": h, "split": sname, "block": blk,
                            "n": len(xq), "tau": t,
                            "short": len(xq) < MIN_N_CELL,
                        })

usable = [g for g in grid if not g["short"] and math.isfinite(g["tau"])]
short = [g for g in grid if g["short"] or not math.isfinite(g["tau"])]
inside = [g for g in usable if CI_LO <= g["tau"] <= CI_HI]
frac_usable = len(inside) / len(usable) if usable else float("nan")
frac_all = len(inside) / len(grid)

say(f"yacheek vsego: {len(grid)}  (3 bazy x 3 konstrukcii x 3 gorizonta x 2 kovid "
    f"x 3 razbieniya x 3 dliny bloka)")
say(f"iz nih strukturno neschitaemyh (n < {MIN_N_CELL}): {len(short)}")
say(f"schitaemyh: {len(usable)};  vnutri 90% intervala osnovnoy ocenki: {len(inside)}")
say(f"C5 dolya (znamenatel' -- schitaemye): {frac_usable * 100:.1f}%")
say(f"C5 dolya (znamenatel' -- vse 486, neschitaemye kak promah): {frac_all * 100:.1f}%")
say("")
say("Vnimanie na chestnost' schyota: dlina bloka na TOCHECHNUYU ocenku tau ne")
say("vliyaet vovse -- ona dvigaet interval. Poetomu 486 yacheek soderzhat")
say(f"{len(grid) // 3} razlichnyh tochechnyh ocenok, kazhdaya povtorena trizhdy.")
say("Dolya ot etogo ne menyaetsya, no nazyvat' 486 'nezavisimymi' bylo by lozh'yu.")

tvals = [g["tau"] for g in usable]
say("")
say(f"Razbros tau po setke: median={pct(tvals, 0.5):+.4f}  "
    f"[p05={pct(tvals, 0.05):+.4f} .. p95={pct(tvals, 0.95):+.4f}]  "
    f"min={min(tvals):+.4f} max={max(tvals):+.4f}")

say("")
say("Po osyam (mediana tau vnutri gruppy, dolya vnutri intervala):")
for axis in ("base", "method", "h", "split", "drop_covid"):
    vals = sorted({str(g[axis]) for g in usable})
    for v in vals:
        sub = [g for g in usable if str(g[axis]) == v]
        ins = sum(1 for g in sub if CI_LO <= g["tau"] <= CI_HI)
        say(f"  {axis:11s}={v:10s} n={len(sub):3d} median tau={pct([g['tau'] for g in sub], 0.5):+.4f} "
            f"vnutri={ins / len(sub) * 100:5.1f}%")

# C5 po pred-registrirovannomu pravilu, HYPOTHESIS.md sec.10 Utochnenie 3:
# "esli by oni razoshlis' po storonam poroga 70 %, verdikt vynosilsya by po
# strogomu". Do 2026-08-01 v kode stoyal tol'ko myagkiy znamenatel', i vetki
# "brat' strogiy" ne bylo vovse -- pravilo, napisannoe DO raschyota, ne
# ispolnyalos'. Progon 2026-07-28 popal rovno v tot sluchay, dlya kotorogo ono
# i pisalos': 77.78 % >= 70 % protiv 69.14 % < 70 %.
c5_usable = frac_usable >= 0.70
c5_all = frac_all >= 0.70
split_sides = c5_usable != c5_all
c5 = c5_all if split_sides else c5_usable
say("")
say(f"C5 myagkiy schyot  (znamenatel' -- schitaemye): {frac_usable * 100:.2f}% -> "
    f"{'PROYDEN' if c5_usable else 'PROVALEN'}")
say(f"C5 strogiy schyot  (znamenatel' -- vse {len(grid)}): {frac_all * 100:.2f}% -> "
    f"{'PROYDEN' if c5_all else 'PROVALEN'}")
if split_sides:
    say("dva schyota razoshlis' po storonam poroga 70% -> po pred-registrirovannomu")
    say("pravilu (HYPOTHESIS sec.10 Utochnenie 3) verdikt vynositsya PO STROGOMU")
say(f"C5 = {'PROYDEN' if c5 else 'PROVALEN'} (porog 70%)")
RESULT["grid"] = {"n_cells": len(grid), "n_short": len(short), "n_usable": len(usable),
                  "n_inside": len(inside), "frac_usable": frac_usable,
                  "frac_all": frac_all, "C5": c5,
                  "C5_usable": c5_usable, "C5_all": c5_all,
                  "C5_rule": ("strogiy schyot (schyoty razoshlis' po storonam 70%)"
                              if split_sides else "myagkiy schyot (schyoty soglasny)"),
                  "tau_median": pct(tvals, 0.5), "tau_p05": pct(tvals, 0.05),
                  "tau_p95": pct(tvals, 0.95), "cells": grid}

# ===========================================================================
# 8. Lestnica L (C6)
# ===========================================================================

head("Z06 sec.8 -- LESTNICA L: CHETYRE STUPENI ILI DVE (C6)")

ci_rec = BOOT_R[BLOCK_MAIN]
ci_mfg = BOOT_M[BLOCK_MAIN]
ord_ok = tau_REC < tau_GDP < tau_MFG
gap1 = ci_rec.get("tau_hi90", float("nan")) < CI_LO       # REC nizhe GDP
gap2 = CI_HI < ci_mfg.get("tau_lo90", float("nan"))       # GDP nizhe MFG
c6 = bool(ord_ok and gap1 and gap2)

say(f"tochechnye: tau_REC={tau_REC:+.4f} < tau_GDP={tau_GDP:+.4f} < tau_MFG={tau_MFG:+.4f}"
    f"  -> poryadok {'soblyudyon' if ord_ok else 'NARUSHEN'}")
say(f"90% intervaly:")
say(f"  tau_REC [{ci_rec.get('tau_lo90', float('nan')):+.4f} .. {ci_rec.get('tau_hi90', float('nan')):+.4f}]")
say(f"  tau_GDP [{CI_LO:+.4f} .. {CI_HI:+.4f}]")
say(f"  tau_MFG [{ci_mfg.get('tau_lo90', float('nan')):+.4f} .. {ci_mfg.get('tau_hi90', float('nan')):+.4f}]")
say(f"  REC/GDP ne peresekayutsya: {gap1};  GDP/MFG ne peresekayutsya: {gap2}")
say(f"C6 = {'PROYDEN -> chetyre stupeni' if c6 else 'PROVALEN -> dve stupeni'}")

if c6:
    steps = [(tau_MFG, None, 1.0), (tau_GDP, tau_MFG, -0.4),
             (tau_REC, tau_GDP, -0.8), (None, tau_REC, -1.0)]
    ladder_kind = "four"
else:
    steps = [(tau_GDP, None, 1.0), (None, tau_GDP, -1.0)]
    ladder_kind = "two"

LADDER = {
    "version": "Z06-v1",
    "kind": ladder_kind,
    "base": BASE_MAIN,
    "method": METHOD_MAIN,
    "units": "urovni kompozita (sd paneley); v skobkah -- v sigma_c",
    "sigma_c": SIGMA_C,
    "steps": [[lo, hi, L] for lo, hi, L in steps],
    "tau": {"tau_MFG": tau_MFG, "tau_GDP": tau_GDP, "tau_REC": tau_REC},
    "tau_sigma": {"tau_MFG": tau_MFG / SIGMA_C, "tau_GDP": tau_GDP / SIGMA_C,
                  "tau_REC": tau_REC / SIGMA_C},
    "ci90": {"tau_MFG": [ci_mfg.get("tau_lo90"), ci_mfg.get("tau_hi90")],
             "tau_GDP": [CI_LO, CI_HI],
             "tau_REC": [ci_rec.get("tau_lo90"), ci_rec.get("tau_hi90")]},
}
say("")
say("Lestnica, kotoraya uhodit v Z05:")
for lo, hi, L in steps:
    lo_s = f"{lo:+.4f}" if lo is not None else "  -inf"
    hi_s = f"{hi:+.4f}" if hi is not None else "  +inf"
    say(f"  {lo_s} < c <= {hi_s}   L = {L:+.1f}")

RESULT["ladder"] = LADDER

# Raspredelenie mesyacev po stupenyam.
#
# Ranshe zdes' stoyalo C.LADDER_V1.update(LADDER) -- t.e. progon molcha
# zapisyval v modul'nuyu konstantu PRED-REGISTRIROVANNUYU lestnicu po tau_GDP,
# tu samuyu, kotoruyu neskol'kimi desyatkami strok nizhe sam zhe i brakuet.
# Ubrano: lestnicu vezde peredayom yavnym argumentom, a v C.LADDER_V1 lezhit
# POSTAVLYAEMAYA, i trogat' eyo iz raschyota nel'zya.
counts: dict[float, int] = {}
for d in main_s.dates:
    # allow_rejected=True yavno: eto raspredelenie mesyacev po stupenyam
    # PRED-REGISTRIROVANNOY lestnicy, kotoruyu etot zhe progon neskol'kimi
    # desyatkami strok nizhe i brakuet. Chislo nuzhno otchyotu (i ono zhe idyot
    # v rejected_why), no prosit' ego nado gromko. Segodnya pometka rejected
    # stavitsya POZZHE etoy stroki, tak chto flag -- na sluchay perestanovki
    # porjadka, a ne dekoraciya.
    L = C.level_step(CMAIN[d], LADDER, allow_rejected=True)
    counts[L] = counts.get(L, 0) + 1
say("")
say(f"Raspredelenie {len(main_s.dates)} mesyacev po stupenyam:")
for L in sorted(counts, reverse=True):
    say(f"  L={L:+.1f}: {counts[L]:3d} mes. ({counts[L] / len(main_s.dates) * 100:.1f}%)")
RESULT["ladder"]["month_counts"] = {str(k): v for k, v in counts.items()}

# --- Prakticheskaya lestnica: [RESHENIE POSLE RASCHYOTA] --------------------
# Pred-registrirovannyy zapasnoy variant rezhet po tau_GDP. Esli imenno tau_GDP
# okazalsya neidentificiruem (shirina intervala bol'she 1.0 sigma_c), stavit'
# stupen' po nemu znachit postavit' v Z05 to, chto sam zhe progon i zabrakoval.
# Poetomu ryadom stroitsya lestnica TOL'KO na teh porogah, kotorye planku
# identificiruemosti proshli. Eto reshenie prinyato POSLE raschyota, verdikta
# ono ne kasaetsya i pomecheno kak takovoe.

def ident(name: str, ci: dict[str, Any]) -> tuple[bool, float]:
    if ci.get("status") != "ok":
        return False, float("nan")
    w = ci["tau_hi90"] - ci["tau_lo90"]
    return w < 1.0 * SIGMA_C, w


ident_tbl = {
    "tau_REC": (tau_REC,) + ident("tau_REC", ci_rec),
    "tau_MFG": (tau_MFG,) + ident("tau_MFG", ci_mfg),
    "tau_GDP": (tau_GDP,) + ident("tau_GDP", CI if isinstance(CI, dict) else {}),
}
say("")
say("Planka identificiruemosti (shirina 90% intervala < 1.0 sigma_c = "
    f"{SIGMA_C:.4f}):")
for k, (val, ok, w) in ident_tbl.items():
    say(f"  {k}: tau={val:+.4f} shirina={w:.4f} ({w / SIGMA_C:.2f} sigma_c) -> "
        f"{'identificiruem' if ok else 'NE identificiruem'}")

keep = sorted((v for v, ok, _ in ident_tbl.values() if ok))
if keep:
    k = len(keep)
    lvls = [1.0 - 2.0 * i / k for i in range(k + 1)]     # ot +1 do -1 ravnomerno
    prac_steps: list[tuple[float | None, float | None, float]] = []
    bounds = [None] + keep + [None]
    for i in range(k + 1):
        lo = bounds[k - i] if k - i > 0 else None
        hi = bounds[k - i + 1] if k - i + 1 <= k else None
        prac_steps.append((lo, hi, lvls[i]))
    prac = {"version": "Z06-v1-practical", "kind": f"{k + 1}-step",
            "post_hoc": True, "base": BASE_MAIN, "method": METHOD_MAIN,
            "sigma_c": SIGMA_C,
            "steps": [[lo, hi, L] for lo, hi, L in prac_steps],
            "thresholds": keep}
    say("")
    say("[RESHENIE POSLE RASCHYOTA] Prakticheskaya lestnica na identificiruemyh porogah:")
    for lo, hi, L in prac_steps:
        lo_s = f"{lo:+.4f}" if lo is not None else "  -inf"
        hi_s = f"{hi:+.4f}" if hi is not None else "  +inf"
        say(f"  {lo_s} < c <= {hi_s}   L = {L:+.2f}")
    pc: dict[float, int] = {}
    for d in main_s.dates:
        L = C.level_step(CMAIN[d], prac)
        pc[L] = pc.get(L, 0) + 1
    for L in sorted(pc, reverse=True):
        say(f"    L={L:+.2f}: {pc[L]:3d} mes. ({pc[L] / len(main_s.dates) * 100:.1f}%)")
    prac["month_counts"] = {str(a): b for a, b in pc.items()}
    RESULT["ladder_practical"] = prac
else:
    say("")
    say("[RESHENIE POSLE RASCHYOTA] Ni odin porog planku ne proshyol -- "
        "prakticheskoy lestnicy net vovse.")
    RESULT["ladder_practical"] = None

# --- Kakaya lestnica UHODIT V POSTAVKU -------------------------------------
# Odno mesto, gde eto reshaetsya, i ono zhe idyot v composite.csv i v pasport.
# Do 2026-08-01 v artefakty popadala LADDER (po tau_GDP) -- ta, kotoruyu progon
# zabrakoval; rashozhdenie s postavlyaemoy sostavlyalo 110 mesyacev iz 390.
LADDER_SHIP = RESULT["ladder_practical"] or LADDER
LADDER_REJECTED = LADDER if RESULT["ladder_practical"] else None
say("")
say(f"V POSTAVKU uhodit lestnica {LADDER_SHIP['version']} "
    f"({LADDER_SHIP['kind']}).")
if LADDER_REJECTED:
    say(f"Zabrakovannaya {LADDER_REJECTED['version']} (po tau_GDP) sohranyaetsya "
        f"otdel'nym klyuchom 'ladder_prereg_rejected_tau_GDP' -- radi "
        f"vosproizvodimosti, a ne radi primeneniya.")

    # Pometka braka -- V SAMIH DANNYH, a ne v dogovoryonnosti.
    #
    # Do 2026-08-02 pometka stoyala tol'ko v composite.py (konstanta
    # LADDER_PREREG_REJECTED_TAU_GDP) i v pasporte, a v result.json -> 'ladder'
    # eyo ne bylo VOVSE. Klyuch s samym ochevidnym imenem nyos zabrakovannuyu
    # lestnicu bez edinogo priznaka braka: vyzov
    # ladder_contribution(s, result['ladder']) otrabatyval molcha i otdaval
    # vklad po porogu tau_GDP. Sleduyushchaya zadacha (Z05) beryot lestnicu
    # imenno iz artefaktov Z06 -- znachit pometka obyazana lezhat' v artefakte.
    #
    # Prichina sobiraetsya iz chisel ETOGO progona, a ne kopiruetsya tekstom:
    # inache posle pereschyota na svezhih dannyh v fayle ostalis' by chuzhie
    # shirina i raspredelenie.
    _w_gdp = ident_tbl["tau_GDP"][2]
    _n_all = sum(counts.values())
    _hi = counts.get(1.0, 0)
    _lo = counts.get(-1.0, 0)
    RESULT["ladder"]["rejected"] = True
    RESULT["ladder"]["rejected_why"] = (
        f"tau_GDP ne identificiruem: shirina 90% intervala "
        f"{_w_gdp / SIGMA_C:.2f} sigma_c protiv trebuemyh <1.0; stupen' po "
        f"nemu delit istoriyu {_hi} / {_lo} "
        f"({_hi / _n_all * 100:.1f}% / {_lo / _n_all * 100:.1f}%)")
    # Sverka s konstantoy: pometka obyazana byt' odna i ta zhe v tryoh mestah
    # (composite.py, composite-passport.json, result.json). Rashozhdenie tut --
    # eto opyat' dva istochnika pravdy, s kotoryh vsyo i nachalos'.
    _const_why = C.LADDER_PREREG_REJECTED_TAU_GDP["rejected_why"]
    if RESULT["ladder"]["rejected_why"] != _const_why:
        say("")
        say("!!! VNIMANIE: prichina brakovki, poschitannaya progonom, razoshlas' s")
        say(f"!!! composite.LADDER_PREREG_REJECTED_TAU_GDP:")
        say(f"!!!   progon:    {RESULT['ladder']['rejected_why']}")
        say(f"!!!   konstanta: {_const_why}")
        say("!!! Normal'no posle pereschyota na svezhih dannyh, no konstantu v")
        say("!!! composite.py nado obnovit' RUKAMI.")
    say(f"V result.json klyuch 'ladder' pomechen rejected=true; "
        f"postavlyaemaya -- klyuch 'ladder_practical'.")
    say(f"  rejected_why: {RESULT['ladder']['rejected_why']}")
    say(f"  s etogo momenta level_step / ladder_contribution na ney PADAYUT "
        f"(composite.RejectedLadder), poka ne poprosit' allow_rejected=True.")

# Sverka s konstantoy v composite.py: chisla lestnicy zhivut v DVUH mestah
# (modul' i artefakty), i rashodit'sya im nel'zya molcha.
if list(LADDER_SHIP.get("thresholds", [])) != list(C.LADDER_V1["thresholds"]):
    say("")
    say("!!! VNIMANIE: porogi postavlyaemoy lestnicy razoshlis' s konstantoy")
    say(f"!!! composite.LADDER_V1: progon {LADDER_SHIP.get('thresholds')} protiv "
        f"{C.LADDER_V1['thresholds']}.")
    say("!!! Eto normal'no posle pereschyota na svezhih dannyh, no LADDER_V1 v")
    say("!!! composite.py nado obnovit' RUKAMI -- inache Z05 voz'myot staryy porog.")
RESULT["identifiability"] = {k: {"tau": v[0], "identified": v[1], "ci_width": v[2]}
                             for k, v in ident_tbl.items()}

# ===========================================================================
# 9. Vintazhi
# ===========================================================================

head("Z06 sec.9 -- VINTAZHI ALFRED")


def fred_vintage_dates(series_id: str) -> list[str]:
    """Spisok vintazhey ryada. Otvechaet na vopros 'pochemu 404', ne gadaya.

    Vnimanie na limit: FRED prinimaet limit ot 1 do 10000. limit=100000 dayot
    HTTP 400 s telom 'Variable limit is not between 1 and 10000' -- to est'
    otkaz po parametru zaprosa, a NE otsutstvie arhiva. Raznicu vidno tol'ko
    po telu otveta.
    """
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
        msg = str(exc)[:90].encode("ascii", "replace").decode("ascii")
        say(f"  [FAIL] {series_id}@{vintage}: {type(exc).__name__} {msg}")
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


VINTAGES = [f"{y}-06-03" for y in range(2007, 2027)]
V_PANELS = {"philly": "NOCDFSA066MSFRBPHI",
            "empire": "NOCDISA066MSFRBNY",
            "dallas": "GROSAMFRBDAL"}

say("Glubina vintazhnogo arhiva -- proverena otdel'nym endpoint'om FRED,")
say("chtoby ne prinyat' 404 na ranniy vintazh za polomku dostupa:")
say(f"  {'ryad':22s} {'vintazhey':>10s} {'pervyy':>12s} {'posledniy':>12s}")
vdepth: dict[str, Any] = {}
for sid in list(V_PANELS.values()) + ["IPMAN", "GDPC1"]:
    vd = fred_vintage_dates(sid)
    vdepth[sid] = {"n": len(vd), "first": vd[0] if vd else None,
                   "last": vd[-1] if vd else None}
    if vd:
        say(f"  {sid:22s} {len(vd):10d} {vd[0]:>12s} {vd[-1]:>12s}")
RESULT["vintage_depth"] = vdepth
first_panel_vintage = max((v["first"] for v in vdepth.values()
                           if v["first"] and v is not vdepth["GDPC1"]
                           and v is not vdepth["IPMAN"]), default=None)
say("")
say(f"Sledstvie: trekhpanel'nyy kompozit v real'nom vremeni nachinaetsya ne ranee")
say(f"{first_panel_vintage} -- u regional'nyh obzorov na FRED prosto NET arhiva glubzhe.")
say("404 na bolee ranniy vintazh -- eto granica arhiva, a ne otkaz dostupa;")
say("provereno vtorym, nezavisimym endpoint'om (series/vintagedates).")
say("")

say("A. Otklik peresmatrivaetsya, kompozit tot zhe (izoliruet REVIZIYU otklika).")
say(f"   {'vintazh':11s} {'n_kv':>5s} {'tau vintazh':>12s} {'tau peresm.':>12s} "
    f"{'raznica':>9s}  v intervale?")
vint_a = []
for v in VINTAGES:
    g_v = alfred("GDPC1", v)
    if not g_v:
        continue
    last = max(g_v)
    dq, xq, yq = quarterly_pairs(CMAIN, g_v, H_MAIN, drop_covid=True, end=last)
    if len(xq) < MIN_N_CELL:
        say(f"   {v:11s} n_kv={len(xq):3d} -- korotko, propuskaem")
        continue
    t_v = tau_of(xq, yq)
    dq2, xq2, yq2 = quarterly_pairs(CMAIN, GDPC1, H_MAIN, drop_covid=True, end=last)
    t_r = tau_of(xq2, yq2)
    ok = CI_LO <= t_v <= CI_HI
    say(f"   {v:11s} {len(xq):5d} {t_v:+12.4f} {t_r:+12.4f} {t_v - t_r:+9.4f}  {ok}")
    vint_a.append({"vintage": v, "n": len(xq), "tau_vintage": t_v,
                   "tau_revised": t_r, "diff": t_v - t_r, "inside": ok})

say("")
say("B. Trekhpanel'nyy kompozit v real'nom vremeni (Philly + Empire + Dallas)")
say("   -- edinstvennye tri paneli iz pyati, u kotoryh voobshche est' vintazhi.")
say(f"   {'vintazh':11s} {'n_kv':>5s} {'tau 3-panel RT':>15s} {'tau 3-panel peresm.':>20s}  v intervale?")


def composite_3p(vintage: str | None) -> dict[str, float] | None:
    """FE-kompozit iz tryoh paneley; vintage=None -> tekushchie dannye."""
    z: dict[str, dict[str, float]] = {}
    for key, sid in V_PANELS.items():
        raw = alfred(sid, vintage) if vintage else to_map(
            C.panel_series(key, "new_orders"))
        if not raw:
            return None
        z[key] = raw
    end = min(max(v) for v in z.values())
    w_ref = [d for d in month_span(C.W_REF_START, end) if not C.is_covid(d)]
    zs: dict[str, dict[str, float]] = {}
    for k, ser in z.items():
        ref = [ser[d] for d in w_ref if d in ser]
        if len(ref) < 24:
            return None
        mu, s = mean(ref), sd(ref)
        zs[k] = {d: (v - mu) / s for d, v in ser.items()}
    start = "2001-07-01"                       # pervyy mesyac s dvumya panelyami
    live = [d for d in month_span(start, max(max(v) for v in zs.values()))
            if any(d in zs[k] for k in zs)]
    fit = [d for d in live if not C.is_covid(d)]
    c, _ = C._fit_fe(zs, live, fit)
    anchor = mean([c[d] for d in w_ref if d in c]) if any(d in c for d in w_ref) else 0.0
    return {d: v - anchor for d, v in c.items()}


c3p_now = composite_3p(None)
vint_b = []
if c3p_now:
    for v in VINTAGES:
        c3p = composite_3p(v)
        g_v = alfred("GDPC1", v)
        if not c3p or not g_v:
            continue
        last = min(max(g_v), max(c3p))
        dq, xq, yq = quarterly_pairs(c3p, g_v, H_MAIN, drop_covid=True, end=last)
        if len(xq) < MIN_N_CELL:
            say(f"   {v:11s} n_kv={len(xq):3d} -- korotko, propuskaem")
            continue
        t_rt = tau_of(xq, yq)
        dq2, xq2, yq2 = quarterly_pairs(c3p_now, GDPC1, H_MAIN, drop_covid=True, end=last)
        t_rv = tau_of(xq2, yq2)
        ok = CI_LO <= t_rt <= CI_HI
        say(f"   {v:11s} {len(xq):5d} {t_rt:+15.4f} {t_rv:+20.4f}  {ok}")
        vint_b.append({"vintage": v, "n": len(xq), "tau_realtime": t_rt,
                       "tau_revised3p": t_rv, "inside": ok})
else:
    say("   [ne postroen] -- ne vse tri paneli otdalis' vintazhami")

n_in_a = sum(1 for r in vint_a if r["inside"])
n_in_b = sum(1 for r in vint_b if r["inside"])
say("")
say(f"Itog A: {n_in_a} iz {len(vint_a)} vintazhey v 90% intervale polnoy vyborki")
say(f"Itog B: {n_in_b} iz {len(vint_b)} vintazhey v 90% intervale polnoy vyborki")
say("Chego net: u Richmond i Kansas City vintazhey ne sushchestvuet -- ih net")
say("na FRED vovse. Pyatipanel'nyy kompozit v real'nom vremeni nevosproizvodim.")
RESULT["vintages"] = {"A_response_only": vint_a, "B_realtime_3panel": vint_b,
                      "A_inside": n_in_a, "B_inside": n_in_b,
                      "note": "Richmond i Kansas City vintazhey ne imeyut"}

# ===========================================================================
# 10. Dlinnoe plecho i dopolnitel'nye stroki
# ===========================================================================

head("Z06 sec.10 -- DLINNOE PLECHO 1968 I STROKI VNE SETKI")

long_s, long_pp = C.composite_with_passport(BASE_MAIN, method="FE",
                                            drop_covid=True, start="1968-05-01",
                                            pin="off")
long_c = to_map(long_s)
dql, xql, yql = quarterly_pairs(long_c, GDPC1, H_MAIN, drop_covid=True)
tau_long = tau_of(xql, yql)
say(f"Dlinnoe plecho {long_s.dates[0]} .. {long_s.dates[-1]} (do 1993-11 -- odna Filadelfiya):")
say(f"  n_kv={len(xql)}  tau_GDP={tau_long:+.4f} = {tau_long / long_pp.sigma_c:+.4f} sigma "
    f"(sigma_c etogo ryada = {long_pp.sigma_c:.4f})")
say(f"  v 90% intervale osnovnoy ocenki: {CI_LO <= tau_long <= CI_HI}")

# Sovremennoe okno dlya IPMAN (vne setki, dlya sravneniya s vperyod-smotryashchim)
d_b, x_b, y_b = [], [], []
for t in sorted(CMAIN):
    u = add_months(t, -H_MAIN)
    if t in IPMAN and u in IPMAN and not covid_window(u, H_MAIN):
        d_b.append(t); x_b.append(CMAIN[t])
        y_b.append(1200.0 / H_MAIN * (math.log(IPMAN[t]) - math.log(IPMAN[u])))
tau_back = tau_of(x_b, y_b)
say("")
say(f"Vne setki: to zhe dlya IPMAN, no okno NAZAD [t-3, t] (sovremennoe chtenie, kak u ISM):")
say(f"  n={len(x_b)}  tau_MFG(nazad)={tau_back:+.4f} protiv tau_MFG(vperyod)={tau_MFG:+.4f}"
    f"  R={corr(x_b, y_b):+.4f} protiv {corr(x_m, y_m):+.4f}")

# INDPRO kak alternativnyy otklik
d_i, x_i, y_i = monthly_pairs(CMAIN, INDPRO, H_MAIN, drop_covid=True)
say(f"Vne setki: otklik INDPRO vmesto IPMAN: n={len(x_i)} tau={tau_of(x_i, y_i):+.4f} "
    f"R={corr(x_i, y_i):+.4f}")

RESULT["extra"] = {
    "long_arm": {"first": long_s.dates[0], "last": long_s.dates[-1], "n_q": len(xql),
                 "tau": tau_long, "sigma_c": long_pp.sigma_c,
                 "inside": CI_LO <= tau_long <= CI_HI},
    "ipman_backward": {"n": len(x_b), "tau": tau_back, "R": corr(x_b, y_b)},
    "indpro": {"n": len(x_i), "tau": tau_of(x_i, y_i), "R": corr(x_i, y_i)},
}

# ===========================================================================
# 11. Verdikt
# ===========================================================================

head("Z06 sec.11 -- VERDIKT")

crit = {"C1": c1, "C2": c2, "C3": c3, "C4": c4, "C5": c5}
for k, v in crit.items():
    say(f"  {k} = {'PROYDEN' if v else 'PROVALEN'}")
say(f"  C6 = {'PROYDEN' if c6 else 'PROVALEN'} (reshaet tol'ko chislo stupeney)")

if all(crit.values()):
    verdict = "PODTVERZHDENO"
elif (not c1) or (not c3) or (frac_usable < 0.50):
    verdict = "OPROVERGNUTO"
else:
    verdict = "NEOPREDELENO"

say("")
say(f"VERDIKT: {verdict}")
say("")
say("Vazhno: verdikt otnositsya k pereformulirovannomu utverzhdeniyu (HYPOTHESIS sec.1.2) --")
say("u kompozita est' identificiruemaya i ustoychivaya liniya nulevogo rosta.")
say("Chisla kursa 48.7 / 49.9 / 52.7 / 43.5 ostayutsya NEPROVERENNYMI: ryada ISM net.")

RESULT["verdict"] = verdict
RESULT["criteria"].update(crit)
RESULT["criteria"]["C6"] = c6

# ===========================================================================
# 12. Vygruzka ryada i pasporta
# ===========================================================================

head("Z06 sec.12 -- VYGRUZKA")

csv_path = os.path.join(_HERE, "composite.csv")
with open(csv_path, "w", encoding="utf-8", newline="") as fh:
    fh.write("date,composite,sigma_units,n_panels,panels,L_step\n")
    for d in main_s.dates:
        v = CMAIN[d]
        mem = main_pp.membership[d]
        fh.write(f"{d},{v:.6f},{v / SIGMA_C:.6f},{len(mem)},"
                 f"\"{'|'.join(mem)}\",{C.level_step(v, LADDER_SHIP):+.1f}\n")
say(f"ryad kompozita: {csv_path} ({len(main_s.dates)} strok, "
    f"L_step po {LADDER_SHIP['version']})")

pp_path = os.path.join(_HERE, "composite-passport.json")
passport = main_pp.to_dict()
passport["ladder"] = LADDER_SHIP
if LADDER_REJECTED:
    passport["ladder_prereg_rejected_tau_GDP"] = LADDER_REJECTED
passport["built_by"] = "Z06/composite.py composite(base='new_orders', method='FE')"
passport["responses"] = RESULT["data"]

# Pin: privyazka ryada k versii dannyh. Bez nego sleduyushchiy progon cherez
# mesyac otdal by DRUGOY ryad molcha -- chto i sluchilos' mezhdu 07-28 i 08-01
# (Richmond peresmotrel istoriyu, W_ref sdvinulos', uehali vse 393 znacheniya).
_dates = list(main_s.dates)
_values = [CMAIN[d] for d in _dates]   # digest sam privedyot k VALUE_FORMAT
passport["pin"] = {
    "version": "Z06-pin-v1",
    "frozen_at": time.strftime("%Y-%m-%d"),
    "note": f"progon run.py, zerno {SEED}",
    "config": dict(C.PINNED_CONFIG),
    "w_ref": {"start": main_pp.w_ref[0], "end": main_pp.w_ref[1]},
    "panels": {k: {"last": v["last"], "n": v["n"], "n_ref": v["n_ref"],
                   "mu_ref": v["mu_ref"], "sd_ref": v["sd_ref"]}
               for k, v in sorted(main_pp.panels.items())},
    "series": {"file": "composite.csv", "first": _dates[0], "last": _dates[-1],
               "n": len(_dates), "sigma_c": SIGMA_C,
               "fetched_at": main_pp.fetched_at,
               "value_format": C.VALUE_FORMAT,
               "sha256": C.series_digest(_dates, _values)},
    "ladder_version": LADDER_SHIP["version"],
    "ladder_thresholds": list(LADDER_SHIP.get("thresholds", [])),
    "policy": ("composite(pin='check') sveryaet zhivuyu sborku s etim blokom i "
               "pri rashozhdenii otkazyvaet, nazyvaya izmenivsheesya; "
               "pin='frozen' otdayot ryad iz fayla bez seti; pin='off' -- "
               "zhivuyu sborku bez sverki."),
}
with open(pp_path, "w", encoding="utf-8") as fh:
    json.dump(passport, fh, ensure_ascii=True, indent=2)
say(f"pasport: {pp_path}")
say(f"  pin {passport['pin']['version']} ot {passport['pin']['frozen_at']}: "
    f"W_ref [{main_pp.w_ref[0]} .. {main_pp.w_ref[1]}], sha256 ryada "
    f"{passport['pin']['series']['sha256'][:16]}...")

RESULT["elapsed_sec"] = round(time.time() - T0, 1)
res_path = os.path.join(_HERE, "result.json")
with open(res_path, "w", encoding="utf-8") as fh:
    json.dump(RESULT, fh, ensure_ascii=True, indent=2, default=str)
say(f"rezultat: {res_path}")
say("")
say(f"gotovo za {RESULT['elapsed_sec']} s")
