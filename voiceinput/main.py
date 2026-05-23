import sys
import time
from datetime import datetime

from pynput import keyboard

from audio_capture import AudioRecorder
from asr_engine import ASREngine

HOTKEY = keyboard.Key.ctrl_r

_recording = False
_recorder: AudioRecorder | None = None
_engine: ASREngine | None = None
_log = []


def _now():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _log_line(msg):
    ts = _now()
    line = f"[{ts}] {msg}"
    _log.append(line)
    print(line)


def on_press(key):
    global _recording, _recorder, _engine

    if key != HOTKEY:
        return

    if not _recording:
        _recording = True
        _t0 = time.perf_counter()
        _recorder = AudioRecorder()
        _recorder.start()
        _log_line(f"按下右 Ctrl 开始录音 [perf={_t0:.3f}]")
    else:
        _recording = False
        t_stop = time.perf_counter()
        audio = _recorder.stop()
        duration = len(audio) / 16000
        _recorder = None

        _log_line(f"再次按下右 Ctrl 停止录音, 音频时长={duration:.2f}s")

        if len(audio) > 0:
            t0 = time.perf_counter()
            text = _engine.recognize(audio)
            t1 = time.perf_counter()
            recog_ms = (t1 - t0) * 1000
            total_ms = (t1 - t_stop) * 1000
            _log_line(f"识别完成: \"{text}\"")
            _log_line(f"耗时: 识别={recog_ms:.0f}ms, 停止到出字={total_ms:.0f}ms")
        else:
            _log_line("未检测到语音")


def main():
    global _engine
    print(f"[{_now()}] VoiceInput 启动")
    print("按下右 Ctrl 开始录音, 再次按下停止识别 | Ctrl+C 退出")
    print("-" * 50)

    _engine = ASREngine()

    with keyboard.Listener(on_press=on_press) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            _log_line("退出")


if __name__ == "__main__":
    main()
