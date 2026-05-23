/* relationships.js – Relationship explorer table */
let relOffset = 0, relLimit = 50;

function initRelationships() {
  document.getElementById('rel-search-btn').addEventListener('click', () => { relOffset = 0; runRelSearch(); });
  loadRelSummary();
  runRelSearch();
}
window.initRelationships = initRelationships;

async function loadRelSummary() {
  try {
    const d = await apiFetch('/api/relationships/summary');
    const colors = { disease: 'pink', drug: 'green', biomarker: 'orange', general: 'purple' };
    const bar = document.getElementById('rel-summary');
    bar.innerHTML = Object.entries(d.by_category).map(([cat, count]) =>
      `<div class="summary-chip"><span class="badge ${colors[cat] || ''}">${cat}</span> <strong>${count.toLocaleString()}</strong> mappings</div>`
    ).join('');
  } catch (e) { console.warn('Rel summary:', e.message); }
}

async function runRelSearch() {
  const cat = document.getElementById('rel-filter-category').value;
  const match = document.getElementById('rel-filter-match').value;
  const params = new URLSearchParams({ limit: relLimit, offset: relOffset });
  if (cat) params.set('category', cat);
  if (match) params.set('match_type', match);
  try {
    const d = await apiFetch('/api/relationships?' + params.toString());
    renderRelTable(d.results);
    renderRelPagination(d.total, relOffset, relLimit);
  } catch (e) { showToast('Relationship query failed: ' + e.message, 'error'); }
}

function renderRelTable(rows) {
  const tbody = document.getElementById('rel-table-body');
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:24px">No relationships found</td></tr>'; return; }
  const matchColors = { mesh: 'cyan', keyword: 'purple', annotator: 'teal' };
  tbody.innerHTML = rows.map(r => `
    <tr onclick="navigateTo('publications');setTimeout(()=>document.getElementById('pub-search-pmid').value='${r.article.pmid}',100)">
      <td title="${escHtml(r.article.title)}">${escHtml(r.article.title.slice(0, 55))}${r.article.title.length > 55 ? '…' : ''}</td>
      <td>${r.article.pub_year || '–'}</td>
      <td><span onclick="event.stopPropagation();loadConceptInBrowser(${r.concept.id})" style="cursor:pointer;color:var(--accent-purple)">${escHtml(r.concept.label)}</span></td>
      <td><span class="badge ${catBadge(r.concept.category)}">${r.concept.category}</span></td>
      <td><span class="badge">${r.match_type}</span></td>
      <td style="color:var(--text-muted);font-size:11px">${escHtml(r.matched_text.slice(0, 40))}</td>
    </tr>`).join('');
}

function renderRelPagination(total, offset, limit) {
  const pages = Math.ceil(total / limit); const cur = Math.floor(offset / limit);
  const el = document.getElementById('rel-pagination');
  if (pages <= 1) { el.innerHTML = ''; return; }
  let html = `<span class="page-info">${total.toLocaleString()} total</span>`;
  html += `<button class="page-btn" onclick="relPage(${cur - 1})" ${cur === 0 ? 'disabled' : ''}>‹ Prev</button>`;
  html += `<span class="page-info">Page ${cur + 1} / ${pages}</span>`;
  html += `<button class="page-btn" onclick="relPage(${cur + 1})" ${cur >= pages - 1 ? 'disabled' : ''}>Next ›</button>`;
  el.innerHTML = html;
}

window.relPage = function (page) { relOffset = page * relLimit; runRelSearch(); };
