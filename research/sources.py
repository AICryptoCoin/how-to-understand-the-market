"""Единый модуль загрузки данных для проверки утверждений книги «Как понимать рынок».

Задача модуля — дать одну функцию на источник, чтобы глава книги могла
сослаться на воспроизводимый код, а не на авторитет автора курса.

Принципы
--------
1. **Только стандартная библиотека** (+ ``certifi`` для сертификатов).
   На машине разработки нет ни ``pandas``, ни ``requests``; модуль обязан
   работать в этом окружении. Если ``pandas`` появится — он не нужен:
   :class:`Series` сознательно тривиальна и легко превращается во что угодно.
2. **Ключи только из окружения.** Никогда не хардкодятся, никогда не пишутся
   в лог, никогда не попадают в кэш-файлы (URL кэшируется с вырезанным ключом).
3. **Кэш на диске с отметкой времени.** Повторный прогон не бьёт по сети.
4. **Вежливость к серверам.** Пауза между запросами к одному хосту, повтор с
   экспоненциальной задержкой, честный User-Agent.
5. **Единый табличный формат.** Всё возвращается как :class:`Series`
   (дата, значение + частота, единицы) либо как ``dict[str, Series]``.

SSL
---
На части машин (в т.ч. на этой) системное хранилище сертификатов неполное, и
запросы к CFTC/BIS падают с ``CERTIFICATE_VERIFY_FAILED`` — это не блокировка,
а цепочка сертификатов. Поэтому по умолчанию используется хранилище ``certifi``.

Карта источников с подтверждённой глубиной истории и лицензионными
ограничениями — в ``SOURCES.md`` рядом с этим файлом.
"""

from __future__ import annotations

import base64
import csv
import html
import io
import json
import os
import re
import ssl
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Iterator, Sequence

__all__ = [
    "Series", "MissingKey", "FetchError", "UpstreamBlocked",
    "fred", "fred_meta", "fred_search",
    "treasury_curve", "yahoo", "stooq",
    "nyfed_acm", "nyfed_reference_rate", "nyfed_sce",
    "philfed_ads", "philfed_mbos", "philfed_nbos", "philfed_spf", "philfed_realtime",
    "empire_state", "richmond_fed", "kansascity_fed", "cfnai", "atlanta_gdpnow",
    "cleveland_inflation_expectations",
    "bls", "bea", "census_eits", "census_variables", "nahb_hmi", "NAHB_TABLES",
    "ecb", "eurostat", "boe", "bis", "oecd_cli", "worldbank", "dbnomics",
    "ofr_fsi", "cftc_cot", "ken_french", "shiller", "damodaran", "eia",
    "coingecko", "binance",
    "cache_dir", "clear_cache",
]

# --------------------------------------------------------------------------- #
# Конфигурация
# --------------------------------------------------------------------------- #

RESEARCH_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.environ.get("RESEARCH_CACHE_DIR") or os.path.join(RESEARCH_DIR, ".cache")
DEFAULT_MAX_AGE = timedelta(hours=12)

#: Глобальный обход кэша. Взводится ``smoke.py --force``; действует и на те
#: источники, что передают свой ``max_age`` (Ken French, Shiller, Damodaran,
#: паспорта FRED) — иначе «--force» обновлял бы их не полностью.
FORCE_ALL = False

# Заголовки HTTP кодируются latin-1 — кириллице здесь не место.
#
# Переопределяется переменной окружения RESEARCH_USER_AGENT. Это не украшение:
# **www.bls.gov отдаёт 403, если в User-Agent нет адреса электронной почты.**
# Проверено прямым перебором — дело не в длине строки и не в кавычках:
#   "...(contact: github.com/loodo)"     -> 403   (ссылка вместо почты)
#   "...(educational research)"          -> 403   (контакта нет вовсе)
#   "...(contact: name@example.com)"     -> 200
# По умолчанию почта не подставляется: UA уходит на каждый сервер, и зашивать
# сюда чей-то личный адрес нельзя. Нужен www.bls.gov — задайте свой:
#   set RESEARCH_USER_AGENT=my-research/1.0 (you@example.com)
# Данные BLS при этом доступны и без него: api.bls.gov работает с общим UA,
# почта нужна только для HTML-страниц сайта.
USER_AGENT = os.environ.get("RESEARCH_USER_AGENT") or (
    "loodo-market-cycle-research/1.0 "
    "(educational research for the book 'How to Read the Market'; "
    "non-commercial)"
)

#: Минимальная пауза между двумя запросами к одному хосту, сек.
HOST_MIN_INTERVAL = 0.6
#: Сколько раз повторять при обрыве/5xx/429.
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 45

_KEY_REGISTRATION = {
    "FRED_API_KEY": "https://fred.stlouisfed.org/docs/api/api_key.html (бесплатно, мгновенно)",
    "BEA_API_KEY": "https://apps.bea.gov/API/signup/ (бесплатно, ключ приходит письмом)",
    "CENSUS_API_KEY": "https://api.census.gov/data/key_signup.html (бесплатно)",
    "EIA_API_KEY": "https://www.eia.gov/opendata/register.php (бесплатно)",
}


class MissingKey(RuntimeError):
    """Нет обязательного ключа в окружении."""


class FetchError(RuntimeError):
    """Сеть/сервер не отдали данные после всех повторов."""


class UpstreamBlocked(FetchError):
    """Источник ответил, но отдал анти-бот заглушку вместо данных."""


# --------------------------------------------------------------------------- #
# SSL-контекст (см. модульный docstring)
# --------------------------------------------------------------------------- #

def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # noqa: PLC0415
    except ImportError:  # pragma: no cover - certifi есть в целевом окружении
        sys.stderr.write(
            "[sources] ВНИМАНИЕ: certifi не установлен, используется системное "
            "хранилище сертификатов. Часть источников (CFTC, BIS) может падать с "
            "CERTIFICATE_VERIFY_FAILED. Лечится: pip install certifi\n"
        )
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


SSL_CONTEXT = _ssl_context()


# --------------------------------------------------------------------------- #
# Ключи из окружения
# --------------------------------------------------------------------------- #

_env_cache: dict[str, str] | None = None


def _env_files() -> list[str]:
    """Кандидаты на .env.research: рядом с модулем и вверх по дереву до корня репо."""
    out = []
    d = RESEARCH_DIR
    for _ in range(8):
        out.append(os.path.join(d, ".env.research"))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    out.append(os.path.join(os.getcwd(), ".env.research"))
    return out


def _load_env() -> dict[str, str]:
    global _env_cache
    if _env_cache is not None:
        return _env_cache
    found: dict[str, str] = {}
    for path in _env_files():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    found.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            continue
        break  # первый найденный файл побеждает
    _env_cache = found
    return found


def _key(name: str) -> str:
    """Ключ из окружения либо .env.research. Значение никогда не логируется."""
    val = os.environ.get(name) or _load_env().get(name)
    if not val:
        where = _KEY_REGISTRATION.get(name, "см. документацию источника")
        raise MissingKey(
            f"Нет {name}.\n"
            f"  Где взять: {where}\n"
            f"  Куда положить: переменная окружения {name}, либо строка\n"
            f"      {name}=<ключ>\n"
            f"  в файле .env.research в корне репозитория "
            f"(он в .gitignore — не коммить его).\n"
            f"  Что доступно без этого ключа — см. research/SOURCES.md."
        )
    return val


def _redact(url: str) -> str:
    """Убрать значения ключей из URL перед кэшированием/логом."""
    return re.sub(
        r"(?i)([?&](?:api_key|apikey|key|UserID|token)=)[^&]+",
        r"\1<redacted>",
        url,
    )


# --------------------------------------------------------------------------- #
# HTTP: троттлинг, повторы, кэш
# --------------------------------------------------------------------------- #

_host_lock = threading.Lock()
_host_last: dict[str, float] = {}

_ANTIBOT_MARKERS = (
    b"This site requires JavaScript to verify your browser",
    b"Checking if the site connection is secure",
    b"NAME=\"ROBOTS\" CONTENT=\"NOINDEX, NOFOLLOW\"",
)


def cache_dir() -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return CACHE_DIR


def clear_cache(prefix: str = "") -> int:
    """Удалить кэш целиком либо по префиксу источника. Возвращает число файлов."""
    if not os.path.isdir(CACHE_DIR):
        return 0
    n = 0
    for name in os.listdir(CACHE_DIR):
        if prefix and not name.startswith(prefix):
            continue
        try:
            os.remove(os.path.join(CACHE_DIR, name))
            n += 1
        except OSError:
            pass
    return n


def _cache_path(tag: str, url: str, payload: bytes | None) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(_redact(url).encode())
    if payload:
        h.update(b"|"); h.update(payload)
    return os.path.join(cache_dir(), f"{tag}-{h.hexdigest()[:24]}.json")


def _throttle(host: str) -> None:
    with _host_lock:
        last = _host_last.get(host, 0.0)
        wait = HOST_MIN_INTERVAL - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        _host_last[host] = time.monotonic()


def _raw_request(url: str, *, timeout: int, data: bytes | None,
                 headers: dict[str, str] | None) -> tuple[int, bytes]:
    hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs)
    _throttle(urllib.parse.urlparse(url).netloc)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            import gzip
            body = gzip.decompress(body)
        return resp.status, body


def fetch(url: str, *, tag: str = "misc", timeout: int = DEFAULT_TIMEOUT,
          data: bytes | None = None, headers: dict[str, str] | None = None,
          force: bool = False, max_age: timedelta | None = None,
          allow_status: Sequence[int] = (200,)) -> bytes:
    """Скачать URL с кэшем, троттлингом и повторами. Возвращает тело ответа.

    ``force=True`` игнорирует кэш и перезаписывает его.
    ``max_age`` — до какого возраста кэш считается свежим (по умолчанию 12 ч).
    """
    max_age = DEFAULT_MAX_AGE if max_age is None else max_age
    path = _cache_path(tag, url, data)

    if not force and not FORCE_ALL and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                blob = json.load(fh)
            age = datetime.now(timezone.utc) - datetime.fromisoformat(blob["fetched_at"])
            if age <= max_age:
                return base64.b64decode(blob["body"])
        except (OSError, ValueError, KeyError):
            pass  # битый кэш — перекачиваем

    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            status, body = _raw_request(url, timeout=timeout, data=data, headers=headers)
            if status in allow_status:
                if any(m in body[:4096] for m in _ANTIBOT_MARKERS):
                    raise UpstreamBlocked(
                        f"{_redact(url)} вернул анти-бот заглушку "
                        f"({len(body)} байт) вместо данных. Источник требует браузер; "
                        f"см. SOURCES.md — там указан рабочий заменитель."
                    )
                blob = {
                    "url": _redact(url),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "status": status,
                    "bytes": len(body),
                    "body": base64.b64encode(body).decode(),
                }
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(blob, fh)
                os.replace(tmp, path)
                return body
            if status in (429,) or 500 <= status < 600:
                last_err = FetchError(f"HTTP {status} от {_redact(url)}")
            else:
                raise FetchError(
                    f"HTTP {status} от {_redact(url)}: "
                    f"{body[:300].decode('utf-8', 'replace')}"
                )
        except UpstreamBlocked:
            raise
        except urllib.error.HTTPError as exc:
            body = b""
            try:
                body = exc.read()
            except Exception:
                pass
            if exc.code in (429,) or 500 <= exc.code < 600:
                last_err = FetchError(f"HTTP {exc.code} от {_redact(url)}")
            else:
                raise FetchError(
                    f"HTTP {exc.code} от {_redact(url)}: "
                    f"{body[:300].decode('utf-8', 'replace')}"
                ) from exc
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
            last_err = exc
        if attempt < MAX_RETRIES - 1:
            time.sleep(1.5 * (2 ** attempt))
    raise FetchError(f"Не удалось скачать {_redact(url)} за {MAX_RETRIES} попыток: {last_err}")


# --------------------------------------------------------------------------- #
# Единый табличный формат
# --------------------------------------------------------------------------- #

