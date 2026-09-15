function qs(name) {
  return new URLSearchParams(location.search).get(name);
}

function withMonth(path) {
  const month = qs("month");
  if (!month) return path;
  const join = path.includes("?") ? "&" : "?";
  return `${path}${join}month=${encodeURIComponent(month)}`;
}

function renderTrail(steps) {
  if (!steps || !steps.length) return "";
  return steps
    .map((p, i) => {
      const sep = i ? `<span class="trail-sep" aria-hidden="true">→</span>` : "";
      const now = i === steps.length - 1 ? " now" : "";
      return `${sep}<span class="pill ${p.cls || ""}${now}">${p.s}</span>`;
    })
    .join("");
}

function lastTrailClass(steps) {
  if (!steps || !steps.length) return "";
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    if (steps[i].cls) return steps[i].cls;
  }
  return "";
}

function setPageLoader(on, label) {
  const el = document.getElementById("page-loader");
  if (!el) return;
  el.classList.toggle("hidden", !on);
  el.setAttribute("aria-busy", on ? "true" : "false");
  const text = el.querySelector("p");
  if (text && label) text.textContent = label;
}

async function fetchApi(path) {
  const res = await fetch(withMonth(path));
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

function renderMonths(nav, months, selected, hrefFor) {
  if (!nav) return;
  nav.replaceChildren();
  months.forEach((m) => {
    const a = document.createElement("a");
    a.href = hrefFor(m.key);
    a.textContent = m.label;
    if (m.key === selected) a.className = "on";
    nav.append(a);
  });
}

function initTabs() {
  const bar = document.querySelector(".sticky-bar");
  const tabs = [...document.querySelectorAll(".section-tabs [data-target]")];
  const sections = tabs
    .map((tab) => document.getElementById(tab.dataset.target))
    .filter(Boolean);
  if (!bar || !tabs.length || !sections.length) return;
  let locked = false;

  function activate(id) {
    tabs.forEach((tab) => {
      const on = tab.dataset.target === id;
      tab.classList.toggle("on", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
  }

  function offset() {
    return bar.getBoundingClientRect().height + 8;
  }

  function goTo(id) {
    const target = document.getElementById(id);
    if (!target) return;
    locked = true;
    activate(id);
    const top = window.scrollY + target.getBoundingClientRect().top - offset();
    window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    window.setTimeout(() => {
      locked = false;
      sync();
    }, 500);
  }

  function sync() {
    if (locked) return;
    const line = offset();
    let current = sections[0];
    for (const section of sections) {
      if (section.getBoundingClientRect().top - line <= 20) current = section;
    }
    if (current) activate(current.id);
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => goTo(tab.dataset.target));
  });
  window.addEventListener("scroll", sync, { passive: true });
  window.addEventListener("resize", sync);
  sync();
}

async function loadHome() {
  const board = document.getElementById("board");
  const empty = document.getElementById("empty");
  setPageLoader(true, "Loading market data");
  let meta;
  try {
    meta = await fetchApi("/api/meta");
  } catch (err) {
    empty.classList.remove("hidden");
    empty.querySelector("p").textContent = "Could not reach the data API.";
    setPageLoader(false);
    return;
  }
  if (meta.empty) {
    empty.classList.remove("hidden");
    board.classList.add("hidden");
    setPageLoader(false);
    return;
  }
  empty.classList.add("hidden");
  board.classList.remove("hidden");
  renderMonths(document.getElementById("months"), meta.months, meta.month, (key) => `/?month=${key}`);
  const updated = document.getElementById("last-updated");
  if (updated && meta.run && meta.run.finished_at) {
    updated.textContent = ` Last updated: ${meta.run.finished_at}`;
  }
  if (meta.errors && meta.errors.length) {
    document.getElementById("notes-tab").classList.remove("hidden");
    const notes = document.getElementById("notes");
    notes.classList.remove("hidden");
    document.getElementById("notes-list").innerHTML = meta.errors.map((e) => `<li>${e}</li>`).join("");
  }
  initTabs();

  const marketEl = document.getElementById("market");
  const sectorsEl = document.getElementById("sectors");
  const chartEl = document.getElementById("charts");

  const marketP = fetchApi("/api/market").then((data) => {
    const flow = data.flow || {};
    marketEl.querySelector(".panel-body").innerHTML = `
      <p class="eyebrow">${data.month_label || ""} · as of ${data.as_of || "—"}</p>
      <h2>Market Regime: ${data.regime_mark || ""} ${data.regime || "—"}</h2>
      <div class="chips">
        <article class="chip-hit" data-flow="fpi" role="button" tabindex="0" aria-expanded="false" aria-controls="flow-daily-modal">
          <span>FPI / FII net</span>
          <strong class="${flow.fpi_cls || ""}">${flow.fpi_s || "—"}</strong>
          ${flow.fpi_trail_steps && flow.fpi_trail_steps.length ? `<div class="trail">${renderTrail(flow.fpi_trail_steps)}</div>` : ""}
          <em>NSDL monthly · click for month-wise and daily</em>
        </article>
        <article class="chip-hit" data-flow="dii" role="button" tabindex="0" aria-expanded="false" aria-controls="flow-daily-modal">
          <span>DII net</span>
          <strong class="${flow.dii_cls || ""}">${flow.dii_s || "—"}</strong>
          ${flow.dii_trail_steps && flow.dii_trail_steps.length ? `<div class="trail">${renderTrail(flow.dii_trail_steps)}</div>` : ""}
          <em>AMFI monthly note · click for month-wise and daily</em>
        </article>
        <article>
          <span>Mutual funds equity net</span>
          <strong class="${flow.mf_cls || ""}">${flow.mf_s || "—"}</strong>
          <em>AMFI monthly equity inflow</em>
        </article>
      </div>`;
    bindFlowChips();
  });

  const sectorsP = fetchApi("/api/sectors").then((data) => {
    const rows = data.rows || [];
    const body = rows.map((r) =>
      `<tr data-score="${r.score == null ? "" : r.score}" data-fpi="${r.fpi_val == null ? "" : r.fpi_val}">
        <td class="rank">${r.rank}</td>
        <td><a href="/sector/${r.slug}?month=${data.month}">${r.sector}</a></td>
        <td>${r.mark || ""} ${r.signal || "—"}</td>
        <td class="score-cell">
          <div class="score-now ${lastTrailClass(r.trail_steps)}">${r.score_s}</div>
          <div class="trail">${renderTrail(r.trail_steps)}</div>
        </td>
        <td class="fpi-cell ${r.fpi_cls || ""}">
          <div class="score-now ${r.fpi_cls || ""}">${r.fpi_s}</div>
          <div class="trail ${r.fpi_via ? "muted" : ""}">${r.fpi_via ? `via ${r.fpi_via}` : renderTrail(r.fpi_trail_steps)}</div>
        </td>
      </tr>`
    ).join("");
    sectorsEl.querySelector(".panel-body").innerHTML = `
      <h3>Sectors · ${meta.month_label || ""}</h3>
      <p class="hint">Score and FPI trails are last four months. NSDL publishes one FPI figure per industry, so Bank / PSU Bank / Private Bank point to Financial Services.</p>
      <div class="table-wrap">
        <table id="rank-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Sector</th>
              <th>Signal</th>
              <th data-sort="score" class="sortable on">Score</th>
              <th data-sort="fpi" class="sortable">FPI net</th>
            </tr>
          </thead>
          <tbody>${body || `<tr><td colspan="5">No sector scores for this month.</td></tr>`}</tbody>
        </table>
      </div>`;
    bindTableSort("score");
  });

  const chartP = fetchApi("/api/chart").then((data) => {
    chartEl.querySelector(".panel-body").classList.remove("hidden");
    if (data.chart) {
      requestAnimationFrame(() => renderFlowChart(data.chart));
    }
  });

  await Promise.allSettled([marketP, sectorsP, chartP]);
  setPageLoader(false);
}

let flowDailyKind = null;
let flowDailyOpener = null;

function bindFlowChips() {
  document.querySelectorAll("[data-flow]").forEach((el) => {
    el.addEventListener("click", () => toggleFlowDaily(el.dataset.flow, el));
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        toggleFlowDaily(el.dataset.flow, el);
      }
    });
  });
}

