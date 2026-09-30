"""Native PySide6 desktop panel for Pulse PC."""
import asyncio
import base64
from collections import deque
import importlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid
import winreg
from datetime import datetime

from dotenv import dotenv_values
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTextCharFormat, QTextCursor
from PySide6.QtCore import QUrl, QDir
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QCheckBox, QColorDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton, QProgressBar, QSlider,
    QScrollArea, QSizePolicy, QStackedWidget, QSystemTrayIcon, QTextEdit,
    QVBoxLayout, QWidget,
)

import config
from bot_runtime import BotRunner
from modules import mobile_access, player_bridge
from player_controller import PlayerController
from modules.program_store import validate_programs, executable_process
from desktop_services import AsyncJob, EventJournal, redact, probe_bot, send_files_with_token, format_bytes, computer_info


STYLE = """
QWidget { background: transparent; color: #EEF3FA; font-family: 'Segoe UI'; font-size: 14px; }
QMainWindow, QWidget#root, QWidget#pageBody { background: transparent; }
QDialog { background: #05080C; }
QLabel { background: transparent; border: none; }
QLabel[kind='eyebrow'] { color: #2A8CFF; font-size: 12px; font-weight: 700; }
QLabel[kind='title'] { font-size: 26px; font-weight: 600; }
QLabel[kind='heading'] { font-size: 18px; font-weight: 600; }
QLabel[kind='muted'] { color: #8A97A8; }
QLabel[kind='stat'] { font-size: 22px; font-weight: 700; }
QLabel[kind='brand'] { font-size: 19px; font-weight: 700; }
QLabel[kind='small'] { color: #6F7E92; font-size: 12px; }
QLabel[kind='accent'] { color: #19C3FF; font-weight: 600; }
QLabel[kind='chip'] { background: #111A24; color: #B9C6D8; border: 1px solid #1F2B3B; border-radius: 16px; padding: 8px 14px; }
QFrame#sidebar { background: transparent; border: none; border-right: 1px solid #1A2431; }
QFrame[kind='card'], QFrame[kind='program'] { background: #0D1319; border: 1px solid #1F2B3B; border-radius: 12px; }
QFrame[kind='program'] { border-left: 3px solid #2A8CFF; }
QFrame[kind='hero'] { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #11335C, stop:0.6 #0D1A2B, stop:1 #0D1319); border: 1px solid #245B9E; border-radius: 14px; }
QPushButton { background: #16202C; border: 1px solid #2A3850; border-radius: 11px; padding: 11px 16px; font-weight: 600; }
QPushButton:hover { background: #1E2C3E; }
QPushButton:focus { border: 1px solid #2A8CFF; }
QPushButton:disabled { background: #111A24; color: #566579; border-color: #1A2431; }
QPushButton[kind='primary'] { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2A8CFF, stop:1 #19C3FF); color: #03101F; border: none; }
QPushButton[kind='primary']:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #5AA8FF, stop:1 #57D6FF); }
QPushButton[kind='primary']:disabled { background: #12263D; color: #4C7399; border-color: #12263D; }
QListWidget { background: #0D1319; border: 1px solid #1F2B3B; border-radius: 10px; padding: 4px; outline: none; }
QListWidget::item { padding: 8px 10px; border-radius: 8px; }
QListWidget::item:selected { background: #14304F; color: #7CC0FF; }
QSlider::groove:horizontal { height: 4px; background: #1F2B3B; border-radius: 2px; }
QSlider::sub-page:horizontal { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2A8CFF, stop:1 #19C3FF); border-radius: 2px; }
QSlider::handle:horizontal { background: #FFFFFF; border: 2px solid #19C3FF; width: 12px; margin: -6px 0; border-radius: 8px; }
QPushButton[kind='nav'] { background: transparent; color: #8A97A8; border: none; border-radius: 13px; padding: 0 12px; text-align: left; }
QPushButton[kind='nav']:hover { background: #111A24; }
QPushButton[kind='nav']:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #163A63, stop:1 #0E1E33); color: #FFFFFF; border-left: 3px solid #19C3FF; }
QPushButton[kind='danger'] { color: #ed9cac; }
QPushButton[kind='stop'] { background: #3A1823; color: #FFB3C0; border: 1px solid #8A3A50; padding-left: 14px; padding-right: 18px; }
QPushButton[kind='stop']:hover { background: #4C2030; border-color: #8A3A50; }
QPushButton[kind='stop']:disabled { background: #16202C; color: #8d7b83; border-color: #263347; }
QLineEdit, QTextEdit { background: #04070B; border: 1px solid #253349; border-radius: 11px; padding: 12px; selection-background-color: #1F4E85; }
QLineEdit:focus, QTextEdit:focus { border-color: #2A8CFF; }
QTextEdit#console { color: #9AA9BD; font-family: Consolas; font-size: 13px; }
QCheckBox { background: transparent; spacing: 10px; }
QCheckBox::indicator { width: 20px; height: 20px; border: 1px solid #2A3850; border-radius: 5px; background: #04070B; }
QCheckBox::indicator:checked { background: #2A8CFF; border-color: #2A8CFF; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 6px 0; }
QScrollBar::handle:vertical { background: #253349; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QMenu { background: #0D1319; border: 1px solid #1F2B3C; padding: 6px; }
QMenu::item { padding: 9px 22px; border-radius: 5px; }
QMenu::item:selected { background: #16202C; }
QToolTip { background: #1A2638; color: #EEF3FA; border: 1px solid #2B4468; padding: 7px; }
QStatusBar { color: #8A97A8; background: transparent; padding: 0 12px 6px; }
QProgressBar { border: 1px solid #253349; border-radius: 6px; background: #04070B; text-align: center; min-height: 18px; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2A8CFF, stop:1 #19C3FF); border-radius: 5px; }
QPushButton[kind='window'] { background: transparent; border: none; border-radius: 7px; padding: 0; }
QPushButton[kind='window']:hover { background: #182231; }
QPushButton#closeWindow:hover { background: #70394e; }
"""


def icon(name, color="#B9C6D8"):
    """Small vector line icons rendered locally; no web fonts or CDN."""
    paths = {
        "pulse": [[(2, 12), (7, 12), (10, 4), (14, 20), (17, 12), (22, 12)]],
        "home": [[(3, 10), (12, 3), (21, 10)], [(5, 9), (5, 21), (10, 21), (10, 14), (14, 14), (14, 21), (19, 21), (19, 9)]],
        "programs": [[(3, 3), (10, 3), (10, 10), (3, 10), (3, 3)], [(14, 3), (21, 3), (21, 10), (14, 10), (14, 3)], [(3, 14), (10, 14), (10, 21), (3, 21), (3, 14)], [(14, 14), (21, 14), (21, 21), (14, 21), (14, 14)]],
        "console": [[(4, 6), (10, 12), (4, 18)], [(13, 18), (21, 18)]],
        "settings": [[(3, 6), (21, 6)], [(3, 12), (21, 12)], [(3, 18), (21, 18)], [(8, 3), (8, 9)], [(16, 9), (16, 15)], [(10, 15), (10, 21)]],
        "mobile": [[(7, 2), (17, 2), (17, 22), (7, 22), (7, 2)], [(11, 19), (13, 19)]],
        "player": [[(9, 18), (9, 5), (19, 3), (19, 16)], [(6, 18), (9, 18)], [(16, 16), (19, 16)]],
        "telegram": [[(2, 10), (22, 2), (16, 22), (11, 13), (2, 10)], [(11, 13), (22, 2)]],
        "play": [[(7, 4), (20, 12), (7, 20), (7, 4)]],
        "stop": [[(5, 5), (19, 5), (19, 19), (5, 19), (5, 5)]],
        "plus": [[(12, 4), (12, 20)], [(4, 12), (20, 12)]],
        "minimize": [[(5, 16), (19, 16)]],
        "maximize": [[(5, 5), (19, 5), (19, 19), (5, 19), (5, 5)]],
        "restore": [[(8, 5), (19, 5), (19, 16)], [(5, 8), (16, 8), (16, 19), (5, 19), (5, 8)]],
        "close": [[(6, 6), (18, 18)], [(18, 6), (6, 18)]],
    }
    solid = {
        "play": [[(7, 4), (20, 12), (7, 20)]],
        "pause": [[(6, 4), (10, 4), (10, 20), (6, 20)], [(14, 4), (18, 4), (18, 20), (14, 20)]],
        "prev": [[(5.5, 5), (8.5, 5), (8.5, 19), (5.5, 19)], [(19, 5), (19, 19), (9.5, 12)]],
        "next": [[(15.5, 5), (18.5, 5), (18.5, 19), (15.5, 19)], [(5, 5), (5, 19), (14.5, 12)]],
        "stop": [[(6, 6), (18, 6), (18, 18), (6, 18)]],
    }
    pix = QPixmap(48, 48)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2, 2)
    if name in solid:
        painter.setPen(QPen(QColor(color), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QColor(color))
        for polygon in solid[name]:
            painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in polygon]))
    else:
        painter.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        for path in paths.get(name, paths["pulse"]):
            for a, b in zip(path, path[1:]):
                painter.drawLine(*a, *b)
    painter.end()
    return QIcon(pix)


