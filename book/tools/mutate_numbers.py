"""Random number-swap mutations of a chapter, for checking a number verifier.

Each mutation replaces ONE number in a text node of a byte copy of the chapter with
another number that already stands elsewhere in the same chapter, in the same notation
(TeX '1{,}23', plain '1,23', or an integer of two or more digits). A verifier that binds
every value to its place must fail on every mutation; a verifier that only checks that a
value occurs somewhere, or that a value belongs to an allowed list, misses such swaps.

The candidate differs from the original by at least one unit of the coarser printed
digit, so a legitimate rounding variant is never counted as a mutation. Tags, attributes,
<script> and <style> are never touched. The source file is only read: its SHA-256 is
checked before and after, and a mismatch fails the run.

usage:
  python mutate_numbers.py --html CHAPTER.html --n 30 --seed 1 -- python verifier.py --html {html}

The command after '--' is the verifier; '{html}' is replaced by the mutated copy.
Exit: 0 all mutations caught, 1 some missed, 2 verifier fails on the unmutated chapter,
3 source changed during the run. ASCII output (cp1251 console).
"""
import argparse
import hashlib
import os
import random
import re
import subprocess
import sys
import tempfile

ap = argparse.ArgumentParser()
ap.add_argument("--html", required=True)
ap.add_argument("--n", type=int, default=30)
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("cmd", nargs=argparse.REMAINDER)
a = ap.parse_args()
cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
if not cmd or not any("{html}" in c for c in cmd):
    sys.exit("verifier command after '--' must contain {html}")

raw = open(a.html, "rb").read()
h0 = hashlib.sha256(raw).hexdigest()
src = raw.decode("utf-8")

# text-node spans of <body>, outside <script> and <style>
body = src.index("<body")
dead = [(m.start(), m.end()) for m in re.finditer(r"<(script|style)\b.*?</\1>", src, flags=re.S)]
spans = []
for m in re.finditer(r">([^<]+)<", src[body:]):
    s, e = body + m.start(1), body + m.end(1)
    if not any(x <= s < y for x, y in dead):
        spans.append((s, e))

TOK = re.compile(r"(?<![A-Za-z\u0370-\u03ff\u0400-\u04ff_\d.,])\d+(?:\{,\}\d+|,\d+)?(?![A-Za-z\u0370-\u03ff\u0400-\u04ff_\d])")


def kind(t):
    return "tex" if "{,}" in t else ("dec" if "," in t else "int")


def value(t):
    return float(t.replace("{,}", ".").replace(",", "."))


def decimals(t):
    t = t.replace("{,}", ",")
    return len(t.split(",")[1]) if "," in t else 0


occ = []
for s, e in spans:
    for m in TOK.finditer(src, s, e):
        t = m.group(0)
        if kind(t) == "int" and len(t) < 2:
            continue                      # single digits: reviewed by name, not by this gate
        occ.append((m.start(), m.end(), t))
pool = {}
for _, _, t in occ:
    pool.setdefault(kind(t), set()).add(t)


def run(path):
    c = [x.replace("{html}", path) for x in cmd]
    return subprocess.run(c, capture_output=True).returncode


print("source sha256 %s | numbers in text nodes: %d (tex %d, dec %d, int>=2 digits %d) | seed %d"
      % (h0[:12], len(occ), sum(kind(t) == "tex" for *_, t in occ), sum(kind(t) == "dec" for *_, t in occ),
         sum(kind(t) == "int" for *_, t in occ), a.seed))
base = run(a.html)
print("verifier on the unmutated chapter: exit %d" % base)
if base != 0:
    sys.exit(2)

rng = random.Random(a.seed)
caught = 0
done = 0
with tempfile.TemporaryDirectory() as td:
    order = list(range(len(occ)))
    rng.shuffle(order)
    for i in order:
        if done == a.n:
            break
        s, e, old = occ[i]
        cands = sorted(t for t in pool[kind(old)]
                       if abs(value(t) - value(old)) >= 10 ** (-min(decimals(old), decimals(t))) - 1e-12)
        if not cands:
            continue
        new = rng.choice(cands)
        p = os.path.join(td, "m%03d.html" % done)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(src[:s] + new + src[e:])
        rc = run(p)
        caught += rc != 0
        line = src.count("\n", 0, s) + 1
        print("  m%03d line %5d  %-12s -> %-12s %s" % (done, line, old.replace("{,}", ","), new.replace("{,}", ","),
                                                       "caught" if rc else "MISSED"))
        done += 1
h1 = hashlib.sha256(open(a.html, "rb").read()).hexdigest()
print("caught %d of %d" % (caught, done))
print("source unchanged: %s" % (h0 == h1))
if h0 != h1:
    sys.exit(3)
sys.exit(0 if caught == done else 1)
