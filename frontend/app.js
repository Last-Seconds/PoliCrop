/* Field Shift v0 front end: map (choose a field) -> field report. Plain JS, no build step. */
(() => {
  "use strict";

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const state = {
    config: null, fieldId: null, field: null, corrections: {}, planLength: null, alternatives: 3,
    history: null, charts: {}, overlay: null, regionLayer: null, gridCell: null,
  };

  // ---------- helpers -----------------------------------------------------------------
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, attrs = {}, ...children) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c != null && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c)));
    return n;
  };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmtDate = (iso) => { const d = new Date(iso + "T00:00:00Z"); return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  const ts = (iso) => Date.parse(iso + "T00:00:00Z");
  const pct = (x) => (x == null ? "–" : `${Math.round(x * 100)}%`);
  const provTag = (title) => el("span", { class: "tag-prov", title: title || "Provisional: not decided yet" }, "provisional");

  async function api(path, opts = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
    let body = null;
    try { body = await res.json(); } catch { /* not JSON */ }
    if (!res.ok) {
      const msg = (body && (body.detail || body.error)) || `${res.status} ${res.statusText}`;
      const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      err.status = res.status;
      throw err;
    }
    return body;
  }

  function showError(container, title, err) {
    container.replaceChildren(el("div", { class: "error", role: "alert" },
      el("strong", {}, title), " ", err ? String(err.message || err) : "",
      el("div", { class: "small" }, "The rest of the report still works. Reload to try again.")));
  }

  function caveatList(caveats, key) {
    const items = (caveats || []).filter((c) => !key || c.applies_to.some((a) => a === key || a.startsWith(key + ":")));
    if (!items.length) return null;
    return el("ul", { class: "caveats" }, items.map((c) => el("li", {}, c.text)));
  }

  function tableToggle(columns, rows, label = "table") {
    const wrap = el("div", { class: "table-wrap", hidden: true },
      el("table", { class: "data-table" },
        el("thead", {}, el("tr", {}, columns.map((c) => el("th", {}, c)))),
        el("tbody", {}, rows.map((r) => el("tr", {}, r.map((v) => el("td", {}, v == null ? "–" : v)))))));
    const btn = el("button", { class: "table-toggle", type: "button", onclick: () => {
      wrap.hidden = !wrap.hidden; btn.textContent = wrap.hidden ? `Show ${label}` : `Hide ${label}`;
    } }, `Show ${label}`);
    return [btn, wrap];
  }

  function chartDefaults() {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = css("--text-2");
    Chart.defaults.borderColor = css("--grid");
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.plugins.tooltip.backgroundColor = css("--surface");
    Chart.defaults.plugins.tooltip.titleColor = css("--text");
    Chart.defaults.plugins.tooltip.bodyColor = css("--text-2");
    Chart.defaults.plugins.tooltip.borderColor = css("--border");
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.maintainAspectRatio = false;
  }

  function makeChart(id, container, config, cls = "") {
    if (state.charts[id]) state.charts[id].destroy();
    const canvas = el("canvas", { role: "img", "aria-label": config._label || id });
    container.append(el("div", { class: `chart-box ${cls}` }, canvas));
    state.charts[id] = new Chart(canvas, config);
    return state.charts[id];
  }

  // ---------- map view ------------------------------------------------------------------
  let map, drawnLayer;

  function initMap() {
    map = L.map("map", { zoomControl: true }).setView([46.9, -117.5], 9);
    window.fieldShiftMap = map; // handle for debugging and browser tests
    const esri = (state.config.attributions || []).find((a) => a.id === "esri_imagery");
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19, attribution: esri ? esri.attribution : "Esri World Imagery",
    }).addTo(map);
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
      maxZoom: 19, opacity: 0.8,
    }).addTo(map);
    state.regionLayer = L.geoJSON(state.config.region.geometry, {
      style: { color: "#ffd84d", weight: 3, fill: false, dashArray: "6 4" }, interactive: false,
    }).addTo(map);
    map.fitBounds(state.regionLayer.getBounds(), { padding: [10, 10] });

    map.pm.setGlobalOptions({ allowSelfIntersection: false, templineStyle: { color: "#4cf" }, hintlineStyle: { color: "#4cf", dashArray: "5 5" } });
    map.on("pm:create", (e) => {
      if (drawnLayer) map.removeLayer(drawnLayer);
      drawnLayer = e.layer;
      drawnLayer.setStyle({ color: "#4cf", weight: 3 });
      submitField(drawnLayer.toGeoJSON().geometry);
    });
    $("#btn-draw").addEventListener("click", () => {
      $("#field-error").hidden = true;
      map.pm.enableDraw("Polygon", { snappable: false, finishOn: null });
    });
    $("#chk-overlay").addEventListener("change", toggleOverlay);
  }

  async function toggleOverlay(e) {
    const on = e.target.checked;
    const legendBox = $("#overlay-legend");
    if (!on) {
      if (state.overlay) map.removeLayer(state.overlay);
      legendBox.hidden = true;
      return;
    }
    try {
      const { years } = await api("/api/overlay/years");
      const year = years[years.length - 1];
      $("#overlay-year").textContent = `(${year}, loading…)`;
      const meta = await api(`/api/overlay/${year}.json`);
      state.overlay = L.imageOverlay(`/api/overlay/${year}.png`, meta.bounds, { opacity: 0.75, interactive: false }).addTo(map);
      $("#overlay-year").textContent = `(${year})`;
      legendBox.replaceChildren(
        ...meta.legend.slice(0, 14).map((l) => el("div", {}, el("span", { class: "sw", style: `background:${l.color}` }), `${l.name} (${pct(l.share)})`)),
        el("div", { class: "muted", style: "grid-column:1/-1" }, `${meta.source}. A classification with errors.`));
      legendBox.hidden = false;
    } catch (err) {
      $("#overlay-year").textContent = "";
      legendBox.replaceChildren(el("div", { class: "error" }, `Crop map unavailable: ${err.message}`));
      legendBox.hidden = false;
    }
  }

  async function loadDemoFields() {
    const list = $("#demo-list");
    try {
      const fc = await api("/api/demo-fields");
      list.replaceChildren(...fc.features.map((f) => el("li", {},
        el("button", { class: "btn", type: "button", title: f.properties.note || "", onclick: () => {
          if (drawnLayer) map.removeLayer(drawnLayer);
          drawnLayer = L.geoJSON(f.geometry, { style: { color: "#4cf", weight: 3 } }).addTo(map);
          submitField(f.geometry);
        } }, f.properties.name))));
      if (!fc.features.length) list.replaceChildren(el("li", { class: "muted" }, "No demo fields configured."));
    } catch (err) {
      list.replaceChildren(el("li", { class: "error" }, `Could not load demo fields: ${err.message}`));
    }
  }

  async function submitField(geometry) {
    const errBox = $("#field-error");
    errBox.hidden = true;
    try {
      const info = await api("/api/field", { method: "POST", body: JSON.stringify({ field: { type: "polygon", geometry } }) });
      location.hash = `field=${info.field_id}`;
    } catch (err) {
      errBox.textContent = err.message;
      errBox.hidden = false;
      if (drawnLayer) { map.removeLayer(drawnLayer); drawnLayer = null; }
    }
  }

  // ---------- report view ----------------------------------------------------------------
  let miniMap, miniField;

  async function openReport(fieldId) {
    state.fieldId = fieldId;
    state.corrections = loadCorrections(fieldId);
    state.planLength = null;
    $("#view-map").hidden = true;
    $("#view-report").hidden = false;
    window.scrollTo(0, 0);
    let info;
    try {
      info = await api(`/api/field/${fieldId}`);
    } catch (err) {
      location.hash = "";
      return;
    }
    state.field = info;
    renderMiniMap(info);
    renderFacts(info);
    for (const id of ["history-body", "rain-month-body", "rain-year-body", "temp-body", "veg-body", "strategies-body"]) {
      document.getElementById(id).replaceChildren(el("div", { class: "loading" }, "Loading…"));
    }
    $("#strategy-controls").replaceChildren();
    loadHistoryAndStrategies();
    loadClimate();
    loadVegetation();
  }

  function renderMiniMap(info) {
    if (!miniMap) {
      miniMap = L.map("mini-map", { zoomControl: false, attributionControl: true });
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
        maxZoom: 19, attribution: "Esri World Imagery",
      }).addTo(miniMap);
    }
    if (miniField) miniMap.removeLayer(miniField);
    if (state.gridCell) { miniMap.removeLayer(state.gridCell); state.gridCell = null; }
    miniField = L.geoJSON(info.geometry, { style: { color: "#4cf", weight: 3, fillOpacity: 0.1 } }).addTo(miniMap);
    setTimeout(() => { miniMap.invalidateSize(); miniMap.fitBounds(miniField.getBounds(), { padding: [20, 20] }); }, 50);
  }

  function renderFacts(info) {
    $("#field-facts").replaceChildren(
      el("div", {}, el("span", { class: "k" }, "Area"), el("span", {}, `${info.area_ha.toLocaleString()} ha (${Math.round(info.area_ha * 2.471).toLocaleString()} acres)`)),
      el("div", {}, el("span", { class: "k" }, "Centre"), el("span", {}, `${info.centroid[1].toFixed(4)}, ${info.centroid[0].toFixed(4)}`)),
      el("div", { id: "fact-grid" }));
  }

  function loadCorrections(id) {
    try { return JSON.parse(localStorage.getItem(`fs-corr-${id}`) || "{}"); } catch { return {}; }
  }
  function saveCorrections() {
    try { localStorage.setItem(`fs-corr-${state.fieldId}`, JSON.stringify(state.corrections)); } catch { /* storage off */ }
  }
  const corrParam = () => encodeURIComponent(JSON.stringify(state.corrections));

  // ---------- crop history ---------------------------------------------------------------
  async function loadHistoryAndStrategies() {
    const body = $("#history-body");
    const fid = state.fieldId;
    try {
      const h = await api(`/api/field/${fid}/history?corrections=${corrParam()}`);
      if (fid !== state.fieldId) return;
      state.history = h;
      renderHistory(h);
    } catch (err) {
      showError(body, "Crop history could not be loaded.", err);
      showError($("#strategies-body"), "Strategies need the crop history.", err);
      return;
    }
    loadStrategies();
  }

  function renderHistory(h) {
    const body = $("#history-body");
    const thrParam = (state.config.settings || []).find((p) => p.key === "crop_history.min_share_confident");
    const strip = el("div", { class: "strip", role: "list" }, h.years.map((y) => {
      const yearCaveats = (h.caveats || []).filter((c) => c.applies_to.includes(`history:${y.year}`));
      const title = [
        `${y.year}: ${y.name}`,
        y.share != null ? `covers ${pct(y.share)} of the field` : null,
        y.corrected ? `corrected by you (map said: ${y.detected_name || "–"})` : null,
        y.runner_up && !y.corrected ? `next most common: ${y.runner_up} (${pct(y.runner_up_share)})` : null,
        y.source && !y.corrected ? `source: ${y.source}` : null,
        ...yearCaveats.map((c) => c.text),
        "Click to correct.",
      ].filter(Boolean).join("\n");
      const dark = isDark(y.color);
      return el("div", { role: "listitem" }, el("button", { class: "yr", type: "button", title, "aria-label": title,
        onclick: (e) => openCorrection(e.currentTarget, y) },
        el("div", { class: `blk ${y.uncertain && !y.corrected && y.code != null ? "uncertain" : ""}`, style: `background-color:${y.color};color:${dark ? "#fff" : "#111"}` },
          y.uncertain && !y.corrected && y.code != null ? el("span", { class: "q", "aria-hidden": "true" }, "?") : null,
          y.corrected ? el("span", { class: "c", title: "Corrected by you" }, "✎") : null,
          shortName(y.name)),
        el("div", { class: "lbl" }, el("span", { class: "y" }, y.year),
          el("span", { class: "s" }, y.corrected ? "yours" : (y.share != null ? pct(y.share) : "no data")))));
    }));
    const seen = new Map();
    h.years.forEach((y) => { if (y.code != null || y.corrected) seen.set(y.name, y.color); });
    const legend = el("div", { class: "legend-inline" },
      [...seen].map(([n, c]) => el("span", {}, el("span", { class: "sw", style: `background:${c}` }), n)),
      el("span", {}, el("span", { class: "sw", style: "background:repeating-linear-gradient(135deg,#bbb 0 3px,#fff 3px 6px);outline:1px dashed #555" }),
        `uncertain: main crop under ${pct(thrParam ? thrParam.value : 0.6)} of field`, " ", provTag("Uncertainty threshold (crop_history.min_share_confident) is provisional.")));
    const rot = h.rotation;
    const rotNote = el("p", { class: "rotation-note" },
      el("strong", {}, "Detected rotation: "),
      `${rot.crops.join(" → ")} (${rot.years[0]}–${rot.years[rot.years.length - 1]}). `, rot.explanation,
      rot.found ? null : provTag("Default plan length is provisional."));
    const corrCount = Object.keys(state.corrections).length;
    const corrNote = corrCount ? el("p", { class: "small" }, `${corrCount} year(s) corrected by you. `,
      el("button", { class: "table-toggle", type: "button", onclick: () => { state.corrections = {}; saveCorrections(); reloadHistory(); } }, "Undo all corrections")) : null;
    const [tbtn, twrap] = tableToggle(["Year", "Crop (map)", "Share of field", "Uncertain", "Corrected", "Source"],
      h.years.map((y) => [y.year, y.name, y.share != null ? pct(y.share) : null, y.uncertain && !y.corrected ? "yes" : "", y.corrected ? `yes (was ${y.detected_name})` : "", y.source]));
    body.replaceChildren(strip, legend, rotNote, corrNote || "", caveatList(h.caveats, "history") || "", tbtn, twrap);
  }

  function shortName(n) {
    return n.replace("Cover crop (species not chosen)", "Cover crop").replace("Fallow/Idle Cropland", "Fallow").replace("Grass/Pasture", "Grass");
  }
  function isDark(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return false;
    const v = parseInt(m[1], 16), r = v >> 16, g = (v >> 8) & 255, b = v & 255;
    return 0.299 * r + 0.587 * g + 0.114 * b < 120;
  }

  function openCorrection(anchor, y) {
    const pop = $("#popover");
    const opts = state.history.correction_options;
    const select = el("select", { "aria-label": `Crop in ${y.year}` },
      el("option", { value: "" }, `As detected (${y.detected_name || y.name})`),
      opts.map((o) => el("option", { value: o.value, selected: state.corrections[y.year] === o.value }, o.label)));
    const close = () => { pop.hidden = true; document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    pop.replaceChildren(
      el("h4", {}, `What grew here in ${y.year}?`),
      el("p", {}, y.share != null ? `The crop map shows ${y.detected_name || y.name} on ${pct(y.share)} of the field.` : "Corrected by you."),
      el("p", {}, "Harvest year: winter wheat sown in autumn counts for the following year."),
      select,
      el("div", { class: "row" },
        el("button", { class: "btn", type: "button", onclick: close }, "Cancel"),
        el("button", { class: "btn primary", type: "button", onclick: () => {
          if (select.value) state.corrections[y.year] = select.value; else delete state.corrections[y.year];
          saveCorrections(); close(); reloadHistory();
        } }, "Apply")));
    const r = anchor.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 276, r.left))}px`;
    pop.style.top = `${Math.min(window.innerHeight - 220, r.bottom + 6)}px`;
    pop.hidden = false;
    document.addEventListener("keydown", onKey);
    select.focus();
  }

  function reloadHistory() {
    $("#history-body").prepend(el("div", { class: "loading" }, "Updating…"));
    $("#strategies-body").replaceChildren(el("div", { class: "loading" }, "Updating strategies…"));
    loadHistoryAndStrategies();
  }

  document.addEventListener("click", (e) => {
    const pop = $("#popover");
    if (!pop.hidden && !pop.contains(e.target) && !e.target.closest(".yr")) pop.hidden = true;
  });

  // ---------- climate ---------------------------------------------------------------------
  async function loadClimate() {
    const fid = state.fieldId;
    try {
      const c = await api(`/api/field/${fid}/climate`);
      if (fid !== state.fieldId) return;
      renderClimate(c);
    } catch (err) {
      for (const id of ["#rain-month-body", "#rain-year-body", "#temp-body"]) showError($(id), "Weather data could not be loaded.", err);
    }
  }

  function renderClimate(c) {
    const rec = c.record;
    const span = `${rec.first_date.slice(0, 4)}–${rec.last_date.slice(0, 4)}`;
    if (c.grid_cell && miniMap) {
      const b = c.grid_cell.bounds;
      state.gridCell = L.rectangle(b, { color: "#ffd84d", weight: 2, fill: false, dashArray: "4 4" }).addTo(miniMap)
        .bindTooltip("NASA POWER weather grid cell: weather values are averages over this whole area");
      $("#fact-grid").replaceChildren(el("span", { class: "k" }, "Weather cell"), el("span", {}, `${c.grid_cell.size_km[0]} × ${c.grid_cell.size_km[1]} km (dashed yellow)`));
    }

    // Rainfall through the year
    const m = c.rainfall_monthly.months;
    const rmBody = $("#rain-month-body");
    rmBody.replaceChildren(el("div", { class: "key" },
      el("span", {}, el("i", { style: `background:${css("--series-rain")}` }), `Average, ${c.rainfall_monthly.first_year}–${c.rainfall_monthly.last_year}`),
      el("span", {}, el("i", { style: `background:${css("--series-rain-range")}` }), "Driest to wettest year")));
    makeChart("rainMonth", rmBody, {
      _label: "Average monthly rainfall with range across years",
      type: "bar",
      data: {
        labels: MONTHS,
        datasets: [
          { label: "Average", data: m.map((x) => x.mean_mm), backgroundColor: css("--series-rain"), borderRadius: 4, barPercentage: 0.45, grouped: false, order: 1 },
          { label: "Driest–wettest year", data: m.map((x) => (x.min_mm == null ? null : [x.min_mm, x.max_mm])), backgroundColor: css("--series-rain-range"), borderRadius: 4, barPercentage: 0.8, grouped: false, order: 2 },
        ],
      },
      options: {
        scales: { y: { title: { display: true, text: "mm per month" }, beginAtZero: true }, x: { grid: { display: false } } },
        plugins: { tooltip: { callbacks: {
          title: (it) => MONTHS[it[0].dataIndex],
          label: (it) => {
            const x = m[it.dataIndex];
            return it.datasetIndex === 0 ? `Average: ${x.mean_mm} mm (${x.years} years)` : `Driest: ${x.min_mm} mm (${x.min_year}) · Wettest: ${x.max_mm} mm (${x.max_year})`;
          },
        } } },
      },
    });
    const [b1, t1] = tableToggle(["Month", "Average (mm)", "Driest (mm)", "Wettest (mm)", "Years"], m.map((x) => [MONTHS[x.month - 1], x.mean_mm, x.min_mm != null ? `${x.min_mm} (${x.min_year})` : null, x.max_mm != null ? `${x.max_mm} (${x.max_year})` : null, x.years]));
    rmBody.append(caveatList(c.caveats, "rainfall_monthly") || "", b1, t1);

    // Rainfall over the years
    const yrs = c.rainfall_yearly.years.filter((y) => y.complete);
    const ryBody = $("#rain-year-body");
    ryBody.replaceChildren(el("p", { class: "small muted" }, `Crop years ${yrs[0]?.label} to ${yrs[yrs.length - 1]?.label}. Each bar is one crop year; no trend line or forecast is drawn.`));
    makeChart("rainYear", ryBody, {
      _label: "Total rainfall per crop year",
      type: "bar",
      data: { labels: yrs.map((y) => y.label), datasets: [{ label: "Total", data: yrs.map((y) => y.total_mm), backgroundColor: css("--series-rain"), borderRadius: 4, barPercentage: 0.75, categoryPercentage: 0.9 }] },
      options: {
        scales: { y: { title: { display: true, text: "mm per crop year" }, beginAtZero: true }, x: { grid: { display: false }, ticks: { maxRotation: 60, autoSkip: true } } },
        plugins: { tooltip: { callbacks: { label: (it) => `${it.raw} mm (Sep–Aug)` } } },
      },
    });
    const [b2, t2] = tableToggle(["Crop year", "Total (mm)"], c.rainfall_yearly.years.map((y) => [y.label, y.complete ? y.total_mm : "incomplete"]));
    ryBody.append(caveatList(c.caveats, "rainfall_yearly") || "", b2, t2);

    // Temperature
    const t = c.temperature_monthly.months;
    const fr = c.frost_days.years.filter((y) => y.complete);
    const tBody = $("#temp-body");
    const left = el("div", {}, el("h3", {}, `Monthly average high and low (${span})`),
      el("div", { class: "key" },
        el("span", {}, el("i", { class: "line", style: `background:${css("--series-high")}` }), "Average daily high"),
        el("span", {}, el("i", { class: "line", style: `background:${css("--series-low")}` }), "Average daily low"),
        el("span", {}, el("i", { class: "dash" }), "0 °C")));
    const right = el("div", {}, el("h3", {}, "Frost days per crop year (low below 0 °C)"));
    tBody.replaceChildren(el("div", { class: "two-charts" }, left, right));
    makeChart("temp", left, {
      _label: "Monthly average daily high and low temperature",
      type: "line",
      data: { labels: MONTHS, datasets: [
        { label: "Average high", data: t.map((x) => x.mean_tmax_c), borderColor: css("--series-high"), backgroundColor: css("--series-high"), borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, tension: 0.3 },
        { label: "Average low", data: t.map((x) => x.mean_tmin_c), borderColor: css("--series-low"), backgroundColor: css("--series-low"), borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, tension: 0.3 },
      ] },
      options: {
        interaction: { mode: "index", intersect: false },
        scales: { y: { title: { display: true, text: "°C" } }, x: { grid: { display: false } } },
        plugins: { tooltip: { callbacks: { label: (it) => `${it.dataset.label}: ${it.raw} °C` } } },
      },
      plugins: [zeroLinePlugin()],
    }, "short");
    makeChart("frost", right, {
      _label: "Frost days per crop year",
      type: "bar",
      data: { labels: fr.map((y) => y.label), datasets: [{ label: "Frost days", data: fr.map((y) => y.frost_days), backgroundColor: css("--series-low"), borderRadius: 4, barPercentage: 0.75 }] },
      options: {
        scales: { y: { title: { display: true, text: "days" }, beginAtZero: true }, x: { grid: { display: false }, ticks: { maxRotation: 60 } } },
        plugins: { tooltip: { callbacks: { label: (it) => `${it.raw} frost days` } } },
      },
    }, "short");
    const [b3, t3] = tableToggle(["Month", "Avg high (°C)", "Avg low (°C)"], t.map((x) => [MONTHS[x.month - 1], x.mean_tmax_c, x.mean_tmin_c]), "temperature table");
    const [b4, t4] = tableToggle(["Crop year", "Frost days"], c.frost_days.years.map((y) => [y.label, y.complete ? y.frost_days : "incomplete"]), "frost-day table");
    tBody.append(caveatList(c.caveats.filter((cv) => cv.applies_to.includes("temperature_monthly") || cv.applies_to.includes("frost_days"))) || "", b3, t3, " ", b4, t4);
  }

  function zeroLinePlugin() {
    return { id: "zero", afterDatasetsDraw(chart) {
      const y = chart.scales.y; if (y.min > 0 || y.max < 0) return;
      const ctx = chart.ctx, py = y.getPixelForValue(0);
      ctx.save(); ctx.setLineDash([5, 4]); ctx.strokeStyle = css("--text-2"); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(chart.chartArea.left, py); ctx.lineTo(chart.chartArea.right, py); ctx.stroke(); ctx.restore();
    } };
  }

  // ---------- vegetation --------------------------------------------------------------------
  async function loadVegetation() {
    const body = $("#veg-body");
    const fid = state.fieldId;
    try {
      const { years } = await api(`/api/field/${fid}/vegetation/years`);
      let done = 0;
      const progress = el("div", { class: "loading" }, `Reading satellite images: 0 of ${years.length} years (first time for a new field can take a few minutes)…`);
      body.replaceChildren(progress);
      // Warm the cache year by year (newest first), at most 2 at a time.
      const queue = [...years].reverse();
      const worker = async () => {
        while (queue.length) {
          const y = queue.shift();
          try { await api(`/api/field/${fid}/vegetation/year/${y}`); } catch { /* reported by the summary */ }
          done += 1;
          if (fid === state.fieldId) progress.textContent = `Reading satellite images: ${done} of ${years.length} years…`;
        }
      };
      await Promise.all([worker(), worker()]);
      if (fid !== state.fieldId) return;
      const v = await api(`/api/field/${fid}/vegetation`);
      if (fid !== state.fieldId) return;
      renderVegetation(v);
    } catch (err) {
      showError(body, "Vegetation data could not be loaded.", err);
    }
  }

  function renderVegetation(v) {
    const body = $("#veg-body");
    const green = css("--series-ndvi");
    const points = [];
    v.segments.forEach((seg, i) => {
      if (i > 0) points.push({ x: ts(seg[0].date) - 1, y: null }); // break the line across gaps
      seg.forEach((o) => points.push({ x: ts(o.date), y: o.ndvi }));
    });
    const start = ts(v.period.start), end = ts(v.period.end);
    const cropBands = (state.history?.years || []).filter((y) => y.code != null || y.corrected).map((y) => ({
      from: ts(`${y.year - 1}-09-01`), to: ts(`${y.year}-08-31`), color: y.color, name: shortName(y.name), year: y.year,
    })).filter((b) => b.to > start && b.from < end);
    body.replaceChildren(el("div", { class: "key" },
      el("span", {}, el("i", { class: "line", style: `background:${green}` }), "NDVI (field average)"),
      el("span", {}, el("i", { style: `background:${css("--bare")}` }), "Bare period"),
      el("span", {}, el("i", { style: `background:${css("--gap")};outline:1px dashed ${css("--muted")}` }), "Gap: no usable image"),
      el("span", {}, el("i", { class: "dash" }), `Bare threshold ${v.threshold}`, " ", provTag("vegetation.bare_ndvi_threshold is provisional")),
      cropBands.length ? el("span", {}, "Top band: crop map (Sep–Aug, harvest year)") : null));
    makeChart("ndvi", body, {
      _label: "NDVI over time with bare periods and gaps",
      type: "line",
      data: { datasets: [{ label: "NDVI", data: points, borderColor: green, backgroundColor: green, borderWidth: 2, pointRadius: 2.5, pointHoverRadius: 6, spanGaps: false, tension: 0 }] },
      options: {
        parsing: false, normalized: true,
        layout: { padding: { top: cropBands.length ? 22 : 0 } },
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        scales: {
          x: { type: "linear", min: start, max: end, ticks: { stepSize: 365.25 * 864e5 / 2, callback: (val) => { const d = new Date(val); return d.getUTCMonth() < 2 ? d.getUTCFullYear() : MONTHS[d.getUTCMonth()]; } }, grid: { color: css("--grid") } },
          y: { min: -0.1, max: 1, title: { display: true, text: "NDVI (0 bare – 1 dense green)" } },
        },
        plugins: { tooltip: { callbacks: {
          title: (it) => fmtDate(new Date(it[0].raw.x).toISOString().slice(0, 10)),
          label: (it) => `NDVI ${it.raw.y.toFixed(2)}${it.raw.y < v.threshold ? " (below bare threshold)" : ""}`,
        } } },
      },
      plugins: [periodsPlugin(v, cropBands)],
    }, "tall");
    const yearTicks = el("div", { class: "small muted" }, `${v.counts.images_used} usable images out of ${v.counts.images_read} read, ${v.years[0]}–${v.years[v.years.length - 1]}. ` +
      `${v.bare_periods.length} bare periods, ${v.gaps.length} gaps longer than ${(state.config.settings.find((p) => p.key === "vegetation.max_gap_days") || {}).value} days.`);
    const [b1, t1] = tableToggle(["Bare period", "Days", "Images", "Mean NDVI"], v.bare_periods.map((p) => [`${fmtDate(p.start)} – ${fmtDate(p.end)}`, p.days, p.observations, p.mean_ndvi]));
    body.append(yearTicks, caveatList(v.caveats, "vegetation") || "", b1, t1);
  }

  function periodsPlugin(v, cropBands) {
    return { id: "periods", beforeDatasetsDraw(chart) {
      const { ctx, chartArea: a, scales: { x, y } } = chart;
      const px = (t) => Math.min(a.right, Math.max(a.left, x.getPixelForValue(t)));
      ctx.save();
      ctx.fillStyle = css("--gap");
      for (const g of v.gaps) ctx.fillRect(px(ts(g.start)), a.top, px(ts(g.end)) - px(ts(g.start)), a.bottom - a.top);
      ctx.fillStyle = css("--bare");
      for (const p of v.bare_periods) {
        const x0 = px(ts(p.start)), x1 = px(ts(p.end) + 864e5);
        ctx.fillRect(x0, a.top, Math.max(2, x1 - x0), a.bottom - a.top);
      }
      ctx.setLineDash([5, 4]); ctx.strokeStyle = css("--text-2"); ctx.lineWidth = 1;
      const ty = y.getPixelForValue(v.threshold);
      ctx.beginPath(); ctx.moveTo(a.left, ty); ctx.lineTo(a.right, ty); ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = "10px system-ui, sans-serif"; ctx.textBaseline = "middle";
      for (const b of cropBands) {
        const x0 = px(b.from), x1 = px(b.to);
        if (x1 - x0 < 2) continue;
        ctx.fillStyle = b.color; ctx.fillRect(x0 + 1, a.top - 18, x1 - x0 - 2, 14);
        ctx.fillStyle = isDark(b.color) ? "#fff" : "#111";
        const label = `${b.name} ${b.year}`;
        if (ctx.measureText(label).width < x1 - x0 - 6) ctx.fillText(label, x0 + 4, a.top - 11);
      }
      ctx.restore();
    } };
  }

  // ---------- strategies ----------------------------------------------------------------------
  async function loadStrategies() {
    const body = $("#strategies-body");
    const fid = state.fieldId;
    body.replaceChildren(el("div", { class: "loading" }, "Generating and filtering candidate rotations…"));
    const qs = new URLSearchParams({ corrections: JSON.stringify(state.corrections), alternatives: state.alternatives });
    if (state.planLength) qs.set("plan_length", state.planLength);
    try {
      const s = await api(`/api/field/${fid}/strategies?${qs}`);
      if (fid !== state.fieldId) return;
      renderStrategies(s);
    } catch (err) {
      showError(body, "Strategies could not be generated.", err);
    }
  }

  function renderStrategies(s) {
    const controls = $("#strategy-controls");
    const lenSel = el("select", { "aria-label": "Plan length", onchange: (e) => { state.planLength = +e.target.value; loadStrategies(); } },
      [2, 3, 4, 5, 6].map((n) => el("option", { value: n, selected: n === s.plan_length }, `${n} years${n === s.detected_period ? " (detected)" : ""}`)));
    const altSel = el("select", { "aria-label": "Number of alternatives", onchange: (e) => { state.alternatives = +e.target.value; loadStrategies(); } },
      [3, 4, 5].map((n) => el("option", { value: n, selected: n === state.alternatives }, n)));
    controls.replaceChildren(el("label", {}, "Plan length ", lenSel), el("label", {}, "Alternatives shown ", altSel));

    const g = s.generation;
    const failures = Object.entries(g.failures_by_rule).map(([k, n]) => `${n.toLocaleString()} broke “${k}”`).join(", ");
    const summary = el("div", { class: "gen-summary" },
      el("div", {}, el("strong", {}, `${g.candidates_generated.toLocaleString()} candidate rotations`), ` of ${s.plan_length} years were generated from the roles `,
        g.roles_used.map((r) => roleLabel(r)).join(", "), ` and the crops grown nearby; ${g.candidates_passed.toLocaleString()} passed the rules${failures ? ` (${failures})` : ""}.`,
        g.truncated ? ` Generation stopped at the limit of ${g.max_candidates.toLocaleString()}.` : ""),
      el("div", {}, el("strong", {}, "Crop pool: "), s.pool.crops.map((c) => c.share != null ? `${c.name} (${pct(c.share)})` : c.name).join(", "), ". ", s.pool.description, " ", provTag("Crop pool radius and minimum share are provisional.")),
      el("div", {}, g.selection));
    const roleKey = el("div", { class: "role-key" }, state.config.roles.map((r) => el("span", {}, el("i", { style: `background:${r.color}` }), r.label)), provTag("Crop roles are provisional."));
    const cards = el("div", { class: "strategies" }, [s.existing, ...s.alternatives].map((st) => strategyCard(st, s)));
    $("#strategies-body").replaceChildren(summary, roleKey, cards, caveatList(s.caveats) || "");
  }

  function roleLabel(id) { const r = state.config.roles.find((x) => x.id === id); return r ? r.label.toLowerCase() : id; }

  function strategyCard(st, s) {
    const isExisting = st.kind === "existing";
    const timeline = el("div", { class: "timeline", role: "list" }, st.steps.map((step) => el("div", { class: "step-row", role: "listitem",
      title: `${step.crop} — ${step.role_label}\n${fmtDate(step.start)} to ${fmtDate(step.end)}${step.window_provisional ? "\n(dates: provisional default crop year)" : ""}` },
      el("div", { class: "when" }, `Year ${step.position}`, el("br"), `${step.start.slice(0, 4)}–${step.end.slice(2, 4)}`),
      el("div", { class: "what", style: `background:${step.role_color};color:${isDark(step.role_color) ? "#fff" : "#111"}` },
        el("span", {}, step.crop), el("small", {}, step.role_label)))));
    const diff = isExisting
      ? el("p", { class: "sum" }, `Detected from your field's crops in ${s.based_on_years.join(", ")}${s.assumed_years.length ? `, assumed to continue through ${s.assumed_years.join(" and ")}` : ""}${s.plan_length !== s.detected_period ? ", repeated to fill the plan" : ""}. Distance: `, el("b", {}, "0"), ".")
      : el("div", {},
        el("h4", {}, "How it differs"),
        el("p", { class: "sum" }, st.summary + "."),
        el("ul", {}, st.differences.map((d) => el("li", {}, d))),
        el("p", { class: "distance" }, "Distance from existing rotation: ", el("b", {}, st.distance), ` of ${st.max_distance} `, provTag("Distance weights (generation.distance_weights) are provisional: same crop 0, same role 0.5, other role 1 per year.")));
    const rules = el("div", {}, el("h4", {}, isExisting ? "Rule check" : "Rules passed"),
      el("ul", { class: "rules-list" }, st.rules.map((r) => el("li", { class: r.passed ? "pass" : "fail", title: r.reason }, r.label, r.passed ? "" : `: ${r.reason}`, " ", r.provisional ? provTag("This rule is provisional.") : null))));
    const gaps = el("div", {}, el("h4", {}, "Not yet assessed"),
      el("div", { class: "chips" }, st.not_assessed.map((c) => el("span", { class: "chip", title: "No data or method for this criterion yet" }, c))));
    return el("article", { class: `strategy ${isExisting ? "existing" : ""}` },
      el("h3", {}, st.label), timeline, diff, rules, gaps,
      el("div", { class: "check-locally" }, el("strong", {}, "Check locally: "), s.check_locally));
  }

  // ---------- footer -------------------------------------------------------------------------------
  function renderFooter(cfg) {
    $("#attributions").replaceChildren(...cfg.attributions.map((a) => el("li", {},
      el("strong", {}, a.name), ` — ${a.provider}. ${a.used_for}. `, el("em", {}, a.attribution.replace("{years}", "").replace("{years}.", "")), " ",
      el("a", { href: a.url, target: "_blank", rel: "noopener" }, "source"), ` · ${a.licence}`)));
    $("#params").replaceChildren(...cfg.settings.filter((p) => p.provisional).map((p) => el("tr", {},
      el("td", {}, p.key), el("td", {}, typeof p.value === "object" ? JSON.stringify(p.value) : `${p.value}${p.unit ? " " + p.unit : ""}`), el("td", {}, p.description || ""))));
  }

  // ---------- routing ----------------------------------------------------------------------------------
  function route() {
    const m = /field=([a-z0-9]+)/i.exec(location.hash);
    if (m) {
      if (m[1] !== state.fieldId || $("#view-report").hidden) openReport(m[1]);
    } else {
      state.fieldId = null;
      $("#view-report").hidden = true;
      $("#view-map").hidden = false;
      setTimeout(() => map && map.invalidateSize(), 50);
    }
  }

  async function init() {
    chartDefaults();
    try {
      state.config = await api("/api/config");
    } catch (err) {
      document.body.prepend(el("div", { class: "error", style: "margin:16px" }, `The app could not start: ${err.message}`));
      return;
    }
    $("#region-name").textContent = state.config.region.name;
    renderFooter(state.config);
    initMap();
    loadDemoFields();
    $("#btn-back").addEventListener("click", () => { location.hash = ""; });
    window.addEventListener("hashchange", route);
    route();
  }

  init();
})();
