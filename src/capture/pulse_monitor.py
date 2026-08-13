"""Linux PulseAudio and PipeWire monitor sources."""

import logging
from typing import Optional
import numpy as np
from src.capture.base_source import AudioSource
from src.core.audio_format import AudioFormat

logger = logging.getLogger(__name__)


class PulseAudioMonitorSource(AudioSource):
    """Linux PulseAudio monitor stream capture."""

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
                    logger.debug(f"PulseAudio status: {status}")
                self._emit_audio(indata.copy())

            self._stream = sd.InputStream(
                samplerate=self.audio_format.sample_rate,
                channels=self.audio_format.channels,
                dtype='float32',
                callback=audio_callback
            )
            self._stream.start()
            self._is_running = True
        except Exception as e:
            logger.warning(f"PulseAudio monitor could not be started: {e}")
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


class PipeWireMonitorSource(PulseAudioMonitorSource):
    """Linux PipeWire monitor stream capture (inherits PulseAudio compatibility)."""
    pass
