import asyncio
import datetime
import httpx
import db
import config

DIV = '┄┄┄┄┄┄┄┄┄┄┄┄┄'

CLIENT_KB = {'keyboard': [[{'text': '📝 Записаться'}, {'text': '📖 Мои записи'}]], 'resize_keyboard': True, 'is_persistent': True}
OWNER_KB = {'keyboard': [[{'text': '📅 Сегодня'}, {'text': '🗓 Календарь'}], [{'text': '📊 Сводка'}, {'text': '❓ Помощь'}]], 'resize_keyboard': True, 'is_persistent': True}
LABELS = {'📝 Записаться': 'start_book', '📖 Мои записи': 'my', '📅 Сегодня': 'today',
          '🗓 Календарь': 'pick_date', '📊 Сводка': 'summary', '❓ Помощь': 'help'}

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

def clear_state(chat_id):
    dialog_state.pop(chat_id, None)

# ---------- КОМАНДЫ ----------

async def cmd_start(chat_id, user):
    tg_id = user['id']
    first_name = user.get('first_name', 'друг')

    if is_owner(tg_id) or claim_owner_if_free(tg_id):
        clear_state(chat_id)
        await say(chat_id,
            f'👑 <b>KRASA</b> · панель владельца\n{DIV}\n'
            f'Привет, <b>{first_name}</b>!\n'
            f'Расписание, записи и сводки — здесь и в меню ниже.\n{DIV}\n'
            f'⚡️ Новые записи прилетают сюда сами — подтверждай прямо из уведомления.',
            OWNER_KB)
        return

    clear_state(chat_id)
    client = get_client(tg_id)
    hello = f'С возвращением, <b>{client["name"]}</b>!' if client else f'Привет, <b>{first_name}</b>!'
    note = 'Контакты помню — запишем за пару тапов 😉' if client else 'Запись занимает 30 секунд. Без звонков.'
    await say(chat_id,
        f'💇‍♀️ <b>KRASA</b> · онлайн-запись\n{DIV}\n'
        f'{hello}\n{note}\n{DIV}\n'
        f'⚡️ Выбери действие ниже:',
        CLIENT_KB)

