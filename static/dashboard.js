// ─── STATE ────────────────────────────────────────────────────────────────────
const state = {
  depots: {
    a: { id: 'depot_a', name: 'SKODA Pune',  lat: 18.7473319, lon: 73.8131906, marker: null },
    b: { id: 'depot_b', name: 'SKODA CSN',   lat: 19.8735693, lon: 75.4874530, marker: null },
  },
  stops: [],        // [{id,name,lat,lon,marker}]
  barriers: [],     // [{lat,lon,radius,circle}]
  routeLayers: [],  // leaflet layers
  pickMode: null,   // 'depot_a'|'depot_b'|'stop'|'barrier'
  analyticsOpen: false,
  routingMode: 'dual',   // 'dual' | 'single'
  singleDepot: 'a',      // 'a' | 'b' — active depot in single-source mode
};

// ─── MAP INIT ─────────────────────────────────────────────────────────────────
const map = L.map('map', { zoomControl: true }).setView([19.2, 74.0], 7);

L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
}).addTo(map);

// ─── ICON HELPERS ─────────────────────────────────────────────────────────────
function depotIcon(label, color) {
  return L.divIcon({
    className: '',
    html: `<div style="background:${color};border:2px solid #fff;border-radius:6px;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.5)">${label}</div>`,
    iconSize: [28, 28], iconAnchor: [14, 14],
  });
}

function stopIcon(num, color) {
  return L.divIcon({
    className: '',
    html: `<div style="background:${color};border:2px solid #fff;border-radius:50%;width:26px;height:26px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;box-shadow:0 2px 8px rgba(0,0,0,.35)">${num}</div>`,
    iconSize: [26, 26], iconAnchor: [13, 13],
  });
}

// ─── INITIAL DEPOT MARKERS ────────────────────────────────────────────────────
function placeDepotMarker(key) {
  const d = state.depots[key];
  if (d.marker) map.removeLayer(d.marker);
  const color = key === 'a' ? '#4f46e5' : '#7c3aed';
  d.marker = L.marker([d.lat, d.lon], { icon: depotIcon(key.toUpperCase(), color) })
    .addTo(map)
    .bindPopup(`<b>Depot ${key.toUpperCase()}</b><br>${d.name}`);
  document.getElementById(`depot-${key}-coords`).textContent = `${d.lat.toFixed(4)}, ${d.lon.toFixed(4)}`;
}

placeDepotMarker('a');
placeDepotMarker('b');

// ─── PICK MODE ────────────────────────────────────────────────────────────────
function startPickDepot(key) {
  setPickMode(`depot_${key}`);
  showBanner(`Click map to set Depot ${key.toUpperCase()} location`);
  document.getElementById(`set-depot-${key}`).classList.add('picking');
}

function startPickStop() {
  if (state.stops.length >= 9) { notify('Maximum 9 stops reached', 'error'); return; }
  setPickMode('stop');
  showBanner('Click map to add a delivery stop');
  document.getElementById('add-stop-btn').style.borderColor = '#6366f1';
  document.getElementById('add-stop-btn').style.color = '#a5b4fc';
}

function startPickBarrier() {
  setPickMode('barrier');
  showBanner('Click map to draw an exclusion zone');
  document.getElementById('barrier-btn').classList.add('picking');
}

function setPickMode(mode) {
  state.pickMode = mode;
  map.getContainer().style.cursor = 'crosshair';
}

function clearPickMode() {
  state.pickMode = null;
  map.getContainer().style.cursor = '';
  hideBanner();
  document.querySelectorAll('.depot-set-btn').forEach(b => b.classList.remove('picking'));
  document.getElementById('barrier-btn').classList.remove('picking');
  document.getElementById('add-stop-btn').style.borderColor = '';
  document.getElementById('add-stop-btn').style.color = '';
}

function showBanner(msg) {
  const b = document.getElementById('mode-banner');
  b.textContent = msg;
  b.style.display = 'block';
}
function hideBanner() {
  document.getElementById('mode-banner').style.display = 'none';
}

// ─── MAP CLICK ────────────────────────────────────────────────────────────────
map.on('click', function(e) {
  if (!state.pickMode) return;
  const { lat, lng: lon } = e.latlng;

  if (state.pickMode === 'depot_a' || state.pickMode === 'depot_b') {
    const key = state.pickMode.split('_')[1];
    state.depots[key].lat = lat;
    state.depots[key].lon = lon;
    placeDepotMarker(key);
    notify(`Depot ${key.toUpperCase()} placed`, 'success');
  } else if (state.pickMode === 'stop') {
    addStop(lat, lon);
  } else if (state.pickMode === 'barrier') {
    addBarrier(lat, lon);
  }
  clearPickMode();
});

