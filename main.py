import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import uvicorn
import db
import slots
import client
import mini

try:
    import config
    import bot as tg_bot
    HAS_BOT = True
except Exception as e:
    HAS_BOT = False
    print('⚠️ Бот-модули не найдены:', e)

app = FastAPI(title='KRASA')
app.include_router(client.router)
app.include_router(mini.router)

@app.on_event('startup')
async def startup():
    db.init_db()
    db.exe("CREATE TABLE IF NOT EXISTS promos(id INTEGER PRIMARY KEY, client_tg_id INTEGER, code TEXT, percent INTEGER, note TEXT, created TEXT, used_at TEXT)")
    try:
        cols = [r['name'] for r in db.q('PRAGMA table_info(bookings)')]
        if 'promo' not in cols:
            db.exe("ALTER TABLE bookings ADD COLUMN promo TEXT DEFAULT ''")
        if 'discount' not in cols:
            db.exe('ALTER TABLE bookings ADD COLUMN discount INTEGER DEFAULT 0')
        if 'price_final' not in cols:
            db.exe('ALTER TABLE bookings ADD COLUMN price_final INTEGER DEFAULT 0')
    except Exception:
        pass
    print('✨ KRASA: сервер жив')
    if HAS_BOT and getattr(config, 'BOT_TOKEN', 'XXXXXXXXX') != 'XXXXXXXXX':
        asyncio.create_task(tg_bot.polling_loop())

# ---------- СИСТЕМНЫЕ ----------

@app.get('/api/ping')
def ping():
    return {'ok': True, 'services': len(db.q('SELECT id FROM services WHERE salon_id=1'))}

@app.get('/')
def root():
    return RedirectResponse('/m')

# ---------- УСЛУГИ ----------

@app.get('/api/services')
def api_services():
    return db.q('SELECT * FROM services WHERE salon_id=1 AND active=1 ORDER BY id')

@app.post('/api/services')
def api_service_add(p: dict):
    sid = db.exe('INSERT INTO services(salon_id,title,duration,price) VALUES(1,?,?,?)',
                 (p.get('title', ''), int(p.get('duration', 60)), int(p.get('price', 0))))
    return {'id': sid}

@app.put('/api/services/{sid}')
def api_service_edit(sid: int, p: dict):
    db.exe('UPDATE services SET title=?,duration=?,price=? WHERE id=?',
           (p.get('title', ''), int(p.get('duration', 60)), int(p.get('price', 0)), sid))
    return {'ok': True}

@app.delete('/api/services/{sid}')
def api_service_del(sid: int):
    db.exe('UPDATE services SET active=0 WHERE id=?', (sid,))
    return {'ok': True}

# ---------- МАСТЕРА ----------

@app.get('/api/masters')
def api_masters():
    ms = db.q('SELECT * FROM masters WHERE salon_id=1 AND active=1 ORDER BY id')
    for m in ms:
        m['services'] = [r['service_id'] for r in db.q('SELECT service_id FROM master_services WHERE master_id=?', (m['id'],))]
        m['week'] = {str(r['weekday']): {'start': r['start'], 'end': r['end']} for r in db.q('SELECT weekday,start,end FROM master_week WHERE master_id=?', (m['id'],))}
        m['offs'] = db.q('SELECT * FROM master_off WHERE master_id=? ORDER BY date', (m['id'],))
    return ms

@app.post('/api/masters')
def api_master_add(p: dict):
    mid = db.exe('INSERT INTO masters(salon_id,name,color) VALUES(1,?,?)', (p.get('name', ''), p.get('color', '#FF4D8D')))
    return {'id': mid}

@app.put('/api/masters/{mid}')
def api_master_edit(mid: int, p: dict):
    db.exe('UPDATE masters SET name=?,color=? WHERE id=?', (p.get('name', ''), p.get('color', '#FF4D8D'), mid))
    return {'ok': True}

@app.put('/api/masters/{mid}/services')
def api_master_services(mid: int, p: dict):
    db.exe('DELETE FROM master_services WHERE master_id=?', (mid,))
    for sid in p.get('ids', []):
        db.exe('INSERT INTO master_services(master_id,service_id) VALUES(?,?)', (mid, sid))
    return {'ok': True}

