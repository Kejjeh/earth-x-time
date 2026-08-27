/* ============================================================================
   WIRING
   Every control below does exactly one thing: mutate axis state and invalidate.
   Nothing filters anything itself — that is queryFacts's job.
   ========================================================================== */

let needGlobe = true, needChron = true, needKrail = true, needPanel = true;
function markAll() { needGlobe = needChron = needKrail = needPanel = true; }
function changed() { invalidate(); markAll(); paintOnInput(); writeHash(); }

function setKt(v) {
  const n = Math.max(KT_MIN, Math.min(KT_MAX, Math.round(v)));
  if (n === S.kt) return;
  S.kt = n; changed();
}
function setWindow(t0, t1) {
  const span = Math.max(50, Math.min(T_MAX, t1 - t0));
  let a = Math.max(0, t0), b = a + span;
  if (b > T_MAX) { b = T_MAX; a = Math.max(0, b - span); }
  S.win.t0 = a; S.win.t1 = b;
  changed();
}
/* Where the selection came from is an argument, not something to infer. Under a
   coarse pointer the detail panel is in grid row 3, roughly 1170px below a 46vh
   stage, and the tooltip never fires on touch — it lives after the drag branch
   returns — so a tap on a marker changes nothing the tapper can see. Only a
   selection made ON a canvas scrolls the panel up: Escape passes null, a
   data-goto hop is already inside the panel, and the guided path is driving the
   stage itself. */
const COARSE = matchMedia('(pointer:coarse)');
function setSelection(id, opts) {
  S.selection = id;
  changed();
  if (id && opts && opts.fromCanvas && COARSE.matches && elDetail) {
    try {
      elDetail.scrollIntoView({ block: 'start', behavior: RM.matches ? 'auto' : 'smooth' });
    } catch (_) { elDetail.scrollIntoView(true); }
  }
}

/* ------------------------------------------------------------------- globe */
let gDrag = null, gMoved = 0;
const gVel = [];

/* One clamp for the zoom, in one place. The wheel, the keyboard and the pinch
   were otherwise each carrying their own copy of the same two magic numbers. */
const ZMIN = 0.45, ZMAX = 3.2;
function setZoom(z) {
  const n = Math.max(ZMIN, Math.min(ZMAX, z));
  if (n === ZOOMF) return false;
  ZOOMF = n; applyZoom(); needGlobe = true;
  return true;
}

/* Two-finger zoom.
 *
 * touch-action:none already routes touches here as pointer events, so one finger
 * has always dragged; there was simply nothing listening for a second. Rather
 * than a separate gesture recogniser, keep the set of live pointers and treat
 * "two or more down" as the pinch state.
 *
 * The baseline is re-established whenever the set changes - a finger added, a
 * finger lifted, a third finger landing - because otherwise the distance ratio
 * is measured against a pair that no longer exists and the globe jumps. Same
 * reason the last finger up hands back to a fresh drag origin instead of
 * resuming the one from before the pinch. */
const PTRS = new Map();
let pinch = null;

