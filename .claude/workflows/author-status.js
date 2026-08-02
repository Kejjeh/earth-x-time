export const meta = {
  name: 'author-status',
  description: 'Stage 4: author sourced dating claims and status timelines for ingested referents',
  whenToUse: 'After tools/ingest.py has produced src/ingested.json. Pass the referent ids as args, or omit to do them all.',
  phases: [
    { title: 'Author', detail: 'one agent per referent: find the dating literature, write claims' },
    { title: 'Verify', detail: 'adversarial citation check on each authored set' },
  ],
}

/* Stage 4 exists because stages 1-3 cannot do this part. Wikidata supplies
   identity, coordinates and labels reliably, but across ten well-known items it
   yielded six dated statements, three with any reference, and one resolving to a
   citation. And the proposed -> contested -> consensus arc is in no database at
   all: citation volume does not encode agreement, since a contested paper is
   cited heavily precisely because it is contested. So this stage reads the
   literature. */

const CONVENTIONS = `
=== EARTH x TIME SCHEMA (obey exactly) ===

TIME: all earth times are FLOAT YEARS BEFORE 2025 CE ("ybp").
  Earth formation 4.54e9 | K-Pg 6.6e7 | printing press (1440 CE) 585 | today 0.
  earth_time_start = the OLDER bound, earth_time_end = the YOUNGER bound.
  For an instant, set them equal. time_precision = the +/- in years.

CLAIM:
{
  "id": "clm_<snake>",              // unique
  "about": "<referent id given to you>",
  "statement": "one concise sentence, <=140 chars, no citation inside",
  "type": "dating" | "existence" | "location" | "causal" | "interpretation",
  "earth_time_start": <float ybp>, "earth_time_end": <float ybp>,
  "time_precision": <float years>,
  "geometry": {"mode":"point"|"region"|"global"|"none",
               "lat":<float|null>,"lng":<float|null>,"radius_km":<float|null>},
  "coords_are_modern": true,
  "subjects": [">=2 from: geology, biology, evolution, chemistry, human_history, astronomy"],
  "zoom_band": [<int 0-10>, <int 0-10>],   // 0 = visible at the full 4.54 Gyr view
  "significance": <int 1-5>,
  "asserted_by": "Author(s) Year, Venue",
  "knowledge_time": <int CE 1650-2025>,
  "doi": "<doi or null>",
  "status_timeline": [ {"knowledge_time":<int CE>, "status":"proposed"|"contested"|"consensus"|"superseded",
                        "source":"Author Year, Venue - what happened"} ]
}

HARD RULES
1. NEVER invent a citation. If you cannot confirm a paper exists with that
   author, year and venue, either search until you can, or write an honest vague
   attribution like "stratigraphic consensus, 1990s" and say so. A vague honest
   source is CORRECT; a fabricated precise one is a product-killing failure.
2. Every claim needs asserted_by AND knowledge_time. No exceptions.
3. status_timeline is ordered oldest-first and its FIRST entry's knowledge_time
   MUST equal the claim's knowledge_time.
4. Where the literature genuinely disagrees, emit 2-3 COMPETING dating claims
   with different earth_time_start, different asserted_by and different
   knowledge_time. Disagreement is the point of this product, not a defect.
5. If a position was once accepted and later overturned, emit it with a
   status_timeline running consensus -> contested -> superseded. Scrubbing
   knowledge-time backwards must resurrect it.
6. Coordinates must be the real type locality, outcrop or site.
`

const SCHEMA = {
  type: 'object',
  required: ['claims'],
  properties: {
    claims: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'about', 'statement', 'type', 'earth_time_start', 'earth_time_end',
          'time_precision', 'geometry', 'coords_are_modern', 'subjects', 'zoom_band',
          'significance', 'asserted_by', 'knowledge_time', 'status_timeline'],
        properties: {
          id: { type: 'string' }, about: { type: 'string' }, statement: { type: 'string' },
          type: { type: 'string', enum: ['dating', 'existence', 'location', 'causal', 'interpretation'] },
          earth_time_start: { type: 'number' }, earth_time_end: { type: 'number' },
          time_precision: { type: 'number' },
          geometry: {
            type: 'object', required: ['mode'],
            properties: {
              mode: { type: 'string', enum: ['point', 'region', 'global', 'none'] },
              lat: { type: ['number', 'null'] }, lng: { type: ['number', 'null'] },
              radius_km: { type: ['number', 'null'] },
            },
          },
          coords_are_modern: { type: 'boolean' },
          subjects: {
            type: 'array', minItems: 2,
            items: { type: 'string', enum: ['geology', 'biology', 'evolution', 'chemistry', 'human_history', 'astronomy'] },
          },
          zoom_band: { type: 'array', minItems: 2, maxItems: 2, items: { type: 'number' } },
          significance: { type: 'number' },
          asserted_by: { type: 'string' },
          knowledge_time: { type: 'number' },
          doi: { type: ['string', 'null'] },
          status_timeline: {
            type: 'array', minItems: 1,
            items: {
              type: 'object', required: ['knowledge_time', 'status', 'source'],
              properties: {
                knowledge_time: { type: 'number' },
                status: { type: 'string', enum: ['proposed', 'contested', 'consensus', 'superseded'] },
                source: { type: 'string' },
              },
            },
          },
        },
      },
    },
    notes: { type: 'string' },
  },
}