// ─── STOPS ────────────────────────────────────────────────────────────────────
function addManualStop() {
  const latInput = document.getElementById('manual-lat');
  const lonInput = document.getElementById('manual-lon');
  const lat = parseFloat(latInput.value);
  const lon = parseFloat(lonInput.value);

  if (isNaN(lat) || isNaN(lon)) {
    notify('Please enter valid coordinates', 'error');
    return;
  }

  if (state.stops.length >= 9) {
    notify('Maximum 9 stops reached', 'error');
    return;
  }

  addStop(lat, lon);
  latInput.value = '';
  lonInput.value = '';
  map.setView([lat, lon], map.getZoom());
}

function addStop(lat, lon) {
  const idx = state.stops.length + 1;
  const id = `stop_${Date.now()}`;
  const name = `Stop ${idx}`;
  const marker = L.marker([lat, lon], { icon: stopIcon(idx, '#f59e0b') })
    .addTo(map)
    .bindPopup(`<b>${name}</b><br>${lat.toFixed(4)}, ${lon.toFixed(4)}`);
  const stop = { id, name, lat, lon, marker, assigned: null };
  state.stops.push(stop);
  renderStopList();
  notify(`${name} added`, 'success');
}

function removeStop(id) {
  const idx = state.stops.findIndex(s => s.id === id);
  if (idx === -1) return;
  if (state.stops[idx].marker) map.removeLayer(state.stops[idx].marker);
  state.stops.splice(idx, 1);
  refreshStopNumbers();
  renderStopList();
}

function refreshStopNumbers() {
  state.stops.forEach((s, i) => {
    const color = s.assigned === 'A' ? '#4f46e5' : s.assigned === 'B' ? '#7c3aed' : '#f59e0b';
    if (s.marker) s.marker.setIcon(stopIcon(i + 1, color));
  });
}

function renderStopList() {
  const list = document.getElementById('stop-list');
  document.getElementById('stop-count').textContent = `(${state.stops.length}/9)`;
  if (!state.stops.length) { list.innerHTML = '<div style="font-size:11px;color:#475569;text-align:center;padding:8px">No stops yet</div>'; return; }
  list.innerHTML = state.stops.map((s, i) => {
    const aColor = s.assigned === 'A' ? 'a' : s.assigned === 'B' ? 'b' : '';
    const badge = s.assigned ? `<span class="stop-assigned ${aColor}">${s.assigned}</span>` : '';
    return `<div class="stop-item" data-id="${s.id}">
      <div class="stop-num">${i + 1}</div>
      <div style="flex:1;min-width:0">
        <div class="stop-name">${s.name}</div>
        <div class="stop-coords">${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}</div>
      </div>
      ${badge}
      <button class="stop-del" onclick="removeStop('${s.id}')" title="Remove">✕</button>
    </div>`;
  }).join('');

  // SortableJS
  Sortable.create(list, {
    animation: 150,
    handle: '.stop-item',
    onEnd(evt) {
      const moved = state.stops.splice(evt.oldIndex, 1)[0];
      state.stops.splice(evt.newIndex, 0, moved);
      refreshStopNumbers();
      renderStopList();
    }
  });
}

// ─── BARRIERS ─────────────────────────────────────────────────────────────────
function addBarrier(lat, lon) {
  const radius = 5000;
  const circle = L.circle([lat, lon], {
    color: '#ef4444', fillColor: '#ef4444', fillOpacity: 0.2,
    radius, weight: 2, dashArray: '6',
  }).addTo(map).bindPopup('Exclusion Zone — click to remove');
  const barrier = { lat, lon, radius, circle };
  state.barriers.push(barrier);
  circle.on('click', () => removeBarrier(barrier));
  updateBarrierCount();
  notify('Exclusion zone added', 'success');
}

function removeBarrier(b) {
  map.removeLayer(b.circle);
  state.barriers.splice(state.barriers.indexOf(b), 1);
  updateBarrierCount();
}

function updateBarrierCount() {
  const el = document.getElementById('barrier-count');
  el.textContent = state.barriers.length ? `${state.barriers.length} exclusion zone(s) active` : 'No barriers';
}

