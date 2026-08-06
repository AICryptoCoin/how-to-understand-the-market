# -*- coding: utf-8 -*-
"""Progon pribora geometrii knigi na nastoyashchih uzkih shirinah.

Ispolzuet sistemnyy Chrome (channel="chrome"), nichego ne kachaet.
Poryadok -- STYLE-GUIDE §7.5: yavnyy razmer okna, perezagruzka, preflight,
potom run(). Selftest i liveness -- na kazhdoy shirine.
"""
import json
import sys
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8971/ocenochnaya-funkciya.html"
WIDTHS = [320, 360, 390, 1280]

JS_PRE = "(async () => { const m = await import('/tools/geometry-check.js'); window.__geo = m; return JSON.stringify(m.preflight()); })()"
JS_RUN = "(async () => { const r = await window.__geo.run(); r.selftest = await window.__geo.selftest(); return JSON.stringify(r); })()"

def main():
    bad = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        for w in WIDTHS:
            ctx = browser.new_context(viewport={"width": w, "height": 900},
                                      device_scale_factor=1)
            page = ctx.new_page()
            page.goto(URL, wait_until="networkidle")
            page.wait_for_timeout(400)
            pre = json.loads(page.evaluate(JS_PRE))
            if not pre["ok"]:
                print("%4d px  PREFLIGHT NE PROSHEL: %s" % (w, pre["reasons"]))
                bad += 1
                ctx.close()
                continue
            res = json.loads(page.evaluate(JS_RUN))
            p = res["page"]
            live = res.get("liveness") or {}
            st = res.get("selftest") or {}
            ok = res.get("ok")
            print("%4d px | innerWidth %-5s ctm %-6s | figur %d, tekstov %-4d | "
                  "boxPairs %-3d stolknoveniy %-2d overflow %-2d | "
                  "selftest %-5s liveness %-5s | scroll %-5s | ok %s"
                  % (w, pre["env"]["innerWidth"], round(pre["env"]["ctmScale"], 3),
                     p["figures"], p["texts"], p["boxPairs"], len(p["collisions"]),
                     len(p["overflow"]), st.get("ok"), live.get("ok"),
                     p["pageScroll"], ok))
            if p["collisions"]:
                for c in p["collisions"][:8]:
                    print("        STOLKNOVENIE:", json.dumps(c, ensure_ascii=False)[:200])
            if p["overflow"]:
                for c in p["overflow"][:8]:
                    print("        OVERFLOW:", json.dumps(c, ensure_ascii=False)[:200])
            if not ok or p["pageScroll"] or p["collisions"]:
                bad += 1
            ctx.close()
        browser.close()
    print("")
    print("SHIRIN S DEFEKTAMI: %d iz %d" % (bad, len(WIDTHS)))
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