@dataclass
class Series:
    """Один ряд: даты + значения, плюс паспорт (частота, единицы, источник).

    ``dates`` — ISO-строки ``YYYY-MM-DD`` (месячные/квартальные ряды
    нормализуются на первый день периода, как это делает FRED).
    ``values`` — ``float`` либо ``None`` для пропусков.
    """

    series_id: str
    source: str
    title: str = ""
    freq: str = ""          # D | W | M | Q | A
    units: str = ""
    sa: str = ""            # SA | NSA | ""
    dates: list[str] = field(default_factory=list)
    values: list[float | None] = field(default_factory=list)
    fetched_at: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.dates)

    def __iter__(self) -> Iterator[tuple[str, float | None]]:
        return zip(self.dates, self.values)

    def rows(self) -> list[tuple[str, float | None]]:
        return list(zip(self.dates, self.values))

    @property
    def observed(self) -> list[tuple[str, float]]:
        """Только точки с непустым значением."""
        return [(d, v) for d, v in zip(self.dates, self.values) if v is not None]

    def first(self) -> tuple[str, float] | None:
        obs = self.observed
        return obs[0] if obs else None

    def last(self) -> tuple[str, float] | None:
        obs = self.observed
        return obs[-1] if obs else None

    def between(self, start: str | None = None, end: str | None = None) -> "Series":
        keep = [
            (d, v) for d, v in zip(self.dates, self.values)
            if (start is None or d >= start) and (end is None or d <= end)
        ]
        out = Series(**{**self.__dict__, "dates": [d for d, _ in keep],
                        "values": [v for _, v in keep]})
        return out

    def to_csv(self, path: str) -> str:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["date", self.series_id])
            w.writerows(self.rows())
        return path

    def describe(self) -> str:
        f, l = self.first(), self.last()
        if not f or not l:
            return f"{self.series_id}: пусто"
        return (f"{self.series_id}: n={len(self.observed)} {self.freq} "
                f"[{f[0]} .. {l[0]}] last={l[1]:g} {self.units}".rstrip())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _from_epoch(seconds: float) -> str:
    """Секунды Unix -> ISO-дата. Работает и с отрицательными значениями.

    ``datetime.fromtimestamp`` на Windows падает с ``OSError: [Errno 22]`` для
    дат до 1970 года, а Yahoo отдаёт историю индексов с 1920-х.
    """
    return (_EPOCH + timedelta(seconds=float(seconds))).date().isoformat()


