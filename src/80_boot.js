/* ============================================================================
   WIRING
   Every control below does exactly one thing: mutate axis state and invalidate.
   Nothing filters anything itself — that is queryFacts's job.
   ========================================================================== */

let needGlobe = true, needChron = true, needKrail = true, needPanel = true;
function markAll() { needGlobe = needChron = needKrail = needPanel = true; }
function changed() { invalidate(); markAll(); paintOnInput(); }

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
function setSelection(id) { S.selection = id; changed(); }

/* ------------------------------------------------------------------- globe */
let gDrag = null, gMoved = 0;
const gVel = [];

gcv.addEventListener('pointerdown', e => {
  gcv.setPointerCapture(e.pointerId);
  gDrag = { x: e.clientX, y: e.clientY, t: performance.now() };
  gMoved = 0; gVel.length = 0;
  S.spin.lam = S.spin.phi = 0;
  gcv.classList.add('dragging');
});

gcv.addEventListener('pointermove', e => {
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
  if (!gDrag) return;
  gDrag = null;
  gcv.classList.remove('dragging');
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
    setSelection(best ? best.id : null);
  }
}
gcv.addEventListener('pointerup', endGlobeDrag);
gcv.addEventListener('pointercancel', () => { gDrag = null; gcv.classList.remove('dragging'); });

gcv.addEventListener('wheel', e => {
  e.preventDefault();
  ZOOMF = Math.max(0.45, Math.min(3.2, ZOOMF * (e.deltaY > 0 ? 0.92 : 1.087)));
  resizeGlobe(); needGlobe = true; paintOnInput();
}, { passive: false });

gcv.addEventListener('keydown', e => {
  const step = e.shiftKey ? 15 : 5;
  if (e.key === 'ArrowLeft') { S.rot.lam -= step; needGlobe = true; }
  else if (e.key === 'ArrowRight') { S.rot.lam += step; needGlobe = true; }
  else if (e.key === 'ArrowUp') { S.rot.phi = Math.min(89, S.rot.phi + step); needGlobe = true; }
  else if (e.key === 'ArrowDown') { S.rot.phi = Math.max(-89, S.rot.phi - step); needGlobe = true; }
  else if (e.key === '+' || e.key === '=') { ZOOMF = Math.min(3.2, ZOOMF * 1.12); resizeGlobe(); needGlobe = true; }
  else if (e.key === '-') { ZOOMF = Math.max(0.45, ZOOMF * 0.89); resizeGlobe(); needGlobe = true; }
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
  ccv.setPointerCapture(e.pointerId);
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
  if (cDrag && cDrag.mode === 'click') setSelection(cDrag.id === S.selection ? null : cDrag.id);
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
kcv.addEventListener('pointerdown', e => { kcv.setPointerCapture(e.pointerId); kDrag = true; stopReplay(); kSet(e); });
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

elDetail.addEventListener('click', e => {
  const b = e.target.closest('[data-goto]'); if (!b) return;
  setSelection(b.dataset.goto);
  elDetail.scrollTop = 0;
});

document.getElementById('btn-basemap').addEventListener('click', e => {
  S.basemap = S.basemap === 'satellite' ? 'chart' : 'satellite';
  const sat = S.basemap === 'satellite';
  e.currentTarget.setAttribute('aria-pressed', String(sat));
  e.currentTarget.textContent = sat ? 'Satellite' : 'Chart';
  document.getElementById('stage').classList.toggle('space', sat);
  needGlobe = true;
});

document.getElementById('btn-plates').addEventListener('click', e => {
  S.showPlates = !S.showPlates;
  e.currentTarget.setAttribute('aria-pressed', String(S.showPlates));
  needGlobe = true;
});
document.getElementById('btn-now').addEventListener('click', () => { stopReplay(); setKt(2025); });
document.getElementById('btn-play').addEventListener('click', () => S.playing ? stopReplay() : startReplay());

document.getElementById('btn-theme').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const dark = cur ? cur === 'dark' : !matchMedia('(prefers-color-scheme: light)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
  readPalette(); markAll();
});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { readPalette(); markAll(); });