@app.put('/api/masters/{mid}/week')
def api_master_week(mid: int, p: dict):
    db.exe('DELETE FROM master_week WHERE master_id=?', (mid,))
    for wd, v in (p.get('week') or {}).items():
        if v.get('on'):
            db.exe('INSERT INTO master_week(master_id,weekday,start,end) VALUES(?,?,?,?)',
                   (mid, int(wd), v.get('start', '10:00'), v.get('end', '20:00')))
    return {'ok': True}

@app.post('/api/masters/{mid}/off')
def api_master_off(mid: int, p: dict):
    db.exe('INSERT INTO master_off(master_id,date,start,end,reason) VALUES(?,?,?,?,?)',
           (mid, p.get('date', ''), p.get('start', '00:00'), p.get('end', '23:59'), p.get('reason', '')))
    return {'ok': True}

@app.delete('/api/off/{oid}')
def api_off_del(oid: int):
    db.exe('DELETE FROM master_off WHERE id=?', (oid,))
    return {'ok': True}

# ---------- СЛОТЫ И ЗАПИСИ ----------

@app.get('/api/slots')
def api_slots(date: str, service_id: int, master_id: int = 0):
    if master_id:
        return [{'time': t, 'master_id': master_id, 'master_name': ''} for t in slots.free_slots(master_id, service_id, date)]
    return slots.free_slots_any(service_id, date)

@app.get('/api/bookings')
def api_bookings(date: str):
    return db.q("""SELECT b.*, s.title stitle, s.duration sdur, s.price sprice, m.name mname, m.color mcolor
                   FROM bookings b
                   LEFT JOIN services s ON s.id=b.service_id
                   LEFT JOIN masters m ON m.id=b.master_id
                   WHERE b.date=? AND b.status!='cancelled' ORDER BY b.start""", (date,))

@app.post('/api/bookings')
def api_booking_add(p: dict):
    svc = db.q('SELECT duration,price FROM services WHERE id=?', (p['service_id'],))
    if not svc:
        raise HTTPException(400, 'service')
    dur, price = svc[0]['duration'], svc[0]['price']
    end = slots._to_hhmm(slots._to_min(p['start']) + dur)
    
    promo_code = p.get('promo', '').strip().upper()
    discount = 0
    price_final = price
    if promo_code:
        promo = db.q('SELECT * FROM promos WHERE code=? AND used_at IS NULL', (promo_code,))
        if promo:
            discount = promo[0]['percent']
            price_final = int(round(price * (100 - discount) / 100))
            db.exe("UPDATE promos SET used_at=datetime('now') WHERE id=?", (promo[0]['id'],))
    
    bid = db.exe("""INSERT INTO bookings(salon_id,master_id,service_id,client_tg_id,client_key,client_name,client_phone,date,start,end,status,comment,created,promo,discount,price_final)
                    VALUES(1,?,?,0,?,?,?,?,?,?,'confirmed',?,datetime('now'),?,?,?)""",
                 (p['master_id'], p['service_id'], p.get('client_key', 'owner'), p.get('client_name', ''),
                  p.get('client_phone', ''), p['date'], p['start'], end, p.get('comment', ''),
                  promo_code, discount, price_final))
    return {'id': bid, 'discount': discount, 'price_final': price_final}

@app.put('/api/bookings/{bid}/status')
def api_booking_status(bid: int, p: dict):
    db.exe('UPDATE bookings SET status=? WHERE id=?', (p.get('status', 'new'), bid))
    return {'ok': True}

# ---------- ДАШБОРД ----------

@app.get('/api/dashboard')
def api_dashboard():
    import datetime
    today = datetime.date.today()
    days = []
    for i in range(13, -1, -1):
        d = today - datetime.timedelta(days=i)
        ds = d.isoformat()
        bk = db.q("""SELECT COUNT(*) cnt, SUM(CASE WHEN status IN ('confirmed','done') THEN COALESCE(price_final,s.price,0) ELSE 0 END) rev
                     FROM bookings b LEFT JOIN services s ON s.id=b.service_id
                     WHERE b.date=? AND b.status!='cancelled'""", (ds,))
        days.append({'date': ds, 'day': f'{d.day}.{d.month}', 'cnt': bk[0]['cnt'] or 0, 'rev': bk[0]['rev'] or 0})
    total_rev = sum(d['rev'] for d in days)
    total_bk = sum(d['cnt'] for d in days)
    return {'days': days, 'total_rev': total_rev, 'total_bk': total_bk}

