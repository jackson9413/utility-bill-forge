"use strict";

const BUCKET_COLORS = {
  energy: "#58a6ff",
  delivery: "#3fb950",
  fuel: "#d29922",
  demand: "#db6d28",
  tax: "#bc8cff",
  fee: "#f85149",
  rider: "#39c5cf",
  base: "#8b98a9",
  credit: "#a371f7",
  deposit: "#6e7681",
  adjustment: "#f0883e",
  unclassified: "#49525e"
};

const VERDICT_COLORS = {
  clean_bill: "#3fb950",
  mostly_fine: "#58a6ff",
  worth_a_call: "#d29922",
  review_needed: "#db6d28",
  dispute_candidate: "#f85149"
};

const AXIS_COLORS = {
  clarity: "#58a6ff",
  correctness: "#3fb950",
  value: "#d29922",
  structure: "#bc8cff",
  control: "#39c5cf"
};

let currentResult = null;
let currentFilter = "all";

const $ = (id) => document.getElementById(id);

function esc(v) {
  return String(v === null || v === undefined ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function money(v) {
  if (v === null || v === undefined) return "-";
  return "$" + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function num(v, digits) {
  if (v === null || v === undefined) return "-";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits === undefined ? 0 : digits });
}

/* Rate display depends on the unit: kWh reads in cents, gas in dollars per
   therm, water in dollars per unit. */
function rate(v, unit) {
  if (v === null || v === undefined) return "-";
  if (unit === "kWh") return (Number(v) * 100).toFixed(2) + "\u00a2/kWh";
  if (unit === "therm" || unit === "MMBtu") return "$" + Number(v).toFixed(3) + "/therm";
  if (unit === "gal") return "$" + Number(v).toFixed(4) + "/gal";
  if (unit === "ccf") return "$" + Number(v).toFixed(3) + "/ccf";
  return "$" + Number(v).toFixed(4) + "/" + (unit || "unit");
}

function scoreColor(score) {
  if (score >= 85) return "#3fb950";
  if (score >= 70) return "#58a6ff";
  if (score >= 55) return "#d29922";
  if (score >= 40) return "#db6d28";
  return "#f85149";
}

async function loadSamples() {
  try {
    const res = await fetch("/api/samples");
    const data = await res.json();
    const list = $("sample-list");
    list.innerHTML = "";
    (data.samples || []).forEach((s) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-ghost sample-item";
      btn.innerHTML = "<strong>" + esc(s.title) + "</strong><span>" + esc(s.note) + "</span>";
      btn.addEventListener("click", async () => {
        const r = await fetch("/api/sample/" + encodeURIComponent(s.id));
        const sample = await r.json();
        $("bill-text").value = sample.text;
        $("utility").value = sample.utility || "auto";
        $("customer-class").value = sample.customer_class || "auto";
        $("profile").value = sample.profile || "residential";
        $("sample-drawer").classList.add("hidden");
        runAnalysis();
      });
      list.appendChild(btn);
    });
  } catch (e) {
    $("sample-list").innerHTML = '<p class="hint">Could not load samples.</p>';
  }
}

async function runAnalysis() {
  const text = $("bill-text").value.trim();
  const status = $("status");
  if (!text) {
    status.textContent = "Paste a bill first.";
    status.className = "status error";
    return;
  }
  status.textContent = "Analyzing...";
  status.className = "status";
  $("analyze").disabled = true;

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: text,
        utility: $("utility").value,
        customer_class: $("customer-class").value,
        profile: $("profile").value
      })
    });
    const data = await res.json();
    if (!res.ok) {
      status.textContent = data.error || "Analysis failed.";
      status.className = "status error";
      return;
    }
    currentResult = data;
    render(data);
    status.textContent = "Done.";
    loadHistory();
  } catch (e) {
    status.textContent = "Something went wrong: " + e.message;
    status.className = "status error";
  } finally {
    $("analyze").disabled = false;
  }
}

