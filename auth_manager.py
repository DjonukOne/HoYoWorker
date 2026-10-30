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
    return has_stoken() or has_password() or bool(
        config.COOKIES.get("cookie_token_v2") or config.COOKIES.get("cookie_token")
    )


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
    config.set_credentials(last_login=int(time.time()))


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

    payload = data.get("data") or {}
    info = payload.get("cookie_info") or {}
    if not info:
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

    client = genshin.Client()
    try:
        result = await client.login_with_password(
            account, password, geetest_solver=_captcha_solver
        )
    except CaptchaRequired:
        raise
    except genshin.errors.AccountLoginFail as error:
        raise AuthError("Неверный логин или пароль.") from error
    except genshin.errors.AccountDoesNotExist as error:
        raise AuthError("Аккаунт с таким логином не найден.") from error
    except Exception as error:
        raise AuthError(f"Не удалось войти: {error}") from error

    cookies = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    _replace(cookies)

    if not config.COOKIES.get("ltoken_v2") and not config.COOKIES.get("cookie_token_v2"):
        raise AuthError("HoYoLAB не выдал токены. Попробуйте войти через браузер.")

    config.set_credentials(
        account=account,
        password=password if remember else None,
        last_refresh=int(time.time()),
        refresh_source="password",
    )
    log("✅ Вход выполнен, токены сохранены в зашифрованном виде.")
    return True


async def _login_with_stored_password(log) -> bool:
    account = config.CREDENTIALS.get("account")
    password = config.CREDENTIALS.get("password")
    if not account or not password:
        return False

    try:
        return await login_with_password(account, password, remember=True, log=log)
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
    """Запросить свежий токен. Вызывается при каждом запуске приложения."""
    if not config.COOKIES and not has_stoken() and not has_password():
        return False

    log("🔐 Запрашиваем свежий токен HoYoLAB...")

    attempts: list[tuple[str, typing.Any, str]] = []

    if has_stoken():
        attempts.append(("stoken", _refresh_with_stoken, "по stoken"))
    if config.COOKIES.get("cookie_token_v2") or config.COOKIES.get("cookie_token"):
        attempts.append(("cookie", _renew_cookie_token, "продлением cookie-токена"))
    if has_password():
        attempts.append(("password", _login_with_stored_password, "по сохранённому паролю"))

    if not attempts:
        log(
            "⚠️ Нет данных для автоматического обновления токена. "
            "Включите «Авто-вход по паролю», чтобы сессия продлевалась сама."
        )
        config.set_credentials(refresh_ok=False)
        # Токен обновить нечем, но сохранённая сессия может быть ещё живой.
        return await _verify_session() is not False

    for source, refresh, title in attempts:
        if not await refresh(log):
            continue

        status = await _verify_session()
        if status is False:
            log(f"⚠️ Токен, полученный {title}, не подошёл. Пробуем другой способ.")
            continue

        config.set_credentials(
            last_refresh=int(time.time()),
            refresh_source=source,
            refresh_ok=True,
        )
        log(f"✅ Токен обновлён {title}.")
        return True

    config.set_credentials(refresh_ok=False)

    if await _verify_session() is not False:
        log(
            "<span style='color:#ffcc66;'>⚠️ Обновить токен не удалось, но текущая сессия "
            "пока работает. Скоро потребуется повторный вход.</span>"
        )
        return True

    log(
        "<span style='color:#ff5555;'>🛑 Не удалось обновить токен. "
        "Скорее всего, сессия отозвана - войдите в аккаунт заново.</span>"
    )
    return False
