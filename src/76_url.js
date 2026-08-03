/* ============================================================================
   THE VIEW IN THE URL

   Everything this page shows is a point in a small state space: two clocks, a
   rotation, a zoom, a resolver mode, a subject filter and a selection. Until now
   none of it left the tab, so "look at what happens to the K-Pg link in 1991"
   was a set of instructions rather than a link.

   Two rules the implementation has to respect:

   1. A malformed hash must never stop the page. Every value is parsed
      defensively, clamped to its own legal range, and checked against the data
      before it is applied; the whole read is wrapped, and a failure returns
      false and leaves the defaults alone. A URL is user input from a stranger.

   2. history.replaceState throws in a sandboxed iframe with an opaque origin -
      which is exactly where this page is often embedded. That is not worth
      breaking a working page over, so the failure is swallowed and the page
      simply has no shareable URL in that context.
   ========================================================================== */

let hashTimer = null;
let hashSelf = '';                    // the last hash we wrote, so we can ignore our own event

function encodeHash() {
  const p = [];
  p.push('k=' + S.kt);
  p.push('t=' + Math.round(S.win.t0) + '_' + Math.round(S.win.t1));
  p.push('r=' + S.rot.lam.toFixed(1) + ',' + S.rot.phi.toFixed(1));
  p.push('z=' + ZOOMF.toFixed(2));
  if (S.resolver !== 'consensus') p.push('m=' + S.resolver);
  if (S.selection) p.push('s=' + S.selection);
  if (S.focus) p.push('f=' + S.focus);
  const off = SUBJECTS.filter(x => !S.subjects.has(x));
  if (off.length) p.push('x=' + off.join('.'));
  if (S.basemap !== 'satellite') p.push('b=' + S.basemap);
  if (!S.showPlates) p.push('p=0');
  return '#' + p.join('&');
}

function writeHash(now) {
  clearTimeout(hashTimer);
  const put = () => {
    const h = encodeHash();
    if (h === location.hash) return;
    hashSelf = h;
    try { history.replaceState(null, '', h); } catch (_) { /* opaque origin; carry on */ }
  };
  // Dragging the globe changes the rotation sixty times a second. Debounced, so
  // the URL settles once the gesture does.
  if (now) put(); else hashTimer = setTimeout(put, 400);
}

function readHash() {
  try {
    const raw = (location.hash || '').replace(/^#/, '');
    if (!raw) return false;
    const p = {};
    for (const kv of raw.split('&')) {
      const i = kv.indexOf('=');
      if (i > 0) p[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1));
    }
    const num = (v, lo, hi, d) => {
      const n = parseFloat(v);
      return isFinite(n) ? Math.max(lo, Math.min(hi, n)) : d;
    };

    S.kt = Math.round(num(p.k, KT_MIN, KT_MAX, S.kt));

    if (p.t) {
      const [a, b] = p.t.split('_');
      const t0 = num(a, 0, T_MAX, S.win.t0), t1 = num(b, 0, T_MAX, S.win.t1);
      if (t1 - t0 >= 50) { S.win.t0 = t0; S.win.t1 = t1; }
    }
    if (p.r) {
      const [a, b] = p.r.split(',');
      S.rot.lam = num(a, -100000, 100000, S.rot.lam);
      S.rot.phi = num(b, -89, 89, S.rot.phi);
    }
    if (p.z) ZOOMF = num(p.z, ZMIN, ZMAX, ZOOMF);
    if (p.m && ['consensus', 'frontier', 'spread'].includes(p.m)) S.resolver = p.m;
    if (p.s && R.referents[p.s]) S.selection = p.s;
    if (p.f && SUBJECTS.includes(p.f)) S.focus = p.f;
    if (p.x) {
      const off = new Set(p.x.split('.').filter(s => SUBJECTS.includes(s)));
      // Turning every subject off would show an empty globe and look broken.
      if (off.size < SUBJECTS.length) S.subjects = new Set(SUBJECTS.filter(s => !off.has(s)));
    }
    if (p.b === 'chart' || p.b === 'satellite') S.basemap = p.b;
    if (p.p === '0') S.showPlates = false;
    return true;
  } catch (err) {
    console.warn('unreadable view in the URL; using defaults', err);
    return false;
  }
}

/** Controls whose pressed state lives in the DOM rather than in a render pass. */
function syncControls() {
  for (const b of document.querySelectorAll('#resolver button')) {
    b.setAttribute('aria-pressed', String(b.dataset.mode === S.resolver));
  }
  const note = document.getElementById('resnote');
  if (note) note.textContent = RESOLVER_NOTE[S.resolver] || '';
  const bm = document.getElementById('btn-basemap');
  if (bm) {
    const sat = S.basemap === 'satellite';
    bm.setAttribute('aria-pressed', String(sat));
    bm.textContent = sat ? 'Satellite' : 'Chart';
  }
  const pl = document.getElementById('btn-plates');
  if (pl) pl.setAttribute('aria-pressed', String(S.showPlates));
  const st = document.getElementById('stage');
  if (st) st.classList.toggle('space', S.basemap === 'satellite');
}

/* Back, forward, and someone pasting a different view into the same tab. */
window.addEventListener('hashchange', () => {
  if (location.hash === hashSelf) return;
  if (!readHash()) return;
  syncControls();
  resizeGlobe();
  SURF.key = '';
  changed();
});
