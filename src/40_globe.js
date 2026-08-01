/* ============================================================================
   THE GLOBE
   Orthographic, canvas 2D, projection written by hand. Every vertex is stored
   as a unit vector at load time, so a frame costs one 3x3 matrix build plus
   nine multiplies per point — no trigonometry in the draw loop.
   ========================================================================== */

const gcv = document.getElementById('globe');
const gx = gcv.getContext('2d');
let GW = 0, GH = 0, GR = 0, GCX = 0, GCY = 0, DPR = 1;
let ZOOMF = 0.86;

const M = new Float64Array(9);
function buildMatrix() {
  const l = S.rot.lam * Math.PI / 180, p = S.rot.phi * Math.PI / 180;
  const cl = Math.cos(l), sl = Math.sin(l), cp = Math.cos(p), sp = Math.sin(p);
  M[0] = cp * cl; M[1] = -cp * sl; M[2] = sp;      // depth row
  M[3] = sl;      M[4] = cl;       M[5] = 0;       // screen x row
  M[6] = -sp * cl; M[7] = sp * sl; M[8] = cp;      // screen y row
}

/* Graticule, built once as unit vectors. */
const GRAT = (() => {
  const out = [];
  for (let lon = -180; lon < 180; lon += 30) {
    const r = [];
    for (let lat = -90; lat <= 90; lat += 4) r.push(...unit(lat, lon));
    out.push(new Float64Array(r));
  }
  for (let lat = -60; lat <= 60; lat += 30) {
    const r = [];
    for (let lon = -180; lon <= 180; lon += 4) r.push(...unit(lat, lon));
    out.push(new Float64Array(r));
  }
  return out;
})();

function resizeGlobe() {
  const r = gcv.parentElement.getBoundingClientRect();
  DPR = Math.min(window.devicePixelRatio || 1, 2);
  GW = Math.max(80, r.width); GH = Math.max(80, r.height);
  gcv.width = Math.round(GW * DPR); gcv.height = Math.round(GH * DPR);
  gcv.style.width = GW + 'px'; gcv.style.height = GH + 'px';
  gx.setTransform(DPR, 0, 0, DPR, 0, 0);
  GCX = GW / 2; GCY = GH / 2;
  GR = Math.min(GW, GH) * 0.5 * ZOOMF;
}

/* ------------------------------------------------------------ ring drawing */
/* Scratch buffers, sized to the largest ring, reused every frame. */
const RB = { d: null, Y: null, Z: null };
function ensureBuffers(n) {
  if (!RB.d || RB.d.length < n) {
    RB.d = new Float64Array(n * 2); RB.Y = new Float64Array(n * 2); RB.Z = new Float64Array(n * 2);
  }
}

function projectRing(ring) {
  const n = ring.length / 3;
  ensureBuffers(n);
  const { d, Y, Z } = RB;
  let nVis = 0;
  for (let i = 0; i < n; i++) {
    const px = ring[i * 3], py = ring[i * 3 + 1], pz = ring[i * 3 + 2];
    d[i] = M[0] * px + M[1] * py + M[2] * pz;
    Y[i] = M[3] * px + M[4] * py + M[5] * pz;
    Z[i] = M[6] * px + M[7] * py + M[8] * pz;
    if (d[i] > 0) nVis++;
  }
  return { n, nVis };
}

/*
 * Which way round the limb does a gap close?
 *
 * Not a question the hidden vertices can answer. Their azimuths wind through
 * extra whole turns on a ring as long as Eurasia, and on a ring as small as a
 * Siberian lake they are identical to within rounding — either way the sign is
 * junk and the arc sweeps the wrong way, flooding the disc.
 *
 * It follows from orientation instead. Walking the limb in the direction of
 * increasing azimuth in the right-handed view frame keeps the visible
 * hemisphere on the left; a ring whose interior is also on its left therefore
 * closes that same way, at every gap, regardless of how much is hidden. The
 * matrix rows are a right-handed triple, and screen angle is atan2(-Z, Y),
 * which runs opposite to that azimuth — hence canvas counterclockwise.
 */
function limbSweepIsCCW(orientation) { return orientation > 0; }

/* Open polylines — graticule, plate boundaries. Hidden runs are simply cut,
   never bridged, so nothing smears across the disc. */
function strokePolyline(ring) {
  const { n } = projectRing(ring);
  const { d, Y, Z } = RB;
  let drawing = false, drew = false;
  gx.beginPath();
  for (let i = 0; i < n; i++) {
    if (d[i] > 0) {
      const sx = GCX + GR * Y[i], sy = GCY - GR * Z[i];
      if (!drawing) { gx.moveTo(sx, sy); drawing = true; } else gx.lineTo(sx, sy);
      drew = true;
    } else drawing = false;
  }
  if (drew) gx.stroke();
  return drew;
}

