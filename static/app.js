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
          <em>NSDL foreign investor flow · click for daily</em>
        </article>
        <article class="chip-hit" data-flow="dii" role="button" tabindex="0" aria-expanded="false" aria-controls="flow-daily-modal">
          <span>DII net</span>
          <strong class="${flow.dii_cls || ""}">${flow.dii_s || "—"}</strong>
          ${flow.dii_trail_steps && flow.dii_trail_steps.length ? `<div class="trail">${renderTrail(flow.dii_trail_steps)}</div>` : ""}
          <em>AMFI monthly note · click for daily</em>
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
  if (title) title.textContent = kind === "dii" ? "Daily DII" : "Daily FPI / FII";
  body.innerHTML = `<p class="hint">Loading daily ${kind === "dii" ? "DII" : "FPI / FII"}…</p>`;
  const closer = modal.querySelector(".flow-daily-close");
  if (closer) closer.focus();
  try {
    const data = await fetchApi(`/api/flows/daily?kind=${encodeURIComponent(kind)}`);
    renderFlowDaily(data);
  } catch (err) {
    body.innerHTML = `<p class="hint">Could not load daily ${kind === "dii" ? "DII" : "FPI / FII"}.</p>`;
  }
}

function renderFlowDaily(data) {
  const title = document.getElementById("flow-daily-title");
  const body = document.getElementById("flow-daily-body");
  if (!body) return;
  if (title) title.textContent = `${data.title || "Daily"} · ${data.month_label || ""}`;
  const series = (data.series || [])
    .map((s) => {
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
            <td>Sum of days</td>
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
                <tr><th>Date</th><th>Buy</th><th>Sell</th><th>Net</th></tr>
              </thead>
              <tbody>
                ${rows || `<tr><td colspan="4">No daily rows stored for this month.</td></tr>`}
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
      <article><span>FPI/FII</span><strong>${data.fpi_s}</strong><em>${data.fpi_via ? `NSDL reports this under ${data.fpi_via}` : (data.fpi_trail_s || "NSDL sector equity")}</em></article>
      <article><span>DII/MF</span><strong>${data.dii_word}</strong><em>AMFI monthly note · market-wide</em></article>
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

function renderFlowChart(data) {
  const canvas = document.getElementById("flow-chart");
  const splitCanvas = document.getElementById("split-chart");
  const splitCard = document.getElementById("split-card");
  const splitTitle = document.getElementById("split-title");
  const legend = document.getElementById("chart-legend");
  const tooltipEl = document.getElementById("chart-tooltip");
  const modeBar = document.getElementById("chart-mode");
  if (!data || !canvas || !legend || !modeBar || typeof Chart === "undefined") return;

  const PALETTE = [
    "#123c2f", "#c45c26", "#1d4e89", "#0f7b4a", "#9b1c1c",
    "#6b4c9a", "#b08900", "#0e7490", "#9f1239", "#365314",
    "#7c2d12", "#1e3a8a", "#115e59", "#a16207", "#4c1d95",
    "#9a3412", "#166534", "#be185d", "#075985", "#44403c",
    "#854d0e", "#334155", "#047857",
  ];
  const hidden = new Set();
  let view = "fpi";
  let lineChart = null;
  let barChart = null;
  let currentUnit = "₹ Cr";

  function color(i) {
    return PALETTE[i % PALETTE.length];
  }

  function pack() {
    if (view === "weekly") {
      return {
        labels: data.weekly.labels,
        keys: data.weekly.keys,
        series: data.weekly.returns,
        unit: "%",
        yTitle: "Weekly return",
        selected: null,
      };
    }
    if (view === "score") {
      return {
        labels: data.monthly.labels,
        keys: data.monthly.keys,
        series: data.monthly.score,
        unit: "score",
        yTitle: "Money-flow score",
        selected: data.selected,
      };
    }
    return {
      labels: data.monthly.labels,
      keys: data.monthly.keys,
      series: data.monthly.fpi,
      unit: "₹ Cr",
      yTitle: "FPI net (₹ Cr)",
      selected: data.selected,
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

  function lastAbs(series) {
    for (let i = series.values.length - 1; i >= 0; i -= 1) {
      const v = series.values[i];
      if (v != null && !Number.isNaN(Number(v))) return Math.abs(Number(v));
    }
    return 0;
  }

  function defaultHidden(series) {
    hidden.clear();
    const ranked = series.slice().sort((a, b) => lastAbs(b) - lastAbs(a));
    ranked.slice(8).forEach((s) => hidden.add(s.name));
  }

  function yTick(v, unit) {
    if (unit === "₹ Cr") return Math.round(v).toLocaleString("en-IN");
    if (unit === "%") return `${v.toFixed(1)}%`;
    return String(Math.round(v));
  }

  function paintLegend(series) {
    legend.replaceChildren();
    series.forEach((s, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.name = s.name;
      b.className = hidden.has(s.name) ? "off" : "on";
      const dot = document.createElement("i");
      dot.style.background = color(i);
      b.append(dot, s.name);
      legend.append(b);
    });
  }

  function tooltipHandler(context) {
    const tooltip = context.tooltip;
    if (!tooltipEl) return;
    if (!tooltip || tooltip.opacity === 0) {
      tooltipEl.classList.add("hidden");
      return;
    }
    const points = (tooltip.dataPoints || [])
      .filter((p) => p.parsed && p.parsed.y != null && !Number.isNaN(p.parsed.y))
      .sort((a, b) => b.parsed.y - a.parsed.y);
    if (!points.length) {
      tooltipEl.classList.add("hidden");
      return;
    }
    const title = tooltip.title && tooltip.title.length ? tooltip.title[0] : "";
    const rows = points
      .map((p) => {
        const n = p.parsed.y;
        const cls = n > 0 ? "up" : n < 0 ? "down" : "";
        return `<li><span class="swatch" style="background:${p.dataset.borderColor}"></span><span class="n">${p.dataset.label}</span><span class="v ${cls}">${fmt(n, currentUnit)}</span></li>`;
      })
      .join("");
    tooltipEl.innerHTML = `<strong>${title}</strong><ul>${rows}</ul>`;
    tooltipEl.classList.remove("hidden");
    const wrap = tooltipEl.parentElement;
    const pad = 12;
    const tw = tooltipEl.offsetWidth;
    const th = tooltipEl.offsetHeight;
    let left = tooltip.caretX + pad;
    let top = tooltip.caretY + pad;
    if (left + tw > wrap.clientWidth - 8) left = tooltip.caretX - tw - pad;
    if (top + th > wrap.clientHeight - 8) top = tooltip.caretY - th - pad;
    tooltipEl.style.left = `${Math.max(8, left)}px`;
    tooltipEl.style.top = `${Math.max(8, top)}px`;
  }

  function lineConfig(packed) {
    currentUnit = packed.unit;
    return {
      type: "line",
      data: {
        labels: packed.labels,
        datasets: packed.series.map((s, i) => ({
          label: s.name,
          data: s.values.map((v) => (v == null || Number.isNaN(Number(v)) ? null : Number(v))),
          borderColor: color(i),
          backgroundColor: color(i),
          borderWidth: 2.25,
          pointRadius: packed.labels.length > 18 ? 2.5 : 4,
          pointHoverRadius: 7,
          pointHitRadius: 10,
          tension: 0.2,
          spanGaps: false,
          hidden: hidden.has(s.name),
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            enabled: false,
            external: tooltipHandler,
          },
        },
        scales: {
          x: {
            ticks: { maxRotation: 0, autoSkip: true, color: "#5c574e", font: { size: 11 } },
            grid: { color: "#efe8da" },
          },
          y: {
            title: { display: true, text: packed.yTitle, color: "#5c574e", font: { size: 12 } },
            ticks: {
              color: "#5c574e",
              font: { size: 11 },
              callback: (v) => yTick(v, packed.unit),
            },
            grid: { color: "#efe8da" },
          },
        },
      },
    };
  }

  function renderSplit(packed) {
    if (!splitCanvas || !splitCard) return;
    const show = view === "fpi";
    splitCard.classList.toggle("hidden", !show);
    if (!show) return;
    const idx = packed.keys.indexOf(data.selected);
    const at = idx >= 0 ? idx : packed.keys.length - 1;
    const rows = packed.series
      .map((s) => ({ name: s.name, val: s.values[at] }))
      .filter((r) => r.val != null && !Number.isNaN(Number(r.val)))
      .sort((a, b) => b.val - a.val);
    if (splitTitle) {
      splitTitle.textContent = `${packed.labels[at] || ""} FPI split · hover a bar for the exact figure`;
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
  }

  function render() {
    const packed = pack();
    paintLegend(packed.series);
    if (lineChart) lineChart.destroy();
    lineChart = new Chart(canvas, lineConfig(packed));
    renderSplit(packed);
  }

  defaultHidden(pack().series);
  render();

  legend.addEventListener("click", (ev) => {
    const btnEl = ev.target.closest("button[data-name]");
    if (!btnEl || !lineChart) return;
    const name = btnEl.dataset.name;
    if (hidden.has(name)) hidden.delete(name);
    else hidden.add(name);
    pack().series.forEach((s, i) => {
      lineChart.setDatasetVisibility(i, !hidden.has(s.name));
    });
    lineChart.update();
    paintLegend(pack().series);
  });

  modeBar.addEventListener("click", (ev) => {
    const btnEl = ev.target.closest("button");
    if (!btnEl) return;
    if (btnEl.dataset.view) {
      view = btnEl.dataset.view;
      defaultHidden(pack().series);
      modeBar.querySelectorAll("button[data-view]").forEach((b) => b.classList.toggle("on", b === btnEl));
      render();
      return;
    }
    if (btnEl.dataset.action === "all") {
      hidden.clear();
      render();
    }
    if (btnEl.dataset.action === "none") {
      pack().series.forEach((s) => hidden.add(s.name));
      render();
    }
  });
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
    if (ev.key === "Escape") closeFlowDaily();
  });
} else if (document.body.dataset.page === "sector") {
  loadSector();
}
