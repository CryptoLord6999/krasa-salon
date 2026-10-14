import hashlib
import hmac
import json
import urllib.parse
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
import db

router = APIRouter()

MINI_CSS = """
:root{--bg:#0F0F12;--card:#1A1A1F;--card2:#232329;--tx:#fff;--tx2:#9A9AA3;--edge:rgba(255,255,255,.08);--hair:rgba(255,255,255,.07);--acc:#FF4D8D;--acc2:#8B5CF6;}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
body{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,'Segoe UI',Roboto,sans-serif;padding-bottom:80px;}
.wrap{max-width:640px;margin:0 auto;padding:16px;}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--edge);}
.logo{font-size:24px;font-weight:800;background:linear-gradient(135deg,#FF4D8D,#8B5CF6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.user{font-size:12px;color:var(--tx2);}
.tabs{display:flex;gap:4px;margin-bottom:16px;overflow-x:auto;padding-bottom:4px;}
.tab{flex:none;background:var(--card2);border:none;color:var(--tx2);padding:8px 14px;border-radius:999px;font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap;}
.tab.active{background:linear-gradient(135deg,#FF4D8D,#8B5CF6);color:#fff;}
.view{display:none;}
.view.active{display:block;animation:fadeIn .3s;}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.card{background:var(--card);border:1px solid var(--edge);border-radius:16px;padding:14px;margin-bottom:12px;}
.row{display:flex;align-items:center;gap:12px;padding:12px 0;}
.row+.row{border-top:1px solid var(--hair);}
.rn{flex:1;font-size:14px;font-weight:600;}
.rs{font-size:11px;color:var(--tx2);margin-top:2px;}
.rv{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums;}
.btn{background:linear-gradient(135deg,#FF4D8D,#8B5CF6);color:#fff;border:none;border-radius:12px;padding:10px 16px;font-size:13px;font-weight:700;cursor:pointer;}
.btn:active{transform:scale(.96);}
.btn.ghost{background:var(--card2);color:var(--tx);}
.btn.mini{padding:6px 10px;font-size:11px;border-radius:8px;}
.btn.danger{background:rgba(255,69,58,.15);color:#FF453A;}
.statrow{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;}
.statpill{background:var(--card2);border:1px solid var(--edge);border-radius:999px;padding:6px 10px;font-size:11px;font-weight:700;color:var(--tx2);}
.statpill b{color:var(--tx);}
.status{font-size:9px;font-weight:800;text-transform:uppercase;border-radius:999px;padding:3px 7px;}
.status.new{background:rgba(255,159,10,.16);color:#FF9F0A;}
.status.confirmed{background:rgba(48,209,88,.16);color:#30D158;}
.avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;flex:none;font-size:14px;}
.empty{color:var(--tx2);font-size:13px;text-align:center;padding:20px 0;}
.sheet{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-radius:20px 20px 0 0;padding:16px;max-height:80vh;overflow-y:auto;transform:translateY(100%);transition:transform .3s;z-index:100;}
.sheet.open{transform:translateY(0);}
.sheet h3{margin:0 0 12px;font-size:18px;}
.fg{background:var(--card2);border-radius:12px;overflow:hidden;margin-bottom:12px;}
.fr{display:flex;align-items:center;gap:10px;padding:12px;}
.fr+.fr{border-top:1px solid var(--hair);}
.fr label{width:80px;font-size:12px;color:var(--tx2);}
.fr input{flex:1;background:transparent;border:none;outline:none;color:var(--tx);font-size:14px;font-weight:600;}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);opacity:0;pointer-events:none;transition:opacity .3s;z-index:99;}
.overlay.show{opacity:1;pointer-events:auto;}
.chart-container{display:flex;align-items:flex-end;justify-content:space-around;height:150px;padding:10px 0;}
.chart-bar-wrap{display:flex;flex-direction:column;align-items:center;flex:1;}
.chart-bar{width:80%;background:linear-gradient(180deg,#FF4D8D,#8B5CF6);border-radius:4px 4px 0 0;min-height:2px;transition:height .5s;}
.chart-label{font-size:9px;color:var(--tx2);margin-top:4px;text-align:center;}
.chart-value{font-size:10px;color:var(--tx);font-weight:700;margin-bottom:2px;}
.add-btn{position:fixed;bottom:90px;right:20px;width:56px;height:56px;border-radius:50%;background:linear-gradient(135deg,#FF4D8D,#8B5CF6);border:none;color:#fff;font-size:24px;cursor:pointer;box-shadow:0 4px 20px rgba(255,77,141,.4);z-index:50;}
.add-btn:active{transform:scale(.9);}
.master-detail{background:var(--card2);border-radius:12px;padding:12px;margin-top:8px;}
.master-detail .svc{display:flex;justify-content:space-between;padding:6px 0;font-size:12px;}
"""

