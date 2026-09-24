"""numbind_sense - does each data binding point at the field its sentence talks about?

numbind proves that a printed number equals the value of the field its rule names. It
cannot prove that the rule names the right field: a place bound to another field with the
same value passes. This instrument reads the meaning side at acceptance. For every rule
that reads data (F, and E with data placeholders) it builds the context of the place and
checks what the field path fixes:

  route  routes.yahoo and common_span_comparison.yahoo - the Yahoo route (the text may
         name it Yahoo or ^GSPC); routes.shiller - Shiller over the full history, or over
         the common span when the expression slices its rows; common_span_comparison.
         shiller - Shiller over the common span; other common_span_comparison fields -
         both routes of the common span.
  month  a path through per_date[i] fixes two months: the forecast origin and the outcome
         month. A context that names a month must name one of them.

The context is read level by level, and the first level that names a route (a month) is
the one judged:

  sentence    the sentence around the number (for a table cell or an SVG text - itself);
  panel       SVG text only: the nearest label of the same drawing naming exactly one;
  row+column  table cell only: the cells left of it in its row, the header cells above;
  paragraph   prose only: the whole text unit;
  caption     the table caption and the figure caption;
  previous    prose only: the nearest of the three text units before it, in the same
              section, that names one - "on this longer series" refers back.

A named route or month that differs from the field is a MISMATCH. With --default, a
context that names no route implies the chapter's main route, and a field of another
route there is an IMPLIED mismatch. Both exit 1 and are listed by name; a context that
names nothing is counted, never passed silently.

--swap proves the instrument alive: every judged rule is rebound in memory to another
route (Yahoo <-> Shiller) and every dated rule to the neighbouring date, and each
rebinding must be flagged. A rebinding that passes is a blind spot, listed by name:
usually a sentence that names both routes. Blind spots are read by eye at acceptance.

--tables reads the other side of a table: a cell that is a sum, a difference or an
absolute difference of two cells of its row, of the same precision, and matches it on
the unrounded data but misses it on the printed numbers by one unit of the last digit.
The reader checks the row with what is printed; a derived column taken from unrounded
values is legitimate only when the table says so in words (a caption or a cell with
"неокруглённ"). Undeclared near misses exit 1 and are listed; declared ones are counted.
Two unrelated columns can meet by chance (a table of two halves side by side, dates of
one row): every line is read by eye, one line per row.

usage: python -X utf8 book/tools/numbind_sense.py MANIFEST [--html FILE] [--default Y|S|C]
                                                  [--swap] [--list] [--tables]
"""
import itertools
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numbind  # noqa: E402

ROOT = numbind.ROOT
show = numbind.show
norm = numbind.normalize


def num(v):
    try:
        return float(re.match(r"-?[\d.]+", v or "").group(0))
    except (AttributeError, ValueError):
        return None


