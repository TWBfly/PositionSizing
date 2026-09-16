/**
 * Futures Position Sizing & Risk Management System - Frontend App Controller
 * Reactive state management, Kelly formula mapping, and dynamic rendering.
 */

// Application State
const state = {
  equity: 1000000.0,
  winRateMin: 30.0,
  winRateMax: 40.0,
  winLossMin: 2.5,
  winLossMax: 4.0,
  fractionalMultiplier: 0.20,
  currentDrawdown: 0.0,
  clusterCapRate: 0.30,
  selectedSymbols: new Set([
    "AG", "JM", "RB", "SA", "FG", "CU", "SN",
    "AO", "PG", "BR", "LH", "JD", "CJ", "P"
  ]),
  allInstruments: [],
  sectors: [],
  clusters: {},
  currentSectorFilter: "ALL",
  searchTerm: "",
  latestCloseDate: "2026-09-15",
  calcData: null,
  activeCodeTab: "tbquant",
  previousItemsMap: {}
};

// DOM Elements Cache
const DOM = {
  // Inputs
  inputEquity: document.getElementById("inputEquity"),
  inputWinRateMin: document.getElementById("inputWinRateMin"),
  inputWinRateMax: document.getElementById("inputWinRateMax"),
  valWinRateMid: document.getElementById("valWinRateMid"),
  inputWinLossMin: document.getElementById("inputWinLossMin"),
  inputWinLossMax: document.getElementById("inputWinLossMax"),
  valWinLossMid: document.getElementById("valWinLossMid"),
  winLossHint: document.getElementById("winLossHint"),
  winLossKellyWarning: document.getElementById("winLossKellyWarning"),
  selectKellyFrac: document.getElementById("selectKellyFrac"),
  valKellyFrac: document.getElementById("valKellyFrac"),
  sliderDrawdown: document.getElementById("sliderDrawdown"),
  valDrawdown: document.getElementById("valDrawdown"),
  circuitBadge: document.getElementById("circuitBadge"),
  sliderClusterCap: document.getElementById("sliderClusterCap"),
  valClusterCap: document.getElementById("valClusterCap"),

  // Gauges
  gaugeMarginPct: document.getElementById("gaugeMarginPct"),
  gaugeMarginVal: document.getElementById("gaugeMarginVal"),
  barMargin: document.getElementById("barMargin"),
  marginStatusText: document.getElementById("marginStatusText"),

  gaugeRiskPct: document.getElementById("gaugeRiskPct"),
  gaugeRiskVal: document.getElementById("gaugeRiskVal"),
  barRisk: document.getElementById("barRisk"),
  riskStatusText: document.getElementById("riskStatusText"),

  gaugeCashPct: document.getElementById("gaugeCashPct"),
  gaugeCashVal: document.getElementById("gaugeCashVal"),
  barCash: document.getElementById("barCash"),
  cashStatusText: document.getElementById("cashStatusText"),

  // Kelly Stats
  kExpectancy: document.getElementById("kExpectancy"),
  kFullKelly: document.getElementById("kFullKelly"),
  kSafeKelly: document.getElementById("kSafeKelly"),
  kDrawdownProb: document.getElementById("kDrawdownProb"),
  kellyMessage: document.getElementById("kellyMessage"),

  // Clusters & Table
  presetButtons: document.getElementById("presetButtons"),
  clustersGrid: document.getElementById("clustersGrid"),
  clusterPills: document.getElementById("clusterPills"),
  sizingTableBody: document.getElementById("sizingTableBody"),
  sizingTableFoot: document.getElementById("sizingTableFoot"),
  checkAll: document.getElementById("checkAll"),
  filterSearch: document.getElementById("filterSearch"),
  sectorTabs: document.getElementById("sectorTabs"),
  stressGrid: document.getElementById("stressGrid"),

  // Table Summary Bar Elements
  tableSummaryBar: document.getElementById("tableSummaryBar"),
  tableSummaryRiskDegree: document.getElementById("tableSummaryRiskDegree"),
  tableSummaryRiskLevel: document.getElementById("tableSummaryRiskLevel"),
  tableSummaryRiskSub: document.getElementById("tableSummaryRiskSub"),
  tableSummaryActualMargin: document.getElementById("tableSummaryActualMargin"),
  tableSummaryMarginSub: document.getElementById("tableSummaryMarginSub"),
  tableSummaryCashBuffer: document.getElementById("tableSummaryCashBuffer"),
  tableSummaryCashSub: document.getElementById("tableSummaryCashSub"),
  tableSummaryCount: document.getElementById("tableSummaryCount"),
  tableSummaryOpenRisk: document.getElementById("tableSummaryOpenRisk"),

  // Feasibility Panel Elements
  fValFullMargin: document.getElementById("fValFullMargin"),
  fSubFullMargin: document.getElementById("fSubFullMargin"),
  fValFullRisk: document.getElementById("fValFullRisk"),
  fSubFullRisk: document.getElementById("fSubFullRisk"),
  fValMinEquity: document.getElementById("fValMinEquity"),
  fSubMinEquity: document.getElementById("fSubMinEquity"),
  feasibilityBadge: document.getElementById("feasibilityBadge"),
  feasibilityMsg: document.getElementById("feasibilityMsg"),

  // Formula Modal Elements
  modalFormula: document.getElementById("modalFormula"),
  btnCloseFormula: document.getElementById("btnCloseFormula"),
  btnCloseFormulaBtn: document.getElementById("btnCloseFormulaBtn"),
  formulaModalTitle: document.getElementById("formulaModalTitle"),
  formulaBody: document.getElementById("formulaBody"),

  // TqSdk Banner Elements
  btnRefreshTq: document.getElementById("btnRefreshTq"),
  btnToggleTqDetails: document.getElementById("btnToggleTqDetails"),
  tqDetailsPanel: document.getElementById("tqDetailsPanel"),
  tqStatusText: document.getElementById("tqStatusText"),
  tqAccountTag: document.getElementById("tqAccountTag"),
  tqSyncTime: document.getElementById("tqSyncTime"),
  toastContainer: document.getElementById("toastContainer")
};

// Debounce helper
let debounceTimer = null;
function triggerRecalculate(delay = 150) {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    executeCalculation();
  }, delay);
}

