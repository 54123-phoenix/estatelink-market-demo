/* Only masked server data belongs in these views. Identity switching is a demo. */
const ArchiveUI = (() => {
  const disposition = {inherit:"交由指定人继承",sell_then_inherit:"出售后继承",donate:"捐赠",memorial_close:"注销 / 纪念"};
  const contractStatus = {draft:"草稿",active:"登记为有效",terminated:"已终止"};
  const labels = {name:"姓名",phone:"手机号",idCard:"身份证号",email:"邮箱",address:"地址",emergencyContact:"紧急联系人",gender:"性别",age:"年龄"};
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  async function request(path, method="GET", body) {
    const response = await fetch(path, {method,cache:"no-store", ...(body === undefined ? {} : {headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "请求未完成，请重试");
    return data;
  }
  function stamp(value) {
    if (!value) return "暂无更新记录";
    const d = new Date(typeof value === "number" && value < 1e12 ? value * 1000 : value);
    return Number.isNaN(d.getTime()) ? "暂无更新记录" : d.toLocaleString("zh-CN",{hour12:false});
  }
  function money(value, currency="CNY") {
    return value == null ? "未填写" : (value/100).toLocaleString("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2}) + " " + currency;
  }
  function details(pairs) { return '<dl class="archive-grid">'+pairs.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v === null || v === undefined || v === "" ? "未填写" : v)}</dd></div>`).join("")+"</dl>"; }
  function profile(user) { return details(Object.entries(labels).map(([key,label])=>[label,user[key]])); }
  function assets(items, editable=false) {
    if (!items.length) return '<p class="archive-empty">尚未登记资产。请在后台添加。</p>';
    return items.map(asset=>`<article class="archive-card"><span class="archive-tag">${asset.assetType === "account" ? "主游戏账号" : "账号内资产"}</span><span class="archive-tag">${asset.hasMarket ? "已关联模拟行情" : "暂无行情"}</span><h3>${esc(asset.name)}</h3>${details([["平台 / 游戏",[asset.platform,asset.game].filter(Boolean).join(" / ")],["账号标识",asset.account],["数量",asset.quantity],["取得总成本",money(asset.costMinor,asset.currency)],["取得日期",asset.acquiredAt],["处置意愿",disposition[asset.disposition] || asset.disposition]])}${asset.notes ? `<p>${esc(asset.notes)}</p>` : ""}<p class="archive-stamp">更新于 ${esc(stamp(asset.updatedAt))}</p>${editable ? `<button type="button" data-edit-asset="${Number(asset.id)}">编辑${asset.assetType === "account" ? "主账号" : "资产"}</button>` : ""}</article>`).join("");
  }
  function contracts(items, editable=false) {
    if (!items.length) return '<p class="archive-empty">暂无合同登记信息。</p>';
    return items.map(c=>`<article class="archive-card"><span class="archive-tag">${esc(contractStatus[c.status] || c.status)}</span><h3>${esc(c.name)}</h3>${details([["合同编号",c.number],["生效日期",c.effectiveDate],["到期日期",c.expiryDate]])}<p>仅记录合同信息，状态由人工登记，不代表已完成签署验证。</p>${editable ? `<button type="button" data-edit-contract="${Number(c.id)}">编辑合同</button>` : ""}</article>`).join("");
  }
  async function load(userId) {
    const base="/api/archive/users/"+userId;
    const [user,assets,contracts]=await Promise.all([request(base),request(base+"/assets"),request(base+"/contracts")]);
    return {user,assets:assets.assets,contracts:contracts.contracts};
  }
  return {esc,request,stamp,money,details,profile,assets,contracts,load,disposition,contractStatus,labels};
})();