# --------------------------------------------------------------------------- context
class Ctx(numbind.Units):
    """numbind's text units plus, for each unit, its table cell, SVG text and figure."""

    def __init__(self):
        super().__init__()
        self.cells = {}          # (table, row, col) -> text
        self.span = {}           # (table, row, col) -> (rowspan, colspan)
        self.head = {}           # (table, row, col) -> header cell (th, or inside thead)
        self.taken = {}          # table -> {(row, col)} occupied by earlier spans
        self.unit_cell = {}      # unit key -> (table, row, col)
        self.unit_fig = {}       # unit key -> figure number
        self.unit_svg = {}       # unit key -> (svg number, serial of its <text>)
        self.unit_sec = {}       # unit key -> id of the latest heading
        self.first_real = {}     # unit key -> rank of its first non-blank text
        self.fig_cap = {}        # figure number -> figcaption text
        self.tab_cap = {}        # table number -> caption text
        self.tab_fig = {}        # table number -> figure number
        self.svg_text = {}       # svg number -> [[serial, x, y, text, class], ...]
        self.text_at = {}        # serial of an svg <text> -> its entry in svg_text
        self.ntab = self.nfig = self.nsvg = 0
        self.tables = []         # open tables: [number, row, col, in_thead]
        self.figs, self.svgs, self.cellstack, self.caps = [], [], [], []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag in numbind.VOID:
            return
        a = dict(attrs)
        if tag == "svg":
            self.nsvg += 1
            self.svgs.append(self.nsvg)
            self.svg_text[self.nsvg] = []
        elif tag == "text" and self.svgs:
            entry = [self.serial, num(a.get("x")), num(a.get("y")), "", a.get("class") or ""]
            self.svg_text[self.svgs[-1]].append(entry)
            self.text_at[self.serial] = entry
        elif tag == "figure":
            self.nfig += 1
            self.figs.append(self.nfig)
        elif tag == "table":
            self.ntab += 1
            self.tables.append([self.ntab, -1, -1, False])
            self.tab_fig[self.ntab] = self.figs[-1] if self.figs else None
            self.taken[self.ntab] = set()
        elif tag == "thead" and self.tables:
            self.tables[-1][3] = True
        elif tag == "tbody" and self.tables:
            self.tables[-1][3] = False
        elif tag == "tr" and self.tables:
            self.tables[-1][1] += 1
            self.tables[-1][2] = -1
        elif tag in ("td", "th") and self.tables:
            t = self.tables[-1]
            taken = self.taken[t[0]]
            c = t[2] + 1
            while (t[1], c) in taken:
                c += 1
            rs, cs = int(a.get("rowspan") or 1), int(a.get("colspan") or 1)
            for i in range(rs):
                for j in range(cs):
                    taken.add((t[1] + i, c + j))
            t[2] = c + cs - 1
            cell = (t[0], t[1], c)
            self.cellstack.append(cell)
            self.cells.setdefault(cell, "")
            self.span[cell] = (rs, cs)
            self.head[cell] = tag == "th" or t[3]
        elif tag == "figcaption" and self.figs:
            self.caps.append(("fig", self.figs[-1]))
        elif tag == "caption" and self.tables:
            self.caps.append(("tab", self.tables[-1][0]))

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        pops = {"figure": self.figs, "table": self.tables, "td": self.cellstack,
                "th": self.cellstack, "figcaption": self.caps, "caption": self.caps,
                "svg": self.svgs}
        if tag in pops and pops[tag]:
            pops[tag].pop()

    def handle_data(self, data):
        super().handle_data(data)
        if self.skip or not self.stack:
            return
        block = next((e for e in reversed(self.stack) if e[0] in numbind.BLOCK), None)
        if block is None:
            return
        cont = (next((e[1] for e in reversed(self.stack) if e[1] and e[0] not in numbind.HEADINGS), None)
                or self.section or "(root)")
        key = (block[2], cont)
        self.unit_sec.setdefault(key, self.section)
        if data.strip() and key not in self.first_real:
            self.first_real[key] = len(self.first_real)
        if self.cellstack:
            self.unit_cell.setdefault(key, self.cellstack[-1])
            self.cells[self.cellstack[-1]] += data
        if self.figs:
            self.unit_fig.setdefault(key, self.figs[-1])
        if block[0] == "text" and block[2] in self.text_at:
            self.text_at[block[2]][3] += data
            self.unit_svg.setdefault(key, (self.svgs[-1], block[2]))
        if self.caps:
            kind, i = self.caps[-1]
            d = self.fig_cap if kind == "fig" else self.tab_cap
            d[i] = d.get(i, "") + data

    def row_col(self, cell):
        """Cells left of the cell in its row (spans included) | header cells above it."""
        t, r, c = cell
        row, col = [], []
        for (tt, rr, cc), text in sorted(self.cells.items()):
            if tt != t:
                continue
            rs, cs = self.span[(tt, rr, cc)]
            if rr <= r < rr + rs and cc < c:
                row.append(norm(text))
            if rr < r and cc <= c < cc + cs and self.head[(tt, rr, cc)]:
                col.append(norm(text))
        return " ".join(row) + " | " + " ".join(col)

    def panel(self, svg, serial, named_fn):
        """Label of the same drawing that heads the text and names exactly one route.

        Labels are the texts of class viz-label or viz-legend (book/STYLE-GUIDE.md): a
        title or an annotation that names one route is a remark, not a panel header.
        A label heads what stands on its own line or below it, so labels further down
        do not count; among the rest the nearest line wins, then the nearest column -
        rows of a chart put the label left of its value, panels put it on top. For a
        month the axis labels count too, and the nearest column wins first: the date on
        a category axis heads the bar in its column, above it or below.
        """
        me = self.text_at[serial]
        if me[1] is None or me[2] is None:
            return ""
        best = None
        dates = named_fn is months_named
        for e in self.svg_text.get(svg, []):
            classes = LABEL | (AXIS if dates else set())
            if (e[0] == serial or e[1] is None or e[2] is None
                    or (not dates and e[2] > me[2] + 2)
                    or not classes & set(e[4].split()) or len(named_fn(e[3])) != 1):
                continue
            if dates:           # the column first: a bar may hang below its axis date
                d = (abs(e[1] - me[1]), abs(e[2] - me[2]))
            else:
                d = (max(0.0, me[2] - e[2]), abs(e[1] - me[1]))
            if best is None or d < best[0]:
                best = (d, e[3])
        return norm(best[1]) if best else ""


