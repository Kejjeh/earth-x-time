# Earth × Time

A spatiotemporal knowledge graph with two clocks at right angles.

**Earth-time** runs along the bottom: when things happened, 4.54 Ga to now, on a
log axis with a real stratigraphic ribbon under it. **Knowledge-time** runs up
the right-hand edge: when we came to believe them, 1650 to 2025. Both scrub
independently. Moving knowledge-time rewires the causal graph — links appear
when they were first proposed, harden when they reached consensus, and grey out
when superseded.

Open `earth-x-time.html` in a browser. No server, no network, no build step to
run it.

## Try these

| | |
|---|---|
| Drag knowledge-time to **1975**, then to **1991** | The Chicxulub → K–Pg link does not exist in 1975. It appears in 1980 as *proposed*, is *contested* through the eighties, and hardens to *consensus* in 1991 when the crater is confirmed. Meanwhile Newell's sea-level explanation dies. |
| Drag to **1880** | The Earth becomes 98 million years old. Kelvin's cooling calculation is the best-supported claim in 1880, and the whole timeline collapses with it. Radioactivity breaks his ceiling in 1903. |
| Scrub **1950 → 2025** with *Peopling of the Americas* selected | Clovis-first holds as consensus, then collapses: 13 ka → 14.6 ka (Monte Verde) → 15.5 ka → 16.6 ka. |
| Select **The Origin of Life** | Draws as a band 1.1 billion years wide, not a point. Five rival datings, solid marker for the winner, hollow ones for the rest. |
| Switch resolver to **Newest** | Ten referents move. Origin of life jumps from 3.43 Ga to 4.28 Ga. |
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

## Building

`src/` is concatenated in filename order and the bulky assets are injected:

```bash
python tools/build.py
```

Writes `earth-x-time.html` (standalone) and `artifact.html` (body-only, for a
host that supplies its own `<head>`). ~415 KB, entirely self-contained.

| Asset | Source | Generator |
|---|---|---|
| Coastlines, plate boundaries | Natural Earth 110m land, PB2002 | `tools/fetch_coast.py` |
| Chronostratigraphy | Macrostrat international timescale — real ICS colours and current boundary ages | `tools/fetch_ics.py` |
| Fonts | IBM Plex Sans / Condensed / Mono, latin subset, inlined as data URIs | `tools/fetch_fonts.py` |
| Seed graph | `src/graph.json`, validated and merged from generated clusters + `src/foundations.json` | `tools/validate_graph.py` |

`tools/validate_graph.py` is a gate, not a formatter. It checks referential
integrity, schema discipline and coordinate sanity, and it asserts the product's
own promises: that the required cross-domain causal chain is wired end to end,
that the six disputed referents really do carry rival dates, that consensus and
newest resolvers disagree somewhere, and that Chicxulub → K–Pg is absent in 1975
and live by 1985. It exits non-zero on any of those.

## Known gaps

- **Citations are not independently verified.** The adversarial fact-checking
  pass that was supposed to confirm every author/year/venue against the
  literature did not complete. Authors were instructed to search before writing
  and to prefer an honest vague attribution over a fabricated precise one, and
  the ten claims in `src/foundations.json` are hand-written from canonical works.
  But treat the citations as plausible rather than checked.
- **Deep-time coordinates are modern coordinates.** Every claim carries
  `coords_are_modern: true` and the detail panel says so. Chicxulub is drawn
  where the Yucatán is now. Plate reconstruction is not implemented; the flag
  exists so it can be added without a migration.
- **175 claims, not the 50–70 specified.** The generated clusters over-produced.
  The extra depth is additive, but it is more than was asked for.
- **Not React.** See below.

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
