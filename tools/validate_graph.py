"""Structural validator for the Earth x Time seed graph.

The adversarial verification agents that were meant to fact-check citations did
not complete, so this script does the part that can be checked deterministically:
referential integrity, schema discipline, coordinate sanity, and — importantly —
whether the narrative demos the product promises actually hold in the data.

It does NOT verify that citations are real. That remains an open gap.
"""
import json, sys, os, html, math, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Mirrors KT_MIN/KT_MAX in src/20_core.js. The ceiling is "now", not a
# constant: the record keeps moving, and a claim the rail cannot reach is a
# claim whose status entry can never fire.
KT_MIN, KT_MAX = 1650, 2026

SUBJECTS = {"geology", "biology", "evolution", "chemistry", "human_history", "astronomy"}
STATUSES = {"proposed", "contested", "consensus", "superseded"}
CTYPES = {"existence", "dating", "location", "causal", "interpretation"}
ACCEPT = {"consensus": 3, "contested": 2, "proposed": 1, "superseded": 0}

errors, warns, fixes = [], [], []


def clean(s):
    if not isinstance(s, str):
        return s
    out = html.unescape(s)
    return out.replace("— ", "— ").strip()


def deep_clean(o):
    if isinstance(o, dict):
        return {k: deep_clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [deep_clean(v) for v in o]
    return clean(o)


def load(path):
    obj = json.load(open(path, encoding="utf-8"))
    # Workflow task output wraps the script's return value under "result".
    if "result" in obj and isinstance(obj["result"], dict):
        obj = obj["result"]
    elif "result" in obj and isinstance(obj["result"], str):
        obj = json.loads(obj["result"])
    return obj


def status_at(claim, kt):
    """Status of a claim as understood in year kt; None if not yet asserted."""
    cur = None
    for e in claim["status_timeline"]:
        if e["knowledge_time"] <= kt:
            cur = e["status"]
        else:
            break
    if cur is None and claim["knowledge_time"] <= kt:
        cur = "proposed"
    return cur


def resolve(claims_for_ref, kt, mode):
    live = []
    for c in claims_for_ref:
        st = status_at(c, kt)
        if st is None:
            continue
        live.append((c, st))
    if not live:
        return None
    if mode == "frontier":
        live.sort(key=lambda p: (-p[0]["knowledge_time"], -ACCEPT[p[1]]))
    else:
        live.sort(key=lambda p: (-ACCEPT[p[1]], -p[0]["knowledge_time"]))
    return live[0][0]


ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-"
_AMAP = {c: i for i, c in enumerate(ALPHA)}


def load_land():
    """Decode the shipped coastline into lon/lat rings."""
    path = os.path.join(ROOT, "assets", "coast.txt")
    if not os.path.exists(path):
        return []
    enc = open(path, encoding="utf-8").read().split("===LAND===")[1].split("===PLATES===")[0].strip()
    rings = []
    for part in filter(None, enc.split("|")):
        i = px = py = 0
        ring = []
        while i < len(part):
            vals = []
            for _ in range(2):
                shift = res = 0
                while True:
                    b = _AMAP[part[i]]; i += 1
                    res |= (b & 0x1f) << shift; shift += 5
                    if b < 0x20:
                        break
                vals.append(~(res >> 1) if (res & 1) else (res >> 1))
            px += vals[0]; py += vals[1]
            ring.append((px / 32, py / 32))
        if len(ring) >= 3:
            rings.append(ring)
    return rings


def on_land(lat, lng, rings):
    """
    Even-odd ray cast in lon/lat.

    Distance to the nearest coastline is NOT the test — it is large both for a
    point far out at sea and for one deep inland, so it flags Jack Hills and the
    Burgess Shale exactly as loudly as it flags the mid-Atlantic. What matters is
    whether the point is inside a landmass. Even-odd counting handles lakes for
    free. Unreliable within a degree of the antimeridian and at the poles, so
    callers should treat a bare "not on land" as a warning, not a verdict.
    """
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if abs(x2 - x1) > 180:          # antimeridian wrap: skip the seam edge
                continue
            if (y1 > lat) != (y2 > lat):
                xin = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                if xin > lng:
                    inside = not inside
    return inside


def main():
    # Defaults to the live graph. It used to require a path because it was
    # written to check generated clusters before they were merged; running it on
    # the merged graph is now the common case, and the foundations merge below
    # has to notice they are already there.
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    src = args[0] if args else os.path.join(ROOT, "src", "graph.json")
    obj = deep_clean(load(src))
    g = obj["graph"] if "graph" in obj else obj

    # Merge the hand-authored foundations (Steno -> Kelvin -> Holmes -> Patterson).
    fpath = os.path.join(ROOT, "src", "foundations.json")
    if os.path.exists(fpath):
        f = json.load(open(fpath, encoding="utf-8"))
        have = {c["id"] for c in g["claims"]}
        if not (f.get("claims") and f["claims"][0]["id"] in have):
            g["referents"] += f.get("referents", [])
            g["claims"] += f.get("claims", [])
            g["edges"] += f.get("edges", [])
        print(f"merged foundations.json: +{len(f.get('claims', []))} claims")

    refs, claims, edges = g["referents"], g["claims"], g["edges"]

    # ---- uniqueness -------------------------------------------------------
    # Clusters overlap at the seams — the Mesozoic and Cenozoic authors both
    # declare kpg_extinction, by design, since edges must span them. Identical
    # re-declarations merge; genuine conflicts are an error.
    rid = {}
    deduped = []
    for r in refs:
        prev = rid.get(r["id"])
        if prev:
            if prev["label"] != r["label"] or prev["kind"] != r["kind"]:
                errors.append(f"referent {r['id']} declared twice with different "
                              f"label/kind: {prev} vs {r}")
            else:
                warns.append(f"referent {r['id']} declared by two clusters -> merged")
            continue
        rid[r["id"]] = r
        deduped.append(r)
    refs = deduped
    g["referents"] = refs
    cid = {}
    for c in claims:
        if c["id"] in cid:
            errors.append(f"duplicate claim id {c['id']}")
        cid[c["id"]] = c

    # ---- per-claim schema -------------------------------------------------
    for c in claims:
        w = f"claim {c['id']}"
        if c["about"] not in rid and c["about"] not in cid:
            errors.append(f"{w}: about='{c['about']}' resolves to nothing")
        if c["type"] not in CTYPES:
            errors.append(f"{w}: bad type {c['type']}")
        bad = [s for s in c["subjects"] if s not in SUBJECTS]
        if bad:
            errors.append(f"{w}: unknown subjects {bad}")
        if len(set(c["subjects"])) < 2:
            errors.append(f"{w}: needs >=2 distinct subjects, has {c['subjects']}")
        c["subjects"] = list(dict.fromkeys(c["subjects"]))
        if not (KT_MIN <= c["knowledge_time"] <= KT_MAX):
            errors.append(f"{w}: knowledge_time {c['knowledge_time']} out of [{KT_MIN},{KT_MAX}]")
        if c["earth_time_end"] > c["earth_time_start"]:
            errors.append(f"{w}: earth_time_end older than start "
                          f"({c['earth_time_end']} > {c['earth_time_start']})")
        if c["earth_time_start"] < 0 or c["earth_time_start"] > 4.6e9:
            errors.append(f"{w}: earth_time_start {c['earth_time_start']} out of range")
        if not c["status_timeline"]:
            errors.append(f"{w}: empty status_timeline")
            continue
        kts = [e["knowledge_time"] for e in c["status_timeline"]]
        if kts != sorted(kts):
            warns.append(f"{w}: status_timeline out of order -> sorted")
            c["status_timeline"].sort(key=lambda e: e["knowledge_time"])
            fixes.append(c["id"])
        for e in c["status_timeline"]:
            if e["status"] not in STATUSES:
                errors.append(f"{w}: bad status {e['status']}")
            if not (KT_MIN <= e["knowledge_time"] <= KT_MAX):
                errors.append(f"{w}: timeline kt {e['knowledge_time']} out of range")
        first = c["status_timeline"][0]["knowledge_time"]
        if first != c["knowledge_time"]:
            warns.append(f"{w}: first timeline kt {first} != claim kt {c['knowledge_time']} -> aligned")
            c["knowledge_time"] = first
            fixes.append(c["id"])
        if not c.get("asserted_by") or len(c["asserted_by"]) < 4:
            errors.append(f"{w}: missing asserted_by  << ORPHAN FACT")
        gm = c["geometry"]
        if gm["mode"] in ("point", "region"):
            if gm.get("lat") is None or gm.get("lng") is None:
                errors.append(f"{w}: {gm['mode']} geometry without coordinates")
            else:
                if not (-90 <= gm["lat"] <= 90):
                    errors.append(f"{w}: lat {gm['lat']} out of range")
                if not (-180 <= gm["lng"] <= 180):
                    errors.append(f"{w}: lng {gm['lng']} out of range")
        zb = c.get("zoom_band") or [0, 10]
        if len(zb) != 2 or zb[0] > zb[1]:
            warns.append(f"{w}: bad zoom_band {zb} -> [0,10]")
            c["zoom_band"] = [0, 10]
        c["significance"] = max(1, min(5, int(c.get("significance", 3))))

    # ---- edges ------------------------------------------------------------
    seen_edge = set()
    kept = []
    for e in edges:
        w = f"edge {e['id']}"
        ok = True
        if e["source"] not in rid:
            errors.append(f"{w}: source '{e['source']}' is not a referent"); ok = False
        if e["target"] not in rid:
            # Edges join referents. An edge pointing at a claim is a modelling slip,
            # not a data loss — the claim keeps its own "about" link either way.
            if e["target"] in cid:
                warns.append(f"{w}: target '{e['target']}' is a claim, not a referent -> edge dropped, claim kept")
            else:
                errors.append(f"{w}: target '{e['target']}' is not a referent")
            ok = False
        if e["claim_id"] not in cid:
            errors.append(f"{w}: claim_id '{e['claim_id']}' resolves to nothing "
                          f"<< edge would have no status timeline"); ok = False
        # Two edges between the same pair are NOT duplicates when different claims
        # assert them: Deccan -> K-Pg is asserted in 1972 (superseded) and again in
        # 2014/2015 (contested). Collapsing those would erase the rewiring story.
        key = (e["source"], e["target"], e["type"], e["claim_id"])
        if key in seen_edge:
            warns.append(f"{w}: identical to an existing {e['type']} edge from the same claim -> dropped")
            ok = False
        if ok:
            seen_edge.add(key)
            kept.append(e)
    g["edges"] = kept

    # ---- coordinates must land near real geography ------------------------
    # A fact-checker caught the Carboniferous coal forests at 45N -20E: 1,500 km
    # into the open North Atlantic, and on a globe that is a visible bug. The
    # coastline is 110m simplified at 0.42 degrees, so the coast can be tens of
    # km off; and plenty of real sites are genuinely offshore (Chicxulub's
    # centre, Thera's caldera). Only flag what no simplification explains.
    land = load_land()
    if land:
        wet = []
        for c in claims:
            gm = c["geometry"]
            if gm["mode"] != "point" or gm.get("lat") is None:
                continue
            if not on_land(gm["lat"], gm["lng"], land):
                wet.append(f"{c['id']} ({c['about']}) at {gm['lat']:.2f},{gm['lng']:.2f}")
        if wet:
            warns.append(f"{len(wet)} point coordinate(s) fall in water — verify each is "
                         f"genuinely offshore (a crater centre, a caldera, a drill site) "
                         f"and not a typo: " + "; ".join(wet[:6]))

    # ---- the promised cross-domain chain ----------------------------------
    chain = ["chicxulub_impact", "kpg_extinction", "mammal_radiation",
             "first_primates", "hominins", "homo_sapiens"]
    adj = {(e["source"], e["target"]) for e in kept if e["type"] == "causal"}
    for a, b in zip(chain, chain[1:]):
        if (a, b) not in adj:
            errors.append(f"REQUIRED causal chain link missing: {a} -> {b}")

    # ---- disputed referents must actually render as bands -----------------
    by_ref = collections.defaultdict(list)
    for c in claims:
        if c["type"] in ("dating", "existence") and c["about"] in rid:
            by_ref[c["about"]].append(c)

    must_dispute = ["origin_of_life", "peopling_americas", "snowball_earth",
                    "kpg_extinction", "thera_eruption", "homo_sapiens"]
    for r in must_dispute:
        # Any dated claim competes for the referent's position, not just type=="dating".
        dated = {round(c["earth_time_start"]) for c in by_ref.get(r, [])}
        if len(dated) < 2:
            errors.append(f"{r}: only {len(dated)} distinct date(s) — renders as a dot, not a band")
        else:
            spread = max(dated) - min(dated)
            print(f"    band {r}: {len(dated)} distinct dates, spread {spread:,.0f} yr")

    # ---- resolver modes must visibly disagree somewhere -------------------
    movers = []
    for r, cs in by_ref.items():
        dating = [c for c in cs if c["type"] == "dating"] or cs
        a = resolve(dating, KT_MAX, "consensus")
        b = resolve(dating, KT_MAX, "frontier")
        if a and b and a["id"] != b["id"] and a["earth_time_start"] != b["earth_time_start"]:
            movers.append((r, a["earth_time_start"], b["earth_time_start"]))
    if not movers:
        errors.append("no referent moves between consensus and frontier — required demo #6 fails")

    # ---- knowledge-time rewiring must be observable -----------------------
    def live_causal(kt):
        out = set()
        for e in kept:
            if e["type"] != "causal":
                continue
            c = cid.get(e["claim_id"])
            if c and status_at(c, kt) in ("proposed", "contested", "consensus"):
                out.add((e["source"], e["target"]))
        return out

    l1975, l1985, l1995, l2025 = (live_causal(y) for y in (1975, 1985, 1995, KT_MAX))
    if ("chicxulub_impact", "kpg_extinction") in l1975:
        errors.append("Chicxulub->K-Pg is already live in 1975 — the rewiring demo is broken")
    if ("chicxulub_impact", "kpg_extinction") not in l1985:
        errors.append("Chicxulub->K-Pg is not live by 1985 — the rewiring demo is broken")
    died = l1975 - l2025
    born = l2025 - l1975
    if not died:
        warns.append("no causal edge dies between 1975 and 2025 — superseded links are invisible")

    # ---- report -----------------------------------------------------------
    print(f"referents {len(refs)}   claims {len(claims)}   edges {len(kept)}")
    print(f"claims about other claims: {sum(1 for c in claims if c['about'] in cid)}")
    print(f"geometry: " + str(collections.Counter(c['geometry']['mode'] for c in claims)))
    print(f"types:    " + str(collections.Counter(c['type'] for c in claims)))
    print(f"subjects: " + str(collections.Counter(s for c in claims for s in c['subjects'])))
    kt = [c["knowledge_time"] for c in claims]
    print(f"knowledge_time span {min(kt)}–{max(kt)}")
    print(f"resolver movers (consensus vs frontier): {len(movers)}")
    for m in movers[:8]:
        print(f"    {m[0]}: {m[1]:,.0f} -> {m[2]:,.0f} ybp")
    print(f"causal edges live in 1975: {len(l1975)}  1985: {len(l1985)}  "
          f"1995: {len(l1995)}  2025: {len(l2025)}")
    print(f"  died 1975->2025: {sorted(died)}")
    print(f"  born 1975->2025: {len(born)}")

    print(f"\nWARNINGS ({len(warns)})")
    for w in warns:
        print("  ~", w)
    print(f"\nERRORS ({len(errors)})")
    for e in errors:
        print("  !", e)

    out = os.path.join(ROOT, "src", "graph.json")
    json.dump(g, open(out, "w", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
    print(f"\nwrote {out}  ({os.path.getsize(out):,} bytes)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
