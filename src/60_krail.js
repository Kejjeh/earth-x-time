/* ============================================================================
   KNOWLEDGE-TIME RAIL
   Deliberately secondary: a thin vertical rail, perpendicular to the Earth-time
   axis, in the one accent colour reserved for it. This is the control that
   rewires the graph.
   ========================================================================== */

const kcv = document.getElementById('krailcv');
const kx = kcv.getContext('2d');
let KW = 0, KH = 0;
const KPAD = 18;

function resizeKrail() {
  KW = Math.max(40, kcv.clientWidth || kcv.getBoundingClientRect().width);
  KH = Math.max(80, kcv.clientHeight || kcv.getBoundingClientRect().height);
  kcv.width = Math.round(KW * DPR); kcv.height = Math.round(KH * DPR);
  kx.setTransform(DPR, 0, 0, DPR, 0, 0);
}

function ktToY(kt) {
  const f = (kt - KT_MIN) / (KT_MAX - KT_MIN);
  return KPAD + (1 - f) * (KH - KPAD * 2);
}
function yToKt(y) {
  const f = 1 - (y - KPAD) / (KH - KPAD * 2);
  return Math.round(Math.max(KT_MIN, Math.min(KT_MAX, KT_MIN + f * (KT_MAX - KT_MIN))));
}

