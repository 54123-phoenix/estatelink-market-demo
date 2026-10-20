/* Archive management: edit forms never receive decrypted personal information. */
const archiveUserId = Number(new URLSearchParams(location.search).get("userId"));
let archiveSnapshot = null;
const $ = id => document.getElementById(id);
function field(key,label,value="",options={}) {
  const {type="text",required=false,max=100,min,step,choices,sensitive=false,clear=false}=options;
  const safe=ArchiveUI.esc;
  let control;
  if (choices) control=`<select name="${key}">${Object.entries(choices).map(([v,l])=>`<option value="${safe(v)}" ${v === String(value ?? "") ? "selected" : ""}>${safe(l)}</option>`).join("")}</select>`;
  else if (type === "textarea") control=`<textarea name="${key}" maxlength="${max}">${safe(value)}</textarea>`;
  else control=`<input name="${key}" type="${type}" ${required ? "required" : ""} maxlength="${max}" ${min == null ? "" : `min="${min}"`} ${step == null ? "" : `step="${step}"`} value="${sensitive ? "" : safe(value)}" placeholder="${sensitive ? "留空保持原值" : ""}">`;
  // Label encloses only its own control; clear has a separate label.
  return `<div class="archive-field"><label>${safe(label)}${control}</label>${sensitive ? `<small>当前：${safe(value || "未填写")}</small>` : ""}${clear ? `<label class="archive-clear"><input type="checkbox" name="clear_${key}">清除此项</label>` : ""}</div>`;
}
function openForm(id) { const f=$(id); f.hidden=false; f.querySelector(".archive-feedback").textContent=""; f.scrollIntoView({behavior:"smooth",block:"center"}); f.querySelector("input,select,textarea")?.focus({preventScroll:true}); }
async function reloadArchive() {
  archiveSnapshot=await ArchiveUI.load(archiveUserId);
  $("archiveTitle").textContent=archiveSnapshot.user.name+"的数字资产档案";
  const times=[archiveSnapshot.user.updatedAt,...archiveSnapshot.assets.map(x=>x.updatedAt),...archiveSnapshot.contracts.map(x=>x.updatedAt)].filter(Boolean);
  $("archiveUpdated").textContent="客户 #"+archiveUserId+" · 更新于 "+ArchiveUI.stamp(times.sort().at(-1));
  $("profileDetails").innerHTML=ArchiveUI.profile(archiveSnapshot.user);
  $("assetList").innerHTML=ArchiveUI.assets(archiveSnapshot.assets,true);
  $("contractList").innerHTML=ArchiveUI.contracts(archiveSnapshot.contracts,true);
  $("archiveStatus").textContent=""; $("archiveContent").hidden=false;
}
function editProfile() {
  const u=archiveSnapshot.user;
  $("profileFields").innerHTML=Object.entries(ArchiveUI.labels).map(([key,label])=>field(key,label,u[key],{
    sensitive:!["age","gender"].includes(key),clear:!["name","phone"].includes(key),max:key === "address" || key === "emergencyContact" ? 500 : 100,
    type:key === "age" ? "number" : "text",min:key === "age" ? 1 : undefined,
    choices:key === "gender" ? {"":"未填写","男":"男","女":"女"} : undefined
  })).join("");
  openForm("profileForm");
}
function editAsset(asset=null) {
  const a=asset || {quantity:1,currency:"CNY",disposition:"inherit"};
  $("assetForm").dataset.id=asset?.id || "";
  $("assetFormTitle").textContent=asset ? (a.assetType === "account" ? "编辑主账号" : "编辑资产") : "登记资产";
  $("assetFields").innerHTML=[
    field("name","资产名称",a.name,{required:true}),field("platform","平台",a.platform),field("game","游戏",a.game,{required:a.assetType === "account"}),
    ...(a.assetType === "account" ? [field("account","游戏账号",a.account,{sensitive:true,max:128})] : []),
    ...(a.assetType === "account" ? [] : [field("quantity","数量",a.quantity,{type:"number",min:1,step:1,required:true})]),
    field("costYuan","取得总成本（元，可不填）",a.costMinor == null ? "" : (a.costMinor/100).toFixed(2),{type:"number",min:0,step:"0.01"}),
    field("currency","成本币种（三位大写字母）",a.currency,{max:3,required:true}),
    field("acquiredAt","取得日期",a.acquiredAt,{type:"date"}),field("disposition","处置意愿",a.disposition,{choices:{"":"未填写",...ArchiveUI.disposition}}),field("notes","备注",a.notes,{type:"textarea",max:500})
  ].join(""); openForm("assetForm");
}
function editContract(contract=null) {
  const c=contract || {status:"draft"};
  $("contractForm").dataset.id=contract?.id || "";
  $("contractFormTitle").textContent=contract ? "编辑合同信息" : "登记合同";
  $("contractFields").innerHTML=[field("number","合同编号",c.number,{required:true}),field("name","合同名称",c.name,{required:true}),field("status","人工登记状态",c.status,{choices:ArchiveUI.contractStatus}),field("effectiveDate","生效日期",c.effectiveDate,{type:"date"}),field("expiryDate","到期日期",c.expiryDate,{type:"date"})].join("");openForm("contractForm");
}
async function saveForm(event,makeRequest) {
  event.preventDefault(); const form=event.currentTarget;
  const controls=[...document.querySelectorAll("#archiveContent button, #archiveContent input, #archiveContent select, #archiveContent textarea")].map(element=>[element,element.disabled]);
  const feedback=form.querySelector(".archive-feedback"); feedback.textContent="正在保存…";feedback.classList.remove("error");
  try {
    const {url,method,body}=makeRequest(new FormData(form));
    controls.forEach(([element])=>element.disabled=true);
    await ArchiveUI.request(url,method,body);
    // Treat successful write separately from a failed follow-up read.
    form.reset();
    form.hidden=true;
    $("archiveStatus").textContent="已自动保存到 SQLite。";
    try { await reloadArchive(); $("archiveStatus").textContent="已自动保存到 SQLite。"; }
    catch (_) { $("archiveStatus").textContent="已保存，但重新读取失败。请刷新页面查看。"; }
  } catch(error) {feedback.textContent=error.message;feedback.classList.add("error");}
  finally {controls.forEach(([element,disabled])=>element.disabled=disabled);}
}
$("profileForm").addEventListener("submit",event=>saveForm(event,data=>{
  const body={};
  for (const key of Object.keys(ArchiveUI.labels)) {
    if (data.has("clear_"+key)) body[key]=null;
    else if (String(data.get(key) ?? "").trim()) body[key]=key === "age" ? Number(data.get(key)) : data.get(key).trim();
  }
  return {url:"/api/archive/users/"+archiveUserId,method:"PATCH",body};
}));
$("assetForm").addEventListener("submit",event=>saveForm(event,data=>{
  const body=Object.fromEntries(data);
  body.currency=body.currency.trim().toUpperCase();
  if (!body.account) delete body.account;
  if (body.quantity !== undefined) body.quantity=Number(body.quantity);
  const amount=body.costYuan;delete body.costYuan;
  if (amount === "") body.costMinor=null;
  else {
    if (!/^(?:\d+(?:\.\d{0,2})?|\.\d{1,2})$/.test(amount)) throw new Error("金额请按普通小数填写，最多两位小数，不使用科学计数法。");
    const [whole,fraction=""]=amount.split(".");body.costMinor=Number(whole)*100+Number(fraction.padEnd(2,"0"));
    if (!Number.isSafeInteger(body.costMinor)) throw new Error("金额超出本演示可精确保存的范围。");
  }
  body.disposition=body.disposition || null;
  body.acquiredAt=body.acquiredAt || null;
  const id=$("assetForm").dataset.id;
  return {url:id ? "/api/archive/assets/"+id : "/api/archive/users/"+archiveUserId+"/assets",method:id ? "PATCH" : "POST",body};
}));
$("contractForm").addEventListener("submit",event=>saveForm(event,data=>{
  const body=Object.fromEntries(data);body.effectiveDate=body.effectiveDate || null;body.expiryDate=body.expiryDate || null;
  const id=$("contractForm").dataset.id;
  return {url:id ? "/api/archive/contracts/"+id : "/api/archive/users/"+archiveUserId+"/contracts",method:id ? "PATCH" : "POST",body};
}));
$("editProfile").addEventListener("click",editProfile);
$("addAsset").addEventListener("click",()=>editAsset());
$("addContract").addEventListener("click",()=>editContract());
document.addEventListener("click",event=>{
  const cancel=event.target.closest("[data-cancel]"); if(cancel) {const form=$(cancel.dataset.cancel);form.reset();form.hidden=true;}
  const a=event.target.closest("[data-edit-asset]");if(a) editAsset(archiveSnapshot.assets.find(x=>x.id === Number(a.dataset.editAsset)));
  const c=event.target.closest("[data-edit-contract]");if(c) editContract(archiveSnapshot.contracts.find(x=>x.id === Number(c.dataset.editContract)));
});
$("mobileLink").href="/mobile?userId="+archiveUserId+"&tab=assets";
if (!Number.isInteger(archiveUserId) || archiveUserId<=0) $("archiveStatus").textContent="请从客户池选择一位客户后管理档案。";
else reloadArchive().catch(error=>{
  $("archiveStatus").textContent=error.message+"。";
  const retry=document.createElement("button");retry.type="button";retry.textContent="重新加载";retry.addEventListener("click",()=>location.reload());$("archiveStatus").append(retry);
});
