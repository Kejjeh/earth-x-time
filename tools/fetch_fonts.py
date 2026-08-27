"""Fetch the five IBM Plex faces, latin subset, inlined as data URIs.

Writes assets/fonts.css - which is what tools/build.py reads. It used to write
tools/fonts_out.css, a file nothing has ever read, so regenerating the fonts
printed its byte counts, exited 0, and changed nothing about the built page.
"""
import urllib.request, re, base64, os, json, sys
SP = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(SP), "assets", "fonts.css")
UA = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}

FACES = [
    ("IBM Plex Sans", "IBM+Plex+Sans:wght@400", "xt-sans", 400),
    ("IBM Plex Sans", "IBM+Plex+Sans:wght@600", "xt-sans", 600),
    ("IBM Plex Sans Condensed", "IBM+Plex+Sans+Condensed:wght@600", "xt-cond", 600),
    ("IBM Plex Mono", "IBM+Plex+Mono:wght@400", "xt-mono", 400),
    ("IBM Plex Mono", "IBM+Plex+Mono:wght@600", "xt-mono", 600),
]

out = []
missing = []
total = 0
for fam, spec, alias, wt in FACES:
    css_url = f"https://fonts.googleapis.com/css2?family={spec}&display=swap"
    # A network failure used to kill the run with a traceback. It is a reason a
    # face is missing, like any other; collect it and let the guard at the end
    # report all of them at once.
    try:
        css = urllib.request.urlopen(urllib.request.Request(css_url, headers=UA), timeout=30).read().decode()
    except Exception as e:                            # noqa: BLE001
        print(f"SKIP {fam} {wt}: {e}")
        missing.append(f"{fam} {wt}")
        continue
    blocks = css.split("@font-face")
    picked = None
    for b in blocks:
        if "U+0000-00FF" in b or ("latin" in b and "ext" not in b):
            m = re.search(r"url\((https://[^)]+\.woff2)\)", b)
            if m: picked = m.group(1); break
    if not picked:
        m = re.search(r"url\((https://[^)]+\.woff2)\)", css)
        picked = m.group(1) if m else None
    if not picked:
        missing.append(f"{fam} {wt}")
        continue
    try:
        data = urllib.request.urlopen(urllib.request.Request(picked, headers=UA), timeout=30).read()
    except Exception as e:                            # noqa: BLE001
        print(f"SKIP {fam} {wt}: {e}")
        missing.append(f"{fam} {wt}")
        continue
    total += len(data)
    b64 = base64.b64encode(data).decode()
    out.append(f"@font-face{{font-family:'{alias}';font-style:normal;font-weight:{wt};font-display:block;src:url(data:font/woff2;base64,{b64}) format('woff2');}}")
    print(f"{fam} {wt} -> {len(data)} bytes raw, {len(b64)} b64")

# A face that did not resolve used to be skipped and the rest written anyway.
# Now that this file is the one the build reads, that would ship a stylesheet
# missing a weight the page uses, and the fallback stack would quietly stand in
# for it. All five or none.
if missing or len(out) != len(FACES):
    sys.exit(f"FATAL: {len(out)}/{len(FACES)} faces resolved"
             + (f" (missing {', '.join(missing)})" if missing else "")
             + f"; {OUT} left untouched")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("TOTAL raw", total, "css file", os.path.getsize(OUT))
print("wrote", OUT)
