#!/usr/bin/env python3
"""Z02 — устойчив ли порядок двенадцати звеньев H-O-P-E (правило R77).

Критерии зафиксированы до расчёта: см. HYPOTHESIS.md. Скрипт ничего не решает
сам — он считает те величины, которые названы в критериях, и печатает их.

Два независимых способа оценки порядка:
  A — датировка пиков внутри окна эпизода, ранговая корреляция с книжным
      порядком по каждому циклу;
  B — матрица попарных лидов на сбалансированной панели, без внешнего
      опорного ряда и без окон.

Запуск:
    python run.py                 # из кэша, если он свежий
    python run.py --force         # перекачать исходные ряды
    python run.py --boot 1000     # больше повторов блочного бутстрапа

Результат: result.json + full-run.txt + order.svg рядом со скриптом.
Зависимости: только стандартная библиотека + sources.py из родительской папки.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
from operator import mul

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import sources as S  # noqa: E402

SEED = 20260727
MAXLAG = 24          # окно карты Piper Sandler: -24 ... +24
BLOCK = 36           # длина блока бутстрапа, мес.
PERM_REPS = 50_000   # перестановочный тест
PLATEAU_REPS = 20_000
EPISODE_REPS = 20_000
BAND = 0.6           # порог ранговой корреляции из FULL-BOOK-PLAN.md §7.2

# --------------------------------------------------------------------------- #
#  Двенадцать звеньев: HYPOTHESIS.md §2.1
# --------------------------------------------------------------------------- #
#  kind: qty — количественный ряд (100*ln(x_t/x_{t-k}))
#        idx — диффузный индекс / индекс настроения (MA_k уровня)
#  step: шаг календаря ряда в месяцах (3 = квартальный)

LINKS = [
    {"n": 1,  "name": "NAHB",            "sid": "NAHB-HMI", "kind": "idx", "step": 1},
    {"n": 2,  "name": "Permits",         "sid": "PERMIT",   "kind": "qty", "step": 1},
    {"n": 3,  "name": "ISM New Orders*", "sid": "NOC",      "kind": "idx", "step": 1},
    {"n": 4,  "name": "Confidence*",     "sid": "UMCSENT",  "kind": "idx", "step": 1},
    {"n": 5,  "name": "Cons.New Orders", "sid": "ACOGNO",   "kind": "qty", "step": 1},
    {"n": 6,  "name": "Mfg Sales",       "sid": "AMTMVS",   "kind": "qty", "step": 1},
    {"n": 7,  "name": "Cap Goods",       "sid": "NEWORDER", "kind": "qty", "step": 1},
    {"n": 8,  "name": "Ind.Production",  "sid": "INDPRO",   "kind": "qty", "step": 1},
    {"n": 9,  "name": "AWH",             "sid": "AWHMAN",   "kind": "qty", "step": 1},
    {"n": 10, "name": "Payrolls",        "sid": "PAYEMS",   "kind": "qty", "step": 1},
    {"n": 11, "name": "Personal Income", "sid": "PI",       "kind": "qty", "step": 1},
    {"n": 12, "name": "Core CPI",        "sid": "CPILFESL", "kind": "qty", "step": 1},
]

# Строки устойчивости — подмены рядов внутри звена (HYPOTHESIS.md §6 п.6)
SWAPS = {
    "link6_long":   {6:  {"sid": "CMRMTSPL", "kind": "qty", "step": 1}},
    "awh_as_index": {9:  {"sid": "AWHMAN",   "kind": "idx", "step": 1}},
    "pi_real":      {11: {"sid": "W875RX1",  "kind": "qty", "step": 1}},
    "orders_alt":   {5:  {"sid": "DGORDER",  "kind": "qty", "step": 1},
                     7:  {"sid": "AMTMNO",   "kind": "qty", "step": 1}},
    # «как нарисовано в курсе»: все количественные звенья датируются по уровню.
    # Фазово это НЕсогласовано (см. HYPOTHESIS.md §2.2) и приводится только
    # затем, чтобы проверить, не создан ли ранний разворот Payrolls самим
    # переходом к приращениям. Core CPI остаётся приращением: уровень цен
    # не разворачивается.
    "levels_asdrawn": {n: {"kind": "idx"} for n in range(1, 12)},
    "deflated":     {5:  {"sid": "ACOGNO/CPI",   "kind": "qty", "step": 1},
                     6:  {"sid": "AMTMVS/CPI",   "kind": "qty", "step": 1},
                     7:  {"sid": "NEWORDER/CPI", "kind": "qty", "step": 1},
                     11: {"sid": "PI/CPI",       "kind": "qty", "step": 1}},
}

# Панели способа B (HYPOTHESIS.md §3.2)
PANELS = {
    "B1": {"links": list(range(1, 13)), "swap": None,
           "title": "полная дюжина (12 звеньев)", "role": "подтверждающая"},
    "B2": {"links": [2, 3, 6, 8, 9, 10, 11, 12], "swap": "link6_long",
           "title": "длинная восьмёрка (звено 6 = CMRMTSPL)", "role": "подтверждающая"},
    "B3": {"links": [1, 2, 3, 4, 6, 8, 9, 10, 11, 12], "swap": "link6_long",
           "title": "десятка с 1985 (звено 6 = CMRMTSPL)", "role": "устойчивость"},
}

# Пятизвенная цепочка — блок D (HYPOTHESIS.md §4.1)
BLOCKS5 = [
    ("H", "Housing",    ["NAHB-HMI", "PERMIT"]),
    ("O", "Orders",     ["NOC", "ACOGNO", "NEWORDER"]),
    ("P", "Profits",    ["CP"]),
    ("E", "Employment", ["AWHMAN", "PAYEMS"]),
    ("I", "Inflation",  ["CPILFESL"]),
]

# Эпизоды с доминирующим шоком предложения — внешние события (HYPOTHESIS.md §3.3)
SUPPLY_SHOCKS = [("1974", "1973-10"), ("1979", "1979-01"), ("2021", "2021-01")]

COVID = ("2020-03", "2021-12")


# --------------------------------------------------------------------------- #
#  Месячная сетка: индекс = год*12 + (месяц-1)
# --------------------------------------------------------------------------- #

def mi(date: str) -> int:
    return int(date[:4]) * 12 + (int(date[5:7]) - 1)


def mi_str(idx: int) -> str:
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def to_monthly(series: S.Series) -> dict[int, float]:
    """Месячный ряд -> {индекс месяца: значение}. Дневной/недельный усредняется."""
    if series.freq in ("D", "W"):
        acc: dict[int, list[float]] = {}
        for d, v in series.observed:
            acc.setdefault(mi(d), []).append(v)
        return {k: sum(vs) / len(vs) for k, vs in acc.items()}
    return {mi(d): v for d, v in series.observed}


# --------------------------------------------------------------------------- #
#  Преобразования (HYPOTHESIS.md §2.2)
# --------------------------------------------------------------------------- #

def log_change(x: dict[int, float], k: int, step: int = 1, sign: int = 1) -> dict[int, float]:
    """100*ln(x_t / x_{t-k}) — приращение за k месяцев."""
    return {t: sign * 100.0 * math.log(v / x[t - k])
            for t, v in x.items() if t - k in x and v > 0 and x[t - k] > 0}


def ma_level(x: dict[int, float], k: int, step: int = 1, sign: int = 1) -> dict[int, float]:
    """Скользящее среднее уровня за k месяцев — фазовый аналог Δk у количественных."""
    out: dict[int, float] = {}
    m = max(1, k // step)
    for t in x:
        window = [x.get(t - i * step) for i in range(m)]
        if any(v is None for v in window):
            continue
        out[t] = sign * sum(window) / len(window)  # type: ignore[arg-type]
    return out


def transform(x: dict[int, float], kind: str, k: int, step: int, sign: int = 1) -> dict[int, float]:
    if kind == "idx":
        return ma_level(x, k, step, sign)
    return log_change(x, k, step, sign)


def smooth3(x: dict[int, float], step: int = 1) -> dict[int, float]:
    """Центрированное трёхмесячное среднее. Для квартальных рядов не применяется."""
    if step != 1:
        return dict(x)
    return {t: (x[t - 1] + x[t] + x[t + 1]) / 3.0
            for t in x if t - 1 in x and t + 1 in x}


# --------------------------------------------------------------------------- #
#  Ранги, Спирмен, перестановочный тест
# --------------------------------------------------------------------------- #

def ranks(values: list[float]) -> list[float]:
    """Средние ранги (совпадения делят ранг)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for q in range(i, j + 1):
            out[order[q]] = avg
        i = j + 1
    return out


