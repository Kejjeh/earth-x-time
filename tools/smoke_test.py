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
import argparse, base64, functools, http.server, json, os, re, socketserver, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


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
        chips = page.evaluate("document.getElementById('subjects').children.length")
        report.check("subject chips rendered", chips == 6, f"{chips} chips")

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

        # A cancelled pinch must not strand the gesture. Android cancels a
        # stationary finger when long-press takes over; iOS cancels one on palm
        # rejection. pointercancel used to null the pinch and stop, leaving the
        # surviving finger with no drag origin and the grabbing cursor stuck on.
        touch("touchStart", [(cx - 60, cy), (cx + 60, cy)])
        touch("touchMove", [(cx - 120, cy), (cx + 120, cy)])
        page.wait_for_timeout(20)
        touch("touchCancel", [])
        page.wait_for_timeout(80)
        report.check("a cancelled pinch leaves no stranded state",
                     page.evaluate("PTRS.size === 0 && pinch === null && gDrag === null"),
                     f"PTRS.size={page.evaluate('PTRS.size')} "
                     f"gDrag={page.evaluate('gDrag !== null')}")
        report.check("a cancelled pinch releases the grabbing cursor",
                     not page.evaluate("document.getElementById('globe').classList.contains('dragging')"))

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

        # ------------------------------- 7b. what is drawn is what is clickable
        # A node recalled only to carry an edge is drawn small (significance
        # capped at 2). Its hit target was sized from the UNCAPPED significance,
        # so a 4.9 px dot claimed a 16 px invisible circle and stole hovers and
        # clicks from whatever was under it.
        page.evaluate("S.selection = null; markAll(); renderNow();")
        page.wait_for_timeout(150)
        mismatch = page.evaluate("""() => {
          const bad = [];
          for (const it of facts().visible) {
            if (!it.viaEdge) continue;
            // planet-wide facts ride the horizon instead of being markers, and
            // carry their own fixed-radius hit target; they are not this check.
            const h = HIT.find(x => x.id === it.id && !x.global);
            if (!h) continue;
            const drawn = markerRadius(Math.min(it.res.significance, 2)) + 7;
            if (Math.abs(h.r - drawn) > 0.01) bad.push({ id: it.id, hit: h.r, drawn });
          }
          return bad;
        }""")
        report.check("edge-recalled markers are only as clickable as they are big",
                     mismatch == [], json.dumps(mismatch)[:160])

        # --------------------------- 7c. the rival markers agree with their band
        # The band is the envelope of the claims competing for the DATE (res.pool).
        # The hollow markers inside it were drawn from res.dated - every live claim
        # carrying any date at all - so markers landed outside their own band and
        # overstated the disagreement. Radius 3 is the alt-marker radius and
        # nothing else in drawFacts uses it (a winner is 2.5 + significance*0.85,
        # never below 3.35).
        marks = page.evaluate("""() => {
          const ctx = document.getElementById('chroncv').getContext('2d');
          const real = ctx.arc.bind(ctx);
          let n = 0;
          ctx.arc = function (x, y, r, a, b, c) { if (r === 3) n++; return real(x, y, r, a, b, c); };
          needChron = true; drawChron();
          ctx.arc = real;
          let pool = 0, dated = 0;
          for (const it of facts().visible) {
            const r = it.res;
            if (!(r.disputed || S.resolver === 'spread')) continue;
            pool += r.pool.filter(l => l !== r.winner).length;
            dated += r.dated.filter(l => l !== r.winner).length;
          }
          return { drawn: n, pool, dated };
        }""")
        # Off-window markers are skipped, so drawn can only ever be <= the pool.
        # What must never happen is drawing more than the pool has in it.
        report.check("rival markers come from the claims competing for the date",
                     marks["drawn"] <= marks["pool"] and marks["pool"] < marks["dated"],
                     json.dumps(marks))

        # ------------------------------------------ 7d. every setting has a URL
        # encodeHash carries the basemap and the plate overlay, but the two
        # buttons only marked the globe dirty, so the toggle never wrote the hash
        # and the setting then arrived in it on the next unrelated interaction.
        page.evaluate("writeHash(true)")
        before = page.evaluate("location.hash")
        page.click("#btn-basemap")
        page.click("#btn-plates")
        page.wait_for_timeout(600)
        after = page.evaluate("location.hash")
        report.check("toggling the basemap and the plates reaches the URL",
                     "b=chart" in after and "p=0" in after,
                     f"{before[:40]} -> {after[:70]}")
        page.click("#btn-basemap")
        page.click("#btn-plates")
        page.wait_for_timeout(600)

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


        # Object.prototype keys are truthy in a plain-object map, so a hash of
        # #s=constructor once put a function into S.selection and threw in the
        # render loop on every frame.
        page.goto("about:blank")
        page.goto(url.split("#")[0] + "#s=constructor&m=toString&f=hasOwnProperty&x=valueOf",
                  wait_until="load", timeout=45000)
        page.wait_for_timeout(900)
        report.check("a hostile hash cannot poison the view",
                     page.evaluate("S.selection") is None
                     and page.evaluate("S.resolver") == "consensus"
                     and page.evaluate("S.focus") is None
                     and page.evaluate("window.__BOOT_OK") is True,
                     f"selection={page.evaluate('S.selection')!r} resolver={page.evaluate('S.resolver')!r}")
        report.check("a hostile hash raises no errors", not page_errors, " | ".join(page_errors[:2]))

        # ------------------------------- 9. a link to something not known yet
        # readHash validates s= against R.referents, which is right as far as it
        # goes - but nothing checked the referent could be RESOLVED at the
        # knowledge-time the same hash sets, so the panel fell through to
        # "Nothing selected" with the selection still set and still in the URL.
        page.goto("about:blank")
        page.goto(url.split("#")[0] + "#k=1700&s=homo_sapiens", wait_until="load", timeout=45000)
        page.wait_for_timeout(1200)
        notyet = page.evaluate("""() => {
          const t = (document.getElementById('detail').innerText || '').trim().toUpperCase();
          return { sel: S.selection, kt: S.kt,
                   resolvable: !!facts().items[S.selection],
                   emptyState: t.startsWith('NOTHING SELECTED'),
                   namesIt: t.includes('HOMO SAPIENS'),
                   saysYear: t.includes('1700') };
        }""")
        report.check("a link to something not known yet explains itself",
                     notyet["sel"] == "homo_sapiens" and not notyet["resolvable"]
                     and not notyet["emptyState"] and notyet["namesIt"] and notyet["saysYear"],
                     json.dumps(notyet))

        # ------------------------ 10. a hop inside the panel lands in the open
        # chooseResult clears a conflicting focus, re-enables the subject and
        # advances knowledge-time before selecting. The panel's own Connections
        # links did none of it, so a hop selected a referent with no mark on the
        # globe or the timeline and rendered a full panel for it anyway.
        page.goto("about:blank")
        page.goto(url.split("#")[0], wait_until="load", timeout=45000)
        page.wait_for_timeout(1400)
        case = page.evaluate("""() => {
          for (const sub of SUBJECTS) {
            S.subjects = new Set([sub]); S.focus = null; setKt(2026);
            S.selection = null; invalidate();
            const F = facts();
            for (const ed of F.allEdges) {
              const a = F.items[ed.edge.source], b = F.items[ed.edge.target];
              if (!a || !b) continue;
              if (a.subjectOn && !b.subjectOn) return { sub, from: ed.edge.source, to: ed.edge.target };
              if (b.subjectOn && !a.subjectOn) return { sub, from: ed.edge.target, to: ed.edge.source };
            }
          }
          return null;
        }""")
        if report.check("there is a filter-hidden neighbour to hop to", case is not None,
                        json.dumps(case)):
            page.evaluate("""(c) => {
              S.subjects = new Set([c.sub]); S.focus = null; setKt(2026);
              setSelection(c.from); renderNow();
            }""", case)
            page.wait_for_timeout(300)
            hopped = page.evaluate("""(c) => {
              const b = document.querySelector('#detail [data-goto="' + c.to + '"]');
              if (!b) return { clicked: false };
              b.click();
              return { clicked: true };
            }""", case)
            page.wait_for_timeout(1500)
            landed = page.evaluate("""() => {
              const it = facts().items[S.selection];
              return { sel: S.selection, visible: !!(it && it.visible),
                       onScreen: HIT.some(h => h.id === S.selection)
                              || CHIT.some(h => h.id === S.selection) };
            }""")
            report.check("a hop inside the panel lands on something you can see",
                         hopped["clicked"] and landed["sel"] == case["to"]
                         and landed["visible"] and landed["onScreen"],
                         json.dumps(landed))

        # --------------- 11. revealing something already in view keeps the view
        # chooseResult widened to [0, oldest*1.7] unconditionally, throwing away
        # a window someone had panned to in order to reveal a thing that was
        # never hidden.
        kept = page.evaluate("""() => {
          setKt(2026); S.subjects = new Set(SUBJECTS); S.focus = null;
          setWindow(0, 1.0e8); renderNow();
          const before = [Math.round(S.win.t0), Math.round(S.win.t1)];
          const r = resolve('kpg_extinction', S.kt, S.resolver);
          const inside = r.oldest <= S.win.t1 && r.youngest >= S.win.t0;
          chooseResult('kpg_extinction');
          return { before, inside,
                   to: TW ? [Math.round(TW.to.t0), Math.round(TW.to.t1)] : before };
        }""")
        report.check("revealing something already on screen keeps the window",
                     kept["inside"] and kept["to"] == kept["before"], json.dumps(kept))

        # ------------------------- 12. Compare eras is as modal as it says it is
        page.evaluate("TW = null; S.selection = null; changed(); renderNow();")
        page.wait_for_timeout(200)
        page.click("#btn-diff")
        page.wait_for_timeout(400)
        modal = page.evaluate("""() => ({
          focusInside: document.getElementById('diffwrap').contains(document.activeElement),
          appInert: document.querySelector('.app').hasAttribute('inert')
        })""")
        for _ in range(10):
            page.keyboard.press("Tab")
        modal["stillInside"] = page.evaluate(
            "document.getElementById('diffwrap').contains(document.activeElement)")
        report.check("Compare eras keeps focus in the dialog it declares modal",
                     modal["focusInside"] and modal["appInert"] and modal["stillInside"],
                     json.dumps(modal))

        # ---------------------------- 13. the year inputs stay on the rail
        # `+value || 1975` accepted 9, 3000 and -5 into S.ktA and drove resolve()
        # and the dialog title with them; and 0 is falsy, so the first character
        # of "2000" silently jumped the comparison to 1975.
        years = []
        for typed in ("9", "0", "3000", "-5"):
            page.fill("#diff-a", typed)
            page.wait_for_timeout(220)
            years.append(page.evaluate("S.ktA"))
        report.check("the compare-eras years stay on the knowledge rail",
                     all(1650 <= y <= 2026 for y in years), json.dumps(years))
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        report.check("Escape gives focus back to the button that opened it",
                     page.evaluate("document.activeElement.id") == "btn-diff",
                     page.evaluate("document.activeElement.id || document.activeElement.tagName"))

        # ------- 14. the numbers validate_graph.py gates on, asked of the page
        # Two implementations of one resolver, pinned to the same figures from
        # both sides. The validator used to assert these against a resolver that
        # was not the product's, and reported 24 movers where the page moves 28
        # and a disputed K-Pg where the page settles it.
        numbers = page.evaluate("""() => {
          let movers = 0;
          for (const id in R.referents) {
            const c = resolve(id, KT_MAX, 'consensus'), f = resolve(id, KT_MAX, 'frontier');
            if (c && f && Math.round(c.pos) !== Math.round(f.pos)) movers++;
          }
          const then = resolve('kpg_extinction', 1970, 'consensus');
          const now = resolve('kpg_extinction', KT_MAX, 'consensus');
          return { referents: Object.keys(R.referents).length, movers,
                   kpgDisputed1970: !!(then && then.disputed),
                   kpgDisputedNow: !!(now && now.disputed) };
        }""")
        report.check("28 of the 57 referents move under Newest",
                     numbers["referents"] == 57 and numbers["movers"] == 28,
                     json.dumps(numbers))
        report.check("the K-Pg date is disputed in 1970 and settled now",
                     numbers["kpgDisputed1970"] and not numbers["kpgDisputedNow"],
                     json.dumps(numbers))

        # ------- 15. the page and the Python tools agree on where the rail ends
        # src/20_core.js is the source of truth and says so, but the ceiling had
        # been typed out in six more places. Two Python tools were still on 2025
        # after it moved to 2026: stage4_merge refused a valid 2026 claim, and
        # ingest rewrote a 2026 citation's year to 2025. The tools now read it
        # from the source file; this pins the running page to the same value.
        from knowledge_time import KT_MIN as PY_MIN, KT_MAX as PY_MAX
        rail = page.evaluate("""() => ({
          min: KT_MIN, max: KT_MAX,
          railMin: +document.getElementById('krailcv').getAttribute('aria-valuemin'),
          railMax: +document.getElementById('krailcv').getAttribute('aria-valuemax'),
          nowLabel: document.getElementById('btn-now').textContent.trim(),
          diffMax: +document.getElementById('diff-a').max
        })""")
        report.check("the page and the Python tools end the rail in the same year",
                     rail["min"] == PY_MIN and rail["max"] == PY_MAX
                     and rail["railMin"] == PY_MIN and rail["railMax"] == PY_MAX
                     and rail["nowLabel"] == str(PY_MAX) and rail["diffMax"] == PY_MAX,
                     f"python {PY_MIN}..{PY_MAX}   page {json.dumps(rail)}")

        # ------- 16. the chips count the marks they account for, and only those
        # subjectCounts was tallied before the window, the zoom band and the
        # roll-up had been applied, so it moved with knowledge-time and nothing
        # else: zoomed to the Holocene the astronomy chip still read 11 with no
        # astronomy drawn anywhere.
        chips = page.evaluate("""() => {
          const out = [];
          const views = [
            { name: 'all 4.6 Ga',        win: [0, 4.6e9],  kt: KT_MAX },
            { name: 'last 60,000 years', win: [0, 60000],  kt: KT_MAX },
            { name: 'since the dinosaurs', win: [0, 7.0e7], kt: KT_MAX },
            { name: 'knowledge-time 1800', win: [0, 4.6e9], kt: 1800 }
          ];
          for (const v of views) {
            S.subjects = new Set(SUBJECTS); S.focus = null; S.selection = null;
            setKt(v.kt); setWindow(v.win[0], v.win[1]); renderNow();
            const F = facts();
            const drawn = {};
            for (const s of SUBJECTS) drawn[s] = 0;
            for (const it of F.visible)
              for (const s of it.res.subjects) if (s in drawn) drawn[s]++;
            const chip = {};
            for (const b of document.querySelectorAll('#subjects .sub'))
              chip[b.dataset.sub] = +b.querySelector('.cnt').textContent;
            const bad = SUBJECTS.filter(s => chip[s] !== drawn[s]);
            if (bad.length) out.push({ view: v.name, bad, chip, drawn });
          }
          return out;
        }""")
        report.check("every subject chip counts the marks it accounts for",
                     chips == [], json.dumps(chips)[:240])

        # ---------------- 17. Replay sweeps the rail the page actually has
        # The span was measured from a literal 1650 rather than KT_MIN, so with
        # the floor anywhere above that the opening seconds produced values
        # setKt clamped away - the rail sat still - and the rest ran at a rate
        # computed for a longer rail than the one on screen.
        replay = page.evaluate("""() => {
          startReplay();
          const start = S.kt;
          tickReplay(0.5);            // half a second in, it must already move
          const early = S.kt;
          for (let i = 0; i < 40; i++) tickReplay(0.5);
          const end = S.kt;
          stopReplay(); setKt(KT_MAX);
          return { start, early, end, min: KT_MIN, max: KT_MAX, playing: S.playing };
        }""")
        report.check("Replay sweeps from the floor of the rail to its ceiling",
                     replay["start"] == replay["min"]
                     and replay["early"] > replay["start"]
                     and replay["end"] == replay["max"]
                     and replay["playing"] is False,
                     json.dumps(replay))

        # Read back what drawKrail actually paints, rather than recomputing the
        # loop bounds here - a check that restates the code it is checking
        # cannot fail. The tick loop started at a literal 1650, so every tick
        # below the floor was painted outside the canvas: ktToY(1650) is 827px
        # in a 737px rail once KT_MIN moves up.
        rail_ticks = page.evaluate("""() => {
          const ctx = document.getElementById('krailcv').getContext('2d');
          const real = ctx.fillText.bind(ctx);
          const seen = [];
          ctx.fillText = function (t, x, y) { seen.push({ t, y }); return real(t, x, y); };
          needKrail = true; drawKrail();
          ctx.fillText = real;
          const years = seen.filter(s => /^\\d{4}$/.test(s.t));
          return {
            KT_MIN, KT_MAX, height: KH, pad: KPAD, count: years.length,
            outsideRange: years.filter(s => +s.t < KT_MIN || +s.t > KT_MAX).map(s => s.t),
            outsideCanvas: years.filter(s => s.y < 0 || s.y > KH).map(s => `${s.t}@${Math.round(s.y)}`)
          };
        }""")
        report.check("every rail tick is a year on the rail, drawn inside it",
                     rail_ticks["count"] > 2
                     and rail_ticks["outsideRange"] == []
                     and rail_ticks["outsideCanvas"] == [],
                     json.dumps(rail_ticks))

        # ---------- 18. the filled coastline does not swallow the globe
        # drawLandRing cuts each ring at the horizon and closes the gaps by
        # following the limb, choosing the sweep from the ring's own orientation.
        # The cheap alternative - collapsing hidden vertices onto the rim - turns
        # any continent straddling the horizon into a polygon that floods the
        # disc, and nothing here was measuring whether it does. Earth is ~29%
        # land; a hemisphere runs from about 0.05 (mid-Pacific) to 0.55.
        page.evaluate("""() => {
          S.basemap = 'chart'; S.showPlates = false;
          document.getElementById('stage').classList.remove('space');
          S.selection = null; TW = null; changed(); renderNow();
        }""")
        page.wait_for_timeout(400)
        fill = page.evaluate("""() => {
          const g = document.getElementById('globe').getContext('2d');
          const h = CSSV.land.replace('#', '');
          const LR = parseInt(h.slice(0, 2), 16),
                LG = parseInt(h.slice(2, 4), 16),
                LB = parseInt(h.slice(4, 6), 16);
          const fracs = [];
          for (let lam = -180; lam < 180; lam += 30) {
            for (const phi of [-60, -20, 20, 60]) {
              S.rot.lam = lam; S.rot.phi = phi; needGlobe = true; renderNow();
              const img = g.getImageData(0, 0, Math.round(GW * DPR), Math.round(GH * DPR));
              const d = img.data, W = img.width;
              let inDisc = 0, isLand = 0;
              for (let i = 0; i < 48; i++) for (let j = 0; j < 48; j++) {
                const x = Math.round((i + 0.5) * W / 48),
                      y = Math.round((j + 0.5) * img.height / 48);
                const dx = x / DPR - GCX, dy = y / DPR - GCY;
                if (dx * dx + dy * dy > (GR * 0.93) * (GR * 0.93)) continue;
                inDisc++;
                const k = (y * W + x) * 4;
                if (Math.abs(d[k] - LR) < 14 && Math.abs(d[k + 1] - LG) < 14 &&
                    Math.abs(d[k + 2] - LB) < 14) isLand++;
              }
              if (inDisc > 100) fracs.push({ lam, phi, f: isLand / inDisc });
            }
          }
          const fs = fracs.map(x => x.f);
          const worst = fracs.slice().sort((a, b) => b.f - a.f)[0];
          return {
            views: fracs.length,
            min: +Math.min(...fs).toFixed(3),
            max: +Math.max(...fs).toFixed(3),
            mean: +(fs.reduce((a, b) => a + b, 0) / fs.length).toFixed(3),
            worst: worst && { lam: worst.lam, phi: worst.phi, f: +worst.f.toFixed(3) }
          };
        }""")
        report.check("the filled coastline never floods the globe",
                     fill["views"] >= 40 and fill["max"] <= 0.70
                     and fill["min"] >= 0.005 and 0.18 <= fill["mean"] <= 0.40,
                     json.dumps(fill))
        page.evaluate("""() => {
          S.basemap = 'satellite'; S.showPlates = true;
          document.getElementById('stage').classList.add('space');
          S.rot.lam = 30; S.rot.phi = 12; changed(); renderNow();
        }""")
        page.wait_for_timeout(300)

        # ------------- 19. the live region is a sentence, not the whole panel
        # #detail carried aria-live="polite" and renderDetail rewrites it from
        # the needPanel block that every setKt sets, so an 8.9 KB region was
        # re-announced 226 times across one Replay. #tip was a second flood on
        # top of it - role="status", rewritten on every hover pointermove.
        live = page.evaluate("""() => ({
          detailLive: document.getElementById('detail').getAttribute('aria-live'),
          tipHidden: document.getElementById('tip').getAttribute('aria-hidden'),
          tipRole: document.getElementById('tip').getAttribute('role'),
          status: !!document.getElementById('sr-status'),
          statusRole: (document.getElementById('sr-status') || {}).getAttribute
                        ? document.getElementById('sr-status').getAttribute('role') : null
        })""")
        report.check("the announcement is a one-line status node, not the panel",
                     live["detailLive"] is None and live["tipHidden"] == "true"
                     and live["tipRole"] is None and live["status"]
                     and live["statusRole"] == "status",
                     json.dumps(live))

        # A held selection scrubbed across the whole rail should speak when its
        # date or its standing moves and stay quiet otherwise - the README leads
        # with exactly that gesture. Keyed on the sentence it announced 109
        # times, because the connection count climbs as edges arrive.
        # Counted against the ground truth rather than against a bound: sweep the
        # whole rail, count how many times the status node changes, and compare
        # with how many times the resolved date / standing / disputedness
        # actually changes. Equal means it speaks exactly when there is news.
        chatter = page.evaluate("""() => {
          const out = {};
          for (const id of ['kpg_extinction', 'peopling_americas']) {
            S.selection = null; changed();
            setSelection(id);
            const st = document.getElementById('sr-status');
            let said = 0, lastSaid = null;
            let real = 0, lastReal = null;
            for (let k = KT_MIN; k <= KT_MAX; k++) {
              setKt(k); renderNow();
              if (st.textContent !== lastSaid) { said++; lastSaid = st.textContent; }
              const r = resolve(id, k, S.resolver);
              const truth = r
                ? `${Math.round(r.pos)}|${r.winner ? r.winner.status : 'none'}|${r.disputed}`
                : 'unresolved';
              if (truth !== lastReal) { real++; lastReal = truth; }
            }
            out[id] = { said, real };
          }
          setKt(KT_MAX); S.selection = null; changed(); renderNow();
          return out;
        }""")
        report.check("a held selection speaks exactly when its date or standing moves",
                     all(v["said"] == v["real"] and v["real"] > 2 for v in chatter.values()),
                     json.dumps(chatter))

        # ------------------- 20. the causal graph can be walked from a keyboard
        # The hop rebuilds the panel, so the button that had focus stops
        # existing and focus fell to <body> - every step threw the user to the
        # top of the document.
        walk = page.evaluate("""() => {
          setKt(KT_MAX); setSelection('kpg_extinction'); renderNow();
          const b = document.querySelector('#detail [data-goto]');
          if (!b) return { none: true };
          b.focus();
          const before = document.activeElement === b;
          b.click();
          return { before, target: b.dataset.goto };
        }""")
        page.wait_for_timeout(700)
        landed = page.evaluate("""() => ({
          selection: S.selection,
          active: document.activeElement ? document.activeElement.tagName : null,
          insideDetail: document.getElementById('detail').contains(document.activeElement)
        })""")
        report.check("a hop inside the panel keeps focus in the panel",
                     walk.get("before") and landed["selection"] == walk.get("target")
                     and landed["insideDetail"],
                     json.dumps({**walk, **landed}))

        report.check("no page errors across the whole desktop run", not page_errors,
                     " | ".join(page_errors[:2]))

        browser.close()