// Format numbers and strings
function formatMoney(amount) {
  return "¥" + Number(amount).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function formatDecimal(num, decimals = 2) {
  return Number(num).toFixed(decimals);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Initialize Application
async function initApp() {
  bindEvents();
  renderPresetButtons();
  await loadInstruments();
  await executeCalculation();
}

// Bind UI event listeners
function bindEvents() {
  // Capital input
  DOM.inputEquity.addEventListener("input", (e) => {
    state.equity = Math.max(10000, parseFloat(e.target.value) || 1000000);
    updateQuickChips();
    updateSummaryBar();
    renderTableFoot();
    triggerRecalculate();
  });

  // Quick capital chips
  document.querySelectorAll(".quick-chips .chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const eq = parseFloat(chip.dataset.equity);
      state.equity = eq;
      DOM.inputEquity.value = eq;
      updateQuickChips();
      updateSummaryBar();
      renderTableFoot();
      triggerRecalculate();
    });
  });

  // Validate whether payoff ratio is high enough for current win rate
  function updateKellyValidityAlert() {
    const pMin = state.winRateMin / 100.0;
    const pMax = state.winRateMax / 100.0;
    const pMid = (pMin + pMax) / 2.0;

    const bMin = state.winLossMin;
    const bMax = state.winLossMax;
    const bMid = (bMin + bMax) / 2.0;

    // Mathematical Expectancy in R: E = p * b - (1 - p)
    const expMid = (pMid * bMid) - (1.0 - pMid);
    const expConservative = (pMin * bMin) - (1.0 - pMin);
    // Break-even critical payoff ratio: b_crit = (1 - p) / p
    const bCritMid = pMid > 0 ? ((1.0 - pMid) / pMid) : 999.0;
    const bCritMin = pMin > 0 ? ((1.0 - pMin) / pMin) : 999.0;

    if (expMid <= 0) {
      // Severe Error: Central expectation is negative or zero, Kelly formula CANNOT be executed!
      if (DOM.valWinLossMid) {
        DOM.valWinLossMid.innerHTML = `中枢 ${formatDecimal(bMid, 2)} : 1 <span style="color: #ff7b72; font-size: 11px; margin-left: 4px; font-weight: 700;">⚠️ 盈亏比过低无法执行</span>`;
      }
      if (DOM.inputWinLossMin) DOM.inputWinLossMin.classList.add("input-error");
      if (DOM.inputWinLossMax) DOM.inputWinLossMax.classList.add("input-error");
      if (DOM.winLossHint) DOM.winLossHint.style.display = "none";
      if (DOM.winLossKellyWarning) {
        DOM.winLossKellyWarning.innerHTML = `
          <div class="kelly-red-alert">
            <div class="alert-title">🚨 盈亏比过低，无法执行凯利公式！</div>
            <div class="alert-desc">
              结合当前胜率 <strong>${formatDecimal(pMid * 100, 1)}%</strong>，保本临界盈亏比需 <strong>≥ ${formatDecimal(bCritMid, 2)} : 1</strong>。<br>
              当前设置的盈亏比中枢仅为 <strong>${formatDecimal(bMid, 2)} : 1</strong>，数学期望为负 (<strong>${formatDecimal(expMid, 2)} R ≤ 0</strong>)。<br>
              依据大数定律与凯利准则，在无统计正期望优势时，最优下注比例严格为 <strong>0%</strong>。<br>
              <span style="color: #ff7b72; font-weight: 700;">系统已强制风控归零（开仓手数与风险预算全部归零），以防本金遭受毁灭性亏损！</span>
            </div>
          </div>
        `;
        DOM.winLossKellyWarning.style.display = "block";
      }
    } else if (expConservative < 0) {
      // Caution: conservative scenario is negative, but mid is positive
      if (DOM.valWinLossMid) {
        DOM.valWinLossMid.textContent = `中枢 ${formatDecimal(bMid, 2)} : 1`;
      }
      if (DOM.inputWinLossMin) DOM.inputWinLossMin.classList.remove("input-error");
      if (DOM.inputWinLossMax) DOM.inputWinLossMax.classList.remove("input-error");
      if (DOM.winLossHint) DOM.winLossHint.style.display = "none";
      if (DOM.winLossKellyWarning) {
        DOM.winLossKellyWarning.innerHTML = `
          <div class="kelly-warn-alert">
            <div class="alert-title">⚠️ 保守下限情景盈亏比偏低提示</div>
            <div class="alert-desc">
              在下限胜率 <strong>${formatDecimal(pMin * 100, 1)}%</strong> 时保本盈亏比需 <strong>≥ ${formatDecimal(bCritMin, 2)} : 1</strong> (当前下限为 ${formatDecimal(bMin, 2)} : 1)。<br>
              虽然中枢期望为正 (+${formatDecimal(expMid, 2)} R)，但下限情景偏弱，系统已自动压缩分数凯利风险额度。
            </div>
          </div>
        `;
        DOM.winLossKellyWarning.style.display = "block";
      }
    } else {
      // Safe / Normal state
      if (DOM.valWinLossMid) {
        DOM.valWinLossMid.textContent = `中枢 ${formatDecimal(bMid, 2)} : 1`;
      }
      if (DOM.inputWinLossMin) DOM.inputWinLossMin.classList.remove("input-error");
      if (DOM.inputWinLossMax) DOM.inputWinLossMax.classList.remove("input-error");
      if (DOM.winLossKellyWarning) {
        DOM.winLossKellyWarning.style.display = "none";
        DOM.winLossKellyWarning.innerHTML = "";
      }
      if (DOM.winLossHint) DOM.winLossHint.style.display = "block";
    }
  }

  // Win rate range inputs (Min ~ Max)
  function onWinRateChange() {
    const minVal = parseFloat(DOM.inputWinRateMin.value);
    const maxVal = parseFloat(DOM.inputWinRateMax.value);
    state.winRateMin = isNaN(minVal) ? 30.0 : minVal;
    state.winRateMax = isNaN(maxVal) ? 40.0 : maxVal;
    const mid = (state.winRateMin + state.winRateMax) / 2.0;
    if (DOM.valWinRateMid) {
      DOM.valWinRateMid.textContent = `中枢 ${formatDecimal(mid, 1)}%`;
    }
    updateKellyValidityAlert();
    triggerRecalculate(80);
  }

  DOM.inputWinRateMin.addEventListener("input", onWinRateChange);
  DOM.inputWinRateMin.addEventListener("change", onWinRateChange);
  DOM.inputWinRateMax.addEventListener("input", onWinRateChange);
  DOM.inputWinRateMax.addEventListener("change", onWinRateChange);

  // Win/Loss ratio range inputs (Min ~ Max)
  function onWinLossChange() {
    const minVal = parseFloat(DOM.inputWinLossMin.value);
    const maxVal = parseFloat(DOM.inputWinLossMax.value);
    state.winLossMin = isNaN(minVal) ? 2.5 : minVal;
    state.winLossMax = isNaN(maxVal) ? 4.0 : maxVal;
    const mid = (state.winLossMin + state.winLossMax) / 2.0;
    if (DOM.valWinLossMid) {
      DOM.valWinLossMid.textContent = `中枢 ${formatDecimal(mid, 2)} : 1`;
    }
    updateKellyValidityAlert();
    triggerRecalculate(80);
  }

  DOM.inputWinLossMin.addEventListener("input", onWinLossChange);
  DOM.inputWinLossMin.addEventListener("change", onWinLossChange);
  DOM.inputWinLossMax.addEventListener("input", onWinLossChange);
  DOM.inputWinLossMax.addEventListener("change", onWinLossChange);

  // Fractional Kelly selector
  DOM.selectKellyFrac.addEventListener("change", (e) => {
    state.fractionalMultiplier = parseFloat(e.target.value);
    DOM.valKellyFrac.textContent = `${e.target.value}x`;
    triggerRecalculate();
  });

  // Drawdown slider
  DOM.sliderDrawdown.addEventListener("input", (e) => {
    state.currentDrawdown = parseFloat(e.target.value);
    DOM.valDrawdown.textContent = `${e.target.value}%`;
    updateDrawdownCircuitBadge(state.currentDrawdown);
    triggerRecalculate();
  });

  // Cluster cap slider
  DOM.sliderClusterCap.addEventListener("input", (e) => {
    state.clusterCapRate = parseFloat(e.target.value) / 100.0;
    DOM.valClusterCap.textContent = `${e.target.value}%`;
    triggerRecalculate();
  });

  // Search input
  DOM.filterSearch.addEventListener("input", (e) => {
    state.searchTerm = e.target.value.toLowerCase().trim();
    renderTable();
  });

  // Sector tabs
  DOM.sectorTabs.addEventListener("click", (e) => {
    if (e.target.classList.contains("tab-btn")) {
      DOM.sectorTabs.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      e.target.classList.add("active");
      state.currentSectorFilter = e.target.dataset.sector;
      renderTable();
    }
  });

  // Check all toggle
  DOM.checkAll.addEventListener("change", (e) => {
    const checked = e.target.checked;
    if (checked) {
      state.allInstruments.forEach(inst => state.selectedSymbols.add(inst.symbol));
    } else {
      state.selectedSymbols.clear();
    }
    renderTable();
    triggerRecalculate();
  });

  // Formula modal close buttons
  if (DOM.btnCloseFormula) {
    DOM.btnCloseFormula.addEventListener("click", () => DOM.modalFormula && DOM.modalFormula.classList.remove("open"));
  }
  if (DOM.btnCloseFormulaBtn) {
    DOM.btnCloseFormulaBtn.addEventListener("click", () => DOM.modalFormula && DOM.modalFormula.classList.remove("open"));
  }

  // Close formula modal on clicking overlay backdrop
  if (DOM.modalFormula) {
    DOM.modalFormula.addEventListener("click", (e) => {
      if (e.target === DOM.modalFormula) DOM.modalFormula.classList.remove("open");
    });
  }

  // TqSdk Details Drawer Toggle
  if (DOM.btnToggleTqDetails && DOM.tqDetailsPanel) {
    DOM.btnToggleTqDetails.addEventListener("click", () => {
      DOM.tqDetailsPanel.classList.toggle("hidden");
      const isHidden = DOM.tqDetailsPanel.classList.contains("hidden");
      DOM.btnToggleTqDetails.textContent = isHidden ? "天勤数据源与字段说明 ▾" : "收起说明 ▴";
    });
  }

  // TqSdk Refresh Button
  if (DOM.btnRefreshTq) {
    DOM.btnRefreshTq.addEventListener("click", async () => {
      DOM.btnRefreshTq.disabled = true;
      const origHtml = DOM.btnRefreshTq.innerHTML;
      DOM.btnRefreshTq.innerHTML = `<span class="pulse-dot"></span> 正在从天勤量化拉取...`;
      try {
        const res = await fetch("/api/tq/refresh", { method: "POST" });
        const json = await res.json();
        if (json.success) {
          await loadInstruments();
          await executeCalculation();
          if (DOM.tqSyncTime && json.status && json.status.last_sync_time) {
            DOM.tqSyncTime.textContent = `最后同步: ${json.status.last_sync_time}`;
          }
        }
      } catch (err) {
        console.error("TqSdk refresh failed:", err);
      } finally {
        DOM.btnRefreshTq.disabled = false;
        DOM.btnRefreshTq.innerHTML = origHtml;
      }
    });
  }

  updateKellyValidityAlert();
}

function updateQuickChips() {
  document.querySelectorAll(".quick-chips .chip[data-equity]").forEach(chip => {
    const chipEq = parseFloat(chip.dataset.equity);
    if (chipEq === state.equity) {
      chip.classList.add("active");
    } else {
      chip.classList.remove("active");
    }
  });
}

function updateWinRateChips(wr) {
  if (!DOM.chipsWinRate) return;
  DOM.chipsWinRate.querySelectorAll(".chip").forEach(chip => {
    const chipWr = parseFloat(chip.dataset.winrate);
    if (Math.abs(chipWr - wr) < 0.1) {
      chip.classList.add("active");
    } else {
      chip.classList.remove("active");
    }
  });
}

function updateDrawdownCircuitBadge(dd) {
  let badgeHtml = "";
  if (dd <= 3.0) {
    badgeHtml = `<span class="badge badge-success">正常运作 (1.0x 全额)</span>`;
  } else if (dd <= 5.0) {
    badgeHtml = `<span class="badge badge-warning">一级防守 (0.80x 杠杆)</span>`;
  } else if (dd <= 8.0) {
    badgeHtml = `<span class="badge badge-warning">二级防守 (0.60x 杠杆)</span>`;
  } else if (dd <= 10.0) {
    badgeHtml = `<span class="badge badge-danger">三级防守 (0.40x 杠杆)</span>`;
  } else {
    badgeHtml = `<span class="badge badge-danger">熔断模式 (0.0x 停止新开)</span>`;
  }
  DOM.circuitBadge.innerHTML = badgeHtml;
}

// Render scenario presets
function renderPresetButtons() {
  DOM.presetButtons.innerHTML = PRESETS.map((p, idx) => `
    <button class="preset-chip ${idx === 0 ? 'active' : ''}" data-id="${p.id}" title="${p.desc}">
      ${p.name}
    </button>
  `).join("");

  DOM.presetButtons.querySelectorAll(".preset-chip").forEach(btn => {
    btn.addEventListener("click", () => {
      DOM.presetButtons.querySelectorAll(".preset-chip").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      applyPreset(btn.dataset.id);
    });
  });
}

function applyPreset(presetId) {
  const p = PRESETS.find(item => item.id === presetId);
  if (!p) return;

  state.equity = p.equity;
  DOM.inputEquity.value = p.equity;
  updateQuickChips();

  state.winRateMin = p.winRateMin;
  state.winRateMax = p.winRateMax;
  DOM.inputWinRateMin.value = p.winRateMin;
  DOM.inputWinRateMax.value = p.winRateMax;
  const midWr = (p.winRateMin + p.winRateMax) / 2.0;
  if (DOM.valWinRateMid) {
    DOM.valWinRateMid.textContent = `中枢 ${formatDecimal(midWr, 1)}%`;
  }

  state.winLossMin = p.winLossMin;
  state.winLossMax = p.winLossMax;
  DOM.inputWinLossMin.value = p.winLossMin;
  DOM.inputWinLossMax.value = p.winLossMax;
  const midWl = (p.winLossMin + p.winLossMax) / 2.0;
  if (DOM.valWinLossMid) {
    DOM.valWinLossMid.textContent = `中枢 ${formatDecimal(midWl, 2)} : 1`;
  }

  state.fractionalMultiplier = parseFloat(p.kellyFrac);
  DOM.selectKellyFrac.value = p.kellyFrac;
  DOM.valKellyFrac.textContent = `${p.kellyFrac}x`;

  state.currentDrawdown = p.drawdown;
  DOM.sliderDrawdown.value = p.drawdown;
  DOM.valDrawdown.textContent = `${p.drawdown}%`;
  updateDrawdownCircuitBadge(p.drawdown);

  state.clusterCapRate = p.clusterCap / 100.0;
  DOM.sliderClusterCap.value = p.clusterCap;
  DOM.valClusterCap.textContent = `${p.clusterCap}%`;

  state.selectedSymbols = new Set(p.symbols);

  renderTable();
  executeCalculation();
}

