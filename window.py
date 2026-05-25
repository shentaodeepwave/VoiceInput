from PySide6.QtCore import Qt, Signal, QPoint, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QMouseEvent, QPalette, QColor, QPainter, QBrush, QPen, QTextOption, QTextCursor, QFontMetrics, QLinearGradient, QRadialGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QApplication, QTextEdit, QFrame, QGraphicsDropShadowEffect, QSizePolicy,
    QScrollArea, QSpacerItem,
)


class _PlaceholderTextEdit(QTextEdit):
    """QTextEdit with placeholder text support."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._placeholder = ""

    def setPlaceholderText(self, text: str):
        self._placeholder = text
        self.viewport().update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._placeholder and not self.toPlainText():
            p = QPainter(self.viewport())
            p.setPen(QColor(0, 0, 0, 60))
            p.setFont(self.font())
            option = QTextOption()
            option.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            p.drawText(self.viewport().rect().adjusted(4, 4, 0, 0), self._placeholder, option)
            p.end()


class _MicButton(QPushButton):
    """Circular mic button with glowing ring animation when recording."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self._recording = False
        self._ring_opacity = 0.0
        self._ring_timer = QTimer(self)
        self._ring_timer.timeout.connect(self._ring_tick)
        self._ring_expanding = True

    def set_recording(self, on: bool):
        self._recording = on
        if on:
            self._ring_opacity = 0.3
            self._ring_expanding = True
            self._ring_timer.start(40)
        else:
            self._ring_timer.stop()
            self._ring_opacity = 0.0
        self.update()

    def _ring_tick(self):
        step = 0.015
        if self._ring_expanding:
            self._ring_opacity += step
            if self._ring_opacity >= 0.65:
                self._ring_expanding = False
        else:
            self._ring_opacity -= step
            if self._ring_opacity <= 0.25:
                self._ring_expanding = True
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 3

        # Outer glow ring when recording
        if self._recording and self._ring_opacity > 0.01:
            outer_r = r + 10
            glow = QRadialGradient(cx, cy, outer_r)
            glow.setColorAt(0.7, QColor(255, 107, 107, int(self._ring_opacity * 40)))
            glow.setColorAt(1.0, QColor(255, 107, 107, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(glow))
            p.drawEllipse(QPoint(int(cx), int(cy)), int(outer_r), int(outer_r))

        # Button circle with gradient
        if self._recording:
            grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
            grad.setColorAt(0, QColor("#ff6b6b"))
            grad.setColorAt(1, QColor("#ee5a24"))
            border_color = QColor("#e53e3e")
        else:
            grad = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
            grad.setColorAt(0, QColor("#10b981"))
            grad.setColorAt(1, QColor("#059669"))
            border_color = QColor(16, 185, 129, 50)

        if self.underMouse() and not self._recording:
            grad.setColorAt(0, QColor("#34d399"))
            grad.setColorAt(1, QColor("#10b981"))

        p.setPen(QPen(border_color, 1.5))
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))

        # Icon — always white on gradient
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#ffffff")))
        if self._recording:
            sq = 11
            p.drawRoundedRect(int(cx - sq / 2), int(cy - sq / 2), sq, sq, 3, 3)
        else:
            p.drawEllipse(QPoint(int(cx), int(cy)), 7, 7)

        p.end()


