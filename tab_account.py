import time
import threading
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QGridLayout, QTextEdit
import config

class AccountTab(QWidget):
    def __init__(self, acc_id, main_win):
        super().__init__()
        self.acc_id = acc_id
        self.main_win = main_win

        layout = QVBoxLayout(self)
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

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setHtml("<b>Готов к работе.</b>")
        layout.addWidget(self.log_text)

        self.refresh_auth_ui()

    def refresh_auth_ui(self):
        cookies = config.ACCOUNTS.get(self.acc_id, {}).get("cookies", {})
        if cookies:
            self.status_label.setText("Статус: 🟢 Авторизован")
            self.btn_auth.setText("Выйти из аккаунта")
            self.btn_auth.setStyleSheet("color: #ff5555; border-color: #ff5555;")
            self.accounts_label.setText("Загрузка персонажей...")
            threading.Thread(target=self.main_win.worker.fetch_accounts_info, args=(self.acc_id,), daemon=True).start()
        else:
            self.status_label.setText("Статус: 🔴 Не авторизован")
            self.btn_auth.setText("Войти через HoYoLAB")
            self.btn_auth.setStyleSheet("")
            self.accounts_label.setText("Войдите, чтобы увидеть список игр.")

    def update_accounts_ui(self, accounts):
        if not accounts:
            self.accounts_label.setText("Персонажи не найдены (или куки устарели).")
            return
        html = "<table width='100%' cellpadding='1' cellspacing='0'>"
        for acc in accounts:
            html += f"<tr><td width='22%'>• {acc['game']}</td><td width='38%'>UID: {acc['uid']}</td><td><span style='color:#d4af37'>{acc['nickname']}</span> (Ур. {acc['level']})</td></tr>"
        html += "</table>"
        self.accounts_label.setText(html)

    def handle_auth_button(self):
        cookies = config.ACCOUNTS.get(self.acc_id, {}).get("cookies", {})
        if cookies:
            config.clear_account_cookies(self.acc_id)
            self.refresh_auth_ui()
            self.append_log("Выполнен выход из аккаунта.")
        else:
            self.main_win.open_login_window(self.acc_id, resume_promo_after=False)

    def run_manual_daily(self):
        if not config.ACCOUNTS.get(self.acc_id, {}).get("cookies"):
            self.append_log("❌ Сначала авторизуйтесь!")
            return
        threading.Thread(target=self.main_win.worker.run_daily, args=(self.acc_id,), daemon=True).start()

    def run_collect_promo(self):
        threading.Thread(target=self.main_win.worker.run_collect_promos, args=(self.acc_id,), daemon=True).start()

    def run_redeem_promo(self):
        if not config.ACCOUNTS.get(self.acc_id, {}).get("cookies"):
            self.append_log("❌ Сначала авторизуйтесь!")
            return
        if config.SETTINGS.get("force_relogin_before_promo", True):
            self.append_log("🔄 Открываю браузер для обновления куки (нажмите 'Войти')...")
            self.main_win.open_login_window(self.acc_id, resume_promo_after=True)
        else:
            threading.Thread(target=self.main_win.worker.run_redeem_promos, args=(self.acc_id,), daemon=True).start()

    def append_log(self, text):
        current_time = time.strftime("%H:%M:%S")
        self.log_text.append(f"<span style='color: #777777;'>[{current_time}]</span> {text}")