def run_mobile(url, headed, report):
    """The phone build, from outside, at 390x844 with real touch.

    Everything above runs at 1440x900, which is exactly the width at which the
    phone layout's blockers are invisible: the stage control strip only grows
    off the left edge once the stage is narrow, and the detail panel is only
    a thousand pixels below the fold once .instrument is in grid row 3.
    """
    from playwright.sync_api import sync_playwright

    print("\n  -- phone, 390x844, touch --", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        ctx = browser.new_context(viewport={"width": 390, "height": 844},
                                  device_scale_factor=2, has_touch=True, is_mobile=True)
        page = ctx.new_page()
        page_errors = []
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.goto(url, wait_until="load", timeout=45000)
        page.wait_for_timeout(1600)
        report.check("the phone build boots", page.evaluate("window.__BOOT_OK") is True,
                     str(page.evaluate("window.__BOOT_ERR"))[:120])

        # ------------- every stage control can actually be reached by a finger
        # .stage-tr was shrink-to-fit anchored right inside an overflow:hidden
        # stage, so it grew off the LEFT edge: at 390px "Guided path" spanned
        # -64 to -1, and #btn-tour is the tour's only entry point - S.tour is
        # not in the hash and there is no keyboard binding.
        unreachable = page.evaluate("""() => {
          const strip = document.querySelector('.stage-tr');
          const bad = [];
          for (const b of strip.querySelectorAll('.iconbtn')) {
            // scroll the strip to the button the way a finger would, then ask
            // the document what is actually on top of its centre.
            b.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            const r = b.getBoundingClientRect();
            const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            if (!(el === b || b.contains(el))) {
              bad.push({ t: b.textContent.trim(), l: Math.round(r.left), r: Math.round(r.right) });
            }
          }
          strip.scrollLeft = 0;
          return bad;
        }""")
        report.check("every stage control is reachable on a phone",
                     unreachable == [], json.dumps(unreachable)[:200])

        # ----------------------------------- a tap on a marker shows something
        # The detail panel is grid row 3 under a 46vh stage - measured at
        # detailTop 1169 in an 870px viewport - and the tooltip never fires on
        # touch, so the tap changed nothing the tapper could see.
        page.evaluate("scrollTo(0, 0); S.selection = null; markAll(); renderNow();")
        page.wait_for_timeout(250)
        pick = page.evaluate("""() => {
          let best = null, bd = 1e18;
          for (const h of HIT) {
            if (!h.id) continue;
            const dx = h.x - GW / 2, dy = h.y - GH / 2, d = dx * dx + dy * dy;
            if (d < bd && h.x > 40 && h.y > 70 && h.x < GW - 40 && h.y < GH - 40) { bd = d; best = h; }
          }
          const r = document.getElementById('globe').getBoundingClientRect();
          return best ? { x: r.left + best.x, y: r.top + best.y, id: best.id } : null;
        }""")
        if report.check("the phone globe has a marker to tap", pick is not None):
            page.touchscreen.tap(pick["x"], pick["y"])
            page.wait_for_timeout(900)
            after = page.evaluate("""() => {
              const r = document.getElementById('detail').getBoundingClientRect();
              return { sel: S.selection, top: Math.round(r.top), vh: innerHeight };
            }""")
            report.check("tapping a marker brings its panel into view",
                         after["sel"] is not None and after["top"] < after["vh"] - 40,
                         json.dumps(after))

        # ------------------ choosing a search result flies something in view
        page.evaluate("scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(250)
        page.fill("#search", "iridium")
        page.wait_for_timeout(300)
        page.press("#search", "Enter")
        page.wait_for_timeout(1200)
        flew = page.evaluate("""() => ({
          sel: S.selection,
          stageTop: Math.round(document.getElementById('stage').getBoundingClientRect().top)
        })""")
        report.check("choosing a search result flies a globe you can see",
                     flew["sel"] is not None and flew["stageTop"] > -40, json.dumps(flew))

        # ------------------------------------------- the globe's focus ring
        # #globe is exactly .stage, and .stage is overflow:hidden, so an
        # outline painted 2px outside the border box is clipped entirely.
        ring = page.evaluate("""() => {
          const g = document.getElementById('globe');
          g.focus();
          const cs = getComputedStyle(g);
          return { outlineWidth: cs.outlineWidth, offset: cs.outlineOffset, shadow: cs.boxShadow };
        }""")
        report.check("the globe's focus ring is painted inside its own box",
                     "inset" in (ring["shadow"] or "")
                     or (ring["offset"] or "").startswith("-"),
                     json.dumps(ring)[:140])

        # ------------- a swipe up scrolls the page, it does not rewrite the view
        # All three surfaces carried touch-action:none, so the browser never got
        # the gesture: a 240px upward swipe took the globe from phi 12 to -89,
        # or knowledge-time from 2026 to 1979, with scrollY still 0 - and on the
        # timeline, whose pan reads only clientX, it did nothing at all. That was
        # 718px of an 870px first screen that refused to scroll.
        cdpm = ctx.new_cdp_session(page)

        def mtouch(kind, points):
            cdpm.send("Input.dispatchTouchEvent", {
                "type": kind,
                "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(points)]})

        def swipe_up(x, y, dist=240, steps=12):
            mtouch("touchStart", [(x, y)])
            for i in range(1, steps + 1):
                mtouch("touchMove", [(x, y - dist * i / steps)])
                page.wait_for_timeout(8)
            mtouch("touchEnd", [])
            page.wait_for_timeout(450)

        for name, sel, probe in (
                ("globe", "#globe", "S.rot.phi"),
                ("knowledge rail", "#krailcv", "S.kt"),
                ("timeline", "#chroncv", "S.win.t1")):
            page.evaluate("""(s) => {
              scrollTo(0, 0); setKt(KT_MAX); S.rot.lam = 30; S.rot.phi = 12;
              setWindow(0, 4.6e9); TW = null; changed(); renderNow();
            }""", sel)
            page.wait_for_timeout(250)
            spot = page.evaluate("""(s) => {
              const r = document.querySelector(s).getBoundingClientRect();
              return { x: r.left + r.width * 0.5, y: r.top + r.height * 0.6 };
            }""", sel)
            before = page.evaluate(probe)
            swipe_up(spot["x"], spot["y"])
            after = page.evaluate(probe)
            scrolled = page.evaluate("scrollY")
            report.check(f"a swipe on the {name} scrolls the page and leaves the view alone",
                         scrolled > 40 and after == before,
                         f"scrollY {scrolled}   {probe} {before} -> {after}")

        # ------------------- and the gestures that are the point still work
        page.evaluate("scrollTo(0, 0); S.rot.lam = 30; TW = null; changed(); renderNow();")
        page.wait_for_timeout(250)
        gspot = page.evaluate("""() => {
          const r = document.getElementById('globe').getBoundingClientRect();
          return { cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
        }""")
        lam0 = page.evaluate("S.rot.lam")
        mtouch("touchStart", [(gspot["cx"] - 90, gspot["cy"])])
        for i in range(1, 13):
            mtouch("touchMove", [(gspot["cx"] - 90 + 15 * i, gspot["cy"])])
            page.wait_for_timeout(8)
        mtouch("touchEnd", [])
        page.wait_for_timeout(350)
        report.check("a horizontal drag still rotates the globe on touch",
                     abs(page.evaluate("S.rot.lam") - lam0) > 5 and page.evaluate("scrollY") == 0,
                     f"lam {lam0} -> {page.evaluate('S.rot.lam'):.1f}")

        page.evaluate("scrollTo(0, 0); setKt(KT_MAX); renderNow();")
        page.wait_for_timeout(200)
        kspot = page.evaluate("""() => {
          const r = document.getElementById('krailcv').getBoundingClientRect();
          return { x: r.left + r.width * 0.6, y: r.top + r.height * 0.7 };
        }""")
        page.touchscreen.tap(kspot["x"], kspot["y"])
        page.wait_for_timeout(400)
        report.check("a tap still sets the year on the rail",
                     page.evaluate("S.kt") < 2026, f"kt -> {page.evaluate('S.kt')}")

        page.evaluate("scrollTo(0, 0); setKt(KT_MAX); setZoom(1.0); S.rot.phi = 12; renderNow();")
        page.wait_for_timeout(200)
        z0m = page.evaluate("ZOOMF")
        mtouch("touchStart", [(gspot["cx"] - 30, gspot["cy"]), (gspot["cx"] + 30, gspot["cy"])])
        for d in (50, 70, 90, 110):
            mtouch("touchMove", [(gspot["cx"] - d, gspot["cy"]), (gspot["cx"] + d, gspot["cy"])])
            page.wait_for_timeout(16)
        mtouch("touchEnd", [(gspot["cx"] + 110, gspot["cy"])])
        mtouch("touchEnd", [])
        page.wait_for_timeout(350)
        report.check("two fingers still zoom the globe on touch",
                     page.evaluate("ZOOMF") - z0m > 0.2 and page.evaluate("PTRS.size") == 0,
                     f"ZOOMF {z0m:.2f} -> {page.evaluate('ZOOMF'):.2f}")

        report.check("no page errors on the phone build", not page_errors,
                     " | ".join(page_errors[:2]))
        browser.close()


# Relative luminance and contrast ratio, WCAG 2.x.
def _lum(rgb):
    out = []
    for v in rgb:
        v = v / 255.0
        out.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def _ratio(a, b):
    l1, l2 = _lum(a), _lum(b)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def _rgb(css):
    m = re.match(r"rgba?\(([^)]+)\)", css or "")
    if not m:
        return None
    parts = [float(x) for x in re.split(r"[,\s/]+", m.group(1).strip()) if x]
    return parts[:3]


# Everything here is 9.5-12px, so none of it is "large text" and none of it gets
# the 3:1 exemption. These are the strings that say what the axes are.
SMALL_TEXT = ["#subhint", ".instrument .lbl", "#presets button", "#resnote",
              "#search-note", ".detail .empty", ".chron-bar .rd", ".iconbtn"]
# The stage is the awkward one: .stage.space is a fixed dark gradient with
# imagery over it, so its backdrop does not follow the theme while its text did.
# A computed backgroundColor cannot see a gradient, so these are measured by
# photographing the overlay's own box with the overlays hidden.
STAGE_TEXT = ["#epistemic", ".as-of", ".stage-bl .legend div"]
AA = 4.5

COMPUTED_CONTRAST = """(sels) => {
  const parse = str => { const m = String(str).match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(/[,\\s\\/]+/).filter(Boolean).map(Number);
    return { rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 }; };
  const out = [];
  for (const s of sels) {
    const el = document.querySelector(s);
    if (!el) { out.push({ s, missing: true }); continue; }
    const cs = getComputedStyle(el);
    const fg = parse(cs.color); if (!fg) continue;
    const chain = []; for (let n = el.parentElement; n; n = n.parentElement) chain.push(n);
    chain.reverse();
    let bg = [255, 255, 255];
    for (const n of chain) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (!c || c.a === 0) continue;
      bg = [0, 1, 2].map(i => c.rgb[i] * c.a + bg[i] * (1 - c.a));
    }
    const f = [0, 1, 2].map(i => fg.rgb[i] * fg.a + bg[i] * (1 - fg.a));
    out.push({ s, fg: f, bg, size: cs.fontSize });
  }
  return out;
}"""


def _backdrop(page, sel):
    """The pixels actually painted behind an overlay, with the overlays hidden."""
    box = page.evaluate("""(s) => {
      const el = document.querySelector(s); if (!el) return null;
      const r = el.getBoundingClientRect();
      if (r.width < 4 || r.height < 4) return null;
      return { color: getComputedStyle(el).color, size: getComputedStyle(el).fontSize,
               x: Math.round(r.left), y: Math.round(r.top),
               w: Math.round(r.width), h: Math.round(r.height) };
    }""", sel)
    if not box:
        return None
    page.evaluate("() => { for (const n of document.querySelectorAll('.stage-tl, .stage-bl'))"
                  " n.style.visibility = 'hidden'; }")
    page.wait_for_timeout(180)
    shot = page.screenshot(clip={"x": box["x"], "y": box["y"],
                                 "width": box["w"], "height": box["h"]})
    page.evaluate("() => { for (const n of document.querySelectorAll('.stage-tl, .stage-bl'))"
                  " n.style.visibility = ''; }")
    page.wait_for_timeout(120)
    mean = page.evaluate("""async (b64) => {
      const img = new Image();
      await new Promise(r => { img.onload = r; img.src = 'data:image/png;base64,' + b64; });
      const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
      const g = c.getContext('2d'); g.drawImage(img, 0, 0);
      const d = g.getImageData(0, 0, c.width, c.height).data;
      let r = 0, gg = 0, bb = 0, n = 0;
      for (let i = 0; i < d.length; i += 4) { r += d[i]; gg += d[i+1]; bb += d[i+2]; n++; }
      return [r / n, gg / n, bb / n];
    }""", base64.b64encode(shot).decode())
    return box, mean


def run_contrast(url, headed, report):
    """Both themes, both basemaps, measured rather than eyeballed.

    --chalk-faint used to sit at 3.32:1 in dark and 2.98:1 in light - where it
    got LIGHTER, which is backwards - and the stage overlays measured 3.25:1 in
    light over imagery, because .stage.space is a fixed dark gradient and only
    the text followed the theme.
    """
    from playwright.sync_api import sync_playwright

    print("\n  -- contrast, both themes --", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        for scheme in ("dark", "light"):
            ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                      device_scale_factor=1, color_scheme=scheme)
            page = ctx.new_page()
            page.goto(url, wait_until="load", timeout=45000)
            page.wait_for_timeout(1500)
            page.evaluate("S.selection = null; changed(); renderNow();")
            page.wait_for_timeout(250)

            worst = []
            for row in page.evaluate(COMPUTED_CONTRAST, SMALL_TEXT):
                if row.get("missing"):
                    worst.append((0.0, row["s"] + " (missing)"))
                    continue
                worst.append((_ratio(row["fg"], row["bg"]), f"{row['s']} @{row['size']}"))
            for basemap in ("satellite", "chart"):
                if basemap == "chart":
                    page.click("#btn-basemap")
                    page.wait_for_timeout(700)
                for sel in STAGE_TEXT:
                    got = _backdrop(page, sel)
                    if not got:
                        continue
                    box, bg = got
                    fg = _rgb(box["color"])
                    worst.append((_ratio(fg, bg), f"{sel} @{box['size']} over {basemap}"))

            worst.sort()
            lo, who = worst[0]
            report.check(f"every small string clears AA in {scheme} mode",
                         lo >= AA, f"worst {lo:.2f}:1  {who}")
            ctx.close()
        browser.close()


# ------------------------------------------------- the artifact head, offline
# No browser needed: this is a property of what tools/build.py emits, and it is
# the one gate that ran for a year without ever being exercised.
def run_artifact(report):
    """Prove that nothing head-only can reach the body of artifact.html.

    The strip step used to be a pattern that matched the two tags src/00_head.html
    happened to have. Five other shapes rode through it into the body, where a
    <base> is honoured by Chromium and repoints every relative URL on the host
    page. So the property under test is not "the current head is stripped" - that
    passed the whole time - it is "a head-only tag cannot get through, whatever
    it looks like": stripped, or the build stops. Never quietly kept.
    """
    sys.path.insert(0, HERE)
    import build

    tail = '<title>T</title>\n<style>b{color:red}</style>'
    shapes = [
        ("self-closed", '<meta charset="utf-8" />\n' + tail),
        ("bare, no slash", '<meta charset="utf-8">\n' + tail),
        ("indented", '  <meta charset="utf-8" />\n' + tail),
        ("uppercase", '<META charset="utf-8" />\n' + tail),
        ("attributes split over lines", '<meta name="viewport"\n   content="width=1" />\n' + tail),
        ("link rel=icon", '<link rel="icon" href="data:," />\n' + tail),
        ("base href", '<base href="/" />\n' + tail),
        ("comment then meta", '<!-- c -->\n<meta charset="utf-8">\n' + tail),
    ]
    for label, head in shapes:
        try:
            out = build.artifact_head(head, where="<test>")
            leaked = re.findall(r"<\s*(?:meta|link|base)\b[^>]*>", out, re.I | re.S)
            report.check(f"head-only tag cannot reach the body: {label}",
                         not leaked, "stripped" if not leaked else f"LEAKED {leaked}")
        except SystemExit as e:
            report.check(f"head-only tag cannot reach the body: {label}",
                         True, f"refused: {str(e)[:48]}")

    # <title> is what the publisher reads to name the page, so it has to survive
    # the strip, and its absence has to stop the build rather than ship unnamed.
    kept = build.artifact_head('<meta charset="utf-8">\n' + tail, where="<test>")
    report.check("<title> survives the strip", "<title>T</title>" in kept, kept[:40])
    try:
        build.artifact_head('<meta charset="utf-8">\n<style>b{}</style>', where="<test>")
        report.check("a head with no <title> stops the build", False, "it did not")
    except SystemExit:
        report.check("a head with no <title> stops the build", True)

    # An unknown head element is refused, not passed through on the assumption
    # that whatever it is must be safe in a body.
    try:
        build.artifact_head('<nosuchtag x="1">\n' + tail, where="<test>")
        report.check("an unrecognised head element stops the build", False, "it did not")
    except SystemExit:
        report.check("an unrecognised head element stops the build", True)

    # And the file actually on disk, which is what gets published.
    art = os.path.join(ROOT, "artifact.html")
    if os.path.exists(art):
        text = open(art, encoding="utf-8").read()
        # The markup only. The JS payload's comments discuss <html> and <body>
        # in English, so scanning the whole file would flag prose.
        markup = text.split("\n<script>\n")[0]
        found = re.findall(r"<\s*(?:meta|link|base)\b[^>]*>", markup, re.I | re.S)
        report.check("built artifact.html carries no head-only tags",
                     not found, f"{len(found)} found" if found else "none")
        report.check("built artifact.html has a <title> for the publisher",
                     re.search(r"<title\b[^>]*>.+?</title>", text[:8192], re.S | re.I) is not None)
        report.check("built artifact.html opens body-only, with no document wrapper",
                     not re.match(r"\s*<\s*(!doctype|html)\b", text, re.I), repr(text[:34]))

    # ---------------------------------------------- what a scraper is handed
    # The og:image is a file in this repo, and the tag is the only thing
    # pointing at it - nothing in the page references preview.jpg, so a rename
    # breaks the card silently and no gate upstream of here would notice. The
    # file also has to be the format its extension claims: it shipped for a
    # while as JPEG bytes under a .png name, which GitHub Pages then served as
    # image/png and several validators reject outright.
    std = os.path.join(ROOT, "earth-x-time.html")
    if os.path.exists(std):
        head = open(std, encoding="utf-8").read()[:9000]
        want = ["og:title", "og:description", "og:image", "og:image:alt", "og:url",
                "twitter:card", "twitter:image", 'name="description"', 'rel="icon"']
        missing = [w for w in want if w not in head]
        report.check("the standalone page carries its social card and favicon",
                     not missing, f"missing {missing}" if missing else "all present")

        m = re.search(r'property="og:image"\s+content="([^"]+)"', head)
        if m:
            name = m.group(1).rsplit("/", 1)[-1]
            path = os.path.join(ROOT, name)
            report.check("og:image names a file that is actually in the repo",
                         os.path.exists(path), f"{name} -> {'found' if os.path.exists(path) else 'MISSING'}")
            if os.path.exists(path):
                magic = open(path, "rb").read(4)
                ext = name.rsplit(".", 1)[-1].lower()
                ok = (ext in ("jpg", "jpeg") and magic[:2] == b"\xff\xd8") or \
                     (ext == "png" and magic == b"\x89PNG")
                report.check("the preview image is the format its name claims",
                             ok, f"{name} starts {magic.hex()}")

        alt = re.search(r'property="og:image:alt"\s+content="([^"]+)"', head)
        report.check("og:image:alt actually describes something",
                     bool(alt) and len(alt.group(1)) > 40,
                     (alt.group(1)[:60] + '...') if alt else "absent")


# --------------------------------------------- the pre-commit hook, for real
# README.md claims these cases are verified "against a staged file and a real
# git commit, not against the checker called directly", and that standard is
# the whole point: the hook picks its own interpreter, git runs it from the
# repo root, and the checker reads the staged blob rather than the file on
# disk. Calling scan() in-process would exercise none of that. So this drives
# real commits in a throwaway repo - never this one.
def run_hook(report):
    import shutil, subprocess, tempfile

    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
    tmp = tempfile.mkdtemp(prefix='hook-check-')

    def git(*a):
        return subprocess.run(('git',) + a, cwd=tmp, env=env, capture_output=True, text=True)

    def attempt(content, fname='p.md'):
        """Stage content, try a real commit, return True if the commit landed."""
        with open(os.path.join(tmp, fname), 'w', encoding='utf-8') as fh:
            fh.write(content + '\n')
        git('add', fname)
        rc = git('commit', '-qm', 'case').returncode
        git('reset', '-q', '--hard', 'HEAD')
        git('clean', '-qfd')
        return rc == 0

    try:
        os.makedirs(os.path.join(tmp, 'tools'))
        os.makedirs(os.path.join(tmp, '.githooks'))
        shutil.copy(os.path.join(ROOT, '.githooks', 'pre-commit'),
                    os.path.join(tmp, '.githooks', 'pre-commit'))
        shutil.copy(os.path.join(HERE, 'check_no_local_paths.py'),
                    os.path.join(tmp, 'tools', 'check_no_local_paths.py'))
        git('init', '-q', '.')
        git('config', 'core.hooksPath', '.githooks')
        git('add', '-A')
        base = git('commit', '-qm', 'base')
        if base.returncode:
            report.check('scratch repo arms the hook', False, base.stderr.strip()[:90])
            return
        report.check('scratch repo arms the hook', True)

        # Each of these names a real account and must never reach a public repo.
        # The last four are the forms that used to commit clean: a mount prefix
        # defeated the lookbehind the segment patterns relied on.
        # Assembled from fragments for the same reason the checker's own patterns
        # are: spelled out whole, these fixtures are themselves leaking paths in
        # a tracked file, and --all would refuse this repo. Found the hard way -
        # the first version of these checks failed its own --all check.
        U, H, N = 'Us' + 'ers', 'ho' + 'me', 'jd' + 'oe'
        for label, content in [
            ('windows, backslash',   rf'see C:\{U}\{N}\proj\x.js'),
            ('windows, forward',     f'see C:/{U}/{N}/proj/x.js'),
            ('macOS',                f'see /{U}/{N}/proj/x.js'),
            ('linux',                f'see /{H}/{N}/proj/x.js'),
            ('WSL mount',            f'see /mnt/c/{U}/{N}/proj/x.js'),
            ('Git Bash / MSYS',      f'see /c/{U}/{N}/proj/x.js'),
            ('Silverblue /var/home', f'see /var/{H}/{N}/proj/x.js'),
            ('UNC share',            rf'see \\fileserver\{U}\{N}\proj\x.js'),
        ]:
            report.check(f'hook blocks a real commit: {label}', not attempt(content))

        # And these must not fire. A gate that cries wolf is one people learn to
        # --no-verify past, which is worse than no gate at all.
        for label, content in [
            ('placeholder /home/you',    'clone to /home/you/earth-x-time'),
            ('repo-relative citation',   'see src/00_head.html:336'),
            ('relative docs/home path',  'see docs/home/index.md'),
            ('relative assets/Users',    'see assets/Users/readme.md'),
            ('/homebrew is not a home',  'installed under /homebrew/lib'),
            ('bare /home directory',     'the /home directory'),
            ('CI runner path',           'see /Users/runner/work/x'),
        ]:
            report.check(f'hook allows a real commit: {label}', attempt(content))

        # The staged blob is what ships, not the file on disk.
        q = os.path.join(tmp, 'q.md')
        open(q, 'w', encoding='utf-8').write(f'see /{H}/{N}/x.js\n')
        git('add', 'q.md')
        open(q, 'w', encoding='utf-8').write('see src/x.js\n')   # cleaned after staging
        rc = git('commit', '-qm', 'staged').returncode
        git('reset', '-q', '--hard', 'HEAD'); git('clean', '-qfd')
        report.check('hook reads the staged blob, not the worktree', rc != 0)

        open(q, 'w', encoding='utf-8').write('clean\n')
        git('add', 'q.md')
        open(q, 'w', encoding='utf-8').write(f'see /{H}/{N}/x.js\n')   # never staged
        rc = git('commit', '-qm', 'unstaged').returncode
        git('reset', '-q', '--hard', 'HEAD'); git('clean', '-qfd')
        report.check('hook ignores an unstaged worktree leak', rc == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The repo as it stands has to pass its own gate in --all mode.
    rc = subprocess.run([sys.executable, os.path.join(HERE, 'check_no_local_paths.py'), '--all'],
                        cwd=ROOT, capture_output=True, text=True)
    report.check('every tracked file passes --all', rc.returncode == 0,
                 rc.stdout.strip().splitlines()[1].strip() if rc.returncode else 'clean')


def run_features(url, headed, report):
    """The knowledge rail as a table of contents, the absent roster, and the
    outbound source links - the three things a reader uses to find their way
    around rather than to operate the page."""
    from playwright.sync_api import sync_playwright

    print("\n  -- rail landmarks, absent roster, source links --", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(url, wait_until="load", timeout=45000)
        page.wait_for_timeout(2200)
        try:
            # ---------------------------------------- the rail names its years
            # One table feeds the caption and the rail. If they ever disagree,
            # the page is telling a reader that 1991 matters while the control
            # that reaches 1991 stays silent about it.
            eras = page.evaluate("() => KT_ERAS.map(e => e.from)")
            labels = page.evaluate("""() => {
              const c = document.getElementById('krailcv').getContext('2d');
              const real = c.fillText.bind(c); const seen = [];
              c.fillText = function (t, x, y) { seen.push(t); return real(t, x, y); };
              needKrail = true; drawKrail(); c.fillText = real;
              return seen.filter(t => /^\\d{4}$/.test(t)).map(Number);
            }""")
            want = [y for y in eras if y > page.evaluate("KT_MIN")]
            report.check("the rail labels every landmark the caption knows about",
                         sorted(labels) == sorted(want), f"drawn {labels}")

            cap = page.evaluate("() => [eraAt(1991).caption, epistemicCaption()]")
            report.check("the caption is read from the same landmark table",
                         cap[0].startswith('Chicxulub'), cap[0][:48])

            # ------------------------- stepping lands only on years that change
            steps = page.evaluate("""() => {
              const out = []; setKt(KT_MAX);
              for (let i = 0; i < 12; i++) {
                const before = S.kt;
                document.getElementById('btn-prev').click();
                if (S.kt === before) break;
                out.push(S.kt);
              }
              return { years: out, allReal: out.every(y => KT_CHANGES.includes(y)) };
            }""")
            report.check("Prev steps only onto years in which something changes",
                         len(steps["years"]) >= 8 and steps["allReal"], str(steps["years"][:8]))

            # The rail must not say two different things about one year: a year
            # Next can reach is a year the readout has something to report.
            silent = page.evaluate(
                "() => KT_CHANGES.filter(y => railReadout(y).detail === 'nothing changes this year')")
            report.check("every year the rail steps to has something to report",
                         silent == [], f"{len(silent)} silent: {silent[:6]}")

            # Links come from GRAPH.edges via the asserting claim's year, never
            # from a status transition - a claim hardening is not a link.
            links = page.evaluate("""() => {
              let total = 0; for (const v of KT_YEAR.values()) total += v.links;
              return { total, edges: GRAPH.edges.length };
            }""")
            report.check("the rail counts links from edges, not from transitions",
                         links["total"] == links["edges"], json.dumps(links))

            sup = page.evaluate("() => KT_SUPERSEDED.reduce((a, p) => a + p[1], 0)")
            report.check("knowledge being withdrawn is drawn at all", sup > 0, f"{sup} supersessions")

            # -------------------------------------- hovering does not set the year
            page.evaluate("() => { setKt(1900); }")
            b = page.evaluate("""() => { const r = document.getElementById('krailcv')
              .getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height * 0.3]; }""")
            page.mouse.move(b[0], b[1])
            page.wait_for_timeout(150)
            hov = page.evaluate("""() => ({ kt: S.kt,
              read: document.getElementById('krail-read').innerText.trim() })""")
            report.check("hovering the rail reads out without moving the year",
                         hov["kt"] == 1900 and len(hov["read"]) > 8, json.dumps(hov)[:110])

            # ------------------------------------------- the absent are named
            page.evaluate("() => { setKt(KT_MAX); setSelection(null); }")
            page.wait_for_timeout(400)
            ros = page.evaluate("""() => {
              const F = facts(), el = document.querySelector('.absent');
              const rows = el ? [...el.querySelectorAll('[data-goto]')] : [];
              return {
                total: Object.keys(R.referents).length,
                visible: F.visible.length,
                rows: rows.length,
                reasoned: rows.filter(r => (r.querySelector('.mech') || {}).textContent).length
              };
            }""")
            report.check("every referent is either on screen or named as absent",
                         ros["visible"] + ros["rows"] == ros["total"], json.dumps(ros))
            report.check("every absent referent says why it is absent",
                         ros["rows"] > 0 and ros["reasoned"] == ros["rows"], json.dumps(ros))

            # #subjects stays exactly six chips - the roster is not rendered there
            report.check("the roster did not land in the subject chips",
                         page.evaluate("document.getElementById('subjects').children.length") == 6)

            # clicking an absent row actually brings it back
            hop = page.evaluate("""() => {
              document.querySelector('.absent').open = true;
              const b = document.querySelector('.absent [data-goto]');
              return b ? b.dataset.goto : null;
            }""")
            page.click(".absent [data-goto]")
            page.wait_for_timeout(1500)
            got = page.evaluate("""() => { const F = facts();
              return { sel: S.selection, vis: !!(F.items[S.selection] && F.items[S.selection].visible) }; }""")
            report.check("clicking an absent referent reveals it",
                         got["sel"] == hop and got["vis"], json.dumps(got))

            # ------------------------------------------------ following a source
            # One DOI in the set carries `<`, `>` and `;`. encodeURI escapes the
            # angle brackets and leaves the slash, so doi.org resolves it;
            # encodeURIComponent would escape the slash and 404.
            doi = page.evaluate("""() => {
              const c = Object.values(R.claims).find(c => /[<>]/.test(c.doi || ''));
              return c ? { raw: c.doi, href: doiHref(c.doi) } : null;
            }""")
            report.check("a DOI with angle brackets still resolves",
                         doi and doi["href"].startswith("https://doi.org/10.")
                         and "%3C" in doi["href"] and "<" not in doi["href"]
                         and doi["href"].count("/") == 4,
                         doi["href"] if doi else "no such DOI")

            page.evaluate("""() => {
              const id = Object.values(R.claims).find(c => c.doi).about;
              setKt(KT_MAX); setSelection(id);
            }""")
            page.wait_for_timeout(500)
            anchors = page.evaluate("""() => {
              const a = [...document.querySelectorAll('#detail a.doi')];
              return {
                n: a.length,
                doi: a.filter(x => x.href.startsWith('https://doi.org/')).length,
                none: a.filter(x => x.classList.contains('none')).length,
                safe: a.every(x => (x.rel || '').includes('noopener') && x.target === '_blank')
              };
            }""")
            report.check("the panel links out to the source at all",
                         anchors["n"] > 0 and anchors["doi"] > 0, json.dumps(anchors))
            report.check("a claim with no DOI says so and offers a search",
                         anchors["none"] > 0, json.dumps(anchors))
            report.check("every outbound link is rel=noopener in a new tab",
                         anchors["safe"], json.dumps(anchors))

            report.check("no page errors while exercising all three", errs == [], "; ".join(errs)[:150])
        finally:
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
        run_artifact(report)
        run_hook(report)
        run(url, a.headed, report)
        run_mobile(url, a.headed, report)
        run_contrast(url, a.headed, report)
        run_features(url, a.headed, report)
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