MINI_JS = """
const API='/api';
let currentTab='day',curDate=new Date().toISOString().split('T')[0],services=[],masters=[],clients=[];
const $=id=>document.getElementById(id);
function showTab(t){currentTab=t;document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.tab===t));
 document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));$('view-'+t).classList.add('active');
 if(t==='day')renderDay();if(t==='services')renderServices();if(t==='masters')renderMasters();
 if(t==='clients')renderClients();if(t==='stats')renderStats();}
async function loadAll(){services=await(await fetch(API+'/services')).json();masters=await(await fetch(API+'/masters')).json();}
async function renderDay(){
 const bk=await(await fetch(API+'/bookings?date='+curDate)).json();
 const total=bk.length,newC=bk.filter(b=>b.status==='new').length;
 const rev=bk.filter(b=>b.status==='confirmed'||b.status==='done').reduce((s,b)=>s+(b.price_final||b.sprice||0),0);
 $('day-stats').innerHTML=`<div class="statpill">Записей: <b>${total}</b></div>`+
   (newC?`<div class="statpill">Новых: <b>${newC}</b></div>`:'')+
   `<div class="statpill">Выручка: <b>${rev.toLocaleString('ru-RU')} ₽</b></div>`;
 $('day-list').innerHTML=bk.length?bk.map(b=>{
   const acts=b.status==='new'?`<button class="btn mini" onclick="bstat(${b.id},'confirmed')">✔</button><button class="btn mini danger" onclick="bstat(${b.id},'cancelled')">✕</button>`:
     b.status==='confirmed'?`<button class="btn mini ghost" onclick="bstat(${b.id},'done')">✓</button>`:'';
   return `<div class="row"><div class="avatar" style="background:${b.mcolor||'#8B5CF6'}">${(b.mname||'?')[0]}</div>
     <div class="rn"><b>${b.start}</b> · ${b.stitle||'—'}<div class="rs">${b.client_name||''} · ${b.mname||''}</div></div>
     <div class="rv">${b.price_final||b.sprice||0} ₽</div>${acts}</div>`;
 }).join(''):'<div class="empty">На этот день записей нет</div>';
}
function bstat(id,st){fetch(API+'/bookings/'+id+'/status',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:st})}).then(()=>renderDay());}
async function renderServices(){
 $('svc-list').innerHTML=services.map(s=>`<div class="row"><div class="rn">${s.title}<div class="rs">${s.duration} мин</div></div>
   <div class="rv">${s.price} ₽</div><button class="btn mini ghost" onclick="editSvc(${s.id})">✎</button></div>`).join('')||'<div class="empty">Услуг нет</div>';
}
function editSvc(id){const s=services.find(x=>x.id===id);if(!s)return;
 $('sheet-title').textContent='Услуга';$('sheet-fields').innerHTML=`<div class="fg">
   <div class="fr"><label>Название</label><input id="s-title" value="${s.title}"></div>
   <div class="fr"><label>Минут</label><input type="number" id="s-dur" value="${s.duration}"></div>
   <div class="fr"><label>Цена ₽</label><input type="number" id="s-price" value="${s.price}"></div></div>`;
 $('sheet').dataset.mode='svc';$('sheet').dataset.id=id;$('sheet').classList.add('open');$('overlay').classList.add('show');}
function addSvc(){$('sheet-title').textContent='Новая услуга';$('sheet-fields').innerHTML=`<div class="fg">
   <div class="fr"><label>Название</label><input id="s-title" placeholder="Например: Стрижка"></div>
   <div class="fr"><label>Минут</label><input type="number" id="s-dur" value="60"></div>
   <div class="fr"><label>Цена ₽</label><input type="number" id="s-price" value="0"></div></div>`;
 $('sheet').dataset.mode='svc_new';$('sheet').dataset.id='';$('sheet').classList.add('open');$('overlay').classList.add('show');}
async function renderMasters(){
 $('mst-list').innerHTML=masters.map(m=>`<div class="row" onclick="showMasterDetail(${m.id})" style="cursor:pointer"><div class="avatar" style="background:${m.color}">${m.name[0]}</div>
   <div class="rn">${m.name}<div class="rs">услуг: ${m.services.length}</div></div><span style="color:var(--tx2)">›</span></div>`).join('')||'<div class="empty">Мастеров нет</div>';
}
async function showMasterDetail(id){
 const m=masters.find(x=>x.id===id);if(!m)return;
 const svcNames=services.filter(s=>m.services.includes(s.id)).map(s=>s.title).join(', ')||'нет';
 $('sheet-title').textContent=m.name;$('sheet-fields').innerHTML=`<div class="master-detail">
   <div class="svc"><span>Услуги:</span><span>${svcNames}</span></div>
   <div class="svc"><span>График:</span><span>${Object.keys(m.week).length} дней</span></div>
   <div class="svc"><span>Цвет:</span><span style="color:${m.color}">●</span></div></div>`;
 $('sheet').dataset.mode='master_view';$('sheet').dataset.id=id;$('sheet').classList.add('open');$('overlay').classList.add('show');}
function addMaster(){$('sheet-title').textContent='Новый мастер';$('sheet-fields').innerHTML=`<div class="fg">
   <div class="fr"><label>Имя</label><input id="m-name" placeholder="Например: Анна"></div>
   <div class="fr"><label>Цвет</label><input id="m-color" value="#FF4D8D"></div></div>`;
 $('sheet').dataset.mode='master_new';$('sheet').dataset.id='';$('sheet').classList.add('open');$('overlay').classList.add('show');}
async function renderClients(){
 clients=await(await fetch(API+'/clients')).json();
 const sleep=clients.filter(c=>c.days>=30).length;
 $('cl-stats').innerHTML=`<div class="statpill">Клиентов: <b>${clients.length}</b></div><div class="statpill">Спящих: <b>${sleep}</b></div>`;
 $('cl-list').innerHTML=clients.length?clients.map(c=>`<div class="row">
   <div class="avatar" style="background:linear-gradient(135deg,#FF4D8D,#8B5CF6)">${(c.name||'?')[0].toUpperCase()}</div>
   <div class="rn">${c.name}<div class="rs">${c.days} дн. назад · визитов: ${c.visits}</div></div>
   <div class="rv">${c.spent||0} ₽</div></div>`).join(''):'<div class="empty">Клиентов нет</div>';
}
async function renderStats(){
 const d=await(await fetch(API+'/dashboard')).json();
 $('stat-total').innerHTML=`<div class="statpill">14 дней: <b>${d.total_bk}</b> записей</div><div class="statpill">Выручка: <b>${d.total_rev.toLocaleString('ru-RU')} ₽</b></div>`;
 const max=Math.max(...d.days.map(x=>x.cnt),1);
 $('stat-chart').innerHTML=d.days.map(x=>{
   const h=Math.max((x.cnt/max)*100,2);
   return `<div class="chart-bar-wrap"><div class="chart-value">${x.cnt}</div><div class="chart-bar" style="height:${h}px" title="${x.day}: ${x.cnt} записей, ${x.rev} ₽"></div><div class="chart-label">${x.day}</div></div>`;
 }).join('');
}
$('overlay').onclick=closeSheet;
function closeSheet(){$('sheet').classList.remove('open');$('overlay').classList.remove('show');}
$('sheet-save').onclick=async function(){
 const mode=$('sheet').dataset.mode;
 if(mode==='svc'){
   const body={title:$('s-title').value,duration:+$('s-dur').value,price:+$('s-price').value};
   await fetch(API+'/services/'+$('sheet').dataset.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   closeSheet();loadAll();renderServices();}
 else if(mode==='svc_new'){
   const body={title:$('s-title').value,duration:+$('s-dur').value,price:+$('s-price').value};
   await fetch(API+'/services',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   closeSheet();loadAll();renderServices();}
 else if(mode==='master_new'){
   const body={name:$('m-name').value,color:$('m-color').value||'#FF4D8D'};
   await fetch(API+'/masters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   closeSheet();loadAll();renderMasters();}
};
loadAll();renderDay();
"""

