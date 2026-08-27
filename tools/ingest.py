"""
Ingest referents and claims from Wikidata, with provenance resolved via Crossref.

    python tools/ingest.py Q13415 Q133346 --out src/ingested.json

Stages 1-3 of the pipeline. The fourth stage — deciding when a claim went from
proposed to contested to consensus — is deliberately NOT here. Citation volume
does not encode agreement (Alvarez 1980 is cited no more after Chicxulub was
confirmed in 1991 than before; a contested paper is cited heavily *because* it
is contested), and no database stores the transitions. Everything emitted here
gets a single-entry status_timeline and `_review: true`, and a human or a
searching model has to finish it.

The one rule this enforces without mercy is the product's own: a Wikidata
statement carrying no reference produces no claim. No source, no fact.

Dependency-free — urllib only, like the other tools here.
"""
import urllib.request, urllib.parse, json, re, sys, os, math, time, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PRESENT = 2025                    # ybp is measured from here, as in the app
sys.path.insert(0, HERE)
# Read from src/20_core.js rather than mirrored. NOT the same quantity as
# PRESENT, however alike the numbers have looked: PRESENT is the epoch every
# stored ybp is measured from, and moving it would move every date in the
# dataset. KT_MAX is how recent a paper the rail can reach.
from knowledge_time import KT_MIN, KT_MAX  # noqa: E402

MAILTO = "joshp1001@gmail.com"    # Crossref/OpenAlex polite pool
UA = {"User-Agent": f"EarthXTime-ingest/0.1 (https://github.com/kejjeh; mailto:{MAILTO})"}

WD_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"
WD_SEARCH = ("https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json"
             "&language=en&uselang=en&type=item&limit=5&search={}")
CROSSREF_DOI = "https://api.crossref.org/works/{}"
CROSSREF_Q = "https://api.crossref.org/works?rows=3&query.bibliographic={}&select=DOI,title,author,issued,container-title,is-referenced-by-count,type"

# Wikidata time precision -> size of the unit it is stated in, in years.
PRECISION_YEARS = {0: 1e9, 1: 1e8, 2: 1e7, 3: 1e6, 4: 1e5, 5: 1e4,
                   6: 1e3, 7: 1e2, 8: 1e1, 9: 1.0, 10: 1 / 12, 11: 1 / 365}

# Properties that assert *when* something was.
TIME_PROPS = {
    "P585": "point in time", "P580": "start time", "P582": "end time",
    "P571": "inception", "P576": "dissolved, abolished or demolished",
    "P2669": "discontinued date",
}

# Rank is Wikidata's own epistemic signal. It says *that* a statement is out of
# favour, never *when* it fell — so this is a starting position, not an answer.
RANK_STATUS = {"preferred": "consensus", "normal": "proposed", "deprecated": "superseded"}

# Map Wikidata "instance of"/"subclass of" labels onto the app's six subjects.
# Keyword rules on the English label, because the QID space is far too broad to
# enumerate. Anything that resolves to fewer than two subjects is held for review.
SUBJECT_RULES = [
    ("geology", r"crater|impact|volcan|geolog|formation|orogen|tecton|basalt|"
                r"strat|mineral|rock|mountain|erupt|earthquake|basin|province"),
    ("biology", r"taxon|species|organism|biolog|fossil|biota|ecosystem|extinction|"
                r"bacteri|eukaryot|plant|animal|clade"),
    ("evolution", r"evolution|speciation|radiation|divergence|phylogen|clade|lineage"),
    ("chemistry", r"chemic|isotop|element|molecul|oxygen|carbon|atmospher|geochem"),
    ("human_history", r"war|battle|civilis|civiliz|invention|empire|dynasty|"
                      r"archaeolog|culture|historical|treaty|revolution|city|settlement"),
    ("astronomy", r"astronom|asteroid|comet|meteor|planet|impact event|solar|cosmic|lunar"),
]

# "event" if it occurs, "entity" if it persists.
EVENT_RULES = r"event|extinction|eruption|impact|battle|war|collision|revolution|" \
              r"transition|explosion|glaciation|excursion|anomaly|disaster|test"

_cache = {}


def fetch(url, tries=3):
    if url in _cache:
        return _cache[url]
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                out = json.load(r)
            _cache[url] = out
            return out
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


# ---------------------------------------------------------------- stage 1: wikidata
def wd_entity(qid):
    return fetch(WD_ENTITY.format(qid))["entities"][qid]


