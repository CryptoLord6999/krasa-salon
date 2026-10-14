import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
import db
import slots

router = APIRouter()

# ---------- API КЛИЕНТА ----------

@router.get('/api/client/services')
def c_services():
    return db.q('SELECT id,title,duration,price FROM services WHERE salon_id=1 AND active=1 ORDER BY price')

@router.get('/api/client/masters')
def c_masters():
    ms = db.q('SELECT id,name,color FROM masters WHERE salon_id=1 AND active=1 ORDER BY id')
    for m in ms:
        m['services'] = [r['service_id'] for r in db.q('SELECT service_id FROM master_services WHERE master_id=?', (m['id'],))]
    return ms

@router.get('/api/client/slots')
def c_slots(date: str, service_id: int, master_id: int = 0):
    if master_id:
        return [{'time': t, 'master_id': master_id, 'master_name': ''} for t in slots.free_slots(master_id, service_id, date)]
    return slots.free_slots_any(service_id, date)

@router.post('/api/client/bookings')
def c_book(p: dict):
    svc = db.q('SELECT duration FROM services WHERE id=? AND active=1', (p.get('service_id'),))
    if not svc:
        raise HTTPException(400, 'service')
    if p['start'] not in slots.free_slots(p['master_id'], p['service_id'], p['date']):
        raise HTTPException(409, 'slot taken')
    end = slots._to_hhmm(slots._to_min(p['start']) + svc[0]['duration'])
    bid = db.exe("""INSERT INTO bookings(salon_id,master_id,service_id,client_tg_id,client_key,client_name,client_phone,date,start,end,status,comment,created)
                    VALUES(1,?,?,0,?,?,?,?,?,?,'new',?,datetime('now'))""",
                 (p['master_id'], p['service_id'], p.get('client_key', ''), p.get('client_name', ''),
                  p.get('client_phone', ''), p['date'], p['start'], end, p.get('comment', '')))
    return {'id': bid, 'status': 'new'}

@router.get('/api/client/bookings')
def c_my(client_key: str):
    return db.q("""SELECT b.*, s.title stitle, s.duration sdur, m.name mname, m.color mcolor FROM bookings b
                   LEFT JOIN services s ON s.id=b.service_id LEFT JOIN masters m ON m.id=b.master_id
                   WHERE b.client_key=? AND b.status!='cancelled' ORDER BY b.date, b.start""", (client_key,))

@router.post('/api/client/bookings/{bid}/cancel')
def c_cancel(bid: int, p: dict):
    b = db.q('SELECT * FROM bookings WHERE id=?', (bid,))
    if not b or b[0]['client_key'] != p.get('client_key'):
        raise HTTPException(403)
    if b[0]['status'] in ('done', 'cancelled'):
        raise HTTPException(409)
    salon = db.q('SELECT cancel_hours FROM salons WHERE id=1')[0]
    dt = datetime.datetime.fromisoformat(b[0]['date'] + 'T' + b[0]['start'])
    if dt - datetime.datetime.now() < datetime.timedelta(hours=salon['cancel_hours'] or 0):
        raise HTTPException(409, f'Отмена не позднее {salon["cancel_hours"]} ч до записи')
    db.exe("UPDATE bookings SET status='cancelled' WHERE id=?", (bid,))
    return {'ok': True}

@router.post('/api/client/bookings/{bid}/move')
def c_move(bid: int, p: dict):
    b = db.q('SELECT * FROM bookings WHERE id=?', (bid,))
    if not b or b[0]['client_key'] != p.get('client_key'):
        raise HTTPException(403)
    if b[0]['status'] in ('done', 'cancelled'):
        raise HTTPException(409)
    if p['start'] not in slots.free_slots(b[0]['master_id'], b[0]['service_id'], p['date']):
        raise HTTPException(409, 'slot taken')
    dur = db.q('SELECT duration FROM services WHERE id=?', (b[0]['service_id'],))[0]['duration']
    end = slots._to_hhmm(slots._to_min(p['start']) + dur)
    db.exe('UPDATE bookings SET date=?,start=?,end=? WHERE id=?', (p['date'], p['start'], end, bid))
    return {'ok': True}

# ---------- СТРАНИЦА КЛИЕНТА ----------

