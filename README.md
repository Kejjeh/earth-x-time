# Earth × Time

A spatiotemporal knowledge graph with two clocks at right angles.

**Earth-time** runs along the bottom: when things happened, 4.54 Ga to now, on a
log axis with a real stratigraphic ribbon under it. **Knowledge-time** runs up
the right-hand edge: when we came to believe them, 1650 to 2026. Both scrub
independently. Moving knowledge-time rewires the causal graph — links appear
when they were first proposed, harden when they reached consensus, and grey out
when superseded.

Open `earth-x-time.html` in a browser. No server, no network, no build step to
run it. 275 claims about 57 referents, wired by 52 edges.

Every view has a URL. The two clocks, the rotation, the zoom, the resolver mode,
the filter and the selection all live in `location.hash`, so
`#k=1975&s=kpg_extinction` is a link rather than a set of instructions.

## Try these

| | |
|---|---|
| Drag knowledge-time to **1975**, then to **1991** | The Chicxulub → K–Pg link does not exist in 1975. It appears in 1980 as *proposed*, is *contested* through the eighties, and hardens to *consensus* in 1991 when the crater is confirmed. Meanwhile Newell's sea-level explanation dies. |
| Drag to **1880** | The Earth becomes 98 million years old. Kelvin's cooling calculation is the best-supported claim in 1880, and the whole timeline collapses with it. Radioactivity breaks his ceiling in 1903. |
| Scrub **1950 → 2025** with *Peopling of the Americas* selected | Clovis-first holds as consensus, then collapses: 13 ka → 14.6 ka (Monte Verde) → 15.5 ka → 16.6 ka. |
| Select **The Origin of Life** | Draws as a band 1.1 billion years wide, not a point. Five rival datings, solid marker for the winner, hollow ones for the rest. |
| Switch resolver to **Newest** | 28 of the 57 referents move. Origin of life jumps from 3.43 Ga to 4.28 Ga. |
| Double-click a **field of study** | Isolates it, and keeps the causal links that leave it. |

## Structure

Everything renders from one function. `queryFacts(axisState)` in
`src/30_model.js` takes the whole axis state — earth-time window, knowledge-time,
subject filter, focus, resolver mode, zoom — and returns what is visible. The
globe, timeline, knowledge rail, detail panel, caption and diff view all read
its output. There is no second filtering path.

A referent's position on the timeline is never stored. `resolve()` recomputes it
from the competing dating-claims at the current knowledge-time, in one of three
modes: best-supported, newest, or show-the-spread. It always returns the winner,
the rivals, and the provenance — never a bare number.

Three rules in there are worth knowing, because each one started as a bug:

- **Only rival datings set the band.** A claim about the *kill mechanism* of an
  extinction is not a rival dating of it. Letting every claim that carries a date
  into the envelope inflated the K–Pg band to 12 Myr when its two actual dating
  claims agree within one.
- **Superseded claims stay visible but stop stretching the band.** They render as
  hollow dashed markers. Otherwise Kelvin's defeated 98 Ma Earth drags the
  formation of the planet forward into the Cenozoic. A consequence worth naming:
  `disputed` is knowledge-time-dependent. The K–Pg date is disputed at 1970 and
  settled at 2025, which is true.
- **An edge keeps its far endpoint on screen.** Culling a node by `zoom_band`
  silently deletes every edge that reaches it. At the default full-Earth view the
  Deccan Traps sit below the band, so the volcanism link that dies in 1991 never
  drew at all. A live edge with one end visible now pulls the other back, one hop,
  drawn small and unlabelled.

Position comes from the claim that *won the date*, including when it says
"global" — otherwise attaching Hutton's 1788 claim to the formation of the Earth
renders the planet's origin as a dot at Siccar Point.

Search reads the claims, not just the labels: "iridium", "Alvarez" and "clumped
isotopes" are how anyone who knows this material looks for it, and none of them
appear in a referent's name. A result row shows its date **as resolved at the
current knowledge-time**, so a search can answer "we did not know that yet";
choosing such a row moves knowledge-time to the year the claim was made.

## Building

`src/` is concatenated in filename order and the bulky assets are injected:

```bash
python tools/build.py
```

Writes `earth-x-time.html` (standalone) and `artifact.html` (body-only, for a
host that supplies its own `<head>`). ~720 KB, entirely self-contained, and the
build refuses to finish if the smoke test fails.

