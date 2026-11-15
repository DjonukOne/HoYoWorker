import db_manager

db_manager.init_db()

ACCOUNTS = db_manager.load_accounts()
PROMOS = db_manager.load_promos()
SETTINGS = db_manager.load_settings()

# Миграция со старой версии (если были старые куки, переносим в Аккаунт 1)
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