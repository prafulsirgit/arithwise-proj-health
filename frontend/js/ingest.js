/* ingest.js – Data management: trigger jobs, poll status, show history */

function initIngest() {
  document.getElementById('ingest-pubmed-btn').addEventListener('click', triggerPubMed);
  document.getElementById('ingest-bp-btn').addEventListener('click', triggerBioPortal);
  document.getElementById('ingest-map-btn').addEventListener('click', triggerMapping);
  document.getElementById('refresh-jobs-btn').addEventListener('click', loadJobs);
  document.getElementById('reset-db-btn').addEventListener('click', resetDatabase);
  loadJobs();
}
window.initIngest = initIngest;

async function triggerPubMed() {
  const query = document.getElementById('ingest-pubmed-query').value.trim();
  const max_results = parseInt(document.getElementById('ingest-pubmed-max').value) || 200;
  if (!query) { showToast('Query cannot be empty', 'error'); return; }
  setBtnLoading('ingest-pubmed-btn', true);
  try {
    const d = await apiFetch('/api/ingest/pubmed', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query, max_results }) });
    showToast(`PubMed job #${d.job_id} queued`, 'success');
    pollJob(d.job_id);
    setTimeout(loadJobs, 1000);
  } catch (e) { showToast('PubMed error: ' + e.message, 'error'); }
  finally { setBtnLoading('ingest-pubmed-btn', false); }
}

async function triggerBioPortal() {
  const raw = document.getElementById('ingest-bp-onts').value.trim();
  const ontologies = raw.split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
  const max_concepts_per_ontology = parseInt(document.getElementById('ingest-bp-max').value) || 500;
  setBtnLoading('ingest-bp-btn', true);
  try {
    const d = await apiFetch('/api/ingest/bioportal', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ontologies, max_concepts_per_ontology }) });
    showToast(`BioPortal job #${d.job_id} queued`, 'success');
    pollJob(d.job_id);
    setTimeout(loadJobs, 1000);
  } catch (e) { showToast('BioPortal error: ' + e.message, 'error'); }
  finally { setBtnLoading('ingest-bp-btn', false); }
}

async function triggerMapping() {
  const limit_unmapped = parseInt(document.getElementById('ingest-map-limit').value) || 100;
  setBtnLoading('ingest-map-btn', true);
  try {
    const d = await apiFetch('/api/ingest/map', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limit_unmapped }) });
    showToast(`Mapping job #${d.job_id} queued`, 'success');
    pollJob(d.job_id);
    setTimeout(loadJobs, 1000);
  } catch (e) { showToast('Mapping error: ' + e.message, 'error'); }
  finally { setBtnLoading('ingest-map-btn', false); }
}

async function loadJobs() {
  try {
    const d = await apiFetch('/api/ingest/jobs?limit=15');
    renderJobsTable(d.jobs);
  } catch (e) { console.warn('Jobs load:', e.message); }
}

function renderJobsTable(jobs) {
  const tbody = document.getElementById('jobs-table-body');
  if (!jobs.length) { tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-muted);padding:20px">No jobs yet</td></tr>'; return; }
  tbody.innerHTML = jobs.map(j => {
    const started = j.started_at ? new Date(j.started_at).toLocaleString() : '–';
    let dur = '–';
    if (j.started_at && j.completed_at) {
      const s = new Date(j.started_at), e = new Date(j.completed_at);
      const sec = Math.round((e - s) / 1000);
      dur = sec < 60 ? `${sec}s` : `${Math.round(sec / 60)}m ${sec % 60}s`;
    }
    return `<tr>
      <td>${j.id}</td>
      <td><span class="badge">${j.job_type}</span></td>
      <td><span class="status-pill ${j.status}">${j.status}</span></td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:var(--text-muted)">${escHtml((j.query || '').slice(0, 60))}</td>
      <td>${j.records_new ?? 0}</td>
      <td>${j.records_processed ?? 0}</td>
      <td style="font-size:11px">${started}</td>
      <td>${dur}</td>
    </tr>`;
  }).join('');
}

function pollJob(jobId) {
  let attempts = 0;
  const timer = setInterval(async () => {
    attempts++;
    try {
      const j = await apiFetch(`/api/ingest/jobs/${jobId}`);
      if (j.status === 'completed') {
        showToast(`Job #${jobId} completed: ${j.records_new} new records`, 'success');
        clearInterval(timer);
        loadJobs();
        // Refresh dashboard counts
        if (typeof loadOverview === 'function') loadOverview();
      } else if (j.status === 'failed') {
        showToast(`Job #${jobId} failed: ${j.error_message}`, 'error');
        clearInterval(timer);
        loadJobs();
      }
    } catch { clearInterval(timer); }
    if (attempts > 120) clearInterval(timer); // max 2 min polling
  }, 3000);
}

function setBtnLoading(id, loading) {
  const btn = document.getElementById(id);
  if (!btn) return;
  if (loading) {
    btn.dataset.originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⟳ Running…';
  } else {
    btn.disabled = false;
    btn.textContent = btn.dataset.originalText || btn.textContent;
    delete btn.dataset.originalText;
  }
}

async function resetDatabase() {
  // Two-step confirmation to prevent accidental wipes
  const first = confirm('⚠ This will permanently delete ALL publications, concepts, mappings, and ingestion history.\n\nAre you sure you want to reset the entire database?');
  if (!first) return;
  const typed = prompt('Type RESET to confirm:');
  if (typed !== 'RESET') { showToast('Reset cancelled.', 'info'); return; }

  const btn = document.getElementById('reset-db-btn');
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⟳ Resetting…';

  try {
    const d = await apiFetch('/api/admin/reset-db', { method: 'POST' });
    showToast('✓ ' + d.message, 'success', 6000);
    loadJobs();
    // Refresh dashboard stats
    if (typeof loadOverview === 'function') loadOverview();
    if (typeof loadCharts === 'function') loadCharts();
  } catch (e) {
    showToast('Reset failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}