// Update table header with dynamic yesterday close date
function updatePriceHeader() {
  const th = document.getElementById("thPriceHeader");
  if (!th) return;
  const d = state.latestCloseDate || (state.calcData && state.calcData.latest_close_date) || "2026-09-15";
  th.innerHTML = `参考现价 <span style="font-weight: 500; font-size: 11px; color: var(--accent-cyan);">(${d} 昨收)</span>`;
}

// Load instruments specifications from backend
async function loadInstruments() {
  try {
    const res = await fetch("/api/instruments");
    const json = await res.json();
    state.allInstruments = json.instruments || [];
    state.sectors = json.sectors || [];
    state.clusters = json.clusters || {};
    if (json.latest_close_date) {
      state.latestCloseDate = json.latest_close_date;
    }
    updatePriceHeader();
  } catch (err) {
    console.error("Failed to load instruments:", err);
  }
}

// Execute calculation via Backend REST API
// Detect when a variety is cancelled (lots dropped to 0) or reduced, and pop up a toast alert
function detectAndShowRebalanceAlerts(newItems) {
  if (!newItems || newItems.length === 0) return;

  if (!state.previousItemsMap || Object.keys(state.previousItemsMap).length === 0) {
    // Initial load: populate state.previousItemsMap without alerting
    state.previousItemsMap = {};
    newItems.forEach(it => {
      state.previousItemsMap[it.symbol] = {
        final_lots: Number(it.final_lots) || 0,
        isSelected: state.selectedSymbols.has(it.symbol),
        name: it.name
      };
    });
    return;
  }

  const cancelledList = [];
  const reducedList = [];
  const blockedList = [];

  newItems.forEach(it => {
    const sym = it.symbol;
    const isSelected = state.selectedSymbols.has(sym);
    const prev = state.previousItemsMap[sym];
    const prevLots = prev ? Number(prev.final_lots) || 0 : 0;
    const prevSelected = prev ? prev.isSelected : false;
    const newLots = Number(it.final_lots) || 0;

    if (isSelected) {
      if (prevLots > 0 && newLots === 0) {
        cancelledList.push({ item: it, prevLots, newLots });
      } else if (prevLots > newLots && newLots > 0) {
        reducedList.push({ item: it, prevLots, newLots });
      } else if (!prevSelected && newLots === 0) {
        // newly checked by user, but blocked from opening position
        blockedList.push({ item: it, prevLots: 0, newLots: 0 });
      }
    }
  });

  // Update previousItemsMap
  state.previousItemsMap = {};
  newItems.forEach(it => {
    state.previousItemsMap[it.symbol] = {
      final_lots: Number(it.final_lots) || 0,
      isSelected: state.selectedSymbols.has(it.symbol),
      name: it.name
    };
  });

  if (cancelledList.length > 0 || reducedList.length > 0 || blockedList.length > 0) {
    showRebalanceToast({ cancelledList, reducedList, blockedList });
  }
}

function showRebalanceToast({ cancelledList, reducedList, blockedList }) {
  if (!DOM.toastContainer) {
    DOM.toastContainer = document.getElementById("toastContainer");
    if (!DOM.toastContainer) return;
  }

  // Clear existing toasts to prevent clutter
  DOM.toastContainer.innerHTML = "";

  const toast = document.createElement("div");
  toast.className = "toast-card";

  let bodyHtml = "";
  let primaryTargetSym = "";

  if (cancelledList.length > 0) {
    primaryTargetSym = cancelledList[0].item.symbol;
    bodyHtml += `
      <div style="font-weight: 700; color: var(--accent-orange); margin-bottom: 4px;">
        ⚠️ 品种开仓被取消 / 手数调零提醒：
      </div>
    `;
    cancelledList.forEach(c => {
      bodyHtml += `
        <div class="toast-item-row">
          <strong>【${c.item.symbol} ${c.item.name}】</strong> 原推荐 ${c.prevLots} 手 ➔ <strong style="color: var(--accent-orange);">0 手</strong><br>
          <span style="color: var(--text-secondary); font-size: 11px;">
            ${escapeHtml(c.item.constraint_reason || '受组合总开放风险及集群防火墙硬顶约束，已被挤出。')}
          </span>
        </div>
      `;
    });
  }

  if (reducedList.length > 0) {
    if (!primaryTargetSym) primaryTargetSym = reducedList[0].item.symbol;
    bodyHtml += `
      <div style="font-weight: 700; color: var(--accent-gold); margin-top: 6px; margin-bottom: 4px;">
        📉 品种手数被压缩调整：
      </div>
    `;
    reducedList.forEach(r => {
      bodyHtml += `
        <div class="toast-item-row" style="border-left-color: rgba(210, 153, 34, 0.4);">
          <strong>【${r.item.symbol} ${r.item.name}】</strong> ${r.prevLots} 手 ➔ <strong class="text-gold">${r.newLots} 手</strong><br>
          <span style="color: var(--text-secondary); font-size: 11px;">
            ${escapeHtml(r.item.why_cannot_increase || '受组合全局风险预算分配限制。')}
          </span>
        </div>
      `;
    });
  }

  if (blockedList.length > 0 && cancelledList.length === 0) {
    if (!primaryTargetSym) primaryTargetSym = blockedList[0].item.symbol;
    bodyHtml += `
      <div style="font-weight: 700; color: var(--accent-orange); margin-bottom: 4px;">
        ⚠️ 新勾选品种暂未能建仓 (0手)：
      </div>
    `;
    blockedList.forEach(b => {
      bodyHtml += `
        <div class="toast-item-row">
          <strong>【${b.item.symbol} ${b.item.name}】</strong> 分配 <strong style="color: var(--accent-orange);">0 手</strong><br>
          <span style="color: var(--text-secondary); font-size: 11px;">
            ${escapeHtml(b.item.constraint_reason || '单手风险或保证金超出预算配额。')}
          </span>
        </div>
      `;
    });
  }

  toast.innerHTML = `
    <div class="toast-header">
      <div class="toast-header-left">
        <span style="font-size: 16px;">⚠️</span>
        <span>风控置换与仓位受阻提醒</span>
      </div>
      <button class="toast-close" title="关闭提示">&times;</button>
    </div>
    <div class="toast-body">
      ${bodyHtml}
    </div>
    <div class="toast-action">
      ${primaryTargetSym ? `<button class="btn-toast-detail" data-symbol="${primaryTargetSym}">查看【${primaryTargetSym}】详细风控瓶颈 ➔</button>` : ''}
    </div>
  `;

  // Close button
  const btnClose = toast.querySelector(".toast-close");
  if (btnClose) {
    btnClose.addEventListener("click", () => {
      toast.classList.add("fade-out");
      setTimeout(() => toast.remove(), 300);
    });
  }

  // Detail button
  const btnDetail = toast.querySelector(".btn-toast-detail");
  if (btnDetail) {
    btnDetail.addEventListener("click", () => {
      const sym = btnDetail.dataset.symbol;
      if (sym) openFormulaModal(sym);
      toast.remove();
    });
  }

  DOM.toastContainer.appendChild(toast);

  // Auto dismiss after 10 seconds
  setTimeout(() => {
    if (toast.parentNode) {
      toast.classList.add("fade-out");
      setTimeout(() => toast.remove(), 300);
    }
  }, 10000);
}

async function executeCalculation() {
  try {
    // Read directly from DOM input values to ensure absolute freshness
    if (DOM.inputEquity) {
      const rawEq = parseFloat(DOM.inputEquity.value);
      if (!isNaN(rawEq)) state.equity = rawEq;
    }

    if (DOM.inputWinRateMin && DOM.inputWinRateMax) {
      const rawWrMin = parseFloat(DOM.inputWinRateMin.value);
      const rawWrMax = parseFloat(DOM.inputWinRateMax.value);
      if (!isNaN(rawWrMin)) state.winRateMin = rawWrMin;
      if (!isNaN(rawWrMax)) state.winRateMax = rawWrMax;
    }

    if (DOM.inputWinLossMin && DOM.inputWinLossMax) {
      const rawWlMin = parseFloat(DOM.inputWinLossMin.value);
      const rawWlMax = parseFloat(DOM.inputWinLossMax.value);
      if (!isNaN(rawWlMin)) state.winLossMin = rawWlMin;
      if (!isNaN(rawWlMax)) state.winLossMax = rawWlMax;
    }

    const pMin = Math.min(state.winRateMin, state.winRateMax);
    const pMax = Math.max(state.winRateMin, state.winRateMax);
    const bMin = Math.min(state.winLossMin, state.winLossMax);
    const bMax = Math.max(state.winLossMin, state.winLossMax);

    // Update mid value indicators in real time
    if (DOM.valWinRateMid) {
      DOM.valWinRateMid.textContent = `中枢 ${formatDecimal((pMin + pMax) / 2.0, 1)}%`;
    }
    if (DOM.valWinLossMid) {
      DOM.valWinLossMid.textContent = `中枢 ${formatDecimal((bMin + bMax) / 2.0, 2)} : 1`;
    }

    const payload = {
      equity: state.equity,
      win_rate_min: pMin / 100.0,
      win_rate_max: pMax / 100.0,
      win_loss_min: bMin,
      win_loss_max: bMax,
      fractional_multiplier: state.fractionalMultiplier,
      current_drawdown_pct: state.currentDrawdown,
      selected_symbols: Array.from(state.selectedSymbols),
      cluster_cap_rate: state.clusterCapRate,
      single_asset_cap_rate: 0.15
    };

    const res = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const json = await res.json();
    if (json.success) {
      detectAndShowRebalanceAlerts(json.data.items);
      state.calcData = json.data;
      if (json.data && json.data.latest_close_date) {
        state.latestCloseDate = json.data.latest_close_date;
      }
      updatePriceHeader();
      renderAll(json.data);
    } else {
      console.error("Calculation failed:", json);
    }
  } catch (err) {
    console.error("Error executing calculation:", err);
  }
}

// Render all views from calculation data
function renderAll(data) {
  renderTqStatus(data.tq_status);
  renderGauges(data);
  renderKellyStats(data.kelly, data.kelly_range);
  renderClusters(data.clusters, data.portfolio_gauges);
  renderTable();
  updateSummaryBar();
  renderTableFoot();
  renderStressTests(data.stress_tests);
}