CSS = """
:root{--bg:#0F0F12;--card:#1A1A1F;--card2:#232329;--tx:#fff;--tx2:#9A9AA3;--edge:rgba(255,255,255,.08);--hair:rgba(255,255,255,.07);--acc:#FF4D8D;--acc2:#8B5CF6;}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
body{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,'Segoe UI',Roboto,sans-serif;-webkit-font-smoothing:antialiased;}
.wrap{max-width:560px;margin:0 auto;padding:16px 16px 96px;}
.head{display:flex;gap:12px;align-items:center;margin-bottom:16px;}
.logo{width:54px;height:54px;border-radius:18px;background:linear-gradient(135deg,#FF4D8D,#8B5CF6);display:flex;align-items:center;justify-content:center;font-size:26px;box-shadow:0 12px 30px rgba(255,77,141,.35);flex:none;}
.salon{font-size:22px;font-weight:800;letter-spacing:-.3px;}
.addr{font-size:12px;color:var(--tx2);margin-top:2px;}
.view{display:none;} .view.active{display:block;animation:vin .3s cubic-bezier(.32,.72,0,1);}
@keyframes vin{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.steps{display:flex;gap:6px;margin-bottom:16px;}
.steps i{flex:1;height:4px;border-radius:2px;background:var(--card2);}
.steps i.on{background:linear-gradient(90deg,#FF4D8D,#8B5CF6);}
.stitle{font-size:24px;font-weight:800;letter-spacing:-.4px;margin:0 0 4px;}
.ssub{font-size:13px;color:var(--tx2);margin-bottom:14px;}
.back{border:none;background:none;color:var(--tx2);font-size:13px;font-weight:700;cursor:pointer;padding:0;margin-bottom:10px;}
.card{background:var(--card);border:1px solid var(--edge);border-radius:16px;margin-bottom:10px;cursor:pointer;transition:transform .12s,border-color .12s;}
.card:active{transform:scale(.98);}
.card.sel{border-color:transparent;background:linear-gradient(var(--card),var(--card)) padding-box,linear-gradient(135deg,#FF4D8D,#8B5CF6) border-box;border:1.5px solid transparent;}
.svc{display:flex;align-items:center;gap:12px;padding:15px 16px;}
.svc .t{flex:1;font-size:15px;font-weight:600;}
.svc .d{font-size:12px;color:var(--tx2);margin-top:2px;}
.svc .p{font-size:16px;font-weight:800;font-variant-numeric:tabular-nums;background:linear-gradient(135deg,#FF4D8D,#8B5CF6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.mrow{display:flex;align-items:center;gap:12px;padding:14px 16px;}
.av{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;flex:none;}
.dates{display:flex;gap:8px;overflow-x:auto;padding:2px 2px 12px;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;}
.dates::-webkit-scrollbar{display:none;}
.dchip{min-width:56px;scroll-snap-align:start;border:1px solid var(--edge);background:var(--card);border-radius:14px;padding:9px 4px;text-align:center;cursor:pointer;flex:none;}
.dchip .wd{font-size:10px;color:var(--tx2);font-weight:700;text-transform:uppercase;}
.dchip .dn{font-size:17px;font-weight:800;margin-top:2px;}
.dchip.on{background:linear-gradient(135deg,#FF4D8D,#8B5CF6);border-color:transparent;}
.dchip.on .wd{color:rgba(255,255,255,.8);}
.slotgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(76px,1fr));gap:8px;margin-top:4px;}
.slot{border:1px solid var(--edge);background:var(--card);border-radius:12px;padding:11px 4px;text-align:center;font-size:14px;font-weight:700;cursor:pointer;font-variant-numeric:tabular-nums;}
.slot:active{transform:scale(.93);}
.slot .mn{display:block;font-size:9px;color:var(--tx2);font-weight:600;margin-top:2px;}
.fg{background:var(--card);border:1px solid var(--edge);border-radius:16px;overflow:hidden;margin-bottom:12px;}
.fr{display:flex;align-items:center;gap:10px;padding:13px 16px;}
.fr+.fr{border-top:1px solid var(--hair);}
.fr label{width:88px;font-size:13px;color:var(--tx2);flex:none;}
.fr input{flex:1;background:transparent;border:none;outline:none;color:var(--tx);font-size:15px;font-weight:600;text-align:right;}
.fr input.text{text-align:left;}
.sum{font-size:13px;color:var(--tx2);margin:0 2px 12px;line-height:1.6;}
.sum b{color:var(--tx);}
.btn{width:100%;border:none;border-radius:14px;padding:15px;font-size:16px;font-weight:800;cursor:pointer;background:linear-gradient(135deg,#FF4D8D,#8B5CF6);color:#fff;box-shadow:0 10px 28px rgba(255,77,141,.35);}
.btn:active{transform:scale(.97);}
.btn.ghost{background:var(--card2);color:var(--tx);box-shadow:none;border:1px solid var(--edge);}
.okwrap{width:96px;height:96px;margin:14px auto;border-radius:50%;background:linear-gradient(135deg,#FF4D8D,#8B5CF6);display:flex;align-items:center;justify-content:center;animation:pop .5s cubic-bezier(.32,.72,0,1);}
.okwrap svg{width:44px;height:44px;stroke:#fff;stroke-width:3;fill:none;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:40;stroke-dashoffset:40;animation:draw .6s .25s forwards;}
@keyframes pop{from{transform:scale(.5);opacity:0}} @keyframes draw{to{stroke-dashoffset:0}}
.my{background:var(--card);border:1px solid var(--edge);border-radius:16px;padding:14px 16px;margin-bottom:10px;}
.my .top{display:flex;justify-content:space-between;align-items:center;gap:8px;}
.my .dt{font-size:16px;font-weight:800;}
.my .meta{font-size:13px;color:var(--tx2);margin-top:4px;line-height:1.5;}
.status{font-size:10px;font-weight:800;letter-spacing:.6px;text-transform:uppercase;border-radius:999px;padding:4px 9px;}
.status.new{background:rgba(255,159,10,.16);color:#FF9F0A;}
.status.confirmed{background:rgba(48,209,88,.16);color:#30D158;}
.status.done{background:rgba(142,142,147,.18);color:#9A9AA3;}
.acts{display:flex;gap:8px;margin-top:12px;}
.acts button{flex:1;border:none;border-radius:11px;padding:10px;font-size:13px;font-weight:700;cursor:pointer;background:var(--card2);color:var(--tx);border:1px solid var(--edge);}
.acts button.red{color:#FF453A;background:rgba(255,69,58,.12);border-color:transparent;}
.sec{padding:12px 2px 8px;font-size:11px;font-weight:700;color:var(--tx2);text-transform:uppercase;letter-spacing:1.2px;}
.empty{color:var(--tx2);font-size:13px;text-align:center;padding:22px 0;}
.tabbar{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:560px;display:flex;background:rgba(26,26,31,.85);backdrop-filter:blur(20px);border-top:1px solid var(--edge);padding:8px 8px 22px;z-index:30;}
.tab{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;background:none;border:none;color:var(--tx2);font-size:10px;font-weight:700;cursor:pointer;padding:4px 0;}
.tab svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;}
.tab.active{color:var(--acc);}
#toast{position:fixed;bottom:96px;left:50%;transform:translateX(-50%) translateY(16px);background:linear-gradient(135deg,#FF4D8D,#8B5CF6);color:#fff;font-weight:700;padding:10px 20px;border-radius:999px;opacity:0;transition:.3s;z-index:70;pointer-events:none;font-size:14px;max-width:86%;text-align:center;}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0);}
"""

