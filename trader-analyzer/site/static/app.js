// Trader Analyzer — фронтенд (Apple HIG + SVG-графики)
const API = "";
const LIMIT = 50;

const state = {
  page: 0, total: 0, strategy: "", city: "", q: "", minPnl: "", sort: "pnl",
};

const $ = (id) => document.getElementById(id);

// ---- палитра стратегий ----
const STRAT_COLORS = {
  ladder: "#0a84ff", longshot: "#5e5ce6", certain: "#30d158",
  value: "#ffd60a", momentum: "#ff9f0a", specialist: "#ff453a",
  mixed: "#8e8e93", unknown: "#48484a",
};
const AVATAR_GRADS = [
  "linear-gradient(135deg,#0a84ff,#5e5ce6)",
  "linear-gradient(135deg,#30d158,#0a84ff)",
  "linear-gradient(135deg,#ff9f0a,#ff453a)",
  "linear-gradient(135deg,#5e5ce6,#bf5af2)",
  "linear-gradient(135deg,#ff375f,#ff9f0a)",
  "linear-gradient(135deg,#64d2ff,#0a84ff)",
];

// ---- форматтеры ----
function fmtMoney(v) {
  if (v == null) return "—";
  const n = Number(v);
  const a = Math.abs(n);
  const sign = n < 0 ? "−" : "";
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)}K`;
  return `${sign}$${a.toFixed(0)}`;
}
function fmtPnl(v) {
  if (v == null) return { cls: "pnl-zero", text: "—" };
  const n = Number(v);
  const cls = n > 0 ? "pnl-pos" : n < 0 ? "pnl-neg" : "pnl-zero";
  return { cls, text: fmtMoney(n) };
}
function fmtPct(v) {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}
function fmtNum(v) {
  if (v == null) return "—";
  return Number(v).toLocaleString("ru-RU");
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- count-up анимация ----
function countUp(el, target, fmt) {
  const start = performance.now();
  const dur = 1000;
  const t0 = Number(target);
  function tick(t) {
    const p = Math.min((t - start) / dur, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(t0 * eased);
    if (p < 1) requestAnimationFrame(tick);
    else el.textContent = fmt(t0);
  }
  requestAnimationFrame(tick);
}

// ---- метрики ----
function renderMetrics(stats) {
  countUp($("m-total"), stats.total, (v) => fmtNum(Math.round(v)));
  $("m-pnl").textContent = fmtMoney(stats.total_pnl);
  $("m-pnl").className = "metric-value " + (stats.total_pnl >= 0 ? "pos" : "neg");
  countUp($("m-playbook"), stats.playbook, (v) => fmtNum(Math.round(v)));
  $("m-winrate").textContent = fmtPct(stats.winrate);
}

// ---- donut chart (SVG) ----
function renderDonut(stats) {
  const svg = $("donut");
  const R = 80, C = 2 * Math.PI * R;
  const total = stats.by_strategy.reduce((s, x) => s + x.n, 0) || 1;
  $("donut-n").textContent = fmtNum(stats.total);

  let offset = 0;
  const circles = stats.by_strategy.map((s) => {
    const frac = s.n / total;
    const len = frac * C;
    const color = STRAT_COLORS[s.strategy] || "#48484a";
    const circle = `<circle cx="100" cy="100" r="${R}" fill="none"
      stroke="${color}" stroke-width="22"
      stroke-dasharray="0 ${C}" stroke-dashoffset="${-offset}"
      data-len="${len}" data-off="${-offset}"
      style="transition: stroke-dasharray 1s var(--spring)"></circle>`;
    offset += len;
    return circle;
  }).join("");
  svg.innerHTML = circles;

  requestAnimationFrame(() => {
    svg.querySelectorAll("circle").forEach((c) => {
      c.setAttribute("stroke-dasharray", `${c.dataset.len} ${C - c.dataset.len}`);
    });
  });

  // легенда
  const legend = $("legend");
  const maxN = Math.max(...stats.by_strategy.map((s) => s.n), 1);
  legend.innerHTML = stats.by_strategy.map((s) => {
    const pnl = fmtPnl(s.sum_pnl);
    const color = STRAT_COLORS[s.strategy] || "#48484a";
    return `
      <div class="legend-row">
        <span class="legend-dot" style="background:${color}"></span>
        <span class="legend-name">${esc(s.strategy)}</span>
        <div class="legend-bar-wrap"><div class="legend-bar"
          data-w="${s.n / maxN}" style="background:${color}"></div></div>
        <span class="legend-n">${fmtNum(s.n)}</span>
        <span class="legend-pnl ${pnl.cls}">${pnl.text}</span>
      </div>`;
  }).join("");
  requestAnimationFrame(() => {
    legend.querySelectorAll(".legend-bar").forEach((b) => {
      b.style.transform = `scaleX(${b.dataset.w})`;
    });
  });
}

// ---- гистограмма PnL ----
function renderHistogram(stats) {
  const el = $("histogram");
  const maxN = Math.max(...stats.pnl_dist.map((d) => d.n), 1);
  el.innerHTML = stats.pnl_dist.map((d) => `
    <div class="hist-col">
      <span class="hist-n">${fmtNum(d.n)}</span>
      <div class="hist-bar-wrap">
        <div class="hist-bar" data-h="${d.n / maxN}"></div>
      </div>
      <span class="hist-label">${esc(d.bucket)}</span>
    </div>`).join("");
  requestAnimationFrame(() => {
    el.querySelectorAll(".hist-bar").forEach((b) => {
      b.style.transform = `scaleY(${b.dataset.h})`;
    });
  });
}

// ---- топ ----
function renderTop(stats) {
  const traders = $("top-traders-list");
  traders.innerHTML = stats.top_wallets.map((w, i) => {
    const pnl = fmtPnl(w.pnl);
    const initials = (w.name || w.wallet || "?").slice(0, 1).toUpperCase();
    const grad = AVATAR_GRADS[i % AVATAR_GRADS.length];
    return `
      <div class="list-row">
        <span class="rank ${i < 3 ? "top" : ""}">${i + 1}</span>
        <span class="avatar" style="background:${grad}">${esc(initials)}</span>
        <span class="list-name">${esc(w.name || w.wallet)}</span>
        <span class="list-meta">${esc(w.strategy)}</span>
        <span class="list-val ${pnl.cls}">${pnl.text}</span>
      </div>`;
  }).join("");

  const cities = $("top-cities-list");
  const maxPnl = Math.max(...stats.top_cities.map((c) => Math.abs(c.sum_pnl)), 1);
  cities.innerHTML = stats.top_cities.map((c, i) => {
    const pnl = fmtPnl(c.sum_pnl);
    const w = Math.abs(c.sum_pnl) / maxPnl;
    return `
      <div class="list-row">
        <span class="rank ${i < 3 ? "top" : ""}">${i + 1}</span>
        <span class="list-name">${esc(c.city)}</span>
        <div class="legend-bar-wrap" style="max-width:120px">
          <div class="legend-bar" data-w="${w}"
            style="background:linear-gradient(90deg,#0a84ff,#5e5ce6)"></div>
        </div>
        <span class="list-meta">${fmtNum(c.n)}</span>
        <span class="list-val ${pnl.cls}">${pnl.text}</span>
      </div>`;
  }).join("");
  requestAnimationFrame(() => {
    cities.querySelectorAll(".legend-bar").forEach((b) => {
      b.style.transform = `scaleX(${b.dataset.w})`;
    });
  });
}

// ---- таблица кошельков ----
const STRAT_CHIP = {
  ladder: "chip-ladder", longshot: "chip-longshot", certain: "chip-certain",
  value: "chip-value", momentum: "chip-momentum",
  specialist: "chip-specialist", mixed: "chip-mixed", unknown: "chip-unknown",
};

function renderWallets(data) {
  const body = $("wallets-body");
  if (!data.items.length) {
    body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text-3);padding:32px">Ничего не найдено</td></tr>`;
    return;
  }
  body.innerHTML = data.items.map((w) => {
    const pnl = fmtPnl(w.pnl);
    const chip = STRAT_CHIP[w.strategy] || "chip-unknown";
    const name = w.name || w.wallet_short || w.wallet;
    const weather = w.weather_ratio != null ? Math.round(w.weather_ratio * 100) : 0;
    return `
      <tr>
        <td>
          <div class="trader-name">${esc(name)}</div>
          <div class="trader-addr">${esc(w.wallet_short || w.wallet || "")}</div>
        </td>
        <td><span class="strat-chip ${chip}">${esc(w.strategy || "—")}</span></td>
        <td class="num ${pnl.cls}">${pnl.text}</td>
        <td class="num">${w.trades_per_month != null ? w.trades_per_month.toFixed(1) : "—"}</td>
        <td class="num">${w.volume_30d != null ? fmtMoney(w.volume_30d) : "—"}</td>
        <td>${esc(w.top_city || "—")}</td>
        <td class="num"><span class="weather-cell">
          <span class="weather-bar"><i style="width:${weather}%"></i></span>
          ${weather}%</span></td>
        <td class="num">${w.median_entry != null ? "$" + w.median_entry.toFixed(2) : "—"}</td>
      </tr>`;
  }).join("");
}

