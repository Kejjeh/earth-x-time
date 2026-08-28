"""
Merge stage-4 authored claims into the graph.

    python tools/stage4_merge.py <workflow-output.json>           # dry run
    python tools/stage4_merge.py <workflow-output.json> --write

Takes the output of the author-status workflow, checks each claim against the
per-claim rules tools/validate_graph.py enforces, attaches the referents that
tools/ingest.py resolved (with their Wikidata QIDs), and writes src/graph.json.

Refuses to merge anything that would violate the schema, and reports what it
rejected rather than quietly dropping it.

It is a per-CLAIM check only: referential integrity across the whole graph, the
narrative gates, and the coordinate triage all live in tools/validate_graph.py,
which is why that is the next step and not build.py. Claiming more than this is
what let significance "high", zoom_band [10,0] and a negative time_precision
merge clean.
"""
import json, os, sys, argparse, collections, html


def unescape(o):
    """Agent output arrives HTML-escaped: 'Alvarez &amp; Asaro', DOIs with &lt;."""
    if isinstance(o, dict):
        return {k: unescape(v) for k, v in o.items()}
    if isinstance(o, list):
        return [unescape(v) for v in o]
    return html.unescape(o) if isinstance(o, str) else o

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from knowledge_time import KT_MIN, KT_MAX  # noqa: E402
SUBJECTS = {"geology", "biology", "evolution", "chemistry", "human_history", "astronomy"}
STATUSES = {"proposed", "contested", "consensus", "superseded"}
TYPES = {"existence", "dating", "location", "causal", "interpretation"}
REQUIRED = ["id", "about", "statement", "type", "earth_time_start", "earth_time_end",
            "time_precision", "geometry", "coords_are_modern", "subjects", "zoom_band",
            "significance", "asserted_by", "knowledge_time", "status_timeline"]


def load_workflow(path):
    o = json.load(open(path, encoding="utf-8"))
    if "result" in o and isinstance(o["result"], dict):
        o = o["result"]
    elif "result" in o and isinstance(o["result"], str):
        o = json.loads(o["result"])
    return o


