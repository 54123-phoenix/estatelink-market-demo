const elements = {
  rows: document.getElementById("accountRows"),
  detail: document.getElementById("detailBody"),
  search: document.getElementById("searchInput"),
  identityFilter: document.getElementById("identityFilter"),
  stageFilter: document.getElementById("stageFilter"),
  resultCount: document.getElementById("resultCount"),
  refreshButton: document.getElementById("refreshButton"),
  previewLink: document.getElementById("clientPreviewLink"),
  syncTime: document.getElementById("syncTime"),
  toast: document.getElementById("toast")
};

const pageQuery = new URLSearchParams(location.search);
let overview = null;
let selectedUserId = Number(pageQuery.get("userId")) || null;
let selectedAssetType = pageQuery.get("asset") === "item" ? "item" : "account";
let loading = false;
let mutating = false;
let toastTimer = null;

const defaultFlow = { listed: false, buyer: false, decision: null, scenario: 0 };

function escapeHTML(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function imageMark(src, fallback, className) {
  return '<span class="media-frame ' + className + '" aria-hidden="true">' +
    '<span class="media-fallback">' + escapeHTML(fallback) + '</span>' +
    (src ? '<img class="media-image" src="' + escapeHTML(src) + '" alt="" loading="lazy" decoding="async">' : '') +
  '</span>';
}

function assetArt(asset, assetType) {
  return '<div class="asset-visual">' +
    '<div class="asset-art ' + assetType + '" aria-hidden="true">' +
      '<span class="asset-art-code">' + escapeHTML(asset.art) + '</span>' +
      '<span class="asset-art-symbol">' + escapeHTML(asset.symbol) + '</span>' +
      '<span class="asset-art-foot">' + (assetType === "account" ? "ACCOUNT" : "ITEM") + '</span>' +
      (asset.image ? '<img class="asset-art-image" src="' + escapeHTML(asset.image) + '" alt="" decoding="async">' : '') +
    '</div>' +
    '<span class="asset-visual-caption">' + escapeHTML(asset.imageCaption || "资产类型示意") + '</span>' +
  '</div>';
}

function money(value) {
  return "¥" + Math.round(value).toLocaleString("zh-CN");
}

function maskPhone(value) {
  const phone = String(value || "");
  return phone.length === 11 ? phone.slice(0, 3) + "****" + phone.slice(-4) : "未登记";
}

function showToast(message, error = false) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = "toast" + (error ? " error" : "");
  elements.toast.hidden = false;
  toastTimer = setTimeout(() => { elements.toast.hidden = true; }, 3200);
}

function userProfile(user) {
  return overview.catalog.profiles[String(user.id)] || null;
}

function flowFor(user, assetType) {
  return { ...defaultFlow, ...(overview.flows[user.id + ":" + assetType] || {}) };
}

function quotesFor(asset, flow) {
  const scenario = overview.catalog.scenarios[flow.scenario] || overview.catalog.scenarios[0];
  return asset.quotes.map(quote => {
    const price = Math.round(quote.price * scenario.factor);
    return { platform: quote.platform, price, fee: quote.fee, net: Math.round(price * (1 - quote.fee)) };
  }).sort((a, b) => b.net - a.net);
}

function assetStage(user, assetType) {
  if (user.status !== "已故") return { key: "unavailable", label: "未进入行情", short: "未进入" };
  const profile = userProfile(user);
  if (!profile || !profile[assetType]) return { key: "unavailable", label: "未建行情档案", short: "未建档" };
  const flow = flowFor(user, assetType);
  if (flow.decision === "hold") return { key: "decided", label: "继续观察", short: "继续观察" };
  if (flow.decision === "sell") return { key: "decided", label: "待成交核验", short: "待成交" };
  if (flow.decision === "buyout") return { key: "decided", label: "待回购复核", short: "待回购" };
  if (flow.buyer) return { key: "attention", label: "待继承人决定", short: "待决定" };
  if (flow.listed) return { key: "listed", label: "模拟挂售中", short: "挂售中" };
  return { key: "unlisted", label: "待挂售", short: "待挂售" };
}

