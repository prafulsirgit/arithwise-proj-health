/* app.js – Router, API client, toast, shared state */
// Empty string = relative URL — works from any host since frontend is served by FastAPI
const API = '';

// ── State ────────────────────────────────────────
window.AppState = { currentPage: 'dashboard' };

// ── API helpers ───────────────────────────────────
async function apiFetch(path, opts = {}) {
  try {
    const r = await fetch(API + path, opts);
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || r.statusText);
    }
    return await r.json();
  } catch (e) {
    console.error('API error:', path, e.message);
    throw e;
  }
}
window.apiFetch = apiFetch;

// ── Toast ─────────────────────────────────────────
function showToast(msg, type = 'info', ms = 4000) {
  const c = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), ms);
}
window.showToast = showToast;

// ── Navigation ─────────────────────────────────────
function navigateTo(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const pageEl = document.getElementById('page-' + page);
  const navEl = document.getElementById('nav-' + page);
  if (pageEl) pageEl.classList.add('active');
  if (navEl) navEl.classList.add('active');
  const titles = { dashboard: 'Dashboard', discover: '🔍 Discover', publications: 'Publications', ontology: 'Ontology Browser', relationships: 'Relationships', graph: 'Knowledge Graph', ingest: 'Data Management' };
  document.getElementById('page-title').textContent = titles[page] || page;
  AppState.currentPage = page;
  window.location.hash = page;
}
window.navigateTo = navigateTo;

document.querySelectorAll('.nav-item').forEach(el => {
  el.addEventListener('click', e => { e.preventDefault(); navigateTo(el.dataset.page); });
});

// ── Global search → Discover ───────────────────────────────
document.getElementById('global-search').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    const q = e.target.value.trim();
    if (!q) return;
    navigateTo('discover');
    setTimeout(() => {
      const inp = document.getElementById('discover-search-input');
      if (inp) inp.value = q;
      if (typeof runDiscoverSearch === 'function') runDiscoverSearch(q);
    }, 100);
  }
});

// ── Health check ───────────────────────────────────
async function checkHealth() {
  const dot = document.querySelector('.status-dot');
  const txt = document.querySelector('.status-text');
  try {
    await apiFetch('/api/health');
    dot.className = 'status-dot online';
    txt.textContent = 'API Online';
  } catch {
    dot.className = 'status-dot offline';
    txt.textContent = 'API Offline';
  }
}

// ── Theme management ──────────────────────────────
function initTheme() {
  const saved = localStorage.getItem('oncodb-theme') || 'light';
  if (saved === 'dark') {
    document.body.classList.add('dark-theme');
  } else {
    document.body.classList.remove('dark-theme');
  }

  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.addEventListener('click', () => {
      const isDark = document.body.classList.toggle('dark-theme');
      localStorage.setItem('oncodb-theme', isDark ? 'dark' : 'light');
      if (typeof loadCharts === 'function' && window.AppState.currentPage === 'dashboard') {
        loadCharts();
      }
    });
  }
}
window.initTheme = initTheme;

// ── Init ────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  const hash = window.location.hash.replace('#', '') || 'discover';
  navigateTo(hash);
  checkHealth();
  setInterval(checkHealth, 30000);
  if (typeof initDashboard === 'function') initDashboard();
  if (typeof initDiscover === 'function') initDiscover();
  if (typeof initSearch === 'function') initSearch();
  if (typeof initOntology === 'function') initOntology();
  if (typeof initRelationships === 'function') initRelationships();
  if (typeof initGraph === 'function') initGraph();
  if (typeof initIngest === 'function') initIngest();
});
