/* analytics.js – Dashboard stats and Chart.js charts */
let chartYears, chartCategories, chartTopConcepts;

async function initDashboard() {
  await loadOverview();
  await loadCharts();
}
window.initDashboard = initDashboard;

async function loadOverview() {
  try {
    const d = await apiFetch('/api/analytics/overview');
    animateCount('stat-articles', d.total_articles);
    animateCount('stat-concepts', d.total_concepts);
    animateCount('stat-mappings', d.total_mappings);
    animateCount('stat-ontologies', d.total_ontologies);
    animateCount('stat-diseases', d.total_diseases);
    animateCount('stat-drugs', d.total_drugs);
    animateCount('stat-biomarkers', d.total_biomarkers);
    animateCount('stat-authors', d.total_authors);
  } catch (e) { console.warn('Overview error:', e.message); }
}

function animateCount(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!target) { el.textContent = '0'; return; }
  let start = 0; const dur = 800; const step = 16;
  const inc = target / (dur / step);
  const timer = setInterval(() => {
    start = Math.min(start + inc, target);
    el.textContent = Math.floor(start).toLocaleString();
    if (start >= target) clearInterval(timer);
  }, step);
}

async function loadCharts() {
  const isDark = document.body.classList.contains('dark-theme');
  const C = isDark 
    ? { cyan: '#00d4ff', purple: '#a855f7', teal: '#22d3ee', pink: '#ec4899', green: '#10b981', orange: '#f59e0b' }
    : { cyan: '#2563eb', purple: '#4f46e5', teal: '#0d9488', pink: '#e11d48', green: '#059669', orange: '#d97706' };
  
  const grid = { color: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(15, 23, 42, 0.05)' };
  const textColor = isDark ? '#94a3b8' : '#475569';
  const baseOpts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid, ticks: { color: textColor, font: { size: 11 } } }, y: { grid, ticks: { color: textColor, font: { size: 11 } } } } };

  // Publications by year
  try {
    const d = await apiFetch('/api/analytics/publications-by-year');
    const ctx = document.getElementById('chart-years').getContext('2d');
    if (chartYears) chartYears.destroy();
    chartYears = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: d.data.map(r => r.year),
        datasets: [{ data: d.data.map(r => r.count), backgroundColor: 'rgba(37, 99, 235, 0.1)', borderColor: C.cyan, borderWidth: 2, borderRadius: 4 }]
      },
      options: { ...baseOpts }
    });
  } catch (e) { console.warn('Year chart:', e.message); }

  // Concept categories doughnut
  try {
    const d = await apiFetch('/api/analytics/concepts-by-category');
    const catColors = { disease: C.pink, drug: C.green, biomarker: C.orange, general: C.purple };
    const ctx = document.getElementById('chart-categories').getContext('2d');
    if (chartCategories) chartCategories.destroy();
    chartCategories = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: d.data.map(r => r.category),
        datasets: [{ data: d.data.map(r => r.count), backgroundColor: d.data.map(r => catColors[r.category] || C.cyan), borderWidth: 0, hoverOffset: 8 }]
      },
      options: { responsive: true, maintainAspectRatio: false, cutout: '65%', plugins: { legend: { position: 'bottom', labels: { color: textColor, font: { size: 12 }, padding: 12 } } } }
    });
  } catch (e) { console.warn('Category chart:', e.message); }

  // Top concepts bar
  try {
    const d = await apiFetch('/api/analytics/top-concepts?limit=12');
    const catColors = { disease: C.pink, drug: C.green, biomarker: C.orange, general: C.purple };
    const ctx = document.getElementById('chart-top-concepts').getContext('2d');
    if (chartTopConcepts) chartTopConcepts.destroy();
    chartTopConcepts = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: d.data.map(r => r.label.length > 22 ? r.label.slice(0, 22) + '…' : r.label),
        datasets: [{ data: d.data.map(r => r.article_count), backgroundColor: d.data.map(r => (catColors[r.category] || C.cyan) + '22'), borderColor: d.data.map(r => catColors[r.category] || C.cyan), borderWidth: 2, borderRadius: 4 }]
      },
      options: { ...baseOpts, indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { ...baseOpts.scales.x }, y: { grid: { display: false }, ticks: { color: textColor, font: { size: 11 } } } } }
    });
  } catch (e) { console.warn('Top concepts chart:', e.message); }

  // Top journals ranked list
  try {
    const d = await apiFetch('/api/analytics/top-journals?limit=8');
    const max = d.data[0]?.count || 1;
    const container = document.getElementById('top-journals-list');
    container.innerHTML = d.data.map((r, i) => `
      <div class="ranked-item">
        <span class="ranked-rank">#${i + 1}</span>
        <span class="ranked-name" title="${r.journal}">${r.journal.length > 30 ? r.journal.slice(0, 30) + '…' : r.journal}</span>
        <div class="ranked-bar-wrap"><div class="ranked-bar" style="width:${(r.count / max * 100)}%"></div></div>
        <span class="ranked-count">${r.count}</span>
      </div>`).join('');
  } catch (e) { console.warn('Journals list:', e.message); }
}
