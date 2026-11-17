"use strict";
/* EDGAR-SENTINEL stock research app (feature 026): one page per company, dilution risk first.
   The company page shows one section at a time, in tabs (User Story 8, the researcher, 16 Nov). */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const finite = (v) => v !== null && v !== undefined && Number.isFinite(Number(v));

const fmt = {
  money(v) {
    if (!finite(v)) return "–";
    const a = Math.abs(v), s = v < 0 ? "−" : "";
    if (a >= 1e12) return `${s}$${(a / 1e12).toFixed(2)}T`;
    if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`;
    if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`;
    return `${s}$${a.toFixed(0)}`;
  },
  count(v) {
    if (!finite(v)) return "–";
    const a = Math.abs(v);
    if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
    if (a >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
    if (a >= 1e4) return `${(v / 1e3).toFixed(0)}K`;
    return Math.round(v).toLocaleString("en-US");
  },
  int: (v) => (finite(v) ? Math.round(v).toLocaleString("en-US") : "–"),
  price(v) {
    if (!finite(v)) return "–";
    return `$${v >= 1000 ? v.toFixed(0) : v >= 1 ? v.toFixed(2) : v.toFixed(4)}`;
  },
  pct: (v, d = 1) => (finite(v) ? `${(v * 100).toFixed(d)}%` : "–"),
  date(s) {
    if (!s) return "–";
    const d = new Date(`${String(s).slice(0, 10)}T00:00:00`);
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  },
  year: (s) => (s ? String(s).slice(0, 4) : "–"),
  value(kind, v) {
    if (!finite(v)) return "–";
    switch (kind) {
      case "pct": return fmt.pct(v);
      case "pctpt": return `${(v * 100).toFixed(1)} pts`;
      case "money": return fmt.money(v);
      case "logmoney": return fmt.money(Math.exp(v));
      case "logprice": return fmt.price(Math.exp(v));
      case "price": return fmt.price(v);
      case "count": return fmt.int(v);
      case "years": return `${v.toFixed(1)} years`;
      case "bool": return v ? "yes" : "no";
      default: return Number(v).toFixed(2);
    }
  },
};
const ROLE = { officer: "Officer", director: "Director", ceo_cfo: "CEO / CFO", ten_pct: "10% owner", other: "Other" };
const BAND = ["", "Very low", "Low", "Moderate", "High", "Very high"];
const SECTOR = { NoDur: "Consumer staples", Durbl: "Consumer durables", Manuf: "Manufacturing", Enrgy: "Energy",
  Chems: "Chemicals", BusEq: "Technology & business equipment", Telcm: "Telecom", Utils: "Utilities",
  Shops: "Retail & wholesale", Hlth: "Healthcare", Money: "Finance", Other: "Other" };
const chancePct = (p) => (p < 0.01 ? fmt.pct(p, 1) : fmt.pct(p, 0));
const tip = (text) => `<span class="tip" tabindex="0" data-tip="${esc(text)}">?</span>`;
const tile = (label, value, sub = "", cls = "", tipText = "") => `<div class="tile"><div class="label">${label}${tipText ? tip(tipText) : ""}</div>
  <div class="value ${cls}">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
const bandChip = (b) => `<span class="band" style="background:var(--b${b})">${b} · ${BAND[b]}</span>`;
const plural = (n, word) => `${fmt.int(n)} ${word}${n === 1 ? "" : "s"}`;

function banner(msg) {
  let b = $(".banner.error");
  if (!b) { b = document.createElement("div"); b.className = "banner error"; $(".topbar").after(b); }
  b.textContent = msg;
}
async function getJSON(url) {
  const r = await fetch(url);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) { banner(body.error || `The request failed (${r.status}).`); throw new Error(body.error || r.status); }
  return body;
}

/* ---------- search ---------- */
const q = $("#q"), sug = $("#suggest");
let timer = null, results = [], active = -1;
q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(doSearch, 140); });
q.addEventListener("keydown", (e) => {
  if (sug.hidden || !results.length) return;
  if (e.key === "ArrowDown") { active = Math.min(active + 1, results.length - 1); drawSuggest(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); drawSuggest(); e.preventDefault(); }
  else if (e.key === "Enter") { pick(results[Math.max(active, 0)]); }
  else if (e.key === "Escape") { sug.hidden = true; }
});
document.addEventListener("click", (e) => { if (!e.target.closest(".search")) sug.hidden = true; });
async function doSearch() {
  const v = q.value.trim();
  if (!v) { sug.hidden = true; return; }
  results = await getJSON(`/api/search?q=${encodeURIComponent(v)}`);
  active = results.length ? 0 : -1;
  drawSuggest();
}
function drawSuggest() {
  if (!results.length) { sug.innerHTML = `<div><span></span><span class="muted">No company found</span></div>`; sug.hidden = false; return; }
  sug.innerHTML = results.map((r, i) => `
    <div class="${i === active ? "on" : ""}" data-i="${i}">
      <b>${esc(r.ticker)}</b><span>${esc(r.name)}</span>
      <span class="small ${r.listed ? "muted" : "gone"}">${r.listed ? esc(r.exchange || "") : `until ${esc(fmt.year(r.last_session))}`}</span>
    </div>`).join("");
  sug.hidden = false;
  sug.querySelectorAll("div[data-i]").forEach((el) => el.addEventListener("click", () => pick(results[+el.dataset.i])));
}
function pick(r) { sug.hidden = true; q.value = `${r.ticker} · ${r.name}`; q.blur(); show(r.cik, true); }

/* ---------- landing: the search, what the app answers and the forecasts' date; no list of
   companies (the researcher, 17 Nov: no list of the highest risks, V2-77) ---------- */
async function landing() {
  current = null;
  $("#landing").hidden = false; $("#stock").hidden = true;
  document.title = "EDGAR-SENTINEL · Stock research";
  $("#band-guide").innerHTML = [1, 2, 3, 4, 5].map((b) => `<div style="background:var(--b${b})">${b} · ${BAND[b]}</div>`).join("");
  const s = await getJSON("/api/summary");
  $("#landing-tiles").innerHTML = [
    tile("Companies with a forecast", fmt.int(s.covered), "US companies still trading that the model covers"),
    tile("Forecasts made on", fmt.date(s.as_of), "with the newest prices and SEC filings"),
    tile("Updated", "Every weekday", "new filings, prices and forecasts each weekday morning"),
  ].join("");
}

/* ---------- tabs ---------- */
const TABS = ["price", "dilution", "insiders", "filings", "about"];
let tab = "price", current = null;
// drawing that waits for its tab to open: a chart drawn while hidden has no size
const later = new Map();
function inTab(name, key, fn) {
  if (tab === name && !$("#stock").hidden) { fn(); return; }
  if (!later.has(name)) later.set(name, new Map());
  later.get(name).set(key, fn);
}
function openTab(name, scroll = false) {
  tab = TABS.includes(name) ? name : "price";
  $$(".tabbar [role=tab]").forEach((b) => {
    const on = b.dataset.tab === tab;
    b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1;
  });
  TABS.forEach((t) => { $(`#tab-${t}`).hidden = t !== tab; });
  if (current) history.replaceState(history.state, "", `/?cik=${encodeURIComponent(current)}#${tab}`);
  if (scroll) scrollToTabs();
  const run = later.get(tab); later.delete(tab);
  if (run) for (const fn of run.values()) fn();
}
function scrollToTabs() { // keep the open tab's top in view under the tab bar
  const bar = $(".topbar"), sticky = getComputedStyle(bar).position === "sticky" ? bar.offsetHeight : 0;
  const y = $("#tabs-anchor").getBoundingClientRect().top + window.scrollY - sticky;
  if (window.scrollY > y) window.scrollTo({ top: y });
}
$$(".tabbar [role=tab]").forEach((b) => b.addEventListener("click", () => openTab(b.dataset.tab, true)));
$(".tabbar").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const n = TABS[(TABS.indexOf(tab) + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
  openTab(n); $(`#t-${n}`).focus(); e.preventDefault();
});
$("#risk-pill").addEventListener("click", (e) => { e.preventDefault(); openTab("dilution", true); });