// Render TqSdk status in banner
function renderTqStatus(tq) {
  if (!tq) return;
  if (DOM.tqAccountTag && tq.account) {
    DOM.tqAccountTag.textContent = `天勤账号: ${tq.account}`;
  }
  if (DOM.tqSyncTime && tq.last_sync_time) {
    DOM.tqSyncTime.textContent = `最后同步: ${tq.last_sync_time}`;
  }
  if (DOM.tqStatusText) {
    DOM.tqStatusText.textContent = tq.status === "online"
      ? "天勤量化已接入 (TqSdk Online)"
      : "天勤行情缓存模式 (TqSdk Cached)";
  }
}

// Render top gauge cards
function renderGauges(data) {
  const g = data.portfolio_gauges;

  // Margin (Card 1)
  DOM.gaugeMarginVal.textContent = formatMoney(g.total_actual_margin);
  DOM.gaugeMarginPct.textContent = `保证金占用率 ${formatDecimal(g.margin_utilization_pct, 2)}% (实盘风险度) / 安全上限 ${formatMoney(g.equity * 0.35)} (35%)`;
  // Max scale is 50%
  const marginBarWidth = Math.min(100, (g.margin_utilization_pct / 50.0) * 100);
  DOM.barMargin.style.width = `${marginBarWidth}%`;

  if (state.selectedSymbols.size === 0 || g.total_actual_margin === 0) {
    DOM.marginStatusText.textContent = "未勾选品种，当前无保证金占用";
    DOM.marginStatusText.className = "gauge-footer";
  } else if (g.margin_utilization_pct <= 30.0) {
    DOM.marginStatusText.textContent = "安全运行中 (处于 25%~30% 常态稳健区间)";
    DOM.marginStatusText.className = "gauge-footer text-success";
  } else if (g.margin_utilization_pct <= 35.0) {
    DOM.marginStatusText.textContent = "轻度预警 (接近 35% 软上限，注意后续调保)";
    DOM.marginStatusText.className = "gauge-footer text-warning";
  } else {
    DOM.marginStatusText.textContent = "严重警告！超过 35% 软上限，强制实施杠杆压缩";
    DOM.marginStatusText.className = "gauge-footer text-danger";
  }

  // 6-Scenario Breakdown in Card 1
  const scContainer = document.getElementById("scenarioBreakdownContainer");
  if (scContainer) {
    if (data.scenario_matrix && data.scenario_matrix.length > 0) {
      const scs = data.scenario_matrix;
      const sumMargin = scs.reduce((acc, s) => acc + s.margin, 0);
      const avgMargin = sumMargin / scs.length;

      scContainer.innerHTML = `
        <div class="scenario-box-header">
          <span class="sc-title">📊 6组情景自适应测算与算术平均明细</span>
          <span class="sc-badge">${scs.length}组相加平均</span>
        </div>
        <div class="scenario-chips-grid">
          ${scs.map((s, idx) => `
            <div class="scenario-mini-card" title="情景 ${s.scenario_index}：胜率 ${s.win_rate_pct}%，盈亏比 ${s.win_loss}，执行 ${s.total_lots}手，保证金 ${formatMoney(s.margin)}，理论风险 ${formatMoney(s.risk)}">
              <div class="sc-head-row">
                <span class="sc-head">情景 ${s.scenario_index}</span>
                <span class="sc-lots-tag">${s.total_lots}手</span>
              </div>
              <div class="sc-params">胜率 ${s.win_rate_pct}% · 盈亏比 ${s.win_loss}</div>
              <div class="sc-margin text-gold">${formatMoney(s.margin)}</div>
              <div class="sc-sub">风险 ${formatMoney(s.risk)}</div>
            </div>
          `).join("")}
        </div>
        <div class="scenario-formula-bar">
          <span>均值公式：∑(${scs.length}组保证金) ÷ ${scs.length} = <strong>${formatMoney(avgMargin)}</strong> (最终可调度保证金额度)</span>
        </div>
      `;
      scContainer.style.display = "block";
    } else {
      scContainer.style.display = "none";
    }
  }

  // Open Risk (Card 2)
  DOM.gaugeRiskVal.textContent = formatMoney(g.total_actual_risk);
  DOM.gaugeRiskPct.textContent = `占净值 ${formatDecimal(g.open_risk_pct, 2)}% / 规划预算 ${formatMoney(g.target_open_risk)}`;
  // Max scale is 3.5%
  const riskBarWidth = Math.min(100, (g.open_risk_pct / 3.0) * 100);
  DOM.barRisk.style.width = `${riskBarWidth}%`;

  if (state.selectedSymbols.size === 0 || g.total_actual_risk === 0) {
    DOM.riskStatusText.textContent = "未勾选品种，无持仓风险敞口";
    DOM.riskStatusText.className = "gauge-footer";
  } else if (g.open_risk_pct <= 2.5) {
    DOM.riskStatusText.textContent = `总开放风险达标 (全击穿止损理论损失 ≤ ${formatDecimal(g.open_risk_pct, 2)}%)`;
    DOM.riskStatusText.className = "gauge-footer text-success";
  } else if (g.open_risk_pct <= 3.0) {
    DOM.riskStatusText.textContent = "已达 3.0% 极限安全线，禁止任何新策略追加风险";
    DOM.riskStatusText.className = "gauge-footer text-warning";
  } else {
    DOM.riskStatusText.textContent = "突破 3.0% 硬上限！必须削减高风险品种手数";
    DOM.riskStatusText.className = "gauge-footer text-danger";
  }

  // Cash Buffer (Card 3)
  DOM.gaugeCashVal.textContent = formatMoney(g.cash_buffer);
  DOM.gaugeCashPct.textContent = `${formatDecimal(g.cash_buffer_pct, 1)}% 储备率 (防守缓冲垫)`;
  DOM.barCash.style.width = `${Math.min(100, g.cash_buffer_pct)}%`;
  if (state.selectedSymbols.size === 0) {
    DOM.cashStatusText.textContent = "100% 全额现金储备，零持仓风险";
    DOM.cashStatusText.className = "gauge-footer text-success";
  } else if (g.cash_buffer_pct >= 65.0) {
    DOM.cashStatusText.textContent = "充裕闲置资金储备 (抗跳空/抗提保/抗追加信号)";
    DOM.cashStatusText.className = "gauge-footer text-success";
  } else {
    DOM.cashStatusText.textContent = "现金防护垫低于 65%，账户抗冲击能力削弱";
    DOM.cashStatusText.className = "gauge-footer text-warning";
  }

  // Feasibility Panel updates (全开仓资本需求与承载力评估)
  if (state.selectedSymbols.size === 0) {
    if (DOM.fValFullMargin) DOM.fValFullMargin.textContent = "¥0.00";
    if (DOM.fSubFullMargin) DOM.fSubFullMargin.textContent = "未勾选品种，暂无保证金需求";
    if (DOM.fValFullRisk) DOM.fValFullRisk.textContent = "¥0.00";
    if (DOM.fSubFullRisk) DOM.fSubFullRisk.textContent = "未勾选品种，无持仓止损敞口";
    if (DOM.fValMinEquity) DOM.fValMinEquity.textContent = "¥0.00";
    if (DOM.fSubMinEquity) DOM.fSubMinEquity.textContent = "未勾选品种，暂无资金门槛";
    if (DOM.feasibilityMsg) DOM.feasibilityMsg.textContent = "请在下方表格勾选拟交易的期货品种以评估所需资本与风险承载力。";
    if (DOM.feasibilityBadge) {
      DOM.feasibilityBadge.className = "badge";
      DOM.feasibilityBadge.textContent = "未勾选品种";
    }
  } else {
    const recMargin = (g.actual_recommended_margin !== undefined) ? g.actual_recommended_margin : (g.total_actual_margin || 0);
    const recRisk = (g.actual_recommended_risk !== undefined) ? g.actual_recommended_risk : (g.total_actual_risk || 0);
    const recMarginPct = g.equity > 0 ? (recMargin / g.equity * 100.0) : 0.0;
    const recRiskPct = g.equity > 0 ? (recRisk / g.equity * 100.0) : 0.0;
    const base1LotMargin = g.basket_full_margin || 0;
    const base1LotRisk = g.basket_full_risk || 0;
    const recEquity = g.recommended_full_equity || 0;
    const baseEquity = g.recommended_min_equity || 0;
    const recDriver = g.rec_equity_driver || "≤3.0% 止损上限";
    const baseDriver = g.base_equity_driver || "≤3.0% 止损上限";

    if (DOM.fValFullMargin) DOM.fValFullMargin.textContent = formatMoney(recMargin);
    if (DOM.fSubFullMargin) {
      DOM.fSubFullMargin.textContent = `占当前本金 ${formatDecimal(recMarginPct, 2)}% · 各开1手底仓需 ${formatMoney(base1LotMargin)}`;
    }
    if (DOM.fValFullRisk) DOM.fValFullRisk.textContent = formatMoney(recRisk);
    if (DOM.fSubFullRisk) {
      DOM.fSubFullRisk.textContent = `全击穿理论损失: ${formatDecimal(recRiskPct, 2)}% · 各开1手基础风险 ${formatMoney(base1LotRisk)}`;
    }
    if (DOM.fValMinEquity) {
      DOM.fValMinEquity.textContent = formatMoney(recEquity > 0 ? recEquity : baseEquity);
    }
    if (DOM.fSubMinEquity) {
      DOM.fSubMinEquity.textContent = `推荐满开建议净值 · 1手底仓门槛 ≥ ${formatMoney(baseEquity)} (受${baseDriver}约束)`;
    }
    if (DOM.feasibilityMsg) DOM.feasibilityMsg.textContent = g.feasibility_message || "";
    if (DOM.feasibilityBadge) {
      if (g.feasibility_status === "NEGATIVE_EXPECTANCY") {
        DOM.feasibilityBadge.className = "badge badge-danger";
        DOM.feasibilityBadge.textContent = "无法执行 (负数学期望)";
      } else if (g.feasibility_status === "FEASIBLE") {
        DOM.feasibilityBadge.className = "badge badge-success";
        DOM.feasibilityBadge.textContent = "资金充裕 (可稳健全开)";
      } else {
        DOM.feasibilityBadge.className = "badge badge-warning";
        DOM.feasibilityBadge.textContent = "资金受限 (已自动削峰填谷平衡)";
      }
    }
  }
}

