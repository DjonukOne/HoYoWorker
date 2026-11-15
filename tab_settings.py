import sys
import os
import threading
import winreg
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, 
                             QPushButton, QTimeEdit, QLineEdit, QCheckBox, QFileDialog, 
                             QScrollArea, QComboBox)
from PyQt6.QtCore import Qt, QTime

import config
from styles import DEFAULT_HSR_STYLE
from settings_games_ui import GamesManagerWidget

class SettingsTab(QWidget):
    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setSpacing(14)

        # 1. Блок расписания
        timers_layout = QHBoxLayout()
        timers_layout.addWidget(QLabel("⏰ Ежедневные отметки в:"))
        self.time_daily = QTimeEdit()
        self.time_daily.setDisplayFormat("HH:mm")
        self.time_daily.setTime(QTime.fromString(config.SETTINGS.get("time_daily", "08:00"), "HH:mm"))
        self.time_daily.timeChanged.connect(self.save_general_settings)
        timers_layout.addWidget(self.time_daily)

        timers_layout.addSpacing(20)

        timers_layout.addWidget(QLabel("🎟️ Проверка промокодов в:"))
        self.time_promo = QTimeEdit()
        self.time_promo.setDisplayFormat("HH:mm")
        self.time_promo.setTime(QTime.fromString(config.SETTINGS.get("time_promo", "12:00"), "HH:mm"))
        self.time_promo.timeChanged.connect(self.save_general_settings)
        timers_layout.addWidget(self.time_promo)
        timers_layout.addStretch()
        self.layout.addLayout(timers_layout)

        # 2. Таблица аккаунтов
        self.layout.addWidget(QLabel("<b>👥 Управление аккаунтами и авто-перелогином:</b>"))
        self.acc_grid = QGridLayout()
        self.acc_grid.setSpacing(8)
        self.acc_grid.setColumnStretch(0, 2)
        self.acc_grid.setColumnStretch(1, 3)
        self.acc_grid.setColumnStretch(2, 2)
        self.layout.addLayout(self.acc_grid)

        # 3. Модульный менеджер игр
        self.games_widget = GamesManagerWidget(self.main_win)
        self.games_widget.games_changed.connect(self.refresh_games_combo)
        self.layout.addWidget(self.games_widget)

        # 4. Дополнительные опции
        self.layout.addWidget(QLabel("<b>⚙️ Поведение и система:</b>"))
        
        self.chk_relogin = QCheckBox("🔄 Всегда открывать авто-перелогин перед вводом промокодов")
        self.chk_relogin.setChecked(config.SETTINGS.get("force_relogin_before_promo", True))
        self.chk_relogin.toggled.connect(self.save_general_settings)
        self.layout.addWidget(self.chk_relogin)

        self.chk_notify = QCheckBox("🔔 Уведомления Windows при активации промокода")
        self.chk_notify.setChecked(config.SETTINGS.get("tray_notify", True))
        self.chk_notify.toggled.connect(self.save_general_settings)
        self.layout.addWidget(self.chk_notify)

        self.chk_autorun = QCheckBox("🚀 Запускать HoYoWorker вместе с Windows")
        self.chk_autorun.setChecked(self.check_autorun())
        self.chk_autorun.toggled.connect(self.toggle_autorun)
        self.layout.addWidget(self.chk_autorun)

        # 5. Ручной ввод промокодов со стрима
        self.layout.addWidget(QLabel("<b>🎁 Быстрый ввод промокодов со стрима (на все аккаунты сразу):</b>"))
        manual_layout = QHBoxLayout()
        
        self.combo_manual_game = QComboBox()
        self.refresh_games_combo()
        manual_layout.addWidget(self.combo_manual_game)

        self.input_manual_code = QLineEdit()
        self.input_manual_code.setPlaceholderText("Код или несколько через пробел...")
        manual_layout.addWidget(self.input_manual_code, stretch=1)

        btn_manual_code = QPushButton("Активировать везде")
        btn_manual_code.clicked.connect(self.run_manual_code)
        manual_layout.addWidget(btn_manual_code)
        self.layout.addLayout(manual_layout)

        # 6. Кастомизация CSS
        self.layout.addWidget(QLabel("<b>🎨 Оформление (CSS темы):</b>"))
        css_layout = QHBoxLayout()
        btn_export_css = QPushButton("📤 Экспорт CSS")
        btn_export_css.clicked.connect(self.export_css)
        btn_import_css = QPushButton("📥 Импорт CSS")
        btn_import_css.clicked.connect(self.import_css)
        btn_reset_css = QPushButton("🔄 Сброс темы")
        btn_reset_css.clicked.connect(self.reset_css)
        css_layout.addWidget(btn_export_css)
        css_layout.addWidget(btn_import_css)
        css_layout.addWidget(btn_reset_css)
        self.layout.addLayout(css_layout)

        self.layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        self.rebuild_accounts_grid()

    def refresh_games_combo(self):
        current_data = self.combo_manual_game.currentData()
        self.combo_manual_game.clear()
        for g_key, g_data in config.GAMES.items():
            short = g_data.get("short_name", g_key)
            self.combo_manual_game.addItem(f"{short} ({g_key})", g_key)
        if current_data:
            idx = self.combo_manual_game.findData(current_data)
            if idx >= 0:
                self.combo_manual_game.setCurrentIndex(idx)

    def rebuild_accounts_grid(self):
        while self.acc_grid.count():
            item = self.acc_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        headers = ["Название вкладки", "Логин (Автоввод)", "Пароль", "⏰", "🎟️", ""]
        for col, text in enumerate(headers):
            lbl = QLabel(f"<b>{text}</b>")
            if col in [3, 4]:
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setFixedWidth(26)
            self.acc_grid.addWidget(lbl, 0, col)

        for row, (acc_id, data) in enumerate(config.ACCOUNTS.items(), start=1):
            name_edit = QLineEdit(data.get("name", ""))
            name_edit.textChanged.connect(lambda val, aid=acc_id: self.update_acc_field(aid, "name", val))
            self.acc_grid.addWidget(name_edit, row, 0)

            login_edit = QLineEdit(data.get("login", ""))
            login_edit.textChanged.connect(lambda val, aid=acc_id: self.update_acc_field(aid, "login", val))
            self.acc_grid.addWidget(login_edit, row, 1)

            pass_edit = QLineEdit(data.get("password", ""))
            pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
            pass_edit.textChanged.connect(lambda val, aid=acc_id: self.update_acc_field(aid, "password", val))
            self.acc_grid.addWidget(pass_edit, row, 2)

            chk_daily = QCheckBox()
            chk_daily.setChecked(data.get("auto_daily", True))
            chk_daily.toggled.connect(lambda val, aid=acc_id: self.update_acc_field(aid, "auto_daily", val))
            self.acc_grid.addWidget(chk_daily, row, 3, alignment=Qt.AlignmentFlag.AlignCenter)

            chk_promo = QCheckBox()
            chk_promo.setChecked(data.get("auto_promo", True))
            chk_promo.toggled.connect(lambda val, aid=acc_id: self.update_acc_field(aid, "auto_promo", val))
            self.acc_grid.addWidget(chk_promo, row, 4, alignment=Qt.AlignmentFlag.AlignCenter)

            btn_del = QPushButton("✕")
            btn_del.setFixedWidth(30)
            btn_del.setStyleSheet("color: #ff5555; border-color: #ff5555; padding: 2px;")
            btn_del.clicked.connect(lambda _, aid=acc_id: self.main_win.remove_account_tab(aid))
            if len(config.ACCOUNTS) <= 1:
                btn_del.setEnabled(False)
            self.acc_grid.addWidget(btn_del, row, 5)

    def update_acc_field(self, acc_id, field, value):
        if acc_id in config.ACCOUNTS:
            config.ACCOUNTS[acc_id][field] = value
            config.save_accounts()
            if field == "name":
                self.main_win.update_tab_titles()

    def save_general_settings(self):
        config.update_settings({
            "time_daily": self.time_daily.time().toString("HH:mm"),
            "time_promo": self.time_promo.time().toString("HH:mm"),
            "force_relogin_before_promo": self.chk_relogin.isChecked(),
            "tray_notify": self.chk_notify.isChecked()
        })

    def run_manual_code(self):
        raw_codes = self.input_manual_code.text().strip()
        if not raw_codes:
            return
        game_key = self.combo_manual_game.currentData()
        self.input_manual_code.clear()
        threading.Thread(
            target=self.main_win.worker.run_custom_code_all, 
            args=(game_key, raw_codes), 
            daemon=True
        ).start()

    def export_css(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт темы CSS", "hoyo_theme.css", "CSS Files (*.css)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(config.SETTINGS.get("custom_css", DEFAULT_HSR_STYLE))

    def import_css(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт темы CSS", "", "CSS Files (*.css)")
        if path:
            with open(path, "r", encoding="utf-8") as f:
                config.update_settings({"custom_css": f.read()})
            self.main_win.apply_theme()

    def reset_css(self):
        config.update_settings({"custom_css": DEFAULT_HSR_STYLE})
        self.main_win.apply_theme()

    def check_autorun(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, "HoYoWorker")
            winreg.CloseKey(key)
            return True
        except Exception:
            return False

    def toggle_autorun(self, enabled):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            if enabled:
                exe_path = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"' if not getattr(sys, 'frozen', False) else f'"{sys.executable}"'
                winreg.SetValueEx(key, "HoYoWorker", 0, winreg.REG_SZ, exe_path)
            else:
                winreg.DeleteValue(key, "HoYoWorker")
            winreg.CloseKey(key)
        except Exception:
            pass