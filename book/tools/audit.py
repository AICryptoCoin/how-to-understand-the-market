#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Аудит книги «Как понимать рынок».

Считает по каждой главе объём, состав, дисциплину происхождения, наличие
обязательных блоков структуры (STYLE-GUIDE §3) и технические дефекты вёрстки
(STYLE-GUIDE §5). Ничего не правит — только печатает.

Запуск из любого каталога:

    python audit.py             таблицы + сводка
    python audit.py --all       не обрезать списки конкретных дефектов
    python audit.py --json      то же машиночитаемо (для CI)
    python audit.py --selftest  проверить сами детекторы на эталонах

Код возврата: 0 — дефектов нет, 1 — есть, 2 — не нашлись файлы книги.
Зависимостей нет: только стандартная библиотека Python ≥3.8.

--------------------------------------------------------------------------
Почему --selftest обязателен. Книга сейчас чистая, и таблица дефектов из одних
нулей неотличима от сломанного детектора. `tools/fixtures/broken.html` намеренно
содержит по экземпляру каждого дефекта, `clean.html` — ни одного; --selftest
сверяет реальные счётчики с ожидаемыми. Меняете детектор — прогоните его.

Что считается «прозой». Текст внутри <article class="prose">, из которого
исключён весь текст внутри <svg>. Подписи внутри графики считаются отдельной
колонкой. Текст в атрибутах (data-tip у фигур) не входит никуда, хотя читателю
он виден: наивный strip тегов регуляркой его захватывает и даёт завышенный
примерно на 7 тыс. слов итог — отсюда расхождение со старыми цифрами.

Карта «класс → свойство» для проверки перебитых атрибутов не зашита, а читается
из assets/book.css: правки палитры и viz-классов подхватываются сами.

Про номера глав. Номер не хранится нигде: он равен позиции главы в
assets/chapters.js. В разметке номер всё-таки записан — страница обязана
читаться без JavaScript, — поэтому есть что сверять, и сверку делает
tools/linkify.py. Аудит зовёт его же (одна реализация на два инструмента) и
показывает результат поглавно: битые слаги, разошедшиеся числа и текстовые
«глава N», оставшиеся вне отсылок.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import linkify  # noqa: E402  — сверка отсылок живёт там и только там
import mathcheck  # noqa: E402  — поломки формул живут там и только там

# ─────────────────────────────────────────────────────────────────────────────
# Пороги вердикта. Меняются здесь и больше нигде.
# ─────────────────────────────────────────────────────────────────────────────

THIN_WORDS = 5000      # меньше — глава считается тонкой
THIN_FIGURES = 2       # меньше — глава считается тонкой
VALUE_TEXT_NODES = 4   # столько числовых подписей в SVG => фигура «со значениями»
EXAMPLES = 15          # сколько конкретных случаев печатать под таблицей дефектов

# Свойства, ради которых разбирается CSS: только они конфликтуют с
# презентационными атрибутами SVG (STYLE-GUIDE §5 п. 6).
TRACKED_PROPS = ("fill", "stroke", "stroke-width", "marker-end")

# Пометки происхождения (STYLE-GUIDE §6, расширение — FULL-BOOK-PLAN §5.2).
ORIGIN_MARKS = ("КАНОН", "ВЫВЕДЕНО", "ДОПОЛНЕНО", "НАШЕ РЕШЕНИЕ", "НЕТ В КУРСЕ",
                "СПОР", "НАШ РАСЧЁТ", "НЕ ПРОВЕРЕНО")

# Типы врезок: класс → (значок, короткое имя).
CALLOUT_KINDS = [
    ("callout--rule",   "⌘", "правило"),
    ("callout--2026",   "↻", "2023→2026"),
    ("callout--crypto", "₿", "крипто"),
    ("callout--trap",   "⚠", "ловушка"),
    ("callout--source", "❞", "источник"),
    ("callout--ours",   "◆", "наше"),
    ("callout--beyond", "✚", "дополнено"),
    ("callout--test",   "⌗", "проверить"),
    ("callout--debate", "⚖", "спор"),
]