function pinchState() {
  const it = PTRS.values();
  const a = it.next().value, b = it.next().value;
  if (!a || !b) return null;
  return { d: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
           mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
}
function rebasePinch() {
  const s = pinchState();
  pinch = s ? { d0: s.d, z0: ZOOMF, mx: s.mx, my: s.my } : null;
}

gcv.addEventListener('pointerdown', e => {
  try { gcv.setPointerCapture(e.pointerId); } catch (_) { /* drag works without capture */ }
  // A primary pointerdown means a gesture is starting with nothing else held, so
  // it is also the moment to forget any pointer whose "up" we never received.
  if (e.isPrimary) { PTRS.clear(); pinch = null; }
  PTRS.set(e.pointerId, { x: e.clientX, y: e.clientY });
  S.spin.lam = S.spin.phi = 0;
  TW = null;                 // a hand on the globe outranks a fly-to in progress
  gVel.length = 0;
  gcv.classList.add('dragging');
  if (PTRS.size >= 2) {
    gDrag = null;            // a pinch is not a drag...
    gMoved = 999;            // ...and must not land as a click when it ends
    rebasePinch();
    return;
  }
  gDrag = { x: e.clientX, y: e.clientY, t: performance.now() };
  gMoved = 0;
});

gcv.addEventListener('pointermove', e => {
  if (PTRS.has(e.pointerId)) PTRS.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pinch && PTRS.size >= 2) {
    const s = pinchState();
    if (s) {
      setZoom(pinch.z0 * (s.d / pinch.d0));
      const k = 180 / (GR * Math.PI) * 1.1;
      S.rot.lam += (s.mx - pinch.mx) * k;
      S.rot.phi = Math.max(-89, Math.min(89, S.rot.phi + (s.my - pinch.my) * k));
      pinch.mx = s.mx; pinch.my = s.my;
      needGlobe = true; paintOnInput();
    }
    return;
  }
  const rect = gcv.getBoundingClientRect();
  if (gDrag) {
    const dx = e.clientX - gDrag.x, dy = e.clientY - gDrag.y;
    gMoved += Math.abs(dx) + Math.abs(dy);
    const k = 180 / (GR * Math.PI) * 1.1;
    S.rot.lam += dx * k;
    S.rot.phi = Math.max(-89, Math.min(89, S.rot.phi + dy * k));
    gVel.push({ dx, dy, t: performance.now() });
    if (gVel.length > 5) gVel.shift();
    gDrag = { x: e.clientX, y: e.clientY, t: performance.now() };
    needGlobe = true;
    paintOnInput();
    return;
  }
  const mx = e.clientX - rect.left, my = e.clientY - rect.top;
  let best = null, bd = 1e9;
  for (const h of HIT) {
    const d = Math.hypot(h.x - mx, h.y - my);
    if (d < h.r && d < bd) { bd = d; best = h; }
  }
  const id = best ? best.id : null;
  if (id !== S.hover) { S.hover = id; needGlobe = true; paintOnInput(); }
  const tip = document.getElementById('tip');
  if (id) {
    const it = facts().items[id];
    tip.innerHTML = `<span class="t">${esc(it.ref.label)}</span>
      <span class="d">${it.res.winner ? fmtYbp(it.res.winner.claim.earth_time_start) : fmtYbp(it.res.oldest) + ' – ' + fmtYbp(it.res.youngest)}${
        it.res.disputed ? ' · disputed' : ''}</span>`;
    tip.style.left = best.x + 'px'; tip.style.top = best.y + 'px';
    tip.classList.add('on');
    gcv.style.cursor = 'pointer';
  } else {
    tip.classList.remove('on');
    gcv.style.cursor = '';
  }
});

function endGlobeDrag(e) {
  gcv.classList.remove('dragging');   // before the guard: a cancelled pinch has no gDrag
  if (!gDrag) return;
  gDrag = null;
  if (!RM.matches && gVel.length) {
    const now = performance.now();
    const recent = gVel.filter(v => now - v.t < 90);
    if (recent.length) {
      const k = 180 / (GR * Math.PI) * 1.1;
      S.spin.lam = recent.reduce((a, v) => a + v.dx, 0) / recent.length * k * 0.9;
      S.spin.phi = recent.reduce((a, v) => a + v.dy, 0) / recent.length * k * 0.9;
    }
  }
  if (gMoved < 5) {
    const rect = gcv.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    let best = null, bd = 1e9;
    for (const h of HIT) {
      const d = Math.hypot(h.x - mx, h.y - my);
      if (d < h.r && d < bd) { bd = d; best = h; }
    }
    setSelection(best ? best.id : null, { fromCanvas: true });
  }
}
/* Lifting a finger mid-pinch must not end the gesture, and must not be read as a
   click. Only the last one up is a real pointerup.

   pointercancel has to do exactly the same bookkeeping, which it did not: it
   nulled the pinch and stopped. Two ways that bites, both reachable on a real
   phone - Android cancels a stationary finger when the long-press gesture takes
   over, iOS cancels one on palm rejection. Three fingers down and the first is
   cancelled: the baseline still describes a pair that no longer exists, so the
   next move divides by the wrong distance and the globe snaps to minimum zoom
   and jumps a hundred degrees of longitude in one frame. Two fingers down and
   one is cancelled: the survivor never gets a drag origin back, so it stops
   rotating the globe and starts hovering tooltips instead, and the grabbing
   cursor is still stuck on when everything is finally lifted. */
function releasePointer(e) {
  PTRS.delete(e.pointerId);
  if (PTRS.size >= 2) { rebasePinch(); return true; }
  pinch = null;
  if (PTRS.size === 1) {
    const p = PTRS.values().next().value;
    gDrag = { x: p.x, y: p.y, t: performance.now() };   // hand back without a jump
    gMoved = 999; gVel.length = 0;
    return true;
  }
  return false;
}
gcv.addEventListener('pointerup', e => { if (!releasePointer(e)) endGlobeDrag(e); });
gcv.addEventListener('pointercancel', e => {
  if (releasePointer(e)) return;
  gDrag = null; gVel.length = 0;
  gcv.classList.remove('dragging');
});

