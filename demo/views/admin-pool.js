let users=[],autoEnabled=false,currentUserId=null;
const tbody=document.getElementById("userTableBody");
const searchInput=document.getElementById("searchInput"),statusFilter=document.getElementById("statusFilter");
const DEFAULT_SMS="【用户池平台】尊敬的用户：我们正在进行例行的账户信息核对，请您在方便时打开本消息回复确认。如给您带来不便，敬请谅解。";
const priority={"疑似已故":0,"已故":1,"未知":2,"健在":3};
function showToast(msg,isError=false) { const t=document.getElementById("toast");t.textContent=msg;t.className="toast"+(isError ? " error" : "");t.style.display="block";setTimeout(()=>t.style.display="none",3000); }
function render() {
  const keyword=searchInput.value.trim().toLowerCase();
  const list=users.filter(u=>(!statusFilter.value || u.status===statusFilter.value) && (!keyword || [u.name,u.id,u.phone,u.game,u.account].some(x=>String(x ?? "").toLowerCase().includes(keyword)))).sort((a,b)=>(priority[a.status]??9)-(priority[b.status]??9));
  tbody.replaceChildren();
  for (const u of list) {
    const row=document.createElement("tr");row.className=u.status==="疑似已故" ? "row-suspected" : u.status==="已故" ? "row-dead" : "";
    for (const value of [u.name,u.gender,u.age,u.idCard,u.game,u.account,u.phone,u.status,u.missedCount+"/3"]) {
      const cell=document.createElement("td");cell.textContent=value ?? "—";row.append(cell);
    }
    if(u.pending) { const hint=document.createElement("div");hint.className="pending-hint";hint.textContent="等待回复 ";const cd=document.createElement("span");cd.className="cd";cd.dataset.deadline=Date.now()+u.pending.remainMs;hint.append(cd," 秒");row.lastChild.append(hint); }
    const actions=document.createElement("td");
    const button=document.createElement("button");button.className="btn-sms";button.textContent=u.pending ? "等待回复…" : "发送短信";button.disabled=Boolean(u.pending);button.addEventListener("click",()=>openModal(u.id));actions.append(button);
    if(u.status==="疑似已故") { const confirmButton=document.createElement("button");confirmButton.className="btn-confirm";confirmButton.textContent="确认已故";confirmButton.addEventListener("click",()=>confirmDead(u.id));actions.append(confirmButton); }
    for(const [label,url] of [["管理档案","/archive-admin?userId="+u.id],["管理行情","/market-admin?userId="+u.id],...(u.status==="已故" ? [["继承人预览","/mobile?userId="+u.id+"&tab=sell"]] : [])]) {
      const link=document.createElement("a");link.className="btn-market";link.textContent=label;link.href=url;actions.append(link);
    }
    row.append(actions);tbody.append(row);
  }
  if(!list.length) { const row=document.createElement("tr"),cell=document.createElement("td");cell.colSpan=10;cell.className="empty";cell.textContent="暂无匹配的客户";row.append(cell);tbody.append(row); }
}
async function loadUsers() {
  try {const data=await ArchiveUI.request("/api/users");users=data.users;updateAutoUI(data.autoSend);render();}
  catch(error) {showToast(error.message,true);}
}
function updateAutoUI(data) {autoEnabled=data.enabled;const b=document.getElementById("autoBtn");b.textContent="自动发送："+(autoEnabled ? "开" : "关");b.classList.toggle("on",autoEnabled);document.getElementById("autoHint").textContent=autoEnabled ? "每 "+data.intervalSec+" 秒询问 "+data.batch+" 位" : "";}
async function toggleAuto() {try {await ArchiveUI.request("/api/auto-send","POST",{enabled:!autoEnabled});await loadUsers();}catch(e){showToast(e.message,true);}}
async function saveData() {try {const data=await ArchiveUI.request("/api/save","POST",{});showToast(data.message || "所有变更均已自动保存到 SQLite");}catch(e){showToast(e.message,true);}}
function openModal(id) {const u=users.find(x=>x.id===id);if(!u)return;currentUserId=id;document.getElementById("smsTarget").textContent="收件人："+u.name+"（"+u.phone+"）";document.getElementById("smsContent").value=DEFAULT_SMS;document.getElementById("smsModal").classList.add("show");}
function closeModal() {document.getElementById("smsModal").classList.remove("show");}
async function confirmSend() {
  const button=document.querySelector("#smsModal .btn-send");button.disabled=true;
  try {await ArchiveUI.request("/api/sms/send","POST",{userId:currentUserId,content:document.getElementById("smsContent").value.trim()});closeModal();showToast("模拟短信已发送");await loadUsers();}
  catch(e){showToast(e.message,true);}finally{button.disabled=false;}
}
async function confirmDead(id) {if(!confirm("确认已完成线下核查？此操作将客户标记为已故。"))return;try{await ArchiveUI.request("/api/users/confirm-dead","POST",{userId:id});await loadUsers();}catch(e){showToast(e.message,true);}}
function openAddModal() {for(const id of ["f_name","f_age","f_phone","f_idCard","f_game","f_account"])document.getElementById(id).value="";document.getElementById("addModal").classList.add("show");document.getElementById("f_name").focus();}
function closeAddModal() {const modal=document.getElementById("addModal");modal.classList.remove("show");modal.querySelectorAll("input").forEach(input=>input.value="");}
async function submitAddUser() {
  const button=document.querySelector("#addModal .btn-send");button.disabled=true;
  const body={};for(const key of ["name","gender","age","phone","idCard","game","account"]){const value=document.getElementById("f_"+key).value.trim();if(value)body[key]=key==="age" ? Number(value) : value;}
  try {const data=await ArchiveUI.request("/api/users/add","POST",body);location.href="/archive-admin?userId="+data.userId;}
  catch(e){showToast(e.message,true);button.disabled=false;}
}
for(const id of ["smsModal","addModal"])document.getElementById(id).addEventListener("click",e=>{if(e.target.id===id){if(id==="addModal")closeAddModal();else closeModal();}});
searchInput.addEventListener("input",render);statusFilter.addEventListener("change",render);
loadUsers();setInterval(()=>{if(!document.hidden)loadUsers();},2000);
setInterval(()=>document.querySelectorAll(".cd").forEach(el=>el.textContent=Math.max(0,Math.ceil((Number(el.dataset.deadline)-Date.now())/1000))),1000);
