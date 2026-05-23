/* visualizations.js – Enriched D3.js force-directed knowledge graph with dynamic expansion */
let simulation, svgSel;
let nodeColors, labelColor, linkColor;

// ── Graph State ──────────────────────────────────────────────────────────────
let currentNodes = [];
let currentEdges = [];
let isFrozen = false;
let activeNodeId = null;

// ── Debounce helper ─────────────────────────────────────────────────────────
function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ── Autocomplete for Articles ────────────────────────────────────────────────
function initArticleAutocomplete() {
  const input = document.getElementById('graph-article-search');
  const list = document.getElementById('graph-article-list');
  const wrap = document.getElementById('graph-article-wrap');

  const doSearch = debounce(async (q) => {
    if (!q || q.length < 2) { closeList(list, wrap); return; }
    try {
      const data = await apiFetch(`/api/publications?q=${encodeURIComponent(q)}&limit=8`);
      renderArticleSuggestions(data.results || [], list, input, wrap);
    } catch { closeList(list, wrap); }
  }, 280);

  input.addEventListener('input', () => {
    doSearch(input.value.trim());
  });

  input.addEventListener('keydown', (e) => {
    handleListKeydown(e, list, input, wrap);
  });

  document.addEventListener('click', (e) => {
    if (!wrap.contains(e.target)) closeList(list, wrap);
  });
}

function renderArticleSuggestions(articles, list, input, wrap) {
  list.innerHTML = '';
  if (!articles.length) {
    list.innerHTML = '<li class="graph-ac-empty">No articles found</li>';
    openList(list, wrap);
    return;
  }
  articles.forEach(a => {
    const li = document.createElement('li');
    li.className = 'graph-ac-item';
    li.setAttribute('role', 'option');
    li.dataset.pmid = a.pmid;
    li.innerHTML = `
      <span class="ac-item-icon">◉</span>
      <span class="ac-item-main">${escHtml(a.title)}</span>
      <span class="ac-item-sub">${a.pub_year || ''} · PMID ${a.pmid}</span>`;
    li.addEventListener('mousedown', (e) => {
      e.preventDefault();
      input.value = a.title;
      closeList(list, wrap);
      loadArticleGraph(a.pmid);
    });
    list.appendChild(li);
  });
  openList(list, wrap);
}

// ── Autocomplete for Concepts ────────────────────────────────────────────────
function initConceptAutocomplete() {
  const input = document.getElementById('graph-concept-search');
  const list = document.getElementById('graph-concept-list');
  const wrap = document.getElementById('graph-concept-wrap');

  const doSearch = debounce(async (q) => {
    if (!q || q.length < 2) { closeList(list, wrap); return; }
    try {
      const data = await apiFetch(`/api/ontologies/concepts?q=${encodeURIComponent(q)}&limit=8`);
      renderConceptSuggestions(data.results || [], list, input, wrap);
    } catch { closeList(list, wrap); }
  }, 280);

  input.addEventListener('input', () => {
    doSearch(input.value.trim());
  });

  input.addEventListener('keydown', (e) => {
    handleListKeydown(e, list, input, wrap);
  });

  document.addEventListener('click', (e) => {
    if (!wrap.contains(e.target)) closeList(list, wrap);
  });
}

function renderConceptSuggestions(concepts, list, input, wrap) {
  list.innerHTML = '';
  if (!concepts.length) {
    list.innerHTML = '<li class="graph-ac-empty">No concepts found</li>';
    openList(list, wrap);
    return;
  }
  const catIcon = { disease: '✚', drug: '⬘', biomarker: '⬙', general: '⬡' };
  concepts.forEach(c => {
    const li = document.createElement('li');
    li.className = 'graph-ac-item';
    li.setAttribute('role', 'option');
    li.dataset.id = c.id;
    li.innerHTML = `
      <span class="ac-item-icon">${catIcon[c.category] || '⬡'}</span>
      <span class="ac-item-main">${escHtml(c.label)}</span>
      <span class="ac-item-sub ac-cat ac-cat-${c.category}">${c.category}</span>`;
    li.addEventListener('mousedown', (e) => {
      e.preventDefault();
      input.value = c.label;
      closeList(list, wrap);
      loadConceptGraph(c.id);
    });
    list.appendChild(li);
  });
  openList(list, wrap);
}

// ── Dropdown helpers ─────────────────────────────────────────────────────────
function openList(list, wrap) {
  list.style.display = 'block';
  wrap.classList.add('ac-open');
}
function closeList(list, wrap) {
  list.style.display = 'none';
  wrap.classList.remove('ac-open');
}

