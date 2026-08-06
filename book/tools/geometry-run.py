# -*- coding: utf-8 -*-
"""Progon pribora geometrii knigi na nastoyashchih shirinah.

Ispolzuet sistemnyy Chrome (channel="chrome"), nichego ne kachaet.
Poryadok -- STYLE-GUIDE §7.5: yavnyy razmer okna, perezagruzka, preflight,
selftest, potom run(). Selftest i liveness -- na kazhdoy shirine, i oba
vhodyat v verdikt.

Zapusk:

    python geometry-run.py                      svoy server, glava po umolchaniyu
    python geometry-run.py ocenochnaya-funkciya.html
    python geometry-run.py --widths 320,1280    tolko nazvannye shiriny
    python geometry-run.py --url http://127.0.0.1:8971/glava.html   chuzhoy server

Dve lovushki, na kotoryh zdes uzhe padali, zakryty v kode:

 1. Verdikt bez selftest. Ranshe selftest pechatalsya, no v `bad` ne vhodil:
    prisportiv etalon, mozhno bylo poluchit "selftest False ... ok True" i
    kod vozvrata 0. Teper selftest -- slagaemoe verdikta.
    Prichina v samom pribore: geometry-check.js:run() sobiraet `ok` bez
    selftest i polya takogo ne otdayot (STYLE-GUIDE §7.4, vrezka).

 2. Chuzhoy server na zanyatom portu. Windows puskaet vtorogo slushatelya na
    zanyatyy port bez oshibki, u sosednego dereva knigi te zhe imena faylov,
    poetomu i 404, i 200 prihodyat odinakovye, a mutaciya do brauzera ne
    doezzhaet. Poetomu: server podnimaem svoy na svobodnom portu (port 0 --
    port vybiraet OS), a otdannye baytu sveryaem s faylami na diske. Pri
    --url server chuzhoy, i sverka baytov -- edinstvennaya zashchita.

    Sverka imenno pobaytovaya, i eto namerenno. Pri core.autocrlf=true lyuboy
    worktree lezhit na diske s CRLF, a glavnoe derevo -- s LF, poetomu dazhe
    tot zhe kommit iz sosednego dereva dayot drugie bayty. Eto ne lozhnaya
    trevoga: merit nado tot fayl, kotoryy pravish, a ne ego dvoynik.
"""
import argparse
import json
import sys
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

BOOK = Path(__file__).resolve().parent.parent
DEFAULT_PAGE = "ocenochnaya-funkciya.html"
# Vyorstka smenilas 2026-08-06: kegl rastyot s ekranom do 21px, kolonka do
# 1425px na 2560 -- prezhniy spisok do etogo diapazona ne dostavil.
WIDTHS = [320, 360, 390, 1280, 1920, 2560]

JS_PRE = ("(async () => { const m = await import('/tools/geometry-check.js');"
          " window.__geo = m; return JSON.stringify(m.preflight()); })()")
# Selftest zovyotsya otdelno ot run() -- imenno tak trebuet STYLE-GUIDE §7.5.
JS_SELF = "(async () => JSON.stringify(await window.__geo.selftest()))()"
JS_RUN = "(async () => JSON.stringify(await window.__geo.run()))()"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