# ---------- АДМИНКА ----------

ADMIN_CSS = """
:root{--bg:#0F0F12;--card:#1A1A1F;--card2:#232329;--tx:#fff;--tx2:#9A9AA3;--edge:rgba(255,255,255,.08);--hair:rgba(255,255,255,.07);--acc:#FF4D8D;--acc2:#8B5CF6;}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent;}
body{margin:0;background:var(--bg);color:var(--tx);font-family:-apple-system,'Segoe UI',Roboto,sans-serif;}
.wrap{max-width:640px;margin:0 auto;padding:0 16px 96px;}
.nav{position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;align-items:flex-end;padding:18px 16px 12px;margin:0 -16px 14px;background:rgba(15,15,18,.75);backdrop-filter:blur(20px);border-bottom:1px solid var(--edge);}
.cap{font-size:11px;color:var(--tx2);letter-spacing:1.4px;text-transform:uppercase;font-weight:700;}
.title{font-size:30px;font-weight:800;letter-spacing:-.5px;margin-top:2px;background:linear-gradient(135deg,#FF4D8D,#8B5CF6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.view{display:none;} .view.active{display:block;animation:vin .3s cubic-bezier(.32,.72,0,1);}
@keyframes vin{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.card{background:var(--card);border:1px solid var(--edge);border-radius:18px;overflow:hidden;margin-bottom:14px;box-shadow:0 12px 32px rgba(0,0,0,.45);}
.card.pad{padding:14px 16px;overflow:visible;}
.row{display:flex;align-items:center;gap:12px;padding:13px 16px;}
.row+.row{border-top:1px solid var(--hair);}
.row.need{background:rgba(255,159,10,.08);border:1px solid rgba(255,159,10,.45);border-radius:14px;margin:0 10px 10px;}
.rn{flex:1;font-size:15px;font-weight:600;min-width:0;}
.rs{font-size:12px;color:var(--tx2);margin-top:2px;}
.rv{text-align:right;font-size:15px;font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums;}
.sec{padding:14px 4px 8px;font-size:11px;font-weight:700;color:var(--tx2);text-transform:uppercase;letter-spacing:1.2px;display:flex;justify-content:space-between;align-items:center;}
.hint{font-size:11px;color:var(--tx2);padding:0 4px 10px;line-height:1.5;}
.btn{border:none;border-radius:12px;padding:12px 18px;font-size:14px;font-weight:700;cursor:pointer;background:linear-gradient(135deg,#FF4D8D,#8B5CF6);color:#fff;box-shadow:0 8px 24px rgba(255,77,141,.3);}
.btn:active{transform:scale(.96);}
.btn.ghost{background:var(--card2);color:var(--tx);box-shadow:none;border:1px solid var(--edge);}
.btn.mini{padding:6px 12px;font-size:12px;border-radius:9px;}
.btn.danger{background:rgba(255,69,58,.15);color:#FF453A;box-shadow:none;}
.pill-btn{border:none;border-radius:999px;padding:9px 14px;font-size:12px;font-weight:800;cursor:pointer;white-space:nowrap;}
.pill-btn:active{transform:scale(.94);}
.pill-btn.ok{background:rgba(48,209,88,.2);color:#30D158;}
.pill-btn.done{background:rgba(142,142,147,.2);color:#9A9AA3;}
.pill-btn.no{background:rgba(255,69,58,.16);color:#FF453A;}
.acts2{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;}
.statrow{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;}
.statpill{background:var(--card2);border:1px solid var(--edge);border-radius:999px;padding:7px 12px;font-size:12px;font-weight:700;color:var(--tx2);}
.statpill b{color:var(--tx);}
.statpill.warn{border-color:rgba(255,159,10,.5);}
.statpill.warn b{color:#FF9F0A;}
.chip{display:inline-flex;align-items:center;border:none;background:var(--card2);border:1px solid var(--edge);color:var(--tx);border-radius:999px;padding:9px 14px;font-size:13px;font-weight:700;cursor:pointer;}
.chip.on{background:linear-gradient(135deg,#FF4D8D,#8B5CF6);color:#fff;border-color:transparent;}
.chip:active{transform:scale(.94);}
.chips{display:flex;flex-wrap:wrap;gap:8px;}
.slotgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(74px,1fr));gap:8px;}
.slot{border:1px solid var(--edge);background:var(--card2);border-radius:12px;padding:10px 4px;text-align:center;font-size:13px;font-weight:700;cursor:pointer;}
.slot:active{transform:scale(.94);}
.daterow{display:flex;gap:8px;align-items:center;margin-bottom:12px;}
.daterow input[type=date]{flex:1;background:var(--card2);border:1px solid var(--edge);border-radius:12px;color:var(--tx);padding:10px;font-size:14px;font-weight:600;outline:none;color-scheme:dark;}
.selrow{display:flex;gap:8px;margin-bottom:12px;}
.selrow select{flex:1;background:var(--card2);border:1px solid var(--edge);border-radius:12px;color:var(--tx);padding:11px;font-size:14px;font-weight:600;outline:none;}
.status{font-size:10px;font-weight:800;letter-spacing:.6px;text-transform:uppercase;border-radius:999px;padding:4px 9px;white-space:nowrap;}
.status.new{background:rgba(255,159,10,.16);color:#FF9F0A;}
.status.confirmed{background:rgba(48,209,88,.16);color:#30D158;}
.status.done{background:rgba(142,142,147,.18);color:#9A9AA3;}
.avatar{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;flex:none;}
.wk{display:flex;align-items:center;gap:8px;padding:8px 0;border-top:1px solid var(--hair);}
.wk .wd{width:34px;font-size:12px;font-weight:700;color:var(--tx2);}
.wk input[type=time]{background:var(--card2);border:1px solid var(--edge);border-radius:9px;color:var(--tx);padding:7px;font-size:13px;outline:none;color-scheme:dark;}
.wk label{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--tx2);cursor:pointer;}
.svccheck{display:flex;align-items:center;gap:8px;padding:7px 0;font-size:14px;}
.exp{display:none;} .master.open .exp{display:block;}
.chev{color:var(--tx2);transition:transform .3s;} .master.open .chev{transform:rotate(90deg);}
.tabbar{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:100%;max-width:640px;display:flex;background:rgba(26,26,31,.85);backdrop-filter:blur(20px);border-top:1px solid var(--edge);padding:8px 8px 22px;z-index:30;}
.tab{flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;background:none;border:none;color:var(--tx2);font-size:10px;font-weight:700;cursor:pointer;padding:4px 0;}
.tab svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;}
.tab.active{color:var(--acc);}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(6px);opacity:0;pointer-events:none;transition:.3s;z-index:50;}
.overlay.show{opacity:1;pointer-events:auto;}
.sheet{position:fixed;left:50%;transform:translate(-50%,105%);bottom:0;width:100%;max-width:480px;background:var(--card);border-radius:24px 24px 0 0;padding:8px 16px 34px;transition:transform .45s cubic-bezier(.32,.72,0,1);z-index:60;border-top:1px solid var(--edge);}
.sheet.open{transform:translate(-50%,0);}
.grab{width:38px;height:5px;border-radius:3px;background:rgba(255,255,255,.28);margin:6px auto 10px;}
.sheet h2{font-size:18px;font-weight:800;margin:4px 0 12px;text-align:center;}
.fg{background:var(--card2);border-radius:14px;overflow:hidden;}
.fr{display:flex;align-items:center;gap:10px;padding:12px 14px;}
.fr+.fr{border-top:1px solid var(--hair);}
.fr label{width:92px;font-size:13px;color:var(--tx2);flex:none;}
.fr input{flex:1;background:transparent;border:none;outline:none;color:var(--tx);font-size:15px;font-weight:600;text-align:right;}
.fr input.text{text-align:left;}
#toast{position:fixed;bottom:96px;left:50%;transform:translateX(-50%) translateY(16px);background:linear-gradient(135deg,#FF4D8D,#8B5CF6);color:#fff;font-weight:700;padding:10px 20px;border-radius:999px;opacity:0;transition:.3s;z-index:70;pointer-events:none;font-size:14px;}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0);}
.empty{color:var(--tx2);font-size:13px;text-align:center;padding:18px 0;}
.chart-wrap{position:relative;height:180px;margin:10px 0;}
.chart-bar{position:absolute;bottom:0;width:6%;background:linear-gradient(180deg,#FF4D8D,#8B5CF6);border-radius:4px 4px 0 0;transition:height .5s;}
.chart-label{position:absolute;bottom:-20px;width:6%;text-align:center;font-size:9px;color:var(--tx2);}
"""