function handleListKeydown(e, list, input, wrap) {
  const items = [...list.querySelectorAll('.graph-ac-item')];
  const active = list.querySelector('.graph-ac-item.focused');
  let idx = items.indexOf(active);

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (active) active.classList.remove('focused');
    const next = items[Math.min(idx + 1, items.length - 1)];
    if (next) next.classList.add('focused');
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (active) active.classList.remove('focused');
    const prev = items[Math.max(idx - 1, 0)];
    if (prev) prev.classList.add('focused');
  } else if (e.key === 'Enter') {
    if (active) { e.preventDefault(); active.dispatchEvent(new MouseEvent('mousedown')); }
  } else if (e.key === 'Escape') {
    closeList(list, wrap);
  }
}

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Init controls ────────────────────────────────────────────────────────────
function initGraph() {
  initArticleAutocomplete();
  initConceptAutocomplete();

  // Load article button fallback
  document.getElementById('graph-load-article').addEventListener('click', () => {
    const raw = document.getElementById('graph-article-search').value.trim();
    if (raw) {
      // If it looks like a PMID, load it directly
      if (/^\d+$/.test(raw)) loadArticleGraph(raw);
      else showToast('Please select an article from the dropdown suggestions', 'info');
    } else {
      showToast('Please type a publication title first', 'warning');
    }
  });

  // Load concept button fallback
  document.getElementById('graph-load-concept').addEventListener('click', () => {
    const raw = document.getElementById('graph-concept-search').value.trim();
    if (raw) {
      showToast('Please select a concept from the dropdown suggestions', 'info');
    } else {
      showToast('Please type a concept name first', 'warning');
    }
  });

  // Action: Clear
  document.getElementById('graph-reset-btn').addEventListener('click', () => {
    if (simulation) simulation.stop();
    currentNodes = [];
    currentEdges = [];
    activeNodeId = null;
    isFrozen = false;

    document.getElementById('graph-freeze-btn').textContent = '⏸ Freeze';
    document.getElementById('graph-placeholder').style.display = 'flex';
    document.getElementById('graph-info').textContent = '';
    d3.select('#knowledge-graph').selectAll('*').remove();

    // Reset side panel
    document.getElementById('graph-details-card').innerHTML = `
      <div class="details-empty-state">
        <div class="empty-icon">ℹ</div>
        <p>Select any node in the graph to display its metadata, abstract, or ontology definitions here.</p>
      </div>
    `;
  });

  // Action: Freeze
  document.getElementById('graph-freeze-btn').addEventListener('click', () => {
    if (!simulation) return;
    if (isFrozen) {
      // Unfreeze
      currentNodes.forEach(n => { n.fx = null; n.fy = null; });
      isFrozen = false;
      document.getElementById('graph-freeze-btn').textContent = '⏸ Freeze';
      simulation.alpha(0.3).restart();
    } else {
      // Freeze
      currentNodes.forEach(n => { n.fx = n.x; n.fy = n.y; });
      isFrozen = true;
      document.getElementById('graph-freeze-btn').textContent = '▶ Run';
    }
  });
}
window.initGraph = initGraph;

// ── Graph Loaders ────────────────────────────────────────────────────────────
window.loadArticleGraph = async function (pmid) {
  navigateTo('graph');
  try {
    const d = await apiFetch(`/api/publications/${pmid}/graph`);
    // Fetch publication details to show in sidebar and input field
    let title = `PMID ${pmid}`;
    try {
      const art = await apiFetch(`/api/publications/${pmid}`);
      title = art.title || title;
      document.getElementById('graph-article-search').value = title;
    } catch { }

    document.getElementById('graph-info').textContent =
      `Knowledge Graph for "${title}" · ${d.nodes.length} nodes, ${d.edges.length} edges`;

    // Render
    renderGraph(d.nodes, d.edges);

    // Set target article as active
    const rootNode = d.nodes.find(n => n.id === `article_${pmid}`);
    if (rootNode) {
      activeNodeId = rootNode.id;
      svgSel.selectAll('g.graph-node').classed('node-active', node => node.id === activeNodeId);
      showNodeDetails(rootNode);
    }
  } catch (e) { showToast('Graph error: ' + e.message, 'error'); }
};