/**
 * Filled landmasses, clipped to the visible hemisphere.
 *
 * Collapsing hidden vertices onto the rim (the cheap trick) turns any continent
 * straddling the horizon into a polygon that swallows the globe. Instead: cut
 * the ring at the horizon, then close each gap by following the limb itself,
 * choosing the sweep direction that passes over where the hidden vertices
 * actually went. Fill the closed path, then stroke only the true coastline so
 * the limb arcs are not mistaken for shoreline.
 */
function drawLandRing(ring, orientation) {
  const { n, nVis } = projectRing(ring);
  if (nVis === 0) return false;
  const { d, Y, Z } = RB;

  if (nVis === n) {
    gx.beginPath();
    for (let i = 0; i < n; i++) {
      const sx = GCX + GR * Y[i], sy = GCY - GR * Z[i];
      if (i === 0) gx.moveTo(sx, sy); else gx.lineTo(sx, sy);
    }
    gx.closePath(); gx.fill(); gx.stroke();
    return true;
  }

  let start = -1;
  for (let i = 0; i < n; i++) if (d[i] <= 0 && d[(i + 1) % n] > 0) { start = i; break; }
  if (start < 0) return false;

  const cross = (i, j) => {
    const t = d[i] / (d[i] - d[j]);
    let y = Y[i] + (Y[j] - Y[i]) * t, z = Z[i] + (Z[j] - Z[i]) * t;
    const m = Math.hypot(y, z) || 1;
    return [y / m, z / m];
  };

  const segs = [];
  let cur = null;
  for (let k = 0; k < n; k++) {
    const i = (start + k) % n, j = (start + k + 1) % n;
    if (d[i] > 0) {
      if (!cur) { cur = { pts: [], inAng: null }; segs.push(cur); }
      cur.pts.push(Y[i], Z[i]);
      if (d[j] <= 0) {
        const c = cross(i, j);
        cur.pts.push(c[0], c[1]);
        cur.outAng = Math.atan2(-c[1], c[0]);
        cur = null;
      }
    } else if (d[j] > 0) {
      const c = cross(i, j);
      cur = { pts: [c[0], c[1]], inAng: Math.atan2(-c[1], c[0]) };
      segs.push(cur);
    }
  }
  const chains = segs.filter(s => s.inAng != null && s.outAng != null);
  if (!chains.length) return false;
  const ccw = limbSweepIsCCW(orientation);

  /* Chains must be re-paired by position along the limb, not by ring order.
     Where a coastline crosses the horizon many times, the chain that follows
     another around the rim is rarely the next one in the ring; pairing by ring
     order crosses the arcs over each other and the fill inverts. */
  const TAU = Math.PI * 2;
  const gapTo = (from, to) => {
    const d = ccw ? (from - to) : (to - from);
    return ((d % TAU) + TAU) % TAU;
  };

  const used = new Array(chains.length).fill(false);
  gx.beginPath();
  for (let s0 = 0; s0 < chains.length; s0++) {
    if (used[s0]) continue;
    let cur = s0, first = true, guard = 0;
    while (guard++ <= chains.length) {
      used[cur] = true;
      const seg = chains[cur];
      for (let q = 0; q < seg.pts.length; q += 2) {
        const sx = GCX + GR * seg.pts[q], sy = GCY - GR * seg.pts[q + 1];
        if (first && q === 0) gx.moveTo(sx, sy); else gx.lineTo(sx, sy);
      }
      first = false;
      let best = -1, bestD = Infinity;
      for (let t = 0; t < chains.length; t++) {
        const d2 = gapTo(seg.outAng, chains[t].inAng);
        if (d2 < bestD - 1e-12) { bestD = d2; best = t; }
      }
      if (best < 0) break;
      gx.arc(GCX, GCY, GR, seg.outAng, chains[best].inAng, ccw);
      if (best === s0 || used[best]) break;
      cur = best;
    }
    gx.closePath();
  }
  gx.fill();

  // coastline only — the limb arcs above are a fill device, not shoreline
  gx.beginPath();
  for (const seg of chains) {
    for (let q = 0; q < seg.pts.length; q += 2) {
      const sx = GCX + GR * seg.pts[q], sy = GCY - GR * seg.pts[q + 1];
      if (q === 0) gx.moveTo(sx, sy); else gx.lineTo(sx, sy);
    }
  }
  gx.stroke();
  return true;
}