ADMIN_JS = """
const $=id=>document.getElementById(id);
let services=[],masters=[],curDate=localISO(),selSvc=0,selMst=0,pending=null,mode=null,ids={};
function localISO(d){d=d||new Date();return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function shiftDate(n){const d=new Date(curDate);d.setDate(d.getDate()+n);curDate=localISO(d);$('date-inp').value=curDate;renderDay();}
function toast(m){const t=$('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),1600);}
function showView(v){document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));$('view-'+v).classList.add('active');
 document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.view===v));
 if(v==='dashboard')loadDashboard();}
function openSheet(title,html,m,i){mode=m;ids=i||{};$('sheet-title').textContent=title;$('sheet-fields').innerHTML=html;
 $('overlay').classList.add('show');$('sheet').classList.add('open');}
function closeSheet(){$('overlay').classList.remove('show');$('sheet').classList.remove('open');}
async function loadRefs(){services=await(await fetch('/api/services')).json();masters=await(await fetch('/api/masters')).json();
 $('svc-sel').innerHTML='<option value=0>Услуга…</option>'+services.map(s=>`<option value=${s.id}>${s.title} · ${s.duration}м · ${s.price}₽</option>`).join('');
 $('mst-sel').innerHTML='<option value=0>Любой мастер</option>'+masters.map(m=>`<option value=${m.id}>${m.name}</option>`).join('');
 $('svc-sel').value=selSvc||'';renderServices();renderMasters();renderDay();}
async function renderDay(){
 const date=curDate;
 const bk=await(await fetch('/api/bookings?date='+date)).json();
 const total=bk.length;
 const newC=bk.filter(b=>b.status==='new').length;
 const rev=bk.filter(b=>b.status==='confirmed'||b.status==='done').reduce((s,b)=>s+(b.price_final||b.sprice||0),0);
 $('day-stats').innerHTML=
   `<div class="statpill">Записей: <b>${total}</b></div>`+
   (newC?`<div class="statpill warn">Ждут: <b>${newC}</b></div>`:'')+
   `<div class="statpill">Выручка: <b>${rev.toLocaleString('ru-RU')} ₽</b></div>`;
 const stTxt={new:'новая',confirmed:'подтверждена',done:'готова'};
 $('day-list').innerHTML=bk.length?bk.map(b=>{
   const acts = b.status==='new'
     ? `<button class="pill-btn ok" onclick="bstat(${b.id},'confirmed')">✔ Подтвердить</button><button class="pill-btn no" onclick="bstat(${b.id},'cancelled')">✕ Отклонить</button>`
     : b.status==='confirmed'
     ? `<button class="pill-btn done" onclick="bstat(${b.id},'done')">✓ Готово</button><button class="pill-btn no" onclick="bstat(${b.id},'cancelled')">✕ Отмена</button>`
     : `<span class="status ${b.status}">${stTxt[b.status]}</span>`;
   const disc=b.discount?` · 🏷 −${b.discount}%`:'';
   return `<div class="row${b.status==='new'?' need':''}">
     <div class="avatar" style="background:${b.mcolor||'#8B5CF6'}">${(b.mname||'?')[0]}</div>
     <div class="rn"><b>${b.start}–${b.end}</b> · ${b.stitle||'—'}${disc}<div class="rs"> ${b.client_name||'клиент'} · ${b.client_phone||''} · ️ ${b.mname||''}</div></div>
     <div class="acts2">${acts}</div>
   </div>`;
 }).join(''):'<div class="empty">На этот день записей нет</div>';
 let slotsHtml='<div class="empty">Выбери услугу — покажу свободные окна</div>';
 if(selSvc){
   const sl=await(await fetch(`/api/slots?date=${date}&service_id=${selSvc}&master_id=${selMst}`)).json();
   slotsHtml=sl.length?`<div class="slotgrid">`+sl.map(s=>`<div class="slot" onclick="openBook('${s.time}',${s.master_id},'${(s.master_name||'').replace(/'/g,"")}')">${s.time}</div>`).join('')+`</div>`:'<div class="empty">Свободных окон нет</div>';
 }
 $('slots-box').innerHTML=slotsHtml;
 renderQuickDates();
}
function renderQuickDates(){
  const today=new Date();
  const wd=['вс','пн','вт','ср','чт','пт','сб'];
  let html='';
  for(let i=0;i<14;i++){
    const d=new Date(today);
    d.setDate(d.getDate()+i);
    const iso=localISO(d);
    const label=i===0?'сегодня':i===1?'завтра':`${wd[d.getDay()]} ${d.getDate()}.${d.getMonth()+1}`;
    const active=iso===curDate?'on':'';
    html+=`<button class="chip ${active}" onclick="curDate='${iso}';$('date-inp').value='${iso}';renderDay();">${label}</button>`;
  }
  $('quick-dates').innerHTML=html;
}
function bstat(id,st){fetch(`/api/bookings/${id}/status`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:st})}).then(()=>{toast('Статус обновлён');renderDay();});}
function openBook(time,masterId,masterName){pending={time,masterId,masterName};
 openSheet('Запись на '+time,`<div class="fg">
  <div class="fr"><label>Клиент</label><input class="text" id="b-name" placeholder="Имя"></div>
  <div class="fr"><label>Телефон</label><input class="text" id="b-phone" placeholder="+7…"></div>
  <div class="fr"><label>Промокод</label><input class="text" id="b-promo" placeholder="необязательно"></div>
 </div>`,'book');}
function renderServices(){
 $('svc-list').innerHTML=services.length?services.map(s=>`<div class="row">
   <div class="rn">${s.title}<div class="rs">${s.duration} мин</div></div>
   <div class="rv">${s.price} ₽</div>
   <button class="btn mini ghost" onclick="openSvc(${s.id})">✎</button>
   <button class="btn mini danger" onclick="delSvc(${s.id})">✕</button></div>`).join(''):'<div class="empty">Услуг нет</div>';
}
function openSvc(id){const s=id?services.find(x=>x.id===id):null;
 openSheet(s?'Услуга':'Новая услуга',`<div class="fg">
  <div class="fr"><label>Название</label><input class="text" id="s-title" value="${s?s.title:''}"></div>
  <div class="fr"><label>Минут</label><input type="number" id="s-dur" value="${s?s.duration:60}"></div>
  <div class="fr"><label>Цена ₽</label><input type="number" id="s-price" value="${s?s.price:0}"></div></div>`,'svc',{id:id||0});}
function delSvc(id){if(!confirm('Скрыть услугу?'))return;fetch('/api/services/'+id,{method:'DELETE'}).then(()=>{toast('Услуга скрыта');loadRefs();});}
function renderMasters(){
 $('mst-list').innerHTML=masters.length?masters.map(m=>`<div class="card master" id="master-${m.id}">
  <div class="row" style="cursor:pointer" onclick="this.parentNode.classList.toggle('open')">
   <div class="avatar" style="background:${m.color}">${m.name[0]}</div>
   <div class="rn">${m.name}<div class="rs">услуг: ${m.services.length} · дней: ${Object.keys(m.week).length}</div></div>
   <span class="chev">›</span></div>
  <div class="exp">
   <div class="row" style="flex-direction:column;align-items:stretch;gap:6px">
     <div class="sec" style="padding:4px 0">Услуги мастера</div>
     ${services.map(s=>`<label class="svccheck"><input type="checkbox" class="m-svc" data-m="${m.id}" value="${s.id}" ${m.services.includes(s.id)?'checked':''}> ${s.title}</label>`).join('')}
     <button class="btn mini" onclick="saveSvcLinks(${m.id})">Сохранить услуги</button>
     <div class="sec" style="padding:8px 0 4px">График недели</div>
     ${['Пн','Вт','Ср','Чт','Пт','Сб','Вс'].map((wd,i)=>{const w=m.week[i];return `<div class="wk">
       <span class="wd">${wd}</span>
       <label><input type="checkbox" class="w-on" data-m="${m.id}" data-w="${i}" ${w?'checked':''}> раб.</label>
       <input type="time" class="w-s" data-m="${m.id}" data-w="${i}" value="${w?w.start:'10:00'}">
       <input type="time" class="w-e" data-m="${m.id}" data-w="${i}" value="${w?w.end:'20:00'}"></div>`;}).join('')}
     <button class="btn mini" onclick="saveWeek(${m.id})">Сохранить график</button>
   </div>
  </div></div>`).join(''):'<div class="empty">Мастеров нет</div>';
}
function saveSvcLinks(mid){const ids=[...document.querySelectorAll(`.m-svc[data-m="${mid}"]:checked`)].map(x=>+x.value);
 fetch(`/api/masters/${mid}/services`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})}).then(()=>{toast('Услуги сохранены');loadRefs();});}
function saveWeek(mid){const week={};for(let i=0;i<7;i++){const on=document.querySelector(`.w-on[data-m="${mid}"][data-w="${i}"]`).checked;
  week[i]={on,start:document.querySelector(`.w-s[data-m="${mid}"][data-w="${i}"]`).value||'10:00',end:document.querySelector(`.w-e[data-m="${mid}"][data-w="${i}"]`).value||'20:00'};}
 fetch(`/api/masters/${mid}/week`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({week})}).then(()=>{toast('График сохранён');loadRefs();});}
function openMaster(){openSheet('Новый мастер',`<div class="fg">
 <div class="fr"><label>Имя</label><input class="text" id="m-name" placeholder="Имя"></div>
 <div class="fr"><label>Цвет</label><input class="text" id="m-color" value="#FF4D8D" placeholder="#FF4D8D"></div></div>`,'master');}
async function loadDashboard(){
 const d=await(await fetch('/api/dashboard')).json();
 $('dash-stats').innerHTML=`<div class="statpill">За 14 дней: <b>${d.total_bk}</b> записей</div><div class="statpill">Выручка: <b>${d.total_rev.toLocaleString('ru-RU')} ₽</b></div>`;
 const max=Math.max(...d.days.map(x=>x.cnt),1);
 let html='';
 d.days.forEach((x,i)=>{
   const h=(x.cnt/max)*160;
   html+=`<div class="chart-bar" style="left:${i*7}%;height:${h}px" title="${x.day}: ${x.cnt} записей, ${x.rev} ₽"></div>`;
   html+=`<div class="chart-label" style="left:${i*7}%">${x.day}</div>`;
 });
 $('chart-bars').innerHTML=html;
}
$('overlay').onclick=closeSheet;
$('sheet-save').onclick=function(){
 if(mode==='svc'){const body={title:$('s-title').value.trim(),duration:+$('s-dur').value||60,price:+$('s-price').value||0};
  if(!body.title)return alert('Название?');
  const u=ids.id?fetch('/api/services/'+ids.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}):fetch('/api/services',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  u.then(()=>{toast('Сохранено');closeSheet();loadRefs();});}
 else if(mode==='master'){const body={name:$('m-name').value.trim(),color:$('m-color').value.trim()||'#FF4D8D'};
  if(!body.name)return alert('Имя?');
  fetch('/api/masters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(()=>{toast('Мастер добавлен');closeSheet();loadRefs();});}
 else if(mode==='book'){const body={service_id:+selSvc,master_id:pending.masterId||+selMst||masters[0].id,date:curDate,start:pending.time,client_name:$('b-name').value.trim(),client_phone:$('b-phone').value.trim(),promo:$('b-promo').value.trim()};
  if(!body.client_name)return alert('Имя клиента?');
  fetch('/api/bookings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json()).then(j=>{toast('Запись создана ✓'+(j.discount?` · скидка −${j.discount}%`:''));closeSheet();renderDay();});}
};
$('date-inp').onchange=e=>{curDate=e.target.value;renderDay();};
$('svc-sel').onchange=e=>{selSvc=+e.target.value;renderDay();};
$('mst-sel').onchange=e=>{selMst=+e.target.value;renderDay();};
$('date-inp').value=curDate;
showView('day');loadRefs();renderQuickDates();
"""

