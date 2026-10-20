/* 行情与处置演示。报价与流程状态由本地演示服务统一提供。 */
let MARKET_PROFILES = {};
let MARKET_SCENARIOS = [];
let MARKET_PLATFORM_IMAGES = {};
let marketRevision = -1;
let marketBusy = false;

let marketUsers = [];
let marketType = new URLSearchParams(location.search).get("asset") === "account" ? "account" : "item";
let marketRange = 30;
let marketStore = {};

async function marketLoadSnapshot(render = true) {
  const response = await fetch("/api/market/overview", { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "加载行情失败");
  if (data.revision < marketRevision) return data;
  const changed = data.revision !== marketRevision ||
    JSON.stringify(data.users) !== JSON.stringify(marketUsers) ||
    Object.keys(MARKET_PROFILES).length === 0;
  MARKET_PROFILES = data.catalog.profiles;
  MARKET_SCENARIOS = data.catalog.scenarios;
  MARKET_PLATFORM_IMAGES = data.catalog.platformImages || {};
  marketStore = data.flows;
  marketUsers = data.users;
  marketRevision = data.revision;
  if (render && changed) renderMarket();
  return data;
}

function marketMoney(amount) {
  return "¥" + Math.round(Number(amount)).toLocaleString("zh-CN");
}

function marketEscape(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
  });
}

function marketPlatformIcon(name) {
  const image = MARKET_PLATFORM_IMAGES[name];
  return '<span class="market-platform-icon" aria-hidden="true"><span>' + marketEscape(name.slice(0, 1)) + '</span>' +
    (image ? '<img src="' + marketEscape(image) + '" alt="" loading="lazy" decoding="async">' : '') + '</span>';
}

function marketCurrentUser() {
  return marketUsers.find(function (user) { return user.id === currentUserId; }) || null;
}

function marketCurrentAsset() {
  const user = marketCurrentUser();
  const profile = user ? MARKET_PROFILES[user.account] : null;
  return profile ? profile[marketType] : null;
}

function marketFlowKey() {
  return String(currentUserId) + ":" + marketType;
}

function marketFlow() {
  const saved = marketStore[marketFlowKey()] || {};
  return Object.assign({ listed: false, buyer: false, decision: null, scenario: 0 }, saved);
}

async function marketSaveFlow(action) {
  if (marketBusy) return;
  const userId = currentUserId;
  const assetType = marketType;
  marketBusy = true;
  document.querySelectorAll("[data-market-action], #marketScenarioButton").forEach(function (button) {
    button.disabled = true;
  });
  try {
    const response = await fetch("/api/market/flow", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: userId, assetType: assetType, action: action })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "操作未完成");
    marketStore[String(userId) + ":" + assetType] = data.flow;
    marketRevision = Math.max(marketRevision, data.revision);
  } catch (error) {
    showToast(error.message || "操作未完成", true);
    try { await marketLoadSnapshot(false); } catch (refreshError) {}
  } finally {
    marketBusy = false;
    renderMarket();
  }
}

function marketResetFlow() {
  return marketSaveFlow("reset");
}

function marketQuotes(asset, flow) {
  const factor = (MARKET_SCENARIOS[flow.scenario] || MARKET_SCENARIOS[0] || { factor: 1 }).factor;
  return asset.quotes.map(function (quote) {
    const price = Math.round(quote.price * factor);
    return {
      platform: quote.platform,
      price: price,
      fee: quote.fee,
      net: Math.round(price * (1 - quote.fee))
    };
  }).sort(function (a, b) { return b.net - a.net; });
}

function marketMaskedAccount(value) {
  const account = String(value || "");
  if (account.length < 5) return "****";
  return account.slice(0, 2) + "****" + account.slice(-2);
}

function marketChartMarkup(values, label) {
  const width = 360;
  const left = 8;
  const right = 352;
  const top = 10;
  const bottom = 113;
  const min = Math.min.apply(null, values);
  const max = Math.max.apply(null, values);
  const spread = Math.max(1, max - min);
  const points = values.map(function (value, index) {
    const x = left + (right - left) * index / (values.length - 1);
    const y = bottom - 8 - (value - min) / spread * (bottom - top - 16);
    return [x.toFixed(1), y.toFixed(1)];
  });
  const line = points.map(function (point) { return point.join(","); }).join(" ");
  const area = left + "," + bottom + " " + line + " " + right + "," + bottom;
  const latest = points[points.length - 1];
  return '<svg viewBox="0 0 360 124" role="img" aria-label="' + marketEscape(label) + '">' +
    '<line class="gridline" x1="8" y1="24" x2="352" y2="24"></line>' +
    '<line class="gridline" x1="8" y1="67" x2="352" y2="67"></line>' +
    '<line class="gridline" x1="8" y1="113" x2="352" y2="113"></line>' +
    '<polygon class="price-area" points="' + area + '"></polygon>' +
    '<polyline class="price-line" points="' + line + '"></polyline>' +
    '<circle class="latest-dot" cx="' + latest[0] + '" cy="' + latest[1] + '" r="5"></circle>' +
    '</svg>';
}