// ---- пагинация ----
function renderPager() {
  const pages = Math.ceil(state.total / LIMIT);
  const from = state.total === 0 ? 0 : state.page * LIMIT + 1;
  const to = Math.min((state.page + 1) * LIMIT, state.total);
  $("pager").textContent = `${from}–${to} из ${fmtNum(state.total)}`;
  $("pg-prev").disabled = state.page === 0;
  $("pg-next").disabled = state.page >= pages - 1;
}

// ---- загрузка кошельков ----
async function loadWallets() {
  const p = new URLSearchParams();
  if (state.strategy) p.set("strategy", state.strategy);
  if (state.city) p.set("city", state.city);
  if (state.q) p.set("q", state.q);
  if (state.minPnl) p.set("min_pnl", state.minPnl);
  p.set("sort", state.sort);
  p.set("desc", "true");
  p.set("limit", String(LIMIT));
  p.set("offset", String(state.page * LIMIT));
  const r = await fetch(`${API}/api/wallets?${p}`);
  const data = await r.json();
  state.total = data.total;
  renderWallets(data);
  renderPager();
  $("wallets-count").textContent = `${fmtNum(data.total)} кошельков`;
}

// ---- фильтры ----
function populateFilters(meta) {
  const stratSel = $("f-strategy");
  stratSel.innerHTML =
    `<option value="">Все стратегии</option>` +
    meta.strategies.map((s) => `<option>${esc(s)}</option>`).join("");
  const citySel = $("f-city");
  citySel.innerHTML =
    `<option value="">Все города</option>` +
    meta.cities.map((c) => `<option>${esc(c)}</option>`).join("");
}