class _RecordingDot(QLabel):
    """Pulsing recording indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self._phase = False
        self._active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._update_style()

    def start_pulse(self):
        self._active = True
        self._phase = False
        self._update_style()
        self._timer.start(700)

    def stop_pulse(self):
        self._active = False
        self._timer.stop()
        self._update_style()

    def _tick(self):
        self._phase = not self._phase
        self._update_style()

    def _update_style(self):
        if not self._active:
            color = "#d0d0d5"
        elif self._phase:
            color = "#FF6B6B"
        else:
            color = "rgba(255, 107, 107, 0.25)"
        self.setStyleSheet(f"""
            QLabel {{
                background: {color};
                border-radius: 4px;
            }}
        """)


class _HistoryButton(QPushButton):
    """Clock icon button for toggling history panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
            }
            QPushButton:hover {
                background: rgba(0, 0, 0, 0.04);
                border-radius: 6px;
            }
        """)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        p.setPen(QPen(QColor(160, 160, 170, 180), 1.2))
        p.setBrush(Qt.NoBrush)
        r = 7
        p.drawEllipse(QPoint(int(cx), int(cy)), r, r)
        p.setPen(QPen(QColor(140, 140, 150, 200), 1.2))
        p.drawLine(int(cx), int(cy), int(cx), int(cy - 4))
        p.drawLine(int(cx), int(cy), int(cx + 3.5), int(cy - 1))
        p.end()


class _HistoryBubble(QFrame):

    def __init__(self, text: str, index: int, parent=None):
        super().__init__(parent)
        self._index = index
        self.setObjectName("bubble")
        self.setStyleSheet("""
            #bubble {
                background: rgba(0, 0, 0, 0.03);
                border-radius: 8px;
                border: 1px solid rgba(0, 0, 0, 0.05);
            }
        """)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(8)

        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setStyleSheet("""
            QLabel {
                color: #3d4048;
                font-size: 13px;
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Microsoft YaHei', sans-serif;
                background: transparent;
                border: none;
            }
        """)
        layout.addWidget(self._label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        actions.addStretch()

        copy_btn = QPushButton()
        copy_btn.setFixedSize(22, 22)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setToolTip("复制")
        copy_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                color: rgba(0,0,0,0.3);
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(0, 0, 0, 0.06);
                color: rgba(0,0,0,0.6);
            }
        """)
        copy_btn.clicked.connect(self._on_copy)
        copy_btn.setText("⎘")
        actions.addWidget(copy_btn)

        del_btn = QPushButton()
        del_btn.setFixedSize(22, 22)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setToolTip("删除")
        del_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                color: rgba(0,0,0,0.2);
                font-size: 10px;
            }
            QPushButton:hover {
                background: rgba(255, 80, 80, 0.1);
                color: #e53e3e;
            }
        """)
        del_btn.clicked.connect(self._on_delete)
        del_btn.setText("✕")
        actions.addWidget(del_btn)

        layout.addLayout(actions)

    def _on_copy(self):
        w = self.window()
        if hasattr(w, 'history_copy'):
            w.history_copy.emit(self._label.text())

    def _on_delete(self):
        w = self.window()
        if hasattr(w, 'history_delete'):
            w.history_delete.emit(self._index)


class _HistoryPanel(QScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("history_panel")
        self.setStyleSheet("""
            #history_panel {
                background: transparent;
                border: none;
            }
        """)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMaximumHeight(260)
        self.setVisible(False)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        self._empty_label = QLabel("暂无记录")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("""
            QLabel {
                color: rgba(0, 0, 0, 0.2);
                font-size: 12px;
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Microsoft YaHei', sans-serif;
                padding: 16px 0;
            }
        """)
        self._empty_label.setVisible(False)
        self._layout.addWidget(self._empty_label)
        self._layout.addStretch()
        self.setWidget(container)

        self.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                background: transparent;
                width: 4px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 0, 0, 0.1);
                border-radius: 2px;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

    def set_records(self, records: list[str]):
        while self._layout.count() > 2:
            item = self._layout.takeAt(0)
            if item.widget() and item.widget() is not self._empty_label:
                item.widget().deleteLater()
            del item

        if not records:
            self._empty_label.setVisible(True)
        else:
            self._empty_label.setVisible(False)
            for i, text in enumerate(records):
                bubble = _HistoryBubble(text, i)
                self._layout.insertWidget(self._layout.count() - 2, bubble)

        self.setVisible(True)

    def remove_record(self, index: int):
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), _HistoryBubble):
                bubble = item.widget()
                if bubble._index == index:
                    self._layout.takeAt(i)
                    bubble.deleteLater()
                    del item
                    break

        if self._layout.count() <= 2:
            self._empty_label.setVisible(True)


class FloatingCardWindow(QWidget):
    mic_clicked = Signal()
    closed = Signal()
    history_toggled = Signal()
    history_copy = Signal(str)
    history_delete = Signal(int)

    def __init__(self, hotkey: str = "F2", is_tap_mode: bool = True):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumSize(360, 160)
        self.setMaximumSize(360, 500)
        self.resize(360, 160)
        self.setWindowOpacity(0.0)

        self._drag_pos: QPoint | None = None
        self._recording = False
        self._hotkey = hotkey
        self._is_tap_mode = is_tap_mode

        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(250)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 40))
        shadow.setOffset(0, 2)

        self._card = QWidget(self)
        self._card.setObjectName("card")
        self._card.setGraphicsEffect(shadow)
        self._card.setStyleSheet("""
            #card {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #faf9f7, stop:0.5 #f5f2ee, stop:1 #faf9f7);
                border-radius: 14px;
                border: 1px solid rgba(0, 0, 0, 0.06);
            }
        """)
        outer.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(8)

        # Header row: label + history button
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self._title_label = QLabel("VoiceInput")
        self._title_label.setStyleSheet("""
            QLabel {
                color: rgba(0, 0, 0, 0.35);
                font-size: 11px;
                font-weight: 500;
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
        """)

        self._history_btn = _HistoryButton()
        self._history_btn.clicked.connect(self.history_toggled.emit)

        header.addWidget(self._title_label)
        header.addStretch()
        header.addWidget(self._history_btn, alignment=Qt.AlignVCenter)
        layout.addLayout(header)

        # Text area
        self._text_edit = _PlaceholderTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setMinimumHeight(24)
        self._text_edit.setMaximumHeight(140)
        self._text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._text_edit.setFrameShape(QFrame.NoFrame)
        self._text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_edit.setAutoFillBackground(False)
        self._text_edit.viewport().setAutoFillBackground(False)
        pal = self._text_edit.palette()
        pal.setColor(QPalette.Base, Qt.transparent)
        pal.setColor(QPalette.Window, Qt.transparent)
        self._text_edit.setPalette(pal)
        layout.addWidget(self._text_edit)

        # History panel
        self._history_panel = _HistoryPanel(self._card)
        layout.addWidget(self._history_panel)

        layout.addStretch()

        # Bottom bar: status dot + mic button
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 2, 0)
        bottom.setSpacing(10)
        bottom.addStretch()

        self._status_dot = _RecordingDot()
        bottom.addWidget(self._status_dot, alignment=Qt.AlignVCenter)

        self._mic_btn = _MicButton()
        self._mic_btn.clicked.connect(self.mic_clicked.emit)
        bottom.addWidget(self._mic_btn, alignment=Qt.AlignVCenter)

        layout.addLayout(bottom)

        self._apply_text_style("normal")
        self._update_placeholder()

    def _apply_text_style(self, mode: str):
        color = "#e53e3e" if mode == "error" else "#2d3748"
        self._text_edit.setStyleSheet(f"""
            QTextEdit {{
                color: {color};
                font-size: 15px;
                font-weight: 400;
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Microsoft YaHei', sans-serif;
                background: transparent;
                padding: 2px 0;
                border: none;
                selection-background-color: rgba(16, 185, 129, 0.25);
            }}
        """)

    # ── Public API ──────────────────────────────────────────────
    def show_with_fade(self):
        self.show()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def hide_with_fade(self):
        self._fade_anim.stop()
        try:
            self._fade_anim.finished.disconnect(self.hide)
        except Exception:
            pass
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self.hide)
        self._fade_anim.start()

    def set_text(self, text: str):
        self._text_edit.setPlainText(text)
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._text_edit.setTextCursor(cursor)
        self._adjust_height()

    def _adjust_height(self):
        if not self._text_edit.toPlainText() and not self._history_panel.isVisible():
            self.resize(360, 160)
            return

        text = self._text_edit.toPlainText()
        available_w = max(self._text_edit.viewport().width(), 1)
        fm = QFontMetrics(self._text_edit.font())
        br = fm.boundingRect(0, 0, available_w, 0, Qt.TextWordWrap, text)
        text_h = max(24, min(br.height() + 8, 140))
        self._text_edit.setFixedHeight(text_h)

        history_h = self._history_panel.height() if self._history_panel.isVisible() else 0

        window_h = text_h + history_h + 28 + 20 + 44 + 16
        max_h = 500 if self._history_panel.isVisible() else 300
        window_h = max(160, min(window_h, max_h))
        self.resize(360, window_h)

    def show_history(self, records: list[str]):
        self._history_panel.set_records(records)
        self._history_panel.widget().adjustSize()
        if records:
            history_h = min(self._history_panel.widget().sizeHint().height(), 260)
        else:
            history_h = self._history_panel._empty_label.sizeHint().height() + 12
        self._history_panel.setFixedHeight(history_h)
        self._adjust_height()

    def hide_history(self):
        self._history_panel.setVisible(False)
        self._history_panel.setFixedHeight(0)
        self._adjust_height()

    def remove_history_record(self, index: int):
        self._history_panel.remove_record(index)
        self._adjust_height()

    def set_placeholder(self, hotkey: str, is_tap_mode: bool):
        self._hotkey = hotkey
        self._is_tap_mode = is_tap_mode
        self._update_placeholder()

    def _update_placeholder(self):
        action = "\u70B9\u6309" if self._is_tap_mode else "\u6309\u4F4F"
        self._text_edit.setPlaceholderText(
            f"{action} {self._hotkey} \u5F00\u59CB\u5F55\u97F3"
        )

    def set_recording(self, on: bool):
        self._recording = on
        self._mic_btn.set_recording(on)
        if on:
            self._history_panel.setVisible(False)
            self._history_panel.setFixedHeight(0)
            self._status_dot.start_pulse()
            self._card.setStyleSheet("""
                #card {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #fff5f5, stop:0.5 #ffe8e8, stop:1 #fff5f5);
                    border-radius: 14px;
                    border: 1px solid rgba(229, 62, 62, 0.2);
                }
            """)
        else:
            self._status_dot.stop_pulse()
            self._card.setStyleSheet("""
                #card {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #faf9f7, stop:0.5 #f5f2ee, stop:1 #faf9f7);
                    border-radius: 14px;
                    border: 1px solid rgba(0, 0, 0, 0.06);
                }
            """)

    def set_error(self, text: str):
        self._apply_text_style("error")
        self._text_edit.setPlainText(text)

    def clear_error(self):
        self._apply_text_style("normal")

    # ── Drag ────────────────────────────────────────────────────
    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drag_pos is not None:
            delta = e.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = e.globalPosition().toPoint()

    def mouseReleaseEvent(self, e: QMouseEvent):
        self._drag_pos = None

    def closeEvent(self, e):
        self._status_dot.stop_pulse()
        self.closed.emit()
        super().closeEvent(e)