def _num(x: Any) -> float | None:
    if x is None:
        return None
    s = str(x).strip().replace(",", "")
    if s in ("", ".", "-", "NA", "N/A", "ND", "null", "None", "*", "(NA)"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _iso(raw: Any, freq_hint: str = "") -> str | None:
    """Привести дату любого встреченного формата к ISO ``YYYY-MM-DD``."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # серийная дата Excel (1900-based, с багом 1900-02-29)
        n = int(raw)
        if 1 < n < 200000:
            base = date(1899, 12, 30)
            return (base + timedelta(days=n)).isoformat()
        return None
    s = str(raw).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%d %b %Y", "%Y-%m", "%b-%y",
                "%Y%m%d", "%d/%m/%Y", "%m/%d/%y",
                "%Y:%m:%d",   # ФРБ Филадельфии, ADS
                "%Y:%m"):
        try:
            d = datetime.strptime(s, fmt).date()
            if fmt == "%b-%y" and d.year > date.today().year + 5:
                d = d.replace(year=d.year - 100)
            return d.isoformat()
        except ValueError:
            continue
    m = re.fullmatch(r"(\d{4})[-/]?Q([1-4])", s, re.I)
    if m:
        return date(int(m.group(1)), (int(m.group(2)) - 1) * 3 + 1, 1).isoformat()
    # BEA: месяц как 2026M05, квартал как 2026Q1 (обработан выше)
    m = re.fullmatch(r"(\d{4})M(\d{2})", s, re.I)
    if m and 1 <= int(m.group(2)) <= 12:
        return date(int(m.group(1)), int(m.group(2)), 1).isoformat()
    m = re.fullmatch(r"(\d{4})(\d{2})", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return date(int(m.group(1)), int(m.group(2)), 1).isoformat()
    m = re.fullmatch(r"(\d{4})", s)
    if m and freq_hint.upper().startswith("A"):
        return date(int(m.group(1)), 1, 1).isoformat()
    return None


# --------------------------------------------------------------------------- #
# Парсеры форматов: CSV, XLSX (zip+XML), XLS (OLE2+BIFF8)
# --------------------------------------------------------------------------- #

def _rows_from_csv(body: bytes, *, encoding: str = "utf-8",
                   delimiter: str = ",", skip: int = 0) -> list[list[str]]:
    text = body.decode(encoding, "replace")
    if text and text[0] == "﻿":
        text = text[1:]
    rdr = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in rdr]
    return rows[skip:]


def _xlsx_sheets(body: bytes) -> dict[str, list[list[Any]]]:
    """Прочитать .xlsx (zip + SpreadsheetML) стандартной библиотекой."""
    import xml.etree.ElementTree as ET

    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    zf = zipfile.ZipFile(io.BytesIO(body))

    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in root.findall(f"{NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))

    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {r.get("Id"): r.get("Target") for r in rels}

    out: dict[str, list[list[Any]]] = {}
    for sh in wb.iter(f"{NS}sheet"):
        name = sh.get("name") or ""
        target = rid_to_target.get(sh.get(f"{RNS}id"), "")
        member = "xl/" + target.lstrip("/").removeprefix("xl/")
        if member not in zf.namelist():
            continue
        grid: dict[tuple[int, int], Any] = {}
        root = ET.fromstring(zf.read(member))
        for c in root.iter(f"{NS}c"):
            ref = c.get("r") or ""
            m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
            if not m:
                continue
            col = 0
            for ch in m.group(1):
                col = col * 26 + (ord(ch) - 64)
            row = int(m.group(2)) - 1
            col -= 1
            t = c.get("t")
            if t == "inlineStr":
                val: Any = "".join(x.text or "" for x in c.iter(f"{NS}t"))
            else:
                v = c.find(f"{NS}v")
                if v is None or v.text is None:
                    continue
                if t == "s":
                    idx = int(v.text)
                    val = shared[idx] if idx < len(shared) else ""
                elif t == "str":
                    val = v.text
                else:
                    val = _num(v.text)
                    if val is None:
                        val = v.text
            grid[(row, col)] = val
        if not grid:
            out[name] = []
            continue
        nrow = max(r for r, _ in grid) + 1
        ncol = max(c for _, c in grid) + 1
        out[name] = [[grid.get((r, c)) for c in range(ncol)] for r in range(nrow)]
    return out


def _ole_stream(data: bytes, want: str = "Workbook") -> bytes:
    """Достать поток из OLE2/CFBF-контейнера (формат .xls до 2007)."""
    if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("не OLE2-контейнер")
    ssz = 1 << struct.unpack_from("<H", data, 30)[0]
    mssz = 1 << struct.unpack_from("<H", data, 32)[0]
    n_fat = struct.unpack_from("<I", data, 44)[0]
    dir_first = struct.unpack_from("<I", data, 48)[0]
    cutoff = struct.unpack_from("<I", data, 56)[0]
    mini_first = struct.unpack_from("<I", data, 60)[0]
    difat_first = struct.unpack_from("<I", data, 68)[0]
    n_difat = struct.unpack_from("<I", data, 72)[0]

    def sector(i: int) -> bytes:
        off = 512 + i * ssz
        return data[off:off + ssz]

    difat = list(struct.unpack_from("<109I", data, 76))
    nxt = difat_first
    while n_difat and nxt < 0xFFFFFFFE:
        vals = struct.unpack_from("<%dI" % (ssz // 4), sector(nxt), 0)
        difat.extend(vals[:-1])
        nxt = vals[-1]
    fat: list[int] = []
    for fs in (d for d in difat[:n_fat] if d < 0xFFFFFFFE):
        fat.extend(struct.unpack_from("<%dI" % (ssz // 4), sector(fs), 0))

    def read_chain(start: int, size: int | None = None) -> bytes:
        parts, cur, guard = [], start, 0
        while cur < 0xFFFFFFFE and guard < 20_000_000:
            parts.append(sector(cur))
            cur = fat[cur]
            guard += 1
        blob = b"".join(parts)
        return blob[:size] if size else blob

    entries = []
    dirdata = read_chain(dir_first)
    for off in range(0, len(dirdata) - 127, 128):
        e = dirdata[off:off + 128]
        nlen = struct.unpack_from("<H", e, 64)[0]
        name = e[:max(0, nlen - 2)].decode("utf-16-le", "replace")
        entries.append((name, e[66], struct.unpack_from("<I", e, 116)[0],
                        struct.unpack_from("<Q", e, 120)[0]))

    target = next((e for e in entries if e[0] == want), None)
    if target is None:
        raise KeyError(f"поток {want!r} не найден; есть: {[e[0] for e in entries]}")
    _, _, sid, size = target
    if size >= cutoff:
        return read_chain(sid, size)

    root = next(e for e in entries if e[1] == 5)
    ministream = read_chain(root[2], root[3])
    mfb = read_chain(mini_first)
    minifat = list(struct.unpack_from("<%dI" % (len(mfb) // 4), mfb, 0))
    parts, cur = [], sid
    while cur < 0xFFFFFFFE:
        parts.append(ministream[cur * mssz:(cur + 1) * mssz])
        cur = minifat[cur]
    return b"".join(parts)[:size]


def _biff_sst(blocks: list[bytes]) -> list[str]:
    """Таблица строк BIFF8 (SST + CONTINUE).

    Массив символов строки может быть разрезан границей CONTINUE; в этом случае
    CONTINUE начинается с нового байта grbit, бит 0 которого задаёт «широту»
    остатка. Заголовок строки не разрезается никогда — значит при переходе
    между строками байт grbit съедать НЕЛЬЗЯ.
    """
    st = {"bi": 0, "bp": 8, "wide": 0}

    def left() -> int:
        return len(blocks[st["bi"]]) - st["bp"]

    def advance(mid_string: bool) -> bool:
        st["bi"] += 1
        if st["bi"] >= len(blocks):
            return False
        st["bp"] = 0
        if mid_string:
            st["wide"] = blocks[st["bi"]][0] & 0x01
            st["bp"] = 1
        return True

    def take(n: int) -> bytes:
        b = blocks[st["bi"]][st["bp"]:st["bp"] + n]
        st["bp"] += n
        return b

    nstr = struct.unpack_from("<I", blocks[0], 4)[0]
    out: list[str] = []
    for _ in range(nstr):
        while left() < 3:
            if not advance(False):
                return out
        clen = struct.unpack_from("<H", take(2), 0)[0]
        flags = take(1)[0]
        st["wide"] = flags & 0x01
        nrun = struct.unpack_from("<H", take(2), 0)[0] if flags & 0x08 else 0
        necb = struct.unpack_from("<I", take(4), 0)[0] if flags & 0x04 else 0

        chunks, remain = [], clen
        while remain > 0:
            if left() == 0 and not advance(True):
                return out
            wide = st["wide"]
            step = min(remain, left() // 2 if wide else left())
            if step <= 0:
                if not advance(True):
                    return out
                continue
            raw = take(step * 2 if wide else step)
            chunks.append(raw.decode("utf-16-le" if wide else "latin-1", "replace"))
            remain -= step
        out.append("".join(chunks))

        skip = nrun * 4 + necb
        while skip > 0:
            if left() == 0 and not advance(False):
                return out
            step = min(skip, left())
            take(step)
            skip -= step
    return out


def _rk_value(v: int) -> float:
    is_int, div100 = v & 0x02, v & 0x01
    if is_int:
        n = v >> 2
        if n & 0x20000000:
            n -= 0x40000000
        x = float(n)
    else:
        x = struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return x / 100 if div100 else x


def _xls_sheets(body: bytes) -> dict[str, list[list[Any]]]:
    """Прочитать legacy .xls (BIFF8) стандартной библиотекой."""
    wb = _ole_stream(body, "Workbook")
    recs, pos = [], 0
    while pos + 4 <= len(wb):
        t, ln = struct.unpack_from("<HH", wb, pos)
        recs.append((t, wb[pos + 4:pos + 4 + ln]))
        pos += 4 + ln

    sst: list[str] = []
    for i, (t, d) in enumerate(recs):
        if t == 0x00FC:
            blocks = [d]
            for t2, d2 in recs[i + 1:]:
                if t2 != 0x003C:
                    break
                blocks.append(d2)
            sst = _biff_sst(blocks)
            break

    def sheet_name(d: bytes) -> str:
        nlen = d[6]
        wide = d[7] & 0x01
        return d[8:8 + (nlen * 2 if wide else nlen)].decode(
            "utf-16-le" if wide else "latin-1", "replace")

    names = [sheet_name(d) for t, d in recs if t == 0x0085]
    bofs = [i for i, (t, _) in enumerate(recs) if t == 0x0809]

    out: dict[str, list[list[Any]]] = {}
    for si, name in enumerate(names):
        if si + 1 >= len(bofs):
            break
        start = bofs[si + 1]
        end = bofs[si + 2] if si + 2 < len(bofs) else len(recs)
        grid: dict[tuple[int, int], Any] = {}
        for t, d in recs[start:end]:
            if t == 0x0203 and len(d) >= 14:                    # NUMBER
                r, c = struct.unpack_from("<HH", d, 0)
                grid[(r, c)] = struct.unpack_from("<d", d, 6)[0]
            elif t == 0x00FD and len(d) >= 10:                  # LABELSST
                r, c, _, isst = struct.unpack_from("<HHHI", d, 0)
                grid[(r, c)] = sst[isst] if isst < len(sst) else ""
            elif t == 0x027E and len(d) >= 10:                  # RK
                r, c = struct.unpack_from("<HH", d, 0)
                grid[(r, c)] = _rk_value(struct.unpack_from("<I", d, 6)[0])
            elif t == 0x00BD and len(d) >= 12:                  # MULRK
                r, c1 = struct.unpack_from("<HH", d, 0)
                for k in range((len(d) - 6) // 6):
                    grid[(r, c1 + k)] = _rk_value(
                        struct.unpack_from("<I", d, 4 + k * 6 + 2)[0])
            elif t == 0x0204 and len(d) >= 9:                   # LABEL
                r, c = struct.unpack_from("<HH", d, 0)
                clen = struct.unpack_from("<H", d, 6)[0]
                wide = d[8] & 0x01
                raw = d[9:9 + (clen * 2 if wide else clen)]
                grid[(r, c)] = raw.decode("utf-16-le" if wide else "latin-1", "replace")
        if not grid:
            out[name] = []
            continue
        nrow = max(r for r, _ in grid) + 1
        ncol = max(c for _, c in grid) + 1
        out[name] = [[grid.get((r, c)) for c in range(ncol)] for r in range(nrow)]
    return out


def _spreadsheet(body: bytes) -> dict[str, list[list[Any]]]:
    """Автовыбор парсера по «магическим» байтам (сайты часто врут расширением).

    Отдельно назван самый частый случай — HTML вместо таблицы. Сервер при этом
    отвечает 200 и присылает солидный объём (страница ошибки бывает на сотни
    килобайт), так что ни код, ни размер подмену не выдают: единственный
    надёжный признак — сигнатура.
    """
    if body[:2] == b"PK":
        return _xlsx_sheets(body)
    if body[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return _xls_sheets(body)
    head = body[:512].lstrip()[:16].lower()
    if head.startswith((b"<!do", b"<html", b"<?xml", b"<")):
        raise UpstreamBlocked(
            f"вместо таблицы пришёл HTML ({len(body)} байт). Обычно это "
            f"страница ошибки или заглушка, отданная с кодом 200 — проверять "
            f"надо сигнатуру, а не статус и не размер."
        )
    raise ValueError(f"неизвестный формат таблицы (magic={body[:8]!r})")


def _wide_table(rows: list[list[Any]], *, header_row: int, date_col: int,
                source: str, freq: str, units: str, sa: str = "",
                id_prefix: str = "") -> dict[str, Series]:
    """Широкая таблица (дата в столбце + колонка на ряд) -> dict[str, Series]."""
    if not rows or header_row >= len(rows):
        return {}
    header = rows[header_row]
    stamp = _now()
    cols = [(i, str(h).strip()) for i, h in enumerate(header)
            if i != date_col and h not in (None, "")]
    out = {name: Series(series_id=f"{id_prefix}{name}", source=source, title=name,
                        freq=freq, units=units, sa=sa, fetched_at=stamp)
           for _, name in cols}
    for row in rows[header_row + 1:]:
        if date_col >= len(row):
            continue
        iso = _iso(row[date_col], freq)
        if not iso:
            continue
        for i, name in cols:
            s = out[name]
            s.dates.append(iso)
            s.values.append(_num(row[i]) if i < len(row) else None)
    return out


# --------------------------------------------------------------------------- #
# FRED (ключ обязателен)
# --------------------------------------------------------------------------- #

FRED_API = "https://api.stlouisfed.org/fred"


def fred_meta(series_id: str, *, force: bool = False) -> dict[str, Any]:
    """Паспорт ряда FRED: название, частота, единицы, границы истории, notes.

    Полезно как первая проверка перед любым утверждением: FRED усекает историю
    лицензионных рядов и замораживает заброшенные — это видно только здесь.
    """
    url = (f"{FRED_API}/series?series_id={urllib.parse.quote(series_id)}"
           f"&file_type=json&api_key={_key('FRED_API_KEY')}")
    body = fetch(url, tag="fred-meta", force=force, max_age=timedelta(days=7))
    return json.loads(body)["seriess"][0]


def fred(series_id: str, *, start: str | None = None, end: str | None = None,
         units: str | None = None, frequency: str | None = None,
         force: bool = False, with_meta: bool = True) -> Series:
    """Ряд из FRED.

    ``units`` — преобразование на стороне FRED (``pch``, ``pc1``, ``chg`` ...).
    ``frequency`` — агрегирование (``m``, ``q``, ``a`` ...).
    """
    key = _key("FRED_API_KEY")
    q = [f"series_id={urllib.parse.quote(series_id)}", "file_type=json", f"api_key={key}"]
    if start:
        q.append(f"observation_start={start}")
    if end:
        q.append(f"observation_end={end}")
    if units:
        q.append(f"units={units}")
    if frequency:
        q.append(f"frequency={frequency}")
    body = fetch(f"{FRED_API}/series/observations?" + "&".join(q),
                 tag="fred", force=force)
    obs = json.loads(body)["observations"]

    meta: dict[str, Any] = {}
    if with_meta:
        try:
            meta = fred_meta(series_id, force=force)
        except FetchError:
            meta = {}
    s = Series(
        series_id=series_id, source="FRED",
        title=meta.get("title", ""), freq=meta.get("frequency_short", ""),
        units=units or meta.get("units_short", ""),
        sa=meta.get("seasonal_adjustment_short", ""),
        fetched_at=_now(),
        meta={k: meta.get(k) for k in
              ("observation_start", "observation_end", "last_updated", "notes") if k in meta},
    )
    for o in obs:
        s.dates.append(o["date"])
        s.values.append(_num(o["value"]))
    return s


def fred_search(text: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Поиск ряда по названию. Пустой результат — доказательство отсутствия."""
    url = (f"{FRED_API}/series/search?search_text={urllib.parse.quote(text)}"
           f"&file_type=json&api_key={_key('FRED_API_KEY')}&limit={limit}"
           f"&order_by=popularity&sort_order=desc")
    return json.loads(fetch(url, tag="fred-search", max_age=timedelta(days=7)))["seriess"]


# --------------------------------------------------------------------------- #
# Казначейство США — кривая доходности (без ключа)
# --------------------------------------------------------------------------- #

_TREASURY_CSV = ("https://home.treasury.gov/resource-center/data-chart-center/"
                 "interest-rates/daily-treasury-rates.csv/{year}/all"
                 "?type={kind}&field_tdr_date_value={year}&page&_format=csv")


def treasury_curve(kind: str = "nominal", *, years: Iterable[int] | None = None,
                   force: bool = False) -> dict[str, Series]:
    """Дневная кривая Казначейства США по годам.

    ``kind='nominal'`` -> daily_treasury_yield_curve (1 Mo .. 30 Yr, с 1990).
    ``kind='real'``    -> daily_treasury_real_yield_curve (TIPS, 5..30 Yr, с 2003).

    Возвращает ``{'10 Yr': Series, ...}``. Годы по умолчанию — текущий.
    """
    kinds = {"nominal": "daily_treasury_yield_curve",
             "real": "daily_treasury_real_yield_curve"}
    if kind not in kinds:
        raise ValueError(f"kind должен быть одним из {sorted(kinds)}")
    if years is None:
        years = [date.today().year]

    merged: dict[str, Series] = {}
    for yr in sorted(years):
        body = fetch(_TREASURY_CSV.format(year=yr, kind=kinds[kind]),
                     tag=f"treasury-{kind}", force=force)
        rows = _rows_from_csv(body)
        part = _wide_table(rows, header_row=0, date_col=0, source="U.S. Treasury",
                           freq="D", units="percent",
                           id_prefix=f"UST-{'REAL' if kind == 'real' else 'NOM'}-")
        for name, s in part.items():
            if name not in merged:
                merged[name] = s
            else:
                merged[name].dates.extend(s.dates)
                merged[name].values.extend(s.values)
    for s in merged.values():
        order = sorted(range(len(s.dates)), key=lambda i: s.dates[i])
        s.dates = [s.dates[i] for i in order]
        s.values = [s.values[i] for i in order]
    return merged


# --------------------------------------------------------------------------- #
# Рынки: Yahoo Finance (без ключа), stooq (заблокирован анти-ботом)
# --------------------------------------------------------------------------- #

#: 1900-01-01 в секундах Unix — Yahoo принимает отрицательный period1.
_YAHOO_FLOOR = -2208988800


def yahoo(symbol: str, *, range_: str | None = None, interval: str = "1d",
          allow_coarser: bool = False, force: bool = False) -> Series:
    """Дневной ряд закрытий с Yahoo Finance chart API.

    Индексы: ``^GSPC``, ``^RUT``, ``^IXIC``, ``^VIX``, ``DX-Y.NYB``.
    Фьючерсы: ``GC=F`` (золото), ``HG=F`` (медь), ``CL=F`` (нефть WTI).

    По умолчанию (``range_=None``) запрашивается вся история через
    ``period1``/``period2``. Так сделано намеренно: **``range=max`` молча
    понижает гранулярность** — на ``^GSPC`` с ``range=max&interval=1d`` Yahoo
    отдаёт 168 точек с шагом ``3mo``, а через ``period1`` — полную дневную
    историю с 1927-12-30. На ``^VIX3M`` тот же ``range=max`` возвращает
    **ровно одну** точку. Фактическую гранулярность функция сверяет с
    запрошенной и **падает** при расхождении (``allow_coarser=True`` — если
    грубый шаг нужен осознанно).

    Даты берутся из самого ряда, а не из ``meta.firstTradeDate``: они не
    совпадают. У ``^HGX``, ``XHB`` и ``ITB`` первый бар примерно на месяц
    позже даты первой сделки из метаданных.
    """
    base = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
    if range_:
        url = f"{base}?range={range_}&interval={interval}"
    else:
        now = int(time.time())
        url = f"{base}?period1={_YAHOO_FLOOR}&period2={now}&interval={interval}"
    payload = json.loads(fetch(url, tag="yahoo", force=force))
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise FetchError(f"Yahoo вернул ошибку для {symbol}: {chart['error']}")
    res = (chart.get("result") or [None])[0]
    if not res:
        raise FetchError(f"Yahoo не вернул данных для {symbol}")
    meta = res.get("meta") or {}
    stamps = res.get("timestamp") or []
    closes = ((res.get("indicators") or {}).get("adjclose")
              or (res.get("indicators") or {}).get("quote") or [{}])[0]
    vals = closes.get("adjclose") or closes.get("close") or []
    got = meta.get("dataGranularity")
    if got and got != interval and not allow_coarser:
        raise FetchError(
            f"Yahoo вернул шаг {got!r} вместо запрошенного {interval!r} для "
            f"{symbol}: это другой ряд, а не тот же с оговоркой. Обычная "
            f"причина — range=max, при котором interval молча игнорируется "
            f"(на '^GSPC' так выходит 168 квартальных точек вместо дневных, "
            f"а на '^VIX3M' — ровно одна). Не задавайте range_, тогда история "
            f"берётся через period1/period2. Осознанно нужен грубый шаг — "
            f"allow_coarser=True."
        )
    s = Series(series_id=symbol, source="Yahoo Finance",
               title=meta.get("shortName") or symbol, freq=got or interval,
               units=meta.get("currency", ""), fetched_at=_now(),
               meta={"instrumentType": meta.get("instrumentType"),
                     "exchange": meta.get("fullExchangeName"),
                     "dataGranularity": got})
    for t, v in zip(stamps, vals):
        s.dates.append(_from_epoch(t))
        s.values.append(_num(v))
    return s


def stooq(symbol: str, *, force: bool = False) -> Series:
    """Дневной ряд со stooq.com.

    ВНИМАНИЕ: из этого окружения stooq отдаёт JavaScript-заглушку на любой
    символ (проверено на ``^spx``, ``xauusd``, ``cu.c``). Функция оставлена
    рабочей — она поднимет :class:`UpstreamBlocked` с понятным текстом.
    Эквивалент без блокировки — :func:`yahoo`.
    """
    body = fetch(f"https://stooq.com/q/d/l/?s={urllib.parse.quote(symbol)}&i=d",
                 tag="stooq", force=force)
    rows = _rows_from_csv(body)
    if not rows or rows[0][:1] != ["Date"]:
        raise UpstreamBlocked(
            f"stooq не отдал CSV для {symbol!r} (получено {len(body)} байт). "
            f"Используй yahoo() — см. SOURCES.md."
        )
    s = Series(series_id=symbol, source="stooq", freq="D", fetched_at=_now())
    close = rows[0].index("Close")
    for r in rows[1:]:
        iso = _iso(r[0])
        if iso:
            s.dates.append(iso)
            s.values.append(_num(r[close]))
    return s


# --------------------------------------------------------------------------- #
# ФРБ Нью-Йорка
# --------------------------------------------------------------------------- #

_ACM_URL = ("https://www.newyorkfed.org/medialibrary/media/research/"
            "data_indicators/ACMTermPremium.xls")


def nyfed_acm(freq: str = "daily", *, force: bool = False) -> dict[str, Series]:
    """Премия за срок ACM (Adrian-Crump-Moench), ФРБ Нью-Йорка.

    30 рядов: ``ACMY01..10`` (доходность zero-coupon), ``ACMTP01..10``
    (премия за срок), ``ACMRNY01..10`` (risk-neutral yield).
    ``freq='daily'`` — с 1961-06-14; ``freq='monthly'`` — с 1961-06-30.

    Файл — legacy .xls на 10 МБ; парсер BIFF8 встроен, внешних зависимостей нет.
    """
    sheet = {"daily": "ACM Daily", "monthly": "ACM Monthly"}
    if freq not in sheet:
        raise ValueError("freq должен быть 'daily' или 'monthly'")
    body = fetch(_ACM_URL, tag="nyfed-acm", timeout=180, force=force,
                 max_age=timedelta(days=1))
    rows = _spreadsheet(body)[sheet[freq]]
    return _wide_table(rows, header_row=0, date_col=0,
                       source="FRB New York (ACM)",
                       freq="D" if freq == "daily" else "M", units="percent")


def nyfed_reference_rate(kind: str = "sofr", *, last: int = 250,
                         force: bool = False) -> Series:
    """Ставки ФРБ Нью-Йорка: ``sofr``, ``effr``, ``obfr``, ``tgcr``, ``bgcr``."""
    secured = {"sofr", "tgcr", "bgcr"}
    group = "secured" if kind in secured else "unsecured"
    url = (f"https://markets.newyorkfed.org/api/rates/{group}/"
           f"{kind}/last/{int(last)}.json")
    payload = json.loads(fetch(url, tag="nyfed-rates", force=force))
    s = Series(series_id=kind.upper(), source="FRB New York (Markets API)",
               freq="D", units="percent", fetched_at=_now())
    for row in reversed(payload.get("refRates", [])):
        iso = _iso(row.get("effectiveDate"))
        if iso:
            s.dates.append(iso)
            s.values.append(_num(row.get("percentRate")))
    return s


def nyfed_sce(*, force: bool = False) -> dict[str, list[list[Any]]]:
    """Survey of Consumer Expectations (ожидания потребителей), листы как есть.

    Структура книги нестабильна между выпусками, поэтому возвращаются сырые
    листы — вызывающая глава сама выбирает нужный.
    """
    url = ("https://www.newyorkfed.org/medialibrary/interactives/sce/sce/"
           "downloads/data/FRBNY-SCE-Data.xlsx")
    return _spreadsheet(fetch(url, tag="nyfed-sce", timeout=120, force=force))


# --------------------------------------------------------------------------- #
# ФРБ Филадельфии
# --------------------------------------------------------------------------- #

_PHIL = "https://www.philadelphiafed.org/-/media"


def philfed_ads(*, force: bool = False) -> Series:
    """Индекс деловых условий ADS (Aruoba-Diebold-Scotti), дневной, с 1960.

    Единственный дневной индикатор состояния экономики США: смешивает данные
    разной частоты. Ноль = средние условия, отрицательное = хуже средних.
    """
    url = f"{_PHIL}/frbp/assets/surveys-and-data/ads/ads_index_most_current_vintage.xlsx"
    sheets = _spreadsheet(fetch(url, tag="philfed-ads", timeout=120, force=force))
    rows = next(iter(sheets.values()))
    if not rows:
        raise FetchError("ADS: пустой лист")
    header = [str(c or "").strip() for c in rows[0]]
    # даты в файле имеют вид YYYY:MM:DD; колонка индекса — ADS_Index
    col = next((i for i, h in enumerate(header) if "ADS" in h.upper()), 1)
    s = Series(series_id="ADS", source="FRB Philadelphia",
               title="Aruoba-Diebold-Scotti Business Conditions Index",
               freq="D", units="index (0 = average)", fetched_at=_now())
    for row in rows[1:]:
        if len(row) <= col:
            continue
        iso = _iso(row[0])
        val = _num(row[col])
        if iso and val is not None:
            s.dates.append(iso)
            s.values.append(val)
    return s


def philfed_mbos(*, force: bool = False) -> dict[str, Series]:
    """Manufacturing Business Outlook Survey, диффузные индексы, с мая 1968.

    Главный бесплатный заменитель ISM Manufacturing: та же механика
    диффузного индекса, история на 20+ лет глубже бесплатного ISM.

    Колонки: суффикс ``C`` = текущий месяц, ``F`` = ожидания на 6 мес.
    ``GA`` general activity, ``NO`` new orders, ``SH`` shipments,
    ``UO`` unfilled orders, ``DT`` delivery time, ``IV`` inventories,
    ``PP`` prices paid, ``PR`` prices received, ``NE`` employment,
    ``AW`` average workweek, ``CEF`` capital expenditures (только future).
    """
    url = (f"{_PHIL}/FRBP/Assets/Surveys-And-Data/MBOS/Historical-Data/"
           f"Diffusion-Indexes/bos_dif.csv?sc_lang=en")
    rows = _rows_from_csv(fetch(url, tag="philfed-mbos", force=force))
    return _wide_table(rows, header_row=0, date_col=0,
                       source="FRB Philadelphia (MBOS)", freq="M",
                       units="diffusion index", sa="SA", id_prefix="MBOS-")


def philfed_nbos(*, force: bool = False) -> dict[str, list[list[Any]]]:
    """Nonmanufacturing Business Outlook Survey (заменитель ISM Services), с 2011.

    Отдаётся только .xlsx с несколькими листами — возвращаются сырые листы.
    """
    url = f"{_PHIL}/FRBP/Assets/Surveys-And-Data/NBOS/nboshistory.xlsx"
    return _spreadsheet(fetch(url, tag="philfed-nbos", timeout=90, force=force))


def philfed_spf(*, force: bool = False) -> dict[str, list[list[Any]]]:
    """Survey of Professional Forecasters, медианные прогнозы, с 1968Q4."""
    url = (f"{_PHIL}/frbp/assets/surveys-and-data/survey-of-professional-forecasters/"
           f"historical-data/medianlevel.xlsx")
    return _spreadsheet(fetch(url, tag="philfed-spf", timeout=120, force=force))


def philfed_realtime(dataset: str = "routputqvqd", *, force: bool = False
                     ) -> dict[str, list[list[Any]]]:
    """Real-Time Data Set: «винтажи» — что показывал ряд на каждую дату публикации.

    Нужен главе про эмпирический метод: почти все утверждения курса проверяются
    на ПЕРЕСМОТРЕННЫХ данных, которых в реальном времени не существовало.
    ``routputqvqd`` — реальный выпуск, квартальные наблюдения × квартальные винтажи.
    """
    url = (f"{_PHIL}/frbp/assets/surveys-and-data/real-time-data/data-files/xlsx/"
           f"{dataset}.xlsx")
    return _spreadsheet(fetch(url, tag="philfed-rtdsm", timeout=120, force=force))


# --------------------------------------------------------------------------- #
# NBER — даты объявлений Комитета по датировке деловых циклов
# --------------------------------------------------------------------------- #

_NBER_ANN = ("https://www.nber.org/research/business-cycle-dating/"
             "business-cycle-dating-committee-announcements")

# «June 8, 2020 | Determination of the February 2020 Peak in US Economic Activity»
# «December 1, 2008 | Announcement of December 2007 business cycle peak/beginning…»
# Две формулировки на одной странице; строки «Memo from the Committee» поворотной
# точки не содержат и отсеиваются сами.
_NBER_ROW = re.compile(
    r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})\s*\|\s*"
    r"(?:Determination of the|Announcement of)\s+"
    r"([A-Z][a-z]+)\s+(\d{4})\s+(?:business cycle\s+)?(peak|trough)",
    re.IGNORECASE)


