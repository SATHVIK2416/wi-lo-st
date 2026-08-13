"""Windows WASAPI Loopback audio capture source."""

import ctypes
import logging
import platform
import threading
from typing import Optional
import numpy as np

from src.capture.base_source import AudioSource
from src.core.audio_format import AudioFormat

logger = logging.getLogger(__name__)


class WASAPILoopbackSource(AudioSource):
    """Captures default Windows playback endpoint via WASAPI Loopback."""

    def __init__(self, audio_format: Optional[AudioFormat] = None):
        super().__init__(audio_format)
        self._stream = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._is_running:
            return

        if platform.system() != "Windows":
            logger.warning("WASAPI Loopback is only natively supported on Windows.")
            self._is_running = True
            return

        try:
            # Initialize COM in this thread
            ctypes.windll.ole32.CoInitialize(None)
        except Exception as e:
            logger.debug(f"CoInitialize note: {e}")

        try:
            import sounddevice as sd

            # Find default WASAPI output device
            wasapi_api_index = None
            for idx, hostapi in enumerate(sd.query_hostapis()):
                if hostapi['name'] == 'Windows WASAPI':
                    wasapi_api_index = idx
                    break

            default_wasapi_device = None
            if wasapi_api_index is not None:
                default_device_info = sd.query_devices()
                for dev_idx, dev in enumerate(default_device_info):
                    if dev['hostapi'] == wasapi_api_index and dev['max_output_channels'] > 0:
                        default_wasapi_device = dev_idx
                        break

            # Setup WasapiSettings for loopback
            wasapi_settings = sd.WasapiSettings(loopback=True)

            def audio_callback(indata, frames, time_info, status):
                if status:
                    logger.debug(f"WASAPI status: {status}")
                # indata is float32 numpy array
                self._emit_audio(indata.copy())

            self._stream = sd.InputStream(
                samplerate=self.audio_format.sample_rate,
                channels=self.audio_format.channels,
                dtype='float32',
                device=default_wasapi_device,
                extra_settings=wasapi_settings,
                callback=audio_callback,
                blocksize=self.audio_format.duration_to_frames(0.01)  # 10ms blocks
            )
            self._stream.start()
            self._is_running = True
            logger.info("WASAPI Loopback capture started successfully.")
        except Exception as e:
            logger.warning(f"Failed to start hardware WASAPI loopback: {e}. Falling back to virtual silence.")
            self._is_running = True

    def stop(self):
        self._is_running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.debug(f"Error closing stream: {e}")
            self._stream = None

    def read(self, num_frames: int) -> np.ndarray:
        return np.zeros((num_frames, self.audio_format.channels), dtype=np.float32)
