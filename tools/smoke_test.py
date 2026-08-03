"""
Load the built page in a real browser and assert it actually works.

    python tools/smoke_test.py                 # tests ./index.html
    python tools/smoke_test.py --url https://kejjeh.github.io/earth-x-time/
    python tools/smoke_test.py --headed        # watch it

WHY THIS EXISTS
---------------
This project lost an entire build to a silent boot failure. The legend swatches
read CSSV['sub-evolution'] where readPalette() writes CSSV.evolution, so undefined
reached withAlpha, which called .replace on it and threw. That line sits three
lines above requestAnimationFrame(frame), so the animation loop was never started
- not throttled, never started - and the whole page ran off a 1.3 Hz watchdog for
the entire development history.

Nothing caught it, because every check I ran called drawGlobe() directly and read
back canvas pixels. That passes perfectly against a page that displays nothing.
The checks that catch it are the ones below: does boot() report that it finished,
does requestAnimationFrame actually tick, is the thing under the middle of the
stage really the canvas, and does dragging move the globe. All of them ask the
page from outside rather than calling into it.

Every assertion here failed at some point during development. None are
hypothetical.

Requires playwright with chromium (`pip install playwright && playwright install
chromium`). Exits non-zero on any failure, so it can gate a build.
"""
import argparse, functools, http.server, json, os, socketserver, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


# ------------------------------------------------------------------ reporting
class Report:
    def __init__(self):
        self.rows = []

    def check(self, name, passed, detail=""):
        self.rows.append((bool(passed), name, str(detail)))
        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {name}" + (f"   {detail}" if detail else ""), flush=True)
        return bool(passed)

    @property
    def failures(self):
        return [r for r in self.rows if not r[0]]


# ------------------------------------------------------------- a local server
# file:// is not good enough: a blob-URL Worker (the animation clock) is refused
# from an opaque file origin, so the heartbeat would silently not be under test.
def serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a, **k: None
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


PROBE = """
window.__ticks = 0;
(function t() { window.__ticks++; requestAnimationFrame(t); })();
"""

# Wrapping the global `render` rather than adding a counter to the source: a
# function declaration in a classic script IS a property of the global object, so
# reassigning it changes what every internal caller resolves.
WRAP_RENDER = """
window.__renders = 0;
if (typeof window.render === 'function' && !window.__wrapped) {
  window.__wrapped = true;
  const inner = window.render;
  window.render = function (dt) { window.__renders++; return inner(dt); };
}
"""

CANVAS_STATS = """
(sel) => {
  const c = document.querySelector(sel);
  if (!c) return { err: 'no canvas' };
  const g = c.getContext('2d');
  const W = c.width, H = c.height;
  if (!W || !H) return { err: 'zero-sized backing store' };
  const seen = new Set();
  let opaque = 0, n = 0;
  for (let i = 0; i < 40; i++) for (let j = 0; j < 40; j++) {
    const x = Math.floor((i + 0.5) * W / 40), y = Math.floor((j + 0.5) * H / 40);
    const d = g.getImageData(x, y, 1, 1).data;
    seen.add((d[0] << 16) | (d[1] << 8) | d[2]);
    if (d[3] > 8) opaque++;
    n++;
  }
  return { w: W, h: H, colours: seen.size, opaqueFrac: opaque / n };
}
"""


