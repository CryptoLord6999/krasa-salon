import sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / 'data'
DB_PATH = DATA_DIR / 'salon.db'

SCHEMA = """
CREATE TABLE IF NOT EXISTS salons(
  id INTEGER PRIMARY KEY, title TEXT, address TEXT, owner_tg_id INTEGER,
  slot_step INTEGER DEFAULT 30, cancel_hours INTEGER DEFAULT 2,
  remind_24h INTEGER DEFAULT 1, remind_2h INTEGER DEFAULT 1, created TEXT);
CREATE TABLE IF NOT EXISTS services(
  id INTEGER PRIMARY KEY, salon_id INTEGER, title TEXT,
  duration INTEGER, price INTEGER, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS masters(
  id INTEGER PRIMARY KEY, salon_id INTEGER, name TEXT,
  color TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS master_services(
  master_id INTEGER, service_id INTEGER);
CREATE TABLE IF NOT EXISTS master_week(
  master_id INTEGER, weekday INTEGER, start TEXT, end TEXT);
CREATE TABLE IF NOT EXISTS master_off(
  id INTEGER PRIMARY KEY, master_id INTEGER, date TEXT,
  start TEXT, end TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS clients(
  id INTEGER PRIMARY KEY, tg_id INTEGER, name TEXT, phone TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY, salon_id INTEGER, master_id INTEGER, service_id INTEGER,
  client_tg_id INTEGER, client_name TEXT, client_phone TEXT,
  date TEXT, start TEXT, end TEXT, status TEXT DEFAULT 'new',
  comment TEXT, created TEXT, remind1 INTEGER DEFAULT 0, remind2 INTEGER DEFAULT 0);
"""

def conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def q(sql, params=()):
    c = conn()
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    finally:
        c.close()

def exe(sql, params=()):
    c = conn()
    try:
        cur = c.execute(sql, params)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()

def init_db():
    c = conn()
    c.executescript(SCHEMA)
    c.commit()
    # Миграция: колонка client_key для клиентских записей
    cols = [r['name'] for r in c.execute('PRAGMA table_info(bookings)')]
    if 'client_key' not in cols:
        c.execute("ALTER TABLE bookings ADD COLUMN client_key TEXT DEFAULT ''")
        c.commit()
        print('🧬 Миграция: добавлена колонка client_key')
    if not c.execute('SELECT id FROM salons WHERE id=1').fetchone():
        c.execute("""INSERT INTO salons(id,title,address,slot_step,cancel_hours,created)
                     VALUES(1,'Салон KRASA','',30,2,datetime('now'))""")
        s1 = c.execute("INSERT INTO services(salon_id,title,duration,price) VALUES(1,'Стрижка женская',60,2500)").lastrowid
        s2 = c.execute("INSERT INTO services(salon_id,title,duration,price) VALUES(1,'Окрашивание в один тон',120,6000)").lastrowid
        s3 = c.execute("INSERT INTO services(salon_id,title,duration,price) VALUES(1,'Маникюр с покрытием',90,2200)").lastrowid
        m1 = c.execute("INSERT INTO masters(salon_id,name,color) VALUES(1,'Анна','#FF4D8D')").lastrowid
        m2 = c.execute("INSERT INTO masters(salon_id,name,color) VALUES(1,'Мария','#8B5CF6')").lastrowid
        for m in (m1, m2):
            for wd in range(6):
                c.execute('INSERT INTO master_week(master_id,weekday,start,end) VALUES(?,?,?,?)', (m, wd, '10:00', '20:00'))
        c.execute('INSERT INTO master_services(master_id,service_id) VALUES(?,?)', (m1, s1))
        c.execute('INSERT INTO master_services(master_id,service_id) VALUES(?,?)', (m1, s2))
        c.execute('INSERT INTO master_services(master_id,service_id) VALUES(?,?)', (m2, s1))
        c.execute('INSERT INTO master_services(master_id,service_id) VALUES(?,?)', (m2, s3))
        c.commit()
        print('🌱 База создана с демо-данными')
    c.close()