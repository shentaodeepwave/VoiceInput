from PySide6.QtCore import Qt, Signal, QPoint, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QMouseEvent, QPalette
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QApplication, QTextEdit, QFrame,
)


class FloatingCardWindow(QWidget):
    mic_clicked = Signal()
    closed = Signal()

    def __init__(self, hotkey_label: str = "F2"):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(400, 250)
        self.setWindowOpacity(0.0)

        self._drag_pos: QPoint | None = None
        self._recording = False
        self._hotkey_label = hotkey_label

        # Fade animation uses native windowOpacity (no graphics effect → no black block)
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(300)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget(self)
        self._card.setObjectName("card")
        self._card.setStyleSheet("""
            #card {
                background: rgba(32, 32, 32, 0.94);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.07);
            }
        """)
        outer.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(0)

        # Text area — QTextEdit with transparent viewport
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFixedHeight(64)
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

        # Bottom bar: status dot + mic button, right-aligned
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 4, 0)
        bottom.setSpacing(12)
        bottom.addStretch()

        # Recording indicator dot
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(10, 10)
        self._status_dot.setStyleSheet("""
            QLabel {
                background: #555555;
                border-radius: 5px;
            }
        """)
        bottom.addWidget(self._status_dot, alignment=Qt.AlignVCenter)

        # Mic button
        self._mic_btn = QPushButton()
        self._mic_btn.setFixedSize(44, 44)
        self._mic_btn.setCursor(Qt.PointingHandCursor)
        self._mic_btn.clicked.connect(self.mic_clicked.emit)
        self._apply_mic_style(False)
        bottom.addWidget(self._mic_btn, alignment=Qt.AlignVCenter)

        layout.addLayout(bottom)

        self._apply_text_style("normal")

        # Dot pulse timer
        self._dot_pulse_timer = QTimer(self)
        self._dot_pulse_timer.timeout.connect(self._dot_tick)
        self._dot_phase = False

    def _apply_text_style(self, mode: str):
        color = "#F44336" if mode == "error" else "#e4e4e4"
        self._text_edit.setStyleSheet(f"""
            QTextEdit {{
                color: {color};
                font-size: 14px;
                font-family: 'Segoe UI Variable', 'Segoe UI', 'Microsoft YaHei', sans-serif;
                background: transparent;
                padding: 4px 0;
                border: none;
                selection-background-color: rgba(96, 205, 255, 0.4);
            }}
        """)

    def _apply_mic_style(self, recording: bool):
        if recording:
            bg = "#202020"
            icon = "⏹"  # stop square
            border = "1px solid #555555"
        else:
            bg = "#3a3a3a"
            icon = "\U0001F3A4"  # mic
            border = "1px solid transparent"

        self._mic_btn.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                border-radius: 22px;
                border: {border};
                color: #cccccc;
                font-size: 17px;
            }}
            QPushButton:hover {{
                background: {bg};
                border-color: #777777;
            }}
        """)
        self._mic_btn.setText(icon)

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
        cursor.movePosition(cursor.End)
        self._text_edit.setTextCursor(cursor)

    def set_hotkey_label(self, key: str):
        self._hotkey_label = key

    def set_recording(self, on: bool):
        self._recording = on
        self._apply_mic_style(on)
        if on:
            self._start_dot_pulse()
        else:
            self._stop_dot_pulse()

    def set_error(self, text: str):
        self._apply_text_style("error")
        self._text_edit.setPlainText(text)

    def clear_error(self):
        self._apply_text_style("normal")

    # ── Status dot pulse ────────────────────────────────────────
    def _start_dot_pulse(self):
        self._status_dot.setStyleSheet("""
            QLabel {
                background: #FF4444;
                border-radius: 5px;
            }
        """)
        self._dot_phase = False
        self._dot_pulse_timer.start(800)

    def _stop_dot_pulse(self):
        self._dot_pulse_timer.stop()
        self._status_dot.setStyleSheet("""
            QLabel {
                background: #555555;
                border-radius: 5px;
            }
        """)

    def _dot_tick(self):
        if not self._recording:
            self._stop_dot_pulse()
            return
        self._dot_phase = not self._dot_phase
        if self._dot_phase:
            self._status_dot.setStyleSheet("""
                QLabel {
                    background: #FF4444;
                    border-radius: 5px;
                }
            """)
        else:
            self._status_dot.setStyleSheet("""
                QLabel {
                    background: rgba(255, 68, 68, 0.2);
                    border-radius: 5px;
                }
            """)

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
        self._stop_dot_pulse()
        self.closed.emit()
        super().closeEvent(e)
