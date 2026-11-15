/* Field Shift front end: choose a field -> the answer first, evidence one tap away. Plain JS, no build step. */
(() => {
  "use strict";

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const VERDICT = { 1: ["b", "▲", "Better"], 0: ["s", "●", "About the same"], "-1": ["w", "▼", "Worse"], null: ["n", "–", "Not assessed"] };
  const state = {
    config: null, fieldId: null, field: null, corrections: {}, inputs: {}, history: null, strategies: null,
    climate: null, soil: null, charts: {}, overlay: null, rendered: new Set(), vegLoading: false,
  };

  // ---------- helpers -----------------------------------------------------------------
  const $ = (sel) => document.querySelector(sel);
  const el = (tag, attrs = {}, ...children) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
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
  const inch = (x, d = 1) => (x == null ? "–" : `${Number(x).toFixed(d)} in`);
  const cropYear = (y) => `${y - 1}–${String(y).slice(2)}`;
  const store = {
    get(k, dflt) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : dflt; } catch { return dflt; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage off */ } },
  };

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
      el("div", { class: "small" }, "The rest of the page still works. Reload to try again.")));
  }

  function table(columns, rows, cls = "") {
    return el("div", { class: "table-wrap" }, el("table", { class: `data-table ${cls}` },
      el("thead", {}, el("tr", {}, columns.map((c) => el("th", { scope: "col" }, c)))),
      el("tbody", {}, rows.map((r) => el("tr", {}, r.map((v) => el("td", {}, v == null ? "–" : v)))))));
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
    Chart.defaults.responsive = true;
  }

  // Charts are only built in visible containers (a closed section has no width: that was the
  // "narrow strip" bug), so every chart is created when its section opens.
  function makeChart(id, container, config, cls = "") {
    if (state.charts[id]) state.charts[id].destroy();
    const canvas = el("canvas", { role: "img", "aria-label": config._label || id });
    const box = el("div", { class: `chart-box ${cls}` }, canvas);
    container.append(box);
    state.charts[id] = new Chart(canvas, config);
    return state.charts[id];
  }

  // ---------- tabs ---------------------------------------------------------------------
  function setTab(tab) {
    const about = tab === "about";
    $("#tab-field").setAttribute("aria-selected", String(!about));
    $("#tab-about").setAttribute("aria-selected", String(about));
    $("#page-field").hidden = about;
    $("#view-about").hidden = !about;
    if (about) renderAbout();
    else setTimeout(() => { if (map) map.invalidateSize(); }, 50);
    window.scrollTo(0, 0);
  }

  // ---------- map view ------------------------------------------------------------------
  let map, drawnLayer, pickLayer;

  async function pickAt(latlng) {
    const box = $("#pick-result"), errBox = $("#field-error");
    errBox.hidden = true;
    box.hidden = false;
    box.replaceChildren(el("div", { class: "loading" }, "Tracing the field at that spot…"));
    if (pickLayer) { map.removeLayer(pickLayer); pickLayer = null; }
    try {
      const r = await api("/api/pick", { method: "POST", body: JSON.stringify({ lon: latlng.lng, lat: latlng.lat }) });
      pickLayer = L.geoJSON(r.geometry, { style: { color: "#4cf", weight: 3, dashArray: "6 4", fillOpacity: 0.15 } }).addTo(map);
      map.fitBounds(pickLayer.getBounds(), { padding: [40, 40], maxZoom: 16 });
      const recent = r.sequence.slice(-4).map((x) => `${x.year} ${x.name.toLowerCase()}`).join(", ");
      box.replaceChildren(
        el("p", {}, el("strong", {}, `Is this your field? About ${r.acres.toLocaleString()} acres.`)),
        el("p", { class: "small" }, `The crop map shows here: ${recent}.`),
        el("p", { class: "small muted" }, r.note),
        el("div", { class: "row" },
          el("button", { class: "btn primary", type: "button", onclick: () => submitField(r.geometry) }, "Yes, use this field"),
          el("button", { class: "btn", type: "button", onclick: () => { box.hidden = true; if (pickLayer) { map.removeLayer(pickLayer); pickLayer = null; } } }, "No, tap again")));
      box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      box.hidden = true;
      errBox.textContent = err.message;
      errBox.hidden = false;
    }
  }

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
      $("#pick-result").hidden = true;
      if (pickLayer) { map.removeLayer(pickLayer); pickLayer = null; }
      map.pm.enableDraw("Polygon", { snappable: false, finishOn: null });
    });
    map.on("click", (e) => {
      if (map.pm.globalDrawModeEnabled()) return;  // drawing: clicks place corners
      pickAt(e.latlng);
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
        el("div", { class: "muted", style: "grid-column:1/-1" }, `USDA crop map ${year}. It has errors.`));
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
        } }, f.properties.name.replace("Demo field", "Example field")))));
      if (!fc.features.length) list.replaceChildren(el("li", { class: "muted" }, "No example fields configured."));
    } catch (err) {
      list.replaceChildren(el("li", { class: "error" }, `Could not load example fields: ${err.message}`));
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

  // ---------- field view ----------------------------------------------------------------
  async function openField(fieldId) {
    state.fieldId = fieldId;
    state.corrections = store.get(`fs-corr-${fieldId}`, {});
    state.inputs = store.get(`fs-inputs-${fieldId}`, {});
    state.history = state.strategies = state.climate = state.soil = state.veg = null;
    state.rendered = new Set();
    for (const id of Object.keys(state.charts)) { state.charts[id].destroy(); delete state.charts[id]; }
    $("#view-map").hidden = true;
    $("#view-field").hidden = false;
    $("#evidence").open = false;
    document.querySelectorAll("#evidence details.ev").forEach((d) => { d.open = false; });
    window.scrollTo(0, 0);
    let info;
    try {
      info = await api(`/api/field/${fieldId}`);
    } catch (err) {
      location.hash = "";
      return;
    }
    state.field = info;
    $("#field-title").textContent = `Your field: ${Math.round(info.area_ha * 2.4710538).toLocaleString()} acres`;
    $("#field-rotation").replaceChildren(el("span", { class: "muted" }, "Reading the crop map…"));
    $("#headline").replaceChildren();
    $("#field-notes").replaceChildren();
    $("#cards").replaceChildren(el("div", { class: "loading" }, "Reading your field: crop history, weather and soil. The first time can take a minute or two."));
    $("#more-cards").replaceChildren(); $("#more-cards").hidden = true; $("#btn-more").hidden = true;
    $("#ev-history").replaceChildren(el("div", { class: "loading" }, "Reading the crop map for each year…"));
    $("#ev-climate").replaceChildren(el("div", { class: "loading" }, "Loading weather…"));
    $("#ev-soil").replaceChildren(el("div", { class: "loading" }, "Reading the soil survey…"));
    $("#ev-veg").replaceChildren(el("p", { class: "muted" }, "Satellite images are read when you open this section; the first time takes a few minutes."));
    renderAdjustSummary();
    loadHistoryAndStrategies();
    loadClimate();
    loadSoil();
  }

  const inputsParam = () => encodeURIComponent(JSON.stringify({ ...state.inputs, corrections: state.corrections }));

  async function loadHistoryAndStrategies() {
    const fid = state.fieldId;
    try {
      const h = await api(`/api/field/${fid}/history?corrections=${encodeURIComponent(JSON.stringify(state.corrections))}`);
      if (fid !== state.fieldId) return;
      state.history = h;
      if ($("#ev-history-d").open) renderHistory(h); else state.rendered.delete("history");
    } catch (err) {
      showError($("#ev-history"), "The crop history could not be loaded.", err);
      showError($("#cards"), "Options need the crop history.", err);
      return;
    }
    loadStrategies();
  }

  async function loadStrategies() {
    const fid = state.fieldId;
    const cards = $("#cards");
    if (!state.strategies) cards.replaceChildren(el("div", { class: "loading" }, "Looking back over the last 15 years for every option…"));
    else cards.prepend(el("div", { class: "loading" }, "Updating…"));
    try {
      const s = await api(`/api/field/${fid}/strategies?inputs=${inputsParam()}`);
      if (fid !== state.fieldId) return;
      state.strategies = s;
      renderStrategies(s);
      if (state.history && sectionOpen("history")) renderHistory(state.history);
    } catch (err) {
      showError(cards, "Options could not be worked out.", err);
    }
  }

  // ---------- the answer -----------------------------------------------------------------
  function renderStrategies(s) {
    $("#field-rotation").replaceChildren(
      el("strong", {}, "Now: "), s.current_rotation_text, ". ",
      el("span", { class: "muted" }, "From the USDA crop map; "),
      el("button", { class: "linklike", type: "button", onclick: openHistory }, "fix it if wrong"), ".");
    $("#field-notes").replaceChildren(...(s.caveats || []).map((c) => el("li", {}, c.text)));
    $("#headline").replaceChildren(...s.headline.map((t) => el("p", {}, t)));
    $("#h-options").textContent = s.options.length === 3 ? "Your rotation and three options" :
      `Your rotation and ${s.options.length} option${s.options.length === 1 ? "" : "s"}`;
    const shownCautions = new Set();
    const cards = [card(s.current, s, true, shownCautions), ...s.options.map((o) => card(o, s, false, shownCautions))];
    $("#cards").replaceChildren(...cards);
    const more = $("#more-cards");
    more.replaceChildren(...s.more.map((o) => card(o, s, false, shownCautions)));
    more.hidden = true;
    const btn = $("#btn-more");
    btn.hidden = !s.more.length;
    btn.textContent = `Show ${s.more.length} more option${s.more.length === 1 ? "" : "s"}`;
    btn.onclick = () => { more.hidden = !more.hidden; btn.textContent = more.hidden ? `Show ${s.more.length} more options` : "Show fewer options"; };
    renderAdjustSummary();
  }

  function roleColor(roleId) { const r = state.config.roles.find((x) => x.id === roleId); return r ? r.color : "#999"; }

  function timeline(steps) {
    const rows = steps.map((st) => {
      const s0 = ts(st.slot_start), s1 = ts(st.slot_end) + 864e5;
      const span = s1 - s0;
      const a = Math.max(ts(st.start), s0), b = Math.min(ts(st.end) + 864e5, s1);
      const left = Math.max(0, (a - s0) / span * 100), width = Math.max(1.5, (b - a) / span * 100);
      const nonHarvest = !st.harvested;
      const when = st.sow_window ? `sown ${MONTHS[new Date(st.sow_window[0] + "T00:00:00Z").getUTCMonth()]}, harvested ${MONTHS[new Date(st.harvest_window[1] + "T00:00:00Z").getUTCMonth()]}` :
        (nonHarvest ? "nothing harvested" : "");
      const title = `${st.crop} (${st.role_label}), crop year ${cropYear(st.harvest_year)}` +
        (st.sow_window ? `\nUsually sown ${fmtDate(st.sow_window[0])} – ${fmtDate(st.sow_window[1])}\nUsually harvested ${fmtDate(st.harvest_window[0])} – ${fmtDate(st.harvest_window[1])}` : `\n${fmtDate(st.start)} – ${fmtDate(st.end)}`);
      return el("div", { class: "tl-row", role: "listitem", title },
        el("div", { class: "tl-year" }, cropYear(st.harvest_year)),
        el("div", { class: "tl-main" },
          el("div", { class: "tl-name" }, st.crop, " ", el("small", {}, when)),
          el("div", { class: "tl-track", "aria-hidden": "true" },
            el("div", { class: `tl-bar ${nonHarvest ? "fallow" : ""}`, style: `left:${left}%;width:${Math.min(width, 100 - left)}%;background-color:${st.role_color}` }))));
    });
    return el("div", { class: "tl" },
      el("div", { role: "list", class: "tl", "aria-label": "Crop years" }, rows),
      el("div", { class: "tl-axis", "aria-hidden": "true" }, el("span"), el("span", {}, el("span", {}, "Sep"), el("span", {}, "Jan"), el("span", {}, "May"), el("span", {}, "Aug"))));
  }

  function measureLine(l, isCurrent) {
    const [cls, sym, word] = VERDICT[l.verdict == null ? null : l.verdict];
    const badge = isCurrent ? null : el("span", { class: `verdict ${cls}` }, `${sym} ${l.held_by_assumed ? "About the same*" : word}`);
    const shortValue = isCurrent ? el("span", { class: "mvalue" }, l.value_text.replace(/ over the last .*$/, "").replace(/ in the \d+ driest.*$/, "")) : null;
    return el("details", { class: `mline ${isCurrent ? "cur" : ""}` },
      el("summary", {}, el("span", { class: "mlabel" }, l.label), badge || shortValue),
      el("div", { class: "mbody" },
        el("p", {}, l.value_text + "."),
        l.range_text ? el("p", {}, `Range: ${l.range_text}.`) : null,
        l.now_text ? el("p", { class: "now" }, `Now: ${l.now_text.charAt(0).toLowerCase()}${l.now_text.slice(1)}.`) : null,
        l.note ? el("p", {}, l.note) : null,
        l.held_by_assumed ? el("p", {}, "* The difference depends on an assumed figure, so it is called about the same. See Why and details.") : null));
  }

  function card(c, s, isCurrent, shownCautions) {
    const visible = [], hidden = [];
    for (const cv of c.cautions) {
      if (visible.length < 2 && !shownCautions.has(cv.key)) { visible.push(cv); shownCautions.add(cv.key); } else hidden.push(cv);
    }
    const cautionList = el("ul", { class: "cautions" }, visible.map((cv) => el("li", {}, cv.short)));
    const hiddenList = el("ul", { class: "cautions", hidden: true }, hidden.map((cv) => el("li", {}, cv.short)));
    const moreBtn = hidden.length ? el("button", { class: "linklike more-cautions", type: "button", onclick: (e) => {
      hiddenList.hidden = !hiddenList.hidden; e.target.textContent = hiddenList.hidden ? `${hidden.length} more caution${hidden.length > 1 ? "s" : ""}` : "Fewer cautions";
    } }, `${hidden.length} more caution${hidden.length > 1 ? "s" : ""}`) : null;
    return el("article", { class: `opt ${isCurrent ? "current" : ""}`, "aria-label": c.label },
      el("div", { class: "opt-head" }, el("h3", {}, c.label), c.band_label ? el("span", { class: "band" }, c.band_label) : null),
      el("p", { class: "sentence" }, c.summary),
      timeline(c.steps),
      el("div", { class: "mlines" }, c.lines.map((l) => measureLine(l, isCurrent))),
      el("div", { class: "facts-line" }, el("span", {}, c.notes.harvests_text), el("span", {}, c.notes.changes_text)),
      (visible.length || hidden.length) ? el("div", {}, cautionList, moreBtn, hiddenList) : null,
      details(c, isCurrent));
  }

  function list(items) { return items && items.length ? el("ul", {}, items.map((t) => el("li", {}, t))) : el("p", { class: "muted" }, "Nothing to add."); }

  function details(c, isCurrent) {
    const d = c.details;
    const inc = c.notes.income;
    const incomeLines = [];
    if (inc.rows.length) {
      incomeLines.push(`Return over total cost per acre (${inc.label}): ` + inc.rows.map((r) => `${r.crop.toLowerCase()} ${r.usd_ac >= 0 ? "+" : "−"}$${Math.abs(r.usd_ac)}`).join(", ") + ".");
      if (inc.average_usd_ac_yr != null) incomeLines.push(`Averaged over the rotation: ${inc.average_usd_ac_yr >= 0 ? "+" : "−"}$${Math.abs(inc.average_usd_ac_yr).toFixed(0)} per acre a year.`);
      else if (inc.missing.length) incomeLines.push(`No figure for ${inc.missing.join(", ").toLowerCase()}, so no average for the rotation.`);
      incomeLines.push(...inc.context);
    }
    const body = el("div", { class: "why-body" },
      el("section", {}, el("h4", {}, "Why this option"), list(d.why)),
      el("section", {}, el("h4", {}, "The evidence"), ...d.evidence.map((e) => el("div", {},
        el("h5", {}, e.label), list(e.lines),
        e.sources.length ? el("p", { class: "src" }, "Sources: ", ...e.sources.flatMap((x, i) => [i ? "; " : "",
          x.url ? el("a", { href: x.url, target: "_blank", rel: "noopener" }, x.citation.replace(/\*/g, "")) : x.citation.replace(/\*/g, "")])) : null))),
      el("section", {}, el("h4", {}, "What it may gain you"),
        isCurrent ? el("p", { class: "muted" }, "This is your current rotation.") : list(d.gains),
        incomeLines.length ? el("div", {}, el("h5", {}, "Income note (not scored)"), list(incomeLines)) : null,
        c.notes.nearby ? el("p", {}, c.notes.nearby.text) : null),
      el("section", {}, el("h4", {}, "What we don't know"), list(d.unknowns)),
      el("section", {}, el("h4", {}, "Check locally"), list(d.check)));
    return el("details", { class: "why" }, el("summary", {}, "Why and details"), body);
  }

  // ---------- adjust -------------------------------------------------------------------------
  const MEASURE_LABEL = () => Object.fromEntries(state.config.measures.map((m) => [m.id, m.label]));

  function nonDefaultInputs() {
    const i = state.inputs, out = [];
    if (i.priorities) out.push("priorities");
    if (i.dry_mode) out.push("dry region mode");
    if (i.tillage) out.push("tillage");
    if (i.ph != null && i.ph !== "") out.push("soil pH");
    if (i.exclude && i.exclude.length) out.push("crops ruled out");
    if (i.keep && i.keep.length) out.push("crops kept");
    if (i.plan_length) out.push("plan length");
    if (i.yields && Object.keys(i.yields).length) out.push("your yields");
    if (i.rain_pct) out.push(`rain ${i.rain_pct > 0 ? "+" : "−"}${Math.abs(i.rain_pct)}%`);
    if (i.temp_f) out.push(`+${i.temp_f} °F`);
    if (Object.keys(state.corrections).length) out.push("crop history fixed");
    return out;
  }

  function renderAdjustSummary() {
    const n = nonDefaultInputs();
    $("#adjust-summary").textContent = n.length ? `Your settings: ${n.join(", ")}` : "Using the defaults";
  }

  function item(labelText, control, def, what) {
    return el("div", { class: "item" }, el("div", { class: "lbl" }, labelText), control,
      def ? el("div", { class: "def" }, `Default: ${def}`) : null, what ? el("div", { class: "what" }, what) : null);
  }

  function buildAdjust(fromInputs) {
    const s = state.strategies, cfg = state.config, inp = structuredClone(fromInputs);
    const labels = MEASURE_LABEL();
    let prio = inp.priorities || cfg.measures.map((m) => m.id);
    const prioList = el("ol", { class: "prio" });
    const drawPrio = () => prioList.replaceChildren(...prio.map((m, i) => el("li", {},
      el("span", {}, `${i + 1}.`), el("span", {}, labels[m]),
      el("button", { class: "btn small-btn", type: "button", "aria-label": `Move ${labels[m]} up`, disabled: i === 0 || null, onclick: () => { [prio[i - 1], prio[i]] = [prio[i], prio[i - 1]]; drawPrio(); } }, "↑"),
      el("button", { class: "btn small-btn", type: "button", "aria-label": `Move ${labels[m]} down`, disabled: i === prio.length - 1 || null, onclick: () => { [prio[i + 1], prio[i]] = [prio[i], prio[i + 1]]; drawPrio(); } }, "↓"))));
    drawPrio();
    const dry = el("input", { type: "checkbox", id: "in-dry", checked: inp.dry_mode || null });

    const tillDefault = cfg.tillage.default;
    const till = el("div", { class: "radios", role: "radiogroup" }, cfg.tillage.options.map((o) => el("label", {},
      el("input", { type: "radio", name: "tillage", value: o.id, checked: (inp.tillage || tillDefault) === o.id || null }), " ", o.label)));
    const ph = el("input", { type: "number", id: "in-ph", min: 3, max: 10, step: 0.1, placeholder: "unknown", value: inp.ph ?? "", inputmode: "decimal" });

    const offered = (s ? s.pool.crops : []).filter((c) => cfg.offered_crops.includes(c.id));
    const allOffered = cfg.crops.filter((c) => cfg.offered_crops.includes(c.id));
    const ex = new Set(inp.exclude || []), kp = new Set(inp.keep || []);
    const cropRows = allOffered.map((c) => {
      const near = offered.some((o) => o.id === c.id);
      return el("tr", {},
        el("td", {}, c.name, near ? "" : el("span", { class: "muted small" }, " (not grown nearby)")),
        el("td", {}, el("input", { type: "checkbox", "data-ex": c.id, "aria-label": `Rule out ${c.name}`, checked: ex.has(c.id) || null })),
        el("td", {}, el("input", { type: "checkbox", "data-kp": c.id, "aria-label": `Keep ${c.name}`, checked: kp.has(c.id) || null })));
    });
    const cropGrid = el("div", { class: "table-wrap" }, el("table", { class: "crop-grid" },
      el("thead", {}, el("tr", {}, el("th", {}, "Crop"), el("th", {}, "Rule out"), el("th", {}, "Keep"))), el("tbody", {}, cropRows)));

    const curLen = s ? s.detected_period : 3;
    const plan = el("select", { id: "in-plan" }, el("option", { value: "" }, `Same as now (${curLen} years)`),
      [2, 3, 4, 5, 6].map((n) => el("option", { value: n, selected: inp.plan_length === n || null }, `${n} years`)));

    const yieldCrops = cfg.crops.filter((c) => c.yield_unit && cfg.offered_crops.includes(c.id) &&
      (!s || s.pool.crops.some((p) => p.id === c.id) || s.current.crop_ids.includes(c.id)));
    const unitWord = (u) => (u.name === "bu" ? "bu/acre" : u.name === "tons" ? "tons/acre" : "lb/acre");
    const yields = el("div", { class: "yield-grid" }, yieldCrops.map((c) => el("label", {}, c.name,
      el("input", { type: "number", min: 0, step: "any", "data-yield": c.id, inputmode: "decimal",
        placeholder: unitWord(c.yield_unit), value: (inp.yields || {})[c.id] ?? "" }))));

    const sc = cfg.scenario;
    const rainOut = el("output", {}), tempOut = el("output", {});
    const rain = el("input", { type: "range", id: "in-rain", min: sc.rain_pct.low, max: sc.rain_pct.high, step: 5, value: inp.rain_pct || 0 });
    const temp = el("input", { type: "range", id: "in-temp", min: sc.temp_f.low, max: sc.temp_f.high, step: 1, value: inp.temp_f || 0 });
    const upd = () => { rainOut.textContent = `${+rain.value > 0 ? "+" : +rain.value < 0 ? "−" : ""}${Math.abs(+rain.value)}%`; tempOut.textContent = `+${temp.value} °F`; };
    rain.addEventListener("input", upd); temp.addEventListener("input", upd); upd();

    const corrN = Object.keys(state.corrections).length;
    const body = $("#adjust-body");
    body.replaceChildren(
      el("fieldset", {}, el("legend", {}, "What matters most to you"),
        item("Order of importance", prioList, cfg.measures.map((m) => m.label).join(", then ").toLowerCase().replace(/^./, (x) => x.toUpperCase()),
          "Options are sorted by how they compare with your rotation on the first measure, then the second, and so on."),
        item(el("label", { for: "in-dry" }, dry, " Dry region mode"), null, "off",
          "Judges water on the 5 driest of the last 15 years, puts water first, and breaks ties in favour of more harvests: least water, most food.")),
      el("fieldset", {}, el("legend", {}, "Your field and how you farm it"),
        item("Tillage", till, cfg.tillage.options.find((o) => o.id === tillDefault).label, "Changes how much crop residue stays on the surface over winter."),
        item(el("label", { for: "in-ph" }, "Soil pH from a soil test"), ph, "unknown: acid soil is not checked",
          "Used to warn when a crop may struggle in acid soil. The soil survey's pH is not used: it describes the soil as surveyed, and measured values here have fallen below 5."),
        item("Crops to rule out or keep", cropGrid, "none", "Ruled-out crops never appear in options; every option includes the crops you keep."),
        item(el("label", { for: "in-plan" }, "Plan length"), plan, `the length of your current rotation (${curLen} years)`, null),
        item("Your typical yields", yields, "regional figures, or what this field's water supports for wheat and barley", "Changes the crop residue estimate and the pea nitrogen credit. Leave blank to use the default."),
        item("Crop history", el("div", {}, el("button", { class: "btn small-btn", type: "button", onclick: () => { $("#adjust").close(); openHistory(); } }, "Fix the crop history"),
          corrN ? el("span", { class: "small" }, ` ${corrN} year${corrN > 1 ? "s" : ""} fixed by you`) : null), "the USDA crop map, spring peas and canola assumed", null)),
      el("fieldset", {}, el("legend", {}, "What if the weather changes"),
        item(el("label", { for: "in-rain" }, "Rain from April to July ", rainOut), rain, "no change", "Looks back over the same years with spring and early-summer rain changed. Water needs stay as they were, so a drier setting shows more shortfalls."),
        item(el("label", { for: "in-temp" }, "Temperature ", tempOut), temp, "no change",
          "Raises every day's high and low. It changes how often chickpeas meet damaging heat and winter peas meet killing cold. It does not raise crop water demand, because the water budget has no evaporation term, so it understates the effect of warming.")));

    const collect = () => {
      const out = {};
      const dflt = cfg.measures.map((m) => m.id);
      if (prio.join() !== dflt.join()) out.priorities = [...prio];
      if (dry.checked) out.dry_mode = true;
      const t = body.querySelector("input[name=tillage]:checked");
      if (t && t.value !== tillDefault) out.tillage = t.value;
      if (ph.value !== "" && !Number.isNaN(+ph.value)) out.ph = +ph.value;
      const exl = [...body.querySelectorAll("[data-ex]:checked")].map((x) => x.dataset.ex);
      const kpl = [...body.querySelectorAll("[data-kp]:checked")].map((x) => x.dataset.kp).filter((k) => !exl.includes(k));
      if (exl.length) out.exclude = exl;
      if (kpl.length) out.keep = kpl;
      if (plan.value) out.plan_length = +plan.value;
      const ys = {};
      body.querySelectorAll("[data-yield]").forEach((x) => { if (x.value !== "" && +x.value > 0) ys[x.dataset.yield] = +x.value; });
      if (Object.keys(ys).length) out.yields = ys;
      if (+rain.value) out.rain_pct = +rain.value;
      if (+temp.value) out.temp_f = +temp.value;
      return out;
    };
    return collect;
  }

  function openAdjust() {
    const dlg = $("#adjust");
    let collect = buildAdjust(state.inputs);
    $("#adjust-reset").onclick = () => { collect = buildAdjust({}); };  // applied only on "Show results"
    // Act on the form's submit (it names the button pressed) rather than the dialog's close event,
    // which some browsers deliver late or not at all for background pages.
    $("#adjust-form").onsubmit = (e) => {
      if (!e.submitter || e.submitter.value !== "apply") return;
      state.inputs = collect();
      store.set(`fs-inputs-${state.fieldId}`, state.inputs);
      renderAdjustSummary();
      loadStrategies();
    };
    dlg.returnValue = "";
    dlg.showModal();
  }

  // ---------- evidence: crop history -----------------------------------------------------------
  function openHistory() {
    const ev = $("#evidence");
    ev.open = true;
    const d = $("#ev-history-d");
    d.open = true;
    d.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function shortName(n) {
    return n.replace("Fallow/Idle Cropland", "Fallow").replace("Grass/Pasture", "Grass");
  }
  function isDark(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return false;
    const v = parseInt(m[1], 16), r = v >> 16, g = (v >> 8) & 255, b = v & 255;
    return 0.299 * r + 0.587 * g + 0.114 * b < 120;
  }

  function renderHistory(h) {
    state.rendered.add("history");
    const body = $("#ev-history");
    const strip = el("div", { class: "strip", role: "list" }, h.years.map((y) => {
      const title = [
        `${y.year}: ${y.name}`,
        y.share != null ? `covers ${pct(y.share)} of the field` : null,
        y.corrected ? `fixed by you (map said: ${y.detected_name || "–"})` : null,
        y.runner_up && !y.corrected ? `next most common: ${y.runner_up} (${pct(y.runner_up_share)})` : null,
        "Tap to fix.",
      ].filter(Boolean).join("\n");
      const unsure = y.uncertain && !y.corrected && y.code != null;
      return el("div", { role: "listitem" }, el("button", { class: "yr", type: "button", title, "aria-label": title,
        onclick: (e) => openCorrection(e.currentTarget, y) },
        el("div", { class: `blk ${unsure ? "uncertain" : ""}`, style: `background-color:${y.color};color:${isDark(y.color) ? "#fff" : "#111"}` },
          unsure ? el("span", { class: "q", "aria-hidden": "true" }, "?") : null,
          y.corrected ? el("span", { class: "c" }, "✎") : null,
          shortName(y.name)),
        el("div", { class: "lbl" }, el("span", { class: "y" }, y.year),
          el("span", { class: "s" }, y.corrected ? "yours" : (y.share != null ? pct(y.share) : "no data")))));
    }));
    const seen = new Map();
    h.years.forEach((y) => { if (y.code != null || y.corrected) seen.set(shortName(y.name), y.color); });
    const legend = el("div", { class: "legend-inline" },
      [...seen].map(([n, c]) => el("span", {}, el("span", { class: "sw", style: `background:${c}` }), n)),
      el("span", {}, el("span", { class: "sw", style: "background:repeating-linear-gradient(135deg,#bbb 0 3px,#fff 3px 6px);outline:1px dashed #555" }),
        "? = unsure: the main crop covers less than 60% of the field"));
    const rot = h.rotation;
    const rotNote = el("p", {}, el("strong", {}, "Your rotation: "),
      `${rot.crops.join(", ")} (from ${rot.years[0]}–${rot.years[rot.years.length - 1]}). `,
      rot.found ? `The crop types repeat every ${rot.period} years.` : `No regular pattern was found, so ${rot.period} years are used.`);
    const corrCount = Object.keys(state.corrections).length;
    const corrNote = corrCount ? el("p", { class: "small" }, `${corrCount} year${corrCount > 1 ? "s" : ""} fixed by you. `,
      el("button", { class: "linklike", type: "button", onclick: () => { state.corrections = {}; store.set(`fs-corr-${state.fieldId}`, {}); reloadHistory(); } }, "Undo all fixes")) : null;
    const notes = [
      "Each year is the crop the USDA crop map shows on most of the field. The map is made from satellite images and has errors, especially between similar crops. Tap a year to fix it.",
      "Years are harvest years: winter wheat sown in autumn 2023 counts for 2024.",
      "The map cannot tell winter from spring peas or canola; spring is assumed unless you fix it.",
      ...h.caveats.filter((c) => c.id === "dry_beans" || c.id === "uncertain_years" || c.id === "history_failures").map((c) => c.text),
    ];
    const nb = state.strategies && state.strategies.nearby;
    const roleWord = (r) => (state.config.roles.find((x) => x.id === r) || { short: r }).short;
    const nearbyBox = nb && nb.top_patterns.length ? el("div", {},
      el("h3", {}, `What grows around you (within ${nb.radius_km} km, ${nb.years[0]}–${nb.years[nb.years.length - 1]})`),
      el("ul", {}, nb.top_patterns.filter((p) => p.roles.length > 1).map((p) => el("li", {},
        `${p.roles.map(roleWord).join(", then ")}: ${pct(p.share)} of nearby cropland`))),
      el("p", { class: "small muted" }, "Patterns of crop types from the crop map, allowing one year to differ because the map has errors. Shares overlap. Evidence that a pattern is workable here, not proof that it is good.")) : null;
    body.replaceChildren(el("p", { class: "small muted" }, "Tap a year to fix it."), strip, legend, rotNote, corrNote || "",
      el("ul", { class: "caveats" }, notes.map((t) => el("li", {}, t))), nearbyBox || "");
  }

  function openCorrection(anchor, y) {
    const pop = $("#popover");
    const opts = state.history.correction_options;
    const select = el("select", { "aria-label": `Crop in ${y.year}` },
      el("option", { value: "" }, `As the map shows (${y.detected_name || y.name})`),
      opts.map((o) => el("option", { value: o.value, selected: state.corrections[y.year] === o.value || null }, o.label)));
    const close = () => { pop.hidden = true; document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    pop.replaceChildren(
      el("h4", {}, `What grew here in ${y.year}?`),
      el("p", {}, y.share != null ? `The crop map shows ${y.detected_name || y.name} on ${pct(y.share)} of the field.` : "Fixed by you."),
      el("p", {}, "Harvest year: winter wheat sown in autumn counts for the following year."),
      select,
      el("div", { class: "row" },
        el("button", { class: "btn small-btn", type: "button", onclick: close }, "Cancel"),
        el("button", { class: "btn primary small-btn", type: "button", onclick: () => {
          if (select.value) state.corrections[y.year] = select.value; else delete state.corrections[y.year];
          store.set(`fs-corr-${state.fieldId}`, state.corrections); close(); reloadHistory();
        } }, "Apply")));
    const r = anchor.getBoundingClientRect();
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - 286, r.left))}px`;
    pop.style.top = `${Math.max(8, Math.min(window.innerHeight - 240, r.bottom + 6))}px`;
    pop.hidden = false;
    document.addEventListener("keydown", onKey);
    select.focus();
  }

  function reloadHistory() {
    $("#ev-history").prepend(el("div", { class: "loading" }, "Updating…"));
    loadHistoryAndStrategies();
    renderAdjustSummary();
  }

  document.addEventListener("click", (e) => {
    const pop = $("#popover");
    if (!pop.hidden && !pop.contains(e.target) && !e.target.closest(".yr")) pop.hidden = true;
  });

  // ---------- evidence: rain and heat ----------------------------------------------------------------
  async function loadClimate() {
    const fid = state.fieldId;
    try {
      const c = await api(`/api/field/${fid}/climate`);
      if (fid !== state.fieldId) return;
      state.climate = c;
      if (sectionOpen("climate")) renderClimate(c);
    } catch (err) {
      showError($("#ev-climate"), "Weather could not be loaded.", err);
    }
  }

  function sectionOpen(sec) {
    const d = document.querySelector(`#evidence details[data-sec="${sec}"]`);
    return $("#evidence").open && d && d.open;
  }

  function renderClimate(c) {
    state.rendered.add("climate");
    const body = $("#ev-climate");
    const hy = c.highlight_year;
    const p = c.periods.filter((x) => x.apr_jul_in != null);
    const trend = p.length >= 2 ? el("p", {},
      `Yearly rain and snow here has stayed about the same (${p.map((x) => inch(x.crop_year_in)).join(" → ")} a crop year), but April–July rain went `,
      `${p.map((x) => inch(x.apr_jul_in)).join(" → ")} and June–July days at or above ${c.hot_threshold_f} °F went `,
      `${p.map((x) => x.hot_days).join(" → ")} a year, over ${p.map((x) => `${x.first}–${x.last}`).join(", ")}. That is where the change shows.`) : null;
    body.replaceChildren(
      el("p", {}, `About ${inch(c.mean_crop_year_in)} of rain and snow (as water) falls in an average crop year (September to August), mostly in winter.`),
      trend || "",
      el("h3", {}, "Rain and snow by month"),
      el("div", { class: "key" }, el("span", {}, el("i", { style: `background:${css("--series-rain")}` }), `Average, ${c.monthly_years[0]}–${c.monthly_years[1]}`),
        el("span", {}, el("i", { style: `background:${css("--series-rain-range")}` }), "Driest to wettest year")));
    const m = c.monthly;
    makeChart("rainMonth", body, {
      _label: "Average monthly rain and snow with range across years",
      type: "bar",
      data: { labels: MONTHS, datasets: [
        { label: "Average", data: m.map((x) => x.mean_in), backgroundColor: css("--series-rain"), borderRadius: 4, barPercentage: 0.45, grouped: false, order: 1 },
        { label: "Driest–wettest year", data: m.map((x) => (x.min_in == null ? null : [x.min_in, x.max_in])), backgroundColor: css("--series-rain-range"), borderRadius: 4, barPercentage: 0.8, grouped: false, order: 2 },
      ] },
      options: {
        scales: { y: { title: { display: true, text: "inches per month" }, beginAtZero: true }, x: { grid: { display: false } } },
        plugins: { tooltip: { callbacks: {
          title: (it) => MONTHS[it[0].dataIndex],
          label: (it) => { const x = m[it.dataIndex]; return it.datasetIndex === 0 ? `Average: ${inch(x.mean_in, 2)}` : `Driest: ${inch(x.min_in, 2)} (${x.min_year}) · Wettest: ${inch(x.max_in, 2)} (${x.max_year})`; },
        } } },
      },
    });
    body.append(el("h3", {}, "Rain and snow in each crop year"),
      el("div", { class: "key" }, el("span", {}, el("i", { style: `background:${css("--series-rain")}` }), "One crop year (September to August)"),
        el("span", {}, el("i", { style: `background:${css("--series-hl")}` }), `${cropYear(hy)}: the driest and hottest year on record here`)));
    const y = c.yearly;
    makeChart("rainYear", body, {
      _label: "Rain and snow per crop year",
      type: "bar",
      data: { labels: y.map((r) => r.year), datasets: [{ label: "Total", data: y.map((r) => r.total_in),
        backgroundColor: y.map((r) => (r.year === hy ? css("--series-hl") : css("--series-rain"))), borderRadius: 3, barPercentage: 0.8, categoryPercentage: 0.9 }] },
      options: {
        scales: { y: { title: { display: true, text: "inches per crop year" }, beginAtZero: true }, x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } } },
        plugins: { tooltip: { callbacks: { title: (it) => `Crop year ${cropYear(y[it[0].dataIndex].year)}`, label: (it) => `${inch(it.raw)}${y[it.dataIndex].year === hy ? " (driest and hottest on record)" : ""}` } } },
      },
    });
    body.append(el("h3", {}, "Spring rain and summer heat, then and now"),
      table(["Period", "April–July rain", `June–July days ≥ ${c.hot_threshold_f} °F`, "Whole crop year"],
        p.map((x) => [`${x.first}–${x.last}`, inch(x.apr_jul_in), x.hot_days == null ? "–" : x.hot_days.toFixed(0), inch(x.crop_year_in)])),
      el("p", { class: "small muted" }, `At the Pullman weather station, April–July rain fell from 5.9 in (1982–1996) to 4.6 in (2012–2025), and June–July days at or above 90 °F rose from 7 to 13 a year, while yearly rain stayed flat.`),
      el("ul", { class: "caveats" }, c.caveats.map((cv) => el("li", {}, cv.text))));
    const stationBox = el("div", {}, el("div", { class: "loading" }, "Checking against the nearest weather station…"));
    body.append(el("h3", {}, "Checked against a weather station"), stationBox);
    api(`/api/field/${state.fieldId}/station`).then((st) => renderStation(stationBox, st))
      .catch((err) => stationBox.replaceChildren(el("p", { class: "muted" }, `The station check could not be run (${err.message}).`)));
    const droughtBox = el("div", {});
    body.append(droughtBox);
    regionContext().then((ctx) => {
      const d = ctx && ctx.drought;
      if (!d) return;
      droughtBox.replaceChildren(el("h3", {}, "Drought in the county"),
        el("p", {}, d.highlight_text || "", " ", d.text, " ", d.latest.text),
        el("p", { class: "small muted" }, `${d.note} More under About this area.`));
    }).catch(() => {});
  }

  function renderStation(box, st) {
    if (st.status !== "ok") { box.replaceChildren(el("p", {}, st.text)); return; }
    box.replaceChildren(el("p", {}, st.text),
      el("p", { class: "small muted" }, `Station average ${inch(st.station_mean_in)} a crop year, grid ${inch(st.grid_mean_in)}; `
        + `the two rise and fall together (correlation ${st.correlation.toFixed(2)}), typically ${inch(st.typical_difference_in)} apart in a single year. `
        + (st.caveat || "")));
  }

  let regionCtxPromise = null;
  function regionContext() {
    if (!regionCtxPromise) regionCtxPromise = api("/api/region/context").catch((e) => { regionCtxPromise = null; throw e; });
    return regionCtxPromise;
  }

  // ---------- evidence: greenness ---------------------------------------------------------------------
  async function loadVegetation() {
    if (state.vegLoading) return;
    state.vegLoading = true;
    const body = $("#ev-veg");
    const fid = state.fieldId;
    try {
      const { years } = await api(`/api/field/${fid}/vegetation/years`);
      let done = 0;
      const progress = el("div", { class: "loading" }, `Reading satellite images: 0 of ${years.length} years (the first time for a new field can take a few minutes)…`);
      body.replaceChildren(progress);
      const queue = [...years].reverse();
      const worker = async () => {
        while (queue.length) {
          const yy = queue.shift();
          try { await api(`/api/field/${fid}/vegetation/year/${yy}`); } catch { /* reported by the summary */ }
          done += 1;
          if (fid === state.fieldId) progress.textContent = `Reading satellite images: ${done} of ${years.length} years…`;
        }
      };
      await Promise.all([worker(), worker()]);
      if (fid !== state.fieldId) return;
      const v = await api(`/api/field/${fid}/vegetation`);
      if (fid !== state.fieldId) return;
      state.veg = v;
      renderVegetation(v);
    } catch (err) {
      showError(body, "Satellite images could not be read.", err);
    } finally {
      state.vegLoading = false;
    }
  }

  function bareSentence(v) {
    const bp = v.bare_periods;
    if (!bp.length) return "The satellite did not see long bare periods on this field.";
    const months = bp.map((p) => new Date(p.start + "T00:00:00Z").getUTCMonth());
    const ends = bp.map((p) => new Date(p.end + "T00:00:00Z").getUTCMonth());
    const mode = (a) => { const c = {}; a.forEach((x) => { c[x] = (c[x] || 0) + 1; }); return +Object.entries(c).sort((a1, b1) => b1[1] - a1[1])[0][0]; };
    const longest = bp.reduce((a, b) => (b.days > a.days ? b : a));
    return `Since ${v.years[0]} the satellite saw the field bare ${bp.length} times, most often starting in ${MONTHS[mode(months)]} and ending in ${MONTHS[mode(ends)]}; ` +
      `the longest stretch was ${longest.days} days (${fmtDate(longest.start)} to ${fmtDate(longest.end)}). Winter images are often missing because of cloud and snow.`;
  }

  function renderVegetation(v) {
    state.rendered.add("veg");
    const body = $("#ev-veg");
    const green = css("--series-ndvi");
    const points = [];
    v.segments.forEach((seg, i) => {
      if (i > 0) points.push({ x: ts(seg[0].date) - 1, y: null });
      seg.forEach((o) => points.push({ x: ts(o.date), y: o.ndvi }));
    });
    const start = ts(v.period.start), end = ts(v.period.end);
    const cropBands = (state.history?.years || []).filter((y) => y.code != null || y.corrected).map((y) => ({
      from: ts(`${y.year - 1}-09-01`), to: ts(`${y.year}-08-31`), color: y.color, name: shortName(y.name), year: y.year,
    })).filter((b) => b.to > start && b.from < end);
    body.replaceChildren(
      el("p", {}, bareSentence(v)),
      el("div", { class: "key" },
        el("span", {}, el("i", { class: "line", style: `background:${green}` }), "Greenness of the field from space"),
        el("span", {}, el("i", { style: `background:${css("--bare")}` }), "Bare: nothing growing"),
        el("span", {}, el("i", { style: `background:${css("--gap")};outline:1px dashed ${css("--muted")}` }), "No clear image"),
        cropBands.length ? el("span", {}, "Top band: the crop map's crop") : null));
    makeChart("ndvi", body, {
      _label: "Greenness over time with bare periods and gaps",
      type: "line",
      data: { datasets: [{ label: "Greenness", data: points, borderColor: green, backgroundColor: green, borderWidth: 2, pointRadius: 2, pointHoverRadius: 6, spanGaps: false, tension: 0 }] },
      options: {
        parsing: false, normalized: true,
        layout: { padding: { top: cropBands.length ? 22 : 0 } },
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        scales: {
          x: { type: "linear", min: start, max: end, grid: { color: css("--grid") },
            afterBuildTicks: (axis) => {  // one tick on 1 January of each year
              const y0 = new Date(start).getUTCFullYear(), y1 = new Date(end).getUTCFullYear();
              axis.ticks = [];
              for (let yr = y0; yr <= y1; yr++) { const t = Date.UTC(yr, 0, 1); if (t >= start && t <= end) axis.ticks.push({ value: t }); }
            },
            ticks: { callback: (val) => new Date(val).getUTCFullYear() } },
          y: { min: -0.1, max: 1, title: { display: true, text: "greenness (0 bare, 0.8 dense crop)" } },
        },
        plugins: { tooltip: { callbacks: {
          title: (it) => fmtDate(new Date(it[0].raw.x).toISOString().slice(0, 10)),
          label: (it) => `Greenness ${it.raw.y.toFixed(2)}${it.raw.y < v.threshold ? " (bare)" : ""}`,
        } } },
      },
      plugins: [periodsPlugin(v, cropBands)],
    }, "tall");
    const longBox = el("div", {}, el("div", { class: "loading" }, "Reading 25 years of NASA MODIS images (the first time takes a minute or two)…"));
    body.append(el("h3", {}, "Each year since 2000"), longBox);
    loadLongGreenness(longBox);
    body.append(el("p", { class: "small muted" }, `Greenness is measured from Sentinel-2 satellite images (${v.counts.images_used} clear images out of ${v.counts.images_read}). It cannot tell a crop from weeds or regrowth; ripe crops before harvest can look bare too. "Bare" means greenness below ${v.threshold} in at least two images in a row.`));
  }

  async function loadLongGreenness(box) {
    const fid = state.fieldId;
    let g, ctx = null;
    try {
      [g, ctx] = await Promise.all([api(`/api/field/${fid}/greenness_history`), regionContext().catch(() => null)]);
    } catch (err) {
      box.replaceChildren(el("p", { class: "muted" }, `The long greenness record could not be read (${err.message}).`));
      return;
    }
    if (fid !== state.fieldId) return;
    if (g.status === "too_small") {
      box.replaceChildren(el("p", { class: "muted" }, "Skipped: the field is too small to hold a whole 250 m MODIS pixel, so its long record would mix in neighbouring land."));
      return;
    }
    const crops = Object.fromEntries((state.history?.years || []).filter((y) => y.code != null || y.corrected).map((y) => [y.year, shortName(y.name)]));
    const dry = new Set((ctx && ctx.drought ? ctx.drought.years.filter((y) => y.worst_class === "d3" || y.worst_class === "d4").map((y) => y.year) : []));
    const ys = g.years.filter((y) => y.peak_ndvi != null);
    const labels = ys.map((y) => String(y.year));
    box.replaceChildren(
      el("p", {}, `Peak greenness of your field each year from NASA's MODIS satellites (250 m pixels; ${g.whole_pixels} whole pixel${g.whole_pixels === 1 ? "" : "s"} inside the field), with the late-spring average, which shows a crop drying down early. Compare years with the same crop.`),
      el("div", { class: "key" },
        el("span", {}, el("i", { class: "line", style: `background:${css("--series-ndvi")}` }), "Peak greenness"),
        el("span", {}, el("i", { class: "line", style: `background:${css("--series-hl")}` }), "May–June average"),
        el("span", {}, "▲ along the bottom: drought year (extreme or exceptional drought over half the county)")));
    makeChart("modis", box, {
      _label: "Peak and late-spring greenness per year since 2000",
      type: "line",
      data: { labels, datasets: [
        { label: "Peak", data: ys.map((y) => y.peak_ndvi), borderColor: css("--series-ndvi"), backgroundColor: css("--series-ndvi"), pointRadius: 3, borderWidth: 2, tension: 0 },
        { label: "May–June average", data: ys.map((y) => y.window_mean_ndvi), borderColor: css("--series-hl"), backgroundColor: css("--series-hl"), pointRadius: 3, borderWidth: 1.5, borderDash: [4, 3], tension: 0 },
        { label: "Drought year", data: ys.map((y) => (dry.has(y.year) ? 0.06 : null)), showLine: false, pointStyle: "triangle", pointRadius: 7, pointHoverRadius: 8, borderColor: css("--text-2"), backgroundColor: css("--text-2") },
      ] },
      options: {
        interaction: { mode: "index", intersect: false },
        scales: { y: { min: 0, max: 1, title: { display: true, text: "greenness" } }, x: { grid: { display: false }, ticks: { maxRotation: 60, autoSkip: true } } },
        plugins: { tooltip: { callbacks: {
          title: (it) => { const y = ys[it[0].dataIndex]; return `${y.year}: ${crops[y.year] || "crop not mapped"}${dry.has(y.year) ? " · drought year" : ""}`; },
          label: (it) => `${it.dataset.label}: ${it.raw == null ? "–" : it.raw.toFixed(2)}`,
        }, filter: (it) => it.datasetIndex !== 2 } },
      },
    });
    box.append(el("details", {}, el("summary", { class: "small" }, "Show the numbers"),
      table(["Year", "Crop (crop map)", "Peak", "May–June", "Drought"], ys.slice().reverse().map((y) => [
        y.year, crops[y.year] || "–", y.peak_ndvi.toFixed(2), y.window_mean_ndvi == null ? "–" : y.window_mean_ndvi.toFixed(2),
        dry.has(y.year) ? "▲ yes" : ""]))),
      el("p", { class: "small muted" }, "The crop map starts in 2008, so earlier years have no crop label. MODIS composites cover 16 days each; a peak date is accurate to about a week."));
  }

  function periodsPlugin(v, cropBands) {
    return { id: "periods", beforeDatasetsDraw(chart) {
      const { ctx, chartArea: a, scales: { x } } = chart;
      const px = (t) => Math.min(a.right, Math.max(a.left, x.getPixelForValue(t)));
      ctx.save();
      ctx.fillStyle = css("--gap");
      for (const g of v.gaps) ctx.fillRect(px(ts(g.start)), a.top, px(ts(g.end)) - px(ts(g.start)), a.bottom - a.top);
      ctx.fillStyle = css("--bare");
      for (const p of v.bare_periods) {
        const x0 = px(ts(p.start)), x1 = px(ts(p.end) + 864e5);
        ctx.fillRect(x0, a.top, Math.max(2, x1 - x0), a.bottom - a.top);
      }
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

  // ---------- evidence: soil and slope ---------------------------------------------------------------------
  async function loadSoil() {
    const fid = state.fieldId;
    try {
      const s = await api(`/api/field/${fid}/soil`);
      if (fid !== state.fieldId) return;
      state.soil = s;
      if (sectionOpen("soil")) renderSoil(s);
    } catch (err) {
      showError($("#ev-soil"), "The soil survey could not be read.", err);
    }
  }

  let fieldMap, fieldLayer;
  function renderSoil(s) {
    state.rendered.add("soil");
    const body = $("#ev-soil");
    const sens = { low: "low: fairly flat, so winter cover matters less here", moderate: "moderate", high: "high: steep, so winter cover matters more here" };
    const sl = s.slope_pct || {};
    const facts = [
      ["Main soil", s.main_name ? `${s.main_name} (${pct(s.main_share)} of the field)` : "not known"],
      ["Drainage", s.drainage ? s.drainage.toLowerCase() : "not known"],
      ["Water the soil can hold for crops", `${inch(s.capacity_in["0_100cm"])} in the top 3 ft; ${inch(s.capacity_in["0_150cm"])} in the top 5 ft${s.capacity_default ? " (a stated default: the soil survey could not be read)" : ""}`],
      ["Slope (soil survey)", sl.rep != null ? `about ${sl.rep}% (range ${sl.low}–${sl.high}%)` : "not known"],
      ["How much erosion matters here", s.sensitivity ? sens[s.sensitivity] : "not known"],
    ];
    const mapBox = el("div", { class: "field-map", "aria-label": "Your field on the map" });
    body.replaceChildren(
      table(["", ""], facts, "left"),
      s.soils.length > 1 ? el("div", {}, el("h3", {}, "Soils on the field"),
        table(["Soil", "Share", "Drainage", "Holds (top 5 ft)"], s.soils.map((x) => [x.name, pct(x.share), x.drainage ? x.drainage.toLowerCase() : "–", inch(x.storage_in["0_150cm"])]))) : null,
      mapBox,
      el("p", { class: "small muted" }, "From the USDA soil survey (gNATSGO and SSURGO). It describes the soil as mapped, not measured on your field. Grain crops can draw water from about 5 ft down; peas, lentils and chickpeas from about 3 ft."),
      s.error ? el("ul", { class: "caveats" }, el("li", {}, s.error)) : "");
    if (fieldMap) { fieldMap.remove(); fieldMap = null; }
    fieldMap = L.map(mapBox, { zoomControl: false, attributionControl: true, dragging: !L.Browser.mobile, scrollWheelZoom: false });
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Esri World Imagery" }).addTo(fieldMap);
    fieldLayer = L.geoJSON(state.field.geometry, { style: { color: "#4cf", weight: 3, fill: false } }).addTo(fieldMap);
    setTimeout(() => { fieldMap.invalidateSize(); fieldMap.fitBounds(fieldLayer.getBounds(), { padding: [16, 16] }); }, 30);
    const slopeBox = el("div", {}, el("div", { class: "loading" }, "Reading the elevation map for slope…"));
    mapBox.before(el("h3", {}, "Slope from the elevation map"), slopeBox);
    const fid = state.fieldId;
    Promise.all([api(`/api/field/${fid}/slope`), api(`/api/field/${fid}/slope_map.json`).catch(() => null)]).then(([sl, meta]) => {
      if (fid !== state.fieldId) return;
      if (sl.error) { slopeBox.replaceChildren(el("p", { class: "muted" }, `No slope from the elevation map: ${sl.error}`)); return; }
      const sh = sl.share_above || {};
      slopeBox.replaceChildren(
        el("p", {}, sl.summary),
        el("p", {}, sl.comparison.sentence),
        meta ? el("div", { class: "key" }, meta.legend.map((g) => el("span", {},
          el("i", { style: `background:${g.color};${g.pattern === "stripes" ? "background-image:repeating-linear-gradient(135deg,rgba(255,255,255,.8) 0 2px,transparent 2px 5px);" : ""}${g.pattern === "faint" ? "opacity:.45;" : ""}` }),
          `${g.label} (${g.range}): ${pct(g.share)} of the field`))) : null);
      if (meta) L.imageOverlay(`/api/field/${fid}/slope.png`, meta.bounds, { opacity: 0.85, interactive: false }).addTo(fieldMap);
    }).catch((err) => slopeBox.replaceChildren(el("p", { class: "muted" }, `The slope map could not be made (${err.message}).`)));
  }

  // Build each evidence section the first time it is opened (charts need a visible box).
  function onSectionToggle(e) {
    const d = e.target;
    if (!d.open || !d.dataset) return;
    if (d.id === "evidence") {  // inner sections left open earlier become visible now
      d.querySelectorAll("details[data-sec]").forEach((x) => { if (x.open) onSectionToggle({ target: x }); });
      return;
    }
    if (!d.dataset.sec || !$("#evidence").open) return;
    const sec = d.dataset.sec;
    if (sec === "history" && state.history && !state.rendered.has("history")) renderHistory(state.history);
    if (sec === "climate" && state.climate && !state.rendered.has("climate")) renderClimate(state.climate);
    if (sec === "soil" && state.soil && !state.rendered.has("soil")) renderSoil(state.soil);
    if (sec === "veg" && !state.rendered.has("veg")) { if (state.veg) renderVegetation(state.veg); else loadVegetation(); }
    for (const ch of Object.values(state.charts)) ch.resize();
  }

  // ---------- about this area -----------------------------------------------------------------------------
  let aboutRendered = false;
  async function renderAbout() {
    if (aboutRendered) return;
    aboutRendered = true;
    const cfg = state.config;
    $("#about-region").replaceChildren(
      el("p", {}, "Whitman County, in eastern Washington, is rain-fed wheat country: the Palouse. Winter wheat, spring wheat, chickpeas, lentils, peas, barley, canola and fallow share the land. Most rain and snow falls in winter and is stored in the deep silt soils for crops to use in spring and summer."),
      el("p", {}, "Rain and snow fall from west to east across the county: about 15 in a year near LaCrosse, where farmers alternate winter wheat with fallow to store a second winter's water, to about 22 in near Pullman, where a crop is grown every year."),
      el("p", {}, "Yearly rain and snow has not changed much since the 1980s, but spring rain has fallen and summer heat has risen: at the Pullman weather station, April–July rain fell from 5.9 in (1982–1996) to 4.6 in (2012–2025), and June–July days at or above 90 °F rose from 7 to 13 a year. 2021 was the driest and hottest year on record; in late July 2021 the whole county was in the most severe drought class of the US Drought Monitor."));
    try {
      const ctx = await regionContext();
      const d = ctx && ctx.drought;
      if (d) {
        const words = { d0: "Abnormally dry", d1: "Moderate drought", d2: "Severe drought", d3: "Extreme drought", d4: "Exceptional drought" };
        $("#about-region").append(el("h3", {}, "Drought since 2000 (US Drought Monitor)"),
          el("p", {}, d.text, " ", d.highlight_text || "", " ", d.latest.text),
          table(["Crop year", `Worst drought over at least ${d.min_share}% of the county`, "Peak week"],
            d.years.slice().reverse().map((y) => [cropYear(y.year), y.worst_class ? `${words[y.worst_class]} (${y.worst_class.toUpperCase()})` : "None",
              y.worst_class ? fmtDate(y.peak_date) : "–"]), "left"),
          el("p", { class: "small muted" }, d.note));
      }
      const sm = ctx && ctx.soil_moisture;
      if (sm && sm.text) {
        const box = el("div", {});
        $("#about-region").append(el("h3", {}, "Topsoil moisture from space, May to July"), el("p", {}, sm.text, " ▼ marks 2021, the driest and hottest year on record."), box,
          el("p", { class: "small muted" }, `${sm.source}. ${sm.note}`));
        const ys = sm.years.filter((y) => y.mean != null);
        makeChart("soilMoisture", box, {
          _label: "May to July topsoil moisture per year",
          type: "bar",
          data: { labels: ys.map((y) => (y.year === 2021 ? "2021 ▼" : String(y.year))), datasets: [{ data: ys.map((y) => +(y.mean * 100).toFixed(1)),
            backgroundColor: ys.map((y) => (y.year === 2021 ? css("--series-hl") : css("--series-rain"))), borderRadius: 3 }] },
          options: { scales: { y: { beginAtZero: true, title: { display: true, text: "% water" } }, x: { grid: { display: false } } },
            plugins: { tooltip: { callbacks: { label: (it) => `${it.raw}% water by volume` } } } },
        }, "short");
      }
    } catch { /* optional section */ }
    try {
      const o = await api("/api/region/outlook");
      renderOutlook(o);
    } catch {
      $("#about-outlook").replaceChildren(el("p", { class: "muted" }, "The 2050 outlook has not been prepared for this area yet."));
    }
    $("#about-sources").replaceChildren(
      el("ul", { class: "sources-list" }, cfg.attributions.map((a) => el("li", {},
        el("strong", {}, a.name), ` (${a.provider}). Used for: ${a.used_for}. `, el("em", {}, a.attribution.replace(" {years}.", "").replace("{years}", "")), " ",
        el("a", { href: a.url, target: "_blank", rel: "noopener" }, "Link"), `. ${a.licence}.`))),
      el("h3", {}, "Farming sources behind the crop figures"),
      el("ol", { class: "sources-list" }, cfg.sources.filter((s) => /^S\d+$/.test(s.id)).map((s) => el("li", { value: s.id.slice(1) },
        `[${s.id}] ${s.citation.replace(/\*/g, "")} `, s.url ? el("a", { href: s.url, target: "_blank", rel: "noopener" }, "Link") : null))));
    renderHow();
  }

  function renderOutlook(o) {
    const box = $("#about-outlook");
    if (!o || !o.rows) { box.replaceChildren(el("p", { class: "muted" }, "The 2050 outlook has not been prepared for this area yet.")); return; }
    box.replaceChildren(el("p", {}, o.intro),
      ...o.rows.map((r) => el("div", { class: "scenario" }, el("h4", {}, r[0]),
        el("ul", {}, o.columns.slice(1).map((c, i) => el("li", {}, el("strong", {}, `${c}: `), r[i + 1]))))),
      ...o.notes.map((t) => el("p", { class: "small" }, t)),
      el("p", {}, o.studies_text, " ", el("a", { href: o.studies_url, target: "_blank", rel: "noopener" }, "Washington State University summary (2018)"), "."),
      o.method_notes && o.method_notes.length ? el("details", {}, el("summary", { class: "small" }, "How this was worked out"),
        el("ul", { class: "small" }, o.method_notes.map((t) => el("li", {}, t)))) : null);
  }

  function basisTag(b) { return el("span", { class: `basis ${b}` }, b); }

  function renderHow() {
    const cfg = state.config;
    const fmtVal = (v) => (v && typeof v === "object" ? ("central" in v ? `${v.low} to ${v.high} (central ${v.central})` : JSON.stringify(v)) : String(v));
    const crops = cfg.crops.filter((c) => cfg.offered_crops.includes(c.id) && c.sowing_window);
    $("#about-how").replaceChildren(
      el("p", {}, el("span", { class: "tag-prov" }, "provisional"), " The model behind the options was designed from sourced figures but has not yet been reviewed by anyone with farming expertise. Every number below is a named setting the team can change without changing code."),
      el("h3", {}, "How options are made"),
      el("ol", {}, [
        "Read your field's crop history from the USDA crop map and find the rotation that repeats.",
        "Build every rotation of the same length from the crops grown within 10 km (plus a cover crop in place of fallow).",
        "Drop rotations that break a hard rule: no crop directly after itself; each crop sown after the one before is harvested; the same legume at most once in 3 years; winter canola only after fallow; no two years running without a harvest.",
        "Judge each one on four measures by looking back over every past crop year of weather (1982 to the last full year): water, soil protection, nitrogen and crop variety.",
        "Compare each with your rotation: better, about the same or worse, with a margin for each measure because the inputs are rough. A difference that rests on an assumed figure, and would not hold at the ends of the ranges, is called about the same.",
        "Drop any option that another beats on everything without having fewer harvests. Sort the rest by your order of importance, and show the top one for a small, a moderate and a large change.",
      ].map((t) => el("li", {}, t))),
      el("h3", {}, "The four measures"),
      el("ul", {}, cfg.measures.map((m) => el("li", {}, el("strong", {}, m.label), `: ${m.question}`))),
      el("p", {}, "There is no total score and no single best option. Income, number of harvests, how much changes and how common a pattern is nearby are shown as notes, never scored."),
      el("h3", {}, "Rules and warnings"),
      table(["Code", "What", "Basis", "Source"], [
        ...cfg.rules.map((r) => [r.code, r.label, basisTag(r.basis), r.source || "–"]),
        ...cfg.warnings.map((w) => [w.code, w.id.replace(/_/g, " "), basisTag(w.basis), w.source || "–"]),
      ], "left"),
      el("h3", {}, "Crop figures"),
      table(["Crop", "Sown", "Harvested", "Water need", "Basis"], crops.map((c) => [
        c.name, `${c.sowing_window.start}–${c.sowing_window.end}`, `${c.harvest_window.start}–${c.harvest_window.end}`,
        c.water_need ? (c.water_need.method === "fixed" ? `${(c.water_need.need_mm / 25.4).toFixed(1)} in` : c.water_need.method === "self_calibrated" ? "what it usually gets here" : `winter wheat ${(c.water_need.offset_mm / 25.4) >= 0 ? "+" : "−"} ${Math.abs(c.water_need.offset_mm / 25.4).toFixed(1)} in`) : "–",
        el("span", {}, basisTag(c.water_need ? c.water_need.basis.basis : "assumed"), " ", c.water_need && c.water_need.basis.source ? c.water_need.basis.source : ""),
      ]), "left"),
      el("p", { class: "small muted" }, "The full crop table, with every value's basis and source, is in data/crops.yaml."),
      el("h3", {}, "Every setting"),
      el("div", { class: "table-wrap" }, el("table", { class: "params" },
        el("thead", {}, el("tr", {}, el("th", {}, "Setting"), el("th", {}, "Value"), el("th", {}, "Basis"), el("th", {}, "What it does"))),
        el("tbody", {}, cfg.settings.map((p) => el("tr", {},
          el("td", {}, p.key), el("td", {}, `${fmtVal(p.value)}${p.unit ? " " + p.unit : ""}`),
          el("td", {}, basisTag(p.basis), p.source ? ` ${p.source}` : "", p.basis === "assumed" ? el("div", {}, el("span", { class: "tag-prov" }, "provisional")) : null),
          el("td", {}, p.description || "")))))),
      el("h3", {}, "What the model does not know"),
      el("ul", {}, [
        "Heat and evaporation are not in the water budget; a hot, dry spring hurts more than the missing rain suggests.",
        "The water needs of peas, lentils, chickpeas and spring canola are fixed figures from one trial, not a response to conditions.",
        "Water left behind by shallow-rooted crops is ignored.",
        "Weather is a 1 km grid estimate and soil storage comes from the soil survey, not from the field.",
      ].map((t) => el("li", {}, t))));
  }

  // ---------- routing ---------------------------------------------------------------------------------------
  function route() {
    const m = /field=([a-z0-9]+)/i.exec(location.hash);
    if (m) {
      setTab("field");
      if (m[1] !== state.fieldId || $("#view-field").hidden) openField(m[1]);
    } else {
      state.fieldId = null;
      $("#view-field").hidden = true;
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
    initMap();
    loadDemoFields();
    $("#btn-back").addEventListener("click", () => { location.hash = ""; });
    $("#btn-adjust").addEventListener("click", openAdjust);
    $("#tab-field").addEventListener("click", () => setTab("field"));
    $("#tab-about").addEventListener("click", () => setTab("about"));
    document.addEventListener("toggle", onSectionToggle, true);
    window.addEventListener("hashchange", route);
    window.addEventListener("resize", () => { for (const ch of Object.values(state.charts)) ch.resize(); });
    route();
  }

  init();
})();