// ─── PROFILE ──────────────────────────────────────────────────────────────────
const PROFILES = {
  truck:              { height: 4.0, weight: 20.0, length: 0, width: 0 },
  heavy_truck:        { height: 4.5, weight: 40.0, length: 0, width: 0 },
  hazmat_truck:       { height: 4.0, weight: 20.0, length: 0, width: 0 },
  canopy_truck:       { height: 3.5, weight: 15.0, length: 0, width: 0 },
  long_trailer_truck: { height: 4.75, weight: 44.0, length: 18.0, width: 2.6 },
};

function onProfileChange() {
  const p = document.getElementById('profile-select').value;
  const d = PROFILES[p] || PROFILES.truck;
  document.getElementById('height').value = d.height;
  document.getElementById('weight').value = d.weight;
  document.getElementById('length').value = d.length;
  document.getElementById('width').value = d.width;
}

// ─── ROUTING MODE ───────────────────────────────────────────────────────────────────
function setRoutingMode(mode) {
  state.routingMode = mode;

  // Toggle button active states
  document.getElementById('mode-dual').classList.toggle('active', mode === 'dual');
  document.getElementById('mode-single').classList.toggle('active', mode === 'single');

  // Show/hide single-source selector
  document.getElementById('single-source-row').style.display = mode === 'single' ? 'flex' : 'none';

  // Refresh active-source highlights on depot cards
  _updateActiveSourceHighlight();
}

function onSingleDepotChange() {
  state.singleDepot = document.getElementById('single-depot-select').value;
  _updateActiveSourceHighlight();
}

function _updateActiveSourceHighlight() {
  ['a', 'b'].forEach(key => {
    const card = document.getElementById(`depot-${key}-card`);
    if (!card) return;
    const isActive = state.routingMode === 'dual' || state.singleDepot === key;
    card.classList.toggle('active-source', state.routingMode === 'single' && state.singleDepot === key);

    // Badge inside the depot-header
    const existing = card.querySelector('.active-source-badge');
    if (existing) existing.remove();
    if (state.routingMode === 'single' && state.singleDepot === key) {
      const badge = document.createElement('span');
      badge.className = 'active-source-badge';
      badge.textContent = 'SOURCE';
      card.querySelector('.depot-header').appendChild(badge);
    }
  });
}

// ─── CLEAR ALL ───────────────────────────────────────────────────────────────────
function clearAll() {
  clearRouteLayers();
  state.stops.forEach(s => { if (s.marker) map.removeLayer(s.marker); });
  state.stops.length = 0;
  state.barriers.forEach(b => map.removeLayer(b.circle));
  state.barriers.length = 0;
  renderStopList();
  updateBarrierCount();
  resetAnalytics();


  // Collapse analytics drawer if open
  if (state.analyticsOpen) {
    state.analyticsOpen = false;
    document.getElementById('analytics-content').style.display = 'none';
    document.getElementById('legs-section').style.display = 'none';
    document.getElementById('analytics-toggle').classList.remove('open');
  }


  setStatus('Cleared');
}

function clearRouteLayers() {
  state.routeLayers.forEach(l => map.removeLayer(l));
  state.routeLayers.length = 0;
}

// ─── STATUS ───────────────────────────────────────────────────────────────────
function setStatus(msg, loading = false) {
  const el = document.getElementById('status-bar');
  el.innerHTML = loading ? `<span class="spinner"></span>${msg}` : msg;
}

