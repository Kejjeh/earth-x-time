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
    // hashSelf is recorded even when the URL already says this, because it is a
    // record of "the view we last knew the bar to be showing", not of what we
    // wrote. Setting it only after a successful write left it holding an older
    // hash, and the hashchange guard then ignored the Back that returned to it.
    hashSelf = h;
    if (h === location.hash) return;
    try { history.replaceState(null, '', h); } catch (_) { /* opaque origin; carry on */ }
  };
  // Dragging the globe changes the rotation sixty times a second. Debounced, so
  // the URL settles once the gesture does.
  if (now) put(); else hashTimer = setTimeout(put, 400);
}

function readHash() {
  try {
    // No early return on an empty hash: "" is a legitimate view - the default
    // one - and navigating Back to a bare URL has to restore it rather than
    // leave whatever the previous entry had on screen.
    const raw = (location.hash || '').replace(/^#/, '');
    const p = {};
    for (const kv of raw.split('&')) {
      const i = kv.indexOf('=');
      if (i > 0) p[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1));
    }
    const num = (v, lo, hi, d) => {
      const n = parseFloat(v);
      return isFinite(n) ? Math.max(lo, Math.min(hi, n)) : d;
    };
    /* `R.referents[id]` is truthy for "constructor", "toString" and every other
       name on Object.prototype, so a hash of #s=constructor passed validation
       and put a function into S.selection, which then threw in the render loop
       on every frame. Membership has to be an own-property test. */
    const own = (o, k) => typeof k === 'string' && Object.prototype.hasOwnProperty.call(o, k);

    /* Every field is SET, not patched. readHash used to leave a field alone when
       its key was absent, which is correct for a first load - the defaults are
       already in place - and wrong for every later one: pressing Back from a
       view with a selection to one without left the selection on screen, and the
       debounced writeHash then put it back into the URL, so the history entry
       silently rewrote itself and Forward went somewhere new. */
    S.kt = Math.round(num(p.k, KT_MIN, KT_MAX, KT_MAX));

    let t0 = 0, t1 = T_MAX;
    if (p.t) {
      const [a, b] = p.t.split('_');
      const u0 = num(a, 0, T_MAX, 0), u1 = num(b, 0, T_MAX, T_MAX);
      if (u1 - u0 >= 50) { t0 = u0; t1 = u1; }
    }
    S.win.t0 = t0; S.win.t1 = t1;

    const [ra, rb] = (p.r || '').split(',');
    S.rot.lam = num(ra, -100000, 100000, 30);
    S.rot.phi = num(rb, -89, 89, 12);
    ZOOMF = num(p.z, ZMIN, ZMAX, 0.86);
    S.resolver = ['consensus', 'frontier', 'spread'].includes(p.m) ? p.m : 'consensus';
    S.selection = own(R.referents, p.s) ? p.s : null;
    S.focus = SUBJECTS.includes(p.f) ? p.f : null;
    const off = new Set((p.x || '').split('.').filter(s => SUBJECTS.includes(s)));
    // Turning every subject off would show an empty globe and read as broken.
    S.subjects = new Set(off.size && off.size < SUBJECTS.length
      ? SUBJECTS.filter(s => !off.has(s)) : SUBJECTS);
    S.basemap = p.b === 'chart' ? 'chart' : 'satellite';
    S.showPlates = p.p !== '0';
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
  hashSelf = '';                  // consumed; a later Back to this view must not be ignored
  readHash();                     // false only means "no hash", which is a real view too
  syncControls();
  applyZoom();
  changed();
});
