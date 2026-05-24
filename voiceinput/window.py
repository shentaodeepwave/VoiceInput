from PySide6.QtCore import Qt, Signal, QPoint, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsOpacityEffect, QApplication,
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

        self._drag_pos: QPoint | None = None
        self._recording = False
        self._hotkey_label = hotkey_label

        # Opacity effect for fade animation
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        # Animations
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(250)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._pulse_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_phase = False

        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget(self)
        self._card.setObjectName("card")
        self._card.setStyleSheet("""
            #card {
                background: rgba(20, 20, 20, 0.92);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.06);
            }
        """)
        outer.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        # Text area
        self._text_label = QLabel("")
        self._text_label.setWordWrap(True)
        self._text_label.setMinimumHeight(60)
        self._text_label.setMaximumHeight(120)
        self._text_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._text_label.setStyleSheet(
            "color: #ccc; font-size: 14px; "
            "font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; "
            "padding: 4px 0; line-height: 1.5;"
        )
        self._text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._text_label)

        layout.addStretch()

        # Bottom bar: mic button right-aligned
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addStretch()

        self._mic_btn = QPushButton()
        self._mic_btn.setFixedSize(48, 48)
        self._mic_btn.setCursor(Qt.PointingHandCursor)
        self._mic_btn.clicked.connect(self.mic_clicked.emit)

        # Mic button opacity effect for pulse
        self._mic_opacity = QGraphicsOpacityEffect(self._mic_btn)
        self._mic_opacity.setOpacity(1.0)
        self._mic_btn.setGraphicsEffect(self._mic_opacity)

        self._apply_mic_style(False)
        bottom.addWidget(self._mic_btn)

        layout.addLayout(bottom)

        # Mic pulse animation
        self._mic_pulse = QPropertyAnimation(self._mic_opacity, b"opacity")
        self._mic_pulse.setDuration(600)
        self._mic_pulse.setEasingCurve(QEasingCurve.InOutSine)

    def _apply_mic_style(self, recording: bool):
        if recording:
            bg = "#F44336"
            text = "⏹"
        else:
            bg = "#4CAF50"
            text = "🎤"

        self._mic_btn.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                border-radius: 24px;
                border: none;
                color: white;
                font-size: 18px;
            }}
            QPushButton:hover {{
                background: {bg};
            }}
        """)
        self._mic_btn.setText(text)

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
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self.hide)
        self._fade_anim.start()

    def set_text(self, text: str):
        self._text_label.setText(text)

    def set_hotkey_label(self, key: str):
        self._hotkey_label = key

    def set_recording(self, on: bool):
        self._recording = on
        self._apply_mic_style(on)
        if on:
            self._start_mic_pulse()
        else:
            self._stop_mic_pulse()

    def set_error(self, text: str):
        self._text_label.setStyleSheet(
            "color: #F44336; font-size: 14px; "
            "font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; "
            "padding: 4px 0; line-height: 1.5;"
        )
        self._text_label.setText(text)

    def clear_error(self):
        self._text_label.setStyleSheet(
            "color: #ccc; font-size: 14px; "
            "font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; "
            "padding: 4px 0; line-height: 1.5;"
        )

    # ── Mic pulse ───────────────────────────────────────────────
    def _start_mic_pulse(self):
        self._pulse_phase = False
        self._mic_pulse.finished.disconnect(self._pulse_tick)
        self._mic_pulse.finished.connect(self._pulse_tick)
        self._pulse_tick()

    def _stop_mic_pulse(self):
        self._mic_pulse.stop()
        self._mic_opacity.setOpacity(1.0)

    def _pulse_tick(self):
        if not self._recording:
            self._stop_mic_pulse()
            return
        self._pulse_phase = not self._pulse_phase
        self._mic_pulse.stop()
        self._mic_pulse.setStartValue(1.0 if self._pulse_phase else 0.55)
        self._mic_pulse.setEndValue(0.55 if self._pulse_phase else 1.0)
        self._mic_pulse.start()

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
        self._stop_mic_pulse()
        self.closed.emit()
        super().closeEvent(e)
