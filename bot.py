import asyncio
import datetime
import secrets
import httpx
import db
import config

try:
    promo.ensure_columns()
except Exception:
    pass

DIV = '┄┄┄┄┄┄┄┄┄'

CLIENT_KB = {'keyboard': [[{'text': '📝 Записаться'}, {'text': ' Мои записи'}]], 'resize_keyboard': True, 'is_persistent': True}
OWNER_KB = {'keyboard': [[{'text': ' Сегодня'}, {'text': '🗓 Календарь'}],
                         [{'text': '📊 Сводка'}, {'text': ' Помощь'}],
                         [{'text': '👥 Клиенты'}, {'text': '➕ Запись'}]], 'resize_keyboard': True, 'is_persistent': True}
LABELS = {'📝 Записаться': 'start_book', ' Мои записи': 'my', ' Сегодня': 'today',
          ' Календарь': 'pick_date', '📊 Сводка': 'summary', ' Помощь': 'help',
          ' Клиенты': 'clients', '➕ Запись': 'newbook'}

# ---------- Telegram API ----------

def _client():
    if config.PROXY:
        return httpx.AsyncClient(timeout=40, proxy=config.PROXY)
    return httpx.AsyncClient(timeout=40)

async def tg(method, data=None):
    try:
        async with _client() as c:
            r = await c.post(f'{config.TG_API}/{method}', json=data or {})
            j = r.json()
            if not j.get('ok'):
                print(f'⚠️ Telegram API [{method}]: {j.get("description", "unknown error")} (code {j.get("error_code")})')
                return {}
            return j
    except httpx.ConnectError:
        print(f'⚠️ Telegram ConnectError [{method}]: нужен прокси')
        return {}
    except httpx.TimeoutException:
        print(f'⚠️ Telegram Timeout [{method}]')
        return {}
    except httpx.ProxyError:
        print(f'⚠️ Telegram ProxyError [{method}]')
        return {}
    except Exception as e:
        print(f'⚠️ Telegram Error [{method}]: {type(e).__name__}: {e}')
        return {}

async def tg_quiet(method, data=None):
    try:
        async with _client() as c:
            r = await c.post(f'{config.TG_API}/{method}', json=data or {})
            return r.json()
    except Exception:
        return {}

