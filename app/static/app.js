/* Gujarat News Intelligence — dashboard logic */
"use strict";

const $ = (sel) => document.querySelector(sel);

const DOMAINS = [
  "Transportation", "Agriculture", "Water Resources", "Technology",
  "Education", "Healthcare", "Industry & Economy", "Energy",
  "Urban Development", "Environment & Climate", "Governance & Policy", "Other",
];

const TYPE_LABELS = {
  directly_about_gujarat: ["About Gujarat", "tag-type-direct"],
  transferable_policy: ["Transferable", "tag-type-transfer"],
  national_impact: ["National impact", "tag-type-transfer"],
  not_relevant: ["Not relevant", ""],
};

const SCORE_LABELS = {
  implementation_feasibility: "Feasibility",
  expected_benefit: "Expected benefit",
  urgency: "Urgency",
  cost_burden: "Cost burden",
};

let pollTimer = null;

/* ---------- API helpers ---------- */
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

/* ---------- Init ---------- */
async function init() {
  const domainSel = $("#f-domain");
  for (const d of DOMAINS) {
    const opt = document.createElement("option");
    opt.value = d; opt.textContent = d;
    domainSel.appendChild(opt);
  }

  try {
    const health = await api("/api/health");
    const badge = $("#llm-badge");
    if (health.llm_enabled) {
      badge.textContent = `AI: ${health.model}`;
      badge.className = "badge badge-on";
    } else {
      badge.textContent = "AI off — heuristic mode";
      badge.className = "badge badge-off";
      badge.title = "Set ANTHROPIC_API_KEY in .env for intelligent analysis";
    }
  } catch { /* server not ready */ }

  $("#btn-run").addEventListener("click", startRun);
  $("#btn-prefs").addEventListener("click", openPrefs);
  $("#modal-close").addEventListener("click", () => $("#modal").classList.add("hidden"));
  $("#modal-save").addEventListener("click", savePrefs);
  $("#modal").addEventListener("click", (e) => {
    if (e.target === $("#modal")) $("#modal").classList.add("hidden");
  });

  let searchDebounce;
  $("#f-search").addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(refresh, 350);
  });
  for (const id of ["#f-domain", "#f-minscore", "#f-relevant"]) {
    $(id).addEventListener("change", refresh);
  }

  // If a run is already in progress (page reload mid-run), resume polling.
  const status = await api("/api/scrape/status").catch(() => null);
  if (status && status.running) beginPolling();

  await refresh();
}

/* ---------- Data refresh ---------- */
async function refresh() {
  const [stats, articles] = await Promise.all([
    api("/api/stats"),
    api(buildArticlesUrl()),
  ]);
  renderStats(stats);
  renderArticles(articles);
}

function buildArticlesUrl() {
  const p = new URLSearchParams();
  if ($("#f-relevant").checked) p.set("relevant_only", "true");
  const minScore = $("#f-minscore").value;
  if (minScore !== "0") p.set("min_score", minScore);
  if ($("#f-domain").value) p.set("domain", $("#f-domain").value);
  const q = $("#f-search").value.trim();
  if (q) p.set("search", q);
  return `/api/articles?${p.toString()}`;
}

function renderStats(s) {
  $("#stat-total").textContent = s.total;
  $("#stat-analyzed").textContent = s.analyzed;
  $("#stat-relevant").textContent = s.relevant;
  $("#stat-pending").textContent = s.pending;
}

/* ---------- Article cards ---------- */
function renderArticles(articles) {
  const container = $("#articles");
  container.innerHTML = "";
  if (!articles.length) {
    container.appendChild(buildEmpty());
    return;
  }
  const tpl = $("#card-template");
  for (const art of articles) {
    container.appendChild(buildCard(tpl, art));
  }
}

function buildEmpty() {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.innerHTML = `<div class="empty-icon">📰</div><h2>No matching articles</h2>
    <p>Try loosening the filters, or run the pipeline to fetch fresh news.</p>`;
  return div;
}