function userStage(user) {
  const profile = userProfile(user);
  if (user.status !== "已故" || !profile) {
    return { key: "unavailable", label: user.status === "已故" ? "未建行情档案" : "尚未进入行情" };
  }
  const stages = ["account", "item"].filter(type => profile[type]).map(type => assetStage(user, type));
  for (const key of ["attention", "decided", "listed", "unlisted"]) {
    if (stages.some(stage => stage.key === key)) {
      return { key, label: {
        attention: "待继承人决定", decided: "已记录决定", listed: "模拟挂售中", unlisted: "待挂售"
      }[key] };
    }
  }
  return { key: "unavailable", label: "未建行情档案" };
}

function identityBadge(status) {
  const style = { "已故": "dead", "健在": "alive", "未知": "unknown", "疑似已故": "suspected" }[status] || "unknown";
  return '<span class="badge badge-' + style + '">' + escapeHTML(status) + '</span>';
}

function stageBadge(stage) {
  const style = { attention: "attention", decided: "decided", listed: "listed", unlisted: "waiting", unavailable: "unavailable" }[stage.key];
  return '<span class="badge badge-' + style + '">' + escapeHTML(stage.label) + '</span>';
}

function filteredUsers() {
  const query = elements.search.value.trim().toLocaleLowerCase("zh-CN");
  const identity = elements.identityFilter.value;
  const stage = elements.stageFilter.value;
  const rank = { attention: 0, decided: 1, listed: 2, unlisted: 3, unavailable: 4 };
  const identityRank = { "疑似已故": 0, "已故": 1, "未知": 2, "健在": 3 };
  return overview.users.filter(user => {
    const matchesQuery = !query || [user.name, user.game, user.account, String(user.id)]
      .some(value => String(value).toLocaleLowerCase("zh-CN").includes(query));
    return matchesQuery && (identity === "all" || user.status === identity) &&
      (stage === "all" || userStage(user).key === stage);
  }).sort((a, b) => {
    const stageDifference = rank[userStage(a).key] - rank[userStage(b).key];
    return stageDifference || identityRank[a.status] - identityRank[b.status] || a.id - b.id;
  });
}

function renderSummary() {
  const eligible = overview.users.filter(user => user.status === "已故" && userProfile(user));
  let listed = 0;
  let pending = 0;
  for (const user of eligible) {
    const profile = userProfile(user);
    for (const type of ["account", "item"]) {
      if (!profile[type]) continue;
      const flow = flowFor(user, type);
      if (flow.listed) listed += 1;
      if (flow.buyer && !flow.decision) pending += 1;
    }
  }
  document.getElementById("totalCount").textContent = overview.users.length;
  document.getElementById("eligibleCount").textContent = eligible.length;
  document.getElementById("listedCount").textContent = listed;
  document.getElementById("pendingCount").textContent = pending;
  elements.syncTime.textContent = "状态同步于 " + new Date(overview.asOf).toLocaleTimeString("zh-CN", { hour12: false });
}

function priceCell(user) {
  const profile = userProfile(user);
  if (user.status !== "已故" || !profile) return '<span class="account-price-empty">行情暂未开放</span>';
  return '<span class="account-prices">' + ["account", "item"].map(type => {
    if (!profile[type]) return "";
    const best = quotesFor(profile[type], flowFor(user, type))[0];
    return '<span><small>' + (type === "account" ? "账号到手" : "道具到手") + '</small><strong>' + money(best.net) + '</strong></span>';
  }).join("") + '</span>';
}

function renderRows(list) {
  elements.resultCount.textContent = "显示 " + list.length + " / " + overview.users.length + " 条账号";
  if (!list.length) {
    elements.rows.innerHTML = '<li class="list-message">没有匹配的账号，请调整搜索或筛选条件。</li>';
    return;
  }
  elements.rows.innerHTML = list.map(user => {
    const profile = userProfile(user);
    const stage = userStage(user);
    const progress = user.status === "已故" && profile
      ? '账号' + assetStage(user, "account").short + ' · 道具' + assetStage(user, "item").short
      : (user.status === "已故" ? "暂无示例报价" : "等待身份核验");
    const selected = user.id === selectedUserId;
    const gameImage = overview.catalog.gameImages?.[user.game];
    return '<li><button type="button" class="account-row' + (selected ? ' selected' : '') + '" data-select-id="' + user.id + '"' + (selected ? ' aria-current="true"' : '') + '>' +
      '<span class="account-row-head">' + imageMark(gameImage, user.game.slice(0, 1), "avatar") +
        '<span class="account-copy"><strong>' + escapeHTML(user.name) + '</strong><small>' + escapeHTML(user.game) + ' · ' + escapeHTML(user.account) + '</small></span>' +
        '<span class="row-chevron" aria-hidden="true">›</span></span>' +
      '<span class="account-row-badges">' + identityBadge(user.status) + stageBadge(stage) + '</span>' +
      priceCell(user) +
      '<span class="account-progress">' + escapeHTML(progress) + '</span>' +
    '</button></li>';
  }).join("");
}