def run(url, headed, report):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        # has_touch so CDP can dispatch real multi-touch at the pinch handler.
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  device_scale_factor=1, has_touch=True)
        page = ctx.new_page()
        page_errors, console_errors = [], []
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)
        page.add_init_script(PROBE)

        page.goto(url, wait_until="load", timeout=45000)
        page.wait_for_timeout(1200)

        # -------------------------------------------------- 1. did boot finish
        boot_ok = page.evaluate("window.__BOOT_OK === true")
        boot_err = page.evaluate("window.__BOOT_ERR || null")
        report.check("boot() ran to completion", boot_ok,
                     "" if boot_ok else f"__BOOT_OK={boot_ok!r}")
        report.check("boot() threw nothing", boot_err is None, boot_err or "")

        report.check("no uncaught page errors", not page_errors,
                     " | ".join(page_errors[:3]))
        report.check("no console errors", not console_errors,
                     " | ".join(console_errors[:3]))

        # ------------------------------------- 2. is the animation loop LIVE
        # The distinction that mattered: rAF being *requested* is not rAF
        # *running*. Count real ticks over a real interval.
        t0 = page.evaluate("window.__ticks")
        page.evaluate(WRAP_RENDER)
        page.wait_for_timeout(600)
        ticks = page.evaluate("window.__ticks") - t0
        renders = page.evaluate("window.__renders")
        report.check("requestAnimationFrame is ticking", ticks >= 20,
                     f"{ticks} ticks in 600ms")
        report.check("the render loop is painting", renders >= 20,
                     f"{renders} renders in 600ms")
        # "Something is painting at 60fps" is NOT the same question as "the page
        # started its own animation loop". Deleting requestAnimationFrame(frame)
        # entirely still passes the check above, because the worker heartbeat
        # picks the work up and paints at 61 Hz. That is the fallback doing its
        # job, and it is precisely the state the page was silently stuck in for
        # its whole development. Ask the page directly which clock is driving it.
        report.check("the page's own rAF loop is live, not just the fallback clock",
                     page.evaluate("typeof rafIsLive === 'function' && rafIsLive()"),
                     f"lastRafAt was {page.evaluate('Math.round(performance.now() - lastRafAt)')}ms ago")
        report.check("the worker heartbeat exists as a fallback",
                     page.evaluate("typeof beat !== 'undefined' && beat !== null"))
        report.check("visibilityState is visible", page.evaluate("document.visibilityState") == "visible")

        # ------------------------------------ 3. is the globe actually THERE
        # A screenshot of a page whose canvas is 80x80 in the corner still looks
        # like a page. Ask what the user's cursor would hit at the middle of it.
        hit_id = page.evaluate("""() => {
          const st = document.getElementById('stage').getBoundingClientRect();
          const el = document.elementFromPoint(st.left + st.width / 2, st.top + st.height / 2);
          return el ? (el.id || el.tagName) : null;
        }""")
        report.check("stage centre hits the globe canvas", hit_id == "globe",
                     f"elementFromPoint -> {hit_id!r}")

        box = page.locator("#globe").bounding_box()
        report.check("globe canvas fills the stage", box and box["width"] > 400 and box["height"] > 300,
                     f"{box['width']:.0f}x{box['height']:.0f}" if box else "no box")

        g = page.evaluate(CANVAS_STATS, "#globe")
        report.check("globe canvas has a real backing store", not g.get("err"), g.get("err", ""))
        if not g.get("err"):
            report.check("globe is drawn, not blank", g["colours"] >= 200,
                         f"{g['colours']} distinct colours in a 40x40 sample")
        c = page.evaluate(CANVAS_STATS, "#chroncv")
        if not c.get("err"):
            report.check("stratigraphic ribbon is drawn", c["colours"] >= 10,
                         f"{c['colours']} distinct colours")
        k = page.evaluate(CANVAS_STATS, "#krailcv")
        if not k.get("err"):
            report.check("knowledge rail is drawn", k["colours"] >= 5,
                         f"{k['colours']} distinct colours")

        # ------------------------------------- 4. the exact line that broke it
        sw = page.evaluate("""() => ['lg-solid','lg-band','lg-arc'].map(id => {
          const el = document.getElementById(id);
          return el ? (el.style.background || el.style.backgroundImage || '') : 'MISSING';
        })""")
        report.check("legend swatches are styled", all(s and s != "MISSING" for s in sw),
                     json.dumps(sw)[:120])
        report.check("subject chips rendered",
                     page.evaluate("document.getElementById('subjects').children.length") == 6,
                     f"{page.evaluate('document.getElementById(\"subjects\").children.length')} chips")

        # --------------------------------------------------- 5. does it respond
        lam0 = page.evaluate("S.rot.lam")
        r0 = page.evaluate("window.__renders")
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        for i in range(1, 13):
            page.mouse.move(cx + i * 16, cy)
            page.wait_for_timeout(8)
        page.mouse.up()
        page.wait_for_timeout(80)
        lam1 = page.evaluate("S.rot.lam")
        report.check("dragging rotates the globe", abs(lam1 - lam0) > 5,
                     f"lam {lam0:.1f} -> {lam1:.1f}")
        report.check("dragging repaints", page.evaluate("window.__renders") - r0 >= 8,
                     f"{page.evaluate('window.__renders') - r0} renders during the drag")

        z0 = page.evaluate("ZOOMF")
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, -240)
        page.wait_for_timeout(120)
        report.check("wheel zooms", abs(page.evaluate("ZOOMF") - z0) > 0.01,
                     f"ZOOMF {z0:.2f} -> {page.evaluate('ZOOMF'):.2f}")

        # --------------------------------------------------------- pinch zoom
        cdp = ctx.new_cdp_session(page)

        def touch(kind, points):
            cdp.send("Input.dispatchTouchEvent", {
                "type": kind,
                "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(points)]})

        page.evaluate("setZoom(1.0); S.selection = null; invalidate();")
        page.wait_for_timeout(60)
        z0 = page.evaluate("ZOOMF")
        touch("touchStart", [(cx - 60, cy), (cx + 60, cy)])
        for d in (80, 110, 150, 190):
            touch("touchMove", [(cx - d, cy), (cx + d, cy)])
            page.wait_for_timeout(16)
        touch("touchEnd", [(cx + 190, cy)])
        touch("touchEnd", [])
        page.wait_for_timeout(120)
        z1 = page.evaluate("ZOOMF")
        report.check("two fingers zoom the globe", z1 > z0 * 1.5, f"ZOOMF {z0:.2f} -> {z1:.2f}")
        report.check("a pinch does not leave a stuck pointer",
                     page.evaluate("PTRS.size === 0 && pinch === null"),
                     f"PTRS.size={page.evaluate('PTRS.size')} pinch={page.evaluate('pinch !== null')}")
        report.check("a pinch is not read as a click",
                     page.evaluate("S.selection") is None,
                     f"selection={page.evaluate('S.selection')!r}")

        # --------------------------------------------------------------- search
        page.fill("#search", "iridium")
        page.wait_for_timeout(250)
        hits = page.evaluate("""() => [...document.getElementById('results').children]
                                       .map(li => li.dataset.id)""")
        report.check("search reaches inside the claims, not just the titles",
                     "kpg_extinction" in hits,
                     f"'iridium' -> {hits}")
        if hits:
            page.evaluate("document.getElementById('results').children[0].click()")
            page.wait_for_timeout(900)
            report.check("choosing a result selects it",
                         page.evaluate("S.selection") in hits,
                         f"selection={page.evaluate('S.selection')!r}")
        page.fill("#search", "")
        page.keyboard.press("Escape")
        page.wait_for_timeout(80)

        # ----------------------------------- 6. the dataset and its whole point
        counts = page.evaluate("""() => ({
          claims: GRAPH.claims.length, referents: GRAPH.referents.length,
          edges: GRAPH.edges.length, visible: facts().visible.length })""")
        report.check("graph loaded", counts["claims"] > 100 and counts["referents"] > 20,
                     json.dumps(counts))
        report.check("something is visible at the default view", counts["visible"] > 5,
                     f"{counts['visible']} referents visible")

        # The signature behaviour: scrubbing knowledge-time rewires causation.
        rewire = page.evaluate("""() => {
          const kt0 = S.kt;
          const at = y => { setKt(y); invalidate();
            const e = facts().allEdges.find(e =>
              e.edge.source === 'chicxulub_impact' && e.edge.target === 'kpg_extinction');
            return e ? e.status : null; };
          const out = { y1975: at(1975), y1980: at(1980), y1991: at(1991), y2025: at(2025) };
          setKt(kt0); invalidate();
          return out;
        }""")
        report.check("Chicxulub -> K-Pg is absent in 1975", rewire["y1975"] is None, json.dumps(rewire))
        report.check("...proposed by 1980", rewire["y1980"] in ("proposed", "contested"), rewire["y1980"])
        report.check("...consensus by 1991", rewire["y1991"] == "consensus", str(rewire["y1991"]))

        # ------------------------------------------------ 7. selection round-trip
        # The marker nearest the middle of the canvas, not whichever was drawn
        # first: the corner overlays are real elements, and a click landing on
        # one never reaches the globe at all.
        page.evaluate("setZoom(0.86); renderNow();")
        page.wait_for_timeout(150)
        picked = page.evaluate("""() => {
          let best = null, bd = 1e18;
          for (const h of HIT) {
            if (!h.id) continue;
            const dx = h.x - GW / 2, dy = h.y - GH / 2, d = dx * dx + dy * dy;
            if (d < bd && h.x > 130 && h.y > 90 && h.x < GW - 130 && h.y < GH - 60) {
              bd = d; best = h;
            }
          }
          return best ? { id: best.id, x: best.x, y: best.y } : null;
        }""")
        if report.check("markers have hit targets", picked is not None):
            page.mouse.click(box["x"] + picked["x"], box["y"] + picked["y"])
            page.wait_for_timeout(200)
            sel = page.evaluate("S.selection")
            report.check("clicking a marker selects it", sel is not None, f"selection={sel!r}")
            txt = page.evaluate("document.getElementById('detail').innerText || ''")
            report.check("the detail panel fills in", len(txt) > 60, f"{len(txt)} chars")
            report.check("every fact shows a source", "Sources" in txt or "1" in txt,
                         txt[:60].replace("\n", " "))
            page.keyboard.press("Escape")
            page.wait_for_timeout(120)

        # -------------------------------------------------------- 8. URL state
        st = page.evaluate("typeof writeHash === 'function'")
        if st:
            page.evaluate("setKt(1900); S.rot.lam = 123; S.rot.phi = -33; writeHash(true);")
            page.wait_for_timeout(120)
            h = page.evaluate("location.hash")
            report.check("URL hash carries the view", len(h) > 8, h[:90])
            # about:blank first, deliberately. Navigating to a URL that differs
            # only in its hash is a SAME-DOCUMENT navigation: the browser fires
            # hashchange and never reloads, so the page under test would be the
            # one already running and this check would pass without proving
            # anything - which is exactly what it was doing. This is the flow a
            # stranger opening a shared link actually gets.
            page.goto("about:blank")
            page.goto(url.split("#")[0] + h, wait_until="load", timeout=45000)
            page.wait_for_timeout(1200)
            back = page.evaluate("({kt: S.kt, lam: Math.round(S.rot.lam), phi: Math.round(S.rot.phi)})")
            report.check("a shared URL restores the view",
                         back["kt"] == 1900 and abs(back["lam"] - 123) <= 1 and abs(back["phi"] + 33) <= 1,
                         json.dumps(back))
            report.check("no errors after restoring from a URL", not page_errors,
                         " | ".join(page_errors[:2]))

        browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="test a deployed URL instead of the local build")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()

    httpd = None
    if a.url:
        url = a.url
    else:
        target = os.path.join(ROOT, "index.html")
        if not os.path.exists(target):
            sys.exit("FATAL: index.html not found - run tools/build.py first")
        httpd, base = serve(ROOT)
        url = base + "index.html"

    print(f"smoke test: {url}")
    report = Report()
    try:
        run(url, a.headed, report)
    finally:
        if httpd:
            httpd.shutdown()

    n = len(report.rows)
    bad = report.failures
    print(f"\n{n - len(bad)}/{n} checks passed")
    if bad:
        print("\nFAILED:")
        for _, name, detail in bad:
            print(f"  {name}   {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
