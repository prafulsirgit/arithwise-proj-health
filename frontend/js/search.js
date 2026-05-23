/* search.js – Publications search, list, and detail panel */
let pubOffset = 0, pubTotal = 0, pubLimit = 20, pubParams = {};

function initSearch() {
  document.getElementById('pub-search-btn').addEventListener('click', () => { pubOffset = 0; runPubSearch(); });
  document.getElementById('pub-clear-btn').addEventListener('click', clearPubSearch);
  ['pub-search-q', 'pub-search-author', 'pub-search-year', 'pub-search-pmid'].forEach(id => {
    document.getElementById(id).addEventListener('keydown', e => { if (e.key === 'Enter') { pubOffset = 0; runPubSearch(); } });
  });
  runPubSearch();
}
window.initSearch = initSearch;

async function runPubSearch() {
  pubParams = {
    q: document.getElementById('pub-search-q').value.trim(),
    author: document.getElementById('pub-search-author').value.trim(),
    year: document.getElementById('pub-search-year').value.trim(),
    pmid: document.getElementById('pub-search-pmid').value.trim(),
    limit: pubLimit, offset: pubOffset
  };
  const qs = Object.entries(pubParams).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
  renderPubSkeleton();
  try {
    const d = await apiFetch('/api/publications?' + qs);
    pubTotal = d.total;
    renderPubList(d.results);
    renderPubMeta(d.total, d.offset, d.limit);
    renderPubPagination(d.total, d.offset, d.limit);
  } catch (e) { showToast('Search failed: ' + e.message, 'error'); }
}

function clearPubSearch() {
  ['pub-search-q', 'pub-search-author', 'pub-search-year', 'pub-search-pmid'].forEach(id => document.getElementById(id).value = '');
  pubOffset = 0; runPubSearch();
}

function renderPubSkeleton() {
  document.getElementById('pub-list').innerHTML = Array(5).fill(0).map(() => `
    <div class="pub-card"><div class="skel-line medium skeleton"></div><div class="skel-line short skeleton"></div></div>`).join('');
}

function renderPubList(articles) {
  const el = document.getElementById('pub-list');
  if (!articles.length) { el.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center">No articles found</div>'; return; }
  el.innerHTML = articles.map(a => `
    <div class="pub-card" data-pmid="${a.pmid}" onclick="loadPubDetail('${a.pmid}', this)">
      <div class="pub-card-title">${escHtml(a.title)}</div>
      <div class="pub-card-meta">
        <span class="badge">${a.pmid}</span>
        ${a.pub_year ? `<span class="badge purple">${a.pub_year}</span>` : ''}
        ${a.pub_type ? `<span class="badge green">${escHtml(a.pub_type.split(';')[0])}</span>` : ''}
      </div>
      ${a.abstract_snippet ? `<div class="pub-card-snippet">${escHtml(a.abstract_snippet)}…</div>` : ''}
    </div>`).join('');
}

function renderPubMeta(total, offset, limit) {
  document.getElementById('pub-list-meta').textContent = `${total.toLocaleString()} result${total !== 1 ? 's' : ''}  ·  showing ${offset + 1}–${Math.min(offset + limit, total)}`;
}

function renderPubPagination(total, offset, limit) {
  const pages = Math.ceil(total / limit);
  const cur = Math.floor(offset / limit);
  const el = document.getElementById('pub-pagination');
  if (pages <= 1) { el.innerHTML = ''; return; }
  let html = `<button class="page-btn" onclick="pubPage(${cur - 1})" ${cur === 0 ? 'disabled' : ''}>‹</button>`;
  for (let i = Math.max(0, cur - 2); i <= Math.min(pages - 1, cur + 2); i++) {
    html += `<button class="page-btn ${i === cur ? 'active' : ''}" onclick="pubPage(${i})">${i + 1}</button>`;
  }
  html += `<button class="page-btn" onclick="pubPage(${cur + 1})" ${cur >= pages - 1 ? 'disabled' : ''}>›</button>`;
  el.innerHTML = html;
}

window.pubPage = function (page) {
  pubOffset = page * pubLimit;
  runPubSearch();
  document.getElementById('pub-list-pane').scrollTop = 0;
};

async function loadPubDetail(pmid, card) {
  document.querySelectorAll('.pub-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  const pane = document.getElementById('pub-detail-pane');
  pane.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text-muted)">Loading…</div>`;
  try {
    const a = await apiFetch(`/api/publications/${pmid}`);
    const catColor = { disease: 'pink', drug: 'green', biomarker: 'orange', general: 'purple' };
    pane.innerHTML = `
      <div class="detail-title">${escHtml(a.title)}</div>
      <div class="detail-meta-row">
        <span class="badge">${a.pmid}</span>
        ${a.pub_year ? `<span class="badge purple">${a.pub_year}</span>` : ''}
        ${a.journal ? `<span class="badge green">${escHtml(a.journal)}</span>` : ''}
        ${a.doi ? `<a class="badge orange" href="https://doi.org/${a.doi}" target="_blank">DOI ↗</a>` : ''}
        <a class="badge" href="${a.pubmed_url}" target="_blank">PubMed ↗</a>
      </div>
      ${a.abstract ? `<div class="detail-section"><h4>Abstract</h4><div class="detail-abstract">${escHtml(a.abstract)}</div></div>` : ''}
      ${a.authors?.length ? `<div class="detail-section"><h4>Authors (${a.authors.length})</h4><div class="author-list">${a.authors.map(au => `<span class="author-tag" title="${escHtml(au.affiliation || '')}">${escHtml(au.name)}</span>`).join('')}</div></div>` : ''}
      ${a.mesh_terms?.length ? `<div class="detail-section"><h4>MeSH Terms</h4><div class="tag-cloud">${a.mesh_terms.map(m => `<span class="tag" onclick="searchByMesh('${escHtml(m)}')">${escHtml(m)}</span>`).join('')}</div></div>` : ''}
      ${a.keywords?.length ? `<div class="detail-section"><h4>Keywords</h4><div class="tag-cloud">${a.keywords.map(k => `<span class="tag">${escHtml(k)}</span>`).join('')}</div></div>` : ''}
      ${a.concepts?.length ? `<div class="detail-section"><h4>Mapped Concepts (${a.concepts.length})</h4><div class="tag-cloud">${a.concepts.map(c => `<span class="concept-chip ${catColor[c.category] || ''}" onclick="loadConceptInBrowser(${c.id})"><span class="concept-chip-label">${escHtml(c.label)}</span><span class="concept-chip-cat">${c.category}</span></span>`).join('')}</div></div>` : '<div class="detail-section"><h4>Mapped Concepts</h4><span style="color:var(--text-muted);font-size:12px">None yet – run concept mapping in Data Management</span></div>'}
      <div class="detail-section"><button class="btn btn-ghost small" onclick="loadArticleGraph('${pmid}')">✦ View Knowledge Graph</button></div>`;
    // Inject AI Summary + Related Papers buttons
    if (typeof injectAIButtons === 'function') injectAIButtons(pmid);
  } catch (e) { pane.innerHTML = `<div style="color:var(--accent-pink);padding:20px">Error: ${escHtml(e.message)}</div>`; }
}

window.loadPubDetail = loadPubDetail;

window.searchByMesh = function (term) {
  document.getElementById('pub-search-q').value = term;
  pubOffset = 0; runPubSearch();
};

window.loadConceptInBrowser = function (id) {
  navigateTo('ontology');
  setTimeout(() => loadConceptDetail(id), 200);
};

function escHtml(s) {
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
window.escHtml = escHtml;