async def send_raw(chat_id, text, reply_markup=None):
    return await tg('sendMessage', {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML', 'reply_markup': reply_markup})

async def answer_callback(query_id, text=None, show_alert=False):
    await tg_quiet('answerCallbackQuery', {'callback_query_id': query_id, 'text': text, 'show_alert': show_alert})

async def delete_message(chat_id, message_id):
    if not message_id:
        return
    await tg_quiet('deleteMessage', {'chat_id': chat_id, 'message_id': message_id})

async def react(chat_id, message_id, emoji='❤️'):
    await tg_quiet('setMessageReaction', {'chat_id': chat_id, 'message_id': message_id,
                                           'reaction': [{'type': 'emoji', 'emoji': emoji}]})

async def emote(chat_id, emoji):
    res = await send_raw(chat_id, emoji)
    if res.get('ok'):
        mid = res['result']['message_id']
        asyncio.get_event_loop().create_task(_delayed_delete(chat_id, mid))

async def _delayed_delete(chat_id, mid):
    await asyncio.sleep(3.5)
    await delete_message(chat_id, mid)

def kb(rows):
    return {'inline_keyboard': rows}

# ---------- ЧИСТЫЙ ЧАТ ----------
last_msg = {}

async def say(chat_id, text, reply_markup=None):
    await tg_quiet('sendChatAction', {'chat_id': chat_id, 'action': 'typing'})
    await delete_message(chat_id, last_msg.get(chat_id))
    res = await send_raw(chat_id, text, reply_markup)
    if res.get('ok'):
        last_msg[chat_id] = res['result']['message_id']
    return res

# ---------- РОЛИ И ПРОФИЛЬ ----------

def is_owner(tg_id):
    salon = db.q('SELECT owner_tg_id FROM salons WHERE id=1')[0]
    return salon['owner_tg_id'] == tg_id

def claim_owner_if_free(tg_id):
    salon = db.q('SELECT owner_tg_id FROM salons WHERE id=1')[0]
    if salon['owner_tg_id'] is None:
        db.exe('UPDATE salons SET owner_tg_id=? WHERE id=1', (tg_id,))
        return True
    return False

def get_client(tg_id):
    rows = db.q('SELECT * FROM clients WHERE tg_id=?', (tg_id,))
    return rows[0] if rows else None

def save_client(tg_id, name, phone):
    rows = db.q('SELECT id FROM clients WHERE tg_id=?', (tg_id,))
    if rows:
        db.exe("UPDATE clients SET name=?, phone=?, updated=datetime('now') WHERE tg_id=?", (name, phone, tg_id))
    else:
        db.exe("INSERT INTO clients(tg_id,name,phone,updated) VALUES(?,?,?,datetime('now'))", (tg_id, name, phone))

dialog_state = {}
owner_state = {}

def clear_state(chat_id):
    dialog_state.pop(chat_id, None)

# ---------- ПРОМО И КЛИЕНТЫ ----------

def client_info(tg_id):
    c = db.q('SELECT name FROM clients WHERE tg_id=?', (tg_id,))
    if not c:
        c = db.q('SELECT client_name name FROM bookings WHERE client_tg_id=? ORDER BY id DESC LIMIT 1', (tg_id,))
    name = c[0]['name'] if c else 'друг'
    last = db.q("SELECT MAX(date) d FROM bookings WHERE client_tg_id=? AND status!='cancelled'", (tg_id,))
    days = 0
    if last and last[0]['d']:
        days = (datetime.date.today() - datetime.date.fromisoformat(last[0]['d'])).days
    return {'name': name, 'days': days}

async def send_promo(tg_id, percent, note=''):
    info = client_info(tg_id)
    code = f'KRASA{percent}-{secrets.token_hex(2).upper()}'
    until = (datetime.date.today() + datetime.timedelta(days=7)).strftime('%d.%m')
    text = (f'🎁 <b>KRASA</b> · подарок для тебя\n{DIV}\n'
            f'{info["name"]}, ты был(а) у нас <b>{info["days"]}</b> дн. назад — и мы соскучились!\n'
            f'Дарим <b>−{percent}%</b> на любую услугу до {until}.\n\n'
            f'🏷 Твой промокод: <code>{code}</code>')
    if note:
        text += f'\n💬 {note}'
    text += f'\n{DIV}\n💡 Вставь код при записи — скидка применится сама.'
    await send_raw(tg_id, text, kb([
        [{'text': '📝 Записаться сейчас', 'callback_data': 'start_book'}],
        [{'text': ' Мои записи', 'callback_data': 'my'}]]))
    db.exe("INSERT INTO promos(client_tg_id,code,percent,note,created) VALUES(?,?,?,?,datetime('now'))",
           (tg_id, code, percent, note))
    return code

def sleeping_clients(min_days=30):
    rows = db.q("""SELECT client_tg_id tgid, MAX(client_name) name, MAX(date) last, COUNT(*) v
                   FROM bookings WHERE client_tg_id!=0 AND client_name!='' AND status!='cancelled'
                   GROUP BY client_tg_id ORDER BY last ASC""")
    today = datetime.date.today()
    out = []
    for r in rows:
        days = (today - datetime.date.fromisoformat(r['last'])).days if r['last'] else 0
        if days >= min_days:
            out.append((r, days))
    return out

def eff_price(b):
    return b.get('price_final') or b.get('sprice') or 0

# ---------- КОМАНДЫ ----------

async def cmd_start(chat_id, user):
    tg_id = user['id']
    first_name = user.get('first_name', 'друг')

    if is_owner(tg_id) or claim_owner_if_free(tg_id):
        clear_state(chat_id)
        owner_state.pop(chat_id, None)
        
        # Кнопка для открытия Mini App (только для владельца)
        admin_kb = {
            'inline_keyboard': [[
                {'text': '🌐 Открыть админку', 'web_app': {'url': f'{config.PUBLIC_URL}/mini'}}
            ]]
        }
        
        await say(chat_id,
            f'👑 <b>KRASA</b> · панель владельца\n{DIV}\n'
            f'Привет, <b>{first_name}</b>!\n'
            f'Всё управление салоном — здесь и в меню ниже.\n{DIV}\n'
            f'️ Новые записи прилетают с кнопками «Подтвердить / Отклонить».\n\n'
            f'👇 Нажми кнопку ниже, чтобы открыть полную админку:',
            admin_kb)
        return

    clear_state(chat_id)
    client = get_client(tg_id)
    hello = f'С возвращением, <b>{client["name"]}</b>!' if client else f'Привет, <b>{first_name}</b>!'
    note = 'Контакты помню — запишем за пару тапов 😉' if client else 'Запись занимает 30 секунд. Без звонков.'
    await say(chat_id,
        f'💇‍♀️ <b>KRASA</b> · онлайн-запись\n{DIV}\n'
        f'{hello}\n{note}\n{DIV}\n'
        f'️ Выбери действие ниже:',
        CLIENT_KB)

async def cmd_help(chat_id, tg_id):
    if is_owner(tg_id):
        await say(chat_id,
            f'❓ <b>KRASA</b> · помощь\n{DIV}\n'
            f'/today — расписание на сегодня\n'
            f'/summary — сводка дня\n'
            f'/clients — спящие клиенты + промо\n'
            f'/menu — главное меню\n'
            f'/whoami — твой id и роль\n{DIV}\n'
            f'💡 График недели и услуги пока удобнее править в веб-админке.',
            OWNER_KB)
    else:
        await say(chat_id,
            f'❓ <b>KRASA</b> · помощь\n{DIV}\n'
            f'/my — мои записи\n'
            f'/menu — главное меню\n{DIV}\n'
            f'💡 Есть промокод? Нажми «🏷 Промокод» на шаге подтверждения.',
            CLIENT_KB)

async def cmd_whoami(chat_id, user):
    salon = db.q('SELECT owner_tg_id FROM salons WHERE id=1')[0]
    await send_raw(chat_id,
        f'🔎 Твой id: <code>{user["id"]}</code>\n'
        f'👑 Владелец: <code>{salon["owner_tg_id"]}</code>\n'
        f'Ты владелец: <b>{"да" if is_owner(user["id"]) else "нет"}</b>')

async def cmd_today(chat_id, tg_id):
    if not is_owner(tg_id):
        await say(chat_id, '⛔ Только для владельца салона.', CLIENT_KB)
        return
    await render_day(chat_id, datetime.date.today().isoformat())

async def cmd_summary(chat_id, tg_id):
    if not is_owner(tg_id):
        await say(chat_id, '⛔ Только для владельца салона.', CLIENT_KB)
        return
    today = datetime.date.today().isoformat()
    bk = db.q("""SELECT b.status, b.price_final, s.price sprice FROM bookings b
                 LEFT JOIN services s ON s.id=b.service_id
                 WHERE b.date=? AND b.status!='cancelled'""", (today,))
    total = len(bk)
    new = sum(1 for b in bk if b['status'] == 'new')
    rev = sum((b['price_final'] or b['sprice'] or 0) for b in bk if b['status'] in ('confirmed', 'done'))
    d = datetime.date.today()
    await say(chat_id,
        f'📊 <b>KRASA</b> · сводка за {d.day}.{d.month}\n{DIV}\n'
        f'<blockquote>🧾 Записей всего: <b>{total}</b>\n'
        f'🆕 Ждут подтверждения: <b>{new}</b>\n'
        f'💰 Выручка (подтв.): <b>{fmt_money(rev)} ₽</b></blockquote>\n'
        f'💡 /today — чтобы подтвердить новые.',
        OWNER_KB)

def fmt_money(v):
    return f'{v:,}'.replace(',', ' ')

async def cmd_clients(chat_id, tg_id):
    if not is_owner(tg_id):
        await say(chat_id, ' Только для владельца салона.', CLIENT_KB)
        return
    sleeping = sleeping_clients(30)
    if not sleeping:
        await say(chat_id,
            f'👥 <b>KRASA</b> · клиенты\n{DIV}\n'
            f'Спящих (30+ дней) нет — все были недавно. Отлично! ',
            OWNER_KB)
        return
    lines = [f'👥 <b>KRASA</b> · спящие клиенты\n{DIV}',
             f'Не были 30+ дней: <b>{len(sleeping)}</b>\n', 'Кому отправить промо?']
    buttons = []
    for r, days in sleeping[:8]:
        buttons.append([{'text': f'🎁 {r["name"]} · {days} дн', 'callback_data': f'promo_{r["tgid"]}'}])
    buttons.append([{'text': '🎁 Всем спящим (−15%)', 'callback_data': 'promo_all_cb'}])
    buttons.append([{'text': '🏠 Меню', 'callback_data': 'home'}])
    await say(chat_id, '\n'.join(lines), kb(buttons))

async def cmd_my(chat_id, tg_id):
    bk = db.q("""SELECT b.*, s.title stitle, m.name mname
                 FROM bookings b
                 LEFT JOIN services s ON s.id=b.service_id
                 LEFT JOIN masters m ON m.id=b.master_id
                 WHERE b.client_tg_id=? AND b.status IN ('new','confirmed')
                 ORDER BY b.date, b.start""", (tg_id,))
    if not bk:
        await say(chat_id,
            f' <b>KRASA</b> · мои записи\n{DIV}\n'
            f'Активных записей пока нет.\nЗапишемся прямо сейчас?',
            CLIENT_KB)
        return

    lines = [f'📖 <b>KRASA</b> · мои записи\n{DIV}']
    buttons = []
    for b in bk:
        st = ' ждёт подтверждения' if b['status'] == 'new' else '✔ подтверждена'
        lines.append(f'<blockquote>📅 <b>{b["date"][8:]}.{b["date"][5:7]}</b> в <b>{b["start"]}</b>\n'
                     f'{b["stitle"]} · {b["mname"]}\n{st}</blockquote>')
        buttons.append([{'text': f'✕ Отменить {b["date"][8:]}.{b["date"][5:7]} {b["start"]}', 'callback_data': f'mycancel_{b["id"]}'}])
    lines.append('💡 Отмена — не позднее чем за 2 часа.')
    buttons.append([{'text': ' Новая запись', 'callback_data': 'start_book'}])
    await say(chat_id, '\n'.join(lines), kb(buttons))

# ---------- ВЛАДЕЛЕЦ: РАСПИСАНИЕ ----------

def date_minus(d, days):
    return (datetime.date.fromisoformat(d) - datetime.timedelta(days=days)).isoformat()

def date_plus(d, days):
    return (datetime.date.fromisoformat(d) + datetime.timedelta(days=days)).isoformat()

WD_FULL = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']

async def render_day(chat_id, date_str):
    bk = db.q("""SELECT b.*, s.title stitle, s.price sprice, m.name mname, m.color mcolor
                 FROM bookings b
                 LEFT JOIN services s ON s.id=b.service_id
                 LEFT JOIN masters m ON m.id=b.master_id
                 WHERE b.date=? AND b.status!='cancelled' ORDER BY b.start""", (date_str,))

    d = datetime.date.fromisoformat(date_str)
    newc = sum(1 for b in bk if b['status'] == 'new')
    rev = sum(eff_price(b) for b in bk if b['status'] in ('confirmed', 'done'))
    head = f'📅 <b>KRASA</b> · {WD_FULL[d.weekday()]} {d.day}.{d.month}\n{DIV}'

    if not bk:
        text = head + '\nЗаписей нет. Выбери другую дату в календаре 🗓'
    else:
        lines = [head,
                 f'Записей: <b>{len(bk)}</b>' + (f' · новых: <b>{newc}</b>' if newc else '') + f' · выручка: <b>{fmt_money(rev)} ₽</b>']
        for b in bk:
            st = '🆕 новая' if b['status'] == 'new' else '✔ подтверждена' if b['status'] == 'confirmed' else '✓ готова'
            disc = f' ·  −{b["discount"]}%' if b.get('discount') else ''
            lines.append(f'<blockquote>🕐 <b>{b["start"]}–{b["end"]}</b> · {b["stitle"]}{disc}\n'
                         f'👤 {b["client_name"]} · {b["client_phone"]}\n'
                         f'✂️ {b["mname"]} · {st}</blockquote>')
        lines.append('💡 Нажми «Подтвердить» — клиент получит уведомление.')
        text = '\n'.join(lines)

    buttons = []
    for b in bk:
        if b['status'] == 'new':
            buttons.append([
                {'text': f'✔ Подтвердить {b["start"]}', 'callback_data': f'confirm_{b["id"]}'},
                {'text': '✕ Отклонить', 'callback_data': f'cancel_{b["id"]}'},
            ])
    buttons.append([
        {'text': '←', 'callback_data': f'day_{date_minus(date_str, 1)}'},
        {'text': 'Сегодня', 'callback_data': 'today'},
        {'text': '→', 'callback_data': f'day_{date_plus(date_str, 1)}'},
    ])
    buttons.append([{'text': '🗓 Календарь', 'callback_data': 'pick_date'}, {'text': ' Меню', 'callback_data': 'home'}])
    await say(chat_id, text, kb(buttons))

async def render_date_picker(chat_id):
    today = datetime.date.today()
    wd = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
    lines = [f'🗓 <b>KRASA</b> · календарь\n{DIV}', 'Выбери день:']
    buttons = []
    row = []
    for i in range(14):
        d = today + datetime.timedelta(days=i)
        label = 'сегодня' if i == 0 else 'завтра' if i == 1 else f'{wd[d.weekday()]} {d.day}.{d.month}'
        row.append({'text': label, 'callback_data': f'day_{d.isoformat()}'})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{'text': '🏠 Меню', 'callback_data': 'home'}])
    await say(chat_id, '\n'.join(lines), kb(buttons))

