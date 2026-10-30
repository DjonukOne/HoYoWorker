"""Глобальное состояние приложения: зашифрованные учётные данные, промокоды, настройки."""

import time

import db_manager

db_manager.init_db()

# Всё, что нужно для входа, лежит в одном зашифрованном словаре:
#   cookies  - рабочие cookies HoYoLAB (ltoken_v2, cookie_token_v2, ltuid_v2, ...)
#   stoken   - долгоживущий токен, из которого можно получать новые токены
#   stuid/mid - идентификаторы аккаунта, нужные вместе со stoken
#   account/password - логин и пароль (только если пользователь согласился их сохранить)
CREDENTIALS = db_manager.load_credentials()
if not isinstance(CREDENTIALS, dict):
    CREDENTIALS = {}

CREDENTIALS.setdefault("cookies", {})
if not isinstance(CREDENTIALS["cookies"], dict):
    CREDENTIALS["cookies"] = {}

# Совместимость с версией, которая хранила cookies отдельной записью.
_legacy_cookies = db_manager.load_cookies()
if _legacy_cookies:
    for name, value in _legacy_cookies.items():
        CREDENTIALS["cookies"].setdefault(name, value)
    db_manager.clear_cookies()
    db_manager.save_credentials(CREDENTIALS)

COOKIES = CREDENTIALS["cookies"]

PROMOS = db_manager.load_promos()
SETTINGS = db_manager.load_settings()


def _sync():
    """Держать COOKIES тем же объектом, что и CREDENTIALS['cookies']."""
    global COOKIES
    COOKIES = CREDENTIALS["cookies"]
    return COOKIES


def save_credentials() -> None:
    CREDENTIALS["saved_at"] = int(time.time())
    db_manager.save_credentials(CREDENTIALS)


def update_cookies(new_cookies):
    """Добавить/обновить cookies и сразу сохранить их в зашифрованном виде."""
    cookies = _sync()
    for name, value in (new_cookies or {}).items():
        if value:
            cookies[name] = str(value)
    save_credentials()


def replace_cookies(new_cookies):
    """Заменить cookies целиком (новый вход в аккаунт)."""
    cookies = _sync()
    cookies.clear()
    for name, value in (new_cookies or {}).items():
        if value:
            cookies[name] = str(value)
    save_credentials()


def set_credentials(**values):
    """Обновить произвольные поля учётных данных (stoken, логин, пароль и т.д.)."""
    for key, value in values.items():
        if value is None:
            CREDENTIALS.pop(key, None)
        else:
            CREDENTIALS[key] = value
    save_credentials()


def update_promos(new_promos):
    global PROMOS
    PROMOS.update(new_promos)
    db_manager.save_promos(PROMOS)


def update_settings(new_settings):
    global SETTINGS
    SETTINGS.update(new_settings)
    db_manager.save_settings(SETTINGS)


def has_cookies() -> bool:
    return bool(COOKIES)


def clear_session():
    """Полный выход: удаляем cookies, stoken и сохранённый пароль."""
    global CREDENTIALS
    CREDENTIALS = {"cookies": {}}
    _sync()
    db_manager.clear_credentials()
    db_manager.clear_cookies()


# Старое название, чтобы не ломать существующий код.
def clear_cookies():
    clear_session()
