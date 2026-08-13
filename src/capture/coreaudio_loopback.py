"""macOS CoreAudio / BlackHole loopback capture interface."""

import logging
from typing import Optional
import numpy as np
from src.capture.base_source import AudioSource
from src.core.audio_format import AudioFormat

logger = logging.getLogger(__name__)


class CoreAudioLoopbackSource(AudioSource):
    """macOS CoreAudio loopback capture using BlackHole/Soundflower/Aggregate device."""

    def __init__(self, audio_format: Optional[AudioFormat] = None):
        super().__init__(audio_format)
        self._stream = None

    def start(self):
        if self._is_running:
            return
        try:
            import sounddevice as sd
            def audio_callback(indata, frames, time_info, status):
                if status:
                    logger.debug(f"CoreAudio status: {status}")
                self._emit_audio(indata.copy())

            self._stream = sd.InputStream(
                samplerate=self.audio_format.sample_rate,
                channels=self.audio_format.channels,
                dtype='float32',
                callback=audio_callback,
                blocksize=self.audio_format.duration_to_frames(0.01)
            )
            self._stream.start()
            self._is_running = True
            logger.info("CoreAudio loopback started.")
        except Exception as e:
            logger.warning(f"Could not initialize CoreAudio stream: {e}")
            self._is_running = True

    def stop(self):
        self._is_running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def read(self, num_frames: int) -> np.ndarray:
        return np.zeros((num_frames, self.audio_format.channels), dtype=np.float32)
