/* ============================================================================
   EARTH-TIME AXIS + STRATIGRAPHIC RIBBON
   The ribbon is the signature: real ICS colours, real boundary ages, six lanes
   that compress and expand as the log axis zooms. Everything else here stays
   quiet so the ribbon can carry the page.
   ========================================================================== */

const ccv = document.getElementById('chroncv');
const cx2 = ccv.getContext('2d');

const LANES = [
  { key: 'eon',    label: 'EON',    h: 14 },
  { key: 'era',    label: 'ERA',    h: 14 },
  { key: 'period', label: 'PERIOD', h: 15 },
  { key: 'epoch',  label: 'EPOCH',  h: 13 },
  { key: 'age',    label: 'AGE',    h: 12 },
  { key: 'human',  label: 'HUMAN',  h: 14 }
];
const TICK_H = 17, FACT_H = 48;
const RIBBON_H = LANES.reduce((a, l) => a + l.h, 0);
const CH_H = TICK_H + FACT_H + RIBBON_H + 4;

let CW = 0, SCALE = null;

function resizeChron() {
  // Width comes from CSS (100% of the section); only the height is content-led,
  // so only the height may be written as an inline style. See resizeGlobe.
  CW = Math.max(120, ccv.clientWidth || ccv.parentElement.getBoundingClientRect().width);
  ccv.width = Math.round(CW * DPR); ccv.height = Math.round(CH_H * DPR);
  ccv.style.height = CH_H + 'px';
  cx2.setTransform(DPR, 0, 0, DPR, 0, 0);
}

function chronScale() { return makeScale(S.win.t0, S.win.t1, CW); }

/* ------------------------------------------------------------------- ticks */
function tickValues(t0, t1) {
  const out = [];
  const lo = Math.max(t0, 1), hi = t1;
  const p0 = Math.floor(Math.log10(lo)), p1 = Math.ceil(Math.log10(hi));
  for (let p = p0; p <= p1; p++) {
    for (const m of [1, 2, 5]) {
      const v = m * Math.pow(10, p);
      if (v >= t0 && v <= t1) out.push(v);
    }
  }
  if (t0 <= 0) out.push(0);
  return out.sort((a, b) => b - a);
}

/* ------------------------------------------------------------------ ribbon */
function drawRibbon(sc, yTop) {
  let y = yTop;
  for (const lane of LANES) {
    const rows = lane.key === 'human' ? HUMAN_BANDS : BANDS[lane.key];
    cx2.fillStyle = withAlpha(CSSV['chalk-faint'], 0.06);
    cx2.fillRect(0, y, CW, lane.h);

    for (const iv of rows) {
      if (iv.e > S.win.t1 || iv.b < S.win.t0) continue;
      const x0 = Math.max(-2, sc.x(Math.min(iv.b, S.win.t1)));
      const x1 = Math.min(CW + 2, sc.x(Math.max(iv.e, S.win.t0)));
      const w = x1 - x0;
      if (w < 0.35) continue;

      cx2.fillStyle = lane.key === 'human' ? withAlpha(iv.c, 0.92) : iv.c;
      cx2.fillRect(x0, y, Math.max(w, 0.6), lane.h - 1);

      if (w > 5) {
        cx2.strokeStyle = withAlpha('#000000', 0.28);
        cx2.lineWidth = 0.5;
        cx2.beginPath(); cx2.moveTo(x0 + 0.25, y); cx2.lineTo(x0 + 0.25, y + lane.h - 1); cx2.stroke();
      }
      if (w > 22) {
        cx2.font = `600 ${lane.h > 13 ? 9.5 : 9}px xt-cond, sans-serif`;
        const tw = cx2.measureText(iv.n).width;
        if (tw + 8 < w) {
          cx2.fillStyle = lane.key === 'human' ? '#E4EAE8' : 'rgba(12,22,26,0.86)';
          cx2.fillText(iv.n, x0 + (w - tw) / 2, y + lane.h - 4);
        }
      }
    }

    // lane identity, pinned left over a scrim
    cx2.font = '600 8px xt-cond, sans-serif';
    const lw = cx2.measureText(lane.label).width;
    cx2.fillStyle = withAlpha(CSSV.abyss, 0.72);
    cx2.fillRect(0, y, lw + 8, lane.h - 1);
    cx2.fillStyle = CSSV['chalk-faint'];
    cx2.fillText(lane.label, 4, y + lane.h - 4.5);

    y += lane.h;
  }

  cx2.strokeStyle = withAlpha(CSSV.rule, 1); cx2.lineWidth = 1;
  cx2.beginPath(); cx2.moveTo(0, yTop + 0.5); cx2.lineTo(CW, yTop + 0.5); cx2.stroke();
}