def wd_resolve(term):
    """
    Accept a name as well as a Q-number.

    Hand-typed QIDs are a silent-failure machine: Q13415 is Beta Canis Majoris,
    not the Chicxulub crater, and an ingester handed the wrong number will
    cheerfully emit a well-formed claim about a star. Resolving by name and
    printing what came back makes the mistake visible at the point it happens.
    """
    if re.fullmatch(r"Q\d+", term, re.I):
        return term.upper(), None
    hits = fetch(WD_SEARCH.format(urllib.parse.quote(term))).get("search", [])
    if not hits:
        raise LookupError(f"no Wikidata item matches {term!r}")
    top = hits[0]
    alts = [f"{h['id']} {h.get('label','')}" for h in hits[1:4]]
    return top["id"], {"matched": f"{top['id']} {top.get('label','')} — "
                                  f"{top.get('description','no description')}",
                       "alternatives": alts}


def wd_label(qid):
    """Label for a QID, cached. Used to read P31 values and reference sources."""
    try:
        e = wd_entity(qid)
    except Exception:                                # noqa: BLE001
        return qid
    return (e.get("labels", {}).get("en", {}) or {}).get("value", qid)


def parse_wd_time(dv):
    """Wikidata time value -> (ybp_float, precision_years). None if unusable."""
    t = dv.get("time", "")
    m = re.match(r"([+-])(\d+)-", t)
    if not m:
        return None
    year = int(m.group(2)) * (-1 if m.group(1) == "-" else 1)
    ybp = float(PRESENT - year)
    unit = PRECISION_YEARS.get(dv.get("precision", 9), 1.0)
    # `before`/`after` are stated in units of `precision`; prefer them when given.
    span = max(dv.get("before", 0), dv.get("after", 0))
    prec = unit * span if span else unit / 2.0
    return ybp, float(prec)


def extract_refs(statement):
    """Every reference on a statement, as {doi, url, stated_in_qid, title, date}."""
    out = []
    for ref in statement.get("references", []):
        sn = ref.get("snaks", {})
        r = {"doi": None, "url": None, "stated_in": None, "title": None, "date": None}

        def val(pid):
            if pid not in sn:
                return None
            dv = sn[pid][0].get("datavalue", {}).get("value")
            return dv

        d = val("P356")
        if isinstance(d, str):
            r["doi"] = d.lower()
        u = val("P854")
        if isinstance(u, str):
            r["url"] = u
            m = re.search(r"(10\.\d{4,9}/[^\s\"'<>&]+)", u)
            if m and not r["doi"]:
                r["doi"] = m.group(1).lower().rstrip(".")
        si = val("P248")
        if isinstance(si, dict) and si.get("id"):
            r["stated_in"] = si["id"]
        ti = val("P1476")
        if isinstance(ti, dict):
            r["title"] = ti.get("text")
        for p in ("P577", "P813"):
            dv = val(p)
            if isinstance(dv, dict) and dv.get("time"):
                m = re.match(r"([+-])(\d+)-", dv["time"])
                if m:
                    r["date"] = int(m.group(2)) * (-1 if m.group(1) == "-" else 1)
                    if p == "P577":
                        break
        if any(r.values()):
            out.append(r)
    return out


# --------------------------------------------------------------- stage 2: crossref
def crossref_by_doi(doi):
    try:
        return fetch(CROSSREF_DOI.format(urllib.parse.quote(doi, safe="")))["message"]
    except Exception:                                # noqa: BLE001
        return None


def crossref_by_title(title):
    try:
        items = fetch(CROSSREF_Q.format(urllib.parse.quote(title)))["message"]["items"]
    except Exception:                                # noqa: BLE001
        return None
    if not items:
        return None
    # Prefer the most-cited hit: conference reprints and errata share the title
    # but not the standing. This is how the 1981 Alvarez reprint loses to the
    # 1980 Science paper.
    return max(items, key=lambda i: i.get("is-referenced-by-count", 0))


def format_citation(msg):
    """Crossref record -> ('Author et al. Year, Venue', year, doi, cited_by)."""
    if not msg:
        return None
    authors = msg.get("author") or []
    fam = [a.get("family") for a in authors if a.get("family")]
    if not fam:
        who = (msg.get("container-title") or ["Unknown"])[0]
    elif len(fam) == 1:
        who = fam[0]
    elif len(fam) == 2:
        who = f"{fam[0]} & {fam[1]}"
    else:
        who = f"{fam[0]} et al."
    parts = (msg.get("issued", {}).get("date-parts") or [[None]])[0]
    year = parts[0] if parts and parts[0] else None
    venue = (msg.get("container-title") or [""])[0]
    text = f"{who} {year}, {venue}".strip().rstrip(",")
    return {"text": text, "year": year, "doi": (msg.get("DOI") or "").lower(),
            "cited_by": msg.get("is-referenced-by-count", 0),
            "title": (msg.get("title") or [""])[0]}


