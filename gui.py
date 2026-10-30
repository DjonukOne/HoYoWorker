import asyncio
import os
import sys
import threading
import time

from PyQt6.QtWidgets import (QMainWindow, QPushButton, QVBoxLayout, QWidget,
                             QLabel, QSystemTrayIcon, QMenu, QTimeEdit, QApplication, QTextEdit, QHBoxLayout,
                             QGridLayout, QDialog, QLineEdit, QCheckBox, QFormLayout, QDialogButtonBox, QMessageBox)
from PyQt6.QtGui import QIcon, QAction, QDesktopServices
from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal, QTime

# Встроенный браузер (QtWebEngine). Если PyQt6 и PyQt6-WebEngine собраны
# с разными версиями Qt, импорт падает с "DLL load failed".
# Это не должно ронять всё приложение: остальные функции (в том числе вход
# по логину и паролю) работают и без встроенного браузера.
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
    WEBENGINE_ERROR = None
except Exception as _webengine_error:  # noqa: BLE001
    QWebEngineView = QWebEngineProfile = QWebEnginePage = object  # type: ignore[misc,assignment]
    WEBENGINE_ERROR = _webengine_error

import auth_manager
import config
from hoyo_api import HoYoWorker


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


ICON_PATH = resource_path("icon.png")

HSR_STYLE = """
QMainWindow { background-color: #121212; }
QDialog { background-color: #121212; }
QLabel { color: #ececec; font-family: "Segoe UI", sans-serif; font-size: 13px; }
QPushButton {
    background-color: #2b2b2b; color: #d4af37; border: 1px solid #d4af37;
    padding: 8px; border-radius: 4px; font-weight: bold; font-size: 13px;
}
QPushButton:hover { background-color: #d4af37; color: #121212; }
QPushButton:pressed { background-color: #aa8c2c; }
QPushButton:disabled { color: #6b6b6b; border-color: #444444; }
QTextEdit {
    background-color: #1e1e1e; color: #cccccc; border: 1px solid #444444;
    border-radius: 4px; font-family: "Consolas", monospace; font-size: 12px;
}
QTimeEdit {
    background-color: #1e1e1e; color: #d4af37; border: 1px solid #d4af37;
    padding: 4px; border-radius: 4px; width: 60px;
}
QLineEdit {
    background-color: #1e1e1e; color: #ececec; border: 1px solid #d4af37;
    padding: 6px; border-radius: 4px;
}
QCheckBox { color: #ececec; font-size: 12px; }
"""


class CustomWebPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if url.scheme() in ['http', 'https', 'data', 'qrc', 'file']:
            return super().acceptNavigationRequest(url, _type, isMainFrame)
        QDesktopServices.openUrl(url)
        return False 


class PopupWindow(QMainWindow):
    def __init__(self, profile):
        super().__init__()
        self.setWindowTitle("Авторизация OAuth")
        self.resize(500, 600)
        self.browser = QWebEngineView()
        self.browser.setPage(CustomWebPage(profile, self.browser))
        self.setCentralWidget(self.browser)


class CustomBrowser(QWebEngineView):
    def __init__(self, profile):
        super().__init__()
        self.setPage(CustomWebPage(profile, self))

    def createWindow(self, _type):
        self.popup = PopupWindow(self.page().profile())
        self.popup.show()
        return self.popup.browser