LABEL = {"viz-label", "viz-legend"}
AXIS = {"viz-axis"}              # a category axis carries the dates of its columns
BACK = 3                         # prose units looked back for "previous"
UPPER = "A-Z" + chr(0x410) + "-" + chr(0x42F) + chr(0x401) + chr(0xAB)
SENT = re.compile(r"(?<=[.!?" + chr(0x2026) + r"])\s+(?=[" + UPPER + "])")


def contexts(html_text):
    """place key -> list of (level name, text or callable(named_fn) -> text)."""
    body = html_text[html_text.find("<body"):] if "<body" in html_text else html_text
    p = Ctx()
    p.feed(body)
    p.close()
    # reading order: by the first non-blank text, not by the first whitespace - a display
    # formula standing straight in <article> shares a unit that opens right after <h2>
    prior, prose = {}, []
    for ukey in sorted(p.order, key=lambda k: p.first_real.get(k, len(p.order) + 1)):
        sec = p.unit_sec.get(ukey)
        prior[ukey] = [t for s_, t in prose[-BACK:] if s_ == sec]
        if ukey not in p.unit_cell and ukey not in p.unit_svg and p.units[ukey][1].strip():
            prose.append((sec, norm(p.units[ukey][1])))
    per, out = {}, {}
    for ukey in p.order:
        cont, raw = p.units[ukey]
        text = norm(raw)
        cell, fig, svg = p.unit_cell.get(ukey), p.unit_fig.get(ukey), p.unit_svg.get(ukey)
        before = prior[ukey]
        toks = numbind.tokens_of(text)
        if not toks:
            continue
        per[cont] = per.get(cont, 0) + 1
        for j, (s, e, printed, v, dec) in enumerate(toks, 1):
            a = 0
            for m in SENT.finditer(text):
                if m.start() >= s:
                    break
                a = m.end()
            m = SENT.search(text, e)
            levels = [("sentence", text[a:m.start() if m else len(text)])]
            if svg:
                levels.append(("panel", lambda fn, svg=svg: p.panel(svg[0], svg[1], fn)))
            if cell:
                levels.append(("row+column", p.row_col(cell)))
                t = cell[0]
                levels.append(("caption", norm(p.tab_cap.get(t, "") + " " + p.fig_cap.get(p.tab_fig.get(t), ""))))
            else:
                levels.append(("paragraph", text))
                if fig:
                    levels.append(("caption", norm(p.fig_cap.get(fig, ""))))
            if not cell and not svg and before:
                levels.append(("previous", lambda fn, before=before: next(
                    (t for t in reversed(before) if fn(t)), "")))
            out["%s#%d.%d" % (cont, per[cont], j)] = levels
    return out


def judge(levels, named_fn):
    """First level that names something: (level, named set, its text), or (None, set(), "")."""
    for name, text in levels:
        if callable(text):
            text = text(named_fn)
        n = named_fn(text)
        if n:
            return name, n, text
    return None, set(), ""


# --------------------------------------------------------------------------- judges
W_SHILLER = "шиллер"
W_COMMON = r"общ\w* (?:\w+ )?отрез"
W_FULL = r"полн\w* истори|1881"


