import ctypes
import json
import os
import sqlite3
import sys
from ctypes import wintypes
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

appdata_dir = Path(os.getenv('APPDATA', os.path.expanduser('~'))) / 'HoYoWorker'
appdata_dir.mkdir(parents=True, exist_ok=True)

DB_FILE = str(appdata_dir / 'ho_data.db')
KEY_FILE = str(appdata_dir / 'secret.key')

# Ключ шифрования на Windows дополнительно оборачивается через DPAPI:
# его сможет расшифровать только ваш пользователь Windows на этом компьютере.
# Даже если файлы ho_data.db и secret.key украдут, пароли/токены не прочитать.
DPAPI_PREFIX = b'DPAPI1:'
HAS_DPAPI = sys.platform == 'win32'
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    """Зашифровать/расшифровать данные средствами Windows DPAPI."""
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    if protect:
        crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptProtectData.restype = wintypes.BOOL
    else:
        crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
        ]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL

    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    blob_out = _DataBlob()

    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )

    if not ok:
        raise OSError('DPAPI вернул ошибку')

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(blob_out.pbData)


def _read_key_file() -> bytes:
    with open(KEY_FILE, 'rb') as f:
        raw = f.read()

    if raw.startswith(DPAPI_PREFIX):
        return _dpapi(raw[len(DPAPI_PREFIX):], protect=False)

    # Старый формат (ключ лежал открытым текстом) - переносим под DPAPI.
    if HAS_DPAPI:
        try:
            _write_key_file(raw)
        except Exception:
            pass
    return raw


def _write_key_file(key: bytes) -> None:
    payload = (DPAPI_PREFIX + _dpapi(key, protect=True)) if HAS_DPAPI else key
    tmp_file = KEY_FILE + '.tmp'
    with open(tmp_file, 'wb') as f:
        f.write(payload)
    try:
        os.chmod(tmp_file, 0o600)
    except OSError:
        pass
    os.replace(tmp_file, KEY_FILE)


def _get_cipher() -> Fernet:
    key = None
    if os.path.exists(KEY_FILE):
        try:
            key = _read_key_file()
        except Exception:
            # Ключ повреждён или принадлежит другому пользователю Windows.
            # Старые данные прочитать не получится, создаём новую сессию.
            key = None

    if not key:
        key = Fernet.generate_key()
        _write_key_file(key)

    try:
        return Fernet(key)
    except Exception:
        # Файл ключа повреждён - создаём новый (старые данные придётся ввести заново).
        key = Fernet.generate_key()
        _write_key_file(key)
        return Fernet(key)


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS secure_storage (key TEXT PRIMARY KEY, value BLOB)')
    conn.commit()
    conn.close()


def _write(key: str, data_bytes: bytes) -> None:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO secure_storage (key, value) VALUES (?, ?)", (key, data_bytes))
    conn.commit()
    conn.close()


def save_data(key, data_dict):
    encrypted_data = _get_cipher().encrypt(json.dumps(data_dict, ensure_ascii=False).encode('utf-8'))
    _write(key, encrypted_data)


def load_data(key):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM secure_storage WHERE key=?", (key,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {}

    try:
        return json.loads(_get_cipher().decrypt(row[0]).decode('utf-8'))
    except (InvalidToken, ValueError):
        return {}


def delete_data(key) -> None:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM secure_storage WHERE key=?", (key,))
    conn.commit()
    conn.close()


def save_credentials(data): save_data('credentials', data)
def load_credentials(): return load_data('credentials')

def save_cookies(data): save_data('cookies', data)
def load_cookies(): return load_data('cookies')

def save_promos(data): save_data('promos', data)
def load_promos(): return load_data('promos')

def save_settings(data): save_data('settings', data)
def load_settings(): return load_data('settings')

def clear_credentials():
    delete_data('credentials')

def clear_cookies():
    delete_data('cookies')