# ---------- CALLBACKS ----------

async def on_callback(query):
    data = query['data']
    chat_id = query['message']['chat']['id']
    tg_id = query['from']['id']
    print(f'↳ callback: {data} | от {tg_id} | владелец={is_owner(tg_id)}')

    if data == 'home':
        await cmd_start(chat_id, query['from'])
        await answer_callback(query['id'])
        return

    if data == 'help':
        await cmd_help(chat_id, tg_id)
        await answer_callback(query['id'])
        return

    if data.startswith('day_'):
        if not is_owner(tg_id):
            await answer_callback(query['id'], 'Только для владельца', True)
            return
        await render_day(chat_id, data[4:])
        await answer_callback(query['id'])
        return

    if data == 'today':
        if not is_owner(tg_id):
            await answer_callback(query['id'], 'Только для владельца', True)
            return
        await render_day(chat_id, datetime.date.today().isoformat())
        await answer_callback(query['id'])
        return

    if data == 'pick_date':
        if not is_owner(tg_id):
            await answer_callback(query['id'], 'Только для владельца', True)
            return
        await render_date_picker(chat_id)
        await answer_callback(query['id'])
        return

    if (data.startswith('confirm_') and data.split('_', 1)[1].isdigit()) or \
       (data.startswith('cancel_') and data.split('_', 1)[1].isdigit()):
        if not is_owner(tg_id):
            await answer_callback(query['id'], 'Только для владельца', True)
            return
        bid = int(data.split('_', 1)[1])
        status = 'confirmed' if data.startswith('confirm_') else 'cancelled'
        db.exe('UPDATE bookings SET status=? WHERE id=?', (status, bid))
        b = db.q('SELECT * FROM bookings WHERE id=?', (bid,))
        if b and b[0]['client_tg_id']:
            verb = 'подтверждена ✅' if status == 'confirmed' else 'отклонена ❌'
            await send_raw(b[0]['client_tg_id'],
                f'📬 <b>KRASA</b>\n{DIV}\nТвоя запись на <b>{b[0]["date"][8:]}.{b[0]["date"][5:7]} в {b[0]["start"]}</b> {verb}',
                CLIENT_KB)
        await answer_callback(query['id'], 'Готово ✓')
        await emote(chat_id, '👏')
        if b:
            await render_day(chat_id, b[0]['date'])
        return

    if data == 'my':
        await cmd_my(chat_id, tg_id)
        await answer_callback(query['id'])
        return

    if data.startswith('mycancel_'):
        bid = int(data[9:])
        b = db.q('SELECT * FROM bookings WHERE id=? AND client_tg_id=?', (bid, tg_id))
        if not b:
            await answer_callback(query['id'], 'Запись не найдена', True)
            return
        db.exe("UPDATE bookings SET status='cancelled' WHERE id=?", (bid,))
        await answer_callback(query['id'], 'Запись отменена')
        await cmd_my(chat_id, tg_id)
        return

    if data == 'start_book':
        clear_state(chat_id)
        dialog_state[chat_id] = {'step': 'service', 'data': {}}
        await start_booking(chat_id)
        await answer_callback(query['id'])
        return

    if data == 'cancel_book':
        clear_state(chat_id)
        await say(chat_id, f'💇‍♀️ <b>KRASA</b>\n{DIV}\nБез проблем! Запись отменена.\n💡 Возвращайся, когда будешь готов(а):', CLIENT_KB)
        await answer_callback(query['id'])
        return

    if data == 'book_ok':
        state = dialog_state.get(chat_id)
        if not state or state['step'] != 'confirm':
            await answer_callback(query['id'], 'Сессия истекла, начни заново', True)
            return
        await finish_booking(chat_id, tg_id)
        await answer_callback(query['id'])
        return

    if data == 'book_edit':
        state = dialog_state.get(chat_id)
        if not state:
            await answer_callback(query['id'], 'Сессия истекла', True)
            return
        state['step'] = 'name'
        await say(chat_id, f'️ <b>KRASA</b>\n{DIV}\nНапиши новое имя 👇',
                  {'force_reply': True, 'input_field_placeholder': 'Твоё имя', 'selective': True})
        await answer_callback(query['id'])
        return

    if data.startswith('svc_'):
        state = dialog_state.get(chat_id)
        if not state:
            await answer_callback(query['id'], 'Сессия истекла, начни заново', True)
            return
        state['data']['service_id'] = int(data[4:])
        state['step'] = 'master'
        await show_masters(chat_id, state['data']['service_id'])
        await answer_callback(query['id'])
        return

    if data.startswith('mst_'):
        state = dialog_state.get(chat_id)
        if not state:
            await answer_callback(query['id'], 'Сессия истекла', True)
            return
        state['data']['master_id'] = int(data[4:])
        state['step'] = 'date'
        await show_dates(chat_id)
        await answer_callback(query['id'])
        return

    if data == 'back_to_svc':
        state = dialog_state.get(chat_id)
        if state:
            state['step'] = 'service'
        await start_booking(chat_id)
        await answer_callback(query['id'])
        return

    if data == 'back_to_mst':
        state = dialog_state.get(chat_id)
        if state:
            state['step'] = 'master'
            await show_masters(chat_id, state['data']['service_id'])
        await answer_callback(query['id'])
        return

    if data == 'back_to_date':
        state = dialog_state.get(chat_id)
        if state:
            state['step'] = 'date'
        await show_dates(chat_id)
        await answer_callback(query['id'])
        return

    if data.startswith('date_'):
        state = dialog_state.get(chat_id)
        if not state:
            await answer_callback(query['id'], 'Сессия истекла', True)
            return
        state['data']['date'] = data[5:]
        state['step'] = 'slot'
        await show_slots(chat_id)
        await answer_callback(query['id'])
        return

    if data.startswith('slot_'):
        state = dialog_state.get(chat_id)
        if not state:
            await answer_callback(query['id'], 'Сессия истекла', True)
            return
        state['data']['slot'] = data[5:]
        client = get_client(tg_id)
        if client:
            state['data']['name'] = client['name']
            state['data']['phone'] = client['phone']
            state['step'] = 'confirm'
            await show_confirm(chat_id)
        else:
            state['step'] = 'name'
            await ask_name(chat_id)
        await answer_callback(query['id'])
        return

    await answer_callback(query['id'])

