"""Say, per claim, what has actually been checked about its source.

    python tools/check_sources.py            # dry run: report, write nothing
    python tools/check_sources.py --write    # lift DOIs into the graph, refresh the sidecar
    python tools/check_sources.py --offline  # no network; re-check the graph against the sidecar

Two different things get called "verified" and this tool keeps them apart,
in the data and therefore in the panel:

  1. BIBLIOGRAPHIC. A `doi` field resolves at Crossref to a work whose first
     author and year match the citation string. That says the reference
     exists and is the paper the string names. It says nothing about whether
     the paper supports the statement, the date, the precision or the status
     timeline attached to it. That is recorded in src/source_check.json,
     keyed by DOI, and the panel words it as "DOI resolves to the cited work".

  2. CONTENT. A claim carries `source_status: "checked"` when a person or an
     adversarial pass read the cited work against the statement. The 2026
     causal-graph pass did that for 37 claims (README, Known gaps). This tool
     never sets that field: a resolving DOI is not a reason to.

What it does change, under --write, is the `doi` field, and only by rules
that name a bibliographic work rather than guess at one:

  inline     the citation string already carries "doi 10.xxxx/..." in prose
             and the field is empty. 23 of the 37 checked claims were written
             that way, which is why the panel called the best-checked claims
             in the graph "no DOI recorded".
  identical  another claim with a byte-identical `asserted_by` carries a DOI.
             Same string, same work.
  crossref   a DOI-bearing claim shares first author and year, and the
             Crossref record's container title appears in this claim's
             citation string. Same author, same year, same journal. Every
             such lift is listed in the sidecar so it can be reviewed.

Nothing else moves. Dates, precision, statuses and the citation prose stay
as they are; a lifted DOI is additive. The graph is written back in the
same compact single-line form validate_graph.py uses, so the diff is the
fields that changed and nothing else.
"""
import json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GRAPH = os.path.join(ROOT, "src", "graph.json")
SIDECAR = os.path.join(ROOT, "src", "source_check.json")

# A DOI in prose, with the trailing punctuation the sentence added stripped.
# `;2` inside a DOI is legal (10.1130/...CO;2) so only the END is trimmed.
DOI_INLINE = re.compile(r"\bdoi[:\s]+(10\.\d{4,9}/\S+)", re.I)
DOI_SHAPE = re.compile(r"^10\.\d{4,9}/\S+$")


