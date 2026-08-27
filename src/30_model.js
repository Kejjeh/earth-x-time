/* ============================================================================
   THE MODEL
   A referent's position on the timeline is never stored. It is recomputed from
   the competing dating-claims every time, at whatever knowledge-time is set.
   ========================================================================== */

const ACCEPT = { consensus: 3, contested: 2, proposed: 1, superseded: 0 };

/** The status of a claim as understood in year kt. null = not yet asserted. */
function statusEntryAt(claim, kt) {
  if (claim.knowledge_time > kt) return null;
  let cur = null;
  for (const e of claim.status_timeline) {
    if (e.knowledge_time <= kt) cur = e; else break;
  }
  return cur || { knowledge_time: claim.knowledge_time, status: 'proposed',
                  source: claim.asserted_by };
}
function statusAt(claim, kt) {
  const e = statusEntryAt(claim, kt);
  return e ? e.status : null;
}

/**
 * Where a referent is drawn.
 *
 * The claim that won the date decides, including when it says "global" — the
 * formation of the Earth is planet-wide, and must not be dragged to Siccar
 * Point just because Hutton's claim about it carries a real outcrop. Only fall
 * back to other claims when the winner is silent on location.
 */
function pickGeometry(live, winner) {
  const rank = { point: 3, region: 2, global: 1, none: 0 };
  if (winner && winner.claim.geometry && winner.claim.geometry.mode !== 'none') {
    return winner.claim.geometry;
  }
  let best = null;
  for (const l of live) {
    const g = l.claim.geometry;
    if (!g || g.mode === 'none') continue;
    if (!best || rank[g.mode] > rank[best.mode]) best = g;
  }
  return best || { mode: 'none', lat: null, lng: null };
}

/**
 * The resolver. Three modes, as the user chooses:
 *   consensus — highest acceptance wins; recency only breaks ties.
 *   frontier  — most recent wins, right or wrong.
 *   spread    — refuse to resolve; the band is the answer.
 * Always returns the full candidate set with provenance, never a bare number.
 */
function resolve(refId, kt, mode) {
  const all = R.byRef[refId] || [];
  const live = [];
  for (const c of all) {
    const entry = statusEntryAt(c, kt);
    if (!entry) continue;
    live.push({ claim: c, status: entry.status, since: entry.knowledge_time,
                sourceNote: entry.source, accept: ACCEPT[entry.status] });
  }
  if (!live.length) return null;

  // Only claims that actually carry a date compete for the position.
  const dated = live.filter(l => !l.claim._meta && isFinite(l.claim.earth_time_start));
  if (!dated.length) return null;
  let pool = dated.filter(l => l.claim.type === 'dating');
  if (!pool.length) pool = dated;

  const byConsensus = pool.slice().sort((a, b) =>
    b.accept - a.accept || b.claim.knowledge_time - a.claim.knowledge_time);
  const byFrontier = pool.slice().sort((a, b) =>
    b.claim.knowledge_time - a.claim.knowledge_time || b.accept - a.accept);

  const winner = mode === 'frontier' ? byFrontier[0]
               : mode === 'spread'   ? null
               : byConsensus[0];

  /* The band is the envelope of the claims actually competing for the date,
     precision included — not of every claim that happens to carry one. A claim
     about the kill mechanism of an extinction is not a rival dating of it, and
     letting it widen the band overstates the disagreement. */
  /* Superseded claims stay on screen as hollow markers, but they no longer
     stretch the band: at knowledge-time 2025, Kelvin's 98 Ma Earth is a defeated
     position, not live disagreement, and letting it set the envelope would drag
     the formation of the Earth into the Cenozoic. In 1880 it is consensus, and
     then it rightly owns the band. */
  const standing = pool.filter(l => l.status !== 'superseded');
  const envelope = standing.length ? standing : pool;

  let oldest = -Infinity, youngest = Infinity;
  for (const l of envelope) {
    const p = l.claim.time_precision || 0;
    oldest = Math.max(oldest, l.claim.earth_time_start + p);
    youngest = Math.min(youngest, Math.max(0, l.claim.earth_time_end - p));
  }

  const distinct = new Set(envelope.map(l => Math.round(l.claim.earth_time_start)));
  const disputed = distinct.size > 1;

  const pos = winner ? winner.claim.earth_time_start : (oldest + youngest) / 2;

  const subjects = [];
  for (const l of live) for (const s of l.claim.subjects)
    if (!subjects.includes(s)) subjects.push(s);

  let significance = 1, zoomMin = 10;
  for (const l of live) {
    significance = Math.max(significance, l.claim.significance || 1);
    zoomMin = Math.min(zoomMin, (l.claim.zoom_band || [0, 10])[0]);
  }

  const anyModern = live.some(l => l.claim.coords_are_modern);

  return {
    refId, live, dated, pool, winner, pos, oldest, youngest, disputed,
    alternatives: pool.filter(l => l !== winner),
    subjects, significance, zoomMin,
    geometry: pickGeometry(live, winner),
    coordsAreModern: anyModern,
    wouldDifferUnderFrontier: byConsensus[0] !== byFrontier[0] &&
      byConsensus[0].claim.earth_time_start !== byFrontier[0].claim.earth_time_start,
    frontierPos: byFrontier[0].claim.earth_time_start,
    consensusPos: byConsensus[0].claim.earth_time_start
  };
}

