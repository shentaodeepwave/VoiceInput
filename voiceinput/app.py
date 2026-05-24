"""VoiceInput GUI — macOS-style voice input method."""
import ctypes
from ctypes import wintypes
import signal
import sys
import time
import threading
from pathlib import Path

import pyperclip
import keyboard as kb
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPoint, QEvent
from PySide6.QtGui import (
    QPainter, QColor, QBrush, QPixmap, QIcon, QMouseEvent,
    QFont, QPen,
)
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget,
    QVBoxLayout, QLabel, QHBoxLayout, QPushButton,
    QPlainTextEdit, QFrame,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox,
)

from audio_capture import AudioRecorder
from asr_engine import ASREngine, load_config

HOTKEY = "right ctrl"
HOTKEY_NAME = "右 Ctrl"
MAX_CHARS = 800
APP_NAME = "VoiceInput"


# ── helpers ────────────────────────────────────────────────────────
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


# ── stylesheets ─────────────────────────────────────────────────────
MAIN_STYLE = """
    #MainWindow {
        background-color: #F0F0F0;
    }
    #cardFrame {
        background-color: #FFFFFF;
        border: 1px solid #E0E0E0;
        border-radius: 10px;
    }
    #textEdit {
        background-color: transparent;
        border: none;
        font-size: 15px;
        padding: 16px;
        font-family: 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', sans-serif;
        color: #1a1a1a;
        selection-background-color: #007AFF;
        selection-color: #FFFFFF;
    }
    #toggleBtn {
        background-color: #007AFF;
        color: #FFFFFF;
        border: none;
        border-radius: 16px;
        padding: 0 24px;
        font-size: 13px;
        font-weight: 600;
        min-height: 32px;
    }
    #toggleBtn:hover {
        background-color: #0062CC;
    }
    #toggleBtn:pressed {
        background-color: #0055B3;
    }
    #toggleBtn[recording="true"] {
        background-color: #FF3B30;
    }
    #toggleBtn[recording="true"]:hover {
        background-color: #D62D20;
    }
    #toggleBtn:disabled {
        background-color: #B0B0B0;
        color: #E0E0E0;
    }
    #actionBtn {
        background-color: #FFFFFF;
        color: #333333;
        border: 1px solid #D0D0D0;
        border-radius: 16px;
        padding: 0 16px;
        font-size: 13px;
        min-height: 32px;
    }
    #actionBtn:hover {
        background-color: #F5F5F5;
        border-color: #BBBBBB;
    }
    #actionBtn:pressed {
        background-color: #E8E8E8;
    }
    #actionBtn:disabled {
        color: #BBBBBB;
        border-color: #E8E8E8;
        background-color: #FAFAFA;
    }
    #statusLabel {
        color: #999999;
        font-size: 12px;
        padding: 6px 8px;
    }
"""

OVERLAY_STYLE = """
    #overlayContainer {
        background: rgba(32, 32, 32, 0.93);
        border-radius: 12px;
        border: 1px solid rgba(255, 255, 255, 0.10);
    }
    #overlayText {
        color: #e8e8e8;
        font-size: 14px;
        font-family: 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', sans-serif;
        padding: 4px 0;
    }
    #overlayHint {
        color: #555555;
        font-size: 11px;
    }
"""


# ── SpeechBridge ────────────────────────────────────────────────────
class SpeechBridge(QObject):
    partial = Signal(str)
    final = Signal(str)
    error = Signal(str)
    toggle = Signal()


