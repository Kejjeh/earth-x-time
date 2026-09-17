"""Offline regressions for tools/check_sources.py. No network, no graph.

    python tools/test_check_sources.py
    python tools/check_sources.py --offline    # runs these too
    python tools/validate_graph.py             # and these

Each case is a way the tool could manufacture or misplace an identifier, or
let a bibliographic fact leak into a claim-level one. They are fixtures, not
real claims; the graph is never read.
"""
import copy, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_sources as cs  # noqa: E402

SMITH_A = {"first_author": "Smith", "year": 2010, "container": "Nature", "short_container": "Nature",
           "title": "Isotopic evidence for an early ocean on the primitive Earth", "checked": "2026-09-17"}
SMITH_B = {"first_author": "Smith", "year": 2010, "container": "Nature", "short_container": "Nature",
           "title": "A second, unrelated result from the same year and journal", "checked": "2026-09-17"}
JONES = {"first_author": "Jones", "year": 2011, "container": "Science", "short_container": "Science",
         "title": "Something else entirely, by someone else, a year later", "checked": "2026-09-17"}


def claim(cid, cite, doi=None, status=None):
    c = {"id": cid, "asserted_by": cite, "statement": "x"}
    if doi:
        c["doi"] = doi
    if status:
        c["source_status"] = status
    return c


def run():
    failed = []

    def check(name, ok, detail=""):
        print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))
        if not ok:
            failed.append(name)

    # 1. Two works by the same first author, same year, same journal; only one
    #    is in the graph. A bare "author year, journal" citation must not be
    #    completed with the one we happen to hold, and neither must a citation
    #    that spells out the OTHER paper's title.
    works = {"10.1000/a": SMITH_A}
    claims = [claim("has_doi", "Smith, J. et al. (2010) Nature 466", "10.1000/a"),
              claim("bare", "Smith et al. 2010, Nature"),
              claim("other_title", "Smith et al. 2010, Nature — " + SMITH_B["title"]),
              claim("this_title", "Smith et al. 2010, Nature — " + SMITH_A["title"])]
    log = []
    lifts = {c["id"]: (d, r) for c, d, r in cs.lift_dois(claims, works, log)}
    check("same author/year/journal, bare citation: no DOI lifted", "bare" not in lifts, str(lifts))
    check("same author/year/journal, other paper's title: no DOI lifted", "other_title" not in lifts, str(lifts))
    check("full title + journal of the held work: lifted by the title rule",
          lifts.get("this_title") == ("10.1000/a", "title"), str(lifts))
    # A near-identical string (one character off) is not "identical".
    claims2 = [claim("has_doi", "Smith et al. 2010, Nature", "10.1000/a"),
               claim("near", "Smith et al. 2010, Nature.")]
    lifts2 = cs.lift_dois(claims2, works, [])
    check("a near-identical citation string is not an identical one", lifts2 == [], str(lifts2))
    # With BOTH Smith papers present the title rule still picks by title, and a
    # citation carrying neither title gets nothing.
    works2 = {"10.1000/a": SMITH_A, "10.1000/b": SMITH_B}
    claims3 = [claim("a", "Smith 2010 Nature", "10.1000/a"), claim("b", "Smith 2010 Nature", "10.1000/b"),
               claim("wants_b", "Smith et al. 2010, Nature — " + SMITH_B["title"]),
               claim("bare", "Smith et al. 2010, Nature")]
    lifts3 = {c["id"]: (d, r) for c, d, r in cs.lift_dois(claims3, works2, [])}
    check("two held works, title names the second: lifts the second",
          lifts3.get("wants_b") == ("10.1000/b", "title") and "bare" not in lifts3, str(lifts3))
    # A short title is not evidence.
    works3 = {"10.1000/c": dict(SMITH_A, title="Reply")}
    claims4 = [claim("c", "Smith 2010, Nature Reply", "10.1000/c"), claim("d", "Smith et al. 2010, Nature — Reply")]
    check("a short title is not identity evidence", cs.lift_dois(claims4, works3, []) == [])

    # 2. A DOI reused beside a different citation. The record is Smith 2010;
    #    the claim cites Jones 2011. The DOI-wide fact "this DOI resolves" is
    #    true; the per-claim fact is not, and the validator must say so.
    claims5 = [claim("ok", "Smith et al. 2010, Nature", "10.1000/a"),
               claim("reused", "Jones 2011, Science", "10.1000/a")]
    bad = cs.consistency(claims5, works)
    check("a DOI beside a different citation fails validation",
          any(b.startswith("reused:") and "Jones" in b for b in bad) and not any(b.startswith("ok:") for b in bad),
          str(bad))
    check("per-claim state: the same DOI is a match on one claim and a mismatch on the other",
          cs.ref_state(claims5[0], works) == "author_year" and cs.ref_state(claims5[1], works) == "mismatch")
    check("a lift whose record does not match the citation is refused at write time",
          cs.apply_lifts([claims5[1]], works, [(claims5[1], "10.1000/a", "identical")], []) == [])
    # Accents: Crossref says Claoué-Long, the citation says Claoue-Long.
    w_acc = dict(SMITH_A, first_author="Claoué-Long", year=1992)
    check("author match is accent-insensitive",
          cs.author_year_match(w_acc, "Claoue-Long et al. 1992, Nature"))
    check("a record with an error never matches", not cs.author_year_match({"error": "HTTP 404"}, "Smith 2010"))
    check("the cited work may be named mid-string ('as summarised in Smith 2010')",
          cs.author_year_match(SMITH_A, "Field consensus, 1990s-2010s, as summarised in Smith & Jones 2010, Nature"))
    check("surname of a different author does not match even with the right year",
          not cs.author_year_match(SMITH_A, "Smithson et al. 2010, Nature")
          and not cs.author_year_match(SMITH_A, "Jones 2010, citing Smith 2009"))
    check("a DOI with no record is 'unchecked', not resolving",
          cs.ref_state(claim("x", "Smith 2010", "10.1000/zzz"), works) == "unchecked")

    # 3. Nothing about resolution touches the content-check status. Lift and
    #    apply over a mixed set: source_status is identical before and after,
    #    key for key, and the only field that changed is `doi`.
    claims6 = [claim("src", "Smith et al. 2010, Nature", "10.1000/a", "checked"),
               claim("dup_unchecked", "Smith et al. 2010, Nature"),
               claim("inline_checked", "Smith 2010, Nature, doi 10.1000/a.", status="checked"),
               claim("titled", "Smith et al. 2010, Nature — " + SMITH_A["title"]),
               claim("unrelated", "Jones 2011, Science")]
    before = copy.deepcopy(claims6)
    applied = cs.apply_lifts(claims6, works, cs.lift_dois(claims6, works, []), [])
    check("three lifts land (identical, inline, title) and the unrelated claim gets nothing",
          sorted(r for _, _, r in applied) == ["identical", "inline", "title"]
          and not claims6[4].get("doi"), str([(c["id"], r) for c, _, r in applied]))
    check("source_status is untouched by lifting",
          [c.get("source_status") for c in claims6] == [c.get("source_status") for c in before])
    changed = {k for a, b in zip(before, claims6) for k in set(a) | set(b) if a.get(k) != b.get(k)}
    check("only the doi field changed", changed <= {"doi"}, str(changed))
    check("a resolving DOI on an unchecked claim leaves it unchecked",
          cs.ref_state(claims6[1], works) == "author_year" and claims6[1].get("source_status") is None)

    print(f"regressions: {'all passed' if not failed else str(len(failed)) + ' FAILED'}")
    return failed


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
