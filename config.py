import os
from pathlib import Path

BASE = Path(__file__).resolve().parent

# ВСТАВЬ СВОЙ ТОКЕН МЕЖДУ ОДИНАРНЫМИ КАВЫЧКАМИ НИЖЕ (вместо примера):
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8943072414:AAE09dUD9Lgw0xlo8k5DoQ-Hez-J_ysz5nE')

PUBLIC_URL = os.environ.get('PUBLIC_URL', 'https://krasa-salon-production.up.railway.app')
TG_API = f'https://api.telegram.org/bot{BOT_TOKEN}'
PROXY = None