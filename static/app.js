/* Leads Report — upload → map columns → 7-view report. Vanilla JS, no build. */
const $ = (id) => document.getElementById(id);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());
const qs = (o) => Object.entries(o).filter(([, v]) => v != null && v !== "")
  .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
const api = (path, params) => fetch(`${path}?${qs(params)}`).then((r) => r.json());

const state = {
  uploadId: "latest", anchor: null, projects: [],
  tab: "v1", project: null,
  window: "ltd",          // views 5,6,7
  level: "source",        // views 6,7
  v3level: "source", v3filters: [],  // view 3 cascade
};
const WINDOWS = [["ftd", "FTD"], ["mtd", "MTD"], ["ltd", "LTD"]];
const UTM_LEVELS = [["source", "UTM source"], ["campaign", "UTM campaign"],
  ["medium", "UTM medium"], ["term", "UTM term"]];
const TABS = [
  ["v1", "Leads count"], ["v2", "Lead quality"], ["v3", "UTM × quality"],
  ["v4", "Managers"], ["v5", "Manager × quality"], ["v6", "Lost × UTM"],
  ["v7", "Attempts × UTM"],
];

/* ============================ upload & mapping ============================ */
let preview = null;
$("upload-btn").addEventListener("click", () => {
  $("upload-panel").classList.toggle("hidden");
  showError("");
});
$("dropzone").addEventListener("click", () => $("file-input").click());
$("dropzone").addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file-input").click(); }
});
$("file-input").addEventListener("change", () => {
  if ($("file-input").files[0]) sendFile($("file-input").files[0]);
});
["dragover", "dragleave", "drop"].forEach((ev) =>
  $("dropzone").addEventListener(ev, (e) => {
    e.preventDefault();
    $("dropzone").classList.toggle("over", ev === "dragover");
    if (ev === "drop" && e.dataTransfer.files[0]) sendFile(e.dataTransfer.files[0]);
  })
);
function showError(msg) {
  $("upload-error").textContent = msg;
  $("upload-error").classList.toggle("hidden", !msg);
}
async function sendFile(file) {
  showError("");
  const body = new FormData();
  body.append("file", file);
  let res;
  try { res = await fetch("/api/uploads/preview", { method: "POST", body }); }
  catch { return showError("Upload failed — is the server running?"); }
  if (!res.ok) return showError((await res.json()).detail || "Upload failed");
  preview = await res.json();
  renderMapping();
}
function renderMapping() {
  $("drop-step").classList.add("hidden");
  $("map-step").classList.remove("hidden");
  $("map-meta").textContent =
    `${preview.filename}${preview.sheet ? ` · sheet "${preview.sheet}"` : ""} · ` +
    `${fmt(preview.row_count)} rows. Match each report field to a column from your file.`;
  const opts = (sel) => `<option value="">— not in this file —</option>` +
    preview.columns.map((c) =>
      `<option value="${esc(c)}"${c === sel ? " selected" : ""}>${esc(c)}</option>`).join("");
  $("map-table").innerHTML =
    `<thead><tr><th>Report field</th><th>Column in your file</th></tr></thead><tbody>` +
    Object.entries(preview.fields).map(([f, spec]) =>
      `<tr><td>${esc(spec.label)}${spec.required ? ' <span class="req">*</span>' : ""}</td>
       <td><select data-field="${f}">${opts(preview.suggested_mapping[f])}</select></td></tr>`
    ).join("") + `</tbody>`;
  const cols = preview.columns;
  $("sample-table").innerHTML =
    `<thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
    preview.sample_rows.map((r) =>
      `<tr>${cols.map((c) => `<td>${esc(r[c])}</td>`).join("")}</tr>`).join("") + `</tbody>`;
}
$("cancel-btn").addEventListener("click", resetUploadPanel);
function resetUploadPanel() {
  preview = null;
  $("file-input").value = "";
  $("map-step").classList.add("hidden");
  $("drop-step").classList.remove("hidden");
  $("upload-panel").classList.add("hidden");
  showError("");
}
$("commit-btn").addEventListener("click", async () => {
  const mapping = {};
  $("map-table").querySelectorAll("select").forEach((s) => { mapping[s.dataset.field] = s.value || null; });
  const res = await fetch("/api/uploads/commit", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: preview.token, mapping }),
  });
  if (!res.ok) return showError((await res.json()).detail || "Publish failed");
  const upload = await res.json();
  resetUploadPanel();
  await refreshUploads(upload.id);
  state.uploadId = upload.id;
  state.anchor = null;
  await loadReport();
});

/* ============================ upload selector ============================ */
async function refreshUploads(selectId) {
  const uploads = await (await fetch("/api/uploads")).json();
  const sel = $("upload-select");
  sel.innerHTML = uploads.map((u) =>
    `<option value="${u.id}">${esc(u.filename)} · ${u.uploaded_at.slice(0, 10)} (${fmt(u.row_count)} rows)</option>`
  ).join("") + (uploads.length > 1 ? `<option value="all">All uploads combined</option>` : "");
  if (selectId) sel.value = selectId;
  return uploads;
}
$("upload-select").addEventListener("change", () => {
  state.uploadId = $("upload-select").value;
  state.anchor = null;
  loadReport();
});
$("anchor-input").addEventListener("change", () => {
  state.anchor = $("anchor-input").value || null;
  overviewCache = null;
  render();
});

/* ============================ report load ============================ */
let overviewCache = null;

async function loadReport() {
  overviewCache = null;
  const ov = await fetchOverview();
  const empty = ov.empty;
  $("report").classList.toggle("hidden", empty);
  $("empty-state").classList.toggle("hidden", !empty);
  if (empty) { $("anchor-line").textContent = ""; return; }
  state.projects = ov.projects;
  if (!state.project || !state.projects.includes(state.project)) state.project = state.projects[0];
  state.anchor = ov.anchor;
  $("anchor-input").value = ov.anchor;
  renderTabs();
  render();
}

async function fetchOverview() {
  if (overviewCache) return overviewCache;
  overviewCache = await api("/api/report/overview", { upload_id: state.uploadId, anchor: state.anchor });
  return overviewCache;
}

function renderTabs() {
  $("tabs").innerHTML = TABS.map(([id, label], i) =>
    `<button class="tab${id === state.tab ? " active" : ""}" data-tab="${id}" role="tab">
       <span class="n">${i + 1}</span>${esc(label)}</button>`).join("");
  $("tabs").querySelectorAll(".tab").forEach((b) =>
    b.addEventListener("click", () => { state.tab = b.dataset.tab; renderTabs(); render(); }));
}

function anchorLine(ov) {
  const d = new Date(ov.anchor + "T00:00:00");
  const month = d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const day = d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  $("anchor-line").innerHTML =
    `<b>FTD</b> ${day} &nbsp;·&nbsp; <b>MTD</b> ${month} &nbsp;·&nbsp; ` +
    `<b>LTD</b> all time &nbsp;·&nbsp; ${fmt(ov.totals.ltd.total)} leads total`;
}

async function render() {
  const ov = await fetchOverview();
  if (ov.empty) return;
  anchorLine(ov);
  const fn = {
    v1: () => renderV1(ov), v2: () => renderV2(ov), v4: () => renderV4(ov),
    v3: renderV3, v5: renderV5, v6: renderV6, v7: renderV7,
  }[state.tab];
  await fn();
}

/* ============================ shared UI bits ============================ */
const qlChip = (rate) =>
  `<span class="chip ${rate >= 10 ? "hi" : rate >= 5 ? "mid" : "lo"}">${rate}%</span>`;

function projectControl() {
  return `<label class="ctl">Project
    <select id="project-select">${state.projects.map((p) =>
      `<option${p === state.project ? " selected" : ""}>${esc(p)}</option>`).join("")}</select></label>`;
}
function windowToggle() {
  return `<div class="ctl">Time window<div class="seg-toggle" id="window-toggle">${
    WINDOWS.map(([w, l]) => `<button data-w="${w}" class="${w === state.window ? "on" : ""}">${l}</button>`).join("")
  }</div></div>`;
}
function levelSelect() {
  return `<label class="ctl">UTM level
    <select id="level-select">${UTM_LEVELS.map(([lv, l]) =>
      `<option value="${lv}"${lv === state.level ? " selected" : ""}>${l}</option>`).join("")}</select></label>`;
}
function wireControls(onChange) {
  const ps = $("project-select");
  if (ps) ps.addEventListener("change", () => { state.project = ps.value; state.v3filters = []; state.v3level = "source"; onChange(); });
  const wt = $("window-toggle");
  if (wt) wt.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => { state.window = b.dataset.w; onChange(); }));
  const ls = $("level-select");
  if (ls) ls.addEventListener("change", () => { state.level = ls.value; onChange(); });
}

/* ===== View 1 — Project vs Leads count (FTD/MTD/LTD) ===== */
function renderV1(ov) {
  const rows = ov.view1;
  $("view").innerHTML = `
    <h2>1 · Project vs leads count</h2>
    <p class="lead">Leads created per project, split by report window. Bars compare the three windows side by side.</p>
    <div class="card"><div class="chartbox" id="v1-chart"></div></div>
    <div class="card tblwrap"><table>
      <thead><tr><th>Project</th><th class="num">FTD</th><th class="num">MTD</th><th class="num">LTD</th></tr></thead>
      <tbody>${rows.map((r) =>
        `<tr><td>${esc(r.project)}</td><td class="num">${fmt(r.ftd)}</td>
         <td class="num">${fmt(r.mtd)}</td><td class="num">${fmt(r.ltd)}</td></tr>`).join("")}
        <tr><td><b>All projects</b></td><td class="num"><b>${fmt(ov.totals.ftd.total)}</b></td>
        <td class="num"><b>${fmt(ov.totals.mtd.total)}</b></td>
        <td class="num"><b>${fmt(ov.totals.ltd.total)}</b></td></tr>
      </tbody></table></div>`;
  groupedHBar($("v1-chart"),
    rows.map((r) => ({ label: r.project, values: [r.ftd, r.mtd, r.ltd] })),
    [{ name: "FTD", color: css("--s-yellow") }, { name: "MTD", color: css("--s-blue") },
     { name: "LTD", color: css("--good") }], { label: "Leads count by window" });
}

/* ===== View 2 — Project vs Lead quality (FTD/MTD/LTD) ===== */
function renderV2(ov) {
  const rows = ov.view2;
  const head = `<thead><tr><th rowspan="2">Project</th>` +
    WINDOWS.map(([, l]) => `<th class="grp" colspan="3">${l}</th>`).join("") +
    `</tr><tr>` + WINDOWS.map(() => `<th class="num">QL</th><th class="num">Open</th><th class="num">Lost</th>`).join("") +
    `</tr></thead>`;
  const body = rows.map((r) => {
    const cells = WINDOWS.map(([w]) => {
      const q = r.windows[w];
      return `<td class="num">${fmt(q.ql)}</td><td class="num">${fmt(q.open)}</td><td class="num">${fmt(q.lost)}</td>`;
    }).join("");
    return `<tr><td>${esc(r.project)}</td>${cells}</tr>`;
  }).join("");
  $("view").innerHTML = `
    <h2>2 · Project vs lead quality</h2>
    <p class="lead">Qualified / open / lost counts per project across the three windows. The stacked bars show the LTD split.</p>
    <div class="card">
      <div class="legend">
        <span><span class="sw" style="background:var(--good)"></span>Qualified</span>
        <span><span class="sw" style="background:var(--s-blue)"></span>Open</span>
        <span><span class="sw" style="background:var(--lost)"></span>Lost</span>
      </div>
      <div class="chartbox" id="v2-chart"></div>
    </div>
    <div class="card tblwrap"><table>${head}<tbody>${body}</tbody></table></div>`;
  stackedHBar($("v2-chart"), rows.map((r) => ({
    label: r.project, suffix: `${r.windows.ltd.ql_rate}% QL`,
    segs: [
      { name: "Qualified", val: r.windows.ltd.ql, color: css("--good") },
      { name: "Open", val: r.windows.ltd.open, color: css("--s-blue") },
      { name: "Lost", val: r.windows.ltd.lost, color: css("--lost") },
    ],
  })), { label: "LTD lead quality by project", rightPad: 76 });
}

/* ===== View 3 — Project + UTM drill vs Lead quality (FTD/MTD/LTD) ===== */
async function renderV3() {
  $("view").innerHTML = `
    <h2>3 · UTM drill-down vs lead quality</h2>
    <p class="lead">Pick a project, then click a row to drill source → campaign → medium → term. Quality is shown for all three windows.</p>
    <div class="controls">${projectControl()}</div>
    <div id="v3-body"></div>`;
  wireControls(renderV3);
  const data = await api("/api/report/utm-quality", {
    upload_id: state.uploadId, anchor: state.anchor, project: state.project,
    level: state.v3level, filters: JSON.stringify(state.v3filters),
  });
  const crumbs = [`<span class="crumb${state.v3filters.length ? "" : " here"}" data-i="-1">${esc(state.project)}</span>`]
    .concat(state.v3filters.map((f, i) =>
      `<span class="sep">›</span><span class="crumb${i === state.v3filters.length - 1 ? " here" : ""}" data-i="${i}">${esc(f.value)}</span>`))
    .join("");
  const canDrill = !!data.next_level;
  const rowsHtml = data.rows.map((r) => {
    const w = r.windows;
    return `<tr class="${canDrill ? "drillable" : ""}" data-val="${esc(r.value)}">
      <td>${esc(r.value)}</td>
      <td class="num">${fmt(w.ftd.ql)}/${fmt(w.ftd.total)}</td>
      <td class="num">${fmt(w.mtd.ql)}/${fmt(w.mtd.total)}</td>
      <td class="num">${fmt(w.ltd.ql)}/${fmt(w.ltd.total)}</td>
      <td class="num">${qlChip(w.ltd.ql_rate)}</td>
      ${canDrill ? `<td class="drill-cue">drill ›</td>` : ""}</tr>`;
  }).join("");
  $("v3-body").innerHTML = `
    <div class="crumbs">${crumbs}</div>
    ${canDrill ? `<p class="drill-hint">Grouped by ${esc(data.level_label)} — click a row to drill into ${esc(UTM_LEVELS[UTM_LEVELS.findIndex(l => l[0] === data.level) + 1][1])}.</p>`
      : `<p class="drill-hint">Grouped by ${esc(data.level_label)} — deepest level.</p>`}
    <div class="card tblwrap"><table>
      <thead><tr><th>${esc(data.level_label)}</th>
        <th class="num">FTD QL/tot</th><th class="num">MTD QL/tot</th>
        <th class="num">LTD QL/tot</th><th class="num">LTD QL%</th>${canDrill ? "<th></th>" : ""}</tr></thead>
      <tbody>${rowsHtml || `<tr><td colspan="6">No leads.</td></tr>`}</tbody></table></div>`;
  $("v3-body").querySelectorAll(".crumb").forEach((c) =>
    c.addEventListener("click", () => {
      const i = +c.dataset.i;
      state.v3filters = state.v3filters.slice(0, i + 1);
      state.v3level = i < 0 ? "source" : UTM_LEVELS[i + 1][0];
      renderV3();
    }));
  if (canDrill) $("v3-body").querySelectorAll("tr.drillable").forEach((tr) =>
    tr.addEventListener("click", () => {
      state.v3filters = [...state.v3filters, { level: data.level, value: tr.dataset.val }];
      state.v3level = data.next_level;
      renderV3();
    }));
}

/* ===== View 4 — Project with allocated sales managers ===== */
function renderV4(ov) {
  $("view").innerHTML = `
    <h2>4 · Projects with allocated sales managers</h2>
    <p class="lead">Who is working each project, and how many leads each manager holds (LTD).</p>
    <div class="proj-cards">${ov.view4.map((p) => `
      <div class="proj-card">
        <h3>${esc(p.project)}</h3>
        <div class="meta">${fmt(p.total)} leads · ${p.manager_count} manager${p.manager_count === 1 ? "" : "s"}</div>
        <div class="mgr-chips">${p.managers.map((m) =>
          `<span class="mgr-chip">${esc(m.name)} <b>${fmt(m.total)}</b></span>`).join("")}</div>
      </div>`).join("")}</div>`;
}

/* ===== View 5 — Project + manager drill vs Lead quality ===== */
async function renderV5() {
  $("view").innerHTML = `
    <h2>5 · Manager drill-down vs lead quality</h2>
    <p class="lead">Per-manager qualified / open / lost split for the selected project and window, with average call attempts.</p>
    <div class="controls">${projectControl()}${windowToggle()}</div>
    <div id="v5-body"></div>`;
  wireControls(renderV5);
  const data = await api("/api/report/managers", {
    upload_id: state.uploadId, anchor: state.anchor, project: state.project, window: state.window,
  });
  $("v5-body").innerHTML = `
    <div class="card tblwrap"><table>
      <thead><tr><th>Manager</th><th class="num">Leads</th><th class="num">QL</th>
        <th class="num">Open</th><th class="num">Lost</th><th class="num">QL rate</th>
        <th class="num">Avg attempts</th></tr></thead>
      <tbody>${data.rows.map((m) =>
        `<tr><td>${esc(m.manager)}</td><td class="num">${fmt(m.total)}</td><td class="num">${fmt(m.ql)}</td>
         <td class="num">${fmt(m.open)}</td><td class="num">${fmt(m.lost)}</td>
         <td class="num">${qlChip(m.ql_rate)}</td><td class="num">${m.avg_attempts ?? "—"}</td></tr>`).join("")
        || `<tr><td colspan="7">No leads in this window.</td></tr>`}</tbody></table></div>`;
}

/* ===== View 6 — Project + Reason for lost, UTM drill vs count ===== */
async function renderV6() {
  $("view").innerHTML = `
    <h2>6 · Reason for lost by UTM</h2>
    <p class="lead">Lost leads for the selected project, broken down by reason and coloured by ${esc("UTM value")}. Stacked bars sum to each reason's total.</p>
    <div class="controls">${projectControl()}${levelSelect()}${windowToggle()}</div>
    <div id="v6-body"></div>`;
  wireControls(renderV6);
  const data = await api("/api/report/lost-utm", {
    upload_id: state.uploadId, anchor: state.anchor, project: state.project,
    window: state.window, level: state.level,
  });
  const palette = [css("--critical"), css("--s-blue"), css("--s-yellow"), css("--good"),
    css("--violet"), css("--lost"), css("--muted")];
  const colorOf = {};
  data.columns.forEach((c, i) => (colorOf[c] = palette[i % palette.length]));
  const legend = data.columns.map((c) =>
    `<span><span class="sw" style="background:${colorOf[c]}"></span>${esc(c)}</span>`).join("");
  const rows = data.reasons.map((r) => ({
    label: r.reason, suffix: String(r.total),
    segs: data.columns.map((c) => ({ name: c, val: r.segments[c] || 0, color: colorOf[c] })),
  }));
  $("v6-body").innerHTML = `
    <div class="card">
      <div class="legend">${legend || '<span class="note">No lost leads.</span>'}</div>
      <div class="chartbox" id="v6-chart"></div>
    </div>
    <div class="card tblwrap"><table>
      <thead><tr><th>Reason for lost</th>${data.columns.map((c) =>
        `<th class="num">${esc(c)}</th>`).join("")}<th class="num">Total</th></tr></thead>
      <tbody>${data.reasons.map((r) =>
        `<tr><td>${esc(r.reason)}</td>${data.columns.map((c) =>
          `<td class="num">${fmt(r.segments[c] || 0)}</td>`).join("")}<td class="num"><b>${fmt(r.total)}</b></td></tr>`).join("")
        || `<tr><td colspan="${data.columns.length + 2}">No lost leads in this window.</td></tr>`}</tbody></table></div>
    <p class="drill-hint">${fmt(data.total_lost)} lost leads · grouped by ${esc(data.level_label)}.</p>`;
  if (rows.length) stackedHBar($("v6-chart"), rows, { label: "Lost reasons by UTM", leftPad: 180, rightPad: 56 });
  else $("v6-chart").innerHTML = '<p class="note">No lost leads in this window.</p>';
}

/* ===== View 7 — Project + Lead quality, UTM drill vs no. of attempts ===== */
async function renderV7() {
  $("view").innerHTML = `
    <h2>7 · Attempts by UTM and lead quality</h2>
    <p class="lead">Average call attempts per ${esc("UTM value")}, split by outcome — how hard the team worked each source before it qualified or was lost.</p>
    <div class="controls">${projectControl()}${levelSelect()}${windowToggle()}</div>
    <div id="v7-body"></div>`;
  wireControls(renderV7);
  const data = await api("/api/report/attempts-utm", {
    upload_id: state.uploadId, anchor: state.anchor, project: state.project,
    window: state.window, level: state.level,
  });
  const series = [{ name: "QL", color: css("--good") }, { name: "Open", color: css("--s-blue") },
    { name: "Lost", color: css("--lost") }];
  $("v7-body").innerHTML = `
    <div class="card">
      <div class="legend">${series.map((s) =>
        `<span><span class="sw" style="background:${s.color}"></span>${s.name} avg attempts</span>`).join("")}</div>
      <div class="chartbox" id="v7-chart"></div>
    </div>
    <div class="card tblwrap"><table>
      <thead><tr><th>${esc(data.level_label)}</th><th class="num">Leads</th>
        <th class="num">Avg (all)</th><th class="num">QL avg</th><th class="num">Open avg</th>
        <th class="num">Lost avg</th></tr></thead>
      <tbody>${data.rows.map((r) =>
        `<tr><td>${esc(r.value)}</td><td class="num">${fmt(r.total)}</td>
         <td class="num">${r.avg_attempts ?? "—"}</td>
         <td class="num">${r.quality.QL.avg_attempts ?? "—"}</td>
         <td class="num">${r.quality.Open.avg_attempts ?? "—"}</td>
         <td class="num">${r.quality.Lost.avg_attempts ?? "—"}</td></tr>`).join("")
        || `<tr><td colspan="6">No leads in this window.</td></tr>`}</tbody></table></div>`;
  const rows = data.rows.map((r) => ({
    label: r.value,
    values: [r.quality.QL.avg_attempts || 0, r.quality.Open.avg_attempts || 0, r.quality.Lost.avg_attempts || 0],
  }));
  if (rows.length) groupedHBar($("v7-chart"), rows, series, { label: "Avg attempts by UTM and quality", decimals: 1 });
  else $("v7-chart").innerHTML = '<p class="note">No leads in this window.</p>';
}

/* ============================ chart helpers ============================ */
function niceMax(v) {
  if (v <= 0) return 1;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / step) * step;
}
function attachTip(box, els, html) {
  const tip = document.createElement("div");
  tip.className = "tip";
  box.appendChild(tip);
  els.forEach((el) => {
    el.addEventListener("mousemove", (e) => {
      tip.style.display = "block";
      tip.innerHTML = html(el);
      const bx = box.getBoundingClientRect();
      let tl = e.clientX - bx.left + 14;
      if (tl + 220 > bx.width) tl -= 240;
      tip.style.left = tl + "px";
      tip.style.top = e.clientY - bx.top - 34 + "px";
    });
    el.addEventListener("mouseleave", () => (tip.style.display = "none"));
  });
}
function clip(s, n) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }

function stackedHBar(box, rows, opts) {
  const W = Math.max(560, box.clientWidth), rowH = 32;
  const m = { t: 6, r: opts.rightPad ?? 64, l: opts.leftPad ?? 160, b: 24 };
  const H = m.t + rows.length * rowH + m.b, iw = W - m.l - m.r;
  const max = niceMax(Math.max(1, ...rows.map((r) => r.segs.reduce((a, s) => a + s.val, 0))));
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${esc(opts.label)}">`;
  for (let g = 0; g <= max; g += max / 5) {
    const gx = m.l + iw * g / max;
    s += `<line x1="${gx}" x2="${gx}" y1="${m.t}" y2="${H - m.b}" stroke="${css("--grid")}"/>`;
    s += `<text x="${gx}" y="${H - 6}" text-anchor="middle">${Math.round(g)}</text>`;
  }
  rows.forEach((r, ri) => {
    const yy = m.t + ri * rowH, bh = 18;
    s += `<text x="${m.l - 10}" y="${yy + bh / 2 + 4}" text-anchor="end" class="dl">${esc(clip(r.label, 21))}</text>`;
    let cx = m.l;
    r.segs.forEach((seg, si) => {
      const w = iw * seg.val / max;
      if (w <= 0) return;
      const isLast = r.segs.slice(si + 1).every((z) => z.val === 0);
      const bw = Math.max(w - 1, 0.5);
      s += isLast
        ? `<path d="M${cx},${yy} h${Math.max(bw - 4, 0)} q4,0 4,4 v${bh - 8} q0,4 -4,4 h${-Math.max(bw - 4, 0)} z" fill="${seg.color}" class="seg" data-row="${esc(r.label)}" data-seg="${esc(seg.name)}" data-v="${seg.val}"/>`
        : `<rect x="${cx}" y="${yy}" width="${bw}" height="${bh}" fill="${seg.color}" class="seg" data-row="${esc(r.label)}" data-seg="${esc(seg.name)}" data-v="${seg.val}"/>`;
      cx += w + 1;
    });
    if (r.suffix) s += `<text x="${cx + 7}" y="${yy + bh / 2 + 4}" class="dl-b">${esc(r.suffix)}</text>`;
  });
  s += `</svg>`;
  box.innerHTML = s;
  attachTip(box, box.querySelectorAll(".seg"),
    (el) => `<b>${el.dataset.row}</b> — ${el.dataset.seg}: <b>${fmt(el.dataset.v)}</b>`);
}

