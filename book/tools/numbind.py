"""numbind - place-bound check of every number in a chapter.

Every number in every text node of the chapter - prose, tables, captions, SVG text,
formulas; never tags, attributes, <script> or <style> - gets a place:

    <container>#<text unit inside it>.<number inside the unit>

The container is the nearest ancestor with an id (a figure, an SVG title), otherwise the
id of the latest heading with an id - chapters mark sections on <h2 id="s5">, and the
paragraphs of a section are the heading's siblings, not its children. A text unit is the
innermost block element (p, li, td, th, figcaption, h1-h6, SVG text, title, desc, div,
...) within one container: a display formula standing straight in <article> belongs to
the section it stands in. A chapter manifest binds every place to its expected value:

    F("Z28", "routes.yahoo.statistics.dependence.n_eff")      a field of a result file
    E("1.96 * {Z28:routes.yahoo.statistics.sd_delta_pp}")      a formula over fields
    A("{#s5#14.1} + {#s5#14.2}")                               shown arithmetic over
                                                               numbers printed elsewhere
    L(12, "structure") / L(1992, "source") / L(0.917, "toy")   a literal, reviewed by name

The printed number must equal the expected value within half a unit of its last printed
digit. Defects: a number without a rule; a rule whose place is gone; a place whose left
context changed (the rule points at another number now); a value outside tolerance.
Expected values of F and E are computed from the data files at run time, never taken
from the chapter. --liveness proves that: every field pattern the manifest reads is
perturbed in memory, and every rule that reads it must stop matching the chapter.

The manifest is a Python file executed with F, E, A, L predefined. It sets
    CHAPTER = "book/<slug>.html"             relative to the repository root
    DATA    = {"Z28": "research/Z28/result.json"}
    RULES   = [(place, left_context, spec), ...]

usage (from anywhere; paths in the manifest are relative to the repository root):
    python book/tools/numbind.py MANIFEST [--html FILE] [--data ALIAS=FILE]
                                          [--review] [--fields] [--liveness]
    python book/tools/numbind.py --template CHAPTER.html   manifest skeleton, all places
    python book/tools/numbind.py --selftest

Exit: 0 clean, 1 defects, 2 manifest or usage error. Contexts are printed raw when
stdout is UTF-8 (python -X utf8), otherwise escaped (cp1251 console).
"""
import argparse
import copy
import html.parser
import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = "utf" in (getattr(sys.stdout, "encoding", "") or "").lower()
CTX = 28


def show(s):
    return s if RAW else s.encode("ascii", "backslashreplace").decode()


# --------------------------------------------------------------------------- places
BLOCK = {"p", "li", "td", "th", "caption", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6",
         "dt", "dd", "blockquote", "pre", "div", "section", "article", "aside", "header",
         "footer", "nav", "figure", "table", "tr", "ul", "ol", "dl", "summary", "details",
         "body", "main", "text", "title", "desc", "svg", "g", "label", "legend", "button"}
