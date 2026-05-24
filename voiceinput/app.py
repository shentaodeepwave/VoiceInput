import time
import threading
from enum import Enum, auto

import pyperclip
import keyboard as kb
from pynput.keyboard import Controller as KbController, Key as KbKey
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QPoint
from PySide6.QtGui import QPainter, QColor, QBrush, QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QMessageBox,
)

from audio_capture import AudioRecorder
from asr_engine import ASREngine
from config import ConfigManager
from vad import VoiceActivityDetector
from window import FloatingCardWindow
from settings import SettingsDialog


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    RECOGNIZING = auto()


class AppBridge(QObject):
    partial = Signal(str, bool)  # text, is_segment_final
    final = Signal(str)
    error = Signal(str)
    silence = Signal()
    toggle = Signal()


def _make_tray_icon(recording: bool = False) -> QIcon:
    px = QPixmap(32, 32)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor("#F44336") if recording else QColor("#4CAF50")
    p.setBrush(QBrush(c))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPoint(16, 16), 8, 8)
    p.end()
    return QIcon(px)


class LiveTyper:
    """Incremental typing with committed/pending segment tracking.

    Committed text is locked — previous segments that won't be backspaced.
    Pending text is the current segment's partial, which can be corrected
    as the ASR refines its prediction.
    """

    def __init__(self):
        self._committed = ""
        self._pending = ""

    @property
    def full_text(self) -> str:
        return self._committed + self._pending

    def update(self, text: str):
        """Replace the pending partial with new text."""
        if text == self._pending:
            return

        # Backspace old pending (only the pending part)
        for _ in range(len(self._pending)):
            kb.press_and_release("backspace")
            time.sleep(0.002)

        # Type new pending
        if text:
            kb.write(text)

        self._pending = text

    def commit_segment(self, text: str):
        """Lock current pending as committed (segment is final)."""
        # The pending text is already typed, just move it to committed
        self._committed += text
        self._pending = ""

    def reset(self):
        """Backspace all typed text (committed + pending)."""
        total = len(self._committed) + len(self._pending)
        for _ in range(total):
            kb.press_and_release("backspace")
            time.sleep(0.002)
        self._committed = ""
        self._pending = ""


