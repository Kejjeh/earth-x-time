/* ============================================================================
   EARTH x TIME — core
   Assets injected at build time by tools/build.py
   ========================================================================== */
'use strict';

const LAND_ENC   = '/*@LAND@*/';
const PLATE_ENC  = '/*@PLATES@*/';
const ICS        = /*@ICS@*/;
const GRAPH      = /*@GRAPH@*/;

/* The epoch every earth_time_* value in graph.json was authored against. NOT the
   same quantity as KT_MAX below, however much they looked like the same number:
   these are stored years-before-present, so moving this moves every historical
   date in the dataset. Hastings is stored as 959 and reads 1066 from here; bump
   PRESENT and it reads 1067. Only change it alongside a migration of the data. */
const PRESENT = 2025;
const T_MAX   = 4.6e9;         // oldest point on the axis
/* The upper end of knowledge-time is NOW, not a constant someone typed once.
   A 2026 paper - Snelling et al., Nature 653:439-443 - overturns the oxygen
   explanation for giant Palaeozoic insects, and with the rail stopping at 2025
   its status entry could never fire: the graph would have shown a consensus the
   literature had already abandoned. Move this when the record moves past it. */
const KT_MIN  = 1650, KT_MAX = 2026;

const RM = matchMedia('(prefers-reduced-motion: reduce)');

/* ---------------------------------------------------------------- decoding */
const ALPHA = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-';
const AMAP = (() => { const m = new Int8Array(128).fill(-1);
  for (let i = 0; i < 64; i++) m[ALPHA.charCodeAt(i)] = i; return m; })();