/* ==========================================================================
   queryFacts — the ONE query.
   Subject filter, earth-time window, map zoom and knowledge-time are not four
   features. They are one query with different axes pinned. Every control feeds
   this; every renderer reads its output.
   ========================================================================== */
function queryFacts(A) {
  const z = zoomLevel(A.win.t1 - A.win.t0);
  const items = {};
  const order = [];
  const subjectCounts = {};
  for (const s of SUBJECTS) subjectCounts[s] = 0;

  for (const id in R.referents) {
    const res = resolve(id, A.kt, A.resolver);
    if (!res) continue;                                   // not yet asserted

    const overlaps = res.youngest <= A.win.t1 && res.oldest >= A.win.t0;
    const subjectOn = res.subjects.some(s => A.subjects.has(s));
    const zoomOK = z >= res.zoomMin - 0.001 || res.significance >= 5 || A.selection === id;

    for (const s of res.subjects) if (s in subjectCounts) subjectCounts[s]++;

    items[id] = {
      id, ref: R.referents[id], res,
      inWindow: overlaps,
      subjectOn, zoomOK,
      inFocus: !A.focus || res.subjects.includes(A.focus),
      rolledUp: 0,
      visible: false, dimmed: false
    };
    order.push(id);
  }

  // part_of aggregation: a child culled by zoom folds into its parent's count.
  for (const e of GRAPH.edges) {
    if (e.type !== 'part_of') continue;
    const child = items[e.source], parent = items[e.target];
    if (child && parent && !child.zoomOK && parent.zoomOK) {
      parent.rolledUp++;
      child.aggregatedInto = e.target;
    }
  }

  for (const id of order) {
    const it = items[id];
    it.visible = it.inWindow && it.subjectOn && it.zoomOK && !it.aggregatedInto;
  }

  /* An edge is information, and culling a node by zoom silently deletes every
     edge that reaches it. That quietly hid the best thing in the dataset: at
     the default full-Earth view the Deccan Traps sit below the zoom band, so
     the volcanism link that dies in 1991 never rendered at all. If a live edge
     has one end on screen, bring the other end back — one hop only, marked so
     it can be drawn as a supporting player rather than a peer. */
  for (const e of GRAPH.edges) {
    if (e.type !== 'causal') continue;
    const claim = R.claims[e.claim_id];
    if (!claim || statusAt(claim, A.kt) === null) continue;
    const a = items[e.source], b = items[e.target];
    if (!a || !b) continue;
    for (const [seen, hidden] of [[a, b], [b, a]]) {
      if (seen.visible && !seen.viaEdge && !hidden.visible &&
          hidden.inWindow && hidden.subjectOn && !hidden.aggregatedInto) {
        hidden.visible = true;
        hidden.viaEdge = true;
      }
    }
  }

  /* Edges. An edge inherits the status timeline of the claim that asserts it,
     so it appears when that claim was first made and greys out when superseded. */
  const edges = [];
  for (const e of GRAPH.edges) {
    const claim = R.claims[e.claim_id];
    if (!claim) continue;
    const st = statusAt(claim, A.kt);
    if (!st) continue;                                   // not proposed yet
    const a = items[e.source], b = items[e.target];
    if (!a || !b) continue;
    if (!a.inWindow && !b.inWindow) continue;
    edges.push({
      edge: e, claim, status: st,
      since: statusEntryAt(claim, A.kt).knowledge_time,
      from: a, to: b,
      superseded: st === 'superseded',
      crossDomain: !claim.subjects.every(s => a.res.subjects.includes(s))
    });
  }

  /* Focus mode isolates a subject but must never hide the edges leaving it:
     a neighbour of a focused node stays on screen, dimmed. */
  if (A.focus) {
    const focused = new Set(order.filter(id => items[id].inFocus && items[id].visible));
    for (const ed of edges) {
      if (focused.has(ed.from.id) && ed.to.visible) ed.to.keepForEdge = true;
      if (focused.has(ed.to.id) && ed.from.visible) ed.from.keepForEdge = true;
    }
    for (const id of order) {
      const it = items[id];
      if (!it.visible) continue;
      if (!it.inFocus) {
        if (it.keepForEdge) it.dimmed = true;
        else it.visible = false;
      }
    }
  }

  const visible = order.map(i => items[i]).filter(i => i.visible);
  const liveEdges = edges.filter(e =>
    e.from.visible && e.to.visible &&
    (!A.focus || e.from.inFocus || e.to.inFocus));

  return {
    z, items, order, visible, edges: liveEdges, allEdges: edges, subjectCounts,
    disputedCount: visible.filter(i => i.res.disputed).length,
    supersededCount: liveEdges.filter(e => e.superseded).length
  };
}