function buildCard(tpl, art) {
  const node = tpl.content.cloneNode(true);
  const card = node.querySelector(".card");
  const a = art.analysis || {};
  const score = art.overall_score ?? 0;

  // Score ring
  const cls = score >= 70 ? "score-high" : score >= 45 ? "score-mid" : "score-low";
  card.querySelector(".card-score").classList.add(cls);
  node.querySelector(".score-num").textContent = score;
  const circumference = 119.4;
  const fg = node.querySelector(".ring-fg");
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      fg.style.strokeDashoffset = circumference * (1 - score / 100);
    })
  );

  // Tags
  setTag(node, ".tag-domain", art.domain || a.domain);
  const [typeLabel, typeCls] = TYPE_LABELS[a.relevance_type] || ["", ""];
  const typeTag = node.querySelector(".tag-type");
  if (typeLabel) { typeTag.textContent = typeLabel; if (typeCls) typeTag.classList.add(typeCls); }
  else typeTag.remove();
  setTag(node, ".tag-origin", a.origin_state && a.origin_state !== "Unknown" ? `From: ${a.origin_state}` : "");
  const modeTag = node.querySelector(".tag-mode");
  if (art.analysis_mode === "heuristic") {
    modeTag.textContent = "Heuristic";
    modeTag.classList.add("tag-mode-heuristic");
    modeTag.title = "Analyzed by keyword fallback — set ANTHROPIC_API_KEY for AI analysis";
  } else modeTag.remove();

  // Title / summary
  const link = node.querySelector(".card-title a");
  link.textContent = art.title;
  link.href = art.url;
  node.querySelector(".card-summary").textContent =
    a.summary || (art.description || "").slice(0, 220);

  // Details
  node.querySelector(".card-reason").textContent = a.reason || "";
  const impl = node.querySelector(".card-impl");
  if (a.implementation_notes) impl.textContent = a.implementation_notes;
  else impl.remove();
  fillChips(node, ".meta-departments", a.departments);
  fillChips(node, ".meta-regions", a.regions);
  fillScoreBars(node, a.scores);

  // Footer
  node.querySelector(".card-source").textContent = art.source || "";
  node.querySelector(".card-date").textContent = formatDate(art.published);
  return node;
}

function setTag(node, sel, text) {
  const el = node.querySelector(sel);
  if (text) el.textContent = text;
  else el.remove();
}

function fillChips(node, blockSel, items) {
  const block = node.querySelector(blockSel);
  if (!items || !items.length) { block.remove(); return; }
  const chips = block.querySelector(".chips");
  for (const item of items) {
    const c = document.createElement("span");
    c.className = "chip";
    c.textContent = item;
    chips.appendChild(c);
  }
}

function fillScoreBars(node, scores) {
  const block = node.querySelector(".meta-scores");
  if (!scores) { block.remove(); return; }
  const wrap = block.querySelector(".score-bars");
  for (const [key, label] of Object.entries(SCORE_LABELS)) {
    if (scores[key] === undefined) continue;
    const val = scores[key];
    const row = document.createElement("div");
    row.className = "score-bar-row";
    row.innerHTML = `<span>${label}</span>
      <div class="score-bar-track"><div class="score-bar-fill" style="width:${val}%"></div></div>
      <span>${val}</span>`;
    wrap.appendChild(row);
  }
}

function formatDate(str) {
  if (!str) return "";
  const d = new Date(str);
  return isNaN(d) ? str : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/* ---------- Pipeline run ---------- */
async function startRun() {
  try {
    await api("/api/scrape", { method: "POST" });
  } catch (e) {
    if (!String(e.message).includes("progress")) { alert("Failed to start: " + e.message); return; }
  }
  beginPolling();
}

function beginPolling() {
  $("#btn-run").disabled = true;
  $("#run-banner").classList.remove("hidden");
  clearInterval(pollTimer);
  pollTimer = setInterval(pollStatus, 1500);
  pollStatus();
}

async function pollStatus() {
  const s = await api("/api/scrape/status").catch(() => null);
  if (!s) return;
  const text = $("#run-text");
  const bar = $("#run-progress");
  if (s.phase === "scraping") {
    text.textContent = `Scraping sources… ${s.fetched} articles fetched`;
    bar.style.width = "15%";
  } else if (s.phase === "analyzing") {
    text.textContent = `Analyzing ${s.analyzed}/${s.to_analyze} articles… (${s.relevant_found} relevant so far)`;
    bar.style.width = s.to_analyze ? `${15 + (s.analyzed / s.to_analyze) * 85}%` : "50%";
  } else if (s.phase === "error") {
    text.textContent = `Error: ${s.last_error}`;
  }
  if (!s.running && (s.phase === "done" || s.phase === "error" || s.phase === "idle")) {
    clearInterval(pollTimer);
    bar.style.width = "100%";
    setTimeout(() => {
      $("#run-banner").classList.add("hidden");
      $("#btn-run").disabled = false;
      bar.style.width = "0%";
    }, 1200);
    await refresh();
  }
}

/* ---------- Preferences ---------- */
async function openPrefs() {
  const p = await api("/api/preferences");
  $("#pref-interests").value = (p.interests || []).join("\n");
  $("#pref-ignore").value = (p.ignore_topics || []).join("\n");
  $("#pref-minscore").value = p.min_score_to_keep ?? 40;
  $("#pref-notes").value = p.notes || "";
  $("#modal").classList.remove("hidden");
}

async function savePrefs() {
  const lines = (v) => v.split("\n").map((s) => s.trim()).filter(Boolean);
  const body = {
    target_state: "Gujarat",
    interests: lines($("#pref-interests").value),
    ignore_topics: lines($("#pref-ignore").value),
    min_score_to_keep: parseInt($("#pref-minscore").value, 10) || 40,
    notes: $("#pref-notes").value.trim(),
  };
  await api("/api/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  $("#modal").classList.add("hidden");
}

init();