class LoginWindow(QMainWindow):
    cookies_ready = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Авторизация HoYoLAB")
        self.resize(800, 600)
        
        self.profile = QWebEngineProfile.defaultProfile()
        self.browser = CustomBrowser(self.profile)
        self.setCentralWidget(self.browser)
        
        self.cookie_store = self.profile.cookieStore()
        self.cookie_store.cookieAdded.connect(self.on_cookie_added)
        self.cookie_store.deleteAllCookies()
        self.browser.setUrl(QUrl("https://www.hoyolab.com"))
        self.auth_done = False
        self.captured_cookies = {}

    def on_cookie_added(self, cookie):
        name = cookie.name().data().decode('utf-8')
        value = cookie.value().data().decode('utf-8')

        relevant = set(auth_manager.SESSION_COOKIE_KEYS) | set(auth_manager.ROOT_COOKIE_KEYS)
        if name not in relevant:
            return

        self.captured_cookies[name] = value

        required = ["ltuid_v2", "ltoken_v2", "cookie_token_v2", "account_id_v2"]
        if all(k in self.captured_cookies for k in required):
            # Сохраняем всё, что успели поймать (включая stoken, если HoYoLAB его выдал):
            # именно из этих данных приложение будет получать новые токены.
            # Сохраняем при каждом новом cookie, чтобы не потерять пришедшие позже.
            auth_manager.save_login_cookies(self.captured_cookies)
            if not self.auth_done:
                self.auth_done = True
                self.cookies_ready.emit()