def serve(directory):
    """Svoy server na portu, kotoryy vybiraet OS. Vozvrashchaet (srv, port)."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0),
                              partial(QuietHandler, directory=str(directory)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def fetch(url):
    """(kod, telo). Otsutstvuyushchiy fayl -- eto otvet, a ne isklyuchenie."""
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode("utf-8", "replace")


def check_serving(base, page):
    """Dokazyvaet, chto server otdayot NASHI fayly, a ne sosednee derevo.

    Kontrol "404 na nesushchestvuyushchiy fayl" etogo NE dokazyvaet: chuzhoe
    derevo knigi otdast takoy zhe 404 i takoy zhe 200 na glavu. Dokazyvaet
    tolko sverka baytov s diskom -- i imenno tekh faylov, kotorye uchastvuyut
    v zamere: samoy glavy i samogo pribora.
    """
    bad = []
    code, _ = fetch(base + "/__net_takogo_fayla__.html")
    if code != 404:
        bad.append("na nesushchestvuyushchiy fayl otvet %s, a ne 404" % code)
    for rel in (page, "tools/geometry-check.js",
                "tools/fixtures/geometry-collision.html"):
        local = BOOK / rel
        if not local.exists():
            bad.append("net na diske: %s" % rel)
            continue
        code, body = fetch(base + "/" + rel)
        if code != 200:
            bad.append("%s: otvet %s, a ne 200" % (rel, code))
        elif body != local.read_bytes():
            bad.append("%s: server otdayot NE nash fayl (%d bayt protiv %d "
                       "na diske) -- eto chuzhoy server na tom zhe portu"
                       % (rel, len(body), len(local.read_bytes())))
    return bad


def main():
    ap = argparse.ArgumentParser(description="progon pribora geometrii")
    ap.add_argument("page", nargs="?", default=DEFAULT_PAGE,
                    help="imya fayla glavy vnutri book/")
    ap.add_argument("--widths", default=None,
                    help="shiriny cherez zapyatuyu (po umolchaniyu %s)"
                         % ",".join(str(w) for w in WIDTHS))
    ap.add_argument("--url", default=None,
                    help="polnyy adres glavy na uzhe podnyatom servere")
    args = ap.parse_args()

    widths = ([int(w) for w in args.widths.split(",")] if args.widths
              else list(WIDTHS))

    srv = None
    if args.url:
        base, _, page = args.url.rpartition("/")
        url = args.url
    else:
        srv, port = serve(BOOK)
        base = "http://127.0.0.1:%d" % port
        page = args.page
        url = "%s/%s" % (base, page)
        print("svoy server: %s (port vybran OS, chuzhoy zanyat byt ne mozhet)"
              % base)

    try:
        problems = check_serving(base, page)
        if problems:
            print("SERVER OTDAYOT NE TO:")
            for p in problems:
                print("   " + p)
            return 2
        print("server proveren: glava, pribor i etalon sovpadayut s diskom "
              "bayt v bayt")
        print("")

        bad = 0
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            for w in widths:
                ctx = browser.new_context(viewport={"width": w, "height": 900},
                                          device_scale_factor=1)
                page_obj = ctx.new_page()
                page_obj.goto(url, wait_until="networkidle")
                page_obj.wait_for_timeout(400)
                pre = json.loads(page_obj.evaluate(JS_PRE))
                if not pre["ok"]:
                    print("%4d px  PREFLIGHT NE PROSHEL: %s" % (w, pre["reasons"]))
                    bad += 1
                    ctx.close()
                    continue
                st = json.loads(page_obj.evaluate(JS_SELF))
                res = json.loads(page_obj.evaluate(JS_RUN))
                p = res["page"]
                live = res.get("liveness") or {}
                ok = res.get("ok")
                print("%4d px | innerWidth %-5s ctm %-6s | figur %d, tekstov %-4d | "
                      "boxPairs %-3d stolknoveniy %-2d overflow %-2d | "
                      "selftest %-5s liveness %-5s | scroll %-5s | ok %s"
                      % (w, pre["env"]["innerWidth"], round(pre["env"]["ctmScale"], 3),
                         p["figures"], p["texts"], p["boxPairs"], len(p["collisions"]),
                         len(p["overflow"]), st.get("ok"), live.get("ok"),
                         p["pageScroll"], ok))
                if not st.get("ok"):
                    print("        SELFTEST KRASNYY: %s | ozhidalos %s, "
                          "polucheno %s" % (st.get("why"), st.get("expect"),
                                            st.get("got")))
                if p["collisions"]:
                    for c in p["collisions"][:8]:
                        print("        STOLKNOVENIE:", json.dumps(c, ensure_ascii=False)[:200])
                if p["overflow"]:
                    for c in p["overflow"][:8]:
                        print("        OVERFLOW:", json.dumps(c, ensure_ascii=False)[:200])
                # Selftest -- slagaemoe verdikta, a ne stroka v otchyote.
                if not ok or not st.get("ok") or p["pageScroll"] or p["collisions"]:
                    bad += 1
                ctx.close()
            browser.close()
        print("")
        print("SHIRIN S DEFEKTAMI: %d iz %d" % (bad, len(widths)))
        return 1 if bad else 0
    finally:
        if srv is not None:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    sys.exit(main())
