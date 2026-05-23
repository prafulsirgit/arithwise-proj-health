/* discover.js – Semantic Oncology Discovery Hub */
'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let discoverResults = null;
let activeDiscoverTab = 'all';
const _placeholders = [
  'Search BRCA1 mutations…', 'Search lung adenocarcinoma…', 'Search immunotherapy…',
  'Search EGFR inhibitors…', 'Search colorectal cancer biomarkers…',
  'Search PD-L1 expression…', 'Search HER2-positive breast cancer…',
  'Search leukemia treatment…', 'Search KRAS mutations…',
  'Search CAR-T cell therapy…',
];
let _phIdx = 0, _phTimer = null;

// ── Init ───────────────────────────────────────────────────────────────────
async function initDiscover() {
  _startPlaceholderCycle();
  _setupDiscoverSearch();
  await Promise.all([loadTrendingTopics(), loadFeaturedPublications()]);
}
window.initDiscover = initDiscover;

// ── Placeholder cycling ────────────────────────────────────────────────────
function _startPlaceholderCycle() {
  const inp = document.getElementById('discover-search-input');
  if (!inp) return;
  function setNext() {
    inp.placeholder = _placeholders[_phIdx % _placeholders.length];
    _phIdx++;
  }
  setNext();
  _phTimer = setInterval(setNext, 2800);
}

// ── Search setup ───────────────────────────────────────────────────────────
function _setupDiscoverSearch() {
  const inp = document.getElementById('discover-search-input');
  const btn = document.getElementById('discover-search-btn');
  if (!inp || !btn) return;

  btn.addEventListener('click', () => {
    const q = inp.value.trim();
    if (q) runDiscoverSearch(q);
  });
  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const q = inp.value.trim();
      if (q) runDiscoverSearch(q);
    }
  });

  // Live suggestions
  let suggestTimer = null;
  inp.addEventListener('input', () => {
    clearTimeout(suggestTimer);
    const q = inp.value.trim();
    if (q.length < 2) { hideSuggestions(); return; }
    suggestTimer = setTimeout(() => fetchSuggestions(q), 280);
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('.discover-search-wrap')) hideSuggestions();
  });
}

// ── Autocomplete suggestions ───────────────────────────────────────────────
async function fetchSuggestions(q) {
  try {
    const d = await apiFetch(`/api/search/suggest?q=${encodeURIComponent(q)}&limit=5`);
    renderSuggestions(d, q);
  } catch (_) {}
}

function renderSuggestions(d, q) {
  const box = document.getElementById('discover-suggestions');
  if (!box) return;
  const items = [
    ...d.articles.map(a => ({ label: a.title, sub: `PMID ${a.pmid} · ${a.pub_year || ''}`, type: 'article', action: () => { document.getElementById('discover-search-input').value = a.title; hideSuggestions(); runDiscoverSearch(a.title); } })),
    ...d.concepts.map(c => ({ label: c.label, sub: c.category, type: c.category, action: () => { document.getElementById('discover-search-input').value = c.label; hideSuggestions(); runDiscoverSearch(c.label); } })),
  ];
  if (!items.length) { hideSuggestions(); return; }
  const catIcon = { article: '◉', disease: '✚', drug: '⬘', biomarker: '⬙', general: '⬡' };
  box.innerHTML = items.map((it, i) => `
    <div class="suggest-item" id="suggest-${i}" tabindex="0">
      <span class="suggest-icon ${it.type}">${catIcon[it.type] || '◈'}</span>
      <div class="suggest-text">
        <div class="suggest-label">${escHtml(it.label)}</div>
        <div class="suggest-sub">${escHtml(it.sub)}</div>
      </div>
    </div>`).join('');
  box.style.display = 'block';
  items.forEach((it, i) => {
    document.getElementById(`suggest-${i}`).addEventListener('click', it.action);
  });
}

function hideSuggestions() {
  const box = document.getElementById('discover-suggestions');
  if (box) box.style.display = 'none';
}