/* Every claim's arrival, so the rail shows where the discoveries cluster. */
const KT_PIPS = (() => {
  const counts = new Map();
  for (const c of GRAPH.claims) {
    const d = Math.floor(c.knowledge_time / 5) * 5;
    counts.set(d, (counts.get(d) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => a[0] - b[0]);
})();
const KT_PIP_MAX = Math.max(...KT_PIPS.map(p => p[1]));

/* Every year in which anything at all changes: a claim arrives, or a claim's
   standing moves. 115 of them, from 1669, and the largest gap between two is
   119 years - which is why dragging blind lands on nothing so often, and why
   the foot has a pair of buttons that step between them. */
const KT_CHANGES = (() => {
  const yrs = new Set();
  for (const c of GRAPH.claims) {
    yrs.add(c.knowledge_time);
    for (const e of (c.status_timeline || [])) yrs.add(e.knowledge_time);
  }
  return [...yrs].filter(y => y >= KT_MIN && y <= KT_MAX).sort((a, b) => a - b);
})();

/* What actually happened in each of those years, precomputed once.
   Links are counted from GRAPH.edges through the knowledge_time of the claim
   that asserts each edge - not from status_timeline entries. A status
   transition is a claim hardening or being retired; it is not an edge
   appearing, and counting it as one would overstate every year in which the
   literature merely changed its mind. */
const KT_YEAR = (() => {
  const m = new Map();
  const at = y => m.get(y) || (m.set(y, { claims: 0, links: 0, superseded: 0, restanding: 0 }), m.get(y));
  for (const c of GRAPH.claims) {
    at(c.knowledge_time).claims++;
    for (const e of (c.status_timeline || [])) {
      /* Every transition is counted, not only the withdrawals. Counting the
         supersessions alone left years like 2026 - where a claim hardens but
         nothing is retired - in KT_CHANGES, so Next would step to a year the
         readout then described as "nothing changes this year". The rail cannot
         say two different things about the same year. */
      if (e.knowledge_time === c.knowledge_time) continue;   // the arrival, already counted
      if (e.status === 'superseded') at(e.knowledge_time).superseded++;
      else at(e.knowledge_time).restanding++;
    }
  }
  for (const e of GRAPH.edges) {
    const c = R.claims[e.claim_id];
    if (c) at(c.knowledge_time).links++;
  }
  return m;
})();

/* 46 supersessions over 23 years, rendered nowhere until now: KT_PIPS shows
   arrivals only, so the rail displayed knowledge arriving and never knowledge
   being withdrawn - on a page whose whole argument is that the record rewrites
   itself. They get the far-left column: the density bars grow leftward from the
   spine and reach x≈29 at their widest in a 104px rail, and the right channel
   is already spoken for by the selected-claim pips at spine+3 and the tick
   labels at spine+8. */
const KT_SUPERSEDED = [...KT_YEAR.entries()]
  .filter(([, v]) => v.superseded > 0)
  .map(([y, v]) => [y, v.superseded])
  .sort((a, b) => a[0] - b[0]);
const KT_SUP_MAX = Math.max(1, ...KT_SUPERSEDED.map(p => p[1]));

function nextChange(from, dir) {
  if (dir > 0) {
    for (const y of KT_CHANGES) if (y > from) return y;
    return null;
  }
  for (let i = KT_CHANGES.length - 1; i >= 0; i--) if (KT_CHANGES[i] < from) return KT_CHANGES[i];
  return null;
}

/* "1980 · 6 claims first made, 1 link wired". A bare pointermove is new here -
   both rails were pointerdown / move-guarded-by-drag / up / cancel, so hovering
   a grey pip told you nothing at all. */
function railReadout(kt) {
  const v = KT_YEAR.get(kt);
  const era = eraAt(kt);
  const parts = [];
  if (v && v.claims) parts.push(`${v.claims} claim${v.claims === 1 ? '' : 's'} first made`);
  if (v && v.links) parts.push(`${v.links} link${v.links === 1 ? '' : 's'} wired`);
  if (v && v.superseded) parts.push(`${v.superseded} superseded`);
  if (v && v.restanding) parts.push(`${v.restanding} changed standing`);
  return { year: kt, era: era.name, detail: parts.join(', ') || 'nothing changes this year' };
}

function drawKrail() {
  kx.clearRect(0, 0, KW, KH);
  const spine = KW * 0.62;
  const y = ktToY(S.kt);

  // the unknown future, greyed
  kx.fillStyle = withAlpha(CSSV['chalk-faint'], 0.06);
  kx.fillRect(0, 0, KW, y);

  // discovery density
  for (const [decade, n] of KT_PIPS) {
    const py = ktToY(decade);
    const w = 4 + (n / KT_PIP_MAX) * (KW * 0.3);
    kx.fillStyle = withAlpha(decade <= S.kt ? CSSV.cyanotype : CSSV['chalk-faint'],
                             decade <= S.kt ? 0.5 : 0.18);
    kx.fillRect(spine - w, py - 1.2, w, 2.4);
  }

  // the claims belonging to the current selection
  if (S.selection) {
    for (const c of (R.byRef[S.selection] || [])) {
      const py = ktToY(Math.max(KT_MIN, c.knowledge_time));
      kx.fillStyle = withAlpha(CSSV.ochre, c.knowledge_time <= S.kt ? 0.95 : 0.35);
      kx.fillRect(spine + 3, py - 1.5, 7, 3);
    }
  }

  // knowledge withdrawn, far-left column, clear of the density bars
  for (const [yr, n] of KT_SUPERSEDED) {
    const py = ktToY(yr);
    const h = 1.6 + (n / KT_SUP_MAX) * 2.6;
    kx.fillStyle = withAlpha(yr <= S.kt ? CSSV.ochre : CSSV['chalk-faint'],
                             yr <= S.kt ? 0.75 : 0.18);
    kx.fillRect(0, py - h / 2, 3.5, h);
  }

  // spine
  kx.strokeStyle = withAlpha(CSSV.cyanotype, 0.35); kx.lineWidth = 1;
  kx.beginPath(); kx.moveTo(spine + 0.5, KPAD); kx.lineTo(spine + 0.5, KH - KPAD); kx.stroke();

  // ticks
  // The first round fifty at or after KT_MIN. Starting at a literal 1650 drew
  // every tick below the floor outside the canvas - ktToY(1650) is 827px in a
  // 737px rail once KT_MIN moves up.
  //
  // The fifties are the scale and no longer the labels: seven bare round
  // numbers told a reader where the rail's middle was and nothing about where
  // its argument turns. They stay as unlabelled minor marks; the labels go to
  // the years in KT_ERAS, which are the years the page has something to say
  // about. Both still draw a four-digit year inside the canvas, which is what
  // the rail-tick check measures.
  for (let yr = Math.ceil(KT_MIN / 50) * 50; yr <= KT_MAX; yr += 50) {
    const py = ktToY(yr);
    kx.strokeStyle = withAlpha(CSSV['chalk-faint'], 0.3);
    kx.beginPath(); kx.moveTo(spine + 0.5, py); kx.lineTo(spine + 3.5, py); kx.stroke();
  }

  kx.font = '400 9px xt-mono, monospace';
  for (const era of KT_ERAS) {
    if (era.from <= KT_MIN || era.from > KT_MAX) continue;
    const py = ktToY(era.from);
    const on = era.from <= S.kt;
    kx.strokeStyle = withAlpha(on ? CSSV.cyanotype : CSSV['chalk-faint'], on ? 0.75 : 0.4);
    kx.lineWidth = 1;
    kx.beginPath(); kx.moveTo(spine + 0.5, py); kx.lineTo(spine + 6, py); kx.stroke();
    kx.fillStyle = on ? CSSV['chalk-dim'] : CSSV['chalk-faint'];
    kx.fillText(String(era.from), spine + 9, py + 3);
  }

  // handle
  kx.strokeStyle = CSSV.cyanotype; kx.lineWidth = 1.6;
  kx.beginPath(); kx.moveTo(2, y + 0.5); kx.lineTo(KW - 2, y + 0.5); kx.stroke();
  kx.beginPath(); kx.arc(spine + 0.5, y + 0.5, 4.5, 0, 7);
  kx.fillStyle = CSSV.cyanotype; kx.fill();
  kx.strokeStyle = CSSV.shale; kx.lineWidth = 1.5; kx.stroke();
}

/* ----------------------------------------------------------------- replay */
/* Sixteen seconds from one end of the rail to the other. The span used to be
   measured from a literal 1650 rather than from KT_MIN, so with the floor
   anywhere above that the first seconds of a replay produced values setKt
   clamped away - the rail sat still - and the rest ran at a rate computed for a
   longer rail than the one on screen. startReplay looked right only because
   setKt clamped for it, which is a second mechanism covering for this one. */
let playT = 0;
const REPLAY_SECONDS = 16;
function tickReplay(dt) {
  if (!S.playing) return;
  playT += dt;
  const span = KT_MAX - KT_MIN;
  const next = Math.round(KT_MIN + (playT / REPLAY_SECONDS) * span);
  if (next >= KT_MAX) { setKt(KT_MAX); stopReplay(); return; }
  setKt(next);
}
function startReplay() {
  S.playing = true; playT = 0; setKt(KT_MIN);
  document.getElementById('btn-play').setAttribute('aria-pressed', 'true');
  document.getElementById('btn-play').textContent = 'Stop';
}
function stopReplay() {
  S.playing = false;
  document.getElementById('btn-play').setAttribute('aria-pressed', 'false');
  document.getElementById('btn-play').textContent = 'Replay';
}