/* ---------- a company ---------- */
function resetCompany() {
  $("#c-name").textContent = "Loading…";
  for (const id of ["c-tickers", "c-meta", "q-change", "price-legend", "fin-tabs", "kind-tabs", "insider-summary", "reasons", "record", "factors", "model"])
    $(`#${id}`).innerHTML = "";
  for (const id of ["q-price", "q-date", "n-insiders", "n-filings", "n-factors", "price-source", "trades-meta", "fin-note"]) $(`#${id}`).textContent = "";
  for (const id of ["stats", "dilution", "short", "profile", "diagnostics"]) $(`#${id}`).innerHTML = `<div class="loading">Loading…</div>`;
  for (const id of ["financials", "trades", "filings"]) $(`#${id}`).innerHTML = `<tbody><tr><td class="loading">Loading…</td></tr></tbody>`;
  for (const id of ["price-chart", "shares-chart", "insider-chart"]) emptyIn(id, "Loading…");
  $("#risk-pill").hidden = true; $("#reasons").hidden = false; $("#factors-fold").hidden = false;
  $("#dilution").classList.remove("span-12");
  $("#trades-more").hidden = true; $("#filings-more").hidden = true;
}

async function show(cik, push, openOn = null) {
  const target = openOn || tab;
  if (push) history.pushState({ cik }, "", `/?cik=${encodeURIComponent(cik)}#${target}`);
  current = cik; later.clear(); priceState = null; insState = null;
  $("#landing").hidden = true; $("#stock").hidden = false;
  resetCompany();
  openTab(target);
  window.scrollTo(0, 0);
  const c = await getJSON(`/api/company/${encodeURIComponent(cik)}`);
  if (current !== cik) return;
  renderCompany(c); renderDilution(c); renderModel(c); renderShort(c); renderAbout(c);
  inTab("price", "shares", () => renderShares(c.shares));
  inTab("filings", "filings", () => loadFilings(cik, null));
  const [p, ins] = await Promise.all([
    getJSON(`/api/prices/${encodeURIComponent(cik)}`), getJSON(`/api/insiders/${encodeURIComponent(cik)}`)]);
  if (current !== cik) return;
  inTab("price", "prices", () => renderPrices(p, ins));
  renderInsiders(ins, c);
  const f = await getJSON(`/api/financials/${encodeURIComponent(cik)}`);
  if (current === cik) renderFinancials(f);
}