/* --------------------------------------------------------------- great arcs */
function arcPoints(a, b, steps) {
  let dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  dot = Math.max(-1, Math.min(1, dot));
  const om = Math.acos(dot), so = Math.sin(om);
  const pts = new Float64Array(steps * 3);
  for (let i = 0; i < steps; i++) {
    const t = i / (steps - 1);
    let c1, c2;
    if (so < 1e-6) { c1 = 1 - t; c2 = t; }
    else { c1 = Math.sin((1 - t) * om) / so; c2 = Math.sin(t * om) / so; }
    pts[i * 3] = a[0] * c1 + b[0] * c2;
    pts[i * 3 + 1] = a[1] * c1 + b[1] * c2;
    pts[i * 3 + 2] = a[2] * c1 + b[2] * c2;
  }
  return pts;
}

/** Draw an arc raised off the surface; returns screen points for the travelling dot. */
function drawArc(pts, lift, color, width, dash, dashOffset) {
  const n = pts.length / 3;
  gx.strokeStyle = color; gx.lineWidth = width;
  if (dash) { gx.setLineDash(dash); gx.lineDashOffset = dashOffset || 0; }
  const screen = new Float64Array(n * 2);
  const vis = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / (n - 1);
    const h = 1 + lift * Math.sin(Math.PI * t);
    const px = pts[i * 3], py = pts[i * 3 + 1], pz = pts[i * 3 + 2];
    const d = M[0] * px + M[1] * py + M[2] * pz;
    const yv = M[3] * px + M[4] * py + M[5] * pz;
    const zv = M[6] * px + M[7] * py + M[8] * pz;
    screen[i * 2] = GCX + GR * h * yv;
    screen[i * 2 + 1] = GCY - GR * h * zv;
    vis[i] = d > -(h - 1) * 0.9 ? 1 : 0;
  }
  let drawing = false;
  gx.beginPath();
  for (let i = 0; i < n; i++) {
    if (vis[i]) {
      if (!drawing) { gx.moveTo(screen[i * 2], screen[i * 2 + 1]); drawing = true; }
      else gx.lineTo(screen[i * 2], screen[i * 2 + 1]);
    } else drawing = false;
  }
  gx.stroke();
  gx.setLineDash([]);
  return { screen, vis, n };
}

/* ------------------------------------------------------------------ markers */
const HIT = [];                              // screen-space hit targets, rebuilt per frame

function markerRadius(sig) { return 2.6 + sig * 1.15; }

function drawMarker(sx, sy, sig, color, status, opts) {
  const r = markerRadius(sig) * (opts.selected ? 1.5 : 1);
  gx.save();
  if (status === 'superseded') gx.globalAlpha = 0.34;
  else if (status === 'proposed') gx.globalAlpha = 0.85;
  if (opts.dimmed) gx.globalAlpha *= 0.3;

  if (opts.disputed) {                        // never launder a dispute into a dot
    gx.beginPath(); gx.arc(sx, sy, r + 3.5, 0, 7);
    gx.strokeStyle = withAlpha(color, 0.45); gx.lineWidth = 1; gx.setLineDash([2, 2.5]);
    gx.stroke(); gx.setLineDash([]);
  }

  gx.beginPath(); gx.arc(sx, sy, r, 0, 7);
  if (status === 'consensus') { gx.fillStyle = color; gx.fill(); }
  else if (status === 'contested') {
    gx.fillStyle = withAlpha(color, 0.55); gx.fill();
    gx.strokeStyle = color; gx.lineWidth = 1.4; gx.stroke();
  } else {
    gx.fillStyle = withAlpha(CSSV.abyss, 0.55); gx.fill();
    gx.strokeStyle = color; gx.lineWidth = 1.6;
    if (status === 'superseded') gx.setLineDash([2.5, 2.5]);
    gx.stroke(); gx.setLineDash([]);
  }

  if (opts.selected) {
    gx.beginPath(); gx.arc(sx, sy, r + 6, 0, 7);
    gx.strokeStyle = CSSV.chalk; gx.lineWidth = 1.2; gx.stroke();
  }
  gx.restore();
}