Each generator writes the `assets/` file the build reads, and refuses to write
at all unless everything it needed arrived — a half-downloaded coastline would
otherwise replace the shipped one with an empty payload and the globe would come
up with no land on it. Two of them used to write into `tools/` instead, where
nothing reads, so regenerating printed byte counts, exited 0, and changed
nothing.

| Asset | Source | Generator |
|---|---|---|
| Coastlines, plate boundaries | Natural Earth 110m land, PB2002 | `tools/fetch_coast.py` |
| Chronostratigraphy | Macrostrat international timescale — real ICS colours and current boundary ages | `tools/fetch_ics.py` |
| Fonts | IBM Plex Sans / Condensed / Mono, latin subset, inlined as data URIs | `tools/fetch_fonts.py` |
| Seed graph | `src/graph.json`, validated and merged from generated clusters + `src/foundations.json` | `tools/validate_graph.py` |

## Ingesting new facts

```bash
python tools/ingest.py "Chicxulub crater" "Great Oxidation Event"
```

Takes Wikidata items by name or QID, resolves every reference through Crossref,
and emits schema-valid claims with DOIs to `src/ingested.json` for review. Names
are accepted because hand-typed QIDs fail silently — Q13415 is Beta Canis
Majoris, not the Chicxulub crater, and an ingester handed the wrong number will
cheerfully emit a well-formed claim about a star. It prints what it matched.

It enforces the product's own rule without mercy: **a statement carrying no
resolvable reference produces no claim.** Which surfaces the main finding —
across ten well-known items, 6 dated statements, 3 carrying any reference, and
**1 resolving to a citation.** Wikidata is dependable for identity, coordinates,
labels and subject hints. It is not a source of *sourced dates*.

Referents adopt a QID, so re-running merges instead of minting
`deccan_traps_2` beside `deccan_traps`. Matching is by QID first, then label.

The output file is a review queue, so it is merged into rather than replaced:
ingesting one more item keeps the work already in it, and a run that ingested
nothing refuses to write at all rather than leaving an empty file behind. It
used to do neither — `--out` defaults to `src/ingested.json`, the write was
unconditional, and one mistyped name emptied ten referents and exited 0.

A failure to reach Wikidata is reported separately from the no-source-no-fact
rule, and a run with any failure exits non-zero. Those are different facts: one
is this tool's own discipline working, the other is not having looked.

**What it deliberately does not do** is author the `status_timeline`. I tested
the obvious idea — read consensus formation off citation history — and it fails:

```
Alvarez 1980, citations/year   1989:80  1990:67  1991:54  1992:76  1993:71
```

Citations *dip* across the 1991 Chicxulub confirmation. A contested paper is
cited heavily *because* it is contested, so citation volume measures attention,
not agreement. Every emitted claim gets a one-entry timeline and `_review: true`;
the proposed → contested → consensus arc has to be authored.

## Validation

Three gates, and none of them is optional.

`tools/smoke_test.py` loads the built page in headless Chromium over a local
server and asks it, from outside, whether it works: did `boot()` report
finishing, is `requestAnimationFrame` actually ticking *and driving* (rather
than the worker heartbeat quietly covering for a loop that never started), is
the element under the middle of the stage really the canvas, does dragging
rotate the globe, does a pinch zoom it, does a cancelled pinch strand the
gesture, does the K–Pg link still appear in 1980 and harden in 1991, does a
shared URL restore the view, can a hostile hash poison it, is a marker only as
clickable as it is big, do the rival markers agree with the band they sit in, and
does toggling the basemap reach the URL, does a link to something not yet known
explain itself rather than reading as empty, does a hop inside the panel land on
something that is actually drawn, does revealing something already on screen
leave the window alone, is `Compare eras` as modal as it declares itself, and do
the resolver's own headline numbers still hold.

Then it opens a second context at 390x844 with real touch and asks the phone
build the questions the desktop one cannot: can a finger reach every control on
the stage, does tapping a marker put its panel where you can see it, does
choosing a search result fly a globe that is on screen, is the globe's focus
ring inside its own clipping box, does a swipe up scroll the page rather than
rewrite the view — and, because that fix trades something away, do a horizontal
drag, a tap on the rail and a two-finger pinch all still do what they did.

