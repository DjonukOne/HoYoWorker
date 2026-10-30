import asyncio
import time

import aiohttp
import genshin
from PyQt6.QtCore import QObject, pyqtSignal

import auth_manager
import config

GAME_NAMES = {
    genshin.Game.GENSHIN: "GENSHIN",
    genshin.Game.STARRAIL: "STARRAIL",
    genshin.Game.ZZZ: "ZZZ"
}

PROMO_URLS = {
    genshin.Game.GENSHIN: "https://api.ennead.cc/mihoyo/genshin/codes",
    genshin.Game.STARRAIL: "https://api.ennead.cc/mihoyo/starrail/codes",
    genshin.Game.ZZZ: "https://api.ennead.cc/mihoyo/zenless/codes"
}

# Как часто обновлять токен, если приложение работает без перезапуска.
SESSION_MAX_AGE = 6 * 3600


class SessionExpired(Exception):
    """Токен перестал работать во время выполнения задачи."""


class HoYoWorker(QObject):
    log_signal = pyqtSignal(str)
    accounts_signal = pyqtSignal(list)
    auth_signal = pyqtSignal(bool)

    # ------------------------------------------------------------------ #
    # Авторизация
    # ------------------------------------------------------------------ #

    def run_startup(self):
        asyncio.run(self.async_startup())

    async def async_startup(self):
        """Запросить новый токен при запуске и показать аккаунты."""
        ok = await auth_manager.ensure_session(log=self.log_signal.emit)
        self.auth_signal.emit(bool(ok))
        await self._get_accs_only()

    async def _refresh_auth(self) -> bool:
        self.log_signal.emit("🔄 Обновляем токен, это займёт пару секунд...")
        ok = await auth_manager.ensure_session(log=self.log_signal.emit)
        if not ok:
            self.log_signal.emit(
                "<span style='color: #ff5555;'>🛑 Сессия HoYoLAB недействительна. "
                "Войдите в аккаунт заново.</span>"
            )
        self.auth_signal.emit(bool(ok))
        return ok

    async def _ensure_fresh_auth(self) -> bool:
        """Обновить токен, если он давно не обновлялся (например, приложение сутками в трее)."""
        last = auth_manager.last_refresh_time()
        if last and (time.time() - last) < SESSION_MAX_AGE:
            return True
        return await self._refresh_auth()

    def fetch_accounts_info(self):
        asyncio.run(self._get_accs_only())

    async def _get_accs_only(self):
        if not config.COOKIES:
            self.accounts_signal.emit([])
            return
        try:
            client = auth_manager.create_client()
            accounts = await client.get_game_accounts()

            acc_list = []
            for acc in accounts:
                short_name = GAME_NAMES.get(acc.game, acc.game.name.upper())
                nick = acc.nickname if acc.nickname else "Без имени"
                acc_list.append({"game": short_name, "uid": acc.uid, "level": acc.level, "nickname": nick})

            self.accounts_signal.emit(acc_list)
        except Exception:
            self.accounts_signal.emit([])

    # ------------------------------------------------------------------ #
    # Ежедневные отметки
    # ------------------------------------------------------------------ #

    def run_daily(self):
        asyncio.run(self.async_daily())

    async def async_daily(self):
        if not config.COOKIES:
            self.log_signal.emit("❌ Нет куки! Авторизуйтесь.")
            return

        for attempt in (1, 2):
            try:
                await self._claim_daily_once()
                return
            except (genshin.errors.InvalidCookies, SessionExpired):
                if attempt == 2:
                    self.log_signal.emit(
                        "<span style='color: #ff5555;'>🛑 Токен отклонён. "
                        "Войдите в аккаунт заново.</span>"
                    )
                    return
                if not await self._refresh_auth():
                    return

    async def _claim_daily_once(self):
        self.log_signal.emit("📅 Начинаем сбор ежедневных отметок...")
        client = auth_manager.create_client()
        try:
            accounts = await client.get_game_accounts()
            for acc in accounts:
                short_name = GAME_NAMES.get(acc.game, acc.game.name.upper())
                self.log_signal.emit(f"<span style='color: #d4af37;'><b>🎮 {short_name} (UID: {acc.uid})</b></span>")
                try:
                    reward = await client.claim_daily_reward(game=acc.game)
                    self.log_signal.emit(f"  ✅ Собрано: {reward.amount} x {reward.name}")
                except genshin.errors.AlreadyClaimed:
                    self.log_signal.emit("  ⏳ [Уже собрано]")
                except genshin.errors.InvalidCookies:
                    raise
                except Exception as e:
                    self.log_signal.emit(f"  ❌ Ошибка: {e}")
                await asyncio.sleep(2)
            self.log_signal.emit("✨ <b>Отметки завершены!</b>")
        except genshin.errors.InvalidCookies:
            raise
        except Exception as e:
            self.log_signal.emit(f"<span style='color: #ff5555;'>🛑 Ошибка API: {e}</span>")

    # ------------------------------------------------------------------ #
    # Промокоды
    # ------------------------------------------------------------------ #

    def run_collect_promos(self):
        asyncio.run(self.async_collect_promos())

    async def fetch_codes(self, url):
        codes = set()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        items = []
                        if isinstance(data, dict):
                            if "active" in data: items = data["active"]
                            elif "CODES" in data: items = data["CODES"]
                        elif isinstance(data, list):
                            items = data

                        for item in items:
                            if isinstance(item, dict):
                                if item.get("is_expired") is True: continue
                                code = item.get("code") or item.get("CODES")
                                if code: codes.add(str(code).strip())
                            elif isinstance(item, str):
                                codes.add(item.strip())
        except Exception: pass
        return list(codes)

    async def async_collect_promos(self):
        self.log_signal.emit("🌐 Сканируем интернет на новые коды...")
        
        if not isinstance(config.PROMOS, dict) or "active_codes" not in config.PROMOS:
            config.PROMOS = {"active_codes": {}, "history": {}}

        new_total_added = 0
        
        for game_enum, url in PROMO_URLS.items():
            short = GAME_NAMES.get(game_enum, "ИГРА")
            codes = await self.fetch_codes(url)
            
            current_active = set(config.PROMOS["active_codes"].get(game_enum.name, []))
            fresh_active = set(codes)
            new_codes = fresh_active - current_active
            config.PROMOS["active_codes"][game_enum.name] = codes
            
            if new_codes:
                self.log_signal.emit(f"  📥 {short}: найдено {len(new_codes)} новых кодов! (Всего актуальных: {len(codes)})")
                new_total_added += len(new_codes)
            else:
                self.log_signal.emit(f"  📥 {short}: новых кодов нет. База актуальна ({len(codes)} шт).")
        
        config.update_promos(config.PROMOS)
        
        if new_total_added > 0:
            self.log_signal.emit(f"✨ <b>База обновлена! Сохранено новых кодов: {new_total_added}.</b>")
        else:
            self.log_signal.emit("✨ <b>База данных не нуждается в обновлении.</b>")

    def run_redeem_promos(self):
        asyncio.run(self.async_redeem_promos())

    async def async_redeem_promos(self):
        if not config.COOKIES:
            self.log_signal.emit("❌ Нет куки! Авторизуйтесь.")
            return

        if not isinstance(config.PROMOS, dict) or "active_codes" not in config.PROMOS:
            self.log_signal.emit("⚠️ База кодов пуста! Сначала нажмите 'Спарсить промокоды'.")
            return

        for attempt in (1, 2):
            try:
                await self._redeem_promos_once()
                return
            except (genshin.errors.InvalidCookies, SessionExpired):
                if attempt == 2:
                    self.log_signal.emit(
                        "<span style='color: #ff5555;'>🛑 Токен отклонён. "
                        "Войдите в аккаунт заново.</span>"
                    )
                    return
                if not await self._refresh_auth():
                    return
                self.log_signal.emit("♻️ Повторяем ввод промокодов с новым токеном...")

    async def _redeem_promos_once(self):
        if not await self._ensure_fresh_auth():
            return

        self.log_signal.emit("🎁 Начинаем ввод промокодов из БД...")
        client = auth_manager.create_client()

        accounts = await client.get_game_accounts()
        for acc in accounts:
            if acc.game not in PROMO_URLS:
                continue

            short_name = GAME_NAMES.get(acc.game, acc.game.name.upper())
            server_name = acc.server_name or "Неизвестный сервер"
            nick = acc.nickname or "Без имени"

            self.log_signal.emit(f"<br><span style='color: #d4af37;'><b>🎮 {short_name} (UID: {acc.uid} | {server_name} | {nick})</b></span>")

            active_codes = config.PROMOS["active_codes"].get(acc.game.name, [])

            uid_str = str(acc.uid)
            if "history" not in config.PROMOS:
                config.PROMOS["history"] = {}
            if uid_str not in config.PROMOS["history"]:
                config.PROMOS["history"][uid_str] = []

            uid_history = config.PROMOS["history"][uid_str]

            to_check = [c for c in active_codes if c not in uid_history]

            if not to_check:
                self.log_signal.emit("  🤷 Все актуальные коды для этого аккаунта уже были проверены ранее.")
                continue

            self.log_signal.emit(f"  📦 Проверяем {len(to_check)} новых кодов. Ждите, это займет время...")
            activated_count = 0

            for code in to_check:
                add_to_history = False
                try:
                    await client.redeem_code(code, uid=acc.uid, game=acc.game)
                    self.log_signal.emit(f"  💎 <span style='color: #55ff55;'>Код {code} успешно активирован!</span>")
                    activated_count += 1
                    add_to_history = True

                except genshin.errors.InvalidCookies:
                    raise

                except genshin.errors.RedemptionException as e:
                    msg = str(e.msg).lower()
                    if e.retcode == -100 or "login" in msg or "cookie" in msg:
                        raise SessionExpired(str(e.msg))
                    if "cooldown" in msg or e.retcode == -5003:
                        self.log_signal.emit(f"  ⏳ Сервер просит подождать. Код {code} пропущен, проверим в следующий раз.")
                    elif "already" in msg or "claimed" in msg or "expired" in msg or "invalid" in msg or "in use" in msg or "not exist" in msg:
                        add_to_history = True
                    else:
                        self.log_signal.emit(f"  ⚠️ Отказ ({code}): {e.msg}")

                except Exception as e:
                    self.log_signal.emit(f"  ❌ Системная ошибка ({code}): {e}")

                if add_to_history:
                    uid_history.append(code)
                    config.update_promos(config.PROMOS)

                await asyncio.sleep(6)

            if activated_count == 0:
                self.log_signal.emit("  ℹ️ Подходящих рабочих кодов не нашлось.")

        self.log_signal.emit("✨ <b>Проверка кодов завершена!</b>")

    def run_auto_promos(self):
        asyncio.run(self.async_collect_promos())
        asyncio.run(self.async_redeem_promos())
