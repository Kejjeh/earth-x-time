"""
Apply an authored patch to src/graph.json.

    python tools/apply_patch.py patch.json            # dry run, prints the plan
    python tools/apply_patch.py patch.json --write

The patch is the object the .claude/workflows/author-causal-edges.js workflow
returns: new referents, new claims, new edges, and removals. This script is the
gate between an agent's output and the dataset - it refuses anything that would
leave the graph inconsistent, rather than trusting that the author and the
adversarial checker between them got it right.

Refuses, specifically:
  * an id that already exists, or that two parts of the patch both claim
  * an edge whose source or target resolves to nothing
  * a new referent with no dated claim - resolve() returns null for it and the
    thing is invisible, which is worse than absent because it looks like a bug
  * a claim about a referent that does not exist
  * a status_timeline out of order, or starting before the claim was made
  * a subject outside the six, or fewer than two of them
  * a removal naming an edge that is not there
Then hands off to tools/validate_graph.py, which re-checks the whole graph.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from knowledge_time import KT_MIN, KT_MAX  # noqa: E402
GRAPH = os.path.join(ROOT, "src", "graph.json")

SUBJECTS = {"geology", "biology", "evolution", "chemistry", "human_history", "astronomy"}
STATUSES = {"proposed", "contested", "consensus", "superseded"}
CTYPES = {"existence", "dating", "location", "causal", "interpretation"}

errors, notes = [], []


def err(m):
    errors.append(m)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    patch = json.load(open(sys.argv[1], encoding="utf-8"))
    # A workflow result arrives wrapped; unwrap whichever layer it came in.
    for key in ("result", "patch"):
        if isinstance(patch, dict) and key in patch and isinstance(patch[key], dict):
            patch = patch[key]
    graph = json.load(open(GRAPH, encoding="utf-8"))

    ref_ids = {r["id"] for r in graph["referents"]}
    claim_ids = {c["id"] for c in graph["claims"]}
    edge_ids = {e["id"] for e in graph["edges"]}

    new_refs = patch.get("new_referents", [])
    new_claims = patch.get("new_claims", [])
    new_edges = patch.get("edges", [])
    removals = patch.get("removals", [])

    # ------------------------------------------------------------- collisions
    seen = set()
    for r in new_refs:
        if r["id"] in ref_ids:
            err(f"referent {r['id']} already exists")
        if r["id"] in seen:
            err(f"referent {r['id']} appears twice in the patch")
        seen.add(r["id"])
    for c in new_claims:
        if c["id"] in claim_ids:
            err(f"claim {c['id']} already exists")
        if c["id"] in seen:
            err(f"claim id {c['id']} appears twice in the patch")
        seen.add(c["id"])
    for e in new_edges:
        if e["id"] in edge_ids:
            err(f"edge {e['id']} already exists")
        if e["id"] in seen:
            err(f"edge id {e['id']} appears twice in the patch")
        seen.add(e["id"])

    all_refs = ref_ids | {r["id"] for r in new_refs}
    all_claims = claim_ids | {c["id"] for c in new_claims}

    # ----------------------------------------------------------------- claims
    dated_for = {}
    for c in new_claims:
        if c.get("about") not in all_refs:
            err(f"claim {c['id']} is about {c.get('about')!r}, which does not exist")
        if c.get("type") not in CTYPES:
            err(f"claim {c['id']} has type {c.get('type')!r}")
        subs = c.get("subjects") or []
        if len(subs) < 2 or set(subs) - SUBJECTS:
            err(f"claim {c['id']} subjects {subs!r}")
        ts = c.get("earth_time_start")
        te = c.get("earth_time_end")
        if not isinstance(ts, (int, float)) or ts < 0 or ts > 4.6e9:
            err(f"claim {c['id']} earth_time_start {ts!r} is not a sane years-before-present")
        if isinstance(ts, (int, float)) and isinstance(te, (int, float)) and te > ts:
            err(f"claim {c['id']} ends ({te}) before it starts ({ts}) in years-before-present")
        # knowledge_time was read but never checked: a missing one made `k < kt`
        # raise TypeError and killed the run with a traceback carrying no claim
        # id, and a knowledge_time of 3024 passed cleanly - a claim no position
        # of the rail can ever reach, which is the same "invisible, so it looks
        # like a bug" this script already refuses for referents.
        kt = c.get("knowledge_time")
        if not isinstance(kt, (int, float)):
            err(f"claim {c['id']} has no knowledge_time")
            kt = None
        elif not (KT_MIN <= kt <= KT_MAX):
            err(f"claim {c['id']} knowledge_time {kt} is outside the rail "
                f"[{KT_MIN},{KT_MAX}] — it could never be reached")
        tl = c.get("status_timeline") or []
        if not tl:
            err(f"claim {c['id']} has no status_timeline")
        last = -1e9
        for s in tl:
            if s.get("status") not in STATUSES:
                err(f"claim {c['id']} status {s.get('status')!r}")
            k = s.get("knowledge_time")
            if not isinstance(k, (int, float)):
                err(f"claim {c['id']} timeline entry has no knowledge_time")
                continue
            if kt is not None and k < kt:
                err(f"claim {c['id']} timeline starts at {k}, before the claim was made ({kt})")
            if k < last:
                err(f"claim {c['id']} timeline is out of order at {k}")
            last = k
            if not (s.get("source") or "").strip():
                err(f"claim {c['id']} timeline entry {k} has no source")
        if isinstance(ts, (int, float)):
            dated_for.setdefault(c["about"], []).append(c["id"])

    # A referent with no dated claim never resolves, so it never draws.
    existing_dated = set()
    for c in graph["claims"]:
        if isinstance(c.get("earth_time_start"), (int, float)):
            existing_dated.add(c.get("about"))
    for r in new_refs:
        if r["id"] not in dated_for and r["id"] not in existing_dated:
            err(f"new referent {r['id']} has no dated claim - resolve() returns null "
                f"and it will never appear on screen")
        if r.get("kind") not in ("event", "entity"):
            err(f"new referent {r['id']} kind {r.get('kind')!r}")

    # ------------------------------------------------------------------ edges
    for e in new_edges:
        for end in ("source", "target"):
            if e.get(end) not in all_refs:
                err(f"edge {e['id']} {end} {e.get(end)!r} does not resolve")
        if e.get("type") not in ("causal", "part_of"):
            err(f"edge {e['id']} type {e.get('type')!r}")
        if e.get("claim_id") not in all_claims:
            err(f"edge {e['id']} cites claim {e.get('claim_id')!r}, which does not exist")
        if e.get("source") == e.get("target"):
            err(f"edge {e['id']} points at itself")
        dup = [x for x in graph["edges"] if x["source"] == e.get("source")
               and x["target"] == e.get("target") and x["claim_id"] == e.get("claim_id")]
        if dup:
            err(f"edge {e['id']} duplicates existing {dup[0]['id']}")

    for r in removals:
        if r["edge_id"] not in edge_ids:
            err(f"removal names edge {r['edge_id']}, which is not in the graph")

    if errors:
        print(f"{len(errors)} problems; nothing written:\n")
        for m in errors:
            print("  " + m)
        return 1

    # ------------------------------------------------------------------ apply
    kill = {r["edge_id"] for r in removals}
    graph["referents"].extend(new_refs)
    graph["claims"].extend(new_claims)
    graph["edges"] = [e for e in graph["edges"] if e["id"] not in kill] + new_edges

    print(f"+{len(new_refs)} referents  +{len(new_claims)} claims  "
          f"+{len(new_edges)} edges  -{len(kill)} edges")
    for r in new_refs:
        print(f"  referent  {r['id']:<28} {r['label']}")
    for e in new_edges:
        print(f"  {e['type']:<8}  {e['source']} -> {e['target']}   {e.get('label','')}")
    for r in removals:
        print(f"  REMOVE    {r['edge_id']}   {r['why']}")
    for d in patch.get("dropped", []):
        print(f"  dropped   {d['what']}: {d['why']}")

    if "--write" not in sys.argv:
        print("\n(dry run; pass --write to apply)")
        return 0

    json.dump(graph, open(GRAPH, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"\nwrote {GRAPH}: {len(graph['referents'])} referents, "
          f"{len(graph['claims'])} claims, {len(graph['edges'])} edges")

    r = subprocess.run([sys.executable, os.path.join(HERE, "validate_graph.py")],
                       capture_output=True, text=True)
    print("\n--- validate_graph.py ---")
    print(r.stdout[-4000:])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