def routes_named(t):
    t = t.lower()
    r = set()
    if "yahoo" in t or "gspc" in t:
        r.add("Y")
    if W_SHILLER in t:
        common = re.search(W_COMMON, t)
        full = re.search(W_FULL, t)
        if common:
            r.add("C")
        if full:
            r.add("S")
        if not common and not full:
            r.add("S|C")
    return r


def route_of_path(path):
    r = set()
    if re.search(r"routes\.yahoo|common_span_comparison\.yahoo", path):
        r.add("Y")
    if "routes.shiller" in path:
        r.add("S")
    if "common_span_comparison.shiller" in path:
        r.add("C")
    if re.search(r"common_span_comparison\.(?!yahoo|shiller)", path):
        r |= {"Y", "C"}
    return r


def route_ok(field, named):
    return any((x == "S|C" and field & {"S", "C"}) or x in field for x in named)


# every case form: "декабрь", "декабря", "декабре", "к декабрю", "декабрём"
MONTHS = ["январ(?:ь|я|е|ю|ём)", "феврал(?:ь|я|е|ю|ём)", "март(?:а|е|у|ом)?", "апрел(?:ь|я|е|ю|ем)",
          "ма(?:й|я|е|ю|ем)", "июн(?:ь|я|е|ю|ем)", "июл(?:ь|я|е|ю|ем)", "август(?:а|е|у|ом)?",
          "сентябр(?:ь|я|е|ю|ём)", "октябр(?:ь|я|е|ю|ём)", "ноябр(?:ь|я|е|ю|ём)",
          "декабр(?:ь|я|е|ю|ём)"]
RU_MONTH = re.compile(r"(?<![\w])(%s)\s+(1[89]\d\d|20\d\d)" % "|".join("(?:%s)" % m for m in MONTHS),
                      re.I)
ISO_MONTH = re.compile(r"(?<!\d)(1[89]\d\d|20\d\d)-(0[1-9]|1[0-2])(?!\d)")


def months_named(t):
    out = {"%s-%s" % m.groups() for m in ISO_MONTH.finditer(t)}
    for m in RU_MONTH.finditer(t):
        word = m.group(1).lower()
        num_ = next(i for i, pat in enumerate(MONTHS, 1) if re.fullmatch(pat, word))
        out.add("%s-%02d" % (m.group(2), num_))
    return out


PH = re.compile(r"\{([A-Za-z0-9_]+):([^{}]+)\}")
# Shiller's rows sliced in the expression - "[683:]", "[-1052:]" - are the common span
SLICE = re.compile(r"routes\.shiller\.per_date[^{}]*\}\s*\[")
PER_DATE = re.compile(r"^(.*\.per_date)\[(\d+)\]")


def paths_of(spec):
    if isinstance(spec, numbind.F):
        return [(spec.alias, spec.path)]
    if isinstance(spec, numbind.E):
        return [(a, p.strip()) for a, p in PH.findall(spec.expr)]
    return []


def months_of(data, alias, path, shift=0):
    """Origin and outcome month of the per_date row the path goes through."""
    m = PER_DATE.match(path)
    rows = numbind.walk(data[alias], m.group(1))[0][1]
    i = int(m.group(2)) + shift
    if not 0 <= i < len(rows):
        i = int(m.group(2)) - shift
    r = rows[i]
    return {r.get("origin"), r.get("outcome_month")} - {None}


