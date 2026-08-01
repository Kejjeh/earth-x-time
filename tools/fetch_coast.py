import urllib.request, json, math, os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coast_out.txt")
ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-"
SCALE = 32.0  # 1/32 degree ~ 3.5 km

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return json.load(urllib.request.urlopen(req, timeout=45))

def perp(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx-ax, by-ay
    if dx == 0 and dy == 0:
        return math.hypot(px-ax, py-ay)
    t = max(0, min(1, ((px-ax)*dx + (py-ay)*dy)/(dx*dx+dy*dy)))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

def dp(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False]*len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts)-1)]
    while stack:
        i, j = stack.pop()
        if j <= i+1: continue
        best, bi = -1, -1
        for k in range(i+1, j):
            d = perp(pts[k], pts[i], pts[j])
            if d > best: best, bi = d, k
        if best > tol:
            keep[bi] = True
            stack.append((i, bi)); stack.append((bi, j))
    return [p for p, k in zip(pts, keep) if k]

def ring_area(pts):
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]; x2, y2 = pts[(i+1) % len(pts)]
        s += x1*y2 - x2*y1
    return abs(s)/2.0

def collect(geom, out):
    t = geom["type"]; c = geom["coordinates"]
    if t == "Polygon": polys = [c]
    elif t == "MultiPolygon": polys = c
    elif t == "LineString": out.append([tuple(p[:2]) for p in c]); return
    elif t == "MultiLineString":
        for l in c: out.append([tuple(p[:2]) for p in l])
        return
    else: return
    for poly in polys:
        for ring in poly:
            out.append([tuple(p[:2]) for p in ring])

def encode_signed(n, buf):
    # Zigzag: ~(n << 1) for negatives, NOT (~n) << 1. The latter maps -5 to +4,
    # so every westward/southward step reverses and the ring walks off the globe.
    v = ~(n << 1) if n < 0 else (n << 1)
    while v >= 0x20:
        buf.append(ALPHA[(0x20 | (v & 0x1f))])
        v >>= 5
    buf.append(ALPHA[v])

def encode_rings(rings):
    parts = []
    for r in rings:
        buf = []
        px = py = 0
        for lon, lat in r:
            x = int(round(lon*SCALE)); y = int(round(lat*SCALE))
            encode_signed(x-px, buf); encode_signed(y-py, buf)
            px, py = x, y
        parts.append("".join(buf))
    return "|".join(parts)

def build(url, tol, min_area, label):
    try:
        gj = fetch(url)
    except Exception as e:
        print(f"SKIP {label}: {e}")
        return None
    rings = []
    for f in gj["features"]:
        g = f.get("geometry")
        if g: collect(g, rings)
    simplified = []
    for r in rings:
        if len(r) > 3 and ring_area(r) < min_area:
            continue
        s = dp(r, tol)
        if len(s) >= 3 or (len(s) >= 2 and min_area == 0):
            simplified.append(s)
    enc = encode_rings(simplified)
    pts = sum(len(s) for s in simplified)
    print(f"{label}: {len(simplified)} rings, {pts} pts, {len(enc)} chars")
    return enc

land = build("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson", 0.42, 1.1, "land")
plates = build("https://raw.githubusercontent.com/fraxen/tectonicplates/master/GeoJSON/PB2002_boundaries.json", 0.9, 0, "plates")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("===LAND===\n" + (land or "") + "\n===PLATES===\n" + (plates or "") + "\n")
print("wrote", OUT)
