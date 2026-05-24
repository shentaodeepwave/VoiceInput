import numpy as np


class VoiceActivityDetector:
    def __init__(self, silence_seconds: float = 1.5, threshold: float = 500):
        self._frame_size = 640  # 40ms at 16kHz
        self._silence_frames = max(1, int(16000 * silence_seconds / self._frame_size))
        self._threshold = threshold
        self._consecutive_silence = 0
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool):
        self._enabled = val
        self.reset()

    @property
    def silence_seconds(self) -> float:
        return self._silence_frames * self._frame_size / 16000

    @silence_seconds.setter
    def silence_seconds(self, seconds: float):
        self._silence_frames = max(1, int(16000 * seconds / self._frame_size))

    def process_chunk(self, chunk: np.ndarray) -> bool:
        if not self._enabled:
            self._consecutive_silence = 0
            return False

        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        if rms < self._threshold:
            self._consecutive_silence += 1
            return self._consecutive_silence >= self._silence_frames
        else:
            self._consecutive_silence = 0
            return False

    def reset(self):
        self._consecutive_silence = 0