MINI_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>KRASA · Mini App</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>""" + MINI_CSS + """</style></head>
<body>
<div class="wrap">
  <div class="header"><div class="logo">KRASA</div><div class="user" id="user-info">Загрузка…</div></div>
  <div class="tabs">
    <button class="tab active" data-tab="day" onclick="showTab('day')">📅 День</button>
    <button class="tab" data-tab="services" onclick="showTab('services')">️ Услуги</button>
    <button class="tab" data-tab="masters" onclick="showTab('masters')">👥 Мастера</button>
    <button class="tab" data-tab="clients" onclick="showTab('clients')">👤 Клиенты</button>
    <button class="tab" data-tab="stats" onclick="showTab('stats')">📊 Статистика</button>
  </div>
  <div class="view active" id="view-day">
    <div class="statrow" id="day-stats"></div>
    <div class="card" id="day-list"></div>
  </div>
  <div class="view" id="view-services"><div class="card" id="svc-list"></div></div>
  <div class="view" id="view-masters"><div class="card" id="mst-list"></div></div>
  <div class="view" id="view-clients">
    <div class="statrow" id="cl-stats"></div>
    <div class="card" id="cl-list"></div>
  </div>
  <div class="view" id="view-stats">
    <div class="statrow" id="stat-total"></div>
    <div class="card chart-container" id="stat-chart"></div>
  </div>
</div>
<button class="add-btn" id="add-btn" onclick="handleAdd()">+</button>
<div class="overlay" id="overlay"></div>
<div class="sheet" id="sheet">
  <h3 id="sheet-title"></h3>
  <div id="sheet-fields"></div>
  <button class="btn" style="width:100%" id="sheet-save">Сохранить</button>
  <button class="btn ghost" style="width:100%;margin-top:8px" onclick="closeSheet()">Отмена</button>
</div>
<script>
function handleAdd(){
 if(currentTab==='services')addSvc();
 else if(currentTab==='masters')addMaster();
}
if(window.Telegram&&Telegram.WebApp){Telegram.WebApp.ready();Telegram.WebApp.expand();
 const u=Telegram.WebApp.initDataUnsafe.user;
 if(u)$('user-info').textContent=u.first_name||'Владелец';
}
""" + MINI_JS + """
</script>
</body></html>"""

@router.get('/mini', response_class=HTMLResponse)
def mini_app(request: Request):
    return MINI_HTML