// ── Unified Search ─────────────────────────────────────────────────────────
async function runDiscoverSearch(q) {
  if (!q) return;
  hideSuggestions();
  document.getElementById('discover-search-input').value = q;

  const resultsSection = document.getElementById('discover-results-section');
  const tabBar = document.getElementById('discover-tabs');
  resultsSection.style.display = 'block';
  tabBar.style.display = 'flex';

  // Show skeleton
  _renderDiscoverSkeleton();

  try {
    const d = await apiFetch(`/api/search/unified?q=${encodeURIComponent(q)}&limit=12`);
    discoverResults = d;
    _renderDiscoverTabCounts(d);
    _renderDiscoverResults(activeDiscoverTab);
  } catch (e) {
    document.getElementById('discover-results-body').innerHTML =
      `<div class="discover-error">Search failed: ${escHtml(e.message)}</div>`;
  }
}
window.runDiscoverSearch = runDiscoverSearch;

function _renderDiscoverSkeleton() {
  document.getElementById('discover-results-body').innerHTML = `
    <div class="discover-skeleton-grid">
      ${Array(6).fill(0).map(() => `
        <div class="pub-card">
          <div class="skel-line medium skeleton"></div>
          <div class="skel-line short skeleton" style="margin-top:8px"></div>
        </div>`).join('')}
    </div>`;
}

function _renderDiscoverTabCounts(d) {
  const tabs = {
    all: d.total_results,
    publications: d.publications.length,
    diseases: d.diseases.length,
    drugs: d.drugs.length,
    biomarkers: d.biomarkers.length,
    concepts: d.concepts.length,
  };
  Object.entries(tabs).forEach(([tab, cnt]) => {
    const badge = document.getElementById(`dtab-${tab}-count`);
    if (badge) badge.textContent = cnt;
  });
}

function switchDiscoverTab(tab) {
  activeDiscoverTab = tab;
  document.querySelectorAll('.discover-tab').forEach(el => el.classList.remove('active'));
  const el = document.getElementById(`dtab-${tab}`);
  if (el) el.classList.add('active');
  if (discoverResults) _renderDiscoverResults(tab);
}
window.switchDiscoverTab = switchDiscoverTab;

function _renderDiscoverResults(tab) {
  const body = document.getElementById('discover-results-body');
  if (!discoverResults) return;
  const d = discoverResults;

  let html = '';

  if (tab === 'all' || tab === 'publications') {
    if (d.publications.length) {
      html += `<div class="discover-section-title">📄 Publications <span class="discover-section-count">${d.publications.length}</span></div>`;
      html += `<div class="discover-grid">` + d.publications.map(a => `
        <div class="discover-pub-card" onclick="openPubFromDiscover('${a.pmid}')">
          <div class="discover-card-title">${escHtml(a.title)}</div>
          <div class="discover-card-meta">
            <span class="badge">${a.pmid}</span>
            ${a.pub_year ? `<span class="badge purple">${a.pub_year}</span>` : ''}
            ${a.journal ? `<span class="badge green" style="max-width:140px;overflow:hidden;text-overflow:ellipsis" title="${escHtml(a.journal)}">${escHtml(a.journal.slice(0,24))}${a.journal.length > 24 ? '…' : ''}</span>` : ''}
          </div>
          ${a.abstract_snippet ? `<div class="discover-card-snippet">${escHtml(a.abstract_snippet)}…</div>` : ''}
        </div>`).join('') + `</div>`;
    }
  }

  const conceptSections = [
    { key: 'diseases', label: 'Diseases', icon: '✚', cat: 'disease' },
    { key: 'drugs', label: 'Drugs / Therapies', icon: '⬘', cat: 'drug' },
    { key: 'biomarkers', label: 'Biomarkers & Genes', icon: '⬙', cat: 'biomarker' },
    { key: 'concepts', label: 'Ontology Concepts', icon: '⬡', cat: 'general' },
  ];

  const catBadge = { disease: 'pink', drug: 'green', biomarker: 'orange', general: 'purple' };

  for (const sec of conceptSections) {
    if ((tab === 'all' || tab === sec.key) && d[sec.key] && d[sec.key].length) {
      html += `<div class="discover-section-title">${sec.icon} ${sec.label} <span class="discover-section-count">${d[sec.key].length}</span></div>`;
      html += `<div class="discover-concept-grid">` + d[sec.key].map(c => `
        <div class="discover-concept-card" onclick="loadConceptInBrowser(${c.id})">
          <div class="discover-concept-label">${escHtml(c.label)}</div>
          <div class="discover-concept-meta">
            <span class="badge ${catBadge[c.category] || ''}">${c.category}</span>
            ${c.ontology ? `<span class="badge">${c.ontology}</span>` : ''}
            ${c.article_count ? `<span class="badge">${c.article_count} articles</span>` : ''}
          </div>
          ${c.definition ? `<div class="discover-concept-def">${escHtml(c.definition.slice(0, 90))}…</div>` : ''}
        </div>`).join('') + `</div>`;
    }
  }

  if (!html) {
    html = `<div class="discover-empty">
      <div class="placeholder-icon">🔍</div>
      <p>No results found for "<strong>${escHtml(discoverResults.query)}</strong>"</p>
      <p style="font-size:13px;color:var(--text-muted);margin-top:8px">Try a different term, e.g., "BRCA1", "lung cancer", "immunotherapy"</p>
    </div>`;
  }

  body.innerHTML = html;
}

