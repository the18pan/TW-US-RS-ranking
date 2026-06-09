let stocks = [];
let sectors = [];
let historyData = {};
let historyChart = null;

let activeTab = "ranking";
let marketFilter = "all";
let capFilter = "all";
let rsFilter = 0;
let sectorFilter = "all";
let searchQuery = "";
let sortCol = "rs";
let sortDir = -1;
let page = 1;

const PER_PAGE = 30;

const SEPA_LABELS = {
  rs70: "RS≥70",
  above_150ma: "站上150MA",
  above_200ma: "站上200MA",
  ma200_up: "200MA上揚",
  ma150_gt_200: "150MA>200MA",
  near_52w_high: "接近52週高點",
};

const CAP_LABELS = {
  L: "大型",
  M: "中型",
  S: "小型",
};

const DEMO_DATA = {
  schema_version: 2,
  updated_at: "Demo",
  total: 10,
  formula: "RS raw = Q1*50% + Q2*25% + Q3*15% + Q4*10%; RS = market percentile",
  sources: { prices: "demo" },
  summary: {
    rs90: 2,
    rs70: 7,
    sepa: 4,
    rs_line_high: 3,
    by_market: {
      tw: { name: "台股", total: 5, rs90: 1, rs70: 4, sepa: 2, rs_line_high: 1 },
      us: { name: "美股", total: 5, rs90: 1, rs70: 3, sepa: 2, rs_line_high: 2 },
    },
  },
  stocks: [
    demoStock("tw", "2330", "台積電", "半導體", "L", 96, 94, 1780, 31.4, 18.2, 12.1, 6.3, 1.2, 4.5, 14.8, true, true),
    demoStock("us", "NVDA", "NVIDIA Corporation", "Technology", "L", 98, 99, 142.7, 42.1, 28.3, 14.9, 8.2, 2.4, 6.8, 21.2, true, true),
    demoStock("tw", "2454", "聯發科", "半導體", "L", 88, 82, 1515, 18.2, 11.4, 9.3, 4.8, -0.8, 2.6, 9.4, false, true),
    demoStock("us", "AVGO", "Broadcom Inc.", "Technology", "L", 91, 92, 1765.1, 24.3, 19.7, 10.1, 7.6, 1.8, 5.1, 16.7, true, true),
    demoStock("tw", "2308", "台達電", "電子零組件", "L", 82, 74, 402, 15.6, 8.4, 6.5, 3.7, 0.6, 1.8, 7.2, false, false),
    demoStock("us", "MSFT", "Microsoft Corporation", "Technology", "L", 86, 84, 468.5, 16.9, 10.8, 7.4, 4.4, 0.4, 1.9, 8.1, false, true),
    demoStock("tw", "2317", "鴻海", "其他電子", "L", 76, 67, 216, 11.1, 6.7, 5.2, 2.1, -0.5, 0.9, 5.3, false, false),
    demoStock("us", "AAPL", "Apple Inc.", "Technology", "L", 72, 65, 203.9, 8.4, 5.1, 3.3, 1.9, -0.3, 1.1, 4.7, false, false),
    demoStock("tw", "5871", "中租-KY", "金融保險", "M", 64, 55, 156, 4.8, 2.2, -1.4, 0.8, 0.1, -0.4, 1.7, false, false),
    demoStock("us", "XOM", "Exxon Mobil Corporation", "Energy", "L", 61, 52, 111.2, 3.7, 4.8, 2.6, -0.7, 0.2, 1.4, 2.3, false, false),
  ],
  sectors: [
    demoSector("tw", "半導體", 2, 92, 1, 2, 0.2, 3.5, 12.1),
    demoSector("us", "Technology", 4, 87, 2, 4, 1.1, 3.7, 12.7),
    demoSector("tw", "電子零組件", 1, 82, 0, 1, 0.6, 1.8, 7.2),
    demoSector("us", "Energy", 1, 61, 0, 0, 0.2, 1.4, 2.3),
    demoSector("tw", "金融保險", 1, 64, 0, 0, 0.1, -0.4, 1.7),
    demoSector("tw", "其他電子", 1, 76, 0, 1, -0.5, 0.9, 5.3),
  ],
};