class VoiceInputApp(QObject):
    def __init__(self):
        super().__init__()
        self._app = QApplication.instance()
        self._config = ConfigManager()
        self._engine = ASREngine(self._config.data)
        self._bridge = AppBridge()
        self._typer = LiveTyper()
        self._state = State.IDLE
        self._recorder: AudioRecorder | None = None
        self._session = None
        self._vad: VoiceActivityDetector | None = None
        self._window: FloatingCardWindow | None = None
        self._start_ts = 0
        self._last_toggle_ts = 0
        self._hotkey_ids = []

        # Signal wiring
        self._bridge.partial.connect(self._on_partial)
        self._bridge.final.connect(self._on_final)
        self._bridge.error.connect(self._on_error)
        self._bridge.silence.connect(self._on_silence)
        self._bridge.toggle.connect(self._on_toggle)

        # System tray
        self._tray = QSystemTrayIcon(_make_tray_icon(False))
        self._tray.setToolTip("VoiceInput — 语音输入法")
        self._rebuild_tray_menu()
        self._tray.show()

        # Hotkey
        self._bind_hotkey()

        # Show window on startup
        self._window = FloatingCardWindow(self._config.data.hotkey)
        self._window.mic_clicked.connect(self._bridge.toggle.emit)
        self._window.closed.connect(self._on_window_closed)
        self._window.destroyed.connect(lambda: setattr(self, "_window", None))
        self._window.show_with_fade()
        self._place_window()

        # First-launch mic check
        if not self._config.data.mic_permission_granted:
            QTimer.singleShot(800, self._check_mic_on_startup)

    # ── Mic Permission ──────────────────────────────────────────
    def _check_mic_on_startup(self):
        result = QMessageBox.question(
            None, "麦克风权限",
            "VoiceInput 需要使用麦克风进行语音输入。\n\n"
            "是否允许使用麦克风？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if result == QMessageBox.Yes:
            ok = self._test_mic()
            if ok:
                self._config.data.mic_permission_granted = True
                self._config.save()
            else:
                self._tray.showMessage(
                    "VoiceInput", "麦克风不可用，请在设置中重新测试",
                    QSystemTrayIcon.Warning, 3000,
                )
        else:
            self._tray.showMessage(
                "VoiceInput", "已拒绝麦克风权限，录音功能不可用",
                QSystemTrayIcon.Warning, 3000,
            )

    def _test_mic(self) -> bool:
        import sounddevice as sd
        try:
            stream = sd.InputStream(samplerate=16000, channels=1)
            stream.start()
            stream.stop()
            stream.close()
            return True
        except Exception:
            return False

    # ── Hotkey ──────────────────────────────────────────────────
    def _bind_hotkey(self):
        self._unbind_hotkey()
        hotkey = self._config.data.hotkey
        if not hotkey:
            return

        if self._config.data.tap_mode:
            hid = kb.add_hotkey(hotkey, self._on_hotkey_trigger, suppress=False)
            self._hotkey_ids = [("add_hotkey", hid)]
        else:
            hid1 = kb.on_press(self._on_hold_press, suppress=False)
            hid2 = kb.on_release(self._on_hold_release, suppress=False)
            self._hotkey_ids = [("on_press", hid1), ("on_release", hid2)]

    def _unbind_hotkey(self):
        for kind, hid in self._hotkey_ids:
            try:
                kb.remove_hotkey(hid) if kind == "add_hotkey" else kb.unhook(hid)
            except Exception:
                pass
        self._hotkey_ids = []

    def rebind_hotkey(self):
        self._bind_hotkey()

    def _on_hotkey_trigger(self):
        self._bridge.toggle.emit()

    def _on_hold_press(self, e):
        if e.name == self._config.data.hotkey and self._state == State.IDLE:
            self._bridge.toggle.emit()

    def _on_hold_release(self, e):
        if e.name == self._config.data.hotkey and self._state == State.RECORDING:
            self._bridge.toggle.emit()

    # ── State Machine ───────────────────────────────────────────
    def _on_toggle(self):
        now = time.time()
        if now - self._last_toggle_ts < 0.4:
            return
        self._last_toggle_ts = now

        if self._state == State.IDLE:
            self._start_recording()
        elif self._state == State.RECORDING:
            self._stop_recording()

    def _start_recording(self):
        if self._state != State.IDLE:
            return

        self._engine = ASREngine(self._config.data)

        try:
            self._session = self._engine.create_session(
                on_partial=self._on_asr_result,
                on_error=self._on_asr_error,
            )
            self._session.start()
        except Exception as e:
            self._show_error(f"连接失败: {e}")
            return

        self._state = State.RECORDING
        self._start_ts = time.perf_counter()

        # VAD
        self._vad = VoiceActivityDetector(
            silence_seconds=self._config.data.vad_silence_seconds,
        )
        self._vad.enabled = self._config.data.vad_enabled

        # Recorder
        self._recorder = AudioRecorder(on_chunk=self._on_chunk)
        self._recorder.start()

        # Window
        self._window.set_recording(True)
        self._window.clear_error()
        self._window.set_text("")
        self._window.show()
        self._window._opacity_effect.setOpacity(1.0)

        # Tray
        self._tray.setIcon(_make_tray_icon(True))
        self._tray.setToolTip("VoiceInput — 录音中...")
        self._rebuild_tray_menu()

    def _stop_recording(self):
        if self._state != State.RECORDING:
            return

        self._state = State.RECOGNIZING
        duration = self._recorder.duration if self._recorder else 0

        self._recorder.stop()
        self._recorder = None
        self._vad = None

        if self._window:
            self._window.set_recording(False)

        self._tray.setIcon(_make_tray_icon(False))
        self._tray.setToolTip("VoiceInput — 语音输入法")
        self._rebuild_tray_menu()

        if duration < 0.5:
            self._typer.reset()
            self._cleanup_session()
            self._transition_to_idle()
            return

        # Wait for final results
        try:
            final = self._session.finish() if self._session else ""
        except Exception:
            final = ""

        self._typer.reset()
        if final.strip():
            self._type_text(final)

        self._cleanup_session()
        self._transition_to_idle()

    def _transition_to_idle(self):
        self._state = State.IDLE
        if self._window:
            self._window.set_recording(False)
            # Update window with final accumulated text
            text = self._typer.full_text
            if text:
                self._window.set_text(text)

    def _cleanup_session(self):
        if self._session:
            try:
                self._session = None
            except Exception:
                pass
        self._session = None

    # ── Audio Chunk Handler ─────────────────────────────────────
    def _on_chunk(self, chunk):
        if self._session and not self._session.is_send_failed:
            self._session.feed(chunk)
        if self._vad and self._vad.process_chunk(chunk):
            self._bridge.silence.emit()

    # ── ASR Callbacks (from background threads) ─────────────────
    def _on_asr_result(self, text: str, is_final: bool,
                       is_seg: bool = False, seg_id: int = 0):
        if is_final:
            self._bridge.final.emit(text)
        else:
            self._bridge.partial.emit(text, is_seg)

    def _on_asr_error(self, msg: str):
        self._bridge.error.emit(msg)

    # ── Qt Signal Handlers ──────────────────────────────────────
    def _on_partial(self, text: str, is_seg: bool):
        if self._state not in (State.RECORDING, State.RECOGNIZING):
            return
        if is_seg:
            # Segment is final — lock it as committed
            self._typer.commit_segment(text)
        else:
            # In-progress partial — update pending
            self._typer.update(text)
        if self._window:
            self._window.set_text(self._typer.full_text)

    def _on_final(self, text: str):
        if self._window and text.strip():
            self._window.set_text(text)

    def _on_error(self, msg: str):
        if self._state == State.RECORDING:
            if self._recorder:
                self._recorder.stop()
                self._recorder = None
            self._vad = None
            self._cleanup_session()

        self._typer.reset()
        self._show_error("识别中断")
        self._state = State.IDLE

    def _on_silence(self):
        if self._state == State.RECORDING:
            self._stop_recording()

    # ── Typing ──────────────────────────────────────────────────
    @staticmethod
    def _type_text(text: str):
        old = pyperclip.paste()
        pyperclip.copy(text)
        time.sleep(0.05)
        ctrl = KbController()
        ctrl.press(KbKey.ctrl)
        ctrl.press("v")
        ctrl.release("v")
        ctrl.release(KbKey.ctrl)

        def restore():
            time.sleep(0.3)
            pyperclip.copy(old)
        threading.Thread(target=restore, daemon=True).start()

    # ── Window ──────────────────────────────────────────────────
    def _place_window(self):
        if not self._window:
            return
        x = self._config.data.window_x
        y = self._config.data.window_y
        if x is not None and y is not None:
            self._window.move(x, y)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            x = (screen.width() - self._window.width()) // 2
            y = screen.bottom() - self._window.height() - 80
            self._window.move(x, y)

    def _save_window_pos(self):
        if self._window:
            pos = self._window.pos()
            self._config.data.window_x = pos.x()
            self._config.data.window_y = pos.y()
            self._config.save()

    def _on_window_closed(self):
        self._save_window_pos()
        if self._state == State.RECORDING:
            if self._recorder:
                self._recorder.stop()
            self._recorder = None
            self._cleanup_session()
            self._state = State.IDLE
            self._tray.setIcon(_make_tray_icon(False))
            self._rebuild_tray_menu()

    def _show_error(self, msg: str):
        if self._window:
            self._window.set_recording(False)
            self._window.set_error(msg)

    # ── System Tray ─────────────────────────────────────────────
    def _rebuild_tray_menu(self):
        menu = QMenu()
        if self._state == State.RECORDING:
            menu.addAction("停止录音", self._bridge.toggle.emit)
        else:
            menu.addAction("开始录音", self._bridge.toggle.emit)
        menu.addSeparator()
        menu.addAction("设置...", self._show_settings)
        menu.addSeparator()
        menu.addAction("退出", self._quit)
        self._tray.setContextMenu(menu)

    # ── Settings ────────────────────────────────────────────────
    def _show_settings(self):
        was_recording = self._state == State.RECORDING
        if was_recording:
            self._stop_recording()

        dlg = SettingsDialog(self._config)
        if dlg.exec() == SettingsDialog.Accepted:
            self._engine = ASREngine(self._config.data)
            self.rebind_hotkey()
            if self._window:
                self._window.set_hotkey_label(self._config.data.hotkey)

    # ── Quit ────────────────────────────────────────────────────
    def _quit(self):
        if self._state == State.RECORDING:
            self._stop_recording()
        self._unbind_hotkey()
        self._save_window_pos()
        self._app.quit()