class PasswordLoginDialog(QDialog):
    """Диалог входа по логину и паролю для авто-продления сессии."""

    def __init__(self, parent=None, account: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Авто-вход в HoYoLAB")
        self.setStyleSheet(HSR_STYLE)
        self.setMinimumWidth(420)

        layout = QVBoxLayout()
        layout.setSpacing(10)

        info = QLabel(
            "Приложение запросит новый токен при каждом запуске.\n"
            "Если HoYoLAB отзовёт сессию, вход по паролю восстановит её автоматически.\n\n"
            "Логин, пароль и токены хранятся только на этом компьютере в зашифрованном "
            "виде (Fernet + защита ключа Windows DPAPI)."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #a0a0a0; font-size: 12px;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(8)

        self.account_edit = QLineEdit(account)
        self.account_edit.setPlaceholderText("email или телефон")
        form.addRow(QLabel("Логин:"), self.account_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("пароль от аккаунта HoYoverse")
        form.addRow(QLabel("Пароль:"), self.password_edit)

        layout.addLayout(form)

        self.remember_box = QCheckBox("Сохранять пароль для автоматического входа")
        self.remember_box.setChecked(True)
        layout.addWidget(self.remember_box)

        buttons = QDialogButtonBox()
        self.login_button = buttons.addButton("Войти", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)
        self.password_edit.returnPressed.connect(self.accept)

    def values(self):
        return (
            self.account_edit.text().strip(),
            self.password_edit.text(),
            self.remember_box.isChecked(),
        )


class MainWindow(QMainWindow):
    login_state = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HoYoWorker")
        self.resize(500, 620) 
        self.setWindowIcon(QIcon(ICON_PATH))
        self.setStyleSheet(HSR_STYLE)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        self.status_label = QLabel("Статус: 🔴 Не авторизован")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.status_label)

        self.auth_hint = QLabel("")
        self.auth_hint.setStyleSheet("color: #a0a0a0; font-size: 11px;")
        self.auth_hint.setWordWrap(True)
        layout.addWidget(self.auth_hint)

        self.accounts_label = QLabel("Нет привязанных аккаунтов.")
        self.accounts_label.setStyleSheet("color: #a0a0a0; margin-bottom: 5px;")
        layout.addWidget(self.accounts_label)

        auth_layout = QHBoxLayout()
        self.btn_auth = QPushButton("Войти в HoYoLAB")
        self.btn_auth.clicked.connect(self.handle_auth_button)
        auth_layout.addWidget(self.btn_auth, 2)

        self.btn_password = QPushButton("Авто-вход по паролю")
        self.btn_password.setToolTip(
            "Сохраняет логин и пароль в зашифрованном виде, чтобы приложение\n"
            "само восстанавливало сессию, когда токен истечёт."
        )
        self.btn_password.clicked.connect(self.open_password_login)
        auth_layout.addWidget(self.btn_password, 1)
        layout.addLayout(auth_layout)

        btns_layout = QGridLayout()
        self.btn_daily = QPushButton("Собрать отметки")
        self.btn_daily.setMinimumHeight(66) 
        self.btn_daily.clicked.connect(self.run_manual_daily)
        btns_layout.addWidget(self.btn_daily, 0, 0, 2, 1) 
        
        self.btn_collect_promo = QPushButton("Спарсить промокоды")
        self.btn_collect_promo.clicked.connect(self.run_collect_promo)
        btns_layout.addWidget(self.btn_collect_promo, 0, 1)
        
        self.btn_redeem_promo = QPushButton("Ввести промокоды")
        self.btn_redeem_promo.clicked.connect(self.run_redeem_promo)
        btns_layout.addWidget(self.btn_redeem_promo, 1, 1)
        
        layout.addLayout(btns_layout)

        timers_layout = QGridLayout()
        timers_layout.addWidget(QLabel("Ежедневные отметки в:"), 0, 0)
        self.time_daily = QTimeEdit()
        self.time_daily.setDisplayFormat("HH:mm")
        
        t_daily = config.SETTINGS.get("time_daily", "08:00")
        self.time_daily.setTime(QTime.fromString(t_daily, "HH:mm")) 
        self.time_daily.timeChanged.connect(self.save_timers) 
        timers_layout.addWidget(self.time_daily, 0, 1)

        timers_layout.addWidget(QLabel("Проверка промокодов в:"), 0, 2)
        self.time_promo = QTimeEdit()
        self.time_promo.setDisplayFormat("HH:mm")
        
        t_promo = config.SETTINGS.get("time_promo", "12:00")
        self.time_promo.setTime(QTime.fromString(t_promo, "HH:mm")) 
        self.time_promo.timeChanged.connect(self.save_timers) 
        timers_layout.addWidget(self.time_promo, 0, 3)
        
        layout.addLayout(timers_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setHtml("<b>Готов к работе.</b>")
        layout.addWidget(self.log_text)

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(ICON_PATH))
        tray_menu = QMenu()
        tray_menu.setStyleSheet("background-color: #2b2b2b; color: #ececec;")
        show_action = QAction("Развернуть", self)
        show_action.triggered.connect(self.show)
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        self.worker = HoYoWorker()
        self.worker.log_signal.connect(self.update_log)
        self.worker.accounts_signal.connect(self.update_accounts_ui)
        self.worker.auth_signal.connect(self.on_auth_result)
        self.login_state.connect(self.on_login_state)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_schedule)
        self.timer.start(1000)
        
        self.daily_ran_at = None
        self.promo_ran_at = None

        if WEBENGINE_ERROR is not None:
            self.update_log(
                "<span style='color:#ffcc66;'>⚠️ Встроенный браузер не загрузился "
                f"({WEBENGINE_ERROR}).</span> Используйте «Авто-вход по паролю» "
                "или переустановите зависимости: pip install -r requirements.txt"
            )

        self.refresh_auth_ui()
        self.start_session_refresh()

    # ------------------------------------------------------------------ #
    # Авторизация
    # ------------------------------------------------------------------ #

    def save_timers(self):
        config.update_settings({
            "time_daily": self.time_daily.time().toString("HH:mm"),
            "time_promo": self.time_promo.time().toString("HH:mm")
        })

    def start_session_refresh(self):
        """При каждом запуске просим у HoYoLAB новый токен."""
        if config.COOKIES or auth_manager.has_stoken() or auth_manager.has_password():
            threading.Thread(target=self.worker.run_startup, daemon=True).start()

    def refresh_auth_ui(self):
        self.btn_password.setEnabled(True)

        if config.COOKIES:
            self.status_label.setText("Статус: 🟢 Авторизован")
            self.btn_auth.setText("Выйти из аккаунта")
            self.btn_auth.setEnabled(True)
            self.btn_auth.setStyleSheet("color: #ff5555; border-color: #ff5555;")
            self.accounts_label.setText("Обновляем токен...")
            self.btn_password.setText("Сменить пароль для авто-входа" if auth_manager.has_password() else "Авто-вход по паролю")
            self.update_auth_hint()
        else:
            self.status_label.setText("Статус: 🔴 Не авторизован")
            self.btn_auth.setStyleSheet("")
            self.accounts_label.setText("Войдите, чтобы увидеть список игр.")

            if WEBENGINE_ERROR is not None:
                self.btn_auth.setText("Встроенный браузер недоступен")
                self.btn_auth.setEnabled(False)
                self.auth_hint.setText(
                    "⚠️ QtWebEngine не загрузился (обычно это конфликт версий PyQt6 "
                    "и PyQt6-WebEngine). Войдите кнопкой «Авто-вход по паролю» — "
                    "она работает без браузера."
                )
            else:
                self.btn_auth.setText("Войти через HoYoLAB")
                self.btn_auth.setEnabled(True)
                self.auth_hint.setText(
                    "Вход через браузер сохранит токены. Чтобы приложение само продлевало "
                    "сессию, включите «Авто-вход по паролю»."
                )

    def update_auth_hint(self):
        if not config.COOKIES:
            self.auth_hint.setText("")
            return

        if config.CREDENTIALS.get("refresh_ok") is False:
            self.auth_hint.setText(
                "⚠️ Последняя попытка обновить токен не удалась. Если задачи начнут падать "
                "с ошибкой авторизации — войдите в аккаунт заново."
            )
        elif auth_manager.has_password():
            self.auth_hint.setText(
                "🔑 Включён авто-вход по паролю: токен запрашивается при каждом запуске, "
                "а при отзыве сессии вход выполняется автоматически."
            )
        elif auth_manager.has_stoken():
            self.auth_hint.setText("🔑 Токен обновляется по stoken при каждом запуске.")
        else:
            self.auth_hint.setText(
                "⚠️ Для полного авто-продления задайте пароль в «Авто-вход по паролю». "
                "Без него токен можно только продлевать, пока он действителен."
            )

    def on_auth_result(self, ok):
        self.btn_password.setEnabled(True)

        if not config.COOKIES:
            self.refresh_auth_ui()
            return

        last = auth_manager.last_refresh_time()
        updated = ""
        if last:
            updated = f" · токен обновлён в {time.strftime('%H:%M:%S', time.localtime(last))}"

        if ok:
            self.status_label.setText(f"Статус: 🟢 Авторизован ({auth_manager.mode_label()}){updated}")
        else:
            self.status_label.setText("Статус: 🟠 Требуется повторный вход")

        self.update_auth_hint()

    def on_login_state(self, ok):
        self.btn_password.setEnabled(True)
        if not ok:
            self.update_auth_hint()

    def update_accounts_ui(self, accounts):
        if not accounts:
            if config.COOKIES:
                self.accounts_label.setText("Персонажи не найдены.")
            return
            
        html = "<table width='100%' cellpadding='1' cellspacing='0'>"
        for acc in accounts:
            html += f"<tr><td width='20%'>• {acc['game']}</td><td width='40%'>UID: {acc['uid']}</td><td><span style='color:#d4af37'>{acc['nickname']}</span> (Ур. {acc['level']})</td></tr>"
        html += "</table>"
        self.accounts_label.setText(html)

    def handle_auth_button(self):
        if config.COOKIES:
            answer = QMessageBox.question(
                self,
                "Выход из аккаунта",
                "Удалить сохранённые токены, stoken и пароль для авто-входа?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

            config.clear_session()
            self.refresh_auth_ui()
            self.update_log("Выполнен выход из аккаунта, сохранённые данные удалены.")
        elif WEBENGINE_ERROR is not None:
            self.show_webengine_error()
        else:
            self.login_window = LoginWindow()
            self.login_window.cookies_ready.connect(self.on_cookies_ready)
            self.login_window.show()

    def show_webengine_error(self):
        QMessageBox.critical(
            self,
            "Встроенный браузер недоступен",
            "Не удалось загрузить QtWebEngine, поэтому окно входа в HoYoLAB не откроется.\n\n"
            "Обычно причина в том, что PyQt6 и PyQt6-WebEngine собраны с разными версиями "
            "Qt (библиотека QtWebEngine отстаёт от PyQt6).\n\n"
            "Как исправить (в окружении, из которого собирается программа):\n"
            "    pip uninstall -y PyQt6 PyQt6-Qt6 PyQt6-WebEngine PyQt6-WebEngine-Qt6\n"
            "    pip install -r requirements.txt\n"
            "затем пересоберите exe.\n\n"
            "Вход по логину и паролю (кнопка «Авто-вход по паролю») работает и без браузера.\n\n"
            f"Техническая информация: {WEBENGINE_ERROR}"
        )

    def on_cookies_ready(self):
        self.update_log("<span style='color:#55ff55;'>✅ Авторизация успешна!</span>")
        # Даём окну пару секунд, чтобы поймать cookies, которые HoYoLAB
        # выставляет чуть позже (например, stoken), и только затем закрываем.
        QTimer.singleShot(2500, self.finish_browser_login)

    def finish_browser_login(self):
        try:
            self.login_window.close()
        except Exception:
            pass
        self.refresh_auth_ui()
        self.start_session_refresh()

    def open_password_login(self):
        dialog = PasswordLoginDialog(self, account=str(config.CREDENTIALS.get("account", "")))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        account, password, remember = dialog.values()
        if not account or not password:
            QMessageBox.warning(self, "Авто-вход", "Введите логин и пароль.")
            return

        self.btn_password.setEnabled(False)
        self.update_log("🔐 Выполняем вход по логину и паролю...")
        threading.Thread(
            target=self.password_login_thread,
            args=(account, password, remember),
            daemon=True,
        ).start()

    def password_login_thread(self, account, password, remember):
        try:
            asyncio.run(auth_manager.login_with_password(
                account, password, remember=remember, log=self.worker.log_signal.emit
            ))
        except auth_manager.AuthError as error:
            self.worker.log_signal.emit(f"<span style='color:#ff5555;'>❌ {error}</span>")
            self.login_state.emit(False)
            return
        except Exception as error:
            self.worker.log_signal.emit(f"<span style='color:#ff5555;'>❌ Ошибка входа: {error}</span>")
            self.login_state.emit(False)
            return

        self.login_state.emit(True)
        self.worker.run_startup()

    # ------------------------------------------------------------------ #
    # Задачи
    # ------------------------------------------------------------------ #

    def run_manual_daily(self):
        if not config.COOKIES:
            self.update_log("Сначала авторизуйтесь!")
            return
        threading.Thread(target=self.worker.run_daily, daemon=True).start()

    def run_collect_promo(self):
        threading.Thread(target=self.worker.run_collect_promos, daemon=True).start()
        
    def run_redeem_promo(self):
        if not config.COOKIES:
            self.update_log("Сначала авторизуйтесь!")
            return
        threading.Thread(target=self.worker.run_redeem_promos, daemon=True).start()
        
    def run_auto_promo(self):
        threading.Thread(target=self.worker.run_auto_promos, daemon=True).start()

    def update_log(self, text):
        current_time = time.strftime("%H:%M:%S")
        self.log_text.append(f"<span style='color: #777777;'>[{current_time}]</span> {text}")

    def check_schedule(self):
        current_time = time.strftime("%H:%M")
        t_daily = self.time_daily.time().toString("HH:mm")
        t_promo = self.time_promo.time().toString("HH:mm")
        
        if current_time == t_daily and self.daily_ran_at != current_time:
            self.daily_ran_at = current_time 
            self.run_manual_daily()
            
        if current_time == t_promo and self.promo_ran_at != current_time:
            self.promo_ran_at = current_time 
            self.run_auto_promo() 

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage("HoYoWorker", "Свернуто в трей.", QSystemTrayIcon.MessageIcon.Information, 2000)