function render(data) {
  const primary = data.primary;
  const m = primary.metrics;
  const score = primary.score;
  $("results").classList.remove("hidden");

  // --- score header ---
  $("score-value").textContent = score.overall.toFixed(0);
  $("score-value").style.color = scoreColor(score.overall);
  const vp = $("verdict-pill");
  vp.textContent = score.verdict_label;
  vp.style.color = VERDICT_COLORS[score.verdict] || "#e6edf3";
  vp.style.borderColor = (VERDICT_COLORS[score.verdict] || "#2a3441") + "66";
  vp.style.background = ((VERDICT_COLORS[score.verdict] || "#2a3441") + "1a");
  $("verdict-blurb").textContent = score.verdict_blurb;

  const metaBits = [];
  if (m.period_start) metaBits.push("<span>Period <b>" + esc(m.period_start) + " to " + esc(m.period_end || "?") + "</b></span>");
  if (m.usage) metaBits.push("<span>Usage <b>" + num(m.usage) + " " + esc(m.unit || "") + "</b></span>");
  metaBits.push("<span>Utility <b>" + esc(m.utility || "unknown") + "</b></span>");
  metaBits.push("<span>Type <b>" + esc(m.customer_class || "residential") + "</b></span>");
  $("bill-meta").innerHTML = metaBits.join("");

  // --- axes ---
  $("axis-row").innerHTML = score.axes.map((a) => {
    const c = AXIS_COLORS[a.key] || "#58a6ff";
    return '<div class="axis-pill">'
      + '<div class="ax-name">' + esc(a.label) + '</div>'
      + '<div class="ax-score" style="color:' + scoreColor(a.score) + '">' + a.score.toFixed(0) + '</div>'
      + '<div class="ax-desc">' + esc(a.description) + '</div>'
      + '<div class="bar"><span style="width:' + a.score + '%;background:' + c + '"></span></div>'
      + '</div>';
  }).join("");

  $("caps").innerHTML = (score.caps || []).length
    ? '<p class="cap-line"><b>Structural caps applied:</b></p>' +
      score.caps.map((c) => '<div class="cap-line">- ' + esc(c.axis) + " capped at " + c.limit + ": " + esc(c.reason) + "</div>").join("")
    : "";

  renderBreakdown(primary);
  renderFindings(primary.findings || []);
  renderSavings(primary.savings || []);
  renderCallScript(primary.call_script);
  renderComparison(data.comparison);

  const sid = data.session_id;
  if (sid) {
    $("export-md").href = "/api/export/" + sid + "?fmt=md";
    $("export-json").href = "/api/export/" + sid + "?fmt=json";
  }
}

