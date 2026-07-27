#!/usr/bin/env python3
"""Z03 — инверсия кривой доходности как признак рецессии.

Критерии зафиксированы до расчёта: см. HYPOTHESIS.md. Скрипт ничего не решает
сам — он считает величины, названные в критериях, и печатает их.

Главный выход задачи — **число ложных тревог**, а не средний лаг: аудит первой
редакции нашёл, что частота ложных срабатываний названа проблемой пять раз
и не измерена ни разу.

Запуск:
    python run.py              # из кэша, если он свежий
    python run.py --force      # перекачать исходные ряды
    python run.py --boot 5000  # больше повторов бутстрапа (по умолчанию 2000)

Результат: result.json и episodes.svg рядом со скриптом + таблицы в stdout.
Зависимости: только стандартная библиотека + sources.py из родительской папки.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from typing import Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import sources as S  # noqa: E402

SEED = 20260727
BLOCK_MONTHS = 24          # блок бутстрапа для AUC
K_MAIN = 3                 # склейка эпизодов, HYPOTHESIS §4
W_MAIN = 24                # окно ожидания, HYPOTHESIS §2
H_MAIN = 12                # горизонт AUC, HYPOTHESIS §7
OOS_FROM = "1990-01"       # удержанный хвост для AUC, HYPOTHESIS §7

# --------------------------------------------------------------------------- #
#  Месячная сетка: индекс = год*12 + (месяц-1)
# --------------------------------------------------------------------------- #


def mi(date: str) -> int:
    return int(date[:4]) * 12 + (int(date[5:7]) - 1)


def mi_str(idx: int) -> str:
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def qi(date: str) -> int:
    """Индекс квартала = год*4 + (квартал-1)."""
    return int(date[:4]) * 4 + (int(date[5:7]) - 1) // 3


def qi_str(idx: int) -> str:
    return f"{idx // 4:04d}Q{idx % 4 + 1}"


def q_last_month(q: int) -> int:
    """Последний месяц квартала как месячный индекс."""
    return (q // 4) * 12 + (q % 4) * 3 + 2


# --------------------------------------------------------------------------- #
#  Месячная агрегация дневного спреда
# --------------------------------------------------------------------------- #


def monthly_mean(series: S.Series) -> dict[int, float]:
    acc: dict[int, list[float]] = {}
    for d, v in series.observed:
        acc.setdefault(mi(d), []).append(v)
    return {k: sum(vs) / len(vs) for k, vs in acc.items()}


def monthly_any_negative(series: S.Series) -> dict[int, bool]:
    """Был ли в месяце хотя бы один день с отрицательным спредом."""
    acc: dict[int, bool] = {}
    for d, v in series.observed:
        t = mi(d)
        acc[t] = acc.get(t, False) or (v < 0)
    return acc


def monthly_days(series: S.Series) -> dict[int, int]:
    acc: dict[int, int] = {}
    for d, _ in series.observed:
        acc[mi(d)] = acc.get(mi(d), 0) + 1
    return acc


def month_level(series: S.Series) -> dict[int, float]:
    return {mi(d): v for d, v in series.observed}


# --------------------------------------------------------------------------- #
#  Эпизоды инверсии
# --------------------------------------------------------------------------- #


def episodes(base: dict[int, bool], k: int) -> list[list[int]]:
    """Максимальные наборы инвертированных месяцев; разрыв <= k их не рвёт.

    Возвращает список эпизодов, каждый — отсортированный список месяцев,
    в которых условие выполнено (месяцы разрыва внутрь не включаются).
    """
    hot = sorted(t for t, flag in base.items() if flag)
    if not hot:
        return []
    out: list[list[int]] = [[hot[0]]]
    for t in hot[1:]:
        if t - out[-1][-1] - 1 <= k:
            out[-1].append(t)
        else:
            out.append([t])
    return out


def signal_month(ep: list[int], base: dict[int, bool], rule: str) -> int | None:
    """Дата сигнала внутри эпизода по правилу слота 2 (HYPOTHESIS §5)."""
    if rule in ("day", "month"):
        return ep[0]
    if rule == "three":
        for t in ep:
            if base.get(t) and base.get(t - 1) and base.get(t - 2):
                return t
        return None            # эпизод короче трёх месяцев — сигнала нет
    raise ValueError(rule)


# --------------------------------------------------------------------------- #
#  События
# --------------------------------------------------------------------------- #


def nber_peaks(usrec: dict[int, float], usrecm: dict[int, float]) -> tuple[list[int], list[str]]:
    """Пики NBER: USREC(p)=0 и USREC(p+1)=1. Контроль по USRECM."""
    peaks, warn = [], []
    for t in sorted(usrec):
        if usrec.get(t) == 0 and usrec.get(t + 1) == 1:
            peaks.append(t)
            if not (usrecm.get(t) == 1 and usrecm.get(t - 1) == 0):
                warn.append(f"{mi_str(t)}: USREC даёт пик, USRECM не подтверждает "
                            f"(USRECM(p)={usrecm.get(t)}, USRECM(p-1)={usrecm.get(t - 1)})")
    return peaks, warn


def two_quarter_events(gdp: dict[int, float]) -> list[int]:
    """«Два квартала спада подряд» -> месяц события = последний месяц квартала q-2.

    Дополнение к HYPOTHESIS §5, записанное ДО первого прогона (см. §12):
    подряд идущие кварталы, удовлетворяющие условию, принадлежат одному спаду,
    поэтому событие фиксируется на ПЕРВОМ квартале такой серии.
    """
    dec = {q: (q - 1 in gdp and gdp[q] < gdp[q - 1]) for q in gdp}
    hits = sorted(q for q in gdp if dec.get(q) and dec.get(q - 1))
    firsts: list[int] = []
    prev = None
    for q in hits:
        if prev is None or q - prev > 1:
            firsts.append(q)
        prev = q
    return [q_last_month(q - 2) for q in firsts]


# --------------------------------------------------------------------------- #
#  Счёт: верные, ложные, пропуски, цензурированные
# --------------------------------------------------------------------------- #


def score(signals: list[int], events: list[int], *, w: int,
          t_start: int, t_end: int) -> dict:
    """HYPOTHESIS §4. Ничего не решает — только считает объявленные величины."""
    ev = sorted(events)
    detail = []
    tp = fa = censored = 0
    lags: list[int] = []
    for t0 in sorted(signals):
        nxt = [p for p in ev if t0 < p <= t0 + w]
        if nxt:
            p = nxt[0]
            tp += 1
            lags.append(p - t0)
            detail.append({"signal": mi_str(t0), "outcome": "TP",
                           "peak": mi_str(p), "lag": p - t0})
        elif t0 + w <= t_end:
            fa += 1
            detail.append({"signal": mi_str(t0), "outcome": "FA",
                           "peak": None, "lag": None})
        else:
            censored += 1
            detail.append({"signal": mi_str(t0), "outcome": "CENSORED",
                           "peak": None, "lag": None,
                           "window_ends": mi_str(t0 + w)})

    eligible, left_edge, fn = [], [], []
    for p in ev:
        if p > t_end or p < t_start:
            continue           # событие вне окна наблюдения спреда вовсе
        if p - w < t_start:
            left_edge.append(mi_str(p))
            continue
        eligible.append(p)
        if not any(p - w <= t0 <= p - 1 for t0 in signals):
            fn.append(mi_str(p))

    lags_sorted = sorted(lags)
    return {
        "n_signals": len(signals), "TP": tp, "FA": fa, "FN": len(fn),
        "censored": censored,
        "fa_per_tp": (round(fa / tp, 3) if tp else None),
        "peaks_eligible": len(eligible),
        "peaks_left_edge_excluded": left_edge,
        "missed_peaks": fn,
        "lags": lags_sorted,
        "lag_median": (lags_sorted[len(lags_sorted) // 2] if lags_sorted else None),
        "lag_min": (lags_sorted[0] if lags_sorted else None),
        "lag_max": (lags_sorted[-1] if lags_sorted else None),
        "lag_iqr": ([lags_sorted[int(0.25 * (len(lags_sorted) - 1))],
                     lags_sorted[int(0.75 * (len(lags_sorted) - 1))]]
                    if lags_sorted else None),
        "episodes": detail,
    }


def build_signals(spread_mean: dict[int, float], spread_anyneg: dict[int, bool],
                  rule: str, k: int) -> tuple[list[int], list[list[int]]]:
    base = ({t: v < 0 for t, v in spread_mean.items()} if rule in ("month", "three")
            else dict(spread_anyneg))
    eps = episodes(base, k)
    sig = [signal_month(ep, base, rule) for ep in eps]
    return [t for t in sig if t is not None], eps


# --------------------------------------------------------------------------- #
#  AUC и парный блочный бутстрап
# --------------------------------------------------------------------------- #


def auc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    """Площадь под ROC через ранги (Манн-Уитни), связки — средними рангами."""
    n1 = sum(labels)
    n0 = len(labels) - n1
    if n1 == 0 or n0 == 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    r1 = sum(r for r, y in zip(ranks, labels) if y == 1)
    return (r1 - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def moving_blocks(n: int, block: int, rng: random.Random) -> list[int]:
    idx: list[int] = []
    last = max(1, n - block + 1)
    while len(idx) < n:
        start = rng.randrange(last)
        idx.extend(range(start, min(start + block, n)))
    return idx[:n]


def auc_compare(months: list[int], x_a: list[float], x_b: list[float],
                y: list[int], *, reps: int, rng: random.Random) -> dict:
    a, b = auc(x_a, y), auc(x_b, y)
    if a is None or b is None:
        return {"auc_a": a, "auc_b": b, "n": len(y), "positives": sum(y)}
    diffs, aa, bb = [], [], []
    n = len(y)
    for _ in range(reps):
        idx = moving_blocks(n, BLOCK_MONTHS, rng)
        ys = [y[i] for i in idx]
        if not 0 < sum(ys) < len(ys):
            continue
        ra = auc([x_a[i] for i in idx], ys)
        rb = auc([x_b[i] for i in idx], ys)
        if ra is None or rb is None:
            continue
        aa.append(ra)
        bb.append(rb)
        diffs.append(ra - rb)
    diffs.sort()
    if not diffs:
        return {"auc_a": round(a, 4), "auc_b": round(b, 4), "n": n, "positives": sum(y)}
    lo = diffs[int(0.05 * (len(diffs) - 1))]
    hi = diffs[int(0.95 * (len(diffs) - 1))]
    share_le0 = sum(1 for d in diffs if d <= 0) / len(diffs)
    share_ge0 = sum(1 for d in diffs if d >= 0) / len(diffs)
    p = min(1.0, 2.0 * min(share_le0, share_ge0))
    aa.sort()
    bb.sort()
    return {
        "auc_a": round(a, 4), "auc_b": round(b, 4),
        "auc_a_ci90": [round(aa[int(0.05 * (len(aa) - 1))], 4),
                       round(aa[int(0.95 * (len(aa) - 1))], 4)],
        "auc_b_ci90": [round(bb[int(0.05 * (len(bb) - 1))], 4),
                       round(bb[int(0.95 * (len(bb) - 1))], 4)],
        "delta": round(a - b, 4),
        "delta_ci90": [round(lo, 4), round(hi, 4)],
        "p_two_sided": round(p, 4),
        "verdict": ("10y-3m строго лучше" if lo > 0 else
                    "10y-2y строго лучше" if hi < 0 else "различие не установлено"),
        "n": n, "positives": sum(y), "boot_ok": len(diffs),
        "span": [mi_str(months[0]), mi_str(months[-1])],
    }


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = round(running, 4)
    return out


def bootstrap_lags(lags: list[int], *, reps: int, rng: random.Random) -> dict:
    """Ресемплинг ЭПИЗОДОВ. При n<10 это оценка неустойчивости, а не тест."""
    if len(lags) < 2:
        return {"n": len(lags)}
    meds, mins, maxs = [], [], []
    for _ in range(reps):
        draw = [lags[rng.randrange(len(lags))] for _ in lags]
        draw.sort()
        meds.append(draw[len(draw) // 2])
        mins.append(draw[0])
        maxs.append(draw[-1])
    meds.sort()
    return {
        "n": len(lags), "reps": reps,
        "median_ci90": [meds[int(0.05 * (reps - 1))], meds[int(0.95 * (reps - 1))]],
        "median_point": sorted(lags)[len(lags) // 2],
    }


# --------------------------------------------------------------------------- #
#  Реал-тайм: винтажи реального выпуска ФРБ Филадельфии
# --------------------------------------------------------------------------- #


def realtime_two_quarter(sheet: list[list]) -> tuple[list[dict], list[str]]:
    """Первое появление «двух кварталов спада подряд» в винтажах ROUTPUT.

    Возвращает список событий: экономическая дата (последний месяц квартала
    q-2, как в §5) и дата распознавания (середина винтажного квартала).
    """
    header = sheet[0]
    warn: list[str] = []
    vint_cols: list[tuple[int, int]] = []       # (индекс колонки, квартал винтажа)
    for c, name in enumerate(header):
        if not isinstance(name, str) or not name.upper().startswith("ROUTPUT"):
            continue
        tail = name.upper().replace("ROUTPUT", "")
        if len(tail) != 4 or tail[2] != "Q":
            warn.append(f"винтаж с неожиданным именем: {name}")
            continue
        yy, q = int(tail[:2]), int(tail[3])
        year = 1900 + yy if yy >= 40 else 2000 + yy
        vint_cols.append((c, year * 4 + (q - 1)))
    vint_cols.sort(key=lambda cq: cq[1])

    first_seen: dict[int, int] = {}             # квартал события -> квартал винтажа
    for col, vq in vint_cols:
        vals: dict[int, float] = {}
        for row in sheet[1:]:
            if not row or not isinstance(row[0], str) or ":Q" not in row[0]:
                continue
            y, q = row[0].split(":Q")
            v = S._num(row[col]) if col < len(row) else None
            if v is not None:
                vals[int(y) * 4 + int(q) - 1] = v
        dec = {q: (q - 1 in vals and vals[q] < vals[q - 1]) for q in vals}
        for q in sorted(vals):
            if dec.get(q) and dec.get(q - 1) and q not in first_seen:
                first_seen[q] = vq

    events: list[dict] = []
    prev = None
    for q in sorted(first_seen):
        if prev is None or q - prev > 1:         # первый квартал серии = спад
            vq = first_seen[q]
            # винтаж «середина квартала»: Q1->февраль, Q2->май, Q3->август, Q4->ноябрь
            rec_month = (vq // 4) * 12 + (vq % 4) * 3 + 1
            events.append({
                "quarter_pair_ends": qi_str(q),
                "event_month": mi_str(q_last_month(q - 2)),
                "_event_mi": q_last_month(q - 2),
                "first_vintage": qi_str(vq),
                "recognised_month": mi_str(rec_month),
                "recognition_lag_months": rec_month - q_last_month(q - 2),
            })
        prev = q
    return events, warn


# --------------------------------------------------------------------------- #
#  Рисунок: эпизоды инверсии на временной оси
# --------------------------------------------------------------------------- #


def episodes_svg(rows: list[dict], path: str, *, w: int) -> str:
    """Каждый эпизод — отрезок от сигнала до назначенного пика либо до конца окна.

    Рисуется ровно то, ради чего задача существует: сколько эпизодов, какой
    у каждого лаг и сколько из них не привели ни к чему.
    """
    W, H = 880, 60 + 34 * len(rows) + 70
    L, R, T = 108, 40, 54
    plot_w = W - L - R
    lo = min(r["x0"] for r in rows) - 6
    hi = max(max(r["x1"], r["x0"] + w) for r in rows) + 6

    def px(t: int) -> float:
        return L + plot_w * (t - lo) / (hi - lo)

    tp = sum(1 for r in rows if r["outcome"] == "TP")
    fa = sum(1 for r in rows if r["outcome"] == "FA")
    out: list[str] = [
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="figz03t figz03d">',
        '<title id="figz03t">Эпизоды инверсии спреда десятилетних к трёхмесячным '
        'и их исход</title>',
        f'<desc id="figz03d">Горизонтальная временная ось по годам. Каждый эпизод '
        f'инверсии — отдельная строка: отрезок начинается в месяце сигнала. '
        f'У верных срабатываний отрезок заканчивается кружком в месяце пика '
        f'по датировке NBER, и его длина есть лаг. У ложных тревог отрезок '
        f'протянут на всё окно ожидания в {w} месяцев и заканчивается крестом: '
        f'пика в окне не случилось. Всего строк {len(rows)}, из них верных '
        f'срабатываний {tp}, ложных тревог {fa}.</desc>',
    ]
    y0 = T
    for year in range(((lo // 12) // 5) * 5, hi // 12 + 1, 5):
        x = px(year * 12)
        if x < L - 1 or x > L + plot_w + 1:
            continue
        out.append(f'<line class="viz-grid" x1="{x:.1f}" y1="{T - 16}" '
                   f'x2="{x:.1f}" y2="{y0 + 34 * len(rows)}"/>')
        out.append(f'<text class="viz-axis" x="{x:.1f}" y="{T - 22}" '
                   f'text-anchor="middle">{year}</text>')
    for i, r in enumerate(rows):
        y = y0 + 34 * i + 16
        colour = "var(--series-1)" if r["outcome"] == "TP" else "var(--series-8)"
        x1 = px(r["x1"])
        out.append(f'<text class="viz-axis" x="{L - 12}" y="{y + 4}" '
                   f'text-anchor="end">{r["label"]}</text>')
        out.append(f'<line class="viz-line" x1="{px(r["x0"]):.1f}" y1="{y}" '
                   f'x2="{x1:.1f}" y2="{y}" stroke="{colour}" stroke-width="4"/>')
        out.append(f'<circle cx="{px(r["x0"]):.1f}" cy="{y}" r="4" fill="{colour}"/>')
        if r["outcome"] == "TP":
            out.append(f'<circle cx="{x1:.1f}" cy="{y}" r="6" fill="none" '
                       f'stroke="{colour}" stroke-width="3"/>')
            out.append(f'<text class="viz-annot" x="{x1 + 12:.1f}" y="{y + 4}" '
                       f'fill="{colour}">{r["note"]}</text>')
        else:
            out.append(f'<line x1="{x1 - 5:.1f}" y1="{y - 5}" x2="{x1 + 5:.1f}" '
                       f'y2="{y + 5}" stroke="{colour}" stroke-width="3"/>')
            out.append(f'<line x1="{x1 - 5:.1f}" y1="{y + 5}" x2="{x1 + 5:.1f}" '
                       f'y2="{y - 5}" stroke="{colour}" stroke-width="3"/>')
            out.append(f'<text class="viz-annot" x="{x1 + 12:.1f}" y="{y + 4}" '
                       f'fill="{colour}">{r["note"]}</text>')
    out.append(f'<text class="viz-annot" x="{L}" y="{y0 + 34 * len(rows) + 30}">'
               f'кружок — пик по датировке NBER; крест — окно {w} мес. истекло, '
               f'пика не случилось</text>')
    out.append("</svg>")
    svg = "\n".join(out)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg + "\n")
    return path


# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--boot", type=int, default=2000)
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    rng = random.Random(SEED)

    print("Загрузка рядов…")
    t10y3m = S.fred("T10Y3M", force=args.force)
    t10y2y = S.fred("T10Y2Y", force=args.force)
    usrec_s = S.fred("USREC", force=args.force)
    usrecm_s = S.fred("USRECM", force=args.force)
    gs10_s = S.fred("GS10", force=args.force)
    tb3ms_s = S.fred("TB3MS", force=args.force)
    gdp_s = S.fred("GDPC1", force=args.force)
    nber = S.nber_announcements(force=args.force)
    rtds = S.philfed_realtime("routputqvqd", force=args.force)
    for s in (t10y3m, t10y2y, usrec_s, usrecm_s, gs10_s, tb3ms_s, gdp_s,
              nber["peaks"], nber["troughs"]):
        print("  ", s.describe())

    spreads = {
        "10y-3m": monthly_mean(t10y3m),
        "10y-2y": monthly_mean(t10y2y),
    }
    anyneg = {
        "10y-3m": monthly_any_negative(t10y3m),
        "10y-2y": monthly_any_negative(t10y2y),
    }
    days = {"10y-3m": monthly_days(t10y3m), "10y-2y": monthly_days(t10y2y)}
    usrec = month_level(usrec_s)
    usrecm = month_level(usrecm_s)
    gdp = {qi(d): v for d, v in gdp_s.observed}

    warnings: list[str] = []
    for name, dd in days.items():
        thin = [mi_str(t) for t, n in sorted(dd.items()) if n < 5]
        if thin:
            warnings.append(f"{name}: месяцы с менее чем 5 торговыми днями — "
                            f"{', '.join(thin[:6])} (всего {len(thin)}); месячное "
                            f"среднее в них шумнее прочих")
        gaps = [mi_str(t) for t in range(min(dd), max(dd) + 1) if t not in dd]
        if gaps:
            warnings.append(f"{name}: месяцы без единого наблюдения — "
                            f"{', '.join(gaps)}; эпизод вокруг такого месяца "
                            f"может распасться на два")

    peaks, peak_warn = nber_peaks(usrec, usrecm)
    warnings += peak_warn
    t_end_usrec = max(usrec)
    print(f"\nПики NBER из USREC (контроль USRECM): "
          f"{', '.join(mi_str(p) for p in peaks[-10:])}  (всего {len(peaks)})")
    ev2q = two_quarter_events(gdp)
    print(f"События «два квартала спада» (текущий винтаж GDPC1, с "
          f"{qi_str(min(gdp))}): {', '.join(mi_str(p) for p in ev2q[-10:])}  "
          f"(всего {len(ev2q)})")
    for w in warnings:
        print(f"  ВНИМАНИЕ: {w}")

    events = {"nber": peaks, "gdp2q": ev2q}
    t_end = {"nber": t_end_usrec, "gdp2q": max(q_last_month(q) for q in gdp)}

    # ---------------- основная конфигурация -------------------------------- #
    main_mean = spreads["10y-3m"]
    t_start_main = min(main_mean)
    sig_main, eps_main = build_signals(main_mean, anyneg["10y-3m"], "month", K_MAIN)
    main_score = score(sig_main, peaks, w=W_MAIN,
                       t_start=t_start_main, t_end=t_end_usrec)

    print(f"\n{'=' * 78}\nОСНОВНАЯ КОНФИГУРАЦИЯ (заготовка главы 48, взята как есть)\n"
          f"ряд 10y-3m · месяц в среднем ниже нуля · окно {W_MAIN} мес. · "
          f"пик NBER · склейка K={K_MAIN}\n{'=' * 78}")
    print(f"{'эпизод':>22}  {'исход':<10} {'пик':<9} {'лаг':>4}  глубина, п.п.")
    ep_by_signal = {signal_month(ep, {t: v < 0 for t, v in main_mean.items()},
                                 "month"): ep for ep in eps_main}
    fig_rows = []
    for d in main_score["episodes"]:
        t0 = mi(d["signal"] + "-01")
        ep = ep_by_signal.get(t0, [t0])
        depth = min(main_mean[t] for t in ep)
        print(f"{d['signal']}..{mi_str(ep[-1]):>9}  {d['outcome']:<10} "
              f"{(d['peak'] or '—'):<9} {(d['lag'] if d['lag'] is not None else '—'):>4}"
              f"  {depth:+.2f}")
        fig_rows.append({
            "label": f"{d['signal']}", "x0": t0,
            "x1": (mi(d["peak"] + "-01") if d["peak"] else t0 + W_MAIN),
            "outcome": d["outcome"],
            "note": (f"пик {d['peak']}, лаг {d['lag']} мес." if d["peak"]
                     else f"пика нет ({d['outcome']})"),
        })
    print(f"\nверных {main_score['TP']} · ложных {main_score['FA']} · "
          f"пропусков {main_score['FN']} · цензурированных {main_score['censored']}")
    print(f"FA/TP = {main_score['fa_per_tp']}")
    print(f"лаг: медиана {main_score['lag_median']}, размах "
          f"{main_score['lag_min']}–{main_score['lag_max']}, "
          f"межквартильный {main_score['lag_iqr']}")
    if main_score["missed_peaks"]:
        print(f"пропущенные пики: {', '.join(main_score['missed_peaks'])}")
    if main_score["peaks_left_edge_excluded"]:
        print(f"пики вне зоны наблюдения (окно уходит левее начала ряда): "
              f"{', '.join(main_score['peaks_left_edge_excluded'])}")
    boot_lag = bootstrap_lags(main_score["lags"], reps=args.boot, rng=rng)
    print(f"бутстрап по эпизодам (n={boot_lag.get('n')}): медиана "
          f"{boot_lag.get('median_point')}, 90 % интервал {boot_lag.get('median_ci90')}")

    u1 = main_score["FN"] <= 1
    u2 = (main_score["fa_per_tp"] is not None and main_score["fa_per_tp"] <= 0.5)
    print(f"\nU1 (пропусков <= 1): {'выполнено' if u1 else 'НЕ выполнено'}"
          f"   U2 (FA/TP <= 0.5): {'выполнено' if u2 else 'НЕ выполнено'}")

    # ---------------- сетка 24 -------------------------------------------- #
    print(f"\n{'=' * 78}\nСЕТКА 24 ОПРЕДЕЛЕНИЙ (рис. 48.1: 2 ряда x 3 срабатывания "
          f"x 2 окна x 2 события)\n{'=' * 78}")
    print(f"{'ряд':<8} {'срабатывание':<14} {'W':>3} {'событие':<7} "
          f"{'эп':>3} {'TP':>3} {'FA':>3} {'FN':>3} {'цен':>4} {'FA/TP':>6} "
          f"{'лаг мед':>8} {'размах':>10}  U1 U2")
    grid: list[dict] = []
    rule_names = {"day": "день<0", "month": "месяц<0", "three": "3 мес. подряд"}
    for sp_name in ("10y-3m", "10y-2y"):
        for rule in ("day", "month", "three"):
            sig, _ = build_signals(spreads[sp_name], anyneg[sp_name], rule, K_MAIN)
            for w in (12, 24):
                for ev_name in ("nber", "gdp2q"):
                    sc = score(sig, events[ev_name], w=w,
                               t_start=min(spreads[sp_name]), t_end=t_end[ev_name])
                    ok1 = sc["FN"] <= 1
                    ok2 = sc["fa_per_tp"] is not None and sc["fa_per_tp"] <= 0.5
                    cell = {"spread": sp_name, "trigger": rule, "window": w,
                            "event": ev_name, "U1": ok1, "U2": ok2,
                            **{k: v for k, v in sc.items() if k != "episodes"},
                            "episodes": sc["episodes"]}
                    grid.append(cell)
                    ratio = sc["fa_per_tp"] if sc["fa_per_tp"] is not None else 0.0
                    span = (f"{sc['lag_min']}-{sc['lag_max']}" if sc["lags"] else "—")
                    print(f"{sp_name:<8} {rule_names[rule]:<14} {w:>3} {ev_name:<7} "
                          f"{sc['n_signals']:>3} {sc['TP']:>3} {sc['FA']:>3} "
                          f"{sc['FN']:>3} {sc['censored']:>4} {ratio:>6.2f} "
                          f"{str(sc['lag_median']):>8} {span:>10}"
                          f"  {'+' if ok1 else '-'}  {'+' if ok2 else '-'}")
    both_ok = sum(1 for c in grid if c["U1"] and c["U2"])
    print(f"\nячеек, где выполнены оба условия: {both_ok} из {len(grid)}")

    # ---------------- эпизод 2022-2024 ------------------------------------ #
    print(f"\n{'=' * 78}\nЭПИЗОД 2022–2024: как он классифицирован в каждой ячейке\n"
          f"{'=' * 78}")
    ep2022: list[dict] = []
    for c in grid:
        hit = [d for d in c["episodes"] if "2022" <= d["signal"][:4] <= "2023"]
        for d in hit:
            ep2022.append({"spread": c["spread"], "trigger": c["trigger"],
                           "window": c["window"], "event": c["event"],
                           "signal": d["signal"], "outcome": d["outcome"],
                           "peak": d["peak"], "lag": d["lag"]})
    tally: dict[str, int] = {}
    for r in ep2022:
        tally[r["outcome"]] = tally.get(r["outcome"], 0) + 1
    for r in ep2022:
        tail = ("" if r["peak"] is None
                else f", событие {r['peak']}, лаг {r['lag']} мес.")
        print(f"  {r['spread']:<8} {rule_names[r['trigger']]:<14} W={r['window']:<3} "
              f"{r['event']:<7} сигнал {r['signal']} -> {r['outcome']}{tail}")
    print(f"  итого по ячейкам: {tally}")

    # ---------------- AUC -------------------------------------------------- #
    print(f"\n{'=' * 78}\nAUC ДВУХ СПРЕДОВ ВНЕ ВЫБОРКИ (с {OOS_FROM}), "
          f"цель — USREC через h месяцев\n{'=' * 78}")
    auc_blocks: dict[str, dict] = {}
    pvals: dict[str, float] = {}
    common = sorted(set(spreads["10y-3m"]) & set(spreads["10y-2y"]))
    for h in (6, 12, 18, 24):
        for label, only_expansion, frm in (("oos", True, OOS_FROM),
                                           ("in_sample", True, None),
                                           ("oos_all_months", False, OOS_FROM)):
            months, xa, xb, ys = [], [], [], []
            for t in common:
                if usrec.get(t) is None or usrec.get(t + h) is None:
                    continue
                if only_expansion and usrec[t] != 0:
                    continue
                if frm and t < mi(frm + "-01"):
                    continue
                if frm is None and t >= mi(OOS_FROM + "-01"):
                    continue
                months.append(t)
                xa.append(-spreads["10y-3m"][t])
                xb.append(-spreads["10y-2y"][t])
                ys.append(1 if usrec[t + h] == 1 else 0)
            if len(ys) < 60:
                continue
            res = auc_compare(months, xa, xb, ys, reps=args.boot, rng=rng)
            auc_blocks[f"h{h}_{label}"] = res
            if label == "oos" and "p_two_sided" in res:
                pvals[f"h{h}"] = res["p_two_sided"]
            print(f"h={h:>2} {label:<15} n={res['n']:>4} поз={res['positives']:>3} "
                  f"AUC(10y-3m)={res.get('auc_a')} AUC(10y-2y)={res.get('auc_b')} "
                  f"Δ={res.get('delta')} 90%={res.get('delta_ci90')} "
                  f"-> {res.get('verdict', '')}")
    adj = holm(pvals) if pvals else {}
    if adj:
        print("\nпоправка Холма на объявленное семейство из 4 горизонтов:")
        for k in sorted(adj):
            print(f"  {k:<6} p={pvals[k]:<8} p_holm={adj[k]}")

    # ---------------- устойчивость ---------------------------------------- #
    print(f"\n{'=' * 78}\nУСТОЙЧИВОСТЬ\n{'=' * 78}")
    robust: dict[str, dict] = {}
    print("окно ожидания W (ряд 10y-3m, месяц<0, пик NBER):")
    for w in (12, 24, 36):
        sc = score(sig_main, peaks, w=w, t_start=t_start_main, t_end=t_end_usrec)
        robust[f"W{w}"] = {k: v for k, v in sc.items() if k != "episodes"}
        print(f"  W={w:>3}  TP={sc['TP']} FA={sc['FA']} FN={sc['FN']} "
              f"цен={sc['censored']} FA/TP={sc['fa_per_tp']} "
              f"лаг {sc['lag_min']}–{sc['lag_max']} (медиана {sc['lag_median']})")
    print("склейка эпизодов K:")
    for k in (0, 1, 3, 6):
        sig_k, _ = build_signals(main_mean, anyneg["10y-3m"], "month", k)
        sc = score(sig_k, peaks, w=W_MAIN, t_start=t_start_main, t_end=t_end_usrec)
        robust[f"K{k}"] = {k2: v for k2, v in sc.items() if k2 != "episodes"}
        print(f"  K={k:>2}  эпизодов={sc['n_signals']} TP={sc['TP']} FA={sc['FA']} "
              f"FN={sc['FN']} цен={sc['censored']} FA/TP={sc['fa_per_tp']}")
    print("разбиения выборки:")
    for name, lo_m, hi_m in (("1982-2001", "1982-01", "2001-12"),
                             ("2002-2026", "2002-01", None),
                             ("без 2020 года", None, None)):
        if name == "без 2020 года":
            pk = [p for p in peaks if p != mi("2020-02-01")]
            sig = sig_main
            sc = score(sig, pk, w=W_MAIN, t_start=t_start_main, t_end=t_end_usrec)
        else:
            lo_i = mi(lo_m + "-01")
            hi_i = mi(hi_m + "-01") if hi_m else t_end_usrec
            sig = [t for t in sig_main if lo_i <= t <= hi_i]
            pk = [p for p in peaks if lo_i <= p <= hi_i]
            sc = score(sig, pk, w=W_MAIN, t_start=lo_i, t_end=hi_i)
        robust[name] = {k2: v for k2, v in sc.items() if k2 != "episodes"}
        print(f"  {name:<14} эпизодов={sc['n_signals']} TP={sc['TP']} FA={sc['FA']} "
              f"FN={sc['FN']} цен={sc['censored']} FA/TP={sc['fa_per_tp']} "
              f"лаг {sc['lag_min']}–{sc['lag_max']}")

    # удлинённая выборка GS10 - TB3MS
    gs10 = month_level(gs10_s)
    tb3 = month_level(tb3ms_s)
    ext_raw = {t: gs10[t] - tb3[t] for t in gs10 if t in tb3}
    overlap = [main_mean[t] - ext_raw[t] for t in ext_raw if t in main_mean]
    offset = sum(overlap) / len(overlap) if overlap else 0.0
    ext_adj = {t: v + offset for t, v in ext_raw.items()}
    print(f"\nудлинённая выборка GS10-TB3MS (дисконтная база): смещение против "
          f"T10Y3M на перекрытии = {offset:+.3f} п.п. по {len(overlap)} месяцам")
    ext_results = {}
    for tag, series_ in (("сырая", ext_raw), ("со снятым смещением", ext_adj)):
        for frm, flabel in ((1970, "с 1970"), (1953, "вся история")):
            sub = {t: v for t, v in series_.items() if t >= mi(f"{frm}-01-01")}
            sig, _ = build_signals(sub, {}, "month", K_MAIN)
            sc = score(sig, peaks, w=W_MAIN, t_start=min(sub), t_end=t_end_usrec)
            ext_results[f"{tag}|{flabel}"] = {k2: v for k2, v in sc.items()
                                              if k2 != "episodes"}
            print(f"  {tag:<20} {flabel:<12} эпизодов={sc['n_signals']} "
                  f"TP={sc['TP']} FA={sc['FA']} FN={sc['FN']} "
                  f"FA/TP={sc['fa_per_tp']} лаг {sc['lag_min']}–{sc['lag_max']} "
                  f"(медиана {sc['lag_median']})")

    # ---------------- реал-тайм -------------------------------------------- #
    print(f"\n{'=' * 78}\nРЕАЛ-ТАЙМ-РАЗМЕТКА\n{'=' * 78}")
    ann_peaks = {d: nber["peaks"].meta["announced"][d]
                 for d, _ in nber["peaks"].observed}
    lags_ann = [int(v) for _, v in nber["peaks"].observed]
    print("1. Лаг объявления пика Комитетом NBER:")
    for d, v in nber["peaks"].observed:
        print(f"   пик {d[:7]}  объявлен {ann_peaks[d]}  лаг {int(v):>2} мес.")
    l_max = max(lags_ann)
    print(f"   медиана {sorted(lags_ann)[len(lags_ann) // 2]} мес., "
          f"размах {min(lags_ann)}–{l_max} мес.")
    print("   объявлений до 1980 года не существует — Комитет начал публиковать "
          "их в 1979 г.; для 1973 и ранее реал-тайм-разметки нет")

    print(f"\n2. Когда вердикт по эпизоду становится известен "
          f"(для ложной тревоги — конец окна плюс максимальный лаг объявления "
          f"{l_max} мес.):")
    rt_verdicts = []
    for d in main_score["episodes"]:
        t0 = mi(d["signal"] + "-01")
        if d["outcome"] == "TP":
            known = ann_peaks.get(d["peak"] + "-01")
            wait = (None if known is None else
                    (int(known[:4]) - t0 // 12) * 12 + int(known[5:7]) - 1 - t0 % 12)
            note = f"объявление пика {known}" if known else "объявления нет (до 1980)"
        else:
            km = t0 + W_MAIN + l_max
            known, wait = mi_str(km), W_MAIN + l_max
            note = f"конец окна {mi_str(t0 + W_MAIN)} + {l_max} мес. на объявление"
        rt_verdicts.append({"signal": d["signal"], "outcome": d["outcome"],
                            "known_at": known, "months_waiting": wait, "note": note})
        print(f"   сигнал {d['signal']}  {d['outcome']:<10} вердикт известен "
              f"{str(known):<12} через {str(wait):>4} мес.  ({note})")

    print("\n3. Реал-тайм-событие «два квартала спада по первой публикации» "
          "(винтажи ROUTPUT ФРБ Филадельфии):")
    sheet = rtds.get("ROUTPUT") or next(iter(rtds.values()))
    rt_events, rt_warn = realtime_two_quarter(sheet)
    for w in rt_warn:
        print(f"   ВНИМАНИЕ: {w}")
    for e in rt_events:
        print(f"   спад с {e['event_month']}  впервые виден в винтаже "
              f"{e['first_vintage']} ({e['recognised_month']}), "
              f"распознан через {e['recognition_lag_months']} мес.")
    rt_months = [e["_event_mi"] for e in rt_events]
    sc_rt = score(sig_main, rt_months, w=W_MAIN, t_start=t_start_main,
                  t_end=max(rt_months) if rt_months else t_end_usrec)
    print(f"\n4. Пересчёт на реал-тайм-событии: TP={sc_rt['TP']} FA={sc_rt['FA']} "
          f"FN={sc_rt['FN']} цен={sc_rt['censored']} FA/TP={sc_rt['fa_per_tp']} "
          f"лаг {sc_rt['lag_min']}–{sc_rt['lag_max']} (медиана {sc_rt['lag_median']})")
    u1_rt = sc_rt["FN"] <= 1
    u2_rt = sc_rt["fa_per_tp"] is not None and sc_rt["fa_per_tp"] <= 0.5
    print(f"   U1={'выполнено' if u1_rt else 'НЕ выполнено'}  "
          f"U2={'выполнено' if u2_rt else 'НЕ выполнено'}")

    # ---------------- вердикт ---------------------------------------------- #
    if u1 and u2 and both_ok >= 18:
        verdict = "ПОДТВЕРЖДЕНО"
    elif (not (u1 and u2)) and both_ok < 12:
        verdict = "ОПРОВЕРГНУТО"
    else:
        verdict = "НЕОПРЕДЕЛЕНО"
    print(f"\n{'=' * 78}\nВЕРДИКТ Z03: {verdict}\n"
          f"  U1 (пропусков <= 1) = {u1}; U2 (FA/TP <= 0.5) = {u2}; "
          f"ячеек сетки с обоими условиями = {both_ok}/24\n{'=' * 78}")

    out = {
        "task": "Z03",
        "verdict": verdict,
        "params": {"seed": SEED, "K_main": K_MAIN, "W_main": W_MAIN,
                   "H_main": H_MAIN, "boot_reps": args.boot,
                   "block_months": BLOCK_MONTHS, "oos_from": OOS_FROM},
        "manifest": {
            "fetched_at": t10y3m.fetched_at,
            "series": {
                s.series_id: {"n": len(s.observed), "first": s.observed[0][0],
                              "last": s.observed[-1][0], "source": s.source,
                              "observation_start": (s.meta or {}).get("observation_start")}
                for s in (t10y3m, t10y2y, usrec_s, usrecm_s, gs10_s, tb3ms_s, gdp_s)
            },
            "nber_announcements": {"url": nber["peaks"].meta["url"],
                                   "peaks": nber["peaks"].meta["announced"],
                                   "troughs": nber["troughs"].meta["announced"]},
            "warnings": warnings,
        },
        "peaks_nber": [mi_str(p) for p in peaks],
        "events_two_quarter": [mi_str(p) for p in ev2q],
        "main": {"config": {"spread": "10y-3m", "trigger": "month<0",
                            "window": W_MAIN, "event": "nber", "K": K_MAIN},
                 "score": main_score, "bootstrap_lag": boot_lag,
                 "U1": u1, "U2": u2},
        "grid24": grid,
        "grid24_both_ok": both_ok,
        "episode_2022": {"rows": ep2022, "tally": tally},
        "auc": auc_blocks,
        "auc_pvalues_raw": pvals,
        "auc_pvalues_holm": adj,
        "robustness": robust,
        "extended_sample": {"offset_pp": round(offset, 4),
                            "overlap_months": len(overlap),
                            "results": ext_results},
        "realtime": {
            "announcement_lag_months": {d[:7]: int(v) for d, v in nber["peaks"].observed},
            "announcement_lag_median": sorted(lags_ann)[len(lags_ann) // 2],
            "announcement_lag_max": l_max,
            "verdict_known_at": rt_verdicts,
            "two_quarter_realtime_events": rt_events,
            "score_on_realtime_event": {k: v for k, v in sc_rt.items()
                                        if k != "episodes"},
            "U1": u1_rt, "U2": u2_rt,
        },
    }
    path = os.path.join(HERE, "result.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nЗаписано: {path}")
    fig = episodes_svg(fig_rows, os.path.join(HERE, "episodes.svg"), w=W_MAIN)
    print(f"Записано: {fig}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