function renderCompany(c) {
  const f = c.facts || {}, card = c.card || {}, qt = c.quote || {};
  const listed = c.tickers.filter((t) => t.listed), shown = listed.length ? listed : c.tickers.slice(0, 1);
  document.title = `${shown[0]?.ticker || ""} · ${f.name || ""} · EDGAR-SENTINEL`;
  $("#c-name").textContent = f.name || `CIK ${c.cik}`;
  // the header names only what is unusual; the rest is under About & data
  $("#c-tickers").innerHTML = shown.map((t) => `<span class="chip ${t.listed ? "" : "old"}">${esc(t.ticker)}</span>`).join("") +
    (f.listed ? "" : `<span class="chip old">No longer trading${f.last_session ? ` · last day ${fmt.date(f.last_session)}` : ""}</span>`) +
    (card.foreign_filer ? `<span class="chip warn">Foreign filer</span>` : "") +
    (f.is_fund ? `<span class="chip warn">Fund</span>` : "") + (f.is_blank_check ? `<span class="chip warn">Blank-check company (SPAC)</span>` : "");
  const ex = listed[0]?.exchange || c.tickers[0]?.exchange;
  $("#c-meta").innerHTML = [ex && `<span>${esc(ex)}</span>`,
    f.sic_description && `<span title="SIC code ${esc(f.sic)}">${esc(f.sic_description)}</span>`,
    f.sector && `<span>${esc(SECTOR[f.sector] || f.sector)}</span>`].filter(Boolean).join("<span>·</span>");
  $("#q-price").textContent = fmt.price(qt.close);
  const ch = finite(qt.close) && finite(qt.previous) ? qt.close / qt.previous - 1 : null;
  $("#q-change").innerHTML = ch === null ? "" : `<span class="change ${ch >= 0 ? "up" : "down"}">${ch >= 0 ? "+" : ""}${fmt.pct(ch, 2)}</span>`;
  $("#q-date").textContent = qt.session ? `close ${fmt.date(qt.session)}` : "no price data";
  $("#n-filings").textContent = finite(c.diagnostics?.filings) ? fmt.count(c.diagnostics.filings) : "";
  const stat = (label, value, tipText) => `<dt>${label}${tipText ? tip(tipText) : ""}</dt><dd>${value}</dd>`;
  const growth = card.share_growth_12m;
  // V2-75: the trading rules out the reported share count, so the values built on it are marked
  const doubt = c.share_count_doubt;
  const times = doubt ? Number(doubt.times).toLocaleString("en-US", { maximumFractionDigits: 1 }) : "";
  const doubtful = doubt ? ` <span class="flag doubt" tabindex="0" data-tip="${esc(`The shares traded per day are worth ${times} times the market value, as if every share changed hands ${times} times a day. The reported share count is almost certainly wrong (for example, given in thousands), and so is the market value computed from it (decision V2-75).`)}">doubtful</span>` : "";
  $("#stats").innerHTML = [
    stat("Market value", fmt.money(card.market_cap) + doubtful, "Share price × shares outstanding: what the whole company is worth on the market."),
    stat("Shares outstanding", fmt.count(card.shares_outstanding) + doubtful, "The number of shares that exist, as last reported to the SEC."),
    stat("Share count, 12 months", finite(growth) ? `<span class="${growth > 0.1 ? "down" : ""}">${growth >= 0 ? "+" : ""}${fmt.pct(growth)}</span>` : "–",
      "How much the number of shares changed over the last year: a rise means past dilution."),
    stat("52-week range", qt.low_52w ? `${fmt.price(qt.low_52w)} – ${fmt.price(qt.high_52w)}` : "–"),
    stat("Traded per day", fmt.money(card.addv20), "Average value of shares traded per day over the last 20 trading days."),
    stat("Price swings, last year", fmt.pct(card.vol_252, 0), "Volatility: the typical size of the price's moves, as a yearly figure (the annualised standard deviation of daily returns)."),
    stat("Moves with the market (beta)", finite(card.beta_252) ? Number(card.beta_252).toFixed(2) : "–", "Beta: how strongly the price moves with the whole market over the last year. 1 moves with it; 2 moves twice as much; near 0 moves on its own."),
    stat("Revenue growth, 12 months", fmt.pct(card.revenue_growth), "The change in revenue over the last 12 months against the 12 months before, as first reported."),
    stat("Gross margin", fmt.pct(card.gross_margin), "Revenue minus the direct cost of what was sold, as a share of revenue."),
    stat("Cash runway", finite(card.cash_runway_years) ? `${Number(card.cash_runway_years).toFixed(1)} years`
      : (card.loss_making === 0 || card.loss_making === false ? "Profitable" : "–"), "For a loss-making company: how many years its cash would cover the current losses."),
    stat("Next results (estimate)", card.next_results_estimate && card.next_results_estimate >= (c.freshness?.prices || "")
      ? fmt.date(card.next_results_estimate) : "–", "The expected date of the next quarterly or annual results, estimated from past release dates."),
  ].join("");
}

/* a model card table ({columns, data}) as one object per row */
function tableRows(t) {
  return t && t.columns ? t.data.map((r) => Object.fromEntries(t.columns.map((k, i) => [k, r[i]]))) : [];
}
function baseRate(mc) { // the share of all test-year forecasts that diluted
  const pooled = tableRows(mc.bands_pooled), n = pooled.reduce((s, r) => s + r.rows, 0);
  return n ? pooled.reduce((s, r) => s + r.rows * r.real_rate, 0) / n : null;
}

/* ---------- dilution risk ---------- */
function renderDilution(c) {
  const d = c.dilution, mc = (c.model || {}).card || {}, base = baseRate(mc);
  const pill = $("#risk-pill"); pill.hidden = false;
  pill.innerHTML = d.available
    ? `<i class="dot" style="background:var(--b${d.band})"></i>Dilution risk <b>${BAND[d.band]}</b> <span class="muted">${chancePct(d.chance)}</span>`
    : `<i class="dot" style="background:var(--faint)"></i>Dilution risk <span class="muted">no forecast</span>`;
  const head = `<div class="card-head"><h2>Dilution risk</h2>${tip("Dilution: the company issues new shares, so each existing share owns a smaller part of the company. It often happens when a loss-making company sells shares to raise cash.")}</div>`;
  if (!d.available) {
    $("#dilution").classList.add("span-12");
    $("#dilution").innerHTML = `${head}<div class="unavailable">${esc(d.reason)}</div>
      <div class="facts-row"><span>Across all companies the model covers, <b>${fmt.pct(base)}</b> raised their share count by 10% or
        more within six months in the test years.</span></div>`;
    $("#reasons").hidden = true; $("#factors-fold").hidden = true;
    $("#record").innerHTML = "";
    $("#record").hidden = true;
    return;
  }
  $("#record").hidden = false;
  $("#dilution").innerHTML = `${head}
    <div class="label">Chance that the share count rises by <b>10% or more</b> within the next <b>6 months</b></div>
    <div class="big" style="color:var(--b${d.band})">${chancePct(d.chance)}</div>
    ${bandChip(d.band)}
    <div class="band-scale">${[1, 2, 3, 4, 5].map((b) => `<div class="${b === d.band ? "on" : ""}" style="background:var(--b${b})"></div>`).join("")}</div>
    <div class="band-labels"><span>Very low</span><span>Very high</span></div>
    <div class="compare">
      <div class="cmp-row"><span>This company</span><span class="cmp-track"><span class="cmp-bar" style="width:${(d.chance * 100).toFixed(1)}%;background:var(--b${d.band})"></span></span><b>${chancePct(d.chance)}</b></div>
      <div class="cmp-row"><span>Average company</span><span class="cmp-track"><span class="cmp-bar" style="width:${finite(base) ? (base * 100).toFixed(1) : 0}%;background:var(--faint)"></span></span><b>${fmt.pct(base)}</b></div>
    </div>
    <div class="facts-row"><span>Forecast for <b>${fmt.date(d.as_of)}</b> by the approved model</span><span>Average: all forecasts of the test years</span></div>
    ${d.stale ? `<p class="note"><span class="chip warn">Not from the latest update</span> This forecast uses the data of
      ${fmt.date(d.as_of)}: the latest update made no new one, so the newest data is not in it.</p>` : ""}`;
  renderReasons(d);
  renderRecord(d, mc, base);
  renderFactors(d);
}