function renderBreakdown(primary) {
  const m = primary.metrics;
  const buckets = m.buckets || {};
  const labels = m.bucket_labels || {};
  const entries = Object.keys(buckets)
    .filter((k) => Math.abs(buckets[k]) > 0.004)
    .map((k) => ({ key: k, amount: buckets[k] }))
    .sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));

  const total = entries.reduce((s, e) => s + Math.abs(e.amount), 0) || 1;

  let stack = "";
  let legend = "";
  entries.forEach((e) => {
    const pct = (Math.abs(e.amount) / total) * 100;
    const color = BUCKET_COLORS[e.key] || "#49525e";
    stack += '<div style="width:' + pct.toFixed(2) + "%;background:" + color + '" title="' + esc(labels[e.key] || e.key) + '"></div>';
    legend += '<div class="legend-row"><span class="swatch" style="background:' + color + '"></span>'
      + "<span>" + esc(labels[e.key] || e.key) + "</span>"
      + '<span class="lg-amt">' + money(e.amount) + " (" + pct.toFixed(0) + "%)</span></div>";
  });

  // Rate cards
  const cards = [];
  cards.push('<div class="rate-card hero"><div class="rc-label">All-in rate</div><div class="rc-value">'
    + rate(m.all_in_rate, m.unit) + "</div><div class="rc-note">Everything on the bill divided by usage"
    + (m.one_time ? ", excluding one-off charges" : "") + ".</div></div>");
  if (m.commodity_rate) {
    cards.push('<div class="rate-card"><div class="rc-label">Commodity rate</div><div class="rc-value">'
      + rate(m.commodity_rate, m.unit) + "</div><div class="rc-note">Just the energy itself.</div></div>");
  }
  if (m.marginal_rate) {
    cards.push('<div class="rate-card"><div class="rc-label">Marginal rate</div><div class="rc-value">'
      + rate(m.marginal_rate, m.unit) + "</div><div class="rc-note">What your next unit of usage costs"
      + (m.tier_gap && m.tier_gap > 1.15 ? " - higher than your average" : "") + ".</div></div>");
  }
  if (m.fixed_share !== null && m.fixed_share !== undefined) {
    cards.push('<div class="rate-card"><div class="rc-label">Fixed share</div><div class="rc-value">'
      + (m.fixed_share * 100).toFixed(0) + "%</div><div class="rc-note">" + money(m.fixed)
      + " of the bill does not move when you use less.</div></div>");
  }

  // Tier ladder
  let tierHtml = "";
  const tiers = (primary.structure && primary.structure.tiers) || [];
  if (tiers.length) {
    const ti = m.tier_info || {};
    tierHtml = "<h3 style="font-size:13.5px;margin:20px 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px">Tier ladder</h3>";
    tierHtml += '<table class="tier-table"><thead><tr><th>Tier</th><th>Range</th><th class="num">Rate</th><th class="num">Your position</th></tr></thead><tbody>';
    tiers.forEach((t, i) => {
      const lo = t.from_kwh === null || t.from_kwh === undefined ? "?" : num(t.from_kwh);
      const hi = t.to_kwh === null || t.to_kwh === undefined ? "and up" : num(t.to_kwh);
      const cur = ti.current_tier === i ? " you are here" : "";
      const cls = ti.current_tier === i ? ' class="tier-current"' : "";
      tierHtml += "<tr" + cls + "><td>" + esc(t.label || ("Tier " + (i + 1))) + "</td>"
        + "<td>" + lo + " - " + hi + " " + esc(t.unit || "") + "</td>"
        + '<td class="num tier-rate">' + rate(t.rate, t.unit) + "</td>"
        + '<td class="num">' + cur + "</td></tr>";
    });
    tierHtml += "</tbody></table>";
    if (ti.kwh_to_cheaper_tier) {
      tierHtml += '<p class="hint" style="margin-top:8px">You are <b style="color:var(--text)">'
        + num(ti.kwh_to_cheaper_tier) + " " + esc(m.unit || "") + "</b> into your most expensive tier. "
        + "Shedding that usage drops you back to the cheaper rate - worth about <b style="color:var(--green)">"
        + money(ti.savings_at_cheaper_tier) + "/month</b>.</p>";
    }
  }

  $("breakdown").innerHTML =
    '<div class="rate-cards">' + cards.join("") + "</div>"
    + '<div class="breakdown-layout"><div><div class="stack">' + stack + "</div>"
    + '<div class="legend">' + legend + "</div>" + tierHtml + "</div>"
    + "<div><table><thead><tr><th>Line item</th><th class="num">Amount</th></tr></thead><tbody>"
    + (primary.bill.items || []).filter((it) => it.role === "charge").map((it) =>
        "<tr><td>" + esc(it.label) + "</td><td class="num">" + money(it.amount) + "</td></tr>").join("")
    + "</tbody></table></div></div>";
}