def nber_announcements(*, force: bool = False) -> dict[str, Series]:
    """Даты, когда Комитет NBER **объявил** каждый пик и каждое дно.

    Зачем это отдельным источником. `USREC` даёт датировку, но не момент, когда
    она стала известна, а Комитет объявляет поворот задним числом — от полугода
    до полутора лет спустя. Любой бэктест, в котором рецессия «известна»
    в момент сигнала, меряет не то, что было доступно решающему.

    Возвращает два ряда: ``peaks`` и ``troughs``. **Дата — месяц самой
    поворотной точки** (первое число), **значение — лаг объявления в месяцах**;
    сама дата объявления лежит в ``meta['announced'][<месяц>]``.

    Ограничение источника, а не загрузчика: практика публичных объявлений
    у Комитета начинается с 1979 года, поэтому первая объявленная точка —
    пик 1980-01. Для более ранних рецессий даты объявления не существует.

    ALFRED этот вопрос не закрывает: винтажи ``USREC`` в нём начинаются
    2014-09-18, то есть покрывают ровно одно объявление из шести.
    """
    body = fetch(_NBER_ANN, tag="nber-announcements", timeout=60, force=force,
                 max_age=timedelta(days=7))
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", body.decode("utf-8", "replace"))
    text = re.sub(r"<[^>]+>", "|", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\n]+", " ", text)

    found: dict[str, dict[str, str]] = {"peak": {}, "trough": {}}
    for a_mon, a_day, a_year, t_mon, t_year, kind in _NBER_ROW.findall(text):
        am, tm = _MONTHS.get(a_mon[:3].title()), _MONTHS.get(t_mon[:3].title())
        if am is None or tm is None:
            continue
        turn = f"{int(t_year):04d}-{tm:02d}-01"
        ann = f"{int(a_year):04d}-{am:02d}-{int(a_day):02d}"
        # Одна поворотная точка объявляется один раз; при повторе побеждает
        # более ранняя дата — переиздание страницы не должно удлинять лаг.
        prev = found[kind.lower()].get(turn)
        if prev is None or ann < prev:
            found[kind.lower()][turn] = ann

    out: dict[str, Series] = {}
    for kind, key in (("peak", "peaks"), ("trough", "troughs")):
        s = Series(series_id=f"NBER-{key.upper()}", source="NBER",
                   title=f"NBER business cycle {kind} announcements",
                   freq="M", units="мес. лага", fetched_at=_now(),
                   meta={"url": _NBER_ANN, "announced": dict(sorted(found[kind].items()))})
        for turn, ann in sorted(found[kind].items()):
            lag = ((int(ann[:4]) - int(turn[:4])) * 12
                   + (int(ann[5:7]) - int(turn[5:7])))
            s.dates.append(turn)
            s.values.append(float(lag))
        out[key] = s

    # Проверка ПО СОДЕРЖИМОМУ, а не по коду ответа: страница NBER — обычный HTML,
    # и при подмене лендингом/капчей она отдаст 200 и правдоподобный размер.
    # Разбор обязан дать хотя бы шесть объявленных пиков и шесть доньев,
    # а каждый лаг — лежать в разумных границах.
    for key in ("peaks", "troughs"):
        n = len(out[key].observed)
        if n < 6:
            raise FetchError(
                f"Страница объявлений NBER разобрана в {n} {key} (ожидалось >= 6). "
                f"Скорее всего, телом пришла не та страница: проверьте {_NBER_ANN}")
        bad = [(d, v) for d, v in out[key].observed if not 0 <= v <= 36]
        if bad:
            raise FetchError(
                f"NBER {key}: лаг объявления вне диапазона 0..36 мес. — {bad[:3]}")
    return out