gcv.addEventListener('wheel', e => {
  e.preventDefault();
  setZoom(ZOOMF * (e.deltaY > 0 ? 0.92 : 1.087));
  paintOnInput();
}, { passive: false });

gcv.addEventListener('keydown', e => {
  const step = e.shiftKey ? 15 : 5;
  if (e.key === 'ArrowLeft') { S.rot.lam -= step; needGlobe = true; }
  else if (e.key === 'ArrowRight') { S.rot.lam += step; needGlobe = true; }
  else if (e.key === 'ArrowUp') { S.rot.phi = Math.min(89, S.rot.phi + step); needGlobe = true; }
  else if (e.key === 'ArrowDown') { S.rot.phi = Math.max(-89, S.rot.phi - step); needGlobe = true; }
  else if (e.key === '+' || e.key === '=') setZoom(ZOOMF * 1.12);
  else if (e.key === '-') setZoom(ZOOMF * 0.89);
  else if (e.key === 'Escape') setSelection(null);
  else return;
  paintOnInput();
  e.preventDefault();
});

/* ------------------------------------------------------------------- chron */
let cDrag = null;

function chronPos(e) {
  const r = ccv.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}

ccv.addEventListener('pointerdown', e => {
  try { ccv.setPointerCapture(e.pointerId); } catch (_) {}
  const p = chronPos(e);
  const sc = SCALE || chronScale();
  const cursorX = sc.x(S.cursor);
  let hit = null, bd = 1e9;
  for (const h of CHIT) {
    const d = Math.hypot(h.x - p.x, h.y - p.y);
    if (d < h.r && d < bd) { bd = d; hit = h; }
  }
  if (hit) { cDrag = { mode: 'click', id: hit.id }; return; }
  if (Math.abs(p.x - cursorX) < 7) { cDrag = { mode: 'cursor' }; return; }
  cDrag = { mode: 'pan', x: p.x, t0: S.win.t0, t1: S.win.t1, moved: 0 };
});

ccv.addEventListener('pointermove', e => {
  const p = chronPos(e);
  if (!cDrag) {
    let hit = null, bd = 1e9;
    for (const h of CHIT) {
      const d = Math.hypot(h.x - p.x, h.y - p.y);
      if (d < h.r && d < bd) { bd = d; hit = h; }
    }
    const id = hit ? hit.id : null;
    if (id !== S.hover) { S.hover = id; needChron = true; needGlobe = true; paintOnInput(); }
    ccv.style.cursor = hit ? 'pointer' : 'crosshair';
    return;
  }
  if (cDrag.mode === 'cursor') {
    const sc = SCALE || chronScale();
    S.cursor = Math.max(0, Math.min(T_MAX, sc.t(p.x)));
    needChron = true; needPanel = true; paintOnInput();
  } else if (cDrag.mode === 'pan') {
    cDrag.moved += 1;
    const k = Math.max((cDrag.t1 - cDrag.t0) / 46, 1e-9);
    const u0 = Math.asinh(cDrag.t0 / k), u1 = Math.asinh(cDrag.t1 / k);
    const shift = ((p.x - cDrag.x) / CW) * (u1 - u0);
    let a = k * Math.sinh(u0 + shift), b = k * Math.sinh(u1 + shift);
    if (a < 0) { b -= a; a = 0; }
    if (b > T_MAX) { a -= (b - T_MAX); b = T_MAX; a = Math.max(0, a); }
    setWindow(a, b);
  }
});

ccv.addEventListener('pointerup', e => {
  if (cDrag && cDrag.mode === 'click')
    setSelection(cDrag.id === S.selection ? null : cDrag.id, { fromCanvas: true });
  else if (cDrag && cDrag.mode === 'pan' && cDrag.moved < 2) {
    const sc = SCALE || chronScale();
    S.cursor = Math.max(0, Math.min(T_MAX, sc.t(chronPos(e).x)));
    needChron = true; needPanel = true;
  }
  cDrag = null;
});
ccv.addEventListener('pointercancel', () => { cDrag = null; });