# Блоки структуры (STYLE-GUIDE §3). Обязательные входят в вердикт;
# условные показываются в таблице, но главу не бракуют: крипто-слой и врезка
# «2023 → 2026» перестали быть обязательными (FULL-BOOK-PLAN §4 п. 8, §5.1),
# а блок «Как это проверить» нужен только главе с эмпирическим утверждением.
STRUCTURE_KEYS = [
    ("eyebrow", "eyebrow"), ("lede", "lede"), ("map", "map"),
    ("crypto", "крипто"), ("c2026", "2023→2026"), ("test", "проверить"),
    ("checklist", "чек-лист"), ("further", "дальше"),
]
STRUCTURE_REQUIRED = {"eyebrow", "lede", "map", "checklist", "further"}

# Технические дефекты: ключ → заголовок колонки.
DEFECT_KEYS = [
    ("html_in_text", "HTML в <text>"),
    ("dup_ids", "Дубли id"),
    ("broken_refs", "Битые url(#)"),
    ("overridden", "Атрибут под классом"),
    ("tables_unscrolled", "Табл. вне scroll"),
    ("hex_colors", "Hex в SVG"),
    ("xref_broken", "Слаг не в реестре"),
    ("xref_stale", "Номер разошёлся"),
    ("text_ch_ref", "Текст «глава N»"),
    ("math_broken", "Формула сломана"),
]

# Классы, текст внутри которых — уже отсылка либо служебная подпись,
# которую переписывает book.js. Текстовые «глава N» ищутся вне их.
MUTE_CLASSES = {"xref", "figref", "xref__n", "figref__n", "chapter-eyebrow"}

# «глава 7», «в главе 17», «главах 13, 14 и 20» — то, что обязано быть отсылкой.
# Отсылка не пересекает границу блока: заголовок ячейки «Пример из главы» и
# следующая ячейка «1» — это не «глава 1». Границу ставит \x00 (см. ChapterParser).
TEXT_CH_REF = re.compile(r"[Гг]лав[аеиуыойх]{0,3}[^\S\x00]+\d{1,3}")

# Теги, которые стоят внутри предложения и текст не разрывают.
INLINE_TAGS = {
    "a", "abbr", "b", "big", "br", "cite", "code", "em", "i", "kbd", "mark",
    "q", "s", "samp", "small", "span", "strong", "sub", "sup", "time", "u", "var",
}
DEFECT_LABELS = dict(DEFECT_KEYS)
DEFECT_LABELS["figures_no_twin"] = "фигуры со значениями без двойника"

# Теги, у которых в SVG не бывает детей: html.parser про SVG не знает и без
# этого списка ломает стек предков на записи вида <rect …> без слеша.
SVG_VOID = {
    "path", "circle", "rect", "line", "polyline", "polygon", "ellipse",
    "use", "stop", "image",
}
HTML_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# HTML-разметка внутри SVG <text> не рендерится (STYLE-GUIDE §5 п. 1).
HTML_IN_TEXT = {"b", "i", "strong", "em", "br", "u", "span", "code", "small"}

# Числовая подпись: «50», «−1.5 %», «2 400», «12 б.п.».
NUMERIC_TEXT = re.compile(
    r"^[+\-−–—]?\s*\d[\d\s\u00a0.,:/–—-]*\s*"
    r"(%|‰|\$|₽|€|×|x|п\.п\.|б\.п\.|бп|пп|млрд|млн|трлн|тыс\.?)?$"
)
# Голое одно-двузначное целое: кандидат в номер шага блок-схемы, а не в значение.
BARE_INT = re.compile(r"^\d{1,2}$")


def measured_values(texts: list) -> list:
    """Оставляет из числовых подписей только те, что похожи на значения.

    Блок-схемы нумеруют шаги теми же <text class="viz-axis">, что и оси:
    «1, 2, 3 … 13» на конвейере главы 21 неотличимы от делений шкалы, пока не
    посмотреть на набор целиком. Сплошной ряд 1..k без пропусков — это
    нумерация, а не измерение, такие подписи отбрасываем. Ось «45 50 55 60»
    рядом 1..k не является и значениями остаётся.
    """
    numeric = [t for t in texts if NUMERIC_TEXT.match(t)]
    bare = {int(t) for t in numeric if BARE_INT.match(t)}
    if len(bare) >= 3 and bare == set(range(1, len(bare) + 1)):
        return [t for t in numeric if not BARE_INT.match(t)]
    return numeric

