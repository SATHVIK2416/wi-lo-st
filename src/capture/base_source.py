"""Abstract base class for audio capture sources."""

from abc import ABC, abstractmethod
from typing import Optional, Callable
import numpy as np
from src.core.audio_format import AudioFormat


class AudioSource(ABC):
    """Abstract base class for all SonicSync audio input sources."""

    def __init__(self, audio_format: Optional[AudioFormat] = None):
        self.audio_format = audio_format or AudioFormat()
        self._is_running = False
        self._callback: Optional[Callable[[np.ndarray], None]] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    def set_callback(self, callback: Callable[[np.ndarray], None]):
        """Set callback function invoked when new audio block is ready."""
        self._callback = callback

    @abstractmethod
    def start(self):
        """Start audio ingestion."""
        pass

    @abstractmethod
    def stop(self):
        """Stop audio ingestion."""
        pass

    @abstractmethod
    def read(self, num_frames: int) -> np.ndarray:
        """Synchronously read audio frames (if not using callback model)."""
        pass

    def _emit_audio(self, data: np.ndarray):
        """Internal helper to pass data to registered callback."""
        if self._callback is not None:
            self._callback(data)