// ─── NOTIFY ───────────────────────────────────────────────────────────────────
function notify(msg, type = 'info') {
  const container = document.getElementById('notif');
  const el = document.createElement('div');
  el.className = `notif-item ${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ─── ANALYTICS ───────────────────────────────────────────────────────────────
function toggleAnalytics() {
  state.analyticsOpen = !state.analyticsOpen;
  const content = document.getElementById('analytics-content');
  const legs = document.getElementById('legs-section');
  const toggle = document.getElementById('analytics-toggle');
  if (state.analyticsOpen) {
    content.style.display = 'grid';
    legs.style.display = document.getElementById('legs-tbody').children.length ? 'block' : 'none';
    toggle.classList.add('open');
  } else {
    content.style.display = 'none';
    legs.style.display = 'none';
    toggle.classList.remove('open');
  }
}

function updateAnalytics(analytics, allLegs) {
  document.getElementById('m-dist').textContent  = analytics.total_dist_km ?? '—';
  document.getElementById('m-time').textContent  = analytics.total_time_h  ?? '—';
  document.getElementById('m-fuel').textContent  = analytics.total_fuel_L  ?? '—';
  updateCO2(analytics.total_fuel_L);

  // Legs table
  const tbody = document.getElementById('legs-tbody');
  if (!tbody) return;
  tbody.innerHTML = allLegs.map(l => {
    return `<tr>
      <td>${l.from_name || l.from_id}</td>
      <td>${l.to_name || l.to_id}</td>
      <td>${l.metrics?.dist_km ?? '—'}</td>
      <td>${l.metrics?.time_h ?? '—'}</td>
      <td>${l.metrics?.fuel_L ?? '—'}</td>
    </tr>`;
  }).join('');

  if (!state.analyticsOpen) toggleAnalytics();
}

function resetAnalytics() {
  ['m-dist','m-time','m-fuel'].forEach(id => document.getElementById(id).textContent = '—');
  document.getElementById('legs-tbody').innerHTML = '';
  document.getElementById('legs-section').style.display = 'none';
  resetCO2();
}

// ─── CO₂ EMISSION WIDGET ────────────────────────────────────────────────────────────────
const CO2_KG_PER_LITRE = 2.68; // diesel emission factor

function updateCO2(fuelL) {
  const widget = document.getElementById('co2-widget');
  const valEl  = document.getElementById('co2-value');
  const unitEl = document.getElementById('co2-unit');
  const subEl  = document.getElementById('co2-sub');
  const barEl  = document.getElementById('co2-bar-fill');
  if (fuelL == null || isNaN(fuelL)) { resetCO2(); return; }
  const co2kg = fuelL * CO2_KG_PER_LITRE;
  if (co2kg >= 1000) {
    valEl.textContent  = (co2kg / 1000).toFixed(2);
    unitEl.textContent = 't CO₂';
  } else {
    valEl.textContent  = co2kg.toFixed(1);
    unitEl.textContent = 'kg CO₂';
  }
  subEl.textContent = `${fuelL.toFixed(1)} L diesel × 2.68 kg/L`;
  const pct = Math.min((co2kg / 500) * 100, 100);
  setTimeout(() => { barEl.style.width = pct + '%'; }, 80);
  widget.classList.add('active');
}

function resetCO2() {
  document.getElementById('co2-value').textContent  = '—';
  document.getElementById('co2-unit').textContent   = '';
  document.getElementById('co2-sub').textContent    = 'Run optimization to calculate';
  document.getElementById('co2-bar-fill').style.width = '0%';
  document.getElementById('co2-widget').classList.remove('active');
}



// ─── ROUTE RENDERING ──────────────────────────────────────────────────────────
const DEPOT_COLORS = { a: '#4f46e5', b: '#7c3aed' };
const LEG_COLORS = { valid_a: '#6366f1', valid_b: '#a855f7', invalid: '#ef4444' };

function renderRoutes(data) {
  clearRouteLayers();

  const allLegs = [];

  data.optimized_routes.forEach((route, ri) => {
    const depotKey = route.depot === 'depot_a' || route.depot === 'A' ? 'a' : 'b';
    const validColor = depotKey === 'a' ? '#22c55e' : '#a855f7';

    route.legs.forEach((leg, li) => {
      if (!leg.geometry || !leg.geometry.length) return;
      const latlngs = leg.geometry.map(p => [p[1], p[0]]); // GeoJSON [lon,lat] → Leaflet [lat,lon]
      const color = leg.valid ? validColor : '#ef4444';
      const weight = leg.valid ? (li === 0 ? 6 : 5) : 4;
      const opacity = leg.valid ? 0.85 : 0.55;

      const poly = L.polyline(latlngs, { color, weight, opacity })
        .addTo(map)
        .bindPopup(`<b>${leg.from_name} → ${leg.to_name}</b><br>
          ${leg.rerouted ? '🔄 <b>Auto-rerouted</b> (barrier avoided)<br>' : ''}
          ${leg.valid ? '✓ Valid' : '✗ ' + (leg.reason || 'Rejected')}<br>
          ${leg.metrics?.dist_km ?? '?'} km | ${leg.metrics?.time_h ?? '?'} h | ${leg.metrics?.fuel_L ?? '?'} L`);

      if (!leg.valid) poly.setStyle({ dashArray: '8 5' });
      state.routeLayers.push(poly);
      allLegs.push(leg);
    });
  });

  // Fit bounds
  if (state.routeLayers.length) {
    const group = L.featureGroup(state.routeLayers);
    map.fitBounds(group.getBounds().pad(0.1));
  }

  // Update assigned stop marker colors
  data.optimized_routes.forEach(route => {
    const depotKey = route.depot === 'depot_a' || route.depot === 'A' ? 'A' : 'B';
    route.stop_sequence.forEach(stopId => {
      const stop = state.stops.find(s => s.id === stopId);
      if (stop) stop.assigned = depotKey;
    });
  });
  refreshStopNumbers();
  renderStopList();

  updateAnalytics(data.analytics, allLegs);
}

// ─── OPTIMIZE ─────────────────────────────────────────────────────────────────
async function runOptimization() {
  if (state.stops.length === 0) { notify('Add at least one delivery stop', 'error'); return; }

  const btn = document.getElementById('optimize-btn');
  btn.disabled = true;
  btn.textContent = 'Optimizing…';
  setStatus('Building cost matrix…', true);

    const fuelPrice      = parseFloat(document.getElementById('c-fuel-price').value);
    const avgSpeed       = parseFloat(document.getElementById('c-avg-speed').value);
    const costPerKm      = parseFloat(document.getElementById('c-cost-per-km').value);
    const fuelEfficiency = parseFloat(document.getElementById('c-fuel-efficiency').value) || 3.5; // km/L

    // Derive backend cost_weights from real-world params:
    //   distance weight   = cost_per_km (₹ per km, covers tolls/driver/depreciation)
    //   fuel weight       = fuel_price (₹ per litre consumed)
    //   time weight       = fuel_price × idling_L_per_h (2 L/h) — monetary cost of idle time
    //   fuel_l_per_km     = 1 / fuelEfficiency  — vehicle-specific consumption rate
    const costWeights = {
      distance:     costPerKm,
      fuel:         fuelPrice,
      time:         fuelPrice * 2.0,   // ~2 L/h idling overhead × ₹/L
      fuel_l_per_km: 1.0 / fuelEfficiency,  // e.g. 3.5 km/L → 0.286 L/km
    };

    // Build depots array based on routing mode
    let depotsPayload;
    if (state.routingMode === 'single') {
      const d = state.depots[state.singleDepot];
      depotsPayload = [{ id: d.id, name: d.name, lat: d.lat, lon: d.lon }];
    } else {
      depotsPayload = [
        { id: 'depot_a', name: state.depots.a.name, lat: state.depots.a.lat, lon: state.depots.a.lon },
        { id: 'depot_b', name: state.depots.b.name, lat: state.depots.b.lat, lon: state.depots.b.lon },
      ];
    }

    const payload = {
      depots: depotsPayload,
      stops: state.stops.map(s => ({ id: s.id, name: s.name, lat: s.lat, lon: s.lon })),
      vehicle_profile: {
        profile: document.getElementById('profile-select').value,
        height:  parseFloat(document.getElementById('height').value),
        weight:  parseFloat(document.getElementById('weight').value),
        length:  parseFloat(document.getElementById('length').value),
        width:   parseFloat(document.getElementById('width').value),
      },
      barriers: state.barriers.map(b => ({ lat: b.lat, lon: b.lon, radius: b.radius })),
      cost_weights: costWeights,
    };

  try {
    const res = await fetch('/api/multi-route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (data.error) {
      notify(`Error: ${data.error}`, 'error');
      setStatus('Optimization failed');
    } else {
      renderRoutes(data);
      const a = data.analytics;
      setStatus(`✓ Optimized — ${a.total_stops} stops | ${a.total_dist_km} km | ${a.infeasible_legs} rejected`);
      if (a.infeasible_legs > 0) notify(`${a.infeasible_legs} leg(s) rejected by RCSP`, 'error');
      if (data.unserviceable?.length) notify(`${data.unserviceable.length} unserviceable stop(s)`, 'error');
      notify(`Routes optimized: ${a.total_dist_km} km, ${a.total_fuel_L} L`, 'success');
    }
  } catch (err) {
    notify(`Request failed: ${err}`, 'error');
    setStatus('Error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Optimize Routes';
  }
}

// ─── GH HEALTH CHECK ─────────────────────────────────────────────────────────
async function checkGH() {
  try {
    const res = await fetch('http://localhost:8989/info');
    if (res.ok) {
      const d = await res.json();
      const profiles = (d.profiles || []).map(p => p.name).join(', ');
      document.getElementById('gh-status').textContent = 'GraphHopper ✓';
      document.getElementById('gh-status').style.color = '#16a34a';
    }
  } catch {
    document.getElementById('gh-status').textContent = 'GraphHopper ✗ Offline';
    document.getElementById('gh-status').style.color = '#dc2626';
  }
}

checkGH();
renderStopList();