/* ------------------------------------------------------------------- facts */
function drawFacts(sc, yTop, h) {
  const F = facts();
  const rows = 4, rowH = (h - 8) / rows;
  const occupied = Array.from({ length: rows }, () => []);
  const placed = [];

  const sorted = F.visible.slice().sort((a, b) => b.res.significance - a.res.significance);

  for (const it of sorted) {
    const r = it.res;
    const xw = sc.x(Math.min(r.oldest, S.win.t1));
    const xy = sc.x(Math.max(r.youngest, S.win.t0));
    const xp = sc.x(Math.max(S.win.t0, Math.min(r.pos, S.win.t1)));
    if (xy < -40 || xw > CW + 40) continue;

    const left = Math.min(xw, xp) - 5, right = Math.max(xy, xp) + 5;
    let row = -1;
    for (let i = 0; i < rows; i++) {
      if (occupied[i].every(o => right < o[0] || left > o[1])) { row = i; break; }
    }
    if (row < 0) continue;
    occupied[row].push([left, right]);
    const y = yTop + 5 + row * rowH + rowH / 2;
    placed.push({ it, xw, xy, xp, y });
  }

  for (const p of placed) {
    const { it, xw, xy, xp, y } = p;
    const r = it.res;
    const col = CSSV[r.subjects.find(s => CSSV[s]) || 'geology'];
    const st = r.winner ? r.winner.status : 'contested';
    const alpha = it.dimmed ? 0.25 : 1;
    cx2.save();
    cx2.globalAlpha = alpha;

    /* A settled fact is a point. A disputed one is a band, and the width of
       that band is information — never a dot with an asterisk. */
    if (r.disputed || S.resolver === 'spread') {
      const bw = Math.max(xy - xw, 1.5);
      cx2.fillStyle = withAlpha(col, 0.16);
      cx2.fillRect(xw, y - 6, bw, 12);
      cx2.strokeStyle = withAlpha(col, 0.5); cx2.lineWidth = 1;
      cx2.strokeRect(xw + 0.5, y - 6.5, bw, 12);
      cx2.beginPath();
      cx2.moveTo(xw, y); cx2.lineTo(xy, y);
      cx2.strokeStyle = withAlpha(col, 0.35); cx2.stroke();

      for (const alt of r.dated) {
        if (alt === r.winner) continue;
        const ax = sc.x(alt.claim.earth_time_start);
        if (ax < -10 || ax > CW + 10) continue;
        cx2.beginPath(); cx2.arc(ax, y, 3, 0, 7);
        cx2.strokeStyle = col; cx2.lineWidth = 1.2;
        if (alt.status === 'superseded') { cx2.setLineDash([2, 2]); cx2.globalAlpha = alpha * 0.5; }
        cx2.stroke(); cx2.setLineDash([]); cx2.globalAlpha = alpha;
      }
    }

    if (r.winner) {
      const rad = 2.5 + r.significance * 0.85;
      cx2.beginPath(); cx2.arc(xp, y, rad, 0, 7);
      if (st === 'consensus' || st === 'contested') {
        cx2.fillStyle = st === 'consensus' ? col : withAlpha(col, 0.55); cx2.fill();
        if (st === 'contested') { cx2.strokeStyle = col; cx2.lineWidth = 1.2; cx2.stroke(); }
      } else {
        cx2.fillStyle = CSSV.shale; cx2.fill();
        cx2.strokeStyle = col; cx2.lineWidth = 1.4;
        if (st === 'superseded') cx2.setLineDash([2, 2]);
        cx2.stroke(); cx2.setLineDash([]);
      }
    }

    if (it.id === S.selection) {
      cx2.beginPath(); cx2.arc(xp, y, 3.5 + r.significance * 0.85 + 4, 0, 7);
      cx2.strokeStyle = CSSV.chalk; cx2.lineWidth = 1.1; cx2.stroke();
    }

    cx2.restore();
    p.hit = { id: it.id, x: xp, y, r: 9 };
  }

  /* Labels get their own pass with collision rejection: at the compressed end
     of the axis a dozen events fall within a few pixels, and a stack of
     overprinted names is worse than no names. Importance wins the space. */
  const lboxes = [];
  const ranked = placed.slice().sort((a, b) => {
    const pri = x => (x.it.id === S.selection ? 100 : x.it.id === S.hover ? 90 : x.it.res.significance);
    return pri(b) - pri(a);
  });
  for (const p of ranked) {
    const { it, xp, y } = p;
    const strong = it.id === S.selection || it.id === S.hover;
    if (!strong && it.res.significance < 4) continue;
    cx2.font = `${strong ? 600 : 400} 10px xt-cond, sans-serif`;
    const t = it.ref.label;
    const tw = cx2.measureText(t).width;
    let lx = xp + 8;
    if (lx + tw > CW - 4) lx = xp - tw - 8;
    if (lx < 2) continue;
    const box = [lx - 2, y - 6, tw + 4, 11];
    if (lboxes.some(o => box[0] < o[0] + o[2] && box[0] + box[2] > o[0] &&
                         box[1] < o[1] + o[3] && box[1] + box[3] > o[1])) continue;
    lboxes.push(box);
    cx2.save();
    cx2.globalAlpha = it.dimmed ? 0.35 : 1;
    cx2.fillStyle = withAlpha(CSSV.shale, 0.82);
    cx2.fillRect(box[0], box[1], box[2], box[3]);
    cx2.fillStyle = strong ? CSSV.chalk : CSSV['chalk-dim'];
    cx2.fillText(t, lx, y + 3);
    cx2.restore();
  }
  return placed.map(p => p.hit).filter(Boolean);
}