function renderReasons(d) {
  const up = d.factors.filter((f) => f.effect > 0).sort((a, b) => b.effect - a.effect).slice(0, 5);
  const down = d.factors.filter((f) => f.effect < 0).sort((a, b) => a.effect - b.effect).slice(0, 3);
  const max = Math.max(1e-9, ...up.concat(down).map((f) => Math.abs(f.effect)));
  const row = (f) => `<span class="arrow ${f.effect > 0 ? "upr" : "downr"}">${f.effect > 0 ? "▲" : "▼"}</span>
    <span>${esc(f.label)}</span><span class="val">${fmt.value(f.kind, f.value)}</span>
    <span class="track"><span class="bar ${f.effect > 0 ? "" : "low"}" style="width:${((Math.abs(f.effect) / max) * 100).toFixed(1)}%"></span></span>`;
  $("#reasons").innerHTML = `<div class="card-head"><h2>What drives this forecast</h2>
      ${tip("The model's own account of this forecast: how much each input pushed this company's chance up or down from the average. The longest push fills the bar.")}</div>
    <div class="rbars">${up.length ? `<div class="group">Raise the chance</div>${up.map(row).join("")}` : ""}
      ${down.length ? `<div class="group">Lower the chance</div>${down.map(row).join("")}` : ""}</div>
    <p class="note">The strongest pushes of the ${fmt.int(d.factors.length)} inputs; all of them are listed under "Every factor" below.</p>`;
}

function renderRecord(d, mc, base) {
  // the band's record: the test years (2019 on) and the one-time test (019), read from the model card
  const yrs = tableRows(mc.bands).filter((r) => r.band === d.band);
  const pb = tableRows(mc.bands_pooled).find((r) => r.band === d.band);
  const ho = mc.holdout, hb = tableRows(mc.holdout?.bands).filter((r) => r.band === d.band);
  const hy = hb.filter((r) => r.year !== "all"), ha = hb.find((r) => r.year === "all");
  const span = (rows) => (rows.length ? `${rows[0].year}–${rows[rows.length - 1].year}` : "");
  const cells = (rows, key, f, first) => rows.map((r, i) => `<td class="${first && i === 0 ? "sep" : ""}">${f(r[key])}</td>`).join("");
  $("#record").innerHTML = `<div class="card-head"><h2>How often companies in band ${d.band} diluted</h2>
      ${tip("The share of forecasts in this band that were followed by a 10%+ rise in shares within six months. A good band diluted about as often as its forecasts said.")}</div>
    <div class="tiles flat">
      ${pb ? tile(`Test years ${span(yrs)}`, fmt.pct(pb.real_rate), `of ${fmt.count(pb.rows)} forecasts; each year forecast by a model trained on earlier years only`) : ""}
      ${ha ? tile(`One-time test ${span(hy)}`, fmt.pct(ha.real_rate), `of ${fmt.count(ha.rows)} forecasts the model had never seen, scored once on ${fmt.date(ho.date)}`) : ""}
      ${tile("All companies", fmt.pct(base), "the average across every band, test years")}
    </div>
    <div class="scroll"><table class="record">
      <tr class="grp"><th></th><th colspan="${yrs.length}">Test years</th>${hy.length ? `<th class="sep" colspan="${hy.length}">One-time test</th>` : ""}</tr>
      <tr><th>Year</th>${yrs.map((r) => `<th>${r.year}</th>`).join("")}${hy.map((r, i) => `<th class="${i === 0 ? "sep" : ""}">${r.year}</th>`).join("")}</tr>
      <tr><td>Diluted</td>${cells(yrs, "real_rate", fmt.pct)}${cells(hy, "real_rate", fmt.pct, true)}</tr>
      ${yrs.every((r) => finite(r.forecast)) ? `<tr><td class="muted">Forecast</td>${cells(yrs, "forecast", fmt.pct)}${cells(hy, "forecast", fmt.pct, true)}</tr>` : ""}
      <tr><td class="muted">Forecasts</td>${cells(yrs, "rows", fmt.count)}${cells(hy, "rows", fmt.count, true)}</tr>
    </table></div>
    ${ho ? `<p class="note">One-time test: forecasts from ${fmt.date(ho.first_row)} to ${fmt.date(ho.last_row)}, scored once on
      ${fmt.date(ho.date)} against answers kept sealed while the model was built.</p>` : ""}`;
}

function renderFactors(d) {
  $("#n-factors").textContent = fmt.int(d.factors.length);
  $("#factors").innerHTML = `<div class="factors"><table class="record"><tr><th>Factor</th><th>Value</th><th>Effect</th></tr>
      ${d.factors.map((f) => `<tr><td>${esc(f.label)}</td><td>${fmt.value(f.kind, f.value)}</td>
        <td class="${f.effect > 0 ? "down" : "up"}">${f.effect > 0 ? "+" : ""}${f.effect.toFixed(3)}</td></tr>`).join("")}</table></div>
    <p class="note">Effect: how much the factor moved this company's forecast up (+) or down (−) from the average, on the model's
      log-odds scale. Forecast made by the daily update with the approved model (decision V2-52), the same frozen model the
      one-time test checked.</p>`;
}

