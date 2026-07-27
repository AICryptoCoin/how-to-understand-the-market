#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перекрёстные ссылки книги: проставить, пересчитать, проверить.

Номер главы в книге не хранится — он равен позиции главы в
`assets/chapters.js`. В разметке номер всё-таки записан: страница обязана
читаться без JavaScript и в печати. Значит, есть два числа — вычисленное
и записанное, — и они обязаны совпадать. Этот скрипт их сводит.

Разметка отсылки:

    см. <a class="xref" data-ch="faktory" data-anchor="s11"
           href="faktory.html#s11" title="56. Факторы и факторная ротация"
        >главу <b class="xref__n">56</b></a>

    <a class="figref" data-ch="hope" data-fig="2" href="#fig-hope-2"
      >рис.&nbsp;<b class="figref__n">12.2</b></a>

Ссылка на саму себя и подпись внутри SVG обходятся без <a>: достаточно
<b class="xref__n" data-ch="k-kodu">71</b>, в SVG вместо <b> — <tspan>.

Что делает скрипт:
  · `--check`   — ничего не пишет. Ищет: битые href и якоря, слаги, которых
                  нет в реестре, записанные числа, разошедшиеся с реестром,
                  подписи фигур и id фигур не по схеме `fig-<слаг>-<k>`.
                  Код возврата 1, если нашёл хоть что-то.
  · `--fix`     — приводит записанные числа, href и title к реестру и
                  превращает оставшийся текст «глава N» в отсылку `a.xref`
                  (N читается как номер по текущему реестру).
  · `--dry-run` — то же, что --fix, но только отчёт.

Запускается из любого каталога, зависимостей нет.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

BOOK = Path(__file__).resolve().parent.parent

# ── реестр глав ─────────────────────────────────────────────────────────────

CHAPTER_RE = re.compile(
    r'\{\s*id:\s*"([^"]+)"\s*,\s*part:\s*"([^"]+)"\s*,\s*file:\s*"([^"]+)"\s*,'
    r'\s*title:\s*"([^"]+)"\s*,\s*status:\s*"([^"]+)"\s*\}'
)


class Chapter:
    __slots__ = ("id", "part", "file", "title", "status", "n")

    def __init__(self, cid, part, file, title, status, n):
        self.id, self.part, self.file = cid, part, file
        self.title, self.status, self.n = title, status, n

    @property
    def done(self) -> bool:
        return self.status == "done"


def load_registry() -> list:
    src = (BOOK / "assets" / "chapters.js").read_text(encoding="utf-8")
    rows = CHAPTER_RE.findall(src)
    if len(rows) < 20:
        raise SystemExit("реестр глав не разобран: найдено %d записей" % len(rows))
    return [Chapter(cid, part, file, title, status, i + 1)
            for i, (cid, part, file, title, status) in enumerate(rows)]


# ── разбор HTML на «можно править» / «нельзя трогать» ───────────────────────

TOKEN_RE = re.compile(r"<!--.*?-->|<[^>]*>", re.S)
OPAQUE = ("svg", "script", "style", "head", "a", "code")
TAG_NAME_RE = re.compile(r"^<\s*(/?)\s*([a-zA-Z0-9]+)")

# «глава 7», «в главе 17», «главы 15 и 16», «главах 13, 14 и 20».
REF_RE = re.compile(
    r"(?P<word>[Гг]лав[аеиуыойх]{0,3})"
    r"(?P<gap>&nbsp;|\s)+"
    r"(?P<first>\d{1,3})"
    r"(?P<tail>(?:(?:(?:,|\s+и)(?:&nbsp;|\s)+|\s*[–—]\s*)\d{1,3})*)"
)
TAIL_NUM_RE = re.compile(r"\d{1,3}")


# Пробел перед номером — неразрывный: «главу 56» не расходится по строкам.
# Именно здесь, а не в CSS: `white-space: nowrap` на всей ссылке запрещает
# перенос и в остальном её тексте и на 320 px выталкивает страницу в скролл.
NBSP_BEFORE_NUM = re.compile(r'(?:\s|&nbsp;)+(?=<(?:b|tspan) class="xref__n")')


