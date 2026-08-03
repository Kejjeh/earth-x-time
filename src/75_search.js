/* ============================================================================
   SEARCH

   Forty-six referents is small enough that any indexing beyond a linear scan
   would be theatre. What is worth doing is searching the CLAIMS, not just the
   labels: "iridium", "Alvarez", "zircon" and "clumped isotopes" are how anyone
   who knows this material would look for it, and none of them appear in a
   referent's name.

   The result rows carry the date as resolved AT THE CURRENT KNOWLEDGE-TIME,
   which means a search can honestly answer "we did not know that yet". Choosing
   such a result moves knowledge-time forward to the year the claim was first
   made rather than selecting something the page would then refuse to draw.
   ========================================================================== */

const SEARCH_IDX = (() => {
  const out = [];
  for (const id in R.referents) {
    const claims = R.byRef[id] || [];
    out.push({
      id,
      label: R.referents[id].label,
      low: R.referents[id].label.toLowerCase(),
      body: claims.map(c => `${c.statement} ${c.asserted_by}`).join(' ').toLowerCase(),
      // The year resolve() can first place it, not the year anyone first said
      // anything about it - those differ, and the label has to match what
      // choosing the row will actually do.
      first: claims.filter(c => !c._meta && isFinite(c.earth_time_start))
        .reduce((m, c) => Math.min(m, c.knowledge_time), Infinity)
    });
  }
  return out;
})();

function searchFacts(qs) {
  const s = qs.trim().toLowerCase();
  if (s.length < 2) return [];
  const hits = [];
  for (const e of SEARCH_IDX) {
    const i = e.low.indexOf(s);
    let score = 0, where = 'label';
    if (i === 0) score = 100;
    else if (i > 0) score = /[\s(-]/.test(e.low[i - 1]) ? 82 : 62;
    else if (e.body.indexOf(s) >= 0) { score = 30; where = 'claim'; }
    else continue;
    hits.push({ ...e, score, where });
  }
  hits.sort((a, b) => b.score - a.score || a.label.length - b.label.length);
  return hits.slice(0, 8);
}

const elSearch = document.getElementById('search');
const elResults = document.getElementById('results');
const elSearchNote = document.getElementById('search-note');
let SR = { hits: [], cursor: -1, q: '' };

function hilite(label, s) {
  const i = label.toLowerCase().indexOf(s.toLowerCase());
  if (i < 0) return esc(label);
  return esc(label.slice(0, i)) + '<mark>' + esc(label.slice(i, i + s.length)) +
    '</mark>' + esc(label.slice(i + s.length));
}

function renderResults() {
  const s = elSearch.value.trim();
  elResults.innerHTML = SR.hits.map((h, i) => {
    const res = resolve(h.id, S.kt, S.resolver);
    const when = res
      ? `<span class="when">${fmtYbp(res.winner ? res.winner.claim.earth_time_start : res.pos)}</span>`
      : `<span class="when later">first claimed ${h.first}</span>`;
    return `<li role="option" id="sr-${i}" data-id="${esc(h.id)}"` +
      ` aria-selected="${i === SR.cursor}">${hilite(h.label, s)}${when}</li>`;
  }).join('');
  elSearch.setAttribute('aria-expanded', String(SR.hits.length > 0));
  elSearch.setAttribute('aria-activedescendant', SR.cursor >= 0 ? `sr-${SR.cursor}` : '');
  const byClaim = SR.hits.filter(h => h.where === 'claim').length;
  elSearchNote.textContent = !s || s.length < 2 ? ''
    : !SR.hits.length ? 'nothing matches'
    : byClaim ? `${byClaim} matched inside a claim, not a title` : '';
}

function closeResults() {
  // Cancel the pending debounce too. Without this, dismissing the dropdown and
  // then doing nothing for 90 ms reopens it: the timer from the last keystroke
  // is still queued and repopulates SR behind the user's back.
  clearTimeout(searchTimer); searchTimer = null;
  SR = { hits: [], cursor: -1, q: elSearch.value.trim() };
  elResults.innerHTML = '';
  elSearch.setAttribute('aria-expanded', 'false');
  elSearchNote.textContent = '';
}

/* Getting there is not enough: a result can be invisible because knowledge-time
   is earlier than the claim, because its field of study is switched off, or
   because another field is isolated. Choosing it opens whatever is in the way. */
function chooseResult(id) {
  if (!Object.prototype.hasOwnProperty.call(R.referents, id)) return;
  const claims = R.byRef[id] || [];
  let kt = S.kt;
  /* Only claims that resolve() will actually count. Taking the minimum over ALL
     claims picks up undated and _meta ones, so a referent whose earliest DATED
     claim is 1953 but which carries a 1785 interpretation reported "first
     claimed 1785" and then selected into an empty panel, because resolve()
     returns null when nothing dated is live. Mirror its predicate exactly. */
  const dated = claims.filter(c => !c._meta && isFinite(c.earth_time_start));
  const first = dated.reduce((m, c) => Math.min(m, c.knowledge_time), Infinity);
  if (isFinite(first) && first > kt) kt = Math.min(KT_MAX, first);

  const res = resolve(id, kt, S.resolver);
  if (res) {
    if (S.focus && !res.subjects.includes(S.focus)) S.focus = null;
    if (!res.subjects.some(s => S.subjects.has(s))) for (const s of res.subjects) S.subjects.add(s);
  }
  const t1 = res && isFinite(res.oldest)
    ? Math.max(2000, Math.min(T_MAX, res.oldest * 1.7))
    : S.win.t1;
  flyTo({ id, kt, win: [0, t1] });
  closeResults();
  elSearch.blur();
}

let searchTimer = null;
function runSearch() {
  SR = { hits: searchFacts(elSearch.value), cursor: -1, q: elSearch.value.trim() };
  renderResults();
}
elSearch.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, 90);
});

/* Typing "pomp" and hitting Enter within 90 ms of the last keystroke used to
   select the top hit for "pom", because the debounced recompute had not run yet.
   Stamp the query the hits belong to, and flush synchronously if Enter arrives
   before the timer does. */
function flushSearch() {
  clearTimeout(searchTimer); searchTimer = null;
  runSearch();
}


elSearch.addEventListener('keydown', e => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const n = SR.hits.length;
    if (!n) return;
    SR.cursor = e.key === 'ArrowDown'
      ? (SR.cursor >= n - 1 ? 0 : SR.cursor + 1)
      : (SR.cursor <= 0 ? n - 1 : SR.cursor - 1);
    renderResults();
    const el = document.getElementById('sr-' + SR.cursor);
    if (el) el.scrollIntoView({ block: 'nearest' });
    e.preventDefault();
  } else if (e.key === 'Enter') {
    if (SR.q !== elSearch.value.trim()) { flushSearch(); SR.cursor = -1; }
    const h = SR.hits[SR.cursor >= 0 ? SR.cursor : 0];
    if (h) chooseResult(h.id);
    e.preventDefault();
  } else if (e.key === 'Escape') {
    if (SR.hits.length) closeResults(); else { elSearch.value = ''; elSearch.blur(); }
    e.stopPropagation();
  }
});

elResults.addEventListener('click', e => {
  const li = e.target.closest('li[data-id]');
  if (li) chooseResult(li.dataset.id);
});

/* "/" focuses search from anywhere, the way it does in every other tool that
   has a search box. Not when the user is already typing into one. */
document.addEventListener('keydown', e => {
  if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
  elSearch.focus();
  elSearch.select();
  e.preventDefault();
});

document.addEventListener('click', e => {
  if (!e.target.closest('#search, #results')) closeResults();
});