function renderModel(c) {
  const m = c.model || {}, mc = m.card || {}, ty = mc.test_years || {};
  const levels = [["base_rate", "Base rate"], ["rule", "Offering rule"], ["logistic", "Logistic regression"], ["boosting", "LightGBM (chosen)"]];
  // the one-time test (019): every number read from the model card's holdout entry
  const ho = mc.holdout, hr = tableRows(mc.holdout?.results).map((r) => ({ ...r, level: String(r.level).replace(" (chosen)", "") }));
  const hYears = [...new Set(hr.map((r) => r.year))].sort((a, b) => (a === "all") - (b === "all") || a.localeCompare(b));
  const hLevels = [["base_rate", "Base rate"], ["rule", "Offering rule"], ["logistic", "Logistic regression"], ["lightgbm", "LightGBM (chosen)"]];
  const hCell = (k, y, key, n) => {
    const r = hr.find((x) => x.level === k && x.year === y);
    return `<td>${r && finite(r[key]) ? r[key].toFixed(n) : "–"}</td>`;
  };
  const calib = (rows) => `<table class="record"><tr><th>Band</th><th>Forecasts</th><th>Forecast</th><th>Diluted</th></tr>
    ${rows.map((r) => `<tr><td>${r.band} · ${BAND[r.band]}</td><td>${fmt.count(r.rows)}</td><td>${fmt.pct(r.forecast)}</td><td>${fmt.pct(r.real_rate)}</td></tr>`).join("")}</table>`;
  $("#model").innerHTML = `<div class="model-grid">
    <div>
      <h3>The model</h3>
      <dl class="stat-list wide"><dt>Model</dt><dd>${esc(m.model || "–")}</dd><dt>Approved</dt><dd>${esc(m.approved || "–")}</dd>
        <dt>Learned from</dt><dd>answers known before ${fmt.date(m.cutoff)}<span class="sub">trees trained through ${fmt.date(m.trained_through)}</span></dd>
        <dt>Frozen</dt><dd>run ${esc(String(m.frozen_run || "").slice(0, 8))}<span class="sub">data ${esc(m.data_hash || "")} · export ${esc(m.export_date || "")}</span></dd></dl>
      <h3>Test years: log loss (lower is better)</h3>
      <div class="scroll"><table class="record"><tr><th>Level</th>${Object.keys(ty).map((y) => `<th>${y}</th>`).join("")}</tr>
        ${levels.map(([k, label]) => `<tr><td>${label}</td>${Object.values(ty).map((r) => `<td>${finite(r[k]) ? r[k].toFixed(3) : "–"}</td>`).join("")}</tr>`).join("")}</table></div>
      <h3>Calibration, test years: forecast against what happened</h3>
      ${calib(tableRows(mc.bands_pooled))}
    </div>
    <div>
      ${ho && hr.length ? `<h3>The one-time test: log loss (lower is better)</h3>
        <p class="note" style="margin:0 0 8px">${fmt.count(ho.rows)} forecasts made at month-ends from ${fmt.date(ho.first_row)} to
          ${fmt.date(ho.last_row)}, scored once on ${fmt.date(ho.date)} against answers kept sealed while the model was built.</p>
        <div class="scroll"><table class="record"><tr><th>Level</th>${hYears.map((y) => `<th>${y === "all" ? "All" : y}</th>`).join("")}<th>AUC</th></tr>
          ${hLevels.map(([k, label]) => `<tr><td>${label}</td>${hYears.map((y) => hCell(k, y, "log_loss", 3)).join("")}${hCell(k, "all", "auc", 2)}</tr>`).join("")}</table></div>
        <h3>Calibration, one-time test</h3>
        ${calib(tableRows(mc.holdout?.bands).filter((r) => r.year === "all"))}` : `<h3>The one-time test</h3><p class="note">Not run yet.</p>`}
    </div></div>
    <p class="note">Log loss: the penalty for each forecast, larger the more confidently wrong. AUC: how often a company that diluted
      got a higher chance than one that did not (0.5 a coin toss). Limits: no forecast for foreign filers, companies no longer
      trading, shares below $1 or companies without a reported share count; learned from 2012–2022.</p>`;
}

/* ---------- charts ---------- */
const CHART = {
  autoSize: true,
  layout: { background: { color: "#ffffff" }, textColor: "#334155", fontFamily: "Inter, Segoe UI, Roboto, sans-serif", fontSize: 11 },
  grid: { vertLines: { color: "#f3f5f9" }, horzLines: { color: "#f3f5f9" } },
  rightPriceScale: { borderColor: "#e3e8ef" }, timeScale: { borderColor: "#e3e8ef" },
  localization: { locale: "en-US" },
};
const charts = {};
function chartIn(id, extra = {}) {
  if (charts[id]) { charts[id].remove(); delete charts[id]; }
  const el = $(`#${id}`); el.innerHTML = "";
  charts[id] = LightweightCharts.createChart(el, { ...CHART, ...extra });
  return charts[id];
}
function emptyIn(id, msg) { if (charts[id]) { charts[id].remove(); delete charts[id]; } $(`#${id}`).innerHTML = `<div class="empty">${esc(msg)}</div>`; }
const tstr = (t) => (typeof t === "string" ? t : typeof t === "object" ? `${t.year}-${String(t.month).padStart(2, "0")}-${String(t.day).padStart(2, "0")}` : new Date(t * 1000).toISOString().slice(0, 10));
function snap(days, d) { // the first trading day on or after d
  let lo = 0, hi = days.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (days[m] < d) lo = m + 1; else hi = m; }
  return lo < days.length ? days[lo] : null;
}
function monthsBefore(day, n) { const d = new Date(`${day}T00:00:00`); d.setMonth(d.getMonth() - n); return d.toISOString().slice(0, 10); }

