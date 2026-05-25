import time
from enum import Enum, auto

import keyboard as kb
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
    if recording:
        p.setBrush(QBrush(QColor("#FF4444")))
    else:
        p.setBrush(QBrush(QColor("#888888")))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPoint(16, 16), 8, 8)
    p.end()
    return QIcon(px)


class VoiceInputApp(QObject):
    def __init__(self):
        super().__init__()
        self._app = QApplication.instance()
        self._config = ConfigManager()
        self._engine = ASREngine(self._config.data)
        self._bridge = AppBridge()
        self._accumulated_text = ""
        self._state = State.IDLE
        self._recorder: AudioRecorder | None = None
        self._session = None
        self._vad: VoiceActivityDetector | None = None
        self._window: FloatingCardWindow | None = None
        self._start_ts = 0
        self._last_toggle_ts = 0
        self._hotkey_ids = []
        self._hold_active = False
        self._history: list[str] = []
        self._history_open = False

        # Signal wiring
        self._bridge.partial.connect(self._on_partial)
        self._bridge.final.connect(self._on_final)
        self._bridge.error.connect(self._on_error)
        self._bridge.silence.connect(self._on_silence)
        self._bridge.toggle.connect(self._on_toggle)

        # System tray
        self._tray = QSystemTrayIcon(_make_tray_icon(False))
        self._tray.setToolTip("VoiceInput — 语音输入法")
        self._tray_menu = None
        self._rebuild_tray_menu()
        self._tray.show()

        # Hotkey
        self._bind_hotkey()

        # Show window on startup
        self._window = FloatingCardWindow(self._config.data.hotkey, self._config.data.tap_mode)
        self._window.mic_clicked.connect(self._bridge.toggle.emit)
        self._window.closed.connect(self._on_window_closed)
        self._window.destroyed.connect(lambda: setattr(self, "_window", None))
        self._window.history_toggled.connect(self._on_history_toggle)
        self._window.history_copy.connect(self._on_history_copy)
        self._window.history_delete.connect(self._on_history_delete)
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
            hid = kb.add_hotkey(hotkey, self._on_hotkey_trigger, suppress=True)
            self._hotkey_ids = [("add_hotkey", hid)]
        else:
            main_key = self._hotkey_main_key()
            hid1 = kb.on_press_key(main_key, self._on_hold_press, suppress=True)
            hid2 = kb.on_release_key(main_key, self._on_hold_release, suppress=True)
            self._hotkey_ids = [("on_press_key", hid1), ("on_release_key", hid2)]

    def _unbind_hotkey(self):
        for kind, hid in self._hotkey_ids:
            try:
                if kind == "add_hotkey":
                    kb.remove_hotkey(hid)
                else:
                    kb.unhook(hid)
            except Exception:
                pass
        self._hotkey_ids = []

    def rebind_hotkey(self):
        self._bind_hotkey()

    def _on_hotkey_trigger(self):
        self._bridge.toggle.emit()

    def _hotkey_main_key(self) -> str:
        """Return the lowercased main key from the configured hotkey.

        For "ctrl+F2" this returns "f2"; for "F2" it returns "f2".
        """
        return self._config.data.hotkey.lower().split("+")[-1]

    def _modifiers_held(self) -> bool:
        modifiers = self._config.data.hotkey.lower().split("+")[:-1]
        return all(kb.is_pressed(mod) for mod in modifiers)

    def _on_hold_press(self, e):
        if not self._hold_active and self._modifiers_held():
            self._hold_active = True
            self._bridge.toggle.emit()

    def _on_hold_release(self, e):
        if self._hold_active:
            self._hold_active = False
            self._bridge.toggle.emit()

    # ── State Machine ───────────────────────────────────────────
    def _on_toggle(self):
        now = time.time()
        if self._config.data.tap_mode and now - self._last_toggle_ts < 0.4:
            return
        self._last_toggle_ts = now

        if self._state == State.IDLE:
            self._start_recording()
        elif self._state == State.RECORDING:
            self._stop_recording()

    def _start_recording(self):
        if self._state != State.IDLE:
            return

        self._history_open = False

        self._engine = ASREngine(self._config.data)

        try:
            self._session = self._engine.create_session(
                on_partial=self._on_asr_result,
                on_error=self._on_asr_error,
            )
            self._session.start()
        except Exception as e:
            self._show_error(f"连接失败: {e}")
            self._session = None
            return

        self._state = State.RECORDING
        self._accumulated_text = ""
        self._start_ts = time.perf_counter()

        # VAD
        self._vad = VoiceActivityDetector(
            silence_seconds=self._config.data.vad_silence_seconds,
        )
        self._vad.enabled = self._config.data.vad_enabled

        # Recorder
        self._recorder = AudioRecorder(on_chunk=self._on_chunk)
        self._recorder.start()

        # Window — bring to front
        self._window.set_recording(True)
        self._window.clear_error()
        self._window.set_text("")
        self._window.show()
        self._window.raise_()
        self._window.setWindowOpacity(1.0)

        # Tray
        self._tray.setIcon(_make_tray_icon(True))
        self._tray.setToolTip("VoiceInput — 录音中...")
        self._rebuild_tray_menu()

    def _stop_recording(self):
        if self._state != State.RECORDING:
            return

        self._state = State.RECOGNIZING
        duration = self._recorder.duration if self._recorder else 0

        try:
            self._recorder.stop()
        except Exception:
            pass
        self._recorder = None
        self._vad = None

        if self._window:
            self._window.set_recording(False)

        self._tray.setIcon(_make_tray_icon(False))
        self._tray.setToolTip("VoiceInput — 语音输入法")
        self._rebuild_tray_menu()

        if duration < 0.5:
            if self._session:
                self._session.cancel()
                self._session = None
            self._transition_to_idle()
            return

        # Wait for final results
        try:
            final = self._session.finish() if self._session else ""
        except Exception:
            final = ""

        if final.strip():
            self._accumulated_text = final
            self._type_text(final)

        self._cleanup_session()
        self._transition_to_idle()

    def _transition_to_idle(self):
        self._state = State.IDLE
        if self._window:
            self._window.set_recording(False)

    def _cleanup_session(self):
        if self._session:
            try:
                self._session.cancel()
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
            self._accumulated_text += text
        display = self._accumulated_text if is_seg else self._accumulated_text + text
        if self._window:
            self._window.set_text(display)

    def _on_final(self, text: str):
        self._accumulated_text = text
        if text.strip():
            self._history.insert(0, text.strip())
            if len(self._history) > 3:
                self._history.pop()
            if self._window:
                self._window.set_text(text)

    def _on_error(self, msg: str):
        if self._state == State.RECORDING:
            try:
                if self._recorder:
                    self._recorder.stop()
                    self._recorder = None
            except Exception:
                self._recorder = None
            self._vad = None
            self._cleanup_session()

        self._accumulated_text = ""

        self._tray.setIcon(_make_tray_icon(False))
        self._tray.setToolTip("VoiceInput — 语音输入法")
        self._rebuild_tray_menu()
        self._state = State.IDLE

    def _on_silence(self):
        if self._state == State.RECORDING:
            self._stop_recording()

    # ── Typing ──────────────────────────────────────────────────
    @staticmethod
    def _type_text(text: str):
        kb.write(text, delay=0.005)

    # ── History ─────────────────────────────────────────────────
    def _on_history_toggle(self):
        self._history_open = not self._history_open
        if self._window:
            if self._history_open:
                self._window.show_history(self._history)
            else:
                self._window.hide_history()

    def _on_history_copy(self, text: str):
        QApplication.clipboard().setText(text)

    def _on_history_delete(self, index: int):
        if 0 <= index < len(self._history):
            del self._history[index]
            if self._window:
                if self._history:
                    self._window.remove_history_record(index)
                else:
                    self._window.show_history([])

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
            try:
                if self._recorder:
                    self._recorder.stop()
            except Exception:
                pass
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
        if self._tray_menu is None:
            self._tray_menu = QMenu()
        else:
            self._tray_menu.clear()

        if self._state == State.RECORDING:
            self._tray_menu.addAction("停止录音", self._bridge.toggle.emit)
        else:
            self._tray_menu.addAction("开始录音", self._bridge.toggle.emit)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction("设置...", self._show_settings)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction("关闭程序", self._quit)
        self._tray.setContextMenu(self._tray_menu)

    # ── Settings ────────────────────────────────────────────────
    def _show_settings(self):
        dlg = SettingsDialog(self._config)
        if dlg.exec() == SettingsDialog.Accepted:
            self._engine = ASREngine(self._config.data)
            self.rebind_hotkey()
            if self._window:
                self._window.set_placeholder(self._config.data.hotkey, self._config.data.tap_mode)

    # ── Quit ────────────────────────────────────────────────────
    def _quit(self):
        if self._state == State.RECORDING:
            self._stop_recording()
        self._unbind_hotkey()
        self._save_window_pos()
        self._app.quit()