function demoStock(market, code, name, sector, cap, rs, rsGlobal, price, q1, q2, q3, q4, c1, c5, c1m, rsHigh, sepa) {
  const exchange = market === "tw" ? "TWSE" : "NASDAQ";
  const tvSymbol = market === "tw" ? `TWSE:${code}` : `${exchange}:${code}`;
  return {
    market,
    market_name: market === "tw" ? "台股" : "美股",
    code,
    name,
    sector,
    industry: sector,
    cap,
    market_cap: 0,
    currency: market === "tw" ? "TWD" : "USD",
    exchange,
    yf_symbol: market === "tw" ? `${code}.TW` : code,
    tv_symbol: tvSymbol,
    rs,
    rs_global: rsGlobal,
    rs_raw: q1 * 0.5 + q2 * 0.25 + q3 * 0.15 + q4 * 0.1,
    q1,
    q2,
    q3,
    q4,
    c1,
    c5,
    c1m,
    price,
    rsHigh,
    sepa,
    sepa_detail: {
      rs70: rs >= 70,
      above_150ma: sepa,
      above_200ma: sepa,
      ma200_up: sepa,
      ma150_gt_200: sepa,
      near_52w_high: rs >= 70,
    },
  };
}

function demoSector(market, name, count, avgRs, rs90, rs70, c1, c5, c1m) {
  return {
    market,
    market_name: market === "tw" ? "台股" : "美股",
    name,
    label: `${market === "tw" ? "台股" : "美股"} / ${name}`,
    count,
    avg_rs: avgRs,
    median_rs: avgRs,
    rs90_count: rs90,
    rs70_count: rs70,
    avg_c1: c1,
    avg_c5: c5,
    avg_c1m: c1m,
  };
}

async function loadData() {
  try {
    const [dataRes, historyRes] = await Promise.all([
      fetch(`rs_data.json?t=${Date.now()}`),
      fetch(`rs_history.json?t=${Date.now()}`).catch(() => ({ ok: false })),
    ]);
    if (!dataRes.ok) throw new Error(`HTTP ${dataRes.status}`);
    const data = await dataRes.json();
    stocks = (data.stocks || []).map(normalizeStock);
    sectors = (data.sectors || []).map(normalizeSector);
    historyData = historyRes.ok ? await historyRes.json() : {};
    hydrateSummary(data);
    document.getElementById("schema-note").textContent = `schema v${data.schema_version || 1}`;
  } catch (error) {
    console.warn("Failed to load generated JSON, using demo data:", error);
    stocks = DEMO_DATA.stocks.map(normalizeStock);
    sectors = DEMO_DATA.sectors.map(normalizeSector);
    historyData = {};
    hydrateSummary(DEMO_DATA, true);
    document.getElementById("schema-note").textContent = "demo data";
  }
}

function normalizeStock(stock) {
  return {
    market: stock.market || "tw",
    market_name: stock.market_name || (stock.market === "us" ? "美股" : "台股"),
    code: String(stock.code || ""),
    name: String(stock.name || ""),
    sector: stock.sector || "Other",
    industry: stock.industry || "",
    cap: stock.cap || "S",
    market_cap: Number(stock.market_cap || 0),
    currency: stock.currency || (stock.market === "us" ? "USD" : "TWD"),
    exchange: stock.exchange || "",
    yf_symbol: stock.yf_symbol || stock.code,
    tv_symbol: stock.tv_symbol || stock.code,
    rs: Number(stock.rs || 0),
    rs_global: Number(stock.rs_global || stock.rs || 0),
    rs_raw: Number(stock.rs_raw || 0),
    q1: Number(stock.q1 || 0),
    q2: Number(stock.q2 || 0),
    q3: Number(stock.q3 || 0),
    q4: Number(stock.q4 || 0),
    c1: Number(stock.c1 || 0),
    c5: Number(stock.c5 || 0),
    c1m: Number(stock.c1m || 0),
    price: Number(stock.price || 0),
    rsHigh: Boolean(stock.rsHigh),
    sepa: Boolean(stock.sepa),
    sepa_detail: stock.sepa_detail || {},
  };
}

