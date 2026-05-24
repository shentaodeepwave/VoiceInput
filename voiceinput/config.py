from dataclasses import dataclass, field, asdict
from pathlib import Path
import os
import yaml


@dataclass
class AppConfig:
    api_url: str = "wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1"
    app_id: str = ""
    access_key_id: str = ""
    access_key_secret: str = ""
    hotkey: str = "F2"
    tap_mode: bool = True
    vad_enabled: bool = False
    vad_silence_seconds: float = 1.5
    mic_permission_granted: bool = False
    window_x: int | None = None
    window_y: int | None = None


class ConfigManager:
    def __init__(self, config_path: Path | None = None):
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"
        self._path = config_path
        self._config = AppConfig()
        self.load()

    @property
    def data(self) -> AppConfig:
        return self._config

    def load(self):
        if not self._path.exists():
            self._apply_env_overrides()
            return

        with open(self._path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        xf = raw.get("xfyun", {})
        self._config.app_id = xf.get("app_id", self._config.app_id)
        self._config.access_key_id = xf.get("access_key_id", self._config.access_key_id)
        self._config.access_key_secret = xf.get("access_key_secret", self._config.access_key_secret)

        for key in ("api_url", "hotkey", "tap_mode", "vad_enabled",
                     "vad_silence_seconds", "mic_permission_granted", "window_x", "window_y"):
            if key in raw:
                setattr(self._config, key, raw[key])

        self._apply_env_overrides()

    def _apply_env_overrides(self):
        for attr, env_var in (
            ("app_id", "XF_APP_ID"),
            ("access_key_id", "XF_ACCESS_KEY_ID"),
            ("access_key_secret", "XF_ACCESS_KEY_SECRET"),
        ):
            val = os.environ.get(env_var, "")
            if val:
                setattr(self._config, attr, val)

    def save(self):
        data = {
            "xfyun": {
                "app_id": self._config.app_id,
                "access_key_id": self._config.access_key_id,
                "access_key_secret": self._config.access_key_secret,
            },
            "api_url": self._config.api_url,
            "hotkey": self._config.hotkey,
            "tap_mode": self._config.tap_mode,
            "vad_enabled": self._config.vad_enabled,
            "vad_silence_seconds": self._config.vad_silence_seconds,
            "mic_permission_granted": self._config.mic_permission_granted,
            "window_x": self._config.window_x,
            "window_y": self._config.window_y,
        }
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