def xref(c: Chapter, text: str, self_id: str) -> str:
    """Отсылка целиком: слаг ведёт, число — запасной вариант для печати."""
    href = "" if c.id == self_id else c.file
    return ('<a class="xref" data-ch="%s" href="%s" title="%d. %s">%s'
            '<b class="xref__n">%d</b></a>'
            % (c.id, href, c.n, c.title, re.sub(r"(?:\s|&nbsp;)+$", "&nbsp;", text), c.n))


def linkify_text(text: str, self_id: str, by_n: dict, stats: dict) -> str:
    def repl(m: re.Match) -> str:
        first = int(m.group("first"))
        if first not in by_n:
            return m.group(0)
        whole = m.group(0)
        head_len = whole.index(m.group("first"))
        head_txt, num_txt = whole[:head_len], whole[head_len:head_len + len(m.group("first"))]
        tail_txt = whole[head_len + len(num_txt):]
        stats["linked"] = stats.get("linked", 0) + 1
        out = xref(by_n[first], head_txt, self_id)

        def tail_repl(tm: re.Match) -> str:
            n = int(tm.group(0))
            if n not in by_n:
                return tm.group(0)
            stats["linked"] = stats.get("linked", 0) + 1
            return xref(by_n[n], "", self_id)

        return out + TAIL_NUM_RE.sub(tail_repl, tail_txt)

    return REF_RE.sub(repl, text)


EYEBROW_RE = re.compile(r'<p class="chapter-eyebrow">[^<]*</p>')


def linkify_plain(src: str, self_id: str, by_n: dict, stats: dict) -> str:
    """Обходит документ, размечая только настоящий текст.

    Хлебная крошка «Часть IV · … · Глава 12» — не отсылка, а подпись самой
    страницы, и её целиком переписывает book.js. Ссылку в ней ставить нельзя.
    """
    saved: list = []
    src = EYEBROW_RE.sub(lambda m: saved.append(m.group(0)) or "\x00E%d\x00" % (len(saved) - 1), src)
    out: list = []
    stack: list = []
    pos = 0
    for m in TOKEN_RE.finditer(src):
        chunk = src[pos:m.start()]
        if chunk:
            out.append(chunk if stack else linkify_text(chunk, self_id, by_n, stats))
        tag = m.group(0)
        out.append(tag)
        pos = m.end()
        if tag.startswith("<!--"):
            continue
        tm = TAG_NAME_RE.match(tag)
        if not tm:
            continue
        closing, name = tm.group(1) == "/", tm.group(2).lower()
        if name not in OPAQUE:
            continue
        if closing:
            if stack and stack[-1] == name:
                stack.pop()
        elif not tag.rstrip().endswith("/>"):
            stack.append(name)
    tail = src[pos:]
    if tail:
        out.append(tail if stack else linkify_text(tail, self_id, by_n, stats))
    return re.sub(r"\x00E(\d+)\x00", lambda m: saved[int(m.group(1))], "".join(out))


# ── пересчёт записанных чисел ───────────────────────────────────────────────

XREF_A_RE = re.compile(r'<a\s+class="xref"([^>]*)>(.*?)</a>', re.S)
FIGREF_A_RE = re.compile(r'<a\s+class="figref"([^>]*)>(.*?)</a>', re.S)
BARE_N_RE = re.compile(r'<(b|tspan) class="xref__n" data-ch="([^"]+)">([^<]*)</\1>')
FIGNUM_RE = re.compile(r'<span class="figure__num">([^<]*)</span>')
FIGID_RE = re.compile(r'<figure class="figure" id="([^"]*)"')
ATTR_RE = re.compile(r'([a-zA-Z-]+)="([^"]*)"')
NUM_SPAN_RE = re.compile(r'<(b|tspan) class="(xref__n|figref__n)">([^<]*)</\1>')


def attrs(s: str) -> dict:
    return dict(ATTR_RE.findall(s))