function normalizeSector(sector) {
  return {
    market: sector.market || "tw",
    market_name: sector.market_name || (sector.market === "us" ? "美股" : "台股"),
    name: sector.name || "Other",
    label: sector.label || `${sector.market_name || ""} / ${sector.name || "Other"}`,
    count: Number(sector.count || 0),
    avg_rs: Number(sector.avg_rs || 0),
    median_rs: Number(sector.median_rs || 0),
    rs90_count: Number(sector.rs90_count || 0),
    rs70_count: Number(sector.rs70_count || 0),
    avg_c1: Number(sector.avg_c1 || 0),
    avg_c5: Number(sector.avg_c5 || 0),
    avg_c1m: Number(sector.avg_c1m || 0),
  };
}

function hydrateSummary(data, demo = false) {
  const summary = data.summary || {};
  const byMarket = summary.by_market || {};
  document.getElementById("update-time").textContent = demo ? "Demo data" : `${data.updated_at || "--"} Asia/Taipei`;
  document.getElementById("cnt-total").textContent = formatInteger(data.total || stocks.length);
  document.getElementById("cnt-rs70").textContent = formatInteger(summary.rs70 || 0);
  document.getElementById("cnt-sepa").textContent = formatInteger(summary.sepa || 0);
  document.getElementById("cnt-high").textContent = formatInteger(summary.rs_line_high || 0);
  const twTotal = byMarket.tw?.total ?? stocks.filter((s) => s.market === "tw").length;
  const usTotal = byMarket.us?.total ?? stocks.filter((s) => s.market === "us").length;
  document.getElementById("cnt-by-market").textContent = `台股 ${formatInteger(twTotal)} · 美股 ${formatInteger(usTotal)}`;
}

function populateSectorSelect() {
  const select = document.getElementById("sector-filter");
  const current = select.value;
  const options = new Map();
  stocks.forEach((stock) => {
    const key = `${stock.market}|${stock.sector}`;
    options.set(key, `${stock.market_name} / ${stock.sector}`);
  });
  select.innerHTML = '<option value="all">全部板塊</option>';
  [...options.entries()]
    .sort((a, b) => a[1].localeCompare(b[1], "zh-Hant"))
    .forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.appendChild(option);
    });
  select.value = options.has(current) ? current : "all";
  sectorFilter = select.value;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatInteger(value) {
  return Number(value || 0).toLocaleString("en-US");
}

function formatPct(value) {
  const numeric = Number(value || 0);
  const sign = numeric > 0 ? "+" : "";
  const cls = numeric > 0 ? "pos" : numeric < 0 ? "neg" : "muted";
  return `<span class="${cls}">${sign}${numeric.toFixed(1)}%</span>`;
}

function formatPrice(stock) {
  if (!stock.price) return "--";
  const digits = stock.price >= 1000 ? 0 : 2;
  const price = stock.price.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return stock.currency === "USD" ? `$${price}` : price;
}

function formatMarketCap(stock) {
  if (!stock.market_cap) return CAP_LABELS[stock.cap] || stock.cap;
  if (stock.market === "us") {
    if (stock.market_cap >= 1e12) return `$${(stock.market_cap / 1e12).toFixed(2)}T`;
    if (stock.market_cap >= 1e9) return `$${(stock.market_cap / 1e9).toFixed(1)}B`;
    return `$${(stock.market_cap / 1e6).toFixed(0)}M`;
  }
  if (stock.market_cap >= 1e12) return `${(stock.market_cap / 1e12).toFixed(2)}兆`;
  return `${(stock.market_cap / 1e8).toFixed(0)}億`;
}

function marketBadge(market) {
  const label = market === "us" ? "美股" : "台股";
  return `<span class="market-badge ${market}">${label}</span>`;
}

function capBadge(stock) {
  const cap = stock.cap || "S";
  return `<span class="cap-badge cap-${cap}" title="${escapeHtml(formatMarketCap(stock))}">${CAP_LABELS[cap] || cap}</span>`;
}