ccv.addEventListener('wheel', e => {
  e.preventDefault();
  const p = chronPos(e);
  const sc = SCALE || chronScale();
  const tp = Math.max(0, sc.t(p.x));
  const f = e.deltaY > 0 ? 1.16 : 0.862;
  const k = Math.max((S.win.t1 - S.win.t0) / 46, 1e-9);
  const up = Math.asinh(tp / k);
  const u0 = Math.asinh(S.win.t0 / k), u1 = Math.asinh(S.win.t1 / k);
  let a = k * Math.sinh(up + (u0 - up) * f);
  let b = k * Math.sinh(up + (u1 - up) * f);
  setWindow(Math.max(0, a), Math.min(T_MAX, b));
}, { passive: false });

ccv.addEventListener('keydown', e => {
  const span = S.win.t1 - S.win.t0;
  if (e.key === 'ArrowLeft') { S.cursor = Math.min(T_MAX, S.cursor + span * (e.shiftKey ? .1 : .02)); }
  else if (e.key === 'ArrowRight') { S.cursor = Math.max(0, S.cursor - span * (e.shiftKey ? .1 : .02)); }
  else if (e.key === '+' || e.key === '=') { setWindow(S.win.t0, S.win.t0 + span * 0.8); return e.preventDefault(); }
  else if (e.key === '-') { setWindow(S.win.t0, S.win.t0 + span * 1.25); return e.preventDefault(); }
  else return;
  needChron = true; needPanel = true; paintOnInput();
  e.preventDefault();
});

document.getElementById('presets').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  setWindow(+b.dataset.t0, +b.dataset.t1);
});

/* ------------------------------------------------------------------- krail */
let kDrag = false;
function kSet(e) {
  const r = kcv.getBoundingClientRect();
  setKt(yToKt(e.clientY - r.top));
}
kcv.addEventListener('pointerdown', e => { try { kcv.setPointerCapture(e.pointerId); } catch (_) {} kDrag = true; stopReplay(); kSet(e); });
kcv.addEventListener('pointermove', e => { if (kDrag) kSet(e); });
kcv.addEventListener('pointerup', () => { kDrag = false; });
kcv.addEventListener('pointercancel', () => { kDrag = false; });
kcv.addEventListener('keydown', e => {
  const step = e.shiftKey ? 25 : 1;
  if (e.key === 'ArrowUp' || e.key === 'ArrowRight') setKt(S.kt + step);
  else if (e.key === 'ArrowDown' || e.key === 'ArrowLeft') setKt(S.kt - step);
  else if (e.key === 'PageUp') setKt(S.kt + 25);
  else if (e.key === 'PageDown') setKt(S.kt - 25);
  else if (e.key === 'Home') setKt(KT_MIN);
  else if (e.key === 'End') setKt(KT_MAX);
  else return;
  e.preventDefault();
});

/* ---------------------------------------------------------------- controls */
document.getElementById('resolver').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  S.resolver = b.dataset.mode;
  for (const x of e.currentTarget.children)
    x.setAttribute('aria-pressed', String(x === b));
  document.getElementById('resnote').textContent = RESOLVER_NOTE[S.resolver];
  changed();
});

document.getElementById('subjects').addEventListener('click', e => {
  const b = e.target.closest('.sub'); if (!b) return;
  const s = b.dataset.sub;
  if (e.detail > 1) return;
  if (S.subjects.has(s)) S.subjects.delete(s); else S.subjects.add(s);
  if (S.subjects.size === 0) S.subjects = new Set(SUBJECTS);
  changed();
});
document.getElementById('subjects').addEventListener('dblclick', e => {
  const b = e.target.closest('.sub'); if (!b) return;
  const s = b.dataset.sub;
  S.focus = S.focus === s ? null : s;
  if (S.focus) S.subjects = new Set(SUBJECTS);
  changed();
});

/* A Connections link used to be a bare setSelection, which skipped every gate
   chooseResult applies: with a subject switched off it selected a referent with
   no mark on the globe or the timeline and rendered a full panel for it anyway.
   Same helper, same guarantees. No stage scroll - the reader is looking at the
   panel, and the panel rebuilds in place. */
elDetail.addEventListener('click', e => {
  const b = e.target.closest('[data-goto]'); if (!b) return;
  const plan = revealReferent(b.dataset.goto);
  if (!plan) return;
  flyTo(plan);
  elDetail.scrollTop = 0;
});

/* Both of these are in the hash, so both have to go through changed().
   Setting needGlobe alone left the URL describing a view the page was no longer
   showing, and the setting then arrived in the hash on the next unrelated
   interaction - the same silent history rewrite src/76_url.js already fixed once
   for the selection. */
