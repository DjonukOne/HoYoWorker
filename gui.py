import sys
import os
import time
import threading
from PyQt6.QtWidgets import (QMainWindow, QPushButton, QVBoxLayout, QWidget, 
                             QLabel, QSystemTrayIcon, QMenu, QTimeEdit, QApplication, QTextEdit, QHBoxLayout, QGridLayout)
from PyQt6.QtGui import QIcon, QAction, QDesktopServices
from PyQt6.QtCore import Qt, QUrl, QTimer, pyqtSignal, QTime
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage

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
QLabel { color: #ececec; font-family: "Segoe UI", sans-serif; font-size: 13px; }
QPushButton {
    background-color: #2b2b2b; color: #d4af37; border: 1px solid #d4af37;
    padding: 8px; border-radius: 4px; font-weight: bold; font-size: 13px;
}
QPushButton:hover { background-color: #d4af37; color: #121212; }
QPushButton:pressed { background-color: #aa8c2c; }
QTextEdit {
    background-color: #1e1e1e; color: #cccccc; border: 1px solid #444444;
    border-radius: 4px; font-family: "Consolas", monospace; font-size: 12px;
}
QTimeEdit {
    background-color: #1e1e1e; color: #d4af37; border: 1px solid #d4af37;
    padding: 4px; border-radius: 4px; width: 60px;
}
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

    def on_cookie_added(self, cookie):
        name = cookie.name().data().decode('utf-8')
        value = cookie.value().data().decode('utf-8')
        target_cookies = ["ltuid_v2", "ltoken_v2", "account_id_v2", "cookie_token_v2", "account_mid_v2"]
        if name in target_cookies:
            config.update_cookies({name: value})
            if not self.auth_done:
                if all(k in config.COOKIES for k in ["ltuid_v2", "ltoken_v2", "cookie_token_v2", "account_id_v2"]):
                    self.auth_done = True
                    self.cookies_ready.emit() 

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HoYoWorker")
        self.resize(500, 560) 
        self.setWindowIcon(QIcon(ICON_PATH))
        self.setStyleSheet(HSR_STYLE)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        self.status_label = QLabel("Статус: 🔴 Не авторизован")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.status_label)

        self.accounts_label = QLabel("Нет привязанных аккаунтов.")
        self.accounts_label.setStyleSheet("color: #a0a0a0; margin-bottom: 5px;")
        layout.addWidget(self.accounts_label)

        self.btn_auth = QPushButton("Войти в HoYoLAB")
        self.btn_auth.clicked.connect(self.handle_auth_button)
        layout.addWidget(self.btn_auth)
        
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

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_schedule)
        self.timer.start(1000)
        
        self.daily_ran_at = None
        self.promo_ran_at = None

        self.refresh_auth_ui()

    def save_timers(self):
        config.update_settings({
            "time_daily": self.time_daily.time().toString("HH:mm"),
            "time_promo": self.time_promo.time().toString("HH:mm")
        })

    def refresh_auth_ui(self):
        if config.COOKIES:
            self.status_label.setText("Статус: 🟢 Авторизован")
            self.btn_auth.setText("Выйти из аккаунта")
            self.btn_auth.setStyleSheet("color: #ff5555; border-color: #ff5555;")
            self.accounts_label.setText("Загрузка персонажей...")
            threading.Thread(target=self.worker.fetch_accounts_info, daemon=True).start()
        else:
            self.status_label.setText("Статус: 🔴 Не авторизован")
            self.btn_auth.setText("Войти через HoYoLAB")
            self.btn_auth.setStyleSheet("") 
            self.accounts_label.setText("Войдите, чтобы увидеть список игр.")

    def update_accounts_ui(self, accounts):
        if not accounts:
            self.accounts_label.setText("Персонажи не найдены.")
            return
            
        html = "<table width='100%' cellpadding='1' cellspacing='0'>"
        for acc in accounts:
            html += f"<tr><td width='20%'>• {acc['game']}</td><td width='40%'>UID: {acc['uid']}</td><td><span style='color:#d4af37'>{acc['nickname']}</span> (Ур. {acc['level']})</td></tr>"
        html += "</table>"
        self.accounts_label.setText(html)

    def handle_auth_button(self):
        if config.COOKIES:
            config.clear_cookies()
            self.refresh_auth_ui()
            self.update_log("Выполнен выход из аккаунта.")
        else:
            self.login_window = LoginWindow()
            self.login_window.cookies_ready.connect(self.on_cookies_ready)
            self.login_window.show()

    def on_cookies_ready(self):
        self.update_log("<span style='color:#55ff55;'>✅ Авторизация успешна!</span>")
        self.login_window.close()
        self.refresh_auth_ui()

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