let priceState = null;
function renderPrices(p, ins) {
  $("#price-source").textContent = p.sources.length ? `Prices: ${p.sources.join(", ")} · adjusted for stock splits` : "";
  if (!p.t.length) { emptyIn("price-chart", "No price data: this company's shares do not trade on a US exchange covered by the data."); $("#price-legend").textContent = ""; return; }
  const last = p.c[p.c.length - 1];
  const chart = chartIn("price-chart");
  const price = chart.addAreaSeries({ lineColor: "#2563eb", topColor: "rgba(37,99,235,0.16)", bottomColor: "rgba(37,99,235,0.0)", lineWidth: 2,
    priceFormat: { type: "custom", formatter: (v) => (v < 0 ? "" : fmt.price(v)), minMove: last < 1 ? 0.0001 : 0.01 } });
  const vol = chart.addHistogramSeries({ priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false, priceFormat: { type: "custom", formatter: (v) => fmt.count(v) } });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  price.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.24 } });
  price.setData(p.t.map((t, i) => ({ time: t, value: p.c[i] })));
  vol.setData(p.t.map((t, i) => ({ time: t, value: p.v[i] || 0, color: i && p.c[i] < p.c[i - 1] ? "rgba(220,38,38,0.32)" : "rgba(5,150,105,0.32)" })));
  // markers: insider purchases and unplanned sales by trading day, and filings that signal new shares
  const byDay = new Map();
  for (const t of ins.trades) {
    if (t.side === "sell" && t.planned) continue;
    const day = snap(p.t, t.trade_date); if (!day) continue;
    const k = `${day}|${t.side}`; byDay.set(k, (byDay.get(k) || 0) + (t.value_usd || 0));
  }
  let marks = [...byDay.entries()].map(([k, v]) => { const [day, side] = k.split("|");
    return { time: day, position: side === "buy" ? "belowBar" : "aboveBar", color: side === "buy" ? "#059669" : "#dc2626",
      shape: side === "buy" ? "arrowUp" : "arrowDown", size: 1, v }; });
  if (marks.length > 250) marks = marks.sort((a, b) => b.v - a.v).slice(0, 250);
  for (const o of p.offerings || []) { const day = snap(p.t, o.date); if (day) marks.push({ time: day, position: "aboveBar", color: "#7c3aed", shape: "circle", size: 1, text: "" }); }
  marks.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  price.setMarkers(marks.map(({ v, ...m }) => m));
  const idx = new Map(p.t.map((t, i) => [t, i]));
  const legend = (i) => {
    $("#price-legend").innerHTML = `<b>${fmt.date(p.t[i])}</b> · Open ${fmt.price(p.o[i])} · High ${fmt.price(p.h[i])} · Low ${fmt.price(p.l[i])} · Close <b>${fmt.price(p.c[i])}</b> · Volume ${fmt.count(p.v[i])}`;
  };
  legend(p.t.length - 1);
  chart.subscribeCrosshairMove((param) => { const i = param.time ? idx.get(tstr(param.time)) : undefined; legend(i === undefined ? p.t.length - 1 : i); });
  priceState = { chart, first: p.t[0], last: p.t[p.t.length - 1] };
  setRange(+($("#ranges button.on")?.dataset.m ?? 12));
}
function setRange(m) {
  $$("#ranges button").forEach((b) => b.classList.toggle("on", +b.dataset.m === m));
  if (!priceState) return;
  const ts = priceState.chart.timeScale();
  if (!m) { ts.fitContent(); return; }
  const from = monthsBefore(priceState.last, m);
  ts.setVisibleRange({ from: from < priceState.first ? priceState.first : from, to: priceState.last });
}
$$("#ranges button").forEach((b) => b.addEventListener("click", () => setRange(+b.dataset.m)));

function renderShares(rows) {
  if (!rows.length) { emptyIn("shares-chart", "No share counts reported to the SEC for this company."); return; }
  const chart = chartIn("shares-chart");
  const s = chart.addLineSeries({ color: "#7c3aed", lineWidth: 2, priceFormat: { type: "custom", formatter: (v) => fmt.count(v) } });
  const seen = new Set();
  s.setData(rows.filter((r) => !seen.has(r.period_end) && seen.add(r.period_end)).map((r) => ({ time: r.period_end, value: r.adjusted })));
  chart.timeScale().fitContent();
}

/* ---------- fundamentals ---------- */
let finState = null;
function renderFinancials(f, which = "quarters") {
  finState = f;
  const btn = (k, label) => `<button data-k="${k}" class="${k === which ? "on" : ""}">${label}</button>`;
  $("#fin-tabs").innerHTML = btn("quarters", "Quarterly") + btn("years", "Annual");
  $$("#fin-tabs button").forEach((b) => b.addEventListener("click", () => renderFinancials(finState, b.dataset.k)));
  const cols = f[which];
  if (!cols.length) {
    $("#financials").innerHTML = `<tbody><tr><td><div class="empty">No financial statements in our data for this company. Companies
      reporting under international accounting standards (IFRS), as many foreign companies do, are not read.</div></td></tr></tbody>`;
    $("#fin-note").textContent = "";
    return;
  }
  const usual = which === "years" ? 12 : 3;
  const cell = (it, v) => {
    if (!v) return `<td class="muted" title="Not in our data: not reported, or under a label (XBRL tag) we do not read">–</td>`;
    const txt = it.kind === "shares" ? fmt.count(v.value) : fmt.money(v.value);
    const len = it.kind === "flow" && v.months && v.months !== usual ? ` <span class="muted small">(${v.months} mo)</span>` : "";
    return `<td title="Filed ${fmt.date(v.filed)}">${txt}${len}</td>`;
  };
  $("#financials").innerHTML = `<thead><tr><th></th>${cols.map((c) => `<th class="num">${fmt.date(c.period_end)}<div class="muted small">filed ${fmt.date(c.filed)}</div></th>`).join("")}</tr></thead><tbody>` +
    f.items.map((it) => `<tr><th>${esc(it.label)}</th>${cols.map((c) => cell(it, c.values[it.item])).join("")}</tr>`).join("") + "</tbody>";
  $("#fin-note").textContent = (which === "years"
    ? "Each fiscal year's totals and its year-end balances, from the annual report (10-K). "
    : "Revenue, income and cash flows for the quarter's three months; where the company reported only a longer total, such as six or nine months of the year so far, its length is shown in brackets. Cash, debt and shares are at the date shown. ") +
    "A dash means the number is not in our data: the company did not report it, or reported it under a less common label (XBRL tag) that we do not read.";
}

/* ---------- short selling ---------- */
function renderShort(c) {
  const k = c.card || {};
  $("#short").innerHTML = finite(k.short_ratio_1m) ? `
    <div class="tiles flat">
      ${tile("Short-sale share, last month", fmt.pct(k.short_ratio_1m))}
      ${tile("Last 3 months", fmt.pct(k.short_ratio_3m))}
      ${tile("Change", finite(k.short_ratio_chg) ? `${k.short_ratio_chg >= 0 ? "+" : ""}${(k.short_ratio_chg * 100).toFixed(1)} pts` : "–", "last month against 3 months")}
    </div>
    <div class="facts-row"><span>FINRA daily short-sale files, data to <b>${fmt.date(c.freshness?.short_volume)}</b></span></div>
    <details class="inline-fold"><summary>What this measures</summary><p class="note">The share of the stock's off-exchange trading
      that was short sales. Most stocks sit around 40–50%, because market makers sell short to fill buy orders, so compare a stock
      with its own history. This is not short interest (the shares sold short and not yet bought back).</p></details>`
    : `<div class="empty">No short-sale data for this company.</div>`;
}