function closeFlowDaily() {
  flowDailyKind = null;
  const modal = document.getElementById("flow-daily-modal");
  if (modal) {
    modal.classList.add("hidden");
    modal.hidden = true;
  }
  document.body.classList.remove("modal-open");
  document.querySelectorAll("[data-flow]").forEach((el) => {
    el.classList.remove("on");
    el.setAttribute("aria-expanded", "false");
  });
  if (flowDailyOpener && typeof flowDailyOpener.focus === "function") {
    flowDailyOpener.focus();
  }
  flowDailyOpener = null;
}

async function toggleFlowDaily(kind, opener) {
  if (flowDailyKind === kind) {
    closeFlowDaily();
    return;
  }
  const modal = document.getElementById("flow-daily-modal");
  const title = document.getElementById("flow-daily-title");
  const body = document.getElementById("flow-daily-body");
  if (!modal || !body) return;
  flowDailyOpener = opener || document.querySelector(`[data-flow="${kind}"]`);
  document.querySelectorAll("[data-flow]").forEach((el) => {
    const on = el.dataset.flow === kind;
    el.classList.toggle("on", on);
    el.setAttribute("aria-expanded", on ? "true" : "false");
  });
  flowDailyKind = kind;
  modal.hidden = false;
  modal.classList.remove("hidden");
  document.body.classList.add("modal-open");
  if (title) title.textContent = kind === "dii" ? "DII" : "FPI / FII";
  body.innerHTML = `<p class="hint">Loading ${kind === "dii" ? "DII" : "FPI / FII"}…</p>`;
  const closer = modal.querySelector(".flow-daily-close");
  if (closer) closer.focus();
  try {
    const data = await fetchApi(`/api/flows/daily?kind=${encodeURIComponent(kind)}`);
    renderFlowDaily(data);
  } catch (err) {
    body.innerHTML = `<p class="hint">Could not load ${kind === "dii" ? "DII" : "FPI / FII"}.</p>`;
  }
}