function chartMarkup(values) {
  const width = 500;
  const height = 160;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(1, max - min);
  const points = values.map((value, index) => ({
    x: 8 + index * (width - 16) / (values.length - 1),
    y: height - 22 - (value - min) / spread * (height - 40)
  }));
  const line = points.map(point => point.x.toFixed(1) + ',' + point.y.toFixed(1)).join(' ');
  const area = 'M 8 138 L ' + points.map(point => point.x.toFixed(1) + ' ' + point.y.toFixed(1)).join(' L ') + ' L 492 138 Z';
  const last = points[points.length - 1];
  return '<svg viewBox="0 0 500 160" role="img" aria-label="示例价格走势，从' + money(values[0]) + '至' + money(values[values.length - 1]) + '">' +
    '<line class="chart-grid" x1="8" y1="18" x2="492" y2="18"></line>' +
    '<line class="chart-grid" x1="8" y1="78" x2="492" y2="78"></line>' +
    '<line class="chart-grid" x1="8" y1="138" x2="492" y2="138"></line>' +
    '<path class="chart-area" d="' + area + '"></path>' +
    '<polyline class="chart-line" points="' + line + '"></polyline>' +
    '<circle class="chart-dot" cx="' + last.x.toFixed(1) + '" cy="' + last.y.toFixed(1) + '" r="5"></circle>' +
  '</svg>';
}

function decisionCopy(decision) {
  return {
    hold: "继承人选择继续观察，该意向尚未成交。",
    sell: "继承人同意按买家意向出售，仍需人工核验与平台成交。",
    buyout: "继承人选择平台自购方案，仍需人工复核。"
  }[decision] || "等待继承人决定。";
}

