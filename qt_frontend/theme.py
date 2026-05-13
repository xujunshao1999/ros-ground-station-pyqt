from __future__ import annotations

from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import QApplication

BG = "#161a22"
SURFACE = "#1c2330"
SURFACE_2 = "#232c3b"
FIELD = "#202838"
BORDER = "#394355"
TEXT = "#f4f6f8"
MUTED = "#aab3c0"
PRIMARY = "#7aa7d9"
SUCCESS = "#22c55e"
WARNING = "#f59e0b"
DANGER = "#dc3f45"
DANGER_HOVER = "#c83238"


def apply_app_theme(app: QApplication) -> None:
    """Apply the operator-console theme to the whole Qt application."""
    app.setStyle("Fusion")
    app.setFont(QFont("Fira Sans", 10))

    palette = QPalette()
    palette.setColor(QPalette.Window, _qcolor(BG))
    palette.setColor(QPalette.WindowText, _qcolor(TEXT))
    palette.setColor(QPalette.Base, _qcolor(SURFACE))
    palette.setColor(QPalette.AlternateBase, _qcolor(SURFACE_2))
    palette.setColor(QPalette.ToolTipBase, _qcolor(SURFACE))
    palette.setColor(QPalette.ToolTipText, _qcolor(TEXT))
    palette.setColor(QPalette.Text, _qcolor(TEXT))
    palette.setColor(QPalette.Button, _qcolor(SURFACE_2))
    palette.setColor(QPalette.ButtonText, _qcolor(TEXT))
    palette.setColor(QPalette.Highlight, _qcolor(PRIMARY))
    palette.setColor(QPalette.HighlightedText, _qcolor(BG))
    app.setPalette(palette)

    app.setStyleSheet(APP_STYLESHEET)


def _qcolor(value: str):
    return QColor(value)


APP_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG};
    color: {TEXT};
}}
QMenuBar, QMenu, QToolBar, QStatusBar {{
    background-color: {SURFACE_2};
    color: {TEXT};
    border-color: {BORDER};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background-color: #2d3748;
}}
QToolBar {{
    spacing: 10px;
    padding: 8px 6px;
    border-bottom: 1px solid {BORDER};
}}
QStatusBar {{
    border-top: 1px solid {BORDER};
}}
QLabel {{
    color: {TEXT};
}}
QToolBar QLabel, QStatusBar QLabel {{
    background-color: #1d2532;
    border: 1px solid #30394a;
    border-radius: 4px;
    padding: 3px 6px;
}}
QLabel[muted="true"] {{
    color: {MUTED};
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {BG};
}}
QTabBar::tab {{
    background-color: {SURFACE};
    color: {MUTED};
    padding: 7px 12px;
    border: 1px solid {BORDER};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    background-color: {SURFACE_2};
    border-top: 2px solid {PRIMARY};
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding: 10px;
    background-color: {SURFACE};
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT};
}}
QPushButton {{
    background-color: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 6px 12px;
    min-height: 24px;
}}
QPushButton:hover {{
    border-color: {PRIMARY};
    background-color: #2d3748;
}}
QPushButton:pressed {{
    background-color: #1a2230;
}}
QPushButton:disabled {{
    color: #7f8997;
    background-color: #1b2330;
    border-color: #30394a;
}}
QPushButton#dangerButton {{
    background-color: {DANGER};
    color: white;
    border-color: {DANGER};
    font-weight: 700;
}}
QPushButton#dangerButton:hover {{
    background-color: {DANGER_HOVER};
    border-color: #e66f74;
}}
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {FIELD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px;
    selection-background-color: {PRIMARY};
    selection-color: {BG};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border-color: {PRIMARY};
}}
QTextEdit[invalid="true"] {{
    border: 2px solid {DANGER};
}}
QTreeWidget, QTableWidget, QListWidget, QTextBrowser {{
    background-color: {SURFACE};
    alternate-background-color: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background-color: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px;
    font-weight: 600;
}}
QProgressBar {{
    background-color: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {SUCCESS};
    border-radius: 3px;
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: #465064;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {PRIMARY};
    border: 1px solid #b6cbe4;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSplitter::handle {{
    background-color: {BORDER};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {SURFACE};
    border: none;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #566174;
    border-radius: 4px;
}}
"""
