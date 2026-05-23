import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from pynput import keyboard

from audio_capture import AudioRecorder
from asr_engine import ASREngine

HOTKEY = keyboard.Key.ctrl_r

_recording = False
_recorder: AudioRecorder | None = None
_session = None
_engine: ASREngine | None = None
_partial_shown = ""
_prev_line_len = 0
_current_seg = -1
_log_file = None


def _now():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _log(msg):
    line = f"[{_now()}] {msg}"
    print(line)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def _on_api_log(msg: dict):
    """Write raw API messages to the log file."""
    if _log_file:
        _log_file.write(json.dumps(msg, ensure_ascii=False) + "\n")
        _log_file.flush()


def _on_partial(text, is_final, is_segment_final=False, seg_id=0):
    global _partial_shown, _prev_line_len
    if is_final:
        sys.stdout.write("\r" + " " * _prev_line_len + "\r")
        sys.stdout.flush()
        if text:
            _log(f"最终结果: {text}")
        _partial_shown = ""
        _prev_line_len = 0
    else:
        if text == _partial_shown:
            return
        _partial_shown = text
        line = f"\r[听写中] {text}"
        if len(line) < _prev_line_len:
            line += " " * (_prev_line_len - len(line))
        _prev_line_len = max(_prev_line_len, len(line))
        sys.stdout.write(line)
        sys.stdout.flush()


def on_press(key):
    global _recording, _recorder, _session

    if key != HOTKEY:
        return

    if not _recording:
        _recording = True
        _t0 = time.perf_counter()

        try:
            _session = _engine.create_session(on_partial=_on_partial, on_log=_on_api_log)
            _session.start()
        except Exception as e:
            _log(f"连接失败: {e}")
            _recording = False
            return

        _recorder = AudioRecorder(on_chunk=_session.feed)
        _recorder.start()

        _log(f"开始录音 + 实时转写 [perf={_t0:.3f}]")
    else:
        _recording = False
        t_stop = time.perf_counter()

        audio = _recorder.stop()
        duration = len(audio) / 16000
        _recorder = None

        _log(f"停止录音, 音频时长={duration:.2f}s, 等待最终结果...")

        t0 = time.perf_counter()
        try:
            final_text = _session.finish()
        except Exception as e:
            _log(f"获取结果失败: {e}")
            final_text = ""
        t1 = time.perf_counter()

        total_ms = (t1 - t0) * 1000
        _log(f"耗时: {total_ms:.0f}ms")
        _session = None


def main():
    global _engine, _log_file

    # Create logs directory and timestamped log file
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_name = datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"
    _log_file = open(log_dir / log_name, "w", encoding="utf-8")

    _log(f"日志文件: {log_name}")
    _log("VoiceInput 启动 (讯飞实时语音转写大模型版)")
    print("按下右 Ctrl 开始录音, 再次按下停止 | Ctrl+C 退出")
    print("-" * 50)

    _engine = ASREngine()

    try:
        with keyboard.Listener(on_press=on_press) as listener:
            try:
                listener.join()
            except KeyboardInterrupt:
                _log("退出")
    finally:
        if _log_file:
            _log_file.close()


if __name__ == "__main__":
    main()