def resolve_reference(r):
    """A Wikidata reference -> a verified citation, or None if it will not resolve."""
    if r.get("doi"):
        c = format_citation(crossref_by_doi(r["doi"]))
        if c:
            c["via"] = "doi"
            return c
    title = r.get("title")
    if not title and r.get("stated_in"):
        title = wd_label(r["stated_in"])
    if title and len(title) > 12:
        c = format_citation(crossref_by_title(title))
        if c:
            c["via"] = "title-search"
            return c
    if r.get("stated_in"):
        lbl = wd_label(r["stated_in"])
        if lbl and not lbl.startswith("Q"):
            return {"text": f"{lbl}" + (f" ({r['date']})" if r.get("date") else ""),
                    "year": r.get("date"), "doi": None, "cited_by": 0,
                    "title": lbl, "via": "wikidata-only"}
    return None


# ------------------------------------------------------------------ stage 3: fit
def slug(label):
    s = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return re.sub(r"_+", "_", s)[:48]


# The schema demands two or more subjects, and a single keyword hit rarely gets
# there: "impact crater" reads as geology alone, when the whole point of the
# Chicxulub story is that it is also astronomy. These pairings are defensible
# defaults, not findings — every ingested claim is _review:true regardless.
SUBJECT_IMPLIES = [
    (r"impact|crater|asteroid|meteor|bolide", ["geology", "astronomy"]),
    (r"extinction", ["biology", "geology"]),
    (r"volcan|erupt|basalt|traps", ["geology", "chemistry"]),
    (r"taxon|species|genus|organism|fossil", ["biology", "evolution"]),
    (r"glaciation|ice age|snowball", ["geology", "chemistry"]),
    (r"archaeolog|ancient city|settlement|battle|war|empire", ["human_history", "geology"]),
    (r"atmospher|oxygen|isotop", ["chemistry", "geology"]),
]


def infer_subjects(type_labels):
    blob = " ".join(type_labels).lower()
    subs = [name for name, pat in SUBJECT_RULES if re.search(pat, blob)]
    for pat, implied in SUBJECT_IMPLIES:
        if re.search(pat, blob):
            subs.extend(implied)
    return list(dict.fromkeys(subs))


def infer_kind(type_labels):
    blob = " ".join(type_labels).lower()
    return "event" if re.search(EVENT_RULES, blob) else "entity"