function renderFlowDaily(data) {
  const title = document.getElementById("flow-daily-title");
  const body = document.getElementById("flow-daily-body");
  if (!body) return;
  if (title) title.textContent = `${data.title || "Flows"} · ${data.month_label || ""}`;
  const series = (data.series || [])
    .map((s) => {
      const month = s.period === "month";
      const rows = (s.rows || [])
        .map(
          (r) =>
            `<tr>
              <td>${r.date_s}</td>
              <td>${r.buy_s}</td>
              <td>${r.sell_s}</td>
              <td class="${r.net_cls || ""}">${r.net_s}</td>
            </tr>`
        )
        .join("");
      const tot = s.total || {};
      const foot = (s.rows || []).length
        ? `<tr class="total">
            <td>${month ? "Sum of months" : "Sum of days"}</td>
            <td>${tot.buy_s || "—"}</td>
            <td>${tot.sell_s || "—"}</td>
            <td class="${tot.net_cls || ""}">${tot.net_s || "—"}</td>
          </tr>`
        : "";
      return `
        <div class="flow-daily-block">
          <h4>${s.label}</h4>
          <p class="hint">${s.note || ""}</p>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>${month ? "Month" : "Date"}</th><th>Buy</th><th>Sell</th><th>Net</th></tr>
              </thead>
              <tbody>
                ${rows || `<tr><td colspan="4">${month ? "No monthly rows stored." : "No daily rows stored for this month."}</td></tr>`}
                ${foot}
              </tbody>
            </table>
          </div>
        </div>`;
    })
    .join("");
  body.innerHTML = series;
}

async function loadSector() {
  const slug = document.body.dataset.slug;
  const hero = document.getElementById("sector-hero");
  setPageLoader(true, "Loading sector");
  let data;
  try {
    data = await fetchApi(`/api/sector/${slug}`);
  } catch (err) {
    setPageLoader(false);
    hero.querySelector(".panel-body").innerHTML = "<p class=\"hint\">Could not load this sector.</p>";
    return;
  }
  document.title = `${data.name} · Flowline`;
  document.getElementById("sector-title").textContent = data.name;
  document.getElementById("back-link").href = `/?month=${data.month}`;
  const bar = document.getElementById("sector-bar");
  bar.classList.remove("hidden");
  renderMonths(document.getElementById("months"), data.months, data.month, (key) => `/sector/${slug}?month=${key}`);
  const score = data.score || {};
  const scoreLabel = score.score == null ? "—" : `${Math.round(score.score)}/100`;
  const symbolChip = data.symbol
    ? `<article>
        <span>Index symbol</span>
        <strong><a href="${data.chart_url}" target="_blank" rel="noreferrer">${data.symbol}</a></strong>
        <em>${data.index_name} · TradingView</em>
      </article>`
    : "";
  hero.querySelector(".panel-body").innerHTML = `
    <p class="eyebrow">${data.month} · as of ${score.as_of_date || "—"}</p>
    <h2><span class="${lastTrailClass(data.trail_steps)}">${scoreLabel}</span> — ${data.mark || ""} ${score.signal || ""}</h2>
    ${data.trail_steps && data.trail_steps.length ? `<p class="trail">${renderTrail(data.trail_steps)}</p>` : ""}
    <div class="chips sector-chips">
      <article>
        <span>FPI/FII</span>
        <strong class="${data.fpi_cls || ""}">${data.fpi_s}</strong>
        ${!data.fpi_via && data.fpi_trail_steps && data.fpi_trail_steps.length ? `<div class="trail">${renderTrail(data.fpi_trail_steps)}</div>` : ""}
        <em>${data.fpi_via ? `NSDL reports this under ${data.fpi_via}` : "NSDL sector equity · last four months"}</em>
      </article>
      <article>
        <span>DII net</span>
        <strong class="${data.dii_cls || ""}">${data.dii_s || data.dii_word || "—"}</strong>
        ${data.dii_trail_steps && data.dii_trail_steps.length ? `<div class="trail">${renderTrail(data.dii_trail_steps)}</div>` : ""}
        <em>AMFI monthly note · market-wide, not this sector</em>
      </article>
      <article><span>1M Return</span><strong>${data.ret_1m}</strong><em>vs own index</em></article>
      <article><span>Relative Strength</span><strong>${data.rs}</strong><em>vs NIFTY 500</em></article>
      ${symbolChip}
    </div>`;
  setPageLoader(false);
}

