import copy
import db_manager

db_manager.init_db()

# 3 базовые захардкоженные игры
DEFAULT_GAMES = {
    "GENSHIN": {
        "short_name": "GENSHIN",
        "promo_url": "https://api.ennead.cc/mihoyo/genshin/codes",
        "builtin": True
    },
    "STARRAIL": {
        "short_name": "STARRAIL",
        "promo_url": "https://api.ennead.cc/mihoyo/starrail/codes",
        "builtin": True
    },
    "ZZZ": {
        "short_name": "ZZZ",
        "promo_url": "https://api.ennead.cc/mihoyo/zenless/codes",
        "builtin": True
    }
}

ACCOUNTS = db_manager.load_accounts()
PROMOS = db_manager.load_promos()
SETTINGS = db_manager.load_settings()
GAMES = db_manager.load_games()

# Инициализация и слияние хардкодных игр с сохраненными в БД
if not GAMES:
    GAMES = copy.deepcopy(DEFAULT_GAMES)
    db_manager.save_games(GAMES)
else:
    for g_key, g_val in DEFAULT_GAMES.items():
        if g_key not in GAMES:
            GAMES[g_key] = copy.deepcopy(g_val)
        else:
            GAMES[g_key]["builtin"] = True

if not ACCOUNTS:
    old_cookies = db_manager.load_old_cookies()
    ACCOUNTS = {
        "acc_1": {
            "name": "Аккаунт 1",
            "cookies": old_cookies if old_cookies else {},
            "login": "",
            "password": "",
            "auto_daily": True,
            "auto_promo": True
        }
    }
    db_manager.save_accounts(ACCOUNTS)

def save_games():
    db_manager.save_games(GAMES)

def add_or_update_game(game_key, short_name, promo_url):
    key = game_key.strip().upper()
    if not key:
        return False
    is_builtin = key in DEFAULT_GAMES
    GAMES[key] = {
        "short_name": short_name.strip() or key,
        "promo_url": promo_url.strip(),
        "builtin": is_builtin
    }
    save_games()
    return True

def delete_game(game_key):
    if game_key in GAMES and not GAMES[game_key].get("builtin", False):
        del GAMES[game_key]
        save_games()
        return True
    return False

def get_game_short_name(raw_key):
    key = str(raw_key).upper()
    if key in GAMES:
        return GAMES[key].get("short_name", key)
    return key

def save_accounts():
    db_manager.save_accounts(ACCOUNTS)

def create_account():
    idx = 1
    while f"acc_{idx}" in ACCOUNTS:
        idx += 1
    acc_id = f"acc_{idx}"
    ACCOUNTS[acc_id] = {
        "name": f"Аккаунт {idx}",
        "cookies": {},
        "login": "",
        "password": "",
        "auto_daily": True,
        "auto_promo": True
    }
    save_accounts()
    return acc_id

def delete_account(acc_id):
    if acc_id in ACCOUNTS and len(ACCOUNTS) > 1:
        del ACCOUNTS[acc_id]
        save_accounts()
        return True
    return False

def update_account_cookies(acc_id, new_cookies):
    if acc_id in ACCOUNTS:
        ACCOUNTS[acc_id]["cookies"].update(new_cookies)
        save_accounts()

def clear_account_cookies(acc_id):
    if acc_id in ACCOUNTS:
        ACCOUNTS[acc_id]["cookies"] = {}
        save_accounts()

def update_promos(new_promos):
    global PROMOS
    PROMOS.update(new_promos)
    db_manager.save_promos(PROMOS)

def update_settings(new_settings):
    global SETTINGS
    SETTINGS.update(new_settings)
    db_manager.save_settings(SETTINGS)