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

Two gates, and neither is optional.

`tools/smoke_test.py` loads the built page in headless Chromium over a local
server and asks it, from outside, whether it works: did `boot()` report
finishing, is `requestAnimationFrame` actually ticking *and driving* (rather
than the worker heartbeat quietly covering for a loop that never started), is
the element under the middle of the stage really the canvas, does dragging
rotate the globe, does a pinch zoom it, does a cancelled pinch strand the
gesture, does the K–Pg link still appear in 1980 and harden in 1991, does a
shared URL restore the view, can a hostile hash poison it. 41 checks, wired into
`build.py`, exits non-zero.

It exists because this project lost an entire build to a boot failure that
nothing detected: a legend swatch read the wrong palette key, `undefined` reached
`withAlpha`, and the `TypeError` landed three lines above
`requestAnimationFrame(frame)`, so the loop was never started. Every check up to
that point called the draw functions directly and read back canvas pixels, which
passes perfectly against a page that displays nothing. Each assertion in the file
has been verified to fail against a deliberately reintroduced bug.

`tools/validate_graph.py` is a gate, not a formatter. It checks referential
integrity, schema discipline and coordinate sanity, and it asserts the product's
own promises: that the required cross-domain causal chain is wired end to end,
that the six disputed referents really do carry rival dates, that consensus and
newest resolvers disagree somewhere, and that Chicxulub → K–Pg is absent in 1975
and live by 1985. It exits non-zero on any of those.

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
- **A UX review found twelve more, none of them implemented.** The worst is that
  `Guided path` renders entirely off the left edge on a phone, which makes the tour
  unreachable on every phone — it has no other entry point. See
  [`docs/ux-review-2026-08-03.md`](docs/ux-review-2026-08-03.md), which covers this
  site and its sibling together.

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