const btn = document.getElementById("update-btn");
const box = document.getElementById("progress");
if (btn && box) {
  const order = [
    "FPI/FII",
    "DII",
    "Mutual Funds",
    "Sector Flows",
    "Market Performance",
    "Sector Performance",
    "Relative Strength",
  ];
  const done = {};

  function render(extra) {
    const lines = ["Scraping into database…"];
    for (const label of order) {
      if (done[label] === true) lines.push(`✓ ${label}`);
      else if (done[label] === false) lines.push(`✗ ${label}`);
    }
    if (extra) lines.push(...extra);
    box.textContent = lines.join("\n");
  }

  btn.addEventListener("click", () => {
    btn.disabled = true;
    box.classList.remove("hidden");
    Object.keys(done).forEach((k) => delete done[k]);
    render(["Working…"]);
    const src = new EventSource("/api/scrape");
    const extra = [];
    src.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "log" && msg.text) extra.push(msg.text);
      if (msg.type === "step" && msg.label) done[msg.label] = !!msg.ok;
      if (msg.type === "month" && msg.text) extra.push(msg.text);
      if (msg.type === "error") extra.push(msg.text || "Update failed");
      if (msg.type === "done") {
        extra.push("✓ Market data updated");
        extra.push(`Historical months updated: ${msg.historical_updated}`);
        extra.push(`Historical months skipped: ${msg.historical_skipped}`);
        extra.push(`Current month updated: ${msg.current_updated ? "YES" : "NO"}`);
        extra.push(`Errors: ${msg.errors}`);
        extra.push(`Last updated: ${msg.last_updated}`);
        src.close();
        btn.disabled = false;
        render(extra);
        setTimeout(() => location.reload(), 800);
        return;
      }
      render(extra.slice(-8));
    };
    src.onerror = () => {
      extra.push("Connection dropped. If the update finished, reload the page.");
      src.close();
      btn.disabled = false;
      render(extra);
    };
  });
}

function bindTableSort(defaultKey) {
  const table = document.getElementById("rank-table");
  if (!table) return;
  let current = defaultKey || "score";
  let dir = -1;

  function val(row, key) {
    const raw = row.dataset[key];
    if (raw === undefined || raw === "") return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function applySort(key, toggle) {
    if (toggle && current === key) dir *= -1;
    else {
      current = key;
      dir = -1;
    }
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    rows.sort((a, b) => {
      const av = val(a, key);
      const bv = val(b, key);
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (av === bv) return 0;
      return av > bv ? dir : -dir;
    });
    rows.forEach((row, i) => {
      row.querySelector(".rank").textContent = String(i + 1);
      tbody.appendChild(row);
    });
    table.querySelectorAll("th.sortable").forEach((el) => {
      el.classList.toggle("on", el.dataset.sort === current);
    });
  }

  table.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => applySort(th.dataset.sort, true));
  });
}


let exitChartFullscreen = function () {};