# Хардкод цвета: ровно 3/4/6/8 hex-символов и дальше не буква-цифра-дефис,
# чтобы url(#arrow-f42) и aria-ссылка #f61t не считались цветом.
HEX_COLOR = re.compile(
    r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})"
    r"(?![0-9a-zA-Z_-])"
)
URL_REF = re.compile(r"url\(\s*['\"]?#([^)'\"\s]+)")

COLOR_ATTRS = ("fill", "stroke", "stop-color", "color", "flood-color", "style",
               "lighting-color", "solid-color")


# ─────────────────────────────────────────────────────────────────────────────
# Разбор CSS: какой класс какое свойство задаёт
# ─────────────────────────────────────────────────────────────────────────────

def strip_at_blocks(css: str) -> str:
    """Выбрасывает @media/@supports целиком — цвет графики они не задают."""
    out, i = [], 0
    while True:
        at = css.find("@", i)
        if at < 0:
            out.append(css[i:])
            return "".join(out)
        brace = css.find("{", at)
        if brace < 0:
            out.append(css[i:])
            return "".join(out)
        out.append(css[i:at])
        depth, j = 0, brace
        while j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1


def parse_css_class_props(css_path: Path) -> dict:
    """`.viz-box { fill: A; stroke: B }` → {"viz-box": {"fill": "A", "stroke": "B"}}."""
    css = css_path.read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = strip_at_blocks(css)
    result: dict = {}
    for sel_raw, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        props = {}
        for m in re.finditer(r"(?:^|;)\s*([a-zA-Z-]+)\s*:([^;]*)", body):
            name = m.group(1).strip().lower()
            if name in TRACKED_PROPS:
                props[name] = m.group(2).strip()
        if not props:
            continue
        for sel in sel_raw.split(","):
            sel = sel.strip()
            # Только одиночный класс без псевдо и без вложенности:
            # .viz-hit:focus-visible действует лишь при фокусе, а .figure svg text
            # задаёт шрифт и к цвету отношения не имеет.
            m = re.fullmatch(r"\.([A-Za-z0-9_-]+)", sel)
            if m:
                result.setdefault(m.group(1), {}).update(props)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Разбор главы
# ─────────────────────────────────────────────────────────────────────────────