document.getElementById('btn-basemap').addEventListener('click', e => {
  S.basemap = S.basemap === 'satellite' ? 'chart' : 'satellite';
  const sat = S.basemap === 'satellite';
  e.currentTarget.setAttribute('aria-pressed', String(sat));
  e.currentTarget.textContent = sat ? 'Satellite' : 'Chart';
  document.getElementById('stage').classList.toggle('space', sat);
  changed();
});

document.getElementById('btn-plates').addEventListener('click', e => {
  S.showPlates = !S.showPlates;
  e.currentTarget.setAttribute('aria-pressed', String(S.showPlates));
  changed();
});
document.getElementById('btn-now').addEventListener('click', () => { stopReplay(); setKt(KT_MAX); });
document.getElementById('btn-play').addEventListener('click', () => S.playing ? stopReplay() : startReplay());

document.getElementById('btn-theme').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const dark = cur ? cur === 'dark' : !matchMedia('(prefers-color-scheme: light)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
  readPalette(); markAll();
});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { readPalette(); markAll(); });

/* The dialog carries role="dialog" aria-modal="true", which tells assistive
   technology that everything outside it is hidden. Nothing made that true:
   focus stayed on the opener - inside the part just declared hidden - thirty
   background controls remained tabbable, and Tab walked straight out. inert
   makes the claim honest, and the opener gets its focus back on the way out. */
const diffwrap = document.getElementById('diffwrap');
const btnDiff = document.getElementById('btn-diff');
const diffA = document.getElementById('diff-a');
const diffB = document.getElementById('diff-b');
let diffOpener = null;

function setDiffOpen(on) {
  if (on === !diffwrap.hidden) return;
  diffwrap.hidden = !on;
  btnDiff.setAttribute('aria-pressed', String(on));
  for (const el of [document.querySelector('.app'), document.getElementById('tourbar')]) {
    if (el) el.toggleAttribute('inert', on);
  }
  if (on) {
    diffOpener = document.activeElement;
    diffB.value = S.kt;
    diffA.value = S.ktA;
    renderDiff();
    diffA.focus();
  } else {
    const back = diffOpener && diffOpener.isConnected ? diffOpener : btnDiff;
    diffOpener = null;
    try { back.focus(); } catch (_) { /* it may have gone away; never fatal */ }
  }
}

btnDiff.addEventListener('click', () => setDiffOpen(diffwrap.hidden));
document.getElementById('diff-close').addEventListener('click', () => setDiffOpen(false));

/* Take a year only once it is a complete one that exists on the rail. Clamping
   per keystroke would snap the "1" on the way to "1850" to 1650 and make the
   field unusable; `+value || dflt` was worse still, because 0 is falsy, so the
   first character of "2000" silently jumped the comparison to 1975. The field
   is reconciled with the state on change, so it can never be left showing a
   year the page is not actually comparing. */
function yearFromInput(el) {
  const n = parseInt(el.value, 10);
  return isFinite(n) && n >= KT_MIN && n <= KT_MAX ? n : null;
}
diffA.addEventListener('input', () => {
  const n = yearFromInput(diffA);
  if (n === null) return;
  S.ktA = n; renderDiff();
});
diffB.addEventListener('input', () => {
  const n = yearFromInput(diffB);
  if (n === null) return;
  setKt(n); renderDiff();
});
diffA.addEventListener('change', () => { diffA.value = S.ktA; renderDiff(); });
diffB.addEventListener('change', () => { diffB.value = S.kt; renderDiff(); });

document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !diffwrap.hidden) setDiffOpen(false);
});

/* -------------------------------------------------------------- guided path */
const TOUR = [
  { id: 'chicxulub_impact', kt: 1995, win: [0, 3.0e8],
    text: 'A ten-kilometre asteroid hits the Yucatán platform. One point on the map, and the reach of it is carried by the arcs, not by the size of the dot.' },
  { id: 'kpg_extinction', kt: 1995, win: [0, 2.0e8],
    text: 'Three-quarters of species end here. Drag the right-hand rail back to 1975 and the link you are looking at does not exist yet.' },
  { id: 'mammal_radiation', kt: KT_MAX, win: [0, 1.0e8],
    text: 'With the large-bodied niches empty, mammals radiate. The chain has just crossed from geology into biology.' },
  { id: 'first_primates', kt: KT_MAX, win: [0, 8.0e7],
    text: 'Primates appear in the aftermath. Isolate evolution in the left-hand panel and this link still shows, because the graph is one graph.' },
  { id: 'hominins', kt: KT_MAX, win: [0, 1.2e7],
    text: 'The hominin line separates from the chimpanzee line. Molecular clocks and fossils disagree about when, so this draws as a band.' },
  { id: 'homo_sapiens', kt: KT_MAX, win: [0, 1.0e6],
    text: 'Us. In 2016 this sat near 200,000 years; Jebel Irhoud moved it to about 315,000. Switch the resolver to Newest and watch it jump.' }
];
let TW = null;