/** Delta + zigzag + base64 varint, quantised to 1/32 degree. Rings split on '|'. */
function decodeRings(enc) {
  if (!enc) return [];
  const rings = [];
  for (const part of enc.split('|')) {
    if (!part) continue;
    const pts = [];
    let i = 0, px = 0, py = 0;
    while (i < part.length) {
      let shift = 0, res = 0, b;
      do { b = AMAP[part.charCodeAt(i++)]; res |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      px += (res & 1) ? ~(res >> 1) : (res >> 1);
      shift = 0; res = 0;
      do { b = AMAP[part.charCodeAt(i++)]; res |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      py += (res & 1) ? ~(res >> 1) : (res >> 1);
      pts.push(px / 32, py / 32);
    }
    if (pts.length >= 4) rings.push(pts);
  }
  return rings;
}

/** Pre-project lon/lat rings to unit vectors once, so each frame is pure matrix work. */
function toXYZ(rings) {
  return rings.map(r => {
    const n = r.length / 2, out = new Float64Array(n * 3);
    for (let i = 0; i < n; i++) {
      const lon = r[i * 2] * Math.PI / 180, lat = r[i * 2 + 1] * Math.PI / 180;
      const cl = Math.cos(lat);
      out[i * 3] = cl * Math.cos(lon);
      out[i * 3 + 1] = cl * Math.sin(lon);
      out[i * 3 + 2] = Math.sin(lat);
    }
    return out;
  });
}

/**
 * Ring orientation on the sphere: +1 if the interior lies to the left as you
 * walk the ring (counterclockwise seen from outside), -1 otherwise.
 * Summing the edge cross-products gives a vector along the ring's axis; compare
 * it with the ring's own centroid direction to get the sense.
 */
function ringOrientation(p) {
  const n = p.length / 3;
  let nx = 0, ny = 0, nz = 0, cx = 0, cy = 0, cz = 0;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const ax = p[i * 3], ay = p[i * 3 + 1], az = p[i * 3 + 2];
    const bx = p[j * 3], by = p[j * 3 + 1], bz = p[j * 3 + 2];
    nx += ay * bz - az * by; ny += az * bx - ax * bz; nz += ax * by - ay * bx;
    cx += ax; cy += ay; cz += az;
  }
  return (nx * cx + ny * cy + nz * cz) > 0 ? 1 : -1;
}

const LAND  = toXYZ(decodeRings(LAND_ENC));
const LAND_CCW = LAND.map(ringOrientation);
const PLATE = toXYZ(decodeRings(PLATE_ENC));

function unit(lat, lng) {
  const a = lng * Math.PI / 180, b = lat * Math.PI / 180, cb = Math.cos(b);
  return [cb * Math.cos(a), cb * Math.sin(a), Math.sin(b)];
}

/* ------------------------------------------------------------ time scaling */
/* A pure log axis pinned at the present crushes deep time: the Cenozoic would
   eat 80% of the width. asinh behaves like a log for large arguments but stays
   finite at zero, and tying its knee to the window span makes the transform
   scale-invariant — every zoom level has the same feel, and the young edge of
   whatever window you are in is always the readable one. */
function makeScale(t0, t1, w) {
  const k = Math.max((t1 - t0) / 46, 1e-9);
  const u0 = Math.asinh(t0 / k), u1 = Math.asinh(t1 / k);
  const du = (u1 - u0) || 1;
  return {
    k, w,
    x: t => w * (1 - (Math.asinh(t / k) - u0) / du),
    t: x => k * Math.sinh(u0 + (1 - x / w) * du)
  };
}

/* Window span -> detail level 0..10, matching the zoom_band values in the data. */
const ZTAB = [[9.663, 0], [9, 0.6], [8, 2], [7, 3.5], [6, 5], [5, 6.5], [4, 8], [3, 9], [2, 10]];
function zoomLevel(span) {
  const L = Math.log10(Math.max(span, 100));
  if (L >= ZTAB[0][0]) return 0;
  if (L <= ZTAB[ZTAB.length - 1][0]) return 10;
  for (let i = 0; i < ZTAB.length - 1; i++) {
    const [a, av] = ZTAB[i], [b, bv] = ZTAB[i + 1];
    if (L <= a && L >= b) return av + (bv - av) * (a - L) / (a - b);
  }
  return 10;
}

/* ------------------------------------------------------------- formatting */
function ceYear(t) { return PRESENT - t; }

function fmtYear(y) {
  y = Math.round(y);
  return y <= 0 ? `${1 - y} BCE` : `${y} CE`;
}

/** One canonical internal scale; units are a display concern only. */
function fmtYbp(t, tight) {
  const a = Math.abs(t);
  if (a >= 1e9) return `${(t / 1e9).toFixed(2).replace(/\.?0+$/, '')} Ga`;
  if (a >= 1e6) {
    const v = t / 1e6;
    const s = v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
    return `${s.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')} Ma`;
  }
  if (a >= 12000) return `${(t / 1000).toFixed(a >= 100000 ? 0 : 1).replace(/\.0$/, '')} ka`;
  if (a >= 1) return fmtYear(ceYear(t));
  return tight ? 'now' : 'the present';
}

/** ± on a date, in the same unit as the date itself. */
function fmtPrecision(p) {
  if (!p) return null;
  if (p >= 1e9) return `± ${(p / 1e9).toFixed(2)} Ga`;
  if (p >= 1e6) return `± ${(p / 1e6).toFixed(p >= 1e7 ? 0 : 1)} Ma`;
  if (p >= 1000) return `± ${(p / 1000).toFixed(p >= 1e4 ? 0 : 1)} ka`;
  return `± ${Math.round(p)} yr`;
}

function fmtSpan(s) {
  if (s >= 1e9) return `${(s / 1e9).toFixed(2)} billion years`;
  if (s >= 1e6) return `${(s / 1e6).toFixed(s >= 1e7 ? 0 : 1)} million years`;
  if (s >= 1000) return `${Math.round(s / 1000).toLocaleString()} thousand years`;
  return `${Math.round(s).toLocaleString()} years`;
}

/* ------------------------------------------------ chronostratigraphic bands */
/* Real ICS colours and boundary ages. ICS ages are "before 1950"; ybp here is
   before 2025, so shift by 75 years — invisible at Ma scale, correct in the
   Holocene where the Meghalayan boundary is only 4.2 ka away. */
const LEVELS = ['eon', 'era', 'period', 'epoch', 'age'];
const BANDS = {};
for (const L of LEVELS) BANDS[L] = [];
for (const iv of ICS) {
  if (!BANDS[iv.t]) continue;
  BANDS[iv.t].push({ n: iv.n, b: iv.b * 1e6 + 75, e: iv.e * 1e6 + 75, c: iv.c });
}
// The international "eons" timescale omits the Hadean; the chart does not.
if (!BANDS.eon.some(b => b.n === 'Hadean')) {
  BANDS.eon.push({ n: 'Hadean', b: T_MAX, e: 4031e6, c: '#AE027E' });
}
for (const L of LEVELS) BANDS[L].sort((a, b) => b.b - a.b);

/* A sixth lane, so the ribbon stays alive once ICS has nothing left to say.
   Deliberately muted and cool-to-warm, so it never passes for an ICS band.
   Old World, approximate, and boundaries are conventional rather than defined. */
const HUMAN_BANDS = [
  { n: 'Palaeolithic',  b: 3300000, e: 11700, c: '#4E5A5E' },
  { n: 'Neolithic',     b: 11700,   e: 5325,  c: '#5A6866' },
  { n: 'Bronze Age',    b: 5325,    e: 3225,  c: '#6C7368' },
  { n: 'Iron Age',      b: 3225,    e: 2475,  c: '#7C7B66' },
  { n: 'Classical',     b: 2475,    e: 1549,  c: '#8D8360' },
  { n: 'Medieval',      b: 1549,    e: 525,   c: '#9E8859' },
  { n: 'Early Modern',  b: 525,     e: 265,   c: '#AF8B50' },
  { n: 'Industrial',    b: 265,     e: 80,    c: '#BE8C46' },
  { n: 'Nuclear',       b: 80,      e: 0,     c: '#C88F3F' }
];

/* ------------------------------------------------------------------ palette */
const SUBJECTS = ['geology', 'biology', 'evolution', 'chemistry', 'human_history', 'astronomy'];
const SUBJECT_LABEL = {
  geology: 'Geology', biology: 'Biology', evolution: 'Evolution',
  chemistry: 'Chemistry', human_history: 'Human history', astronomy: 'Astronomy'
};
const CSSV = {};
function readPalette() {
  const cs = getComputedStyle(document.documentElement);
  for (const s of SUBJECTS) CSSV[s] = cs.getPropertyValue('--sub-' + s).trim();
  for (const k of ['abyss', 'shale', 'shale-2', 'shale-3', 'chalk', 'chalk-dim', 'chalk-faint',
                   'cyanotype', 'cyanotype-d', 'ochre', 'rule', 'ocean-hi', 'ocean-lo',
                   'land', 'land-edge', 'plate'])
    CSSV[k] = cs.getPropertyValue('--' + k).trim();
}
function subjColor(subjects) { return CSSV[subjects[0]] || CSSV.chalk_dim || '#888'; }

function withAlpha(hex, a) {
  // Defensive: a missing palette key used to throw here, and the throw killed
  // boot() before it ever started the animation loop.
  const h = (hex || '').replace('#', '');
  if (h.length < 6) return hex;
  const n = parseInt(h.slice(0, 6), 16);
  return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`;
}

/* -------------------------------------------------------------------- state */
const S = {
  win: { t0: 0, t1: T_MAX },
  cursor: 66043000,
  kt: KT_MAX,
  ktA: 1975,
  subjects: new Set(SUBJECTS),
  focus: null,
  resolver: 'consensus',
  selection: null,
  hover: null,
  showPlates: true,
  basemap: 'satellite',          // 'satellite' | 'chart'
  rot: { lam: 30, phi: 12 },
  spin: { lam: 0, phi: 0 },
  tour: -1,
  playing: false
};

const R = { referents: {}, claims: {}, byRef: {}, edgesOut: {}, edgesIn: {} };
for (const r of GRAPH.referents) { R.referents[r.id] = r; R.byRef[r.id] = []; R.edgesOut[r.id] = []; R.edgesIn[r.id] = []; }
for (const c of GRAPH.claims) {
  R.claims[c.id] = c;
  if (R.byRef[c.about]) R.byRef[c.about].push(c);
}
for (const e of GRAPH.edges) {
  if (R.edgesOut[e.source]) R.edgesOut[e.source].push(e);
  if (R.edgesIn[e.target]) R.edgesIn[e.target].push(e);
}
/* Claims about claims still belong to a referent for placement — walk up. */
function rootReferent(claimId, depth) {
  const c = R.claims[claimId];
  if (!c) return null;
  if (R.referents[c.about]) return c.about;
  if ((depth || 0) > 6) return null;
  return rootReferent(c.about, (depth || 0) + 1);
}
for (const c of GRAPH.claims) {
  if (!R.referents[c.about]) {
    const root = rootReferent(c.id);
    if (root) R.byRef[root].push(c);
    c._meta = true;             // a claim about a claim: historiography, not geology
  }
}