# --------------------------------------------------------------------------- #
# Прочие ФРБ
# --------------------------------------------------------------------------- #

def empire_state(*, seasonally_adjusted: bool = True, force: bool = False
                 ) -> dict[str, Series]:
    """Empire State Manufacturing Survey (ФРБ Нью-Йорка), с июля 2001.

    Колонки как в MBOS, с суффиксом ``DISA``/``DINA``.
    """
    name = ("esms_seasonallyadjusted_diffusion" if seasonally_adjusted
            else "esms_notseasonallyadjusted_diffusion")
    url = f"https://www.newyorkfed.org/medialibrary/media/survey/empire/data/{name}.csv"
    rows = _rows_from_csv(fetch(url, tag="empire", force=force))
    return _wide_table(rows, header_row=0, date_col=0,
                       source="FRB New York (Empire State)", freq="M",
                       units="diffusion index",
                       sa="SA" if seasonally_adjusted else "NSA", id_prefix="ESMS-")


_RICHMOND_MFG = (
    "https://www.richmondfed.org/-/media/RichmondFedOrg/region_communities/"
    "regional_data_analysis/regional_economy/surveys_of_business_conditions/"
    "manufacturing/data/mfg_historicaldata.xlsx"
)


def richmond_fed(*, force: bool = False) -> dict[str, Series]:
    """Fifth District Survey of Manufacturing Activity (ФРБ Ричмонда), с 1993-11.

    Четвёртая панель в композите-замене ISM. На FRED ФРБ Ричмонда свой обзор
    НЕ публикует (там от него единственный релиз — Non-Employment Index),
    поэтому берём файл напрямую.

    Ключевая колонка — ``sa_mfg_composite`` (сезонно сглаженный композит; веса
    ФРБ Ричмонда: отгрузки 33% / новые заказы 40% / занятость 27%). Всего в
    книге 66 колонок: префикс ``sa_``/``nsa_`` = со сглаживанием и без,
    суффикс ``_c`` = current, ``_e`` = expectations.

    Внимание к пути: рабочий URL лежит в ветке ``region_communities/
    regional_data_analysis/``. Ветка ``research/...surveys_of_business_conditions``
    отдаёт 404 — на неё легко наткнуться и решить, что ряда нет.
    """
    rows = next(iter(_spreadsheet(
        fetch(_RICHMOND_MFG, tag="richmond-mfg", timeout=90, force=force)).values()))
    if not rows:
        raise FetchError("ФРБ Ричмонда: пустой лист")
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    try:
        date_col = header.index("date")
    except ValueError:
        raise FetchError(
            f"ФРБ Ричмонда: нет колонки 'date'; есть {header[:6]}") from None

    stamp = _now()
    out: dict[str, Series] = {}
    for i, name in enumerate(header):
        if i == date_col or not name:
            continue
        out[name] = Series(series_id=f"RICHMOND-{name}",
                           source="FRB Richmond (Fifth District Mfg Survey)",
                           title=name, freq="M", units="diffusion index",
                           sa="SA" if name.startswith("sa_") else "NSA",
                           fetched_at=stamp)
    for row in rows[1:]:
        if date_col >= len(row):
            continue
        iso = _iso(row[date_col])   # даты лежат серийными числами Excel
        if not iso:
            continue
        for i, name in enumerate(header):
            if i == date_col or not name or i >= len(row):
                continue
            out[name].dates.append(iso)
            out[name].values.append(_num(row[i]))
    return out


_KC_SURVEY_PAGE = "https://www.kansascityfed.org/surveys/manufacturing-survey/"


def kansascity_fed(*, force: bool = False) -> dict[str, Series]:
    """Tenth District Manufacturing Survey (ФРБ Канзас-Сити), с 2001-07.

    Пятая панель композита-замены ISM. На FRED этого обзора нет (среди релизов
    ФРБ Канзас-Сити только Risk-On/Risk-Off, стресс и рынок труда), но файл
    выложен открыто.

    Две ловушки, из-за которых этот ряд дважды признавали закрытым:

    * ссылка на месячный файл содержит дату выпуска
      (``2026Jul23historicalmfg.xlsx``) — она меняется каждый месяц, поэтому
      берётся со страницы обзора, а не хардкодится;
    * страница отдаёт содержимое и через JS, поэтому осмотр отрендеренного DOM
      ссылок не показывает — искать надо в исходном HTML.

    Раскладка **транспонированная**: строки = показатели, колонки = месяцы
    (серийные даты Excel). Три секции с повторяющимися названиями строк —
    ``versus a month ago`` SA / NSA и ``versus a year ago`` NSA, — поэтому ключ
    результата всегда «секция / показатель», например
    ``"SA m/m / Composite Index"``.
    """
    page = fetch(_KC_SURVEY_PAGE, tag="kc-page", force=force,
                 max_age=timedelta(days=1)).decode("utf-8", "replace")
    hrefs = re.findall(r'href="([^"]*historicalmfg\.xlsx[^"]*)"', page, re.I)
    if not hrefs:
        raise FetchError(
            "На странице обзора ФРБ Канзас-Сити не нашлось ссылки на "
            "*historicalmfg.xlsx — вероятно, изменилась вёрстка. "
            "Искать в ИСХОДНОМ HTML: в отрендеренном DOM ссылок не видно."
        )
    href = html.unescape(hrefs[0])
    url = href if href.startswith("http") else "https://www.kansascityfed.org" + href
    sys.stderr.write(f"[sources] KC mfg: {url}\n")

    rows = next(iter(_spreadsheet(
        fetch(url, tag="kc-mfg", timeout=90, force=force,
              max_age=timedelta(days=1))).values()))
    if not rows:
        raise FetchError("ФРБ Канзас-Сити: пустой лист")

    # Строка с серийными датами — та, где больше всего чисел, похожих на даты.
    def date_count(row: list[Any]) -> int:
        return sum(1 for c in row if (v := _num(c)) and 20000 < v < 60000)

    hdr_i = max(range(min(12, len(rows))), key=lambda i: date_count(rows[i]))
    date_at: dict[int, str] = {}
    for i, c in enumerate(rows[hdr_i]):
        v = _num(c)
        if v and 20000 < v < 60000:
            iso = _iso(v)
            if iso:
                date_at[i] = iso[:8] + "01"   # нормализуем на первое число месяца

    section = ""
    pending: list[str] = []
    out: dict[str, Series] = {}
    stamp = _now()
    for row in rows[hdr_i + 1:]:
        label = str(row[0]).strip() if row and isinstance(row[0], str) else ""
        has_values = any(_num(row[i]) is not None for i in date_at if i < len(row))
        if label and not has_values:
            # Заголовок секции занимает две строки: «Versus a Month Ago» +
            # «(seasonally adjusted)». Накапливаем и берём ТЕКСТ КАК ЕСТЬ.
            # Выводить период из слов нельзя: у секции «Expected in Six Months»
            # тоже есть слово «Month», и попытка угадать склеивала её с
            # «Versus a Month Ago» в один ряд двойной длины.
            pending.append(label)
            continue
        if pending:
            block = re.sub(r"\s+", " ", " ".join(pending)).strip()
            # Настоящий заголовок секции всегда несёт «(…seasonally adjusted)».
            # Без этой проверки строка показателя, у которой в этом выпуске нет
            # ни одного значения, назначалась «секцией» и уводила следующие
            # показатели в несуществующую группу.
            if "adjusted" in block.lower():
                section = block
            pending = []
        if not label or not has_values:
            continue
        key = f"{section} / {label}" if section else label
        s = out.get(key)
        if s is None:
            s = out[key] = Series(
                series_id=f"KCFED-{key}", source="FRB Kansas City (Tenth District)",
                title=label, freq="M", units="diffusion index",
                sa="NSA" if "not seasonally" in section.lower() else "SA",
                fetched_at=stamp, meta={"section": section})
        for i, iso in sorted(date_at.items(), key=lambda kv: kv[1]):
            if i < len(row):
                s.dates.append(iso)
                s.values.append(_num(row[i]))

    for s in out.values():
        dupes = {d for d, nxt in zip(s.dates, s.dates[1:]) if d == nxt}
        if dupes:
            raise FetchError(
                f"ФРБ Канзас-Сити: в ряду {s.series_id} на {len(dupes)} дат пришло "
                f"больше одного значения (например {sorted(dupes)[:3]}) — значит "
                f"две строки файла попали в один ключ. Изменилась раскладка секций."
            )
    return out


def cfnai(*, force: bool = False) -> dict[str, Series]:
    """Chicago Fed National Activity Index, с марта 1967.

    85 индикаторов в одном числе; ноль = тренд. Заменитель Conference Board LEI
    в части «широкий индекс активности» (но LEI опережающий, а CFNAI — нет).
    """
    url = "https://www.chicagofed.org/-/media/publications/cfnai/cfnai-data-series-xlsx.xlsx"
    sheets = _spreadsheet(fetch(url, tag="cfnai", timeout=90, force=force))
    rows = next(iter(sheets.values()))
    hdr = next((i for i, r in enumerate(rows)
                if any(isinstance(c, str) and "CFNAI" in c.upper() for c in r)), 0)
    return _wide_table(rows, header_row=hdr, date_col=0,
                       source="FRB Chicago", freq="M", units="index (0 = trend)")


def atlanta_gdpnow(*, force: bool = False) -> dict[str, list[list[Any]]]:
    """GDPNow (ФРБ Атланты): нау-каст роста ВВП. Сырые листы (~10 МБ)."""
    url = ("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
           "cqer/researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx")
    return _spreadsheet(fetch(url, tag="gdpnow", timeout=180, force=force))


def cleveland_inflation_expectations(*, force: bool = False
                                     ) -> dict[str, list[list[Any]]]:
    """Модельные инфляционные ожидания ФРБ Кливленда (1–30 лет).

    В отличие от breakeven (T5YIE) это модельная оценка, свободная от премии
    за инфляционный риск и премии за ликвидность TIPS.
    """
    url = ("https://www.clevelandfed.org/-/media/files/webcharts/"
           "inflationexpectations/inflation-expectations.xlsx")
    return _spreadsheet(fetch(url, tag="cleveland-infexp", timeout=90, force=force))


# --------------------------------------------------------------------------- #
# BLS (без ключа — v1; с ключом — v2)
# --------------------------------------------------------------------------- #