function drawLabel(sx, sy, text, color, boxes, strong) {
  gx.font = `${strong ? 600 : 400} 11px ${'xt-cond'}, sans-serif`;
  const w = gx.measureText(text).width;
  const cands = [[sx + 10, sy + 4], [sx - w - 10, sy + 4], [sx - w / 2, sy - 12], [sx - w / 2, sy + 18]];
  for (const [bx, by] of cands) {
    const box = [bx - 2, by - 10, w + 4, 13];
    let hit = false;
    for (const o of boxes) {
      if (box[0] < o[0] + o[2] && box[0] + box[2] > o[0] && box[1] < o[1] + o[3] && box[1] + box[3] > o[1]) { hit = true; break; }
    }
    if (hit) continue;
    if (bx < 4 || bx + w > GW - 4 || by < 12 || by > GH - 6) continue;
    boxes.push(box);
    gx.fillStyle = withAlpha(CSSV.abyss, 0.72);
    gx.fillRect(box[0], box[1], box[2], box[3]);
    gx.fillStyle = strong ? CSSV.chalk : color;
    gx.fillText(text, bx, by);
    return true;
  }
  return false;
}

/* ------------------------------------------------------------------- render */
let arcPhase = 0;

function drawGlobe(dt) {
  const F = facts();
  buildMatrix();
  HIT.length = 0;
  gx.clearRect(0, 0, GW, GH);

  // ocean
  const grd = gx.createRadialGradient(GCX - GR * 0.3, GCY - GR * 0.35, GR * 0.1, GCX, GCY, GR);
  grd.addColorStop(0, CSSV['ocean-hi']); grd.addColorStop(1, CSSV['ocean-lo']);
  gx.beginPath(); gx.arc(GCX, GCY, GR, 0, 7); gx.fillStyle = grd; gx.fill();

  gx.save();
  gx.beginPath(); gx.arc(GCX, GCY, GR, 0, 7); gx.clip();

  // graticule
  gx.strokeStyle = withAlpha(CSSV['land-edge'], 0.16); gx.lineWidth = 0.5;
  for (const g of GRAT) strokePolyline(g);

  // land
  gx.fillStyle = CSSV.land; gx.strokeStyle = CSSV['land-edge']; gx.lineWidth = 0.7;
  for (let i = 0; i < LAND.length; i++) drawLandRing(LAND[i], LAND_CCW[i]);

  // plate boundaries — a geological-survey underlay, drawn over the land it cuts
  if (S.showPlates) {
    gx.strokeStyle = CSSV.plate; gx.lineWidth = 0.9; gx.setLineDash([3, 2.5]);
    for (const p of PLATE) strokePolyline(p);
    gx.setLineDash([]);
  }

  gx.restore();

  // limb
  gx.beginPath(); gx.arc(GCX, GCY, GR, 0, 7);
  gx.strokeStyle = withAlpha(CSSV['land-edge'], 0.7); gx.lineWidth = 1; gx.stroke();

  /* ---- planet-wide facts ride the horizon rather than pretending to be dots */
  const globals = F.visible.filter(i => i.res.geometry.mode === 'global');
  if (globals.length) {
    const pulse = RM.matches ? 0.5 : 0.5 + 0.5 * Math.sin(arcPhase * 1.4);
    const seg = (Math.PI * 2) / globals.length;
    globals.forEach((it, i) => {
      const col = CSSV[it.res.subjects.find(s => CSSV[s]) || 'geology'];
      const st = it.res.winner ? it.res.winner.status : 'contested';
      gx.beginPath();
      gx.arc(GCX, GCY, GR + 5, i * seg + 0.03, (i + 1) * seg - 0.03);
      gx.strokeStyle = withAlpha(col, st === 'superseded' ? 0.2 : 0.35 + 0.3 * pulse);
      gx.lineWidth = it.id === S.selection ? 5 : 2.5 + it.res.significance * 0.3;
      gx.stroke();
      const mid = (i + 0.5) * seg;
      HIT.push({ id: it.id, x: GCX + (GR + 5) * Math.cos(mid), y: GCY + (GR + 5) * Math.sin(mid), r: 9, global: true });
    });
  }

  /* ---- causal arcs, animated in the direction of causation */
  for (const ed of F.edges) {
    const a = ed.from.res.geometry, b = ed.to.res.geometry;
    const av = a.mode === 'global' || a.mode === 'none' ? null : unit(a.lat, a.lng);
    const bv = b.mode === 'global' || b.mode === 'none' ? null : unit(b.lat, b.lng);
    if (!av || !bv) continue;
    const col = ed.superseded ? CSSV['chalk-faint']
      : ed.edge.type === 'part_of' ? withAlpha(CSSV['chalk-dim'], 0.5)
      : CSSV[ed.claim.subjects.find(s => CSSV[s]) || 'geology'];
    const w = ed.superseded ? 1 : ed.status === 'consensus' ? 2 : 1.4;
    const lift = 0.08;
    const pts = arcPoints(av, bv, 48);
    gx.save();
    gx.globalAlpha = ed.superseded ? 0.45 : 0.9;
    const geo = drawArc(pts, lift, withAlpha(col, ed.superseded ? 0.5 : 0.75), w,
      ed.superseded ? [3, 3] : ed.edge.type === 'part_of' ? [1, 4] : null, 0);

    if (!ed.superseded && !RM.matches && ed.edge.type === 'causal') {
      const k = Math.floor(((arcPhase * 0.35 + (ed.edge.id.length % 7) / 7) % 1) * (geo.n - 1));
      if (geo.vis[k]) {
        gx.beginPath();
        gx.arc(geo.screen[k * 2], geo.screen[k * 2 + 1], 2.6, 0, 7);
        gx.fillStyle = col; gx.fill();
      }
    }
    gx.restore();
  }

  /* ---- markers */
  const boxes = [];
  const pts = [];
  for (const it of F.visible) {
    const g = it.res.geometry;
    if (g.mode === 'global' || g.mode === 'none') continue;
    const v = unit(g.lat, g.lng);
    const d = M[0] * v[0] + M[1] * v[1] + M[2] * v[2];
    if (d <= 0.02) continue;
    const sx = GCX + GR * (M[3] * v[0] + M[4] * v[1] + M[5] * v[2]);
    const sy = GCY - GR * (M[6] * v[0] + M[7] * v[1] + M[8] * v[2]);
    pts.push({ it, sx, sy, d, g });
  }
  pts.sort((a, b) => a.d - b.d);

  for (const p of pts) {
    const { it, sx, sy, g } = p;
    const col = CSSV[it.res.subjects.find(s => CSSV[s]) || 'geology'];
    const st = it.res.winner ? it.res.winner.status : 'contested';

    if (g.mode === 'region' && g.radius_km > 120) {
      const ang = Math.min(g.radius_km / 6371, 0.85);
      const c = unit(g.lat, g.lng);
      let ref = Math.abs(c[2]) > 0.9 ? [1, 0, 0] : [0, 0, 1];
      let e1 = [ref[1] * c[2] - ref[2] * c[1], ref[2] * c[0] - ref[0] * c[2], ref[0] * c[1] - ref[1] * c[0]];
      const m1 = Math.hypot(e1[0], e1[1], e1[2]); e1 = e1.map(v => v / m1);
      const e2 = [c[1] * e1[2] - c[2] * e1[1], c[2] * e1[0] - c[0] * e1[2], c[0] * e1[1] - c[1] * e1[0]];
      const ca = Math.cos(ang), sa = Math.sin(ang);
      gx.beginPath();
      let started = false;
      for (let i = 0; i <= 40; i++) {
        const th = i / 40 * Math.PI * 2, ct = Math.cos(th), stt = Math.sin(th);
        const q = [c[0] * ca + (e1[0] * ct + e2[0] * stt) * sa,
                   c[1] * ca + (e1[1] * ct + e2[1] * stt) * sa,
                   c[2] * ca + (e1[2] * ct + e2[2] * stt) * sa];
        const dd = M[0] * q[0] + M[1] * q[1] + M[2] * q[2];
        if (dd <= 0) { started = false; continue; }
        const qx = GCX + GR * (M[3] * q[0] + M[4] * q[1] + M[5] * q[2]);
        const qy = GCY - GR * (M[6] * q[0] + M[7] * q[1] + M[8] * q[2]);
        if (!started) { gx.moveTo(qx, qy); started = true; } else gx.lineTo(qx, qy);
      }
      gx.strokeStyle = withAlpha(col, it.dimmed ? 0.08 : 0.22);
      gx.lineWidth = 1; gx.setLineDash([2, 4]); gx.stroke(); gx.setLineDash([]);
      gx.fillStyle = withAlpha(col, it.dimmed ? 0.03 : 0.055); gx.fill();
    }

    drawMarker(sx, sy, it.res.significance, col, st, {
      selected: it.id === S.selection,
      dimmed: it.dimmed,
      disputed: it.res.disputed
    });

    if (it.rolledUp) {
      gx.font = `600 9px ${'xt-mono'}, monospace`;
      gx.fillStyle = CSSV['chalk-dim'];
      gx.fillText('+' + it.rolledUp, sx + markerRadius(it.res.significance) + 3, sy - 5);
    }

    HIT.push({ id: it.id, x: sx, y: sy, r: markerRadius(it.res.significance) + 7 });

    const strong = it.id === S.selection || it.id === S.hover;
    if (!it.dimmed && (strong || it.res.significance >= 4))
      drawLabel(sx, sy, it.ref.label, col, boxes, strong);
  }

  if (!RM.matches) arcPhase += dt;
}