/* ----------------------------------------------------------------- caching */
let FACTS = null;
function invalidate() { FACTS = null; }
function facts() { return FACTS || (FACTS = queryFacts(S)); }

/* --------------------------------------------------- the rewriting caption */
function epistemicCaption() {
  const F = facts();
  const kt = S.kt;
  const bits = [];

  if (kt < 1700) bits.push('The Earth has a history, but almost no one is counting it in years yet.');
  else if (kt < 1800) bits.push('Strata are understood to record a sequence. Their length is anyone’s guess.');
  else if (kt < 1862) bits.push('Deep time is accepted. Nothing can yet put a number on it.');
  else if (kt < 1907) bits.push('Physics says the Earth is under 100 million years old, and physics is winning.');
  else if (kt < 1956) bits.push('Radioactivity has broken Kelvin’s ceiling; the age of the Earth is climbing.');
  else if (kt < 1980) bits.push('The planet is 4.55 billion years old. Extinctions are still thought to be gradual.');
  else if (kt < 1991) bits.push('An asteroid has been proposed for the K–Pg extinction. Most palaeontologists are unconvinced.');
  else if (kt < 2000) bits.push('Chicxulub has been found. The impact hypothesis has hardened into consensus.');
  else if (kt < 2015) bits.push('Clovis-first is collapsing, and the Deccan Traps are back in the K–Pg argument.');
  else bits.push('Pre-Clovis sites are accepted, the Anthropocene has been proposed and rejected.');

  const n = F.visible.length, d = F.disputedCount;
  bits.push(`${n} of ${Object.keys(R.referents).length} subjects visible, ${d} of them still disputed.`);
  return bits.filter(Boolean).join(' ');
}