function rsColor(rs) {
  if (rs >= 90) return "rs-hot";
  if (rs >= 80) return "rs-strong";
  if (rs >= 70) return "rs-watch";
  if (rs >= 50) return "rs-mid";
  return "rs-weak";
}

function rsCell(rs) {
  const safe = Math.max(0, Math.min(99, Number(rs || 0)));
  return `<div class="rs-cell">
    <div class="rs-track"><div class="rs-fill ${rsColor(safe)}" style="width:${safe}%"></div></div>
    <span class="${rsColor(safe)}">${safe}</span>
  </div>`;
}

function tvUrl(stock) {
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(stock.tv_symbol || stock.code)}`;
}

function stockHistoryKey(stock) {
  return `${stock.market}:${stock.code}`;
}

function getHistoryEntries(stock) {
  return historyData[stockHistoryKey(stock)] || [];
}

function hasUsableHistory(stock) {
  return getHistoryEntries(stock).length >= 2;
}

function getFilteredStocks() {
  const query = searchQuery.trim().toLowerCase();
  const filtered = stocks.filter((stock) => {
    if (marketFilter !== "all" && stock.market !== marketFilter) return false;
    if (capFilter !== "all" && stock.cap !== capFilter) return false;
    if (stock.rs < rsFilter) return false;
    if (sectorFilter !== "all" && `${stock.market}|${stock.sector}` !== sectorFilter) return false;
    if (query) {
      const haystack = `${stock.code} ${stock.name} ${stock.sector} ${stock.industry} ${stock.exchange}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });

  return filtered.sort((a, b) => compareValues(a, b, sortCol) * sortDir);
}

function compareValues(a, b, col) {
  const av = a[col];
  const bv = b[col];
  if (typeof av === "boolean" || typeof bv === "boolean") {
    return Number(av) - Number(bv);
  }
  if (typeof av === "number" || typeof bv === "number") {
    return Number(av || 0) - Number(bv || 0);
  }
  return String(av || "").localeCompare(String(bv || ""), "zh-Hant");
}

function renderRanking() {
  const data = getFilteredStocks();
  const totalPages = Math.max(1, Math.ceil(data.length / PER_PAGE));
  if (page > totalPages) page = totalPages;
  const start = (page - 1) * PER_PAGE;
  const rows = data.slice(start, start + PER_PAGE);

  document.getElementById("result-count").textContent = `${formatInteger(data.length)} 檔`;
  document.getElementById("ranking-body").innerHTML = rows
    .map((stock, idx) => {
      const rank = start + idx + 1;
      const lineTag = stock.rsHigh ? '<span class="line-tag">52W High</span>' : '<span class="dash">--</span>';
      const sepaTag = stock.sepa ? '<span class="sepa-mini">SEPA</span>' : "";
      const historyReady = hasUsableHistory(stock);
      return `<tr class="${historyReady ? "clickable-row" : "history-disabled-row"}" data-key="${escapeHtml(stockHistoryKey(stock))}" title="${historyReady ? "查看 RS 歷史" : "歷史資料累積中"}">
        <td class="right rank">${rank}</td>
        <td>${marketBadge(stock.market)}</td>
        <td class="symbol"><a href="${tvUrl(stock)}" target="_blank" rel="noopener">${escapeHtml(stock.code)}</a></td>
        <td class="name-cell">${escapeHtml(stock.name)} ${sepaTag}</td>
        <td>${rsCell(stock.rs)}</td>
        <td class="mono">${stock.rs_global}</td>
        <td>${lineTag}</td>
        <td class="right mono">${formatPrice(stock)}</td>
        <td class="right mono">${formatPct(stock.q1)}</td>
        <td class="right mono">${formatPct(stock.q2)}</td>
        <td class="right mono">${formatPct(stock.q3)}</td>
        <td class="right mono">${formatPct(stock.q4)}</td>
        <td class="right mono">${formatPct(stock.c1)}</td>
        <td class="right mono">${formatPct(stock.c5)}</td>
        <td class="right mono">${formatPct(stock.c1m)}</td>
        <td>${capBadge(stock)}</td>
        <td class="sector">${escapeHtml(stock.sector)}</td>
      </tr>`;
    })
    .join("");

  document.querySelectorAll("#ranking-body tr").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("a")) return;
      const stock = stocks.find((item) => stockHistoryKey(item) === row.dataset.key);
      if (stock && hasUsableHistory(stock)) openHistory(stock);
    });
  });

  renderPagination(totalPages);
}

