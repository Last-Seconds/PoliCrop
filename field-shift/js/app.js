/* Field Shift - Palouse front-end (DEMO). Everything numeric here is a placeholder. */
(function () {
  'use strict';
  const E = window.Engine, I = window.I18N;
  let lang = 'tr';
  const t = (k, vars) => {
    let s = (I[lang] && I[lang][k] !== undefined) ? I[lang][k] : (I.tr[k] !== undefined ? I.tr[k] : k);
    if (vars) Object.keys(vars).forEach((v) => { s = s.replace('{' + v + '}', vars[v]); });
    return s;
  };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (id) => document.getElementById(id);
  const clamp01 = (x) => Math.max(0, Math.min(1, x));

  const PRESETS = [
    { k: 'presetCook', lat: 46.78, lon: -117.09 },
    { k: 'presetMoscow', lat: 46.76, lon: -116.97 },
    { k: 'presetColfax', lat: 46.86, lon: -117.33 }
  ];
  const SLIDERS = [['water', 'pWater'], ['income', 'pIncome'], ['soil', 'pSoil'], ['erosion', 'pErosion'], ['risk', 'pRisk']];
  const LAYERS = [['erosion', 'layerErosion'], ['ndvi', 'layerNdvi'], ['moisture', 'layerMoisture'], ['color', 'layerColor']];

  const state = {
    lat: PRESETS[0].lat, lon: PRESETS[0].lon,
    sliders: { water: 5, income: 5, soil: 5, erosion: 5, risk: 5 },
    drought: false, excluded: new Set(),
    current: ['winter_wheat', 'winter_wheat', 'spring_barley'],
    crops: JSON.parse(JSON.stringify(E.CROPS)),
    layer: 'erosion', month: 3, playing: false, tree: false, timer: null
  };
  const cropName = (id) => (state.crops[id] && (state.crops[id][lang] || state.crops[id].en || state.crops[id].tr)) || id;

  /* ---------------- MAP ---------------- */
  let map, gridGroup, treeGroup, outline;
  const N = 10, CELL_M = 60;

  function initMap() {
    map = L.map('map', { zoomControl: true }).setView([state.lat, state.lon], 12);
    const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18, attribution: 'Tiles © Esri' });
    const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' });
    const topo = L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', { maxZoom: 17, attribution: '© OpenTopoMap (CC-BY-SA)' });
    sat.addTo(map);
    L.control.layers({ 'Satellite': sat, 'Topo': topo, 'OSM': osm }, null, { position: 'topleft' }).addTo(map);
    gridGroup = L.layerGroup().addTo(map);
    treeGroup = L.layerGroup().addTo(map);
    map.on('click', (e) => { state.lat = e.latlng.lat; state.lon = e.latlng.lng; renderPresets(); renderMap(); renderCoords(); renderReport(); });
  }

  function hash(i, j, s) { const x = Math.sin(i * 127.1 + j * 311.7 + s * 74.7) * 43758.5453; return x - Math.floor(x); }
  function terrain(i, j) {
    const s = Math.abs(Math.round((state.lat + state.lon) * 1000)) % 97;
    const v = 0.5 + 0.35 * Math.sin(i * 0.55 + s) * Math.cos(j * 0.45 + s * 0.7) + 0.15 * (hash(i, j, s) - 0.5);
    return clamp01(v);
  }
  const MF_EROSION = [0.95, 1, 0.9, 0.7, 0.5, 0.4, 0.3, 0.3, 0.4, 0.5, 0.7, 0.9];
  const C_NDVI = [0.25, 0.25, 0.35, 0.5, 0.7, 0.8, 0.55, 0.2, 0.15, 0.2, 0.3, 0.3];
  const C_MOIST = [0.38, 0.4, 0.42, 0.38, 0.3, 0.22, 0.14, 0.1, 0.12, 0.2, 0.3, 0.36];
  const RAMPS = {
    erosion: ['#2f8f4e', '#e8d44d', '#c8461f'],
    ndvi: ['#c9b48a', '#9bc46b', '#1f7a2e'],
    moisture: ['#e3c98a', '#7fb8c9', '#1d5a8a'],
    color: ['#c9a36a', '#8a5a32', '#3d2414']
  };
  function hex(h) { return [1, 3, 5].map((k) => parseInt(h.substr(k, 2), 16)); }
  function rampColor(name, v) {
    const st = RAMPS[name].map(hex); v = clamp01(v);
    const seg = v < 0.5 ? 0 : 1; const f = v < 0.5 ? v * 2 : (v - 0.5) * 2;
    const a = st[seg], b = st[seg + 1];
    return 'rgb(' + [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f)).join(',') + ')';
  }
  function cellValue(layer, i, j, m) {
    const terr = terrain(i, j);
    if (layer === 'erosion') return clamp01(terr * MF_EROSION[m] * 1.15);
    if (layer === 'ndvi') return clamp01((C_NDVI[m] * (1 - 0.25 * terr) + 0.05) / 0.8);
    const moist = clamp01((C_MOIST[m] * (1 + 0.3 * (0.5 - terr))) / 0.5);
    if (layer === 'moisture') return moist;
    return clamp01(0.6 * (1 - 0.6 * terr) + 0.4 * moist - 0.1); // illustrative soil color
  }

  function renderMap() {
    gridGroup.clearLayers(); treeGroup.clearLayers();
    const dLat = CELL_M / 111320, dLon = CELL_M / (111320 * Math.cos(state.lat * Math.PI / 180));
    const lat0 = state.lat - (N / 2) * dLat, lon0 = state.lon - (N / 2) * dLon;
    for (let i = 0; i < N; i++) {
      for (let j = 0; j < N; j++) {
        const v = cellValue(state.layer, i, j, state.month);
        L.rectangle([[lat0 + i * dLat, lon0 + j * dLon], [lat0 + (i + 1) * dLat, lon0 + (j + 1) * dLon]],
          { stroke: false, fillColor: rampColor(state.layer, v), fillOpacity: 0.62, interactive: false }).addTo(gridGroup);
      }
    }
    L.rectangle([[lat0, lon0], [lat0 + N * dLat, lon0 + N * dLon]], { color: '#ffffff', weight: 2, fill: false, interactive: false }).addTo(gridGroup);
    if (state.tree) {
      const g = 25 / 111320, gl = 25 / (111320 * Math.cos(state.lat * Math.PI / 180));
      const st = { color: '#1f4a2b', weight: 1, dashArray: '4 3', fillColor: '#2f6b3f', fillOpacity: 0.7 };
      L.rectangle([[lat0 - g, lon0 - gl], [lat0, lon0 + N * dLon]], st).bindPopup(t('treePopup')).addTo(treeGroup);
      L.rectangle([[lat0, lon0 - gl], [lat0 + N * dLat, lon0]], st).bindPopup(t('treePopup')).addTo(treeGroup);
    }
    const key = state.lat.toFixed(5) + ',' + state.lon.toFixed(5);
    if (state.panKey !== key) { state.panKey = key; map.panTo([state.lat, state.lon], { animate: true }); }
    renderLegend();
  }
  function renderLegend() {
    const r = RAMPS[state.layer];
    const name = t(LAYERS.find((x) => x[0] === state.layer)[1]);
    $('legend').innerHTML = '<b>' + esc(name) + '</b><div class="bar" style="background:linear-gradient(90deg,' + r.join(',') + ')"></div>' +
      '<div class="ends"><span>' + t('legendLow') + '</span><span>' + t('legendHigh') + '</span></div>';
  }
  function renderLayerBtns() {
    $('layerBtns').innerHTML = LAYERS.map((l) => '<button data-layer="' + l[0] + '" class="' + (state.layer === l[0] ? 'on' : '') + '">' + t(l[1]) + '</button>').join('');
    $('layerBtns').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { state.layer = b.dataset.layer; renderLayerBtns(); renderMap(); }));
  }
  function renderMonth() { $('monthLabel').textContent = I[lang].months[state.month]; $('monthRange').value = state.month; }

  /* ---------------- CONTROLS ---------------- */
  function renderPresets() {
    $('presets').innerHTML = PRESETS.map((p, i) => {
      const on = Math.abs(state.lat - p.lat) < 1e-6 && Math.abs(state.lon - p.lon) < 1e-6;
      return '<button data-i="' + i + '" class="' + (on ? 'on' : '') + '">' + t(p.k) + '</button>';
    }).join('');
    $('presets').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
      const p = PRESETS[+b.dataset.i]; state.lat = p.lat; state.lon = p.lon; map.setView([p.lat, p.lon], 13);
      renderPresets(); renderMap(); renderCoords(); renderReport();
    }));
  }
  function renderCoords() { $('coords').textContent = t('lat') + ': ' + state.lat.toFixed(4) + ' · ' + t('lon') + ': ' + state.lon.toFixed(4); }
  function renderSliders() {
    $('sliders').innerHTML = SLIDERS.map((s) =>
      '<div class="slider-row"><label><span>' + t(s[1]) + '</span><b id="v_' + s[0] + '">' + state.sliders[s[0]] + '</b></label>' +
      '<input type="range" min="0" max="10" step="1" value="' + state.sliders[s[0]] + '" data-k="' + s[0] + '"></div>').join('');
    $('sliders').querySelectorAll('input').forEach((r) => r.addEventListener('input', () => {
      state.sliders[r.dataset.k] = +r.value; $('v_' + r.dataset.k).textContent = r.value; renderStrategies();
    }));
  }
  function renderConstraints() {
    $('constraints').innerHTML = Object.keys(state.crops).map((id) =>
      '<label><input type="checkbox" data-id="' + esc(id) + '" ' + (state.excluded.has(id) ? 'checked' : '') + '> ' + esc(cropName(id)) + '</label>').join('');
    $('constraints').querySelectorAll('input').forEach((c) => c.addEventListener('change', () => {
      if (c.checked) state.excluded.add(c.dataset.id); else state.excluded.delete(c.dataset.id);
      renderStrategies();
    }));
  }
  function cropOptions(sel) { return Object.keys(state.crops).map((id) => '<option value="' + esc(id) + '"' + (id === sel ? ' selected' : '') + '>' + esc(cropName(id)) + '</option>').join(''); }
  function renderCurrent() {
    $('currentSelects').innerHTML = state.current.map((c, i) => '<label>' + t('year') + ' ' + (i + 1) + '<select data-i="' + i + '">' + cropOptions(c) + '</select></label>').join('');
    $('currentSelects').querySelectorAll('select').forEach((s) => s.addEventListener('change', () => { state.current[+s.dataset.i] = s.value; renderStrategies(); }));
  }

  /* ---------------- STRATEGY CARDS ---------------- */
  function meter(label, val, color, low, high) {
    const band = (low !== undefined) ? '<div class="band" style="left:' + low + '%;width:' + Math.max(2, high - low) + '%"></div>' : '';
    return '<div class="meter"><div class="lbl"><span>' + label + '</span><b>' + Math.round(val) + '</b></div><div class="track"><div class="fill" style="width:' + val + '%;background:' + color + '"></div>' + band + '</div></div>';
  }
  function topPriorities() {
    if (state.drought) return [t('pWater'), lang === 'tr' ? 'Gıda üretimi' : 'Food output'];
    const arr = SLIDERS.map((s) => [s[1], state.sliders[s[0]]]).sort((a, b) => b[1] - a[1]);
    return [t(arr[0][0]), t(arr[1][0])];
  }
  function benefitsOf(r) {
    const out = [];
    if (r.hasLegume) out.push(t('benLegume'));
    if (r.seq.indexOf('winter_wheat') >= 0) out.push(t('benWinter'));
    if (r.kinds >= 3) out.push(t('benDiverse'));
    if (r.avg.water >= 65) out.push(t('benWater'));
    return out;
  }
  function risksOf(r) {
    const out = [];
    if (r.repeats > 0) out.push(t('riskRepeat'));
    if (r.seq.indexOf('dry_pea') >= 0 || r.seq.indexOf('lentil') >= 0) out.push(t('riskPea'));
    if (r.seq.indexOf('chickpea') >= 0) out.push(t('riskChick'));
    if (r.seq.indexOf('canola') >= 0) out.push(t('riskCanola'));
    out.push(t('riskGeneral'));
    return out;
  }
  function li(arr) { return '<ul>' + arr.map((x) => '<li>' + x + '</li>').join('') + '</ul>'; }
  function card(kind, r, whyText) {
    const tags = { cur: t('tagCurrent'), s1: t('tagS1'), s2: whyText.s2tag };
    const chips = r.seq.map((c, i) => '<span class="chip">' + (i + 1) + ' · ' + esc(cropName(c)) + '</span>').join('<span class="arrow">→</span>');
    const warn = (kind === 'cur' && r.seq.some((c) => state.excluded.has(c))) ? '<div class="warn">' + (lang === 'tr' ? 'Mevcut rotasyonda hariç tuttuğunuz bir bitki var.' : 'Your current rotation contains a crop you excluded.') + '</div>' : '';
    const ev = [t('evDemo'), t('evClimate'), t('evTerrain'), t('evSoil')];
    const gaps = [t('gapMarket'), t('gapField'), t('gapClimate')];
    const ben = benefitsOf(r);
    return '<div class="card ' + kind + '"><div class="tag">' + tags[kind] + '</div><div class="chips">' + chips + '</div>' + warn +
      meter(t('score'), r.score, 'var(--green)', r.low, r.high) +
      meter(t('riskIdx'), r.riskIndex, 'var(--red)') +
      '<div class="hint">' + t('range') + ': ' + Math.round(r.low) + '–' + Math.round(r.high) + ' (demo)</div>' +
      '<details open><summary>' + t('why') + '</summary><p>' + whyText.why + '</p></details>' +
      '<details><summary>' + t('evidence') + '</summary>' + li(ev) + '</details>' +
      '<details><summary>' + t('benefits') + '</summary>' + (ben.length ? li(ben) : '<p>–</p>') + '</details>' +
      '<details><summary>' + t('gaps') + '</summary>' + li(gaps) + '</details>' +
      '<details><summary>' + t('risks') + '</summary>' + li(risksOf(r)) + '</details></div>';
  }
  function renderStrategies() {
    const sug = E.suggest(state);
    const pr = topPriorities();
    let html = card('cur', sug.current, { why: t('whyCurrent') });
    if (sug.currentBest) html += '<div class="warn">' + t('currentBestMsg') + '</div>';
    if (!sug.s1 && !sug.s2) html += '<div class="warn">' + t('noSuggestion') + '</div>';
    if (sug.s1) html += card('s1', sug.s1, { why: t('whyTop', { a: pr[0], b: pr[1] }) });
    if (sug.s2) html += card('s2', sug.s2, { why: t(sug.label2 === 'soil' ? 'whySoil' : 'whyRes'), s2tag: t(sug.label2 === 'soil' ? 'tagS2Soil' : 'tagS2Res') });
    $('tab-strategies').innerHTML = html;
    renderWhatIf(true);
  }

  /* ---------------- WHAT IF ---------------- */
  let wi = ['winter_wheat', 'winter_wheat', 'winter_wheat'];
  function renderWhatIf(keepResult) {
    const pane = $('tab-whatif');
    const hadResult = !!(keepResult && $('wiResult') && $('wiResult').innerHTML);
    pane.innerHTML = '<p>' + t('whatIfIntro') + '</p><div class="wi-row">' +
      wi.map((c, i) => '<select data-i="' + i + '">' + cropOptions(c) + '</select>').join('') + '</div>' +
      '<button class="btn" id="wiGo">' + t('whatIfBtn') + '</button> <button class="btn alt" id="wiWheat">' + t('whatIfWheat3') + '</button><div id="wiResult" style="margin-top:10px"></div>';
    pane.querySelectorAll('select').forEach((s) => s.addEventListener('change', () => { wi[+s.dataset.i] = s.value; }));
    $('wiGo').addEventListener('click', calcWhatIf);
    $('wiWheat').addEventListener('click', () => { wi = ['winter_wheat', 'winter_wheat', 'winter_wheat']; renderWhatIf(false); calcWhatIf(); });
    if (hadResult) calcWhatIf();
  }
  function calcWhatIf() {
    const w = E.weightsFrom(state.sliders, state.drought);
    const a = E.scoreRotation(wi, w, state.crops), c = E.scoreRotation(state.current, w, state.crops);
    const ds = a.score - c.score, dr = a.riskIndex - c.riskIndex;
    const cls = (v, goodWhenPositive) => ((v >= 0) === goodWhenPositive ? 'pos' : 'neg');
    const sign = (v) => (v >= 0 ? '+' : '') + v.toFixed(1);
    $('wiResult').innerHTML = '<div class="card s2"><div class="chips">' + wi.map((x, i) => '<span class="chip">' + (i + 1) + ' · ' + esc(cropName(x)) + '</span>').join('<span class="arrow">→</span>') + '</div>' +
      meter(t('score'), a.score, 'var(--green)', a.low, a.high) + meter(t('riskIdx'), a.riskIndex, 'var(--red)') +
      '<p class="hint">' + t('whatIfVs') + ':</p><p>' + t('deltaScore') + ': <span class="delta ' + cls(ds, true) + '">' + sign(ds) + '</span> · ' +
      t('deltaRisk') + ': <span class="delta ' + cls(dr, false) + '">' + sign(dr) + '</span></p>' +
      (a.repeats ? '<div class="warn">' + t('riskRepeat') + '</div>' : '') + '</div>';
  }

  /* ---------------- FIELD REPORT (sample) ---------------- */
  function renderReport() {
    const zones = [['zoneTop', 55, 70, 80], ['zoneMid', 75, 60, 55], ['zoneBot', 90, 45, 25]];
    $('tab-report').innerHTML = '<h2>' + t('reportTitle') + '</h2><p class="hint">' + t('reportHint') + '</p>' +
      zones.map((z) => '<div class="zone card"><h3>' + t(z[0]) + '</h3><div class="bars">' +
        bar(t('repYield'), z[1], 'var(--green)') + bar(t('repN'), z[2], 'var(--gold)') + bar(t('repEros'), z[3], 'var(--red)') + '</div></div>').join('') +
      '<p class="hint">' + t('repNote') + '</p>';
  }
  function bar(label, v, color) { return '<div class="bar-row"><span>' + label + '</span><div class="t"><div style="width:' + v + '%;background:' + color + '"></div></div><b>' + v + '</b></div>'; }

  /* ---------------- UPLOAD (CSV / Excel) ---------------- */
  function slug(s) { return String(s).trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || ('crop_' + Math.random().toString(36).slice(2, 6)); }
  function mergeRows(rows) {
    let n = 0;
    rows.forEach((r) => {
      const low = {}; Object.keys(r).forEach((k) => { low[String(k).trim().toLowerCase()] = r[k]; });
      const name = low.crop || low.bitki || low.name; if (!name) return;
      const num = (k) => { const v = parseFloat(String(low[k] === undefined ? '' : low[k]).replace(',', '.')); return isNaN(v) ? 50 : Math.max(0, Math.min(100, v)); };
      const lg = String(low.legume === undefined ? '' : low.legume).toLowerCase();
      state.crops[slug(name)] = { tr: String(name), en: String(name), water: num('water'), income: num('income'), soil: num('soil'), erosion: num('erosion'), risk: num('risk'), food: num('food'), legume: ['1', 'true', 'yes', 'evet'].indexOf(lg) >= 0 };
      n++;
    });
    return n;
  }
  function parseCsv(text) {
    const lines = text.split(/\r?\n/).filter((l) => l.trim());
    if (lines.length < 2) return [];
    const d = lines[0].indexOf(';') >= 0 ? ';' : ',';
    const head = lines[0].split(d).map((s) => s.trim());
    return lines.slice(1).map((l) => { const c = l.split(d); const o = {}; head.forEach((h, i) => { o[h] = (c[i] || '').trim(); }); return o; });
  }
  function onFile(f) {
    if (!f) return;
    const done = (rows) => {
      const n = mergeRows(rows);
      $('uploadMsg').textContent = n ? t('uploadOk', { n: n }) : t('uploadErr');
      if (n) { renderConstraints(); renderCurrent(); renderStrategies(); }
    };
    const reader = new FileReader();
    if (/\.csv$/i.test(f.name)) { reader.onload = () => done(parseCsv(String(reader.result))); reader.readAsText(f); }
    else if (window.XLSX) {
      reader.onload = () => { try { const wb = XLSX.read(reader.result, { type: 'array' }); done(XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]])); } catch (e) { $('uploadMsg').textContent = t('uploadErr'); } };
      reader.readAsArrayBuffer(f);
    } else { $('uploadMsg').textContent = t('uploadErr'); }
  }
  function downloadTemplate() {
    const head = 'crop,water,income,soil,erosion,risk,food,legume';
    const rows = Object.keys(E.CROPS).map((id) => { const c = E.CROPS[id]; return [c.en, c.water, c.income, c.soil, c.erosion, c.risk, c.food, c.legume ? 1 : 0].join(','); });
    const blob = new Blob([head + '\n' + rows.join('\n') + '\n'], { type: 'text/csv' });
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'crop_template.csv'; a.click();
  }

  /* ---------------- i18n + wiring ---------------- */
  function applyI18n() {
    document.documentElement.lang = lang;
    document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll('.lang button').forEach((b) => b.classList.toggle('on', b.dataset.lang === lang));
    renderPresets(); renderCoords(); renderSliders(); renderConstraints(); renderCurrent();
    renderLayerBtns(); renderMonth(); renderLegend(); renderStrategies(); renderWhatIf(false); renderReport();
  }
  function wire() {
    document.querySelectorAll('.lang button').forEach((b) => b.addEventListener('click', () => { lang = b.dataset.lang; applyI18n(); }));
    document.querySelectorAll('#tabs button').forEach((b) => b.addEventListener('click', () => {
      document.querySelectorAll('#tabs button').forEach((x) => x.classList.toggle('on', x === b));
      document.querySelectorAll('.tabpane').forEach((p) => p.classList.toggle('on', p.id === 'tab-' + b.dataset.tab));
    }));
    $('droughtMode').addEventListener('change', (e) => { state.drought = e.target.checked; renderStrategies(); });
    $('monthRange').addEventListener('input', (e) => { state.month = +e.target.value; renderMonth(); renderMap(); });
    $('treeToggle').addEventListener('change', (e) => { state.tree = e.target.checked; renderMap(); });
    $('playBtn').addEventListener('click', () => {
      state.playing = !state.playing; $('playBtn').textContent = state.playing ? '❚❚' : '▶';
      if (state.playing) { state.timer = setInterval(() => { state.month = (state.month + 1) % 12; renderMonth(); renderMap(); }, 800); }
      else { clearInterval(state.timer); }
    });
    $('fileInput').addEventListener('change', (e) => onFile(e.target.files[0]));
    $('tplBtn').addEventListener('click', downloadTemplate);
  }

  document.addEventListener('DOMContentLoaded', () => { initMap(); wire(); applyI18n(); renderMap(); setTimeout(() => map.invalidateSize(), 250); });
})();