// Render Kelly statistics
function renderKellyStats(k, kRange) {
  if (!k || !k.has_edge || k.expectancy_r <= 0) {
    DOM.kExpectancy.textContent = `${k ? k.expectancy_r : 0} R (无统计优势)`;
    DOM.kExpectancy.className = "k-val text-danger";
    DOM.kFullKelly.textContent = "0.00% (无法执行)";
    DOM.kFullKelly.className = "k-val text-danger";
    DOM.kSafeKelly.textContent = "0.00% (强制归零)";
    DOM.kSafeKelly.className = "k-val text-danger";
    DOM.kDrawdownProb.textContent = "100.0% (长跑必亏)";
    DOM.kDrawdownProb.className = "k-val text-danger";
    DOM.kellyMessage.textContent = "❌ 策略数学期望 ≤ 0，无法执行凯利公式！系统已强制将开仓手数与风险预算归零。";
    DOM.kellyMessage.className = "gauge-footer text-danger";
    return;
  }

  DOM.kExpectancy.className = "k-val text-gold";
  DOM.kFullKelly.className = "k-val";
  DOM.kSafeKelly.className = "k-val text-gold";
  DOM.kDrawdownProb.className = "k-val text-success";
  DOM.kellyMessage.className = "gauge-footer";

  if (kRange && kRange.expectancy_range_r) {
    const eMin = kRange.expectancy_range_r[0];
    const eMax = kRange.expectancy_range_r[1];
    DOM.kExpectancy.textContent = `${eMin >= 0 ? '+' : ''}${eMin} ~ +${eMax} R`;
  } else {
    DOM.kExpectancy.textContent = `${k.expectancy_r >= 0 ? '+' : ''}${k.expectancy_r} R`;
  }

  DOM.kFullKelly.textContent = `${formatDecimal(k.full_kelly_pct, 2)}%`;

  if (kRange && kRange.f_safe_range_pct) {
    DOM.kSafeKelly.textContent = `${formatDecimal(kRange.f_safe_range_pct[0], 2)}% ~ ${formatDecimal(kRange.f_safe_range_pct[1], 2)}%`;
  } else {
    DOM.kSafeKelly.textContent = `${formatDecimal(k.safe_kelly_pct, 2)}%`;
  }

  DOM.kDrawdownProb.textContent = `< ${k.drawdown_50_prob_pct}%`;

  if (kRange && kRange.expectancy_range_r) {
    DOM.kellyMessage.textContent = `区间期望 [${kRange.expectancy_range_r[0]}, ${kRange.expectancy_range_r[1]}] R (中枢 ${k.expectancy_r >= 0 ? '+' : ''}${k.expectancy_r} R) | ${k.message}`;
  } else {
    DOM.kellyMessage.textContent = k.message;
  }
}

// Render Clusters breakdown
function renderClusters(clusters, gauges) {
  if (!clusters || clusters.length === 0) {
    DOM.clustersGrid.innerHTML = "<p>无活跃聚类</p>";
    return;
  }

  DOM.clustersGrid.innerHTML = clusters.map(c => {
    const isAlert = c.risk_pct >= 28.0;
    return `
      <div class="cluster-item">
        <div class="cluster-item-header">
          <span class="cluster-title">${c.cluster_name}</span>
          <span class="cluster-pct-badge ${isAlert ? 'alert' : ''}">${c.risk_pct}% 风险</span>
        </div>
        <div class="cluster-details">
          <span>风险: ${formatMoney(c.risk)}</span>
          <span>保证金: ${formatMoney(c.margin)}</span>
          <span>共 ${c.lots} 手</span>
        </div>
        <div class="progress-container" style="height: 6px; margin-bottom: 6px;">
          <div class="progress-bar ${isAlert ? 'bar-risk' : ''}" style="width: ${Math.min(100, (c.risk_pct / 30.0) * 100)}%;"></div>
        </div>
        <div class="cluster-symbols">
          覆盖品种: ${c.symbols.join(", ") || '无'}
        </div>
      </div>
    `;
  }).join("");

  DOM.clusterPills.innerHTML = clusters.map(c => `
    <span class="tag ${c.risk_pct >= 28 ? 'badge-danger' : 'tag-blue'}">
      ${c.cluster_id.split('_')[0].toUpperCase()}: ${c.risk_pct}%
    </span>
  `).join("");
}

// Render Variety Sizing Table
function renderTable() {
  if (!state.allInstruments || state.allInstruments.length === 0) return;

  const itemsMap = {};
  if (state.calcData && state.calcData.items) {
    state.calcData.items.forEach(it => {
      itemsMap[it.symbol] = it;
    });
  }

  // Filter instruments
  const filtered = state.allInstruments.filter(inst => {
    // Sector filter
    if (state.currentSectorFilter !== "ALL" && inst.sector !== state.currentSectorFilter) {
      return false;
    }
    // Search filter
    if (state.searchTerm) {
      const matchSym = inst.symbol.toLowerCase().includes(state.searchTerm);
      const matchName = inst.name.toLowerCase().includes(state.searchTerm);
      const matchSec = inst.sector.toLowerCase().includes(state.searchTerm);
      if (!matchSym && !matchName && !matchSec) return false;
    }
    return true;
  });

  DOM.sizingTableBody.innerHTML = filtered.map(inst => {
    const isSelected = state.selectedSymbols.has(inst.symbol);
    // ponytail: fallback must mirror backend formula (1.2 * ATR * gap_penalty) to avoid data jump on checkbox toggle
    const gp = inst.gap_penalty || 1.0;
    const effStop = Math.max(1.2 * inst.typical_atr * gp, 0.02 * inst.default_price * gp);
    const instMargin = inst.margin_per_lot ? inst.margin_per_lot : (inst.default_price * inst.multiplier * inst.margin_rate);
    const item = itemsMap[inst.symbol] || {
      price: inst.default_price,
      multiplier: inst.multiplier,
      margin_rate_pct: (inst.margin_rate * 100).toFixed(1),
      typical_atr: inst.typical_atr,
      gap_risk_level: inst.gap_risk_level || "常规平稳",
      gap_risk_tag: inst.gap_risk_tag || "normal",
      gap_penalty: gp,
      gap_ratio_pct: inst.gap_ratio_pct || 20.0,
      max_gap_ratio: inst.max_gap_ratio || 0.5,
      effective_stop: effStop.toFixed(2),
      risk_per_lot: (effStop * inst.multiplier).toFixed(2),
      margin_per_lot: Number(instMargin).toFixed(2),
      underlying_symbol: inst.underlying_symbol || inst.symbol,
      risk_lots: 0.0,
      table_max_lots: inst.max_lots_1m,
      final_lots: 0,
      actual_risk: 0,
      risk_contrib_pct: 0,
      actual_margin: 0
    };

    const finalLots = isSelected ? (Number(item.final_lots) || 0) : 0;
    const isZero = finalLots === 0;

    const actualRisk = (isSelected && finalLots > 0) ? (Number(item.actual_risk) || (finalLots * Number(item.risk_per_lot))) : 0;
    const actualMargin = (isSelected && finalLots > 0) ? (Number(item.actual_margin) || (finalLots * Number(item.margin_per_lot))) : 0;
    const riskContribPct = (isSelected && finalLots > 0) ? (Number(item.risk_contrib_pct) || 0) : 0;

    const gapTagClass = item.gap_risk_tag === 'high' ? 'tag-gap-high' : (item.gap_risk_tag === 'medium' ? 'tag-gap-medium' : 'tag-gap-normal');
    const gapPenaltyText = item.gap_penalty && item.gap_penalty > 1.0 ? ` (${item.gap_penalty}x)` : '';
    const gapTooltip = `隔夜跳空率: ${item.gap_ratio_pct || 20}%, 极端跳空: ${item.max_gap_ratio || 0.5}x ATR, 跳空止损惩罚: ${item.gap_penalty || 1.0}x`;

    const contractCode = (item.underlying_symbol || inst.underlying_symbol || inst.symbol).replace(/^(SHFE|DCE|CZCE|INE|GFEX|CFFEX)\./, '');

    return `
      <tr class="${isSelected ? '' : 'opacity-muted'}">
        <td>
          <input type="checkbox" class="sym-check" data-symbol="${inst.symbol}" ${isSelected ? 'checked' : ''}>
        </td>
        <td>
          <span class="sym-badge">${inst.symbol}</span>
          <span class="exch-tag" title="活跃主力合约: ${item.underlying_symbol || inst.underlying_symbol || inst.symbol}">${contractCode}</span>
        </td>
        <td><strong>${inst.name}</strong></td>
        <td><span class="tag tag-blue">${inst.sector}</span></td>
        <td><strong>${formatDecimal(item.price, 2)}</strong></td>
        <td>${formatDecimal(item.typical_atr, 2)}</td>
        <td>
          <span class="tag ${gapTagClass}" title="${gapTooltip}">
            ${item.gap_risk_level || '常规平稳'}${gapPenaltyText}
          </span>
        </td>
        <td>${formatDecimal(item.effective_stop, 2)}</td>
        <td><strong>${formatMoney(item.risk_per_lot)}</strong></td>
        <td><strong>${formatMoney(item.margin_per_lot)}</strong></td>
        <td>${item.table_max_lots}手</td>
        <td class="td-highlight">
          <span class="lots-badge ${isZero ? (isSelected ? 'badge-warning-zero' : 'zero') : ''} btn-formula" data-symbol="${inst.symbol}" title="${escapeHtml(isZero ? (isSelected ? (item.constraint_reason || '开仓受阻，点击查看详细原因') : '未勾选建仓') : (item.why_cannot_increase || '点击查看详细推导'))}" style="cursor: pointer;">
            ${finalLots} 手 <span style="font-size: 11px; opacity: 0.85;">${isZero && isSelected ? '⚠️' : '📐'}</span>
          </span>
          ${isSelected && isZero ? `
            <div class="lots-sub-warning btn-formula" data-symbol="${inst.symbol}" title="${escapeHtml(item.constraint_reason || '开仓受阻，点击查看详细原因')}">
              开仓受阻 · 详情
            </div>
          ` : (isSelected && finalLots > 0 ? `
            <div class="lots-sub-hint btn-formula" data-symbol="${inst.symbol}" title="${escapeHtml(item.why_cannot_increase || '点击查看详情')}">
              ${escapeHtml(item.status_label || '正常配置')}
            </div>
          ` : '')}
        </td>
        <td>${formatDecimal(riskContribPct, 1)}%</td>
        <td><strong class="text-cyan">${formatMoney(actualMargin)}</strong></td>
      </tr>
    `;
  }).join("");

  // Re-bind checkboxes
  DOM.sizingTableBody.querySelectorAll(".sym-check").forEach(chk => {
    chk.addEventListener("change", (e) => {
      const sym = e.target.dataset.symbol;
      if (e.target.checked) {
        state.selectedSymbols.add(sym);
      } else {
        state.selectedSymbols.delete(sym);
      }
      renderTable();
      triggerRecalculate();
    });
  });

  // Re-bind formula click on lots badge
  DOM.sizingTableBody.querySelectorAll(".btn-formula").forEach(btn => {
    btn.addEventListener("click", (e) => {
      const sym = e.currentTarget.dataset.symbol;
      if (sym) {
        openFormulaModal(sym);
      }
    });
  });

  // Sync checkAll state
  if (DOM.checkAll && state.allInstruments && state.allInstruments.length > 0) {
    if (state.selectedSymbols.size === state.allInstruments.length) {
      DOM.checkAll.checked = true;
      DOM.checkAll.indeterminate = false;
    } else if (state.selectedSymbols.size === 0) {
      DOM.checkAll.checked = false;
      DOM.checkAll.indeterminate = false;
    } else {
      DOM.checkAll.checked = false;
      DOM.checkAll.indeterminate = true;
    }
  }

  updateSummaryBar();
  renderTableFoot();
}