class ChapterParser(HTMLParser):
    def __init__(self, class_props: dict):
        super().__init__(convert_charrefs=True)
        self.cp = class_props

        self.stack: list = []      # [(tag, classes)] — только элементы с детьми
        self.svg_depth = 0
        self.skip_depth = 0        # script/style/head
        self.article_depth = 0
        self.text_depth = 0        # внутри SVG <text>

        self.prose: list = []
        self.plain: list = []      # проза без текста отсылок и хлебных крошек
        self.svg_words = 0

        self.figures: list = []    # {"id", "has_table", "texts"}
        self.cur_fig = None

        self.tables_total = 0
        self.tables_unscrolled: list = []
        self.indicators = 0
        self.callouts = {cls: 0 for cls, _, _ in CALLOUT_KINDS}
        self.checklists = 0
        self.has_eyebrow = False
        self.has_lede = False
        self.has_map = False

        self.headings: list = []
        self._heading_buf = None

        self.ids: dict = {}
        self.url_refs: list = []   # [(refid, «где»)]

        self.html_in_text: list = []
        self.overridden: list = []
        self.hex_colors: list = []

        self._text_buf: list = []

    # — служебное —

    def _fig_label(self) -> str:
        if self.cur_fig is not None:
            return self.cur_fig["id"] or f"фигура {len(self.figures)}"
        return "вне фигуры"

    def _in_scroll(self) -> bool:
        return any("table-scroll" in classes for _, classes in self.stack)

    def _muted(self) -> bool:
        return any(classes & MUTE_CLASSES for _, classes in self.stack)

    # — теги —

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, self_closing=True)

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, self_closing=False)

    def _start(self, tag, attrs, self_closing):
        tag = tag.lower()
        d = {k.lower(): (v or "") for k, v in attrs}
        classes = set(d.get("class", "").split())

        if tag == "svg":
            self.svg_depth += 1
        if tag in ("script", "style", "head"):
            self.skip_depth += 1
        if tag == "article":
            self.article_depth += 1

        if d.get("id"):
            self.ids[d["id"]] = self.ids.get(d["id"], 0) + 1

        if tag == "figure" and "figure" in classes:
            self.cur_fig = {"id": d.get("id", ""), "has_table": False, "texts": []}
            self.figures.append(self.cur_fig)
        if self.cur_fig is not None and "figure__table" in classes:
            self.cur_fig["has_table"] = True

        for name, val in d.items():
            for m in URL_REF.finditer(val):
                self.url_refs.append(
                    (m.group(1), f"{self._fig_label()}: <{tag} {name}=…>"))

        if tag == "table":
            self.tables_total += 1
            if not self._in_scroll():
                self.tables_unscrolled.append(self._fig_label())
        if "indicator" in classes:
            self.indicators += 1
        for cls in self.callouts:
            if cls in classes:
                self.callouts[cls] += 1
        if tag == "ul" and "checklist" in classes:
            self.checklists += 1
        if "chapter-eyebrow" in classes:
            self.has_eyebrow = True
        if "chapter-lede" in classes:
            self.has_lede = True
        if "chapter-map" in classes:
            self.has_map = True

        if tag in ("h1", "h2", "h3"):
            self._heading_buf = []

        if self.article_depth and not self.svg_depth and tag not in INLINE_TAGS:
            self.plain.append("\x00")

        if self.svg_depth:
            self._check_svg_element(tag, d, classes)
            if tag == "text":
                self.text_depth += 1
                self._text_buf = []
            elif self.text_depth and tag in HTML_IN_TEXT:
                self.html_in_text.append(f"{self._fig_label()}: <{tag}> внутри <text>")

        if self_closing:
            return
        if tag in HTML_VOID or (self.svg_depth and tag in SVG_VOID):
            # предками такие элементы не бывают: на стек не кладём,
            # закрывающий тег для них игнорируется в handle_endtag
            return
        self.stack.append((tag, classes))

    def _check_svg_element(self, tag, d, classes):
        """Перебитые классом атрибуты и хардкод цвета — STYLE-GUIDE §5 п. 4 и 6."""
        styled = {
            m.group(1).strip().lower()
            for m in re.finditer(r"(?:^|;)\s*([a-zA-Z-]+)\s*:", d.get("style", ""))
        }
        for cls in sorted(classes):
            for prop, css_val in self.cp.get(cls, {}).items():
                if prop in styled:
                    continue                       # инлайн-стиль перекрывает класс
                if prop in d:
                    # атрибут есть, но класс сильнее — акцент молча пропадёт
                    self.overridden.append((self._fig_label(), tag, cls, prop))
                else:
                    # атрибута нет: работает значение из CSS. Если это url(#…),
                    # ссылка обязана существовать в этом же документе.
                    for m in URL_REF.finditer(css_val):
                        self.url_refs.append((
                            m.group(1),
                            f'{self._fig_label()}: <{tag} class="{cls}"> '
                            f"наследует {prop} из CSS"))
        for attr in COLOR_ATTRS:
            val = d.get(attr)
            hit = HEX_COLOR.search(val) if val else None
            if hit:
                self.hex_colors.append((self._fig_label(), tag, attr, hit.group(0)))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in HTML_VOID or (self.svg_depth and tag in SVG_VOID):
            return

        if self.article_depth and not self.svg_depth and tag not in INLINE_TAGS:
            self.plain.append("\x00")

        if tag == "text" and self.text_depth:
            self.text_depth -= 1
            txt = re.sub(r"\s+", " ", "".join(self._text_buf)).strip()
            if self.cur_fig is not None and txt:
                self.cur_fig["texts"].append(txt)
            self._text_buf = []
        if tag in ("h1", "h2", "h3") and self._heading_buf is not None:
            self.headings.append(
                re.sub(r"\s+", " ", "".join(self._heading_buf)).strip())
            self._heading_buf = None
        if tag == "svg" and self.svg_depth:
            self.svg_depth -= 1
        if tag in ("script", "style", "head") and self.skip_depth:
            self.skip_depth -= 1
        if tag == "article" and self.article_depth:
            self.article_depth -= 1
        if tag == "figure" and self.cur_fig is not None:
            self.cur_fig = None

        # снимаем стек до ближайшего совпадения: кривую вложенность не роняем
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self._heading_buf is not None:
            self._heading_buf.append(data)
        if self.svg_depth:
            if self.text_depth:
                self._text_buf.append(data)
            self.svg_words += len(data.split())
            return
        if self.article_depth:
            self.prose.append(data)
            self.plain.append(" " if self._muted() else data)


