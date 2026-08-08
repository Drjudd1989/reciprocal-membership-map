/**
 * app.js — Reciprocal Memberships Map
 * Leaflet map initialization, data fetching, pin rendering, filter logic
 */

// ── Program configuration ────────────────────────────────────────────────────
const PROGRAMS = {
  ASTC: { color: '#4A9EFF', label: 'ASTC' },
  ACM:  { color: '#B66DFF', label: 'ACM'  },
  AZA:  { color: '#FF8C42', label: 'AZA'  },
  AHS:  { color: '#52D68A', label: 'AHS'  },
};

// ── State ────────────────────────────────────────────────────────────────────
let allVenues = [];
let markersByProgram = { ASTC: [], ACM: [], AZA: [], AHS: [] };
let activePrograms = new Set(['ASTC', 'ACM', 'AZA', 'AHS']);
let map;
let refreshAbortController = null;

// ── Map initialization ───────────────────────────────────────────────────────
function initMap() {
  map = L.map('map', {
    center: [38.5, -96.0],   // Continental US center
    zoom: 4,
    zoomControl: false,
    attributionControl: true,
  });

  // CartoDB Dark Matter tiles — free, no API key, dark background
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
  }).addTo(map);

  // Zoom control — bottom right
  L.control.zoom({ position: 'bottomright' }).addTo(map);
}

// ── Circle marker factory ────────────────────────────────────────────────────
function makeMarker(venue) {
  const color = PROGRAMS[venue.program]?.color || '#888';

  const marker = L.circleMarker([venue.latitude, venue.longitude], {
    radius: 7,
    fillColor: color,
    fillOpacity: 0.92,
    color: '#ffffff',
    weight: 1.8,
    opacity: 0.9,
  });

  marker.on('mouseover', function () {
    this.setStyle({ radius: 10, weight: 2.5, fillOpacity: 1 });
    this.bringToFront();
  });
  marker.on('mouseout', function () {
    this.setStyle({ radius: 7, weight: 1.8, fillOpacity: 0.92 });
  });

  marker.bindPopup(() => buildPopupHTML(venue), {
    maxWidth: 320,
    className: '',
    closeButton: true,
  });

  return marker;
}

// ── Popup HTML builder ───────────────────────────────────────────────────────
function buildPopupHTML(venue) {
  const program = venue.program.toUpperCase();
  const badgeClass = program.toLowerCase();

  const location = [venue.city, venue.state].filter(Boolean).join(', ');

  let individualHTML = '';
  if (venue.individual_memberships) {
    individualHTML = `
      <div class="popup-section-label">Individual Memberships</div>
      <div class="popup-memberships">${escHtml(venue.individual_memberships)}</div>`;
  }

  let groupHTML = '';
  if (venue.group_memberships) {
    groupHTML = `
      <div class="popup-section-label">Group Memberships</div>
      <div class="popup-memberships">${escHtml(venue.group_memberships)}</div>`;
  }

  let proofHTML = '';
  if (venue.proof_of_residence) {
    proofHTML = `
      <div class="popup-proof-warning">
        ⚠ Proof of Residence Required
      </div>`;
  }

  let actionsHTML = '';
  if (venue.source_pdf_url) {
    actionsHTML += `
      <a href="${escHtml(formatUrl(venue.source_pdf_url))}" target="_blank" rel="noopener noreferrer"
         class="popup-link primary" aria-label="Verify in source PDF">
        📄 Verify in PDF
      </a>`;
  }
  if (venue.website) {
    actionsHTML += `
      <a href="${escHtml(formatUrl(venue.website))}" target="_blank" rel="noopener noreferrer"
         class="popup-link secondary" aria-label="Visit venue website">
        🌐 Website
      </a>`;
  }

  const hasMemberships = individualHTML || groupHTML;
  const divider = hasMemberships ? '<div class="popup-divider"></div>' : '';

  return `
    <div class="popup-card">
      <div class="popup-program-badge ${badgeClass}">
        ${escHtml(program)}
      </div>
      <div class="popup-name">${escHtml(venue.name)}</div>
      ${location ? `<div class="popup-location">📍 ${escHtml(location)}</div>` : ''}
      ${divider}
      ${individualHTML}
      ${groupHTML}
      ${proofHTML}
      ${actionsHTML ? `<div class="popup-actions">${actionsHTML}</div>` : ''}
    </div>`;
}

