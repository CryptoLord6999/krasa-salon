import datetime
import db

def _to_min(t):
    h, m = t.split(':')
    return int(h) * 60 + int(m)

def _to_hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"

def master_week_map(master_id):
    rows = db.q('SELECT weekday,start,end FROM master_week WHERE master_id=?', (master_id,))
    return {r['weekday']: (r['start'], r['end']) for r in rows}

def busy_intervals(master_id, date_str):
    iv = []
    for b in db.q("SELECT start,end FROM bookings WHERE master_id=? AND date=? AND status IN ('new','confirmed')", (master_id, date_str)):
        iv.append((_to_min(b['start']), _to_min(b['end'])))
    for o in db.q('SELECT start,end FROM master_off WHERE master_id=? AND date=?', (master_id, date_str)):
        iv.append((_to_min(o['start'] or '00:00'), _to_min(o['end'] or '23:59')))
    iv.sort()
    return iv

def free_slots(master_id, service_id, date_str, step=None):
    salon = db.q('SELECT slot_step FROM salons WHERE id=1')[0]
    step = step or salon['slot_step'] or 30
    svc = db.q('SELECT duration FROM services WHERE id=?', (service_id,))
    if not svc:
        return []
    dur = svc[0]['duration']
    wk = master_week_map(master_id)
    wd = datetime.date.fromisoformat(date_str).weekday()
    if wd not in wk:
        return []
    ws, we = wk[wd]
    start, end = _to_min(ws), _to_min(we)
    busy = busy_intervals(master_id, date_str)
    slots = []
    t = start
    while t + dur <= end:
        if all(not (t < be and bs < t + dur) for bs, be in busy):
            slots.append(_to_hhmm(t))
        t += step
    return slots

def free_slots_any(service_id, date_str):
    """Слоты по всем мастерам с этой услугой: [{time, master_id, master_name}]"""
    out = {}
    rows = db.q("""SELECT m.id, m.name FROM masters m
                   JOIN master_services ms ON ms.master_id=m.id
                   WHERE m.salon_id=1 AND m.active=1 AND ms.service_id=?""", (service_id,))
    for m in rows:
        for t in free_slots(m['id'], service_id, date_str):
            if t not in out:
                out[t] = {'time': t, 'master_id': m['id'], 'master_name': m['name']}
    return [out[k] for k in sorted(out)]