/* ---------- insiders ---------- */
let insState = null;
function renderInsiders(ins, c) {
  insState = ins;
  $("#n-insiders").textContent = ins.trades.length ? fmt.count(ins.trades.length) : "";
  const fresh = c.freshness?.insider_filings || c.freshness?.prices;
  const since = fresh ? monthsBefore(fresh, 12) : "0000";
  const last12 = ins.trades.filter((t) => (t.trade_date || "") >= since);
  const sum = (rows) => rows.reduce((s, t) => s + (t.value_usd || 0), 0);
  const buys = last12.filter((t) => t.side === "buy"), sells = last12.filter((t) => t.side === "sell");
  const people = (rows) => new Set(rows.map((t) => t.owner)).size;
  const sold = sum(sells), planned = sum(sells.filter((t) => t.planned));
  const latest = ins.trades.reduce((a, t) => (!a || (t.trade_date || "") > (a.trade_date || "") ? t : a), null);
  $("#insider-summary").innerHTML = [
    tile("Bought, last 12 months", fmt.money(sum(buys)), plural(people(buys), "insider"), sum(buys) ? "up" : ""),
    tile("Sold, last 12 months", fmt.money(sold), plural(people(sells), "insider"), sold ? "down" : ""),
    tile("Pre-planned share of sales", sold ? fmt.pct(planned / sold, 0) : "–", "of the value sold, last 12 months", "",
      "Sales under a trading plan set up in advance (Rule 10b5-1) say less about the insider's view of the company."),
    tile("Latest trade", latest ? fmt.date(latest.trade_date) : "–",
      latest ? `${latest.side === "buy" ? "Buy" : "Sell"} · ${esc(latest.owner || "")}` : "none reported"),
  ].join("");
  inTab("insiders", "chart", drawInsiderChart);
  drawTrades(false);
}
function drawInsiderChart() {
  const ins = insState; if (!ins) return;
  if (!ins.monthly.length) { emptyIn("insider-chart", "No insider trades reported (Form 4) for this company."); return; }
  const hide = $("#hide-planned").checked;
  const chart = chartIn("insider-chart");
  const money = { type: "custom", formatter: (v) => fmt.money(Math.abs(v)) };
  const quiet = { lastValueVisible: false, priceLineVisible: false, priceFormat: money };
  const buy = chart.addHistogramSeries({ color: "#059669", ...quiet });
  const sell = chart.addHistogramSeries({ color: "#dc2626", ...quiet });
  buy.setData(ins.monthly.map((m) => ({ time: m.month, value: m.bought || 0 })));
  sell.setData(ins.monthly.map((m) => ({ time: m.month, value: -((hide ? m.sold_unplanned : m.sold) || 0) })));
  const last = ins.monthly[ins.monthly.length - 1].month, first = ins.monthly[0].month;
  const from = monthsBefore(last, 24);
  chart.timeScale().setVisibleRange({ from: from < first ? first : from, to: last });
}
$("#hide-planned").addEventListener("change", () => { inTab("insiders", "chart", drawInsiderChart); drawTrades(false); });
function drawTrades(all) {
  const ins = insState; if (!ins) return;
  const hide = $("#hide-planned").checked;
  const rows = ins.trades.filter((t) => !(hide && t.side === "sell" && t.planned));
  const shown = all ? rows : rows.slice(0, 15);
  $("#trades-meta").textContent = rows.length ? `${plural(rows.length, "Form 4 filing")}, newest first` : "";
  $("#trades").innerHTML = rows.length ? `<thead><tr><th>Trade date</th><th>Insider</th><th>Role</th><th>Buy / sell</th>
      <th class="num">Shares</th><th class="num">Avg price</th><th class="num">Value</th><th>Pre-planned</th><th>Filing</th></tr></thead><tbody>` +
    shown.map((t) => `<tr><td class="nowrap">${fmt.date(t.trade_date)}</td><td>${esc(t.owner || "")}</td>
      <td>${esc(ROLE[t.role] || t.role || "")}</td><td class="side ${t.side}">${t.side === "buy" ? "Buy" : "Sell"}</td>
      <td class="num">${fmt.count(t.shares)}</td><td class="num">${fmt.price(t.avg_price)}</td><td class="num">${fmt.money(t.value_usd)}</td>
      <td>${t.planned ? "Yes (10b5-1)" : ""}</td><td>${t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener">Form 4 ↗</a>` : ""}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td><div class="empty">No insider trades reported for this company.</div></td></tr></tbody>`;
  const more = $("#trades-more"); more.hidden = all || rows.length <= shown.length;
  more.textContent = `Show all ${fmt.int(rows.length)} trades`;
  more.onclick = () => drawTrades(true);
}

/* ---------- filings ---------- */
let filingKind = null, filingLimit = 25;
async function loadFilings(cik, kind, limit = 25) {
  filingKind = kind; filingLimit = limit;
  const f = await getJSON(`/api/filings/${encodeURIComponent(cik)}?limit=${limit}${kind ? `&kind=${kind}` : ""}`);
  if (current !== cik) return;
  const all = Object.values(f.counts).reduce((a, b) => a + b, 0);
  const pill = (k, label, n) => `<button data-k="${k || ""}" class="${(k || null) === kind ? "on" : ""}">${esc(label)} · ${fmt.int(n)}</button>`;
  $("#kind-tabs").innerHTML = pill(null, "All", all) + Object.entries(window.KINDS).filter(([k]) => f.counts[k]).map(([k, label]) => pill(k, label, f.counts[k])).join("");
  $$("#kind-tabs button").forEach((b) => b.addEventListener("click", () => loadFilings(cik, b.dataset.k || null)));
  $("#filings").innerHTML = f.filings.length ? `<thead><tr><th>Filed</th><th>Form</th><th>What it is</th><th></th><th></th></tr></thead><tbody>` +
    f.filings.map((r) => {
      const a = r.about, items = r.item_list || [];
      const dil = a.dilution_signal || items.some((i) => i.dilution_signal);
      return `<tr><td class="nowrap">${fmt.date(r.filing_date)}</td>
        <td><span class="form ${dil ? "dil" : ""}" data-tip="${esc(a.description)}">${esc(r.form)}</span></td>
        <td class="what"><b>${esc(a.name)}</b>${r.report_date && r.report_date !== r.filing_date ? ` <span class="muted small">· period ${fmt.date(r.report_date)}</span>` : ""}
          ${items.length ? `<ul class="items">${items.map((i) => `<li><b>${esc(i.item)}</b> ${esc(i.name)}${i.dilution_signal ? ' <span class="flag">new shares</span>' : ""}</li>`).join("")}</ul>`
            : `<div class="desc" title="${esc(a.description)}">${esc(a.description)}</div>`}</td>
        <td>${dil && !items.length ? '<span class="flag">new shares</span>' : ""}</td>
        <td class="nowrap">${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">View ↗</a>` : ""}</td></tr>`;
    }).join("") + "</tbody>" : `<tbody><tr><td><div class="empty">No filings of this kind.</div></td></tr></tbody>`;
  const more = $("#filings-more"); more.hidden = f.filings.length >= f.total;
  more.textContent = `Show more (${fmt.int(f.total - f.filings.length)} older)`;
  more.onclick = () => loadFilings(cik, filingKind, filingLimit + 200);
}

