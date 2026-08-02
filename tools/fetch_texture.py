"""Fetch NASA Blue Marble and inline it as a base64 equirectangular texture.

Public domain (NASA Earth Observatory, "Land Shallow Topo"). Downscaled and
JPEG-compressed until it is small enough to embed, because the page must carry
everything it needs and fetch nothing.

Writes assets/earth.txt as a bare base64 JPEG payload.
"""
import urllib.request, base64, io, os, sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "assets", "earth.txt")
SRC = "https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57752/land_shallow_topo_2048.jpg"
UA = {"User-Agent": "Mozilla/5.0"}

raw = urllib.request.urlopen(urllib.request.Request(SRC, headers=UA), timeout=90).read()
img = Image.open(io.BytesIO(raw)).convert("RGB")
print(f"source {img.size[0]}x{img.size[1]}  {len(raw):,} bytes")

# The globe is ~600px across at its usual size, spanning 180 degrees of
# longitude, so roughly 3.3 px/degree. A 1280-wide texture gives 3.5 px/degree —
# matched to the display, with a little headroom for zooming in.
best = None
for w in (1024, 1280, 1536):
    for q in (72, 78, 84):
        im = img.resize((w, w // 2), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True, progressive=False)
        n = len(buf.getvalue())
        b64 = (n * 4 + 2) // 3
        flag = ""
        if b64 < 125_000 and (best is None or n > best[0]):
            best = (n, w, q, buf.getvalue()); flag = "  <- best so far"
        print(f"  {w}x{w//2} q{q}: {n:>7,} bytes  ({b64:>7,} base64){flag}")

if not best:
    sys.exit("nothing fit the budget")
n, w, q, data = best
b64 = base64.b64encode(data).decode()
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write(b64)
print(f"\nchose {w}x{w//2} q{q} -> {n:,} bytes raw, {len(b64):,} base64")
print(f"wrote {OUT}")
