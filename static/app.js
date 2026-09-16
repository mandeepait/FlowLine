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

let dealFetchBusy = false;
let scrapeBusy = false;

function loaderHeld() {
  return dealFetchBusy || scrapeBusy;
}

function setPageLoader(on, label) {
  const el = document.getElementById("page-loader");
  if (!el) return;
  const show = !!on || loaderHeld();
  el.classList.toggle("hidden", !show);
  el.setAttribute("aria-busy", show ? "true" : "false");
  document.body.classList.toggle("is-loading", show);
  const text = document.getElementById("page-loader-title") || el.querySelector("p");
  if (text && label) text.textContent = label;
}

function setLoaderSteps(items, extra) {
  const ol = document.getElementById("page-loader-steps");
  if (!ol) return;
  const rows = (items || []).map((item) => {
    const st = item.ok;
    const cls = st === true ? "ok" : st === false ? "bad" : "wait";
    return `<li class="${cls}"><span>${mark(st)}</span>${item.text}</li>`;
  });
  if (extra) rows.push(`<li class="now">${extra}</li>`);
  ol.innerHTML = rows.join("");
}

document.addEventListener(
  "click",
  (ev) => {
    if (!document.body.classList.contains("is-loading")) return;
    ev.preventDefault();
    ev.stopPropagation();
  },
  true
);
document.addEventListener(
  "keydown",
  (ev) => {
    if (!document.body.classList.contains("is-loading")) return;
    ev.preventDefault();
    ev.stopPropagation();
  },
  true
);

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
              <th data-sort="score" class="sortable on desc">Score <span class="sort-icon" aria-hidden="true"></span></th>
              <th data-sort="fpi" class="sortable">FPI net <span class="sort-icon" aria-hidden="true"></span></th>
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

function istToday() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function dealTypeLabel(v) {
  if (v === "SHORT_SELLING") return "Short Selling";
  if (v === "BULK") return "Bulk";
  if (v === "BLOCK") return "Block";
  return v || "—";
}

function fmtIst(s) {
  if (!s) return "";
  const raw = String(s);
  const d = new Date(raw.includes("+") || raw.endsWith("Z") ? raw : `${raw}+05:30`);
  if (Number.isNaN(d.getTime())) return raw;
  return `${new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d)} IST`;
}

function mark(ok) {
  if (ok === true) return "✓";
  if (ok === false) return "✗";
  return "…";
}

function escAttr(val) {
  return String(val ?? "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

function sortIcon() {
  return ' <span class="sort-icon" aria-hidden="true"></span>';
}

function bindSortableTable(table, defaultKey, defaultDir) {
  if (!table) return;
  let current = defaultKey;
  let dir = defaultDir === "asc" ? "asc" : "desc";

  function val(row, key, type) {
    const raw = row.dataset[key];
    if (raw === undefined || raw === "") return null;
    if (type === "text") return raw.toLowerCase();
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw.toLowerCase();
  }

  function apply(key, toggle) {
    const heading = table.querySelector(`th[data-sort="${key}"]`);
    const type = heading && heading.dataset.type === "text" ? "text" : "num";
    if (toggle) {
      if (current === key) dir = dir === "desc" ? "asc" : "desc";
      else {
        current = key;
        dir = type === "text" ? "asc" : "desc";
      }
    }
    const sign = dir === "asc" ? 1 : -1;
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr[data-sortrow]"));
    rows.sort((a, b) => {
      const av = val(a, current, type);
      const bv = val(b, current, type);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (av === bv) return 0;
      return av > bv ? sign : -sign;
    });
    rows.forEach((row) => tbody.appendChild(row));
    table.querySelectorAll("th.sortable").forEach((el) => {
      const on = el.dataset.sort === current;
      el.classList.toggle("on", on);
      el.classList.toggle("asc", on && dir === "asc");
      el.classList.toggle("desc", on && dir === "desc");
      el.setAttribute("aria-sort", on ? (dir === "asc" ? "ascending" : "descending") : "none");
    });
  }

  table.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => apply(th.dataset.sort, true));
  });
  apply(current, false);
}

function dealWindow() {
  const fromEl = document.getElementById("deal-from");
  const toEl = document.getElementById("deal-to");
  return {
    from: (fromEl && fromEl.value) || isoMonthsAgo(6),
    to: (toEl && toEl.value) || istToday(),
  };
}