ADMIN_HTML = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>KRASA · админ</title>
<style>""" + ADMIN_CSS + """</style></head>
<body><div class="wrap">
<div class="nav">
  <div><div class="cap">панель владельца</div><div class="title">KRASA</div></div>
  <button class="btn mini" onclick="openMaster()">+ мастер</button>
</div>

<div class="view active" id="view-day">
  <div class="daterow">
    <button class="btn mini ghost" onclick="shiftDate(-1)">←</button>
    <input type="date" id="date-inp">
    <button class="btn mini ghost" onclick="shiftDate(1)">→</button>
    <button class="btn mini" onclick="curDate=localISO();$('date-inp').value=curDate;renderDay()">Сегодня</button>
  </div>
  <div class="statrow" id="day-stats"></div>
  <div class="sec"><span>Быстрый выбор (14 дней)</span></div>
  <div class="chips" id="quick-dates" style="margin-bottom:12px"></div>
  <div class="selrow">
    <select id="svc-sel"></select>
    <select id="mst-sel"></select>
  </div>
  <div class="sec"><span>Свободные окна</span></div>
  <div class="card pad" id="slots-box"></div>
  <div class="sec"><span>Записи на день</span></div>
  <div class="hint">Новые записи подсвечены оранжевым — нажми «✔ Подтвердить», и клиент получит уведомление.</div>
  <div class="card" id="day-list" style="background:transparent;border:none;box-shadow:none"></div>