# --------------------------------------------------------------------------- run
def tables(html_text):
    """Near misses of derived table columns: (row label, key, printed, relation, declared)."""
    body = html_text[html_text.find("<body"):] if "<body" in html_text else html_text
    p = Ctx()
    p.feed(body)
    p.close()
    per, keyof = {}, {}
    for uk in p.order:
        cont, raw = p.units[uk]
        if not numbind.tokens_of(norm(raw)):
            continue
        per[cont] = per.get(cont, 0) + 1
        keyof[uk] = "%s#%d" % (cont, per[cont])
    rows = {}
    for uk, (t, r, c) in p.unit_cell.items():
        if uk not in keyof:
            continue
        toks = numbind.tokens_of(norm(p.units[uk][1]))
        if len(toks) == 1:
            rows.setdefault((t, r), {})[c] = (keyof[uk] + ".1",) + tuple(toks[0][2:])
    out = []
    for (t, r), row in sorted(rows.items()):
        caption = (p.tab_cap.get(t, "") + " " + p.fig_cap.get(p.tab_fig.get(t), "")
                   + " " + " ".join(p.cells.get((t, rr, cc), "") for (tt, rr, cc) in p.cells if tt == t))
        declared = "неокруглённ" in caption.lower() or "неокругленн" in caption.lower()
        for c in sorted(row):
            key, printed, v, dec = row[c]
            if dec < 1:
                continue
            unit = 10 ** (-dec)
            others = [row[x] for x in sorted(row) if x != c and row[x][3] == dec]
            pairs = list(itertools.permutations(others, 2))
            rel = [(n, fa, fb, w) for (_, fa, a, _), (_, fb, b, _) in pairs
                   for n, w in (("a-b", a - b), ("|a-b|", abs(a - b)), ("a+b", a + b))]
            if any(abs(v - w) <= 0.5 * unit + 1e-9 for _, _, _, w in rel):
                continue
            near = [x for x in rel if abs(v - x[3]) <= 1.5 * unit + 1e-9]
            if near:            # one line per row: the three cells of a + b = c are one miss
                n, fa, fb, w = near[0]
                label = norm(p.cells.get((t, r, 0), ""))[:24]
                out.append((label, key, printed, "%s(%s, %s) = %.4f" % (n, fa, fb, w), declared))
                break
    return out