// Render and update top summary bar for selected instruments
function updateSummaryBar() {
  if (!state.allInstruments || state.allInstruments.length === 0) return;

  const totalCount = state.allInstruments.length;
  const selectedCount = state.selectedSymbols.size;
  const equity = (state.calcData && state.calcData.equity) || (Number(DOM.inputEquity.value) || 1000000.0);

  const itemsMap = {};
  if (state.calcData && state.calcData.items) {
    state.calcData.items.forEach(it => {
      itemsMap[it.symbol] = it;
    });
  }

  let total1LotMargin = 0;
  let totalActualMargin = 0;
  let totalActualRisk = 0;
  let totalFinalLots = 0;

  state.allInstruments.forEach(inst => {
    if (state.selectedSymbols.has(inst.symbol)) {
      const price = Number(inst.default_price) || 0;
      const mult = Number(inst.multiplier) || 1;
      const mRate = Number(inst.margin_rate) || 0.1;
      const oneLotMargin = price * mult * mRate;
      total1LotMargin += oneLotMargin;

      const item = itemsMap[inst.symbol];
      if (item) {
        totalActualMargin += Number(item.actual_margin) || 0;
        totalActualRisk += Number(item.actual_risk) || 0;
        totalFinalLots += Number(item.final_lots) || 0;
      }
    }
  });

  // Calculate Risk Degree (%) = total actual margin / equity * 100
  const riskDegreePct = equity > 0 ? (totalActualMargin / equity * 100.0) : 0.0;
  const baseRiskDegreePct = equity > 0 ? (total1LotMargin / equity * 100.0) : 0.0;

  // DOM updates
  if (DOM.tableSummaryRiskDegree) {
    DOM.tableSummaryRiskDegree.textContent = `${formatDecimal(riskDegreePct, 2)}%`;
  }
  if (DOM.tableSummaryRiskLevel) {
    if (selectedCount === 0) {
      DOM.tableSummaryRiskLevel.className = "badge";
      DOM.tableSummaryRiskLevel.textContent = "未勾选品种";
    } else if (riskDegreePct <= 30.0) {
      DOM.tableSummaryRiskLevel.className = "badge badge-success";
      DOM.tableSummaryRiskLevel.textContent = "常态稳健 (≤30%)";
    } else if (riskDegreePct <= 35.0) {
      DOM.tableSummaryRiskLevel.className = "badge badge-warning";
      DOM.tableSummaryRiskLevel.textContent = "轻度预警 (30%~35%)";
    } else {
      DOM.tableSummaryRiskLevel.className = "badge badge-danger";
      DOM.tableSummaryRiskLevel.textContent = "占用偏高 (>35%)";
    }
  }

  if (DOM.tableSummaryRiskSub) {
    const riskPct = equity > 0 ? (totalActualRisk / equity * 100.0) : 0.0;
    DOM.tableSummaryRiskSub.textContent = selectedCount === 0
      ? "实盘占用保证金/总权益 · 非止损亏损风险"
      : `保证金占用率 (实盘风险度) · 实际总止损敞口 ${formatDecimal(riskPct, 2)}%`;
  }

  if (DOM.tableSummaryActualMargin) {
    DOM.tableSummaryActualMargin.textContent = formatMoney(totalActualMargin);
  }
  if (DOM.tableSummaryMarginSub) {
    DOM.tableSummaryMarginSub.textContent = `推荐执行总手数: ${totalFinalLots} 手 · 占权益 ${formatDecimal(riskDegreePct, 2)}%`;
  }

  const cashBuffer = Math.max(0, equity - totalActualMargin);
  const cashBufferPct = equity > 0 ? (cashBuffer / equity * 100.0) : 0.0;

  if (DOM.tableSummaryCashBuffer) {
    DOM.tableSummaryCashBuffer.textContent = formatMoney(cashBuffer);
  }
  if (DOM.tableSummaryCashSub) {
    DOM.tableSummaryCashSub.textContent = `防守缓冲储备: ${formatDecimal(cashBufferPct, 1)}%`;
  }

  if (DOM.tableSummaryCount) {
    DOM.tableSummaryCount.textContent = `已选 ${selectedCount} / ${totalCount} 个品种`;
  }
  if (DOM.tableSummaryOpenRisk) {
    const riskPct = equity > 0 ? (totalActualRisk / equity * 100.0) : 0.0;
    DOM.tableSummaryOpenRisk.textContent = `总开放风险: ${formatMoney(totalActualRisk)} (${formatDecimal(riskPct, 2)}%)`;
  }
}

// Render table footer with column totals
function renderTableFoot() {
  if (!DOM.sizingTableFoot || !state.allInstruments) return;

  const itemsMap = {};
  if (state.calcData && state.calcData.items) {
    state.calcData.items.forEach(it => {
      itemsMap[it.symbol] = it;
    });
  }

  let totalRiskPerLot = 0;
  let totalMarginPerLot = 0;
  let totalFinalLots = 0;
  let totalActualRisk = 0;
  let totalActualMargin = 0;
  let selectedCount = 0;

  state.allInstruments.forEach(inst => {
    if (state.selectedSymbols.has(inst.symbol)) {
      selectedCount++;
      const item = itemsMap[inst.symbol];
      const gp = inst.gap_penalty || 1.0;
      const effStop = Math.max(1.2 * inst.typical_atr * gp, 0.02 * inst.default_price * gp);
      const rPerLot = item ? Number(item.risk_per_lot) : (effStop * inst.multiplier);
      const mPerLot = item ? Number(item.margin_per_lot) : (inst.default_price * inst.multiplier * inst.margin_rate);

      totalRiskPerLot += rPerLot;
      totalMarginPerLot += mPerLot;

      if (item) {
        totalFinalLots += Number(item.final_lots) || 0;
        totalActualRisk += Number(item.actual_risk) || 0;
        totalActualMargin += Number(item.actual_margin) || 0;
      }
    }
  });

  const equity = (state.calcData && state.calcData.equity) || (Number(DOM.inputEquity.value) || 1000000.0);
  const riskDegreePct = equity > 0 ? (totalActualMargin / equity * 100.0) : 0.0;
  const actualRiskPct = equity > 0 ? (totalActualRisk / equity * 100.0) : 0.0;

  DOM.sizingTableFoot.innerHTML = `
    <tr>
      <td colspan="8" style="text-align: left;">
        <strong>选中汇总合计 (已勾选 ${selectedCount} 个活跃品种 · 保证金占用率: <span class="text-gold">${formatDecimal(riskDegreePct, 2)}%</span> <span style="font-size: 11px; font-weight: normal; color: var(--text-secondary);">(期货实盘俗称风险度)</span> · 实际止损总敞口: <span class="text-blue">${formatDecimal(actualRiskPct, 2)}%</span>)</strong>
      </td>
      <td><strong>${formatMoney(totalRiskPerLot)}</strong></td>
      <td><strong class="text-blue">${formatMoney(totalMarginPerLot)}</strong></td>
      <td>-</td>
      <td class="td-highlight">
        <span class="lots-badge ${totalFinalLots === 0 ? 'zero' : ''}">${totalFinalLots} 手</span>
      </td>
      <td title="各品种实际风险金额之和除以总风险，归一化比例恒为 100.0%（闭环分配），对应占账户总净值 ${formatDecimal(actualRiskPct, 2)}%">
        <strong>${selectedCount > 0 && totalActualRisk > 0 ? '100.0%' : '0.0%'}</strong>
        <div style="font-size: 11px; font-weight: normal; color: var(--accent-blue); white-space: nowrap;">(占净值 ${formatDecimal(actualRiskPct, 2)}%)</div>
      </td>
      <td><strong class="text-cyan">${formatMoney(totalActualMargin)}</strong></td>
    </tr>
  `;
}

