import asyncio
import aiohttp
import genshin
from PyQt6.QtCore import QObject, pyqtSignal
import config

GAME_NAMES = {
    genshin.Game.GENSHIN: "GENSHIN",
    genshin.Game.STARRAIL: "STARRAIL",
    genshin.Game.ZZZ: "ZZZ"
}

STRING_TO_GAME = {
    "GENSHIN": genshin.Game.GENSHIN,
    "STARRAIL": genshin.Game.STARRAIL,
    "ZZZ": genshin.Game.ZZZ
}

PROMO_URLS = {
    genshin.Game.GENSHIN: "https://api.ennead.cc/mihoyo/genshin/codes",
    genshin.Game.STARRAIL: "https://api.ennead.cc/mihoyo/starrail/codes",
    genshin.Game.ZZZ: "https://api.ennead.cc/mihoyo/zenless/codes"
}

class HoYoWorker(QObject):
    log_signal = pyqtSignal(str, str)        # (acc_id или 'ALL', текст)
    accounts_signal = pyqtSignal(str, list)  # (acc_id, список персонажей)
    need_relogin_signal = pyqtSignal(str)    # (acc_id)
    notify_signal = pyqtSignal(str, str)     # (Заголовок, Текст)

    def fetch_accounts_info(self, acc_id):
        asyncio.run(self._get_accs_only(acc_id))

    async def _get_accs_only(self, acc_id):
        cookies = config.ACCOUNTS.get(acc_id, {}).get("cookies", {})
        if not cookies:
            self.accounts_signal.emit(acc_id, [])
            return
        try:
            client = genshin.Client(cookies)
            accounts = await client.get_game_accounts()
            
            acc_list = []
            for acc in accounts:
                short_name = GAME_NAMES.get(acc.game, acc.game.name.upper())
                nick = acc.nickname if acc.nickname else "Без имени"
                acc_list.append({"game": short_name, "uid": acc.uid, "level": acc.level, "nickname": nick})
            
            self.accounts_signal.emit(acc_id, acc_list)
        except Exception:
            self.accounts_signal.emit(acc_id, [])

    def run_daily(self, acc_id):
        asyncio.run(self.async_daily(acc_id))

    async def async_daily(self, acc_id):
        acc_data = config.ACCOUNTS.get(acc_id, {})
        cookies = acc_data.get("cookies", {})
        if not cookies:
            self.log_signal.emit(acc_id, "❌ Нет куки! Авторизуйтесь.")
            return

        self.log_signal.emit(acc_id, "📅 Начинаем сбор ежедневных отметок...")
        client = genshin.Client(cookies)
        try:
            accounts = await client.get_game_accounts()
            for acc in accounts:
                short_name = GAME_NAMES.get(acc.game, acc.game.name.upper())
                self.log_signal.emit(acc_id, f"<span style='color: #d4af37;'><b>🎮 {short_name} (UID: {acc.uid})</b></span>")
                try:
                    reward = await client.claim_daily_reward(game=acc.game)
                    self.log_signal.emit(acc_id, f"  ✅ Собрано: {reward.amount} x {reward.name}")
                except genshin.errors.AlreadyClaimed:
                    self.log_signal.emit(acc_id, "  ⏳ [Уже собрано]")
                except Exception as e:
                    self.log_signal.emit(acc_id, f"  ❌ Ошибка: {e}")
                await asyncio.sleep(2)
            self.log_signal.emit(acc_id, "✨ <b>Отметки завершены!</b>")
        except Exception as e:
            self.log_signal.emit(acc_id, f"<span style='color: #ff5555;'>🛑 Ошибка API: {e}</span>")

    def run_collect_promos(self, target_acc_id="ALL"):
        asyncio.run(self.async_collect_promos(target_acc_id))

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

    async def async_collect_promos(self, target_acc_id="ALL"):
        self.log_signal.emit(target_acc_id, "🌐 Сканируем интернет на новые коды...")
        
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
                self.log_signal.emit(target_acc_id, f"  📥 {short}: найдено {len(new_codes)} новых кодов! (Всего: {len(codes)})")
                new_total_added += len(new_codes)
            else:
                self.log_signal.emit(target_acc_id, f"  📥 {short}: новых кодов нет. Актуальных: {len(codes)} шт.")
        
        config.update_promos(config.PROMOS)
        if new_total_added > 0:
            self.log_signal.emit(target_acc_id, f"✨ <b>База обновлена! Новых кодов: {new_total_added}.</b>")
        else:
            self.log_signal.emit(target_acc_id, "✨ <b>База данных актуальна.</b>")

    def run_redeem_promos(self, acc_id):
        asyncio.run(self.async_redeem_promos(acc_id))

    async def async_redeem_promos(self, acc_id):
        acc_data = config.ACCOUNTS.get(acc_id, {})
        cookies = acc_data.get("cookies", {})
        if not cookies:
            self.log_signal.emit(acc_id, "❌ Нет куки! Авторизуйтесь.")
            return

        if not isinstance(config.PROMOS, dict) or "active_codes" not in config.PROMOS:
            self.log_signal.emit(acc_id, "⚠️ База кодов пуста! Сначала спарсите промокоды.")
            return

        self.log_signal.emit(acc_id, "🎁 Начинаем ввод промокодов из БД...")
        client = genshin.Client(cookies)

        try:
            accounts = await client.get_game_accounts()
            for acc in accounts:
                if acc.game not in PROMO_URLS:
                    continue
                
                short_name = GAME_NAMES.get(acc.game, acc.game.name.upper())
                nick = acc.nickname or "Без имени"
                self.log_signal.emit(acc_id, f"<br><span style='color: #d4af37;'><b>🎮 {short_name} (UID: {acc.uid} | {nick})</b></span>")
                
                active_codes = config.PROMOS["active_codes"].get(acc.game.name, [])
                uid_str = str(acc.uid)
                config.PROMOS.setdefault("history", {}).setdefault(uid_str, [])
                uid_history = config.PROMOS["history"][uid_str]
                
                to_check = [c for c in active_codes if c not in uid_history]
                if not to_check:
                    self.log_signal.emit(acc_id, "  🤷 Все актуальные коды уже проверены ранее.")
                    continue
                
                self.log_signal.emit(acc_id, f"  📦 Проверяем кодов: {len(to_check)} шт...")
                activated_count = 0
                
                for code in to_check:
                    add_to_history = False
                    try:
                        await client.redeem_code(code, uid=acc.uid, game=acc.game)
                        self.log_signal.emit(acc_id, f"  💎 <span style='color: #55ff55;'>Код {code} успешно активирован!</span>")
                        activated_count += 1
                        add_to_history = True
                        if config.SETTINGS.get("tray_notify", True):
                            self.notify_signal.emit("Промокод активирован!", f"{acc_data.get('name')}: {short_name} — {code}")
                        
                    except genshin.errors.InvalidCookies:
                        self.log_signal.emit(acc_id, "  <span style='color: #ffaa00;'>🔄 Куки устарели! Запускаю окно перелогина...</span>")
                        self.need_relogin_signal.emit(acc_id)
                        return
                        
                    except genshin.errors.RedemptionException as e:
                        msg = str(e.msg).lower()
                        if e.retcode == -100 or "login" in msg or "cookie" in msg:
                            self.log_signal.emit(acc_id, "  <span style='color: #ffaa00;'>🔄 Сессия истекла! Запускаю окно перелогина...</span>")
                            self.need_relogin_signal.emit(acc_id)
                            return
                        if "cooldown" in msg or e.retcode == -5003:
                            self.log_signal.emit(acc_id, f"  ⏳ Кулдаун сервера. Код {code} отложен.")
                        elif any(w in msg for w in ["already", "claimed", "expired", "invalid", "in use", "not exist"]):
                            add_to_history = True 
                        else:
                            self.log_signal.emit(acc_id, f"  ⚠️ Отказ ({code}): {e.msg}")
                            
                    except Exception as e:
                        self.log_signal.emit(acc_id, f"  ❌ Ошибка ({code}): {e}")
                        
                    if add_to_history:
                        uid_history.append(code)
                        config.update_promos(config.PROMOS)
                    
                    await asyncio.sleep(5.5)
                
                if activated_count == 0:
                    self.log_signal.emit(acc_id, "  ℹ️ Новых рабочих кодов не подошло.")
                    
            self.log_signal.emit(acc_id, "✨ <b>Проверка кодов завершена!</b>")
        except genshin.errors.InvalidCookies:
            self.log_signal.emit(acc_id, "<span style='color: #ffaa00;'>🔄 Требуется обновление куки. Открываю браузер...</span>")
            self.need_relogin_signal.emit(acc_id)
        except Exception as e:
            self.log_signal.emit(acc_id, f"<span style='color: #ff5555;'>🛑 Ошибка API: {e}</span>")

    def run_custom_code_all(self, game_key, raw_codes):
        asyncio.run(self.async_custom_code_all(game_key, raw_codes))

    async def async_custom_code_all(self, game_key, raw_codes):
        target_game = STRING_TO_GAME.get(game_key)
        if not target_game:
            return

        # Разбиваем строку на отдельные коды (если ввели несколько через пробел или запятую)
        codes = [c.strip() for c in raw_codes.replace(",", " ").split() if c.strip()]
        if not codes:
            return

        self.log_signal.emit("ALL", f"🎁 Ручной ввод ({game_key}): <b>{', '.join(codes)}</b>...")
        
        for acc_id, acc_data in config.ACCOUNTS.items():
            cookies = acc_data.get("cookies", {})
            if not cookies:
                continue
            try:
                client = genshin.Client(cookies)
                accounts = await client.get_game_accounts()
                target_accs = [a for a in accounts if a.game == target_game]
                
                if not target_accs:
                    self.log_signal.emit(acc_id, f"  ℹ️ Персонаж в {game_key} не найден, пропуск.")
                    continue

                for acc in target_accs:
                    uid_str = str(acc.uid)
                    config.PROMOS.setdefault("history", {}).setdefault(uid_str, [])
                    uid_history = config.PROMOS["history"][uid_str]

                    for code in codes:
                        try:
                            await client.redeem_code(code, uid=acc.uid, game=acc.game)
                            self.log_signal.emit(acc_id, f"  💎 <span style='color: #55ff55;'>Код {code} ({game_key}) активирован!</span>")
                            if code not in uid_history:
                                uid_history.append(code)
                                config.update_promos(config.PROMOS)
                        except Exception as e:
                            self.log_signal.emit(acc_id, f"  ⚠️ Код {code} ({game_key}): {e}")
                        await asyncio.sleep(5.5)
            except Exception as e:
                self.log_signal.emit(acc_id, f"❌ Ошибка при вводе ручного кода: {e}")
        self.log_signal.emit("ALL", "✨ <b>Ручной ввод кодов завершен!</b>")