def ingest_qid(qid, existing_by_qid, existing_ids, report):
    ent = wd_entity(qid)
    label = (ent.get("labels", {}).get("en", {}) or {}).get("value", qid)
    claims_wd = ent.get("claims", {})

    type_labels = []
    for pid in ("P31", "P279"):
        for st in claims_wd.get(pid, []):
            v = st["mainsnak"].get("datavalue", {}).get("value")
            if isinstance(v, dict) and v.get("id"):
                type_labels.append(wd_label(v["id"]))

    subjects = infer_subjects(type_labels + [label])
    kind = infer_kind(type_labels + [label])

    # Idempotency. A QID already on a referent is an exact match. Failing that,
    # fall back to slug equality so hand-authored referents — which predate this
    # tool and carry no QID — adopt one instead of spawning "deccan_traps_2"
    # alongside "deccan_traps". Reported either way; the review step is the check.
    ref_id, link = existing_by_qid.get(qid), None
    if not ref_id:
        cand = slug(label)
        if cand in existing_ids:
            ref_id, link = cand, f"{cand}: adopting {qid} by label match — confirm same referent"
        else:
            # try the existing ids for a looser match on significant words
            words = {w for w in cand.split("_") if len(w) > 3}
            for eid in existing_ids:
                if words and words <= set(eid.split("_")):
                    ref_id = eid
                    link = f"{eid}: adopting {qid} by partial label match ('{label}') — confirm"
                    break
    if not ref_id:
        ref_id = slug(label)
    if link:
        report["links"].append(link)

    # Geometry from P625, preferring a non-deprecated statement.
    geometry = {"mode": "none", "lat": None, "lng": None, "radius_km": None}
    for st in sorted(claims_wd.get("P625", []), key=lambda s: s["rank"] == "deprecated"):
        v = st["mainsnak"].get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("latitude") is not None:
            geometry = {"mode": "point", "lat": round(v["latitude"], 4),
                        "lng": round(v["longitude"], 4), "radius_km": None}
            break

    out_claims = []
    dropped = []
    for pid, pname in TIME_PROPS.items():
        for st in claims_wd.get(pid, []):
            dv = st["mainsnak"].get("datavalue", {}).get("value")
            if not isinstance(dv, dict):
                continue
            parsed = parse_wd_time(dv)
            if not parsed:
                dropped.append(f"{qid} {pid}: unparseable time {dv.get('time')}")
                continue
            ybp, prec = parsed

            report["counts"]["time_statements"] += 1
            refs = extract_refs(st)
            if refs:
                report["counts"]["with_reference"] += 1
            if not refs:
                dropped.append(f"{qid} {pid} ({ybp:,.0f} ybp): NO REFERENCE — "
                               f"no source, no fact")
                continue

            citation = None
            for r in refs:
                citation = resolve_reference(r)
                if citation:
                    break
            if citation:
                report["counts"]["resolved"] += 1
            if not citation:
                dropped.append(f"{qid} {pid} ({ybp:,.0f} ybp): "
                               f"{len(refs)} reference(s), none resolvable to a citation")
                continue

            # A claim is only as good as the year on its source. Clamping a
            # 2026 citation to 2025 emitted a sourced-looking claim with the
            # wrong source, and `kt or KT_MAX` invented a publication year for a
            # citation carrying none - both in the tool whose one rule is that
            # no source means no fact. Drop it, and say so.
            kt = citation.get("year")
            if not isinstance(kt, int) or not (KT_MIN <= kt <= KT_MAX):
                dropped.append(f"{qid} {pid} ({ybp:,.0f} ybp): citation "
                               f"{citation.get('doi') or citation.get('text')} has no usable "
                               f"year ({kt!r}); knowledge_time must be a real one in "
                               f"[{KT_MIN},{KT_MAX}]")
                continue
            status = RANK_STATUS.get(st.get("rank", "normal"), "proposed")

            cid = f"clm_{ref_id}_{pid.lower()}_{abs(hash((qid, pid, round(ybp), citation['doi'] or citation['text']))) % 10**6}"
            out_claims.append({
                "id": cid,
                "about": ref_id,
                "statement": f"{label}: {pname} given as "
                             f"{fmt_ybp(ybp)}." ,
                "type": "dating",
                "earth_time_start": ybp,
                "earth_time_end": ybp,
                "time_precision": prec,
                "geometry": dict(geometry),
                "coords_are_modern": True,
                "subjects": subjects,
                "zoom_band": [0, 10],
                "significance": significance_from(citation, ybp),
                "asserted_by": citation["text"],
                "knowledge_time": kt,
                "status_timeline": [{
                    "knowledge_time": kt, "status": status,
                    "source": f"{citation['text']}"
                              + (f" — doi:{citation['doi']}" if citation.get("doi") else "")
                              + f" — Wikidata rank '{st.get('rank')}' on {qid} {pid}",
                }],
                # everything below is metadata for review, stripped before merge
                "_review": True,
                "_wikidata": {"qid": qid, "property": pid, "rank": st.get("rank")},
                "_doi": citation.get("doi"),
                "_resolved_via": citation.get("via"),
                "_cited_by": citation.get("cited_by"),
            })

    report["dropped"].extend(dropped)
    report["counts"]["referents"] += 1
    if len(subjects) < 2:
        report["needs_subjects"].append(f"{ref_id} ({qid}): inferred {subjects or 'none'} "
                                        f"from {type_labels[:4]} — needs >=2")
    if geometry["mode"] == "none":
        report["no_geometry"].append(f"{ref_id} ({qid})")

    referent = {"id": ref_id, "label": label, "kind": kind, "wikidata": qid,
                "subjects": subjects}
    return referent, out_claims


def significance_from(citation, ybp):
    """Rough 1-5 from how heavily the anchoring paper is cited."""
    c = citation.get("cited_by") or 0
    return 5 if c > 2000 else 4 if c > 500 else 3 if c > 100 else 2 if c > 10 else 1


def fmt_ybp(t):
    a = abs(t)
    if a >= 1e9:
        return f"{t/1e9:.2f} Ga"
    if a >= 1e6:
        return f"{t/1e6:.3g} Ma"
    if a >= 12000:
        return f"{t/1000:.3g} ka"
    y = PRESENT - t
    return f"{abs(y):.0f} {'BCE' if y <= 0 else 'CE'}"