const VERIFY = {
  type: 'object',
  required: ['verdicts', 'corrected'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['claim_id', 'severity', 'issue', 'action'],
        properties: {
          claim_id: { type: 'string' },
          severity: { type: 'string', enum: ['fabrication', 'wrong', 'imprecise', 'ok'] },
          issue: { type: 'string' }, action: { type: 'string' },
        },
      },
    },
    corrected: SCHEMA,
  },
}

const targets = Array.isArray(args) && args.length ? args : null

phase('Author')

const INGESTED = 'src/ingested.json'

const results = await pipeline(
  targets || ['__ALL__'],
  (t) => agent(
    `${CONVENTIONS}\n\n` +
    `Read ${INGESTED} in the repository. It was produced by tools/ingest.py from ` +
    `Wikidata and carries referents with confirmed QIDs, labels and coordinates, ` +
    `but almost no sourced dates — Wikidata's date statements mostly cite nothing.\n\n` +
    (t === '__ALL__'
      ? `Work on EVERY referent in that file.\n`
      : `Work ONLY on the referent whose id is "${t}".\n`) +
    `\nFor each referent:\n` +
    `1. Use WebSearch to find the primary literature that DATES it. Prefer the ` +
    `paper that established the currently accepted figure, plus any earlier ` +
    `figure it displaced, plus any live rival.\n` +
    `2. Confirm every citation exists — author, year, venue. Where you can, give ` +
    `the DOI in the "doi" field; you can check one at ` +
    `https://api.crossref.org/works?query.bibliographic=<title>\n` +
    `3. Write the claims, including the status_timeline transitions and what ` +
    `caused each one.\n` +
    `4. Reuse the referent's existing coordinates and QID-derived id exactly. Do ` +
    `not invent new referent ids.\n\n` +
    `Return the structured object. No prose.`,
    { label: `author:${t}`, phase: 'Author', schema: SCHEMA, effort: 'high' }
  ),
  (authored, t) => {
    if (!authored || !authored.claims || !authored.claims.length) return null
    return agent(
      `You are an adversarial fact-checker for a knowledge graph that markets ` +
      `itself on epistemic honesty. A fabricated citation is product-killing, so ` +
      `hunt for those specifically.\n\n${CONVENTIONS}\n\n` +
      `Authored claims:\n${JSON.stringify(authored)}\n\n` +
      `1. For EVERY citation in asserted_by and in status_timeline sources, use ` +
      `WebSearch to confirm the paper exists with that author, year and venue. ` +
      `Anything you cannot confirm is severity "fabrication" — replace it in the ` +
      `corrected output with the correct citation or an honest vague attribution.\n` +
      `2. Check every date against the literature. Flag anything off by more than ` +
      `its own time_precision. Watch for right-paper-wrong-number: a real paper ` +
      `cited for a figure it never published.\n` +
      `3. Check every lat/lng lands at the named site, on the right continent.\n` +
      `4. Check schema discipline: >=2 subjects from the vocabulary; ` +
      `status_timeline ordered oldest-first with its first knowledge_time equal to ` +
      `the claim's; earth_time_end <= earth_time_start; knowledge_time in [1650,2025].\n` +
      `5. Confirm any referent with rival datings really would render as a band.\n\n` +
      `Return "verdicts" (every claim with an issue, plus spot-checks on the most ` +
      `load-bearing) and "corrected": the COMPLETE fixed set, not a diff.`,
      { label: `verify:${t}`, phase: 'Verify', schema: VERIFY, effort: 'high' }
    ).then(v => ({ target: t, authored, verified: v }))
  }
)

const clean = results.filter(Boolean)
const claims = []
const audit = []
for (const r of clean) {
  const data = (r.verified && r.verified.corrected) ? r.verified.corrected : r.authored
  claims.push(...(data.claims || []))
  const issues = ((r.verified && r.verified.verdicts) || []).filter(v => v.severity !== 'ok')
  audit.push({ target: r.target, claims: (data.claims || []).length, issues })
  log(`${r.target}: ${(data.claims || []).length} claims, ${issues.length} corrected`)
}

const fabrications = audit.flatMap(a => a.issues.filter(i => i.severity === 'fabrication'))
log(`TOTAL ${claims.length} claims; ${fabrications.length} fabricated citations caught`)

return { claims, audit }