async def cmd_help(chat_id, tg_id):
    if is_owner(tg_id):
        await say(chat_id,
            f'❓ <b>KRASA</b> · помощь\n{DIV}\n'
            f'/today — расписание на сегодня\n'
            f'/summary — сводка дня (выручка, новые)\n'
            f'/menu — главное меню\n'
            f'/whoami — твой id и роль\n{DIV}\n'
            f'💡 Новые записи приходят с кнопками «Подтвердить / Отклонить».',
            OWNER_KB)
    else:
        await say(chat_id,
            f'❓ <b>KRASA</b> · помощь\n{DIV}\n'
            f'/my — мои записи\n'
            f'/menu — главное меню\n{DIV}\n'
            f'💡 Запись: 📝 → 4 шага → готово. Отмена не позднее 2 часов.',
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
    bk = db.q("""SELECT b.status, s.price FROM bookings b
                 LEFT JOIN services s ON s.id=b.service_id
                 WHERE b.date=? AND b.status!='cancelled'""", (today,))
    total = len(bk)
    new = sum(1 for b in bk if b['status'] == 'new')
    rev = sum(b['price'] or 0 for b in bk if b['status'] in ('confirmed', 'done'))
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

async def cmd_my(chat_id, tg_id):
    bk = db.q("""SELECT b.*, s.title stitle, m.name mname
                 FROM bookings b
                 LEFT JOIN services s ON s.id=b.service_id
                 LEFT JOIN masters m ON m.id=b.master_id
                 WHERE b.client_tg_id=? AND b.status IN ('new','confirmed')
                 ORDER BY b.date, b.start""", (tg_id,))
    if not bk:
        await say(chat_id,
            f'📖 <b>KRASA</b> · мои записи\n{DIV}\n'
            f'Активных записей пока нет.\nЗапишемся прямо сейчас?',
            CLIENT_KB)
        return

    lines = [f'📖 <b>KRASA</b> · мои записи\n{DIV}']
    buttons = []
    for b in bk:
        st = '🆕 ждёт подтверждения' if b['status'] == 'new' else '✔ подтверждена'
        lines.append(f'<blockquote>📅 <b>{b["date"][8:]}.{b["date"][5:7]}</b> в <b>{b["start"]}</b>\n'
                     f'{b["stitle"]} · {b["mname"]}\n{st}</blockquote>')
        buttons.append([{'text': f'✕ Отменить {b["date"][8:]}.{b["date"][5:7]} {b["start"]}', 'callback_data': f'mycancel_{b["id"]}'}])
    lines.append('💡 Отмена — не позднее чем за 2 часа.')
    buttons.append([{'text': '📝 Новая запись', 'callback_data': 'start_book'}])
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
    rev = sum(b['sprice'] or 0 for b in bk if b['status'] in ('confirmed', 'done'))
    head = f'📅 <b>KRASA</b> · {WD_FULL[d.weekday()]} {d.day}.{d.month}\n{DIV}'

    if not bk:
        text = head + '\nЗаписей нет. Выбери другую дату в календаре 🗓'
    else:
        lines = [head,
                 f'Записей: <b>{len(bk)}</b>' + (f' · новых: <b>{newc}</b>' if newc else '') + f' · выручка: <b>{fmt_money(rev)} ₽</b>']
        for b in bk:
            st = '🆕 новая' if b['status'] == 'new' else '✔ подтверждена' if b['status'] == 'confirmed' else '✓ готова'
            lines.append(f'<blockquote>🕐 <b>{b["start"]}–{b["end"]}</b> · {b["stitle"]}\n'
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
    buttons.append([{'text': '🗓 Календарь', 'callback_data': 'pick_date'}, {'text': '🏠 Меню', 'callback_data': 'home'}])
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

# ---------- КЛИЕНТ: ВИЗАРД ----------

async def start_booking(chat_id):
    services = db.q('SELECT id,title,duration,price FROM services WHERE salon_id=1 AND active=1 ORDER BY price')
    if not services:
        await say(chat_id, '⚠️ Пока нет доступных услуг. Свяжись с салоном.', CLIENT_KB)
        return
    lines = [f'💇‍♀️ <b>KRASA</b> · шаг 1/4\n{DIV}', 'Выбери услугу:']
    buttons = []
    for s in services:
        lines.append(f'• <b>{s["title"]}</b> · {s["duration"]} мин · <b>{s["price"]} ₽</b>')
        buttons.append([{'text': f'{s["title"]} · {s["price"]} ₽', 'callback_data': f'svc_{s["id"]}'}])
    buttons.append([{'text': '✕ Отмена', 'callback_data': 'cancel_book'}])
    await say(chat_id, '\n'.join(lines), kb(buttons))

async def show_masters(chat_id, service_id):
    svc = db.q('SELECT id,title FROM services WHERE id=?', (service_id,))
    if not svc:
        return
    masters = db.q("""SELECT m.id,m.name FROM masters m
                      JOIN master_services ms ON ms.master_id=m.id
                      WHERE m.salon_id=1 AND m.active=1 AND ms.service_id=?""", (service_id,))
    lines = [f'💇‍♀️ <b>KRASA</b> · шаг 2/4\n{DIV}',
             f'Услуга: <b>{svc[0]["title"]}</b>\n', 'К кому запишем?']
    buttons = [[{'text': '✦ Любой свободный', 'callback_data': 'mst_0'}]]
    for m in masters:
        buttons.append([{'text': f'✂️ {m["name"]}', 'callback_data': f'mst_{m["id"]}'}])
    buttons.append([{'text': '← Назад', 'callback_data': 'back_to_svc'}, {'text': '✕ Отмена', 'callback_data': 'cancel_book'}])
    await say(chat_id, '\n'.join(lines), kb(buttons))

async def show_dates(chat_id):
    lines = [f'💇‍♀️ <b>KRASA</b> · шаг 3/4\n{DIV}', 'Выбери дату:']
    buttons = []
    today = datetime.date.today()
    wd = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
    row = []
    for i in range(14):
        d = today + datetime.timedelta(days=i)
        label = 'сегодня' if i == 0 else 'завтра' if i == 1 else f'{wd[d.weekday()]} {d.day}.{d.month}'
        row.append({'text': label, 'callback_data': f'date_{d.isoformat()}'})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{'text': '← Назад', 'callback_data': 'back_to_mst'}, {'text': '✕ Отмена', 'callback_data': 'cancel_book'}])
    await say(chat_id, '\n'.join(lines), kb(buttons))

async def show_slots(chat_id):
    import slots
    state = dialog_state.get(chat_id)
    if not state:
        return
    data = state['data']
    mid, sid, date_str = data['master_id'], data['service_id'], data['date']

    if mid:
        times = slots.free_slots(mid, sid, date_str)
    else:
        times = [s['time'] for s in slots.free_slots_any(sid, date_str)]

    if not times:
        await say(chat_id,
            f'😔 <b>KRASA</b>\n{DIV}\n'
            f'На <b>{date_str[8:]}.{date_str[5:7]}</b> окон нет.\nВыбери другую дату:',
            kb([[{'text': '← Другая дата', 'callback_data': 'back_to_date'},
                 {'text': '✕ Отмена', 'callback_data': 'cancel_book'}]]))
        return

    lines = [f'💇‍♀️ <b>KRASA</b> · шаг 4/4\n{DIV}',
             f'📅 <b>{date_str[8:]}.{date_str[5:7]}</b> · свободные окна:']
    buttons = []
    row = []
    for t in times:
        row.append({'text': f'🕐 {t}', 'callback_data': f'slot_{t}'})
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{'text': '← Назад', 'callback_data': 'back_to_date'}, {'text': '✕ Отмена', 'callback_data': 'cancel_book'}])
    await say(chat_id, '\n'.join(lines), kb(buttons))

