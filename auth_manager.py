"""Авторизация HoYoLAB.

Главная идея: токены HoYoLAB (ltoken_v2 / cookie_token_v2) живут недолго,
поэтому их нельзя просто "сохранить и забыть". Мы храним в зашифрованном виде
всё, из чего можно получить НОВЫЙ токен, и запрашиваем его при каждом запуске:

1. ``stoken`` - долгоживущий токен аккаунта. Из него через
   ``ma-passport/token/getBySToken`` выпускаются свежие ``ltoken_v2``
   и ``cookie_token_v2`` (именно ``cookie_token_v2`` нужен для промокодов).
2. ``cookie_token_v2``/``cookie_token`` - их срок можно продлить запросом
   ``fetch_cookie_accountinfo`` (работает, пока токен ещё действителен).
3. Логин и пароль (опционально, сохраняются только с согласия пользователя) -
   позволяют полностью перевыпустить сессию, если токены уже мертвы.

Всё это лежит в конфиге в зашифрованном виде (см. db_manager).
"""

from __future__ import annotations

import hashlib
import random
import string
import time
import typing
import uuid

import aiohttp
import genshin

import config

APP_ID = "c9oqaq3s3gu8"
DS_SALT_APP_LOGIN = "IZPgfb0dRPtBeLuFkdDznSZ6f4wWt6y2"

STOKEN_TOKENS_URL = "https://sg-public-api.hoyoverse.com/account/ma-passport/token/getBySToken"
COOKIE_INFO_URL = "https://sg-public-api.hoyoverse.com/account/ma-cn-session/webapi/fetch_cookie_accountinfo"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Cookies с отпечатком устройства: HoYoLAB считает их частью "устройства",
# поэтому сохраняем и по возможности переиспользуем.
DEVICE_COOKIE_KEYS = ("_MHYUUID", "DEVICEFP", "DEVICEFP_SEED_ID", "DEVICEFP_SEED_TIME")

# Полный вход по паролю перевыпускает cookie-токен (нужен для промокодов),
# но каждое такое действие - повод для проверки "я не робот". Поэтому делаем
# его не чаще раза в двое суток и только когда сессия правда требует обновления.
RELOGIN_INTERVAL = 2 * 24 * 3600

# После запроса капчи не дёргаем авто-вход некоторое время, чтобы не злить
# защиту HoYoLAB и не показывать ошибку при каждом запуске.
CAPTCHA_COOLDOWN = 6 * 3600

# Cookies, которые можно отправлять в обычные запросы к API.
SESSION_COOKIE_KEYS = (
    "ltuid_v2", "ltmid_v2", "ltoken_v2", "cookie_token_v2",
    "account_id_v2", "account_mid_v2",
    "ltuid", "ltmid", "ltoken", "cookie_token", "account_id",
    "e_nap_token", "e_hkrpg_token",
)

# Корневые токены: дают доступ ко всему аккаунту, в обычные запросы не уходят.
ROOT_COOKIE_KEYS = ("stoken", "stoken_v2", "stuid", "mid", "login_ticket")


class AuthError(Exception):
    """Ошибка авторизации, текст можно показывать пользователю."""


class CaptchaRequired(AuthError):
    """HoYoLAB требует капчу - нужен вход через встроенный браузер."""


# --------------------------------------------------------------------------- #
# Состояние
# --------------------------------------------------------------------------- #

def is_authorized() -> bool:
    return bool(config.COOKIES)


def has_stoken() -> bool:
    return bool(config.CREDENTIALS.get("stoken"))


def has_password() -> bool:
    return bool(config.CREDENTIALS.get("password") and config.CREDENTIALS.get("account"))


def can_auto_refresh() -> bool:
    """Есть ли чем получить новый токен без участия пользователя."""
    return has_stoken() or has_password() or has_cookie_token()


def last_refresh_time() -> typing.Optional[int]:
    value = config.CREDENTIALS.get("last_refresh")
    return value if isinstance(value, int) else None