</div>

<div class="view" id="view-services">
  <div class="sec"><span>Услуги</span><button class="btn mini" onclick="openSvc(0)">+ услуга</button></div>
  <div class="card" id="svc-list"></div>
</div>

<div class="view" id="view-masters">
  <div class="sec"><span>Команда</span><button class="btn mini" onclick="openMaster()">+ мастер</button></div>
  <div id="mst-list"></div>
</div>

<div class="view" id="view-dashboard">
  <div class="sec"><span>Статистика за 14 дней</span></div>
  <div class="statrow" id="dash-stats"></div>
  <div class="card pad">
    <div class="chart-wrap" id="chart-bars"></div>
  </div>
  <div class="hint">💡 График показывает количество записей по дням. Наведи на столбик — увидишь выручку.</div>
</div>

</div>
<div class="tabbar">
  <button class="tab active" data-view="day" onclick="showView('day')"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/></svg><span>День</span></button>
  <button class="tab" data-view="services" onclick="showView('services')"><svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h10"/></svg><span>Услуги</span></button>
  <button class="tab" data-view="masters" onclick="showView('masters')"><svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 19c.7-3.2 2.9-5 5.5-5s4.8 1.8 5.5 5"/><circle cx="17" cy="9" r="2.6"/><path d="M16 14.2c2.3.3 4 1.9 4.5 4.3"/></svg><span>Команда</span></button>
  <button class="tab" data-view="dashboard" onclick="showView('dashboard')"><svg viewBox="0 0 24 24"><path d="M4 19h16M7 14.5l3.2-4 3 2.4L17.5 7"/></svg><span>Статистика</span></button>
</div>
<div class="overlay" id="overlay"></div>
<div class="sheet" id="sheet">
  <div class="grab"></div>
  <h2 id="sheet-title"></h2>
  <div id="sheet-fields"></div>
  <button class="btn" style="width:100%;margin-top:14px" id="sheet-save">Сохранить</button>
  <button class="btn ghost" style="width:100%;margin-top:8px" onclick="closeSheet()">Отмена</button>
</div>
<div id="toast"></div>
<script>""" + ADMIN_JS + """</script>
</body></html>"""

@app.get('/admin', response_class=HTMLResponse)
def admin():
    return ADMIN_HTML

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)