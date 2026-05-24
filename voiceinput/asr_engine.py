import os
import time
import hmac
import hashlib
import base64
import json
import threading
import uuid
from pathlib import Path
from urllib.parse import urlencode, quote
from datetime import datetime, timezone, timedelta

import numpy as np
import websocket
import yaml


XF_URL = "wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1"


def _build_url(app_id, access_key_id, access_key_secret, vad_eos=2000):
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
        "vad_eos": str(vad_eos),
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

    def __init__(self, app_id, access_key_id, access_key_secret,
                 on_partial=None, on_log=None, on_error=None, vad_eos=2000):
        self._app_id = app_id
        self._key_id = access_key_id
        self._key_secret = access_key_secret
        self._vad_eos = vad_eos
        self.on_partial = on_partial
        self.on_log = on_log
        self.on_error = on_error

        self._ws = None
        self._sid = None
        self._running = False
        self._final_text = ""
        self._final_event = threading.Event()
        self._recv_thread = None
        self._send_failed = False
        self._segments = {}            # seg_id -> final text (type=0)
        self._intermediate_texts = {}  # seg_id -> latest intermediate text (type=1)

        self._ready = threading.Event()
        self._conn_error = None
        self._pending_chunks = []
        self._lock = threading.Lock()

    def start(self):
        """Launch WebSocket connection in background. Non-blocking."""
        t = threading.Thread(target=self._connect, daemon=True)
        t.start()

    def _connect(self):
        try:
            url = _build_url(self._app_id, self._key_id, self._key_secret, self._vad_eos)
            ws = websocket.create_connection(url)
            ws.settimeout(0.5)
            handshake = json.loads(ws.recv())
            sid = handshake.get("sid", "")
            if self.on_log:
                self.on_log({"event": "handshake", **handshake})
            with self._lock:
                self._ws = ws
                self._sid = sid
                self._running = True
            self._recv_thread = threading.Thread(target=self._receiver, daemon=True)
            self._recv_thread.start()
        except Exception as e:
            self._conn_error = str(e)
            if self.on_error:
                self.on_error(str(e))
        finally:
            self._ready.set()

    def feed(self, chunk: np.ndarray):
        """Buffer or send one 40ms audio chunk."""
        with self._lock:
            if not self._ready.is_set():
                self._pending_chunks.append(chunk.copy())
                return
            pending = self._pending_chunks
            self._pending_chunks = []

        if self._conn_error:
            return

        for c in pending:
            if not self._send_failed:
                try:
                    self._ws.send_binary(c.tobytes())
                except Exception:
                    self._send_failed = True

        if self._ws and not self._send_failed:
            try:
                self._ws.send_binary(chunk.tobytes())
            except Exception:
                self._send_failed = True

    def finish(self) -> str:
        self._ready.wait(timeout=10)
        if self._conn_error or not self._ws:
            self._running = False
            return ""

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

    def _build_accumulated(self):
        """Finalized segments + latest intermediate (if newer than finalized)."""
        parts = []
        for sid in sorted(self._segments.keys()):
            parts.append(self._segments[sid])
        if self._intermediate_texts:
            max_final = max(self._segments.keys()) if self._segments else -1
            latest_sid = max(self._intermediate_texts.keys())
            if latest_sid > max_final:
                parts.append(self._intermediate_texts[latest_sid])
        return "".join(parts)

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

                if st_type == "0" and text:
                    self._segments[seg_id] = text
                    self._intermediate_texts.clear()
                elif st_type == "1" and text:
                    self._intermediate_texts[seg_id] = text

                if is_last:
                    parts = []
                    for sid in sorted(self._segments.keys()):
                        parts.append(self._segments[sid])
                    self._final_text = "".join(parts)
                    self._final_event.set()
                    if self.on_partial:
                        self.on_partial(self._final_text, True, False, -1)
                else:
                    live = self._build_accumulated()
                    if live and self.on_partial:
                        is_segment_final = st_type == "0"
                        self.on_partial(live, False, is_segment_final, seg_id)


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

    def create_session(self, on_partial=None, on_log=None, on_error=None, vad_eos=2000):
        return XfyunStreamingSession(
            self._app_id, self._key_id, self._key_secret,
            on_partial=on_partial, on_log=on_log,
            on_error=on_error, vad_eos=vad_eos,
        )
