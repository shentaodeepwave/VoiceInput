"""VoiceInput GUI — 浮窗 + 系统托盘语音输入法."""
import ctypes
from ctypes import wintypes
import signal
import sys
import time
import threading
from pathlib import Path

import pyperclip
import keyboard as kb
from pynput.keyboard import Controller as KbController, Key as KbKey
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPoint
from PySide6.QtGui import QPainter, QColor, QBrush, QPixmap, QIcon, QMouseEvent, QCursor
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget,
    QVBoxLayout, QLabel, QHBoxLayout,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox,
)

from audio_capture import AudioRecorder
from asr_engine import ASREngine, load_config

HOTKEY = "right ctrl"
HOTKEY_NAME = "右 Ctrl"


def get_caret_screen_pos():
    """Return (x, y) screen coordinates of the text cursor, or None."""
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
        rc = info.rcCaret
        if rc.left != 0 or rc.top != 0:
            pt = wintypes.POINT(rc.left, rc.bottom)
            ctypes.windll.user32.ClientToScreen(
                info.hwndCaret or hwnd, ctypes.byref(pt)
            )
            return pt.x, pt.y
    return None


# ── tray icon ────────────────────────────────────────────────────
def _make_tray_icon(recording: bool = False) -> QIcon:
    px = QPixmap(32, 32)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor("#ff4444") if recording else QColor("#cccccc")
    p.setBrush(QBrush(c))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPoint(16, 16), 8, 8)
    p.end()
    return QIcon(px)


# ── bridge ─────────────────────────────────────────────────────────
class SpeechBridge(QObject):
    partial = Signal(str)
    final = Signal(str)
    error = Signal(str)
    toggle = Signal()
    do_type = Signal()


# ── floating overlay ───────────────────────────────────────────────
class FloatingWindow(QWidget):
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self._drag_pos: QPoint | None = None
        self._setup_ui()
        self.place_near_cursor()

    def _setup_ui(self):
        self.setFixedWidth(620)
        self.setMinimumHeight(100)
        self._container = QWidget(self)
        self._container.setObjectName("c")
        self._container.setStyleSheet("""
            #c {
                background: rgba(24, 24, 24, 0.94);
                border-radius: 14px;
                border: 1px solid rgba(255,255,255,0.08);
            }
        """)
        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(22, 14, 22, 14)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        self._dot = QLabel("⬤")
        self._dot.setStyleSheet("color: #ff4444; font-size: 10px;")
        self._status = QLabel("正在录音...")
        self._status.setStyleSheet("color: #999; font-size: 12px;")
        self._dur = QLabel("00:00")
        self._dur.setStyleSheet("color: #555; font-size: 12px;")
        hdr.addWidget(self._dot)
        hdr.addWidget(self._status)
        hdr.addStretch()
        hdr.addWidget(self._dur)
        layout.addLayout(hdr)

        self._text = QLabel("")
        self._text.setWordWrap(True)
        self._text.setStyleSheet(
            "color: #eee; font-size: 15px; "
            "font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; "
            "padding: 6px 0; line-height: 1.5;"
        )
        layout.addWidget(self._text, 1)

        self._hint = QLabel(f"按 {HOTKEY_NAME} 或 Enter 输入文字")
        self._hint.setStyleSheet("color: #444; font-size: 11px;")
        layout.addWidget(self._hint, alignment=Qt.AlignRight)

    def set_text(self, text: str):
        self._text.setText(text)
        self._adjust_height()

    def set_duration(self, seconds: int):
        self._dur.setText(f"{seconds // 60:02d}:{seconds % 60:02d}")

    def set_recording(self, on: bool):
        if on:
            self._dot.setStyleSheet("color: #ff4444; font-size: 10px;")
            self._status.setText("正在录音...")
        else:
            self._dot.setStyleSheet("color: #ffaa00; font-size: 10px;")
            self._status.setText("识别完成")

    def _adjust_height(self):
        h = self._text.sizeHint().height() + 90
        h = max(100, min(h, 400))
        self._container.resize(self.width(), h)
        self.setFixedHeight(h)

    def place_near_cursor(self):
        pos = get_caret_screen_pos()
        if pos is None:
            pos = QCursor.pos().toTuple()
        screen = QApplication.primaryScreen().availableGeometry()
        x = pos[0] - self.width() // 2
        x = max(screen.left(), min(x, screen.right() - self.width()))
        y = pos[1] + 24
        if y + self.height() > screen.bottom():
            y = pos[1] - self.height() - 8
        self.move(x, y)

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
        self.closed.emit()
        super().closeEvent(e)