def bls(series_ids: str | Sequence[str], *, start: int | None = None,
        end: int | None = None, force: bool = False) -> dict[str, Series]:
    """Ряды BLS по идентификаторам.

    Без ключа используется API v1: до 25 рядов и 10 лет за запрос, 25 запросов
    в сутки с адреса. С ``BLS_API_KEY`` — v2 (50 рядов, 20 лет, 500 запросов).

    Примеры: ``LNS14000000`` (безработица), ``CES0000000001`` (NFP),
    ``CUUR0000SA0`` (CPI, NSA), ``CUSR0000SA0`` (CPI, SA), ``JTS000000000000000JOL``.
    """
    ids = [series_ids] if isinstance(series_ids, str) else list(series_ids)
    end = end or date.today().year
    start = start or end - 9
    body_obj: dict[str, Any] = {
        "seriesid": ids, "startyear": str(start), "endyear": str(end),
    }
    key = os.environ.get("BLS_API_KEY") or _load_env().get("BLS_API_KEY")
    version = "v1"
    if key:
        body_obj["registrationkey"] = key
        version = "v2"
    payload = json.dumps(body_obj).encode()
    raw = fetch(f"https://api.bls.gov/publicAPI/{version}/timeseries/data/",
                tag="bls", data=payload,
                headers={"Content-Type": "application/json"}, force=force)
    doc = json.loads(raw)
    if doc.get("status") != "REQUEST_SUCCEEDED":
        raise FetchError(f"BLS отказал: {doc.get('status')} {doc.get('message')}")

    out: dict[str, Series] = {}
    for ser in doc["Results"]["series"]:
        s = Series(series_id=ser["seriesID"], source="BLS", freq="M",
                   fetched_at=_now())
        pts = []
        for d in ser["data"]:
            period = d["period"]
            if period.startswith("M") and period != "M13":
                iso = f"{d['year']}-{int(period[1:]):02d}-01"
            elif period.startswith("Q"):
                s.freq = "Q"
                iso = f"{d['year']}-{(int(period[1:]) - 1) * 3 + 1:02d}-01"
            elif period == "M13" or period.startswith("A"):
                s.freq = "A"
                iso = f"{d['year']}-01-01"
            else:
                continue
            pts.append((iso, _num(d["value"])))
        pts.sort()
        s.dates = [p[0] for p in pts]
        s.values = [p[1] for p in pts]
        out[ser["seriesID"]] = s
    return out


# --------------------------------------------------------------------------- #
# BEA (ключ обязателен)
# --------------------------------------------------------------------------- #

def bea(table: str = "T10102", *, dataset: str = "NIPA", frequency: str = "Q",
        years: str = "ALL", force: bool = False) -> dict[str, Series]:
    """Таблица BEA (по умолчанию NIPA).

    Примеры таблиц: ``T10102`` (реальный рост ВВП по компонентам),
    ``T20600`` (личный доход, месячная), ``T20804`` (индексы цен PCE, месячная).
    Ряды разбиваются по ``SeriesCode``+``LineDescription``.
    """
    url = (f"https://apps.bea.gov/api/data/?UserID={_key('BEA_API_KEY')}"
           f"&method=GetData&datasetname={dataset}&TableName={table}"
           f"&Frequency={frequency}&Year={years}&ResultFormat=JSON")
    doc = json.loads(fetch(url, tag="bea", force=force, timeout=90))
    results = doc.get("BEAAPI", {}).get("Results", {})
    if isinstance(results, list):
        results = results[0] if results else {}
    if "Error" in results or "Error" in doc.get("BEAAPI", {}):
        err = results.get("Error") or doc["BEAAPI"].get("Error")
        raise FetchError(f"BEA отказал: {str(err)[:300]}")
    rows = results.get("Data", [])

    out: dict[str, Series] = {}
    stamp = _now()
    for r in rows:
        code = r.get("SeriesCode", "?")
        if code not in out:
            out[code] = Series(
                series_id=f"{table}:{code}", source="BEA",
                title=r.get("LineDescription", ""), freq=frequency,
                units=r.get("CL_UNIT", "") or r.get("UNIT_MULT", ""),
                fetched_at=stamp, meta={"table": table, "dataset": dataset},
            )
        iso = _iso(r.get("TimePeriod"), frequency)
        if iso:
            out[code].dates.append(iso)
            out[code].values.append(_num(r.get("DataValue")))
    for s in out.values():
        order = sorted(range(len(s.dates)), key=lambda i: s.dates[i])
        s.dates = [s.dates[i] for i in order]
        s.values = [s.values[i] for i in order]
    return out


# --------------------------------------------------------------------------- #
# Census (ключ обязателен) — EITS
# --------------------------------------------------------------------------- #

#: Программы EITS, требующие географический предикат ``for=us:*``.
_EITS_NEEDS_GEO = {"advm3", "m3", "mwts", "qfr", "qss", "asm"}


def census_variables(program: str = "resconst", *, force: bool = False) -> dict[str, Any]:
    """Список допустимых переменных программы EITS. Первый шаг при ошибке 204."""
    url = f"https://api.census.gov/data/timeseries/eits/{program}/variables.json"
    doc = json.loads(fetch(url, tag="census-vars", force=force,
                           max_age=timedelta(days=30)))
    return doc.get("variables", {})


def census_eits(program: str = "resconst", *, category_code: str | None = None,
                data_type_code: str | None = None, seasonally_adj: str | None = None,
                geo_level_code: str | None = "US", error_data: str | None = "no",
                time: str = "from 2000-01", force: bool = False) -> dict[str, Series]:
    """Economic Indicators Time Series (EITS) Бюро переписи США.

    Программы: ``resconst`` (жилищное строительство: старты, разрешения),
    ``marts`` (розница), ``mtis`` (запасы и продажи), ``advm3`` (заказы).

    Синтаксис EITS капризный — вот что установлено запросами:

    * ``time`` — ПРЕДИКАТ, а не переменная в ``get``. ``get=...,time`` даёт
      ``error: unknown variable 'time'``; колонка ``time`` возвращается сама.
    * ``time_slot_id`` обязателен в ``get`` для ряда программ.
    * часть программ (``advm3``, ``m3``, ``mwts``) требует ещё и ``for=us:*``,
      иначе ``error: missing 'for' argument``.
    * если фильтр не совпал ни с чем — приходит **HTTP 204 и пустое тело**,
      а не ошибка. Это самая частая причина «пустого» результата: смотри
      :func:`census_variables` и запрос без фильтров.
    * поле, указанное и в ``get``, и в предикате, возвращается ДВАЖДЫ —
      поэтому фильтруемые поля здесь в ``get`` не кладутся.
    * **главная ловушка:** без ``geo_level_code`` ответ молча смешивает США и
      4 региона переписи в одну кучу (для ``APERMITS`` за 2026-06 приходит
      5 строк: 203/155/708/308 по регионам и 1374 по стране). Поэтому здесь
      ``geo_level_code`` по умолчанию ``'US'``, а ``error_data='no'``
      отсекает строки с оценкой погрешности.

    Значения ключей результата: ``program:category:data_type:geo:SA``.
    """
    filters = {
        "category_code": category_code,
        "data_type_code": data_type_code,
        "seasonally_adj": seasonally_adj,
        "geo_level_code": geo_level_code,
        "error_data": error_data,
    }
    get_vars = ["cell_value", "time_slot_id"]
    get_vars += [name for name, val in filters.items() if val is None]

    params = [("get", ",".join(get_vars)), ("time", time)]
    params += [(name, val) for name, val in filters.items() if val is not None]
    if program in _EITS_NEEDS_GEO:
        params.append(("for", "us:*"))
    params.append(("key", _key("CENSUS_API_KEY")))

    url = (f"https://api.census.gov/data/timeseries/eits/{program}?"
           + urllib.parse.urlencode(params, safe=":*+"))
    body = fetch(url, tag="census", force=force, allow_status=(200, 204))
    if not body.strip():
        shown = {k: v for k, v in filters.items() if v is not None}
        raise FetchError(
            f"Census вернул пустой ответ (HTTP 204) для программы {program!r} — "
            f"комбинация фильтров не существует: {shown}. "
            f"Допустимые переменные: census_variables({program!r}); "
            f"допустимые коды — запрос без фильтров."
        )
    table = json.loads(body)
    header, rows = table[0], table[1:]
    idx: dict[str, int] = {}
    for i, name in enumerate(header):
        idx.setdefault(name, i)  # дубли колонок: берём первое вхождение

    def cell(row: list[str], name: str, fallback: str | None) -> str:
        return row[idx[name]] if name in idx and idx[name] < len(row) else (fallback or "")

    out: dict[str, Series] = {}
    stamp = _now()
    for r in rows:
        cat = cell(r, "category_code", category_code)
        dtc = cell(r, "data_type_code", data_type_code)
        sa_raw = cell(r, "seasonally_adj", seasonally_adj)
        geo = cell(r, "geo_level_code", geo_level_code)
        sa = "SA" if str(sa_raw).lower() in ("yes", "y") else "NSA"
        key = f"{program}:{cat}:{dtc}:{geo}:{sa}"
        if key not in out:
            out[key] = Series(series_id=key, source="U.S. Census Bureau (EITS)",
                              title=f"{program} {cat} {dtc} {geo}".strip(),
                              freq="M", sa=sa, fetched_at=stamp)
        iso = _iso(cell(r, "time", None))
        if iso:
            out[key].dates.append(iso)
            out[key].values.append(_num(cell(r, "cell_value", None)))

    for s in out.values():
        order = sorted(range(len(s.dates)), key=lambda i: s.dates[i])
        s.dates = [s.dates[i] for i in order]
        s.values = [s.values[i] for i in order]
        dupes = {d for d, nxt in zip(s.dates, s.dates[1:]) if d == nxt}
        if dupes:
            raise FetchError(
                f"Census: в ряду {s.series_id} по {len(dupes)} датам пришло больше "
                f"одного значения (например {sorted(dupes)[:3]}). Значит есть ещё "
                f"неразрешённая размерность — сузь фильтры "
                f"(см. census_variables({program!r}))."
            )
    return out


# --------------------------------------------------------------------------- #
# NAHB — Housing Market Index (ключевой опережающий индикатор книги)
# --------------------------------------------------------------------------- #

_NAHB_INDEX = ("https://www.nahb.org/news-and-economics/housing-economics/"
               "indices/housing-market-index")

#: Таблицы на индекс-странице NAHB. У каждой СВОЯ раскладка — см. nahb_hmi().
NAHB_TABLES = {
    "t2": "национальный HMI, история (композит, SA); строки = годы, колонки = месяцы",
    "t3": "компоненты (present sales / expected sales / traffic); ТРАНСПОНИРОВАНА: "
          "строки = месяцы, колонки = годы, блоки разделены заголовками",
    # ВНИМАНИЕ: t4 и t5 — НЕ «две части одного набора регионов». В каждом лежат
    # все четыре региона; t5 это трёхмесячная скользящая средняя тех же рядов,
    # что и в t4. Склеить их как один источник — значит получить дубли и
    # смешать сырой ряд со сглаженным.
    "t4": "все 4 региона, уровни, с 2004-12; полосная раскладка (не разбирается)",
    "t5": "те же 4 региона, 3-месячная скользящая средняя, с 2005-02 "
          "(не разбирается)",
}