const diffwrap = document.getElementById('diffwrap');
document.getElementById('btn-diff').addEventListener('click', e => {
  const on = diffwrap.hidden;
  diffwrap.hidden = !on;
  e.currentTarget.setAttribute('aria-pressed', String(on));
  if (on) { document.getElementById('diff-b').value = S.kt; renderDiff(); }
});
document.getElementById('diff-close').addEventListener('click', () => {
  diffwrap.hidden = true;
  document.getElementById('btn-diff').setAttribute('aria-pressed', 'false');
});
document.getElementById('diff-a').addEventListener('input', e => { S.ktA = +e.target.value || 1975; renderDiff(); });
document.getElementById('diff-b').addEventListener('input', e => { setKt(+e.target.value || 2025); renderDiff(); });
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !diffwrap.hidden) {
    diffwrap.hidden = true;
    document.getElementById('btn-diff').setAttribute('aria-pressed', 'false');
  }
});

/* -------------------------------------------------------------- guided path */
const TOUR = [
  { id: 'chicxulub_impact', kt: 1995, win: [0, 3.0e8],
    text: 'A ten-kilometre asteroid hits the Yucatán platform. One point on the map, and the reach of it is carried by the arcs, not by the size of the dot.' },
  { id: 'kpg_extinction', kt: 1995, win: [0, 2.0e8],
    text: 'Three-quarters of species end here. Drag the right-hand rail back to 1975 and the link you are looking at does not exist yet.' },
  { id: 'mammal_radiation', kt: 2025, win: [0, 1.0e8],
    text: 'With the large-bodied niches empty, mammals radiate. The chain has just crossed from geology into biology.' },
  { id: 'first_primates', kt: 2025, win: [0, 8.0e7],
    text: 'Primates appear in the aftermath. Isolate evolution in the left-hand panel and this link still shows, because the graph is one graph.' },
  { id: 'hominins', kt: 2025, win: [0, 1.2e7],
    text: 'The hominin line separates from the chimpanzee line. Molecular clocks and fossils disagree about when, so this draws as a band.' },
  { id: 'homo_sapiens', kt: 2025, win: [0, 1.0e6],
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
let rafPending = false;

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
  rafPending = false;
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  try { render(dt); } catch (err) { console.error('render failed', err); }
  rafPending = true;
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
function rafIsLive() { return performance.now() - lastPaint < 250 && rafPending; }

function paintOnInput() {
  if (painting || rafIsLive()) return;
  if (performance.now() - lastPaint < 11) return;
  painting = true;
  try { renderNow(); } finally { painting = false; }
}

/* If rAF has not painted recently and something is dirty, paint anyway. This is
   what makes the page work at all where rAF is paused; animation stops, but the
   globe, the ribbon and the panels are all there and still respond. */
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
  document.getElementById('stage').classList.toggle('space', S.basemap === 'satellite');
  resizeGlobe(); resizeChron(); resizeKrail();
  document.getElementById('resnote').textContent = RESOLVER_NOTE.consensus;
  for (const [id, css] of [['lg-solid', `background:${CSSV['sub-geology']}`],
                           ['lg-band', `background:${withAlpha(CSSV['sub-evolution'], .25)};border:1px solid ${CSSV['sub-evolution']}`],
                           ['lg-arc', `background:linear-gradient(90deg, transparent, ${CSSV['sub-biology']})`]]) {
    document.getElementById(id).style.cssText = css + ';height:9px';
  }
  changed();
  renderNow();                    // paint once without waiting for rAF
  requestAnimationFrame(frame);   // then run the animation loop if it is available
}

const ro = new ResizeObserver(() => {
  resizeGlobe(); resizeChron(); resizeKrail(); markAll();
});
ro.observe(document.getElementById('stage'));
ro.observe(document.querySelector('.chron'));
ro.observe(document.querySelector('.krail'));

if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => markAll());
boot();
