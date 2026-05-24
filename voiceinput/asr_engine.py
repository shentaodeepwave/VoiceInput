import hmac
import hashlib
import base64
import json
import threading
import uuid
from urllib.parse import urlencode, quote
from datetime import datetime, timezone, timedelta

import numpy as np
import websocket


def _build_url(api_url: str, app_id: str, access_key_id: str, access_key_secret: str) -> str:
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
    return f"{api_url}?{urlencode(params, quote_via=quote)}"


def _extract_text(data: dict) -> str:
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
    def __init__(self, app_id: str, access_key_id: str, access_key_secret: str,
                 api_url: str, on_partial=None, on_error=None):
        self._app_id = app_id
        self._key_id = access_key_id
        self._key_secret = access_key_secret
        self._api_url = api_url
        self.on_partial = on_partial
        self.on_error = on_error

        self._ws = None
        self._sid = None
        self._running = False
        self._final_text = ""
        self._final_event = threading.Event()
        self._recv_thread = None
        self._send_failed = False
        self._segments: dict[int, str] = {}

    @property
    def is_send_failed(self) -> bool:
        return self._send_failed

    def start(self):
        url = _build_url(self._api_url, self._app_id, self._key_id, self._key_secret)
        self._ws = websocket.create_connection(url)
        self._ws.settimeout(0.5)

        handshake = json.loads(self._ws.recv())
        self._sid = handshake.get("sid", "")

        self._running = True
        self._recv_thread = threading.Thread(target=self._receiver, daemon=True)
        self._recv_thread.start()

    def feed(self, chunk: np.ndarray):
        if self._ws and not self._send_failed:
            try:
                self._ws.send_binary(chunk.tobytes())
            except Exception:
                self._send_failed = True
                if self.on_error:
                    self.on_error("网络中断")

    def finish(self) -> str:
        end_msg = {"end": True, "sessionId": self._sid}
        if not self._send_failed:
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
                if self._running and self.on_error:
                    self.on_error("网络中断")
                break

            if msg.get("msg_type") == "result" and msg.get("res_type") == "asr":
                data = msg.get("data", {})
                text = _extract_text(data)
                seg_id = data.get("seg_id", 0)
                st_type = data.get("cn", {}).get("st", {}).get("type", "1")
                is_last = data.get("ls", False)

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


class ASREngine:
    def __init__(self, config):
        self._cfg = config
        self._app_id = config.app_id
        self._key_id = config.access_key_id
        self._key_secret = config.access_key_secret
        self._api_url = config.api_url

    def create_session(self, on_partial=None, on_error=None):
        return XfyunStreamingSession(
            self._app_id, self._key_id, self._key_secret,
            api_url=self._api_url,
            on_partial=on_partial,
            on_error=on_error,
        )