def nahb_hmi(table: str = "t2", *, force: bool = False) -> dict[str, Series]:
    """NAHB/Wells Fargo Housing Market Index — месячный, с 1985-01.

    **Ряд открыт и бесплатен**, хотя на FRED его нет (поиск даёт ноль
    результатов). Это несовпадение стоило одной ошибочной записи в SOURCES.md:
    отсутствие на FRED не означает отсутствия в природе. Файлы лежат на сайте
    NAHB, ключ не нужен.

    Две особенности, из-за которых нельзя просто захардкодить ссылку:

    * URL меняется каждый месяц — в пути стоит ``/<год>-<месяц>/``, а в конце
      ``?rev=<hash>``. Поэтому ссылка каждый раз берётся с индекс-страницы.
    * данные лежат **широко**: строка = год, 12 колонок = месяцы. Здесь они
      разворачиваются в обычный ряд.

    Поддержаны ``t2`` (композит) и ``t3`` (компоненты). ``t4``/``t5`` (регионы)
    сознательно НЕ разбираются: там полосная раскладка — строки это регионы,
    колонки идут непрерывной чередой месяцев, а год стоит в отдельной строке
    только там, где меняется, и такие полосы уложены одна под другой (151 строка).
    Разобрать её можно, но небрежный парсер молча склеит полосы в неверный ряд,
    поэтому функция честно отказывается, а не делает вид, что справилась.

    Лицензия: «(c) NAHB, All rights reserved». График в книге с атрибуцией
    «NAHB/Wells Fargo Housing Market Index» — нормальная практика; массовую
    перепубликацию самого ряда согласовывать с NAHB.
    """
    if table not in NAHB_TABLES:
        raise ValueError(f"table должен быть одним из {sorted(NAHB_TABLES)}")
    if table in ("t4", "t5"):
        raise NotImplementedError(
            f"NAHB {table} — полосная раскладка: 22 год-блока по 4 строки "
            f"регионов, год указан только там, где меняется. Разбор не "
            f"реализован намеренно: риск молча склеить блоки. Учтите также, "
            f"что t4 и t5 — не две части одного набора: в обоих все четыре "
            f"региона, а t5 это 3-месячная скользящая средняя от t4. "
            f"История с 1985 есть только у композита nahb_hmi('t2'); "
            f"регионы начинаются с 2004-12 (t4) и 2005-02 (t5)."
        )

    page = fetch(_NAHB_INDEX, tag="nahb-index", force=force,
                 max_age=timedelta(days=1)).decode("utf-8", "replace")
    hrefs = re.findall(r'href="([^"]*\.xls[x]?[^"]*)"', page, re.I)
    match = next((h for h in hrefs if f"/{table}-" in h.lower()), None)
    if not match:
        raise FetchError(
            f"На индекс-странице NAHB не нашлось ссылки на таблицу {table!r}. "
            f"Найдено: {[h.rsplit('/', 1)[-1][:40] for h in hrefs]}. "
            f"Вероятно, NAHB поменял вёрстку — поправить nahb_hmi()."
        )
    # В HTML амперсанды экранированы (&amp;) — без unescape в запрос уходит
    # параметр «amp;hash», и в лог попадает URL, который нельзя скопировать
    # и повторить руками.
    match = html.unescape(match)
    url = match if match.startswith("http") else "https://www.nahb.org" + match
    # Логируем фактический URL: в нём месяц выпуска и ревизионный хеш, так что
    # он меняется каждый месяц. Без записи в лог потом не восстановить, какая
    # ревизия файла лежит за уже посчитанным графиком.
    sys.stderr.write(f"[sources] NAHB {table}: {url}\n")

    sheets = _spreadsheet(fetch(url, tag=f"nahb-{table}", timeout=90, force=force,
                                max_age=timedelta(days=1)))
    rows = next((r for r in sheets.values() if r), [])
    if not rows:
        raise FetchError(f"NAHB {table}: пустая книга ({url.rsplit('/', 1)[-1][:40]})")

    def is_month(c: Any) -> int | None:
        if not isinstance(c, str):
            return None
        return _MONTHS.get(c.strip().rstrip(".")[:3])

    def is_year(c: Any) -> int | None:
        v = _num(c)
        return int(v) if v is not None and 1900 < v < 2200 else None

    out: dict[str, Series] = {}
    stamp = _now()

    def put(key: str, year: int, month: int, value: float | None) -> None:
        if value is None:
            return
        s = out.get(key)
        if s is None:
            s = out[key] = Series(
                series_id=f"NAHB-{key}", source="NAHB/Wells Fargo",
                title=("NAHB/Wells Fargo Housing Market Index"
                       if table == "t2" else f"NAHB HMI — {key}"),
                freq="M", units="index (50 = разделительная линия)", sa="SA",
                fetched_at=stamp,
                # url обязателен в паспорте: в пути стоит месяц выпуска, а в хвосте
                # ревизионный хеш ?rev=…, поэтому «какой именно файл разобран»
                # восстанавливается только отсюда
                meta={"table": table, "license": "(c) NAHB", "url": url})
        s.dates.append(date(year, month, 1).isoformat())
        s.values.append(value)

    if table == "t2":
        # строки = годы, колонки = месяцы
        hdr = next((i for i, r in enumerate(rows)
                    if sum(1 for c in r if is_month(c)) >= 6), None)
        if hdr is None:
            raise FetchError("NAHB t2: не нашлась строка с месяцами")
        month_at = {i: m for i, c in enumerate(rows[hdr]) if (m := is_month(c))}
        for row in rows[hdr + 1:]:
            year = is_year(row[0]) if row else None
            if year is None:
                continue
            for col, mon in month_at.items():
                if col < len(row):
                    put("HMI", year, mon, _num(row[col]))
    else:
        # t3 транспонирована: строки = месяцы, колонки = годы,
        # блоки компонент разделены строками-заголовками без чисел.
        component = "HMI"
        year_at: dict[int, int] = {}
        for row in rows:
            years = {i: y for i, c in enumerate(row) if (y := is_year(c)) and i > 0}
            if len(years) >= 3:
                year_at = years            # новая шапка годов для блока ниже
                continue
            mon = is_month(row[0]) if row else None
            if mon is None:
                label = next((str(c).strip() for c in row
                              if isinstance(c, str) and str(c).strip()), "")
                if label and not label.lower().startswith("table"):
                    component = re.sub(r"\s+", " ", label)[:60]
                continue
            for col, yr in year_at.items():
                if col < len(row):
                    put(component, yr, mon, _num(row[col]))

    for s in out.values():
        order = sorted(range(len(s.dates)), key=lambda i: s.dates[i])
        s.dates = [s.dates[i] for i in order]
        s.values = [s.values[i] for i in order]
        dupes = {d for d, nxt in zip(s.dates, s.dates[1:]) if d == nxt}
        if dupes:
            raise FetchError(
                f"NAHB {table}: в ряду {s.series_id} на {len(dupes)} дат пришло "
                f"больше одного значения (например {sorted(dupes)[:3]}) — "
                f"раскладка файла изменилась, поправить nahb_hmi()."
            )
    return out


# --------------------------------------------------------------------------- #
# Европа и международные организации
# --------------------------------------------------------------------------- #

def ecb(series_key: str = "YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y", *,
        last_n: int | None = None, start: str | None = None,
        force: bool = False) -> Series:
    """Ряд ЕЦБ (SDMX). ``series_key`` — ``DATAFLOW.k1.k2...``."""
    flow, _, rest = series_key.partition(".")
    q = ["format=csvdata"]
    if last_n:
        q.append(f"lastNObservations={int(last_n)}")
    if start:
        q.append(f"startPeriod={start}")
    url = f"https://data-api.ecb.europa.eu/service/data/{flow}/{rest}?" + "&".join(q)
    rows = _rows_from_csv(fetch(url, tag="ecb", force=force))
    if not rows:
        return Series(series_id=series_key, source="ECB", fetched_at=_now())
    idx = {n: i for i, n in enumerate(rows[0])}
    s = Series(series_id=series_key, source="ECB", freq="", fetched_at=_now())
    for r in rows[1:]:
        if len(r) <= max(idx.get("TIME_PERIOD", 0), idx.get("OBS_VALUE", 0)):
            continue
        iso = _iso(r[idx["TIME_PERIOD"]])
        if iso:
            s.dates.append(iso)
            s.values.append(_num(r[idx["OBS_VALUE"]]))
    return s


def eurostat(dataset: str = "prc_hicp_manr", *, force: bool = False,
             **filters: str) -> dict[str, Series]:
    """Ряд Евростата (JSON-stat 2.0). Фильтры — как query-параметры."""
    params = {"format": "JSON", **filters}
    url = (f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
           f"{dataset}?" + urllib.parse.urlencode(params))
    doc = json.loads(fetch(url, tag="eurostat", force=force))
    times = list(doc["dimension"]["time"]["category"]["index"].keys())
    vals = doc.get("value", {})
    s = Series(series_id=dataset, source="Eurostat",
               title=doc.get("label", ""), units=" ".join(
                   doc.get("dimension", {}).get("unit", {})
                      .get("category", {}).get("label", {}).values()),
               fetched_at=_now())
    for i, t in enumerate(times):
        iso = _iso(t)
        if iso:
            s.dates.append(iso)
            s.values.append(_num(vals.get(str(i))))
    return {dataset: s}