# ── VADToggle ───────────────────────────────────────────────────────
class VADToggle(QWidget):
    """Three-position elliptical pill toggle for VAD delay rate."""
    modeChanged = Signal(str, float)  # (mode_name, delay_ms)

    MODES = [
        ("聊天模式", 1500),
        ("标准模式", 2000),
        ("工作模式", 2500),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index = 1  # default: 标准模式
        self.setFixedSize(180, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("VAD 静音检测延迟: 点击切换")

    def current_delay(self) -> float:
        return self.MODES[self._index][1]

    def current_name(self) -> str:
        return self.MODES[self._index][0]

    def set_mode_index(self, idx: int):
        if 0 <= idx < len(self.MODES):
            self._index = idx
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent):
        self._index = (self._index + 1) % len(self.MODES)
        name, delay = self.MODES[self._index]
        self.modeChanged.emit(name, float(delay) / 1000.0)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        seg_w = w / 3

        font = QFont("PingFang SC", 9)
        font.setFamilies(["PingFang SC", "Microsoft YaHei", "Segoe UI", "sans-serif"])
        p.setFont(font)

        for i, (name, _) in enumerate(self.MODES):
            x = seg_w * i
            if i == self._index:
                # active segment — filled blue pill
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor("#007AFF")))
                p.drawRoundedRect(x + 2, 2, seg_w - 4, h - 4, h / 2, h / 2)
                p.setPen(QColor("#FFFFFF"))
            else:
                p.setPen(QColor("#999999"))
            p.drawText(int(x), 0, int(seg_w), h, Qt.AlignCenter, name)

        # border pill
        p.setPen(QPen(QColor("#D0D0D0"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)


# ── CompactOverlay ──────────────────────────────────────────────────
class CompactOverlay(QWidget):
    """Frameless floating window shown when main window is minimized."""
    restoreRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self._drag_pos: QPoint | None = None
        self._quitting = False
        self._setup_ui()
        self.setFixedWidth(420)

    def _setup_ui(self):
        self.setMinimumHeight(70)
        self._container = QWidget(self)
        self._container.setObjectName("overlayContainer")
        self._container.setStyleSheet(OVERLAY_STYLE)
        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self._text = QLabel("")
        self._text.setObjectName("overlayText")
        self._text.setWordWrap(True)
        self._text.setMinimumHeight(20)
        layout.addWidget(self._text, 1)

        self._hint = QLabel(f"按 {HOTKEY_NAME} 开始录音 · 双击恢复窗口")
        self._hint.setObjectName("overlayHint")
        layout.addWidget(self._hint, alignment=Qt.AlignRight)

    def set_text(self, text: str):
        self._text.setText(text)
        self._adjust_height()

    def _adjust_height(self):
        h = self._text.sizeHint().height() + 52
        h = max(70, min(h, 300))
        self._container.resize(self.width(), h)
        self.setFixedHeight(h)

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

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        self.restoreRequested.emit()

    def closeEvent(self, e):
        if self._quitting:
            e.accept()
        else:
            self.restoreRequested.emit()
            e.ignore()


# ── MainWindow ──────────────────────────────────────────────────────
class MainWindow(QWidget):
    toggleRequested = Signal()
    copyRequested = Signal()
    clearRequested = Signal()
    vadModeChanged = Signal(str, float)
    minimized = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(480, 360)
        self.resize(640, 460)
        self.setStyleSheet(MAIN_STYLE)
        self._quitting = False
        self._setup_ui()
        self._set_button_ready()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        # text area in a white card
        card = QFrame()
        card.setObjectName("cardFrame")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)

        self._text_edit = QPlainTextEdit()
        self._text_edit.setObjectName("textEdit")
        self._text_edit.setPlaceholderText(f"按 {HOTKEY_NAME} 或点击按钮开始录音...")
        self._text_edit.setMinimumHeight(200)
        card_layout.addWidget(self._text_edit)
        main_layout.addWidget(card, 1)

        # button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._toggle_btn = QPushButton("开始录音")
        self._toggle_btn.setObjectName("toggleBtn")
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.clicked.connect(self.toggleRequested.emit)
        btn_row.addWidget(self._toggle_btn)

        self._copy_btn = QPushButton("复制")
        self._copy_btn.setObjectName("actionBtn")
        self._copy_btn.setCursor(Qt.PointingHandCursor)
        self._copy_btn.clicked.connect(self.copyRequested.emit)
        btn_row.addWidget(self._copy_btn)

        self._clear_btn = QPushButton("清空")
        self._clear_btn.setObjectName("actionBtn")
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.clicked.connect(self.clearRequested.emit)
        btn_row.addWidget(self._clear_btn)

        btn_row.addStretch()

        self._vad_toggle = VADToggle()
        self._vad_toggle.modeChanged.connect(self.vadModeChanged.emit)
        btn_row.addWidget(self._vad_toggle)

        main_layout.addLayout(btn_row)

        # status bar
        self._status_label = QLabel("就绪")
        self._status_label.setObjectName("statusLabel")
        main_layout.addWidget(self._status_label)

    # ── public methods ───────────────────────────────────────────
    def text(self) -> str:
        return self._text_edit.toPlainText()

    def set_text(self, text: str):
        self._text_edit.setPlainText(text[:MAX_CHARS])

    def clear_text(self):
        self._text_edit.clear()

    def set_recording(self, active: bool):
        if active:
            self._toggle_btn.setText("停止录音")
            self._toggle_btn.setProperty("recording", "true")
        else:
            self._toggle_btn.setText("开始录音")
            self._toggle_btn.setProperty("recording", "false")
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)
        self._toggle_btn.setEnabled(True)

    def set_status(self, text: str):
        self._status_label.setText(text)

    def set_buttons_enabled(self, enabled: bool):
        self._toggle_btn.setEnabled(enabled)
        self._copy_btn.setEnabled(enabled)
        self._clear_btn.setEnabled(enabled)

    def _set_button_ready(self):
        self._toggle_btn.setText("开始录音")
        self._toggle_btn.setProperty("recording", "false")
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)
        self._toggle_btn.setEnabled(True)

    # ── window events ────────────────────────────────────────────
    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                QTimer.singleShot(0, self._on_minimize)
        super().changeEvent(event)

    def _on_minimize(self):
        self.setWindowState(Qt.WindowNoState)
        self.hide()
        self.minimized.emit()

    def restore(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self._quitting:
            event.accept()
        else:
            self.hide()
            self.minimized.emit()
            event.ignore()


# ── SettingsDialog ──────────────────────────────────────────────────
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


# ── VoiceInputApp ───────────────────────────────────────────────────
class VoiceInputApp(QObject):
    def __init__(self):
        super().__init__()
        self._app = QApplication.instance()

        try:
            self._engine = ASREngine()
        except ValueError as e:
            QMessageBox.critical(None, "配置错误", str(e))
            self._app.quit()
            return

        self._bridge = SpeechBridge()
        self._recording = False
        self._recorder: AudioRecorder | None = None
        self._session = None
        self._last_hotkey_ts = 0
        self._vad_delay = 2000  # default: standard mode (ms)

        self._bridge.partial.connect(self._on_partial)
        self._bridge.final.connect(self._on_final)
        self._bridge.error.connect(self._on_error)
        self._bridge.toggle.connect(self._toggle_recording)

        # main window
        self._main_win = MainWindow()
        self._main_win.toggleRequested.connect(self._toggle_recording)
        self._main_win.copyRequested.connect(self._copy_text)
        self._main_win.clearRequested.connect(self._clear_text)
        self._main_win.vadModeChanged.connect(self._on_vad_changed)
        self._main_win.minimized.connect(self._show_overlay)
        self._main_win.show()

        # compact overlay
        self._overlay = CompactOverlay()
        self._overlay.restoreRequested.connect(self._restore_main)

        # tray
        self._tray = QSystemTrayIcon(_make_tray_icon(False))
        self._tray.setToolTip(f"{APP_NAME} — 语音输入法")
        self._tray.activated.connect(self._on_tray_activated)
        self._rebuild_tray_menu()
        self._tray.show()

        # hotkey
        kb.add_hotkey(HOTKEY, self._on_hotkey, suppress=False)

        # mic permission check
        QTimer.singleShot(300, self._check_mic)

        print(f"VoiceInput 已启动 — 按 {HOTKEY_NAME} 或点击按钮开始录音")
        self._tray.showMessage(
            APP_NAME,
            f"已启动 — 按 {HOTKEY_NAME} 或点击按钮切换录音",
            QSystemTrayIcon.Information,
            2000,
        )

    # ── mic permission ───────────────────────────────────────────
    def _check_mic(self):
        try:
            import sounddevice as sd
            s = sd.InputStream(samplerate=16000, channels=1, blocksize=640, dtype="int16")
            s.start()
            s.stop()
            s.close()
        except Exception as e:
            msg = str(e)
            self._main_win.set_status(f"麦克风错误: {msg}")
            print(f"[ERROR] 麦克风检测失败: {msg}")

    # ── tray ─────────────────────────────────────────────────────
    def _rebuild_tray_menu(self):
        menu = QMenu()
        label = "停止录音" if self._recording else "开始录音"
        menu.addAction(label, self._toggle_recording)
        menu.addSeparator()
        menu.addAction("显示主窗口", self._restore_main)
        menu.addAction("设置...", self._show_settings)
        menu.addSeparator()
        menu.addAction("退出", self._quit)
        self._tray.setContextMenu(menu)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._restore_main()

    # ── hotkey ───────────────────────────────────────────────────
    def _on_hotkey(self):
        now = time.time()
        if now - self._last_hotkey_ts < 0.8:
            return
        self._last_hotkey_ts = now
        print(f"[DEBUG] 热键触发, recording={self._recording}")
        self._bridge.toggle.emit()

    # ── recording toggle ─────────────────────────────────────────
    def _toggle_recording(self):
        if not self._recording:
            self._start_recording()
        else:
            self._stop_recording()
        self._rebuild_tray_menu()

    def _start_recording(self):
        self._recording = True
        self._main_win.clear_text()
        self._main_win.set_recording(True)
        self._main_win.set_status("录音中...")

        self._overlay.set_text("")

        self._tray.setIcon(_make_tray_icon(True))
        self._tray.setToolTip(f"{APP_NAME} — 录音中...")

        self._session = self._engine.create_session(
            on_partial=self._on_asr_partial,
            on_log=None,
            on_error=self._on_session_error,
            vad_eos=self._vad_delay,
        )
        self._session.start()

        self._recorder = AudioRecorder(on_chunk=self._session.feed)
        self._recorder.start()

        print(f"[DEBUG] 开始录音 (VAD={self._vad_delay}ms)")

    def _stop_recording(self):
        if not self._recording:
            return
        self._recording = False

        if self._recorder:
            self._recorder.stop()
            self._recorder = None

        self._main_win.set_recording(False)
        self._main_win.set_status("识别中...")
        self._main_win._toggle_btn.setEnabled(False)

        if self._session:
            session = self._session
            self._session = None
            threading.Thread(
                target=self._finish_session, args=(session,), daemon=True
            ).start()

        self._tray.setIcon(_make_tray_icon(False))
        self._tray.setToolTip(f"{APP_NAME} — 语音输入法")
        self._rebuild_tray_menu()
        print("[DEBUG] 停止录音")

    def _finish_session(self, session):
        try:
            final = session.finish()
        except Exception as e:
            print(f"[ERROR] finish() 异常: {e}")
            final = ""
        if final:
            self._bridge.final.emit(final)
        else:
            self._bridge.final.emit("")

    # ── ASR callbacks (from background threads) ──────────────────
    def _on_asr_partial(self, text: str, is_final: bool,
                        is_seg: bool = False, seg_id: int = 0):
        if is_final:
            self._bridge.final.emit(text)
        else:
            self._bridge.partial.emit(text)

    def _on_partial(self, text: str):
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
            if self._recording:
                self._main_win.set_text(text)
                if self._overlay.isVisible():
                    self._overlay.set_text(text)
                self._stop_recording()
                self._main_win.set_recording(False)
                self._main_win.set_status(f"已达到字符上限 ({MAX_CHARS}字)")
                self._main_win._toggle_btn.setEnabled(True)
            return
        self._main_win.set_text(text)
        if self._overlay.isVisible():
            self._overlay.set_text(text)

    def _on_final(self, text: str):
        # Handle server-side VAD auto-stop (recording still active)
        if self._recording:
            if self._recorder:
                self._recorder.stop()
                self._recorder = None
            self._recording = False
            self._session = None
            self._tray.setIcon(_make_tray_icon(False))
            self._tray.setToolTip(f"{APP_NAME} — 语音输入法")
        if text.strip():
            display = text[:MAX_CHARS]
            self._main_win.set_text(display)
            if self._overlay.isVisible():
                self._overlay.set_text(display)
        self._main_win.set_recording(False)
        self._main_win.set_status("就绪")
        self._main_win._toggle_btn.setEnabled(True)
        self._rebuild_tray_menu()
        print(f"[DEBUG] 识别完成: {text}")

    def _on_error(self, msg: str):
        self._main_win.set_status(f"错误: {msg}")
        self._main_win.set_recording(False)
        self._main_win._toggle_btn.setEnabled(True)

    def _on_session_error(self, msg: str):
        if self._recording:
            self._stop_recording()
        self._bridge.error.emit(f"连接错误: {msg}")

    # ── UI actions ───────────────────────────────────────────────
    def _copy_text(self):
        text = self._main_win.text()
        if text.strip():
            pyperclip.copy(text)
            self._main_win.set_status("已复制到剪贴板")
            QTimer.singleShot(2000, lambda: self._main_win.set_status("就绪"))

    def _clear_text(self):
        self._main_win.clear_text()
        self._main_win.set_status("就绪")

    def _on_vad_changed(self, name: str, delay: float):
        self._vad_delay = int(delay * 1000)
        print(f"[DEBUG] VAD 模式切换: {name} ({self._vad_delay}ms)")

    # ── window management ────────────────────────────────────────
    def _show_overlay(self):
        """Switch to compact overlay mode."""
        self._main_win.hide()
        # position overlay at top-center of screen
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.center().x() - self._overlay.width() // 2
        y = screen.top() + 40
        self._overlay.move(x, y)
        self._overlay.show()
        print("[DEBUG] 切换到悬浮窗模式")

    def _restore_main(self):
        """Restore main window from overlay mode."""
        self._overlay.hide()
        self._main_win.restore()
        print("[DEBUG] 恢复主窗口")

    def _show_settings(self):
        dlg = SettingsDialog()
        if dlg.exec() == QDialog.Accepted:
            try:
                self._engine = ASREngine()
            except ValueError as e:
                QMessageBox.critical(None, "配置错误", str(e))

    def _quit(self):
        if self._recording:
            self._stop_recording()
        self._main_win._quitting = True
        self._overlay._quitting = True
        try:
            kb.unhook_all()
        except Exception:
            pass
        self._main_win.close()
        self._overlay.close()
        self._app.quit()


# ── main ────────────────────────────────────────────────────────────
def main():
    signal.signal(signal.SIGINT, lambda *a: QApplication.quit())

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)

    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)

    VoiceInputApp()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