function flyTo(step) {
  const it = queryFacts({ ...S, kt: step.kt }).items[step.id];
  const g = it && it.res.geometry;
  const target = { lam: S.rot.lam, phi: S.rot.phi };
  if (g && (g.mode === 'point' || g.mode === 'region')) {
    let lam = -g.lng;
    while (lam - S.rot.lam > 180) lam -= 360;
    while (lam - S.rot.lam < -180) lam += 360;
    target.lam = lam; target.phi = Math.max(-70, Math.min(70, g.lat));
  }
  TW = {
    t: 0, dur: RM.matches ? 0.01 : 1.1,
    from: { lam: S.rot.lam, phi: S.rot.phi, t0: S.win.t0, t1: S.win.t1, kt: S.kt },
    to: { lam: target.lam, phi: target.phi, t0: step.win[0], t1: step.win[1], kt: step.kt }
  };
  setSelection(step.id);
}
function tourGo(i) {
  if (i < 0 || i >= TOUR.length) return tourExit();
  S.tour = i;
  const step = TOUR[i];
  document.getElementById('tourbar').hidden = false;
  document.getElementById('tour-n').textContent = `${i + 1} / ${TOUR.length}`;
  document.getElementById('tour-step').innerHTML =
    `<b>${esc(R.referents[step.id].label)}</b>${esc(step.text)}`;
  flyTo(step);
}
function tourExit() { S.tour = -1; document.getElementById('tourbar').hidden = true; }
document.getElementById('btn-tour').addEventListener('click', () => tourGo(0));
document.getElementById('tour-next').addEventListener('click', () => tourGo(S.tour + 1));
document.getElementById('tour-prev').addEventListener('click', () => tourGo(S.tour - 1));
document.getElementById('tour-exit').addEventListener('click', tourExit);

/* -------------------------------------------------------------- render loop */
function ease(t) { return t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }

/*
 * render(dt) does the work; frame(now) only schedules it.
 *
 * They were one function, and everything the page shows was drawn from inside
 * the requestAnimationFrame callback. rAF does not fire in a document whose
 * visibilityState is "hidden" — a background tab, an offscreen preview pane,
 * some embeddings — so the entire UI simply never appeared, while every static
 * thing boot() writes did. Splitting them lets a watchdog paint without rAF,
 * and stops each manual paint from starting a second animation chain that all
 * run at once when the page finally becomes visible.
 */
let last = performance.now();
let lastPaint = 0;
let lastRafAt = -1e9;

function render(dt) {
  lastPaint = performance.now();
  sizeGuard();

  if (TW) {
    TW.t += dt;
    const p = Math.min(1, TW.t / TW.dur), e = ease(p);
    S.rot.lam = TW.from.lam + (TW.to.lam - TW.from.lam) * e;
    S.rot.phi = TW.from.phi + (TW.to.phi - TW.from.phi) * e;
    const lg = (a, b) => Math.exp(Math.log(Math.max(a, 1)) + (Math.log(Math.max(b, 1)) - Math.log(Math.max(a, 1))) * e);
    setWindow(TW.from.t0 + (TW.to.t0 - TW.from.t0) * e, lg(TW.from.t1, TW.to.t1));
    setKt(Math.round(TW.from.kt + (TW.to.kt - TW.from.kt) * e));
    needGlobe = true;
    if (p >= 1) TW = null;
  }

  if (S.playing) tickReplay(dt);

  if ((S.spin.lam || S.spin.phi) && !gDrag) {
    S.rot.lam += S.spin.lam;
    S.rot.phi = Math.max(-89, Math.min(89, S.rot.phi + S.spin.phi));
    S.spin.lam *= 0.94; S.spin.phi *= 0.94;
    if (Math.abs(S.spin.lam) < 0.008 && Math.abs(S.spin.phi) < 0.008) S.spin.lam = S.spin.phi = 0;
    needGlobe = true;
  }

  const animating = !RM.matches && facts().edges.length > 0;
  if (needGlobe || animating) { drawGlobe(dt); needGlobe = false; }
  if (needChron) { drawChron(); needChron = false; }
  if (needKrail) { drawKrail(); needKrail = false; }
  if (needPanel) {
    renderDetail(); renderSubjects();
    document.getElementById('asof-year').textContent = S.kt;
    document.getElementById('krail-year').textContent = S.kt;
    document.getElementById('epistemic').textContent = epistemicCaption();
    const span = S.win.t1 - S.win.t0;
    document.getElementById('rd-window').textContent =
      S.win.t0 <= 0 && S.win.t1 >= T_MAX * 0.99
        ? 'all 4.54 billion years'
        : `${fmtYbp(S.win.t1)} to ${fmtYbp(S.win.t0)} · ${fmtSpan(span)} wide`;
    const ctx = cursorContext(S.cursor);
    document.getElementById('rd-cursor').innerHTML =
      `Cursor at <b>${fmtYbp(S.cursor)}</b>${ctx.length ? ' · ' + esc(ctx.join(' · ')) : ''}`;
    kcv.setAttribute('aria-valuenow', S.kt);
    ccv.setAttribute('aria-valuenow', Math.round(S.cursor));
    if (!diffwrap.hidden) renderDiff();
    needPanel = false;
  }
}