function renderFlowChart(data) {
  const heatEl = document.getElementById("flow-heat");
  const hoverEl = document.getElementById("chart-hover");
  const heatTitle = document.getElementById("heat-title");
  const splitCanvas = document.getElementById("split-chart");
  const splitCard = document.getElementById("split-card");
  const splitTitle = document.getElementById("split-title");
  const marketCanvas = document.getElementById("market-flow-chart");
  const marketCard = document.getElementById("market-flow-card");
  const marketTitle = document.getElementById("market-flow-title");
  const marketSortBar = document.getElementById("market-sort");
  const modeBar = document.getElementById("chart-mode");
  const sortBar = document.getElementById("chart-sort");
  const dirBtn = document.getElementById("chart-dir");
  const searchEl = document.getElementById("chart-search");
  if (!data || !heatEl || !modeBar) return;

  let view = "fpi";
  let sortMode = "latest";
  let sortCol = -1;
  let sortDir = "desc";
  let marketSort = "time";
  let marketDir = "asc";
  let barChart = null;
  let marketChart = null;

  function hasVals(arr) {
    return Array.isArray(arr) && arr.some((v) => v != null && !Number.isNaN(Number(v)));
  }

  function pack() {
    if (view === "weekly") {
      return {
        labels: data.weekly.labels,
        keys: data.weekly.keys,
        series: data.weekly.returns,
        unit: "%",
        selected: null,
        dense: true,
        title: "Weekly index return",
      };
    }
    if (view === "score") {
      return {
        labels: data.monthly.labels,
        keys: data.monthly.keys,
        series: data.monthly.score,
        unit: "score",
        selected: data.selected,
        dense: false,
        title: "Monthly score",
      };
    }
    return {
      labels: data.monthly.labels,
      keys: data.monthly.keys,
      series: data.monthly.fpi,
      unit: "₹ Cr",
      selected: data.selected,
      dense: false,
      title: "Monthly FPI",
    };
  }

  function fmt(v, unit) {
    if (v == null || Number.isNaN(Number(v))) return "—";
    const n = Number(v);
    if (unit === "₹ Cr") {
      const sign = n > 0 ? "+" : "";
      return `${sign}₹${Math.round(n).toLocaleString("en-IN")} Cr`;
    }
    if (unit === "%") return `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;
    return String(Math.round(n * 10) / 10);
  }

  function compact(v, unit) {
    if (v == null || Number.isNaN(Number(v))) return "";
    const n = Number(v);
    if (unit === "₹ Cr") {
      const abs = Math.abs(n);
      if (abs >= 1000) return `${n > 0 ? "+" : "-"}${(abs / 1000).toFixed(1)}k`;
      return `${n > 0 ? "+" : ""}${Math.round(n)}`;
    }
    if (unit === "%") return `${n > 0 ? "+" : ""}${n.toFixed(1)}`;
    return String(Math.round(n));
  }

  function mixRgbSafe(t, from, to) {
    const u = Math.max(0, Math.min(1, t));
    const ch = (i) => Math.round(from[i] + (to[i] - from[i]) * u);
    return `rgb(${ch(0)}, ${ch(1)}, ${ch(2)})`;
  }

  function scaleOf(series, unit) {
    const vals = series
      .flatMap((s) => s.values)
      .filter((v) => v != null && !Number.isNaN(Number(v)))
      .map((v) => Math.abs(Number(v)))
      .sort((a, b) => a - b);
    if (!vals.length) return 1;
    const p90 = vals[Math.min(vals.length - 1, Math.floor(vals.length * 0.9))];
    if (unit === "score") return 30;
    return Math.max(p90 || 1, unit === "%" ? 2 : 1);
  }

  function cellFill(v, scale, unit) {
    if (v == null || Number.isNaN(Number(v))) return "#efe8da";
    const n = Number(v);
    const t = unit === "score"
      ? Math.max(-1, Math.min(1, (n - 50) / scale))
      : Math.max(-1, Math.min(1, n / scale));
    if (t >= 0) return mixRgbSafe(t, [255, 253, 248], [15, 123, 74]);
    return mixRgbSafe(-t, [255, 253, 248], [155, 28, 28]);
  }

  function inkFor(v, scale, unit) {
    if (v == null || Number.isNaN(Number(v))) return "#5c574e";
    const n = Number(v);
    const t = unit === "score"
      ? Math.abs((n - 50) / scale)
      : Math.abs(n / scale);
    return t > 0.55 ? "#fffdf8" : "#1b1916";
  }

  function lastVal(series) {
    for (let i = series.values.length - 1; i >= 0; i -= 1) {
      const v = series.values[i];
      if (v != null && !Number.isNaN(Number(v))) return Number(v);
    }
    return null;
  }

  function valAt(row, col) {
    if (col == null || col < 0) return lastVal(row);
    const v = row.values[col];
    if (v == null || Number.isNaN(Number(v))) return null;
    return Number(v);
  }

  function sortColIndex(packed) {
    if (sortMode === "name") return -2;
    if (sortMode === "selected") return packed.keys.indexOf(data.selected);
    if (sortMode === "col") return sortCol;
    return -1;
  }

  function sortedRows(packed) {
    const q = (searchEl && searchEl.value.trim().toLowerCase()) || "";
    const rows = packed.series
      .map((s) => ({ ...s }))
      .filter((s) => !q || s.name.toLowerCase().includes(q));
    const col = sortColIndex(packed);
    rows.sort((a, b) => {
      if (sortMode === "name" || col === -2) {
        const d = a.name.localeCompare(b.name);
        return sortDir === "asc" ? d : -d;
      }
      const va = valAt(a, col);
      const vb = valAt(b, col);
      if (va == null && vb == null) return a.name.localeCompare(b.name);
      if (va == null) return 1;
      if (vb == null) return -1;
      const d = va - vb;
      return sortDir === "asc" ? d : -d;
    });
    return rows;
  }

  function dirLabel() {
    if (sortMode === "name") return sortDir === "asc" ? "A → Z" : "Z → A";
    return sortDir === "desc" ? "High → low" : "Low → high";
  }

  function syncSortButtons() {
    if (sortBar) {
      sortBar.querySelectorAll("button[data-sort]").forEach((b) => {
        b.classList.toggle("on", b.dataset.sort === sortMode);
      });
    }
    if (dirBtn) {
      dirBtn.dataset.dir = sortDir;
      dirBtn.textContent = dirLabel();
    }
  }

  function greenHint(unit) {
    if (unit === "score") return "score above 50";
    if (unit === "%") return "positive return";
    return "FPI inflow";
  }

  function paintHeat() {
    const packed = pack();
    const rows = sortedRows(packed);
    const scale = scaleOf(packed.series, packed.unit);
    const selectedKey = packed.selected;
    const selIdx = selectedKey ? packed.keys.indexOf(selectedKey) : -1;
    const col = sortColIndex(packed);
    if (heatTitle) heatTitle.textContent = `Sector heatmap · ${packed.title}`;
    const head = packed.labels
      .map((lab, i) => {
        const on = i === selIdx ? " on" : "";
        const sort = i === col ? ` sort ${sortDir}` : "";
        return `<th class="sortable${on}${sort}" data-col="${i}" title="Sort by ${lab}">${lab}</th>`;
      })
      .join("");
    const nameSort = sortMode === "name" ? ` sort ${sortDir}` : "";
    const body = rows
      .map((row) => {
        const cells = row.values
          .map((v, i) => {
            const title = `${row.name} · ${packed.labels[i]}: ${fmt(v, packed.unit)}`;
            const text = packed.dense ? "" : compact(v, packed.unit);
            const on = i === selIdx ? " on" : "";
            const sort = i === col ? " sort" : "";
            return `<td class="${on}${sort}">
              <span class="flow-cell${packed.dense ? " tight" : ""}" style="background:${cellFill(v, scale, packed.unit)};color:${inkFor(v, scale, packed.unit)}" title="${title.replace(/"/g, "&quot;")}" data-tip="${title.replace(/"/g, "&quot;")}">${text}</span>
            </td>`;
          })
          .join("");
        return `<tr><th scope="row">${row.name}</th>${cells}</tr>`;
      })
      .join("");
    heatEl.innerHTML = `
      <table class="flow-heat${packed.dense ? " dense" : ""}">
        <thead><tr><th class="sortable${nameSort}" data-col="name">Sector</th>${head}</tr></thead>
        <tbody>${body || `<tr><td colspan="${packed.labels.length + 1}">No sectors match.</td></tr>`}</tbody>
      </table>`;
    if (hoverEl) {
      hoverEl.textContent = `${rows.length} of ${packed.series.length} sectors · click a column to sort · green = ${greenHint(packed.unit)}`;
    }
  }

  function renderSplit(packed) {
    if (!splitCanvas || !splitCard || typeof Chart === "undefined") return;
    const show = view === "fpi";
    splitCard.classList.toggle("hidden", !show);
    if (!show) return;
    const idx = packed.keys.indexOf(data.selected);
    const at = idx >= 0 ? idx : packed.keys.length - 1;
    const rows = sortedRows(packed)
      .map((s) => ({ name: s.name, val: s.values[at] }))
      .filter((r) => r.val != null && !Number.isNaN(Number(r.val)));
    if (splitTitle) {
      splitTitle.textContent = `${packed.labels[at] || ""} FPI split · all sectors`;
    }
    const cfg = {
      type: "bar",
      data: {
        labels: rows.map((r) => r.name),
        datasets: [
          {
            label: "FPI net",
            data: rows.map((r) => r.val),
            backgroundColor: rows.map((r) => (r.val >= 0 ? "#0f7b4a" : "#9b1c1c")),
            borderWidth: 0,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => items[0] && items[0].label,
              label: (item) => ` ${fmt(item.parsed.x, "₹ Cr")}`,
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: "₹ Cr", color: "#5c574e" },
            ticks: { callback: (v) => Math.round(v).toLocaleString("en-IN"), color: "#5c574e" },
            grid: { color: "#efe8da" },
          },
          y: { ticks: { color: "#1b1916", font: { size: 11 } }, grid: { display: false } },
        },
      },
    };
    if (barChart) barChart.destroy();
    barChart = new Chart(splitCanvas, cfg);
    const wrap = splitCard.querySelector(".chart-canvas-wrap");
    if (wrap && !splitCard.classList.contains("is-fs")) {
      wrap.style.height = `${Math.max(280, rows.length * 22 + 48)}px`;
    }
  }

  function marketOrder() {
    const n = (data.monthly.keys || []).length;
    const idx = Array.from({ length: n }, (_, i) => i);
    const series = {
      fpi: (data.market && data.market.fpi) || [],
      dii: (data.market && data.market.dii) || [],
      fii: (data.market && data.market.fii_cash) || [],
    };
    if (marketSort === "time") {
      if (marketDir === "desc") idx.reverse();
      return idx;
    }
    const vals = series[marketSort] || [];
    idx.sort((a, b) => {
      const va = vals[a];
      const vb = vals[b];
      const na = va == null || Number.isNaN(Number(va)) ? null : Number(va);
      const nb = vb == null || Number.isNaN(Number(vb)) ? null : Number(vb);
      if (na == null && nb == null) return 0;
      if (na == null) return 1;
      if (nb == null) return -1;
      return marketDir === "asc" ? na - nb : nb - na;
    });
    return idx;
  }

  function resizeCharts() {
    if (marketChart) marketChart.resize();
    if (barChart) barChart.resize();
  }

  function renderMarket() {
    if (!marketCanvas || !marketCard || typeof Chart === "undefined") return;
    const market = data.market || {};
    const labels = data.monthly.labels || [];
    const showFpi = hasVals(market.fpi);
    const showDii = hasVals(market.dii);
    const showFii = hasVals(market.fii_cash);
    const show = showFpi || showDii || showFii;
    marketCard.classList.toggle("hidden", !show);
    if (marketSortBar) {
      const fiiBtn = marketSortBar.querySelector("[data-msort='fii']");
      if (fiiBtn) fiiBtn.classList.toggle("hidden", !showFii);
      marketSortBar.querySelectorAll("button[data-msort]").forEach((b) => {
        b.classList.toggle("on", b.dataset.msort === marketSort);
      });
    }
    if (!show) return;
    const order = marketOrder();
    const pick = (arr) => order.map((i) => (arr && arr[i] != null ? arr[i] : null));
    const orderedLabels = order.map((i) => labels[i]);
    const datasets = [];
    if (showFpi) {
      datasets.push({
        label: "NSDL FPI",
        data: pick(market.fpi),
        backgroundColor: "#123c2f",
        borderWidth: 0,
      });
    }
    if (showDii) {
      datasets.push({
        label: "AMFI DII",
        data: pick(market.dii),
        backgroundColor: "#c45c26",
        borderWidth: 0,
      });
    }
    if (showFii) {
      datasets.push({
        label: "NSE FII cash",
        data: pick(market.fii_cash),
        backgroundColor: "#1d4e89",
        borderWidth: 0,
      });
    }
    if (marketTitle) {
      marketTitle.textContent = "Market monthly · FPI vs DII";
    }
    if (marketChart) marketChart.destroy();
    marketChart = new Chart(marketCanvas, {
      type: "bar",
      data: { labels: orderedLabels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: "top", labels: { color: "#5c574e", boxWidth: 10 } },
          tooltip: {
            callbacks: {
              label: (item) => ` ${item.dataset.label}: ${fmt(item.parsed.y, "₹ Cr")}`,
            },
          },
        },
        scales: {
          x: { ticks: { color: "#5c574e", maxRotation: 45, minRotation: 0 }, grid: { display: false } },
          y: {
            title: { display: true, text: "₹ Cr", color: "#5c574e" },
            ticks: { callback: (v) => Math.round(v).toLocaleString("en-IN"), color: "#5c574e" },
            grid: { color: "#efe8da" },
          },
        },
      },
    });
  }

  function bindFullscreen() {
    const buttons = document.querySelectorAll(".chart-fs-btn[data-fs]");
    function exit() {
      document.querySelectorAll(".chart-card.is-fs").forEach((c) => c.classList.remove("is-fs"));
      document.body.classList.remove("chart-fs-open");
      buttons.forEach((b) => {
        b.textContent = "Full screen";
      });
      requestAnimationFrame(resizeCharts);
    }
    exitChartFullscreen = exit;
    buttons.forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => {
        const card = document.getElementById(btn.dataset.fs);
        if (!card) return;
        const open = card.classList.contains("is-fs");
        exit();
        if (!open) {
          card.classList.add("is-fs");
          document.body.classList.add("chart-fs-open");
          btn.textContent = "Exit";
          requestAnimationFrame(resizeCharts);
        }
      });
    });
  }

  function render() {
    const packed = pack();
    syncSortButtons();
    paintHeat();
    renderSplit(packed);
  }

  if (!heatEl.dataset.bound) {
    heatEl.dataset.bound = "1";
    heatEl.addEventListener("mouseover", (ev) => {
      const cell = ev.target.closest("[data-tip]");
      if (hoverEl && cell) hoverEl.textContent = cell.dataset.tip;
    });
    heatEl.addEventListener("mouseout", (ev) => {
      if (ev.target.closest("[data-tip]") && hoverEl) {
        const packed = pack();
        const rows = sortedRows(packed);
        hoverEl.textContent = `${rows.length} of ${packed.series.length} sectors · click a column to sort · green = ${greenHint(packed.unit)}`;
      }
    });
    heatEl.addEventListener("click", (ev) => {
      const th = ev.target.closest("thead th[data-col]");
      if (!th) return;
      const col = th.dataset.col;
      if (col === "name") {
        if (sortMode === "name") sortDir = sortDir === "asc" ? "desc" : "asc";
        else {
          sortMode = "name";
          sortDir = "asc";
        }
      } else {
        const i = Number(col);
        if (sortMode === "col" && sortCol === i) sortDir = sortDir === "desc" ? "asc" : "desc";
        else {
          sortMode = "col";
          sortCol = i;
          sortDir = "desc";
        }
      }
      render();
    });
  }

  if (searchEl && !searchEl.dataset.bound) {
    searchEl.dataset.bound = "1";
    searchEl.addEventListener("input", render);
  }

  if (!modeBar.dataset.bound) {
    modeBar.dataset.bound = "1";
    modeBar.addEventListener("click", (ev) => {
      const btnEl = ev.target.closest("button[data-view]");
      if (!btnEl) return;
      view = btnEl.dataset.view;
      modeBar.querySelectorAll("button[data-view]").forEach((b) => b.classList.toggle("on", b === btnEl));
      render();
    });
  }

  if (sortBar && !sortBar.dataset.bound) {
    sortBar.dataset.bound = "1";
    sortBar.addEventListener("click", (ev) => {
      const btnEl = ev.target.closest("button[data-sort]");
      if (!btnEl) return;
      const next = btnEl.dataset.sort;
      if (sortMode === next) {
        sortDir = sortDir === "desc" ? "asc" : "desc";
      } else {
        sortMode = next;
        sortCol = -1;
        sortDir = next === "name" ? "asc" : "desc";
      }
      render();
    });
  }

  if (dirBtn && !dirBtn.dataset.bound) {
    dirBtn.dataset.bound = "1";
    dirBtn.addEventListener("click", () => {
      sortDir = sortDir === "desc" ? "asc" : "desc";
      render();
    });
  }

  if (marketSortBar && !marketSortBar.dataset.bound) {
    marketSortBar.dataset.bound = "1";
    marketSortBar.addEventListener("click", (ev) => {
      const btnEl = ev.target.closest("button[data-msort]");
      if (!btnEl) return;
      const next = btnEl.dataset.msort;
      if (marketSort === next) {
        marketDir = marketDir === "desc" ? "asc" : "desc";
      } else {
        marketSort = next;
        marketDir = next === "time" ? "asc" : "desc";
      }
      renderMarket();
    });
  }

  bindFullscreen();
  renderMarket();
  render();
}

if (document.body.dataset.page === "home") {
  loadHome();
  const modal = document.getElementById("flow-daily-modal");
  if (modal) {
    modal.addEventListener("click", (ev) => {
      if (ev.target && ev.target.dataset && ev.target.dataset.close) closeFlowDaily();
    });
    const closer = modal.querySelector(".flow-daily-close");
    if (closer) closer.addEventListener("click", closeFlowDaily);
  }
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (document.body.classList.contains("chart-fs-open")) {
      exitChartFullscreen();
      return;
    }
    closeFlowDaily();
  });
} else if (document.body.dataset.page === "sector") {
  loadSector();
}