Then it loads the page once more in each theme and measures the contrast of
every small explanatory string against its real background — photographing the
painted pixels behind the stage overlays, because a computed `background-color`
cannot see the gradient they sit on. And it asks the page where the knowledge
rail ends, and compares that with what the Python tools read, whether every
subject chip counts exactly the marks it accounts for, and whether Replay
sweeps the rail the page actually has, and — by sampling the disc across
forty-eight rotations in Chart mode — whether the filled coastline still covers
about the 29% of Earth that is land rather than swallowing the globe, whether
the announcement a screen reader hears is a sentence rather than the whole
panel, whether a held selection speaks when its date moves and stays quiet when
it does not, and whether the causal graph can be walked from a keyboard.
77 checks, wired into `build.py`, exits non-zero.

It exists because this project lost an entire build to a boot failure that
nothing detected: a legend swatch read the wrong palette key, `undefined` reached
`withAlpha`, and the `TypeError` landed three lines above
`requestAnimationFrame(frame)`, so the loop was never started. Every check up to
that point called the draw functions directly and read back canvas pixels, which
passes perfectly against a page that displays nothing. Each assertion in the file
has been verified to fail against a deliberately reintroduced bug.

`tools/check_no_local_paths.py` refuses any commit whose staged content carries
an absolute path out of somebody's home directory — `C:\Users\…`, `/Users/…`,
`/home/…`. It exists because one nearly shipped: a citation in
`docs/ux-review-2026-08-03.md` was written by an agent that had been handed
absolute paths in its brief, and it was caught by hand, which is not a control.
Obvious placeholders (`/home/you/…`) still pass. The hook is versioned in
`.githooks/` so it is reviewable in the diff; a fresh clone arms it once:

```bash
git config core.hooksPath .githooks
```

Run it over everything already tracked with `--all`. Its cases — eight leak
shapes, seven that must not fire, and the staged blob read both ways — are
verified against a staged file and a real `git commit`, not against the checker
called directly, and the smoke test drives those commits in a throwaway repo on
every build.

It matches an absolute path token and then looks for a home segment inside it,
rather than matching the segment directly. The first version did the latter,
with a lookbehind to keep `docs/home/index.md` from firing, and that lookbehind
also required the segment to sit at the root: `/mnt/c/Users/name`,
`/c/Users/name`, `/var/home/name` and `\\server\Users\name` all committed
clean. Git Bash renders `C:\Users\name` as `/c/Users/name`, so the checker had
been missing the shape of the exact incident it exists for.

The knowledge-time bounds are declared once, in `src/20_core.js`, and
`tools/knowledge_time.py` reads them out of it — nothing mirrors them by hand.
They had been typed out in seven places, and when the ceiling moved from 2025 to
2026 so a 2026 paper's status entry could fire, four were left behind:
`stage4_merge.py` refused a well-formed 2026 claim, `ingest.py` silently
rewrote a 2026 citation's year to 2025, and the rail's own button and ARIA
range still advertised the old year. Moving the ceiling is one edit now, and
the smoke test compares the running page with what the tools read.

Two tools merge authored content into `src/graph.json`, and they now agree on
the safe default: both `tools/apply_patch.py` and `tools/stage4_merge.py` are a
dry run unless you pass `--write`. `stage4_merge.py` used to be the other way
round, so confusing the two wrote to the committed graph when you meant to see
a plan. Its own per-claim check also now covers `significance`, `zoom_band` and
`time_precision` — all three were in its required-fields list and none of their
values was ever looked at, against a docstring promising the same rules the
validator enforces. It points at the validator before the build, because
`build.py` does not validate.

`tools/validate_graph.py` is a gate, not a formatter. It checks referential
integrity, schema discipline and coordinate sanity, and it asserts the product's
own promises: that the required cross-domain causal chain is wired end to end,
that the five permanently disputed referents really do carry rival dates as
understood in 2026, that the K–Pg date is disputed in 1970 and settled now, that
consensus and newest resolvers disagree somewhere, and that Chicxulub → K–Pg is
absent in 1975 and live by 1985. It exits non-zero on any of those.

Its offshore-coordinate check used to warn about the same 29 points on every
run, asking for a verification it gave nowhere to record — so it said the same
thing forever, and a genuine typo would have been item 30 in a list of 29
known-good ones. The triage is now in the file: six sites, each with its reason
and its measured distance to the shipped coastline. Four are on land and inside
the ~46 km a 0.42° simplification can move a coast (Siccar Point 1.2 km,
Nuvvuagittuq 2.9, the Newfoundland base-Cambrian section 4.5, Senlac Hill ~20);
Chicxulub's crater centre is genuinely half offshore; and Santorini reads 182 km
out because the island is not in the 110m dataset at all. Anything else is
reported with its distance, which says whether it is a headland or a sign error.