function dealBaseParams(extra) {
  const ex = document.getElementById("deal-exchange");
  const ty = document.getElementById("deal-type");
  const side = document.getElementById("deal-side");
  const search = document.getElementById("deal-search");
  const params = new URLSearchParams();
  if (ex && ex.value && ex.value !== "ALL") params.set("exchange", ex.value);
  if (ty && ty.value && ty.value !== "ALL") params.set("dealType", ty.value);
  if (side && side.value && side.value !== "ALL") params.set("buySell", side.value);
  if (search && search.value.trim()) params.set("symbol", search.value.trim());
  Object.entries(extra || {}).forEach(([k, v]) => {
    if (v != null && v !== "") params.set(k, v);
  });
  return params;
}

function dealQuery(extra) {
  const params = dealBaseParams(extra);
  if (dealViewDate) {
    params.set("date", dealViewDate);
  } else {
    const win = dealWindow();
    params.set("fromDate", win.from);
    params.set("toDate", win.to);
  }
  const q = params.toString();
  return q ? `?${q}` : "";
}

function isoDaysAgo(n) {
  const parts = istToday().split("-").map(Number);
  const dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  dt.setUTCDate(dt.getUTCDate() - n);
  return dt.toISOString().slice(0, 10);
}

function isoMonthsAgo(n) {
  const parts = istToday().split("-").map(Number);
  const dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  dt.setUTCMonth(dt.getUTCMonth() - n);
  return dt.toISOString().slice(0, 10);
}

function periodFrom(key) {
  if (key === "7") return isoDaysAgo(7);
  if (key === "30") return isoDaysAgo(30);
  if (key === "90") return isoDaysAgo(90);
  return isoMonthsAgo(6);
}

function syncPeriodButtons() {
  const win = dealWindow();
  const today = istToday();
  document.querySelectorAll(".deal-periods [data-period]").forEach((btn) => {
    const from = periodFrom(btn.dataset.period);
    btn.classList.toggle("on", !dealViewDate && win.to === today && win.from === from);
  });
}

function applyDealPeriod(key) {
  dealViewDate = "";
  const fromEl = document.getElementById("deal-from");
  const toEl = document.getElementById("deal-to");
  if (fromEl) fromEl.value = periodFrom(key);
  if (toEl) toEl.value = istToday();
  syncPeriodButtons();
  loadDeals(1);
}