def check(c, known_referents):
    """Every reason this claim cannot be merged."""
    bad = []
    for f in REQUIRED:
        if f not in c:
            bad.append(f"missing {f}")
    if bad:
        return bad
    if c["type"] not in TYPES:
        bad.append(f"bad type {c['type']}")
    if c["about"] not in known_referents:
        bad.append(f"about='{c['about']}' is not a known referent")
    if len(set(c["subjects"])) < 2:
        bad.append(f"needs >=2 subjects, has {c['subjects']}")
    if set(c["subjects"]) - SUBJECTS:
        bad.append(f"unknown subjects {sorted(set(c['subjects']) - SUBJECTS)}")
    if not (KT_MIN <= c["knowledge_time"] <= KT_MAX):
        bad.append(f"knowledge_time {c['knowledge_time']} out of "
                   f"[{KT_MIN},{KT_MAX}]")
    if c["earth_time_end"] > c["earth_time_start"]:
        bad.append("earth_time_end is older than earth_time_start")
    if not (0 <= c["earth_time_start"] <= 4.6e9):
        bad.append(f"earth_time_start {c['earth_time_start']} out of range")
    if not c.get("asserted_by") or len(c["asserted_by"]) < 4:
        bad.append("no asserted_by << ORPHAN FACT")
    st = c.get("status_timeline") or []
    if not st:
        bad.append("empty status_timeline")
    else:
        if [e["knowledge_time"] for e in st] != sorted(e["knowledge_time"] for e in st):
            bad.append("status_timeline out of order")
        if st[0]["knowledge_time"] != c["knowledge_time"]:
            bad.append(f"first timeline entry {st[0]['knowledge_time']} != "
                       f"claim knowledge_time {c['knowledge_time']}")
        for e in st:
            if e["status"] not in STATUSES:
                bad.append(f"bad status {e['status']}")
    # REQUIRED lists these three, and nothing validated their values, so a
    # claim carrying significance "high", zoom_band [10,0] or a negative
    # time_precision merged clean - against a docstring promising the same rules
    # validate_graph.py enforces.
    sig = c.get("significance")
    if isinstance(sig, bool) or not isinstance(sig, (int, float)):
        bad.append(f"significance {sig!r} is not a number")
    elif not (1 <= sig <= 5):
        bad.append(f"significance {sig} outside 1-5")
    zb = c.get("zoom_band")
    if (not isinstance(zb, list) or len(zb) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in zb)
            or zb[0] > zb[1]):
        bad.append(f"bad zoom_band {zb!r}")
    tp = c.get("time_precision")
    if isinstance(tp, bool) or not isinstance(tp, (int, float)):
        bad.append(f"time_precision {tp!r} is not a number")
    elif tp < 0:
        # A negative one inverts resolve()'s envelope - oldest ends up younger
        # than youngest - and the panel prints "+/- -5000 yr".
        bad.append(f"time_precision {tp} is negative")

    gm = c.get("geometry") or {}
    if gm.get("mode") in ("point", "region"):
        if gm.get("lat") is None or gm.get("lng") is None:
            bad.append(f"{gm['mode']} geometry without coordinates")
        elif not (-90 <= gm["lat"] <= 90 and -180 <= gm["lng"] <= 180):
            bad.append(f"coordinates out of range {gm['lat']},{gm['lng']}")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_output")
    ap.add_argument("--ingested", default=os.path.join(ROOT, "src", "ingested.json"))
    ap.add_argument("--graph", default=os.path.join(ROOT, "src", "graph.json"))
    # Dry run by default, like tools/apply_patch.py. It used to be the other
    # way round: two tools in this directory merge authored content into
    # src/graph.json, and they had opposite defaults, so confusing them wrote to
    # the committed graph when you meant to see a plan. --dry-run is still
    # accepted and still means what it says.
    ap.add_argument("--write", action="store_true",
                    help="apply the merge; without it this is a dry run")
    ap.add_argument("--dry-run", action="store_true",
                    help=argparse.SUPPRESS)
    a = ap.parse_args()

    wf = unescape(load_workflow(a.workflow_output))
    new_claims = wf.get("claims", [])
    ing = json.load(open(a.ingested, encoding="utf-8"))
    graph = json.load(open(a.graph, encoding="utf-8"))

    # Ingested ids that name something the graph already has under another id.
    apath = os.path.join(ROOT, "src", "referent_aliases.json")
    alias = {}
    if os.path.exists(apath):
        alias = {k: v for k, v in json.load(open(apath, encoding="utf-8")).items()
                 if not k.startswith("_") and isinstance(v, str) and v}

    by_id = {r["id"]: r for r in graph["referents"]}
    # Referents that ingest.py resolved but the graph has not seen, plus QID
    # backfill onto ones it has: identity is the thing Wikidata is actually good
    # for, so take it even where the dates had to come from elsewhere.
    added_refs, backfilled, aliased = [], [], []
    for r in ing.get("referents", []):
        target = alias.get(r["id"])
        if target and target in by_id:
            # Same thing in the world: keep the graph's referent, take the QID.
            if r.get("wikidata") and not by_id[target].get("wikidata"):
                by_id[target]["wikidata"] = r["wikidata"]
            aliased.append(f"{r['id']} -> {target} ({r.get('wikidata','no qid')})")
            continue
        if r["id"] in by_id:
            if r.get("wikidata") and not by_id[r["id"]].get("wikidata"):
                by_id[r["id"]]["wikidata"] = r["wikidata"]
                backfilled.append(f"{r['id']} -> {r['wikidata']}")
        else:
            rec = {k: r[k] for k in ("id", "label", "kind") if k in r}
            if r.get("wikidata"):
                rec["wikidata"] = r["wikidata"]
            graph["referents"].append(rec)
            by_id[rec["id"]] = rec
            added_refs.append(rec["id"])

    known = set(by_id)
    existing_claim_ids = {c["id"] for c in graph["claims"]}

    merged, rejected, dupes = [], [], []
    for c in new_claims:
        if c.get("about") in alias:
            c["about"] = alias[c["about"]]
        problems = check(c, known)
        if problems:
            rejected.append((c.get("id", "?"), c.get("about", "?"), problems))
            continue
        if c["id"] in existing_claim_ids:
            dupes.append(c["id"])
            continue
        clean = {k: v for k, v in c.items() if not k.startswith("_")}
        clean.setdefault("coords_are_modern", True)
        merged.append(clean)
        existing_claim_ids.add(c["id"])

    print(f"stage-4 claims in     {len(new_claims)}")
    print(f"  merged              {len(merged)}")
    print(f"  rejected            {len(rejected)}")
    print(f"  already present     {len(dupes)}")
    print(f"referents added       {len(added_refs)}  {added_refs}")
    print(f"QIDs backfilled       {len(backfilled)}  {backfilled}")
    if aliased:
        print(f"ALIASED onto existing referents ({len(aliased)}) — no duplicates created:")
        for x in aliased:
            print("  -", x)

    if merged:
        withdoi = sum(1 for c in merged if c.get("doi"))
        print(f"  carrying a DOI      {withdoi}/{len(merged)}")
        per = collections.Counter(c["about"] for c in merged)
        print(f"  per referent        {dict(per)}")
        rival = {r: n for r, n in per.items() if n > 1}
        if rival:
            print(f"  referents that will render as bands: {sorted(rival)}")

    if rejected:
        print(f"\nREJECTED — not merged:")
        for cid, about, probs in rejected[:15]:
            print(f"  {cid} ({about}): {'; '.join(probs)}")

    if a.dry_run or not a.write:
        print("\n(dry run; pass --write to apply)")
        return 0

    graph["claims"].extend(merged)
    json.dump(graph, open(a.graph, "w", encoding="utf-8"),
              separators=(",", ":"), ensure_ascii=False)
    print(f"\nwrote {a.graph}: {len(graph['referents'])} referents, "
          f"{len(graph['claims'])} claims, {len(graph['edges'])} edges")
    # validate_graph.py is the gate; check() above is only a per-claim subset of
    # it and says nothing about referential integrity across the whole graph.
    # Pointing straight at build.py, which does not validate, let a malformed
    # merge reach the built page unchallenged.
    print("Next: python tools/validate_graph.py, then python tools/build.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