function groupedHBar(box, rows, series, opts) {
  const W = Math.max(560, box.clientWidth), rowH = 20 + series.length * 13;
  const m = { t: 6, r: 52, l: 176, b: 24 };
  const H = m.t + rows.length * rowH + m.b, iw = W - m.l - m.r;
  const dec = opts.decimals ?? 0;
  const max = niceMax(Math.max(1, ...rows.flatMap((r) => r.values)));
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${esc(opts.label)}">`;
  for (let g = 0; g <= max; g += max / 5) {
    const gx = m.l + iw * g / max;
    s += `<line x1="${gx}" x2="${gx}" y1="${m.t}" y2="${H - m.b}" stroke="${css("--grid")}"/>`;
    s += `<text x="${gx}" y="${H - 6}" text-anchor="middle">${(+g).toFixed(dec ? 0 : 0)}</text>`;
  }
  const bh = 11;
  rows.forEach((r, ri) => {
    const y0 = m.t + ri * rowH + 6;
    s += `<text x="${m.l - 10}" y="${y0 + (series.length * bh) / 2 + 3}" text-anchor="end" class="dl">${esc(clip(r.label, 22))}</text>`;
    r.values.forEach((v, si) => {
      const yy = y0 + si * bh, w = iw * v / max, bw = Math.max(w - 1, 0);
      s += `<path d="M${m.l},${yy} h${Math.max(bw - 3, 0)} q3,0 3,3 v${bh - 5} q0,3 -3,3 h${-Math.max(bw - 3, 0)} z" fill="${series[si].color}" class="gb" data-row="${esc(r.label)}" data-seg="${esc(series[si].name)}" data-v="${dec ? v.toFixed(dec) : v}"/>`;
      if (w > 26) s += `<text x="${m.l + w - 4}" y="${yy + bh - 2}" text-anchor="end" class="dl-b" style="font-size:9.5px">${dec ? v.toFixed(dec) : v}</text>`;
    });
  });
  s += `</svg>`;
  box.innerHTML = s;
  attachTip(box, box.querySelectorAll(".gb"),
    (el) => `<b>${el.dataset.row}</b> — ${el.dataset.seg}: <b>${el.dataset.v}</b>`);
}

/* ============================ init ============================ */
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (!$("report").classList.contains("hidden")) render(); }, 160);
});
if (window.matchMedia)
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!$("report").classList.contains("hidden")) render();
  });

(async () => {
  const uploads = await refreshUploads();
  if (uploads.length) { state.uploadId = uploads[0].id; await loadReport(); }
  else {
    $("empty-state").classList.remove("hidden");
    $("upload-panel").classList.remove("hidden");
  }
})();
