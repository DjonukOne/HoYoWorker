import sys
import os

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

ICON_PATH = resource_path("icon.png")

DEFAULT_HSR_STYLE = """
QMainWindow, QWidget#CentralWidget { background-color: #121212; }
QLabel { color: #ececec; font-family: "Segoe UI", sans-serif; font-size: 13px; }
QPushButton {
    background-color: #2b2b2b; color: #d4af37; border: 1px solid #d4af37;
    padding: 7px 12px; border-radius: 4px; font-weight: bold; font-size: 13px;
}
QPushButton:hover { background-color: #d4af37; color: #121212; }
QPushButton:pressed { background-color: #aa8c2c; }
QTextEdit, QLineEdit {
    background-color: #1e1e1e; color: #ececec; border: 1px solid #444444;
    border-radius: 4px; font-family: "Consolas", monospace; font-size: 12px; padding: 5px;
}
QLineEdit:focus { border: 1px solid #d4af37; }
QTimeEdit, QComboBox {
    background-color: #1e1e1e; color: #d4af37; border: 1px solid #d4af37;
    padding: 5px 8px; border-radius: 4px; font-weight: bold; min-width: 75px;
}
QComboBox QAbstractItemView {
    background-color: #1e1e1e; color: #ececec; selection-background-color: #d4af37;
    selection-color: #121212; border: 1px solid #d4af37;
}
QTabWidget::pane { border: 1px solid #333333; background-color: #121212; border-radius: 4px; }
QTabBar::tab {
    background-color: #1e1e1e; color: #a0a0a0; border: 1px solid #333333;
    border-bottom: none; padding: 6px 10px; margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px;
    font-family: "Consolas", monospace; font-size: 12px; font-weight: bold;
}
QTabBar::tab:selected { background-color: #2b2b2b; color: #d4af37; border-color: #d4af37; }
QTabBar::tab:hover { background-color: #252525; color: #ffffff; }
QCheckBox { color: #ececec; font-size: 13px; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #d4af37; border-radius: 3px; background: #1e1e1e; }
QCheckBox::indicator:checked { background: #d4af37; }
QScrollArea { border: none; background-color: transparent; }
"""