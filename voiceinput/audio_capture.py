import numpy as np
import sounddevice as sd


class AudioRecorder:
    def __init__(self, samplerate=16000, on_chunk=None):
        self.samplerate = samplerate
        self.on_chunk = on_chunk  # callback(bytes) for each 40ms PCM chunk
        self._chunks = []
        self._recording = False
        self._stream = None

    def _callback(self, indata, frames, time, status):
        if status:
            print(f"Audio warning: {status}")
        if self._recording:
            data = indata.copy()
            self._chunks.append(data)
            if self.on_chunk:
                self.on_chunk(data)

    def start(self):
        self._chunks = []
        self._recording = True
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            blocksize=640,  # exactly 40ms per callback at 16kHz
            callback=self._callback,
            dtype="int16",
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        self._recording = False
        self._stream.stop()
        self._stream.close()
        self._stream = None
        if self._chunks:
            audio = np.concatenate(self._chunks, axis=0)
            return audio.flatten()
        return np.array([], dtype="int16")