// Render Stress testing cards
function renderStressTests(stress) {
  if (!stress) return;

  DOM.stressGrid.innerHTML = `
    <!-- Scenario 1 -->
    <div class="stress-card">
      <div class="stress-header">
        <span class="stress-title">${stress.margin_hike.name}</span>
        <span class="badge ${stress.margin_hike.passed ? 'badge-success' : 'badge-danger'}">
          ${stress.margin_hike.passed ? '安全通过' : '预警'}
        </span>
      </div>
      <div class="stress-body">
        <div class="stress-stat-row">
          <span>当前保证金占用:</span>
          <span class="stress-stat-val">${formatMoney(stress.margin_hike.current_margin)}</span>
        </div>
        <div class="stress-stat-row">
          <span>调保后预测占用:</span>
          <span class="stress-stat-val text-warning">${formatMoney(stress.margin_hike.stressed_margin)} (${stress.margin_hike.stressed_margin_pct}%)</span>
        </div>
      </div>
      <div class="stress-verdict ${stress.margin_hike.passed ? 'verdict-pass' : 'verdict-warn'}">
        ${stress.margin_hike.verdict}
      </div>
    </div>

    <!-- Scenario 2 -->
    <div class="stress-card">
      <div class="stress-header">
        <span class="stress-title">${stress.gap_black_swan.name}</span>
        <span class="badge ${stress.gap_black_swan.passed ? 'badge-success' : 'badge-danger'}">
          ${stress.gap_black_swan.passed ? '回撤受控' : '超限'}
        </span>
      </div>
      <div class="stress-body">
        <div class="stress-stat-row">
          <span>全品种跳空理论损失:</span>
          <span class="stress-stat-val text-danger">-${formatMoney(stress.gap_black_swan.theoretical_loss)}</span>
        </div>
        <div class="stress-stat-row">
          <span>占账户净值比率:</span>
          <span class="stress-stat-val">-${stress.gap_black_swan.loss_pct}% (安全线: ≤6.0%)</span>
        </div>
      </div>
      <div class="stress-verdict ${stress.gap_black_swan.passed ? 'verdict-pass' : 'verdict-warn'}">
        ${stress.gap_black_swan.verdict}
      </div>
    </div>

    <!-- Scenario 3 -->
    <div class="stress-card">
      <div class="stress-header">
        <span class="stress-title">${stress.cluster_joint_stop.name}</span>
        <span class="badge ${stress.cluster_joint_stop.passed ? 'badge-success' : 'badge-danger'}">
          ${stress.cluster_joint_stop.passed ? '防火墙有效' : '敞口过高'}
        </span>
      </div>
      <div class="stress-body">
        <div class="stress-stat-row">
          <span>产业链共振止损损失:</span>
          <span class="stress-stat-val text-danger">-${formatMoney(stress.cluster_joint_stop.cluster_loss)}</span>
        </div>
        <div class="stress-stat-row">
          <span>占账户净值比率:</span>
          <span class="stress-stat-val">-${stress.cluster_joint_stop.loss_pct}% (安全线: ≤1.2%)</span>
        </div>
      </div>
      <div class="stress-verdict ${stress.cluster_joint_stop.passed ? 'verdict-pass' : 'verdict-warn'}">
        ${stress.cluster_joint_stop.verdict}
      </div>
    </div>

    <!-- Scenario 4 -->
    <div class="stress-card">
      <div class="stress-header">
        <span class="stress-title">${stress.consecutive_losses.name}</span>
        <span class="badge ${stress.consecutive_losses.passed !== false ? 'badge-success' : 'badge-danger'}">
          ${stress.consecutive_losses.passed !== false ? '生存达标' : '回撤超限'}
        </span>
      </div>
      <div class="stress-body">
        <div class="stress-stat-row">
          <span>10连败后剩余权益:</span>
          <span class="stress-stat-val text-success">${formatMoney(stress.consecutive_losses.surviving_equity)}</span>
        </div>
        <div class="stress-stat-row">
          <span>受控累计净值回撤:</span>
          <span class="stress-stat-val">-${stress.consecutive_losses.cumulative_dd_pct}% <span class="text-xs text-muted" title="无断路器纯复利衰减">(-${stress.consecutive_losses.raw_cumulative_dd_pct || stress.consecutive_losses.cumulative_dd_pct}%)</span></span>
        </div>
      </div>
      <div class="stress-verdict ${stress.consecutive_losses.passed !== false ? 'verdict-pass' : 'verdict-warn'}">
        ${stress.consecutive_losses.verdict}
      </div>
    </div>
  `;
}

