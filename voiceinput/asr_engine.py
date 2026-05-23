import os
import numpy as np
from faster_whisper import WhisperModel

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_model():
    candidates = [
        os.path.join(PROJECT_ROOT, "models", "faster-whisper-small"),
        os.path.join(PROJECT_ROOT, "models", "faster-whisper-tiny"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return "tiny"


class ASREngine:
    def __init__(self, model_path=None):
        if model_path is None:
            model_path = _find_model()
        self.model = WhisperModel(model_path, device="cpu", compute_type="int8")

    def recognize(self, audio: np.ndarray) -> str:
        if len(audio) == 0:
            return ""
        audio = audio.astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(audio, beam_size=5)
        return " ".join(s.text.strip() for s in segments)
