#!/usr/bin/env python3
"""Z04 — дезинверсия из глубокой инверсии как более точный сигнал, чем инверсия.

Критерии зафиксированы до расчёта: см. HYPOTHESIS.md. Разметка эпизодов —
та же, что в Z03: модуль Z03/run.py импортируется целиком, а не переписывается,
чтобы «одна разметка» была фактом кода, а не обещанием отчёта.

Запуск:
    python run.py              # из кэша, если он свежий
    python run.py --force      # перекачать исходные ряды
    python run.py --boot 5000  # повторов бутстрапа (по умолчанию 2000)
    python run.py --sim 2000   # повторов симуляции мощности (по умолчанию 2000)
    python run.py --sim-boot 200  # бутстрап внутри симуляции (по умолчанию 200)

Результат: result.json рядом со скриптом + таблицы в stdout.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import sys
from typing import Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH = os.path.dirname(HERE)
sys.path.insert(0, RESEARCH)

import sources as S  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "z03", os.path.join(RESEARCH, "Z03", "run.py"))
z03 = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(z03)

mi, mi_str = z03.mi, z03.mi_str

SEED = 20260727
K_MAIN = z03.K_MAIN            # склейка эпизодов — как в Z03
W_MAIN = z03.W_MAIN            # окно назначения пика — как в Z03
DEPTHS = (-0.50, -0.25, -1.00)         # основной первым, HYPOTHESIS §3
DISINV_RULES = ("zero", "plus010", "three")   # основной первым
FA_WINDOW = (-12, 24)          # окно для ложных тревог дезинверсии, §6


# --------------------------------------------------------------------------- #
#  Эпизоды: минимум, дезинверсия, назначенный пик
# --------------------------------------------------------------------------- #


def disinversion_month(spread: dict[int, float], t_min: int, rule: str) -> int | None:
    """Месяц дезинверсии по правилу из HYPOTHESIS §3."""
    ts = sorted(t for t in spread if t > t_min)
    if rule == "zero":
        return next((t for t in ts if spread[t] >= 0), None)
    if rule == "plus010":
        return next((t for t in ts if spread[t] >= 0.10), None)
    if rule == "three":
        for t in ts:
            if all(spread.get(t + i) is not None and spread[t + i] >= 0
                   for i in range(3)):
                return t
        return None
    raise ValueError(rule)


def build_episodes(spread: dict[int, float], peaks: list[int], *,
                   k: int, w: int, rule: str) -> list[dict]:
    """Разметка Z03 + минимум, дезинверсия и оба лага до ОДНОГО пика."""
    base = {t: v < 0 for t, v in spread.items()}
    out: list[dict] = []
    for ep in z03.episodes(base, k):
        t0 = ep[0]
        t_min = min(ep, key=lambda t: spread[t])
        depth = spread[t_min]
        nxt = [p for p in sorted(peaks) if t0 < p <= t0 + w]
        p = nxt[0] if nxt else None
        d = disinversion_month(spread, t_min, rule)
        out.append({
            "signal": mi_str(t0), "_t0": t0,
            "last_month": mi_str(ep[-1]),
            "min_month": mi_str(t_min), "_tmin": t_min, "depth": round(depth, 3),
            "disinversion": (mi_str(d) if d is not None else None), "_d": d,
            "peak": (mi_str(p) if p is not None else None), "_p": p,
            "lag_inv": (p - t0 if p is not None else None),
            "lag_dis": (p - d if p is not None and d is not None else None),
            "months_inverted": len(ep),
        })
    return out


# --------------------------------------------------------------------------- #
#  Разброс
# --------------------------------------------------------------------------- #


def sd(xs: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def spread_stats(xs: Sequence[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    n = len(s)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    q1, q3 = s[int(0.25 * (n - 1))], s[int(0.75 * (n - 1))]
    mean = sum(s) / n
    dev = sd(s)
    return {
        "n": n, "mean": round(mean, 2), "median": round(med, 2),
        "sd": (None if dev is None else round(dev, 3)),
        "min": s[0], "max": s[-1], "range": s[-1] - s[0],
        "iqr": [q1, q3],
        "mad": round(sorted(abs(x - med) for x in s)[n // 2], 2),
        "cv": (None if dev is None or mean == 0 else round(dev / abs(mean), 3)),
        "values": list(s),
    }


def ratio_bootstrap(pairs: list[tuple[float, float]], *, reps: int,
                    rng: random.Random) -> dict:
    """90 %-й интервал для R = SD(лаг дезинверсии) / SD(лаг инверсии).

    Ресемплируются ЭПИЗОДЫ целиком — пара лагов одного эпизода не разъединяется.
    """
    n = len(pairs)
    if n < 2:
        return {"n": n}
    rs = []
    for _ in range(reps):
        draw = [pairs[rng.randrange(n)] for _ in range(n)]
        a = sd([p[1] for p in draw])       # дезинверсия
        b = sd([p[0] for p in draw])       # инверсия
        if a is None or b is None or b == 0:
            continue
        rs.append(a / b)
    if len(rs) < reps // 10:
        return {"n": n, "boot_ok": len(rs), "degenerate": True}
    rs.sort()
    return {"n": n, "boot_ok": len(rs),
            "ci90": [round(rs[int(0.05 * (len(rs) - 1))], 3),
                     round(rs[int(0.95 * (len(rs) - 1))], 3)],
            "median": round(rs[len(rs) // 2], 3)}


def min_detectable_ratio(n: int, rho: float, *, sim: int, boot: int,
                         rng: random.Random) -> dict:
    """Наименьшее истинное отношение SD, которое объявленный критерий ловит.

    Симуляция ровно того критерия, что объявлен: точечная оценка R < 1
    и верхняя граница 90 %-го бутстрап-интервала < 1. Пары генерируются
    двумерной нормалью с наблюдённой корреляцией — иначе парный бутстрап
    моделировался бы на данных, у которых пары независимы.
    """
    grid = [round(0.2 + 0.1 * i, 1) for i in range(9)]     # 0.2 .. 1.0
    power: dict[float, float] = {}
    for r_true in grid:
        hits = 0
        for _ in range(sim):
            pairs = []
            for _ in range(n):
                z1 = rng.gauss(0, 1)
                z2 = rho * z1 + math.sqrt(max(0.0, 1 - rho * rho)) * rng.gauss(0, 1)
                pairs.append((z1, r_true * z2))
            a, b = sd([p[1] for p in pairs]), sd([p[0] for p in pairs])
            if a is None or b is None or b == 0 or a / b >= 1:
                continue
            ups = []
            for _ in range(boot):
                draw = [pairs[rng.randrange(n)] for _ in range(n)]
                aa, bb = sd([p[1] for p in draw]), sd([p[0] for p in draw])
                if aa is not None and bb not in (None, 0):
                    ups.append(aa / bb)
            if not ups:
                continue
            ups.sort()
            if ups[int(0.95 * (len(ups) - 1))] < 1:
                hits += 1
        power[r_true] = round(hits / sim, 3)
    # Мощность при истинном R = 1 — это не мощность, а РАЗМЕР критерия: доля
    # срабатываний, когда разброса на самом деле нет. Пока он велик,
    # «минимальное отличимое отношение» смысла не имеет, и его нельзя печатать
    # как характеристику разрешающей способности.
    size = power[1.0]
    # Мощность падает по мере приближения R к единице, поэтому граница
    # разрешающей способности — САМОЕ БОЛЬШОЕ (ближайшее к 1) отношение,
    # которое ещё ловится с вероятностью 0.8, а не самое маленькое.
    detect = [r for r in grid if r < 1.0 and power[r] >= 0.8]
    detectable = max(detect) if detect else None
    informative = size <= 0.10
    return {"n": n, "rho": round(rho, 3), "sim": sim, "boot_inner": boot,
            "power": power, "size_at_ratio_1": size, "informative": informative,
            "min_detectable_ratio": (detectable if informative else None)}


def pearson(a: Sequence[float], b: Sequence[float]) -> float:
    n = len(a)
    if n < 3:
        return 0.5
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if sa == 0 or sb == 0:
        return 0.5
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--sim", type=int, default=2000)
    ap.add_argument("--sim-boot", type=int, default=200,
                    help="повторов бутстрапа ВНУТРИ симуляции мощности")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    rng = random.Random(SEED)

    print("Загрузка рядов…")
    t10y3m = S.fred("T10Y3M", force=args.force)
    t10y2y = S.fred("T10Y2Y", force=args.force)
    dgs10 = S.fred("DGS10", force=args.force)
    dgs2 = S.fred("DGS2", force=args.force)
    usrec_s = S.fred("USREC", force=args.force)
    usrecm_s = S.fred("USRECM", force=args.force)
    gs10_s = S.fred("GS10", force=args.force)
    tb3ms_s = S.fred("TB3MS", force=args.force)
    for s in (t10y3m, t10y2y, dgs10, dgs2, usrec_s, gs10_s, tb3ms_s):
        print("  ", s.describe())

    spreads = {"10y-3m": z03.monthly_mean(t10y3m),
               "10y-2y": z03.monthly_mean(t10y2y)}
    usrec = z03.month_level(usrec_s)
    usrecm = z03.month_level(usrecm_s)
    peaks, peak_warn = z03.nber_peaks(usrec, usrecm)
    for w in peak_warn:
        print(f"  ВНИМАНИЕ: {w}")

    # --- контроль источника: DGS10-DGS2 против T10Y2Y ---------------------- #
    d10 = {d: v for d, v in dgs10.observed}
    d02 = {d: v for d, v in dgs2.observed}
    t2y = {d: v for d, v in t10y2y.observed}
    common = sorted(set(d10) & set(d02) & set(t2y))
    diffs = sorted(abs(d10[d] - d02[d] - t2y[d]) for d in common)
    med_diff = diffs[len(diffs) // 2]
    worst = max(diffs)
    print(f"\nСверка источника: |DGS10 - DGS2 - T10Y2Y| по {len(common)} дням — "
          f"медиана {med_diff:.4f} п.п., максимум {worst:.4f} п.п.")
    if med_diff > 0.01:
        print("ОСТАНОВ: два пути к спреду 10y-2y расходятся больше чем на "
              "0.01 п.п. в медиане — считать на «примерно том же» ряде нельзя.")
        return 2

    # --- 18 конфигураций ---------------------------------------------------- #
    print(f"\n{'=' * 86}\nТАБЛИЦА ЭПИЗОДОВ (склейка K={K_MAIN}, окно назначения "
          f"пика W={W_MAIN} мес., дезинверсия «первый месяц со спредом >= 0»)\n"
          f"{'=' * 86}")
    for sp_name in ("10y-3m", "10y-2y"):
        eps = build_episodes(spreads[sp_name], peaks, k=K_MAIN, w=W_MAIN, rule="zero")
        print(f"\n[{sp_name}]")
        print(f"{'сигнал':>8} {'инверт.':>8} {'минимум':>9} {'глубина':>8} "
              f"{'дезинв.':>9} {'пик':>9} {'лаг инв':>8} {'лаг дез':>8}")
        for e in eps:
            print(f"{e['signal']:>8} {e['months_inverted']:>8} {e['min_month']:>9} "
                  f"{e['depth']:>+8.2f} {str(e['disinversion']):>9} "
                  f"{str(e['peak']):>9} {str(e['lag_inv']):>8} "
                  f"{str(e['lag_dis']):>8}")

    print(f"\n{'=' * 86}\nСРАВНЕНИЕ РАЗБРОСА: 18 конфигураций "
          f"(3 порога глубины x 3 определения дезинверсии x 2 спреда)\n{'=' * 86}")
    print(f"{'спред':<8} {'порог':>6} {'дезинв.':<8} {'n':>3} "
          f"{'SD инв':>7} {'SD дез':>7} {'R':>6} {'90% интервал R':>28} "
          f"{'CV инв':>7} {'CV дез':>7}  V0 V1 V2")
    configs: list[dict] = []
    for sp_name in ("10y-3m", "10y-2y"):
        for depth in DEPTHS:
            for rule in DISINV_RULES:
                eps = build_episodes(spreads[sp_name], peaks,
                                     k=K_MAIN, w=W_MAIN, rule=rule)
                deep = [e for e in eps if e["depth"] <= depth]
                paired = [e for e in deep
                          if e["lag_inv"] is not None and e["lag_dis"] is not None]
                li = [e["lag_inv"] for e in paired]
                ld = [e["lag_dis"] for e in paired]
                st_i, st_d = spread_stats(li), spread_stats(ld)
                sd_i, sd_d = st_i.get("sd"), st_d.get("sd")
                r = (None if not sd_i or sd_d is None else round(sd_d / sd_i, 3))
                boot = ratio_bootstrap(list(zip(li, ld)), reps=args.boot, rng=rng)
                v0 = len(paired) >= 5
                v1 = r is not None and r < 1
                v2 = "ci90" in boot and boot["ci90"][1] < 1
                cell = {"spread": sp_name, "depth_threshold": depth,
                        "disinversion_rule": rule, "n_deep": len(deep),
                        "n_paired": len(paired), "lag_inv": st_i, "lag_dis": st_d,
                        "ratio": r, "bootstrap": boot,
                        "V0": v0, "V1": v1, "V2": v2,
                        "censored_no_disinversion":
                            [e["signal"] for e in deep if e["disinversion"] is None],
                        "no_peak": [e["signal"] for e in deep if e["peak"] is None],
                        "episodes": paired}
                configs.append(cell)
                ci = (f"[{boot['ci90'][0]}, {boot['ci90'][1]}]" if "ci90" in boot
                      else "—")
                if "ci90" in boot and boot["ci90"][0] == boot["ci90"][1]:
                    ci += " выродился"
                print(f"{sp_name:<8} {depth:>+6.2f} {rule:<8} {len(paired):>3} "
                      f"{('—' if sd_i is None else f'{sd_i:.2f}'):>7} "
                      f"{('—' if sd_d is None else f'{sd_d:.2f}'):>7} "
                      f"{('—' if r is None else f'{r:.2f}'):>6} {ci:>28} "
                      f"{str(st_i.get('cv')):>7} {str(st_d.get('cv')):>7}"
                      f"  {'+' if v0 else '-'}  {'+' if v1 else '-'}"
                      f"  {'+' if v2 else '-'}")

    main_cell = next(c for c in configs if c["spread"] == "10y-3m"
                     and c["depth_threshold"] == DEPTHS[0]
                     and c["disinversion_rule"] == DISINV_RULES[0])

    # --- ложные тревоги дезинверсии ---------------------------------------- #
    print(f"\n{'=' * 86}\nЛОЖНЫЕ ТРЕВОГИ ДЕЗИНВЕРСИИ (окно {FA_WINDOW[0]}..+"
          f"{FA_WINDOW[1]} мес. вокруг дезинверсии; вердикта не несёт)\n{'=' * 86}")
    fa_tab = {}
    for sp_name in ("10y-3m", "10y-2y"):
        eps = build_episodes(spreads[sp_name], peaks, k=K_MAIN, w=W_MAIN, rule="zero")
        deep = [e for e in eps if e["depth"] <= DEPTHS[0] and e["_d"] is not None]
        hit = [e for e in deep
               if any(e["_d"] + FA_WINDOW[0] <= p <= e["_d"] + FA_WINDOW[1]
                      for p in peaks)]
        fa_tab[sp_name] = {"deep_with_disinversion": len(deep),
                           "with_peak_in_window": len(hit),
                           "false": [e["disinversion"] for e in deep if e not in hit]}
        print(f"  {sp_name}: дезинверсий из глубокой инверсии {len(deep)}, "
              f"пик в окне у {len(hit)}, ложных {len(deep) - len(hit)}"
              + (f" — {', '.join(fa_tab[sp_name]['false'])}"
                 if fa_tab[sp_name]["false"] else ""))

    # --- эпизод 2022–2024 --------------------------------------------------- #
    print(f"\n{'=' * 86}\nЭПИЗОД 2022–2024 ОТДЕЛЬНОЙ СТРОКОЙ\n{'=' * 86}")
    ep2022 = {}
    for sp_name in ("10y-3m", "10y-2y"):
        for rule in DISINV_RULES:
            eps = build_episodes(spreads[sp_name], peaks, k=K_MAIN, w=W_MAIN, rule=rule)
            for e in eps:
                if e["signal"][:4] in ("2022", "2023"):
                    ep2022[f"{sp_name}|{rule}"] = e
                    print(f"  {sp_name:<8} дезинв.={rule:<8} сигнал {e['signal']}, "
                          f"минимум {e['min_month']} ({e['depth']:+.2f} п.п.), "
                          f"дезинверсия {e['disinversion']}, "
                          f"назначенный пик {e['peak'] or 'нет'}")

    # --- удлинённая выборка «после 1970» ------------------------------------ #
    print(f"\n{'=' * 86}\nУДЛИНЁННАЯ ВЫБОРКА GS10-TB3MS (единственный путь к "
          f"«после 1970»)\n{'=' * 86}")
    gs10 = z03.month_level(gs10_s)
    tb3 = z03.month_level(tb3ms_s)
    ext_raw = {t: gs10[t] - tb3[t] for t in gs10 if t in tb3}
    ov = [spreads["10y-3m"][t] - ext_raw[t] for t in ext_raw if t in spreads["10y-3m"]]
    offset = sum(ov) / len(ov) if ov else 0.0
    print(f"  смещение дисконтной базы против T10Y3M на перекрытии: "
          f"{offset:+.3f} п.п. по {len(ov)} месяцам")
    ext_res = {}
    for tag, ser in (("сырая", ext_raw),
                     ("со снятым смещением", {t: v + offset for t, v in ext_raw.items()})):
        sub = {t: v for t, v in ser.items() if t >= mi("1970-01-01")}
        eps = build_episodes(sub, peaks, k=K_MAIN, w=W_MAIN, rule="zero")
        deep = [e for e in eps if e["depth"] <= DEPTHS[0]]
        paired = [e for e in deep
                  if e["lag_inv"] is not None and e["lag_dis"] is not None]
        li = [e["lag_inv"] for e in paired]
        ld = [e["lag_dis"] for e in paired]
        st_i, st_d = spread_stats(li), spread_stats(ld)
        r = (None if not st_i.get("sd") or st_d.get("sd") is None
             else round(st_d["sd"] / st_i["sd"], 3))
        boot = ratio_bootstrap(list(zip(li, ld)), reps=args.boot, rng=rng)
        ext_res[tag] = {"n_deep": len(deep), "n_paired": len(paired),
                        "lag_inv": st_i, "lag_dis": st_d, "ratio": r,
                        "bootstrap": boot,
                        "episodes": [{k: v for k, v in e.items()
                                      if not k.startswith("_")} for e in paired]}
        ci = f"[{boot['ci90'][0]}, {boot['ci90'][1]}]" if "ci90" in boot else "—"
        print(f"  {tag:<20} глубоких {len(deep)}, с пиком {len(paired)}, "
              f"SD инв {st_i.get('sd')}, SD дез {st_d.get('sd')}, R={r}, "
              f"90 % {ci}")
        print(f"    лаг инверсии: {st_i.get('values')}")
        print(f"    лаг дезинверсии: {st_d.get('values')}")

    # --- достижимая мощность (HYPOTHESIS §5) -------------------------------- #
    print(f"\n{'=' * 86}\nРАЗРЕШАЮЩАЯ СПОСОБНОСТЬ ПРИ ФАКТИЧЕСКОМ ЧИСЛЕ СОБЫТИЙ\n"
          f"{'=' * 86}")
    print("Симулируется ровно объявленный критерий (V1 и V2) на парах лагов "
          "с заданным\nистинным отношением SD. Столбец R=1.0 — это не мощность, "
          "а РАЗМЕР критерия:\nдоля срабатываний, когда разброс на самом деле "
          "одинаков.")
    ns: dict[int, float] = {}
    for sp_name in ("10y-3m", "10y-2y"):
        cell = next(c for c in configs if c["spread"] == sp_name
                    and c["depth_threshold"] == DEPTHS[0]
                    and c["disinversion_rule"] == DISINV_RULES[0])
        if cell["n_paired"] >= 2:
            ns.setdefault(cell["n_paired"],
                          pearson([e["lag_inv"] for e in cell["episodes"]],
                                  [e["lag_dis"] for e in cell["episodes"]]))
    ext_paired = ext_res["сырая"]["episodes"]
    if len(ext_paired) >= 2:
        ns.setdefault(len(ext_paired),
                      pearson([e["lag_inv"] for e in ext_paired],
                              [e["lag_dis"] for e in ext_paired]))
    for n_target in (5, 10, 20):
        ns.setdefault(n_target, 0.5)
    powers = {}
    for n, rho in sorted(ns.items()):
        pw = min_detectable_ratio(n, rho, sim=args.sim, boot=args.sim_boot, rng=rng)
        powers[str(n)] = pw
        print(f"\n  n={n}, корреляция лагов rho={pw['rho']}")
        print("    R истинное: " + "  ".join(f"{k:>5}" for k in pw["power"]))
        print("    срабатывает:" + "  ".join(f"{v:>5}" for v in pw["power"].values()))
        print(f"    размер (доля срабатываний при R=1): {pw['size_at_ratio_1']}")
        if not pw["informative"]:
            note = ("НЕ ОПРЕДЕЛЕНО — критерий неинформативен: он срабатывает "
                    "и тогда, когда разницы нет")
        elif pw["min_detectable_ratio"] is None:
            note = "не достигается ни при каком R >= 0.2 из сетки"
        else:
            r = pw["min_detectable_ratio"]
            note = (f"{r} — то есть разброс дезинверсии должен быть меньше "
                    f"разброса инверсии как минимум в {1 / r:.1f} раза")
        print(f"    наибольшее отличимое отношение SD (мощность 0.8): {note}")

    # --- вердикт ------------------------------------------------------------ #
    n_paired = main_cell["n_paired"]
    v0 = main_cell["V0"]
    v1, v2 = main_cell["V1"], main_cell["V2"]
    depth_cells = [c for c in configs if c["spread"] == "10y-3m"
                   and c["disinversion_rule"] == DISINV_RULES[0]]
    v3 = sum(1 for c in depth_cells if c["V1"] and c["V2"]) >= 2
    against = sum(1 for c in depth_cells
                  if c["ratio"] is not None and c["ratio"] >= 1) >= 2
    if not v0:
        verdict = "НЕОПРЕДЕЛЕНО"
        why = (f"V0 не выполнено: парных эпизодов {n_paired} < 5. "
               f"Автоматический вердикт объявлен в HYPOTHESIS §4 до расчёта")
    elif v1 and v2 and v3:
        verdict, why = "ПОДТВЕРЖДЕНО", "V0, V1, V2 и V3 выполнены"
    elif (main_cell["ratio"] is not None and main_cell["ratio"] >= 1) and against:
        verdict, why = "ОПРОВЕРГНУТО", "R >= 1 в основной конфигурации и в 2 из 3 порогов"
    else:
        verdict, why = "НЕОПРЕДЕЛЕНО", "критерий не выполнен и не опровергнут"
    print(f"\n{'=' * 86}\nВЕРДИКТ Z04: {verdict}\n  {why}\n"
          f"  основная конфигурация: спред 10y-3m, порог {DEPTHS[0]:+.2f} п.п., "
          f"дезинверсия «первый месяц со спредом >= 0»; "
          f"парных эпизодов {n_paired}, R={main_cell['ratio']}\n{'=' * 86}")

    out = {
        "task": "Z04",
        "verdict": verdict, "verdict_reason": why,
        "params": {"seed": SEED, "K": K_MAIN, "W": W_MAIN,
                   "depths": list(DEPTHS), "disinversion_rules": list(DISINV_RULES),
                   "fa_window": list(FA_WINDOW), "boot_reps": args.boot,
                   "sim_reps": args.sim, "sim_boot": args.sim_boot,
                   "family_size": len(configs)},
        "manifest": {
            "fetched_at": t10y3m.fetched_at,
            "series": {s.series_id: {"n": len(s.observed), "first": s.observed[0][0],
                                     "last": s.observed[-1][0], "source": s.source}
                       for s in (t10y3m, t10y2y, dgs10, dgs2, usrec_s, gs10_s, tb3ms_s)},
            "source_crosscheck_10y2y": {
                "days": len(common), "median_abs_diff_pp": round(med_diff, 5),
                "max_abs_diff_pp": round(worst, 5)},
        },
        "main_config": {"spread": "10y-3m", "depth_threshold": DEPTHS[0],
                        "disinversion_rule": DISINV_RULES[0],
                        "n_paired": n_paired, "ratio": main_cell["ratio"],
                        "V0": v0, "V1": v1, "V2": v2, "V3": v3},
        "configs18": [{k: v for k, v in c.items() if k != "episodes"}
                      for c in configs],
        "main_episodes": [{k: v for k, v in e.items() if not k.startswith("_")}
                          for e in main_cell["episodes"]],
        "episodes_all": {
            sp: [{k: v for k, v in e.items() if not k.startswith("_")}
                 for e in build_episodes(spreads[sp], peaks, k=K_MAIN, w=W_MAIN,
                                         rule="zero")]
            for sp in ("10y-3m", "10y-2y")},
        "disinversion_false_alarms": fa_tab,
        "episode_2022": {k: {k2: v2 for k2, v2 in v.items() if not k2.startswith("_")}
                         for k, v in ep2022.items()},
        "power": powers,
        "extended_sample": {"offset_pp": round(offset, 4),
                            "overlap_months": len(ov), "results": ext_res},
    }
    path = os.path.join(HERE, "result.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\nЗаписано: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