VOID = {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "col", "area", "base",
        "embed", "param", "track"}
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class Units(html.parser.HTMLParser):
    """Collect text units: (unit element serial, container) -> text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []           # [tag, id, serial]
        self.serial = 0
        self.section = None       # id of the latest heading with an id
        self.units = {}           # (serial, container) -> [container, text]
        self.order = []           # unit keys in order of first text
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        if tag in ("script", "style"):
            self.skip += 1
        self.serial += 1
        eid = dict(attrs).get("id")
        if tag in HEADINGS and eid:
            self.section = eid
        self.stack.append([tag, eid, self.serial])

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                if tag in ("script", "style"):
                    self.skip -= 1
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self.skip or not self.stack:
            return
        block = next((e for e in reversed(self.stack) if e[0] in BLOCK), None)
        if block is None:
            return
        cont = (next((e[1] for e in reversed(self.stack) if e[1] and e[0] not in HEADINGS), None)
                or self.section or "(root)")
        key = (block[2], cont)
        u = self.units.get(key)
        if u is None:
            u = self.units[key] = [cont, ""]
            self.order.append(key)
        u[1] += data


def normalize(t):
    t = t.replace("{,}", ",")
    t = re.sub(r"[\u00a0\u202f\u2009\s]+", " ", t)
    return t.strip()


NUM = re.compile(r"\d{1,3}(?: \d{3})+(?![\d,])|\d+(?:,\d+)?")
LETTER = re.compile(r"[A-Za-z\u0370-\u03ff\u0400-\u04ff_]")


def tokens_of(text):
    """Numbers of a normalized unit text: (start, end, printed, value, decimals)."""
    out = []
    for m in NUM.finditer(text):
        s, e = m.start(), m.end()
        before = text[s - 1] if s else ""
        after = text[e] if e < len(text) else ""
        if (before and (LETTER.match(before) or before in ".,")) or (after and LETTER.match(after)):
            continue                              # index or label: M10, Z28, rho_1, 2m
        sign = ""
        if before in "+-\u2212" and s >= 1:
            prev = text[s - 2] if s >= 2 else ""
            if not (prev.isalnum() or prev in ")]}"):
                sign = before
        p = m.group(0)
        digits = p.replace(" ", "")
        dec = len(digits.split(",")[1]) if "," in digits else 0
        v = float(digits.replace(",", "."))
        out.append((s - len(sign), e, sign + p, -v if sign in "-\u2212" and sign else v, dec))
    return out


def places(html_text):
    """Ordered list of places: dict(key, container, ctx, printed, value, dec)."""
    body = html_text[html_text.find("<body"):] if "<body" in html_text else html_text
    p = Units()
    p.feed(body)
    p.close()
    per_cont = {}
    out = []
    for serial in p.order:
        cont, raw = p.units[serial]
        text = normalize(raw)
        toks = tokens_of(text)
        if not toks:
            continue
        per_cont[cont] = per_cont.get(cont, 0) + 1
        for j, (s, e, printed, v, dec) in enumerate(toks, 1):
            out.append({"key": "%s#%d.%d" % (cont, per_cont[cont], j), "container": cont,
                        "ctx": text[max(0, s - CTX):s], "printed": printed, "value": v, "dec": dec})
    return out


# --------------------------------------------------------------------------- specs
class Spec:
    kind = "?"
    cls = "?"


class F(Spec):
    kind, cls = "F", "data"

    def __init__(self, alias, path):
        self.alias, self.path = alias, path


class E(Spec):
    kind = "E"

    def __init__(self, expr):
        self.expr = expr
        self.cls = "data" if re.search(r"\{[A-Za-z0-9_]+:", expr) else "computed"


class A(Spec):
    kind, cls = "A", "arithmetic"

    def __init__(self, expr):
        self.expr = expr


class L(Spec):
    kind = "L"

    def __init__(self, value, cls):
        if cls not in ("structure", "source", "toy"):
            raise ValueError("L class must be structure, source or toy: %r" % cls)
        self.value, self.cls = value, cls


STEP = re.compile(r"([^.\[\]]+)|\[(\*|\d+)\]")


def walk(obj, path):
    """Values at path; '[*]' fans out. Returns list of (concrete path, value)."""
    cur = [("", obj)]
    for m in STEP.finditer(path):
        name, idx = m.group(1), m.group(2)
        nxt = []
        for cp, o in cur:
            if name is not None:
                if not isinstance(o, dict) or name not in o:
                    raise KeyError("no field %r at %r" % (name, cp or "(top)"))
                nxt.append(((cp + "." if cp else "") + name, o[name]))
            elif idx == "*":
                if not isinstance(o, list):
                    raise KeyError("not a list at %r" % cp)
                nxt.extend(("%s[%d]" % (cp, i), x) for i, x in enumerate(o))
            else:
                i = int(idx)
                if not isinstance(o, list) or i >= len(o):
                    raise KeyError("no index %d at %r" % (i, cp))
                nxt.append(("%s[%d]" % (cp, i), o[i]))
        cur = nxt
    return cur


def pattern_of(path):
    return re.sub(r"\[\d+\]", "[*]", path)


PH_DATA = re.compile(r"\{([A-Za-z0-9_]+):([^{}]+)\}")
PH_TOK = re.compile(r"\{#([^{}]+)\}")
Phi = statistics.NormalDist().cdf
NS = {"sqrt": math.sqrt, "ceil": math.ceil, "floor": math.floor, "log": math.log,
      "exp": math.exp, "Phi": Phi, "mean": statistics.fmean, "sd": statistics.stdev,
      "corr": statistics.correlation, "abs": abs, "round": round, "sum": sum, "max": max,
      "min": min, "len": len, "int": int, "float": float, "sorted": sorted, "zip": zip}


def evaluate(spec, data, printed):
    """Expected value and the (alias, path-pattern) set it reads."""
    reads = set()
    if isinstance(spec, L):
        return float(spec.value), reads
    if isinstance(spec, F):
        got = walk(data[spec.alias], spec.path)
        if len(got) != 1:
            raise ValueError("F path must name one value: %s" % spec.path)
        reads.add((spec.alias, pattern_of(spec.path)))
        return float(got[0][1]), reads
    if isinstance(spec, E):
        vals = []

        def sub(m):
            alias, path = m.group(1), m.group(2).strip()
            got = walk(data[alias], path)
            reads.add((alias, pattern_of(path)))
            vals.append([v for _, v in got] if "*" in path else got[0][1])
            return "_v[%d]" % (len(vals) - 1)
        code = PH_DATA.sub(sub, spec.expr)
        # values go into globals: a generator or comprehension inside eval does not see
        # eval's locals (found by the executor of chapter 11, 2026-09-24)
        g = dict(NS)
        g["_v"] = vals
        return float(eval(code, g)), reads
    if isinstance(spec, A):
        vals = []

        def subt(m):
            k = m.group(1).strip()
            if k not in printed:
                raise KeyError("A refers to a place that is not in the chapter: %s" % k)
            vals.append(printed[k])
            return "_t[%d]" % (len(vals) - 1)
        code = PH_TOK.sub(subt, spec.expr)
        if PH_DATA.search(code):
            raise ValueError("A must not read data; use E: %s" % spec.expr)
        g = dict(NS)
        g["_t"] = vals
        return float(eval(code, g)), reads
    raise ValueError("unknown spec %r" % (spec,))


def tol(dec):
    return 0.5 * 10 ** (-dec) + 1e-9


# --------------------------------------------------------------------------- runs
def load_manifest(path):
    ns = {"F": F, "E": E, "A": A, "L": L}
    src = Path(path).read_text(encoding="utf-8")
    exec(compile(src, str(path), "exec"), ns)
    for k in ("CHAPTER", "DATA", "RULES"):
        if k not in ns:
            raise ValueError("manifest has no %s" % k)
    return ns


def check(html_text, data, rules):
    """Return (places, defects, results) for one chapter text and one data set."""
    pl = places(html_text)
    by_key = {p["key"]: p for p in pl}
    printed = {p["key"]: p["value"] for p in pl}
    defects = []
    seen = set()
    results = []
    for key, ctx, spec in rules:
        if key in seen:
            defects.append(("double rule", key, ""))
            continue
        seen.add(key)
        p = by_key.get(key)
        if p is None:
            defects.append(("place gone", key, ""))
            continue
        if normalize(ctx) != normalize(p["ctx"]):
            defects.append(("place moved", key, "manifest ...%s | chapter ...%s" % (ctx, p["ctx"])))
            continue
        if spec is None:
            defects.append(("unbound", key, "%s ...%s" % (p["printed"], p["ctx"])))
            continue
        try:
            exp, reads = evaluate(spec, data, printed)
        except Exception as ex:                          # noqa: BLE001 - report, do not hide
            defects.append(("rule error", key, "%s: %s" % (type(ex).__name__, ex)))
            continue
        ok = abs(p["value"] - exp) <= tol(p["dec"])
        results.append((key, spec, exp, reads, ok, p))
        if not ok:
            defects.append(("value", key, "printed %s expected %.6g ...%s" % (p["printed"], exp, p["ctx"])))
    for p in pl:
        if p["key"] not in seen:
            defects.append(("no rule", p["key"], "%s ...%s" % (p["printed"], p["ctx"])))
    return pl, defects, results


def perturb(obj, path_pattern):
    """Copy of obj with every numeric leaf matching the pattern shifted by 0.6 .. 2.0."""
    o = copy.deepcopy(obj)
    got = walk(o, path_pattern)
    n = 0
    for i, (cp, v) in enumerate(got):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        delta = 1.3 + 0.7 * math.sin(3.1 * i + 1.0)
        steps = STEP.findall(cp)              # walk the concrete path again to set the leaf
        ref = o
        for name, idx in steps[:-1]:
            ref = ref[name] if name else ref[int(idx)]
        name, idx = steps[-1]
        if name:
            ref[name] = v + delta
        else:
            ref[int(idx)] = v + delta
        n += 1
    return o, n


def liveness(html_text, data, rules):
    pl, defects, results = check(html_text, data, rules)
    patterns = {}
    for key, spec, exp, reads, ok, p in results:
        for r in reads:
            patterns.setdefault(r, []).append(key)
    dead = []
    rows = []
    rule_by_key = {k: s for k, _, s in rules}
    for (alias, pat), keys in sorted(patterns.items()):
        d2 = dict(data)
        d2[alias], n = perturb(data[alias], pat)
        if n == 0:
            rows.append((alias, pat, len(keys), 0, "not numeric - reviewed by name"))
            continue
        wanted = set(keys)
        _, _, res2 = check(html_text, d2, [(k, c, s) for k, c, s in rules if k in wanted])
        failed = {r[0] for r in res2 if not r[4]}
        still = [k for k in keys if k not in failed]
        rows.append((alias, pat, len(keys), len(keys) - len(still), ""))
        for k in still:
            dead.append((alias, pat, k))
    return rows, dead


def report(manifest_path, html_path, data, rules, want_review, want_fields, want_live):
    html_text = Path(html_path).read_text(encoding="utf-8")
    pl, defects, results = check(html_text, data, rules)
    counts = {}
    for key, spec, exp, reads, ok, p in results:
        counts[spec.cls] = counts.get(spec.cls, 0) + 1
    print("numbind: %s" % show(str(html_path)))
    print("numbers in the chapter: %d | rules: %d" % (len(pl), len(rules)))
    print("bound by class: " + ", ".join("%s %d" % (k, counts[k]) for k in sorted(counts)))
    kinds = {}
    for d in defects:
        kinds[d[0]] = kinds.get(d[0], 0) + 1
    print("defects: %d (%s)" % (len(defects), ", ".join("%s %d" % kv for kv in sorted(kinds.items())) or "none"))
    for kind, key, msg in defects:
        print("  %-12s %-40s %s" % (kind, key, show(msg)))
    if want_review:
        print("\nliterals, reviewed by name:")
        leaves = {}
        for alias, obj in data.items():
            for cp, v in walk_all(obj):
                leaves.setdefault(round(v, 6), []).append("%s:%s" % (alias, cp))
        for key, spec, exp, reads, ok, p in results:
            if isinstance(spec, L):
                flag = ""
                if p["dec"] > 0 or abs(p["value"]) >= 100:
                    hits = [c for vv, cs in leaves.items() if abs(vv - p["value"]) <= tol(p["dec"]) for c in cs]
                    if hits:
                        flag = "  <- equals data %s%s" % (hits[0], " (+%d)" % (len(hits) - 1) if len(hits) > 1 else "")
                print("  %-9s %-40s %-10s ...%s%s" % (spec.cls, key, p["printed"], show(p["ctx"]), flag))
    if want_fields or want_live:
        rows, dead = liveness(html_text, data, rules)
        print("\nfield patterns read by the manifest: %d" % len(rows))
        for alias, pat, nkeys, nfail, note in rows:
            print("  %-4s %-70s places %3d  failed after perturbation %3d %s" % (alias, pat, nkeys, nfail, note))
        if want_live:
            print("liveness: %d places did not react to their own field" % len(dead))
            for alias, pat, k in dead:
                print("  DEAD %s %s  %s" % (alias, pat, k))
            if dead:
                defects.append(("dead", "", ""))
    return 1 if defects else 0


def walk_all(o, cp=""):
    """Numeric leaves outside long lists (per-date rows would match anything by chance)."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk_all(v, (cp + "." if cp else "") + k)
    elif isinstance(o, list):
        if len(o) > 30:
            return
        for i, v in enumerate(o):
            yield from walk_all(v, "%s[%d]" % (cp, i))
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        yield cp, float(o)