def _centered_unit(v: list[float]) -> list[float] | None:
    n = len(v)
    m = sum(v) / n
    c = [u - m for u in v]
    nrm = math.sqrt(sum(u * u for u in c))
    if nrm <= 0:
        return None
    return [u / nrm for u in c]


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    za, zb = _centered_unit(ranks(a)), _centered_unit(ranks(b))
    if za is None or zb is None:
        return None
    return sum(map(mul, za, zb))


def perm_pvalue(est: list[float], post: list[float], rng: random.Random,
                reps: int = PERM_REPS) -> float:
    """p для 'порядок не случаен': перестановки книжного порядка, односторонний."""
    za = _centered_unit(ranks(est))
    zb = _centered_unit(ranks(post))
    if za is None or zb is None:
        return 1.0
    obs = sum(map(mul, za, zb))
    pool = list(zb)
    hits = 0
    for _ in range(reps):
        rng.shuffle(pool)
        if sum(map(mul, za, pool)) >= obs - 1e-12:
            hits += 1
    return (hits + 1) / (reps + 1)


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = round(running, 5)
    return out


# --------------------------------------------------------------------------- #
#  Способ A: датировка пиков внутри окна эпизода
# --------------------------------------------------------------------------- #

def date_peak(y: dict[int, float], lo: int, hi: int, step: int,
              method: str = "drawdown") -> dict | None:
    """Дата разворота звена внутри окна эпизода.

    ``argmax``   — оценка из пред-регистрации: максимум внутри окна.
    ``drawdown`` — исправленная оценка: начало наибольшего спада, то есть пара
                   ``p < q``, максимизирующая ``y_p − y_q``; датой считается
                   ``p``. Причина замены и диагностика — HYPOTHESIS.md §8.

    Возвращает обе даты сразу, чтобы обе версии считались одним прогоном.
    """
    pts = [(t, y[t]) for t in range(lo, hi + 1) if t in y]
    if len(pts) < max(6, (hi - lo) // (2 * step)):
        return None
    vals = [v for _, v in pts]
    sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0

    amax_t, amax_v = max(pts, key=lambda p: p[1])
    amin_t, _amin_v = min(pts, key=lambda p: p[1])

    # наибольший спад: пара p<q с максимальным y_p - y_q
    run_t, run_v = pts[0]
    dd, dd_p, dd_q = -1.0, pts[0][0], pts[0][0]
    for t, v in pts[1:]:
        if run_v - v > dd:
            dd, dd_p, dd_q = run_v - v, run_t, t
        if v > run_v:
            run_t, run_v = t, v

    if method == "argmax":
        best_t, best_v, right = amax_t, amax_v, hi
    else:
        best_t, best_v, right = dd_p, y[dd_p], dd_q

    thr = best_v - 0.5 * sd
    plateau = [t for t, v in pts if v >= thr and t <= right]
    if not plateau:
        plateau = [best_t]
    return {
        "peak": best_t, "peak_str": mi_str(best_t), "value": round(best_v, 4),
        "plateau": plateau,
        "plateau_span": [mi_str(min(plateau)), mi_str(max(plateau))],
        "plateau_width": len(plateau) * step,
        "at_edge": best_t <= lo + step or best_t >= hi - step,
        "n_obs": len(pts),
        # диагностика пред-регистрированной оценки, не зависящая от гипотезы:
        "argmax": mi_str(amax_t), "argmin": mi_str(amin_t),
        "argmax_after_min": amax_t > amin_t,
        "drawdown_start": mi_str(dd_p), "drawdown_end": mi_str(dd_q),
        "drawdown_sd": round(dd / sd, 2) if sd > 0 else None,
    }


def covers(x: dict[int, float], lo: int, hi: int, step: int) -> bool:
    """Сплошное покрытие окна с шагом ряда — иначе звено выбывает из эпизода."""
    if not x:
        return False
    mod = min(x) % step
    need = [t for t in range(lo, hi + 1) if t % step == mod]
    return bool(need) and all(t in x for t in need)


def episode_order(prepared: dict[str, dict[int, float]], links: list[dict],
                  anchor: int, half: int, rng: random.Random,
                  *, do_perm: bool = True, method: str = "drawdown") -> dict:
    """Ранжирование звеньев одного эпизода и его ранговая корреляция с книгой."""
    lo, hi = anchor - half, anchor + half
    rows, dropped = [], []
    for lk in links:
        x = prepared.get(lk["sid"])
        if x is None or not covers(x, lo, hi, lk["step"]):
            dropped.append(lk["n"])
            continue
        pk = date_peak(x, lo, hi, lk["step"], method)
        if pk is None:
            dropped.append(lk["n"])
            continue
        rows.append({**pk, "link": lk["n"], "name": lk["name"], "sid": lk["sid"]})
    res = {"anchor": mi_str(anchor), "window": [mi_str(lo), mi_str(hi)],
           "n": len(rows), "dropped": dropped, "links": rows}
    if len(rows) < 4:
        res["rho"] = None
        return res

    post = [float(r["link"]) for r in rows]
    est = [float(r["peak"]) for r in rows]
    rho = spearman(est, post)
    res["rho"] = None if rho is None else round(rho, 4)
    res["est_order"] = [r["name"] for r in sorted(rows, key=lambda r: r["peak"])]
    res["est_rank"] = {r["name"]: rk for r, rk in zip(rows, ranks(est))}
    res["edge_hits"] = sum(1 for r in rows if r["at_edge"])
    res["median_plateau"] = statistics.median(r["plateau_width"] for r in rows)

    if do_perm:
        res["p_perm"] = round(perm_pvalue(est, post, rng), 5)
        # неопределённость даты: пик берётся равномерно из плато
        draws = []
        plats = [r["plateau"] for r in rows]
        zb = _centered_unit(ranks(post))
        for _ in range(PLATEAU_REPS):
            e = [float(rng.choice(p)) for p in plats]
            za = _centered_unit(ranks(e))
            draws.append(0.0 if za is None else sum(map(mul, za, zb)))
        draws.sort()
        res["rho_plateau"] = {
            "p05": round(draws[int(0.05 * (len(draws) - 1))], 4),
            "p50": round(draws[len(draws) // 2], 4),
            "p95": round(draws[int(0.95 * (len(draws) - 1))], 4),
            "share_above_band": round(sum(1 for d in draws if d > BAND) / len(draws), 3),
        }
    # сам список месяцев плато в результат не пишем: он нужен только внутри
    # (границы и ширина уже сохранены), а в JSON раздувает файл в разы
    for r in rows:
        r.pop("plateau", None)
    return res


# --------------------------------------------------------------------------- #
#  Способ B: матрица попарных лидов на сбалансированной панели
# --------------------------------------------------------------------------- #

def balanced_ts(prepared: dict[str, dict[int, float]], sids: list[str],
                maxlag: int, exclude: tuple[int, int] | None) -> list[int]:
    """t, у которых есть все ряды на всех лагах [-maxlag, +maxlag]."""
    if not sids:
        return []
    lo = max(min(prepared[s]) for s in sids) + maxlag
    hi = min(max(prepared[s]) for s in sids) - maxlag
    out = []
    for t in range(lo, hi + 1):
        ok = True
        for h in range(-maxlag, maxlag + 1):
            u = t + h
            if exclude and exclude[0] <= u <= exclude[1]:
                ok = False
                break
            if any(u not in prepared[s] for s in sids):
                ok = False
                break
        if ok:
            out.append(t)
    return out


def lead_matrix(cols: list[list[list[float] | None]], maxlag: int) -> dict:
    """cols[i][h+maxlag] — нормированный столбец ряда i на лаге h.

    Возвращает матрицу лидов L[i][j] (>0 — i раньше j) и пиковые корреляции.
    """
    m = len(cols)
    L = [[0] * m for _ in range(m)]
    R = [[0.0] * m for _ in range(m)]
    for i in range(m):
        zi = cols[i][maxlag]
        if zi is None:
            continue
        for j in range(i + 1, m):
            best_h, best_r = 0, -2.0
            for h in range(-maxlag, maxlag + 1):
                zj = cols[j][h + maxlag]
                if zj is None:
                    continue
                r = sum(map(mul, zi, zj))
                if r > best_r:
                    best_h, best_r = h, r
            L[i][j], L[j][i] = best_h, -best_h
            R[i][j] = R[j][i] = best_r
    return {"L": L, "R": R}


def scores_from_L(L: list[list[int]]) -> list[float]:
    m = len(L)
    return [sum(L[i][j] for j in range(m) if j != i) / (m - 1) for i in range(m)]


def transitivity(L: list[list[int]]) -> dict:
    m = len(L)
    total = viol = 0
    for i in range(m):
        for j in range(m):
            if i == j or L[i][j] <= 0:
                continue
            for k in range(m):
                if k in (i, j) or L[j][k] <= 0:
                    continue
                total += 1
                if L[i][k] < 0:
                    viol += 1
    return {"triples": total, "violations": viol,
            "rate": round(viol / total, 4) if total else None}


def build_cols(prepared: dict[str, dict[int, float]], sids: list[str],
               ts: list[int], maxlag: int) -> list[list[list[float] | None]]:
    cols: list[list[list[float] | None]] = []
    for s in sids:
        x = prepared[s]
        row: list[list[float] | None] = []
        for h in range(-maxlag, maxlag + 1):
            row.append(_centered_unit([x[t + h] for t in ts]))
        cols.append(row)
    return cols


def panel_result(prepared: dict[str, dict[int, float]], links: list[dict],
                 rng: random.Random, *, maxlag: int, boot: int,
                 exclude: tuple[int, int] | None = None,
                 do_boot: bool = True) -> dict:
    sids = [lk["sid"] for lk in links]
    ts = balanced_ts(prepared, sids, maxlag, exclude)
    if len(ts) < 60:
        return {"n": len(ts), "error": "панель меньше 60 точек"}
    cols = build_cols(prepared, sids, ts, maxlag)
    lm = lead_matrix(cols, maxlag)
    sc = scores_from_L(lm["L"])
    post = [float(lk["n"]) for lk in links]
    # раньше -> выше балл; книжный порядок: раньше -> меньше номер
    rho = spearman([-v for v in sc], post)
    order = [links[i]["name"] for i in sorted(range(len(links)), key=lambda i: -sc[i])]
    m = len(links)
    edge = sum(1 for i in range(m) for j in range(i + 1, m)
               if abs(lm["L"][i][j]) == maxlag)
    near0 = sum(1 for i in range(m) for j in range(i + 1, m)
                if abs(lm["L"][i][j]) <= 1)
    sc_med = [statistics.median([lm["L"][i][j] for j in range(m) if j != i])
              for i in range(m)]
    rho_med = spearman([-v for v in sc_med], post)
    res = {
        "n": len(ts), "span": [mi_str(ts[0] - maxlag), mi_str(ts[-1] + maxlag)],
        "t_span": [mi_str(ts[0]), mi_str(ts[-1])],
        "links": [lk["name"] for lk in links],
        "sids": sids,
        "scores": [round(v, 2) for v in sc],
        "scores_median": [round(v, 2) for v in sc_med],
        "est_order": order,
        "rho": None if rho is None else round(rho, 4),
        "rho_median_score": None if rho_med is None else round(rho_med, 4),
        "transitivity": transitivity(lm["L"]),
        "edge_pairs": edge, "near_zero_pairs": near0, "pairs": m * (m - 1) // 2,
        "L": lm["L"],
        "peak_r": [[round(v, 3) for v in row] for row in lm["R"]],
        "p_perm": round(perm_pvalue([-v for v in sc], post, rng), 5),
    }
    if do_boot:
        n = len(ts)
        vals = []
        for _ in range(boot):
            idx = moving_blocks(n, BLOCK, rng)
            bts = [ts[i] for i in idx]
            bcols = build_cols(prepared, sids, bts, maxlag)
            bl = lead_matrix(bcols, maxlag)
            bsc = scores_from_L(bl["L"])
            r = spearman([-v for v in bsc], post)
            if r is not None:
                vals.append(r)
        vals.sort()
        if vals:
            res["bootstrap"] = {
                "reps": len(vals), "block": BLOCK,
                "p05": round(vals[int(0.05 * (len(vals) - 1))], 4),
                "p50": round(vals[len(vals) // 2], 4),
                "p95": round(vals[int(0.95 * (len(vals) - 1))], 4),
                "share_above_band": round(sum(1 for v in vals if v > BAND) / len(vals), 3),
                "share_above_zero": round(sum(1 for v in vals if v > 0) / len(vals), 3),
            }
    return res


def moving_blocks(n: int, block: int, rng: random.Random) -> list[int]:
    idx: list[int] = []
    last = max(1, n - block + 1)
    while len(idx) < n:
        start = rng.randrange(last)
        idx.extend(range(start, min(start + block, n)))
    return idx[:n]


# --------------------------------------------------------------------------- #
#  Вывод одновременно на экран и в full-run.txt
# --------------------------------------------------------------------------- #

class Tee:
    def __init__(self, path: str):
        self.fh = open(path, "w", encoding="utf-8")

    def write(self, s: str) -> None:
        sys.__stdout__.write(s)
        self.fh.write(s)

    def flush(self) -> None:
        sys.__stdout__.flush()
        self.fh.flush()


def fmt(v, w=6, prec=3) -> str:
    return " " * (w - 1) + "-" if v is None else f"{v:+{w}.{prec}f}"


# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--boot", type=int, default=400)
    ap.add_argument("--quick", action="store_true",
                    help="черновой прогон: мало повторов, результат не публиковать")
    args = ap.parse_args()
    if args.quick:
        global PERM_REPS, PLATEAU_REPS, EPISODE_REPS
        PERM_REPS, PLATEAU_REPS, EPISODE_REPS = 300, 200, 300
        args.boot = min(args.boot, 5)

    try:
        sys.__stdout__.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    sys.stdout = Tee(os.path.join(HERE, "full-run.txt"))  # type: ignore[assignment]

    rng = random.Random(SEED)
    out: dict = {"task": "Z02", "params": {
        "seed": SEED, "maxlag": MAXLAG, "block": BLOCK, "boot_reps": args.boot,
        "perm_reps": PERM_REPS, "plateau_reps": PLATEAU_REPS, "band": BAND}}

    # ---------------------------------------------------------------- данные
    print("Загрузка рядов...")
    raw: dict[str, S.Series] = {}
    raw["NAHB-HMI"] = S.nahb_hmi("t2", force=args.force)["HMI"]
    raw["NOC"] = S.philfed_mbos(force=args.force)["NOC"]
    for sid in ("PERMIT", "UMCSENT", "ACOGNO", "AMTMVS", "NEWORDER", "INDPRO",
                "AWHMAN", "PAYEMS", "PI", "CPILFESL", "CMRMTSPL", "W875RX1",
                "DGORDER", "AMTMNO", "AWHAETP", "ICSA", "CP", "CPIAUCSL",
                "USREC", "FEDFUNDS"):
        raw[sid] = S.fred(sid, force=args.force)

    monthly = {sid: to_monthly(s) for sid, s in raw.items()}

    manifest = {}
    for sid, s in raw.items():
        d = monthly[sid]
        step = 3 if s.freq == "Q" else 1
        holes = [mi_str(t) for t in range(min(d), max(d) + 1, step) if t not in d]
        manifest[sid] = {
            "source": s.source, "freq": s.freq, "n": len(d),
            "first": mi_str(min(d)), "last": mi_str(max(d)),
            "obs_start_meta": (s.meta or {}).get("observation_start", ""),
            "title": s.title[:90], "holes": holes,
            "url": (s.meta or {}).get("url", "") if s.source != "FRED" else "",
        }
        print(f"   {sid:<10} {s.freq:<2} {mi_str(min(d))}..{mi_str(max(d))} "
              f"n={len(d):<5} дыр={len(holes)}"
              + (f"  {', '.join(holes[:3])}" if holes else ""))
    out["manifest"] = manifest
    out["fetched_at"] = raw["PERMIT"].fetched_at

    for sid, info in manifest.items():
        if info["holes"]:
            print(f"   ВНИМАНИЕ: в {sid} пропущено {len(info['holes'])} мес. "
                  f"({', '.join(info['holes'][:5])}"
                  f"{'...' if len(info['holes']) > 5 else ''}). Сбалансированная "
                  f"панель требует все лаги, поэтому дыра срезает {MAXLAG} мес. "
                  f"вокруг себя, а эпизод с дырой в окне теряет звено целиком.")

    # дефлированные варианты
    cpi = monthly["CPIAUCSL"]
    for src, dst in (("ACOGNO", "ACOGNO/CPI"), ("AMTMVS", "AMTMVS/CPI"),
                     ("NEWORDER", "NEWORDER/CPI"), ("PI", "PI/CPI")):
        monthly[dst] = {t: v / cpi[t] for t, v in monthly[src].items() if t in cpi}

    # ------------------------------------------------------- якоря эпизодов
    usrec = monthly["USREC"]
    peaks = []
    ts_all = sorted(usrec)
    for a, b in zip(ts_all, ts_all[1:]):
        if usrec[a] == 0 and usrec[b] == 1:
            peaks.append(a)
    peaks_1970 = [p for p in peaks if p >= mi("1970-01")]
    print(f"\nПики NBER после 1970 (выведены из USREC, не из памяти): "
          f"{', '.join(mi_str(p) for p in peaks_1970)}")

    primary = [p for p in peaks_1970 if p < mi("2020-01")]
    covid_peak = [p for p in peaks_1970 if p >= mi("2020-01")]
    print(f"Основной набор ({len(primary)}): "
          f"{', '.join(mi_str(p) for p in primary)}")
    print(f"Отдельно, ковид: {', '.join(mi_str(p) for p in covid_peak)}")
    out["episodes"] = {"nber_peaks_post1970": [mi_str(p) for p in peaks_1970],
                       "primary": [mi_str(p) for p in primary],
                       "covid": [mi_str(p) for p in covid_peak]}

    ff = monthly["FEDFUNDS"]
    tight: list[int] = []
    for t in sorted(ff):
        if t + 12 not in ff:
            continue
        if ff[t + 12] - ff[t] < 1.5:
            continue
        win = [ff[u] for u in range(t - 6, t + 4) if u in ff]
        if len(win) < 8 or ff[t] > min(win):
            continue
        if tight and t - tight[-1] < 24:
            continue
        tight.append(t)
    tight_1970 = [t for t in tight if t >= mi("1970-01")]
    print(f"\nНачала циклов ужесточения ФРС по объявленному правилу "
          f"(f[t+12]-f[t]>=1.5 п.п., локальный минимум, шаг >=24 мес.):")
    print("   " + ", ".join(f"{mi_str(t)} ({ff[t]:.2f}->{ff[t + 12]:.2f}%)"
                            for t in tight_1970))
    out["episodes"]["fed_tightening_starts"] = [mi_str(t) for t in tight_1970]

    # --------------------------------------------------- подготовка рядов
    def prepare(k: int, swap: str | None = None,
                extra: dict[str, tuple[str, int]] | None = None
                ) -> tuple[dict[str, dict[int, float]], list[dict]]:
        links = []
        for lk in LINKS:
            spec = dict(lk)
            if swap and lk["n"] in SWAPS[swap]:
                spec.update(SWAPS[swap][lk["n"]])
            links.append(spec)
        prep: dict[str, dict[int, float]] = {}
        for spec in links:
            prep[spec["sid"]] = smooth3(
                transform(monthly[spec["sid"]], spec["kind"], k, spec["step"]),
                spec["step"])
        for sid, (kind, sign) in (extra or {}).items():
            step = 3 if raw.get(sid) is not None and raw[sid].freq == "Q" else 1
            prep[sid] = smooth3(
                transform(monthly[sid], kind, k, step, sign), step)
        return prep, links

    EXTRA = {"ICSA": ("qty", -1), "CP": ("qty", 1), "AWHAETP": ("qty", 1)}

    # =================================================================== A
    print(f"\n{'=' * 100}")
    print("СПОСОБ A. Датировка пиков внутри окна эпизода (+-24 мес. от якоря)")
    print(f"{'=' * 100}")

    METHODS = [("drawdown", "исправленная: начало наибольшего спада в окне"),
               ("argmax", "пред-регистрированная: максимум в окне")]
    PRIMARY_METHOD = "drawdown"

    a_res: dict = {"by_method": {}}
    pvals_family: dict[str, float] = {}

    for method, mlabel in METHODS:
        m_res: dict = {}
        print(f"\n{'-' * 100}")
        print(f"Оценка даты разворота — {mlabel}"
              + ("   [ОСНОВНАЯ, см. HYPOTHESIS.md §8]" if method == PRIMARY_METHOD
                 else "   [для сравнения]"))
        print(f"{'-' * 100}")
        for k in (12, 6, 3):
            prep, links = prepare(k)
            tag = f"k{k}"
            m_res[tag] = {"episodes": {}}
            print(f"\n  окно дифференцирования k = {k} "
                  f"{'(основное)' if k == 12 else '(устойчивость)'}")
            print(f"{'эпизод':<9} {'n':>3} {'rho':>7} {'p_perm':>8} "
                  f"{'плато':>6} {'край':>5} {'rho[5..95]':>16} {'выбыли':<14} порядок")
            for anchor in primary + covid_peak:
                e = episode_order(prep, links, anchor, MAXLAG, rng,
                                  do_perm=True, method=method)
                m_res[tag]["episodes"][mi_str(anchor)] = e
                if e.get("rho") is None:
                    print(f"{mi_str(anchor):<9} {e['n']:>3}   мало звеньев")
                    continue
                pl = e.get("rho_plateau", {})
                print(f"{mi_str(anchor):<9} {e['n']:>3} {e['rho']:>+7.3f} "
                      f"{e['p_perm']:>8.4f} {e['median_plateau']:>6.0f} "
                      f"{e['edge_hits']:>5} "
                      f"[{pl.get('p05', 0):+.2f},{pl.get('p95', 0):+.2f}]".rjust(16)
                      + f" {','.join(map(str, e['dropped'])) or '-':<14} "
                      + " ".join(e["est_order"][:6]))
                if k == 12 and anchor in primary and method == PRIMARY_METHOD:
                    pvals_family[f"A:{mi_str(anchor)}"] = e["p_perm"]

            rhos = [e["rho"] for a, e in m_res[tag]["episodes"].items()
                    if e.get("rho") is not None and mi(a + "-01") in primary]
            m_res[tag]["primary_rhos"] = rhos
            m_res[tag]["passed"] = sum(1 for r in rhos if r > BAND)
            m_res[tag]["of"] = len(rhos)
            m_res[tag]["median_rho"] = (round(statistics.median(rhos), 4)
                                        if rhos else None)
            print(f"    ИТОГО k={k}: rho>{BAND} в {m_res[tag]['passed']} из "
                  f"{len(rhos)} основных циклов; медиана rho = "
                  f"{m_res[tag]['median_rho']}")

        base = m_res["k12"]["primary_rhos"]
        shares = []
        for _ in range(EPISODE_REPS):
            draw = [rng.choice(base) for _ in base]
            shares.append(sum(1 for r in draw if r > BAND) / len(draw))
        shares.sort()
        m_res["episode_bootstrap"] = {
            "reps": EPISODE_REPS,
            "p05": round(shares[int(0.05 * (len(shares) - 1))], 3),
            "p50": round(shares[len(shares) // 2], 3),
            "p95": round(shares[int(0.95 * (len(shares) - 1))], 3),
        }
        eb = m_res["episode_bootstrap"]
        print(f"    бутстрап по эпизодам (доля циклов с rho>{BAND}): "
              f"медиана {eb['p50']}, 90 % интервал [{eb['p05']}, {eb['p95']}]")
        a_res["by_method"][method] = m_res

    # --------- диагностика, из-за которой заменена оценка (HYPOTHESIS.md §8)
    prep12, links12 = prepare(12)
    diag_total = diag_after_min = 0
    diag_rows = {}
    for anchor in primary:
        e = a_res["by_method"][PRIMARY_METHOD]["k12"]["episodes"][mi_str(anchor)]
        bad = [r["name"] for r in e["links"] if r["argmax_after_min"]]
        diag_rows[mi_str(anchor)] = {"n": e["n"], "argmax_after_min": bad}
        diag_total += e["n"]
        diag_after_min += len(bad)
    print(f"\nДиагностика пред-регистрированной оценки (от гипотезы не зависит):")
    print(f"   у {diag_after_min} из {diag_total} пар «звено x цикл» максимум "
          f"в окне лежит ПОЗЖЕ минимума того же окна, то есть argmax датирует "
          f"не спад, а последующее восстановление.")
    for a, row in diag_rows.items():
        print(f"   {a}: {len(row['argmax_after_min'])}/{row['n']}  "
              + (", ".join(row["argmax_after_min"]) or "-"))
    a_res["diagnostic_argmax_after_min"] = {
        "total_pairs": diag_total, "after_min": diag_after_min,
        "share": round(diag_after_min / diag_total, 3) if diag_total else None,
        "by_episode": diag_rows}

    # подробная таблица основного расчёта
    print(f"\nДаты разворота, k=12, основная оценка "
          f"(месяц; в скобках ширина плато, мес.; ! — упёрлось в границу окна):")
    hdr = f"{'звено':<17}" + "".join(f"{mi_str(a):>16}" for a in primary + covid_peak)
    print(hdr)
    detail = {}
    for lk in links12:
        line = f"{lk['n']:>2}. {lk['name']:<13}"
        detail[lk["name"]] = {}
        for anchor in primary + covid_peak:
            e = a_res["by_method"][PRIMARY_METHOD]["k12"]["episodes"][mi_str(anchor)]
            hit = next((r for r in e["links"] if r["link"] == lk["n"]), None)
            if hit is None:
                line += f"{'-':>16}"
                detail[lk["name"]][mi_str(anchor)] = None
            else:
                mark = "!" if hit["at_edge"] else " "
                cell = f"{hit['peak_str']}({hit['plateau_width']}){mark}"
                line += f"{cell:>16}"
                detail[lk["name"]][mi_str(anchor)] = {
                    "peak": hit["peak_str"], "plateau": hit["plateau_width"],
                    "at_edge": hit["at_edge"], "argmax": hit["argmax"],
                    "drawdown_sd": hit["drawdown_sd"]}
        print(line)
    a_res["peak_table"] = detail

    # ---- согласны ли циклы ДРУГ С ДРУГОМ, а не только с книгой
    print(f"\nСогласие циклов между собой (Спирмен между оценёнными порядками "
          f"двух циклов\nна их общем подмножестве звеньев; книга здесь "
          f"не участвует вовсе):")
    ep_main = [mi_str(a) for a in primary]
    peaks_by_ep = {}
    for a in ep_main:
        e = a_res["by_method"][PRIMARY_METHOD]["k12"]["episodes"][a]
        peaks_by_ep[a] = {r["link"]: r["peak"] for r in e["links"]}
    print("          " + "".join(f"{a:>10}" for a in ep_main))
    cross = {}
    pairwise = []
    for a in ep_main:
        line = f"{a:<10}"
        for b in ep_main:
            if a == b:
                line += f"{'.':>10}"
                continue
            common = sorted(set(peaks_by_ep[a]) & set(peaks_by_ep[b]))
            if len(common) < 4:
                line += f"{'-':>10}"
                continue
            r = spearman([float(peaks_by_ep[a][c]) for c in common],
                         [float(peaks_by_ep[b][c]) for c in common])
            cross[f"{a}|{b}"] = None if r is None else round(r, 4)
            line += f"{(r if r is not None else 0):>+10.3f}"
            if a < b and r is not None:
                pairwise.append(r)
        print(line)
    med_cross = round(statistics.median(pairwise), 4) if pairwise else None
    n_pos = sum(1 for r in pairwise if r > BAND)
    print(f"   пар циклов: {len(pairwise)}; медиана взаимного согласия "
          f"{med_cross}; выше {BAND} — {n_pos} пар")
    print(f"   для сравнения: медиана согласия с книгой = "
          f"{a_res['by_method'][PRIMARY_METHOD]['k12']['median_rho']}")
    a_res["cross_cycle_agreement"] = {
        "matrix": cross, "median": med_cross, "pairs": len(pairwise),
        "above_band": n_pos}

    # ---- измеренный порядок: медианный ранг звена по шести циклам
    print(f"\nИзмеренный порядок: медианный ранг звена по шести основным циклам")
    print(f"{'книга':>6}  {'звено':<17} {'медианный ранг':>15} "
          f"{'в скольких циклах':>18}  ранги по циклам")
    med_rank = {}
    for lk in links12:
        rr = []
        for a in ep_main:
            e = a_res["by_method"][PRIMARY_METHOD]["k12"]["episodes"][a]
            rk = (e.get("est_rank") or {}).get(lk["name"])
            if rk is None:
                continue
            rr.append(1.0 + (rk - 1.0) * 11.0 / max(1, e["n"] - 1))
        if not rr:
            continue
        med_rank[lk["name"]] = {"median": round(statistics.median(rr), 2),
                                "cycles": len(rr),
                                "ranks": [round(v, 1) for v in rr],
                                "spread": round(max(rr) - min(rr), 1)}
    for lk in links12:
        v = med_rank.get(lk["name"])
        if not v:
            continue
        print(f"{lk['n']:>6}  {lk['name']:<17} {v['median']:>15.1f} "
              f"{v['cycles']:>18}  "
              + " ".join(f"{x:.0f}" for x in v["ranks"])
              + f"   размах {v['spread']:.0f}")
    est_final = [nm for nm, _ in sorted(med_rank.items(),
                                        key=lambda kv: kv[1]["median"])]
    post_final = [lk["name"] for lk in links12 if lk["name"] in med_rank]
    rho_final = spearman([float(med_rank[nm]["median"]) for nm in post_final],
                         [float(i + 1) for i in range(len(post_final))])
    print(f"   измеренный порядок: {' > '.join(est_final)}")
    print(f"   rho медианного порядка с книжным = "
          f"{rho_final if rho_final is not None else 0:+.3f}")
    a_res["median_rank"] = med_rank
    a_res["median_order"] = est_final
    a_res["median_order_rho"] = None if rho_final is None else round(rho_final, 4)

    # ------------------------------------------------- устойчивость способа A
    print(f"\n--- устойчивость способа A ---")
    rob: dict = {}

    def run_variant(name: str, prep, links, anchors, half=MAXLAG,
                    method: str = PRIMARY_METHOD) -> dict:
        rhos, ns = [], []
        for anchor in anchors:
            e = episode_order(prep, links, anchor, half, rng, do_perm=False,
                              method=method)
            if e.get("rho") is not None:
                rhos.append(e["rho"])
                ns.append(e["n"])
        passed = sum(1 for r in rhos if r > BAND)
        v = {"rhos": rhos, "n_links": ns, "passed": passed, "of": len(rhos),
             "median": round(statistics.median(rhos), 4) if rhos else None}
        print(f"{name:<40} {passed}/{len(rhos)}  медиана {v['median']}  "
              f"rho = {', '.join(f'{r:+.2f}' for r in rhos)}")
        return v

    print(f"{'конфигурация':<40} прошли  медиана  rho по циклам")
    rob["main_k12"] = run_variant("основная (k=12, +-24, сглаж.)", prep12, links12, primary)
    for half in (18, 30, 36):
        rob[f"window{half}"] = run_variant(f"окно эпизода +-{half} мес.",
                                           prep12, links12, primary, half)
    prep_ns = {s["sid"]: transform(monthly[s["sid"]], s["kind"], 12, s["step"])
               for s in links12}
    rob["no_smoothing"] = run_variant("без сглаживания", prep_ns, links12, primary)
    for swap in ("link6_long", "awh_as_index", "pi_real", "orders_alt",
                 "deflated", "levels_asdrawn"):
        p2, l2 = prepare(12, swap)
        rob[swap] = run_variant(f"подмена: {swap}", p2, l2, primary)
        if swap == "levels_asdrawn":
            e = episode_order(p2, l2, primary[-1], MAXLAG, rng, do_perm=False)
            rob[swap]["order_2007"] = e["est_order"]
            print(f"{'   порядок 2007 на уровнях:':<40} "
                  + " > ".join(e["est_order"]))
    rob["early"] = run_variant("разбиение: ранние циклы 1973-1981",
                               prep12, links12, primary[:3])
    rob["late"] = run_variant("разбиение: поздние циклы 1990-2007",
                              prep12, links12, primary[3:])
    rob["with_covid"] = run_variant("с ковидом (7 эпизодов)",
                                    prep12, links12, primary + covid_peak)
    merged = [p for p in primary if p != mi("1981-07")]
    rob["merge_8081"] = run_variant("слияние 1980/1981 + ковид (6 эпизодов)",
                                    prep12, links12, merged + covid_peak)
    rob["fed_anchor"] = run_variant("якорь: начала ужесточения ФРС",
                                    prep12, links12, tight_1970)
    rob["preregistered_argmax"] = run_variant(
        "оценка из пред-регистрации (argmax)", prep12, links12, primary,
        method="argmax")
    rob["preregistered_argmax_fed"] = run_variant(
        "argmax + якорь ужесточения ФРС", prep12, links12, tight_1970,
        method="argmax")
    a_res["robustness"] = rob

    # вне выборки
    print(f"\nВне выборки: порядок оценён на 1973-1990, проверен на 2001-2020.")
    ins = [run_variant("  обучение 1973-1990", prep12, links12, primary[:4])]
    oos = [run_variant("  контроль 2001-2020", prep12, links12,
                       primary[4:] + covid_peak)]
    a_res["oos"] = {"in": ins[0], "out": oos[0]}

    # эпизоды шока предложения
    print(f"\n--- эпизоды с доминирующим шоком предложения (отдельный расчёт) ---")
    print(f"{'эпизод':<9} {'якорь':<9} {'n':>3} {'rho':>7} {'p_perm':>8}  порядок")
    supply = {}
    for label, when in SUPPLY_SHOCKS:
        anchor = mi(when + "-01")
        e = episode_order(prep12, links12, anchor, MAXLAG, rng, do_perm=True)
        supply[label] = e
        if e.get("rho") is None:
            print(f"{label:<9} {when:<9} {e['n']:>3}   мало звеньев")
            continue
        print(f"{label:<9} {when:<9} {e['n']:>3} {e['rho']:>+7.3f} "
              f"{e['p_perm']:>8.4f}  " + " ".join(e["est_order"][:6]))
    n_ok = sum(1 for e in supply.values() if (e.get("rho") or -9) > BAND)
    print(f"    ИТОГО: rho>{BAND} в {n_ok} из {len(supply)} шоковых эпизодов")
    print("    Оговорка из пред-регистрации: 1973-10 и 1979-01 лежат внутри окон")
    print("    циклов 1973-11 и 1980-01, поэтому независимый эпизод здесь один — 2021.")
    a_res["supply_shocks"] = supply
    out["A"] = a_res

    # =================================================================== B
    print(f"\n{'=' * 100}")
    print("СПОСОБ B. Матрица попарных лидов на сбалансированной панели")
    print(f"{'=' * 100}")
    b_res: dict = {}
    for pname, pspec in PANELS.items():
        prep, links_all = prepare(12, pspec["swap"])
        links = [lk for lk in links_all if lk["n"] in pspec["links"]]
        print(f"\n{pname} — {pspec['title']} ({pspec['role']})")
        r = panel_result(prep, links, rng, maxlag=MAXLAG, boot=args.boot,
                         do_boot=(pspec["role"] == "подтверждающая"))
        b_res[pname] = {**r, "title": pspec["title"], "role": pspec["role"]}
        if "error" in r:
            print(f"   {r['error']} (n={r['n']})")
            continue
        print(f"   панель: t = {r['t_span'][0]}..{r['t_span'][1]}, n = {r['n']}; "
              f"данные покрывают {r['span'][0]}..{r['span'][1]}")
        print(f"   оценённый порядок: {' > '.join(r['est_order'])}")
        print(f"   балл (мес. лида, + = раньше): "
              + ", ".join(f"{nm}={sc:+.1f}" for nm, sc in
                          zip(r["links"], r["scores"])))
        print(f"   rho с книжным порядком = {r['rho']:+.3f}   "
              f"p_perm = {r['p_perm']:.4f}   "
              f"(на медианном балле {r['rho_median_score']:+.3f})")
        tr = r["transitivity"]
        print(f"   нарушений транзитивности: {tr['violations']} из {tr['triples']} "
              f"троек ({(tr['rate'] or 0) * 100:.1f} %)")
        print(f"   лид упёрся в границу поиска +-{MAXLAG} мес. у "
              f"{r['edge_pairs']} пар из {r['pairs']} — у этих пар лид "
              f"не локализован; у {r['near_zero_pairs']} пар лид не больше "
              f"месяца, то есть очерёдности между ними нет")
        b = r.get("bootstrap")
        if b:
            print(f"   блочный бутстрап (блок {b['block']} мес., {b['reps']} повторов): "
                  f"медиана {b['p50']:+.3f}, 90 % интервал "
                  f"[{b['p05']:+.3f}, {b['p95']:+.3f}]; "
                  f"доля выборок с rho>{BAND} = {b['share_above_band']}, "
                  f"с rho>0 = {b['share_above_zero']}")
        if pspec["role"] == "подтверждающая":
            pvals_family[f"B:{pname}"] = r["p_perm"]

    # без ковида
    print(f"\nТе же панели без ковидного окна {COVID[0]}..{COVID[1]}:")
    for pname, pspec in PANELS.items():
        prep, links_all = prepare(12, pspec["swap"])
        links = [lk for lk in links_all if lk["n"] in pspec["links"]]
        r = panel_result(prep, links, rng, maxlag=MAXLAG, boot=args.boot,
                         exclude=(mi(COVID[0] + "-01"), mi(COVID[1] + "-01")),
                         do_boot=False)
        b_res[pname + "_nocovid"] = r
        if "error" in r:
            print(f"   {pname}: {r['error']}")
            continue
        print(f"   {pname}: n={r['n']}, rho={r['rho']:+.3f}, "
              f"нарушений транзитивности {(r['transitivity']['rate'] or 0) * 100:.1f} %, "
              f"порядок: {' > '.join(r['est_order'][:6])} ...")

    # попарная матрица лидов основной панели — печать целиком
    if "L" in b_res.get("B1", {}):
        print(f"\nМатрица попарных лидов B1 (месяцев; строка раньше столбца, если +):")
        names = b_res["B1"]["links"]
        print("        " + "".join(f"{nm[:6]:>7}" for nm in names))
        for i, nm in enumerate(names):
            print(f"{nm[:7]:<8}" + "".join(f"{b_res['B1']['L'][i][j]:>7}"
                                           for j in range(len(names))))
    out["B"] = b_res

    # =================================================================== D
    print(f"\n{'=' * 100}")
    print("БЛОК D. Пятизвенная цепочка H -> O -> P -> E -> I (вторичное утверждение)")
    print(f"{'=' * 100}")
    prep_d, _ = prepare(12, extra=EXTRA)
    step_of = {lk["sid"]: lk["step"] for lk in LINKS}
    step_of["CP"] = 3
    d_res = {"episodes": {}}
    print(f"{'эпизод':<9} {'n_бл':>5} {'rho5':>7} {'точно':>6} {'H<O':>5}  "
          f"позиции блоков (медиана даты пика)")
    for anchor in primary + covid_peak:
        lo, hi = anchor - MAXLAG, anchor + MAXLAG
        pos, members = {}, {}
        for code, _title, sids in BLOCKS5:
            dates = []
            for sid in sids:
                x = prep_d.get(sid)
                st = step_of.get(sid, 1)
                if x is None or not covers(x, lo, hi, st):
                    continue
                pk = date_peak(x, lo, hi, st)
                if pk:
                    dates.append(pk["peak"])
            if dates:
                pos[code] = statistics.median(dates)
                members[code] = [mi_str(d) for d in sorted(dates)]
        codes = [c for c, _, _ in BLOCKS5 if c in pos]
        if len(codes) < 4:
            print(f"{mi_str(anchor):<9} {len(codes):>5}   мало блоков")
            continue
        est = [pos[c] for c in codes]
        post = [float([c for c, _, _ in BLOCKS5].index(c) + 1) for c in codes]
        rho5 = spearman(est, post)
        exact = [c for c in sorted(codes, key=lambda c: pos[c])] == codes
        h_before_o = ("H" in pos and "O" in pos and pos["H"] < pos["O"])
        d_res["episodes"][mi_str(anchor)] = {
            "rho5": None if rho5 is None else round(rho5, 4),
            "order": [c for c in sorted(codes, key=lambda c: pos[c])],
            "positions": {c: mi_str(int(pos[c])) for c in codes},
            "members": members, "exact": exact, "H_before_O": h_before_o,
            "n_blocks": len(codes)}
        print(f"{mi_str(anchor):<9} {len(codes):>5} "
              f"{(rho5 if rho5 is not None else 0):>+7.3f} "
              f"{'да' if exact else 'нет':>6} {'да' if h_before_o else 'НЕТ':>5}  "
              + "  ".join(f"{c}:{mi_str(int(pos[c]))}"
                          for c in sorted(codes, key=lambda c: pos[c])))
    ep5 = [v for a, v in d_res["episodes"].items() if mi(a + "-01") in primary]
    d_res["passed"] = sum(1 for v in ep5 if (v["rho5"] or -9) > BAND)
    d_res["of"] = len(ep5)
    d_res["exact"] = sum(1 for v in ep5 if v["exact"])
    d_res["h_before_o"] = sum(1 for v in ep5 if v["H_before_O"])
    print(f"    ИТОГО по основным циклам: rho5>{BAND} в {d_res['passed']} из "
          f"{d_res['of']}; порядок точно совпал в {d_res['exact']}; "
          f"H раньше O в {d_res['h_before_o']} из {d_res['of']}")
    out["D"] = d_res

    # =================================================================== E
    print(f"\n{'=' * 100}")
    print("БЛОК E. Поток раньше запаса: ICSA и AWH против Payrolls (описательно)")
    print(f"{'=' * 100}")
    e_res = {"episodes": {}}
    print(f"{'эпизод':<9} {'ICSA':<9} {'AWH':<9} {'Payrolls':<9} "
          f"{'ICSA<PAY':>9} {'AWH<PAY':>9}")
    for anchor in primary + covid_peak:
        lo, hi = anchor - MAXLAG, anchor + MAXLAG
        got = {}
        for sid in ("ICSA", "AWHMAN", "PAYEMS"):
            x = prep_d.get(sid)
            if x is not None and covers(x, lo, hi, 1):
                pk = date_peak(x, lo, hi, 1)
                if pk:
                    got[sid] = pk["peak"]
        if "PAYEMS" not in got:
            continue
        ic = got.get("ICSA")
        aw = got.get("AWHMAN")
        row = {
            "ICSA": mi_str(ic) if ic else None,
            "AWHMAN": mi_str(aw) if aw else None,
            "PAYEMS": mi_str(got["PAYEMS"]),
            "icsa_before_payems": None if ic is None else ic < got["PAYEMS"],
            "awh_before_payems": None if aw is None else aw < got["PAYEMS"],
            "icsa_lead_months": None if ic is None else got["PAYEMS"] - ic,
            "awh_lead_months": None if aw is None else got["PAYEMS"] - aw,
        }
        e_res["episodes"][mi_str(anchor)] = row
        print(f"{mi_str(anchor):<9} {str(row['ICSA']):<9} {str(row['AWHMAN']):<9} "
              f"{row['PAYEMS']:<9} "
              f"{('да' if row['icsa_before_payems'] else 'НЕТ'):>9} "
              f"{('да' if row['awh_before_payems'] else 'НЕТ'):>9}")
    rows = list(e_res["episodes"].values())
    e_res["icsa_before_payems"] = sum(1 for r in rows if r["icsa_before_payems"])
    e_res["awh_before_payems"] = sum(1 for r in rows if r["awh_before_payems"])
    e_res["of"] = len(rows)
    print(f"    ИТОГО: заявки раньше Payrolls в {e_res['icsa_before_payems']} "
          f"из {e_res['of']} эпизодов; часы раньше Payrolls в "
          f"{e_res['awh_before_payems']} из {e_res['of']}")
    out["E"] = e_res

    # ================================================== множественность
    print(f"\n{'=' * 100}")
    print("Множественность: поправка Холма внутри объявленного семейства "
          f"из {len(pvals_family)} гипотез")
    print(f"{'=' * 100}")
    adj = holm(pvals_family)
    for k_ in sorted(adj):
        print(f"   {k_:<16} p = {pvals_family[k_]:<9.5f} p_holm = {adj[k_]:.5f}")
    out["pvalues_raw"] = pvals_family
    out["pvalues_holm"] = adj

    # ================================================== критерии и вердикт
    b1, b2 = b_res.get("B1", {}), b_res.get("B2", {})
    rho_ok = max((b1.get("rho") or -9), (b2.get("rho") or -9)) > BAND
    lb_ok = all((b.get("bootstrap", {}) or {}).get("p05", -9) > 0 for b in (b1, b2))
    c3 = rho_ok and lb_ok
    c4 = sum(1 for k_, v in adj.items() if k_.startswith("A:") and v < 0.05) >= 4

    print(f"\n{'=' * 100}")
    print("КРИТЕРИИ (HYPOTHESIS.md §4)")
    print(f"{'=' * 100}")

    verdicts = {}
    for method, mlabel in METHODS:
        m = a_res["by_method"][method]
        c1 = m["k12"]["passed"] >= 4 and m["k12"]["of"] == 6
        c2 = all(m[f"k{k}"]["passed"] >= 4 for k in (3, 6))
        if c1 and c2 and c3:
            v = "ПОДТВЕРЖДЕНО"
        elif (not c1) and (not c3):
            v = "ОПРОВЕРГНУТО"
        else:
            v = "НЕОПРЕДЕЛЕНО"
        verdicts[method] = {"C1": c1, "C2": c2, "C3": c3, "C4": c4, "verdict": v}
        head = "ОСНОВНАЯ" if method == PRIMARY_METHOD else "пред-регистрированная"
        print(f"\n   Оценка даты разворота — {head} ({mlabel}):")
        print(f"     C1  rho>{BAND} в >=4 из 6 основных циклов (k=12) ... "
              f"{'ДА' if c1 else 'НЕТ'}   факт: {m['k12']['passed']}/{m['k12']['of']}, "
              f"медиана rho = {m['k12']['median_rho']}")
        print(f"     C2  то же на k=3 и k=6 ........................... "
              f"{'ДА' if c2 else 'НЕТ'}   факт: k6 {m['k6']['passed']}/{m['k6']['of']}, "
              f"k3 {m['k3']['passed']}/{m['k3']['of']}")
        print(f"     ВЕРДИКТ по этой оценке: {v}")

    print(f"\n   C3  rho_full>{BAND} на панели и нижняя граница 90 % > 0  "
          f"{'ДА' if c3 else 'НЕТ'}")
    print(f"       факт: B1 rho={b1.get('rho')} [90 %: "
          f"{(b1.get('bootstrap') or {}).get('p05')}, "
          f"{(b1.get('bootstrap') or {}).get('p95')}]; "
          f"B2 rho={b2.get('rho')} [90 %: "
          f"{(b2.get('bootstrap') or {}).get('p05')}, "
          f"{(b2.get('bootstrap') or {}).get('p95')}]")
    print(f"   C4  >=4 циклов с p_holm<0.05 (вердикт не определяет) .. "
          f"{'ДА' if c4 else 'НЕТ'}")

    verdict = verdicts[PRIMARY_METHOD]["verdict"]
    agree = len({v["verdict"] for v in verdicts.values()}) == 1
    print(f"\nВЕРДИКТ Z02: {verdict}"
          + ("   (обе оценки даты разворота дают один и тот же вердикт)" if agree
             else "   ВНИМАНИЕ: оценки расходятся, см. REPORT.md"))
    print(f"Блок D (пятизвенная цепочка): rho5>{BAND} в {d_res['passed']} из "
          f"{d_res['of']} -> "
          f"{'ПОДТВЕРЖДЕНО' if d_res['passed'] >= 4 else 'НЕ ПОДТВЕРЖДЕНО'}")

    out["criteria"] = verdicts
    out["criteria_agree"] = agree
    out["verdict"] = verdict
    out["verdict_D"] = "ПОДТВЕРЖДЕНО" if d_res["passed"] >= 4 else "НЕ ПОДТВЕРЖДЕНО"

    # ================================================== рисунок и файлы
    fig = order_svg(a_res["by_method"][PRIMARY_METHOD], primary, covid_peak,
                    os.path.join(HERE, "order.svg"))

    path = os.path.join(HERE, "result.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nЗаписано: {path}")
    print(f"Записано: {fig}")
    print(f"Записано: {os.path.join(HERE, 'full-run.txt')}")
    return 0


# --------------------------------------------------------------------------- #
#  Рисунок: где на самом деле оказалось каждое звено
# --------------------------------------------------------------------------- #

def order_svg(a_res: dict, primary: list[int], covid: list[int], path: str) -> str:
    W, H = 860, 520
    L, R, T, B = 168, 150, 58, 60
    pw, ph = W - L - R, H - T - B
    names = [lk["name"] for lk in LINKS]
    eps = [mi_str(a) for a in primary] + [mi_str(a) for a in covid]

    def px(rank: float) -> float:
        return L + pw * (rank - 1) / 11.0

    def py(i: int) -> float:
        return T + ph * i / 11.0

    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="figz02t figz02d">',
         '<title id="figz02t">Оценённое место каждого из двенадцати звеньев '
         'по циклам против места, постулированного книгой</title>',
         '<desc id="figz02d">По вертикали — двенадцать звеньев в том порядке, '
         'в котором их перечисляет книга, сверху вниз от NAHB до Core CPI. '
         'По горизонтали — место, которое звено фактически заняло по дате '
         'разворота внутри окна цикла, от первого слева до двенадцатого справа. '
         'Каждая точка — один цикл, крупный ромб — медиана по циклам. '
         'Диагональ означала бы полное совпадение с книгой. '
         'Разброс точек по горизонтали для большинства звеньев перекрывает '
         'половину шкалы: место звена меняется от цикла к циклу сильнее, '
         'чем расстояние между соседними звеньями.</desc>']
    for r in range(1, 13):
        o.append(f'<line class="viz-grid" x1="{px(r):.1f}" y1="{T - 8}" '
                 f'x2="{px(r):.1f}" y2="{T + ph + 8}"/>')
        o.append(f'<text class="viz-axis" x="{px(r):.1f}" y="{T + ph + 28}" '
                 f'text-anchor="middle">{r}</text>')
    o.append(f'<text class="viz-axis" x="{L + pw / 2:.0f}" y="{T + ph + 50}" '
             f'text-anchor="middle">фактическое место по дате разворота -></text>')
    o.append(f'<line class="viz-axisline" x1="{px(1):.1f}" y1="{py(0):.1f}" '
             f'x2="{px(12):.1f}" y2="{py(11):.1f}" stroke-dasharray="4 4"/>')

    for i, nm in enumerate(names):
        o.append(f'<text class="viz-label" x="{L - 14}" y="{py(i) + 4:.1f}" '
                 f'text-anchor="end">{i + 1}. {nm}</text>')
        got = []
        for a in eps:
            e = a_res["k12"]["episodes"].get(a, {})
            rk = (e.get("est_rank") or {}).get(nm)
            if rk is None:
                continue
            n = e["n"]
            # ранг внутри подмножества -> шкала 1..12
            scaled = 1.0 + (rk - 1.0) * 11.0 / max(1, n - 1)
            got.append((a, scaled))
        for a, sc in got:
            covid_ep = a in [mi_str(c) for c in covid]
            col = "var(--series-7)" if covid_ep else "var(--series-1)"
            o.append(f'<circle cx="{px(sc):.1f}" cy="{py(i):.1f}" r="4" '
                     f'style="fill:{col}" opacity="0.55"/>')
        base = [sc for a, sc in got if a not in [mi_str(c) for c in covid]]
        if base:
            med = statistics.median(base)
            o.append(f'<path d="M{px(med):.1f},{py(i) - 7:.1f} '
                     f'L{px(med) + 7:.1f},{py(i):.1f} '
                     f'L{px(med):.1f},{py(i) + 7:.1f} '
                     f'L{px(med) - 7:.1f},{py(i):.1f} Z" '
                     f'style="fill:var(--series-8)"/>')
            o.append(f'<text class="viz-annot" x="{L + pw + 12}" '
                     f'y="{py(i) + 4:.1f}">медиана {med:.1f}</text>')
    o.append(f'<text class="viz-annot" x="{L}" y="{T - 26}">'
             f'кружок — один цикл (серый - ковид), ромб — медиана по шести '
             f'основным циклам; пунктир — книжный порядок</text>')
    o.append("</svg>")
    svg = "\n".join(o)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg + "\n")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