# ---------- ТЕКСТ ----------

async def handle_text(chat_id, tg_id, text, msg_id):
    state = dialog_state.get(chat_id)
    if not state:
        return

    if state['step'] == 'name':
        name = text.strip()
        await delete_message(chat_id, msg_id)
        if len(name) < 2:
            await say(chat_id, '🤔 Имя слишком короткое. Напиши, пожалуйста, полное имя 👇',
                      {'force_reply': True, 'input_field_placeholder': 'Твоё имя', 'selective': True})
            return
        state['data']['name'] = name[:80]
        state['step'] = 'phone'
        await react(chat_id, msg_id, '❤️')
        await say(chat_id,
            f' Привет, <b>{name}</b>!\n{DIV}\nТеперь напиши номер телефона 👇',
            {'force_reply': True, 'input_field_placeholder': '+7 999 123 45 67', 'selective': True})
        return

    if state['step'] == 'phone':
        phone = text.strip()
        await delete_message(chat_id, msg_id)
        if len(phone) < 6:
            await say(chat_id, '🤔 Номер слишком короткий. Напиши телефон полностью 👇',
                      {'force_reply': True, 'input_field_placeholder': '+7 999 123 45 67', 'selective': True})
            return
        state['data']['phone'] = phone[:30]
        state['step'] = 'confirm'
        await react(chat_id, msg_id, '❤️')
        await show_confirm(chat_id)
        return

    await delete_message(chat_id, msg_id)