function formatUrl(url) {
  if (!url) return '';
  const trimmed = url.trim();
  if (!/^https?:\/\//i.test(trimmed)) {
    return `https://${trimmed}`;
  }
  return trimmed;
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Data loading ─────────────────────────────────────────────────────────────
async function loadVenues() {
  setStatus('Loading venues…');
  try {
    let resp = await fetch('/api/locations', { credentials: 'include' });

    // Fallback to static JSON file if API endpoint is missing (e.g. GitHub Pages)
    if (!resp.ok) {
      resp = await fetch('./locations.json');
    }

    if (!resp.ok) {
      setStatus(`Error: ${resp.status} ${resp.statusText}`);
      return;
    }

    allVenues = await resp.json();
    renderAllMarkers();
    await updateCounts();
    setStatus(`${visibleCount()} venues shown`);

  } catch (err) {
    console.warn('API endpoint unavailable, falling back to static locations.json:', err);
    try {
      const resp = await fetch('./locations.json');
      if (resp.ok) {
        allVenues = await resp.json();
        renderAllMarkers();
        await updateCounts();
        setStatus(`${visibleCount()} venues shown`);
        return;
      }
    } catch (fallbackErr) {
      console.error('Static fallback failed:', fallbackErr);
    }
    setStatus('Failed to load data.');
  }
}

function renderAllMarkers() {
  // Clear existing markers
  Object.values(markersByProgram).forEach(markers =>
    markers.forEach(m => map.removeLayer(m))
  );
  markersByProgram = { ASTC: [], ACM: [], AZA: [], AHS: [] };

  for (const venue of allVenues) {
    if (!venue.latitude || !venue.longitude) continue;
    const program = venue.program;
    if (!markersByProgram[program]) markersByProgram[program] = [];

    const marker = makeMarker(venue);
    markersByProgram[program].push(marker);

    if (activePrograms.has(program)) {
      marker.addTo(map);
    }
  }
}

// ── Filter logic ─────────────────────────────────────────────────────────────
function toggleProgram(program) {
  if (activePrograms.has(program)) {
    activePrograms.delete(program);
    markersByProgram[program]?.forEach(m => map.removeLayer(m));
  } else {
    activePrograms.add(program);
    markersByProgram[program]?.forEach(m => m.addTo(map));
  }

  // Update button state
  const btn = document.getElementById(`btn-${program.toLowerCase()}`);
  if (btn) {
    btn.classList.toggle('active', activePrograms.has(program));
    btn.setAttribute('aria-pressed', String(activePrograms.has(program)));
  }

  setStatus(`${visibleCount()} venues shown`);
}

function visibleCount() {
  return [...activePrograms].reduce((sum, p) =>
    sum + (markersByProgram[p]?.length || 0), 0
  );
}

// ── Count badges ─────────────────────────────────────────────────────────────
async function updateCounts() {
  try {
    let resp = await fetch('/api/counts', { credentials: 'include' });
    if (!resp.ok) {
      resp = await fetch('./counts.json');
    }
    if (!resp.ok) return;
    const counts = await resp.json();

    for (const [program, count] of Object.entries(counts)) {
      const el = document.getElementById(`count-${program.toLowerCase()}`);
      if (el) el.textContent = count;
    }
  } catch (e) {
    try {
      const resp = await fetch('./counts.json');
      if (resp.ok) {
        const counts = await resp.json();
        for (const [program, count] of Object.entries(counts)) {
          const el = document.getElementById(`count-${program.toLowerCase()}`);
          if (el) el.textContent = count;
        }
      }
    } catch (fallbackErr) {
      console.warn('Could not fetch counts:', e);
    }
  }
}

// ── Status bar ────────────────────────────────────────────────────────────────
function setStatus(msg) {
  const bar = document.getElementById('status-bar');
  if (bar) bar.textContent = msg;
}

// ── Refresh flow ──────────────────────────────────────────────────────────────
function showRefreshOverlay() {
  document.getElementById('refresh-overlay')?.classList.remove('hidden');
  document.getElementById('refresh-btn')?.classList.add('spinning');
}

function hideRefreshOverlay() {
  document.getElementById('refresh-overlay')?.classList.add('hidden');
  document.getElementById('refresh-btn')?.classList.remove('spinning');
}

async function triggerRefresh() {
  if (!confirm('This will re-download the ASTC PDF and re-geocode all venues.\nIt may take several minutes. Continue?')) {
    return;
  }

  showRefreshOverlay();
  setStatus('Refreshing data…');
  refreshAbortController = new AbortController();

  try {
    const resp = await fetch('/api/admin/refresh?program=all', {
      method: 'POST',
      credentials: 'include',
      signal: refreshAbortController.signal,
    });

    if (resp.status === 404) {
      setStatus('Admin refresh unavailable on static hosting (run scripts locally).');
      return;
    }

    const result = await resp.json();

    if (resp.ok && result.status === 'complete') {
      setStatus('Refresh complete! Reloading venues…');
      await loadVenues();
    } else {
      setStatus('Refresh encountered errors — check console.');
      console.error('Refresh result:', result);
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      setStatus('Refresh cancelled.');
    } else {
      console.error('Refresh failed:', err);
      setStatus('Refresh failed.');
    }
  } finally {
    hideRefreshOverlay();
    refreshAbortController = null;
  }
}

// ── Event listeners ───────────────────────────────────────────────────────────
function bindEvents() {
  // Program filter buttons
  document.querySelectorAll('.filter-btn[data-program]').forEach(btn => {
    btn.addEventListener('click', () => {
      toggleProgram(btn.dataset.program);
    });
  });

  // Refresh button
  document.getElementById('refresh-btn')?.addEventListener('click', triggerRefresh);

  // Cancel refresh
  document.getElementById('refresh-cancel')?.addEventListener('click', () => {
    refreshAbortController?.abort();
    hideRefreshOverlay();
  });
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  try {
    if (typeof L === 'undefined') {
      throw new Error('Leaflet map engine (L) is not loaded.');
    }
    initMap();
    bindEvents();
    loadVenues();
  } catch (err) {
    console.error('Initialization failed:', err);
    setStatus(`Error: ${err.message}`);
  }
});
