from PySide6.QtCore import Qt, Signal, QPoint, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QMouseEvent, QPalette, QColor, QPainter, QPainterPath, QBrush, QPen, QTextOption, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QApplication, QTextEdit, QFrame, QGraphicsDropShadowEffect,
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
            p.setPen(QColor(255, 255, 255, 60))
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

        # Glow ring when recording
        if self._recording and self._ring_opacity > 0.01:
            ring_r = min(w, h) / 2 + 6
            gradient = QPainter()
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(124, 143, 255, int(self._ring_opacity * 60))))
            p.drawEllipse(QPoint(int(cx), int(cy)), int(ring_r), int(ring_r))

        # Button circle
        if self._recording:
            bg = QColor("#2a2a35")
            border_color = QColor("#FF6B6B")
        else:
            bg = QColor("#323240")
            border_color = QColor(255, 255, 255, 25)

        if self.underMouse() and not self._recording:
            bg = QColor("#3d3d50")

        p.setPen(QPen(border_color, 1.5))
        p.setBrush(QBrush(bg))
        r = min(w, h) / 2 - 3
        p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))

        # Icon
        p.setPen(Qt.NoPen)
        icon_color = QColor("#e0e0e0" if not self._recording else "#FF6B6B")
        p.setBrush(QBrush(icon_color))

        if self._recording:
            # Stop square
            sq = 12
            p.drawRoundedRect(int(cx - sq / 2), int(cy - sq / 2), sq, sq, 3, 3)
        else:
            # Microphone: vertical capsule > narrow neck > handle
            path = QPainterPath()
            cap_w, cap_h = 9, 14
            hdl_w, hdl_h = 4, 9
            top = cy - 9
            mid_y = top + cap_h
            bot_y = mid_y + hdl_h
            r = 3

            # Top capsule
            path.moveTo(cx - cap_w / 2, top + r)
            path.arcTo(cx - cap_w / 2, top, cap_w, r * 2, 180, -180)
            path.lineTo(cx + cap_w / 2, mid_y - r)
            # Right neck curve — bulge outward
            path.quadTo(cx + cap_w / 2 + 2, mid_y, cx + hdl_w / 2, mid_y)
            path.lineTo(cx + hdl_w / 2, bot_y - r)
            path.arcTo(cx - hdl_w / 2, bot_y - r * 2, hdl_w, r * 2, 0, -180)
            path.lineTo(cx - hdl_w / 2, mid_y)
            # Left neck curve — bulge outward
            path.quadTo(cx - cap_w / 2 - 2, mid_y, cx - cap_w / 2, mid_y - r)
            path.closeSubpath()

            p.drawPath(path)

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
            color = "#555560"
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


class FloatingCardWindow(QWidget):
    mic_clicked = Signal()
    closed = Signal()

    def __init__(self, hotkey: str = "F2", is_tap_mode: bool = True):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(360, 160)
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
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)

        self._card = QWidget(self)
        self._card.setObjectName("card")
        self._card.setGraphicsEffect(shadow)
        self._card.setStyleSheet("""
            #card {
                background: rgba(24, 24, 32, 0.96);
                border-radius: 14px;
                border: 1px solid rgba(255, 255, 255, 0.06);
            }
        """)
        outer.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(8)

        # Header row: label + recording dot
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self._title_label = QLabel("VoiceInput")
        self._title_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 0.35);
                font-size: 11px;
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
        """)

        self._status_dot = _RecordingDot()

        header.addWidget(self._title_label)
        header.addStretch()
        header.addWidget(self._status_dot, alignment=Qt.AlignVCenter)
        layout.addLayout(header)

        # Text area
        self._text_edit = _PlaceholderTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFixedHeight(32)
        self._text_edit.setFrameShape(QFrame.NoFrame)
        self._text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text_edit.setAutoFillBackground(False)
        self._text_edit.viewport().setAutoFillBackground(False)
        pal = self._text_edit.palette()
        pal.setColor(QPalette.Base, Qt.transparent)
        pal.setColor(QPalette.Window, Qt.transparent)
        self._text_edit.setPalette(pal)
        layout.addWidget(self._text_edit)

        layout.addStretch()

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 2, 0)
        bottom.setSpacing(8)
        bottom.addStretch()

        self._mic_btn = _MicButton()
        self._mic_btn.clicked.connect(self.mic_clicked.emit)
        bottom.addWidget(self._mic_btn, alignment=Qt.AlignVCenter)

        layout.addLayout(bottom)

        self._apply_text_style("normal")
        self._update_placeholder()

    def _apply_text_style(self, mode: str):
        color = "#FF6B6B" if mode == "error" else "#d4d4dc"
        self._text_edit.setStyleSheet(f"""
            QTextEdit {{
                color: {color};
                font-size: 15px;
                font-weight: 350;
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Microsoft YaHei', sans-serif;
                background: transparent;
                padding: 2px 0;
                border: none;
                selection-background-color: rgba(124, 143, 255, 0.3);
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
            self._status_dot.start_pulse()
            self._card.setStyleSheet("""
                #card {
                    background: rgba(24, 24, 32, 0.96);
                    border-radius: 14px;
                    border: 1px solid rgba(124, 143, 255, 0.18);
                }
            """)
        else:
            self._status_dot.stop_pulse()
            self._card.setStyleSheet("""
                #card {
                    background: rgba(24, 24, 32, 0.96);
                    border-radius: 14px;
                    border: 1px solid rgba(255, 255, 255, 0.06);
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
