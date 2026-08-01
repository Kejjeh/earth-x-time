"""Assemble the single-file app.

Concatenates src/ in order and injects the bulky assets (fonts, coastlines,
timescale, seed graph) so none of them have to be pasted by hand.

Emits two files with identical content:
  earth-x-time.html   full standalone document, for opening off disk
  artifact.html       body-only, for a host that supplies its own <head>
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
ASSETS = os.path.join(ROOT, "assets")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def main():
    head = read(os.path.join(SRC, "00_head.html"))
    body = read(os.path.join(SRC, "10_body.html"))
    js = "\n".join(read(os.path.join(SRC, n)) for n in sorted(os.listdir(SRC))
                   if re.match(r"^\d\d_.*\.js$", n))

    fonts = read(os.path.join(ASSETS, "fonts.css"))
    coast = read(os.path.join(ASSETS, "coast.txt"))
    land = coast.split("===LAND===")[1].split("===PLATES===")[0].strip()
    plates = coast.split("===PLATES===")[1].strip()

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

    # The artifact host supplies its own <head>, so drop our meta tags there and
    # keep only <title> (which the publisher reads) plus the inlined styles.
    art = re.sub(r'^<meta [^>]*/>\n', '', head, flags=re.M) + "\n" + body + \
        '\n<script>\n' + js + '\n</script>\n'
    out_art = os.path.join(ROOT, "artifact.html")
    with open(out_art, "w", encoding="utf-8") as f:
        f.write(art)

    out_std = os.path.join(ROOT, "earth-x-time.html")
    with open(out_std, "w", encoding="utf-8") as f:
        f.write('<!doctype html>\n<html lang="en">\n<head>\n' + head +
                '\n</head>\n<body>\n' + body +
                '\n<script>\n' + js + '\n</script>\n</body>\n</html>\n')

    print(f"claims {len(graph['claims'])}  referents {len(graph['referents'])}  edges {len(graph['edges'])}")
    print(f"ics intervals {len(ics)}")
    print(f"land {len(land):,} chars   plates {len(plates):,} chars")
    print(f"fonts {len(fonts):,} chars")
    print(f"js {len(js):,} chars")
    for p in (out_std, out_art):
        print(f"  {os.path.basename(p):22} {os.path.getsize(p):,} bytes")


if __name__ == "__main__":
    main()