class MessageLabel(QLabel):
    """Do not reserve a blank line for messages that have not arrived yet."""
    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))


def label(text, kind="", wrap=False):
    widget = QLabel(text) if text else MessageLabel()
    if not text:
        widget.hide()
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setProperty("kind", kind)
    widget.setWordWrap(wrap)
    if wrap:
        widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return widget


def button(text, callback, kind="", symbol=None):
    widget = QPushButton(text)
    widget.setProperty("kind", kind)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if symbol:
        widget.setIcon(icon(symbol, "#03101F" if kind == "primary" else "#B9C6D8"))
    widget.clicked.connect(callback)
    return widget


def card(kind="card"):
    widget = QFrame()
    widget.setProperty("kind", kind)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(24, 22, 24, 22)
    layout.setSpacing(14)
    return widget, layout


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".pulse-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class WindowTitleBar(QFrame):
    """Custom controls for the rounded, translucent top-level window."""
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.drag_offset = None
        self.setFixedHeight(44)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 4, 0)
        mark = QLabel()
        emblem = QPixmap(str(Path(config.APP_DIR) / "image" / "emblem.png"))
        mark.setPixmap(emblem.scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) if not emblem.isNull() else icon("pulse", "#2A8CFF").pixmap(22, 22))
        title = QLabel('<span style="color:#EEF3FA">Pulse</span> <span style="color:#2A8CFF">PC</span>')
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet("font-size: 15px; font-weight: 700; letter-spacing: 1px;")
        for widget in (mark, title):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(widget)
        row.addStretch()
        self.minimize_button = button("", window.showMinimized, "window", "minimize")
        self.maximize_button = button("", window.toggle_maximized, "window", "maximize")
        self.close_button = button("", window.close, "window", "close")
        self.close_button.setObjectName("closeWindow")
        for control, title in ((self.minimize_button, "Свернуть"), (self.maximize_button, "Развернуть"), (self.close_button, "Закрыть")):
            control.setFixedSize(36, 30)
            control.setIconSize(QSize(16, 16))
            control.setToolTip(title)
            control.setAccessibleName(title)
            row.addWidget(control)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.owner.windowHandle()
            if handle and handle.startSystemMove():
                event.accept()
                return
            self.drag_offset = event.globalPosition().toPoint() - self.owner.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and not self.owner.isMaximized():
            self.owner.move(event.globalPosition().toPoint() - self.drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = None
            self.owner.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class UiSignals(QObject):
    log = Signal(str)
    status = Signal(str)
    restart = Signal()
    quit = Signal()
    job_done = Signal(str, object, object)
    transfer_progress = Signal(object)


class GuiLogHandler(logging.Handler):
    def __init__(self, signals):
        super().__init__()
        self.signals = signals
        self.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))

    def emit(self, record):
        self.signals.log.emit(self.format(record))


