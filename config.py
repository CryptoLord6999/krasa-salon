import os
from pathlib import Path

BASE = Path(__file__).resolve().parent

BOT_TOKEN = os.environ.get('BOT_TOKEN', 'ТВОЙ_ТОКЕН_ОТ_BOTFATHER')
PUBLIC_URL = os.environ.get('PUBLIC_URL', 'https://твой-адрес.up.railway.app')
TG_API = f'https://api.telegram.org/bot{BOT_TOKEN}'
PROXY = None