function marketDecisionMarkup(asset, flow, quotes, eligible) {
  if (!eligible) {
    return '<p class="market-flow-copy">当前身份尚未进入遗产处置。行情可预览，模拟挂售与决定需在客户池状态变为“已故”后进行。</p>' +
      '<div class="market-actions"><button type="button" class="market-primary" disabled>等待身份核实</button></div>';
  }

  if (!flow.listed) {
    return '<p class="market-flow-copy">比较价格后，可模拟把这份资产同步展示到 3 个平台。进度会同步到行情管理后台。</p>' +
      '<div class="market-actions"><button type="button" class="market-primary" data-market-action="list">模拟同步挂售</button></div>';
  }

  if (!flow.buyer) {
    return '<p class="market-flow-copy">已在 3 个平台模拟挂售。下一步可触发一位买家的购买意向，查看继承人如何决定。</p>' +
      '<div class="market-actions">' +
      '<button type="button" class="market-primary" data-market-action="buyer">模拟收到购买意向</button>' +
      '<button type="button" class="market-subtle" data-market-action="reset">重置</button>' +
      '</div>';
  }

  const buyerNet = Math.round(asset.buyer.price * (1 - asset.buyer.fee));
  const bestNet = quotes[0].net;
  const difference = Math.abs(bestNet - buyerNet);
  const comparison = bestNet >= buyerNet
    ? "比当前最佳参考到手少 " + marketMoney(difference)
    : "比当前最佳参考到手多 " + marketMoney(difference);
  const buyoutGap = bestNet - asset.buyout;
  const buyoutComparison = buyoutGap >= 0
    ? "低于最佳第三方参考到手 " + marketMoney(buyoutGap)
    : "高于最佳第三方参考到手 " + marketMoney(Math.abs(buyoutGap));

  if (flow.decision) {
    const result = {
      hold: {
        title: "已记录：继续观察",
        detail: "继承人暂不变卖。行情仍可能上涨或回落，可继续对比不同平台。"
      },
      sell: {
        title: "已记录：同意出售意向",
        detail: "按该买家意向预计到手 " + marketMoney(buyerNet) + "。下一步仍需人工核验和平台成交。"
      },
      buyout: {
        title: "已记录：选择平台回购",
        detail: "平台作为买方报价 " + marketMoney(asset.buyout) + "，" + buyoutComparison + "。下一步需人工复核。"
      }
    }[flow.decision];
    return '<div class="market-result" role="status"><strong>' + result.title + '</strong>' + result.detail + '</div>' +
      '<div class="market-actions">' +
      '<button type="button" class="market-secondary" data-market-action="revise">重新选择</button>' +
      '<button type="button" class="market-subtle" data-market-action="reset">重置演示</button>' +
      '</div>';
  }

  return '<div class="market-event">' +
    '<p class="market-event-title">' + marketEscape(asset.buyer.platform) + ' 出现一位模拟买家</p>' +
    '<p class="market-event-notice">已记录模拟买家意向，等待继承人决定</p>' +
    '<p class="market-event-price">' + marketMoney(buyerNet) + ' <small>预计到手</small></p>' +
    '<p class="market-event-desc">买家报价 ' + marketMoney(asset.buyer.price) + '，扣除示例费用后' + comparison + '。这是一条演示意向，尚未成交。</p>' +
    '</div>' +
    '<p class="market-flow-copy">现在出售可尽快确定金额；继续持有可能出现更高价，也可能下跌。请由继承人决定。</p>' +
    '<div class="market-actions">' +
    '<button type="button" class="market-secondary" data-market-action="hold">继续观察</button>' +
    '<button type="button" class="market-primary" data-market-action="sell">同意按此意向出售</button>' +
    '</div>' +
    '<div class="market-buyout">' +
    '<div class="market-buyout-head"><strong>平台自购方案</strong><span>' + marketMoney(asset.buyout) + '</span></div>' +
    '<p>平台同时是买方，报价与第三方到手金额一起展示。若继承人希望即时变卖，可自行选择；本演示不发生真实收购。</p>' +
    '<button type="button" class="market-subtle" data-market-action="buyout">选择平台回购报价</button>' +
    '</div>' +
    '<button type="button" class="market-text-button market-reset" data-market-action="reset">重置演示流程</button>';
}

