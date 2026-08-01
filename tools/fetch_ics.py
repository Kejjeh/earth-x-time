import urllib.request, json, os
SP = os.path.dirname(os.path.abspath(__file__))
url = "https://macrostrat.org/api/v2/defs/intervals?timescale_id=1"
req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
d = json.load(urllib.request.urlopen(req, timeout=45))
rows = d["success"]["data"]
print("intervals:", len(rows))
levels = {}
for r in rows:
    levels.setdefault(r.get("type"), 0)
    levels[r["type"]] += 1
print("by type:", levels)
keep = []
for r in rows:
    t = r.get("type")
    if t not in ("eon","era","period","epoch","age"): continue
    keep.append({
        "n": r["name"], "t": t,
        "b": float(r["b_age"]), "e": float(r["t_age"]),
        "c": r["color"],
    })
keep.sort(key=lambda x: (-x["b"], x["t"]))
out = os.path.join(SP, "ics_out.json")
with open(out,"w",encoding="utf-8") as f:
    json.dump(keep, f, separators=(",",":"))
print("kept", len(keep), "->", out, os.path.getsize(out), "bytes")
print("sample:", json.dumps(keep[:2]), "...", json.dumps([k for k in keep if k["n"] in ("Cretaceous","Cambrian","Holocene","Ediacaran","Hadean")]))