function renderPagination(totalPages) {
  const container = document.getElementById("pagination");
  container.innerHTML = "";
  const add = (label, target, disabled = false, active = false) => {
    const button = document.createElement("button");
    button.className = `page-btn${active ? " active" : ""}`;
    button.textContent = label;
    button.disabled = disabled;
    button.addEventListener("click", () => {
      page = target;
      renderRanking();
    });
    container.appendChild(button);
  };
  add("<<", 1, page === 1);
  add("<", Math.max(1, page - 1), page === 1);
  const first = Math.max(1, page - 2);
  const last = Math.min(totalPages, page + 2);
  for (let p = first; p <= last; p += 1) add(String(p), p, false, p === page);
  add(">", Math.min(totalPages, page + 1), page === totalPages);
  add(">>", totalPages, page === totalPages);
}

function renderSepa() {
  const rows = getFilteredStocks().filter((stock) => stock.sepa);
  document.getElementById("sepa-count").textContent = `${formatInteger(rows.length)} 檔`;
  document.getElementById("sepa-body").innerHTML = rows
    .map((stock, idx) => {
      const checks = Object.entries(SEPA_LABELS)
        .map(([key, label]) => {
          const pass = Boolean(stock.sepa_detail?.[key]);
          return `<span class="check ${pass ? "pass" : "fail"}">${pass ? "✓" : "×"} ${label}</span>`;
        })
        .join("");
      return `<tr>
        <td class="right rank">${idx + 1}</td>
        <td>${marketBadge(stock.market)}</td>
        <td class="symbol"><a href="${tvUrl(stock)}" target="_blank" rel="noopener">${escapeHtml(stock.code)}</a></td>
        <td class="name-cell">${escapeHtml(stock.name)}</td>
        <td>${rsCell(stock.rs)}</td>
        <td class="mono">${stock.rs_global}</td>
        <td class="right mono">${formatPct(stock.q1)}</td>
        <td class="right mono">${formatPct(stock.c1m)}</td>
        <td class="checks">${checks}</td>
        <td class="sector">${escapeHtml(stock.sector)}</td>
      </tr>`;
    })
    .join("");
}

function renderSectors() {
  const rows = sectors
    .filter((sector) => marketFilter === "all" || sector.market === marketFilter)
    .sort((a, b) => b.avg_rs - a.avg_rs);
  document.getElementById("sector-count").textContent = `${formatInteger(rows.length)} 個板塊`;
  document.getElementById("sector-body").innerHTML = rows
    .map((sector, idx) => `<tr>
      <td class="right rank">${idx + 1}</td>
      <td>${marketBadge(sector.market)}</td>
      <td class="name-cell">${escapeHtml(sector.name)}</td>
      <td class="right mono">${formatInteger(sector.count)}</td>
      <td>${rsCell(Math.round(sector.avg_rs))}</td>
      <td class="right mono">${formatInteger(sector.rs90_count)}</td>
      <td class="right mono">${formatInteger(sector.rs70_count)}</td>
      <td class="right mono">${formatPct(sector.avg_c1)}</td>
      <td class="right mono">${formatPct(sector.avg_c5)}</td>
      <td class="right mono">${formatPct(sector.avg_c1m)}</td>
    </tr>`)
    .join("");
}

function renderAll() {
  renderRanking();
  renderSepa();
  renderSectors();
}

