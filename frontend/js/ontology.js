/* ontology.js – Ontology concept browser and hierarchy viewer */
let ontOffset = 0, ontLimit = 20, ontTotal = 0;

async function initOntology() {
  await loadOntologyFilters();
  document.getElementById('ont-search-btn').addEventListener('click', () => { ontOffset = 0; runOntSearch(); });
  document.getElementById('ont-search-q').addEventListener('keydown', e => { if (e.key === 'Enter') { ontOffset = 0; runOntSearch(); } });
  runOntSearch();
}
window.initOntology = initOntology;

async function loadOntologyFilters() {
  try {
    const d = await apiFetch('/api/ontologies');
    const sel = document.getElementById('ont-filter-ontology');
    d.ontologies.forEach(o => {
      const opt = document.createElement('option');
      opt.value = o.acronym; opt.textContent = `${o.acronym} – ${o.name || o.acronym} (${(o.concept_count || 0).toLocaleString()})`;
      sel.appendChild(opt);
    });
  } catch (e) { console.warn('Ontology filter load:', e.message); }
}

async function runOntSearch() {
  const q = document.getElementById('ont-search-q').value.trim();
  const ont = document.getElementById('ont-filter-ontology').value;
  const cat = document.getElementById('ont-filter-category').value;
  const params = new URLSearchParams({ limit: ontLimit, offset: ontOffset });
  if (q) params.set('q', q);
  if (ont) params.set('ontology', ont);
  if (cat) params.set('category', cat);

  renderOntSkeleton();
  try {
    const d = await apiFetch('/api/ontologies/concepts?' + params.toString());
    ontTotal = d.total;
    renderOntList(d.results);
    document.getElementById('ont-list-meta').textContent = `${d.total.toLocaleString()} concepts · ${ontOffset + 1}–${Math.min(ontOffset + ontLimit, d.total)}`;
    renderOntPagination(d.total, ontOffset, ontLimit);
  } catch (e) { showToast('Concept search failed: ' + e.message, 'error'); }
}

function renderOntSkeleton() {
  document.getElementById('ont-list').innerHTML = Array(6).fill(0).map(() =>
    `<div class="concept-card"><div class="skel-line medium skeleton"></div><div class="skel-line short skeleton"></div></div>`).join('');
}

function renderOntList(concepts) {
  const el = document.getElementById('ont-list');
  if (!concepts.length) { el.innerHTML = '<div style="color:var(--text-muted);padding:20px;text-align:center">No concepts found</div>'; return; }
  el.innerHTML = concepts.map(c => `
    <div class="concept-card" data-id="${c.id}" onclick="loadConceptDetail(${c.id}, this)">
      <div class="concept-card-label">${escHtml(c.label)}</div>
      <div class="concept-card-meta">
        <span class="badge ${catBadge(c.category)}">${c.category}</span>
        ${c.ontology?.acronym ? `<span class="badge">${c.ontology.acronym}</span>` : ''}
      </div>
      ${c.definition ? `<div class="concept-card-def">${escHtml(c.definition.slice(0, 100))}…</div>` : ''}
    </div>`).join('');
}

function catBadge(cat) {
  return { disease: 'pink', drug: 'green', biomarker: 'orange', general: 'purple' }[cat] || '';
}

function renderOntPagination(total, offset, limit) {
  const pages = Math.ceil(total / limit);
  const cur = Math.floor(offset / limit);
  const el = document.getElementById('ont-pagination');
  if (pages <= 1) { el.innerHTML = ''; return; }
  let html = `<button class="page-btn" onclick="ontPage(${cur - 1})" ${cur === 0 ? 'disabled' : ''}>‹</button>`;
  for (let i = Math.max(0, cur - 2); i <= Math.min(pages - 1, cur + 2); i++)
    html += `<button class="page-btn ${i === cur ? 'active' : ''}" onclick="ontPage(${i})">${i + 1}</button>`;
  html += `<button class="page-btn" onclick="ontPage(${cur + 1})" ${cur >= pages - 1 ? 'disabled' : ''}>›</button>`;
  el.innerHTML = html;
}

