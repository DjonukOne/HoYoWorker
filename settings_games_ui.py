from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
import config

class GamesManagerWidget(QWidget):
    games_changed = pyqtSignal() # Сигнал для обновления выпадающего списка игр в настройках

    def __init__(self, main_win):
        super().__init__()
        self.main_win = main_win
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("<b>🎮 Модули игр (Настройка и добавление проектов):</b>")
        layout.addWidget(title)

        self.grid = QGridLayout()
        self.grid.setSpacing(6)
        self.grid.setColumnStretch(0, 2)
        self.grid.setColumnStretch(1, 2)
        self.grid.setColumnStretch(2, 5)
        layout.addLayout(self.grid)

        # Строка добавления новой игры
        add_layout = QHBoxLayout()
        self.in_key = QLineEdit()
        self.in_key.setPlaceholderText("ID (напр. HONKAI)")
        self.in_short = QLineEdit()
        self.in_short.setPlaceholderText("Короткое имя (HI3)")
        self.in_url = QLineEdit()
        self.in_url.setPlaceholderText("URL API промокодов (необязательно)")
        
        btn_add = QPushButton("➕ Добавить")
        btn_add.clicked.connect(self.add_new_game)

        add_layout.addWidget(self.in_key, stretch=2)
        add_layout.addWidget(self.in_short, stretch=2)
        add_layout.addWidget(self.in_url, stretch=5)
        add_layout.addWidget(btn_add)
        layout.addLayout(add_layout)

        self.rebuild_grid()

    def rebuild_grid(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        headers = ["ID игры", "Короткое имя", "Источник промокодов (URL)", ""]
        for col, text in enumerate(headers):
            lbl = QLabel(f"<span style='color:#a0a0a0;'>{text}</span>")
            self.grid.addWidget(lbl, 0, col)

        for row, (g_key, g_data) in enumerate(config.GAMES.items(), start=1):
            is_builtin = g_data.get("builtin", False)

            key_edit = QLineEdit(g_key)
            key_edit.setReadOnly(True)
            key_edit.setStyleSheet("color: #888888; background-color: #161616;")
            self.grid.addWidget(key_edit, row, 0)

            short_edit = QLineEdit(g_data.get("short_name", g_key))
            short_edit.textChanged.connect(lambda val, k=g_key: self.update_game_field(k, "short_name", val))
            self.grid.addWidget(short_edit, row, 1)

            url_edit = QLineEdit(g_data.get("promo_url", ""))
            url_edit.setPlaceholderText("Нет источника кодов")
            url_edit.textChanged.connect(lambda val, k=g_key: self.update_game_field(k, "promo_url", val))
            self.grid.addWidget(url_edit, row, 2)

            if is_builtin:
                lock_lbl = QLabel("🔒")
                lock_lbl.setToolTip("Базовая игра (нельзя удалить)")
                lock_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lock_lbl.setFixedWidth(30)
                self.grid.addWidget(lock_lbl, row, 3)
            else:
                btn_del = QPushButton("✕")
                btn_del.setFixedWidth(30)
                btn_del.setStyleSheet("color: #ff5555; border-color: #ff5555; padding: 2px;")
                btn_del.clicked.connect(lambda _, k=g_key: self.remove_game(k))
                self.grid.addWidget(btn_del, row, 3)

    def update_game_field(self, g_key, field, val):
        if g_key in config.GAMES:
            config.GAMES[g_key][field] = val.strip()
            config.save_games()
            if field == "short_name":
                self.games_changed.emit()

    def add_new_game(self):
        key = self.in_key.text().strip().upper()
        short = self.in_short.text().strip()
        url = self.in_url.text().strip()
        if not key:
            return
        if config.add_or_update_game(key, short, url):
            self.in_key.clear()
            self.in_short.clear()
            self.in_url.clear()
            self.rebuild_grid()
            self.games_changed.emit()

    def remove_game(self, g_key):
        if config.delete_game(g_key):
            self.rebuild_grid()
            self.games_changed.emit()