function bindEvents() {
  document.querySelectorAll(".nav-link").forEach((button) => {
    button.addEventListener("click", () => {
      activeTab = button.dataset.tab;
      document.querySelectorAll(".nav-link").forEach((btn) => btn.classList.toggle("active", btn === button));
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === `tab-${activeTab}`);
      });
    });
  });

  bindSegmented("market-filter", "market", (value) => {
    marketFilter = value;
    page = 1;
    renderAll();
  });
  bindSegmented("cap-filter", "cap", (value) => {
    capFilter = value;
    page = 1;
    renderAll();
  });
  bindSegmented("rs-filter", "rs", (value) => {
    rsFilter = Number(value || 0);
    page = 1;
    renderAll();
  });

  document.getElementById("sector-filter").addEventListener("change", (event) => {
    sectorFilter = event.target.value;
    page = 1;
    renderAll();
  });

  document.getElementById("search-input").addEventListener("input", (event) => {
    searchQuery = event.target.value;
    page = 1;
    renderAll();
  });

  document.querySelectorAll("th[data-col]").forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.dataset.col;
      if (sortCol === col) {
        sortDir *= -1;
      } else {
        sortCol = col;
        sortDir = ["name", "code", "market", "sector", "cap"].includes(col) ? 1 : -1;
      }
      document.querySelectorAll("th[data-col]").forEach((item) => item.classList.remove("sorted"));
      th.classList.add("sorted");
      page = 1;
      renderRanking();
    });
  });

  document.getElementById("export-btn").addEventListener("click", exportWatchlist);
  document.getElementById("modal-close").addEventListener("click", closeHistory);
  document.getElementById("history-modal").addEventListener("click", (event) => {
    if (event.target.id === "history-modal") closeHistory();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeHistory();
  });
}

function bindSegmented(id, dataAttr, callback) {
  const root = document.getElementById(id);
  root.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      root.querySelectorAll("button").forEach((btn) => btn.classList.remove("active"));
      button.classList.add("active");
      callback(button.dataset[dataAttr]);
    });
  });
}

function exportWatchlist() {
  const list = getFilteredStocks().filter((stock) => stock.rs >= Math.max(rsFilter, 70));
  if (!list.length) {
    alert("目前篩選條件下沒有可匯出的 RS≥70 股票。");
    return;
  }
  const grouped = new Map();
  list.forEach((stock) => {
    const key = `${stock.market_name} / ${stock.sector}`;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(stock);
  });

  const content = [...grouped.entries()]
    .map(([group, items]) => {
      const lines = items
        .sort((a, b) => b.rs - a.rs)
        .map((stock) => `${stock.tv_symbol || stock.code} # ${stock.market_name} ${stock.code} ${stock.name} RS ${stock.rs}`)
        .join("\n");
      return `### ${group}\n${lines}`;
    })
    .join("\n\n");

  const date = new Date().toISOString().slice(0, 10);
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `tw_us_rs_watchlist_${date}.txt`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function openHistory(stock) {
  const key = stockHistoryKey(stock);
  const entries = historyData[key] || [];
  if (entries.length < 2) return;
  const modal = document.getElementById("history-modal");
  const canvas = document.getElementById("history-chart");
  const empty = document.getElementById("history-empty");

  document.getElementById("modal-title").textContent = `${stock.market_name} ${stock.code} ${stock.name}`;
  document.getElementById("modal-subtitle").textContent = entries.length
    ? `近 ${entries.length} 筆市場內 RS 紀錄`
    : "第一次跑完每日更新後會開始累積歷史。";

  if (historyChart) {
    historyChart.destroy();
    historyChart = null;
  }

  if (entries.length < 2 || typeof Chart === "undefined") {
    canvas.style.display = "none";
    empty.style.display = "grid";
  } else {
    canvas.style.display = "block";
    empty.style.display = "none";
    historyChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: entries.map((item) => item.date.slice(5)),
        datasets: [
          {
            label: "RS",
            data: entries.map((item) => item.rs),
            borderColor: "#2dd4bf",
            backgroundColor: "rgba(45, 212, 191, .12)",
            borderWidth: 2,
            pointRadius: entries.length > 80 ? 0 : 2,
            fill: true,
            tension: 0.25,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#8f9aa7", maxTicksLimit: 10 }, grid: { color: "#24272f" } },
          y: { min: 0, max: 99, ticks: { color: "#8f9aa7" }, grid: { color: "#24272f" } },
        },
      },
    });
  }

  modal.classList.add("open");
}

function closeHistory() {
  document.getElementById("history-modal").classList.remove("open");
}

async function init() {
  await loadData();
  populateSectorSelect();
  bindEvents();
  renderAll();
}

init();