function bindFilters() {
  $("f-strategy").addEventListener("change", (e) => {
    state.strategy = e.target.value; state.page = 0; loadWallets();
  });
  $("f-city").addEventListener("change", (e) => {
    state.city = e.target.value; state.page = 0; loadWallets();
  });
  $("f-sort").addEventListener("change", (e) => {
    state.sort = e.target.value; state.page = 0; loadWallets();
  });
  let qTimer;
  $("f-q").addEventListener("input", (e) => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { state.q = e.target.value; state.page = 0; loadWallets(); }, 250);
  });
  let pnlTimer;
  $("f-minpnl").addEventListener("input", (e) => {
    clearTimeout(pnlTimer);
    pnlTimer = setTimeout(() => { state.minPnl = e.target.value; state.page = 0; loadWallets(); }, 400);
  });
  $("pg-prev").addEventListener("click", () => {
    if (state.page > 0) { state.page--; loadWallets(); }
  });
  $("pg-next").addEventListener("click", () => {
    state.page++; loadWallets();
  });
}

// ---- init ----
async function init() {
  const [stats, meta] = await Promise.all([
    fetch(`${API}/api/stats`).then((r) => r.json()),
    fetch(`${API}/api/meta`).then((r) => r.json()),
  ]);
  renderMetrics(stats);
  renderDonut(stats);
  renderHistogram(stats);
  renderTop(stats);
  populateFilters(meta);
  bindFilters();
  await loadWallets();
  $("live-label").textContent =
    `${fmtNum(stats.total)} профилей · ${fmtNum(stats.playbook)} playbook`;
}

init();
