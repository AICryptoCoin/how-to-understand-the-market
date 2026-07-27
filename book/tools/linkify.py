#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Превращает текстовые отсылки «глава N» в гиперссылки на файл главы.

Книга свёрстана как гипертекст, но её собственные перекрёстные отсылки были
бумажными: 206 раз «см. главу 17» и ровно одна настоящая ссылка. Скрипт
закрывает это механически.

Что делает:
  · читает реестр глав из assets/chapters.js (номер → файл, заголовок);
  · в каждом файле главы находит текстовые вхождения «глав[аеиуыой] N»
    и оборачивает их в <a href="chNN-….html" title="N. Заголовок">;
  · перечисления «в главах 13 и 14», «главы 15, 16 и 18» размечает целиком —
    каждый номер получает свою ссылку;
  · НЕ трогает: содержимое <svg>, <script>, <style>, <head>, текст внутри
    уже существующих <a>, любые атрибуты тегов (там живёт разметка тултипов),
    и отсылки главы на саму себя (в «хлебной крошке» и в тексте).

Запуск:
    python tools/linkify.py            # правит файлы
    python tools/linkify.py --dry-run  # только отчёт
    python tools/linkify.py --check    # проверка: висячих ссылок нет
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

BOOK = Path(__file__).resolve().parent.parent

# ── реестр глав ─────────────────────────────────────────────────────────────

CHAPTER_RE = re.compile(
    r'\{\s*n:\s*(\d+)\s*,\s*part:\s*\d+\s*,\s*file:\s*"([^"]+)"\s*,\s*title:\s*"([^"]+)"'
)


def load_registry() -> dict[int, tuple[str, str]]:
    src = (BOOK / "assets" / "chapters.js").read_text(encoding="utf-8")
    reg = {int(n): (f, t) for n, f, t in CHAPTER_RE.findall(src)}
    if len(reg) < 20:
        raise SystemExit("реестр глав не разобран: найдено %d записей" % len(reg))
    return reg


# ── разбор HTML на «можно править» / «нельзя трогать» ───────────────────────

# Открывающий/закрывающий тег либо комментарий. Всё, что между ними, — текст.
TOKEN_RE = re.compile(r"<!--.*?-->|<[^>]*>", re.S)

# Зоны, внутри которых текст не размечается.
OPAQUE = ("svg", "script", "style", "head", "a", "code")

TAG_NAME_RE = re.compile(r"^<\s*(/?)\s*([a-zA-Z0-9]+)")

# «глава 7», «в главе 17», «главы 15 и 16», «главах 13, 14 и 20».
REF_RE = re.compile(
    r"(?P<word>[Гг]лав[аеиуыойх]{0,3})"
    r"(?P<gap>&nbsp;|\s)+"
    r"(?P<first>\d{1,2})"
    r"(?P<tail>(?:(?:(?:,|\s+и)(?:&nbsp;|\s)+|\s*[–—]\s*)\d{1,2})*)"
)

TAIL_NUM_RE = re.compile(r"\d{1,2}")


def link(num: int, text: str, reg) -> str:
    file, title = reg[num]
    return '<a href="%s" title="%s. %s">%s</a>' % (file, num, title, text)


def linkify_text(text: str, self_n: int, reg, stats: dict) -> str:
    def repl(m: re.Match) -> str:
        first = int(m.group("first"))
        if first not in reg:
            return m.group(0)
        if first == self_n:
            stats["self"] = stats.get("self", 0) + 1
            return m.group(0)
        head = m.group("word") + m.group("gap") * 0 + m.group(0)[len(m.group("word")):]
        # head сейчас — весь матч; разбираем его на части заново
        whole = m.group(0)
        head_len = whole.index(m.group("first")) + len(m.group("first"))
        head_txt, tail_txt = whole[:head_len], whole[head_len:]
        out = link(first, head_txt, reg)
        stats["linked"] = stats.get("linked", 0) + 1

        def tail_repl(tm: re.Match) -> str:
            n = int(tm.group(0))
            if n not in reg or n == self_n:
                return tm.group(0)
            stats["linked"] = stats.get("linked", 0) + 1
            return link(n, tm.group(0), reg)

        return out + TAIL_NUM_RE.sub(tail_repl, tail_txt)

    return REF_RE.sub(repl, text)


def process(path: Path, self_n: int, reg, stats: dict) -> str:
    src = path.read_text(encoding="utf-8")
    out: list[str] = []
    stack: list[str] = []
    pos = 0
    for m in TOKEN_RE.finditer(src):
        chunk = src[pos:m.start()]
        if chunk:
            out.append(chunk if stack else linkify_text(chunk, self_n, reg, stats))
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
        out.append(tail if stack else linkify_text(tail, self_n, reg, stats))
    return "".join(out)


# ── проверка: ни одна ссылка не ведёт в никуда ──────────────────────────────

HREF_RE = re.compile(r'href="([^"]+)"')
ID_RE = re.compile(r'\sid="([^"]+)"')


def check(reg) -> int:
    files = sorted(BOOK.glob("ch*.html")) + [BOOK / "index.html"]
    ids: dict[str, set[str]] = {}
    for f in files:
        ids[f.name] = set(ID_RE.findall(f.read_text(encoding="utf-8")))
    bad = 0
    for f in files:
        src = f.read_text(encoding="utf-8")
        for href in HREF_RE.findall(src):
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            target, _, frag = href.partition("#")
            if not target:                       # чистый якорь внутри файла
                if frag and frag not in ids[f.name]:
                    print("БИТО %s → #%s" % (f.name, frag)); bad += 1
                continue
            dest = (f.parent / target).resolve()
            if not dest.exists():
                print("БИТО %s → %s (нет файла)" % (f.name, target)); bad += 1
                continue
            if frag:
                known = ids.get(dest.name)
                if known is None:
                    known = set(ID_RE.findall(dest.read_text(encoding="utf-8")))
                    ids[dest.name] = known
                if frag not in known:
                    print("БИТО %s → %s#%s (нет якоря)" % (f.name, target, frag)); bad += 1
    print("проверено файлов: %d · битых ссылок: %d" % (len(files), bad))
    return bad


def main() -> int:
    reg = load_registry()
    if "--check" in sys.argv:
        return 1 if check(reg) else 0

    dry = "--dry-run" in sys.argv
    total = 0
    for n, (fname, _) in sorted(reg.items()):
        path = BOOK / fname
        stats: dict[str, int] = {}
        new = process(path, n, reg, stats)
        got = stats.get("linked", 0)
        total += got
        if got and not dry:
            io.open(path, "w", encoding="utf-8", newline="").write(new)
        print("гл. %2d  %-42s ссылок: %3d · своих пропущено: %d"
              % (n, fname, got, stats.get("self", 0)))
    print("─" * 78)
    print("всего проставлено ссылок: %d%s" % (total, "  (dry-run)" if dry else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