window.loadConceptGraph = async function (id) {
  navigateTo('graph');
  try {
    const d = await apiFetch(`/api/ontologies/concepts/${id}/graph`);
    const root = d.nodes.find(n => n.concept_id === id);
    const label = root ? root.label : `Concept ${id}`;
    document.getElementById('graph-concept-search').value = label;

    document.getElementById('graph-info').textContent =
      `Knowledge Graph for "${label}" · ${d.nodes.length} nodes, ${d.edges.length} edges`;

    // Render
    renderGraph(d.nodes, d.edges);

    if (root) {
      activeNodeId = root.id;
      svgSel.selectAll('g.graph-node').classed('node-active', node => node.id === activeNodeId);
      showNodeDetails(root);
    }
  } catch (e) { showToast('Graph error: ' + e.message, 'error'); }
};

// ── Merge Data Helper ────────────────────────────────────────────────────────
function mergeGraphData(newNodes, newEdges) {
  // Merge nodes
  newNodes.forEach(node => {
    if (!currentNodes.some(n => n.id === node.id)) {
      currentNodes.push(node);
    }
  });

  // Merge edges
  newEdges.forEach(edge => {
    const sourceId = typeof edge.source === 'object' ? edge.source.id : edge.source;
    const targetId = typeof edge.target === 'object' ? edge.target.id : edge.target;

    const exists = currentEdges.some(e => {
      const eSourceId = typeof e.source === 'object' ? e.source.id : e.source;
      const eTargetId = typeof e.target === 'object' ? e.target.id : e.target;
      return eSourceId === sourceId && eTargetId === targetId;
    });

    if (!exists) {
      currentEdges.push(edge);
    }
  });
}

// ── Details Sidebar Renderer ──────────────────────────────────────────────────
async function showNodeDetails(d) {
  const panel = document.getElementById('graph-details-card');
  panel.innerHTML = `
    <div class="details-empty-state">
      <div class="skeleton skel-line"></div>
      <div class="skeleton skel-line medium"></div>
      <div class="skeleton skel-line short"></div>
    </div>
  `;

  try {
    if (d.type === 'article') {
      const art = await apiFetch(`/api/publications/${d.pmid}`);
      const authorList = art.authors && art.authors.length ? art.authors.map(a => a.name).join(', ') : 'Unknown';
      panel.innerHTML = `
        <div><span class="graph-detail-badge article">Article</span></div>
        <div class="graph-detail-title">${escHtml(art.title)}</div>
        
        <div class="graph-detail-section">
          <div class="graph-detail-section-title">Authors</div>
          <div>${escHtml(authorList)}</div>
        </div>
        
        <div class="graph-detail-section">
          <div class="graph-detail-section-title">Journal & Year</div>
          <div>${escHtml(art.journal)} (${art.pub_year})</div>
        </div>
        
        <div class="graph-detail-section">
          <div class="graph-detail-section-title">Abstract</div>
          <div class="graph-detail-abstract">${escHtml(art.abstract || 'No abstract available.')}</div>
        </div>
        
        <div class="graph-detail-section">
          <div class="graph-detail-section-title">Database Info</div>
          <div>PMID: ${art.pmid} ${art.doi ? `· DOI: ${art.doi}` : ''}</div>
        </div>
        
        <button class="btn btn-ghost small graph-detail-btn" onclick="navigateToPub('${art.pmid}')">View Publication details</button>
      `;
    } else if (d.type === 'author') {
      panel.innerHTML = `
        <div><span class="graph-detail-badge author">Author</span></div>
        <div class="graph-detail-title">${escHtml(d.label)}</div>
        
        <div class="graph-detail-section">
          <div class="graph-detail-section-title">Oncology Researchers</div>
          <div>Explore links to find cancer publications authored by this researcher in our local database.</div>
        </div>
      `;
    } else {
      // Concept node details
      const conc = await apiFetch(`/api/ontologies/concepts/${d.concept_id}`);
      const syns = conc.synonyms && conc.synonyms.length ? conc.synonyms.join(', ') : 'None';
      panel.innerHTML = `
        <div><span class="graph-detail-badge ${conc.category}">${conc.category}</span></div>
        <div class="graph-detail-title">${escHtml(conc.label)}</div>
        
        <div class="graph-detail-section">
          <div class="graph-detail-section-title">Ontology Definition</div>
          <div class="graph-detail-abstract">${escHtml(conc.definition || 'No definition available.')}</div>
        </div>
        
        <div class="graph-detail-section">
          <div class="graph-detail-section-title">Synonyms</div>
          <div>${escHtml(syns)}</div>
        </div>
        
        <div class="graph-detail-section">
          <div class="graph-detail-section-title">Origin Ontology</div>
          <div>${escHtml(conc.ontology ? conc.ontology.name : 'Unknown')} (${conc.ontology ? conc.ontology.acronym : ''})</div>
        </div>
        
        <button class="btn btn-ghost small graph-detail-btn" onclick="navigateToOnt('${conc.id}')">Explore in Ontology Browser</button>
      `;
    }
  } catch (err) {
    panel.innerHTML = `
      <div class="details-empty-state">
        <p style="color:var(--accent-pink)">Error loading details: ${err.message}</p>
      </div>
    `;
  }
}

