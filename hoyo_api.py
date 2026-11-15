import asyncio
import genshin
from PyQt6.QtCore import QObject, pyqtSignal
import config
from promo_parser import collect_all_promos

def extract_game_key(acc):
    """Извлекает строковый ключ игры из объекта аккаунта HoYoLAB (даже для новых/бета игр)."""
    if hasattr(acc.game, "name"):
        return acc.game.name.upper()
    if getattr(acc, "game_biz", None):
        return str(acc.game_biz).upper()
    return str(acc.game).upper()

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
                raw_key = extract_game_key(acc)
                # Если игры еще нет в настройках, get_game_short_name вернет сам raw_key!
                short_name = config.get_game_short_name(raw_key)
                nick = acc.nickname if acc.nickname else "Без имени"
                acc_list.append({
                    "game": short_name,
                    "raw_key": raw_key,
                    "uid": acc.uid,
                    "level": acc.level,
                    "nickname": nick
                })
            
            self.accounts_signal.emit(acc_id, acc_list)
        except Exception:
            self.accounts_signal.emit(acc_id, [])

    def run_daily(self, acc_id):
        asyncio.run(self.async_daily(acc_id))

    async def async_daily(self, acc_id):
        cookies = config.ACCOUNTS.get(acc_id, {}).get("cookies", {})
        if not cookies:
            self.log_signal.emit(acc_id, "❌ Нет куки! Авторизуйтесь.")
            return

        self.log_signal.emit(acc_id, "📅 Начинаем сбор ежедневных отметок...")
        client = genshin.Client(cookies)
        try:
            accounts = await client.get_game_accounts()
            for acc in accounts:
                raw_key = extract_game_key(acc)
                short_name = config.get_game_short_name(raw_key)
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
        asyncio.run(collect_all_promos(self.log_signal, target_acc_id))

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
                raw_key = extract_game_key(acc)
                if raw_key not in config.GAMES:
                    continue
                
                short_name = config.get_game_short_name(raw_key)
                nick = acc.nickname or "Без имени"
                self.log_signal.emit(acc_id, f"<br><span style='color: #d4af37;'><b>🎮 {short_name} (UID: {acc.uid} | {nick})</b></span>")
                
                active_codes = config.PROMOS["active_codes"].get(raw_key, [])
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
        codes = [c.strip() for c in raw_codes.replace(",", " ").split() if c.strip()]
        if not codes:
            return

        short_title = config.get_game_short_name(game_key)
        self.log_signal.emit("ALL", f"🎁 Ручной ввод ({short_title}): <b>{', '.join(codes)}</b>...")
        
        for acc_id, acc_data in config.ACCOUNTS.items():
            cookies = acc_data.get("cookies", {})
            if not cookies:
                continue
            try:
                client = genshin.Client(cookies)
                accounts = await client.get_game_accounts()
                target_accs = [a for a in accounts if extract_game_key(a) == game_key]
                
                if not target_accs:
                    self.log_signal.emit(acc_id, f"  ℹ️ Персонаж в {short_title} не найден, пропуск.")
                    continue

                for acc in target_accs:
                    uid_str = str(acc.uid)
                    config.PROMOS.setdefault("history", {}).setdefault(uid_str, [])
                    uid_history = config.PROMOS["history"][uid_str]

                    for code in codes:
                        try:
                            await client.redeem_code(code, uid=acc.uid, game=acc.game)
                            self.log_signal.emit(acc_id, f"  💎 <span style='color: #55ff55;'>Код {code} ({short_title}) активирован!</span>")
                            if code not in uid_history:
                                uid_history.append(code)
                                config.update_promos(config.PROMOS)
                        except Exception as e:
                            self.log_signal.emit(acc_id, f"  ⚠️ Код {code} ({short_title}): {e}")
                        await asyncio.sleep(5.5)
            except Exception as e:
                self.log_signal.emit(acc_id, f"❌ Ошибка при вводе ручного кода: {e}")
        self.log_signal.emit("ALL", "✨ <b>Ручной ввод кодов завершен!</b>")