def resync(src: str, self_id: str, by_id: dict,
           broken: list = None, stale: list = None) -> str:
    """Приводит записанные в разметке числа, href и title к реестру.

    Одна функция и для починки, и для проверки: `--check` вызывает её же и
    смотрит, что она хотела бы изменить. Две реализации одной сверки — ровно
    тот класс ошибки, ради которого затевалось слияние.
    """
    broken = [] if broken is None else broken
    stale = [] if stale is None else stale

    def note(m, new, what):
        if new != m.group(0):
            stale.append(what)
        return new

    def fix_xref(m: re.Match) -> str:
        a, body = attrs(m.group(1)), m.group(2)
        c = by_id.get(a.get("data-ch", ""))
        if not c:
            broken.append("xref на неизвестный слаг %r" % a.get("data-ch"))
            return m.group(0)
        anchor = a.get("data-anchor")
        head = '<a class="xref" data-ch="%s"%s href="%s%s" title="%d. %s">' % (
            c.id, ' data-anchor="%s"' % anchor if anchor else "",
            "" if c.id == self_id else c.file, "#" + anchor if anchor else "", c.n, c.title)
        new = head + NBSP_BEFORE_NUM.sub("&nbsp;", NUM_SPAN_RE.sub(
            lambda n: '<%s class="%s">%d</%s>' % (n.group(1), n.group(2), c.n, n.group(1)),
            body)) + "</a>"
        return note(m, new, "отсылка на главу %r" % c.id)

    def fix_figref(m: re.Match) -> str:
        a, body = attrs(m.group(1)), m.group(2)
        c, k = by_id.get(a.get("data-ch", "")), a.get("data-fig", "")
        if not c or not k.isdigit():
            broken.append("figref на неизвестный слаг %r" % a.get("data-ch"))
            return m.group(0)
        new = '<a class="figref" data-ch="%s" data-fig="%s" href="%s#fig-%s-%s">' % (
            c.id, k, "" if c.id == self_id else c.file, c.id, k)
        new += NUM_SPAN_RE.sub(
            lambda n: '<%s class="%s">%d.%s</%s>' % (n.group(1), n.group(2), c.n, k, n.group(1)),
            body) + "</a>"
        return note(m, new, "отсылка на рис. %s-%s" % (c.id, k))

    def fix_bare(m: re.Match) -> str:
        c = by_id.get(m.group(2))
        if not c:
            broken.append("голый номер на неизвестный слаг %r" % m.group(2))
            return m.group(0)
        return note(m, '<%s class="xref__n" data-ch="%s">%d</%s>'
                    % (m.group(1), c.id, c.n, m.group(1)), "номер главы %r" % c.id)

    src = XREF_A_RE.sub(fix_xref, src)
    src = FIGREF_A_RE.sub(fix_figref, src)
    src = BARE_N_RE.sub(fix_bare, src)

    me = by_id.get(self_id)
    if me:
        counter = [0]

        def fix_fignum(m):
            counter[0] += 1
            return note(m, '<span class="figure__num">Рис. %d.%d.</span>' % (me.n, counter[0]),
                        "подпись рис. %d.%d" % (me.n, counter[0]))

        src = FIGNUM_RE.sub(fix_fignum, src)
    return src


def refs_report(src: str, self_id: str, by_id: dict) -> tuple:
    """(битые слаги, разошедшиеся числа) — то же, что чинит resync."""
    broken: list = []
    stale: list = []
    resync(src, self_id, by_id, broken, stale)
    return broken, stale


# ── проверки ────────────────────────────────────────────────────────────────

HREF_RE = re.compile(r'href="([^"]+)"')
ID_RE = re.compile(r'\sid="([^"]+)"')


def pages(reg: list) -> list:
    out = [BOOK / c.file for c in reg if c.done]
    out += [BOOK / "index.html", BOOK / "errata.html"]
    return [p for p in out if p.exists()]