window.navigateToPub = function (pmid) {
  navigateTo('publications');
  setTimeout(() => {
    document.getElementById('pub-search-pmid').value = pmid;
    document.getElementById('pub-search-btn').click();
  }, 200);
};

window.navigateToOnt = function (conceptId) {
  navigateTo('ontology');
  setTimeout(() => {
    loadConceptInBrowser(parseInt(conceptId));
  }, 200);
};

// ── Interactive Expansion on Click ─────────────────────────────────────────────
async function handleNodeClick(event, d) {
  event.stopPropagation();
  activeNodeId = d.id;

  // Highlight active node in SVG
  svgSel.selectAll('g.graph-node').classed('node-active', n => n.id === activeNodeId);

  // Update sidebar metadata
  showNodeDetails(d);

  // Expand neighbors
  try {
    let response;
    if (d.type === 'article') {
      response = await apiFetch(`/api/publications/${d.pmid}/graph`);
    } else if (d.type === 'author') {
      const res = await apiFetch(`/api/publications?author=${encodeURIComponent(d.label)}&limit=5`);
      const nodes = [];
      const edges = [];
      res.results.forEach(art => {
        const artId = `article_${art.pmid}`;
        nodes.push({
          id: artId,
          label: art.title.slice(0, 60) + '...',
          type: 'article',
          pmid: art.pmid
        });
        edges.push({
          source: artId,
          target: d.id,
          type: 'written_by'
        });
      });
      response = { nodes, edges };
    } else {
      response = await apiFetch(`/api/ontologies/concepts/${d.concept_id}/graph`);
    }

    if (response && response.nodes) {
      mergeGraphData(response.nodes, response.edges);
      updateGraph();

      document.getElementById('graph-info').textContent =
        `Active Graph · ${currentNodes.length} nodes, ${currentEdges.length} edges`;
    }
  } catch (err) {
    showToast('Failed to expand connections: ' + err.message, 'error');
  }
}

// ── D3 Rendering Logic ────────────────────────────────────────────────────────
function renderGraph(nodes, edges) {
  const isDark = document.body.classList.contains('dark-theme');
  nodeColors = isDark ? {
    article: '#00d4ff', author: '#94a3b8', disease: '#ec4899',
    drug: '#10b981', biomarker: '#f59e0b', general: '#a855f7'
  } : {
    article: '#2563eb', author: '#64748b', disease: '#e11d48',
    drug: '#059669', biomarker: '#d97706', general: '#4f46e5'
  };
  labelColor = isDark ? '#94a3b8' : '#475569';
  linkColor = isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(15, 23, 42, 0.08)';

  const container = document.getElementById('graph-container');
  document.getElementById('graph-placeholder').style.display = 'none';
  const W = container.clientWidth, H = container.clientHeight;

  currentNodes = nodes;
  currentEdges = edges;

  if (simulation) simulation.stop();
  d3.select('#knowledge-graph').selectAll('*').remove();

  svgSel = d3.select('#knowledge-graph').attr('width', W).attr('height', H);

  // Define Arrow Marker
  svgSel.append('defs').append('marker')
    .attr('id', 'arrow').attr('viewBox', '0 -4 8 8').attr('refX', 18).attr('refY', 0)
    .attr('markerWidth', 5).attr('markerHeight', 5).attr('orient', 'auto')
    .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', 'rgba(100,140,255,0.4)');

  const mainGroup = svgSel.append('g').attr('class', 'main-zoom-group');

  // Setup Zoom
  svgSel.call(d3.zoom().scaleExtent([0.15, 5]).on('zoom', e => mainGroup.attr('transform', e.transform)));

  // Setup simulation links & forces
  simulation = d3.forceSimulation()
    .force('link', d3.forceLink().id(d => d.id).distance(120))
    .force('charge', d3.forceManyBody().strength(-300))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collide', d3.forceCollide(32));

  // Build the layout
  updateGraph();
}

