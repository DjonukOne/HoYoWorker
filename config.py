import db_manager

db_manager.init_db()

COOKIES = db_manager.load_cookies()
PROMOS = db_manager.load_promos()
SETTINGS = db_manager.load_settings()

def update_cookies(new_cookies):
    global COOKIES
    COOKIES.update(new_cookies)
    db_manager.save_cookies(COOKIES)

def update_promos(new_promos):
    global PROMOS
    PROMOS.update(new_promos)
    db_manager.save_promos(PROMOS)

def update_settings(new_settings):
    global SETTINGS
    SETTINGS.update(new_settings)
    db_manager.save_settings(SETTINGS)

def clear_cookies():
    global COOKIES
    COOKIES = {}
    db_manager.clear_cookies()