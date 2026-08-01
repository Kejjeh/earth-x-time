import urllib.request, re, base64, os, json
SP = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}

FACES = [
    ("IBM Plex Sans", "IBM+Plex+Sans:wght@400", "xt-sans", 400),
    ("IBM Plex Sans", "IBM+Plex+Sans:wght@600", "xt-sans", 600),
    ("IBM Plex Sans Condensed", "IBM+Plex+Sans+Condensed:wght@600", "xt-cond", 600),
    ("IBM Plex Mono", "IBM+Plex+Mono:wght@400", "xt-mono", 400),
    ("IBM Plex Mono", "IBM+Plex+Mono:wght@600", "xt-mono", 600),
]

out = []
total = 0
for fam, spec, alias, wt in FACES:
    css_url = f"https://fonts.googleapis.com/css2?family={spec}&display=swap"
    css = urllib.request.urlopen(urllib.request.Request(css_url, headers=UA), timeout=30).read().decode()
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
        print("MISS", fam, wt); continue
    data = urllib.request.urlopen(urllib.request.Request(picked, headers=UA), timeout=30).read()
    total += len(data)
    b64 = base64.b64encode(data).decode()
    out.append(f"@font-face{{font-family:'{alias}';font-style:normal;font-weight:{wt};font-display:block;src:url(data:font/woff2;base64,{b64}) format('woff2');}}")
    print(f"{fam} {wt} -> {len(data)} bytes raw, {len(b64)} b64")

path = os.path.join(SP, "fonts_out.css")
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("TOTAL raw", total, "css file", os.path.getsize(path))
