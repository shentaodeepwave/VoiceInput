import keyboard
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QLabel, QDialogButtonBox, QMessageBox,
)

from config import ConfigManager


class HotkeyCaptureWidget(QWidget):
    hotkey_changed = Signal(str)

    def __init__(self, current: str = "F2", parent=None):
        super().__init__(parent)
        self._current = current
        self._capturing = False
        self._hook = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._btn = QPushButton(current)
        self._btn.setFixedHeight(32)
        self._btn.clicked.connect(self._start_capture)
        layout.addWidget(self._btn)

        hint = QLabel("点击后按下新快捷键")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)
        layout.addStretch()

    def _start_capture(self):
        self._capturing = True
        self._btn.setText("按下按键...")
        self._btn.setStyleSheet("background: #F44336; color: white; border-radius: 4px;")
        try:
            self._hook = keyboard.on_press(self._on_key, suppress=True)
        except Exception:
            self._capturing = False
            self._btn.setText(self._current)
            self._btn.setStyleSheet("")

    def _on_key(self, e):
        if not self._capturing:
            return

        parts = []
        if keyboard.is_pressed("ctrl") or keyboard.is_pressed("right ctrl"):
            parts.append("ctrl")
        if keyboard.is_pressed("shift") or keyboard.is_pressed("right shift"):
            parts.append("shift")
        if keyboard.is_pressed("alt") or keyboard.is_pressed("right alt"):
            parts.append("alt")

        name = e.name
        if name not in ("ctrl", "shift", "alt", "right ctrl", "right shift", "right alt", "windows", "right windows"):
            parts.append(name)

        if parts:
            spec = "+".join(parts)
            self._current = spec
            self._btn.setText(spec)
            self.hotkey_changed.emit(spec)

        self._capturing = False
        self._btn.setStyleSheet("")
        try:
            keyboard.unhook(self._hook)
        except Exception:
            pass

    def value(self) -> str:
        return self._current


class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._config = config
        self._cfg = config.data

        self.setWindowTitle("设置 — VoiceInput")
        self.setFixedSize(440, 360)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        tabs.addTab(self._api_tab(), "API")
        tabs.addTab(self._hotkey_tab(), "快捷键与模式")
        tabs.addTab(self._vad_tab(), "语音检测")
        tabs.addTab(self._mic_tab(), "麦克风")

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _api_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(10)

        self._api_url = QLineEdit(self._cfg.api_url)
        form.addRow("API 地址:", self._api_url)

        self._app_id = QLineEdit(self._cfg.app_id)
        form.addRow("AppID:", self._app_id)

        self._key_id = QLineEdit(self._cfg.access_key_id)
        form.addRow("APIKey:", self._key_id)

        self._key_secret = QLineEdit(self._cfg.access_key_secret)
        self._key_secret.setEchoMode(QLineEdit.Password)
        form.addRow("APISecret:", self._key_secret)

        hint = QLabel("从 https://console.xfyun.cn/ 获取")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(hint)

        return w

    def _hotkey_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(12)

        self._hotkey_widget = HotkeyCaptureWidget(self._cfg.hotkey)
        form.addRow("全局快捷键:", self._hotkey_widget)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("点按模式（单击开始 / 单击停止）", True)
        self._mode_combo.addItem("长按模式（按住说话 / 松开停止）", False)
        self._mode_combo.setCurrentIndex(0 if self._cfg.tap_mode else 1)
        form.addRow("触发模式:", self._mode_combo)

        hint = QLabel("提示：Fn 键在 Windows 上可能无法捕获，建议使用 F2 或其他组合键")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(hint)

        return w

    def _vad_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setSpacing(12)

        self._vad_enabled = QCheckBox("启用静音检测（VAD）")
        self._vad_enabled.setChecked(self._cfg.vad_enabled)
        form.addRow(self._vad_enabled)

        self._vad_seconds = QLineEdit(str(self._cfg.vad_silence_seconds))
        self._vad_seconds.setValidator(QDoubleValidator(0.1, 9999.0, 1))
        self._vad_seconds.setFixedWidth(80)
        form.addRow("静音超时时长:", self._vad_seconds)

        hint = QLabel("检测到连续静音超过设定时长后，自动停止录音。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow(hint)

        return w

    def _mic_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        self._mic_status = QLabel("未检测")
        self._mic_status.setStyleSheet("color: #888; font-size: 13px;")

        test_btn = QPushButton("重新测试麦克风")
        test_btn.setFixedHeight(32)
        test_btn.clicked.connect(self._test_mic)

        row = QHBoxLayout()
        row.addWidget(test_btn)
        row.addWidget(self._mic_status)
        row.addStretch()
        layout.addLayout(row)

        hint = QLabel(
            "如果麦克风无法使用，请检查：\n"
            "1. 麦克风是否正确连接\n"
            "2. 系统麦克风权限是否已开启\n"
            "3. 麦克风是否被其他应用占用"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)
        layout.addStretch()

        return w

    def _test_mic(self):
        import sounddevice as sd
        try:
            devices = sd.query_devices()
            inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
            if not inputs:
                self._mic_status.setText("未检测到麦克风设备")
                self._mic_status.setStyleSheet("color: #F44336; font-size: 13px;")
                self._config.data.mic_permission_granted = False
                self._config.save()
                return

            stream = sd.InputStream(samplerate=16000, channels=1)
            stream.start()
            stream.stop()
            stream.close()
            self._mic_status.setText(f"正常（{inputs[0].get('name', '未知')})")
            self._mic_status.setStyleSheet("color: #4CAF50; font-size: 13px;")
            self._config.data.mic_permission_granted = True
            self._config.save()
        except Exception as e:
            self._mic_status.setText(f"错误: {e}")
            self._mic_status.setStyleSheet("color: #F44336; font-size: 13px;")
            self._config.data.mic_permission_granted = False
            self._config.save()

    def _save(self):
        cfg = self._cfg
        cfg.api_url = self._api_url.text().strip()
        cfg.app_id = self._app_id.text().strip()
        cfg.access_key_id = self._key_id.text().strip()
        cfg.access_key_secret = self._key_secret.text().strip()
        cfg.hotkey = self._hotkey_widget.value()
        cfg.tap_mode = self._mode_combo.currentData()
        cfg.vad_enabled = self._vad_enabled.isChecked()
        try:
            cfg.vad_silence_seconds = float(self._vad_seconds.text() or "1.5")
        except ValueError:
            cfg.vad_silence_seconds = 1.5
        self._config.save()
        self.accept()