# ── settings dialog ────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置 — VoiceInput")
        self.setFixedSize(420, 200)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        cfg = load_config()
        layout = QFormLayout(self)
        layout.setSpacing(10)

        self._app_id = QLineEdit(cfg[0])
        self._key_id = QLineEdit(cfg[1])
        self._key_secret = QLineEdit(cfg[2])
        self._key_secret.setEchoMode(QLineEdit.Password)

        layout.addRow("AppID:", self._app_id)
        layout.addRow("APIKey:", self._key_id)
        layout.addRow("APISecret:", self._key_secret)

        hint = QLabel("从 https://console.xfyun.cn/ 获取")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addRow(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _save(self):
        import yaml
        config_path = Path(__file__).parent / "config.yaml"
        data = {
            "xfyun": {
                "app_id": self._app_id.text().strip(),
                "access_key_id": self._key_id.text().strip(),
                "access_key_secret": self._key_secret.text().strip(),
            }
        }
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        self.accept()


# ── main app ───────────────────────────────────────────────────────
class VoiceInputApp(QObject):
    def __init__(self):
        super().__init__()
        self._app = QApplication.instance()
        self._engine = ASREngine()
        self._bridge = SpeechBridge()
        self._recording = False
        self._recorder: AudioRecorder | None = None
        self._session = None
        self._float_win: FloatingWindow | None = None
        self._duration_timer = QTimer(self)
        self._duration_timer.timeout.connect(self._tick_duration)
        self._start_ts = 0
        self._toggle_action = None
        self._last_hotkey_ts = 0
        self._pending_text = ""

        self._bridge.partial.connect(self._on_partial)
        self._bridge.final.connect(self._on_final)
        self._bridge.error.connect(self._on_error)
        self._bridge.toggle.connect(self._toggle_recording)
        self._bridge.do_type.connect(self._type_pending)

        # tray
        self._tray = QSystemTrayIcon(_make_tray_icon(False))
        self._tray.setToolTip("VoiceInput — 语音输入法")
        self._rebuild_tray_menu()
        self._tray.show()

        # hotkey — add_hotkey is more reliable with Qt than on_press_key
        kb.add_hotkey(HOTKEY, self._on_hotkey, suppress=False)
        kb.on_press_key("enter", self._on_enter_hotkey, suppress=False)

        print(f"VoiceInput 已启动 — 按 {HOTKEY_NAME} 或右键托盘图标切换录音")
        self._tray.showMessage(
            "VoiceInput",
            f"已启动 — 按 {HOTKEY_NAME} 或右键托盘切换录音",
            QSystemTrayIcon.Information,
            2000,
        )

    def _rebuild_tray_menu(self):
        menu = QMenu()
        label = "⬤ 停止录音" if self._recording else "⬤ 开始录音"
        self._toggle_action = menu.addAction(label, self._toggle_recording)
        menu.addSeparator()
        menu.addAction("设置...", self._show_settings)
        menu.addSeparator()
        menu.addAction("退出", self._quit)
        self._tray.setContextMenu(menu)

    # ── hotkey ──────────────────────────────────────────────────
    def _on_hotkey(self):
        now = time.time()
        if now - self._last_hotkey_ts < 0.8:
            return
        self._last_hotkey_ts = now
        print(f"[DEBUG] 热键触发, recording={self._recording}")
        self._bridge.toggle.emit()

    def _on_enter_hotkey(self, event=None):
        if self._pending_text and not self._recording:
            print("[DEBUG] Enter 触发输入")
            self._bridge.do_type.emit()

    def _type_pending(self):
        if self._pending_text:
            self._type_text(self._pending_text)
            print(f"[DEBUG] 输入文字: {self._pending_text}")
            self._pending_text = ""
            self._hide_floating()

    def _toggle_recording(self):
        print(f"[DEBUG] _toggle_recording called, recording={self._recording}")
        if self._pending_text and not self._recording:
            self._type_pending()
        if not self._recording:
            self._start_recording()
        else:
            self._stop_recording()
        self._rebuild_tray_menu()

    def _start_recording(self):
        if self._float_win:
            self._float_win.close()
            self._float_win = None

        # Show floating window immediately (before WebSocket connect)
        self._recording = True
        self._start_ts = int(time.perf_counter())

        self._float_win = FloatingWindow()
        self._float_win.show()
        self._float_win.set_recording(True)
        self._duration_timer.start(200)

        self._tray.setIcon(_make_tray_icon(True))
        self._tray.setToolTip("VoiceInput — 连接中...")

        # Start connecting in background; audio is buffered until ready
        self._session = self._engine.create_session(
            on_partial=self._on_asr_partial,
            on_log=None,
            on_error=self._on_session_error,
        )
        self._session.start()

        # Start audio capture immediately (chunks buffered until WS ready)
        self._recorder = AudioRecorder(on_chunk=self._session.feed)
        self._recorder.start()

        print("[DEBUG] 开始录音")

    def _stop_recording(self):
        self._recording = False
        self._duration_timer.stop()

        if self._recorder:
            self._recorder.stop()
            self._recorder = None

        if self._float_win:
            self._float_win.set_recording(False)

        if self._session:
            try:
                final = self._session.finish()
            except Exception:
                final = ""
            self._session = None

        self._tray.setIcon(_make_tray_icon(False))
        self._tray.setToolTip("VoiceInput — 语音输入法")

        if final.strip():
            self._pending_text = final.strip()
            if self._float_win:
                self._float_win.set_text(self._pending_text)
            print(f"[DEBUG] 识别完成: {self._pending_text}")
        else:
            self._pending_text = ""
            QTimer.singleShot(800, self._hide_floating)

    def _hide_floating(self):
        if self._float_win and not self._recording:
            self._float_win.close()
            self._float_win = None

    # ── ASR callbacks (from background threads) ─────────────────
    def _on_asr_partial(self, text: str, is_final: bool,
                        is_seg: bool = False, seg_id: int = 0):
        if is_final:
            self._bridge.final.emit(text)
        else:
            self._bridge.partial.emit(text)

    def _on_partial(self, text: str):
        if self._float_win:
            self._float_win.set_text(text)

    def _on_final(self, text: str):
        if self._float_win and text.strip():
            self._float_win.set_text(text)
            self._float_win.set_recording(False)

    def _on_error(self, msg: str):
        QMessageBox.warning(None, "错误", msg)

    def _on_session_error(self, msg: str):
        if self._recording:
            self._stop_recording()
        self._bridge.error.emit(msg)

    def _tick_duration(self):
        if self._float_win:
            elapsed = int(time.perf_counter()) - self._start_ts
            self._float_win.set_duration(elapsed)

    @staticmethod
    def _type_text(text: str):
        def _paste():
            old = pyperclip.paste()
            pyperclip.copy(text)
            time.sleep(0.08)
            ctrl = KbController()
            ctrl.press(KbKey.ctrl)
            ctrl.press("v")
            ctrl.release("v")
            ctrl.release(KbKey.ctrl)
            time.sleep(0.3)
            pyperclip.copy(old)
        threading.Thread(target=_paste, daemon=True).start()

    def _show_settings(self):
        dlg = SettingsDialog()
        if dlg.exec() == QDialog.Accepted:
            self._engine = ASREngine()

    def _quit(self):
        if self._recording:
            self._stop_recording()
        kb.unhook_all()
        self._app.quit()


def main():
    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, lambda *a: QApplication.quit())

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("VoiceInput")

    # Timer to let Python process signals
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)

    VoiceInputApp()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