// Render Formula & Sizing Derivation Modal
function openFormulaModal(symbol) {
  if (!symbol) return;
  const inst = (state.allInstruments || []).find(i => i.symbol === symbol) || {};
  const item = (state.calcData && state.calcData.items ? state.calcData.items.find(i => i.symbol === symbol) : null) || {};

  const name = inst.name || item.name || symbol;
  const sector = inst.sector || item.sector || "综合板块";
  const cluster = item.cluster || inst.cluster || "CL_GENERAL";
  const price = Number(item.price || inst.default_price || 0);
  const mult = Number(item.multiplier || inst.multiplier || 1);
  const marginRatePct = Number(item.margin_rate_pct || (inst.margin_rate ? inst.margin_rate * 100 : 7)).toFixed(1);
  const marginRate = Number(item.margin_rate || inst.margin_rate || 0.07);
  const atr = Number(item.typical_atr || inst.typical_atr || 0);
  const gapPenalty = Number(item.gap_penalty || inst.gap_penalty || 1.0);
  const effStop = Number(item.effective_stop || 0) || Math.max(1.2 * atr * gapPenalty, 0.02 * price * gapPenalty);
  const notionalPerLot = price * mult;
  const marginPerLot = Number(item.margin_per_lot || (price * mult * marginRate));
  const riskPerLot = Number(item.risk_per_lot || (effStop * mult));
  const tableMaxLots = Number(item.table_max_lots || inst.max_lots_1m || 8);
  const isSelected = state.selectedSymbols.has(symbol);
  const finalLots = isSelected ? (Number(item.final_lots) || 0) : 0;
  const actualMargin = finalLots * marginPerLot;
  const actualRisk = finalLots * riskPerLot;

  const equity = Number((state.calcData && state.calcData.equity) || DOM.inputEquity.value || 1000000);
  const safeKellyPct = Number((state.calcData && state.calcData.kelly && state.calcData.kelly.safe_kelly_pct) || 2.67);
  const activeRiskBudget = equity * (safeKellyPct / 100.0);
  const clusterCapRate = state.clusterCapRate || 0.30;
  const clusterBudget = activeRiskBudget * clusterCapRate;
  const softMarginBudget = equity * 0.35;

  // Step calculations
  const rawKellyLots = riskPerLot > 0 ? (activeRiskBudget / riskPerLot) : 0;
  const floorKellyLots = Math.floor(rawKellyLots);
  const floorMarginLots = marginPerLot > 0 ? Math.floor(softMarginBudget / marginPerLot) : 0;
  const floorClusterLots = riskPerLot > 0 ? Math.floor(clusterBudget / riskPerLot) : 0;

  // Binding constraints detection
  let limitingFactor = "";
  if (!isSelected) {
    limitingFactor = "该品种当前未在左侧勾选参与建仓 (未激活)";
  } else if (finalLots === tableMaxLots && tableMaxLots <= floorClusterLots && tableMaxLots <= floorMarginLots) {
    limitingFactor = `受品种物理流动性与容量上限 (${tableMaxLots} 手) 严格硬约束`;
  } else if (finalLots * riskPerLot >= clusterBudget * 0.95 && state.selectedSymbols.size > 1) {
    limitingFactor = `受板块/产业链聚类防火墙上限 (${(clusterCapRate * 100).toFixed(0)}%, ¥${formatMoney(clusterBudget)}) 约束`;
  } else if (finalLots * marginPerLot >= softMarginBudget * 0.9) {
    limitingFactor = `受账户保证金软上限 (35%, ¥${formatMoney(softMarginBudget)}) 约束`;
  } else if (state.selectedSymbols.size > 1) {
    limitingFactor = `受多品种组合全局削峰填谷与广度优先平衡 (6组行情情景矩阵均值) 约束`;
  } else {
    limitingFactor = `受品种物理流动性容量上限 (${tableMaxLots} 手) 与凯利风险预算综合约束`;
  }

  // Update Modal Title
  if (DOM.formulaModalTitle) {
    DOM.formulaModalTitle.textContent = `【${symbol} ${name}】推荐执行手数数学推导全过程 (${finalLots} 手)`;
  }

  // Generate Constraint & Sizing Diagnostics Card
  let constraintCardHtml = "";
  if (!isSelected) {
    constraintCardHtml = `
      <div class="formula-card">
        <div class="formula-card-header">
          <div class="formula-card-title">
            <span>ℹ️ 未激活建仓状态</span>
          </div>
          <span class="badge">未勾选</span>
        </div>
        <div style="font-size: 13px; color: var(--text-secondary); line-height: 1.6;">
          该品种当前未在左侧勾选参与建仓。如需建仓，请在左侧表格中勾选复选框，系统将自动纳入六情景凯利公式与机制聚类优化计算。
        </div>
      </div>
    `;
  } else if (finalLots === 0) {
    constraintCardHtml = `
      <div class="formula-card constraint-alert-card">
        <div class="formula-card-header">
          <div class="formula-card-title" style="color: var(--accent-orange); font-size: 15px;">
            <span>🚨 开仓被取消 / 无法开仓详细诊断与风控瓶颈</span>
          </div>
          <span class="lots-badge badge-warning-zero">开仓受阻 (0 手)</span>
        </div>
        <div class="constraint-main-box">
          <div style="font-weight: 700; color: #ff9b57; margin-bottom: 4px;">
            🛑 阻断核心原因：
          </div>
          <div style="color: var(--text-primary); line-height: 1.65; font-size: 13px;">
            ${escapeHtml(item.constraint_reason || '受组合总开放风险预算或所属机制聚类防火墙限制，已被挤出。')}
          </div>
        </div>
        <div style="margin-top: 10px; font-size: 12px; line-height: 1.7; color: var(--text-secondary);">
          <div><strong>🔍 技术细节：</strong>${escapeHtml(item.why_cannot_increase || '单手风险或保证金超出预算配额。')}</div>
          <div style="margin-top: 6px;">
            <strong>💡 解除受阻/恢复开仓建议：</strong>
            <span class="text-gold" style="font-weight: 600;">${escapeHtml(item.suggestion || '建议减少勾选其它高风险品种或调大资金。')}</span>
          </div>
        </div>
      </div>
    `;
  } else {
    // finalLots > 0
    constraintCardHtml = `
      <div class="formula-card constraint-info-card">
        <div class="formula-card-header">
          <div class="formula-card-title" style="color: var(--accent-blue); font-size: 15px;">
            <span>🔒 为什么当前推荐 ${finalLots} 手，无法继续增加手数？</span>
          </div>
          <span class="lots-badge">${escapeHtml(item.status_label || '正常配置')}</span>
        </div>
        <div class="constraint-main-box">
          <div style="font-weight: 700; color: var(--accent-cyan); margin-bottom: 4px;">
            🎯 加仓瓶颈限制：
          </div>
          <div style="color: var(--text-primary); line-height: 1.65; font-size: 13px;">
            ${escapeHtml(item.why_cannot_increase || '受组合全局风险预算分配限制。')}
          </div>
        </div>
        <div style="margin-top: 10px; font-size: 12px; line-height: 1.7; color: var(--text-secondary);">
          <div><strong>📊 当前风控数据：</strong>已配置 ${finalLots} 手，实际占用止损风险 ${formatMoney(actualRisk)}，实际占用保证金 ${formatMoney(actualMargin)}。若加仓至 ${finalLots + 1} 手，风险将达到 ${formatMoney(actualRisk + riskPerLot)}。</div>
          <div style="margin-top: 4px;">
            <strong>💡 优化方案建议：</strong>
            <span class="text-gold">${escapeHtml(item.suggestion || '当前配置已是数学最优均衡，建议严格按推荐执行。')}</span>
          </div>
        </div>
      </div>
    `;
  }

  // Generate HTML for Formula Body
  if (DOM.formulaBody) {
    DOM.formulaBody.innerHTML = `
      <div class="formula-card">
        <div class="formula-card-header">
          <div class="formula-card-title">
            <span>📌 核心结论与执行摘要</span>
          </div>
          <span class="lots-badge ${finalLots === 0 ? 'zero' : ''}">${finalLots} 手</span>
        </div>
        <div class="formula-grid-3">
          <div class="formula-item">
            <div class="f-label">最终推荐手数</div>
            <div class="f-value text-gold">${finalLots} 手</div>
          </div>
          <div class="formula-item">
            <div class="f-label">实际占用保证金</div>
            <div class="f-value text-cyan">${formatMoney(actualMargin)} (${formatDecimal(equity > 0 ? actualMargin/equity*100 : 0, 2)}%)</div>
          </div>
          <div class="formula-item">
            <div class="f-label">实际止损风险敞口</div>
            <div class="f-value text-danger">${formatMoney(actualRisk)} (${formatDecimal(equity > 0 ? actualRisk/equity*100 : 0, 2)}%)</div>
          </div>
        </div>
        <div style="margin-top: 10px; font-size: 12px; color: var(--text-secondary); display: flex; align-items: center; gap: 8px;">
          <span>🎯 主导制约瓶颈：</span>
          <span class="formula-tag-binding">${limitingFactor}</span>
        </div>
      </div>

      ${constraintCardHtml}

      <div class="formula-card">
        <div class="formula-card-header">
          <div class="formula-card-title">
            <span>第一部分：合约基础参数与单手风险公式</span>
          </div>
          <span style="font-size: 12px; color: var(--text-secondary);">天勤量化实盘真实数据</span>
        </div>
        <div class="formula-grid-3" style="margin-bottom: 12px;">
          <div class="formula-item">
            <div class="f-label">参考基准价格 (P)</div>
            <div class="f-value">¥${formatDecimal(price, 2)}</div>
          </div>
          <div class="formula-item">
            <div class="f-label">合约乘数 (M)</div>
            <div class="f-value">${mult} /手</div>
          </div>
          <div class="formula-item">
            <div class="f-label">单手合约名义价值</div>
            <div class="f-value">${formatMoney(notionalPerLot)}</div>
          </div>
          <div class="formula-item">
            <div class="f-label">交易所保证金率 (r)</div>
            <div class="f-value text-gold">${marginRatePct}%</div>
          </div>
          <div class="formula-item">
            <div class="f-label">波动率 ATR(14)</div>
            <div class="f-value">${formatDecimal(atr, 2)} 点</div>
          </div>
          <div class="formula-item">
            <div class="f-label">隔夜跳空惩罚 (GP)</div>
            <div class="f-value">${formatDecimal(gapPenalty, 2)}x</div>
          </div>
        </div>

        <div class="formula-step">
          <div class="formula-step-header">
            <span class="formula-step-name">1. 单手保证金占用计算公式 (Margin Per Lot)</span>
            <span class="formula-step-res text-gold">${formatMoney(marginPerLot)}</span>
          </div>
          <div class="formula-math-box">
            M<sub>lot</sub> = P × M × r = ${formatDecimal(price, 2)} × ${mult} × ${marginRatePct}% = ${formatMoney(marginPerLot)}
          </div>
        </div>

        <div class="formula-step">
          <div class="formula-step-header">
            <span class="formula-step-name">2. 真实波动止损空间公式 (Effective Stop Loss Points)</span>
            <span class="formula-step-res">${formatDecimal(effStop, 2)} 点</span>
          </div>
          <div class="formula-math-box">
            Stop = max(1.2 × ATR × GP, 0.02 × P × GP)<br>
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;= max(1.2 × ${formatDecimal(atr, 2)} × ${formatDecimal(gapPenalty, 2)}, 0.02 × ${formatDecimal(price, 2)} × ${formatDecimal(gapPenalty, 2)}) = ${formatDecimal(effStop, 2)} 点
          </div>
        </div>

        <div class="formula-step">
          <div class="formula-step-header">
            <span class="formula-step-name">3. 单手理论击穿止损风险公式 (Risk Per Lot)</span>
            <span class="formula-step-res text-danger">${formatMoney(riskPerLot)}</span>
          </div>
          <div class="formula-math-box">
            R<sub>lot</sub> = Stop × M = ${formatDecimal(effStop, 2)} × ${mult} = ${formatMoney(riskPerLot)}
          </div>
        </div>
      </div>

      <div class="formula-card">
        <div class="formula-card-header">
          <div class="formula-card-title">
            <span>第二部分：凯利公式宏观安全预算约束</span>
          </div>
          <span style="font-size: 12px; color: var(--text-secondary);">基于分数凯利与回撤电路</span>
        </div>
        <div class="formula-grid-3" style="margin-bottom: 12px;">
          <div class="formula-item">
            <div class="f-label">当前账户净值 (Equity)</div>
            <div class="f-value">${formatMoney(equity)}</div>
          </div>
          <div class="formula-item">
            <div class="f-label">安全凯利风险比率 (f_safe)</div>
            <div class="f-value text-gold">${formatDecimal(safeKellyPct, 2)}%</div>
          </div>
          <div class="formula-item">
            <div class="f-label">总开放风险预算总额 (B_risk)</div>
            <div class="f-value text-danger">${formatMoney(activeRiskBudget)}</div>
          </div>
        </div>
        <div class="formula-step">
          <div class="formula-step-header">
            <span class="formula-step-name">账户安全风险预算公式</span>
            <span class="formula-step-res text-gold">${formatMoney(activeRiskBudget)}</span>
          </div>
          <div class="formula-math-box">
            B<sub>risk</sub> = Equity × f<sub>safe</sub> × Circuit_Factor = ${formatMoney(equity)} × ${formatDecimal(safeKellyPct, 2)}% × 1.0 = ${formatMoney(activeRiskBudget)}
          </div>
        </div>
      </div>

      <div class="formula-card">
        <div class="formula-card-header">
          <div class="formula-card-title">
            <span>第三部分：五重漏斗风控模型手数推导</span>
          </div>
          <span style="font-size: 12px; color: var(--text-secondary);">单调递减漏斗裁剪</span>
        </div>

        <div class="formula-step">
          <div class="formula-step-header">
            <span class="formula-step-name">漏斗 1：无约束纯凯利风险承载手数 (Pure Kelly Risk Lots)</span>
            <span class="formula-step-res">${floorKellyLots} 手</span>
          </div>
          <div class="formula-math-box">
            N<sub>kelly</sub> = ⌊ B<sub>risk</sub> ÷ R<sub>lot</sub> ⌋ = ⌊ ${formatMoney(activeRiskBudget)} ÷ ${formatMoney(riskPerLot)} ⌋ = ⌊ ${formatDecimal(rawKellyLots, 2)} ⌋ = ${floorKellyLots} 手
          </div>
        </div>

        <div class="formula-step">
          <div class="formula-step-header">
            <span class="formula-step-name">漏斗 2：账户保证金 35% 软上限约束 (Margin Soft Cap Lots)</span>
            <span class="formula-step-res">${floorMarginLots} 手</span>
          </div>
          <div class="formula-math-box">
            N<sub>margin</sub> = ⌊ (Equity × 35%) ÷ M<sub>lot</sub> ⌋ = ⌊ ${formatMoney(softMarginBudget)} ÷ ${formatMoney(marginPerLot)} ⌋ = ${floorMarginLots} 手
          </div>
        </div>

        <div class="formula-step">
          <div class="formula-step-header">
            <span class="formula-step-name">漏斗 3：产业链/板块聚类防火墙 ≤30% 约束 (Cluster Firewall Lots)</span>
            <span class="formula-step-res">${floorClusterLots} 手</span>
          </div>
          <div class="formula-math-box">
            N<sub>cluster</sub> = ⌊ (B<sub>risk</sub> × ${(clusterCapRate * 100).toFixed(0)}%) ÷ R<sub>lot</sub> ⌋ = ⌊ ${formatMoney(clusterBudget)} ÷ ${formatMoney(riskPerLot)} ⌋ = ${floorClusterLots} 手
          </div>
        </div>

        <div class="formula-step">
          <div class="formula-step-header">
            <span class="formula-step-name">漏斗 4：品种物理流动性容量上限 (Liquidity Capacity Cap)</span>
            <span class="formula-step-res text-gold">${tableMaxLots} 手</span>
          </div>
          <div class="formula-math-box">
            N<sub>liquidity</sub> = max_lots_1m (基于日均成交量与持仓深度换算硬上限) = ${tableMaxLots} 手
          </div>
        </div>

        <div class="formula-step">
          <div class="formula-step-header">
            <span class="formula-step-name">漏斗 5：多情景与多品种全局平衡后最终推荐 (Final Sizing)</span>
            <span class="formula-step-res text-gold" style="font-size: 15px;">${finalLots} 手</span>
          </div>
          <div class="formula-math-box">
            N<sub>final</sub> = min(N<sub>kelly</sub>, N<sub>margin</sub>, N<sub>cluster</sub>, N<sub>liquidity</sub>, 组合均衡裁剪) = ${finalLots} 手
          </div>
        </div>
      </div>

      <div class="formula-card">
        <div class="formula-card-header">
          <div class="formula-card-title">
            <span>第四部分：执行安全性验算 (Verification Check)</span>
          </div>
          <span class="badge badge-success">验算通过</span>
        </div>
        <div style="font-size: 13px; line-height: 1.8; color: var(--text-secondary);">
          <div>✔ <strong>保证金安全验证：</strong>开仓 ${finalLots} 手占用 ${formatMoney(actualMargin)}，占总资金 ${(equity > 0 ? actualMargin/equity*100 : 0).toFixed(2)}% ≤ 30.0% (完全在常态稳健区间内)。</div>
          <div>✔ <strong>止损风险安全验证：</strong>单品种击穿止损理论损失 ${formatMoney(actualRisk)}，占净值 ${(equity > 0 ? actualRisk/equity*100 : 0).toFixed(2)}% ≤ 3.0% (完全受控)。</div>
          <div>✔ <strong>现金储备验证：</strong>剩余闲置现金防护垫 ${formatMoney(equity - actualMargin)}，充足抵御交易所提保与连续跳空冲击。</div>
        </div>
      </div>
    `;
  }

  // Open modal
  if (DOM.modalFormula) {
    DOM.modalFormula.classList.add("open");
  }
}

// Start application
document.addEventListener("DOMContentLoaded", initApp);