function frame(now) {
  lastRafAt = performance.now();
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  try { render(dt); } catch (err) { console.error('render failed', err); }
  requestAnimationFrame(frame);
}

/** Paint immediately, outside the animation loop. */
function renderNow() {
  last = performance.now();
  try { render(0.016); } catch (err) { console.error('render failed', err); }
}

/*
 * Paint straight from the input handler when rAF is not running.
 *
 * Where visibilityState is "hidden" rAF never fires, so the only thing painting
 * is the watchdog — four frames a second, which makes dragging the globe feel
 * broken. Pointer and wheel events are not throttled the way rAF and background
 * timers are, so rendering inside the handler restores a smooth drag: the frame
 * rate becomes the event rate. Throttled to ~90fps so a fast trackpad cannot
 * queue more paints than we can serve, and guarded against re-entry.
 */
let painting = false;
/* Has the animation loop actually run lately?

   The old test asked whether a frame had been *requested*, which stays true
   forever after the first one: rAF stops firing but the flag never clears,
   while lastPaint keeps being refreshed by the watchdog. So the guard read
   "rAF is alive" permanently and paintOnInput returned early on every input,
   dropping the page back to the 250 ms watchdog - four frames a second. That
   is the unresponsiveness. Ask when a frame last actually ran. */
function rafIsLive() { return performance.now() - lastRafAt < 120; }

/* Paint on every input event; no time throttle.

   A throttle needs a trailing timer to make up skipped frames, and in a hidden
   document - exactly the case that made painting from input necessary - chained
   timers are clamped to about 1 Hz, so the make-up frame never arrives. There is
   no need for one: a paint is ~1 ms on a cache hit, the adaptive scale keeps a
   miss cheap, the re-entrancy guard stops overlap, and the event loop cannot
   deliver the next move until this handler returns. Sharpening stays deferred,
   because that frame is expensive and belongs after the gesture. */
let sharpen = null;
function scheduleSharpen() {
  if (sharpen) clearTimeout(sharpen);
  sharpen = setTimeout(() => { sharpen = null; needGlobe = true; renderNow(); }, 190);
}
function paintOnInput() {
  LAST_INPUT_AT = performance.now();
  lastInteraction = LAST_INPUT_AT;
  scheduleSharpen();
  writeHash();                    // debounced; the URL settles when the gesture does
  if (painting || rafIsLive()) return;
  painting = true;
  try { renderNow(); } finally { painting = false; }
}

/* If rAF has not painted recently and something is dirty, paint anyway. This is
   what makes the page work at all where rAF is paused; animation stops, but the
   globe, the ribbon and the panels are all there and still respond. */

