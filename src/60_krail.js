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

  // spine
  kx.strokeStyle = withAlpha(CSSV.cyanotype, 0.35); kx.lineWidth = 1;
  kx.beginPath(); kx.moveTo(spine + 0.5, KPAD); kx.lineTo(spine + 0.5, KH - KPAD); kx.stroke();

  // ticks
  kx.font = '400 9px xt-mono, monospace';
  for (let yr = 1650; yr <= 2025; yr += 50) {
    const py = ktToY(yr);
    kx.strokeStyle = withAlpha(CSSV['chalk-faint'], 0.45);
    kx.beginPath(); kx.moveTo(spine + 0.5, py); kx.lineTo(spine + 5, py); kx.stroke();
    kx.fillStyle = CSSV['chalk-faint'];
    kx.fillText(String(yr), spine + 8, py + 3);
  }

  // handle
  kx.strokeStyle = CSSV.cyanotype; kx.lineWidth = 1.6;
  kx.beginPath(); kx.moveTo(2, y + 0.5); kx.lineTo(KW - 2, y + 0.5); kx.stroke();
  kx.beginPath(); kx.arc(spine + 0.5, y + 0.5, 4.5, 0, 7);
  kx.fillStyle = CSSV.cyanotype; kx.fill();
  kx.strokeStyle = CSSV.shale; kx.lineWidth = 1.5; kx.stroke();
}

/* ----------------------------------------------------------------- replay */
let playT = 0;
function tickReplay(dt) {
  if (!S.playing) return;
  playT += dt;
  const span = KT_MAX - 1650;
  const next = Math.round(1650 + (playT / 16) * span);
  if (next >= KT_MAX) { setKt(KT_MAX); stopReplay(); return; }
  setKt(next);
}
function startReplay() {
  S.playing = true; playT = 0; setKt(1650);
  document.getElementById('btn-play').setAttribute('aria-pressed', 'true');
  document.getElementById('btn-play').textContent = 'Stop';
}
function stopReplay() {
  S.playing = false;
  document.getElementById('btn-play').setAttribute('aria-pressed', 'false');
  document.getElementById('btn-play').textContent = 'Replay';
}
