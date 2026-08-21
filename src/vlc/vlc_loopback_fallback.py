"""Fallback coordinator between direct libVLC audio memory callbacks and OS loopback."""

import logging
import threading
import time
from typing import Optional
import numpy as np

from src.capture.base_source import AudioSource
from src.core.audio_format import AudioFormat
from src.vlc.vlc_source import VLCSource
from src.capture.wasapi_loopback import WASAPILoopbackSource
from src.capture.coreaudio_loopback import CoreAudioLoopbackSource
from src.capture.pulse_monitor import PulseAudioMonitorSource

logger = logging.getLogger(__name__)


class VLCLoopbackFallbackSource(AudioSource):
    """Hybrid VLC source with automatic failover to OS loopback if direct memory callbacks stall.

    The libVLC amem callback path can silently deliver zero audio while the
    player itself reports healthy playback (e.g. callback binding failures).
    A watchdog thread monitors frame liveness while VLC is in a playing state;
    after a sustained stall it switches ingestion to the OS loopback capture.
    """

    STALL_TIMEOUT_SEC = 5.0

    def __init__(self, audio_format: Optional[AudioFormat] = None):
        super().__init__(audio_format)
        self.vlc_source = VLCSource(audio_format)
        self._loopback_source: Optional[AudioSource] = None
        self._use_loopback_fallback = False
        self._last_frame_time: float = 0.0
        self._failovers = 0

        self._watchdog_thread: Optional[threading.Thread] = None

        # Connect VLC callbacks to our emit handler
        self.vlc_source.set_callback(self._on_direct_vlc_audio)

    def _init_loopback(self):
        import platform
        sys_name = platform.system()
        if sys_name == "Windows":
            self._loopback_source = WASAPILoopbackSource(self.audio_format)
        elif sys_name == "Darwin":
            self._loopback_source = CoreAudioLoopbackSource(self.audio_format)
        else:
            self._loopback_source = PulseAudioMonitorSource(self.audio_format)

        self._loopback_source.set_callback(self._on_loopback_audio)

    def _on_direct_vlc_audio(self, data: np.ndarray):
        self._last_frame_time = time.monotonic()
        if not self._use_loopback_fallback:
            self._emit_audio(data)

    def _on_loopback_audio(self, data: np.ndarray):
        if self._use_loopback_fallback:
            self._emit_audio(data)

    def enable_loopback_fallback(self, enable: bool = True):
        self._use_loopback_fallback = bool(enable)
        if self._use_loopback_fallback and self._loopback_source is None:
            self._init_loopback()
            self._loopback_source.start()
        elif not self._use_loopback_fallback and self._loopback_source is not None:
            self._loopback_source.stop()

    def _vlc_is_playing(self) -> bool:
        try:
            return str(self.vlc_source.controller.get_state()).lower() == "playing"
        except Exception:
            return False

    def _watchdog_loop(self):
        while self._is_running:
            time.sleep(1.0)
            if not self._is_running or self._use_loopback_fallback:
                continue
            if not self._vlc_is_playing():
                self._last_frame_time = time.monotonic()
                continue
            stalled_for = time.monotonic() - self._last_frame_time
            if stalled_for > self.STALL_TIMEOUT_SEC:
                logger.warning(
                    f"VLC audio callbacks stalled for {stalled_for:.1f}s while playing; "
                    "failing over to OS loopback capture."
                )
                self._failovers += 1
                self.enable_loopback_fallback(True)

    def start(self):
        self._is_running = True
        self._last_frame_time = time.monotonic()
        self.vlc_source.start()
        if self._use_loopback_fallback and self._loopback_source is not None:
            self._loopback_source.start()
        if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True, name="vlc-fallback-watchdog")
            self._watchdog_thread.start()

    def stop(self):
        self._is_running = False
        self.vlc_source.stop()
        if self._loopback_source is not None:
            self._loopback_source.stop()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=2.0)
            self._watchdog_thread = None

    def read(self, num_frames: int) -> np.ndarray:
        return self.vlc_source.read(num_frames)

    def get_status(self) -> dict:
        status = self.vlc_source.get_status()
        status["loopback_fallback_active"] = self._use_loopback_fallback
        status["fallback_failovers"] = self._failovers
        return status
