"""Say, per claim, what has actually been checked about its source.

    python tools/check_sources.py            # dry run: report, write nothing
    python tools/check_sources.py --write    # lift DOIs into the graph, refresh the sidecar
    python tools/check_sources.py --offline  # no network; re-check the graph against the
                                             # sidecar and run the offline regressions

Two different things get called "verified" and this tool keeps them apart,
in the data and therefore in the panel:

  1. BIBLIOGRAPHIC. A `doi` field resolves at Crossref, and the record's first
     author and year are the ones THIS claim's citation string names. That is
     an author/year match, checked per claim: it says the identifier is live
     and points at a work by the cited author from the cited year. It does not
     prove the identifier is the paper the citation means (an author can have
     two papers in one journal in one year), and it says nothing about whether
     the paper supports the statement, the date, the precision or the status
     timeline. Crossref's answer per DOI is recorded in src/source_check.json;
     the match is recomputed against each claim's own citation, never
     inherited from another claim that happens to share the DOI.

  2. CONTENT. A claim carries `source_status: "checked"` when a person or an
     adversarial pass read the cited work against the statement. The 2026
     causal-graph pass did that for 37 claims (README, Known gaps). This tool
     never sets, clears or reads that field to decide anything: a resolving
     DOI is not a reason to touch it.

What it does change, under --write, is the `doi` field, and only by rules
that name a bibliographic work from evidence a reviewer can see in the
citation string itself:

  inline     the citation string already carries "doi 10.xxxx/..." in prose
             and the field is empty. 23 of the 37 checked claims were written
             that way, which is why the panel called the best-checked claims
             in the graph "no DOI recorded".
  identical  another claim with a byte-identical `asserted_by` carries a DOI.
             Same string, same work.
  title      the citation string spells out the work's full title and its
             journal, and exactly one DOI in the graph resolves to a work
             with that title, that journal, that first author and that year.
             A full title identifies a paper; author, year and journal alone
             do not, so a citation like "Renne et al. 2013, Science" is never
             completed by this rule however many Renne 2013 Science DOIs the
             graph holds. (An earlier revision did exactly that under a
             `crossref` rule; those lifts were reverted.)

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
RULES = ("inline", "identical", "title")
# A title shorter than this is not evidence of identity ("Reply", "Comment").
MIN_TITLE = 25


def fold(s):
    """Accent-insensitive lowercase with whitespace collapsed: Crossref says
    GRÜN and Claoué-Long, the citation strings say Grun and Claoue-Long, and
    both are the same person."""
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s or "")
                if not unicodedata.combining(ch)).lower()
    return re.sub(r"\s+", " ", s).strip()


def strip_inline_doi(s):
    m = DOI_INLINE.search(s)
    if not m:
        return None
    return m.group(1).rstrip(".,;:)")


def crossref(doi):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    req = urllib.request.Request(url, headers={"User-Agent": "earth-x-time tools/check_sources.py"})
    # The public API rate-limits bursts with a 429; a short wait and one more
    # try is the difference between a checked DOI and a spurious failure.
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)["message"]
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def summarise(msg):
    """What the sidecar keeps per DOI: bibliographic facts only. No verdict
    lives here; verdicts are per claim (claim_matches) and recomputed."""
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


def author_year_match(work, asserted_by):
    """The Crossref record's first-author surname appears as a whole word in
    this claim's citation string, and the record's year follows it within the
    same reference (a semicolon ends a reference). Usually that is the
    string's opening ("Renne et al. 2013, Science"), or a full author list;
    it also covers "... as summarised in Burgess & Bowring 2015, Science
    Advances". A different surname or a different year does not match. This
    is the whole of what "resolves" means in the panel, and it is not
    identity: an author can have two papers in one year."""
    if not work or work.get("error") or not work.get("first_author") or not work.get("year"):
        return False
    pat = (r"(?<![a-z])" + re.escape(fold(work["first_author"])) + r"(?![a-z])"
           r"[^;]*?(?<!\d)" + str(work["year"]) + r"(?!\d)")
    return re.search(pat, fold(asserted_by)) is not None


def claim_matches(c, works):
    """Per claim: its own DOI, its own citation string."""
    return bool(c.get("doi")) and author_year_match(works.get(c["doi"]), c["asserted_by"])


def ref_state(c, works):
    """'none' (no DOI) | 'author_year' (record exists, this citation's author
    and year match) | 'mismatch' (record exists, they do not) | 'unchecked'
    (no record). The build refuses the last two."""
    d = c.get("doi")
    if not d:
        return "none"
    if d not in works or works[d].get("error"):
        return "unchecked"
    return "author_year" if author_year_match(works[d], c["asserted_by"]) else "mismatch"


def title_evidence(work, asserted_by):
    """The citation spells out the work's full title AND its journal, and
    names its first author and year. That is work-level evidence a reviewer
    can see; author/year/journal without the title is not."""
    if not work or work.get("error"):
        return False
    t = fold(work.get("title"))
    if len(t) < MIN_TITLE:
        return False
    cite = fold(asserted_by)
    names = [fold(n) for n in (work.get("container"), work.get("short_container")) if n]
    return (t in cite and any(n in cite for n in names)
            and author_year_match(work, asserted_by))


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
    work for. Pure: mutates nothing. Every rule needs evidence in the claim's
    own citation string; none of them completes a bare "Author year, Journal"."""
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

    # title: the citation spells out the full title and the journal of a work
    # some DOI in the graph resolves to, and only one such DOI exists
    graph_dois = sorted({c["doi"] for c in claims if have(c)})
    for c in claims:
        if have(c) or c["id"] in lifted_ids:
            continue
        cands = [d for d in graph_dois if title_evidence(works.get(d), c["asserted_by"])]
        if len(cands) == 1:
            lifts.append((c, cands[0], "title"))
            lifted_ids.add(c["id"])
        elif len(cands) > 1:
            log.append(f"  ~ {c['id']}: {len(cands)} works carry this title and journal; left alone")
    return lifts


