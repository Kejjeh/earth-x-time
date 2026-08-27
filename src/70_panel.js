/* ============================================================================
   PANELS
   Nothing here is allowed to show a date without showing who said so.
   ========================================================================== */

const elDetail = document.getElementById('detail');
const elStatus = document.getElementById('sr-status');

/* One line, announced only when something worth saying has changed.

   #detail used to be the live region, and renderDetail rewrites it from the
   needPanel block that every setKt sets, so scrubbing the rail re-announced the
   whole 8.9 KB panel once per year. What a screen reader needs is the thing
   selected, where it resolves to, and whether anyone disagrees - a sentence.

   The key is separate from the line on purpose, and both halves of that matter.
   Keying on the selection alone goes silent through the one interaction the
   README leads with - hold a selection, scrub the rail, watch the date collapse.
   Keying on the sentence is too twitchy the other way: the connection count
   climbs as edges arrive, so sweeping the rail a year at a time announced 13
   times against the 8 occasions the date or the standing actually moved. The
   key is the referent, the resolved date, the status and whether it is disputed
   - exactly the set of things the second axis exists to move. */
let announced = null;
function announceSelection(key, line) {
  if (!elStatus || key === announced) return;
  announced = key;
  elStatus.textContent = line || '';
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const RESOLVER_NOTE = {
  consensus: 'The best-supported claim wins. Recency only breaks ties between claims that are equally accepted. Trustworthy, and usually behind the literature.',
  frontier: 'The most recent claim wins, whether or not anyone else believes it. This is the edge of current thinking, and the edge is often wrong.',
  spread: 'Nothing is resolved. Every surviving claim is drawn at once, and the width of the band is the size of the disagreement.'
};

function statusPill(st) {
  return `<span class="st st-${st}">${st}</span>`;
}

function claimBlock(l, isWinner, kt) {
  const c = l.claim;
  const col = CSSV[c.subjects.find(s => CSSV[s]) || 'geology'];
  const dateTxt = c.earth_time_end !== c.earth_time_start
    ? `${fmtYbp(c.earth_time_start)} – ${fmtYbp(c.earth_time_end)}`
    : fmtYbp(c.earth_time_start);
  const prec = fmtPrecision(c.time_precision);
  const hist = c.status_timeline.map(e => `
    <li><span>${e.knowledge_time}</span><span>${esc(e.status)} — ${esc(e.source)}</span></li>`).join('');
  return `
  <div class="claim" data-win="${isWinner}" style="--cl:${col}">
    <div class="row1">
      <span class="date num">${dateTxt}</span>
      ${prec ? `<span class="num" style="font-size:10.5px;color:var(--chalk-faint)">${prec}</span>` : ''}
      ${statusPill(l.status)}
      ${isWinner ? '<span class="winner-flag">resolved to this</span>' : ''}
    </div>
    <p class="stmt">${esc(c.statement)}</p>
    <p class="src">${esc(c.asserted_by)} · first asserted <span class="kt num">${c.knowledge_time}</span></p>
    <ul class="hist">${hist}</ul>
  </div>`;
}

function edgeLink(ed, dir) {
  const other = dir === 'out' ? ed.edge.target : ed.edge.source;
  const ref = R.referents[other];
  if (!ref) return '';
  const live = !ed.superseded;
  return `
  <button class="edge-link" data-goto="${other}" data-live="${live}">
    <span class="arrow">${dir === 'out' ? '→' : '←'}</span>
    <span>
      <span class="who">${esc(ref.label)}</span>
      <span class="mech">${esc(ed.edge.label)} · ${esc(ed.claim.asserted_by)} · ${ed.status} since ${ed.since}</span>
    </span>
  </button>`;
}

function renderDetail() {
  const F = facts();

  /* A real referent that resolve() cannot place at this knowledge-time. Reached
     by a shared link - #k=1700&s=homo_sapiens - and it used to fall through to
     "Nothing selected" while the selection was set and still in the URL. That is
     not an error state: it is the most interesting thing the page has to say,
     and resolve() has already worked out the year it changes. */
  if (S.selection && !F.items[S.selection] &&
      Object.prototype.hasOwnProperty.call(R.referents, S.selection)) {
    const ref = R.referents[S.selection];
    const first = firstDatedYear(S.selection);
    /* Keyed without the year: scrubbing 1650 to 1900 with this selected is one
       piece of news, not two hundred and fifty. The year the record changes is
       the durable half, so the line carries that rather than the current one. */
    announceSelection(`${ref.id}|unknown`,
      `${ref.label}: nothing datable is claimed about this yet.`
      + (isFinite(first) ? ` The first dated claim arrives in ${first}.` : ''));
    const pending = (R.byRef[S.selection] || [])
      .filter(c => c.knowledge_time > S.kt)
      .sort((a, b) => a.knowledge_time - b.knowledge_time);
    elDetail.innerHTML = `
      <div class="dt-head">
        <div class="dt-kind"><span class="tag">${esc(ref.kind)}</span></div>
        <h2>${esc(ref.label)}</h2>
      </div>
      <div class="resolved">
        <span class="lbl" style="display:block;margin-bottom:4px">Not yet known in ${S.kt}</span>
        <div class="big">no dated claim</div>
        <p class="prov">Nothing datable has been asserted about this in
        <b class="num">${S.kt}</b>. The page is not hiding it — in this year, nobody
        had put a number on it.</p>
        ${isFinite(first) ? `<p class="prov"><button class="edge-link" data-goto="${esc(ref.id)}"
          style="padding:2px 0"><span><span class="who">Go to ${first}</span>
          <span class="mech">the year the first dated claim arrives</span></span></button></p>` : ''}
      </div>
      ${pending.length ? `<div class="sect">
        <span class="lbl">What is still to come · ${pending.length}</span>
        ${pending.slice(0, 8).map(c => `<div class="claim pending" style="--cl:var(--rule)">
          <p class="stmt">${esc(c.statement)}</p>
          <p class="src">${esc(c.asserted_by)} — arrives in <span class="kt num">${c.knowledge_time}</span></p>
        </div>`).join('')}
      </div>` : ''}`;
    return;
  }

  if (!S.selection || !F.items[S.selection]) {
    announceSelection('', '');
    const disp = F.visible.filter(i => i.res.disputed)
      .sort((a, b) => (b.res.oldest - b.res.youngest) - (a.res.oldest - a.res.youngest))
      .slice(0, 5);
    elDetail.innerHTML = `
      <div class="empty">
        <strong>Nothing selected</strong>
        Click any marker on the globe or the timeline. Every claim carries its
        source, its date, and the year someone first made it.
        ${disp.length ? `<p style="margin-top:14px"><strong>Widest disagreements right now</strong></p><ul>${
          disp.map(i => `<li><button class="edge-link" data-goto="${i.id}" style="padding:2px 0">
            <span><span class="who">${esc(i.ref.label)}</span>
            <span class="mech">${fmtSpan(i.res.oldest - i.res.youngest)} of disagreement</span></span>
          </button></li>`).join('')}</ul>` : ''}
      </div>`;
    return;
  }

  const it = F.items[S.selection];
  const r = it.res;
  const ref = it.ref;
  const kt = S.kt;

  const outE = F.allEdges.filter(e => e.edge.source === ref.id);
  const inE = F.allEdges.filter(e => e.edge.target === ref.id);

  // Only the claims that actually compete for the date belong under that heading.
  const positional = r.pool.slice().sort((a, b) => {
    if (a === r.winner) return -1; if (b === r.winner) return 1;
    return b.accept - a.accept || b.claim.knowledge_time - a.claim.knowledge_time;
  });
  const meta = r.live.filter(l => l.claim._meta);
  const context = r.live.filter(l => !positional.includes(l) && !meta.includes(l));

  const pending = (R.byRef[ref.id] || []).filter(c => c.knowledge_time > kt);

  const dateLine = r.winner
    ? fmtYbp(r.winner.claim.earth_time_start)
    : `${fmtYbp(r.oldest)} – ${fmtYbp(r.youngest)}`;
  const prec = r.winner ? fmtPrecision(r.winner.claim.time_precision) : null;

  announceSelection(
    `${ref.id}|${Math.round(r.pos)}|${r.winner ? r.winner.status : 'none'}|${r.disputed}`,
    `${ref.label}, ${dateLine}`
    + (r.winner ? `, ${r.winner.status}, resolved to ${r.winner.claim.asserted_by}` : ', not resolved')
    + (r.disputed ? `, disputed across ${fmtSpan(r.oldest - r.youngest)}` : '')
    + `. ${r.pool.length} claim${r.pool.length === 1 ? '' : 's'} competing for the date`
    + `, ${outE.length + inE.length} connection${outE.length + inE.length === 1 ? '' : 's'}.`);

  elDetail.innerHTML = `
    <div class="dt-head">
      <div class="dt-kind">
        <span class="tag">${ref.kind}</span>
        ${r.subjects.map(s => `<span class="tag" style="color:${CSSV[s]};border-color:${withAlpha(CSSV[s], .4)}">${SUBJECT_LABEL[s] || s}</span>`).join('')}
      </div>
      <h2>${esc(ref.label)}</h2>
      ${r.winner ? `<p class="dt-stmt">${esc(r.winner.claim.statement)}</p>` : ''}
    </div>

    <div class="resolved">
      <span class="lbl" style="display:block;margin-bottom:4px">Resolved position</span>
      <div class="big">${dateLine} ${prec ? `<span class="pm">${prec}</span>` : ''}</div>
      ${r.winner ? `
        <p class="prov">Resolved by <b>${esc(S.resolver === 'frontier' ? 'newest claim' : 'best supported')}</b>
        to <b>${esc(r.winner.claim.asserted_by)}</b>, ${r.winner.status} since <b>${r.winner.since}</b>.
        ${r.dated.length > 1 ? `${r.dated.length - 1} competing claim${r.dated.length > 2 ? 's' : ''} below.` : ''}</p>`
        : `<p class="prov">Not resolved. Showing the full range of ${r.dated.length} surviving claims.</p>`}
      ${r.disputed ? `<p class="spread-note">Disputed — ${fmtSpan(r.oldest - r.youngest)} between the outermost claims.</p>` : ''}
      ${r.wouldDifferUnderFrontier && S.resolver !== 'spread' ? `
        <p class="prov">Switching to <b>newest</b> would move this to
        <b class="num">${fmtYbp(S.resolver === 'frontier' ? r.consensusPos : r.frontierPos)}</b>.</p>` : ''}
    </div>

    ${positional.length ? `<div class="sect">
      <span class="lbl">Claims competing for the date · ${positional.length}</span>
      ${positional.map(l => claimBlock(l, l === r.winner, kt)).join('')}
    </div>` : ''}

    ${context.length ? `<div class="sect">
      <span class="lbl">What else is claimed · ${context.length}</span>
      ${context.map(l => claimBlock(l, false, kt)).join('')}
    </div>` : ''}

    ${meta.length ? `<div class="sect">
      <span class="lbl">Claims about those claims</span>
      ${meta.map(l => claimBlock(l, false, kt)).join('')}
    </div>` : ''}

    ${pending.length ? `<div class="sect">
      <span class="lbl">Not yet known in ${kt} · ${pending.length}</span>
      ${pending.map(c => `<div class="claim pending" style="--cl:var(--rule)">
        <div class="row1"><span class="date num">${fmtYbp(c.earth_time_start)}</span></div>
        <p class="stmt">${esc(c.statement)}</p>
        <p class="src">${esc(c.asserted_by)} — arrives in <span class="kt num">${c.knowledge_time}</span></p>
      </div>`).join('')}
    </div>` : ''}

    ${(outE.length || inE.length) ? `<div class="sect">
      <span class="lbl">Connections</span>
      ${inE.map(e => edgeLink(e, 'in')).join('')}
      ${outE.map(e => edgeLink(e, 'out')).join('')}
    </div>` : ''}

    <div class="sect">
      <span class="lbl">Basis</span>
      <div class="meta-row"><span class="k">Position</span><span class="v">${
        r.geometry.mode === 'global' ? 'planet-wide, no single locus'
        : r.geometry.mode === 'none' ? 'no spatial extent'
        : `${r.geometry.lat.toFixed(2)}°, ${r.geometry.lng.toFixed(2)}°${
            r.geometry.mode === 'region' && r.geometry.radius_km ? ` · ~${Math.round(r.geometry.radius_km)} km across` : ''}`
      }</span></div>
      <div class="meta-row"><span class="k">Coordinates</span><span class="v ${r.coordsAreModern ? 'flagged' : ''}">${
        r.coordsAreModern
          ? 'present-day. Plate motion not reconstructed, so deep-time positions are where the rock is now, not where it was.'
          : 'reconstructed to the period'
      }</span></div>
      <div class="meta-row"><span class="k">Detail level</span><span class="v num">appears at zoom ${r.zoomMin.toFixed(0)}</span></div>
      <div class="meta-row"><span class="k">Claims</span><span class="v num">${r.live.length} live in ${kt}${pending.length ? ` · ${pending.length} still to come` : ''}</span></div>
    </div>`;
}

/* ------------------------------------------------------------------- diff */
function renderDiff() {
  const a = Math.min(S.ktA, S.kt), b = Math.max(S.ktA, S.kt);
  const FA = queryFacts({ ...S, kt: a }), FB = queryFacts({ ...S, kt: b });
  const groups = { arrived: [], moved: [], status: [], wired: [], retired: [] };

  for (const c of GRAPH.claims) {
    const sa = statusAt(c, a), sb = statusAt(c, b);
    if (!sa && sb) groups.arrived.push({ c, sb });
    else if (sa && sb && sa !== sb) groups.status.push({ c, sa, sb });
  }
  for (const id in R.referents) {
    const ra = resolve(id, a, S.resolver), rb = resolve(id, b, S.resolver);
    if (ra && rb && Math.round(ra.pos) !== Math.round(rb.pos))
      groups.moved.push({ id, ra, rb });
    else if (!ra && rb) { /* covered by arrived */ }
  }
  const liveSet = F => new Set(F.allEdges.filter(e => !e.superseded).map(e => e.edge.id));
  const la = liveSet(FA), lb = liveSet(FB);
  for (const e of FB.allEdges) if (!la.has(e.edge.id) && lb.has(e.edge.id)) groups.wired.push(e);
  for (const e of FA.allEdges) if (la.has(e.edge.id) && !lb.has(e.edge.id)) groups.retired.push(e);

  const sec = (title, colour, items) => items.length ? `
    <div class="diff-grp"><span class="lbl">${title} · ${items.length}</span>${items.join('')}</div>` : '';

  const body = [
    sec('Causal links that appeared', '', groups.wired.map(e => `
      <div class="diff-item" style="--dc:${CSSV.biology || CSSV['sub-biology'] || '#6FA85F'}">
        <div class="who">${esc(R.referents[e.edge.source].label)} → ${esc(R.referents[e.edge.target].label)}</div>
        <div class="what">${esc(e.edge.label)}</div>
        <div class="trans">${esc(e.claim.asserted_by)} · ${e.status} since ${e.since}</div>
      </div>`)),
    sec('Causal links retired', '', groups.retired.map(e => `
      <div class="diff-item" style="--dc:var(--chalk-faint)">
        <div class="who" style="text-decoration:line-through">${esc(R.referents[e.edge.source].label)} → ${esc(R.referents[e.edge.target].label)}</div>
        <div class="what">${esc(e.edge.label)}</div>
        <div class="trans">superseded — ${esc(e.claim.asserted_by)}</div>
      </div>`)),
    sec('Dates that moved', '', groups.moved.map(m => `
      <div class="diff-item" style="--dc:var(--ochre)">
        <div class="who">${esc(R.referents[m.id].label)}</div>
        <div class="trans">${fmtYbp(m.ra.pos)} → ${fmtYbp(m.rb.pos)}${
          m.rb.winner ? ` · now ${esc(m.rb.winner.claim.asserted_by)}` : ''}</div>
      </div>`)),
    sec('Claims that arrived', '', groups.arrived.map(x => `
      <div class="diff-item" style="--dc:var(--cyanotype)">
        <div class="who">${esc(R.referents[x.c.about] ? R.referents[x.c.about].label : 'On another claim')}</div>
        <div class="what">${esc(x.c.statement)}</div>
        <div class="trans">${esc(x.c.asserted_by)} · ${x.c.knowledge_time} · now ${x.sb}</div>
      </div>`)),
    sec('Standing changed', '', groups.status.map(x => `
      <div class="diff-item" style="--dc:${x.sb === 'superseded' ? 'var(--chalk-faint)' : 'var(--sub-chemistry)'}">
        <div class="who">${esc(R.referents[x.c.about] ? R.referents[x.c.about].label : 'A claim about a claim')}</div>
        <div class="what">${esc(x.c.statement)}</div>
        <div class="trans">${x.sa} → ${x.sb} · ${esc(x.c.asserted_by)}</div>
      </div>`))
  ].join('');

  document.getElementById('diff-body').innerHTML = body ||
    `<p class="diff-empty">Nothing changed between ${a} and ${b}.</p>`;
  document.getElementById('diff-title').textContent = `What changed between ${a} and ${b}`;
}

/* --------------------------------------------------------- subject filter */
function renderSubjects() {
  const F = facts();
  const host = document.getElementById('subjects');
  host.innerHTML = SUBJECTS.map(s => `
    <button class="sub" data-sub="${s}"
            data-on="${S.subjects.has(s)}" data-focus="${S.focus === s}"
            aria-pressed="${S.subjects.has(s)}">
      <span class="swatch" style="--sw:${CSSV[s]}"></span>
      <span>${SUBJECT_LABEL[s]}</span>
      <span class="cnt">${F.subjectCounts[s] || 0}</span>
    </button>`).join('');
  document.getElementById('subhint').textContent = S.focus
    ? `Isolating ${SUBJECT_LABEL[S.focus].toLowerCase()}. Neighbours reached by a causal link stay visible, dimmed.`
    : '';
}