function updateGraph() {
  const isDark = document.body.classList.contains('dark-theme');
  nodeColors = isDark ? {
    article: '#00d4ff', author: '#94a3b8', disease: '#ec4899',
    drug: '#10b981', biomarker: '#f59e0b', general: '#a855f7'
  } : {
    article: '#2563eb', author: '#64748b', disease: '#e11d48',
    drug: '#059669', biomarker: '#d97706', general: '#4f46e5'
  };
  labelColor = isDark ? '#94a3b8' : '#475569';
  linkColor = isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(15, 23, 42, 0.08)';

  const mainGroup = svgSel.select('.main-zoom-group');
  if (mainGroup.empty()) return;

  // 1. Data join links
  let link = mainGroup.select('.links-group');
  if (link.empty()) link = mainGroup.append('g').attr('class', 'links-group');

  const linkSelection = link.selectAll('line')
    .data(currentEdges, d => `${d.source.id || d.source}-${d.target.id || d.target}`);

  linkSelection.exit().remove();

  const linkEnter = linkSelection.enter().append('line')
    .attr('stroke', linkColor)
    .attr('stroke-width', 1.5)
    .attr('class', d => `link-${d.type}`)
    .attr('marker-end', d => d.type === 'mapped_to' ? 'url(#arrow)' : null);

  const allLinks = linkEnter.merge(linkSelection);

  // 2. Data join nodes
  let node = mainGroup.select('.nodes-group');
  if (node.empty()) node = mainGroup.append('g').attr('class', 'nodes-group');

  const nodeSelection = node.selectAll('g.graph-node')
    .data(currentNodes, d => d.id);

  nodeSelection.exit().remove();

  const nodeEnter = nodeSelection.enter().append('g')
    .attr('class', 'graph-node')
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', dragStart)
      .on('drag', dragged)
      .on('end', dragEnd)
    )
    .on('click', handleNodeClick);

  // Circle representation
  nodeEnter.append('circle')
    .attr('r', d => {
      if (d.type === 'article') return 13;
      if (d.type === 'author') return 8;
      return 10;
    })
    .attr('fill', d => nodeColors[d.type] || '#64748b')
    .attr('fill-opacity', 0.8)
    .attr('stroke', d => nodeColors[d.type] || '#64748b')
    .attr('stroke-width', 2);

  // Text label
  nodeEnter.append('text')
    .attr('dy', 22)
    .attr('text-anchor', 'middle')
    .attr('font-size', '10px')
    .attr('fill', labelColor)
    .text(d => d.label.length > 16 ? d.label.slice(0, 16) + '…' : d.label);

  // Tooltip title fallback
  nodeEnter.append('title').text(d => d.label);

  const allNodes = nodeEnter.merge(nodeSelection);

  // Classify selected state
  allNodes.classed('node-active', d => d.id === activeNodeId);

  // Reset forces with new data
  simulation.nodes(currentNodes);
  simulation.force('link').links(currentEdges);

  if (isFrozen) {
    // Keep nodes frozen on updates
    currentNodes.forEach(n => { if (n.x && n.y) { n.fx = n.x; n.fy = n.y; } });
  } else {
    simulation.alphaTarget(0.2).restart();
    setTimeout(() => simulation.alphaTarget(0), 1000);
  }

  // Simulation tick update
  simulation.on('tick', () => {
    allLinks
      .attr('x1', d => d.source.x)
      .attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x)
      .attr('y2', d => d.target.y);

    allNodes.attr('transform', d => `translate(${d.x},${d.y})`);
  });
}

function dragStart(event, d) {
  if (isFrozen) return;
  if (!event.active) simulation.alphaTarget(0.3).restart();
  d.fx = d.x;
  d.fy = d.y;
}

function dragged(event, d) {
  if (isFrozen) {
    d.x = event.x;
    d.y = event.y;
    d.fx = event.x;
    d.fy = event.y;
    // Redraw frozen items immediately
    updateTickPositions();
  } else {
    d.fx = event.x;
    d.fy = event.y;
  }
}

function dragEnd(event, d) {
  if (isFrozen) return;
  if (!event.active) simulation.alphaTarget(0);
  d.fx = null;
  d.fy = null;
}

function updateTickPositions() {
  const mainGroup = svgSel.select('.main-zoom-group');
  mainGroup.selectAll('.links-group line')
    .attr('x1', d => d.source.x)
    .attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x)
    .attr('y2', d => d.target.y);
  mainGroup.selectAll('g.graph-node')
    .attr('transform', d => `translate(${d.x},${d.y})`);
}