function renderFindings(findings) {
  const counts = { all: findings.length, high: 0, medium: 0, low: 0 };
  findings.forEach((f) => { counts[f.severity] = (counts[f.severity] || 0) + 1; });

  const filters = [["all", "All"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]];
  $("finding-filters").innerHTML = filters.map(([id, label]) =>
    '<button class="chip' + (currentFilter === id ? " active" : "") + '" data-filter="' + id + '">'
    + label + " (" + (counts[id] || 0) + ")</button>").join("");

  const shown = currentFilter === "all" ? findings : findings.filter((f) => f.severity === currentFilter);
  if (!shown.length) {
    $("findings").innerHTML = '<div class="empty-state">'
      + (findings.length ? "Nothing at this severity." : "Nothing wrong with this bill. That is the good outcome.")
      + "</div>";
    return;
  }

  $("findings").innerHTML = shown.map((f) =>
    '<div class="finding ' + f.severity + '">'
    + '<div class="finding-head"><span class="sev">' + esc(f.severity) + "</span>"
    + "<h3>" + esc(f.title) + "</h3>"
    + (f.annual_savings ? '<span class="savings-tag">~$' + num(f.annual_savings) + "/yr</span>" : "")
    + "</div>"
    + '<div class="evidence">' + esc(f.evidence) + "</div>"
    + '<p class="why"><b>Why it matters:</b> ' + esc(f.why) + "</p>"
    + '<p class="fix"><b>What to do:</b> ' + esc(f.fix) + "</p>"
    + "</div>").join("");

  document.querySelectorAll("#finding-filters .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      currentFilter = chip.dataset.filter;
      renderFindings(findings);
    });
  });
}

function renderSavings(scenarios) {
  if (!scenarios.length) {
    $("savings").innerHTML = '<div class="empty-state">No savings scenarios detected on this bill.</div>';
    return;
  }
  const quantified = scenarios.filter((s) => s.annual_estimate);
  const total = quantified.reduce((s, x) => s + x.annual_estimate, 0);

  let html = "";
  if (total > 0) {
    html += '<p class="hint" style="margin:0 0 14px">Identified annual opportunity: <b style="color:var(--green);font-size:16px">$'
      + num(total) + "</b> / year. These are estimates built from this bill's own numbers, not guarantees.</p>";
  }
  html += scenarios.map((s) =>
    '<div class="scenario"><div class="scenario-head"><h3>' + esc(s.title) + "</h3>"
    + (s.annual_estimate ? '<span class="amount">~$' + num(s.annual_estimate) + "/yr</span>" : '<span class="conf">action needed</span>')
    + '<span class="conf ' + esc(s.confidence) + '">' + esc(s.confidence) + " confidence</span></div>"
    + "<p>" + esc(s.detail) + "</p>"
    + '<p class="basis">Basis: ' + esc(s.basis) + "</p>"
    + (s.steps && s.steps.length ? "<ul>" + s.steps.map((st) => "<li>" + esc(st) + "</li>").join("") + "</ul>" : "")
    + "</div>").join("");
  $("savings").innerHTML = html;
}

function renderCallScript(script) {
  const el = $("call-script");
  if (!script || !script.questions || !script.questions.length) {
    el.innerHTML = '<div class="empty-state">No questions to ask on this one.</div>';
    return;
  }
  let html = '<ol class="script-list">';
  script.questions.forEach((q) => {
    html += "<li><span class=\"q-text\">" + esc(q.question) + "</span>"
      + '<span class="q-because">because: ' + esc(q.because || "") + "</span></li>";
  });
  html += "</ol>";
  if (script.prep && script.prep.length) {
    html += '<h3 style="font-size:13px;margin:18px 0 8px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px">Before you call</h3><ul class="prep-list">';
    script.prep.forEach((p) => { html += "<li>" + esc(p) + "</li>"; });
    html += "</ul>";
  }
  if (script.dispute_hint) {
    html += '<div class="dispute-box"><b>Is it worth disputing?</b><p>' + esc(script.dispute_hint) + "</p></div>";
  }
  el.innerHTML = html;
}

