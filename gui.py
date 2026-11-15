import time
import threading
from PyQt6.QtWidgets import QMainWindow, QWidget, QSystemTrayIcon, QMenu, QApplication, QTabWidget
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QTimer

import config
from styles import ICON_PATH, DEFAULT_HSR_STYLE
from hoyo_api import HoYoWorker
from browser_auth import LoginWindow
from tab_account import AccountTab
from tab_settings import SettingsTab

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HoYoWorker")
        self.resize(680, 620)
        self.setMinimumWidth(650)
        self.setWindowIcon(QIcon(ICON_PATH))
        self.apply_theme()

        self.worker = HoYoWorker()
        self.worker.log_signal.connect(self.route_log)
        self.worker.accounts_signal.connect(self.route_accounts_ui)
        self.worker.need_relogin_signal.connect(self.on_need_relogin)
        self.worker.notify_signal.connect(self.show_notification)

        self.account_widgets = {}
        self.login_windows = {}
        self.marquee_step = 0

        self.tabs = QTabWidget()
        self.tabs.tabBarClicked.connect(self.on_tab_clicked)
        self.setCentralWidget(self.tabs)

        self.build_tabs()

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

        self.schedule_timer = QTimer(self)
        self.schedule_timer.timeout.connect(self.check_schedule)
        self.schedule_timer.start(1000)

        self.marquee_timer = QTimer(self)
        self.marquee_timer.timeout.connect(self.tick_marquee)
        self.marquee_timer.start(250)

        self.daily_ran_at = None
        self.promo_ran_at = None

    def apply_theme(self):
        css = config.SETTINGS.get("custom_css", DEFAULT_HSR_STYLE)
        self.setStyleSheet(css)

    def build_tabs(self):
        self.tabs.blockSignals(True)
        self.tabs.clear()
        self.account_widgets.clear()

        self.settings_tab = SettingsTab(self)
        self.tabs.addTab(self.settings_tab, "⚙ Настройки")

        for acc_id in config.ACCOUNTS.keys():
            w = AccountTab(acc_id, self)
            self.account_widgets[acc_id] = w
            self.tabs.addTab(w, "")

        self.plus_dummy = QWidget()
        self.tabs.addTab(self.plus_dummy, " + ")

        self.update_tab_titles()
        if len(config.ACCOUNTS) > 0:
            self.tabs.setCurrentIndex(1)
        self.tabs.blockSignals(False)

    def on_tab_clicked(self, index):
        if index == self.tabs.count() - 1:
            new_acc_id = config.create_account()
            w = AccountTab(new_acc_id, self)
            self.account_widgets[new_acc_id] = w
            self.tabs.insertTab(self.tabs.count() - 1, w, "")
            self.settings_tab.rebuild_accounts_grid()
            self.update_tab_titles()
            QTimer.singleShot(10, lambda: self.tabs.setCurrentIndex(self.tabs.count() - 2))

    def remove_account_tab(self, acc_id):
        if config.delete_account(acc_id):
            self.build_tabs()
            self.tabs.setCurrentIndex(0)

    def tick_marquee(self):
        self.marquee_step += 1
        self.update_tab_titles()

    def update_tab_titles(self):
        MAX_LEN = 12
        for i, acc_id in enumerate(config.ACCOUNTS.keys(), start=1):
            raw_name = config.ACCOUNTS[acc_id].get("name", acc_id)
            if len(raw_name) <= MAX_LEN:
                display_name = raw_name.ljust(MAX_LEN)
            else:
                padded = raw_name + "   •   "
                double_padded = padded + padded
                offset = self.marquee_step % len(padded)
                display_name = double_padded[offset : offset + MAX_LEN]
            self.tabs.setTabText(i, display_name)

    def open_login_window(self, acc_id, resume_promo_after=False):
        win = LoginWindow(acc_id, resume_promo_after=resume_promo_after)
        win.cookies_ready.connect(self.on_cookies_ready)
        self.login_windows[acc_id] = win
        win.show()
        win.activateWindow()

    def on_cookies_ready(self, acc_id, resume_promo_after):
        if acc_id in self.login_windows:
            self.login_windows[acc_id].close()
        if acc_id in self.account_widgets:
            self.account_widgets[acc_id].append_log("<span style='color:#55ff55;'>✅ Свежие куки успешно получены!</span>")
            self.account_widgets[acc_id].refresh_auth_ui()
        if resume_promo_after:
            threading.Thread(target=self.worker.run_redeem_promos, args=(acc_id,), daemon=True).start()

    def on_need_relogin(self, acc_id):
        self.open_login_window(acc_id, resume_promo_after=True)

    def route_log(self, target_acc_id, text):
        if target_acc_id == "ALL":
            for w in self.account_widgets.values():
                w.append_log(text)
        elif target_acc_id in self.account_widgets:
            self.account_widgets[target_acc_id].append_log(text)

    def route_accounts_ui(self, acc_id, accounts):
        if acc_id in self.account_widgets:
            self.account_widgets[acc_id].update_accounts_ui(accounts)

    def show_notification(self, title, msg):
        self.tray_icon.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 3500)

    def check_schedule(self):
        current_time = time.strftime("%H:%M")
        t_daily = config.SETTINGS.get("time_daily", "08:00")
        t_promo = config.SETTINGS.get("time_promo", "12:00")

        if current_time == t_daily and self.daily_ran_at != current_time:
            self.daily_ran_at = current_time
            for acc_id, data in config.ACCOUNTS.items():
                if data.get("auto_daily", True) and data.get("cookies"):
                    threading.Thread(target=self.worker.run_daily, args=(acc_id,), daemon=True).start()

        if current_time == t_promo and self.promo_ran_at != current_time:
            self.promo_ran_at = current_time
            threading.Thread(target=self.run_scheduled_promos_flow, daemon=True).start()

    def run_scheduled_promos_flow(self):
        self.worker.run_collect_promos("ALL")
        for acc_id, data in config.ACCOUNTS.items():
            if data.get("auto_promo", True) and data.get("cookies"):
                if config.SETTINGS.get("force_relogin_before_promo", True):
                    self.worker.need_relogin_signal.emit(acc_id)
                else:
                    self.worker.run_redeem_promos(acc_id)

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage("HoYoWorker", "Свернуто в трей.", QSystemTrayIcon.MessageIcon.Information, 2000)