def audit_chapter(path: Path, meta: dict, class_props: dict, by_id: dict = None) -> dict:
    raw = path.read_text(encoding="utf-8")
    p = ChapterParser(class_props)
    p.feed(raw)
    p.close()

    prose = re.sub(r"\s+", " ", "".join(p.prose)).strip()
    words = len(prose.split())

    # Отсылки: сверка целиком отдана linkify — там же, где чинится.
    xref_broken, xref_stale = linkify.refs_report(
        raw, meta.get("id", ""), by_id if by_id is not None else {})
    plain = re.sub(r"\s+", " ", "".join(p.plain))
    text_ch_ref = [m.group(0) for m in TEXT_CH_REF.finditer(plain)]

    # Комбинированные пометки вида [ДОПОЛНЕНО: …; ВЫВЕДЕНО по следствию] —
    # это честно два голоса, поэтому считаем каждое вхождение отдельно.
    # Пометка — целое слово в капсе: «СПОРНЫЙ» в подписи графики не является
    # пометкой [СПОР], а «КАНОНИЧЕСКИЙ» — пометкой [КАНОН].
    math_broken = mathcheck.check(raw)

    marks = {m: len(re.findall(r"(?<![А-ЯЁA-Z])%s(?![А-ЯЁA-Zа-яёa-z])" % re.escape(m), raw))
             for m in ORIGIN_MARKS}

    with_values = [f for f in p.figures
                   if len(measured_values(f["texts"])) >= VALUE_TEXT_NODES]
    missing_twin = [f for f in with_values if not f["has_table"]]

    dup_ids = sorted(k for k, v in p.ids.items() if v > 1)
    broken_refs = [f"#{ref} — {where}" for ref, where in p.url_refs if ref not in p.ids]

    structure = {
        "eyebrow": p.has_eyebrow,
        "lede": p.has_lede,
        "map": p.has_map,
        "crypto": p.callouts["callout--crypto"] > 0,
        "c2026": p.callouts["callout--2026"] > 0,
        "test": p.callouts["callout--test"] > 0,
        "checklist": p.checklists > 0,
        "further": any("Что читать дальше" in h for h in p.headings),
    }

    defects = {
        "html_in_text": len(p.html_in_text),
        "dup_ids": len(dup_ids),
        "broken_refs": len(broken_refs),
        "overridden": len(p.overridden),
        "tables_unscrolled": len(p.tables_unscrolled),
        "hex_colors": len(p.hex_colors),
        "xref_broken": len(xref_broken),
        "xref_stale": len(xref_stale),
        "text_ch_ref": len(text_ch_ref),
        "figures_no_twin": len(missing_twin),
        "math_broken": len(math_broken),
    }

    reasons = [f"{DEFECT_LABELS[k]}: {n}" for k, n in defects.items() if n]
    missing_blocks = [lbl for k, lbl in STRUCTURE_KEYS
                      if k in STRUCTURE_REQUIRED and not structure[k]]
    if missing_blocks:
        reasons.append("нет блоков: " + ", ".join(missing_blocks))

    if reasons:
        verdict = "с дефектами"
    elif words < THIN_WORDS or len(p.figures) < THIN_FIGURES:
        verdict = "тонкая"
        reasons.append(f"объём {words} слов, фигур {len(p.figures)}")
    else:
        verdict = "в норме"

    return {
        "n": meta["n"], "id": meta.get("id", ""), "file": path.name, "title": meta["title"],
        "words": words, "chars": len(prose), "svg_words": p.svg_words,
        "figures": len(p.figures),
        "figures_with_values": len(with_values),
        "figures_with_twin": sum(1 for f in p.figures if f["has_table"]),
        "figures_missing_twin": [f["id"] or "?" for f in missing_twin],
        "tables": p.tables_total,
        "indicators": p.indicators,
        "callouts": dict(p.callouts),
        "callouts_total": sum(p.callouts.values()),
        "marks": marks,
        "structure": structure,
        "missing_blocks": missing_blocks,
        "defects": defects,
        "detail": {
            "html_in_text": p.html_in_text,
            "dup_ids": dup_ids,
            "broken_refs": broken_refs,
            "overridden": [f'{a}: <{b} class="{c}" {e}=…>' for a, b, c, e in p.overridden],
            "tables_unscrolled": p.tables_unscrolled,
            "hex_colors": [f'{a}: <{b} {c}="{e}">' for a, b, c, e in p.hex_colors],
            "xref_broken": xref_broken,
            "xref_stale": xref_stale,
            "text_ch_ref": text_ch_ref,
            "math_broken": math_broken,
        },
        "verdict": verdict,
        "reasons": reasons,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Печать
# ─────────────────────────────────────────────────────────────────────────────

def table(title: str, headers: list, rows: list, aligns: str = "") -> None:
    aligns = (aligns + "l" * len(headers))[:len(headers)]
    cells = [[str(c) for c in r] for r in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]
    rule = "─" * (sum(widths) + 3 * (len(widths) - 1))

    def line(vals, force_left=False):
        return "   ".join(
            v.ljust(widths[i]) if (force_left or aligns[i] == "l") else v.rjust(widths[i])
            for i, v in enumerate(vals)).rstrip()

    print()
    print(title)
    print(rule)
    print(line(headers, force_left=True))
    print(rule)
    for r in cells:
        print(line(r))


def examples(name: str, items: list, show_all: bool) -> None:
    if not items:
        return
    limit = len(items) if show_all else EXAMPLES
    print(f"\n  {name} — {len(items)} шт.:")
    for it in items[:limit]:
        print(f"    · {it}")
    if len(items) > limit:
        print(f"    … и ещё {len(items) - limit} (запустите с --all)")


def mark(v: bool) -> str:
    return "✓" if v else "—"


def thousands(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def load_registry() -> list:
    """Номер главы — позиция в реестре плюс один, и больше нигде."""
    return [{"n": c.n, "id": c.id, "part": c.part, "file": c.file,
             "title": c.title, "status": c.status}
            for c in linkify.load_registry()]


# ─────────────────────────────────────────────────────────────────────────────
# Самопроверка детекторов
# ─────────────────────────────────────────────────────────────────────────────

# Что эталоны обязаны дать. Числа выверены по tools/fixtures/*.html;
# правите эталон — правьте и таблицу.
SELFTEST_EXPECT = {
    "broken.html": {
        "html_in_text": 2, "dup_ids": 1, "broken_refs": 2, "overridden": 3,
        "tables_unscrolled": 1, "hex_colors": 2, "figures_no_twin": 1,
        "xref_broken": 1, "xref_stale": 1, "text_ch_ref": 1,
        "math_broken": 2,
        "missing_blocks": 5,
    },
    "clean.html": {
        "html_in_text": 0, "dup_ids": 0, "broken_refs": 0, "overridden": 0,
        "tables_unscrolled": 0, "hex_colors": 0, "figures_no_twin": 0,
        "xref_broken": 0, "xref_stale": 0, "text_ch_ref": 0,
        "math_broken": 0,
        "missing_blocks": 0,
    },
}


def selftest(book: Path, class_props: dict) -> int:
    fixtures = book / "tools" / "fixtures"
    by_id = {c.id: c for c in linkify.load_registry()}
    ok = True
    for name, expect in SELFTEST_EXPECT.items():
        path = fixtures / name
        if not path.exists():
            print(f"НЕТ ЭТАЛОНА: {path}")
            ok = False
            continue
        r = audit_chapter(path, {"n": 0, "title": name}, class_props, by_id)
        got = dict(r["defects"])
        got["missing_blocks"] = len(r["missing_blocks"])
        print(f"\n{name}")
        print("─" * 60)
        for key, want in expect.items():
            good = got.get(key) == want
            ok &= good
            print(f"  {'ok  ' if good else 'FAIL'}  {key:<20} ожидалось {want}, "
                  f"получено {got.get(key)}")
    print()
    print("САМОПРОВЕРКА: " + ("детекторы работают" if ok else "ЕСТЬ РАСХОЖДЕНИЯ"))
    return 0 if ok else 1


# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Аудит книги «Как понимать рынок»")
    ap.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    ap.add_argument("--all", action="store_true", help="не обрезать списки дефектов")
    ap.add_argument("--selftest", action="store_true",
                    help="проверить детекторы на эталонах tools/fixtures")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    book = Path(__file__).resolve().parent.parent
    for f in (book / "assets" / "chapters.js", book / "assets" / "book.css"):
        if not f.exists():
            print(f"НЕ НАЙДЕН: {f}", file=sys.stderr)
            return 2

    class_props = parse_css_class_props(book / "assets" / "book.css")

    if args.selftest:
        return selftest(book, class_props)

    chapters = load_registry()
    if not chapters:
        print("Реестр глав не разобрался — проверьте assets/chapters.js", file=sys.stderr)
        return 2
    by_id = {c.id: c for c in linkify.load_registry()}

    written = [c for c in chapters if c["status"] == "done"]
    planned = [c for c in chapters if c["status"] != "done"]

    results, orphan_registry = [], []
    for meta in written:
        path = book / meta["file"]
        if path.exists():
            results.append(audit_chapter(path, meta, class_props, by_id))
        else:
            orphan_registry.append(meta["file"])
    # Файл главы, которой нет в реестре, — сирота. Ненаписанная глава реестра
    # файла иметь не должна: это либо забытый `status`, либо забытый файл.
    known = {c["file"] for c in chapters}
    service = {"index.html", "errata.html"}
    orphan_files = sorted({p.name for p in book.glob("*.html")} - known - service)
    orphan_files += [c["file"] for c in planned if (book / c["file"]).exists()]

    dup_slugs = sorted({c["id"] for c in chapters
                        if [x["id"] for x in chapters].count(c["id"]) > 1})

    if args.json:
        print(json.dumps({"chapters": results,
                          "planned": [c["id"] for c in planned],
                          "duplicate_ids": dup_slugs,
                          "registry_without_file": orphan_registry,
                          "file_without_registry": orphan_files},
                         ensure_ascii=False, indent=2))
        return 0

    print("═" * 96)
    print("АУДИТ КНИГИ «КАК ПОНИМАТЬ РЫНОК»")
    print(f"каталог: {book}")
    print(f"глав в плане: {len(chapters)} · написано: {len(written)} · "
          f"разобрано файлов: {len(results)}")
    print("═" * 96)

    table(
        "1. ОБЪЁМ И СОСТАВ (проза без SVG)",
        ["Гл", "Название", "Слов", "Знаков", "Фиг", "Табл", "Карт", "Врез", "В графике"],
        [[r["n"], r["title"][:34], thousands(r["words"]), thousands(r["chars"]),
          r["figures"], r["tables"], r["indicators"], r["callouts_total"],
          r["svg_words"]] for r in results],
        aligns="rlrrrrrrr",
    )

    table(
        "2. ВРЕЗКИ ПО ТИПАМ   " + " · ".join(f"{ic} {nm}" for _, ic, nm in CALLOUT_KINDS),
        ["Гл"] + [ic for _, ic, _ in CALLOUT_KINDS] + ["Всего"],
        [[r["n"]] + [r["callouts"][c] for c, _, _ in CALLOUT_KINDS] + [r["callouts_total"]]
         for r in results],
        aligns="r" * 9,
    )

    table(
        "3. ФИГУРЫ И ТАБЛИЧНЫЕ ДВОЙНИКИ (двойник обязателен для фигур со значениями)",
        ["Гл", "Фигур", "Со значениями", "С двойником", "Без двойника",
         "Со значениями и без двойника"],
        [[r["n"], r["figures"], r["figures_with_values"], r["figures_with_twin"],
          r["figures"] - r["figures_with_twin"],
          ", ".join(r["figures_missing_twin"]) or "—"] for r in results],
        aligns="rrrrrl",
    )

    table(
        "4. ПОМЕТКИ ПРОИСХОЖДЕНИЯ (STYLE-GUIDE §6)",
        ["Гл"] + list(ORIGIN_MARKS) + ["Всего"],
        [[r["n"]] + [r["marks"][m] for m in ORIGIN_MARKS] + [sum(r["marks"].values())]
         for r in results],
        aligns="r" * 7,
    )

    table(
        "5. ОБЯЗАТЕЛЬНЫЕ БЛОКИ СТРУКТУРЫ (STYLE-GUIDE §3)",
        ["Гл"] + [lbl for _, lbl in STRUCTURE_KEYS],
        [[r["n"]] + [mark(r["structure"][k]) for k, _ in STRUCTURE_KEYS] for r in results],
        aligns="r" + "c" * len(STRUCTURE_KEYS),
    )

    table(
        "6. ТЕХНИЧЕСКИЕ ДЕФЕКТЫ (STYLE-GUIDE §5)",
        ["Гл"] + [lbl for _, lbl in DEFECT_KEYS],
        [[r["n"]] + [r["defects"][k] or "·" for k, _ in DEFECT_KEYS] for r in results],
        aligns="r" * (len(DEFECT_KEYS) + 1),
    )
    for k, lbl in DEFECT_KEYS:
        examples(lbl, [f'гл. {r["n"]} · {d}' for r in results for d in r["detail"][k]],
                 args.all)

    table(
        "7. ВЕРДИКТ",
        ["Гл", "Название", "Флаг", "Причины"],
        [[r["n"], r["title"][:34], r["verdict"], "; ".join(r["reasons"]) or "—"]
         for r in results],
        aligns="rlll",
    )

    print()
    print("═" * 96)
    print("СВОДКА ПО КНИГЕ")
    print("═" * 96)
    print(f"  глав: {len(results)} написано из {len(chapters)} по плану")
    print(f"  прозы: {thousands(sum(r['words'] for r in results))} слов · "
          f"{thousands(sum(r['chars'] for r in results))} знаков")
    print(f"  подписей внутри графики: "
          f"{thousands(sum(r['svg_words'] for r in results))} слов")
    print(f"  фигур: {sum(r['figures'] for r in results)} "
          f"(со значениями {sum(r['figures_with_values'] for r in results)}, "
          f"с табличным двойником {sum(r['figures_with_twin'] for r in results)})")
    print(f"  таблиц: {sum(r['tables'] for r in results)} · "
          f"карточек индикаторов: {sum(r['indicators'] for r in results)} · "
          f"врезок: {sum(r['callouts_total'] for r in results)}")
    print("  пометки происхождения: " + " · ".join(
        f"{m} {sum(r['marks'][m] for r in results)}" for m in ORIGIN_MARKS))
    print("  дефекты: " + " · ".join(
        f"{lbl} {sum(r['defects'][k] for r in results)}" for k, lbl in DEFECT_KEYS))

    if dup_slugs:
        print("\n  Слаг встречается дважды: " + ", ".join(dup_slugs))
    if orphan_registry:
        print("\n  Помечена done, а файла нет: " + ", ".join(orphan_registry))
    if orphan_files:
        print("\n  Файл есть, а главы в реестре нет (или её статус не done): "
              + ", ".join(orphan_files))

    attention = [r for r in results if r["verdict"] != "в норме"]
    print()
    print("─" * 96)
    if not attention:
        print("ТРЕБУЮТ ВНИМАНИЯ: нет — все главы в норме.")
    else:
        print(f"ТРЕБУЮТ ВНИМАНИЯ: {len(attention)} из {len(results)}")
        for r in attention:
            print(f"  · гл. {r['n']:>2}  {r['title'][:38]:<38} "
                  f"[{r['verdict']}] {'; '.join(r['reasons'])}")
    print("─" * 96)

    return 1 if (dup_slugs or orphan_registry or orphan_files
                 or any(r["verdict"] == "с дефектами" for r in results)) else 0


if __name__ == "__main__":
    sys.exit(main())