function renderAsset(user, assetType) {
  const asset = userProfile(user)[assetType];
  const flow = flowFor(user, assetType);
  const stage = assetStage(user, assetType);
  const quotes = quotesFor(asset, flow);
  const best = quotes[0];
  const scenario = overview.catalog.scenarios[flow.scenario] || overview.catalog.scenarios[0];
  const values = asset.history.slice();
  values[values.length - 1] = Math.round(values[values.length - 1] * scenario.factor);
  const change = (values[values.length - 1] - values[0]) / values[0] * 100;
  const buyerNet = Math.round(asset.buyer.price * (1 - asset.buyer.fee));
  const buyerGap = best.net - buyerNet;
  const buyerComparison = buyerGap >= 0
    ? "低于当前最高参考到手 " + money(buyerGap)
    : "高于当前最高参考到手 " + money(Math.abs(buyerGap));
  const buyoutGap = best.net - asset.buyout;
  const buyoutComparison = buyoutGap >= 0
    ? "低于当前最高第三方参考到手 " + money(buyoutGap)
    : "高于当前最高第三方参考到手 " + money(Math.abs(buyoutGap));
  const busy = mutating ? " disabled" : "";
  const mobileHref = "/mobile?userId=" + user.id + "&tab=sell&asset=" + assetType;
  const decisionTitle = flow.decision ? stage.label : "等待继承人选择";
  let actionMarkup = "";
  if (!flow.listed) {
    actionMarkup = '<button class="button button-primary" type="button" data-market-action="list"' + busy + '>模拟同步挂售</button>';
  } else if (!flow.buyer) {
    actionMarkup = '<button class="button button-primary" type="button" data-market-action="buyer"' + busy + '>模拟买家意向</button>';
  } else {
    actionMarkup = '<a class="button button-primary" href="' + mobileHref + '" target="_blank" rel="noopener">查看继承人决定</a>';
  }
  if (flow.listed || flow.buyer || flow.decision || flow.scenario) {
    actionMarkup += '<button class="button button-text" type="button" data-market-action="reset"' + busy + '>重置本方案</button>';
  }

  const quoteRows = quotes.map((quote, index) => `
    <li class="quote-row${index === 0 ? " best-quote" : ""}">
      <span class="quote-rank" aria-hidden="true">${String(index + 1).padStart(2, "0")}</span>
      ${imageMark(overview.catalog.platformImages?.[quote.platform], quote.platform.trim().slice(0, 1), "platform-mark")}
      <span class="quote-main">
        <span class="quote-platform-name">${escapeHTML(quote.platform)}${index === 0 ? '<em class="best-label">到手较高</em>' : ""}</span>
        <span class="quote-breakdown">报价 ${money(quote.price)} · 示例费用 ${money(quote.price - quote.net)}（${(quote.fee * 100).toFixed(1)}%）</span>
      </span>
      <span class="quote-net"><strong>${money(quote.net)}</strong><small>预计到手</small></span>
    </li>
  `).join("");
  const offers = flow.buyer ? `
    <div class="offer-grid">
      <article class="offer-card">
        <span class="offer-label">${escapeHTML(asset.buyer.platform)} · 模拟买家意向</span>
        <div class="offer-amount"><strong>${money(buyerNet)}</strong><span>扣费后预计到手</span></div>
        <p>买家报价 ${money(asset.buyer.price)}，示例费用 ${(asset.buyer.fee * 100).toFixed(1)}%。${buyerComparison}。${escapeHTML(decisionCopy(flow.decision))}</p>
      </article>
      <article class="offer-card offer-self">
        <span class="offer-label">平台自购报价 <em>平台是买方</em></span>
        <div class="offer-amount"><strong>${money(asset.buyout)}</strong><span>平台出价</span></div>
        <p>${buyoutComparison}。平台自购需单独复核，不替代第三方报价比较。</p>
      </article>
    </div>
  ` : "";

  return `
    <div class="asset-record" id="assetPanel" role="tabpanel" aria-labelledby="assetTab-${assetType}">
      <div class="asset-hero">
        ${assetArt(asset, assetType)}
        <div class="asset-copy">
          <p class="asset-kind">${escapeHTML(asset.kind)}</p>
          <h3 class="asset-title">${escapeHTML(asset.name)}</h3>
          <p class="asset-meta">${escapeHTML(asset.meta)}</p>
          <p class="asset-note">${escapeHTML(asset.note)}</p>
        </div>
        <div class="price-feature">
          <span>当前最高参考到手</span>
          <strong>${money(best.net)}</strong>
          <span class="price-source">来自 ${escapeHTML(best.platform)}</span>
          <small>已扣除示例费用</small>
        </div>
      </div>

      <div class="analytics-grid">
        <section class="quote-section" aria-labelledby="quoteTitle">
          <div class="detail-section-head"><div><h3 id="quoteTitle">渠道比价</h3><p>按预计到手从高到低排列</p></div><span class="section-count">${quotes.length} 家渠道</span></div>
          <ol class="quote-list">${quoteRows}</ol>
          <p class="quote-source">本地演示报价样本 · 记录于 2026-10-18 12:00</p>
        </section>
        <section class="trend-section" aria-labelledby="trendTitle">
          <div class="detail-section-head"><div><h3 id="trendTitle">价格观察</h3><p>近 30 天示例走势</p></div><span class="scenario-chip">${escapeHTML(scenario.name)}</span></div>
          <div class="chart-wrap">${chartMarkup(values)}</div>
          <div class="chart-axis"><span>30 天前</span><span>当前</span></div>
          <div class="trend-stats">
            <div><span>区间低位</span><strong>${money(Math.min(...values))}</strong></div>
            <div><span>区间高位</span><strong>${money(Math.max(...values))}</strong></div>
            <div><span>区间变化</span><strong>${change >= 0 ? "上涨" : "下跌"} ${Math.abs(change).toFixed(1)}%</strong></div>
          </div>
          <div class="trend-actions"><p>历史走势仅供参考，之后仍可能上涨或回落。</p><button class="button button-secondary" type="button" data-market-action="scenario"${busy}>切换模拟情景</button></div>
        </section>
      </div>

      <section class="flow-section" aria-labelledby="flowTitle">
        <div class="detail-section-head"><div><h3 id="flowTitle">处置进度</h3><p>从展示到决定，每一步都有记录</p></div>${stageBadge(stage)}</div>
        <ol class="steps">
          <li class="${flow.listed ? "done" : ""}"><span class="step-marker">1</span><div><strong>同步展示</strong><p>${flow.listed ? "已在 3 个平台模拟挂售" : "尚未模拟挂售"}</p></div></li>
          <li class="${flow.buyer ? "done" : ""}"><span class="step-marker">2</span><div><strong>买家意向</strong><p>${flow.buyer ? "已记录一位模拟买家" : "等待购买意向"}</p></div></li>
          <li class="${flow.decision ? "done" : ""}"><span class="step-marker">3</span><div><strong>继承人决定</strong><p>${escapeHTML(decisionTitle)}</p></div></li>
        </ol>
        ${offers}
        <div class="flow-bottom">
          <div class="flow-advice"><strong>是否出售，由继承人决定</strong><p>账号流转须核对平台规则与继承资格；演示操作不会发起真实交易。</p></div>
          <div class="detail-actions">${actionMarkup}</div>
        </div>
      </section>
    </div>
  `;
}
function renderDetail() {
  const user = overview.users.find(item => item.id === selectedUserId);
  if (!user) {
    elements.previewLink.hidden = true;
    elements.detail.innerHTML = '<div class="detail-placeholder"><strong>没有可查看的账号</strong><p>调整左侧搜索或筛选条件后，可继续查看行情。</p></div>';
    return;
  }
  elements.previewLink.hidden = false;
  const profile = userProfile(user);
  if (profile && !profile[selectedAssetType]) selectedAssetType = profile.account ? "account" : "item";
  const tabs = profile && user.status === "已故"
    ? '<div class="asset-tabs" role="tablist" aria-label="处置方案">' + ["account", "item"].filter(type => profile[type]).map(type =>
        '<button class="asset-tab" id="assetTab-' + type + '" type="button" role="tab" data-asset-tab="' + type + '" aria-selected="' + (type === selectedAssetType) + '" aria-controls="assetPanel" tabindex="' + (type === selectedAssetType ? '0' : '-1') + '">' + (type === "account" ? "账号整体方案" : "单件道具方案") + '</button>'
      ).join('') + '</div>'
    : '';
  const absence = user.status !== "已故"
    ? '<div class="absence"><span class="absence-tag">行情暂未开放</span><h3>尚未进入遗产行情</h3><p>当前客户池状态为“' + escapeHTML(user.status) + '”。完成身份及继承资格核验后，才可进入挂售与处置流程。</p><a class="button button-secondary" href="/">前往客户池管理</a></div>'
    : '<div class="absence"><span class="absence-tag">等待配置报价</span><h3>暂无演示行情档案</h3><p>这条账号已进入遗产处置范围，但本演示尚未为它配置渠道报价与道具信息。</p></div>';
  elements.detail.innerHTML =
    '<div class="detail-top"><div class="detail-identity">' + imageMark(overview.catalog.gameImages?.[user.game], user.game.slice(0, 1), "detail-game-image") + '<div><p class="detail-caption">客户池档案 #' + String(user.id).padStart(2, '0') + '</p><h2 id="selectedAccountTitle" tabindex="-1">' + escapeHTML(user.name) + '的数字资产</h2></div></div><div class="detail-statuses">' + identityBadge(user.status) + stageBadge(userStage(user)) + '</div></div>' +
    '<dl class="detail-meta"><div><dt>游戏 / 平台</dt><dd>' + escapeHTML(user.game) + '</dd></div><div><dt>账号 ID</dt><dd>' + escapeHTML(user.account) + '</dd></div><div><dt>联系号码</dt><dd>' + escapeHTML(maskPhone(user.phone)) + '</dd></div><div><dt>连续未回应</dt><dd>' + Number(user.missedCount || 0) + ' 次</dd></div></dl>' +
    (profile && user.status === "已故" ? tabs + renderAsset(user, selectedAssetType) : absence);
  const href = '/mobile?userId=' + user.id + '&tab=sell&asset=' + selectedAssetType;
  elements.previewLink.href = href;
  const nextQuery = new URLSearchParams(location.search);
  nextQuery.set("userId", String(user.id));
  nextQuery.set("asset", selectedAssetType);
  history.replaceState(null, "", location.pathname + "?" + nextQuery.toString());
}

