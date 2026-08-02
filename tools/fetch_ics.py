"""Fetch the ICS international chronostratigraphic chart from Macrostrat.

Official ICS colours and current boundary ages for every eon, era, period,
epoch and age. These are the numbers the stratigraphic ribbon is drawn from, so
they come from a machine-readable authority rather than from memory: the 2023+
values (Cambrian base 538.8 Ma, Ordovician base 486.85 Ma) differ from the
figures most people carry around.

Writes assets/ics.json.
"""
import urllib.request, json, collections, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "assets", "ics.json")
UA = {"User-Agent": "Mozilla/5.0"}

# "?all" is required. ?timescale_id=1 is "international ages" on its own and
# returns no eons, eras, periods or epochs at all.
URL = "https://macrostrat.org/api/v2/defs/intervals?all"

# ?all also carries regional and biostratigraphic timescales — Russian Stages,
# conodont zones, New Zealand ages, ammonite zonations. Keep only the
# international chart, or the ribbon fills with units that are not on it.
INTERNATIONAL = {
    "international eons", "international eras", "international periods",
    "international epochs", "international ages",
}
LEVELS = ("eon", "era", "period", "epoch", "age")

rows = json.load(urllib.request.urlopen(
    urllib.request.Request(URL, headers=UA), timeout=60))["success"]["data"]

keep = []
for r in rows:
    names = {t.get("name") for t in (r.get("timescales") or [])}
    if not (names & INTERNATIONAL):
        continue
    if r.get("int_type") not in LEVELS:          # the field is int_type, not type
        continue
    if r.get("b_age") is None or r.get("t_age") is None:
        continue
    keep.append({"n": r["name"], "t": r["int_type"],
                 "b": float(r["b_age"]), "e": float(r["t_age"]), "c": r["color"]})

seen, ded = set(), []
for k in keep:
    key = (k["n"], k["t"])
    if key in seen:
        continue
    seen.add(key)
    ded.append(k)

# Macrostrat's "international eons" omits the Hadean; the printed chart has it.
# The renderer patches this at load time too, so the two must stay in agreement.
if not any(k["n"] == "Hadean" for k in ded):
    ded.append({"n": "Hadean", "t": "eon", "b": 4600.0, "e": 4031.0, "c": "#AE027E"})

order = {lvl: i for i, lvl in enumerate(LEVELS)}
ded.sort(key=lambda x: (order[x["t"]], -x["b"]))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(ded, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))

print(f"kept {len(ded)} intervals  {dict(collections.Counter(k['t'] for k in ded))}")
print(f"wrote {OUT}  {os.path.getsize(OUT):,} bytes")
for name in ("Hadean", "Archean", "Proterozoic", "Phanerozoic", "Cambrian", "Cretaceous"):
    m = [k for k in ded if k["n"] == name]
    if m:
        print(f"  {name:14} {m[0]['b']:>7.1f} - {m[0]['e']:<7.1f} Ma  {m[0]['c']}")