def mode_label() -> str:
    """Короткое описание режима авторизации для интерфейса."""
    if has_password():
        return "авто-вход по паролю"
    if has_stoken():
        return "авто-обновление по stoken"
    if config.COOKIES.get("cookie_token_v2") or config.COOKIES.get("cookie_token"):
        return "продление cookie-токена"
    return "нужен повторный вход"


def session_cookies() -> dict[str, str]:
    """Cookies для запросов: без корневых токенов."""
    jar = {key: str(value) for key, value in config.COOKIES.items() if value}
    for key in ROOT_COOKIE_KEYS:
        jar.pop(key, None)
    return jar


def create_client() -> "genshin.Client":
    """Клиент genshin с текущими cookies и автосохранением обновлённых токенов."""
    client = genshin.Client(session_cookies())
    try:
        # Библиотека сама умеет перевыпускать cookie_token по stoken;
        # хук сохраняет то, что она получила.
        client.on_cookie_update = persist_cookie_update
    except Exception:
        pass
    return client


def _split(cookies: typing.Mapping[str, typing.Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Разделить cookies на корневые токены и обычные."""
    root: dict[str, str] = {}
    rest: dict[str, str] = {}

    for name, value in cookies.items():
        if not value:
            continue
        if name in ("stoken", "stoken_v2"):
            root["stoken"] = str(value)
        elif name == "stuid":
            root["stuid"] = str(value)
        elif name == "mid":
            root["mid"] = str(value)
        elif name == "login_ticket":
            continue
        else:
            rest[name] = str(value)

    return root, rest


def _account_id(cookies: typing.Mapping[str, typing.Any]) -> typing.Optional[str]:
    for name in ("ltuid_v2", "account_id_v2", "ltuid", "account_id"):
        value = cookies.get(name)
        if value:
            return str(value)
    return None


def _absorb(cookies: typing.Mapping[str, typing.Any]) -> None:
    """Дописать полученные cookies (обновление токенов)."""
    root, rest = _split(cookies)

    if rest:
        config.update_cookies(rest)
    if root:
        config.set_credentials(**root)


def _replace(cookies: typing.Mapping[str, typing.Any]) -> None:
    """Полностью заменить сессию (новый вход в аккаунт)."""
    root, rest = _split(cookies)

    old_id = _account_id(config.COOKIES)
    new_id = _account_id(rest)

    # Вход выполнен под другим аккаунтом - старые токены и пароль больше не нужны.
    if old_id and new_id and old_id != new_id:
        config.set_credentials(stoken=None, stuid=None, mid=None, account=None, password=None)

    config.replace_cookies(rest)
    if root:
        config.set_credentials(**root)


def persist_cookie_update(cookies: typing.Mapping[str, typing.Any]) -> None:
    """Хук для genshin.Client: сохраняем то, что библиотека обновила сама."""
    try:
        _absorb(dict(cookies))
    except Exception:
        pass


def save_login_cookies(cookies: typing.Mapping[str, typing.Any]) -> None:
    """Сохранить cookies, полученные во встроенном браузере."""
    _replace(dict(cookies))
    config.set_credentials(last_login=int(time.time()), last_login_at=int(time.time()))


# --------------------------------------------------------------------------- #
# Устройство и защита от капчи
# --------------------------------------------------------------------------- #

def _device_id() -> str:
    """Постоянный идентификатор устройства.

    genshin по умолчанию придумывает новый device_id на каждый вход, и для
    HoYoLAB это каждый раз "новое устройство" - отсюда проверка "я не робот".
    Поэтому генерируем один раз и переиспользуем.
    """
    value = config.CREDENTIALS.get("device_id")
    if not value:
        value = str(uuid.uuid4())
        config.set_credentials(device_id=value)
    return str(value)


def _login_cookies() -> dict[str, str]:
    """Cookies, которые стоит отправить вместе с запросом входа."""
    jar = session_cookies()
    device = config.CREDENTIALS.get("device_cookies") or {}
    if isinstance(device, dict):
        jar.update({key: str(value) for key, value in device.items() if value})
    return jar


def captcha_blocked() -> bool:
    """Недавно HoYoLAB просил капчу - авто-вход временно не трогаем."""
    until = config.CREDENTIALS.get("captcha_until")
    return isinstance(until, int) and until > time.time()


def _set_captcha_block(seconds: int = CAPTCHA_COOLDOWN) -> None:
    config.set_credentials(captcha_until=int(time.time() + seconds))


def _relogin_due() -> bool:
    """Пора ли перевыпустить сессию по паролю (cookie-токен живёт пару дней)."""
    last = config.CREDENTIALS.get("last_login_at")
    if not isinstance(last, int):
        return True
    return (time.time() - last) >= RELOGIN_INTERVAL


def has_cookie_token() -> bool:
    return bool(config.COOKIES.get("cookie_token_v2") or config.COOKIES.get("cookie_token"))


def _mark_refreshed(source: str) -> None:
    config.set_credentials(
        last_refresh=int(time.time()),
        refresh_source=source,
        refresh_ok=True,
        last_refresh_note=None,
    )


# --------------------------------------------------------------------------- #
# Запросы к HoYoLAB
# --------------------------------------------------------------------------- #

def _dynamic_secret() -> str:
    stamp = int(time.time())
    rand = "".join(random.choices(string.ascii_letters, k=6))
    digest = hashlib.md5(f"salt={DS_SALT_APP_LOGIN}&t={stamp}&r={rand}".encode()).hexdigest()
    return f"{stamp},{rand},{digest}"


async def _json(response: aiohttp.ClientResponse) -> dict:
    try:
        data = await response.json(content_type=None)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def _refresh_with_stoken(log) -> bool:
    """Получить новые ltoken_v2 и cookie_token_v2 по stoken."""
    stoken = config.CREDENTIALS.get("stoken")
    mid = config.CREDENTIALS.get("mid") or config.COOKIES.get("ltmid_v2")
    if not stoken or not mid:
        return False

    cookies = {"stoken": stoken, "mid": mid}
    for key in ("ltuid_v2", "account_id_v2"):
        if config.COOKIES.get(key):
            cookies[key] = config.COOKIES[key]

    headers = {
        "ds": _dynamic_secret(),
        "x-rpc-app_id": APP_ID,
        "User-Agent": USER_AGENT,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                STOKEN_TOKENS_URL,
                json={"dst_token_types": [2, 4]},
                headers=headers,
                cookies=cookies,
            ) as response:
                data = await _json(response)
    except Exception as error:
        log(f"⚠️ Не удалось связаться с HoYoLAB: {error}")
        return False

    if data.get("retcode") != 0:
        log(f"⚠️ stoken отклонён (код {data.get('retcode')}: {data.get('message')}).")
        return False

    tokens = {
        item.get("token_type"): item.get("token")
        for item in (data.get("data") or {}).get("tokens", [])
        if isinstance(item, dict)
    }

    fresh = {}
    if tokens.get(2):
        fresh["ltoken_v2"] = tokens[2]
    if tokens.get(4):
        fresh["cookie_token_v2"] = tokens[4]

    if not fresh:
        return False

    _absorb(fresh)
    return True


async def _renew_cookie_token(log) -> bool:
    """Продлить срок жизни cookie-токена (нужен для ввода промокодов)."""
    jar = session_cookies()
    if not (jar.get("cookie_token") or jar.get("cookie_token_v2")):
        return False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                COOKIE_INFO_URL,
                cookies=jar,
                headers={"User-Agent": USER_AGENT},
            ) as response:
                data = await _json(response)
    except Exception as error:
        log(f"⚠️ Не удалось продлить cookie-токен: {error}")
        return False

    retcode = data.get("retcode")
    if retcode not in (0, None):
        log(
            f"⚠️ Продление cookie-токена недоступно "
            f"(код {retcode}: {data.get('message') or 'без описания'})."
        )
        return False

    payload = data.get("data") or {}
    info = payload.get("cookie_info") or {}
    if not info:
        log("⚠️ HoYoLAB не вернул cookie-токен при продлении.")
        return False

    fresh = {}
    if info.get("cookie_token"):
        fresh["cookie_token"] = info["cookie_token"]
    if info.get("account_id"):
        fresh["account_id"] = str(info["account_id"])

    if not fresh:
        return False

    _absorb(fresh)
    return True


async def _captcha_solver(_mmt) -> typing.Any:
    """Капчу в фоне не решаем - сообщаем пользователю, что нужен вход через браузер."""
    raise CaptchaRequired(
        "HoYoLAB требует проверку «я не робот». Войдите через кнопку «Войти в HoYoLAB»."
    )


async def login_with_password(
    account: str,
    password: str,
    *,
    remember: bool = True,
    log=print,
) -> bool:
    """Полный вход по логину и паролю. Выпускает свежие токены.

    ``remember=True`` - сохранить пароль в зашифрованном виде, чтобы приложение
    могло входить автоматически, когда токены всё-таки истекут.
    """
    account = (account or "").strip()
    if not account or not password:
        raise AuthError("Введите логин и пароль.")

    device_id = _device_id()
    client = genshin.Client(_login_cookies())
    try:
        # Подменяем генератор device_id: вход должен выглядеть как тот же
        # компьютер, иначе HoYoLAB каждый раз просит капчу.
        client.generate_web_device_id = lambda: device_id
    except Exception:
        pass

    try:
        result = await client.login_with_password(
            account, password, geetest_solver=_captcha_solver
        )
    except CaptchaRequired:
        _set_captcha_block()
        raise
    except genshin.errors.AccountLoginFail as error:
        raise AuthError("Неверный логин или пароль.") from error
    except genshin.errors.AccountDoesNotExist as error:
        raise AuthError("Аккаунт с таким логином не найден.") from error
    except ModuleNotFoundError as error:
        # Например "No module named 'rsa'" - не хватает зависимости для
        # шифрования пароля. Подсказываем, что делать.
        raise AuthError(
            f"Не хватает модуля «{error.name}». Установите зависимости командой "
            "pip install -r requirements.txt"
        ) from error
    except Exception as error:
        raise AuthError(f"Не удалось войти: {error}") from error

    # Все cookies, которые HoYoLAB выставил при входе (включая отпечаток
    # устройства и, если повезёт, stoken).
    manager_cookies = getattr(client.cookie_manager, "cookies", None)
    if manager_cookies:
        cookies = dict(manager_cookies)
    elif hasattr(result, "to_dict"):
        cookies = result.to_dict()
    else:
        cookies = dict(result)

    _replace(cookies)

    fingerprint = {key: value for key, value in cookies.items() if key in DEVICE_COOKIE_KEYS}
    if fingerprint:
        config.set_credentials(device_cookies=fingerprint)

    if not config.COOKIES.get("ltoken_v2") and not config.COOKIES.get("cookie_token_v2"):
        raise AuthError("HoYoLAB не выдал токены. Попробуйте войти через браузер.")

    config.set_credentials(
        account=account,
        password=password if remember else None,
        last_login_at=int(time.time()),
        captcha_until=None,
    )
    _mark_refreshed("password")
    log("✅ Вход выполнен, токены сохранены в зашифрованном виде.")
    return True


async def _login_with_stored_password(log) -> bool:
    account = config.CREDENTIALS.get("account")
    password = config.CREDENTIALS.get("password")
    if not account or not password:
        return False

    if captcha_blocked():
        log("ℹ️ Авто-вход по паролю пропущен: HoYoLAB недавно просил капчу.")
        return False

    try:
        return await login_with_password(account, password, remember=True, log=log)
    except CaptchaRequired:
        log(
            "ℹ️ HoYoLAB запросил капчу при авто-входе. "
            f"Авто-вход приостановлен на {CAPTCHA_COOLDOWN // 3600} ч, "
            "текущая сессия продолжает работать."
        )
        return False
    except AuthError as error:
        log(f"⚠️ Авто-вход не удался: {error}")
        return False


async def _verify_session() -> typing.Optional[bool]:
    """Проверить сессию реальным запросом.

    True - работает, False - токены отклонены HoYoLAB, None - сеть/прочее.
    """
    if not config.COOKIES:
        return False

    client = create_client()
    try:
        await client.get_game_accounts()
        return True
    except genshin.errors.InvalidCookies:
        return False
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Главная точка входа
# --------------------------------------------------------------------------- #

async def ensure_session(log=print) -> bool:
    """Запросить свежий токен. Вызывается при каждом запуске приложения.

    Порядок:
    1. дешёвые способы - stoken и продление cookie-токена (без капчи);
    2. полный вход по паролю - только если он действительно нужен
       (сессия мертва или cookie-токен давно не обновлялся) и HoYoLAB
       не просил капчу в последние часы;
    3. если сессия ещё рабочая - спокойно продолжаем с ней.
    """
    if not config.COOKIES and not has_stoken() and not has_password():
        return False

    log("🔐 Запрашиваем свежий токен HoYoLAB...")

    note = ""

    # Проверку сессии делаем максимум один раз за запуск.
    unchecked = object()
    verified: typing.Any = unchecked

    async def verify() -> typing.Optional[bool]:
        nonlocal verified
        if verified is unchecked:
            verified = await _verify_session()
        return verified

    def invalidate() -> None:
        nonlocal verified
        verified = unchecked

    # 1. Обновление по stoken - самый надёжный способ без капчи.
    if has_stoken():
        if await _refresh_with_stoken(log):
            invalidate()
            if await verify() is not False:
                _mark_refreshed("stoken")
                log("✅ Токен обновлён по stoken.")
                return True
            note = "токен, полученный по stoken, не подошёл"
        else:
            note = "stoken не принят HoYoLAB"

    # 2. Продление cookie-токена (именно он нужен для промокодов).
    if has_cookie_token():
        if await _renew_cookie_token(log):
            invalidate()
            if await verify() is not False:
                _mark_refreshed("cookie")
                log("✅ Токен обновлён продлением cookie-токена.")
                return True
            note = note or "продлённый cookie-токен не подошёл"
        else:
            note = note or "продление cookie-токена недоступно"

    # 3. Полный вход по паролю.
    if has_password():
        if captcha_blocked():
            note = "HoYoLAB недавно требовал капчу для авто-входа"
        else:
            needs_login = (await verify() is False) or _relogin_due()

            if needs_login:
                if await _login_with_stored_password(log):
                    invalidate()
                    if await verify() is not False:
                        _mark_refreshed("password")
                        log("✅ Сессия перевыпущена по паролю.")
                        return True
                    note = "вход по паролю не дал рабочую сессию"
                elif captcha_blocked():
                    note = "HoYoLAB требует капчу для авто-входа"
                else:
                    note = note or "авто-вход по паролю не удался"

    # 4. Может, текущий токен ещё жив - тогда просто работаем дальше.
    if await verify() is not False:
        note = note or "новый токен сейчас получить нельзя"
        config.set_credentials(refresh_ok=False, last_refresh_note=note)
        log(
            f"<span style='color:#ffcc66;'>ℹ️ {note.capitalize()}. "
            "Используем текущую сессию - если промокоды перестанут приниматься, "
            "войдите в аккаунт заново.</span>"
        )
        return True

    config.set_credentials(refresh_ok=False, last_refresh_note="сессия недействительна")
    log(
        "<span style='color:#ff5555;'>🛑 Сессия HoYoLAB недействительна. "
        "Войдите в аккаунт заново.</span>"
    )
    return False
