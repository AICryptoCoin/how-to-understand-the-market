"""Opis' ryadov: skachivaet klyuchevye pokazateli i proveryaet ih PO SODERZHIMOMU.

Двойное назначение:

1. **Проверка контура по содержимому, а не по коду ответа.** Источник считается
   рабочим только если тело распарсилось в ожидаемое число наблюдений ожидаемого
   типа и границы истории попали в заявленный диапазон. Это не педантизм:
   stooq на любой символ отдаёт HTTP 200 и правдоподобный размер, а телом идёт
   JavaScript-заглушка. Тест, который зелёный на заглушке, **хуже
   отсутствующего** — он превращает пропажу данных в тишину.

2. **Опись данных.** Глубина истории — главный ограничитель того, что вообще
   можно утверждать: на 3 годах ICE-спреда нельзя говорить о рецессиях, а на
   58 годах Philly Fed — можно.

Что проверяется по каждому ряду (всё обязательно, иначе строка красная):

* тело распарсилось в :class:`sources.Series`;
* число наблюдений не меньше ``min_obs`` — ловит усечения и заглушки;
* все значения — числа (``float``), а не строки и не ``NaN``;
* первое наблюдение не позже ``starts_by`` — ловит лицензионное усечение
  истории (именно так видно, что ICE-ряд начинается с 2023 года);
* последнее наблюдение не старше ``max_lag_days`` — ловит замороженные ряды
  (именно так видно, что ``USSLIND`` мёртв с 2020 года).

Запуск::

    python smoke.py                # с кэшем (быстро)
    python smoke.py --force        # заново по сети
    python smoke.py --only curve   # только группа
    python smoke.py --list         # перечислить группы
    python smoke.py --verbose      # полные traceback'и

Вывод намеренно без символов вне cp1251: консоль этой машины в cp1251, и
падение на em-dash при печати отчёта — глупый способ потерять результат.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

import sources as S

# Отчёт не должен падать из-за кодировки консоли.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


@dataclass(frozen=True)
class Check:
    """Один ряд описи вместе с ожиданиями, по которым он проверяется."""

    group: str
    label: str
    key: str                       # тег нужного ключа, "-" если не нужен
    fn: Callable[[], S.Series]
    min_obs: int                   # минимум наблюдений
    starts_by: str                 # первое наблюдение не позже этой даты
    max_lag_days: int              # последнее наблюдение не старше N дней


def _curve(tenor: str, kind: str = "nominal", first_year: int = 1990):
    def go() -> S.Series:
        years = list(range(first_year, date.today().year + 1))
        return S.treasury_curve(kind, years=years)[tenor]
    return go


def _shiller_cape() -> S.Series:
    """CAPE Шиллера как Series.

    В описи он стоит не ради самого CAPE, а как страж свежести: прямая ссылка
    на `ie_data.xls` без UUID отдаёт корректный, но устаревший на 22 месяца
    файл. Такую подмену видно только по последнему наблюдению.
    """
    sheets = S.shiller()
    rows = sheets.get("Data") or next(iter(sheets.values()))
    # Шапка многострочная, и слово "CAPE" встречается в ДВУХ колонках: у самого
    # CAPE (подписан "P/E10 or" + "CAPE") и у "Excess CAPE Yield". Поиск по
    # слову "CAPE" даёт вторую и молча возвращает доходность вместо индекса
    # (0.014 вместо 37). Опознаём по метке "P/E10", исключая вариант "TR".
    width = max(len(r) for r in rows[:12])
    joined = {
        c: " ".join(str(r[c]) for r in rows[:12]
                    if c < len(r) and isinstance(r[c], str)).upper()
        for c in range(width)
    }
    col = next(c for c, text in joined.items()
               if "P/E10" in text and "TR " not in text)
    hdr = max(i for i, r in enumerate(rows[:12])
              if col < len(r) and isinstance(r[col], str))

    s = S.Series(series_id="SHILLER-CAPE", source="Shiller (shillerdata.com)",
                 title="CAPE (Shiller P/E)", freq="M", units="ratio",
                 fetched_at=S._now())
    for r in rows[hdr + 1:]:
        # Дата лежит СТРОКОЙ формата "ГГГГ.ММ" ("2026.07"), а не числом.
        stamp = S._num(r[0]) if r else None
        if stamp is None:
            continue
        year, month = int(stamp), round(round(stamp - int(stamp), 4) * 100)
        if not (1871 <= year <= 2100 and 1 <= month <= 12):
            continue
        # Ранние CAPE помечены "NA": индекс требует 10 лет предыстории и
        # реально начинается с 1881-01, хотя таблица идёт с 1871-01.
        val = S._num(r[col]) if col < len(r) else None
        if val is None:
            continue
        s.dates.append(date(year, month, 1).isoformat())
        s.values.append(val)
    return s


# Ожидания ниже — фактические границы, снятые с серверов 2026-07-27, с запасом
# вниз по числу наблюдений. Если строка краснеет, это не «тест сломался»:
# это либо источник изменился, либо историю усекли — и то, и то надо смотреть.
CHECKS: list[Check] = [
    # --- труд ---------------------------------------------------------------
    Check("labour", "Bezrabotica (U-3)", "FRED",
          lambda: S.fred("UNRATE"), 900, "1948-01-01", 75),
    Check("labour", "Pervichnye zayavki na posobie", "FRED",
          lambda: S.fred("ICSA"), 3000, "1967-01-07", 21),
    Check("labour", "Zanyatost' vne sel'hoz (NFP)", "FRED",
          lambda: S.fred("PAYEMS"), 1000, "1939-01-01", 75),

    # --- жильё --------------------------------------------------------------
    Check("housing", "NAHB HMI (kompozit)", "-",
          lambda: S.nahb_hmi("t2")["HMI"], 480, "1985-01-01", 60),
    Check("housing", "NAHB: trafik pokupateley", "-",
          lambda: S.nahb_hmi("t3")["Traffic of Prospective Buyers"],
          480, "1985-01-01", 60),
    Check("housing", "Razresheniya na stroitel'stvo", "FRED",
          lambda: S.fred("PERMIT"), 780, "1960-01-01", 75),
    Check("housing", "Nachala stroitel'stva", "FRED",
          lambda: S.fred("HOUST"), 790, "1959-01-01", 75),
    Check("housing", "Razresheniya (pervoistochnik Census)", "CENSUS",
          lambda: S.census_eits("resconst", category_code="APERMITS",
                                data_type_code="TOTAL", seasonally_adj="yes",
                                time="from 1990-01")["resconst:APERMITS:TOTAL:US:SA"],
          420, "1990-01-01", 75),

    # --- цены ---------------------------------------------------------------
    Check("prices", "CPI, vse stat'i", "FRED",
          lambda: S.fred("CPIAUCSL"), 930, "1947-01-01", 75),
    Check("prices", "Core CPI", "FRED",
          lambda: S.fred("CPILFESL"), 810, "1957-01-01", 75),
    Check("prices", "Core PCE (deflyator)", "FRED",
          lambda: S.fred("PCEPILFE"), 790, "1959-01-01", 100),
    Check("prices", "Core PCE (pervoistochnik BEA)", "BEA",
          lambda: S.bea("T20804", frequency="M")["DPCCRG"], 790, "1959-01-01", 100),

    # --- производство -------------------------------------------------------
    Check("output", "Promyshlennoe proizvodstvo", "FRED",
          lambda: S.fred("INDPRO"), 1270, "1919-01-01", 75),
    Check("output", "Zagruzka moshchnostey", "FRED",
          lambda: S.fred("TCU"), 700, "1967-01-01", 75),

    # --- кривая доходности --------------------------------------------------
    Check("curve", "UST 3 mesyaca", "-", _curve("3 Mo"), 9000, "1990-01-02", 14),
    Check("curve", "UST 2 goda", "-", _curve("2 Yr"), 9000, "1990-01-02", 14),
    Check("curve", "UST 10 let", "-", _curve("10 Yr"), 9000, "1990-01-02", 14),
    Check("curve", "UST 30 let", "-", _curve("30 Yr"), 8000, "1990-01-02", 14),
    Check("curve", "Spred 10Y-2Y", "FRED",
          lambda: S.fred("T10Y2Y"), 12000, "1976-06-01", 14),
    Check("curve", "Spred 10Y-3M", "FRED",
          lambda: S.fred("T10Y3M"), 11000, "1982-01-04", 14),
    Check("curve", "TIPS 10 let (real'naya stavka)", "-",
          _curve("10 YR", "real", 2003), 5800, "2003-01-02", 14),
    Check("curve", "Breakeven 5 let", "FRED",
          lambda: S.fred("T5YIE"), 5800, "2003-01-02", 14),
    Check("curve", "Breakeven 10 let", "FRED",
          lambda: S.fred("T10YIE"), 5800, "2003-01-02", 14),
    Check("curve", "Premiya za srok ACM, 10 let", "-",
          lambda: S.nyfed_acm("daily")["ACMTP10"], 16000, "1961-06-14", 21),

    # --- рынки --------------------------------------------------------------
    Check("markets", "Indeks dollara DXY", "-",
          lambda: S.yahoo("DX-Y.NYB"), 14000, "1971-01-04", 14),
    Check("markets", "Zoloto (fyuchers)", "-",
          lambda: S.yahoo("GC=F"), 6400, "2000-08-30", 14),
    Check("markets", "Med' (fyuchers)", "-",
          lambda: S.yahoo("HG=F"), 6400, "2000-08-30", 14),
    Check("markets", "Neft' WTI", "FRED",
          lambda: S.fred("DCOILWTICO"), 10000, "1986-01-02", 21),
    Check("markets", "S&P 500", "-",
          lambda: S.yahoo("^GSPC"), 24000, "1927-12-30", 14),
    Check("markets", "Russell 2000", "-",
          lambda: S.yahoo("^RUT"), 9600, "1987-09-10", 14),
    Check("markets", "Nasdaq Composite", "-",
          lambda: S.yahoo("^IXIC"), 13800, "1971-02-05", 14),
    # CAPE стоит в описи как страж свежести: прямая ссылка без UUID отдаёт
    # корректный, но отставший на 22 месяца файл, и видно это только по
    # последнему наблюдению. Начало 1881-01, а не 1871-01: индексу нужно
    # 10 лет предыстории, и ранние строки помечены "NA".
    Check("markets", "CAPE Shillera (strazh svezhesti)", "-",
          _shiller_cape, 1700, "1881-01-01", 75),

    # --- индексы состояния экономики и панели-замена ISM --------------------
    Check("activity", "Indeks delovyh usloviy ADS", "-",
          lambda: S.philfed_ads(), 24000, "1960-03-01", 21),
    Check("activity", "Philly Fed: obshchaya aktivnost'", "-",
          lambda: S.philfed_mbos()["GAC"], 690, "1968-05-01", 45),
    Check("activity", "Philly Fed: budushchie novye zakazy", "-",
          lambda: S.philfed_mbos()["NOF"], 690, "1968-05-01", 45),
    Check("activity", "Empire State: obshchie usloviya", "-",
          lambda: S.empire_state()["GACDISA"], 290, "2001-07-31", 45),
    Check("activity", "Dallas Fed: rost novyh zakazov", "FRED",
          lambda: S.fred("GROSAMFRBDAL"), 255, "2004-06-01", 75),
    Check("activity", "Richmond Fed: kompozit", "-",
          lambda: S.richmond_fed()["sa_mfg_composite"], 380, "1993-11-01", 75),
    Check("activity", "Kansas City Fed: kompozit", "-",
          lambda: S.kansascity_fed()[
              "Versus a Month Ago (seasonally adjusted) / Composite Index"],
          290, "2001-07-01", 45),
    Check("activity", "CFNAI (Chikago)", "FRED",
          lambda: S.fred("CFNAI"), 700, "1967-03-01", 75),

    # --- датировка цикла ----------------------------------------------------
    Check("cycle", "Recessii NBER (USREC)", "FRED",
          lambda: S.fred("USREC"), 2000, "1854-12-01", 75),
    # Даты объявлений Комитета NBER. Ряд событийный, а не наблюдаемый: пик
    # объявляют раз в десятилетие, поэтому max_lag_days здесь НЕ проверка
    # свежести (её тут просто не существует), а верхняя граница, за которой
    # молчание источника перестаёт быть нормой. Реальный контроль по
    # содержимому — min_obs и границы лага внутри самого загрузчика:
    # шесть объявленных пиков, каждый лаг в диапазоне 0..36 месяцев.
    # Значение ряда — лаг объявления в месяцах, и он же нужен задаче Z03.
    Check("cycle", "Obyavleniya NBER: piki", "-",
          lambda: S.nber_announcements()["peaks"], 6, "1980-01-01", 5000),
]

GROUP_ORDER = ["labour", "housing", "prices", "output", "curve", "markets",
               "activity", "cycle"]


def _have_key(tag: str) -> bool:
    if tag in ("-", ""):
        return True
    try:
        S._key(tag if tag.endswith("_API_KEY") else f"{tag}_API_KEY")
        return True
    except S.MissingKey:
        return False


def validate(c: Check, s: S.Series) -> str | None:
    """Вернуть причину провала либо None, если ряд прошёл по содержимому."""
    if not isinstance(s, S.Series):
        return f"vernulsya {type(s).__name__}, a ne Series"
    obs = s.observed
    if not obs:
        return "ryad pust (ni odnogo znacheniya) - vozmozhno, telom prishla zaglushka"
    if len(obs) < c.min_obs:
        return f"nablyudeniy {len(obs)}, ozhidalos' >= {c.min_obs}"
    bad = next((v for _, v in obs
                if not isinstance(v, float) or math.isnan(v) or math.isinf(v)), None)
    if bad is not None or any(not isinstance(v, float) for _, v in obs):
        return "sredi znacheniy est' ne-chisla (NaN/inf/str)"
    first, last = obs[0][0], obs[-1][0]
    if first > c.starts_by:
        return (f"istoriya nachinaetsya {first}, a dolzhna ne pozzhe {c.starts_by} "
                f"- pohozhe na usechenie")
    # Сверка с паспортом ряда. FRED в конверте наблюдений отдаёт ранние строки
    # с value="." — если считать их за данные, ряд «начинается» на годы раньше,
    # чем на самом деле (AWHMAN: 1134 строки против 1050 чисел, 1932 против
    # 1939; NEWORDER: 700 против 412, 1968 против 1992). Первое ЧИСЛОВОЕ
    # наблюдение обязано совпасть с observation_start из паспорта.
    declared = (s.meta or {}).get("observation_start")
    if declared and first != declared:
        return (f"pervoe chislovoe nablyudenie {first}, a v pasporte ryada "
                f"observation_start={declared} - libo v ryad popali dyry "
                f"(value=\".\"), libo istoriya usechena")
    lag = (date.today() - datetime.strptime(last, "%Y-%m-%d").date()).days
    if lag > c.max_lag_days:
        return (f"poslednee nablyudenie {last} ({lag} dn. nazad), dopustimo "
                f"{c.max_lag_days} - ryad moglo zamorozit'")
    return None


def _ascii(text: str) -> str:
    """Только ASCII: сообщения об ошибках приходят и из sources.py, где текст
    русский, а консоль этой машины в cp1251 — без этого отчёт о падении сам
    превращается в мусор."""
    return text.encode("ascii", "replace").decode("ascii")


def selftest() -> int:
    """Негативный контроль: проверить, что детектор ЛОВИТ known-bad случаи.

    Таблица из одних зелёных строк без этой проверки неотличима от сломанного
    детектора. Здесь три реальных класса провала, каждый с известным ответом.
    """
    print("SELFTEST: detektor dolzhen POYMAT' kazhdyy sluchay nizhe\n")
    cases: list[tuple[str, Callable[[], str | None]]] = [
        ("JS-zaglushka vmesto dannyh (stooq, otdaet HTTP 200)",
         lambda: _stub_case()),
        ("licenzionnoe usechenie istorii (ICE HY OAS s 2023)",
         lambda: validate(Check("x", "ICE", "FRED",
                                lambda: S.fred("BAMLH0A0HYM2"),
                                5000, "1996-12-31", 14), S.fred("BAMLH0A0HYM2"))),
        ("zamorozhennyy ryad (USSLIND, mertv s 2020-02)",
         lambda: validate(Check("x", "USSLIND", "FRED",
                                lambda: S.fred("USSLIND"),
                                400, "1982-01-01", 75), S.fred("USSLIND"))),
        ("Yahoo range=max molcha ponizhaet granulyarnost' (^GSPC)",
         lambda: _granularity_case()),
        ("dyry value='.' v konverte FRED (NEWORDER: 700 strok, 412 chisel)",
         lambda: validate(Check("x", "NEWORDER", "FRED",
                                lambda: S.fred("NEWORDER"),
                                400, "1968-02-01", 75), S.fred("NEWORDER"))),
        ("HTML vmesto tablicy pri 200 (podmena po signature)",
         lambda: _html_instead_of_spreadsheet()),
        ("ne ta stranica NBER pri 200 i 78 KB (obyavleniy v tele net)",
         lambda: _nber_wrong_page()),
    ]
    caught = 0
    for name, run in cases:
        try:
            reason = run()
        except Exception as exc:                              # noqa: BLE001
            reason = f"{type(exc).__name__}: {exc}"
        if reason:
            caught += 1
            print(f"  POYMAN  {name}\n          -> {_ascii(str(reason))[:110]}")
        else:
            print(f"  PROPUSK {name}  <-- DETEKTOR SLOMAN")
    print(f"\npoymano {caught} iz {len(cases)}")
    return 0 if caught == len(cases) else 1


def _granularity_case() -> str | None:
    """``range=max`` игнорирует ``interval`` и отдаёт квартальные точки."""
    try:
        s = S.yahoo("^GSPC", range_="max", interval="1d")
    except S.FetchError as exc:
        return f"FetchError: {exc}"
    return validate(Check("x", "^GSPC", "-", lambda: s, 24000, "1927-12-30", 14), s)


def _html_instead_of_spreadsheet() -> str | None:
    """Сервер отвечает **200** и присылает HTML там, где ожидался архив.

    Настоящий случай, не искусственный: этот путь к обзорам ЕК отдаёт
    200 и 68 154 байта с сигнатурой ``<!DO``. Ни код, ни размер подмену не
    выдают — только сигнатура. Ровно поэтому проверка идёт по телу.
    """
    try:
        body = S.fetch("https://ec.europa.eu/economy_finance/db_indicators/"
                       "surveys/documents/series/main_indicators_nace2.zip",
                       tag="selftest-html", max_age=timedelta(hours=12))
    except S.FetchError as exc:
        return f"FetchError na zagruzke: {exc}"
    if body[:2] == b"PK":
        return None            # внезапно приехал настоящий архив - не поймали
    try:
        S._spreadsheet(body)
    except Exception as exc:                                  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return None


def _nber_wrong_page() -> str | None:
    """Родительский раздел NBER вместо страницы объявлений: **200 и ~78 КБ**.

    Реальная ошибка на один сегмент пути, а не искусственная: `/business-cycle-dating`
    отдаёт полноценную страницу нужного раздела, в которой нет ни одной строки
    объявления. Ни код, ни размер, ни сигнатура `<!DOCTYPE html>` подмену
    не выдают — выдаёт только число разобранных поворотных точек.
    """
    import html as _html
    import re as _re
    try:
        body = S.fetch("https://www.nber.org/research/business-cycle-dating",
                       tag="selftest-nber", max_age=timedelta(hours=12))
    except S.FetchError as exc:
        return f"FetchError na zagruzke: {exc}"
    text = _re.sub(r"(?is)<(script|style).*?</\1>", " ", body.decode("utf-8", "replace"))
    text = _re.sub(r"[ \t\r\n]+", " ", _html.unescape(_re.sub(r"<[^>]+>", "|", text)))
    rows = S._NBER_ROW.findall(text)
    peaks = {(m, y) for _, _, _, m, y, k in rows if k.lower() == "peak"}
    if len(peaks) < 6:
        return (f"telo {len(body)} bayt, HTTP 200, a obyavleniy razobrano "
                f"{len(peaks)} iz >= 6")
    return None


def _stub_case() -> str | None:
    """stooq отдаёт 200 и правдоподобную длину, телом — JavaScript-заглушка."""
    try:
        s = S.stooq("^spx")
    except S.UpstreamBlocked as exc:
        return f"UpstreamBlocked: {exc}"
    return validate(Check("x", "stooq", "-", lambda: s, 5000, "2000-01-01", 14), s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Opis' dostupnyh ryadov")
    ap.add_argument("--force", action="store_true", help="ignorirovat' kesh")
    ap.add_argument("--only", metavar="GROUP", help="tol'ko ukazannaya gruppa")
    ap.add_argument("--list", action="store_true", help="perechislit' gruppy")
    ap.add_argument("--verbose", action="store_true", help="polnyy traceback")
    ap.add_argument("--selftest", action="store_true",
                    help="proverit', chto detektor lovit known-bad sluchai")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.list:
        for g in GROUP_ORDER:
            print(f"  {g:10} {sum(1 for c in CHECKS if c.group == g)} ryadov")
        return 0

    checks = [c for c in CHECKS if not args.only or c.group == args.only]
    if not checks:
        print(f"gruppa {args.only!r} ne naydena; sm. --list", file=sys.stderr)
        return 2
    if args.force:
        S.FORCE_ALL = True

    head = (f"{'pokazatel':38} {'istochnik':22} {'ch':2} {'n':>7} "
            f"{'pervaya':10} {'poslednyaya':11} {'poslednee':>13}")
    print(head)
    print("-" * len(head))

    ok = failed = nokey = 0
    problems: list[tuple[str, str]] = []
    t0 = time.time()
    current = None

    for c in checks:
        if c.group != current:
            current = c.group
            print(f"\n[{c.group}]")
        if not _have_key(c.key):
            nokey += 1
            print(f"{c.label:38} NET KLYUCHA ({c.key})")
            continue
        try:
            s = c.fn()
            reason = validate(c, s)
            if reason:
                failed += 1
                problems.append((c.label, _ascii(reason)))
                print(f"{c.label:38} NE PROSHEL: {_ascii(reason)[:58]}")
                continue
            obs = s.observed
            ok += 1
            print(f"{c.label:38} {s.source[:22]:22} {s.freq or '?':2} "
                  f"{len(obs):>7} {obs[0][0]:10} {obs[-1][0]:11} "
                  f"{obs[-1][1]:>13,.4g}")
        except Exception as exc:                              # noqa: BLE001
            failed += 1
            problems.append((c.label, _ascii(f"{type(exc).__name__}: {exc}")))
            print(f"{c.label:38} OSHIBKA: {type(exc).__name__}: {_ascii(str(exc))[:44]}")
            if args.verbose:
                traceback.print_exc()

    print("\n" + "=" * len(head))
    print(f"proshli po soderzhimomu: {ok} | ne proshli: {failed} | "
          f"bez klyucha: {nokey} | {time.time() - t0:.1f} s")
    print(f"kesh: {S.CACHE_DIR}")
    if problems:
        print("\nCHTO NE PROSHLO (etot spisok vazhnee pervogo):")
        for label, msg in problems:
            print(f"  - {label}: {msg[:150]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
