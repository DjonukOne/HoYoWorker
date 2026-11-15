import sqlite3
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet

appdata_dir = Path(os.getenv('APPDATA', os.path.expanduser('~'))) / 'HoYoWorker'
appdata_dir.mkdir(parents=True, exist_ok=True)

DB_FILE = str(appdata_dir / 'ho_data.db')
KEY_FILE = str(appdata_dir / 'secret.key')

def _get_cipher():
    if not os.path.exists(KEY_FILE):
        key = Fernet.generate_key()
        with open(KEY_FILE, 'wb') as f:
            f.write(key)
    else:
        with open(KEY_FILE, 'rb') as f:
            key = f.read()
    return Fernet(key)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS secure_storage (key TEXT PRIMARY KEY, value BLOB)')
    conn.commit()
    conn.close()

def save_data(key, data_dict):
    cipher = _get_cipher()
    data_bytes = json.dumps(data_dict).encode('utf-8')
    encrypted_data = cipher.encrypt(data_bytes)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO secure_storage (key, value) VALUES (?, ?)", (key, encrypted_data))
    conn.commit()
    conn.close()

def load_data(key):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM secure_storage WHERE key=?", (key,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        try:
            return json.loads(_get_cipher().decrypt(row[0]).decode('utf-8'))
        except Exception:
            return {}
    return {}

def save_accounts(data): save_data('accounts', data)
def load_accounts(): return load_data('accounts')

def save_promos(data): save_data('promos', data)
def load_promos(): return load_data('promos')

def save_settings(data): save_data('settings', data)
def load_settings(): return load_data('settings')

def save_games(data): save_data('games', data)
def load_games(): return load_data('games')

def load_old_cookies(): return load_data('cookies')