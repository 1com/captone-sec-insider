/* EDGAR-SENTINEL MVP: tabs, theme, charts (ECharts), screener and company lookup. */
(function () {
  "use strict";

  const DATA = JSON.parse(document.getElementById("dashboard-data").textContent);
  const MODE = window.MVP_MODE || "local";
  const root = document.documentElement;
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TABS = ["screener", "overview", "findings", "model", "company", "method"];
  const GROUPS = { A: "Clusters", B1: "Solo CEO/CFO" };

  /* ---------- formatting ---------- */
  function pct(x, digits, signed) {
    if (x === null || x === undefined || !isFinite(x)) return "–";
    const d = digits === undefined ? 1 : digits;
    const sign = signed === false ? (x < 0 ? "−" : "") : (x > 0 ? "+" : x < 0 ? "−" : "");
    return sign + Math.abs(x * 100).toFixed(d) + "%";
  }
  function money(x) {
    if (x === null || x === undefined || !isFinite(x)) return "–";
    const a = Math.abs(x);
    const units = [[1e9, "B"], [1e6, "M"], [1e3, "k"]];
    for (const [div, u] of units) {
      if (a >= div) return (x < 0 ? "−$" : "$") + (a / div).toFixed(a < 10 * div ? 1 : 0) + u;
    }
    return (x < 0 ? "−$" : "$") + a.toFixed(0);
  }
  function num(x) { return x === null || x === undefined ? "–" : Number(x).toLocaleString("en-US"); }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  function signed(x, d) {
    const cls = x > 0 ? "pos" : x < 0 ? "neg" : "";
    return '<span class="' + cls + '">' + pct(x, d) + "</span>";
  }
  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }
  function chip(group, short) {
    const label = group === "A" ? "Cluster" : (short ? "CEO/CFO" : "Solo CEO/CFO");
    return '<span class="chip ' + group.toLowerCase() + '"><i></i>' + label + "</span>";
  }

  /* ---------- theme ---------- */
  const STORE = "edgar-sentinel-theme";
  function stored() { try { return localStorage.getItem(STORE); } catch (e) { return null; } }
  function remember(v) { try { localStorage.setItem(STORE, v); } catch (e) { /* storage blocked */ } }
  const saved = stored();
  if (saved === "dark" || saved === "light") root.setAttribute("data-theme", saved);
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  function effectiveTheme() {
    return root.getAttribute("data-theme") || (darkQuery.matches ? "dark" : "light");
  }
  $("#theme-toggle").addEventListener("click", () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    remember(next);
    refreshCharts();
    refreshTradingView();
  });
  if (darkQuery.addEventListener) {
    darkQuery.addEventListener("change", () => {
      if (!root.getAttribute("data-theme")) { refreshCharts(); refreshTradingView(); }
    });
  }
  const css = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  function palette() {
    return {
      ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), line: css("--line"),
      surface: css("--surface"), s1: css("--s1"), s2: css("--s2"), s3: css("--s3"),
      ref: css("--ref"), font: css("--font-sans") || "system-ui, sans-serif",
    };
  }

  /* ---------- chart plumbing ---------- */
  const charts = new Map();
  const hasCharts = typeof window.echarts !== "undefined";
  function draw(id, build) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!hasCharts) {
      el.innerHTML = '<p class="empty">Charts could not load (no internet connection?). The numbers are in the table below.</p>';
      el.style.height = "auto";
      const toggle = document.querySelector('[data-table-toggle="table-' + id.replace("chart-", "") + '"]');
      if (toggle) openTable(toggle.getAttribute("data-table-toggle"));
      return;
    }
    let entry = charts.get(id);
    if (!entry || entry.inst.isDisposed() || entry.inst.getDom() !== el) {
      entry = { inst: window.echarts.init(el, null, { renderer: "svg" }), build: build };
      charts.set(id, entry);
    }
    entry.build = build;
    entry.inst.setOption(build(), true);
  }
  function refreshCharts() {
    charts.forEach((entry, id) => {
      const el = document.getElementById(id);
      if (el && el.offsetParent !== null && !entry.inst.isDisposed()) entry.inst.setOption(entry.build(), true);
    });
  }
  window.addEventListener("resize", () => charts.forEach((e) => { if (!e.inst.isDisposed()) e.inst.resize(); }));

  function base(t) {
    return {
      animationDuration: reduced ? 0 : 450,
      textStyle: { fontFamily: t.font, color: t.ink2 },
      grid: { left: 8, right: 18, top: 40, bottom: 8, containLabel: true },
      tooltip: {
        backgroundColor: t.surface, borderColor: t.line, borderWidth: 1, padding: [8, 10],
        textStyle: { color: t.ink, fontFamily: t.font, fontSize: 12 },
        extraCssText: "box-shadow:0 6px 18px rgba(0,0,0,.14);border-radius:8px;",
      },
      legend: {
        top: 0, left: 0, icon: "roundRect", itemWidth: 14, itemHeight: 4, itemGap: 18,
        textStyle: { color: t.ink2, fontFamily: t.font, fontSize: 12 },
      },
    };
  }
  function axis(t, extra) {
    return Object.assign({
      axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false },
      axisLabel: { color: t.muted, fontFamily: t.font, fontSize: 11 },
      splitLine: { lineStyle: { color: t.line } },
      nameTextStyle: { color: t.muted, fontFamily: t.font, fontSize: 11 },
    }, extra || {});
  }
  const pctAxis = (v) => (v * 100).toFixed(0) + "%";

  /* ---------- findings: return path with bands ---------- */
  let bench = "iwm";
  function pathOption() {
    const t = palette();
    const b = base(t);
    const ks = DATA.study.ks.map(String);
    const series = [];
    [["A", t.s1], ["B1", t.s2]].forEach(([g, color], gi) => {
      const p = DATA.study.paths[g + "_" + bench];
      if (!p || !p.mean.length) return;
      const band = p.hi.map((h, i) => (h === null || p.lo[i] === null ? null : h - p.lo[i]));
      series.push({ id: g + "-lo", name: GROUPS[g], type: "line", data: p.lo, stack: g, stackStrategy: "all",
        color: color, symbol: "none", lineStyle: { opacity: 0 }, silent: true, tooltip: { show: false } });
      series.push({ id: g + "-band", name: GROUPS[g], type: "line", data: band, stack: g, stackStrategy: "all",
        color: color, symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: color, opacity: 0.09 },
        silent: true, tooltip: { show: false } });
      const line = { id: g + "-mean", name: GROUPS[g], type: "line", data: p.mean, symbol: "none", z: 5, color: color,
        lineStyle: { width: 2, color: color }, itemStyle: { color: color } };
      if (gi === 0) {
        line.markLine = {
          symbol: "none", silent: true,
          lineStyle: { color: t.muted, type: "dashed", width: 1 },
          label: { color: t.muted, fontFamily: t.font, fontSize: 11 },
          data: [
            { xAxis: "0", label: { formatter: "Entry", position: "insideEndTop" } },
            { yAxis: 0, label: { show: false }, lineStyle: { color: t.ref, type: "solid", opacity: 0.6 } },
          ],
        };
      }
      series.push(line);
    });
    return Object.assign(b, {
      legend: Object.assign(b.legend, { data: ["Clusters", "Solo CEO/CFO"] }),
      tooltip: Object.assign(b.tooltip, {
        trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.muted } },
        formatter: (params) => {
          const k = params.length ? params[0].axisValue : "";
          const rows = params.filter((p) => String(p.seriesId || "").endsWith("-mean"))
            .map((p) => {
              const g = p.seriesName === GROUPS.A ? "A" : "B1";
              const path = DATA.study.paths[g + "_" + bench];
              const i = p.dataIndex;
              return p.marker + p.seriesName + ": <b>" + pct(p.value) + "</b> <span style=\"opacity:.7\">(" +
                pct(path.lo[i]) + " to " + pct(path.hi[i]) + ")</span>";
            }).join("<br>");
          return "Day " + k + (k === "0" ? " · entry" : "") + "<br>" + rows;
        },
      }),
      grid: { left: 8, right: 18, top: 40, bottom: 26, containLabel: true },
      xAxis: axis(t, {
        type: "category", data: ks, boundaryGap: false, splitLine: { show: false },
        name: "Trading days from entry", nameLocation: "middle", nameGap: 30,
        axisLabel: { color: t.muted, fontSize: 11, interval: (i, v) => Number(v) % 21 === 0 || Number(v) === -20 },
      }),
      yAxis: axis(t, { type: "value", axisLabel: { color: t.muted, fontSize: 11, formatter: pctAxis } }),
      series: series,
    });
  }

  function yearsOption() {
    const t = palette();
    const b = base(t);
    const years = Array.from(new Set(DATA.study.by_year.map((r) => r.year))).sort();
    const find = (g, y) => DATA.study.by_year.find((r) => r.group === g && r.year === y);
    const make = (g, color) => ({
      name: GROUPS[g], type: "bar", barMaxWidth: 26, barGap: "12%", color: color, itemStyle: { color: color },
      data: years.map((y) => {
        const r = find(g, y);
        const v = r ? r.mean : null;
        return { value: v, n: r ? r.n : 0, itemStyle: { borderRadius: v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4] } };
      }),
    });
    return Object.assign(b, {
      legend: Object.assign(b.legend, { data: ["Clusters", "Solo CEO/CFO"] }),
      tooltip: Object.assign(b.tooltip, {
        trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: "rgba(127,127,127,.08)" } },
        formatter: (params) => params[0].axisValue + "<br>" + params.map((p) =>
          p.marker + p.seriesName + ": <b>" + pct(p.value) + "</b> (" + num(p.data.n) + " events)").join("<br>"),
      }),
      xAxis: axis(t, { type: "category", data: years.map(String), splitLine: { show: false } }),
      yAxis: axis(t, { type: "value", axisLabel: { color: t.muted, fontSize: 11, formatter: pctAxis } }),
      series: [make("A", t.s1), make("B1", t.s2)],
    });
  }

  /* ---------- model ---------- */
  const MODEL_NAMES = { logit: "Logistic regression", lgbm: "LightGBM" };
  function calibrationOption() {
    const t = palette();
    const b = base(t);
    const res = DATA.model.results;
    const sel = DATA.model.selected;
    const pts = (arr) => arr.map((p) => [p.pred, p.obs, p.n]);
    const all = res[sel].calibration.concat(res.baseline.calibration);
    const vals = all.flatMap((p) => [p.pred, p.obs]);
    const lo = Math.max(0, Math.floor((Math.min.apply(null, vals) - 0.04) * 20) / 20);
    const hi = Math.min(1, Math.ceil((Math.max.apply(null, vals) + 0.04) * 20) / 20);
    const fmt = (v) => (v * 100).toFixed(0) + "%";
    return Object.assign(b, {
      legend: Object.assign(b.legend, { data: [MODEL_NAMES[sel], "Market-only baseline"] }),
      tooltip: Object.assign(b.tooltip, {
        trigger: "item",
        formatter: (p) => p.seriesName + "<br>Predicted <b>" + fmt(p.value[0]) + "</b> · observed <b>" +
          fmt(p.value[1]) + "</b><br>" + num(p.value[2]) + " events",
      }),
      grid: { left: 8, right: 18, top: 40, bottom: 26, containLabel: true },
      xAxis: axis(t, { type: "value", min: lo, max: hi, name: "Predicted chance of a positive net return",
        nameLocation: "middle", nameGap: 30, axisLabel: { color: t.muted, fontSize: 11, formatter: fmt } }),
      yAxis: axis(t, { type: "value", min: lo, max: hi, axisLabel: { color: t.muted, fontSize: 11, formatter: fmt } }),
      series: [
        { name: "Perfect calibration", type: "line", data: [[lo, lo], [hi, hi]], symbol: "none", silent: true,
          lineStyle: { type: "dashed", color: t.ref, width: 1.5 }, tooltip: { show: false } },
        { name: MODEL_NAMES[sel], color: t.s1, type: "line", data: pts(res[sel].calibration), symbol: "circle",
          symbolSize: 9, lineStyle: { width: 2, color: t.s1 }, itemStyle: { color: t.s1, borderColor: t.surface, borderWidth: 2 } },
        { name: "Market-only baseline", color: t.s3, type: "line", data: pts(res.baseline.calibration), symbol: "circle",
          symbolSize: 9, lineStyle: { width: 2, color: t.s3 }, itemStyle: { color: t.s3, borderColor: t.surface, borderWidth: 2 } },
      ],
    });
  }

  function driversOption() {
    const t = palette();
    const b = base(t);
    const d = DATA.model.drivers.slice(0, 8).reverse();
    return Object.assign(b, {
      legend: { show: false },
      grid: { left: 8, right: 24, top: 10, bottom: 8, containLabel: true },
      tooltip: Object.assign(b.tooltip, {
        trigger: "item",
        formatter: (p) => {
          const x = d[p.dataIndex];
          return "<b>" + esc(x.label) + "</b><br>Importance " + x.importance.toFixed(4) + " (± " +
            x.std.toFixed(4) + ")<br>More of it " + x.direction + " the score";
        },
      }),
      xAxis: axis(t, { type: "value", axisLabel: { color: t.muted, fontSize: 11, formatter: (v) => v.toFixed(3) } }),
      yAxis: axis(t, { type: "category", data: d.map((x) => x.label), splitLine: { show: false },
        axisLabel: { color: t.ink2, fontSize: 11, width: 210, overflow: "truncate" } }),
      series: [{ type: "bar", barMaxWidth: 16, itemStyle: { color: t.s1 },
        data: d.map((x) => ({ value: x.importance, itemStyle: { borderRadius: x.importance >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4] } })) }],
    });
  }

  /* ---------- "show the numbers" tables ---------- */
  function tableHtml(head, rows, numericFrom) {
    return "<table><thead><tr>" + head.map((h, i) => '<th class="' + (i >= numericFrom ? "num" : "") + '">' + h + "</th>").join("") +
      "</tr></thead><tbody>" + rows.map((r) => "<tr>" + r.map((c, i) => '<td class="' + (i >= numericFrom ? "num" : "") + '">' + c + "</td>").join("") + "</tr>").join("") +
      "</tbody></table>";
  }
  const tables = {
    "table-path": () => {
      const marks = [-20, -10, -1, 0, 4, 20, 62, 125, 251];
      const ks = DATA.study.ks;
      const rows = marks.map((k) => {
        const i = ks.indexOf(k);
        const cell = (g) => {
          const p = DATA.study.paths[g + "_" + bench];
          return i < 0 || !p.mean.length ? "–" : pct(p.mean[i]) + ' <span class="muted">(' + pct(p.lo[i]) + " to " + pct(p.hi[i]) + ")</span>";
        };
        const label = k >= 0 ? "Day " + k + " (" + (k + 1) + " held)" : "Day " + k;
        return [label, cell("A"), cell("B1")];
      });
      return tableHtml(["Trading day", "Clusters", "Solo CEO/CFO"], rows, 1);
    },
    "table-years": () => {
      const years = Array.from(new Set(DATA.study.by_year.map((r) => r.year))).sort();
      const cell = (g, y) => {
        const r = DATA.study.by_year.find((x) => x.group === g && x.year === y);
        return r ? signed(r.mean) + ' <span class="muted">(' + num(r.n) + ")</span>" : "–";
      };
      return tableHtml(["Year", "Clusters (events)", "Solo CEO/CFO (events)"], years.map((y) => [y, cell("A", y), cell("B1", y)]), 1);
    },
    "table-calibration": () => {
      const res = DATA.model.results;
      const rows = [];
      [[DATA.model.selected, MODEL_NAMES[DATA.model.selected]], ["baseline", "Market-only baseline"]].forEach(([k, name]) =>
        res[k].calibration.forEach((p, i) => rows.push([name, "Group " + (i + 1), pct(p.pred, 0, false), pct(p.obs, 0, false), num(p.n)])));
      return tableHtml(["Model", "Score group", "Predicted", "Observed", "Events"], rows, 2);
    },
    "table-drivers": () => tableHtml(["Input", "Importance", "± spread", "More of it…"],
      DATA.model.drivers.map((x) => [esc(x.label), x.importance.toFixed(4), x.std.toFixed(4), x.direction + " the score"]), 1),
  };
  function openTable(id) {
    const box = document.getElementById(id);
    if (!box) return;
    box.innerHTML = tables[id] ? tables[id]() : "";
    box.hidden = false;
    const btn = document.querySelector('[data-table-toggle="' + id + '"]');
    if (btn) btn.textContent = "Hide the numbers";
  }
  function toggleTable(id) {
    const box = document.getElementById(id);
    if (!box) return;
    if (box.hidden) openTable(id);
    else {
      box.hidden = true;
      const btn = document.querySelector('[data-table-toggle="' + id + '"]');
      if (btn) btn.textContent = "Show the numbers";
    }
  }

  /* ---------- screener ---------- */
  let sortKey = "date";
  let sortDir = -1;
  function cmp(a, b) {
    if (a === b) return 0;
    if (a === null || a === undefined) return 1;
    if (b === null || b === undefined) return -1;
    return a < b ? -1 : 1;
  }
  function scoreCell(r) {
    if (r.g8_fail) return '<span class="muted">price check failed</span>';
    if (r.score === null) return '<span class="muted">not priced</span>';
    return '<span class="scorebar"><span class="track"><span class="fill" style="width:' + Math.round(r.score * 100) +
      '%"></span></span><span>' + Math.round(r.score * 100) + "%</span></span>" +
      (r.pct === null ? "" : '<span class="ago">higher than ' + Math.round(r.pct * 100) + "% of pilot events</span>") +
      (r.partial ? '<span class="flag">partial data</span>' : "");
  }
  function screenerRow(r) {
    const win = r.window_open
      ? '<span class="winbar"><span class="track"><span class="fill" style="width:' +
        Math.round((r.left / DATA.meta.horizon) * 100) + '%"></span></span><span>' + r.left + " days</span></span>"
      : '<span class="muted">Window over</span>';
    return '<tr><td><span class="mono">' + esc(r.date) + '</span><span class="ago">' + r.days_since + " days ago</span></td>" +
      "<td>" + win + "</td>" +
      '<td class="wrap-cell"><button class="linkish" data-company="' + esc(r.cik) + '"><span class="ticker">' + esc(r.ticker || "—") + "</span></button> " + esc(r.name) + "</td>" +
      "<td>" + chip(r.group) + "</td>" +
      '<td class="num">' + r.insiders + '</td><td class="num">' + money(r.value) + "</td>" +
      '<td class="muted">' + esc(r.roles) + "</td><td>" + scoreCell(r) + "</td></tr>";
  }
  function renderScreener() {
    const w = $("#f-window").value;
    const g = $("#f-group").value;
    const minS = Number($("#f-score").value);
    const minV = Number($("#f-value").value);
    const q = $("#f-text").value.trim().toLowerCase();
    const list = DATA.screener.filter((r) =>
      (w === "all" || r.window_open) &&
      (g === "all" || r.group === g) &&
      (minS === 0 || (r.score !== null && r.score >= minS)) &&
      r.value >= minV &&
      (!q || r.name.toLowerCase().includes(q) || (r.ticker || "").toLowerCase().startsWith(q)));
    list.sort((a, b) => cmp(a[sortKey], b[sortKey]) * sortDir || cmp(b.value, a.value));
    $("#screener-body").innerHTML = list.length ? list.map(screenerRow).join("") :
      '<tr><td colspan="8" class="empty">No events match these filters. Try a lower minimum score or value.</td></tr>';
    $("#screener-count").textContent = list.length + " of " + DATA.screener.length + " events";
    $$("#screener-table th.sortable").forEach((th) => {
      th.setAttribute("aria-sort", th.dataset.sort === sortKey ? (sortDir > 0 ? "ascending" : "descending") : "none");
    });
  }
  ["f-window", "f-group", "f-score", "f-value"].forEach((id) => $("#" + id).addEventListener("change", renderScreener));
  $("#f-text").addEventListener("input", renderScreener);
  $$("#screener-table th.sortable").forEach((th) => {
    th.tabIndex = 0;
    const act = () => {
      const k = th.dataset.sort;
      if (sortKey === k) sortDir = -sortDir;
      else { sortKey = k; sortDir = ["name", "group"].includes(k) ? 1 : -1; }
      renderScreener();
    };
    th.addEventListener("click", act);
    th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); } });
  });

  /* ---------- company lookup ---------- */
  const index = DATA.search.map((r) => ({ cik: r[0], name: r[1], ticker: r[2] || "", lname: r[1].toLowerCase(), lt: (r[2] || "").toLowerCase() }));
  const shardCache = new Map();
  let currentProfile = null;
  async function loadProfile(cik) {
    if (DATA.featured_profile && DATA.featured_profile.cik === cik) return DATA.featured_profile;
    const k = Number(cik) % DATA.meta.shards;
    if (!shardCache.has(k)) {
      const res = await fetch("data/companies-" + k + ".json");
      if (!res.ok) throw new Error("HTTP " + res.status);
      shardCache.set(k, await res.json());
    }
    return shardCache.get(k)[cik] || null;
  }
  const TV_EXCH = { Nasdaq: "NASDAQ", NYSE: "NYSE", OTC: "OTC", CBOE: "CBOE" };
  function tvSymbol(p) { return p.ticker ? ((TV_EXCH[p.exchange] ? TV_EXCH[p.exchange] + ":" : "") + p.ticker) : null; }
  function tvUrl(p) {
    const ex = TV_EXCH[p.exchange];
    return "https://www.tradingview.com/symbols/" + (ex ? ex + "-" : "") + encodeURIComponent(p.ticker) + "/";
  }
  function quarterRange() {
    const out = [];
    for (let y = 2006; y <= 2026; y++) for (let q = 1; q <= 4; q++) { if (y === 2026 && q > 3) break; out.push(y + "Q" + q); }
    return out;
  }
  function companyOption(p) {
    const t = palette();
    const b = base(t);
    const qs = quarterRange();
    const map = new Map(p.quarters.map((r) => [r[0], r]));
    const buys = qs.map((q) => { const r = map.get(q); return r ? r[1] : 0; });
    const sells = qs.map((q) => { const r = map.get(q); return r ? -r[3] : 0; });
    return Object.assign(b, {
      legend: Object.assign(b.legend, { data: ["Insider buying", "Insider selling"] }),
      tooltip: Object.assign(b.tooltip, {
        trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: "rgba(127,127,127,.08)" } },
        formatter: (params) => {
          const r = map.get(params[0].axisValue);
          const bn = r ? r[2] : 0, sn = r ? r[4] : 0;
          return params[0].axisValue + "<br>" + params[0].marker + "Buying: <b>" + money(r ? r[1] : 0) + "</b> (" + bn + " filings)<br>" +
            (params[1] ? params[1].marker : "") + "Selling: <b>" + money(r ? r[3] : 0) + "</b> (" + sn + " filings)";
        },
      }),
      xAxis: axis(t, { type: "category", data: qs, splitLine: { show: false },
        axisLabel: { color: t.muted, fontSize: 11, interval: (i, v) => v.endsWith("Q1") && Number(v.slice(0, 4)) % 2 === 0, formatter: (v) => v.slice(0, 4) } }),
      yAxis: axis(t, { type: "value", axisLabel: { color: t.muted, fontSize: 11, formatter: (v) => money(Math.abs(v)) } }),
      series: [
        { name: "Insider buying", color: t.s1, type: "bar", stack: "flow", data: buys, barMaxWidth: 10, itemStyle: { color: t.s1, borderRadius: [3, 3, 0, 0] } },
        { name: "Insider selling", color: t.s2, type: "bar", stack: "flow", data: sells, barMaxWidth: 10, itemStyle: { color: t.s2, borderRadius: [0, 0, 3, 3] } },
      ],
    });
  }
  function renderProfile(p) {
    currentProfile = p;
    const box = $("#company-profile");
    const tot = p.totals || {};
    const edgar = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=" + encodeURIComponent(p.cik) + "&type=4&owner=include&count=40";
    const status = p.listed ? esc(p.exchange || "Listed") : "No longer listed";
    let html = '<article class="card"><div class="company-head"><div style="display:grid;gap:6px;min-width:0">' +
      "<h2>" + esc(p.name) + "</h2>" +
      '<div class="company-meta">' + (p.ticker ? '<span class="ticker">' + esc(p.ticker) + "</span>" : (p.reported ? '<span class="ticker muted">' + esc(p.reported) + "</span>" : "")) +
      "<span>" + status + '</span><span class="mono">CIK ' + esc(p.cik) + "</span></div></div>" +
      '<div class="links"><a class="btn" href="' + edgar + '" target="_blank" rel="noopener">Form 4 filings on SEC EDGAR ↗</a>' +
      (p.listed && p.ticker ? '<a class="btn" href="' + tvUrl(p) + '" target="_blank" rel="noopener">Price chart on TradingView ↗</a>' : "") +
      "</div></div></article>";
    html += '<div class="kpis">' +
      '<div class="kpi"><span class="kpi-label"><i class="dot" style="background:var(--s1)"></i>Insider purchase filings</span><span class="kpi-value">' + num(tot.buys || 0) + '</span><span class="kpi-sub">' + money(tot.buy_v || 0) + " in total</span></div>" +
      '<div class="kpi"><span class="kpi-label"><i class="dot" style="background:var(--s2)"></i>Insider sale filings</span><span class="kpi-value">' + num(tot.sells || 0) + '</span><span class="kpi-sub">' + money(tot.sell_v || 0) + " in total</span></div>" +
      '<div class="kpi"><span class="kpi-label">Insider events</span><span class="kpi-value">' + p.events.length + '</span><span class="kpi-sub">' +
      plural(p.events.filter((e) => e[1] === "A").length, "cluster") + " · " + p.events.filter((e) => e[1] === "B1").length + " solo CEO/CFO</span></div>" +
      '<div class="kpi"><span class="kpi-label">Latest Form 4 in the data</span><span class="kpi-value" style="font-size:1.35rem">' + esc(tot.last_date || "–") + '</span><span class="kpi-sub">Purchases and sales only</span></div></div>';
    html += '<article class="card"><div class="card-head"><div><h2>Insider buying and selling by quarter</h2>' +
      '<p class="card-sub">Dollar value of open-market purchases (code P) above the line and sales (code S) below it, by filing quarter.</p></div></div>' +
      '<div class="chart short" id="chart-company" role="img" aria-label="Quarterly insider buying and selling"></div>' +
      '<p class="source">Source: SEC Form 4 filings, original reports only.</p></article>';
    const evRows = p.events.map((e) => [esc(e[0]), chip(e[1]), e[2], money(e[3]),
      e[4] === null ? '<span class="muted">' + (Number(e[0].slice(0, 4)) <= 2011 ? "pilot event" : "–") + "</span>" : Math.round(e[4] * 100) + "%"]);
    const fRows = p.filings.map((f) => [esc(f[0]), f[1] === "P" ? '<span class="pos">Buy</span>' : '<span class="neg">Sell</span>',
      esc(f[2]), '<span class="muted">' + esc(f[3]) + "</span>", num(f[4]), money(f[5]),
      '<a href="https://www.sec.gov/Archives/edgar/data/' + encodeURIComponent(p.cik) + "/" + esc(String(f[6]).replace(/-/g, "")) + '/" target="_blank" rel="noopener">Filing ↗</a>']);
    html += '<div class="grid">' +
      '<article class="card"><h2>Insider events</h2>' + (evRows.length ?
        '<div class="table-wrap">' + tableHtml(["Filed", "Type", "Insiders", "Value", "Score"], evRows, 2) + "</div>" :
        '<p class="empty">No events.</p>') + '<p class="source">Scores exist only for Jul–Sep 2026 events.</p></article>' +
      '<article class="card"><h2>Recent insider filings</h2>' + (fRows.length ?
        '<div class="table-wrap">' + tableHtml(["Filed", "Trade", "Role", "Insider", "Shares", "Value", ""], fRows, 4) + "</div>" :
        '<p class="empty">No purchases or sales on file.</p>') + "</article></div>";
    if (MODE === "local" && p.listed && p.ticker) {
      html += '<article class="card"><div class="card-head"><div><h2>Price chart</h2><p class="card-sub">Live chart from TradingView, licensed for display. Not part of the study data.</p></div></div><div class="tv" id="tv-box"></div></article>';
    }
    box.innerHTML = html;
    draw("chart-company", () => companyOption(p));
    refreshTradingView();
  }
  function refreshTradingView() {
    const host = document.getElementById("tv-box");
    if (!host || !currentProfile || MODE !== "local") return;
    host.innerHTML = '<div class="tradingview-widget-container" style="height:100%;width:100%"><div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div></div>';
    const s = document.createElement("script");
    s.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    s.async = true;
    s.text = JSON.stringify({ autosize: true, symbol: tvSymbol(currentProfile), interval: "D", range: "60M",
      timezone: "America/New_York", theme: effectiveTheme(), style: "1", locale: "en", allow_symbol_change: false,
      hide_side_toolbar: true, calendar: false, support_host: "https://www.tradingview.com" });
    s.onerror = () => { host.innerHTML = '<p class="empty">The price chart needs an internet connection.</p>'; };
    host.firstChild.appendChild(s);
  }
  async function openCompany(cik, switchTab) {
    if (switchTab !== false) show("company");
    const box = $("#company-profile");
    box.innerHTML = '<p class="empty">Loading company…</p>';
    try {
      const p = await loadProfile(String(cik));
      if (p) renderProfile(p);
      else box.innerHTML = '<p class="empty">No insider data for this company in the prototype.</p>';
    } catch (e) {
      box.innerHTML = '<p class="empty">Could not load company data (' + esc(e.message) + "). Serve the site with <code>uv run python -m mvp serve</code> rather than opening the file directly.</p>";
    }
  }

  const input = $("#company-search");
  const list = $("#company-suggest");
  let active = -1;
  let matches = [];
  function search(q) {
    q = q.trim().toLowerCase();
    if (!q) return [];
    const exact = [], prefix = [], name = [];
    for (const r of index) {
      if (r.lt === q) exact.push(r);
      else if (r.lt.startsWith(q)) prefix.push(r);
      else if (r.lname.includes(q)) name.push(r);
      if (exact.length + prefix.length + name.length > 200) break;
    }
    return exact.concat(prefix, name).slice(0, 8);
  }
  function renderSuggest() {
    if (!matches.length) { list.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
    list.innerHTML = matches.map((r, i) => '<li role="option" id="opt-' + i + '" data-cik="' + esc(r.cik) + '" aria-selected="' + (i === active) +
      '"><span class="ticker">' + esc(r.ticker || "—") + "</span><span>" + esc(r.name) + "</span></li>").join("");
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }
  function choose(r) {
    if (!r) return;
    input.value = (r.ticker ? r.ticker + " · " : "") + r.name;
    matches = [];
    renderSuggest();
    openCompany(r.cik, false);
  }
  input.addEventListener("input", () => { matches = search(input.value); active = matches.length ? 0 : -1; renderSuggest(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { active = Math.min(active + 1, matches.length - 1); renderSuggest(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); renderSuggest(); e.preventDefault(); }
    else if (e.key === "Enter") { e.preventDefault(); choose(matches[active] || search(input.value)[0]); }
    else if (e.key === "Escape") { matches = []; renderSuggest(); }
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-cik]");
    if (li) { e.preventDefault(); choose(index.find((r) => r.cik === li.dataset.cik)); }
  });
  input.addEventListener("blur", () => setTimeout(() => { matches = []; renderSuggest(); }, 120));

  /* ---------- tabs and delegated clicks ---------- */
  let companyLoaded = false;
  function renderTab(tab) {
    if (tab === "findings") { draw("chart-path", pathOption); draw("chart-years", yearsOption); }
    if (tab === "model") { draw("chart-calibration", calibrationOption); draw("chart-drivers", driversOption); }
    if (tab === "company" && !companyLoaded) {
      companyLoaded = true;
      if (!currentProfile && DATA.featured) openCompany(DATA.featured, false);
    }
    requestAnimationFrame(() => charts.forEach((entry, id) => {
      const el = document.getElementById(id);
      if (el && el.offsetParent !== null && !entry.inst.isDisposed()) entry.inst.resize();
    }));
  }
  function show(tab, updateHash) {
    if (!TABS.includes(tab)) tab = "screener";
    $$('[role="tabpanel"]').forEach((p) => { p.hidden = p.id !== tab; });
    $$(".tab").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false"));
    if (updateHash !== false) { try { history.replaceState(null, "", "#" + tab); } catch (e) { /* sandboxed */ } }
    if (tab === "company") companyLoaded = companyLoaded || !!currentProfile;
    renderTab(tab);
    window.scrollTo(0, 0);
  }
  document.addEventListener("click", (e) => {
    const tabEl = e.target.closest("[data-tab]");
    if (tabEl) { e.preventDefault(); show(tabEl.dataset.tab); return; }
    const co = e.target.closest("[data-company]");
    if (co) { e.preventDefault(); openCompany(co.dataset.company); return; }
    const tt = e.target.closest("[data-table-toggle]");
    if (tt) { e.preventDefault(); toggleTable(tt.getAttribute("data-table-toggle")); return; }
    const bb = e.target.closest("[data-bench]");
    if (bb) {
      bench = bb.dataset.bench;
      $$("[data-bench]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.bench === bench ? "true" : "false"));
      $$("[data-bench-table]").forEach((x) => { x.hidden = x.dataset.benchTable !== bench; });
      draw("chart-path", pathOption);
      const pt = document.getElementById("table-path");
      if (pt && !pt.hidden) openTable("table-path");
    }
  });
  $(".tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const cur = TABS.indexOf(($('.tab[aria-selected="true"]') || {}).dataset.tab);
    const next = TABS[(cur + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    show(next);
    $("#tab-" + next).focus();
  });

  const start = (location.hash || "").replace("#", "");
  renderScreener();
  show(TABS.includes(start) ? start : "screener", false);
  window.addEventListener("load", () => { if (start) window.scrollTo(0, 0); });
})();