JS = """
const API='/api/client';
const WD=['вс','пн','вт','ср','чт','пт','сб'];
let key=localStorage.krasa_key;
if(!key){key='web-'+Math.random().toString(36).slice(2)+Date.now().toString(36);localStorage.krasa_key=key;}
let services=[],masters=[],step=1,selSvc=null,selMst=0,selDate=localISO(0),selSlot=null,selSlotMaster=null,moveId=null;
function localISO(off){const d=new Date();d.setDate(d.getDate()+(off||0));return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function f(u,o){return fetch(u,o).then(r=>{if(!r.ok)return r.json().then(j=>{throw new Error(j.detail||'Ошибка')});return r.json();});}
function toast(m){const t=$('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2200);}
function $(id){return document.getElementById(id);}
function showTab(v){document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));$('view-'+v).classList.add('active');
 document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.view===v));
 if(v==='my')renderMy();}
async function init(){services=await f(API+'/services');masters=await f(API+'/masters');renderStep();}
function steps(n){let h='';for(let i=1;i<=4;i++)h+='<i class="'+(i<=n?'on':'')+'"></i>';return h;}
function renderStep(){
 $('steps').innerHTML=steps(Math.min(step,4));
 const w=$('wizard');
 if(step===1){
  w.innerHTML='<div class="stitle">Выберите услугу</div><div class="ssub">шаг 1 из 4</div>'+
   services.map(s=>'<div class="card svc'+(selSvc&&selSvc.id===s.id?' sel':'')+'" onclick="pickSvc('+s.id+')"><div class="t">'+s.title+'<div class="d">'+s.duration+' мин</div></div><div class="p">'+s.price+' ₽</div></div>').join('');
 } else if(step===2){
  const ms=masters.filter(m=>m.services.includes(selSvc.id));
  w.innerHTML='<button class="back" onclick="step=1;renderStep()">← назад</button><div class="stitle">К кому запишем?</div><div class="ssub">шаг 2 из 4</div>'+
   '<div class="card mrow'+(selMst===0?' sel':'')+'" onclick="pickMst(0)"><div class="av" style="background:linear-gradient(135deg,#FF4D8D,#8B5CF6)">✦</div><div class="rn" style="flex:1;font-weight:600">Любой свободный мастер</div></div>'+
   ms.map(m=>'<div class="card mrow'+(selMst===m.id?' sel':'')+'" onclick="pickMst('+m.id+')"><div class="av" style="background:'+m.color+'">'+m.name[0]+'</div><div style="flex:1;font-weight:600">'+m.name+'</div></div>').join('');
 } else if(step===3){
  let dates='';for(let i=0;i<14;i++){const d=localISO(i);const dt=new Date(d);
   dates+='<div class="dchip'+(d===selDate?' on':'')+'" onclick="pickDate(\\''+d+'\\')"><div class="wd">'+(i===0?'сегодня':WD[dt.getDay()])+'</div><div class="dn">'+dt.getDate()+'</div></div>';}
  w.innerHTML='<button class="back" onclick="step=2;renderStep()">← назад</button><div class="stitle">Когда удобно?</div><div class="ssub">шаг 3 из 4</div>'+
   '<div class="dates">'+dates+'</div><div id="slots" class="empty">Загружаю окна…</div>';
  loadSlots();
 } else if(step===4){
  const m=selMst?masters.find(x=>x.id===selMst):null;
  w.innerHTML='<button class="back" onclick="step=3;renderStep()">← назад</button><div class="stitle">Подтверждение</div><div class="ssub">шаг 4 из 4</div>'+
   '<div class="sum"><b>'+selSvc.title+'</b> · '+selSvc.duration+' мин · '+selSvc.price+' ₽<br>'+
   (m?m.name:'любой мастер')+' · '+selDate.slice(8)+'.'+selDate.slice(5,7)+' в '+selSlot+'</div>'+
   '<div class="fg"><div class="fr"><label>Имя</label><input class="text" id="c-name" value="'+(localStorage.krasa_name||'')+'"></div>'+
   '<div class="fr"><label>Телефон</label><input class="text" id="c-phone" value="'+(localStorage.krasa_phone||'')+'"></div>'+
   '<div class="fr"><label>Коммент</label><input class="text" id="c-comment" placeholder="пожелания"></div></div>'+
   '<button class="btn" onclick="submitBook()">Записаться</button>';
 } else if(step===5){
  w.innerHTML='<div class="okwrap"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>'+
   '<div class="stitle" style="text-align:center">Вы записаны!</div>'+
   '<div class="ssub" style="text-align:center">Салон подтвердит запись в ближайшее время</div>'+
   '<button class="btn" onclick="showTab(\\'my\\')">Мои записи</button>'+
   '<button class="btn ghost" style="margin-top:8px" onclick="resetWizard()">Записаться ещё</button>';
 }
}
function pickSvc(id){selSvc=services.find(s=>s.id===id);if(selMst&&!masters.find(m=>m.id===selMst).services.includes(id))selMst=0;step=2;renderStep();}
function pickMst(id){selMst=id;step=3;renderStep();}
function pickDate(d){selDate=d;selSlot=null;renderStep();}
async function loadSlots(){
 const sl=await f(API+'/slots?date='+selDate+'&service_id='+selSvc.id+'&master_id='+selMst);
 $('slots').outerHTML=sl.length?'<div id="slots" class="slotgrid">'+sl.map(s=>'<div class="slot" onclick="pickSlot(\\''+s.time+'\\','+s.master_id+',\\''+(s.master_name||'').replace(/'/g,'')+'\\')">'+s.time+(s.master_name?'<span class="mn">'+s.master_name+'</span>':'')+'</div>').join('')+'</div>':'<div id="slots" class="empty">На этот день окон нет — листайте даты</div>';
}
function pickSlot(t,mid,mn){selSlot=t;selSlotMaster=mid;
 if(moveId){doMove();return;}
 step=4;renderStep();}
async function submitBook(){
 const name=$('c-name').value.trim(),phone=$('c-phone').value.trim();
 if(!name)return toast('Как вас зовут?');
 localStorage.krasa_name=name;localStorage.krasa_phone=phone;
 try{
  await f(API+'/bookings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
   service_id:selSvc.id,master_id:selSlotMaster||selMst,date:selDate,start:selSlot,
   client_key:key,client_name:name,client_phone:phone,comment:$('c-comment').value.trim()})});
  step=5;renderStep();
 }catch(e){toast(e.message);}
}
async function doMove(){
 try{await f('/api/client/bookings/'+moveId+'/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client_key:key,date:selDate,start:selSlot})});
  toast('Перенесено ✓');moveId=null;showTab('my');}catch(e){toast(e.message);}
}
function resetWizard(){step=1;selSvc=null;selMst=0;selSlot=null;moveId=null;selDate=localISO(0);renderStep();showTab('book');}
async function renderMy(){
 const list=await f(API+'/bookings?client_key='+encodeURIComponent(key));
 const now=new Date();
 const up=list.filter(b=>(b.status==='new'||b.status==='confirmed')&&new Date(b.date+'T'+b.end)>=now);
 const past=list.filter(b=>!up.includes(b));
 $('my-up').innerHTML=up.length?up.map(b=>'<div class="my"><div class="top"><div class="dt">'+b.date.slice(8)+'.'+b.date.slice(5,7)+' · '+b.start+'</div><span class="status '+b.status+'">'+(b.status==='new'?'ждёт подтверждения':'подтверждена')+'</span></div>'+
  '<div class="meta">'+b.stitle+' · '+b.mname+'<br>'+b.start+'–'+b.end+'</div>'+
  '<div class="acts"><button onclick="startMove('+b.id+')">Перенести</button><button class="red" onclick="cancelB('+b.id+')">Отменить</button></div></div>').join(''):'<div class="empty">Пока нет предстоящих записей</div>';
 $('my-past').innerHTML=past.length?past.map(b=>'<div class="my" style="opacity:.6"><div class="top"><div class="dt">'+b.date.slice(8)+'.'+b.date.slice(5,7)+' · '+b.start+'</div><span class="status '+b.status+'">'+(b.status==='done'?'готова':'отменена')+'</span></div><div class="meta">'+b.stitle+' · '+b.mname+'</div></div>').join(''):'<div class="empty">История пуста</div>';
}
function startMove(id){const b=null;moveId=id;
 f(API+'/bookings?client_key='+encodeURIComponent(key)).then(list=>{const x=list.find(y=>y.id===id);
  selSvc=services.find(s=>s.id===x.service_id);selMst=x.master_id;step=3;showTab('book');renderStep();});}
function cancelB(id){if(!confirm('Отменить запись?'))return;
 f('/api/client/bookings/'+id+'/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client_key:key})})
 .then(()=>{toast('Запись отменена');renderMy();}).catch(e=>toast(e.message));}
init();
"""

CLIENT_PAGE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>KRASA · запись</title>
<style>""" + CSS + """</style></head>
<body><div class="wrap">
<div class="head">
  <div class="logo">💇‍♀️</div>
  <div><div class="salon">KRASA</div><div class="addr">бьюти-спейс · запись онлайн</div></div>
</div>
<div class="view active" id="view-book">
  <div class="steps" id="steps"></div>
  <div id="wizard"></div>
</div>
<div class="view" id="view-my">
  <div class="sec">Предстоящие</div><div id="my-up"></div>
  <div class="sec">История</div><div id="my-past"></div>
</div>
</div>
<nav class="tabbar">
  <button class="tab active" data-view="book" onclick="showTab('book')"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M12 11v6M9 14h6"/></svg><span>Запись</span></button>
  <button class="tab" data-view="my" onclick="showTab('my')"><svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.4"/><path d="M5 20c.8-3.6 3.4-5.6 7-5.6s6.2 2 7 5.6"/></svg><span>Мои записи</span></button>
</nav>
<div id="toast"></div>
<script>""" + JS + """</script>
</body></html>"""

@router.get('/m', response_class=HTMLResponse)
def client_page():
    return CLIENT_PAGE