Those assertions run through a `resolve()` that mirrors `src/30_model.js` line
for line, because for a while they did not, and a gate that asks a different
question is not a gate: it reported 24 resolver movers where the page moves 28,
and reported K–Pg carrying three rival dates with a 1.04 Myr spread where the
page settles it to one date and a 22 kyr envelope. The two implementations are
now pinned to the same figures from both ends — the smoke test asks the browser
for the same numbers.

## Known gaps

- **Citations are verified for the 2026 additions, and plausible-but-unchecked
  for the rest.** The 37 claims added when the causal graph was wired went
  through an adversarial pass that searched for every author, year, venue and
  DOI: 35 proposed items were dropped, including one citation that does not
  exist and four papers that do not say what they were quoted as saying. The
  earlier 238 did not get that treatment. The authors were told to search before
  writing and to prefer an honest vague attribution to a fabricated precise one,
  and the ten claims in `src/foundations.json` are hand-written from canonical
  works — but treat those as plausible rather than checked.
- **Deep-time coordinates are modern coordinates.** Every claim carries
  `coords_are_modern: true` and the detail panel says so. Chicxulub is drawn
  where the Yucatán is now. Plate reconstruction is not implemented; the flag
  exists so it can be added without a migration.
- **275 claims, not the 50–70 specified.** The generated clusters over-produced,
  and a later pass wiring the causal graph added more. The extra depth is
  additive, but it is far more than was asked for.
- **Eight causal claims still carry no edge.** Each was examined and dropped for
  a stated reason — the cited paper does not assert the relation, or the correct
  endpoint is a referent that does not exist yet. They render in the panel and
  say nothing to the graph.
- **Not React.** See below.
- **A UX review found twelve items; items 1 and 4 and both halves of item 10
  that concern this site are done, the rest are not.** The phone blockers are fixed — the stage control
  strip no longer runs off the left edge (`Guided path` was entirely off-screen,
  and it is the tour's only entry point), a tap on a marker now scrolls its
  panel into view, a chosen search result no longer flies a globe that is above
  the viewport, and the globe's focus ring is painted inside its own clipping
  box instead of being clipped away. All four are asserted by the phone section
  of the smoke test. A hop inside the panel now goes through the same gate
  `chooseResult` does — and that gate no longer throws away a window someone
  panned to in order to reveal something already inside it — and `Compare eras`
  now makes the rest of the page `inert` instead of only claiming to. A swipe up
  scrolls the page instead of slamming the globe to the pole or moving
  knowledge-time by forty-seven years — which costs the rail's vertical
  drag-scrub on touch, deliberately: tap-to-set, the arrow keys and `Home`/`End`
  all remain, and the globe still tilts under two fingers. Every small
  explanatory string now clears WCAG AA in both themes and over both basemaps,
  worst case 5.12:1, where the worst case used to be 2.74:1 — that one was
  broader than the review said, because `--chalk-faint` got *lighter* in light
  mode and so failed in the dark theme too. The live region is a one-line status
  node now rather than an 8.9 KB panel re-announced 226 times across one Replay,
  and the causal graph keeps focus so it can be walked from a keyboard.

  One claim in the review does not reproduce and nothing was changed for it:
  scrubbing does **not** throw the panel back to the top. `scrollTop` belongs to
  the element rather than to its children and survives an `innerHTML`
  replacement — measured holding at 1662 while `scrollHeight` grew 2097 → 4049
  across 1950 → 2025.

  Still open: the knowledge-rail landmarks of item 6, naming the referents that
  are off screen (item 7), and DOI links on `asserted_by` (item 12). See
  [`docs/ux-review-2026-08-03.md`](docs/ux-review-2026-08-03.md), which covers
  this site and its sibling together.

## Two deliberate departures

**Vanilla JS, not React.** The artifact CSP blocks external hosts, so React
cannot be loaded from a CDN, and inlining it would add ~140 KB to buy very
little: the globe and timeline are imperative canvas work, and only the panels
are declarative. The architecture is React-shaped regardless — unidirectional
flow from a single state object through one query into a pure render — but the
render is hand-rolled.

**Canvas 2D with a hand-written orthographic projection, not three.js.** Every
vertex is pre-projected to a unit vector once at load, so a frame costs one 3×3
matrix build plus nine multiplies per point. Measured 0.68 ms/frame for globe
and timeline together with all facts loaded — about 25× the 60 fps budget. A
WebGL globe would have been slower to make smooth and no better to look at.