window.openPubFromDiscover = function (pmid) {
  navigateTo('publications');
  setTimeout(() => {
    document.getElementById('pub-search-pmid').value = pmid;
    runPubSearch && runPubSearch();
    setTimeout(() => {
      const card = document.querySelector(`[data-pmid="${pmid}"]`);
      if (card) card.click();
    }, 800);
  }, 150);
};

// ── Trending Topics ─────────────────────────────────────────────────────────
async function loadTrendingTopics() {
  const container = document.getElementById('trending-chips');
  if (!container) return;
  container.innerHTML = `<span class="trending-loading">Loading trends…</span>`;
  try {
    const d = await apiFetch('/api/search/trending?limit=18');
    if (!d.topics || !d.topics.length) {
      container.innerHTML = `<span style="color:var(--text-muted);font-size:13px">Ingest publications to see trending topics</span>`;
      return;
    }
    const catColor = { disease: 'pink', drug: 'green', biomarker: 'orange', mesh: 'purple', general: 'purple' };
    container.innerHTML = d.topics.map(t => `
      <button class="trending-chip ${catColor[t.category] || ''}"
              onclick="runDiscoverSearch('${escHtml(t.term)}')"
              title="${t.count} occurrences">
        ${escHtml(t.term)}
        <span class="trending-chip-count">${t.count}</span>
      </button>`).join('');
  } catch (e) {
    container.innerHTML = `<span style="color:var(--text-muted);font-size:13px">Could not load trending topics</span>`;
  }
}
window.loadTrendingTopics = loadTrendingTopics;

// ── Featured Publications ──────────────────────────────────────────────────
async function loadFeaturedPublications() {
  const container = document.getElementById('featured-pubs-list');
  if (!container) return;
  try {
    const d = await apiFetch('/api/search/featured?limit=5');
    if (!d.publications || !d.publications.length) {
      container.innerHTML = `<div style="color:var(--text-muted);font-size:13px;padding:12px">Ingest data to see featured publications</div>`;
      return;
    }
    container.innerHTML = d.publications.map((p, i) => `
      <div class="featured-pub-item" onclick="openPubFromDiscover('${p.pmid}')">
        <div class="featured-pub-rank">#${i + 1}</div>
        <div class="featured-pub-content">
          <div class="featured-pub-title">${escHtml(p.title)}</div>
          <div class="featured-pub-meta">
            ${p.pub_year ? `<span class="badge purple">${p.pub_year}</span>` : ''}
            <span class="badge">${p.mapping_count} concept links</span>
          </div>
        </div>
      </div>`).join('');
  } catch (e) {
    container.innerHTML = '';
  }
}
window.loadFeaturedPublications = loadFeaturedPublications;