class PulsePCApp(QMainWindow):
    def __init__(self, *, auto_start=True, enable_tray=True, runner_factory=BotRunner):
        super().__init__()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.installEventFilter(self)
        self.resize(1120, 820)
        self.setMinimumSize(800, 600)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(QIcon(str(Path(config.APP_DIR) / "image" / "icon.ico")))
        if self.windowIcon().isNull():
            self.setWindowIcon(icon("pulse", "#2A8CFF"))
        self.is_quitting = False
        self.programs_dirty = False
        self.programs_valid = True
        self.temp_programs = []
        self.edit_index = None
        self.jobs = {}
        self.transfer_state = {}
        self.file_dialog = None
        self.transfer_cancelling = False
        self.log_lines = deque(maxlen=2000)
        self.journal = None
        self.state = "STOPPED"
        self.tray_icon = None
        self.background_color = QColor("#05080C")
        self.signals = UiSignals(self)
        self.signals.log.connect(self.append_log, Qt.ConnectionType.QueuedConnection)
        self.signals.status.connect(self.update_bot_status, Qt.ConnectionType.QueuedConnection)
        self.signals.restart.connect(self.restart_bot, Qt.ConnectionType.QueuedConnection)
        self.signals.quit.connect(self.quit_app, Qt.ConnectionType.QueuedConnection)
        self.signals.job_done.connect(self.job_finished, Qt.ConnectionType.QueuedConnection)
        self.signals.transfer_progress.connect(self.update_transfer_progress, Qt.ConnectionType.QueuedConnection)
        self.bot_runner = runner_factory(self.signals.log.emit, self.signals.status.emit, self.signals.restart.emit, self.signals.quit.emit)
        self.setup_ui()
        self.load_settings()
        try:
            self.journal = EventJournal(Path(config.BASE_DIR) / "logs")
            self.log_lines.extend(self.journal.history())
            self.render_logs()
        except OSError as exc:
            self.append_log(f"ERROR  Журнал недоступен: {exc}")
        self.load_programs()
        self.log_handler = GuiLogHandler(self.signals)
        logging.getLogger().addHandler(self.log_handler)
        if enable_tray:
            self.setup_tray()
        self.update_bot_status("STOPPED")
        self.append_log("SYS  Pulse PC готов к запуску.")
        if enable_tray:
            QTimer.singleShot(800, self.show_startup_notification)
        if auto_start:
            QTimer.singleShot(500, self.auto_start_bot)
        self.metrics_timer = QTimer(self)
        self.metrics_timer.timeout.connect(self.refresh_metrics)
        self.metrics_timer.start(5000)
        if auto_start:
            QTimer.singleShot(1000, self.refresh_metrics)

    def setup_ui(self):
        root = QWidget()
        root.setObjectName("root")
        root.setMouseTracking(True)
        root.installEventFilter(self)
        shell = QVBoxLayout(root)
        shell.setContentsMargins(8, 8, 8, 8)
        shell.setSpacing(0)
        self.title_bar = WindowTitleBar(self)
        shell.addWidget(self.title_bar)
        row = QHBoxLayout()
        shell.addLayout(row, 1)
        row.setContentsMargins(0, 12, 0, 0)
        row.setSpacing(0)
        side = QFrame()
        self.sidebar = side
        side.setObjectName("sidebar")
        side.setFixedWidth(196)
        nav = QVBoxLayout(side)
        nav.setContentsMargins(10, 6, 14, 12)
        nav.setSpacing(8)
        self.nav_buttons = []
        for index, (name, title) in enumerate((("home", "Главная"), ("programs", "Программы"), ("console", "Консоль"), ("settings", "Настройки"), ("mobile", "Телефон"), ("player", "Плеер"))):
            item = button(title, lambda checked=False, i=index: self.switch_tab(i), "nav", name)
            item.setFixedHeight(48)
            item.setIconSize(QSize(23, 23))
            item.setCheckable(True)
            item.setToolTip(title)
            item.setAccessibleName(title)
            self.nav_buttons.append((item, name))
        # Page order is fixed; the sidebar shows the player right after Programs.
        for position in (0, 1, 5, 2, 3, 4):
            nav.addWidget(self.nav_buttons[position][0])
        nav.addStretch()
        row.addWidget(side)
        self.pages = QStackedWidget()
        row.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        self.statusBar().setSizeGripEnabled(False)
        self.build_home()
        self.build_programs()
        self.build_console()
        self.build_settings()
        self.build_mobile()
        self.build_player()
        self.switch_tab(0)
        self.mobile_timer = QTimer(self)
        self.mobile_timer.timeout.connect(self.refresh_mobile)
        self.mobile_timer.start(2000)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#1B2F4D"), 1))
        glow = QLinearGradient(0, 0, self.width() * 0.6, self.height())
        glow.setColorAt(0.0, QColor("#0A1B33"))
        glow.setColorAt(0.45, self.background_color)
        glow.setColorAt(1.0, QColor("#04070B"))
        painter.setBrush(glow)
        radius = 0 if self.isMaximized() or self.isFullScreen() else 14
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(bounds, radius, radius)

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            maximized = self.isMaximized()
            self.title_bar.maximize_button.setIcon(icon("restore" if maximized else "maximize"))
            text = "Восстановить" if maximized else "Развернуть"
            self.title_bar.maximize_button.setToolTip(text)
            self.title_bar.maximize_button.setAccessibleName(text)
            self.update()

    def resize_edges(self, point):
        edges = Qt.Edge(0)
        if not self.isMaximized() and not self.isFullScreen():
            if point.x() < 8:
                edges |= Qt.Edge.LeftEdge
            elif point.x() >= self.width() - 8:
                edges |= Qt.Edge.RightEdge
            if point.y() < 8:
                edges |= Qt.Edge.TopEdge
            elif point.y() >= self.height() - 8:
                edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            point = self.mapFromGlobal(event.globalPosition().toPoint())
            edges = self.resize_edges(point)
            diagonal = edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
            other_diagonal = edges in (Qt.Edge.RightEdge | Qt.Edge.TopEdge, Qt.Edge.LeftEdge | Qt.Edge.BottomEdge)
            cursor = (Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor if other_diagonal
                      else Qt.CursorShape.SizeHorCursor if edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge)
                      else Qt.CursorShape.SizeVerCursor if edges else Qt.CursorShape.ArrowCursor)
            watched.setCursor(cursor)
            if edges and event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                handle = self.windowHandle()
                if handle and handle.startSystemResize(edges):
                    return True
        elif event.type() == QEvent.Type.Leave:
            watched.unsetCursor()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "sidebar"):
            return
        compact = self.width() < 1000
        self.sidebar.setFixedWidth(76 if compact else 196)
        for item, _ in self.nav_buttons:
            item.setText("" if compact else item.accessibleName())
        self.program_columns.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)

    def page(self, eyebrow, title, description="", action=None):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("pageBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 18, 22, 20)
        layout.setSpacing(16)
        heading = QHBoxLayout()
        heading.addWidget(label(title, "title"))
        heading.addStretch()
        if action is not None:
            heading.addWidget(action)
        layout.addLayout(heading)
        layout.addSpacing(2)
        scroll.setWidget(body)
        self.pages.addWidget(scroll)
        return layout

    def build_home(self):
        layout = self.page("", "Главная")
        hero, content = card("hero")
        top = QHBoxLayout()
        self.product_title = label("Telegram-бот", "heading")
        top.addWidget(self.product_title)
        top.addStretch()
        self.connection = label("●  Не подключён", "chip")
        top.addWidget(self.connection)
        content.addLayout(top)
        self.status_hint = label("", "muted", True)
        content.addWidget(self.status_hint)
        buttons = QHBoxLayout()
        self.toggle_button = button("Запустить", self.toggle_bot_state, "primary", "play")
        self.toggle_button.setMinimumWidth(175)
        buttons.addWidget(self.toggle_button)
        buttons.addWidget(button("Настройки", lambda: self.switch_tab(3)))
        buttons.addStretch()
        content.addLayout(buttons)
        layout.addWidget(hero)
        metrics, metrics_layout = card()
        metrics_heading = QHBoxLayout()
        metrics_heading.addWidget(label("Компьютер", "heading"))
        metrics_heading.addStretch()
        metrics_heading.addWidget(button("Обновить", lambda: self.refresh_metrics(force=True)))
        metrics_layout.addLayout(metrics_heading)
        self.metrics_text = label("Нажмите «Обновить», чтобы посмотреть нагрузку и память.", "muted", True)
        metrics_layout.addWidget(self.metrics_text)
        self.metrics_updated = label("", "small", True)
        metrics_layout.addWidget(self.metrics_updated)
        layout.addWidget(metrics)
        transfer, transfer_layout = card()
        transfer_layout.addWidget(label("Файлы в Telegram", "heading"))
        transfer_layout.addWidget(label("В личный чат администратора · до 50 МБ на файл", "muted", True))
        transfer_buttons = QHBoxLayout()
        self.send_file_button = button("Выбрать файлы…", self.choose_file_to_send)
        self.cancel_transfer_button = button("Отменить отправку", self.cancel_transfer, "stop")
        self.cancel_transfer_button.setEnabled(False)
        self.cancel_transfer_button.hide()
        transfer_buttons.addWidget(self.send_file_button)
        transfer_buttons.addWidget(self.cancel_transfer_button)
        transfer_buttons.addStretch()
        transfer_layout.addLayout(transfer_buttons)
        self.transfer_count = label("Файлы не выбраны", "accent", True)
        self.transfer_file = label("", "muted", True)
        self.transfer_size = label("", "muted", True)
        self.transfer_speed = label("Скорость: —", "muted")
        self.transfer_speed.setToolTip("Приблизительная скорость передачи данных. Доставка подтверждается ответом Telegram.")
        self.file_progress = QProgressBar()
        self.file_progress.setValue(0)
        self.file_progress.setFormat("Текущий файл: %p%")
        self.batch_progress = QProgressBar()
        self.batch_progress.setValue(0)
        self.batch_progress.setFormat("Вся очередь: %p%")
        self.transfer_details = QWidget()
        detail_layout = QVBoxLayout(self.transfer_details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.transfer_count, self.transfer_file, self.transfer_size, self.transfer_speed, self.file_progress, self.batch_progress):
            detail_layout.addWidget(widget)
        transfer_layout.addWidget(self.transfer_details)
        self.transfer_details.hide()
        self.transfer_message = label("", "muted", True)
        transfer_layout.addWidget(self.transfer_message)
        layout.addWidget(transfer)
        layout.addStretch()

    def field(self, layout, title, placeholder="", max_length=32767):
        entry = QLineEdit()
        entry.setPlaceholderText(placeholder)
        entry.setMaxLength(max_length)
        entry.setAccessibleName(title)
        caption = label(title)
        caption.setBuddy(entry)
        layout.addWidget(caption)
        layout.addWidget(entry)
        return entry

    def build_programs(self):
        self.save_programs_button = button("Сохранить список", self.save_programs, "primary")
        layout = self.page("Быстрый запуск", "Программы", "Добавьте программы, которые будут доступны для быстрого запуска через Telegram.", action=self.save_programs_button)
        columns = QHBoxLayout()
        self.program_columns = columns
        columns.setSpacing(16)
        form, fields = card()
        self.program_form_title = label("Новая программа", "heading")
        fields.addWidget(self.program_form_title)
        self.program_count = label("0 / 15", "accent")
        fields.addWidget(self.program_count)
        self.program_name = self.field(fields, "Название программы", "Например, OBS Studio", 40)
        self.program_path = self.field(fields, "Путь к программе", "C:\\Program Files\\…\\program.exe")
        fields.addWidget(button("Выбрать файл…", self.browse_executable))
        self.program_description = self.field(fields, "Описание", "Что должна запускать команда?", 130)
        self.add_program_button = button("Добавить программу", self.add_program, "primary", "plus")
        fields.addWidget(self.add_program_button)
        self.cancel_edit_button = button("Отменить редактирование", self.cancel_program_edit)
        self.cancel_edit_button.hide()
        fields.addWidget(self.cancel_edit_button)
        fields.addStretch()
        columns.addWidget(form, 4)
        preview = QWidget()
        items = QVBoxLayout(preview)
        items.setContentsMargins(0, 0, 0, 0)
        items.addWidget(label("Ваши программы", "heading", True))
        self.program_list = QVBoxLayout()
        self.program_list.setSpacing(12)
        items.addLayout(self.program_list)
        items.addStretch()
        columns.addWidget(preview, 5)
        layout.addLayout(columns)
        self.program_message = label("", "muted", True)
        layout.addWidget(self.program_message)
        layout.addStretch()

    def build_mobile(self):
        layout = self.page("Мобильное приложение", "Телефон")
        status, inner = card()
        status.setMaximumWidth(760)
        inner.addWidget(label("Видимость для телефона", "heading"))
        self.mobile_status = label("", "accent", True)
        inner.addWidget(self.mobile_status)
        self.mobile_address = label("", "muted", True)
        inner.addWidget(self.mobile_address)
        inner.addWidget(label("Приложение Pulse PC на телефоне само находит этот ПК в той же Wi-Fi сети. "
                              "При первом подключении здесь появится запрос — подтвердите его.", "muted", True))
        self.allow_pairing = QCheckBox("Разрешить подключение новых устройств")
        self.allow_pairing.setChecked(mobile_access.load()["allow_pairing"])
        self.allow_pairing.toggled.connect(lambda on: mobile_access.set_option("allow_pairing", on))
        inner.addWidget(self.allow_pairing)
        layout.addWidget(status)
        devices, self.mobile_devices = card()
        devices.setMaximumWidth(760)
        self.mobile_devices.addWidget(label("Подключённые телефоны", "heading"))
        self.mobile_device_rows = QVBoxLayout()
        self.mobile_device_rows.setSpacing(10)
        self.mobile_devices.addLayout(self.mobile_device_rows)
        layout.addWidget(devices)
        layout.addStretch()
        self.mobile_signature = None

    def refresh_mobile(self, force=False):
        if not force and self.pages.currentIndex() != 4:
            return
        state = mobile_access.STATE
        if state["running"]:
            self.mobile_status.setText("●  ПК виден телефону")
            self.mobile_address.setText("Адрес: " + ", ".join(state["addresses"]))
        else:
            self.mobile_status.setText("●  Мобильный доступ выключен")
            self.mobile_address.setText("Он работает вместе с ботом: запустите бота на главной странице.")
        try:
            data = mobile_access.load()
        except OSError:
            return
        signature = json.dumps(data["devices"], sort_keys=True)
        if not force and signature == self.mobile_signature:
            return
        self.mobile_signature = signature
        while self.mobile_device_rows.count():
            item = self.mobile_device_rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if not data["devices"]:
            self.mobile_device_rows.addWidget(label("Пока нет подключённых телефонов.", "muted", True))
        for device in data["devices"]:
            row = QFrame()
            row.setProperty("kind", "program")
            line = QHBoxLayout(row)
            line.setContentsMargins(16, 12, 16, 12)
            text = QVBoxLayout()
            text.addWidget(label(device.get("name", "Телефон"), "heading", True))
            seen = device.get("last_seen", "").replace("T", " ") or "ещё не был в сети"
            text.addWidget(label(f"Добавлен: {device.get('added', '').replace('T', ' ')}  ·  Активность: {seen}", "small", True))
            line.addLayout(text, 1)
            line.addWidget(button("Отозвать", lambda checked=False, d=device: self.revoke_device(d), "danger"))
            self.mobile_device_rows.addWidget(row)

    def revoke_device(self, device):
        answer = QMessageBox.question(self, "Отозвать телефон", f"Отозвать доступ для «{device.get('name', 'Телефон')}»?")
        if answer == QMessageBox.StandardButton.Yes:
            mobile_access.remove_device(device["id"])
            self.refresh_mobile(force=True)

    def build_player(self):
        layout = self.page("Музыка", "Плеер")
        self.player = PlayerController(self)
        self.player.changed.connect(self.refresh_player)
        now, inner = card()
        now.setMaximumWidth(760)
        self.player_title = label("Ничего не играет", "heading", True)
        self.player_artist = label("Выберите трек ниже — или запустите его с телефона.", "muted", True)
        inner.addWidget(self.player_title)
        inner.addWidget(self.player_artist)
        self.player_seek = QSlider(Qt.Orientation.Horizontal)
        self.player_seek.setRange(0, 1000)
        self.player_seek.sliderReleased.connect(self.seek_player)
        inner.addWidget(self.player_seek)
        self.player_time = label("0:00 / 0:00", "small")
        inner.addWidget(self.player_time)
        controls = QHBoxLayout()
        prev_button = button("", lambda: self.player.handle("prev"), "", "prev")
        self.player_toggle = button("", lambda: self.player.handle("toggle"), "primary", "play")
        next_button = button("", lambda: self.player.handle("next"), "", "next")
        for transport in (prev_button, self.player_toggle, next_button):
            transport.setFixedSize(56, 48)
            transport.setIconSize(QSize(22, 22))
            transport.setToolTip({prev_button: "Предыдущий", next_button: "Следующий"}.get(transport, "Пауза / воспроизведение"))
            transport.setStyleSheet("padding: 0;")
            controls.addWidget(transport)
        controls.addSpacing(18)
        controls.addWidget(label("Громкость", "small"))
        self.player_volume = QSlider(Qt.Orientation.Horizontal)
        self.player_volume.setRange(0, 100)
        self.player_volume.setValue(50)
        self.player_volume.setMaximumWidth(160)
        self.player_volume.valueChanged.connect(lambda v: self.player.handle("volume", v / 100))
        controls.addWidget(self.player_volume)
        controls.addStretch()
        inner.addLayout(controls)
        layout.addWidget(now)

        library, linner = card()
        library.setMaximumWidth(760)
        linner.addWidget(label("Библиотека", "heading"))
        linner.addWidget(label("Папки с музыкой. Их треки можно запускать с телефона (вкладка «Аудио»).", "muted", True))
        self.library_folders = QListWidget()
        self.library_folders.setMaximumHeight(110)
        linner.addWidget(self.library_folders)
        folder_buttons = QHBoxLayout()
        folder_buttons.addWidget(button("Добавить папку…", self.add_library_folder))
        folder_buttons.addWidget(button("Убрать выбранную", self.remove_library_folder, "danger"))
        folder_buttons.addStretch()
        linner.addLayout(folder_buttons)
        self.library_tracks = QListWidget()
        self.library_tracks.setMinimumHeight(260)
        self.library_tracks.itemActivated.connect(self.play_library_item)
        linner.addWidget(self.library_tracks)
        self.library_count = label("", "small")
        linner.addWidget(self.library_count)
        layout.addWidget(library)
        layout.addStretch()
        self.library_data = []
        self.refresh_library()

    def refresh_library(self):
        self.library_folders.clear()
        self.library_folders.addItems(player_bridge.load_folders())
        self.library_data = player_bridge.scan_tracks()
        self.library_tracks.clear()
        for track in self.library_data:
            self.library_tracks.addItem(f"{track['title']}   ·   {track['folder']}")
        suffix = " (показаны первые 2000)" if len(self.library_data) >= player_bridge.MAX_TRACKS else ""
        self.library_count.setText(f"Треков: {len(self.library_data)}{suffix}")

    def add_library_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка с музыкой")
        if folder:
            player_bridge.save_folders(player_bridge.load_folders() + [os.path.normpath(folder)])
            self.refresh_library()

    def remove_library_folder(self):
        row = self.library_folders.currentRow()
        folders = player_bridge.load_folders()
        if 0 <= row < len(folders):
            del folders[row]
            player_bridge.save_folders(folders)
            self.refresh_library()

    def play_library_item(self, item):
        row = self.library_tracks.row(item)
        if 0 <= row < len(self.library_data):
            self.player.open_track(self.library_data[row]["path"], self.library_data)

    def seek_player(self):
        duration = self.player.player.duration() / 1000
        self.player.handle("seek", self.player_seek.value() / 1000 * duration)

    @staticmethod
    def clock(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 60}:{seconds % 60:02d}"

    def refresh_player(self):
        state = player_bridge.snapshot()
        active = state["active"]
        self.player_title.setText(state["title"] if active else "Ничего не играет")
        self.player_artist.setText((state["artist"] or state["album"]) if active else "Выберите трек ниже — или запустите его с телефона.")
        self.player_toggle.setIcon(icon("pause" if state["status"] == "playing" else "play", "#03101F"))
        if not self.player_seek.isSliderDown():
            duration = state["duration"]
            self.player_seek.setValue(int(state["position"] / duration * 1000) if duration > 0 else 0)
        self.player_time.setText(f"{self.clock(state['position'])} / {self.clock(state['duration'])}")
        volume = int(state["volume"] * 100)
        if abs(self.player_volume.value() - volume) > 1 and not self.player_volume.isSliderDown():
            self.player_volume.blockSignals(True)
            self.player_volume.setValue(volume)
            self.player_volume.blockSignals(False)

    def build_console(self):
        layout = self.page("Мониторинг", "Консоль", "Здесь отображаются события и действия системы.")
        controls = QHBoxLayout()
        self.errors_only = QCheckBox("Только ошибки")
        self.errors_only.toggled.connect(self.render_logs)
        controls.addWidget(self.errors_only)
        controls.addStretch()
        controls.addWidget(button("Экспорт…", self.export_logs))
        controls.addWidget(button("Копировать", self.copy_logs))
        controls.addWidget(button("Очистить окно", self.clear_logs))
        layout.addLayout(controls)
        frame, content = card()
        console_heading = QHBoxLayout()
        console_heading.addWidget(label("Журнал событий", "heading"))
        console_heading.addStretch()
        self.log_count = label("0 событий", "chip")
        console_heading.addWidget(self.log_count)
        content.addLayout(console_heading)
        self.console = QTextEdit()
        self.console.setObjectName("console")
        self.console.setReadOnly(True)
        self.console.setAcceptRichText(False)
        self.console.document().setMaximumBlockCount(2000)
        self.console.setMinimumHeight(360)
        content.addWidget(self.console, 1)
        content.addWidget(label("Последние 2 000 событий. Очистка окна сохраняет историю на диске.", "small", True))
        layout.addWidget(frame, 1)

    def build_settings(self):
        layout = self.page("Конфигурация", "Настройки", "Подключение Telegram-бота и автозагрузка приложения.")
        form, fields = card()
        form.setMaximumWidth(760)
        fields.addWidget(label("Подключение", "heading"))
        self.token = self.field(fields, "Токен бота", "Токен от @BotFather")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_token = QCheckBox("Показать токен")
        self.show_token.toggled.connect(lambda show: self.token.setEchoMode(QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password))
        fields.addWidget(self.show_token)
        self.admin_id = self.field(fields, "ID администратора", "Числовой Telegram User ID", 20)
        self.admin_id.setToolTip("ID вашего личного аккаунта Telegram. После настройки отправьте боту /start.")
        self.probe_button = button("Проверить бота", self.check_bot)
        fields.addWidget(self.probe_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.probe_message = label("", "muted", True)
        fields.addWidget(self.probe_message)
        fields.addSpacing(8)
        self.autostart = QCheckBox("Запускать Pulse PC вместе с Windows")
        self.autostart.setChecked(self.check_autostart())
        self.autostart.toggled.connect(self.change_autostart)
        fields.addWidget(self.autostart)
        self.autostart.setToolTip("Закрытие окна сворачивает приложение в трей, если он доступен. Полный выход — через меню значка Pulse PC.")
        fields.addWidget(button("Сохранить настройки", self.save_settings, "primary"), 0, Qt.AlignmentFlag.AlignLeft)
        fields.addWidget(button("Возможности бота…", self.open_bot_options), 0, Qt.AlignmentFlag.AlignLeft)
        self.settings_message = label("", "accent", True)
        fields.addWidget(self.settings_message)
        layout.addWidget(form)
        layout.addStretch()
        self.token.textChanged.connect(self.refresh_status_hint)
        self.admin_id.textChanged.connect(self.refresh_status_hint)
        self.autostart.toggled.connect(self.refresh_status_hint)

    def open_bot_options(self):
        from bot_options_ui import BotOptionsDialog
        from modules.keyboards import load_programs
        try:
            dialog = BotOptionsDialog(load_programs(), self)
            dialog.exec()
        except (OSError, ValueError) as exc:
            self.settings_message.setText(f"Не удалось открыть настройки бота: {exc}")

    def refresh_status_hint(self):
        token = self.token.text().strip()
        admin = self.admin_id.text().strip()
        ready = bool(token and token != "your_telegram_bot_token_here" and admin.isascii() and admin.isdigit() and int(admin) > 0)
        hints = {
            "STOPPED": "Запустите бота, чтобы управлять компьютером через Telegram." if ready else "Начните с настроек: добавьте токен бота и ID администратора.",
            "STARTING": "Подключаемся к Telegram…",
            "RUNNING": "Бот принимает команды. Окно можно свернуть.",
            "RECONNECTING": "Проверьте интернет. Переподключение выполняется автоматически.",
            "STOPPING": "Завершаем работу бота. Дождитесь остановки.",
        }
        self.status_hint.setText(hints[self.state])
        if self.state == "RUNNING":
            from modules.monitor import pc_is_locked
            if pc_is_locked:
                self.status_hint.setText("ПК заблокирован. Управление приостановлено; помощь и отмена таймера доступны.")

    def switch_tab(self, index):
        self.pages.setCurrentIndex(index)
        for i, (item, name) in enumerate(self.nav_buttons):
            item.setChecked(i == index)
            item.setIcon(icon(name, "#7CC0FF" if i == index else "#8A97A8"))
        if index != 3:
            self.show_token.setChecked(False)
        if index == 4:
            self.refresh_mobile(force=True)
        if index == 5:
            self.refresh_library()

    def notify(self, text):
        self.statusBar().showMessage(text, 6000)
        self.append_log(text)

    @Slot(str)
    def append_log(self, text):
        text = redact(text, self.token.text().strip() if hasattr(self, "token") else "")
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}]  {text.rstrip()}"
        self.log_lines.append(line)
        if self.journal:
            self.journal.append(line)
        if not self.errors_only.isChecked() or self.is_error(line):
            self.insert_log(line)
        self.update_log_count()

    def update_log_count(self):
        visible = sum(1 for line in self.log_lines if not self.errors_only.isChecked() or self.is_error(line))
        self.log_count.setText(f"Событий: {visible} / {len(self.log_lines)}")

    @staticmethod
    def is_error(text):
        return any(word in text.upper() for word in ("ERROR", "ОШИБ", "КРИТИЧ", "TRACEBACK"))

    def insert_log(self, text):
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        upper = text.upper()
        color = "#ed9cac" if any(word in upper for word in ("ERROR", "ОШИБ", "КРИТИЧ")) else "#9AA9BD"
        if "ЗАПУЩЕН" in upper or "СОХРАНЕН" in upper:
            color = "#2A8CFF"
        fmt.setForeground(QColor(color))
        cursor.insertText(text + "\n", fmt)
        self.console.setTextCursor(cursor)
        self.console.ensureCursorVisible()

    def render_logs(self):
        self.console.clear()
        for line in self.log_lines:
            if not self.errors_only.isChecked() or self.is_error(line):
                self.insert_log(line)
        self.update_log_count()

    def clear_logs(self):
        self.log_lines.clear()
        self.console.clear()
        self.update_log_count()
        self.statusBar().showMessage("Окно очищено. История сохранена в config/logs.", 5000)

    def export_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт журнала", "pulse-log.txt", "Текст (*.txt)")
        if path:
            try:
                atomic_write(path, self.console.toPlainText())
                self.statusBar().showMessage("Журнал экспортирован", 5000)
            except OSError as exc:
                self.notify(f"Ошибка экспорта журнала: {exc}")

    def start_job(self, name, factory):
        if self.is_quitting or name in self.jobs:
            return False
        job = AsyncJob(factory, lambda result, error: self.signals.job_done.emit(name, result, error))
        self.jobs[name] = job
        job.start()
        return True

    @Slot(str, object, object)
    def job_finished(self, name, result, error):
        job = self.jobs.get(name)
        if job and job.thread.is_alive():
            QTimer.singleShot(10, lambda: self.job_finished(name, result, error))
            return
        self.jobs.pop(name, None)
        if self.is_quitting:
            return
        text = redact(error or str(result), self.token.text().strip())
        if name == "probe":
            self.probe_button.setEnabled(True)
            self.probe_message.setText(text)
        elif name == "file":
            self.send_file_button.setEnabled(True)
            self.cancel_transfer_button.setEnabled(False)
            self.cancel_transfer_button.hide()
            self.transfer_speed.setText("Скорость: —")
            completed = self.transfer_state.get("completed", 0)
            total = self.transfer_state.get("total", 0)
            if error:
                text += f" Подтверждено отправлено: {completed} из {total}."
            self.transfer_message.setText(text)
        elif name == "metrics":
            self.metrics_text.setText(text)
            self.metrics_updated.setText("Не удалось обновить данные" if error else f"Обновлено в {datetime.now():%H:%M:%S}")
        if name != "metrics":
            self.notify(("ERROR  " if error else "") + text)

    def check_bot(self):
        token = self.token.text().strip()
        if not token or token == "your_telegram_bot_token_here":
            self.probe_message.setText("Введите токен от @BotFather.")
            return
        if self.start_job("probe", lambda: probe_bot(token)):
            self.probe_button.setEnabled(False)
            self.probe_message.setText("Проверяю подключение…")

    def choose_file_to_send(self):
        if "file" in self.jobs or self.is_quitting:
            return
        if self.file_dialog:
            self.file_dialog.raise_()
            self.file_dialog.activateWindow()
            return
        dialog = QFileDialog(self, "Отправить файлы администратору в Telegram")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setSidebarUrls([QUrl.fromLocalFile(QDir.homePath())] +
                              [QUrl.fromLocalFile(drive.absoluteFilePath()) for drive in QDir.drives()])
        dialog.filesSelected.connect(self.enqueue_files)
        def finished(_):
            self.file_dialog = None
            dialog.deleteLater()
        dialog.finished.connect(finished)
        self.file_dialog = dialog
        dialog.show()

    def enqueue_files(self, paths):
        if not paths or "file" in self.jobs or self.is_quitting:
            return
        token, admin = self.token.text().strip(), self.admin_id.text().strip()
        if not token or not admin.isascii() or not admin.isdigit() or int(admin) <= 0:
            self.switch_tab(3)
            self.settings_message.setText("Укажите токен и ID администратора для отправки файла.")
            return
        paths = list(paths)
        self.transfer_cancelling = False
        self.update_transfer_progress(dict(phase="preparing", total=len(paths), completed=0, index=0, name="", size=0, transferred=0, total_size=0, total_transferred=0, speed=0))
        if self.start_job("file", lambda: send_files_with_token(token, admin, paths, self.signals.transfer_progress.emit)):
            self.send_file_button.setEnabled(False)
            self.cancel_transfer_button.setEnabled(True)
            self.cancel_transfer_button.show()

    def cancel_transfer(self):
        job = self.jobs.get("file")
        if job:
            self.transfer_cancelling = True
            self.cancel_transfer_button.setEnabled(False)
            self.transfer_message.setText("Отмена отправки…")
            job.cancel()

    @Slot(object)
    def update_transfer_progress(self, state):
        self.transfer_state = state
        self.transfer_details.show()
        total, completed = state["total"], state["completed"]
        self.transfer_count.setText(f"Отправлено: {completed} из {total} · Осталось: {total - completed}")
        self.transfer_file.setText(f"Файл {state['index']} из {total}: {state['name']}" if state["name"] else "Подготовка файлов…")
        self.transfer_size.setText(f"Текущий файл: {format_bytes(state['transferred'])} / {format_bytes(state['size'])}\nВсего: {format_bytes(state['total_transferred'])} / {format_bytes(state['total_size'])}")
        self.transfer_speed.setText(f"Скорость: ≈ {format_bytes(state['speed'])}/с")
        self.file_progress.setValue(min(100, int(100 * state["transferred"] / state["size"])) if state["size"] else 0)
        self.batch_progress.setValue(min(100, int(100 * state["total_transferred"] / state["total_size"])) if state["total_size"] else 0)
        phase = state["phase"]
        messages = {"waiting": "Telegram просит подождать. Отправка продолжится автоматически…", "preparing": "Проверка размеров и доступности файлов…", "uploading": "Отправка…", "confirming": "Данные переданы. Ожидание подтверждения Telegram…", "sent": "Файл доставлен.", "completed": "Все файлы отправлены.", "cancelled": "Отправка отменена. Уже отправленные файлы остаются в Telegram.", "error": "Отправка остановлена из-за ошибки."}
        self.transfer_message.setText("Отмена отправки…" if self.transfer_cancelling and phase not in ("cancelled", "completed", "error") else messages.get(phase, "Обновление состояния отправки…"))
        active = state.get("active", [])
        if active:
            self.transfer_file.setText("Одновременно отправляется: " + str(len(active)) + "\n" + "\n".join(f"{item['name']}: {format_bytes(item['transferred'])} / {format_bytes(item['size'])}" for item in active))

    def refresh_metrics(self, force=False):
        self.refresh_status_hint()
        if force or (self.isVisible() and self.pages.currentIndex() == 0):
            self.start_job("metrics", lambda: asyncio.to_thread(computer_info))

    def copy_logs(self):
        QApplication.clipboard().setText(self.console.toPlainText())
        self.statusBar().showMessage("Логи скопированы", 3000)

    def load_settings(self):
        values = dotenv_values(Path(config.BASE_DIR) / ".env")
        self.token.setText(values.get("BOT_TOKEN") or "")
        self.admin_id.setText(values.get("ADMIN_ID") or "")

    def save_settings(self, checked=False, *, silent=False):
        token = self.token.text().strip()
        admin = self.admin_id.text().strip()
        if admin and (not admin.isascii() or not admin.isdigit() or int(admin) <= 0):
            self.settings_message.setText("ID администратора должен быть положительным целым числом.")
            return False
        values = {"BOT_TOKEN": token, "ADMIN_ID": admin}
        path = Path(config.BASE_DIR) / ".env"
        try:
            # Preserve unrelated settings and comments from the existing file.
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            output = []
            for line in lines:
                match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
                if not match or match[1] not in values:
                    output.append(line)
            for key, value in values.items():
                escaped = value.replace("\\", "\\\\").replace("'", "\\'")
                output.append(f"{key}='{escaped}'")
            atomic_write(path, "\n".join(output) + "\n")
            importlib.reload(config)
        except OSError as exc:
            self.settings_message.setText(f"Не удалось сохранить настройки: {exc}")
            return False
        if not silent:
            self.settings_message.setText("Настройки сохранены." + (" Перезапустите бота для применения токена." if self.bot_runner.is_running else ""))
            self.notify("Настройки сохранены.")
        return True

    def load_programs(self):
        path = Path(config.PROGRAMS_FILE_PATH)
        try:
            programs = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            validate_programs(programs)
            self.programs_valid = True
            self.temp_programs = programs
            for program in self.temp_programs:
                program.setdefault("id", uuid.uuid4().hex)
        except (OSError, ValueError) as exc:
            self.programs_valid = False
            self.program_message.setText(f"Не удалось прочитать programs.json: {exc}. Исправьте файл и перезапустите приложение.")
        self.refresh_programs()

    def refresh_programs(self):
        while self.program_list.count():
            item = self.program_list.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.program_count.setText(f"{len(self.temp_programs)} / 15")
        self.add_program_button.setEnabled(self.programs_valid and (self.edit_index is not None or len(self.temp_programs) < 15))
        self.save_programs_button.setEnabled(self.programs_valid and (self.programs_dirty or self.edit_index is not None))
        if not self.temp_programs:
            empty, inner = card()
            inner.addWidget(label("Пока нет программ", "heading", True))
            inner.addWidget(label("Выберите файл, добавьте программу и сохраните список.", "muted", True))
            self.program_list.addWidget(empty)
        for index, program in enumerate(self.temp_programs):
            item, inner = card("program")
            inner.addWidget(label(program["name"], "heading", True))
            if program.get("description"):
                inner.addWidget(label(str(program["description"]), "muted", True))
            path_label = QLineEdit(program["path"])
            path_label.setReadOnly(True)
            path_label.setAccessibleName("Путь к программе")
            path_label.setToolTip(program["path"])
            path_label.setCursorPosition(0)
            path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            path_label.setStyleSheet("QLineEdit { background: transparent; border: none; padding: 0; color: #8A97A8; }")
            inner.addWidget(path_label)
            actions = QGridLayout()
            actions.addWidget(button("Изменить", lambda checked=False, i=index: self.edit_program(i)), 0, 0)
            launch = button("Запустить", lambda checked=False, i=index: self.test_program(i))
            launch.setToolTip("Проверить запуск программы на этом ПК")
            actions.addWidget(launch, 0, 1)
            up = button("↑", lambda checked=False, i=index: self.move_program(i, -1))
            down = button("↓", lambda checked=False, i=index: self.move_program(i, 1))
            up.setToolTip("Переместить выше")
            down.setToolTip("Переместить ниже")
            up.setEnabled(index > 0)
            down.setEnabled(index < len(self.temp_programs) - 1)
            ordering = QHBoxLayout()
            ordering.addWidget(up)
            ordering.addWidget(down)
            actions.addLayout(ordering, 1, 0)
            actions.addWidget(button("Удалить", lambda checked=False, i=index: self.delete_program(i), "danger"), 1, 1)
            inner.addLayout(actions)
            self.program_list.addWidget(item)

    def browse_executable(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите программу", "", "Программы (*.exe *.lnk *.bat *.cmd);;Все файлы (*)")
        if path:
            self.program_path.setText(os.path.normpath(path))
            if not self.program_name.text().strip():
                self.program_name.setText(Path(path).stem)

    @staticmethod
    def program_process(path):
        return executable_process(path)

    def add_program(self):
        name = self.program_name.text().strip()
        path = self.program_path.text().strip().strip('"')
        if not self.programs_valid or (self.edit_index is None and len(self.temp_programs) >= 15):
            return False
        if not name or not path:
            self.program_message.setText("Укажите название и путь к программе.")
            return False
        if not Path(os.path.expandvars(path)).is_file():
            self.program_message.setText("Файл не найден. Проверьте путь к программе.")
            return False
        values = {"name": name, "path": path, "process": self.program_process(path), "description": self.program_description.text().strip()}
        if self.edit_index is None:
            self.temp_programs.append({**values, "id": uuid.uuid4().hex})
        else:
            self.temp_programs[self.edit_index].update(values)
        self.programs_dirty = True
        self.cancel_program_edit()
        self.program_message.setText("Есть несохранённые изменения. Нажмите «Сохранить список изменений».")
        return True

    def edit_program(self, index):
        if self.edit_index is not None:
            if index == self.edit_index:
                return
            if not self.add_program():
                return
        self.edit_index = index
        program = self.temp_programs[index]
        self.program_name.setText(program["name"])
        self.program_path.setText(program["path"])
        self.program_description.setText(str(program.get("description", "")))
        self.program_form_title.setText("Редактирование")
        self.add_program_button.setText("Применить изменения")
        self.add_program_button.setEnabled(True)
        self.cancel_edit_button.show()
        self.save_programs_button.setEnabled(True)
        self.pages.widget(1).verticalScrollBar().setValue(0)
        self.program_name.setFocus()

    def cancel_program_edit(self):
        self.edit_index = None
        self.program_form_title.setText("Новая программа")
        self.add_program_button.setText("Добавить программу")
        self.cancel_edit_button.hide()
        for field in (self.program_name, self.program_path, self.program_description):
            field.clear()
        self.refresh_programs()

    def move_program(self, index, offset):
        target = index + offset
        if not 0 <= target < len(self.temp_programs):
            return
        self.temp_programs[index], self.temp_programs[target] = self.temp_programs[target], self.temp_programs[index]
        if self.edit_index == index:
            self.edit_index = target
        elif self.edit_index == target:
            self.edit_index = index
        self.programs_dirty = True
        self.refresh_programs()
        self.program_message.setText("Порядок изменён. Сохраните список изменений.")

    def test_program(self, index):
        program = self.temp_programs[index]
        try:
            path = Path(os.path.expandvars(program["path"]))
            if not path.is_file():
                raise ValueError("Файл не найден. Измените путь к программе.")
            os.startfile(str(path.resolve()))
            self.notify(f"Запущена программа: {program['name']}")
        except (OSError, ValueError) as exc:
            self.program_message.setText(f"Ошибка запуска: {exc}")

    def delete_program(self, index):
        self.temp_programs.pop(index)
        if self.edit_index == index:
            self.cancel_program_edit()
        elif self.edit_index is not None and self.edit_index > index:
            self.edit_index -= 1
        self.programs_dirty = True
        self.refresh_programs()
        self.program_message.setText("Есть несохранённые изменения. Нажмите «Сохранить список изменений».")

    def save_programs(self):
        if not self.programs_valid:
            return False
        if self.edit_index is not None and not self.add_program():
            return False
        try:
            atomic_write(config.PROGRAMS_FILE_PATH, json.dumps(self.temp_programs, ensure_ascii=False, indent=2) + "\n")
        except OSError as exc:
            self.program_message.setText(f"Ошибка сохранения списка: {exc}")
            return False
        self.programs_dirty = False
        self.refresh_programs()
        self.program_message.setText("Список сохранён и доступен в Telegram.")
        self.notify("Список программ сохранён.")
        return True

    def toggle_bot_state(self):
        if self.state == "STOPPING" or self.is_quitting:
            return
        if self.bot_runner.is_running:
            self.update_bot_status("STOPPING")
            self.bot_runner.stop()
            return
        if not self.token.text().strip() or self.token.text().strip() == "your_telegram_bot_token_here" or not self.admin_id.text().strip():
            self.switch_tab(3)
            self.settings_message.setText("Для запуска укажите токен бота и ID администратора.")
            return
        if not self.save_settings(silent=True):
            self.switch_tab(3)
            return
        self.update_bot_status("STARTING")
        self.bot_runner.start()

    def auto_start_bot(self):
        if self.token.text().strip() not in ("", "your_telegram_bot_token_here") and self.admin_id.text().strip():
            self.toggle_bot_state()

    @Slot(str)
    def update_bot_status(self, status):
        self.state = status
        text = {"STOPPED": "Остановлен", "STARTING": "Подключение…", "RECONNECTING": "Нет связи — переподключение…", "RUNNING": "Запущен", "STOPPING": "Остановка…"}[status]
        running = status == "RUNNING"
        active = status in ("STARTING", "RUNNING", "RECONNECTING")
        busy = status == "STOPPING"
        connection_text = {"STOPPED": "Не подключён", "STARTING": "Подключение", "RECONNECTING": "Нет связи", "RUNNING": "Telegram подключён", "STOPPING": "Отключение"}[status]
        self.connection.setText("●  " + connection_text)
        color = "#19C3FF" if running else ("#f3c77c" if active or busy else "#8A97A8")
        self.connection.setStyleSheet(f"color: {color};")
        self.refresh_status_hint()
        self.toggle_button.setText(text if busy else ("Остановить" if active else "Запустить"))
        self.toggle_button.setProperty("kind", "stop" if active else "primary")
        self.toggle_button.setIcon(icon("stop" if active else "play", "#FFB3C0" if active else "#03101F"))
        self.toggle_button.setEnabled(not busy and not self.is_quitting)
        self.toggle_button.style().unpolish(self.toggle_button)
        self.toggle_button.style().polish(self.toggle_button)
        self.setWindowTitle(f"Pulse PC — {text}")
        if self.tray_icon:
            self.tray_icon.setToolTip(f"Pulse PC — {text}")
            self.tray_status.setText(f"Статус: {text}")
            self.tray_toggle.setText("Остановить бота" if active else "Запустить бота")
            self.tray_toggle.setEnabled(not busy and not self.is_quitting)

    @Slot()
    def restart_bot(self):
        if self.is_quitting:
            return
        if self.bot_runner.thread and self.bot_runner.thread.is_alive():
            QTimer.singleShot(100, self.restart_bot)
        else:
            self.toggle_bot_state()

    def check_autostart(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                for name in ("PulsePC", "PulsePC_Bot"):
                    try:
                        winreg.QueryValueEx(key, name)
                        return True
                    except FileNotFoundError:
                        pass
            return False
        except OSError:
            return False

    def change_autostart(self, enable):
        executable = Path(sys.executable)
        if not getattr(sys, "frozen", False):
            windowless = executable.with_name("pythonw.exe")
            if windowless.exists():
                executable = windowless
            command = f'"{executable}" "{Path(__file__).resolve()}" --minimized'
        else:
            command = f'"{executable}" --minimized'
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                if enable:
                    winreg.SetValueEx(key, "PulsePC", 0, winreg.REG_SZ, command)
                for name in (("PulsePC_Bot",) if enable else ("PulsePC", "PulsePC_Bot")):
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            self.autostart.blockSignals(True)
            self.autostart.setChecked(self.check_autostart())
            self.autostart.blockSignals(False)
            self.notify(f"Ошибка изменения автозагрузки: {exc}")
            return
        self.notify("Автозагрузка " + ("включена." if enable else "отключена."))

    def setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu(self)
        self.tray_status = menu.addAction("Статус: Остановлен")
        self.tray_status.setEnabled(False)
        self.tray_toggle = menu.addAction("Запустить бота", self.toggle_bot_state)
        menu.addSeparator()
        menu.addAction("Открыть панель", self.show_window)
        menu.addAction("Выход", self.quit_app)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.messageClicked.connect(self.show_window)
        self.tray_icon.show()

    def show_startup_notification(self):
        if self.is_quitting:
            return
        if self.tray_icon and QSystemTrayIcon.supportsMessages():
            self.tray_icon.showMessage(
                "Pulse PC запущен",
                "Приложение работает. Нажмите на уведомление, чтобы открыть панель управления.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
        else:
            self.statusBar().showMessage("Pulse PC запущен", 5000)

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        if self.tray_icon and not self.is_quitting:
            self.hide()
        else:
            self.quit_app()

    @Slot()
    def quit_app(self):
        if self.is_quitting:
            return
        if self.programs_dirty or self.edit_index is not None:
            answer = QMessageBox.question(self, "Несохранённые программы", "Сохранить изменения списка перед выходом?", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save and not self.save_programs():
                self.show_window()
                self.switch_tab(1)
                return
        self.is_quitting = True
        if self.file_dialog:
            self.file_dialog.reject()
        self.metrics_timer.stop()
        for job in self.jobs.values():
            job.cancel()
        self.toggle_button.setEnabled(False)
        self.bot_runner.stop()
        self._finish_quit()

    def _finish_quit(self):
        if (self.bot_runner.thread and self.bot_runner.thread.is_alive()) or any(job.thread.is_alive() for job in self.jobs.values()):
            QTimer.singleShot(50, self._finish_quit)
            return
        if self.tray_icon:
            self.tray_icon.hide()
        logging.getLogger().removeHandler(self.log_handler)
        if self.journal:
            self.journal.close()
        QApplication.instance().quit()


_lock_handles = []


def acquire_gui_lock():
    import msvcrt
    acquired = []
    try:
        for filename in ("gui.lock", "bot.lock"):
            stream = open(Path(config.BASE_DIR) / filename, "a+b")
            acquired.append(stream)
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        for stream in acquired:
            stream.close()
        return False
    _lock_handles.extend(acquired)
    return True


def main():
    application = QApplication(sys.argv)
    application.setApplicationName("Pulse PC")
    application.setQuitOnLastWindowClosed(False)
    if not acquire_gui_lock():
        QMessageBox.information(None, "Pulse PC", "Панель управления уже запущена. Откройте её через значок в системном трее.")
        return 0
    logging.basicConfig(level=logging.INFO)
    window = PulsePCApp()
    if not ({"--minimized", "-m"} & set(sys.argv)) or not window.tray_icon:
        window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