# ---------- POLLING ----------

async def check_bot():
    print('🔎 Проверяю связь с Telegram...')
    res = await tg('getMe')
    if res.get('ok'):
        u = res['result']
        print(f'✅ Бот подключён: @{u.get("username")} (id {u.get("id")})')
        await tg('setMyCommands', {'commands': [
            {'command': 'start', 'description': 'главное меню'},
            {'command': 'menu', 'description': 'меню с кнопками'},
            {'command': 'today', 'description': 'расписание на сегодня (владелец)'},
            {'command': 'summary', 'description': 'сводка дня (владелец)'},
            {'command': 'my', 'description': 'мои записи'},
            {'command': 'help', 'description': 'помощь'},
            {'command': 'whoami', 'description': 'моя роль и id'},
        ]})
    else:
        print('❌ Бот НЕ подключился. Проверь токен и/или прокси.')

async def polling_loop():
    await check_bot()
    offset = 0
    print('🤖 Бот слушает Telegram')
    while True:
        try:
            res = await tg('getUpdates', {'offset': offset, 'timeout': 30})
            for u in res.get('result', []):
                offset = max(offset, u['update_id'] + 1)
                try:
                    await handle_update(u)
                except Exception as e:
                    print(f'⚠️ handle_update: {type(e).__name__}: {e}')
        except Exception as e:
            print(f'⚠️ polling: {type(e).__name__}: {e}')
        await asyncio.sleep(1)