# ----------------------------------------------------------------------- driver
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("qids", nargs="+", metavar="ITEM",
                    help="Wikidata Q-numbers or names, e.g. Q13230 or 'Chicxulub crater'")
    ap.add_argument("--out", default=os.path.join(ROOT, "src", "ingested.json"))
    ap.add_argument("--graph", default=os.path.join(ROOT, "src", "graph.json"),
                    help="existing graph, read to keep ingestion idempotent")
    args = ap.parse_args()

    existing_by_qid, existing_ids = {}, set()
    if os.path.exists(args.graph):
        g = json.load(open(args.graph, encoding="utf-8"))
        for r in g.get("referents", []):
            existing_ids.add(r["id"])
            if r.get("wikidata"):
                existing_by_qid[r["wikidata"]] = r["id"]

    report = {"dropped": [], "needs_subjects": [], "no_geometry": [], "links": [],
              "counts": {"referents": 0, "time_statements": 0, "with_reference": 0, "resolved": 0}}
    referents, claims = [], []
    for term in args.qids:
        term = term.strip()
        print(f"\n=== {term} ===")
        try:
            qid, match = wd_resolve(term)
            if match:
                print(f"  resolved: {match['matched']}")
                if match["alternatives"]:
                    print(f"  (also matched: {'; '.join(match['alternatives'])})")
            ref, cls = ingest_qid(qid, existing_by_qid, existing_ids, report)
        except Exception as e:                       # noqa: BLE001
            print(f"  FAILED: {type(e).__name__}: {e}")
            report["dropped"].append(f"{term}: fetch failed — {e}")
            continue
        existing_ids.add(ref["id"])
        referents.append(ref)
        claims.extend(cls)
        print(f"  {ref['label']}  ->  {ref['id']}  [{ref['kind']}]")
        print(f"  subjects: {', '.join(ref.get('subjects') or []) or '(none inferred)'}"
              f"   claims kept: {len(cls)}")
        for c in cls:
            print(f"    {fmt_ybp(c['earth_time_start']):>12} +/-{fmt_ybp(c['time_precision']):<10} "
                  f"kt{c['knowledge_time']} [{c['status_timeline'][0]['status']:10}] "
                  f"{c['asserted_by'][:52]}")
            print(f"    {'':12}  doi:{c['_doi'] or '—'}  via {c['_resolved_via']}  "
                  f"cited-by {c['_cited_by']}")

    out = {"referents": referents, "claims": claims, "edges": [],
           "_report": report,
           "_note": "Every claim here is _review:true with a one-entry status_timeline. "
                    "The proposed/contested/consensus arc is NOT derivable from any API "
                    "and must be authored before merging."}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump(out, open(args.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)

    print("\n" + "=" * 68)
    print(f"referents {len(referents)}   claims {len(claims)}   -> {args.out}")
    print(f"resolved by DOI: {sum(1 for c in claims if c['_resolved_via']=='doi')}   "
          f"by title search: {sum(1 for c in claims if c['_resolved_via']=='title-search')}   "
          f"Wikidata-only: {sum(1 for c in claims if c['_resolved_via']=='wikidata-only')}")
    c = report["counts"]
    pct = 100 * c["resolved"] // max(1, c["time_statements"])
    print(f"\nWIKIDATA COVERAGE: {c['time_statements']} dated statements across "
          f"{c['referents']} items -> {c['with_reference']} carry any reference "
          f"-> {c['resolved']} resolve to a citation ({pct}%).")
    print("  Wikidata is dependable for identity, coordinates and labels.")
    print("  It is NOT a source of sourced dates: most date statements cite nothing.")

    if report["links"]:
        print(f"\nADOPTED BY EXISTING REFERENTS ({len(report['links'])}) — confirm each:")
        for l in report["links"]:
            print("  -", l)

    print(f"\nDROPPED ({len(report['dropped'])}) — mostly the no-source-no-fact rule:")
    for d in report["dropped"][:12]:
        print("  -", d)
    if report["needs_subjects"]:
        print(f"\nNEEDS SUBJECTS ({len(report['needs_subjects'])}):")
        for s in report["needs_subjects"]:
            print("  -", s)
    if report["no_geometry"]:
        print(f"\nNO COORDINATES: {', '.join(report['no_geometry'])}")
    print("\nNext: author the status_timeline for each claim, then merge into "
          "src/graph.json and re-run tools/validate_graph.py.")


if __name__ == "__main__":
    main()