def fold(s):
    """Accent-insensitive lowercase: Crossref says GRÜN and Claoué-Long, the
    citation strings say Grun and Claoue-Long, and both are the same person."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(ch)).lower()


def author_year(asserted_by):
    m = re.match(r"\s*([A-Za-zÀ-ɏ'\-]+).*?\b(1[5-9]\d\d|20\d\d)\b", asserted_by)
    return (fold(m.group(1)), int(m.group(2))) if m else (None, None)


def strip_inline_doi(s):
    m = DOI_INLINE.search(s)
    if not m:
        return None
    return m.group(1).rstrip(".,;:)")


def crossref(doi):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": "earth-x-time tools/check_sources.py"})
    # The public API rate-limits bursts with a 429; a short wait and one more
    # try is the difference between a checked DOI and a spurious "unmatched".
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)["message"]
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def summarise(msg):
    issued = (msg.get("issued") or msg.get("published-print") or msg.get("published-online")
              or {}).get("date-parts", [[None]])[0][0]
    authors = msg.get("author") or []
    first = authors[0].get("family") if authors else None
    return {
        "first_author": first,
        "year": issued,
        "container": (msg.get("container-title") or [""])[0],
        "short_container": (msg.get("short-container-title") or [""])[0],
        "title": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", (msg.get("title") or [""])[0])).strip()[:160],
    }


def bibliographic_match(work, asserted_by):
    """First author surname and year both present in the citation string."""
    a, y = author_year(asserted_by)
    if not work.get("first_author") or not a:
        return False
    return fold(work["first_author"]) == a and work.get("year") == y


def load_graph():
    with open(GRAPH, encoding="utf-8") as f:
        return json.load(f)


def save_graph(g):
    with open(GRAPH, "w", encoding="utf-8") as f:
        json.dump(g, f, separators=(",", ":"), ensure_ascii=False)


def load_sidecar():
    if not os.path.exists(SIDECAR):
        return {"works": {}, "lifted": []}
    with open(SIDECAR, encoding="utf-8") as f:
        return json.load(f)


def lift_dois(claims, works, log):
    """Returns [(claim, doi, rule)] for every DOI-less claim a rule can name a
    work for. Pure: mutates nothing."""
    lifts = []
    have = lambda c: bool(c.get("doi"))

    # inline: the prose already says it
    for c in claims:
        if have(c):
            continue
        d = strip_inline_doi(c["asserted_by"])
        if d and DOI_SHAPE.match(d):
            lifts.append((c, d, "inline"))
    lifted_ids = {c["id"] for c, _, _ in lifts}

    # identical: same string, same work
    by_string = {}
    for c in claims:
        if have(c):
            by_string.setdefault(c["asserted_by"], set()).add(c["doi"])
    for c in claims:
        if have(c) or c["id"] in lifted_ids:
            continue
        dois = by_string.get(c["asserted_by"])
        if dois and len(dois) == 1:
            lifts.append((c, next(iter(dois)), "identical"))
            lifted_ids.add(c["id"])
        elif dois:
            log.append(f"  ~ {c['id']}: identical citation carries {len(dois)} different DOIs; left alone")

    # crossref: same first author, same year, and the record's journal named
    by_ay = {}
    for c in claims:
        if have(c):
            by_ay.setdefault(author_year(c["asserted_by"]), set()).add(c["doi"])
    for c in claims:
        if have(c) or c["id"] in lifted_ids:
            continue
        ay = author_year(c["asserted_by"])
        if ay[0] is None or ay not in by_ay:
            continue
        cands = []
        for d in by_ay[ay]:
            w = works.get(d)
            if not w or not w.get("match"):
                continue
            names = [n for n in (w.get("container"), w.get("short_container")) if n]
            if any(fold(n) in fold(c["asserted_by"]) for n in names):
                cands.append(d)
        if len(cands) == 1:
            lifts.append((c, cands[0], "crossref"))
            lifted_ids.add(c["id"])
        elif len(cands) > 1:
            log.append(f"  ~ {c['id']}: {len(cands)} works match author/year/journal; left alone")
    return lifts


def main():
    argv = sys.argv[1:]
    write = "--write" in argv
    offline = "--offline" in argv
    g = load_graph()
    claims = g["claims"]
    side = load_sidecar()
    works = side.get("works", {})
    log = []

    # ---- 1. resolve every recorded DOI (network) ------------------------------
    dois = sorted({c["doi"] for c in claims if c.get("doi")})
    # Inline DOIs get resolved too, so a lift can be checked before it lands.
    for c in claims:
        if not c.get("doi"):
            d = strip_inline_doi(c["asserted_by"])
            if d and DOI_SHAPE.match(d) and d not in dois:
                dois.append(d)
    if not offline:
        today = date.today().isoformat()
        for i, d in enumerate(dois):
            cited = next((c["asserted_by"] for c in claims
                          if c.get("doi") == d or strip_inline_doi(c["asserted_by"]) == d), "")
            try:
                w = summarise(crossref(d))
                w["match"] = bibliographic_match(w, cited)
                w["checked"] = today
                if not w["match"]:
                    log.append(f"  ! {d}: Crossref says {w['first_author']} {w['year']}; "
                               f"cited as {cited[:60]!r}")
            except Exception as e:                       # noqa: BLE001
                w = {"match": False, "checked": today, "error": str(e)[:120]}
                log.append(f"  ! {d}: {e}")
            works[d] = w
            time.sleep(0.6)                              # polite to a public API
        side["works"] = works

    # ---- 2. lift DOIs by rule -------------------------------------------------
    lifts = lift_dois(claims, works, log)
    for c, d, rule in lifts:
        w = works.get(d) or {}
        ok = "resolves" if w.get("match") else "UNMATCHED"
        print(f"  {rule:9} {c['id']:44} {d}  [{ok}]")
    if write:
        for c, d, rule in lifts:
            if not (works.get(d) or {}).get("match"):
                log.append(f"  ~ {c['id']}: not lifting {d}, Crossref did not match the citation")
                continue
            c["doi"] = d
        merged = {x["claim"]: x for x in side.get("lifted", [])}
        for c, d, rule in lifts:
            if (works.get(d) or {}).get("match"):
                merged[c["id"]] = {"claim": c["id"], "doi": d, "rule": rule}
        side["lifted"] = [merged[k] for k in sorted(merged)]

    # ---- 3. report ------------------------------------------------------------
    n = len(claims)
    with_doi = [c for c in claims if c.get("doi")]
    resolves = [c for c in with_doi if (works.get(c["doi"]) or {}).get("match")]
    checked = [c for c in claims if c.get("source_status") == "checked"]
    both = [c for c in checked if (works.get(c.get("doi")) or {}).get("match")]
    print(f"\nclaims {n}")
    print(f"  DOI recorded                       {len(with_doi)}")
    print(f"  DOI resolves to the cited work     {len(resolves)}   (bibliographic only)")
    print(f"  content checked against the paper  {len(checked)}   (of which {len(both)} also carry a resolving DOI)")
    print(f"  neither                            {sum(1 for c in claims if not c.get('doi') and c.get('source_status') != 'checked')}")
    print(f"  would lift under --write           {len(lifts)}" if not write else f"  lifted                             {len(lifts)}")
    if log:
        print("\nnotes")
        print("\n".join(log))

    if write:
        side["_comment"] = (
            "Written by tools/check_sources.py. `works` is what Crossref said about each DOI "
            "in the graph and whether its first author and year match the citation string. "
            "That is a bibliographic check only: it confirms the reference exists and is the "
            "paper named, not that the paper supports the claim, its date or its status "
            "timeline. Claim-level checking is the `source_status` field on the claim itself. "
            "`lifted` lists every claim whose `doi` field this tool filled, and by which rule.")
        side["checked"] = date.today().isoformat()
        with open(SIDECAR, "w", encoding="utf-8") as f:
            json.dump(side, f, indent=1, ensure_ascii=False)
            f.write("\n")
        save_graph(g)
        print(f"\nwrote {SIDECAR} and {GRAPH}")
    elif not offline:
        print("\n(dry run: pass --write to lift DOIs into the graph and save the sidecar)")

    # ---- 4. consistency, the part validate_graph.py also runs ----------------
    bad = consistency(claims, works)
    if bad:
        print("\nINCONSISTENT")
        print("\n".join("  ! " + b for b in bad))
        return 1
    return 0


def consistency(claims, works):
    """Offline invariants. validate_graph.py calls this too, so a graph cannot
    reach the build with a DOI the sidecar has never looked at."""
    bad = []
    by_string = {}
    for c in claims:
        d = c.get("doi")
        if d is not None and not DOI_SHAPE.match(str(d)):
            bad.append(f"{c['id']}: doi {d!r} is not shaped like a DOI")
        if d and d not in works:
            bad.append(f"{c['id']}: doi {d} has no record in src/source_check.json; run tools/check_sources.py --write")
        if not d and strip_inline_doi(c["asserted_by"]):
            bad.append(f"{c['id']}: citation carries a DOI in prose but the doi field is empty")
        st = c.get("source_status")
        if st is not None and st != "checked":
            bad.append(f"{c['id']}: source_status {st!r} is not a known value")
        by_string.setdefault(c["asserted_by"], set()).add(d or None)
    for s, ds in by_string.items():
        if len(ds) > 1:
            bad.append(f"identical citation {s[:50]!r} carries different doi values {sorted(map(str, ds))}")
    return bad


if __name__ == "__main__":
    sys.exit(main())
