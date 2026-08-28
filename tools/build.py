"""Assemble the single-file app.

Concatenates src/ in order and injects the bulky assets (fonts, coastlines,
timescale, seed graph) so none of them have to be pasted by hand.

Emits two files with identical content:
  earth-x-time.html   full standalone document, for opening off disk
  artifact.html       body-only, for a host that supplies its own <head>
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
ASSETS = os.path.join(ROOT, "assets")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


# Elements that belong to a <head>. The artifact host supplies its own, so these
# must not travel into the body it wraps, and "harmless if they do" is wrong:
# Chromium honours a <base> wherever it sits, so a leaked one silently repoints
# every relative URL on the host page, and a leaked <link rel="icon"> lands in
# the DOM beside the host's own favicon.
HEAD_ONLY = ("meta", "link", "base")

# One token of the head prelude: a comment, a whole <title>...</title>, any other
# tag, or the run of text between them. Anything that does not tokenise is a
# shape this does not know, and is refused rather than guessed at.
_PRELUDE_TOKEN = re.compile(
    r"(?P<comment><!--.*?-->)"
    r"|(?P<title><title\b[^>]*>.*?</title\s*>)"
    r"|<(?P<name>[A-Za-z][\w:-]*)\b[^>]*>"
    r"|(?P<text>[^<]+)",
    re.S | re.I)


def artifact_head(head, where="src/00_head.html"):
    """The <head> content, minus the parts the artifact host supplies itself.

    Keeps <title>, which the publisher reads, and the inlined <style>.

    This used to be `re.sub(r'^<meta [^>]*/>\n', ...)`, which recognised the two
    tags this file happened to have, spelled the way it happened to spell them.
    Five other shapes went straight into the body: a <meta> without the trailing
    slash, an indented one, an uppercase one, a <link>, a <base>.

    Teaching the pattern those five shapes would fail the same way at the sixth,
    so this refuses what it does not recognise instead of passing it through. A
    build that stops is a bad minute; a <base> loose in someone else's page is
    not something they would think to look for.
    """
    cut = re.search(r"<style\b", head, re.I)
    if not cut:
        sys.exit(f"FATAL: no <style> in {where}; the artifact build splits the head "
                 "there and no longer knows where the prelude ends.")
    prelude, styles = head[:cut.start()], head[cut.start():]

    kept, pos = [], 0
    for m in _PRELUDE_TOKEN.finditer(prelude):
        if m.start() != pos:
            sys.exit(f"FATAL: cannot parse the head prelude of {where} at character "
                     f"{pos}: {prelude[pos:pos + 70]!r}")
        pos = m.end()
        if m.group("comment"):
            continue
        if m.group("title"):
            kept.append(m.group(0).strip())
            continue
        if m.group("text") is not None:
            if m.group("text").strip():
                sys.exit(f"FATAL: stray text in the head prelude of {where}: "
                         f"{m.group('text').strip()[:70]!r}")
            continue
        name = m.group("name").lower()
        if name in HEAD_ONLY:
            continue
        sys.exit(f"FATAL: unrecognised <{name}> in the head prelude of {where}. The "
                 f"artifact build keeps <title> and the inlined <style> and drops "
                 f"{'/'.join(HEAD_ONLY)}; decide what artifact_head() should do with "
                 f"<{name}> rather than letting it into the body by default.")
    if pos != len(prelude):
        sys.exit(f"FATAL: cannot parse the head prelude of {where} at character "
                 f"{pos}: {prelude[pos:pos + 70]!r}")

    if not kept:
        sys.exit(f"FATAL: no <title> survived the head prelude of {where}; the "
                 "artifact publisher reads it to name the page.")
    return "\n".join(kept) + "\n" + styles


def main():
    head = read(os.path.join(SRC, "00_head.html"))
    body = read(os.path.join(SRC, "10_body.html"))
    js = "\n".join(read(os.path.join(SRC, n)) for n in sorted(os.listdir(SRC))
                   if re.match(r"^\d\d_.*\.js$", n))

    fonts = read(os.path.join(ASSETS, "fonts.css"))
    coast = read(os.path.join(ASSETS, "coast.txt"))
    land = coast.split("===LAND===")[1].split("===PLATES===")[0].strip()
    plates = coast.split("===PLATES===")[1].strip()

    earth = read(os.path.join(ASSETS, "earth.txt")).strip()
    ics = json.load(open(os.path.join(ASSETS, "ics.json"), encoding="utf-8"))
    graph = json.load(open(os.path.join(SRC, "graph.json"), encoding="utf-8"))

    # The encoding alphabet excludes quote, backslash and angle brackets, so the
    # payloads drop into a JS string literal untouched. Assert it rather than hope.
    for name, blob in (("land", land), ("plates", plates)):
        bad = set(blob) - set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-|")
        if bad:
            sys.exit(f"FATAL: {name} payload contains unsafe characters: {sorted(bad)!r}")

    head = head.replace("/*@FONTS@*/", fonts)
    js = js.replace("/*@LAND@*/", land)
    js = js.replace("/*@PLATES@*/", plates)
    js = js.replace("/*@EARTH@*/", earth)
    js = js.replace("/*@ICS@*/", json.dumps(ics, separators=(",", ":")))
    js = js.replace("/*@GRAPH@*/", json.dumps(graph, separators=(",", ":"), ensure_ascii=False))

    # Nothing may reach the browser with a placeholder still in it.
    inner = head + "\n" + body + '\n<script>\n' + js + '\n</script>\n'
    left = re.findall(r"/\*@[A-Z]+@\*/", inner)
    if left:
        sys.exit(f"FATAL: unsubstituted placeholders remain: {set(left)}")
    if "</script>" in js.replace("</script>", "", 0)[:0]:
        pass
    if re.search(r"</script", js, re.I):
        sys.exit("FATAL: a literal </script> inside the JS payload would close the tag early")

    art_head = artifact_head(head)
    # Belt and braces over the markup, and only the markup: the JS payload below
    # is prose as much as code, and its comments discuss <html> and <body> in
    # English. Widening this to the whole file would fail on a sentence.
    stray = re.search(r"<\s*(meta|link|base)\b", art_head + body, re.I)
    if stray:
        sys.exit(f"FATAL: a head-only <{stray.group(1)}> reached artifact.html: "
                 f"{(art_head + body)[stray.start():stray.start() + 70]!r}")
    art = art_head + "\n" + body + '\n<script>\n' + js + '\n</script>\n'
    out_art = os.path.join(ROOT, "artifact.html")
    with open(out_art, "w", encoding="utf-8") as f:
        f.write(art)

    out_std = os.path.join(ROOT, "earth-x-time.html")
    with open(out_std, "w", encoding="utf-8") as f:
        f.write('<!doctype html>\n<html lang="en">\n<head>\n' + head +
                '\n</head>\n<body>\n' + body +
                '\n<script>\n' + js + '\n</script>\n</body>\n</html>\n')

    # GitHub Pages serves index.html from the repo root.
    out_idx = os.path.join(ROOT, "index.html")
    with open(out_idx, "w", encoding="utf-8") as f:
        f.write(open(out_std, encoding="utf-8").read())

    print(f"claims {len(graph['claims'])}  referents {len(graph['referents'])}  edges {len(graph['edges'])}")
    print(f"ics intervals {len(ics)}")
    print(f"land {len(land):,} chars   plates {len(plates):,} chars   earth {len(earth):,} chars")
    print(f"fonts {len(fonts):,} chars")
    print(f"js {len(js):,} chars")
    for p in (out_std, out_art, out_idx):
        print(f"  {os.path.basename(p):22} {os.path.getsize(p):,} bytes")

    if "--no-smoke" not in sys.argv:
        smoke()


def smoke():
    """Open the thing we just built in a real browser and prove it runs.

    Not optional politeness. A build that emits a well-formed 637 KB document
    whose boot() throws on line 3 is indistinguishable from a good one by every
    check upstream of here - that is not hypothetical, it is what happened.
    """
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("\n(skipping smoke test: pip install playwright && playwright install chromium)")
        return
    print("\nsmoke test")
    r = subprocess.run([sys.executable, os.path.join(HERE, "smoke_test.py")],
                       capture_output=True, text=True)
    tail = [l for l in r.stdout.splitlines() if "FAIL" in l or "checks passed" in l]
    print("\n".join("  " + l.strip() for l in tail) or r.stdout[-800:])
    if r.returncode:
        sys.exit("FATAL: the built page does not work - see above")


if __name__ == "__main__":
    main()