def run(manifest, html_path, default, want_swap, want_list, want_tables=False):
    m = numbind.load_manifest(manifest)
    html_path = Path(html_path) if html_path else ROOT / m["CHAPTER"]
    data = {k: json.loads((ROOT / v).read_text(encoding="utf-8")) for k, v in m["DATA"].items()}
    html_text = html_path.read_text(encoding="utf-8")
    ctx = contexts(html_text)
    keys = [p["key"] for p in numbind.places(html_text)]
    if sorted(ctx) != sorted(keys):
        print("BROKEN: context keys differ from numbind places (%d vs %d)" % (len(ctx), len(keys)))
        return 2
    n_data = n_route = n_month = 0
    r_levels, m_levels = {}, {}
    r_bad, r_implied, r_none, m_bad, m_none = [], [], [], [], []
    sw_r, sw_m = [0, []], [0, []]
    listing = []
    for key, _c, spec in m["RULES"]:
        ps = paths_of(spec)
        if not ps or key not in ctx:
            continue
        n_data += 1
        levels = ctx[key]
        src = spec.path if isinstance(spec, numbind.F) else spec.expr
        field = set()
        for _a, p in ps:
            field |= route_of_path(p)
        if isinstance(spec, numbind.E) and SLICE.search(spec.expr):
            field.add("C")
        if field:
            n_route += 1
            lvl, named, text = judge(levels, routes_named)
            if lvl is None and default:
                lvl, named, text = "implied", {default}, levels[0][1]
            if lvl is None:
                r_none.append((key, src, levels[0][1]))
            else:
                r_levels[lvl] = r_levels.get(lvl, 0) + 1
                ok = route_ok(field, named)
                listing.append(("route", key, "".join(sorted(field)), "/".join(sorted(named)), lvl, ok, src, text))
                if not ok:
                    (r_implied if lvl == "implied" else r_bad).append((key, field, named, lvl, src, text))
                elif want_swap and len(field) == 1 and lvl != "implied":
                    alt = {"Y": {"S"}, "S": {"Y"}, "C": {"Y"}}[next(iter(field))]
                    if route_ok(alt, named):
                        sw_r[1].append((key, field, named, lvl, src, text))
                    else:
                        sw_r[0] += 1
        dated = [(a, p) for a, p in ps if PER_DATE.match(p)]
        if dated:
            n_month += 1
            fm = set()
            for a, p in dated:
                fm |= months_of(data, a, p)
            lvl, named, text = judge(levels, months_named)
            if lvl is None:
                m_none.append((key, src, fm, levels[0][1]))
            else:
                m_levels[lvl] = m_levels.get(lvl, 0) + 1
                ok = bool(named & fm)
                listing.append(("month", key, "/".join(sorted(fm)), "/".join(sorted(named)), lvl, ok, src, text))
                if not ok:
                    m_bad.append((key, fm, named, lvl, src, text))
                elif want_swap:
                    alt = set()
                    for a, p in dated:
                        alt |= months_of(data, a, p, shift=1)
                    if named & alt:
                        sw_m[1].append((key, alt, named, lvl, src, text))
                    else:
                        sw_m[0] += 1

    def cut(t):
        return show(t[:170])

    def lv(d):
        return ", ".join("%s %d" % kv for kv in sorted(d.items())) or "-"

    print("numbind_sense: %s" % show(str(html_path)))
    print("rules reading data: %d" % n_data)
    print("route: rules with a route %d | judged %d (%s) | MISMATCH %d | IMPLIED %d | nothing named %d"
          % (n_route, sum(r_levels.values()), lv(r_levels), len(r_bad), len(r_implied), len(r_none)))
    print("month: rules through per_date %d | judged %d (%s) | MISMATCH %d | nothing named %d"
          % (n_month, sum(m_levels.values()), lv(m_levels), len(m_bad), len(m_none)))
    for tag, rows in (("ROUTE-MISMATCH", r_bad), ("ROUTE-IMPLIED ", r_implied)):
        for key, field, named, lvl, src, text in rows:
            print("  %s %-26s field %-3s named %-6s at %-10s %s | %s"
                  % (tag, key, "".join(sorted(field)), "/".join(sorted(named)), lvl, src[:80], cut(text)))
    for key, fm, named, lvl, src, text in m_bad:
        print("  MONTH-MISMATCH %-26s field %-15s named %-15s at %-10s %s | %s"
              % (key, "/".join(sorted(fm)), "/".join(sorted(named))[:15], lvl, src[:70], cut(text)))
    if want_swap:
        print("swap control: route rebinding flagged %d of %d; month rebinding flagged %d of %d"
              % (sw_r[0], sw_r[0] + len(sw_r[1]), sw_m[0], sw_m[0] + len(sw_m[1])))
        for key, field, named, lvl, src, text in sw_r[1]:
            print("  BLIND route %-26s field %s named %-6s at %-10s | %s"
                  % (key, "".join(sorted(field)), "/".join(sorted(named)), lvl, cut(text)))
        for key, alt, named, lvl, src, text in sw_m[1]:
            print("  BLIND month %-26s alt %s named %s at %-10s | %s"
                  % (key, "/".join(sorted(alt)), "/".join(sorted(named))[:30], lvl, cut(text)))
    if want_list:
        print("\njudged rules:")
        for what, key, fv, nv, lvl, ok, src, text in listing:
            print("  %-5s %-4s %-26s field %-15s named %-15s %-10s %s | %s"
                  % (what, "ok" if ok else "BAD", key, fv[:15], nv[:15], lvl, src[:70], cut(text)))
        print("\nroute not named (%d):" % len(r_none))
        for key, src, text in r_none:
            print("  %-26s %s | %s" % (key, src[:80], cut(text)))
        print("\nmonth not named (%d):" % len(m_none))
        for key, src, fm, text in m_none:
            print("  %-26s %-15s %s | %s" % (key, "/".join(sorted(fm)), src[:70], cut(text)))
    t_bad = []
    if want_tables:
        near = tables(html_text)
        t_bad = [x for x in near if not x[4]]
        print("tables: rows whose derived cell is off the printed row by one unit %d | declared unrounded %d"
              % (len(t_bad), len(near) - len(t_bad)))
        for label, key, printed, rel, declared in near:
            print("  %s %-30s %-10s %-24s printed row gives %s"
                  % ("declared  " if declared else "NEAR-MISS ", key, printed, show(label), show(rel)))
    return 1 if (r_bad or r_implied or m_bad or t_bad) else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("manifest")
    ap.add_argument("--html")
    ap.add_argument("--default", choices=["Y", "S", "C"])
    ap.add_argument("--swap", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--tables", action="store_true")
    a = ap.parse_args()
    return run(a.manifest, a.html, a.default, a.swap, a.list, a.tables)


if __name__ == "__main__":
    sys.exit(main())