function fmtDay(iso) {
  if (!iso) return "—";
  const [y, m, d] = String(iso).slice(0, 10).split("-");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(d)} ${months[Number(m) - 1]}`;
}

function dealStockHref(symbol) {
  return `/deals/${encodeURIComponent(symbol || "")}`;
}

function stockLink(symbol, label) {
  return `<a class="stock-link" href="${dealStockHref(symbol)}">${label || symbol || "—"}</a>`;
}

function inrShort(n) {
  const v = Number(n) || 0;
  const sign = v < 0 ? "-" : v > 0 ? "" : "";
  const mag = Math.abs(v);
  if (mag >= 1e7) return `${sign}₹${(mag / 1e7).toFixed(2).replace(/\.?0+$/, "")} Cr`;
  if (mag >= 1e5) return `${sign}₹${(mag / 1e5).toFixed(1).replace(/\.0$/, "")} L`;
  if (mag >= 1e3) return `${sign}₹${(mag / 1e3).toFixed(1).replace(/\.0$/, "")} K`;
  return `${sign}₹${Math.round(mag).toLocaleString("en-IN")}`;
}

function renderDealTimeline(daily, targetId) {
  const el = document.getElementById(targetId || "deal-timeline");
  if (!el) return;
  const days = (daily || []).slice().reverse();
  if (!days.length) {
    el.innerHTML = "<p class=\"hint\">No stored buy/sell dates yet. Today's fetch will fill this.</p>";
    return;
  }
  const max = Math.max(...days.map((d) => (d.buyValue || 0) + (d.sellValue || 0)), 1);
  el.innerHTML = days
    .map((d) => {
      const buy = d.buyValue || 0;
      const sell = d.sellValue || 0;
      const net = buy - sell;
      const on = d.date === dealViewDate ? " on" : "";
      return `<div class="deal-tl-row${on}" data-deal-day="${escAttr(d.date)}">
        <div class="deal-tl-date"><strong>${fmtDay(d.date)}</strong><em>${d.date}</em></div>
        <div class="deal-tl-side">
          <span class="up">Buy ${inrShort(buy)}</span>
          <div class="deal-tl-track"><span class="deal-tl-buy" style="width:${(buy / max) * 100}%"></span></div>
        </div>
        <div class="deal-tl-side">
          <span class="down">Sell ${inrShort(sell)}</span>
          <div class="deal-tl-track"><span class="deal-tl-sell" style="width:${(sell / max) * 100}%"></span></div>
        </div>
        <div class="deal-tl-net ${net >= 0 ? "up" : "down"}">${net >= 0 ? "+" : ""}${inrShort(net)}</div>
      </div>`;
    })
    .join("");
}

function stockTimeline(rows) {
  const byDate = {};
  (rows || []).forEach((r) => {
    const day = (r.trade_date || "").slice(0, 10);
    if (!day) return;
    if (!byDate[day]) byDate[day] = { date: day, buyValue: 0, sellValue: 0, buys: 0, sells: 0 };
    const val = Number(r.deal_value) || 0;
    if (r.buy_sell === "BUY") {
      byDate[day].buyValue += val;
      byDate[day].buys += 1;
    } else {
      byDate[day].sellValue += val;
      byDate[day].sells += 1;
    }
  });
  return Object.values(byDate).sort((a, b) => (a.date < b.date ? -1 : 1));
}

function maybeAutoFetchToday(last) {
  const key = `flowline-deal-autofetch-${istToday()}`;
  try {
    if (sessionStorage.getItem(key)) return false;
    const at = (last && (last.at_s || last.at)) || "";
    if (String(at).slice(0, 10) === istToday()) return false;
    sessionStorage.setItem(key, "1");
  } catch (err) {
    return false;
  }
  const todayBtn = document.getElementById("deal-fetch-today");
  const histBtn = document.getElementById("deal-fetch-hist");
  if (todayBtn) runDealFetch("/api/deals/fetch/today", todayBtn, [histBtn]);
  return true;
}

function maybeBackfillMonths(stats) {
  if (dealFetchBusy || dealDidBackfill) return;
  const sixFrom = isoMonthsAgo(6);
  const today = istToday();
  const win = dealWindow();
  if (win.from !== sixFrom || win.to !== today || dealViewDate) return;
  const days = (stats && stats.daily) || [];
  const oldest = days.length ? days[0].date : "";
  if (days.length >= 12 && oldest && oldest <= isoMonthsAgo(5)) {
    dealDidBackfill = true;
    return;
  }
  dealDidBackfill = true;
  const todayBtn = document.getElementById("deal-fetch-today");
  const histBtn = document.getElementById("deal-fetch-hist");
  const q = new URLSearchParams({ fromDate: sixFrom, toDate: today, exchange: "ALL", dealType: "ALL" });
  if (histBtn) runDealFetch(`/api/deals/fetch?${q}`, histBtn, [todayBtn]);
}

let dealViewDate = "";
let dealPage = 1;
let dealsBound = false;
let dealDidAutoFetch = false;
let dealDidBackfill = false;
let dealSearchTimer = 0;
let dealCapRetry = false;

function renderLastFetch(last) {
  const el = document.getElementById("deal-last");
  if (!el) return;
  if (!last || !last.at) {
    el.textContent = "Last Fetch: none yet";
    return;
  }
  const nse = last.nse || {};
  const bse = last.bse || {};
  const line = (obj, key, label) =>
    obj[key] ? `${label}: ${obj[key].ok ? "✓" : "✗"}` : `${label}: —`;
  el.innerHTML = `Last Fetch ${fmtIst(last.at_s || last.at)}
    · NSE ${line(nse, "BULK", "Bulk")} ${line(nse, "BLOCK", "Block")} ${line(nse, "SHORT_SELLING", "Short Selling")}
    · BSE ${line(bse, "BULK", "Bulk")} ${line(bse, "BLOCK", "Block")}
    · Fetched ${(last.fetched || 0).toLocaleString("en-IN")} · Inserted ${(last.inserted || 0).toLocaleString("en-IN")} · Duplicates ${(last.duplicates || 0).toLocaleString("en-IN")}`;
}

function renderStockStrip(scores) {
  const el = document.getElementById("deal-stock-strip");
  if (!el) return;
  const top = (scores || []).slice(0, 24);
  if (!top.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = top
    .map(
      (r) =>
        `<a class="deal-stock-chip" href="${dealStockHref(r.symbol)}">
          <strong>${r.company_name || r.symbol}</strong>
          <em class="${(r.net_value || 0) >= 0 ? "up" : "down"}">${r.score}</em>
          <span>${r.market_cap_s || "—"}</span>
        </a>`
    )
    .join("");
}

async function loadDeals(page) {
  const root = document.getElementById("deals");
  if (!root) return;
  setPageLoader(true, page ? "Refreshing large deals" : "Loading large deals");
  bindDeals();
  const fromEl = document.getElementById("deal-from");
  const toEl = document.getElementById("deal-to");
  if (fromEl && !fromEl.value) fromEl.value = isoMonthsAgo(6);
  if (toEl && !toEl.value) toEl.value = istToday();
  syncPeriodButtons();
  dealPage = page || 1;
  const q = dealQuery({ page: dealPage, pageSize: 50 });
  let list;
  let stats;
  try {
    [list, stats] = await Promise.all([
      fetchApi(`/api/deals${q}`),
      fetchApi(`/api/deals/stats${dealQuery()}`),
    ]);
  } catch (err) {
    document.getElementById("deal-table-wrap").innerHTML = "<p class=\"hint\">Could not load stored deals.</p>";
    setPageLoader(false);
    return;
  }
  const win = dealWindow();
  const hint = document.getElementById("deal-session-hint");
  if (hint) {
    hint.textContent = dealViewDate
      ? `Showing ${dealViewDate}. Pick 6 months to return to the full range.`
      : `Official prints ${win.from} → ${win.to}. Market cap is from NSE quote when available.`;
  }
  const fmt = stats.formatted || {};
  document.getElementById("deal-cards").innerHTML = `
    <article><span>Total Deals</span><strong>${fmt.totalDeals || "0"}</strong></article>
    <article><span>Total Value</span><strong>${fmt.totalValue || "—"}</strong></article>
    <article><span>Buy Value</span><strong class="up">${fmt.buyValue || "—"}</strong></article>
    <article><span>Sell Value</span><strong class="down">${fmt.sellValue || "—"}</strong></article>
    <article><span>Net Buy</span><strong class="${(stats.netValue || 0) >= 0 ? "up" : "down"}">${fmt.netBuy || "—"}</strong></article>
    <article><span>Stocks</span><strong>${fmt.stocks || "0"}</strong></article>`;
  renderLastFetch(stats.lastFetch || list.lastFetch);
  renderStockStrip(stats.scores || []);
  renderDealTimeline(stats.daily || []);
  const sectors = (stats.sectors || [])
    .map((r) => {
      const name = r.slug ? `<a href="/sector/${r.slug}">${r.sector}</a>` : r.sector;
      return `<tr data-sortrow data-sector="${escAttr(r.sector)}" data-buy="${r.buy_value ?? ""}" data-sell="${r.sell_value ?? ""}" data-net="${r.net_value ?? ""}" data-deals="${r.deals ?? ""}" data-signal="${escAttr(r.signal)}">
        <td>${name}</td>
        <td class="num">${r.buy_s}</td>
        <td class="num">${r.sell_s}</td>
        <td class="num ${r.net_cls || ""}">${r.net_s}</td>
        <td class="num">${r.deals}</td>
        <td>${r.signal}</td>
      </tr>`;
    })
    .join("");
  document.getElementById("deal-sector-wrap").innerHTML = `
    <table id="deal-sector-table">
      <thead>
        <tr>
          <th class="sortable" data-sort="sector" data-type="text">Sector${sortIcon()}</th>
          <th class="sortable num" data-sort="buy">Buy Value${sortIcon()}</th>
          <th class="sortable num" data-sort="sell">Sell Value${sortIcon()}</th>
          <th class="sortable num" data-sort="net">Net Value${sortIcon()}</th>
          <th class="sortable num" data-sort="deals">Deals${sortIcon()}</th>
          <th class="sortable" data-sort="signal" data-type="text">Signal${sortIcon()}</th>
        </tr>
      </thead>
      <tbody>${sectors || `<tr><td colspan="6">No sector-mapped deals for this filter.</td></tr>`}</tbody>
    </table>`;
  bindSortableTable(document.getElementById("deal-sector-table"), "net", "desc");
  const scores = (stats.scores || [])
    .map(
      (r) =>
        `<tr data-sortrow data-stock="${escAttr(r.company_name || r.symbol)}" data-score="${r.score ?? ""}" data-mcap="${r.market_cap ?? ""}" data-buy="${r.buy_value ?? ""}" data-sell="${r.sell_value ?? ""}" data-net="${r.net_value ?? ""}" data-deals="${r.deals ?? ""}">
          <td>${stockLink(r.symbol, r.company_name || r.symbol)}</td>
          <td class="num">${r.market_cap_s || "—"}</td>
          <td class="num">${r.score}</td>
          <td class="num">${r.buy_s}</td>
          <td class="num">${r.sell_s}</td>
          <td class="num ${r.net_cls || ""}">${r.net_s}</td>
          <td class="num">${r.deals}</td>
        </tr>`
    )
    .join("");
  document.getElementById("deal-score-wrap").innerHTML = `
    <table id="deal-score-table">
      <thead>
        <tr>
          <th class="sortable" data-sort="stock" data-type="text">Stock${sortIcon()}</th>
          <th class="sortable num" data-sort="mcap">Market Cap${sortIcon()}</th>
          <th class="sortable num" data-sort="score">Deal Score${sortIcon()}</th>
          <th class="sortable num" data-sort="buy">Buy Value${sortIcon()}</th>
          <th class="sortable num" data-sort="sell">Sell Value${sortIcon()}</th>
          <th class="sortable num" data-sort="net">Net Value${sortIcon()}</th>
          <th class="sortable num" data-sort="deals">Deals${sortIcon()}</th>
        </tr>
      </thead>
      <tbody>${scores || `<tr><td colspan="7">No scored stocks for this filter.</td></tr>`}</tbody>
    </table>`;
  bindSortableTable(document.getElementById("deal-score-table"), "score", "desc");
  const rows = (list.rows || [])
    .map(
      (r) =>
        `<tr data-sortrow data-date="${escAttr(r.trade_date)}" data-exchange="${escAttr(r.exchange)}" data-stock="${escAttr(r.company_name || r.symbol)}" data-ticker="${escAttr(r.symbol)}" data-type="${escAttr(r.deal_type)}" data-side="${escAttr(r.buy_sell)}" data-client="${escAttr(r.client_name)}" data-qty="${r.quantity ?? ""}" data-price="${r.price ?? ""}" data-value="${r.deal_value ?? ""}">
          <td>${r.trade_date || ""}</td>
          <td>${r.exchange || ""}</td>
          <td>${stockLink(r.symbol, r.company_name || r.symbol || "—")}</td>
          <td>${r.symbol || ""}</td>
          <td>${dealTypeLabel(r.deal_type)}</td>
          <td>${r.buy_sell || ""}</td>
          <td>${r.client_name || "—"}</td>
          <td class="num">${r.quantity_s}</td>
          <td class="num">${r.price_s}</td>
          <td class="num">${r.deal_value_s}</td>
        </tr>`
    )
    .join("");
  document.getElementById("deal-table-wrap").innerHTML = `
    <table id="deal-rows-table">
      <thead>
        <tr>
          <th class="sortable" data-sort="date" data-type="text">Date${sortIcon()}</th>
          <th class="sortable" data-sort="exchange" data-type="text">Exchange${sortIcon()}</th>
          <th class="sortable" data-sort="stock" data-type="text">Stock${sortIcon()}</th>
          <th class="sortable" data-sort="ticker" data-type="text">Symbol${sortIcon()}</th>
          <th class="sortable" data-sort="type" data-type="text">Deal Type${sortIcon()}</th>
          <th class="sortable" data-sort="side" data-type="text">Buy/Sell${sortIcon()}</th>
          <th class="sortable" data-sort="client" data-type="text">Client${sortIcon()}</th>
          <th class="sortable num" data-sort="qty">Quantity${sortIcon()}</th>
          <th class="sortable num" data-sort="price">Price${sortIcon()}</th>
          <th class="sortable num" data-sort="value">Deal Value${sortIcon()}</th>
        </tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="10">No stored deals for this filter. Fetch today's or historical deals from NSE/BSE.</td></tr>`}</tbody>
    </table>`;
  bindSortableTable(document.getElementById("deal-rows-table"), "value", "desc");
  const pager = document.getElementById("deal-pager");
  const pages = list.pages || 1;
  pager.innerHTML = `
    <button type="button" data-deal-page="${dealPage - 1}" ${dealPage <= 1 ? "disabled" : ""}>Previous</button>
    <span>Page ${dealPage} of ${pages} · ${(list.total || 0).toLocaleString("en-IN")} deals</span>
    <button type="button" data-deal-page="${dealPage + 1}" ${dealPage >= pages ? "disabled" : ""}>Next</button>`;
  if (!dealDidAutoFetch) {
    dealDidAutoFetch = true;
    if (!maybeAutoFetchToday(stats.lastFetch || list.lastFetch)) {
      maybeBackfillMonths(stats);
    }
  } else if (!dealFetchBusy && !dealDidBackfill) {
    maybeBackfillMonths(stats);
  }
  if (!dealCapRetry && (stats.scores || []).some((r) => r.market_cap == null)) {
    dealCapRetry = true;
    setTimeout(() => loadDeals(dealPage), 14000);
  }
  setPageLoader(false);
}

function bindDeals() {
  if (dealsBound) return;
  dealsBound = true;
  const todayBtn = document.getElementById("deal-fetch-today");
  const histBtn = document.getElementById("deal-fetch-hist");
  const refreshBtn = document.getElementById("deal-refresh");
  document.querySelectorAll(".deal-periods [data-period]").forEach((btn) => {
    btn.addEventListener("click", () => applyDealPeriod(btn.dataset.period));
  });
  ["deal-exchange", "deal-type", "deal-side", "deal-from", "deal-to"].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("change", () => {
      if (id === "deal-from" || id === "deal-to") dealViewDate = "";
      loadDeals(1);
    });
  });
  const search = document.getElementById("deal-search");
  if (search) {
    search.addEventListener("input", () => {
      clearTimeout(dealSearchTimer);
      dealSearchTimer = setTimeout(() => loadDeals(1), 280);
    });
  }
  if (refreshBtn) refreshBtn.addEventListener("click", () => loadDeals(dealPage));
  if (todayBtn) todayBtn.addEventListener("click", () => runDealFetch("/api/deals/fetch/today", todayBtn, [histBtn]));
  if (histBtn) {
    histBtn.addEventListener("click", () => {
      const win = dealWindow();
      const ex = document.getElementById("deal-exchange").value;
      const ty = document.getElementById("deal-type").value;
      const q = new URLSearchParams({ fromDate: win.from, toDate: win.to, exchange: ex, dealType: ty });
      runDealFetch(`/api/deals/fetch?${q}`, histBtn, [todayBtn]);
    });
  }
  document.getElementById("deals").addEventListener("click", (ev) => {
    const pageBtn = ev.target.closest("[data-deal-page]");
    if (pageBtn && !pageBtn.disabled) {
      loadDeals(Number(pageBtn.dataset.dealPage));
      return;
    }
    const day = ev.target.closest("[data-deal-day]");
    if (day && day.dataset.dealDay) {
      dealViewDate = day.dataset.dealDay;
      loadDeals(1);
    }
  });
}

function runDealFetch(url, btn, others) {
  if (dealFetchBusy) return;
  dealFetchBusy = true;
  const box = document.getElementById("deal-fetch-status");
  const buttons = [btn, ...(others || [])].filter(Boolean);
  buttons.forEach((b) => {
    b.disabled = true;
  });
  const steps = {};
  const order = [
    "NSE_BULK",
    "NSE_BLOCK",
    "NSE_SHORT_SELLING",
    "BSE_BULK",
    "BSE_BLOCK",
  ];
  const labels = {
    NSE_BULK: "Fetching NSE Bulk Deals",
    NSE_BLOCK: "Fetching NSE Block Deals",
    NSE_SHORT_SELLING: "Fetching NSE Short Selling",
    BSE_BULK: "Fetching BSE Bulk Deals",
    BSE_BLOCK: "Fetching BSE Block Deals",
  };
  function paint(extra) {
    setPageLoader(true, "Fetching official NSE + BSE deals");
    setLoaderSteps(
      order.map((k) => ({ text: labels[k], ok: steps[k] })),
      extra || ""
    );
    if (box) {
      box.classList.add("hidden");
      box.textContent = extra || "";
    }
  }
  paint("Working… please wait. Do not close this page.");
  const src = new EventSource(url);
  src.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "step" && msg.key) steps[msg.key] = msg.ok;
    if (msg.type === "progress" && msg.text) paint(msg.text);
    else if (msg.type === "error") {
      paint(msg.text || "Fetch failed");
    } else if (msg.type === "done") {
      src.close();
      paint(
        `Completed · fetched ${(msg.fetched || 0).toLocaleString("en-IN")} · inserted ${(msg.inserted || 0).toLocaleString("en-IN")} · loading stored deals`
      );
      dealFetchBusy = false;
      buttons.forEach((b) => {
        b.disabled = false;
      });
      setPageLoader(true, "Loading stored deals");
      loadDeals(1);
      return;
    } else {
      paint(msg.text || "");
    }
  };
  src.onerror = () => {
    src.close();
    dealFetchBusy = false;
    buttons.forEach((b) => {
      b.disabled = false;
    });
    paint("Connection dropped. Reloading stored deals if the fetch finished.");
    setPageLoader(true, "Connection dropped");
    setTimeout(() => {
      setPageLoader(false);
      loadDeals(1);
    }, 1200);
  };
}

function dealPrintRows(rows) {
  return (rows || [])
    .map(
      (r) =>
        `<tr>
          <td>${r.exchange || ""}</td>
          <td>${dealTypeLabel(r.deal_type)}</td>
          <td class="${r.buy_sell === "BUY" ? "up" : "down"}">${r.buy_sell || ""}</td>
          <td>${r.client_name || "—"}</td>
          <td class="num">${r.quantity_s}</td>
          <td class="num">${r.price_s}</td>
          <td class="num">${r.deal_value_s}</td>
        </tr>`
    )
    .join("");
}

function renderStockPageTimeline(days) {
  if (!days || !days.length) {
    return "<p class=\"hint\">No dated buy/sell prints stored for this stock.</p>";
  }
  const max = Math.max(...days.map((d) => (d.buyValue || 0) + (d.sellValue || 0)), 1);
  return days
    .map((d) => {
      const buy = d.buyValue || 0;
      const sell = d.sellValue || 0;
      const net = d.netValue != null ? d.netValue : buy - sell;
      const prints = dealPrintRows(d.rows);
      return `<article class="deal-page-day">
        <div class="deal-page-day-head">
          <div class="deal-tl-date"><strong>${fmtDay(d.date)}</strong><em>${d.date}</em></div>
          <div class="deal-tl-side">
            <span class="up">Buy ${d.buy_s || inrShort(buy)} · ${d.buys || 0}</span>
            <div class="deal-tl-track"><span class="deal-tl-buy" style="width:${(buy / max) * 100}%"></span></div>
          </div>
          <div class="deal-tl-side">
            <span class="down">Sell ${d.sell_s || inrShort(sell)} · ${d.sells || 0}</span>
            <div class="deal-tl-track"><span class="deal-tl-sell" style="width:${(sell / max) * 100}%"></span></div>
          </div>
          <div class="deal-tl-net ${d.net_cls || (net >= 0 ? "up" : "down")}">${d.net_s || `${net >= 0 ? "+" : ""}${inrShort(net)}`}</div>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Exchange</th><th>Type</th><th>Buy/Sell</th><th>Client</th><th>Qty</th><th>Price</th><th>Value</th></tr></thead>
            <tbody>${prints || `<tr><td colspan="7">No prints on this date.</td></tr>`}</tbody>
          </table>
        </div>
      </article>`;
    })
    .join("");
}

async function loadDealStock() {
  const body = document.getElementById("deal-stock-body");
  const title = document.getElementById("deal-stock-title");
  const symbol = document.body.dataset.symbol;
  if (!body || !symbol) return;
  setPageLoader(true, "Loading stock deals");
  let data;
  try {
    data = await fetchApi(`/api/deals/stock/${encodeURIComponent(symbol)}`);
  } catch (err) {
    body.innerHTML = "<p class=\"hint\">No stored deals for this stock.</p>";
    setPageLoader(false);
    return;
  }
  document.title = `${data.company_name || data.symbol} · Large Deals`;
  if (title) title.textContent = `${data.company_name || data.symbol} · Large Deal Activity`;
  const t = data.totals || {};
  const w = data.windows || {};
  const flow = data.sector_flow || {};
  const days = data.timeline && data.timeline.length ? data.timeline : stockTimeline(data.rows || []);
  const span =
    data.firstDate && data.lastDate && data.firstDate !== data.lastDate
      ? `${data.firstDate} → ${data.lastDate}`
      : data.lastDate || data.date || "";
  body.innerHTML = `
    <p class="eyebrow">${data.symbol} · ${data.sector || "Unmapped sector"} · ${span} · ${data.dateCount || days.length} date${(data.dateCount || days.length) === 1 ? "" : "s"}</p>
    <div class="chips deal-chips">
      <article><span>Market Cap</span><strong>${data.market_cap_s || "—"}</strong></article>
      <article><span>Last Price</span><strong>${data.last_price_s || "—"}</strong></article>
      <article><span>Total Buy Quantity</span><strong>${t.buy_qty_s || "—"}</strong></article>
      <article><span>Total Sell Quantity</span><strong>${t.sell_qty_s || "—"}</strong></article>
      <article><span>Net Quantity</span><strong>${t.net_qty_s || "—"}</strong></article>
      <article><span>Total Buy Value</span><strong class="up">${t.buy_s || "—"}</strong></article>
      <article><span>Total Sell Value</span><strong class="down">${t.sell_s || "—"}</strong></article>
      <article><span>Net Deal Value</span><strong class="${t.net_cls || ""}">${t.net_s || "—"}</strong></article>
    </div>
    <div class="signals">
      <div><span>Large Deal Activity Score</span><strong>${data.score}</strong></div>
      <div><span>Bulk Deal</span><strong>${data.bulk || "—"}</strong></div>
      <div><span>Block Deal</span><strong>${data.block || "—"}</strong></div>
      <div><span>Sector Flow</span><strong>${flow.signal || "—"}</strong></div>
      <div><span>7D Deal Activity</span><strong class="${(w["7d"] || {}).net_cls || ""}">${(w["7d"] || {}).net_s || "—"}</strong></div>
      <div><span>30D Deal Activity</span><strong class="${(w["30d"] || {}).net_cls || ""}">${(w["30d"] || {}).net_s || "—"}</strong></div>
      <div><span>90D Deal Activity</span><strong class="${(w["90d"] || {}).net_cls || ""}">${(w["90d"] || {}).net_s || "—"}</strong></div>
    </div>
    <p class="hint">Every stored official print is listed under the date it happened. Score is not a black-box rating and is not guaranteed institutional accumulation.</p>
    <h4 class="deal-sub">Buy / sell timeline</h4>
    <div class="deal-page-tl">${renderStockPageTimeline(days)}</div>`;
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
    scrapeBusy = true;
    box.classList.add("hidden");
    Object.keys(done).forEach((k) => delete done[k]);
    function paint(extra) {
      setPageLoader(true, "Updating official market data");
      setLoaderSteps(
        order.map((label) => ({ text: label, ok: done[label] })),
        extra || "Working… please wait. Do not close this page."
      );
      render(extra ? [extra] : ["Working…"]);
    }
    paint("Scraping into the database…");
    const src = new EventSource("/api/scrape");
    const extra = [];
    src.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "log" && msg.text) extra.push(msg.text);
      if (msg.type === "step" && msg.label) done[msg.label] = !!msg.ok;
      if (msg.type === "month" && msg.text) extra.push(msg.text);
      if (msg.type === "error") extra.push(msg.text || "Update failed");
      if (msg.type === "done") {
        extra.push("Market data updated");
        paint(
          `Done · historical ${msg.historical_updated || 0} updated · ${msg.historical_skipped || 0} skipped · reloading`
        );
        src.close();
        scrapeBusy = false;
        btn.disabled = false;
        render(extra);
        setTimeout(() => location.reload(), 800);
        return;
      }
      paint(extra.slice(-1)[0] || "Working… please wait. Do not close this page.");
    };
    src.onerror = () => {
      extra.push("Connection dropped. If the update finished, reload the page.");
      src.close();
      scrapeBusy = false;
      btn.disabled = false;
      paint("Connection dropped. If the update finished, reload the page.");
      setTimeout(() => setPageLoader(false), 1600);
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
      const on = el.dataset.sort === current;
      el.classList.toggle("on", on);
      el.classList.toggle("asc", on && dir === 1);
      el.classList.toggle("desc", on && dir === -1);
      el.setAttribute("aria-sort", on ? (dir === 1 ? "ascending" : "descending") : "none");
      if (!el.querySelector(".sort-icon")) {
        el.insertAdjacentHTML("beforeend", ' <span class="sort-icon" aria-hidden="true"></span>');
      }
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
} else if (document.body.dataset.page === "deals") {
  loadDeals();
} else if (document.body.dataset.page === "deal-stock") {
  loadDealStock();
}
