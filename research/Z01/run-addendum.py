#!/usr/bin/env python3
"""Z01 · дополнение — три вопроса, оставшихся открытыми после основного прогона.

Критерии зафиксированы до расчёта: см. HYPOTHESIS-ADDENDUM.md. Скрипт ничего
не решает сам — он считает названные там величины и печатает их.

  Д1  поздняя половина 2008–2026 без ковидных лет: пик остаётся на 9 или
      уезжает к 19 (критерий взят из самой главы «Структурные разрывы»)
  Д2  окно поиска сдвига 0–48 вместо 0–36: локализован ли лид вообще,
      и что происходит с p после пересчёта поправки на новое семейство
  Д3  независимость пар в блоке разворотов: две пары указывают на один
      и тот же минимум безработицы или нет

`run.py` не изменяется и не импортирует этот файл. Здесь он импортируется как
модуль ради его же функций — поток случайных чисел основного скрипта не
затрагивается: каждая конфигурация получает собственный детерминированный
поток random.Random(f"{SEED}:{имя}").

Запуск:
    python run-addendum.py            # 2000 повторов бутстрапа, как в основном
    python run-addendum.py --boot 500 # быстрее, для отладки
    python run-addendum.py --force    # перекачать ряды (по умолчанию из кэша)

Результат: result-addendum.json рядом со скриптом + таблицы в stdout.
Зависимости: только стандартная библиотека, sources.py и run.py.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from typing import Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run as R  # noqa: E402  — основной скрипт задачи, используется как библиотека

SEED = R.SEED
BLOCK = R.BLOCK
ALPHA = 0.05                 # порог значимости, объявлен в §2.4 дополнения
FAMILY_DECLARED = 16         # 12 конфигураций HYPOTHESIS §5 + 4 конфигурации дополнения

# Полосы допуска Д1 (§1.3 дополнения) — «окрестность девяти» и «окрестность
# девятнадцати» из блока «как это проверить» главы, доведённые до чисел.
NEAR_NINE = (7, 11)
NEAR_NINETEEN = (17, 21)
S2_HALF = 0.165              # половина наблюдённого r(0) = −0,330

# Полоса допуска Д2 (§2.3): запас от новой границы окна поиска.
MAXLAG_WIDE = 48
LOCALIZED_MAX = 44


def stream(name: str) -> random.Random:
    """Собственный детерминированный поток на конфигурацию.

    Так порядок конфигураций в скрипте не влияет на числа: добавление новой
    строки не сдвигает бутстрапы соседей, как это было бы с общим потоком.
    """
    return random.Random(f"{SEED}:{name}")


# --------------------------------------------------------------------------- #
#  Расчёт конфигурации с произвольным окном поиска лага
# --------------------------------------------------------------------------- #


def run_config_ml(name: str, x: dict[int, float], y: dict[int, float], sign: int,
                  band: tuple[int, int], claimed: int, *,
                  t_from: int | None, t_to: int | None, maxlag: int,
                  reps: int, rng: random.Random, do_boot: bool) -> dict:
    """То же, что run_config в run.py, но окно поиска лага — параметр.

    При maxlag = 36 обязана давать те же числа, что run.py; это проверяется
    сверкой с result.json перед тем, как считать что-либо новое.
    """
    ts, xs, ys = R.panel(x, y, t_from=t_from, t_to=t_to, maxlag=maxlag)
    if len(xs) < 60:
        return {"config": name, "n": len(xs), "maxlag": maxlag,
                "error": "выборка меньше 60 точек"}
    cors = R.ccf(xs, ys)
    h_star, r_star = R.peak(cors, sign)
    res = {
        "config": name,
        "maxlag": maxlag,
        "n": len(xs),
        "span": [R.mi_str(ts[0]), R.mi_str(ts[-1] + maxlag)],
        "t_last": R.mi_str(ts[-1]),
        "peak_lag": h_star,
        "peak_r": None if r_star is None else round(r_star, 4),
        "r_at_claimed": None if cors[claimed] is None else round(cors[claimed], 4),
        "r_at_0": None if cors[0] is None else round(cors[0], 4),
        "peak_in_band": h_star is not None and band[0] <= h_star <= band[1],
        "ccf": [None if r is None else round(r, 4) for r in cors],
    }
    if do_boot and r_star is not None:
        boot = R.bootstrap_lag(xs, ys, sign, reps=reps, block=BLOCK, rng=rng)
        boot["in_band"] = band[0] <= boot["p50"] <= band[1]
        drawn = boot.pop("_lags")
        boot["share_in_band"] = round(
            sum(1 for h in drawn if band[0] <= h <= band[1]) / len(drawn), 3)
        # описательно: где именно скапливаются бутстрап-максимумы. Нужно, чтобы
        # отличить «интервал упёрся в край окна» от «за краем действительно
        # ничего нет». Потребления случайных чисел не добавляет.
        boot["hist6"] = {f"{lo}-{min(lo + 5, maxlag)}":
                         sum(1 for h in drawn if lo <= h <= lo + 5)
                         for lo in range(0, maxlag + 1, 6)}
        boot["share_above_36"] = round(
            sum(1 for h in drawn if h > 36) / len(drawn), 4)
        boot["share_at_maxlag"] = round(
            sum(1 for h in drawn if h == maxlag) / len(drawn), 4)
        res["bootstrap"] = boot
        res["p_lagsearch"] = round(
            R.null_pvalue(xs, ys, sign, r_star, reps=reps, block=BLOCK, rng=rng), 4)
    return res


def holm_subset(pvals: dict[str, float], m: int) -> dict[str, float]:
    """Поправка Холма, когда семейство объявлено больше числа посчитанных p.

    При m = len(pvals) совпадает с holm() из run.py. При m > len(pvals) —
    консервативный вариант: множитель берётся от объявленного размера
    семейства, а не от числа тех гипотез, до которых дошли руки.
    """
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    out, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)
        out[k] = round(running, 4)
    return out


def median(vals: Sequence[float]) -> float:
    """Стандартная медиана: при чётном n — среднее двух центральных.

    run.py печатает vals[n // 2], что при чётном n даёт верхний из двух
    центральных. После схлопывания пар n становится чётным, поэтому разница
    перестаёт быть косметической и оба числа печатаются рядом.
    """
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def dedupe_pairs(pairs: list[tuple[int, int, int]], *, keep: str
                 ) -> list[tuple[int, int, int]]:
    """Схлопывание пар с общим ведомым событием (§3.2 дополнения).

    keep="nearest" — остаётся ведущий с наименьшим лидом (согласовано с самим
    правилом «ближайшее последующее» в match_turns).
    keep="earliest" — остаётся ведущий с наибольшим лидом.
    """
    by_follower: dict[int, list[tuple[int, int, int]]] = {}
    for t, u, lag in pairs:
        by_follower.setdefault(u, []).append((t, u, lag))
    out = []
    for u in sorted(by_follower):
        group = by_follower[u]
        pick = min(group, key=lambda p: p[2]) if keep == "nearest" \
            else max(group, key=lambda p: p[2])
        out.append(pick)
    return sorted(out)


def collisions(pairs: list[tuple[int, int, int]]) -> dict[int, list[tuple[int, int, int]]]:
    by_follower: dict[int, list[tuple[int, int, int]]] = {}
    for t, u, lag in pairs:
        by_follower.setdefault(u, []).append((t, u, lag))
    return {u: g for u, g in by_follower.items() if len(g) > 1}


def fmt_r(v) -> str:
    return "   —  " if v is None else f"{v:+.3f}"


def hr(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="перекачать исходные ряды")
    ap.add_argument("--boot", type=int, default=2000, help="повторов бутстрапа")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    base_path = os.path.join(HERE, "result.json")
    with open(base_path, encoding="utf-8") as fh:
        base = json.load(fh)
    print(f"Исходный прогон: {base_path}, данные загружены "
          f"{base['manifest']['fetched_at']}")
    print(f"Кэш исходных рядов: {os.environ.get('RESEARCH_CACHE_DIR') or 'research/.cache'}"
          f"  (перекачка {'ВКЛЮЧЕНА' if args.force else 'выключена'})")

    print("\nЗагрузка рядов…")
    hmi_s = R.S.nahb_hmi("t2", force=args.force)["HMI"]
    unrate_s = R.S.fred("UNRATE", force=args.force)
    dgs10_s = R.S.fred("DGS10", force=args.force)
    for s in (hmi_s, unrate_s, dgs10_s):
        print("  ", s.describe())

    hmi = R.to_monthly(hmi_s)
    unrate = R.to_monthly(unrate_s)
    dgs10 = R.to_monthly(dgs10_s)

    covid = (R.mi("2020-03-01"), R.mi("2021-12-01"))
    split = R.mi("2008-01-01")

    # ряды Δ12 — те же, что в основном скрипте
    x_a = R.log_change(hmi, 12)
    y_a = R.diff(unrate, 12)
    x_b = R.log_change(hmi, 12)
    y_b = R.diff(dgs10, 12)

    band_a, band_b = tuple(R.CLAIMS["A"]["band"]), tuple(R.CLAIMS["B"]["band"])
    claim_a, claim_b = R.CLAIMS["A"]["lead"], R.CLAIMS["B"]["lead"]

    out: dict = {"task": "Z01-addendum", "seed": SEED, "block": BLOCK,
                 "boot_reps": args.boot, "alpha": ALPHA,
                 "family_declared": FAMILY_DECLARED,
                 "base_fetched_at": base["manifest"]["fetched_at"]}

    # ---------------------------------------------------------------- #
    #  Предусловие: та же функция при maxlag = 36 воспроизводит result.json
    # ---------------------------------------------------------------- #
    hr("Предусловие. Сверка run_config_ml(maxlag=36) с result.json")
    checks = []
    probes = [
        ("A", "delta12", x_a, y_a, -1, band_a, claim_a, None, None),
        ("A", "no_covid_d12",
         {t: v for t, v in x_a.items() if not covid[0] <= t <= covid[1]},
         {t: v for t, v in y_a.items() if not covid[0] <= t <= covid[1]},
         -1, band_a, claim_a, None, None),
        ("A", "split_post2008", x_a, y_a, -1, band_a, claim_a, split, None),
        ("A", "split_pre2008", x_a, y_a, -1, band_a, claim_a, None, split - 1),
        ("B", "delta12", x_b, y_b, +1, band_b, claim_b, None, None),
        ("B", "split_post2008", x_b, y_b, +1, band_b, claim_b, split, None),
    ]
    fields = ("n", "span", "peak_lag", "peak_r", "r_at_claimed", "r_at_0",
              "peak_in_band", "ccf")
    for code, cname, x, y, sign, band, claimed, tf, tt in probes:
        got = run_config_ml(cname, x, y, sign, band, claimed, t_from=tf, t_to=tt,
                            maxlag=36, reps=args.boot, rng=stream("probe"),
                            do_boot=False)
        want = base["claims"][code]["configs"][cname]
        bad = [f for f in fields if got.get(f) != want.get(f)]
        checks.append({"config": f"{code}:{cname}", "ok": not bad, "mismatch": bad})
        print(f"  {code}:{cname:<16} {'СОВПАДАЕТ' if not bad else 'РАСХОЖДЕНИЕ: ' + ', '.join(bad)}"
              f"   (n={got.get('n')}, пик={got.get('peak_lag')}, "
              f"r(пик)={fmt_r(got.get('peak_r'))})")
    out["precondition"] = checks
    if not all(c["ok"] for c in checks):
        print("\nПРЕДУСЛОВИЕ НЕ ВЫПОЛНЕНО — дальнейшие числа недействительны.")
        with open(os.path.join(HERE, "result-addendum.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        return 1
    print("  Все сверяемые поля совпали. Бутстрап-поля delta12 не сверяются: "
          "они зависят от общего потока случайных чисел run.py.")

    # ---------------------------------------------------------------- #
    #  Д1. Поздняя половина без ковидных лет
    # ---------------------------------------------------------------- #
    hr("Д1. Поздняя половина 2008–2026 без ковидных лет "
       "(критерий — из главы «Структурные разрывы»)")

    x_nc = {t: v for t, v in x_a.items() if not covid[0] <= t <= covid[1]}
    y_nc = {t: v for t, v in y_a.items() if not covid[0] <= t <= covid[1]}
    d1 = run_config_ml("post2008_no_covid", x_nc, y_nc, -1, band_a, claim_a,
                       t_from=split, t_to=None, maxlag=36, reps=args.boot,
                       rng=stream("post2008_no_covid"), do_boot=True)

    # объявленная устойчивость: чистое окно без дыры в панели
    pre_covid_end = covid[0] - 1
    x_pc = {t: v for t, v in x_a.items() if t <= pre_covid_end}
    y_pc = {t: v for t, v in y_a.items() if t <= pre_covid_end}
    d1b = run_config_ml("post2008_pre_covid", x_pc, y_pc, -1, band_a, claim_a,
                        t_from=split, t_to=None, maxlag=36, reps=args.boot,
                        rng=stream("post2008_pre_covid"), do_boot=True)

    ref = {k: base["claims"]["A"]["configs"][k]
           for k in ("split_pre2008", "split_post2008", "no_covid_d12")}

    print(f"{'конфигурация':<20} {'n':>5} {'период':<20} {'пик':>5} "
          f"{'r(пик)':>8} {'r(10)':>8} {'r(0)':>8}")
    for cname, c in list(ref.items()) + [("post2008_no_covid", d1),
                                         ("post2008_pre_covid", d1b)]:
        if "error" in c:
            print(f"{cname:<20} {c['n']:>5}  {c['error']}")
            continue
        print(f"{cname:<20} {c['n']:>5} {c['span'][0]}..{c['span'][1]:<9} "
              f"{c['peak_lag']:>5} {fmt_r(c['peak_r'])} {fmt_r(c['r_at_claimed'])} "
              f"{fmt_r(c['r_at_0'])}")

    if "error" not in d1:
        b = d1["bootstrap"]
        print(f"\nбутстрап лага post2008_no_covid (блок {BLOCK} мес., {b['reps']} повторов): "
              f"медиана {b['p50']}, 90 % интервал [{b['p05']}, {b['p95']}], "
              f"ширина {b['width90']} мес.")
        print(f"  распределение по шестёркам: " + "  ".join(
            f"{k}:{v}" for k, v in b["hist6"].items()))
        print(f"  доля бутстрап-максимумов в полосе курса 8–12: {b['share_in_band']}")
        print(f"p с поправкой на поиск по 37 лагам: {d1['p_lagsearch']}")
        print("\nвзаимная корреляция post2008_no_covid по лагам:")
        for row in range(0, 37, 12):
            print("  " + "  ".join(
                f"{h:>2}:{d1['ccf'][h]:+.3f}" for h in range(row, min(row + 12, 37))))

        h1 = d1["peak_lag"]
        r0 = d1["r_at_0"]
        s1 = ("устоял" if NEAR_NINE[0] <= h1 <= NEAR_NINE[1] else
              "опровергнут" if NEAR_NINETEEN[0] <= h1 <= NEAR_NINETEEN[1] else
              "неопределённо")
        s2 = ("опровергнут" if r0 >= 0 else
              "устоял" if abs(r0) >= S2_HALF else "неопределённо")
        verdict_d1 = ("ОПРОВЕРГНУТО" if "опровергнут" in (s1, s2) else
                      "ПОДТВЕРЖДЕНО" if s1 == s2 == "устоял" else "НЕОПРЕДЕЛЕНО")
    else:
        h1 = r0 = None
        s1 = s2 = "неопределённо"
        verdict_d1 = "НЕОПРЕДЕЛЕНО"

    print(f"\nS1 (аргмакс {h1}; окрестность девяти {NEAR_NINE}, "
          f"окрестность девятнадцати {NEAR_NINETEEN}): {s1}")
    print(f"S2 (r(0) = {fmt_r(r0)}; порог |r| >= {S2_HALF}): {s2}")
    print(f"ВЕРДИКТ Д1 (раздел главы о двух половинах): {verdict_d1}")
    out["D1"] = {"post2008_no_covid": d1, "post2008_pre_covid": d1b,
                 "reference": ref, "S1": s1, "S2": s2, "verdict": verdict_d1,
                 "near_nine": list(NEAR_NINE), "near_nineteen": list(NEAR_NINETEEN),
                 "s2_threshold": S2_HALF}

    # ---------------------------------------------------------------- #
    #  Д2. Окно поиска до 48 месяцев
    # ---------------------------------------------------------------- #
    hr(f"Д2. Окно поиска сдвига 0–{MAXLAG_WIDE} вместо 0–36")

    wide = {}
    for code, x, y, sign, band, claimed in (
            ("A", x_a, y_a, -1, band_a, claim_a),
            ("B", x_b, y_b, +1, band_b, claim_b)):
        name = f"{code}_maxlag{MAXLAG_WIDE}"
        wide[code] = run_config_ml(name, x, y, sign, band, claimed,
                                   t_from=None, t_to=None, maxlag=MAXLAG_WIDE,
                                   reps=args.boot, rng=stream(name), do_boot=True)

    print(f"{'конфигурация':<20} {'n':>5} {'период':<20} {'пик':>5} "
          f"{'r(пик)':>8} {'r(заявл)':>9} {'r(0)':>8}")
    for code in ("A", "B"):
        old = base["claims"][code]["configs"]["delta12"]
        new = wide[code]
        print(f"{code + ':delta12 (0-36)':<20} {old['n']:>5} "
              f"{old['span'][0]}..{old['span'][1]:<9} {old['peak_lag']:>5} "
              f"{fmt_r(old['peak_r'])} {fmt_r(old['r_at_claimed']):>9} "
              f"{fmt_r(old['r_at_0'])}")
        print(f"{code + f':delta12 (0-{MAXLAG_WIDE})':<20} {new['n']:>5} "
              f"{new['span'][0]}..{new['span'][1]:<9} {new['peak_lag']:>5} "
              f"{fmt_r(new['peak_r'])} {fmt_r(new['r_at_claimed']):>9} "
              f"{fmt_r(new['r_at_0'])}")

    for code in ("A", "B"):
        c = wide[code]
        b = c["bootstrap"]
        print(f"\n{code}: бутстрап лага — медиана {b['p50']}, "
              f"90 % интервал [{b['p05']}, {b['p95']}], ширина {b['width90']} мес.  "
              f"(было при 0–36: {base['claims'][code]['configs']['delta12']['bootstrap']['p05']}"
              f"…{base['claims'][code]['configs']['delta12']['bootstrap']['p95']})")
        print(f"{code}: p с поправкой на поиск по {MAXLAG_WIDE + 1} лагам = "
              f"{c['p_lagsearch']}  (было по 37 лагам: "
              f"{base['claims'][code]['configs']['delta12']['p_lagsearch']})")
        print(f"{code}: распределение бутстрап-лага по шестёркам: " + "  ".join(
            f"{k}:{v}" for k, v in b["hist6"].items()))
        print(f"{code}: доля бутстрап-максимумов правее 36 мес. = "
              f"{b['share_above_36']}, ровно на границе {MAXLAG_WIDE} = "
              f"{b['share_at_maxlag']}")
        print(f"{code}: взаимная корреляция по лагам 36–{MAXLAG_WIDE}: " + "  ".join(
            f"{h}:{c['ccf'][h]:+.3f}" for h in range(36, MAXLAG_WIDE + 1)))

    # множественность
    pvals = {
        "A@36": base["claims"]["A"]["configs"]["delta12"]["p_lagsearch"],
        "B@36": base["claims"]["B"]["configs"]["delta12"]["p_lagsearch"],
        f"A@{MAXLAG_WIDE}": wide["A"]["p_lagsearch"],
        f"B@{MAXLAG_WIDE}": wide["B"]["p_lagsearch"],
    }
    holm_declared = holm_subset(pvals, FAMILY_DECLARED)
    holm_computed = holm_subset(pvals, len(pvals))
    print(f"\nПоправка на множественность (порог {ALPHA}):")
    print(f"  {'гипотеза':<10} {'p сырое':>9} {'Холм m=' + str(FAMILY_DECLARED):>14} "
          f"{'Холм m=' + str(len(pvals)):>13}")
    for k in ("A@36", f"A@{MAXLAG_WIDE}", "B@36", f"B@{MAXLAG_WIDE}"):
        print(f"  {k:<10} {pvals[k]:>9} {holm_declared[k]:>14} {holm_computed[k]:>13}"
              f"   {'проходит' if holm_declared[k] <= ALPHA else 'НЕ проходит'} "
              f"(осн.)")
    print(f"  Для сравнения: в исходном прогоне run.py применил Холма при m=2 — "
          f"A@36 p_holm={base['pvalues_holm'].get('A:delta12')}, "
          f"B@36 p_holm={base['pvalues_holm'].get('B:delta12')}. "
          f"Пред-регистрация объявляла семейство из 12.")

    verdicts_d2 = {}
    for code in ("A", "B"):
        c = wide[code]
        h = c["peak_lag"]
        p95 = c["bootstrap"]["p95"]
        key = f"{code}@{MAXLAG_WIDE}"
        if h == MAXLAG_WIDE or p95 == MAXLAG_WIDE:
            l1 = "не локализован"
        elif h <= LOCALIZED_MAX and p95 <= LOCALIZED_MAX:
            l1 = "локализован"
        else:
            l1 = "неопределённо"
        l2 = holm_declared[key] <= ALPHA
        v = ("ОПРОВЕРГНУТО" if l1 == "не локализован" else
             "ПОДТВЕРЖДЕНО" if l1 == "локализован" and l2 else "НЕОПРЕДЕЛЕНО")
        verdicts_d2[code] = {"L1": l1, "L1_peak": h, "L1_p95": p95,
                             "L2_pass": l2, "p_holm_declared": holm_declared[key],
                             "p_holm_computed": holm_computed[key],
                             "verdict": v}
        print(f"\n{code}: L1 (пик {h}, p95 {p95}; порог локализации {LOCALIZED_MAX}, "
              f"граница окна {MAXLAG_WIDE}) — {l1}")
        print(f"{code}: L2 (p Холма при m={FAMILY_DECLARED} = {holm_declared[key]} "
              f"против порога {ALPHA}) — {'пройден' if l2 else 'НЕ пройден'}")
        print(f"ВЕРДИКТ Д2/{code}: {v}")

    out["D2"] = {"configs": wide, "pvalues_raw": pvals,
                 "holm_declared_m16": holm_declared,
                 "holm_computed_m4": holm_computed,
                 "verdicts": verdicts_d2,
                 "localized_max": LOCALIZED_MAX, "maxlag": MAXLAG_WIDE}

    # ---------------------------------------------------------------- #
    #  Д3. Независимость пар в блоке разворотов
    # ---------------------------------------------------------------- #
    hr("Д3. Независимость пар в блоке разворотов")

    hmi_yoy = R.log_change(hmi, 12)
    d10_yoy = R.diff(dgs10, 12)
    tables = {
        "A_hmi_peak_to_unrate_trough": (
            "пик HMI → минимум безработицы",
            R.match_turns(R.extrema(hmi, kind="max"),
                          R.extrema(unrate, kind="min"))),
        "B_hmi_yoy_peak_to_dgs10_yoy_peak": (
            "пик NAHB YoY → пик US10Y YoY",
            R.match_turns(R.extrema(hmi_yoy, kind="max"),
                          R.extrema(d10_yoy, kind="max"))),
    }

    d3: dict = {}
    for key, (title, pairs) in tables.items():
        coll = collisions(pairs)
        near = dedupe_pairs(pairs, keep="nearest")
        early = dedupe_pairs(pairs, keep="earliest")
        lags_all = [p[2] for p in pairs]
        lags_near = [p[2] for p in near]
        lags_early = [p[2] for p in early]
        print(f"\n{title}")
        print(f"  пар как в REPORT.md: {len(pairs)}; "
              f"различных ведомых событий: {len(near)}")
        if coll:
            print(f"  КОЛЛИЗИИ (одно ведомое событие на несколько ведущих): {len(coll)}")
            for u in sorted(coll):
                who = ", ".join(f"{R.mi_str(t)} (лид {lag})" for t, _, lag in coll[u])
                print(f"    {R.mi_str(u)}  ←  {who}")
        else:
            print("  коллизий нет")
        print(f"  медиана до схлопывания: стандартная {median(lags_all):g}, "
              f"как печатает run.py {sorted(lags_all)[len(lags_all) // 2]}; "
              f"n={len(lags_all)}, размах {min(lags_all)}–{max(lags_all)}")
        print(f"  схлопывание «ближайший» (основное): n={len(lags_near)}, "
              f"медиана {median(lags_near):g}, размах {min(lags_near)}–{max(lags_near)}, "
              f"лиды {sorted(lags_near)}")
        print(f"  схлопывание «самый ранний» (альтернатива): n={len(lags_early)}, "
              f"медиана {median(lags_early):g}, размах {min(lags_early)}–{max(lags_early)}, "
              f"лиды {sorted(lags_early)}")
        d3[key] = {
            "title": title,
            "pairs_raw": [{"lead_at": R.mi_str(t), "follow_at": R.mi_str(u), "lead": lag}
                          for t, u, lag in pairs],
            "n_raw": len(pairs),
            "n_independent": len(near),
            "collisions": {R.mi_str(u): [R.mi_str(t) for t, _, _ in g]
                           for u, g in sorted(coll.items())},
            "median_raw_standard": median(lags_all),
            "median_raw_runpy": sorted(lags_all)[len(lags_all) // 2],
            "nearest": {"n": len(lags_near), "median": median(lags_near),
                        "leads": sorted(lags_near),
                        "pairs": [{"lead_at": R.mi_str(t), "follow_at": R.mi_str(u),
                                   "lead": lag} for t, u, lag in near]},
            "earliest": {"n": len(lags_early), "median": median(lags_early),
                         "leads": sorted(lags_early),
                         "pairs": [{"lead_at": R.mi_str(t), "follow_at": R.mi_str(u),
                                    "lead": lag} for t, u, lag in early]},
        }

    a_tab = d3["A_hmi_peak_to_unrate_trough"]
    claim_confirmed = "1989-03" in a_tab["collisions"] and \
        len(a_tab["collisions"]["1989-03"]) == 2 and a_tab["n_independent"] == 6
    verdict_d3 = "ПОДТВЕРЖДЕНО" if claim_confirmed else "ОПРОВЕРГНУТО"
    print(f"\nПроверяемое утверждение: две из семи пар таблицы A указывают "
          f"на один и тот же минимум 1989-03, независимых пар шесть.")
    print(f"ВЕРДИКТ Д3: {verdict_d3}")
    d3["verdict"] = verdict_d3
    out["D3"] = d3

    path = os.path.join(HERE, "result-addendum.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nЗаписано: {path}")

    hr("Сводка")
    print(f"Д1 (раздел главы о двух половинах): {verdict_d1}")
    for code in ("A", "B"):
        print(f"Д2/{code} (лид локализован в окне 0–{MAXLAG_WIDE}): "
              f"{verdicts_d2[code]['verdict']}")
    print(f"Д3 (две пары на один минимум): {verdict_d3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
