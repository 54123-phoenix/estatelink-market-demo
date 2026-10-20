let archiveRequestSequence=0;
let archiveLastProfile=null;
function archiveResetMobile() {
  archiveRequestSequence++;
  archiveLastProfile=null;
  document.getElementById("mobileArchive").textContent=currentUserId ? "正在读取档案…" : "该演示身份不存在，请选择有效客户。";
  document.getElementById("meSummary").textContent=currentUserId ? "正在读取资料…" : "尚未选择有效客户。";
}
async function archiveLoadMobile() {
  const sequence=++archiveRequestSequence,userId=currentUserId;
  if(!userId)return;
  try {
    const data=await ArchiveUI.load(userId);
    if(sequence!==archiveRequestSequence || userId!==currentUserId)return;
    archiveLastProfile=data.user;
    document.getElementById("mobileArchive").innerHTML=
      `<div class="archive-heading"><h2>${ArchiveUI.esc(data.user.name)}的档案</h2><button type="button" class="archive-button" data-archive-refresh>刷新</button></div><p class="archive-stamp">客户 #${userId} · 资料更新于 ${ArchiveUI.esc(ArchiveUI.stamp(data.user.updatedAt))}</p>`+
      `<section class="archive-section"><h2>基本资料</h2>${ArchiveUI.profile(data.user)}</section>`+
      `<section class="archive-section"><div class="archive-heading"><h2>主账号与资产</h2><span class="archive-tag">${data.assets.length} 项</span></div><div class="archive-list">${ArchiveUI.assets(data.assets)}</div></section>`+
      `<section class="archive-section"><h2>服务合同</h2><div class="archive-list">${ArchiveUI.contracts(data.contracts)}</div></section>`;
    document.getElementById("meSummary").innerHTML=`<h2>${ArchiveUI.esc(data.user.name)} · 客户 #${userId}</h2>${ArchiveUI.details([["手机号",data.user.phone],["主账号",data.user.account],["联系状态",data.user.status]])}<p class="archive-stamp">资料由后台维护。可在“账号信息”查看完整档案。</p>`;
  } catch(error) {
    if(sequence!==archiveRequestSequence || userId!==currentUserId)return;
    const container=document.getElementById("mobileArchive");container.replaceChildren(document.createTextNode(error.message+"。"));
    const retry=document.createElement("button");retry.type="button";retry.className="archive-button";retry.dataset.archiveRefresh="";retry.textContent="重新加载";container.append(retry);
    document.getElementById("meSummary").textContent="档案读取失败，可切换到账号信息页重试。";
  }
}
document.addEventListener("click",event=>{if(event.target.closest("[data-archive-refresh]"))archiveLoadMobile();});
setInterval(()=>{if(!document.hidden && currentUserId && document.getElementById("page-assets").classList.contains("active"))archiveLoadMobile();},5000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden && document.getElementById("page-assets").classList.contains("active"))archiveLoadMobile();});