def check(reg: list) -> int:
    by_id = {c.id: c for c in reg}
    files = pages(reg)
    ids: dict = {}
    for f in files:
        ids[f.name] = set(ID_RE.findall(f.read_text(encoding="utf-8")))

    bad: list = []

    for f in files:
        src = f.read_text(encoding="utf-8")
        self_id = next((c.id for c in reg if c.file == f.name), "")

        # 1. висячие адреса и якоря
        for href in HREF_RE.findall(src):
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            target, _, frag = href.partition("#")
            if not target:
                if frag and frag not in ids[f.name]:
                    bad.append("%s → #%s (нет якоря)" % (f.name, frag))
                continue
            dest = (f.parent / target).resolve()
            if not dest.exists():
                bad.append("%s → %s (нет файла)" % (f.name, target))
                continue
            if frag:
                known = ids.get(dest.name)
                if known is None:
                    known = set(ID_RE.findall(dest.read_text(encoding="utf-8")))
                    ids[dest.name] = known
                if frag not in known:
                    bad.append("%s → %s#%s (нет якоря)" % (f.name, target, frag))

        # 2. слаги, номера, адреса отсылок — сверка с реестром
        broken, stale = refs_report(src, self_id, by_id)
        bad.extend("%s: %s" % (f.name, b) for b in broken)
        bad.extend("%s: %s — записанное число разошлось с реестром "
                   "(чинится `linkify.py --fix`)" % (f.name, s) for s in stale)

        # 3. id фигур: fig-<слаг>-<k> по порядку
        if self_id:
            for k, fid in enumerate(FIGID_RE.findall(src), 1):
                if fid != "fig-%s-%d" % (self_id, k):
                    bad.append("%s: id фигуры %r, ожидался fig-%s-%d" % (f.name, fid, self_id, k))

    # 4. реестр против диска
    seen = set()
    for c in reg:
        if c.id in seen:
            bad.append("реестр: слаг %r встречается дважды" % c.id)
        seen.add(c.id)
        if c.done and not (BOOK / c.file).exists():
            bad.append("реестр: глава %d %r помечена done, файла %s нет" % (c.n, c.id, c.file))
        if not c.done and (BOOK / c.file).exists():
            bad.append("реестр: файл %s есть, а статус %r" % (c.file, c.status))

    for line in bad:
        print("БИТО " + line)
    print("проверено страниц: %d (глав написано %d из %d) · дефектов: %d"
          % (len(files), sum(1 for c in reg if c.done), len(reg), len(bad)))
    return len(bad)


# ── прогон ──────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    reg = load_registry()
    if "--check" in sys.argv:
        return 1 if check(reg) else 0

    by_id = {c.id: c for c in reg}
    by_n = {c.n: c for c in reg}
    dry = "--dry-run" in sys.argv
    total = 0
    for c in reg:
        path = BOOK / c.file
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        stats: dict = {}
        broken: list = []
        new = resync(src, c.id, by_id, broken)
        new = linkify_plain(new, c.id, by_n, stats)
        got = stats.get("linked", 0)
        total += got
        for p in broken:
            print("  ! %s: %s" % (c.file, p))
        if new != src and not dry:
            io.open(path, "w", encoding="utf-8", newline="").write(new)
        print("гл. %2d  %-38s новых ссылок: %3d%s"
              % (c.n, c.file, got, "" if new == src else " · номера пересчитаны"))

    # Служебные страницы: числа в отсылках пересчитываем, текст не размечаем.
    # На обложке и в errata «глава N» встречается в датированных записях,
    # которые не перенумеровываются (FULL-BOOK-PLAN §6.5 п. 10).
    for name in ("index.html", "errata.html"):
        path = BOOK / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        broken = []
        new = resync(src, "", by_id, broken)
        for p in broken:
            print("  ! %s: %s" % (name, p))
        if new != src and not dry:
            io.open(path, "w", encoding="utf-8", newline="").write(new)
        print("        %-38s %s" % (name, "номера пересчитаны" if new != src else "без изменений"))

    print("─" * 78)
    print("всего размечено ссылок: %d%s" % (total, "  (dry-run)" if dry else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