/* ---------- about & data ---------- */
function renderAbout(c) {
  const f = c.facts || {}, card = c.card || {}, d = c.diagnostics || {}, pr = d.prices || {}, fr = d.freshness || {};
  const row = (label, value, tipText) => (value ? `<dt>${label}${tipText ? tip(tipText) : ""}</dt><dd>${value}</dd>` : "");
  const tick = (t) => `<b>${esc(t.ticker)}</b> ${esc(t.exchange || "")}<span class="sub">${t.first_session
    ? `${fmt.date(t.first_session)} to ${t.listed ? "today" : fmt.date(t.last_session)}` : "no prices"}${t.listed ? "" : " · former"}</span>`;
  $("#profile").innerHTML = [
    row("Name", `<b>${esc(f.name || "")}</b>`),
    row("Tickers", c.tickers.map(tick).join("<br>") || "–"),
    row("Status", f.listed ? "Trading" : `No longer trading${f.last_session ? ` · last day ${fmt.date(f.last_session)}` : ""}`),
    row("Files as", card.foreign_filer ? "Foreign company (annual report 20-F or 40-F)" : "US company (reports 10-K and 10-Q)"),
    row("Industry", f.sic_description ? `${esc(f.sic_description)}<span class="sub">SIC code ${esc(f.sic)}</span>` : ""),
    row("Sector", f.sector ? esc(SECTOR[f.sector] || f.sector) : ""),
    row("Former names", f.former_names ? esc(f.former_names) : ""),
    row("Listed through", f.listed_via ? `a merger with ${esc(f.listed_via)}<span class="sub">${fmt.date(f.listed_via_date)}</span>` : "",
      "A blank-check company (SPAC) is a shell that lists with cash and later merges with a private company, which becomes public through it. The shell's months before the merger are not this company's history."),
    row("Kind", [f.is_fund && "Fund", f.is_blank_check && "Blank-check company (SPAC)"].filter(Boolean).join(" · ")),
    row("Periodic reports", f.first_periodic ? `${fmt.date(f.first_periodic)} to ${fmt.date(f.last_periodic)}` : ""),
    row("SEC ID (CIK)", `<a href="https://www.sec.gov/edgar/browse/?CIK=${esc(c.cik)}" target="_blank" rel="noopener">${esc(c.cik)} ↗</a>`,
      "CIK: the SEC's permanent ID for the company; it never changes, even when the name or ticker does."),
  ].join("");
  const lastOf = (form) => (d.last_filings || []).find((r) => r.form === form);
  $("#diagnostics").innerHTML = [
    row("Prices", pr.days ? `${esc(pr.sources || "")}, ${fmt.date(pr.first)} to ${fmt.date(pr.last)}<span class="sub">${fmt.int(pr.days)} trading days${pr.glitch_days ? ` · ${fmt.int(pr.glitch_days)} bad price days left out` : ""}</span>` : "none"),
    row("SEC filings", `${fmt.int(d.filings)} in all${lastOf("8-K") ? `<span class="sub">last 8-K ${fmt.date(lastOf("8-K").last)}</span>` : ""}`),
    row("Annual / quarterly", `${lastOf("10-K") ? `10-K ${fmt.date(lastOf("10-K").last)}` : lastOf("20-F") ? `20-F ${fmt.date(lastOf("20-F").last)}` : "–"}${lastOf("10-Q") ? `<span class="sub">10-Q ${fmt.date(lastOf("10-Q").last)}</span>` : ""}`),
    row("Insider filings", `${fmt.int(d.insider_filings)} Form 4${lastOf("4") ? `<span class="sub">last ${fmt.date(lastOf("4").last)}</span>` : ""}`),
    row("Coverage", `${esc(card.coverage || "–")}<span class="sub">${card.eligible_dilution ? "in the dilution question" : "outside the dilution question"}</span>`),
    row("Sources current to", `prices ${fmt.date(fr.prices)}<span class="sub">filings ${fmt.date(fr.filings)} · Form 4 ${fmt.date(fr.insider_filings)} · short sales ${fmt.date(fr.short_volume)} · financials ${fmt.date(fr.financials)}</span>`),
  ].join("");
}

/* ---------- start ---------- */
window.KINDS = window.KINDS || {};
const freshEl = $("#fresh-date"); if (freshEl) freshEl.textContent = fmt.date(freshEl.dataset.date);
function route() {
  const cik = new URLSearchParams(location.search).get("cik"), h = location.hash.slice(1);
  if (cik) show(cik, false, TABS.includes(h) ? h : null); else landing();
}
window.addEventListener("popstate", route);
window.addEventListener("hashchange", () => { const h = location.hash.slice(1); if (current && TABS.includes(h) && h !== tab) openTab(h); });
route();
