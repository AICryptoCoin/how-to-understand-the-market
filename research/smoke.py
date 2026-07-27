"""Опись рядов: скачивает ключевые показатели и печатает, чем мы располагаем.

Двойное назначение:

1. **Проверка контура.** Если что-то в ``sources.py`` сломалось или источник
   изменил формат — это видно здесь, а не посреди проверки главы.
2. **Опись данных.** По каждому ряду печатается число наблюдений, первая и
   последняя дата и последнее значение. Глубина истории — главный ограничитель
   того, что вообще можно утверждать: на 3 годах ICE-спреда нельзя говорить о
   рецессиях, а на 58 годах Philly Fed — можно.

Запуск::

    python smoke.py                # с кэшем (быстро)
    python smoke.py --force        # заново по сети
    python smoke.py --only curve   # только группа
    python smoke.py --list         # перечислить группы

Ряды, требующие ключа, помечены в колонке «ключ». Если ключа нет, строка
получает статус ``НЕТ КЛЮЧА`` и прогон продолжается — контур без ключей
остаётся проверяемым.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from typing import Callable

import sources as S

# --------------------------------------------------------------------------- #
# Опись: (группа, показатель, нужный ключ, функция -> Series)
# --------------------------------------------------------------------------- #

Check = tuple[str, str, str, Callable[[], S.Series]]


def _curve(tenor: str) -> Callable[[], S.Series]:
    def go() -> S.Series:
        years = list(range(1990, __import__("datetime").date.today().year + 1))
        return S.treasury_curve("nominal", years=years)[tenor]
    return go


def _real_curve(tenor: str) -> Callable[[], S.Series]:
    def go() -> S.Series:
        years = list(range(2003, __import__("datetime").date.today().year + 1))
        return S.treasury_curve("real", years=years)[tenor]
    return go


CHECKS: list[Check] = [
    # --- труд ---------------------------------------------------------------
    ("labour", "Безработица (U-3)", "FRED", lambda: S.fred("UNRATE")),
    ("labour", "Первичные заявки на пособие", "FRED", lambda: S.fred("ICSA")),
    ("labour", "Занятость вне сельского хоз-ва (NFP)", "FRED", lambda: S.fred("PAYEMS")),

    # --- жильё --------------------------------------------------------------
    ("housing", "NAHB HMI (композит)", "—", lambda: S.nahb_hmi("t2")["HMI"]),
    ("housing", "NAHB: трафик покупателей", "—",
     lambda: S.nahb_hmi("t3")["Traffic of Prospective Buyers"]),
    ("housing", "Разрешения на строительство", "FRED", lambda: S.fred("PERMIT")),
    ("housing", "Начала строительства", "FRED", lambda: S.fred("HOUST")),
    ("housing", "Разрешения (первоисточник Census)", "CENSUS",
     lambda: S.census_eits("resconst", category_code="APERMITS",
                           data_type_code="TOTAL", seasonally_adj="yes",
                           time="from 1990-01")["resconst:APERMITS:TOTAL:US:SA"]),

    # --- цены ---------------------------------------------------------------
    ("prices", "CPI, все статьи", "FRED", lambda: S.fred("CPIAUCSL")),
    ("prices", "Core CPI", "FRED", lambda: S.fred("CPILFESL")),
    ("prices", "Core PCE (базовый дефлятор)", "FRED", lambda: S.fred("PCEPILFE")),
    ("prices", "Core PCE (первоисточник BEA)", "BEA",
     lambda: S.bea("T20804", frequency="M")["DPCCRG"]),

    # --- производство -------------------------------------------------------
    ("output", "Промышленное производство", "FRED", lambda: S.fred("INDPRO")),
    ("output", "Загрузка мощностей", "FRED", lambda: S.fred("TCU")),

    # --- кривая доходности --------------------------------------------------
    ("curve", "UST 3 месяца", "—", _curve("3 Mo")),
    ("curve", "UST 2 года", "—", _curve("2 Yr")),
    ("curve", "UST 10 лет", "—", _curve("10 Yr")),
    ("curve", "UST 30 лет", "—", _curve("30 Yr")),
    ("curve", "Спред 10Y-2Y", "FRED", lambda: S.fred("T10Y2Y")),
    ("curve", "Спред 10Y-3M", "FRED", lambda: S.fred("T10Y3M")),
    ("curve", "TIPS 10 лет (реальная ставка)", "—", _real_curve("10 YR")),
    ("curve", "Breakeven 5 лет", "FRED", lambda: S.fred("T5YIE")),
    ("curve", "Breakeven 10 лет", "FRED", lambda: S.fred("T10YIE")),
    ("curve", "Премия за срок ACM, 10 лет", "—",
     lambda: S.nyfed_acm("daily")["ACMTP10"]),

    # --- рынки --------------------------------------------------------------
    ("markets", "Индекс доллара DXY", "—", lambda: S.yahoo("DX-Y.NYB")),
    ("markets", "Золото (фьючерс)", "—", lambda: S.yahoo("GC=F")),
    ("markets", "Медь (фьючерс)", "—", lambda: S.yahoo("HG=F")),
    ("markets", "Нефть WTI", "FRED", lambda: S.fred("DCOILWTICO")),
    ("markets", "S&P 500", "—", lambda: S.yahoo("^GSPC")),
    ("markets", "Russell 2000", "—", lambda: S.yahoo("^RUT")),
    ("markets", "Nasdaq Composite", "—", lambda: S.yahoo("^IXIC")),

    # --- индексы состояния экономики ---------------------------------------
    ("activity", "Индекс деловых условий ADS", "—", lambda: S.philfed_ads()),
    ("activity", "Philly Fed: общая активность (замена ISM)", "—",
     lambda: S.philfed_mbos()["GAC"]),
    ("activity", "Philly Fed: будущие новые заказы", "—",
     lambda: S.philfed_mbos()["NOF"]),
    ("activity", "CFNAI (Чикаго)", "FRED", lambda: S.fred("CFNAI")),
]

GROUP_ORDER = ["labour", "housing", "prices", "output", "curve", "markets", "activity"]


# --------------------------------------------------------------------------- #

def _have_key(tag: str) -> bool:
    if tag in ("—", ""):
        return True
    try:
        S._key(tag if tag.endswith("_API_KEY") else f"{tag}_API_KEY")
        return True
    except S.MissingKey:
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Опись доступных рядов")
    ap.add_argument("--force", action="store_true", help="игнорировать кэш")
    ap.add_argument("--only", metavar="GROUP", help="только указанная группа")
    ap.add_argument("--list", action="store_true", help="перечислить группы")
    ap.add_argument("--verbose", action="store_true", help="полный traceback ошибок")
    args = ap.parse_args(argv)

    if args.list:
        for g in GROUP_ORDER:
            n = sum(1 for c in CHECKS if c[0] == g)
            print(f"  {g:10} {n} рядов")
        return 0

    checks = [c for c in CHECKS if not args.only or c[0] == args.only]
    if not checks:
        print(f"группа {args.only!r} не найдена; см. --list", file=sys.stderr)
        return 2

    if args.force:
        S.FORCE_ALL = True

    head = (f"{'показатель':44} {'источник':22} {'ч':2} {'n':>7} "
            f"{'первая':10} {'последняя':10} {'последнее':>14}")
    print(head)
    print("-" * len(head))

    ok = failed = nokey = 0
    problems: list[tuple[str, str]] = []
    t0 = time.time()
    current_group = None

    for group, label, keytag, fn in checks:
        if group != current_group:
            current_group = group
            print(f"\n[{group}]")
        if not _have_key(keytag):
            nokey += 1
            print(f"{label:44} {'НЕТ КЛЮЧА (' + keytag + ')':22}")
            continue
        try:
            s = fn()
            first, last = s.first(), s.last()
            if not first or not last:
                raise RuntimeError("ряд пуст (нет ни одного значения)")
            ok += 1
            print(f"{label:44} {s.source[:22]:22} {s.freq or '?':2} "
                  f"{len(s.observed):>7} {first[0]:10} {last[0]:10} "
                  f"{last[1]:>14,.4g}")
        except Exception as exc:                              # noqa: BLE001
            failed += 1
            problems.append((label, f"{type(exc).__name__}: {exc}"))
            print(f"{label:44} ОШИБКА: {type(exc).__name__}: {str(exc)[:60]}")
            if args.verbose:
                traceback.print_exc()

    print("\n" + "=" * len(head))
    print(f"успешно: {ok} | ошибок: {failed} | без ключа: {nokey} "
          f"| {time.time() - t0:.1f} с | кэш: {S.CACHE_DIR}")
    if problems:
        print("\nчто не отдалось:")
        for label, msg in problems:
            print(f"  - {label}: {msg[:160]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