function renderComparison(comparison) {
  const panel = $("comparison-panel");
  if (!comparison || !comparison.rows || comparison.rows.length < 2) {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  let html = '<table><thead><tr><th>Bill</th><th>Period</th><th class="num">Usage</th><th class="num">Total</th>'
    + '<th class="num">All-in rate</th><th class="num">Fixed</th><th class="num">Score</th></tr></thead><tbody>';
  comparison.rows.forEach((r) => {
    html += "<tr><td>#" + (r.index + 1) + "</td><td>" + esc(r.period_start || "?") + "</td>"
      + '<td class="num">' + (r.usage ? num(r.usage) + " " + esc(r.unit || "") : "-") + "</td>"
      + '<td class="num">' + money(r.total) + "</td>"
      + '<td class="num">' + (r.all_in_rate ? rate(r.all_in_rate, r.unit) : "-") + "</td>"
      + '<td class="num">' + money(r.fixed) + "</td>"
      + '<td class="num">' + num(r.score) + "</td></tr>";
  });
  html += "</tbody></table>";
  if (comparison.notes && comparison.notes.length) {
    html += '<div style="margin-top:14px">';
    comparison.notes.forEach((n) => {
      html += '<div class="finding ' + esc(n.severity) + '"><div class="finding-head"><span class="sev">'
        + esc(n.severity) + '</span><h3>' + esc(n.title) + "</h3></div>"
        + "<p>" + esc(n.detail) + "</p></div>";
    });
    html += "</div>";
  }
  $("comparison").innerHTML = html;
}

async function loadHistory() {
  try {
    const res = await fetch("/api/sessions");
    const data = await res.json();
    const rows = data.sessions || [];
    if (!rows.length) {
      $("history").innerHTML = '<div class="empty-state">No past analyses yet.</div>';
      return;
    }
    $("history").innerHTML = rows.map((s) => {
      const stars = [1, 2, 3, 4, 5].map((i) =>
        '<button class="star' + (s.rating >= i ? " on" : "") + '" data-id="' + s.id + '" data-star="' + i
        + '" title="' + i + '">&#9733;</button>').join("");
      return '<div class="history-row" data-id="' + s.id + '">'
        + '<div class="hr-main"><div class="hr-title">'
        + esc(s.utility || "bill") + " - " + (s.usage ? num(s.usage) + " " + esc(s.unit || "") : "usage n/a")
        + " - " + money(s.total) + "</div>"
        + '<div class="hr-sub">' + esc(s.created_at || "") + " - score " + num(s.score)
        + " (" + esc(s.verdict || "") + ")</div></div>"
        + '<div class="stars">' + stars + "</div>"
        + '<input class="notes-input" data-id="' + s.id + '" value="' + esc(s.notes || "") + '" placeholder="Add a note">'
        + '<a class="btn btn-ghost" href="/api/export/' + s.id + '?fmt=md" download>MD</a>'
        + '<a class="btn btn-ghost" href="/api/export/' + s.id + '?fmt=json" download>JSON</a>'
        + "</div>";
    }).join("");

    document.querySelectorAll(".star").forEach((st) => {
      st.addEventListener("click", async () => {
        const id = st.dataset.id;
        const star = Number(st.dataset.star);
        const stars = st.parentNode.querySelectorAll(".star");
        const current = Array.from(stars).findIndex((s) => s.classList.contains("on")) + 1;
        const value = current === star ? 0 : star;
        await fetch("/api/sessions/" + id, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rating: value })
        });
        loadHistory();
      });
    });

    document.querySelectorAll(".notes-input").forEach((inp) => {
      inp.addEventListener("change", async () => {
        await fetch("/api/sessions/" + inp.dataset.id, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ notes: inp.value })
        });
      });
    });
  } catch (e) {
    $("history").innerHTML = '<div class="empty-state">Could not load history.</div>';
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadSamples();
  loadHistory();
  $("analyze").addEventListener("click", runAnalysis);
  $("clear").addEventListener("click", () => {
    $("bill-text").value = "";
    $("results").classList.add("hidden");
    $("status").textContent = "";
  });
  $("refresh-history").addEventListener("click", loadHistory);
  $("toggle-samples").addEventListener("click", () => {
    $("sample-drawer").classList.toggle("hidden");
  });
});