function renderMarket() {
  const user = marketCurrentUser();
  const asset = marketCurrentAsset();
  const status = user ? user.status : "未选择";
  const eligible = status === "已故";
  const statusEl = document.getElementById("marketUserStatus");
  const emptyEl = document.getElementById("marketEmpty");
  const detailEl = document.getElementById("marketDetail");

  statusEl.textContent = "客户池状态：" + status;
  statusEl.classList.toggle("ready", eligible);
  document.getElementById("marketOwner").textContent = user
    ? "客户池档案 · " + user.game + " · " + marketMaskedAccount(user.account)
    : "数字遗产档案";
  document.getElementById("marketTitle").textContent = user && asset
    ? user.name + (eligible ? "留下的数字资产" : "的数字资产") : "数字资产行情";
  document.getElementById("marketIntroCopy").textContent = eligible && asset
    ? "这些游戏收藏可以留存，也可以在看清价格与费用后变卖。决定由继承人作出。"
    : "了解价格与费用后，再决定如何安放这份数字收藏。";

  emptyEl.hidden = Boolean(asset);
  detailEl.hidden = !asset;
  if (!asset) return;

  const flow = marketFlow();
  if (!MARKET_SCENARIOS[flow.scenario]) flow.scenario = 0;
  const quotes = marketQuotes(asset, flow);
  const best = quotes[0];
  const itemTab = document.getElementById("marketItemTab");
  const accountTab = document.getElementById("marketAccountTab");
  itemTab.classList.toggle("active", marketType === "item");
  accountTab.classList.toggle("active", marketType === "account");
  itemTab.setAttribute("aria-selected", marketType === "item" ? "true" : "false");
  accountTab.setAttribute("aria-selected", marketType === "account" ? "true" : "false");
  itemTab.tabIndex = marketType === "item" ? 0 : -1;
  accountTab.tabIndex = marketType === "account" ? 0 : -1;
  document.getElementById("marketAssetPanel").setAttribute("aria-labelledby", marketType === "item" ? "marketItemTab" : "marketAccountTab");

  document.getElementById("marketAsset").innerHTML =
    '<div class="market-art ' + marketType + '" aria-hidden="true">' +
      '<span class="market-art-code">' + marketEscape(asset.art) + '</span>' +
      '<span class="market-art-symbol">' + marketEscape(asset.symbol) + '</span>' +
      (asset.image ? '<img class="market-art-image" src="' + marketEscape(asset.image) + '" alt="" decoding="async">' : '') +
    '</div>' +
    '<div class="market-asset-copy">' +
      '<span class="market-asset-kind">' + marketEscape(asset.kind) + '</span>' +
      '<p class="market-asset-name">' + marketEscape(asset.name) + '</p>' +
      '<span class="market-asset-meta">' + marketEscape(asset.meta) + (asset.image ? ' · 图片示意' : '') + '</span>' +
      '<p class="market-asset-estimate">' + marketMoney(best.net) + '<small>最佳预计到手</small></p>' +
    '</div>';
  document.getElementById("marketAssetNote").textContent = asset.note;

  const gate = document.getElementById("marketGate");
  gate.hidden = eligible;
  if (!eligible) gate.textContent = "当前状态为“" + status + "”，挂售和处置决定已锁定。可选择已故客户查看完整演示。";

  document.querySelectorAll("[data-market-range]").forEach(function (button) {
    const active = Number(button.dataset.marketRange) === marketRange;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  const scenario = MARKET_SCENARIOS[flow.scenario];
  const values = (marketRange === 7 ? asset.history.slice(-7) : asset.history.slice());
  values[values.length - 1] = Math.round(values[values.length - 1] * scenario.factor);
  const first = values[0];
  const last = values[values.length - 1];
  const pct = (last - first) / first * 100;
  const movement = pct >= 0 ? "上涨 " : "下跌 ";
  const chartLabel = "近 " + marketRange + " 天演示价格走势，从 " + marketMoney(first) + " 到 " + marketMoney(last);
  document.getElementById("marketChart").innerHTML = marketChartMarkup(values, chartLabel);
  document.getElementById("marketTrendSummary").innerHTML =
    '<span>区间低 ' + marketMoney(Math.min.apply(null, values)) + '</span>' +
    '<span>区间高 ' + marketMoney(Math.max.apply(null, values)) + '</span>' +
    '<strong>' + movement + Math.abs(pct).toFixed(1) + '%</strong>';
  const high = Math.max.apply(null, values);
  const belowHigh = (high - last) / high * 100;
  document.getElementById("marketInsight").textContent = belowHigh >= 0.5
    ? "当前示例价格较区间高点低 " + belowHigh.toFixed(1) + "%。历史高价可供参考，但无法保证再次出现。"
    : "当前示例价格接近这段走势的高位，之后仍可能上涨或回落。";
  document.getElementById("marketScenarioButton").textContent = "模拟行情变化 ↻ " + scenario.name;

  document.getElementById("marketQuotes").innerHTML = quotes.map(function (quote, index) {
    const label = flow.listed ? " · 模拟挂售中" : " · 参考行情";
    return '<div class="market-quote">' +
      '<div>' +
        '<div class="market-platform-line">' + marketPlatformIcon(quote.platform) + '<span class="market-platform">' + marketEscape(quote.platform) + '</span>' +
        (index === 0 ? '<span class="market-best">到手最高</span>' : '') + '</div>' +
        '<p class="market-quote-meta">示例报价 ' + marketMoney(quote.price) +
        ' · 费用 ' + (quote.fee * 100).toFixed(1) + '%' + label + '</p>' +
      '</div>' +
      '<div class="market-quote-amount' + (index === 0 ? ' best' : '') + '">' +
        '<strong>' + marketMoney(quote.net) + '</strong><span>预计到手</span>' +
      '</div>' +
    '</div>';
  }).join("");

  const flowStatus = document.getElementById("marketFlowStatus");
  flowStatus.textContent = flow.decision
    ? ({ hold: "继续观察", sell: "待成交核验", buyout: "待回购复核" }[flow.decision] || "已记录")
    : flow.buyer ? "待继承人决定" : flow.listed ? "模拟挂售中" : "待挂售";
  flowStatus.classList.toggle("done", Boolean(flow.decision));
  document.getElementById("marketDecisionBody").innerHTML = marketDecisionMarkup(asset, flow, quotes, eligible);
  if (marketBusy) {
    document.querySelectorAll("[data-market-action], #marketScenarioButton").forEach(function (button) {
      button.disabled = true;
    });
  }
}

document.getElementById("marketItemTab").addEventListener("click", function () {
  marketType = "item";
  renderMarket();
});
document.getElementById("marketAccountTab").addEventListener("click", function () {
  marketType = "account";
  renderMarket();
});
document.querySelector(".market-tabs").addEventListener("keydown", function (event) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  marketType = marketType === "item" ? "account" : "item";
  renderMarket();
  document.getElementById(marketType === "item" ? "marketItemTab" : "marketAccountTab").focus();
});
document.querySelectorAll("[data-market-range]").forEach(function (button) {
  button.addEventListener("click", function () {
    marketRange = Number(button.dataset.marketRange);
    renderMarket();
  });
});
document.getElementById("marketScenarioButton").addEventListener("click", function () {
  if (!marketCurrentAsset()) return;
  marketSaveFlow("scenario");
});
document.getElementById("marketSwitchCase").addEventListener("click", function () {
  const example = marketUsers.find(function (user) {
    return user.status === "已故" && Boolean(MARKET_PROFILES[user.account]);
  });
  if (!example) return showToast("未找到已故客户的演示档案", true);
  identitySelect.value = String(example.id);
  onIdentityChange();
});
document.getElementById("marketDecisionBody").addEventListener("click", function (event) {
  const button = event.target.closest("[data-market-action]");
  if (!button) return;
  if (!marketCurrentUser() || marketCurrentUser().status !== "已故") {
    showToast("客户池状态未进入遗产处置", true);
    return;
  }
  const action = button.dataset.marketAction;
  const flow = marketFlow();
  if (action === "list") marketSaveFlow("list");
  else if (action === "buyer" && flow.listed) marketSaveFlow("buyer");
  else if (action === "hold" && flow.buyer) marketSaveFlow("hold");
  else if (action === "sell" && flow.buyer) marketSaveFlow("sell");
  else if (action === "buyout" && flow.buyer) marketSaveFlow("buyout");
  else if (action === "revise") marketSaveFlow("revise");
  else if (action === "reset") marketResetFlow();
});

document.addEventListener("error", function (event) {
  if (event.target instanceof HTMLImageElement &&
      (event.target.classList.contains("market-art-image") || event.target.closest(".market-platform-icon"))) {
    event.target.hidden = true;
  }
}, true);