function renderAll() {
  if (!overview) return;
  const list = filteredUsers();
  if (!list.some(user => user.id === selectedUserId)) selectedUserId = list[0] ? list[0].id : null;
  renderSummary();
  renderRows(list);
  renderDetail();
}

async function loadOverview(announce = false) {
  if (loading || mutating) return;
  loading = true;
  elements.refreshButton.disabled = true;
  elements.refreshButton.textContent = "同步中…";
  try {
    const response = await fetch("/api/market/overview", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "读取失败");
    if (overview && data.revision < overview.revision) return;
    const changed = !overview || data.revision !== overview.revision ||
      JSON.stringify(data.users) !== JSON.stringify(overview.users);
    overview = data;
    if (changed) renderAll();
    else elements.syncTime.textContent = "状态同步于 " + new Date(data.asOf).toLocaleTimeString("zh-CN", { hour12: false });
    if (announce) showToast("账号与处置进度已同步");
  } catch (error) {
    if (!overview) {
      elements.rows.innerHTML = '<li class="list-message">账号读取失败。<button type="button" id="retryLoad">重新加载</button></li>';
      elements.detail.innerHTML = '<div class="detail-placeholder"><strong>暂时无法显示行情</strong><p>连接演示服务后可查看账号详情。</p></div>';
      elements.resultCount.textContent = "暂时无法读取";
    }
    if (announce) showToast(error.message || "读取失败", true);
  } finally {
    loading = false;
    elements.refreshButton.disabled = false;
    elements.refreshButton.textContent = "刷新数据";
  }
}