/* ------------------------------------------------------- the animation clock

   Measured in a document whose visibilityState is "hidden":

       requestAnimationFrame        0 Hz   (never fires)
       main-thread setInterval(16)  1.3 Hz (clamped by intensive throttling)
       Worker setInterval(16)      61.7 Hz (not throttled)

   Input already paints itself, so dragging is smooth regardless. But anything
   that animates on its own — the travelling dots along causal arcs, the pulse
   on planet-wide facts, the inertia after a flick, Replay sweeping the
   knowledge rail — has no clock at all, and ran at the watchdog's 1.3 Hz.

   A dedicated worker's timer is exempt from that throttling, so one posts a
   tick and the main thread renders on it. MessageChannel also escapes the
   clamp, at 330,000 Hz, but that is a busy-spin rather than a clock.

   The beat stands down the moment rAF starts working, so a normal foreground
   tab is driven by rAF exactly as before, and it stops rendering after two
   minutes without input so a genuinely backgrounded tab is not animated for
   nobody. If the host's CSP forbids blob workers it degrades to what we had. */
let beat = null;
let lastInteraction = performance.now();
const BEAT_IDLE_MS = 120000;

function isAnimating() {
  if (RM.matches) return false;
  if (Math.abs(S.spin.lam) > 0.008 || Math.abs(S.spin.phi) > 0.008) return true;
  if (S.playing || TW) return true;              // Replay, and the guided path
  return facts().edges.length > 0;               // arcs animate continuously
}

function onBeat() {
  if (rafIsLive()) return;                       // the real loop is back
  if (performance.now() - lastInteraction > BEAT_IDLE_MS) return;
  const dirty = needGlobe || needChron || needKrail || needPanel;
  if (!dirty && !isAnimating()) return;
  const now = performance.now();
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  if (isAnimating()) needGlobe = true;           // arcs and spin repaint the globe
  try { render(dt); } catch (err) { console.error('render failed', err); }
}

function startHeartbeat() {
  if (beat) return;
  try {
    const url = URL.createObjectURL(new Blob(
      ['setInterval(function(){postMessage(0)},16);'], { type: 'text/javascript' }));
    beat = new Worker(url);
    URL.revokeObjectURL(url);
    beat.onmessage = onBeat;
  } catch (_) {
    beat = null;                                  // CSP may forbid it; carry on
  }
}

setInterval(() => {
  if (performance.now() - lastPaint > 400 &&
      (needGlobe || needChron || needKrail || needPanel)) renderNow();
}, 250);

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { markAll(); renderNow(); }
});

/* ------------------------------------------------------------------- start */
function boot() {
  readPalette();
  readHash();                     // a shared view wins over the defaults...
  syncControls();                 // ...and the controls have to say so
  resizeGlobe(); resizeChron(); resizeKrail();
  /* readPalette() keys subjects as CSSV.geology, not CSSV['sub-geology']. Reading
     the wrong key passed undefined into withAlpha, which threw — and because
     this sits before requestAnimationFrame(frame), that silent TypeError meant
     the animation loop was never started at all. Everything ran off the
     throttled watchdog instead. Decoration must never be able to do that, so
     the keys are right and the whole block is contained. */
  try {
    for (const [id, css] of [
      ['lg-solid', `background:${CSSV.geology}`],
      ['lg-band', `background:${withAlpha(CSSV.evolution, .25)};border:1px solid ${CSSV.evolution}`],
      ['lg-arc', `background:linear-gradient(90deg, transparent, ${CSSV.biology})`]]) {
      const el = document.getElementById(id);
      if (el) el.style.cssText = css + ';height:9px';
    }
  } catch (err) {
    console.error('legend swatches failed (non-fatal)', err);
  }
  changed();
  renderNow();                    // paint once without waiting for rAF
  requestAnimationFrame(frame);   // then run the animation loop if it is available
  startHeartbeat();               // ...and a worker clock for when it is not
  window.__BOOT_OK = true;
}

/* If boot ever throws again, the loop still starts.

   The flags are not debug scaffolding, they are the contract tools/smoke_test.py
   checks. A boot that dies silently is this project's signature failure — it cost
   the whole first build — and "the page looks fine in a screenshot" does not
   detect it. Something has to be able to ask, from outside, whether boot ran. */
function safeBoot() {
  window.__BOOT_OK = false;
  window.__BOOT_ERR = null;
  try { boot(); }
  catch (err) {
    window.__BOOT_ERR = String((err && err.stack) || err);
    console.error('boot failed; starting the render loop anyway', err);
    try { markAll(); renderNow(); } catch (_) {}
    requestAnimationFrame(frame);
    startHeartbeat();
  }
}

const ro = new ResizeObserver(() => {
  resizeGlobe(); resizeChron(); resizeKrail(); markAll();
});
ro.observe(document.getElementById('stage'));
ro.observe(document.querySelector('.chron'));
ro.observe(document.querySelector('.krail'));

if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => markAll());
safeBoot();
