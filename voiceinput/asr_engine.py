import os
import time
import hmac
import hashlib
import base64
import json
import queue
import threading
import uuid
from pathlib import Path
from urllib.parse import urlencode, quote
from datetime import datetime, timezone, timedelta

import numpy as np
import websocket
import yaml


XF_URL = "wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1"


def _build_url(app_id, access_key_id, access_key_secret):
    tz = timezone(timedelta(hours=8))
    utc_str = datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S+0800")

    params = {
        "accessKeyId": access_key_id,
        "appId": app_id,
        "audio_encode": "pcm_s16le",
        "lang": "autodialect",
        "samplerate": "16000",
        "utc": utc_str,
        "uuid": uuid.uuid4().hex,
    }

    sorted_keys = sorted(params.keys())
    parts = []
    for k in sorted_keys:
        parts.append(f"{quote(k, safe='')}={quote(str(params[k]), safe='')}")
    base_string = "&".join(parts)

    signature = base64.b64encode(
        hmac.new(
            access_key_secret.encode(),
            base_string.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()

    params["signature"] = signature
    return f"{XF_URL}?{urlencode(params, quote_via=quote)}"


def _extract_text(data):
    parts = []
    try:
        for segment in data.get("cn", {}).get("st", {}).get("rt", []):
            for ws_item in segment.get("ws", []):
                for cw in ws_item.get("cw", []):
                    parts.append(cw.get("w", ""))
    except Exception:
        pass
    return "".join(parts)


class XfyunStreamingSession:
    """Real-time streaming ASR session — open once, feed chunks, get live results."""

    def __init__(self, app_id, access_key_id, access_key_secret, on_partial=None, on_log=None):
        self._app_id = app_id
        self._key_id = access_key_id
        self._key_secret = access_key_secret
        self.on_partial = on_partial  # callback(text: str, is_final: bool)
        self.on_log = on_log          # callback(msg: dict) for raw API messages

        self._ws = None
        self._sid = None
        self._running = False
        self._final_text = ""
        self._final_event = threading.Event()
        self._recv_thread = None
        self._send_failed = False
        self._segments = {}  # seg_id -> final text for that segment

    def start(self):
        url = _build_url(self._app_id, self._key_id, self._key_secret)
        self._ws = websocket.create_connection(url)
        self._ws.settimeout(0.5)

        handshake = json.loads(self._ws.recv())
        self._sid = handshake.get("sid", "")
        if self.on_log:
            self.on_log({"event": "handshake", **handshake})

        self._running = True
        self._recv_thread = threading.Thread(target=self._receiver, daemon=True)
        self._recv_thread.start()

    def feed(self, chunk: np.ndarray):
        """Send one 40ms audio chunk (640 samples int16) to the server."""
        if self._ws and not self._send_failed:
            try:
                self._ws.send_binary(chunk.tobytes())
            except Exception:
                self._send_failed = True

    def finish(self) -> str:
        """End the stream and return the final recognized text."""
        end_msg = {"end": True, "sessionId": self._sid}
        if self.on_log:
            self.on_log({"event": "send_end", **end_msg})
        try:
            self._ws.send(json.dumps(end_msg))
        except Exception:
            pass

        self._final_event.wait(timeout=5)
        self._running = False

        if self._recv_thread:
            self._recv_thread.join(timeout=2)
        self._ws.close()
        return self._final_text

    def _receiver(self):
        while True:
            try:
                msg = json.loads(self._ws.recv())
            except websocket.WebSocketTimeoutException:
                if not self._running and self._final_text:
                    break
                continue
            except Exception:
                break

            if self.on_log:
                self.on_log({"event": "recv", "raw": msg})

            if msg.get("msg_type") == "result" and msg.get("res_type") == "asr":
                data = msg.get("data", {})
                text = _extract_text(data)
                seg_id = data.get("seg_id", 0)
                st_type = data.get("cn", {}).get("st", {}).get("type", "1")
                is_last = data.get("ls", False)

                # Accumulate final (type=0) results per segment
                if st_type == "0" and text:
                    self._segments[seg_id] = text

                if is_last:
                    parts = []
                    for sid in sorted(self._segments.keys()):
                        parts.append(self._segments[sid])
                    self._final_text = "".join(parts)
                    self._final_event.set()
                    if self.on_partial:
                        self.on_partial(self._final_text, True, False, -1)
                elif text and self.on_partial:
                    is_segment_final = st_type == "0"
                    self.on_partial(text, False, is_segment_final, seg_id)


def load_config():
    config_path = Path(__file__).parent / "config.yaml"

    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        xf = cfg.get("xfyun", {})
        app_id = xf.get("app_id", "")
        key_id = xf.get("access_key_id", "")
        key_secret = xf.get("access_key_secret", "")
    else:
        app_id = key_id = key_secret = ""

    app_id = app_id or os.environ.get("XF_APP_ID", "")
    key_id = key_id or os.environ.get("XF_ACCESS_KEY_ID", "")
    key_secret = key_secret or os.environ.get("XF_ACCESS_KEY_SECRET", "")

    if not all([app_id, key_id, key_secret]):
        raise ValueError(
            "请先配置 API 密钥:\n"
            f"  编辑 {config_path}\n"
            "  或设置环境变量: XF_APP_ID, XF_ACCESS_KEY_ID, XF_ACCESS_KEY_SECRET\n"
            "  从 https://console.xfyun.cn/ 获取"
        )

    return app_id, key_id, key_secret


class ASREngine:
    """Convenience wrapper that loads config and creates streaming sessions."""

    def __init__(self, model_path=None):
        self._app_id, self._key_id, self._key_secret = load_config()

    def create_session(self, on_partial=None, on_log=None):
        return XfyunStreamingSession(
            self._app_id, self._key_id, self._key_secret,
            on_partial=on_partial, on_log=on_log,
        )