def template(html_path):
    """Manifest skeleton, UTF-8 on stdout whatever the console: redirect it to a file."""
    pl = places(Path(html_path).read_text(encoding="utf-8"))
    lines = ['CHAPTER = "book/%s"' % Path(html_path).name,
             'DATA = {"Z28": "research/Z28/result.json"}',
             "RULES = ["]
    lines += ["    (%r, %r, None),  # %s" % (p["key"], p["ctx"], p["printed"]) for p in pl]
    lines.append("]")
    sys.stdout.flush()
    sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
    return 0


# --------------------------------------------------------------------------- selftest
def selftest():
    ch = ('<body><section id="s1"><p>Mean 0{,}17 pp at n = 1052, tau = 8{,}89.</p>'
          '<p>Pair 0{,}1072 + 0{,}0636 = 0{,}1708; rho_1 and M10 are labels.</p></section>'
          '<figure id="f"><svg><text>[\u22120,18; +0,51]</text></svg></figure>'
          '<script>var x = 99;</script></body>')
    data = {"d": {"m": 0.168805, "n": 1052, "tau": 8.887350, "ci": [-0.177336, 0.514947], "k": 7}}
    ctx = {p["key"]: p["ctx"] for p in places(ch)}       # as --template writes them
    specs = [
        ("s1#1.1", F("d", "m")),
        ("s1#1.2", F("d", "n")),
        ("s1#1.3", E("{d:tau}")),
        ("s1#2.1", L(0.1072, "toy")),
        ("s1#2.2", L(0.0636, "toy")),
        ("s1#2.3", A("{#s1#2.1} + {#s1#2.2}")),
        ("f#1.1", F("d", "ci[0]")),
        ("f#1.2", F("d", "ci[1]")),
    ]
    rules = [(k, ctx.get(k, ""), s) for k, s in specs]
    results = []

    def case(name, text, rs, want):
        _, defects, _ = check(text, data, rs)
        got = {}
        for d in defects:
            got[d[0]] = got.get(d[0], 0) + 1
        ok = got == want
        results.append(ok)
        print("  %-4s %-34s expected %s got %s" % ("ok" if ok else "FAIL", name, want, got))

    pl = places(ch)
    ok = [p["key"] for p in pl] == ["s1#1.1", "s1#1.2", "s1#1.3", "s1#2.1", "s1#2.2", "s1#2.3", "f#1.1", "f#1.2"]
    results.append(ok)
    print("  %-4s %-34s %s" % ("ok" if ok else "FAIL", "places: labels, script skipped", show(" ".join(p["key"] + "=" + p["printed"] for p in pl))))
    case("clean", ch, rules, {})
    case("value swapped", ch.replace("8{,}89", "8{,}78"), rules, {"value": 1})
    case("sign lost", ch.replace("\u22120,18", "0,18"), rules, {"place moved": 1, "value": 1})
    case("shown sum broken", ch.replace("0{,}1708", "0{,}1707"), rules, {"value": 1})
    case("rule missing", ch, rules[:-1], {"no rule": 1})
    case("place gone", ch.replace("[\u22120,18; +0,51]", "[\u22120,18]"), rules, {"place gone": 1})
    case("text before number changed", ch.replace("Pair 0{,}1072", "Sum 0{,}1072"), rules, {"place moved": 3})
    fake = rules[:2] + [("s1#1.3", rules[2][1], E("8.88735 + 0 * {d:tau}"))] + rules[3:]
    rows, dead = liveness(ch, data, fake)
    ok = [d[2] for d in dead] == ["s1#1.3"]
    results.append(ok)
    print("  %-4s %-34s dead %s" % ("ok" if ok else "FAIL", "liveness catches a constant", [d[2] for d in dead]))
    printed = {p["key"]: p["value"] for p in places(ch)}
    try:
        # the name must stand inside the generator body: the outermost iterable is
        # evaluated in eval's own scope and would pass even on the broken engine
        v1, _ = evaluate(E("sum({d:ci[*]}[i] for i in range(2))"), data, printed)
        v2, _ = evaluate(A("sum([{#s1#2.1}, {#s1#2.2}][i] for i in range(2))"), data, printed)
        ok = abs(v1 - 0.337611) < 1e-9 and abs(v2 - 0.1708) < 1e-9
        got = "%.6f %.4f" % (v1, v2)
    except Exception as ex:                              # noqa: BLE001 - the case under test
        ok, got = False, "%s: %s" % (type(ex).__name__, ex)
    results.append(ok)
    print("  %-4s %-34s %s" % ("ok" if ok else "FAIL", "generators inside E and A", got))
    rows, dead = liveness(ch, data, rules)
    ok = dead == []
    results.append(ok)
    print("  %-4s %-34s dead %s" % ("ok" if ok else "FAIL", "liveness clean on honest rules", dead))
    print("SELFTEST: %s" % ("instrument works" if all(results) else "BROKEN"))
    return 0 if all(results) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("manifest", nargs="?")
    ap.add_argument("--html")
    ap.add_argument("--data", action="append", default=[], help="ALIAS=FILE")
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--fields", action="store_true")
    ap.add_argument("--liveness", action="store_true")
    ap.add_argument("--template")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.template:
        return template(a.template)
    if not a.manifest:
        ap.print_usage()
        return 2
    try:
        m = load_manifest(a.manifest)
        html_path = Path(a.html) if a.html else ROOT / m["CHAPTER"]
        paths = {k: ROOT / v for k, v in m["DATA"].items()}
        for item in a.data:
            k, v = item.split("=", 1)
            paths[k] = Path(v)
        data = {k: json.loads(Path(v).read_text(encoding="utf-8")) for k, v in paths.items()}
    except Exception as ex:                              # noqa: BLE001
        print("manifest or usage error: %s: %s" % (type(ex).__name__, show(str(ex))))
        return 2
    return report(a.manifest, html_path, data, m["RULES"], a.review, a.fields, a.liveness)


if __name__ == "__main__":
    sys.exit(main())