def boe(series_code: str = "IUDBEDR", *, start: str = "01/Jan/1975",
        force: bool = False) -> Series:
    """Ряд Банка Англии (IADB). ``IUDBEDR`` — Bank Rate."""
    end = date.today().strftime("%d/%b/%Y")
    url = (f"https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp"
           f"?csv.x=yes&Datefrom={start}&Dateto={end}&SeriesCodes={series_code}"
           f"&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
    rows = _rows_from_csv(fetch(url, tag="boe", force=force))
    s = Series(series_id=series_code, source="Bank of England", freq="D",
               units="percent", fetched_at=_now())
    for r in rows[1:]:
        if len(r) < 2:
            continue
        iso = _iso(r[0])
        if iso:
            s.dates.append(iso)
            s.values.append(_num(r[1]))
    return s


def bis(key: str = "D.US", *, dataflow: str = "WS_CBPOL", version: str = "1.0",
        last_n: int | None = None, force: bool = False) -> Series:
    """Ряд BIS (SDMX v2). ``WS_CBPOL`` — учётные ставки центробанков.

    Требует certifi-контекста: с системным хранилищем падает на проверке цепочки.
    """
    q = ["format=csv"]
    if last_n:
        q.append(f"lastNObservations={int(last_n)}")
    url = (f"https://stats.bis.org/api/v2/data/dataflow/BIS/{dataflow}/{version}/"
           f"{key}?" + "&".join(q))
    rows = _rows_from_csv(fetch(url, tag="bis", force=force))
    if not rows:
        return Series(series_id=f"{dataflow}/{key}", source="BIS", fetched_at=_now())
    idx = {n: i for i, n in enumerate(rows[0])}
    s = Series(series_id=f"{dataflow}/{key}", source="BIS", fetched_at=_now())
    for r in rows[1:]:
        if "TIME_PERIOD" not in idx or len(r) <= idx["TIME_PERIOD"]:
            continue
        iso = _iso(r[idx["TIME_PERIOD"]])
        if iso:
            s.dates.append(iso)
            s.values.append(_num(r[idx["OBS_VALUE"]]))
    return s


def oecd_cli(country: str = "USA", *, start: str = "1955-01",
             force: bool = False) -> Series:
    """Композитный опережающий индикатор ОЭСР (CLI), амплитудно-скорректированный.

    Рабочая замена заброшенному FRED-ряду ``USSLIND``: живой, месячный,
    с 1955 года. Публикуется с задержкой ~4 месяца.
    """
    url = (f"https://sdmx.oecd.org/public/rest/data/"
           f"OECD.SDD.STES,DSD_STES@DF_CLI,4.1/{country}.M.LI...AA...H"
           f"?startPeriod={start}&format=csvfile")
    rows = _rows_from_csv(fetch(url, tag="oecd-cli", force=force))
    if not rows:
        return Series(series_id=f"CLI-{country}", source="OECD", fetched_at=_now())
    idx = {n: i for i, n in enumerate(rows[0])}
    s = Series(series_id=f"CLI-{country}", source="OECD",
               title="Composite Leading Indicator (amplitude adjusted)",
               freq="M", units="index (100 = trend)", fetched_at=_now())
    pts = []
    for r in rows[1:]:
        iso = _iso(r[idx["TIME_PERIOD"]])
        if iso:
            pts.append((iso, _num(r[idx["OBS_VALUE"]])))
    pts.sort()
    s.dates = [p[0] for p in pts]
    s.values = [p[1] for p in pts]
    return s


def worldbank(indicator: str = "NY.GDP.MKTP.CD", *, country: str = "USA",
              force: bool = False) -> Series:
    """Ряд Всемирного банка (годовой)."""
    url = (f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
           f"?format=json&per_page=20000")
    doc = json.loads(fetch(url, tag="worldbank", force=force))
    rows = doc[1] if len(doc) > 1 and doc[1] else []
    s = Series(series_id=f"{indicator}:{country}", source="World Bank", freq="A",
               title=(rows[0]["indicator"]["value"] if rows else ""),
               fetched_at=_now())
    pts = [(f"{r['date']}-01-01", _num(r["value"])) for r in rows]
    pts.sort()
    s.dates = [p[0] for p in pts]
    s.values = [p[1] for p in pts]
    return s


def dbnomics(provider: str, dataset: str, series: str | None = None, *,
             force: bool = False) -> dict[str, Series]:
    """Зеркало DBnomics (без ключа).

    Полезно для ФРБ-данных (``FED/G17_*``, ``FED/H15``) и U. Michigan
    (``SCSMICH/MICS``). ВНИМАНИЕ: свежесть зеркала зависит от провайдера —
    ``FED`` актуален, ``ISM``/``NAR`` устарели и частично испорчены.
    Подробности и предупреждения — в SOURCES.md.
    """
    path = f"{provider}/{dataset}"
    if series:
        path += f"/{series}"
    url = f"https://api.db.nomics.world/v22/series/{path}?observations=1&limit=1000"
    doc = json.loads(fetch(url, tag="dbnomics", force=force))
    out: dict[str, Series] = {}
    for d in doc.get("series", {}).get("docs", []):
        s = Series(series_id=f"{provider}/{dataset}/{d.get('series_code')}",
                   source=f"DBnomics ({provider})",
                   title=d.get("series_name", ""),
                   freq=d.get("@frequency", "") or "",
                   units=d.get("unit", "") or "", fetched_at=_now())
        for p, v in zip(d.get("period", []), d.get("value", [])):
            iso = _iso(p)
            if iso:
                s.dates.append(iso)
                s.values.append(_num(v))
        out[d.get("series_code", "?")] = s
    return out


# --------------------------------------------------------------------------- #
# Финансовые условия, позиционирование, факторы
# --------------------------------------------------------------------------- #

def ofr_fsi(*, force: bool = False) -> dict[str, Series]:
    """Индекс финансового стресса OFR, дневной, с 2000-01-03.

    Колонки: ``OFR FSI`` и подындексы Credit / Equity valuation / Safe assets /
    Funding / Volatility, плюс разбивка по регионам.
    """
    url = "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
    rows = _rows_from_csv(fetch(url, tag="ofr-fsi", force=force))
    return _wide_table(rows, header_row=0, date_col=0,
                       source="Office of Financial Research", freq="D",
                       units="index (0 = normal)", id_prefix="OFR-")


def cftc_cot(year: int | None = None, *, report: str = "fut_disagg_txt",
             force: bool = False) -> list[list[str]]:
    """Отчёты CFTC Commitments of Traders (позиционирование), годовой архив.

    ``report``: ``fut_disagg_txt`` (disaggregated, фьючерсы),
    ``fut_fin_txt`` (financial TFF), ``deacot`` (legacy).
    Возвращает строки CSV как есть — файл широкий и меняет схему между годами.

    Требует certifi-контекста: с системным хранилищем сертификатов
    ``CERTIFICATE_VERIFY_FAILED``.
    """
    year = year or date.today().year
    url = f"https://www.cftc.gov/files/dea/history/{report}_{year}.zip"
    body = fetch(url, tag="cftc", timeout=180, force=force, max_age=timedelta(days=3))
    zf = zipfile.ZipFile(io.BytesIO(body))
    member = zf.namelist()[0]
    return _rows_from_csv(zf.read(member), encoding="latin-1")


def ken_french(dataset: str = "F-F_Research_Data_Factors", *,
               force: bool = False) -> dict[str, list[list[str]]]:
    """Библиотека данных Кена Френча (Dartmouth) — 616 архивов, факторы с 1926-07.

    Главный источник для проверки главы про факторы. Возвращает
    ``{имя_файла_в_архиве: строки}``; в одном файле часто несколько блоков
    (месячные, потом годовые), разделённых пустой строкой — блоки не
    склеиваются, разбор оставлен вызывающей стороне.

    Примеры ``dataset``: ``F-F_Research_Data_Factors`` (Mkt-RF, SMB, HML, RF),
    ``F-F_Research_Data_5_Factors_2x3`` (+RMW, CMA),
    ``F-F_Momentum_Factor``, ``F-F_ST_Reversal_Factor``,
    ``10_Industry_Portfolios``, ``Portfolios_Formed_on_BE-ME``.
    Суффикс ``_daily`` даёт дневные версии.
    """
    name = dataset if dataset.endswith("_CSV.zip") else f"{dataset}_CSV.zip"
    url = f"https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{name}"
    body = fetch(url, tag="kenfrench", timeout=120, force=force,
                 max_age=timedelta(days=7))
    zf = zipfile.ZipFile(io.BytesIO(body))
    return {n: _rows_from_csv(zf.read(n), encoding="latin-1") for n in zf.namelist()}


def shiller(*, force: bool = False) -> dict[str, list[list[Any]]]:
    """Данные Роберта Шиллера: S&P, дивиденды, прибыль, CAPE с 1871-01.

    Единственный бесплатный источник глубокой истории S&P и CAPE: FRED-ряд
    ``SP500`` лицензионно урезан до 10 лет. Возвращает сырые листы;
    нужный обычно называется ``Data``.

    **Ссылку обязательно брать со страницы, а не хардкодить.** Прямой путь
    ``…/downloads/ie_data.xls`` без UUID-сегмента отвечает 200 и отдаёт
    совершенно корректный OLE2-файл — просто **устаревший на 22 месяца**
    (последнее наблюдение 2024.09 против 2026.07 на актуальной ссылке).
    Такая подмена опаснее 404: файл парсится, ряд выглядит целым, и ошибка
    всплывёт только в выводах. Поэтому здесь скрейпится ``shillerdata.com``,
    а `smoke.py` дополнительно следит за свежестью последнего наблюдения.
    """
    page = fetch("https://shillerdata.com/", tag="shiller-page", force=force,
                 max_age=timedelta(days=1)).decode("utf-8", "replace")
    hrefs = re.findall(r'href="([^"]*ie_data[^"]*\.xls[^"]*)"', page, re.I)
    if not hrefs:
        raise FetchError(
            "На shillerdata.com не нашлось ссылки на ie_data.xls — изменилась "
            "вёрстка. Хардкодить прямой путь НЕЛЬЗЯ: он отдаёт устаревшую копию."
        )
    url = html.unescape(hrefs[0])
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        url = "https://shillerdata.com" + url
    sys.stderr.write(f"[sources] Shiller: {url}\n")
    body = fetch(url, tag="shiller", timeout=120, force=force,
                 max_age=timedelta(days=7))

    # Производные колонки (CAPE, TR CAPE, реальные ряды) — это ФОРМУЛЫ Excel.
    # Встроенный BIFF-читатель отдаёт только сохранённые значения ячеек, а
    # формульные приходят пустыми; сырые колонки (Date, P, D, E, CPI, GS10)
    # читаются нормально. xlrd достаёт закешированный результат формулы, поэтому
    # используется, если установлен. Жёсткой зависимостью не делаем.
    try:
        import xlrd                                          # noqa: PLC0415
    except ImportError:
        sys.stderr.write(
            "[sources] ВНИМАНИЕ: xlrd не установлен — у Шиллера будут пустыми "
            "формульные колонки (CAPE, TR CAPE, реальные ряды). Сырые "
            "(Date, P, D, E, CPI, GS10) читаются. Поставьте xlrd для CAPE.\n"
        )
        return _spreadsheet(body)

    wb = xlrd.open_workbook(file_contents=body)
    out: dict[str, list[list[Any]]] = {}
    for name in wb.sheet_names():
        sh = wb.sheet_by_name(name)
        out[name] = [[sh.cell_value(r, c) if sh.cell_value(r, c) != "" else None
                      for c in range(sh.ncols)] for r in range(sh.nrows)]
    return out


def damodaran(dataset: str = "histretSP", *, force: bool = False
              ) -> dict[str, list[list[Any]]]:
    """Данные Асвата Дамодарана (NYU Stern): доходности классов активов с 1928.

    ``histretSP`` — акции/облигации/векселя/недвижимость/золото по годам.
    """
    url = f"https://pages.stern.nyu.edu/~adamodar/pc/datasets/{dataset}.xls"
    return _spreadsheet(fetch(url, tag="damodaran", timeout=120, force=force,
                              max_age=timedelta(days=7)))


def eia(route: str = "petroleum/pri/spt", *, frequency: str = "monthly",
        length: int = 5000, force: bool = False, **params: str) -> dict[str, Any]:
    """EIA API v2 (энергетика). Требует бесплатный ключ ``EIA_API_KEY``.

    Без ключа endpoint отвечает HTTP 403 (проверено).
    """
    q = {"api_key": _key("EIA_API_KEY"), "frequency": frequency,
         "data[0]": "value", "length": str(length), **params}
    url = f"https://api.eia.gov/v2/{route}/data/?" + urllib.parse.urlencode(q)
    return json.loads(fetch(url, tag="eia", force=force))


# --------------------------------------------------------------------------- #
# Крипта
# --------------------------------------------------------------------------- #

def coingecko(coin: str = "bitcoin", *, days: str = "365", vs: str = "usd",
              force: bool = False) -> Series:
    """Цена монеты с CoinGecko (публичный тариф, без ключа).

    На публичном тарифе шаг ответа зависит от ``days``: свыше суток приходят
    внутридневные точки. Здесь они сворачиваются в дневной ряд — берётся
    последняя точка календарного дня (UTC), чтобы даты не дублировались.
    """
    url = (f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart"
           f"?vs_currency={vs}&days={days}")
    doc = json.loads(fetch(url, tag="coingecko", force=force))
    daily: dict[str, float | None] = {}
    for ms, price in doc.get("prices", []):
        daily[_from_epoch(ms / 1000)] = _num(price)   # последняя точка дня побеждает
    s = Series(series_id=f"{coin}-{vs}", source="CoinGecko", freq="D",
               units=vs.upper(), fetched_at=_now())
    for iso in sorted(daily):
        s.dates.append(iso)
        s.values.append(daily[iso])
    return s


def binance(symbol: str = "BTCUSDT", *, interval: str = "1d",
            full_history: bool = True, force: bool = False) -> Series:
    """Свечи Binance (закрытие). Без ключа.

    **Одна страница — максимум 1000 свечей**, поэтому без пагинации на дневном
    шаге получаются только последние ~2.7 года, а не история. По умолчанию
    страницы обходятся до конца: ``startTime=0`` Binance понимает как «с начала
    истории», дальше сдвигаемся по времени закрытия последней свечи.
    Первая дневная свеча ``BTCUSDT`` — **2017-08-17** (не 2017-08-01: пара
    появилась в середине месяца).
    """
    s = Series(series_id=symbol, source="Binance", freq=interval,
               units="USDT", fetched_at=_now())
    base = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
            f"&interval={interval}&limit=1000")
    start = 0
    seen: set[str] = set()
    while True:
        rows = json.loads(fetch(f"{base}&startTime={start}", tag="binance",
                                force=force, max_age=timedelta(hours=12)))
        if not rows:
            break
        for k in rows:
            iso = _from_epoch(k[0] / 1000)
            if iso in seen:          # страницы у Binance перекрываются краями
                continue
            seen.add(iso)
            s.dates.append(iso)
            s.values.append(_num(k[4]))
        if not full_history or len(rows) < 1000:
            break
        start = int(rows[-1][6]) + 1      # k[6] = время закрытия последней свечи
    order = sorted(range(len(s.dates)), key=lambda i: s.dates[i])
    s.dates = [s.dates[i] for i in order]
    s.values = [s.values[i] for i in order]
    return s


# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    print(__doc__)
    print(f"кэш: {CACHE_DIR}")
    have = [n for n in ("FRED_API_KEY", "BEA_API_KEY", "CENSUS_API_KEY")
            if os.environ.get(n) or _load_env().get(n)]
    print(f"ключи найдены: {', '.join(have) if have else '(нет)'}")
    print("прогон описи рядов: python smoke.py")