async function performAction(action) {
  if (mutating || !overview || !selectedUserId) return;
  const userId = selectedUserId;
  const assetType = selectedAssetType;
  mutating = true;
  renderDetail();
  try {
    const response = await fetch("/api/market/flow", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId, assetType, action })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "操作未完成");
    const key = userId + ":" + assetType;
    if (action === "reset") delete overview.flows[key];
    else overview.flows[key] = data.flow;
    overview.revision = data.revision;
    overview.asOf = Date.now();
    showToast({ list: "已模拟同步挂售", buyer: "已记录模拟买家意向", scenario: "示例行情已切换", reset: "本方案已重置" }[action] || "操作已完成");
  } catch (error) {
    showToast(error.message || "操作未完成", true);
  } finally {
    mutating = false;
    renderAll();
  }
}

elements.rows.addEventListener("click", event => {
  if (event.target.id === "retryLoad") return loadOverview();
  const button = event.target.closest("[data-select-id]");
  if (!button || !overview) return;
  selectedUserId = Number(button.dataset.selectId);
  selectedAssetType = "account";
  renderAll();
  document.getElementById("selectedAccountTitle")?.focus({ preventScroll: true });
  if (window.matchMedia("(max-width: 720px)").matches) {
    document.querySelector(".detail-workspace").scrollIntoView({ block: "start" });
  }
});

elements.detail.addEventListener("click", event => {
  const tab = event.target.closest("[data-asset-tab]");
  if (tab) {
    selectedAssetType = tab.dataset.assetTab;
    renderDetail();
    document.getElementById("assetTab-" + selectedAssetType).focus();
    return;
  }
  const button = event.target.closest("[data-market-action]");
  if (button) performAction(button.dataset.marketAction);
});

elements.detail.addEventListener("keydown", event => {
  const tab = event.target.closest("[data-asset-tab]");
  if (!tab || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
  event.preventDefault();
  selectedAssetType = selectedAssetType === "account" ? "item" : "account";
  renderDetail();
  document.getElementById("assetTab-" + selectedAssetType).focus();
});

function updateFilters() {
  renderAll();
  elements.rows.scrollTop = 0;
}

elements.search.addEventListener("input", updateFilters);
elements.identityFilter.addEventListener("change", updateFilters);
elements.stageFilter.addEventListener("change", updateFilters);
elements.refreshButton.addEventListener("click", () => loadOverview(true));

document.addEventListener("error", event => {
  if (event.target instanceof HTMLImageElement &&
      (event.target.classList.contains("media-image") || event.target.classList.contains("asset-art-image"))) {
    event.target.hidden = true;
  }
}, true);

loadOverview();
setInterval(() => {
  if (document.visibilityState === "visible") loadOverview();
}, 5000);