def apply_lifts(claims, works, lifts, log):
    """Write lifted DOIs into the claims, each one only if, once written, the
    claim's own citation matches the record. Returns the (claim, doi, rule)
    triples that landed. Touches the `doi` field and nothing else."""
    applied = []
    for c, d, rule in lifts:
        if not author_year_match(works.get(d), c["asserted_by"]):
            log.append(f"  ~ {c['id']}: not lifting {d}, Crossref record does not match this citation")
            continue
        c["doi"] = d
        applied.append((c, d, rule))
    return applied


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
        for d in dois:
            try:
                w = summarise(crossref(d))
                w["checked"] = today
            except Exception as e:                       # noqa: BLE001
                w = {"checked": today, "error": str(e)[:120]}
                log.append(f"  ! {d}: {e}")
            works[d] = w
            time.sleep(0.6)                              # polite to a public API
        side["works"] = works
    for c in claims:
        if ref_state(c, works) == "mismatch":
            w = works[c["doi"]]
            log.append(f"  ! {c['id']}: {c['doi']} is {w.get('first_author')} {w.get('year')} "
                       f"at Crossref; cited as {c['asserted_by'][:60]!r}")

    # ---- 2. lift DOIs by rule -------------------------------------------------
    lifts = lift_dois(claims, works, log)
    for c, d, rule in lifts:
        ok = "author/year match" if author_year_match(works.get(d), c["asserted_by"]) else "NO MATCH"
        print(f"  {rule:9} {c['id']:44} {d}  [{ok}]")
    if write:
        applied = apply_lifts(claims, works, lifts, log)
        merged = {x["claim"]: x for x in side.get("lifted", []) if x.get("rule") in RULES}
        for c, d, rule in applied:
            merged[c["id"]] = {"claim": c["id"], "doi": d, "rule": rule}
        side["lifted"] = [merged[k] for k in sorted(merged)]

    # ---- 3. report ------------------------------------------------------------
    n = len(claims)
    with_doi = [c for c in claims if c.get("doi")]
    resolves = [c for c in with_doi if claim_matches(c, works)]
    checked = [c for c in claims if c.get("source_status") == "checked"]
    both = [c for c in checked if claim_matches(c, works)]
    print(f"\nclaims {n}")
    print(f"  DOI recorded                       {len(with_doi)}")
    print(f"  DOI resolves, author/year match    {len(resolves)}   (bibliographic only, per claim)")
    print(f"  content checked against the paper  {len(checked)}   (of which {len(both)} also carry such a DOI)")
    print(f"  neither                            {sum(1 for c in claims if not c.get('doi') and c.get('source_status') != 'checked')}")
    print(f"  would lift under --write           {len(lifts)}" if not write else f"  lifted                             {len(applied)}")
    if log:
        print("\nnotes")
        print("\n".join(log))

    if write:
        side["_comment"] = (
            "Written by tools/check_sources.py. `works` is what Crossref said about each DOI "
            "in the graph: first author, year, journal, title. It carries no verdict; whether "
            "a claim's citation matches its DOI's record (first author and year) is recomputed "
            "per claim by the tool, the validator and the build. Even a match is a "
            "bibliographic fact only: it says the identifier is live and points at a work by "
            "the cited author from the cited year, not that the paper supports the claim, its "
            "date or its status timeline. Claim-level checking is the `source_status` field on "
            "the claim itself and this tool never writes it. `lifted` lists every claim whose "
            "`doi` field this tool filled, and by which rule (inline, identical, title).")
        side["checked"] = date.today().isoformat()
        with open(SIDECAR, "w", encoding="utf-8") as f:
            json.dump(side, f, indent=1, ensure_ascii=False)
            f.write("\n")
        save_graph(g)
        print(f"\nwrote {SIDECAR} and {GRAPH}")
    elif not offline:
        print("\n(dry run: pass --write to lift DOIs into the graph and save the sidecar)")

    # ---- 4. consistency, the part validate_graph.py also runs ----------------
    rc = 0
    bad = consistency(claims, works)
    if bad:
        print("\nINCONSISTENT")
        print("\n".join("  ! " + b for b in bad))
        rc = 1
    if offline:
        import test_check_sources
        failed = test_check_sources.run()
        if failed:
            rc = 1
    return rc


