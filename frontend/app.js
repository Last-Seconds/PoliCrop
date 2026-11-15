/* Policrop front end: choose a field -> the answer first, evidence one tap away. Plain JS, no build step. */
(() => {
  "use strict";

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const VERDICT = { 1: ["b", "arrow-up", "Better"], 0: ["s", "equal", "About the same"], "-1": ["w", "arrow-down", "Worse"], null: ["n", "minus", "Not assessed"] };
  const state = {
    config: null, fieldId: null, recId: null, db: null, field: null, corrections: {}, inputs: {}, history: null, strategies: null,
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
  // One icon set (Lucide, ISC licence), drawn inline at 16 px with stroke 2; see .ico in styles.css.
  const ICONS = {
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "star": '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"/>',
    "arrow-up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    "arrow-down": '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    "arrow-left": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    "equal": '<line x1="5" x2="19" y1="9" y2="9"/><line x1="5" x2="19" y1="15" y2="15"/>',
    "minus": '<path d="M5 12h14"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "pencil": '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "triangle": '<path d="M13.73 4a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>',
  };
  const icon = (name, cls = "") => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    n.setAttribute("viewBox", "0 0 24 24");
    n.setAttribute("class", `ico ${cls}`.trim());
    n.setAttribute("aria-hidden", "true");
    n.setAttribute("focusable", "false");
    n.innerHTML = ICONS[name];
    return n;
  };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmtDate = (iso) => { const d = new Date(iso + "T00:00:00Z"); return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  const ts = (iso) => Date.parse(iso + "T00:00:00Z");
  const pct = (x) => (x == null ? "–" : `${Math.round(x * 100)}%`);
  const inch = (x, d = 1) => (x == null ? "–" : `${Number(x).toFixed(d)} in`);
  const cropYear = (y) => `${y - 1}–${String(y).slice(2)}`;

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

  // ---------- my fields (brief 3, part F) ----------------------------------------------
  // Everything lives in this browser: one versioned record per field. Results are never stored;
  // they are recomputed from what is kept, so model and data changes show up on the next visit.
  const FS_KEY = "fieldshift.fields";
  const FS_VERSION = 1;
  const FILE_FORMAT = "fieldshift-fields";
  const MAX_FILE_BYTES = 2 * 1024 * 1024;
  const RECORD_KEYS = ["corrections", "inputs", "kept", "records", "answers", "fit", "example_records"];

  function blankRec(fieldId, geometry) {
    return { id: `f${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`, field_id: fieldId, geometry,
      name: "", saved: false, acres: null, rotation_text: "", corrections: {}, inputs: {}, kept: [], records: [],
      answers: {}, fit: false, example_records: false, updated: Date.now() };
  }

  function loadDb() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(FS_KEY) || "null"); } catch { raw = null; }
    const db = { version: FS_VERSION, fields: {}, last: null };
    if (raw && typeof raw === "object" && raw.fields && typeof raw.fields === "object") {
      for (const [k, r] of Object.entries(raw.fields)) {
        const ok = readRecord(r, raw.version || 1);
        if (ok.rec) db.fields[k] = { ...ok.rec, id: k };  // what cannot be read is skipped, the rest kept
      }
      db.last = typeof raw.last === "string" && db.fields[raw.last] ? raw.last : null;
    }
    return db;
  }

  function saveDb() {
    try { localStorage.setItem(FS_KEY, JSON.stringify(state.db)); return true; } catch { return false; }
  }

  const currentRec = () => (state.db && state.recId ? state.db.fields[state.recId] : null);

  function updateRec(patch, opts = {}) {
    const rec = currentRec();
    if (!rec) return;
    Object.assign(rec, patch, { updated: Date.now() });
    if ("corrections" in patch) state.corrections = rec.corrections;
    if ("inputs" in patch) state.inputs = rec.inputs;
    saveDb();
    if (rec.saved && !opts.quiet) flashSaved();
  }

  function flashSaved() {
    const m = $("#saved-mark");
    if (!m) return;
    m.hidden = false;
    m.classList.remove("pulse"); void m.offsetWidth; m.classList.add("pulse");
  }

  // Older storage (brief 2 kept corrections and inputs under per-field keys): read it once.
  function legacyFor(fieldId) {
    const get = (k) => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : null; } catch { return null; } };
    return { corrections: get(`fs-corr-${fieldId}`), inputs: get(`fs-inputs-${fieldId}`) };
  }

  function recordFor(fieldId, geometry, recId) {
    const db = state.db;
    let rec = recId && db.fields[recId] && db.fields[recId].field_id === fieldId ? db.fields[recId] : null;
    if (!rec) rec = Object.values(db.fields).find((r) => r.field_id === fieldId && r.saved) ||
      Object.values(db.fields).find((r) => r.field_id === fieldId) || null;
    if (!rec) {
      rec = blankRec(fieldId, geometry);
      const old = legacyFor(fieldId);
      if (old.corrections && typeof old.corrections === "object") rec.corrections = old.corrections;
      if (old.inputs && typeof old.inputs === "object") rec.inputs = old.inputs;
      db.fields[rec.id] = rec;
    }
    if (!rec.geometry && geometry) rec.geometry = geometry;
    // The last field looked at is remembered even if never saved; an older unsaved one makes way.
    for (const [k, r] of Object.entries(db.fields)) if (!r.saved && k !== rec.id) delete db.fields[k];
    db.last = rec.id;
    saveDb();
    return rec;
  }

  function suggestName(rec) {
    const places = (state.config.region.places || []);
    const c = state.field && state.field.centroid;
    let best = null;
    if (c) for (const p of places) {
      const d = Math.hypot((p.lon - c[0]) * Math.cos(c[1] * Math.PI / 180), p.lat - c[1]);
      if (!best || d < best.d) best = { d, name: p.name };
    }
    const acres = rec.acres || (state.field ? Math.round(state.field.area_ha * 2.4710538) : null);
    return `Field${best ? ` near ${best.name}` : ""}${acres ? `, ${acres.toLocaleString()} acres` : ""}`;
  }

  function renderSaveControl() {
    const rec = currentRec();
    const box = $("#save-box");
    if (!rec) { box.replaceChildren(); return; }
    if (rec.saved) {
      box.replaceChildren(el("span", { id: "saved-mark", class: "saved-mark" }, icon("check"), " saved"));
      return;
    }
    box.replaceChildren(el("span", { id: "saved-mark", class: "saved-mark", hidden: true }, icon("check"), " saved"),
      el("button", { class: "btn", type: "button", "aria-label": "Save this field", onclick: () => {
        const input = el("input", { type: "text", maxlength: 120, value: suggestName(rec), "aria-label": "Name for this field" });
        box.replaceChildren(el("form", { class: "save-form", onsubmit: (e) => {
          e.preventDefault();
          const name = input.value.trim() || suggestName(rec);
          updateRec({ name, saved: true });
          renderSaveControl(); flashSaved();
          if (state.strategies) renderFieldLine(state.strategies);
        } }, input, el("button", { class: "btn primary", type: "submit" }, "Save"),
          el("button", { class: "btn", type: "button", onclick: renderSaveControl }, "Cancel")));
        input.focus(); input.select();
      } }, "Save"));
  }

  function renderMyFields() {
    const box = $("#my-fields");
    const saved = Object.values(state.db.fields).filter((r) => r.saved).sort((a, b) => b.updated - a.updated);
    const last = state.db.last && state.db.fields[state.db.last] && !state.db.fields[state.db.last].saved ? state.db.fields[state.db.last] : null;
    const items = saved.map((r) => el("li", { class: "myfield" },
      el("button", { class: "myfield-open", type: "button", onclick: () => openRecord(r) },
        el("strong", {}, r.name), el("span", {}, [r.acres ? `${r.acres.toLocaleString()} acres` : null, r.rotation_text || null].filter(Boolean).join(" · "))),
      el("div", { class: "myfield-actions" },
        el("button", { class: "btn small-btn", type: "button", onclick: () => {
          const n = prompt("New name for this field", r.name);
          if (n && n.trim()) { r.name = n.trim().slice(0, 120); r.updated = Date.now(); saveDb(); renderMyFields(); }
        } }, "Rename"),
        el("button", { class: "btn small-btn", type: "button", onclick: () => {
          if (confirm(`Remove “${r.name}” and everything kept with it from this browser? This cannot be undone.`)) {
            delete state.db.fields[r.id]; if (state.db.last === r.id) state.db.last = null; saveDb(); renderMyFields();
          }
        } }, "Remove"))));
    box.replaceChildren(
      el("div", { class: "myfields-head" }, el("h2", {}, "My fields"),
        el("div", { class: "row" },
          saved.length ? el("button", { class: "btn small-btn", type: "button", onclick: downloadFields }, "Download my fields") : null,
          el("label", { class: "btn small-btn file-btn" }, "Load a file",
            el("input", { type: "file", accept: ".json,application/json", class: "visually-hidden", onchange: (e) => { loadFieldsFile(e.target.files[0]); e.target.value = ""; } })))),
      saved.length ? el("ul", { class: "myfields-list" }, items) : el("p", { class: "muted" }, "No saved fields yet. Choose a field below, then save it."),
      last ? el("p", {}, el("button", { class: "linklike", type: "button", onclick: () => openRecord(last) }, "Back to the field you looked at last"),
        last.rotation_text ? ` (${last.acres ? `${last.acres} acres, ` : ""}${last.rotation_text.toLowerCase()})` : "") : null,
      el("p", { class: "small muted" }, "Your fields are kept in this browser on this device only, with no account; our server keeps only the outline it needs to work. Download them to keep a copy or move them."),
      el("div", { id: "file-msg", "aria-live": "polite" }));
  }

  async function openRecord(rec) {
    try {
      const info = await api("/api/field", { method: "POST", body: JSON.stringify({ field: { type: "polygon", geometry: rec.geometry } }) });
      if (info.field_id !== rec.field_id) { rec.field_id = info.field_id; saveDb(); }
      location.hash = `field=${info.field_id}&rec=${rec.id}`;
    } catch (err) {
      fileMsg(`This field could not be opened: ${err.message}`, true);
    }
  }

  function fileMsg(text, isError) {
    const m = $("#file-msg");
    if (m) m.replaceChildren(el("p", { class: isError ? "error" : "notice", role: isError ? "alert" : null }, text));
  }

  function exportRec(r) {
    const out = { name: r.name, geometry: r.geometry, acres: r.acres, rotation_text: r.rotation_text, updated: r.updated };
    for (const k of RECORD_KEYS) out[k] = r[k];
    return out;
  }

  function downloadFields() {
    const fields = Object.values(state.db.fields).filter((r) => r.saved).map(exportRec);
    const blob = new Blob([JSON.stringify({ format: FILE_FORMAT, version: FS_VERSION, exported: new Date().toISOString(), fields }, null, 1)],
      { type: "application/json" });
    const a = el("a", { href: URL.createObjectURL(blob), download: `my-fields-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---- validation of anything read back (a file is untrusted input) ----
  const isObj = (x) => x && typeof x === "object" && !Array.isArray(x);
  function validPolygon(g) {
    if (!isObj(g) || g.type !== "Polygon" || !Array.isArray(g.coordinates) || !g.coordinates.length) return false;
    let n = 0;
    for (const ring of g.coordinates) {
      if (!Array.isArray(ring) || ring.length < 4) return false;
      for (const p of ring) {
        if (!Array.isArray(p) || p.length < 2 || !p.slice(0, 2).every((v) => typeof v === "number" && Number.isFinite(v))) return false;
        if (Math.abs(p[0]) > 180 || Math.abs(p[1]) > 90) return false;
        if (++n > 20000) return false;
      }
    }
    return true;
  }
  function cleanInputs(x) {
    if (!isObj(x)) return {};
    const out = {};
    const num = (v) => typeof v === "number" && Number.isFinite(v);
    const strs = (v) => Array.isArray(v) && v.every((s) => typeof s === "string" && s.length < 40);
    if (strs(x.priorities)) out.priorities = x.priorities.slice(0, 8);
    if (typeof x.dry_mode === "boolean") out.dry_mode = x.dry_mode;
    if (strs(x.exclude)) out.exclude = x.exclude.slice(0, 30);
    if (strs(x.keep)) out.keep = x.keep.slice(0, 30);
    if (num(x.plan_length)) out.plan_length = x.plan_length;
    if (num(x.ph)) out.ph = x.ph;
    if (typeof x.tillage === "string" && x.tillage.length < 20) out.tillage = x.tillage;
    if (isObj(x.yields)) out.yields = Object.fromEntries(Object.entries(x.yields).filter(([k, v]) => k.length < 40 && num(v)).slice(0, 30));
    if (num(x.rain_pct)) out.rain_pct = x.rain_pct;
    if (num(x.temp_f)) out.temp_f = x.temp_f;
    return out;
  }
  function cleanRecords(x) {
    if (!Array.isArray(x)) return [];
    return x.slice(0, 200).filter((r) => isObj(r) && Number.isInteger(r.year) && typeof r.crop === "string" &&
      typeof r.yield_lb_ac === "number" && Number.isFinite(r.yield_lb_ac) && r.yield_lb_ac > 0)
      .map((r) => ({ year: r.year, crop: r.crop.slice(0, 40), yield_lb_ac: r.yield_lb_ac,
        entered: isObj(r.entered) ? { value: Number(r.entered.value) || null, unit: String(r.entered.unit || "").slice(0, 20), basis: r.entered.basis === "total" ? "total" : "per_acre", acres: Number(r.entered.acres) || null } : null,
        confirmed: !!r.confirmed }));
  }
  // Returns {rec} or {error}. Version 1 is the only one so far; fields added later default when missing.
  function readRecord(r, version) {
    if (!isObj(r)) return { error: "an entry is not a field" };
    if (!validPolygon(r.geometry)) return { error: "its outline is missing or damaged" };
    const rec = blankRec(typeof r.field_id === "string" && /^[a-z0-9]{1,64}$/i.test(r.field_id) ? r.field_id : null, r.geometry);
    rec.name = typeof r.name === "string" ? r.name.slice(0, 120) : "";
    rec.saved = r.saved === undefined ? true : !!r.saved;
    rec.acres = typeof r.acres === "number" && Number.isFinite(r.acres) ? Math.round(r.acres) : null;
    rec.rotation_text = typeof r.rotation_text === "string" ? r.rotation_text.slice(0, 200) : "";
    rec.corrections = isObj(r.corrections) ? Object.fromEntries(Object.entries(r.corrections)
      .filter(([k, v]) => /^\d{4}$/.test(k) && typeof v === "string" && v.length < 40)) : {};
    rec.inputs = cleanInputs(r.inputs);
    rec.kept = Array.isArray(r.kept) ? r.kept.filter((k) => isObj(k) && Array.isArray(k.crops) && k.crops.length >= 2 && k.crops.length <= 8 &&
      k.crops.every((c) => typeof c === "string" && c.length < 40)).slice(0, 12)
      .map((k) => ({ crops: k.crops, note: typeof k.note === "string" ? k.note.slice(0, 300) : "" })) : [];
    rec.records = cleanRecords(r.records);
    rec.answers = isObj(r.answers) ? Object.fromEntries(Object.entries(r.answers)
      .filter(([k, v]) => /^\d{4}:[a-z_]{1,40}$/.test(k) && typeof v === "string" && v.length < 30)) : {};
    rec.fit = !!r.fit;
    rec.example_records = !!r.example_records;
    rec.updated = typeof r.updated === "number" ? r.updated : Date.now();
    void version;
    return { rec };
  }

  async function loadFieldsFile(file) {
    if (!file) return;
    const refuse = (why) => fileMsg(`This file was not loaded, and nothing was changed: ${why}`, true);
    if (file.size > MAX_FILE_BYTES) return refuse("it is larger than a Policrop file can be (2 MB).");
    let data;
    try { data = JSON.parse(await file.text()); } catch { return refuse("it is not a readable Policrop file."); }
    if (!isObj(data) || data.format !== FILE_FORMAT || !Array.isArray(data.fields)) return refuse("it is not a Policrop fields file.");
    if (typeof data.version !== "number" || data.version > FS_VERSION) return refuse("it was made by a newer version of Policrop.");
    if (!data.fields.length) return refuse("it holds no fields.");
    if (data.fields.length > 200) return refuse("it holds more fields than one file can (200).");
    const recs = [];
    for (const [i, r] of data.fields.entries()) {
      const got = readRecord(r, data.version);
      if (got.error) return refuse(`field ${i + 1}${isObj(r) && typeof r.name === "string" ? ` (“${r.name.slice(0, 60)}”)` : ""}: ${got.error}.`);
      recs.push(got.rec);
    }
    // The server checks each outline (inside the area served, sensible size) and gives its id.
    for (const [i, rec] of recs.entries()) {
      try {
        const info = await api("/api/field", { method: "POST", body: JSON.stringify({ field: { type: "polygon", geometry: rec.geometry } }) });
        rec.field_id = info.field_id;
        if (!rec.acres) rec.acres = Math.round(info.area_ha * 2.4710538);
      } catch (err) {
        return refuse(`field ${i + 1} (“${rec.name}”): ${err.message}`);
      }
    }
    let added = 0, replaced = 0;
    for (const rec of recs) {
      rec.saved = true;
      if (!rec.name) rec.name = `Field, ${rec.acres} acres`;
      const same = Object.values(state.db.fields).find((r) => r.saved && r.field_id === rec.field_id);
      if (same) {
        const replace = confirm(`You already have a field with the same outline as “${rec.name}” (saved as “${same.name}”).\n\nOK: replace it with the one from the file.\nCancel: keep both.`);
        if (replace) { state.db.fields[same.id] = { ...rec, id: same.id }; replaced++; continue; }
        rec.name = `${rec.name} (from file)`;
      }
      state.db.fields[rec.id] = rec; added++;
    }
    saveDb();
    renderMyFields();
    fileMsg(`Loaded ${recs.length} field${recs.length === 1 ? "" : "s"}${replaced ? `, replacing ${replaced}` : ""}.`);
  }

  // ---------- tabs ---------------------------------------------------------------------
  function setTab(tab) {
    const about = tab === "about";
    $("#tab-field").setAttribute("aria-selected", String(!about));
    $("#tab-about").setAttribute("aria-selected", String(about));
    $("#page-field").hidden = about;
    $("#view-about").hidden = !about;
    if (about) { renderAbout(); renderEnso($("#about-enso")); }
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
  async function openField(fieldId, recId) {
    state.fieldId = fieldId;
    state.recId = null;
    state.corrections = {};
    state.inputs = {};
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
    const rec = recordFor(fieldId, info.geometry, recId);
    state.recId = rec.id;
    if (!rec.acres) rec.acres = Math.round(info.area_ha * 2.4710538);
    state.corrections = rec.corrections || {};
    state.inputs = rec.inputs || {};
    renderSaveControl();
    renderFieldLine(null);
    setupFieldMap();
    $("#headline").textContent = "";
    $("#compare").replaceChildren();
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

  // Everything kept with the field that the model reads (results are always recomputed from it).
  function modelInputs() {
    const rec = currentRec() || {};
    return { ...state.inputs, corrections: state.corrections, kept: rec.kept || [], records: rec.records || [],
      answers: rec.answers || {}, fit: !!rec.fit, example_records: !!rec.example_records };
  }
  const inputsParam = () => encodeURIComponent(JSON.stringify(modelInputs()));

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
      loadSeason();
      if (state.history && sectionOpen("history")) renderHistory(state.history);
    } catch (err) {
      showError(cards, "Options could not be worked out.", err);
    }
  }

  // ---------- the answer (brief 3, S2: the comparison at a glance, short cards, details in layers) ----------
  const MEASURES = ["water", "soil", "nitrogen", "variety"];
  const SHORT_MEASURE = { water: "Water", soil: "Soil", nitrogen: "Nitrogen", variety: "Variety" };
  const vcls = (v) => VERDICT[v == null ? null : v][0];

  function renderStrategies(s) {
    renderFieldLine(s);
    $("#headline").textContent = s.headline[0] || "";
    renderCompare(s);
    const shown = new Set();
    $("#cards").replaceChildren(card(s.current, s, shown), ...s.options.map((o) => card(o, s, shown)));
    const keptBox = $("#kept-cards");
    keptBox.replaceChildren(...(s.kept || []).map((o) => card(o, s, shown)));
    $("#kept-wrap").hidden = !(s.kept || []).length;
    const more = $("#more-cards");
    more.replaceChildren(...s.more.map((o) => card(o, s, shown)));
    more.hidden = true;
    const btn = $("#btn-more");
    btn.hidden = !s.more.length;
    const label = () => (more.hidden ? `Show ${s.more.length} more option${s.more.length === 1 ? "" : "s"}` : "Show fewer options");
    btn.textContent = label();
    btn.onclick = () => { more.hidden = !more.hidden; btn.textContent = label(); };
    renderAdjustSummary();
  }

  function renderFieldLine(s) {
    const rec = currentRec();
    const acres = s && s.field ? s.field.acres : (state.field ? Math.round(state.field.area_ha * 2.4710538) : null);
    const rot = s ? s.current_rotation_text : null;
    if (rec && rot && rec.rotation_text !== rot) updateRec({ rotation_text: rot, acres }, { quiet: true });
    $("#field-line").replaceChildren(...[
      rec && rec.saved ? el("strong", {}, rec.name, " · ") : null,
      acres != null ? `${acres.toLocaleString()} acres` : "",
      rot ? el("span", {}, " · Now: ", rot.charAt(0).toLowerCase() + rot.slice(1), " · ",
        el("button", { class: "linklike", type: "button", onclick: openHistory }, "fix")) : el("span", { class: "muted" }, " · reading the crop map…")]
      .filter((x) => x != null));
  }

  function renderCompare(s) {
    const rows = [s.current, ...s.options];
    const head = el("div", { class: "cmp-head", "aria-hidden": "true" }, MEASURES.map((m) => el("span", {}, SHORT_MEASURE[m])));
    $("#compare").replaceChildren(head, ...rows.map((c) => {
      const isCur = c.kind === "existing";
      const name = isCur ? "Now" : c.closed.title;
      const tag = isCur ? null : c.closed.tag;
      const crops = c.closed.chips.map((x) => x.name).join(" → ");
      const said = (isCur ? "the rotation every option is compared with" :
        c.closed.verdicts.map((v) => `${v.label} ${v.word}`).join(", ")) +
        (c.cautions.some((x) => x.serious) ? `; caution: ${c.cautions.filter((x) => x.serious).map((x) => x.short).join("; ")}` : "");
      return el("button", { class: `cmp-row ${isCur ? "cur" : ""}`, type: "button", "aria-label": `${tag ? tag + ", " : ""}${name}: ${crops}; ${said}. Open its card.`,
        onclick: () => openCard(c.id) },
        el("span", { class: "cmp-title" }, tag ? [el("span", { class: "opt-tag" }, tag), " "] : null, el("strong", {}, name), c.kept ? [" ", icon("star", "filled kept-star")] : "",
          c.cautions.some((x) => x.serious) ? el("span", { class: "cmp-warn", title: c.cautions.filter((x) => x.serious).map((x) => x.short).join("; ") }, " ", icon("alert")) : null,
          " ", el("span", { class: "cmp-crops" }, crops)),
        ...c.closed.verdicts.map((v) => el("span", { class: `cmp-v ${isCur ? "n" : vcls(v.value)}`, "aria-hidden": "true" },
          isCur ? icon("minus") : [icon(VERDICT[v.value == null ? null : v.value][1]), v.word.replace(/^about the same/, "same")])));
    }));
  }

  function openCard(id) {
    const c = document.getElementById(`card-${id}`);
    if (!c) return;
    const btn = c.querySelector(".why-btn");
    if (btn && btn.getAttribute("aria-expanded") === "false") btn.click();
    c.scrollIntoView({ behavior: "smooth", block: "start" });
    c.focus({ preventScroll: true });
  }

  function roleColor(roleId) { const r = state.config.roles.find((x) => x.id === roleId); return r ? r.color : "#999"; }

  function card(c, s, shown) {
    const cl = c.closed, isCur = c.kind === "existing";
    // Serious cautions are always shown (addendum 2, A1). Otherwise one caution, preferring one not already
    // shown on an earlier card; the rest behind a count.
    const serious = c.cautions.filter((x) => x.serious);
    const first = serious.length ? null : (c.cautions.find((x) => !shown.has(x.key)) || c.cautions[0]);
    if (first) shown.add(first.key);
    const rest = c.cautions.filter((x) => x !== first && !x.serious);
    const restList = el("ul", { class: "cautions rest", hidden: true }, rest.map((x) => el("li", {}, x.short)));
    const restBtn = rest.length ? el("button", { class: "linklike", type: "button", "aria-expanded": "false", onclick: (e) => {
      restList.hidden = !restList.hidden; e.currentTarget.setAttribute("aria-expanded", String(!restList.hidden));
      e.currentTarget.textContent = restList.hidden ? `${rest.length} more caution${rest.length > 1 ? "s" : ""}` : "fewer";
    } }, `${rest.length} more caution${rest.length > 1 ? "s" : ""}`) : null;
    const det = el("div", { class: "details", hidden: true });
    let built = false;
    const toggle = el("button", { class: "btn why-btn", type: "button", "aria-expanded": "false", onclick: () => {
      if (!built) { det.append(...detailsLayers(c, s)); built = true; }
      det.hidden = !det.hidden;
      toggle.setAttribute("aria-expanded", String(!det.hidden));
      toggle.textContent = det.hidden ? "Why and details" : "Hide details";
    } }, "Why and details");
    return el("article", { class: `opt ${isCur ? "current" : ""}`, id: `card-${c.id}`, tabindex: "-1", "aria-label": cl.tag ? `${cl.tag}, ${cl.title}` : cl.title },
      el("div", { class: "opt-head" }, el("div", { class: "opt-title" }, cl.tag ? el("span", { class: "opt-tag" }, cl.tag) : null, el("h3", {}, cl.title)),
        cl.band ? el("span", { class: "band" }, cl.band) : null,
        c.kept ? el("span", { class: "kept-mark" }, icon("star", "filled"), " kept") : null),
      el("ol", { class: "chips", "aria-label": "Crops, year by year" }, cl.chips.map((ch) =>
        el("li", { class: "chip", style: `--role:${roleColor(ch.role)}` }, ch.name))),
      isCur ? el("p", { class: "cur-note" }, "Every option is compared with this.") :
        el("ul", { class: "vlines" }, cl.verdicts.map((v) => el("li", {}, el("span", { class: "vl" }, v.label),
          el("span", { class: `verdict ${vcls(v.value)}` }, icon(VERDICT[v.value == null ? null : v.value][1]), v.word)))),
      serious.length ? el("ul", { class: "cautions serious" }, serious.map((x) => el("li", { class: "caution serious" }, x.short))) : null,
      (first || restBtn) ? el("div", { class: "caution-line" }, first ? el("span", { class: "caution" }, first.short) : null,
        restBtn ? " " : null, restBtn, restList) : null,
      cl.harvest ? el("p", { class: "harvest" }, cl.harvest) : null,
      toggle, det);
  }

  function list(items) { return items && items.length ? el("ul", {}, items.map((t) => el("li", {}, t))) : el("p", { class: "muted" }, "Nothing to add."); }

  function expander(label, build) {
    const box = el("div", { class: "layer2", hidden: true });
    let built = false;
    const btn = el("button", { class: "linklike more-link", type: "button", "aria-expanded": "false", onclick: () => {
      if (!built) { box.append(...build().filter(Boolean)); built = true; }
      box.hidden = !box.hidden;
      btn.setAttribute("aria-expanded", String(!box.hidden));
      btn.textContent = box.hidden ? label : "show less";
    } }, label);
    return [btn, box];
  }

  function sourceLinks(srcs) {
    if (!srcs || !srcs.length) return null;
    return el("p", { class: "src" }, "Sources: ", ...srcs.flatMap((x, i) => [i ? " " : "",
      el("a", { href: `#src-${x.id}`, title: (x.citation || "").replace(/\*/g, ""), onclick: (e) => { e.preventDefault(); goSource(x.id); } },
        `[${x.id.replace(/^S/, "")}]`)]));
  }

  function numbers(c, m) {
    const l = c.lines.find((x) => x.measure === m);
    const ev = c.details.evidence.find((x) => x.measure === m);
    return [list(ev.lines),
      l.range_text ? el("p", {}, `Range: ${l.range_text}.`) : null,
      l.note ? el("p", {}, l.note) : null,
      l.held_by_assumed ? el("p", {}, "* The difference depends on an assumed figure, so it is called about the same.") : null,
      sourceLinks(ev.sources)];
  }

  function incomeLines(c) {
    const inc = c.notes.income, out = [];
    if (!inc.rows.length) return out;
    out.push(`Return over total cost per acre (${inc.label}): ` + inc.rows.map((r) => `${r.crop.toLowerCase()} ${r.usd_ac >= 0 ? "+" : "−"}$${Math.abs(r.usd_ac)}`).join(", ") + ".");
    if (inc.average_usd_ac_yr != null) out.push(`Averaged over the rotation: ${inc.average_usd_ac_yr >= 0 ? "+" : "−"}$${Math.abs(inc.average_usd_ac_yr).toFixed(0)} per acre a year.`);
    else if (inc.missing.length) out.push(`No figure for ${inc.missing.join(", ").toLowerCase()}, so no average for the rotation.`);
    return out.concat(inc.context);
  }

  function detailsLayers(c, s) {
    const f = c.first, d = c.details, isCur = c.kind === "existing";
    const sec = (title, ...body) => el("section", {}, el("h4", {}, title), ...body.flat().filter(Boolean));
    return [
      sec("Why this option", el("p", {}, f.why), expander("see all", () => [list([...d.why, ...(d.map_notes || []), ...(s.settings_notes || [])])])),
      sec("The evidence", f.evidence.map((e) => el("div", { class: "ev-line" },
        el("p", {}, el("strong", {}, `${e.label}: `), e.text), ...expander("show the numbers", () => numbers(c, e.measure))))),
      sec("What it may gain you", el("p", {}, f.gains), expander("see all", () => [
        isCur ? null : list(d.gains),
        incomeLines(c).length ? el("div", {}, el("h5", {}, "Income note (not scored)"), list(incomeLines(c))) : null,
        c.notes.nearby ? el("p", {}, c.notes.nearby.text) : null,
        el("p", {}, c.notes.harvests_text, ". ", c.notes.changes_text, "."),
        c.notes.change_details && c.notes.change_details.length ? list(c.notes.change_details) : null])),
      sec("What we don't know", list(f.unknowns), expander(`see all (${d.unknowns.length})`, () => [list(d.unknowns)])),
      sec("Check locally", list(f.check), expander("see all", () => [list(d.check),
        el("ul", { class: "rules-list" }, c.rules.map((r) => el("li", {}, el("span", { class: r.passed ? "pass" : "fail" }, icon(r.passed ? "check" : "x")), el("span", { class: "visually-hidden" }, r.passed ? "Passes: " : "Fails: "), `${r.label}${r.passed ? "" : `: ${r.reason}`}`)))])),
      el("div", { class: "card-actions" },
        isCur ? null : keepControl(c),
        el("button", { class: "btn", type: "button", onclick: () => printOption(c, s) }, "Print this option")),
    ];
  }

  // ---------- keeping options (brief 3, F) ----------
  const sameRotation = (a, b) => a.length === b.length && a.some((_, k) => a.slice(k).concat(a.slice(0, k)).join() === b.join());

  function keepControl(c) {
    const rec = currentRec();
    const kept = (rec.kept || []).find((k) => sameRotation(k.crops, c.crop_ids));
    const box = el("div", { class: "keep" });
    const draw = () => {
      const k = (currentRec().kept || []).find((x) => sameRotation(x.crops, c.crop_ids));
      if (!k) {
        box.replaceChildren(el("button", { class: "btn", type: "button", onclick: () => {
          updateRec({ kept: [...(currentRec().kept || []), { crops: [...c.crop_ids], note: "" }] });
          draw(); loadStrategies();
        } }, icon("star"), " Keep this option"));
        return;
      }
      const note = el("input", { type: "text", maxlength: 300, value: k.note || "", placeholder: "A note, if you like", "aria-label": "Note on this kept option" });
      note.addEventListener("change", () => {
        updateRec({ kept: currentRec().kept.map((x) => (sameRotation(x.crops, c.crop_ids) ? { ...x, note: note.value } : x)) });
      });
      box.replaceChildren(el("p", { class: "small" }, icon("star", "filled"), " Kept with this field."), note,
        el("button", { class: "btn", type: "button", onclick: () => {
          updateRec({ kept: currentRec().kept.filter((x) => !sameRotation(x.crops, c.crop_ids)) });
          draw(); loadStrategies();
        } }, "Stop keeping it"));
    };
    draw();
    void kept;
    return box;
  }

  // ---------- a page to take away (brief 3, S2 target 9) ----------
  function printOption(c, s) {
    const rec = currentRec();
    const area = $("#print-area");
    const kept = (rec.kept || []).find((k) => sameRotation(k.crops, c.crop_ids));
    area.replaceChildren(
      el("h1", {}, "Policrop: one option for one field"),
      el("p", {}, `${rec.saved ? rec.name + ", " : ""}${s.field.acres.toLocaleString()} acres. Now: ${s.current_rotation_text}. Printed ${new Date().toLocaleDateString()}.`),
      el("h2", {}, c.kind === "existing" ? "Your current rotation" : `${c.closed.tag ? c.closed.tag + ", " : ""}${c.closed.title}: ${c.closed.chips.map((x) => x.name).join(" → ")}`),
      kept && kept.note ? el("p", {}, `Your note: ${kept.note}`) : null,
      el("p", {}, c.first.why),
      el("h3", {}, "Compared with your current rotation"),
      el("table", { class: "print-table" }, el("tbody", {}, c.lines.map((l) => el("tr", {},
        el("th", {}, l.label), el("td", {}, c.kind === "existing" ? "" : [icon(VERDICT[l.verdict == null ? null : l.verdict][1]), " ", l.verdict_word]),
        el("td", {}, l.value_text + (l.now_text ? `. Now: ${l.now_text.charAt(0).toLowerCase()}${l.now_text.slice(1)}` : "") + "."))))),
      el("h3", {}, "Cautions"),
      c.cautions.length ? el("ul", {}, c.cautions.map((x) => el("li", {}, el("strong", {}, x.short), ": ", x.text))) : el("p", {}, "None."),
      el("h3", {}, "Questions to check locally"),
      el("ul", {}, c.details.check.map((t) => el("li", {}, t))),
      el("p", { class: "small" }, "Policrop compares rotations on this field's past weather, soil and crop history (in past years like these). It does not forecast a harvest. Provisional model: not yet reviewed by anyone with farming expertise."));
    area.hidden = false;
    window.print();
    setTimeout(() => { area.hidden = true; }, 500);
  }

  function goSource(id) {
    setTab("about");
    const box = $("#about-sources").closest("details");
    if (box) box.open = true;
    setTimeout(() => { const li = document.getElementById(`src-${id}`); if (li) { li.scrollIntoView({ block: "center" }); li.classList.add("flash"); } }, 300);
  }

  // ---------- adjust (brief 3, S2 target 5: five things first, the rest under "more settings") ----------
  const MEASURE_LABEL = () => Object.fromEntries(state.config.measures.map((m) => [m.id, m.label]));

  function nonDefaultInputs() {
    const i = state.inputs, out = [];
    if (i.priorities) out.push(`${MEASURE_LABEL()[i.priorities[0]].toLowerCase()} first`);
    if (i.dry_mode) out.push("dry region mode");
    if (i.tillage) out.push("tillage");
    if (i.ph != null && i.ph !== "") out.push("soil pH");
    if (i.exclude && i.exclude.length) out.push("crops ruled out");
    if (i.keep && i.keep.length) out.push("crops kept");
    if (i.plan_length) out.push("plan length");
    if (i.yields && Object.keys(i.yields).length) out.push("your yields");
    if (i.rain_pct) out.push(`spring rain ${i.rain_pct > 0 ? "+" : "−"}${Math.abs(i.rain_pct)}%`);
    if (i.temp_f) out.push(`+${i.temp_f} °F`);
    if (Object.keys(state.corrections).length) out.push("crop history fixed");
    const rec = currentRec();
    if (rec && (rec.records || []).length) out.push("your harvest records");
    if (rec && rec.fit) out.push("fitted to your field");
    return out;
  }

  function renderAdjustSummary() {
    const n = nonDefaultInputs();
    $("#adjust-summary").textContent = n.length ? `Your settings: ${n.join(", ")}` : "";
  }

  function info(text) {
    const p = el("p", { class: "what", hidden: true }, text);
    const b = el("button", { class: "info-btn", type: "button", "aria-label": "What this does", "aria-expanded": "false",
      onclick: () => { p.hidden = !p.hidden; b.setAttribute("aria-expanded", String(!p.hidden)); } }, icon("info"));
    return [b, p];
  }

  function item(labelNode, control, what) {
    const [b, p] = what ? info(what) : [null, null];
    return el("div", { class: "item" }, el("div", { class: "lbl" }, labelNode, b), p, control);
  }

  function chipToggles(crops, selected, aria) {
    return el("div", { class: "chip-toggles", role: "group", "aria-label": aria }, crops.map((c) =>
      el("button", { type: "button", class: "chip-toggle", "data-id": c.id, "aria-pressed": String(selected.has(c.id)),
        onclick: (e) => { const on = e.currentTarget.getAttribute("aria-pressed") !== "true"; e.currentTarget.setAttribute("aria-pressed", String(on)); } },
      c.name, c.note ? el("span", { class: "muted" }, ` ${c.note}`) : null)));
  }
  const pressed = (box) => [...box.querySelectorAll(".chip-toggle[aria-pressed=true]")].map((b) => b.dataset.id);

  // Parts B and C add their controls here (under "more settings").
  const ADJUST_EXTRAS = [];

  function buildAdjust(fromInputs) {
    const s = state.strategies, cfg = state.config, inp = structuredClone(fromInputs);
    const labels = MEASURE_LABEL();
    const dflt = cfg.measures.map((m) => m.id);
    let prio = inp.priorities || [...dflt];

    const top = el("div", { class: "radios", role: "radiogroup", "aria-label": "What matters most?" });
    const prioList = el("ol", { class: "prio" });
    const drawTop = () => top.replaceChildren(...dflt.map((m) => el("label", { class: "radio" },
      el("input", { type: "radio", name: "top", value: m, checked: prio[0] === m || null,
        onchange: () => { prio = [m, ...prio.filter((x) => x !== m)]; drawPrio(); } }), " ", labels[m])));
    const drawPrio = () => prioList.replaceChildren(...prio.map((m, i) => el("li", {},
      el("span", {}, `${i + 1}.`), el("span", {}, labels[m]),
      el("button", { class: "btn small-btn", type: "button", "aria-label": `Move ${labels[m]} up`, disabled: i === 0 || null, onclick: () => { [prio[i - 1], prio[i]] = [prio[i], prio[i - 1]]; drawPrio(); drawTop(); } }, icon("arrow-up")),
      el("button", { class: "btn small-btn", type: "button", "aria-label": `Move ${labels[m]} down`, disabled: i === prio.length - 1 || null, onclick: () => { [prio[i + 1], prio[i]] = [prio[i], prio[i + 1]]; drawPrio(); drawTop(); } }, icon("arrow-down")))));
    drawTop(); drawPrio();

    const dry = el("input", { type: "checkbox", id: "in-dry", checked: inp.dry_mode || null });
    const tillDefault = cfg.tillage.default;
    const till = el("div", { class: "radios", role: "radiogroup", "aria-label": "Tillage" }, cfg.tillage.options.map((o) => el("label", { class: "radio" },
      el("input", { type: "radio", name: "tillage", value: o.id, checked: (inp.tillage || tillDefault) === o.id || null }), " ", o.label)));

    const near = new Set((s ? s.pool.crops : []).map((c) => c.id));
    const allOffered = cfg.crops.filter((c) => cfg.offered_crops.includes(c.id))
      .map((c) => ({ id: c.id, name: c.name, note: near.has(c.id) || c.role === "cover_crop" ? "" : "(not grown nearby)" }));
    const ex = chipToggles(allOffered, new Set(inp.exclude || []), "Crops to rule out");
    const kp = chipToggles(allOffered, new Set(inp.keep || []), "Crops to keep");

    const sc = cfg.scenario;
    const rainOut = el("output", {}), tempOut = el("output", {});
    const rain = el("input", { type: "range", id: "in-rain", min: sc.rain_pct.low, max: sc.rain_pct.high, step: 5, value: inp.rain_pct || 0 });
    const temp = el("input", { type: "range", id: "in-temp", min: sc.temp_f.low, max: sc.temp_f.high, step: 1, value: inp.temp_f || 0 });
    const upd = () => {
      const r = +rain.value;
      rainOut.textContent = r === 0 ? "as it was" : `${r > 0 ? "+" : "−"}${Math.abs(r)}% rain, April to July`;
      tempOut.textContent = +temp.value ? `+${temp.value} °F` : "as it was";
    };
    rain.addEventListener("input", upd); temp.addEventListener("input", upd); upd();

    const curLen = s ? s.detected_period : 3;
    const plan = el("select", { id: "in-plan" }, el("option", { value: "" }, `Same as now (${curLen} years)`),
      [2, 3, 4, 5, 6].map((n) => el("option", { value: n, selected: inp.plan_length === n || null }, `${n} years`)));
    const ph = el("input", { type: "number", id: "in-ph", min: 3, max: 10, step: 0.1, placeholder: "not known", value: inp.ph ?? "", inputmode: "decimal" });
    const yieldCrops = cfg.crops.filter((c) => c.yield_unit && cfg.offered_crops.includes(c.id) &&
      (!s || s.pool.crops.some((p) => p.id === c.id) || s.current.crop_ids.includes(c.id)));
    const unitWord = (u) => (u.name === "bu" ? "bu/acre" : u.name === "tons" ? "tons/acre" : "lb/acre");
    const yields = el("div", { class: "yield-grid" }, yieldCrops.map((c) => el("label", {}, c.name,
      el("input", { type: "number", min: 0, step: "any", "data-yield": c.id, inputmode: "decimal",
        placeholder: unitWord(c.yield_unit), value: (inp.yields || {})[c.id] ?? "" }))));
    const corrN = Object.keys(state.corrections).length;

    const extras = ADJUST_EXTRAS.map((fn) => fn(inp)).filter(Boolean);
    const body = $("#adjust-body");
    body.replaceChildren(
      item(el("span", {}, "What matters most?"), top, "Options are sorted by how they compare with your rotation on this measure first. The full order is under more settings."),
      item(el("label", { for: "in-dry", class: "switch" }, dry, " Dry region mode"), null,
        "Judges water on the 5 driest of the last 15 years, puts water first, and breaks ties in favour of more harvests: least water, most food."),
      item(el("span", {}, "Tillage"), till, "Changes how much crop residue stays on the surface over winter."),
      item(el("span", {}, "Crops to rule out"), ex, "Tap a crop to rule it out: it will not appear in any option."),
      item(el("label", { for: "in-rain" }, "What if spring is drier? ", rainOut), rain,
        "Looks back over the same years with April–July rain changed. Water needs stay as they were, so a drier setting shows more shortfalls."),
      el("details", { class: "more-settings" }, el("summary", {}, "More settings"),
        item(el("span", {}, "Full order of importance"), prioList, "Options are sorted by how they compare with your rotation on the first measure, then the second, and so on."),
        item(el("span", {}, "Crops to keep"), kp, "Every option includes the crops you keep."),
        item(el("label", { for: "in-plan" }, "Plan length"), plan, null),
        item(el("label", { for: "in-ph" }, "Soil pH from a soil test"), ph,
          "Used to warn when a crop may struggle in acid soil. The soil survey's pH is not used: it describes the soil as surveyed, and measured values here have fallen below 5."),
        item(el("span", {}, "Your typical yields"), yields, "Changes the crop residue estimate and the legume nitrogen credit. Leave blank to use regional figures for your rainfall zone."),
        ...extras.map((x) => x.node),
        item(el("label", { for: "in-temp" }, "Temperature ", tempOut), temp,
          "Raises every day's high and low. It changes how often chickpeas meet damaging heat and winter peas meet killing cold. It does not raise crop water demand, because the water estimate has no evaporation term, so it understates the effect of warming."),
        item(el("span", {}, "Crop history"), el("div", {}, el("button", { class: "btn", type: "button", onclick: () => { $("#adjust").close(); openHistory(); } }, "Fix the crop history"),
          corrN ? el("span", {}, ` ${corrN} year${corrN > 1 ? "s" : ""} fixed by you`) : null), null)));

    return () => {
      const out = {};
      if (prio.join() !== dflt.join()) out.priorities = [...prio];
      if (dry.checked) out.dry_mode = true;
      const t = body.querySelector("input[name=tillage]:checked");
      if (t && t.value !== tillDefault) out.tillage = t.value;
      if (ph.value !== "" && !Number.isNaN(+ph.value)) out.ph = +ph.value;
      const exl = pressed(ex);
      const kpl = pressed(kp).filter((k) => !exl.includes(k));
      if (exl.length) out.exclude = exl;
      if (kpl.length) out.keep = kpl;
      if (plan.value) out.plan_length = +plan.value;
      const ys = {};
      body.querySelectorAll("[data-yield]").forEach((x) => { if (x.value !== "" && +x.value > 0) ys[x.dataset.yield] = +x.value; });
      if (Object.keys(ys).length) out.yields = ys;
      if (+rain.value) out.rain_pct = +rain.value;
      if (+temp.value) out.temp_f = +temp.value;
      for (const x of extras) if (x.collect) x.collect();
      return out;
    };
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
      updateRec({ inputs: state.inputs });
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
          y.corrected ? el("span", { class: "c" }, icon("pencil")) : null,
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
      el("button", { class: "linklike", type: "button", onclick: () => { updateRec({ corrections: {} }); reloadHistory(); } }, "Undo all fixes")) : null;
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
          updateRec({ corrections: { ...state.corrections } }); close(); reloadHistory();
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

  // ---------- the farmer's records, fitting (brief 3, parts B and C) -------------------------------
  const UNITS = [["bu", "bushels"], ["lb", "pounds"], ["cwt", "hundredweight"], ["ton", "tons"]];

  function recordsGroup() {
    const rec = currentRec();
    const s = state.strategies;
    const box = el("div", { class: "records" });
    const msg = el("div", { "aria-live": "polite" });
    const draw = () => {
      const r = currentRec();
      const sec = state.strategies && state.strategies.records;
      const years = (state.history ? state.history.years : []).filter((y) => y.crop_id && state.config.offered_crops.includes(y.crop_id)
        && !["fallow", "cover_crop"].includes((state.config.crops.find((c) => c.id === y.crop_id) || {}).role)).slice(-12).reverse();
      const have = Object.fromEntries((r.records || []).map((x) => [`${x.year}:${x.crop}`, x]));
      const rows = years.map((y) => {
        const k = have[`${y.year}:${y.crop_id}`];
        const crop = state.config.crops.find((c) => c.id === y.crop_id);
        const unitDefault = crop && crop.yield_unit ? ({ bu: "bu", tons: "ton" }[crop.yield_unit.name] || "lb") : "lb";
        return el("tr", { "data-year": y.year, "data-crop": y.crop_id },
          el("td", {}, y.year), el("td", {}, crop ? crop.name : y.crop_id),
          el("td", {}, el("input", { type: "number", min: 0, step: "any", inputmode: "decimal", "aria-label": `Harvest ${y.year}`,
            value: k && k.entered ? k.entered.value : (k ? k.yield_lb_ac : ""), "data-k": "value" })),
          el("td", {}, el("select", { "aria-label": `Unit ${y.year}`, "data-k": "unit" }, UNITS.map(([u, w]) =>
            el("option", { value: u, selected: (k && k.entered ? k.entered.unit : (k ? "lb" : unitDefault)) === u || null }, w)))),
          el("td", {}, el("select", { "aria-label": `Per acre or total ${y.year}`, "data-k": "basis" },
            el("option", { value: "per_acre" }, "per acre"),
            el("option", { value: "total", selected: k && k.entered && k.entered.basis === "total" || null }, "total from the field"))));
      });
      const table = el("div", { class: "table-wrap" }, el("table", { class: "data-table left rec-table" },
        el("thead", {}, el("tr", {}, ["Year", "Crop", "Harvest", "Unit", ""].map((h) => el("th", {}, h)))), el("tbody", {}, rows)));
      const acres = el("input", { type: "number", min: 0, step: "any", value: (r.harvest_acres || (r.acres || "")), "aria-label": "Acres harvested" });
      box.replaceChildren(
        el("p", {}, "Fill in the years you know; leave the rest empty. Or download the blank sheet, fill it in and load it."),
        table,
        el("label", { class: "row" }, "Acres harvested, for totals: ", acres),
        el("div", { class: "row" },
          el("button", { class: "btn primary", type: "button", onclick: () => useTyped(table, acres, msg) }, "Use these figures"),
          el("a", { class: "btn", href: `/api/field/${state.fieldId}/records_template.xlsx?corrections=${encodeURIComponent(JSON.stringify(state.corrections))}` }, "Download a blank sheet"),
          el("label", { class: "btn file-btn" }, "Load a sheet (.xlsx or .csv)",
            el("input", { type: "file", accept: ".xlsx,.csv", class: "visually-hidden", onchange: (e) => { uploadSheet(e.target.files[0], msg); e.target.value = ""; } }))),
        el("p", { class: "small muted" }, "A file you load is read on our server for its values only, then discarded. Your records are kept in this browser, with the field."),
        msg,
        el("div", { class: "row" },
          el("button", { class: "btn", type: "button", onclick: async () => {
            const ex = await api(`/api/field/${state.fieldId}/example_records?corrections=${encodeURIComponent(JSON.stringify(state.corrections))}`);
            updateRec({ records: ex.records.map((x) => ({ ...x, entered: null })), example_records: true, answers: {} });
            msg.replaceChildren(el("p", { class: "notice" }, "Example records loaded: example data, not a real farm."));
            loadStrategies(); draw();
          } }, "Try with example records"),
          (r.records || []).length ? el("button", { class: "btn", type: "button", onclick: () => {
            updateRec({ records: [], answers: {}, example_records: false, fit: false }); loadStrategies(); draw();
          } }, "Clear records") : null,
          (r.records || []).length ? el("button", { class: "btn", type: "button", onclick: downloadRecords }, "Download my records") : null),
        sec && sec.count ? recordsResult(sec, draw) : null);
    };
    draw();
    return { node: item(el("span", {}, "Your harvest records"), box,
      "Your own yields, by year. They are compared with what that year's weather would have led us to expect, and blended with regional figures: a few records nudge the result, many lead it."), collect: null };
  }

  function downloadRecords() {
    const r = currentRec();
    const blob = new Blob([JSON.stringify({ format: "fieldshift-records", version: 1, field: r.name || null, records: r.records, answers: r.answers }, null, 1)], { type: "application/json" });
    const a = el("a", { href: URL.createObjectURL(blob), download: "my-harvest-records.json" });
    document.body.append(a); a.click(); a.remove();
  }

  async function useTyped(table, acres, msg) {
    const rows = [...table.querySelectorAll("tbody tr")].map((tr) => ({
      year: +tr.dataset.year, crop: tr.dataset.crop, value: tr.querySelector("[data-k=value]").value,
      unit: tr.querySelector("[data-k=unit]").value, basis: tr.querySelector("[data-k=basis]").value, acres: acres.value || null,
    })).filter((x) => x.value !== "");
    const res = await api(`/api/field/${state.fieldId}/records/check`, { method: "POST", body: JSON.stringify({ rows }) });
    showPreview(res.rows, msg, acres.value);
  }

  async function uploadSheet(file, msg) {
    if (!file) return;
    msg.replaceChildren(el("div", { class: "loading" }, "Reading the file…"));
    try {
      const res = await fetch(`/api/field/${state.fieldId}/records/read?name=${encodeURIComponent(file.name)}`, { method: "POST", body: await file.arrayBuffer() });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || res.statusText);
      showPreview(body.rows, msg, null, body);
    } catch (err) {
      msg.replaceChildren(el("p", { class: "error", role: "alert" }, err.message));
    }
  }

  function showPreview(rows, msg, acres, info) {
    const names = Object.fromEntries(state.config.crops.map((c) => [c.id, c.name]));
    const ok = rows.filter((r) => r.status === "ok" || r.status === "confirm");
    const confirms = {};
    const table = el("div", { class: "table-wrap" }, el("table", { class: "data-table left" },
      el("thead", {}, el("tr", {}, ["Line", "Year", "Crop", "Read as", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, rows.filter((r) => r.status !== "empty").map((r) => el("tr", {},
        el("td", {}, r.line), el("td", {}, r.year ?? "–"), el("td", {}, r.crop ? names[r.crop] : "–"),
        el("td", {}, r.yield_lb_ac ? `${Math.round(r.yield_lb_ac).toLocaleString()} lb/acre (${r.value} ${r.unit}${r.basis === "total" ? " total" : " per acre"})` : "–"),
        el("td", {}, r.status === "ok" ? [icon("check"), el("span", { class: "visually-hidden" }, "used")] : r.status === "confirm" ?
          el("label", {}, el("input", { type: "checkbox", onchange: (e) => { confirms[r.line] = e.target.checked; } }), ` keep? ${r.reason}`) :
          el("span", { class: "error-text" }, `not used: ${r.reason}`)))))));
    msg.replaceChildren(
      el("h4", {}, "Check how each row was read"),
      info && info.unsure && info.unsure.length ? el("p", { class: "notice" }, `Some columns could be read more than one way (${info.unsure.join(", ")}): check the years, crops and figures below.`) : null,
      table,
      el("div", { class: "row" },
        el("button", { class: "btn primary", type: "button", onclick: () => {
          const use = ok.filter((r) => r.status === "ok" || confirms[r.line]);
          const prev = Object.fromEntries((currentRec().records || []).map((x) => [`${x.year}:${x.crop}`, x]));
          for (const r of use) prev[`${r.year}:${r.crop}`] = { year: r.year, crop: r.crop, yield_lb_ac: r.yield_lb_ac,
            entered: { value: r.value, unit: r.unit, basis: r.basis, acres: acres ? +acres : null }, confirmed: r.status === "confirm" };
          updateRec({ records: Object.values(prev), example_records: false });
          msg.replaceChildren(el("p", { class: "notice" }, `${use.length} record${use.length === 1 ? "" : "s"} added. Close Adjust and press Show results to see them used.`));
          loadStrategies();
        } }, `Use ${ok.length} row${ok.length === 1 ? "" : "s"}`)));
  }

  function recordsResult(sec, redraw) {
    const rec = currentRec();
    const names = Object.fromEntries(state.config.crops.map((c) => [c.id, c.name]));
    const rows = sec.comparison.rows;
    const chartBox = el("div", {});
    setTimeout(() => {
      if (!chartBox.isConnected) return;
      makeChart("records", chartBox, {
        _label: "Your yield beside our estimate for each year",
        type: "bar",
        data: { labels: rows.map((r) => `${r.year} ${names[r.crop].toLowerCase()}`), datasets: [
          { label: "Your yield", data: rows.map((r) => r.actual_lb_ac), backgroundColor: css("--series-ndvi") },
          { label: "Our estimate for that year's weather", data: rows.map((r) => r.expected_lb_ac), backgroundColor: css("--series-rain") }] },
        options: { plugins: { legend: { display: true }, tooltip: { callbacks: { afterBody: (it) => {
          const r = rows[it[0].dataIndex]; return [r.reason_words ? `Your answer: ${r.reason_words}${r.excluded ? " (left out of fitting)" : ""}` : "", sec.example ? "Example data, not a real farm" : ""].filter(Boolean);
        } } } }, scales: { y: { title: { display: true, text: "lb per acre" }, beginAtZero: true } } },
      }, "short");
    }, 50);
    const q = sec.questions.map((x) => el("div", { class: "question" },
      el("p", {}, el("strong", {}, `${x.year}, ${x.crop_name.toLowerCase()}: `), "Our estimate missed this year. Do you know why?"),
      el("select", { "aria-label": `Why ${x.year} was different`, onchange: (e) => {
        const answers = { ...(currentRec().answers || {}) };
        if (e.target.value) answers[x.key] = e.target.value; else delete answers[x.key];
        updateRec({ answers }); loadStrategies();
      } }, el("option", { value: "" }, "Choose…"), Object.entries(sec.reasons).map(([k, w]) => el("option", { value: k, selected: x.answer === k || null }, w)))));
    const fitOn = !!rec.fit;
    const fit = sec.fit;
    const fitBox = el("div", { class: "fit" },
      el("label", { class: "switch" }, el("input", { type: "checkbox", checked: fitOn || null, onchange: (e) => { updateRec({ fit: e.target.checked }); loadStrategies().then(redraw); } }), " Fit to my field"),
      fitOn && fit ? el("p", {}, fit.applied ? fit.message : fit.message, sec.example ? " (example data, not a real farm)" : "") : null,
      fitOn ? el("button", { class: "btn", type: "button", onclick: () => { updateRec({ fit: false }); loadStrategies().then(redraw); } }, "Undo: back to the regional values") : null,
      fit && fit.coverage ? el("p", { class: "notice" }, fit.coverage) : null);
    return el("div", { class: "rec-result" },
      el("h4", {}, "Your yields against our estimate"), sec.example ? el("p", { class: "notice" }, "Example data, not a real farm.") : null,
      chartBox, el("p", {}, sec.comparison.sentence + " Each estimate uses that year's own weather, month by month: in past years like this, not a forecast."),
      q.length ? el("div", {}, ...q) : null,
      sec.levels.length ? el("details", {}, el("summary", {}, "What your records changed"), el("ul", {}, sec.levels.map((l) => el("li", {},
        `${l.crop}: ${l.level_lb_ac.toLocaleString()} lb/acre against the regional ${l.regional_lb_ac.toLocaleString()} (weight ${Math.round(l.w * 100)}%)`
        + (l.borrowed_from.length ? `, estimated from your ${l.borrowed_from.map((x) => x.toLowerCase()).join(" and ")} records` : "")
        + (sec.example ? " — example data, not a real farm" : ""))))) : null,
      fitBox);
  }
  ADJUST_EXTRAS.push(() => (state.fieldId ? recordsGroup() : null));

  // ---------- this year so far (brief 3, part D) ---------------------------------------------
  async function loadSeason() {
    const line = $("#season-line");
    line.hidden = true;
    const fid = state.fieldId;
    const asof = (/asof=(\d{4}-\d{2}-\d{2})/.exec(location.hash) || [])[1];
    let s;
    try {
      s = await api(`/api/field/${fid}/season?inputs=${inputsParam()}${asof ? `&date=${asof}` : ""}`);
    } catch { return; }
    if (fid !== state.fieldId || !s.show || ["hidden"].includes(s.status)) return;
    const date = fmtDate(s.date);
    let head;
    if (s.status === "unavailable") head = `This year so far (${date}): the check is unavailable — ${s.reason || "no station data"}.`;
    else if (s.status === "refills") head = `This year so far (${date}): ${s.message}`;
    else head = `This year so far (${date}): stored water is wetter than ${s.rank.wetter_than} of the last ${s.rank.of} winters at this date.`;
    const body = [];
    if (s.stored_in != null) body.push(`Stored water so far for ${s.next_crop.toLowerCase()} (${s.kind === "fallow" ? "after fallow" : "after a harvested crop"}): about ${s.stored_in} in of a possible ${s.capacity_in} in.`);
    if (s.status === "ok") body.push(`In ${s.lookalike_years.length} past years that started like this one, ${s.next_role === "fallow" ? "a spring crop" : s.next_crop.toLowerCase()} ran short in ${s.lookalike_short}.` + (s.lookalike_note ? ` ${s.lookalike_note}` : ""));
    if (s.guideline && s.guideline.band) body.push(`Guideline only [S27]: for ${s.guideline.band} of yearly rain and snow, about ${s.guideline.spring_in} in of stored water before spring planting and ${s.guideline.autumn_in} in before autumn planting.`);
    for (const a of s.alternatives || []) body.push(`${a.crop}: short in ${a.short} of ${a.of} of those years.`);
    if (s.records && s.records.length) body.push(`You recorded ${s.records.map((r) => `${Math.round(r.yield_lb_ac)} lb/acre in ${r.year}`).join(" and ")} in years like this.`);
    if (s.source && s.source.text) body.push(s.source.text);
    body.push("In past years like this; not a forecast. It does not tell you what to plant.");
    line.replaceChildren(el("details", {}, el("summary", {}, head), el("ul", {}, body.map((t) => el("li", {}, t)))));
    line.hidden = false;
  }

  // ---------- validation and El Niño (brief 3, parts A and D) --------------------------------------
  async function renderValidation(box) {
    let v;
    try { v = await api("/api/validation"); } catch (err) { box.replaceChildren(el("p", { class: "muted" }, err.message)); return; }
    const names = Object.fromEntries(state.config.crops.map((c) => [c.id, c.name]));
    const r2 = (x) => (x == null ? "–" : x.toFixed(2));
    const pc = (x) => (x == null ? "–" : `${Math.round(x * 100)}%`);
    const east = v.areas.find((a) => a.id === "east"), west = v.areas.find((a) => a.id === "west");
    const words = (r) => (r == null ? "unknown" : r >= 0.7 ? "fairly close" : r >= 0.5 ? "moderate" : "weak");
    box.replaceChildren(
      el("p", {}, `How closely the tool's idea of a good or bad year matched what satellites saw (${v.method.years}): the match was ${words(east.all_crops.correlation)} in the east (correlation ${r2(east.all_crops.correlation)}, ${east.all_crops.years} years) and ${words(west.all_crops.correlation)} in the dry west (${r2(west.all_crops.correlation)}, ${west.all_crops.years} years). The quick tests found ${v.quick_tests.east_correlation} and ${v.quick_tests.west_correlation}.`),
      el("p", {}, `Neighbouring fields differ more in one year (spread ${r2(east.all_crops.spread_between_neighbouring_pixels)}) than the whole area differs between years (${r2(east.all_crops.spread_of_area_average_between_years)}), so the tool describes the year, not one field's result.`),
      el("p", {}, "\"Greenness\" is the highest satellite greenness (MODIS NDVI) in late April to late July, over pixels where one crop covers at least 75%. It is not yield."),
      table(["Area", "Rain and snow a year", "Crop", "Correlation", "Better than the crop's average (leave one year out)", "Years", "Pixels a year"],
        v.areas.flatMap((a) => Object.entries(a.crops).filter(([, c]) => c.years >= 6).map(([cid, c]) => [a.name, `${a.mean_crop_year_precip_in} in`, names[cid] || cid,
          r2(c.correlation), pc(c.loo_reduction), c.years, c.pixels_median]))),
      el("p", { class: "small" }, "Where it did not match: a negative figure means the index did worse than simply using the crop's own average. Lentils and peas did not fit in the east, as in the quick tests."),
      el("h4", {}, "How strongly each crop swings with the year (winter wheat = 1)"),
      table(["Crop", "Sensitivity", "Basis", "Years"], Object.entries(v.sensitivities).map(([cid, s]) => [names[cid] || cid, s.value, s.basis, s.n_years ?? "–"])),
      el("p", { class: "small muted" }, `County yields: ${v.county_yields.available ? "used" : "not available (data/us/county_yields.csv not supplied), so greenness was used"}. Generated ${v.generated}.`));
  }

  async function renderEnso(box) {
    if (!state.fieldId) { box.replaceChildren(el("p", { class: "muted" }, "Open a field to see what El Niño winters have meant there.")); return; }
    try {
      const e = await api(`/api/field/${state.fieldId}/enso`);
      if (e.status !== "ok") throw new Error("unavailable");
      box.replaceChildren(el("p", {}, `NOAA's index for ${e.season} ${e.year}: ${e.anomaly > 0 ? "+" : ""}${e.anomaly} (${e.state}). On your field, September–March rain and snow averaged ${e.el_nino_sep_mar_in} in in El Niño winters (${e.el_nino_years}) against ${e.other_sep_mar_in} in in the others (${e.other_years}).`),
        el("p", {}, e.note));
    } catch { box.replaceChildren(el("p", { class: "muted" }, "The El Niño index could not be read.")); }
  }

  // ---------- field layers on the map (addendum 2, B) ----------
  const LAYERS = [
    { id: "photo", label: "Satellite photo" },
    { id: "crops", label: "Crop map" },
    { id: "slope", label: "Slope" },
  ];
  const fmap = { map: null, outline: null, overlay: null, fieldId: null, layer: "photo", cache: {} };

  function setupFieldMap() {
    const box = $("#field-mapbox");
    if (fmap.fieldId !== state.fieldId && fmap.map) {
      if (fmap.overlay) { fmap.map.removeLayer(fmap.overlay); fmap.overlay = null; }
      if (fmap.outline) fmap.map.removeLayer(fmap.outline);
      fmap.outline = L.geoJSON(state.field.geometry, { style: { color: "#4cf", weight: 3, fill: false } }).addTo(fmap.map);
      fmap.map.fitBounds(fmap.outline.getBounds(), { padding: [20, 20] });
      fmap.fieldId = state.fieldId;
      showLayer("photo");
    }
    box.open = window.matchMedia("(min-width: 1000px)").matches;
    if (box.open) ensureFieldMap();
  }

  function ensureFieldMap() {
    if (!state.field) return;
    if (!fmap.map) {
      fmap.map = L.map("field-map-main", { zoomControl: true, scrollWheelZoom: false, dragging: !L.Browser.mobile, tap: false });
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Esri World Imagery" }).addTo(fmap.map);
      $("#layer-control").replaceChildren(...LAYERS.map((l) => el("label", { class: "radio" },
        el("input", { type: "radio", name: "maplayer", value: l.id, checked: l.id === "photo" || null, onchange: () => showLayer(l.id) }), " ", l.label)));
    }
    setTimeout(() => {
      fmap.map.invalidateSize();
      if (fmap.fieldId !== state.fieldId) {
        if (fmap.outline) fmap.map.removeLayer(fmap.outline);
        fmap.outline = L.geoJSON(state.field.geometry, { style: { color: "#4cf", weight: 3, fill: false } }).addTo(fmap.map);
        fmap.fieldId = state.fieldId;
        showLayer(fmap.layer);
      }
      fmap.map.fitBounds(fmap.outline.getBounds(), { padding: [20, 20] });
    }, 30);
  }

  async function showLayer(id) {
    fmap.layer = id;
    document.querySelectorAll("#layer-control input").forEach((i) => { i.checked = i.value === id; });
    if (fmap.overlay) { fmap.map.removeLayer(fmap.overlay); fmap.overlay = null; }
    const legend = $("#layer-legend");
    const fid = state.fieldId;
    if (id === "photo") { legend.textContent = "Satellite photo; your field is outlined in blue."; return; }
    legend.textContent = "Loading…";
    try {
      if (id === "crops") {
        const { years } = await api("/api/overlay/years");
        const year = years[years.length - 1];
        const meta = fmap.cache[`crops${year}`] || (fmap.cache[`crops${year}`] = await api(`/api/overlay/${year}.json`));
        if (fid !== state.fieldId || fmap.layer !== id) return;
        fmap.overlay = L.imageOverlay(`/api/overlay/${year}.png`, meta.bounds, { opacity: 0.7, interactive: false }).addTo(fmap.map);
        legend.replaceChildren(`USDA crop map ${year} (it has errors): `, ...meta.legend.slice(0, 5).flatMap((l, i) => [i ? ", " : "",
          el("span", { class: "sw", style: `background:${l.color}` }), ` ${l.name.toLowerCase()}`]), ".");
      } else if (id === "slope") {
        const meta = fmap.cache[`slope${fid}`] || (fmap.cache[`slope${fid}`] = await api(`/api/field/${fid}/slope_map.json`));
        if (fid !== state.fieldId || fmap.layer !== id) return;
        fmap.overlay = L.imageOverlay(`/api/field/${fid}/slope.png`, meta.bounds, { opacity: 0.85, interactive: false }).addTo(fmap.map);
        const steep = meta.legend.find((g) => g.class === "high");
        legend.replaceChildren(el("span", { class: "sw", style: `background:${steep ? steep.color : "#B2182B"}` }),
          ` red stripes: steeper than 15% (${steep ? Math.round(steep.share * 100) : 0}% of the field), where winter cover matters most; orange 5–15%; pale under 5%.`);
      }
    } catch (err) {
      legend.textContent = `This layer could not be shown (${err.message}).`;
    }
  }

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
        backgroundColor: y.map((r) => (r.year === hy ? css("--series-hl") : css("--series-rain"))), borderRadius: 4, barPercentage: 0.8, categoryPercentage: 0.9 }] },
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
        el("span", {}, icon("triangle", "filled"), " along the bottom: drought year (extreme or exceptional drought over half the county)")));
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
        dry.has(y.year) ? "yes" : ""]))),
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
            backgroundColor: ys.map((y) => (y.year === 2021 ? css("--series-hl") : css("--series-rain"))), borderRadius: 4 }] },
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
      el("ol", { class: "sources-list" }, cfg.sources.filter((s) => /^S\d+$/.test(s.id)).map((s) => el("li", { value: s.id.slice(1), id: `src-${s.id}` },
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
        "Drop rotations that break a hard rule: no crop directly after itself; each crop sown after the one before is harvested; legumes at least 3 years apart; winter canola only after fallow; no two years running without a harvest.",
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
      table(["Crop", "Sown", "Harvested", "Water need", "Water use (for the too-dry caution)", "Basis"], crops.map((c) => [
        c.name, `${c.sowing_window.start}–${c.sowing_window.end}`, `${c.harvest_window.start}–${c.harvest_window.end}`,
        c.water_need ? "what it usually gets here" : "–",
        !c.water_use ? "–" : c.water_use.method === "from_yield" ? `typical yield ÷ ${c.water_use.lb_per_in_high} lb per inch (to ÷ ${c.water_use.lb_per_in_low})` : `${(c.water_use.use_mm / 25.4).toFixed(1)} in`,
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
      el("h3", {}, "Checked against what happened"), (() => { const b = el("div", {}, el("div", { class: "loading" }, "Loading…")); renderValidation(b); return b; })(),
      el("h3", {}, "What the model does not know"),
      el("ul", {}, (cfg.model_gaps || []).map((t) => el("li", {}, t))));
  }

  // ---------- routing ---------------------------------------------------------------------------------------
  function route() {
    const m = /field=([a-z0-9]+)/i.exec(location.hash);
    const r = /rec=([a-z0-9]+)/i.exec(location.hash);
    if (m) {
      setTab("field");
      if (m[1] !== state.fieldId || (r && r[1] !== state.recId) || $("#view-field").hidden) openField(m[1], r ? r[1] : null);
    } else {
      state.fieldId = null;
      state.recId = null;
      $("#view-field").hidden = true;
      $("#view-map").hidden = false;
      renderMyFields();
      setTimeout(() => map && map.invalidateSize(), 50);
    }
  }

  function initTheme() {
    let t = null;
    try { t = localStorage.getItem("fieldshift.theme"); } catch { /* storage off */ }
    const apply = (v) => { document.documentElement.dataset.theme = v; $("#btn-theme").setAttribute("aria-pressed", String(v === "dark")); };
    apply(t === "dark" ? "dark" : "light");
    $("#btn-theme").addEventListener("click", () => {
      const v = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      apply(v);
      try { localStorage.setItem("fieldshift.theme", v); } catch { /* storage off */ }
      chartDefaults();
      for (const ch of Object.values(state.charts)) ch.update();
    });
  }

  async function init() {
    initTheme();
    chartDefaults();
    try {
      state.config = await api("/api/config");
    } catch (err) {
      document.body.prepend(el("div", { class: "error", style: "margin:16px" }, `The app could not start: ${err.message}`));
      return;
    }
    state.db = loadDb();
    initMap();
    loadDemoFields();
    renderMyFields();
    $("#btn-back").addEventListener("click", () => { location.hash = ""; });
    $("#btn-adjust").addEventListener("click", openAdjust);
    $("#tab-field").addEventListener("click", () => setTab("field"));
    $("#tab-about").addEventListener("click", () => setTab("about"));
    document.addEventListener("toggle", onSectionToggle, true);
    $("#field-mapbox").addEventListener("toggle", (e) => { if (e.target.open) ensureFieldMap(); });
    window.addEventListener("hashchange", route);
    window.addEventListener("resize", () => { for (const ch of Object.values(state.charts)) ch.resize(); });
    route();
  }

  init();
})();