async def ask_name(chat_id):
    state = dialog_state.get(chat_id)
    if not state:
        return
    d = state['data']
    svc = db.q('SELECT title,price FROM services WHERE id=?', (d['service_id'],))[0]
    await say(chat_id,
        f'📝 <b>KRASA</b> · почти готово\n{DIV}\n'
        f'<blockquote>• {svc["title"]} · {svc["price"]} ₽\n'
        f'• 📅 {d["date"][8:]}.{d["date"][5:7]} в {d["slot"]}</blockquote>\n'
        f'Как тебя зовут? Ответь на это сообщение 👇',
        {'force_reply': True, 'input_field_placeholder': 'Твоё имя', 'selective': True})

async def show_confirm(chat_id):
    state = dialog_state.get(chat_id)
    if not state:
        return
    d = state['data']
    svc = db.q('SELECT title,price FROM services WHERE id=?', (d['service_id'],))[0]
    master_name = 'любой мастер'
    if d.get('master_id'):
        m = db.q('SELECT name FROM masters WHERE id=?', (d['master_id'],))
        if m:
            master_name = m[0]['name']
    await say(chat_id,
        f'✅ <b>KRASA</b> · подтверждение\n{DIV}\n'
        f'<blockquote>• {svc["title"]} · {svc["price"]} ₽\n'
        f'• ✂️ {master_name}\n'
        f'• 📅 {d["date"][8:]}.{d["date"][5:7]} в {d["slot"]}\n'
        f'• 👤 {d["name"]} · {d["phone"]}</blockquote>\n'
        f'Всё верно?',
        kb([
            [{'text': '✅ Подтвердить запись', 'callback_data': 'book_ok'}],
            [{'text': '✏️ Изменить контакты', 'callback_data': 'book_edit'}],
            [{'text': '✕ Отмена', 'callback_data': 'cancel_book'}],
        ]))

async def finish_booking(chat_id, tg_id):
    import slots
    state = dialog_state.pop(chat_id, None)
    if not state:
        return
    d = state['data']
    svc = db.q('SELECT duration,title,price FROM services WHERE id=?', (d['service_id'],))[0]
    end = slots._to_hhmm(slots._to_min(d['slot']) + svc['duration'])
    bid = db.exe("""INSERT INTO bookings(salon_id,master_id,service_id,client_tg_id,client_key,client_name,client_phone,date,start,end,status,comment,created)
              VALUES(1,?,?,?,?,?,?,?,?,?,'new','',datetime('now'))""",
           (d['master_id'], d['service_id'], tg_id, f'tg_{tg_id}',
            d['name'], d['phone'], d['date'], d['slot'], end))
    save_client(tg_id, d['name'], d['phone'])

    salon = db.q('SELECT owner_tg_id FROM salons WHERE id=1')[0]
    if salon['owner_tg_id']:
        await send_raw(salon['owner_tg_id'],
            f'🔔 <b>Новая запись!</b>\n{DIV}\n'
            f'<blockquote>• {svc["title"]} · {svc["price"]} ₽\n'
            f'• 📅 {d["date"][8:]}.{d["date"][5:7]} в {d["slot"]}\n'
            f'• 👤 {d["name"]} · {d["phone"]}</blockquote>\n'
            f'💡 Подтверди или отклони прямо здесь:',
            kb([[{'text': '✔ Подтвердить', 'callback_data': f'confirm_{bid}'},
                 {'text': '✕ Отклонить', 'callback_data': f'cancel_{bid}'}]]))
        await emote(salon['owner_tg_id'], '🔥')

    master_name = 'любой мастер'
    if d.get('master_id'):
        m = db.q('SELECT name FROM masters WHERE id=?', (d['master_id'],))
        if m:
            master_name = m[0]['name']
    await say(chat_id,
        f'🎉 <b>Запись создана!</b>\n{DIV}\n'
        f'<blockquote>• {svc["title"]} · {svc["price"]} ₽\n'
        f'• ✂️ {master_name}\n'
        f'• 📅 {d["date"][8:]}.{d["date"][5:7]} в {d["slot"]}</blockquote>\n'
        f'Салон скоро подтвердит.\n'
        f'⚡️ В следующий раз будет ещё быстрее — контакты я запомнил 😉',
        CLIENT_KB)
    await emote(chat_id, '🎉')

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
        await say(chat_id, f'✏️ <b>KRASA</b>\n{DIV}\nНапиши новое имя 👇',
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
            f'👋 Привет, <b>{name}</b>!\n{DIV}\nТеперь напиши номер телефона 👇',
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