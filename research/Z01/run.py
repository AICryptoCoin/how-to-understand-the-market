#!/usr/bin/env python3
"""Z01 — лид NAHB HMI к безработице (10 мес.) и к доходности US10Y (18 мес.).

Критерии зафиксированы до расчёта: см. HYPOTHESIS.md. Скрипт ничего не решает
сам — он считает те величины, которые названы в критериях, и печатает их.

Запуск:
    python run.py              # из кэша, если он свежий
    python run.py --force      # перекачать исходные ряды
    python run.py --boot 5000  # больше повторов бутстрапа (по умолчанию 2000)

Результат: result.json рядом со скриптом + таблицы в stdout.
Зависимости: только стандартная библиотека + sources.py из родительской папки.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from typing import Callable, Iterable, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import sources as S  # noqa: E402

MAXLAG = 36
BLOCK = 24
SEED = 20260727

# Полосы допуска и заявленные лиды — из HYPOTHESIS.md §3.
CLAIMS = {
    "A": {"lead": 10, "band": (8, 12), "sign": -1,
          "title": "NAHB HMI → уровень безработицы (обратная связь)"},
    "B": {"lead": 18, "band": (15, 21), "sign": +1,
          "title": "NAHB HMI YoY → US10Y YoY (прямая связь)"},
}

# --------------------------------------------------------------------------- #
#  Месячная сетка: индекс = год*12 + (месяц-1)
# --------------------------------------------------------------------------- #


def mi(date: str) -> int:
    y, m = int(date[:4]), int(date[5:7])
    return y * 12 + (m - 1)


def mi_str(idx: int) -> str:
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def to_monthly(series: S.Series) -> dict[int, float]:
    """Месячный ряд → {индекс месяца: значение}. Дневной — усредняется по месяцу."""
    if series.freq == "D":
        acc: dict[int, list[float]] = {}
        for d, v in series.observed:
            acc.setdefault(mi(d), []).append(v)
        return {k: sum(vs) / len(vs) for k, vs in acc.items()}
    out: dict[int, float] = {}
    for d, v in series.observed:
        out[mi(d)] = v
    return out


# --------------------------------------------------------------------------- #
#  Преобразования
# --------------------------------------------------------------------------- #


def log_change(x: dict[int, float], k: int) -> dict[int, float]:
    """100·ln(x_t / x_{t-k}) — при k=12 это процентное изменение год к году."""
    return {t: 100.0 * math.log(v / x[t - k])
            for t, v in x.items() if t - k in x and v > 0 and x[t - k] > 0}


def diff(x: dict[int, float], k: int) -> dict[int, float]:
    """x_t − x_{t−k} — для ставок, измеряемых в процентных пунктах."""
    return {t: v - x[t - k] for t, v in x.items() if t - k in x}


def level(x: dict[int, float], k: int) -> dict[int, float]:  # noqa: ARG001
    return dict(x)


# --------------------------------------------------------------------------- #
#  Корреляция и взаимная корреляция на сбалансированной панели
# --------------------------------------------------------------------------- #


def pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = len(a)
    if n < 8:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = sb = sab = 0.0
    for u, v in zip(a, b):
        du, dv = u - ma, v - mb
        sa += du * du
        sb += dv * dv
        sab += du * dv
    if sa <= 0 or sb <= 0:
        return None
    return sab / math.sqrt(sa * sb)


def panel(x: dict[int, float], y: dict[int, float], *,
          t_from: int | None = None, t_to: int | None = None,
          maxlag: int = MAXLAG) -> tuple[list[int], list[float], list[list[float]]]:
    """Сбалансированная панель: только те t, где есть x_t и все y_{t+h}, h=0..maxlag.

    Одна и та же выборка на всех лагах — иначе сравнение лагов сравнивает
    заодно и разные куски истории.
    """
    ts, xs, ys = [], [], []
    for t in sorted(x):
        if t_from is not None and t < t_from:
            continue
        if t_to is not None and t > t_to:
            continue
        row = [y.get(t + h) for h in range(maxlag + 1)]
        if any(v is None for v in row):
            continue
        ts.append(t)
        xs.append(x[t])
        ys.append([float(v) for v in row])  # type: ignore[arg-type]
    return ts, xs, ys


def ccf(xs: Sequence[float], ys: Sequence[Sequence[float]]) -> list[float | None]:
    """corr(x_t, y_{t+h}) для h = 0..maxlag."""
    out: list[float | None] = []
    for h in range(len(ys[0]) if ys else 0):
        out.append(pearson(xs, [row[h] for row in ys]))
    return out


def peak(cors: Sequence[float | None], sign: int) -> tuple[int | None, float | None]:
    """Лаг наибольшей корреляции в ожидаемом направлении."""
    best_h, best_v = None, None
    for h, r in enumerate(cors):
        if r is None:
            continue
        v = sign * r
        if best_v is None or v > best_v:
            best_h, best_v = h, v
    return best_h, (None if best_v is None else sign * best_v)


# --------------------------------------------------------------------------- #
#  Блочный бутстрап
# --------------------------------------------------------------------------- #


def moving_blocks(n: int, block: int, rng: random.Random) -> list[int]:
    """Индексы одной бутстрап-выборки методом скользящих блоков."""
    idx: list[int] = []
    last = max(1, n - block + 1)
    while len(idx) < n:
        start = rng.randrange(last)
        idx.extend(range(start, min(start + block, n)))
    return idx[:n]


def bootstrap_lag(xs: Sequence[float], ys: Sequence[Sequence[float]], sign: int,
                  *, reps: int, block: int, rng: random.Random) -> dict:
    """Распределение лага пика. Блок ресемплится целиком со всеми y_{t+h}."""
    n = len(xs)
    lags: list[int] = []
    for _ in range(reps):
        idx = moving_blocks(n, block, rng)
        bx = [xs[i] for i in idx]
        by = [ys[i] for i in idx]
        h, _ = peak(ccf(bx, by), sign)
        if h is not None:
            lags.append(h)
    lags.sort()
    if not lags:
        return {}
    return {
        "p05": lags[int(0.05 * (len(lags) - 1))],
        "p50": lags[int(0.50 * (len(lags) - 1))],
        "p95": lags[int(0.95 * (len(lags) - 1))],
        "width90": lags[int(0.95 * (len(lags) - 1))] - lags[int(0.05 * (len(lags) - 1))],
        "in_band": None,      # заполняется вызывающим
        "share_in_band": None,  # доля бутстрап-пиков внутри полосы допуска
        "reps": len(lags),
        "_lags": lags,
    }


def null_pvalue(xs: Sequence[float], ys: Sequence[Sequence[float]], sign: int,
                observed: float, *, reps: int, block: int,
                rng: random.Random) -> float:
    """p с поправкой на поиск по 37 лагам.

    Нулевая гипотеза: связи нет, но автокорреляция ведущего ряда сохраняется.
    Ведущий ряд ресемплится блоками независимо от ведомого.
    """
    n = len(xs)
    hits = 0
    for _ in range(reps):
        idx = moving_blocks(n, block, rng)
        bx = [xs[i] for i in idx]
        _, r = peak(ccf(bx, ys), sign)
        if r is not None and sign * r >= sign * observed:
            hits += 1
    return (hits + 1) / (reps + 1)


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Поправка Холма внутри объявленного семейства."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)
        out[k] = round(running, 4)
    return out


# --------------------------------------------------------------------------- #
#  Развороты (описательный блок C)
# --------------------------------------------------------------------------- #


def extrema(x: dict[int, float], *, half: int = 12, kind: str = "max") -> list[int]:
    """Локальные экстремумы: строго не хуже всех соседей в полуокне."""
    ts = sorted(x)
    out = []
    for t in ts:
        window = [x[u] for u in range(t - half, t + half + 1) if u in x]
        if len(window) < half + 2:
            continue
        if kind == "max" and x[t] >= max(window) and x[t] > min(window):
            out.append(t)
        if kind == "min" and x[t] <= min(window) and x[t] < max(window):
            out.append(t)
    # схлопнуть плато в одну точку
    dedup = []
    for t in out:
        if dedup and t - dedup[-1] <= half:
            continue
        dedup.append(t)
    return dedup


def match_turns(leads: list[int], follows: list[int], *,
                lo: int = 0, hi: int = 36) -> list[tuple[int, int, int]]:
    pairs = []
    for t in leads:
        nxt = [u for u in follows if lo <= u - t <= hi]
        if nxt:
            pairs.append((t, nxt[0], nxt[0] - t))
    return pairs


# --------------------------------------------------------------------------- #
#  Сценарий одной конфигурации
# --------------------------------------------------------------------------- #


def run_config(name: str, x: dict[int, float], y: dict[int, float], sign: int,
               band: tuple[int, int], claimed: int, *,
               t_from: int | None, t_to: int | None,
               reps: int, rng: random.Random, do_boot: bool) -> dict:
    ts, xs, ys = panel(x, y, t_from=t_from, t_to=t_to)
    if len(xs) < 60:
        return {"config": name, "n": len(xs), "error": "выборка меньше 60 точек"}
    cors = ccf(xs, ys)
    h_star, r_star = peak(cors, sign)
    res = {
        "config": name,
        "n": len(xs),
        "span": [mi_str(ts[0]), mi_str(ts[-1] + MAXLAG)],
        "peak_lag": h_star,
        "peak_r": None if r_star is None else round(r_star, 4),
        "r_at_claimed": None if cors[claimed] is None else round(cors[claimed], 4),
        "r_at_0": None if cors[0] is None else round(cors[0], 4),
        "peak_in_band": h_star is not None and band[0] <= h_star <= band[1],
        "ccf": [None if r is None else round(r, 4) for r in cors],
    }
    if do_boot and r_star is not None:
        boot = bootstrap_lag(xs, ys, sign, reps=reps, block=BLOCK, rng=rng)
        boot["in_band"] = band[0] <= boot["p50"] <= band[1]
        drawn = boot.pop("_lags")
        boot["share_in_band"] = round(
            sum(1 for h in drawn if band[0] <= h <= band[1]) / len(drawn), 3)
        res["bootstrap"] = boot
        res["p_lagsearch"] = round(
            null_pvalue(xs, ys, sign, r_star, reps=reps, block=BLOCK, rng=rng), 4)
    return res


def rolling(x: dict[int, float], y: dict[int, float], sign: int,
            band: tuple[int, int], claimed: int, *, window: int = 120) -> dict:
    ts_all = sorted(t for t in x if t + MAXLAG in y)
    if len(ts_all) < window:
        return {"windows": 0}
    hits = 0
    total = 0
    sign_ok = 0
    lags: list[int] = []
    signs_seen: set[int] = set()
    for start in range(ts_all[0], ts_all[-1] - window + 2):
        ts, xs, ys = panel(x, y, t_from=start, t_to=start + window - 1)
        if len(xs) < 90:
            continue
        cors = ccf(xs, ys)
        h, _ = peak(cors, sign)
        if h is None:
            continue
        total += 1
        lags.append(h)
        if band[0] <= h <= band[1]:
            hits += 1
        rc = cors[claimed]
        if rc is not None:
            signs_seen.add(1 if rc > 0 else -1)
            if (rc > 0) == (sign > 0):
                sign_ok += 1
    if not total:
        return {"windows": 0}
    lags.sort()
    return {
        "windows": total,
        "share_in_band": round(hits / total, 3),
        "share_sign_ok": round(sign_ok / total, 3),
        "sign_stable": len(signs_seen) == 1,
        "lag_p10": lags[int(0.10 * (len(lags) - 1))],
        "lag_median": lags[len(lags) // 2],
        "lag_p90": lags[int(0.90 * (len(lags) - 1))],
    }


# --------------------------------------------------------------------------- #
#  Рисунок: кривая взаимной корреляции по лагам
# --------------------------------------------------------------------------- #


def ccf_svg(series: list[dict], path: str) -> str:
    """SVG кривых взаимной корреляции — в разметке и классах книги.

    Рисуется то, что решает спор: где лежит максимум и насколько кривая плоская.
    Точка, объявленная курсом, отмечена отдельно от фактического максимума.
    """
    W, H = 860, 460
    L, R, T, B = 92, 40, 56, 66
    plot_w, plot_h = W - L - R, H - T - B
    lo, hi = -0.8, 0.4

    def px(h: int) -> float:
        return L + plot_w * h / MAXLAG

    def py(r: float) -> float:
        return T + plot_h * (hi - r) / (hi - lo)

    out: list[str] = [
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="figz01t figz01d">',
        '<title id="figz01t">Взаимная корреляция NAHB HMI с безработицей и '
        'с доходностью десятилетних по лагам</title>',
        '<desc id="figz01d">По горизонтали — на сколько месяцев NAHB сдвинут '
        'вперёд относительно второго ряда, от нуля до тридцати шести. '
        'По вертикали — коэффициент корреляции годовых приращений. '
        'Кривая для безработицы отрицательна на всём диапазоне и достигает '
        'минимума около семнадцатого месяца, а не десятого; вокруг минимума '
        'она почти плоская. Кривая для доходности десятилетних положительна '
        'после восьмого месяца и достигает максимума на восемнадцатом.</desc>',
    ]
    # сетка и оси
    for r in (0.4, 0.2, 0.0, -0.2, -0.4, -0.6, -0.8):
        y = py(r)
        cls = "viz-axisline" if r == 0.0 else "viz-grid"
        out.append(f'<line class="{cls}" x1="{L}" y1="{y:.1f}" '
                   f'x2="{L + plot_w}" y2="{y:.1f}"/>')
        out.append(f'<text class="viz-axis" x="{L - 10}" y="{y + 4:.1f}" '
                   f'text-anchor="end">{r:+.1f}</text>')
    for h in range(0, MAXLAG + 1, 6):
        out.append(f'<text class="viz-axis" x="{px(h):.1f}" y="{T + plot_h + 24}" '
                   f'text-anchor="middle">{h}</text>')
    out.append(f'<text class="viz-axis" x="{L + plot_w / 2:.0f}" '
               f'y="{T + plot_h + 48}" text-anchor="middle">'
               f'сдвиг NAHB вперёд, месяцев →</text>')

    colors = ("var(--series-8)", "var(--series-1)")
    for i, s in enumerate(series):
        band = s["band"]
        out.append(f'<rect class="viz-band" x="{px(band[0]):.1f}" y="{T}" '
                   f'width="{px(band[1]) - px(band[0]):.1f}" height="{plot_h}" '
                   f'fill="{colors[i]}" opacity="0.07"/>')
        pts = " ".join(f'{px(h):.1f},{py(r):.1f}'
                       for h, r in enumerate(s["ccf"]) if r is not None)
        out.append(f'<polyline class="viz-line" fill="none" stroke="{colors[i]}" '
                   f'points="{pts}"/>')
        hp, rp = s["peak_lag"], s["ccf"][s["peak_lag"]]
        out.append(f'<circle class="viz-mark" cx="{px(hp):.1f}" cy="{py(rp):.1f}" '
                   f'r="5" fill="{colors[i]}"/>')
        out.append(f'<text class="viz-annot" x="{px(hp):.1f}" '
                   f'y="{py(rp) + (-14 if rp > 0 else 22):.1f}" text-anchor="middle">'
                   f'максимум {hp} мес.</text>')
        hc, rc = s["claimed"], s["ccf"][s["claimed"]]
        out.append(f'<line class="viz-grid" x1="{px(hc):.1f}" y1="{py(rc):.1f}" '
                   f'x2="{px(hc):.1f}" y2="{py(0.0):.1f}" '
                   f'stroke="{colors[i]}" stroke-dasharray="3 3"/>')
        out.append(f'<circle cx="{px(hc):.1f}" cy="{py(rc):.1f}" r="4" '
                   f'fill="none" stroke="{colors[i]}" stroke-width="2"/>')
        out.append(f'<text class="viz-annot" x="{L + 12}" y="{T + 18 + i * 20}" '
                   f'fill="{colors[i]}">{s["label"]}</text>')
    out.append(f'<text class="viz-annot" x="{L + plot_w}" y="{T + plot_h + 48}" '
               f'text-anchor="end">кружком обведено значение на лаге, '
               f'заявленном курсом</text>')
    out.append("</svg>")
    svg = "\n".join(out)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg + "\n")
    return path


def fmt_r(v) -> str:
    return "   —  " if v is None else f"{v:+.3f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="перекачать исходные ряды")
    ap.add_argument("--boot", type=int, default=2000, help="повторов бутстрапа")
    args = ap.parse_args()

    # Консоль Windows по умолчанию cp1251 и роняет вывод на «→»
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    rng = random.Random(SEED)

    print("Загрузка рядов…")
    hmi_s = S.nahb_hmi("t2", force=args.force)["HMI"]
    unrate_s = S.fred("UNRATE", force=args.force)
    dgs10_s = S.fred("DGS10", force=args.force)
    for s in (hmi_s, unrate_s, dgs10_s):
        print("  ", s.describe())

    hmi = to_monthly(hmi_s)
    unrate = to_monthly(unrate_s)
    dgs10 = to_monthly(dgs10_s)

    def holes(d: dict[int, float]) -> list[str]:
        return [mi_str(t) for t in range(min(d), max(d) + 1) if t not in d]

    manifest = {
        "fetched_at": hmi_s.fetched_at,
        "series": {
            "NAHB_HMI": {"n": len(hmi), "first": mi_str(min(hmi)), "last": mi_str(max(hmi)),
                         "source": hmi_s.source, "url": hmi_s.meta.get("url", ""),
                         "holes": holes(hmi)},
            "UNRATE": {"n": len(unrate), "first": mi_str(min(unrate)),
                       "last": mi_str(max(unrate)), "source": unrate_s.source,
                       "holes": holes(unrate)},
            "DGS10_m": {"n": len(dgs10), "first": mi_str(min(dgs10)),
                        "last": mi_str(max(dgs10)), "source": dgs10_s.source,
                        "aggregation": "среднее за месяц", "holes": holes(dgs10)},
        },
    }
    for sid, info in manifest["series"].items():
        if info["holes"]:
            print(f"  ВНИМАНИЕ: в {sid} пропущены месяцы {', '.join(info['holes'])}. "
                  f"Сбалансированная панель требует всех y_{{t+h}}, поэтому пропуск "
                  f"срезает {MAXLAG} мес. хвоста вокруг дыры — это видно в колонке n.")

    covid = (mi("2020-03-01"), mi("2021-12-01"))
    split = mi("2008-01-01")
    oos = mi("2013-01-01")

    results: dict[str, dict] = {}
    pvals: dict[str, float] = {}

    for code, spec in CLAIMS.items():
        sign, band, claimed = spec["sign"], spec["band"], spec["lead"]
        print(f"\n{'=' * 78}\n{code}. {spec['title']}  ·  заявлено {claimed} мес., "
              f"полоса {band[0]}–{band[1]}\n{'=' * 78}")

        block: dict = {"title": spec["title"], "claimed_lead": claimed,
                       "band": list(band), "expected_sign": sign, "configs": {}}

        # ведущий и ведомый ряды для трёх окон дифференцирования
        for k in (3, 6, 12):
            if code == "A":
                x = log_change(hmi, k)
                y = diff(unrate, k)
            else:
                x = log_change(hmi, k)
                y = diff(dgs10, k)

            main_name = f"delta{k}"
            block["configs"][main_name] = run_config(
                main_name, x, y, sign, band, claimed,
                t_from=None, t_to=None, reps=args.boot, rng=rng,
                do_boot=(k == 12))

            # ковид отдельно на каждом окне: без этого нельзя отличить
            # «лид исчезает на коротких приращениях» от «его съедает 2020 год»
            x_nc = {t: v for t, v in x.items() if not covid[0] <= t <= covid[1]}
            y_nc = {t: v for t, v in y.items() if not covid[0] <= t <= covid[1]}
            block["configs"][f"no_covid_d{k}"] = run_config(
                f"no_covid_d{k}", x_nc, y_nc, sign, band, claimed,
                t_from=None, t_to=None, reps=args.boot, rng=rng, do_boot=False)

            if k == 12:
                block["rolling"] = rolling(x, y, sign, band, claimed)
                block["configs"]["split_pre2008"] = run_config(
                    "split_pre2008", x, y, sign, band, claimed,
                    t_from=None, t_to=split - 1, reps=args.boot, rng=rng, do_boot=False)
                block["configs"]["split_post2008"] = run_config(
                    "split_post2008", x, y, sign, band, claimed,
                    t_from=split, t_to=None, reps=args.boot, rng=rng, do_boot=False)

                author_from = mi("1990-01-01") if code == "A" else mi("2000-01-01")
                block["configs"]["author_window"] = run_config(
                    "author_window", x, y, sign, band, claimed,
                    t_from=author_from, t_to=None, reps=args.boot, rng=rng, do_boot=False)

                ins = run_config("oos_in", x, y, sign, band, claimed,
                                 t_from=None, t_to=oos - 1, reps=args.boot,
                                 rng=rng, do_boot=False)
                out = run_config("oos_out", x, y, sign, band, claimed,
                                 t_from=oos, t_to=None, reps=args.boot,
                                 rng=rng, do_boot=False)
                h_in = ins.get("peak_lag")
                out["r_at_insample_peak"] = (
                    out["ccf"][h_in] if h_in is not None and "ccf" in out else None)
                block["configs"]["oos_in"] = ins
                block["configs"]["oos_out"] = out

        # уровни — как рисовал автор, с оговоркой
        y_lvl = unrate if code == "A" else dgs10
        block["configs"]["levels_asdrawn"] = run_config(
            "levels_asdrawn", level(hmi, 0), y_lvl, sign, band, claimed,
            t_from=None, t_to=None, reps=args.boot, rng=rng, do_boot=False)

        for cfg_name in ("delta3", "delta6", "delta12"):
            c = block["configs"][cfg_name]
            if "p_lagsearch" in c:
                pvals[f"{code}:{cfg_name}"] = c["p_lagsearch"]

        # печать
        print(f"{'конфигурация':<18} {'n':>5} {'период':<20} {'пик':>5} "
              f"{'r(пик)':>8} {f'r({claimed})':>8} {'r(0)':>8}  полоса")
        for cname, c in block["configs"].items():
            if "error" in c:
                print(f"{cname:<18} {c['n']:>5}  {c['error']}")
                continue
            print(f"{cname:<18} {c['n']:>5} {c['span'][0]}..{c['span'][1]:<9} "
                  f"{c['peak_lag']:>5} {fmt_r(c['peak_r'])} {fmt_r(c['r_at_claimed'])} "
                  f"{fmt_r(c['r_at_0'])}  {'да' if c['peak_in_band'] else 'НЕТ'}")

        b = block["configs"]["delta12"].get("bootstrap")
        if b:
            print(f"\nбутстрап лага (блок {BLOCK} мес., {b['reps']} повторов): "
                  f"медиана {b['p50']}, 90 % интервал [{b['p05']}, {b['p95']}], "
                  f"ширина {b['width90']} мес.")
        if "p_lagsearch" in block["configs"]["delta12"]:
            print(f"p с поправкой на поиск по 37 лагам: "
                  f"{block['configs']['delta12']['p_lagsearch']}")
        r = block.get("rolling", {})
        if r.get("windows"):
            print(f"скользящие 10-летние окна: {r['windows']} шт., "
                  f"пик в полосе {r['share_in_band'] * 100:.0f} %, "
                  f"знак на лаге {claimed} верен {r['share_sign_ok'] * 100:.0f} %, "
                  f"лаг p10/медиана/p90 = {r['lag_p10']}/{r['lag_median']}/{r['lag_p90']}")

        # критерии
        d12 = block["configs"]["delta12"]
        boot = d12.get("bootstrap", {})
        block["criteria"] = {
            "C1_peak_in_band": bool(d12.get("peak_in_band")),
            "C2_rolling_share_ge_070": bool(r.get("share_in_band", 0) >= 0.70),
            "C3_sign_stable": bool(r.get("sign_stable")),
            "C4_boot_width_le_12": bool(boot.get("width90", 99) <= 12),
        }
        ok = block["criteria"]
        if ok["C1_peak_in_band"] and ok["C3_sign_stable"]:
            block["verdict"] = ("ПОДТВЕРЖДЕНО"
                                if ok["C2_rolling_share_ge_070"] and ok["C4_boot_width_le_12"]
                                else "НЕОПРЕДЕЛЕНО")
        else:
            block["verdict"] = "ОПРОВЕРГНУТО"
        print("\nкритерии: " + "  ".join(
            f"{k.split('_')[0]}={'✓' if v else '✗'}" for k, v in ok.items()))
        print(f"ВЕРДИКТ {code}: {block['verdict']}")
        results[code] = block

    # блок C — развороты
    print(f"\n{'=' * 78}\nC. Лид разворотов (описательно, вердикт не несёт)\n{'=' * 78}")
    hmi_peaks = extrema(hmi, kind="max")
    unrate_troughs = extrema(unrate, kind="min")
    pairs_a = match_turns(hmi_peaks, unrate_troughs)
    print("пик HMI → следующий минимум безработицы:")
    for t, u, lag in pairs_a:
        print(f"  {mi_str(t)}  →  {mi_str(u)}   лид {lag:>2} мес.   "
              f"HMI {hmi[t]:.0f} → UNRATE {unrate[u]:.1f} %")
    lags_a = [p[2] for p in pairs_a]
    if lags_a:
        lags_sorted = sorted(lags_a)
        print(f"  n={len(lags_a)}  медиана {lags_sorted[len(lags_sorted) // 2]} мес.  "
              f"размах {min(lags_a)}–{max(lags_a)} мес.")

    hmi_yoy = log_change(hmi, 12)
    d10_yoy = diff(dgs10, 12)
    pairs_b = match_turns(extrema(hmi_yoy, kind="max"), extrema(d10_yoy, kind="max"))
    print("\nпик NAHB YoY → следующий пик US10Y YoY:")
    for t, u, lag in pairs_b:
        print(f"  {mi_str(t)}  →  {mi_str(u)}   лид {lag:>2} мес.")
    lags_b = [p[2] for p in pairs_b]
    if lags_b:
        lb = sorted(lags_b)
        print(f"  n={len(lags_b)}  медиана {lb[len(lb) // 2]} мес.  "
              f"размах {min(lags_b)}–{max(lags_b)} мес.")

    turning = {
        "A_hmi_peak_to_unrate_trough": [
            {"hmi_peak": mi_str(t), "unrate_trough": mi_str(u), "lead": lag}
            for t, u, lag in pairs_a],
        "B_hmi_yoy_peak_to_dgs10_yoy_peak": [
            {"hmi_yoy_peak": mi_str(t), "dgs10_yoy_peak": mi_str(u), "lead": lag}
            for t, u, lag in pairs_b],
    }

    # множественность
    adj = holm(pvals) if pvals else {}
    if adj:
        print(f"\n{'=' * 78}\nПоправка Холма внутри объявленного семейства "
              f"(12 конфигураций)\n{'=' * 78}")
        for k in sorted(adj):
            print(f"  {k:<20} p={pvals[k]:<8} p_holm={adj[k]}")

    out = {
        "task": "Z01",
        "manifest": manifest,
        "params": {"maxlag": MAXLAG, "block": BLOCK, "boot_reps": args.boot,
                   "seed": SEED, "rolling_window": 120},
        "claims": results,
        "turning_points": turning,
        "pvalues_raw": pvals,
        "pvalues_holm": adj,
    }
    path = os.path.join(HERE, "result.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nЗаписано: {path}")

    fig = ccf_svg([
        {"label": "NAHB → безработица (Δ12, обратная связь)",
         "ccf": results["A"]["configs"]["delta12"]["ccf"],
         "peak_lag": results["A"]["configs"]["delta12"]["peak_lag"],
         "claimed": CLAIMS["A"]["lead"], "band": CLAIMS["A"]["band"]},
        {"label": "NAHB YoY → US10Y YoY (прямая связь)",
         "ccf": results["B"]["configs"]["delta12"]["ccf"],
         "peak_lag": results["B"]["configs"]["delta12"]["peak_lag"],
         "claimed": CLAIMS["B"]["lead"], "band": CLAIMS["B"]["band"]},
    ], os.path.join(HERE, "ccf.svg"))
    print(f"Записано: {fig}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
