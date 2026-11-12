"use strict";
/* EDGAR-SENTINEL stock research app (feature 026): one page per company, dilution risk first. */

const $ = (s, el = document) => el.querySelector(s);
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
      <span class="small ${r.listed ? "muted" : "gone"}">${r.listed ? esc(r.exchange || "") : `until ${esc(String(r.last_session || "").slice(0, 4))}`}</span>
    </div>`).join("");
  sug.hidden = false;
  sug.querySelectorAll("div[data-i]").forEach((el) => el.addEventListener("click", () => pick(results[+el.dataset.i])));
}
function pick(r) { sug.hidden = true; q.value = `${r.ticker} · ${r.name}`; q.blur(); show(r.cik, true); }

/* ---------- landing ---------- */
async function landing() {
  $("#landing").hidden = false; $("#stock").hidden = true;
  const top = await getJSON("/api/top");
  $("#top-meta").textContent = `${fmt.int(top.covered)} companies forecast · ${fmt.date(top.as_of)}`;
  $("#top-table").innerHTML = `<thead><tr><th>Ticker</th><th>Company</th><th>Exchange</th>
      <th class="num">Chance of 10%+ new shares in 6 months</th><th>Risk band</th></tr></thead><tbody>` +
    top.companies.map((c) => `<tr class="click" data-cik="${esc(c.cik)}"><td><b>${esc(c.ticker)}</b></td>
      <td>${esc(c.name)}</td><td class="muted">${esc(c.exchange || "")}</td>
      <td class="num"><b>${chancePct(c.chance)}</b></td><td>${bandChip(c.band)}</td></tr>`).join("") + "</tbody>";
  document.querySelectorAll("#top-table tr.click").forEach((tr) => tr.addEventListener("click", () => show(tr.dataset.cik, true)));
}
const bandChip = (b) => `<span class="band" style="background:var(--b${b})">${b} · ${BAND[b]}</span>`;

/* ---------- a company ---------- */
let current = null;
async function show(cik, push) {
  if (push) history.pushState({ cik }, "", `/?cik=${encodeURIComponent(cik)}`);
  current = cik;
  $("#landing").hidden = true; $("#stock").hidden = false;
  window.scrollTo(0, 0);
  const c = await getJSON(`/api/company/${encodeURIComponent(cik)}`);
  if (current !== cik) return;
  renderCompany(c); renderDilution(c); renderShort(c); renderDiagnostics(c); renderShares(c.shares);
  const [p, ins] = await Promise.all([
    getJSON(`/api/prices/${encodeURIComponent(cik)}`), getJSON(`/api/insiders/${encodeURIComponent(cik)}`)]);
  if (current !== cik) return;
  renderPrices(p, ins); renderInsiders(ins, c);
  loadFilings(cik, null);
  const f = await getJSON(`/api/financials/${encodeURIComponent(cik)}`);
  if (current === cik) renderFinancials(f);
}

let finState = null;
function renderFinancials(f, which = "quarters") {
  finState = f;
  const tab = (k, label) => `<button data-k="${k}" class="${k === which ? "on" : ""}">${label} · ${f[k].length}</button>`;
  $("#fin-tabs").innerHTML = tab("quarters", "Last quarters") + tab("years", "Fiscal years");
  document.querySelectorAll("#fin-tabs button").forEach((b) => b.addEventListener("click", () => renderFinancials(finState, b.dataset.k)));
  const cols = f[which];
  if (!cols.length) {
    $("#financials").innerHTML = `<tbody><tr><td class="empty">No financial statements in our data for this company. Companies reporting under international accounting standards (IFRS), as many foreign companies do, are not read.</td></tr></tbody>`;
    $("#fin-note").textContent = "";
    return;
  }
  const usual = which === "years" ? 12 : 3;
  const cell = (it, v) => {
    if (!v) return `<td class="muted" title="Not in our data: not reported, or under a label (XBRL tag) we do not read">–</td>`;
    const txt = it.kind === "shares" ? fmt.count(v.value) : fmt.money(v.value);
    const len = it.kind === "flow" && v.months && v.months !== usual ? ` <span class="muted small">(${v.months} mo)</span>` : "";
    return `<td class="nowrap" title="Filed ${fmt.date(v.filed)}">${txt}${len}</td>`;
  };
  $("#financials").innerHTML = `<thead><tr><th></th>${cols.map((c) => `<th class="nowrap">${fmt.date(c.period_end)}<div class="muted small">filed ${fmt.date(c.filed)}</div></th>`).join("")}</tr></thead><tbody>` +
    f.items.map((it) => `<tr><th>${esc(it.label)}</th>${cols.map((c) => cell(it, c.values[it.item])).join("")}</tr>`).join("") + "</tbody>";
  $("#fin-note").textContent = which === "years"
    ? "Each fiscal year's totals and its year-end balances, from the annual report (10-K)."
    : "Revenue, income and cash flows for the quarter's three months; where the company reported only a longer total, such as six or nine months of the year so far, its length is shown in brackets. Cash, debt and shares are at the date shown.";
}

function renderCompany(c) {
  const f = c.facts || {}, card = c.card || {}, qt = c.quote || {};
  document.title = `${c.tickers[0]?.ticker || ""} · ${f.name || ""} · EDGAR-SENTINEL`;
  $("#c-name").textContent = f.name || `CIK ${c.cik}`;
  $("#c-tickers").innerHTML = c.tickers.map((t) => `<span class="chip ${t.listed ? "" : "old"}"
      title="${esc(t.exchange || "")} ${esc(t.first_session || "")} to ${esc(t.last_session || "")}">${esc(t.ticker)}</span>`).join("") +
    (f.listed ? `<span class="chip ok">Trading</span>` : `<span class="chip old">No longer trading${f.last_session ? ` (last day ${fmt.date(f.last_session)})` : ""}</span>`) +
    (card.foreign_filer ? `<span class="chip warn">Foreign filer</span>` : `<span class="chip ok">US filer</span>`) +
    (f.is_fund ? `<span class="chip warn">Fund</span>` : "") + (f.is_blank_check ? `<span class="chip warn">Blank-check company (SPAC)</span>` : "");
  const ex = c.tickers.find((t) => t.listed)?.exchange || c.tickers[0]?.exchange;
  $("#c-meta").innerHTML = [
    ex && `<span>${esc(ex)}</span>`,
    f.sic_description && `<span title="SIC code ${esc(f.sic)}">${esc(f.sic_description)}</span>`,
    f.sector && `<span class="muted">${esc(SECTOR[f.sector] || f.sector)}</span>`,
    f.former_names && `<span class="muted small">formerly ${esc(f.former_names)}</span>`,
    f.listed_via && `<span class="muted small"><span class="tip" data-tip="A blank-check company (SPAC) is a shell that lists with cash and later merges with a private company, which becomes public through it. The shell's months before the merger are not this company's history.">?</span>
      listed through a merger with ${esc(f.listed_via)} on ${fmt.date(f.listed_via_date)}</span>`,
    `<span><span class="tip" data-tip="CIK: the SEC's permanent ID for the company; it never changes, even when the name or ticker does.">?</span>
      CIK <a href="https://www.sec.gov/edgar/browse/?CIK=${esc(c.cik)}" target="_blank" rel="noopener">${esc(c.cik)} ↗</a></span>`,
  ].filter(Boolean).join("");
  $("#q-price").textContent = fmt.price(qt.close);
  const ch = finite(qt.close) && finite(qt.previous) ? qt.close / qt.previous - 1 : null;
  $("#q-change").innerHTML = ch === null ? "" : `<span class="${ch >= 0 ? "up" : "down"}">${ch >= 0 ? "+" : ""}${fmt.pct(ch, 2)} on the day</span>`;
  $("#q-date").textContent = qt.session ? `Close on ${fmt.date(qt.session)}` : "No price data";
  const stat = (label, value, tip) => `<div><span>${label}${tip ? ` <span class="tip" data-tip="${esc(tip)}">?</span>` : ""}</span><b>${value}</b></div>`;
  $("#stats").innerHTML = [
    stat("Market value", fmt.money(card.market_cap), "Share price × shares outstanding: what the whole company is worth on the market."),
    stat("Shares outstanding", fmt.count(card.shares_outstanding), "The number of shares that exist, as last reported to the SEC."),
    stat("52-week range", qt.low_52w ? `${fmt.price(qt.low_52w)} – ${fmt.price(qt.high_52w)}` : "–"),
    stat("Traded per day", fmt.money(card.addv20), "Average value of shares traded per day over the last 20 trading days."),
    stat("Share count, 12 months", card.share_growth_12m == null ? "–" : `${card.share_growth_12m >= 0 ? "+" : ""}${fmt.pct(card.share_growth_12m)}`, "How much the number of shares changed over the last year: a rise means past dilution."),
    stat("Cash runway", finite(card.cash_runway_years) ? `${Number(card.cash_runway_years).toFixed(1)} yrs` : (card.loss_making === 0 || card.loss_making === false ? "Profitable" : "–"), "For a loss-making company: how many years its cash would cover the current losses."),
    stat("Next results (estimate)", card.next_results_estimate && card.next_results_estimate >= (c.freshness?.prices || "")
      ? fmt.date(card.next_results_estimate) : "–", "The expected date of the next quarterly or annual results, estimated from past release dates."),
  ].join("");
}

function renderDilution(c) {
  const d = c.dilution, mc = (c.model || {}).card || {};
  const pooled = mc.bands_pooled ? mc.bands_pooled.data.map((r) => Object.fromEntries(mc.bands_pooled.columns.map((k, i) => [k, r[i]]))) : [];
  const base = pooled.length ? pooled.reduce((s, r) => s + r.rows * r.real_rate, 0) / pooled.reduce((s, r) => s + r.rows, 0) : null;
  const head = `<div class="card-head"><h2>Dilution risk</h2><span class="tip" data-tip="Dilution: the company issues new shares, so each existing share owns a smaller part of the company. It often happens when a loss-making company sells shares to raise cash.">?</span></div>`;
  if (!d.available) {
    $("#dilution").innerHTML = `${head}<div class="unavailable">${esc(d.reason)}</div>
      <p class="note">Across all companies the model covers, ${fmt.pct(base)} raised their share count by 10% or more within six months (test years 2019–2022).</p>`;
    return;
  }
  const yrs = mc.bands ? mc.bands.data.map((r) => Object.fromEntries(mc.bands.columns.map((k, i) => [k, r[i]]))).filter((r) => r.band === d.band) : [];
  const pb = pooled.find((r) => r.band === d.band);
  const up = d.factors.filter((f) => f.effect > 0).slice(0, 3), down = d.factors.filter((f) => f.effect < 0).slice(0, 2);
  const reason = (f) => `<li><span class="arrow ${f.effect > 0 ? "upr" : "downr"}">${f.effect > 0 ? "▲" : "▼"}</span>
      <span>${esc(f.label)}</span><b class="num">${fmt.value(f.kind, f.value)}</b></li>`;
  $("#dilution").innerHTML = `${head}
    <div class="big" style="color:var(--b${d.band})">${chancePct(d.chance)}</div>
    <div class="sub">chance that the share count rises by <b>10% or more</b> within the next <b>6 months</b></div>
    ${bandChip(d.band)} <span class="muted small">All companies: ${fmt.pct(base)}</span>
    <div class="band-scale">${[1, 2, 3, 4, 5].map((b) => `<div class="${b === d.band ? "on" : ""}" style="background:var(--b${b})"></div>`).join("")}</div>
    <div class="band-labels"><span>Very low</span><span>Very high</span></div>
    <h3>How often companies in this band diluted</h3>
    <table class="record"><tr><th>Test year</th>${yrs.map((r) => `<th>${r.year}</th>`).join("")}<th>All</th></tr>
      <tr><td>Diluted</td>${yrs.map((r) => `<td>${fmt.pct(r.real_rate)}</td>`).join("")}<td><b>${pb ? fmt.pct(pb.real_rate) : "–"}</b></td></tr>
      <tr><td class="muted">Companies</td>${yrs.map((r) => `<td class="muted">${fmt.count(r.rows)}</td>`).join("")}<td class="muted">${pb ? fmt.count(pb.rows) : ""}</td></tr></table>
    <h3>Main reasons</h3>
    <ul class="reasons">${up.map(reason).join("")}${down.map(reason).join("")}</ul>
    <p class="note">▲ raises the chance, ▼ lowers it. Forecast for ${fmt.date(d.as_of)}, made by the daily update with the approved
      model (decision V2-52), the same frozen model the one-time test on 2023+ data checked. Details under Diagnostics.</p>
    ${d.stale ? `<p class="note"><span class="chip warn">Not from the latest update</span> This forecast uses the data of
      ${fmt.date(d.as_of)}: the latest update made no new one, so the newest data is not in it.</p>` : ""}`;
}

/* ---------- charts ---------- */
const CHART = {
  autoSize: true,
  layout: { background: { color: "#ffffff" }, textColor: "#334155", fontFamily: "Inter, Segoe UI, Roboto, sans-serif", fontSize: 11 },
  grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
  rightPriceScale: { borderColor: "#e5e9f0" }, timeScale: { borderColor: "#e5e9f0" },
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
  const price = chart.addAreaSeries({ lineColor: "#2563eb", topColor: "rgba(37,99,235,0.18)", bottomColor: "rgba(37,99,235,0.0)", lineWidth: 2,
    priceFormat: { type: "custom", formatter: (v) => (v < 0 ? "" : fmt.price(v)), minMove: last < 1 ? 0.0001 : 0.01 } });
  const vol = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "custom", formatter: (v) => fmt.count(v) } });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  price.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.24 } });
  price.setData(p.t.map((t, i) => ({ time: t, value: p.c[i] })));
  vol.setData(p.t.map((t, i) => ({ time: t, value: p.v[i] || 0, color: i && p.c[i] < p.c[i - 1] ? "rgba(220,38,38,0.35)" : "rgba(5,150,105,0.35)" })));
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
  document.querySelectorAll("#ranges button").forEach((b) => b.classList.toggle("on", +b.dataset.m === m));
  if (!priceState) return;
  const ts = priceState.chart.timeScale();
  if (!m) { ts.fitContent(); return; }
  const from = monthsBefore(priceState.last, m);
  ts.setVisibleRange({ from: from < priceState.first ? priceState.first : from, to: priceState.last });
}
document.querySelectorAll("#ranges button").forEach((b) => b.addEventListener("click", () => setRange(+b.dataset.m)));

function renderShares(rows) {
  if (!rows.length) { emptyIn("shares-chart", "No share counts reported to the SEC for this company."); return; }
  const chart = chartIn("shares-chart");
  const s = chart.addLineSeries({ color: "#7c3aed", lineWidth: 2, priceFormat: { type: "custom", formatter: (v) => fmt.count(v) } });
  const seen = new Set();
  s.setData(rows.filter((r) => !seen.has(r.period_end) && seen.add(r.period_end)).map((r) => ({ time: r.period_end, value: r.adjusted })));
  chart.timeScale().fitContent();
}

let insState = null;
function renderInsiders(ins, c) {
  insState = ins;
  drawInsiderChart();
  const fresh = c.freshness?.insider_filings || c.freshness?.prices;
  const since = fresh ? monthsBefore(fresh, 12) : "0000";
  const last12 = ins.trades.filter((t) => (t.trade_date || "") >= since);
  const sum = (side) => last12.filter((t) => t.side === side).reduce((s, t) => s + (t.value_usd || 0), 0);
  const people = (side) => new Set(last12.filter((t) => t.side === side).map((t) => t.owner)).size;
  $("#insider-summary").innerHTML = `
    <div><span>Bought, last 12 months</span><b class="up">${fmt.money(sum("buy"))}</b><span>${people("buy")} insider${people("buy") === 1 ? "" : "s"}</span></div>
    <div><span>Sold, last 12 months</span><b class="down">${fmt.money(sum("sell"))}</b><span>${people("sell")} insider${people("sell") === 1 ? "" : "s"}</span></div>`;
  drawTrades(false);
}
function drawInsiderChart() {
  const ins = insState; if (!ins) return;
  if (!ins.monthly.length) { emptyIn("insider-chart", "No insider trades reported (Form 4) for this company."); return; }
  const hide = $("#hide-planned").checked;
  const chart = chartIn("insider-chart");
  const money = { type: "custom", formatter: (v) => fmt.money(Math.abs(v)) };
  const buy = chart.addHistogramSeries({ color: "#059669", priceFormat: money });
  const sell = chart.addHistogramSeries({ color: "#dc2626", priceFormat: money });
  buy.setData(ins.monthly.map((m) => ({ time: m.month, value: m.bought || 0 })));
  sell.setData(ins.monthly.map((m) => ({ time: m.month, value: -((hide ? m.sold_unplanned : m.sold) || 0) })));
  const last = ins.monthly[ins.monthly.length - 1].month, first = ins.monthly[0].month;
  const from = monthsBefore(last, 24);
  chart.timeScale().setVisibleRange({ from: from < first ? first : from, to: last });
}
$("#hide-planned").addEventListener("change", () => { drawInsiderChart(); drawTrades(false); });
function drawTrades(all) {
  const ins = insState; if (!ins) return;
  const hide = $("#hide-planned").checked;
  const rows = ins.trades.filter((t) => !(hide && t.side === "sell" && t.planned));
  const shown = all ? rows : rows.slice(0, 15);
  $("#trades-meta").textContent = `${fmt.int(rows.length)} Form 4 filings`;
  $("#trades").innerHTML = rows.length ? `<thead><tr><th>Trade date</th><th>Insider</th><th>Role</th><th>Buy / sell</th>
      <th class="num">Shares</th><th class="num">Avg price</th><th class="num">Value</th><th>Pre-planned</th><th>Filing</th></tr></thead><tbody>` +
    shown.map((t) => `<tr><td>${fmt.date(t.trade_date)}</td><td>${esc(t.owner || "")}</td>
      <td>${esc(ROLE[t.role] || t.role || "")}</td><td class="side ${t.side}">${t.side === "buy" ? "Buy" : "Sell"}</td>
      <td class="num">${fmt.count(t.shares)}</td><td class="num">${fmt.price(t.avg_price)}</td><td class="num">${fmt.money(t.value_usd)}</td>
      <td>${t.planned ? "Yes (10b5-1)" : ""}</td><td>${t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener">Form 4 ↗</a>` : ""}</td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="muted">No insider trades reported for this company.</td></tr></tbody>`;
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
  const tab = (k, label, n) => `<button data-k="${k || ""}" class="${(k || null) === kind ? "on" : ""}">${esc(label)} · ${fmt.int(n)}</button>`;
  $("#kind-tabs").innerHTML = tab(null, "All", all) + Object.entries(window.KINDS).filter(([k]) => f.counts[k]).map(([k, label]) => tab(k, label, f.counts[k])).join("");
  document.querySelectorAll("#kind-tabs button").forEach((b) => b.addEventListener("click", () => loadFilings(cik, b.dataset.k || null)));
  $("#filings").innerHTML = f.filings.length ? `<thead><tr><th>Filed</th><th>Form</th><th>What it is</th><th></th><th>Link</th></tr></thead><tbody>` +
    f.filings.map((r) => {
      const a = r.about, items = r.item_list || [];
      const dil = a.dilution_signal || items.some((i) => i.dilution_signal);
      return `<tr><td class="nowrap">${fmt.date(r.filing_date)}</td>
        <td><span class="form ${dil ? "dil" : ""}" data-tip="${esc(a.description)}">${esc(r.form)}</span></td>
        <td><b>${esc(a.name)}</b>${r.report_date && r.report_date !== r.filing_date ? ` <span class="muted small">· period ${fmt.date(r.report_date)}</span>` : ""}
          ${items.length ? `<ul class="items">${items.map((i) => `<li><b>${esc(i.item)}</b> ${esc(i.name)}${i.dilution_signal ? ' <span class="flag">new shares</span>' : ""}</li>`).join("")}</ul>` : `<div class="muted small">${esc(a.description)}</div>`}</td>
        <td>${dil && !items.length ? '<span class="flag">new shares</span>' : ""}</td>
        <td>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">View ↗</a>` : ""}</td></tr>`;
    }).join("") + "</tbody>" : `<tbody><tr><td class="muted">No filings of this kind.</td></tr></tbody>`;
  const more = $("#filings-more"); more.hidden = f.filings.length >= f.total;
  more.textContent = `Show more (${fmt.int(f.total - f.filings.length)} older)`;
  more.onclick = () => loadFilings(cik, filingKind, filingLimit + 200);
}

/* ---------- short selling, diagnostics ---------- */
function renderShort(c) {
  const k = c.card || {};
  $("#short").innerHTML = finite(k.short_ratio_1m) ? `
    <dl class="kv"><dt>Short-sale share of volume, last month</dt><dd><b>${fmt.pct(k.short_ratio_1m)}</b></dd>
      <dt>Last 3 months</dt><dd>${fmt.pct(k.short_ratio_3m)}</dd>
      <dt>Change</dt><dd>${finite(k.short_ratio_chg) ? `${(k.short_ratio_chg * 100).toFixed(1)} pts` : "–"}</dd>
      <dt>Data to</dt><dd>${fmt.date(c.freshness?.short_volume)}</dd></dl>
    <p class="note">The share of the stock's off-exchange trading that was short sales (FINRA daily files). Most stocks sit
      around 40–50%, because market makers sell short to fill buy orders; compare a stock with its own history. This is not
      short interest (the shares sold short and not yet bought back).</p>`
    : `<div class="empty">No short-sale data for this company.</div>`;
}

function renderDiagnostics(c) {
  const d = c.diagnostics || {}, pr = d.prices || {}, fr = d.freshness || {}, m = c.model || {}, mc = m.card || {};
  const lastOf = (form) => (d.last_filings || []).find((r) => r.form === form);
  const ty = mc.test_years || {};
  const levels = [["base_rate", "Base rate"], ["rule", "Offering rule"], ["logistic", "Logistic regression"], ["boosting", "LightGBM (chosen)"]];
  const dil = c.dilution || {};
  $("#diagnostics").innerHTML = `
    <div><h3>The data behind this page</h3>
      <dl class="kv">
        <dt>Prices</dt><dd>${pr.days ? `${esc(pr.sources || "")}, ${fmt.date(pr.first)} to ${fmt.date(pr.last)} · ${fmt.int(pr.days)} trading days${pr.glitch_days ? ` · ${fmt.int(pr.glitch_days)} bad price days left out` : ""}` : "none"}</dd>
        <dt>SEC filings</dt><dd>${fmt.int(d.filings)} in all${lastOf("8-K") ? ` · last 8-K ${fmt.date(lastOf("8-K").last)}` : ""}</dd>
        <dt>Annual / quarterly</dt><dd>${lastOf("10-K") ? `10-K ${fmt.date(lastOf("10-K").last)}` : lastOf("20-F") ? `20-F ${fmt.date(lastOf("20-F").last)}` : "–"}${lastOf("10-Q") ? ` · 10-Q ${fmt.date(lastOf("10-Q").last)}` : ""}</dd>
        <dt>Insider filings</dt><dd>${fmt.int(d.insider_filings)} Form 4${lastOf("4") ? ` · last ${fmt.date(lastOf("4").last)}` : ""}</dd>
        <dt>Coverage</dt><dd>${esc((c.card || {}).coverage || "–")}${(c.card || {}).eligible_dilution ? " · in the dilution question" : " · outside the dilution question"}</dd>
        <dt>Sources current to</dt><dd>prices ${fmt.date(fr.prices)} · filings ${fmt.date(fr.filings)} · Form 4 ${fmt.date(fr.insider_filings)} · short sales ${fmt.date(fr.short_volume)} · financials ${fmt.date(fr.financials)}</dd>
      </dl>
      <p class="note">Prices are adjusted for stock splits. Share counts and financial values are shown as first reported, never revised later, so the forecast only uses what was known at the time.</p>
    </div>
    <div><h3>How the dilution forecast works</h3>
      <dl class="kv"><dt>Model</dt><dd>${esc(m.model || "–")}</dd><dt>Approved</dt><dd>${esc(m.approved || "–")}</dd>
        <dt>Learned from</dt><dd>answers known before ${fmt.date(m.cutoff)} (trees trained through ${fmt.date(m.trained_through)})</dd>
        <dt>Frozen</dt><dd>run ${esc(String(m.frozen_run || "").slice(0, 8))} · data ${esc(m.data_hash || "")} · export ${esc(m.export_date || "")}</dd></dl>
      <h3 style="margin-top:12px">Test years: log loss (lower is better)</h3>
      <table class="record"><tr><th>Level</th>${Object.keys(ty).map((y) => `<th>${y}</th>`).join("")}</tr>
        ${levels.map(([k, label]) => `<tr><td>${label}</td>${Object.values(ty).map((r) => `<td>${finite(r[k]) ? r[k].toFixed(3) : "–"}</td>`).join("")}</tr>`).join("")}</table>
      <h3 style="margin-top:12px">Calibration: forecast against what happened (all test years)</h3>
      <table class="record"><tr><th>Band</th><th>Companies</th><th>Forecast</th><th>Diluted</th></tr>
        ${(mc.bands_pooled?.data || []).map(([b, n, f, r]) => `<tr><td>${b} · ${BAND[b]}</td><td>${fmt.count(n)}</td><td>${fmt.pct(f)}</td><td>${fmt.pct(r)}</td></tr>`).join("")}</table>
      ${dil.available ? `<h3 style="margin-top:12px">Every factor behind this forecast</h3>
        <div class="factors"><table class="record"><tr><th>Factor</th><th>Value</th><th>Effect</th></tr>
          ${dil.factors.map((f) => `<tr><td>${esc(f.label)}</td><td>${fmt.value(f.kind, f.value)}</td><td class="${f.effect > 0 ? "down" : "up"}">${f.effect > 0 ? "+" : ""}${f.effect.toFixed(3)}</td></tr>`).join("")}</table></div>
        <p class="note">Effect: how much the factor moved this company's forecast up (+) or down (−) from the average, on the model's log-odds scale.</p>` : ""}
      <p class="note">Limits: no forecast for foreign filers or companies no longer trading; learned from 2012–2022.
        ${mc.holdout ? "The one-time test on 2023+ data has been run (see the model report)." : "The one-time test on data from 2023 on, which the model has never seen, has not been run yet; its result will appear here."}</p>
    </div>`;
}

/* ---------- start ---------- */
window.KINDS = window.KINDS || {};
const freshEl = $("#fresh-date"); if (freshEl) freshEl.textContent = fmt.date(freshEl.dataset.date);
function route() {
  const cik = new URLSearchParams(location.search).get("cik");
  if (cik) show(cik, false); else landing();
}
window.addEventListener("popstate", route);
route();