def consistency(claims, works):
    """Offline invariants, per claim. validate_graph.py calls this too, so a
    graph cannot reach the build with a DOI the sidecar has never looked at,
    or a DOI sitting beside a citation its record does not match."""
    bad = []
    by_string = {}
    for c in claims:
        d = c.get("doi")
        if d is not None and not DOI_SHAPE.match(str(d)):
            bad.append(f"{c['id']}: doi {d!r} is not shaped like a DOI")
        st = ref_state(c, works)
        if st == "unchecked":
            bad.append(f"{c['id']}: doi {d} has no record in src/source_check.json; run tools/check_sources.py --write")
        elif st == "mismatch":
            w = works[d]
            bad.append(f"{c['id']}: doi {d} resolves to {w.get('first_author')} {w.get('year')} "
                       f"but this claim cites {c['asserted_by'][:50]!r}")
        if not d and strip_inline_doi(c["asserted_by"]):
            bad.append(f"{c['id']}: citation carries a DOI in prose but the doi field is empty")
        ss = c.get("source_status")
        if ss is not None and ss != "checked":
            bad.append(f"{c['id']}: source_status {ss!r} is not a known value")
        by_string.setdefault(c["asserted_by"], set()).add(d or None)
    for s, ds in by_string.items():
        if len(ds) > 1:
            bad.append(f"identical citation {s[:50]!r} carries different doi values {sorted(map(str, ds))}")
    return bad


if __name__ == "__main__":
    sys.exit(main())