window.ontPage = function (page) { ontOffset = page * ontLimit; runOntSearch(); };

async function loadConceptDetail(id, card) {
  if (card) { document.querySelectorAll('.concept-card').forEach(c => c.classList.remove('selected')); card.classList.add('selected'); }
  const pane = document.getElementById('ont-detail-pane');
  pane.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text-muted)">Loading…</div>`;
  try {
    const c = await apiFetch(`/api/ontologies/concepts/${id}`);
    pane.innerHTML = `
      <div class="detail-title">${escHtml(c.label)}</div>
      <div class="detail-meta-row">
        <span class="badge ${catBadge(c.category)}">${c.category}</span>
        ${c.ontology?.acronym ? `<span class="badge">${c.ontology.acronym}</span>` : ''}
        <span class="badge">${c.article_count} article${c.article_count !== 1 ? 's' : ''}</span>
        ${c.bioportal_url ? `<a class="badge" href="${c.bioportal_url}" target="_blank">BioPortal ↗</a>` : ''}
      </div>
      ${c.definition ? `<div class="detail-section"><h4>Definition</h4><div class="detail-abstract">${escHtml(c.definition)}</div></div>` : ''}
      ${c.synonyms?.length ? `<div class="detail-section"><h4>Synonyms</h4><div class="tag-cloud">${c.synonyms.map(s => `<span class="tag">${escHtml(s)}</span>`).join('')}</div></div>` : ''}
      ${c.parents?.length ? `<div class="detail-section"><h4>Parent Concepts</h4><div class="hierarchy-tree">${c.parents.map(p => `<div class="tree-node" onclick="loadConceptDetail(${p.id})">↑ ${escHtml(p.label)} <span class="badge ${catBadge(p.category)}">${p.category}</span></div>`).join('')}</div></div>` : ''}
      ${c.children?.length ? `<div class="detail-section"><h4>Child Concepts (${c.children.length})</h4><div class="hierarchy-tree">${c.children.map(ch => `<div class="tree-node" onclick="loadConceptDetail(${ch.id})">↓ ${escHtml(ch.label)} <span class="badge ${catBadge(ch.category)}">${ch.category}</span></div>`).join('')}</div></div>` : ''}
      ${c.article_count ? `<div class="detail-section"><button class="btn btn-ghost small" onclick="loadConceptArticles(${id},'${escHtml(c.label)}')">📄 View ${c.article_count} linked articles</button> <button class="btn btn-ghost small" onclick="loadConceptGraph(${id})">✦ Knowledge Graph</button></div>` : ''}
      <div id="concept-articles-list"></div>`;
  } catch (e) { pane.innerHTML = `<div style="color:var(--accent-pink);padding:20px">Error: ${e.message}</div>`; }
}
window.loadConceptDetail = loadConceptDetail;

window.loadConceptArticles = async function (id, label) {
  const el = document.getElementById('concept-articles-list');
  el.innerHTML = `<div style="color:var(--text-muted);font-size:13px;padding:10px">Loading articles…</div>`;
  try {
    const d = await apiFetch(`/api/ontologies/concepts/${id}/articles?limit=10`);
    el.innerHTML = `<div class="detail-section"><h4>Linked Articles (${d.total})</h4>${d.articles.map(a => `
      <div class="pub-card" style="margin-bottom:8px" onclick="navigateTo('publications');setTimeout(()=>loadPubDetail('${a.pmid}',document.querySelector('[data-pmid=\\'${a.pmid}\\']')||document.createElement('div')),200)">
        <div class="pub-card-title">${escHtml(a.title)}</div>
        <div class="pub-card-meta"><span class="badge">${a.pmid}</span>${a.pub_year ? `<span class="badge purple">${a.pub_year}</span>` : ''}<span class="badge green">${a.match_type}</span></div>
      </div>`).join('')}</div>`;
  } catch (e) { el.innerHTML = `<div style="color:var(--accent-pink)">Error loading articles</div>`; }
};