async def handle_update(u):
    if 'message' in u:
        msg = u['message']
        chat_id = msg['chat']['id']
        user = msg.get('from', {})
        text = (msg.get('text') or '').strip()
        if text.startswith('/start') or text.startswith('/menu'):
            await cmd_start(chat_id, user)
        elif text.startswith('/today'):
            await cmd_today(chat_id, user['id'])
        elif text.startswith('/summary'):
            await cmd_summary(chat_id, user['id'])
        elif text.startswith('/my'):
            await cmd_my(chat_id, user['id'])
        elif text.startswith('/whoami'):
            await cmd_whoami(chat_id, user)
        elif text.startswith('/help'):
            await cmd_help(chat_id, user['id'])
        elif text in LABELS:
            act = LABELS[text]
            if act == 'start_book':
                clear_state(chat_id)
                dialog_state[chat_id] = {'step': 'service', 'data': {}}
                await start_booking(chat_id)
            elif act == 'my':
                await cmd_my(chat_id, user['id'])
            elif act == 'today':
                await cmd_today(chat_id, user['id'])
            elif act == 'pick_date':
                if is_owner(user['id']):
                    await render_date_picker(chat_id)
                else:
                    await say(chat_id, '⛔ Только для владельца.', CLIENT_KB)
            elif act == 'summary':
                await cmd_summary(chat_id, user['id'])
            elif act == 'help':
                await cmd_help(chat_id, user['id'])
        else:
            if text:
                await handle_text(chat_id, user['id'], text, msg['message_id'])
        return

    if 'callback_query' in u:
        await on_callback(u['callback_query'])