/* ------------------------------------------------------------------ render */
let CHIT = [];

function drawChron() {
  const sc = SCALE = chronScale();
  cx2.clearRect(0, 0, CW, CH_H);

  // tick rail
  cx2.fillStyle = CSSV['chalk-faint'];
  cx2.font = '400 9.5px xt-mono, monospace';
  const ticks = tickValues(S.win.t0, S.win.t1);
  let lastX = -999;
  for (const t of ticks) {
    const x = sc.x(t);
    if (x < 2 || x > CW - 2) continue;
    cx2.strokeStyle = withAlpha(CSSV['chalk-faint'], 0.3);
    cx2.beginPath(); cx2.moveTo(x, TICK_H - 5); cx2.lineTo(x, TICK_H); cx2.stroke();
    const lab = fmtYbp(t, true);
    const w = cx2.measureText(lab).width;
    if (x - w / 2 > lastX + 6 && x + w / 2 < CW - 2) {
      cx2.fillStyle = CSSV['chalk-faint'];
      cx2.fillText(lab, x - w / 2, TICK_H - 7);
      lastX = x + w / 2;
    }
  }

  CHIT = drawFacts(sc, TICK_H, FACT_H);
  drawRibbon(sc, TICK_H + FACT_H);

  // the Earth-time cursor
  const cxp = sc.x(S.cursor);
  if (cxp >= -1 && cxp <= CW + 1) {
    cx2.strokeStyle = CSSV.ochre; cx2.lineWidth = 1;
    cx2.beginPath(); cx2.moveTo(cxp + 0.5, 0); cx2.lineTo(cxp + 0.5, CH_H); cx2.stroke();
    cx2.fillStyle = CSSV.ochre;
    cx2.beginPath();
    cx2.moveTo(cxp, TICK_H + 1); cx2.lineTo(cxp - 4, TICK_H - 4); cx2.lineTo(cxp + 4, TICK_H - 4);
    cx2.closePath(); cx2.fill();
  }
}

/* --------------------------------------------------------- what's under the cursor */
function cursorContext(t) {
  const out = [];
  for (const L of ['eon', 'era', 'period', 'epoch', 'age']) {
    const hit = BANDS[L].find(b => t <= b.b && t >= b.e);
    if (hit) out.push(hit.n);
  }
  const h = HUMAN_BANDS.find(b => t <= b.b && t >= b.e);
  if (h && t < 3300000) out.push(h.n);
  return out;
}
