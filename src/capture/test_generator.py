"""Precision synthetic test audio generator for acoustic calibration and sync testing."""

import time
import threading
from typing import Optional
import numpy as np
from src.capture.base_source import AudioSource
from src.core.audio_format import AudioFormat


class TestSignalType:
    SINE_1KHZ = "sine_1khz"
    PINK_NOISE = "pink_noise"
    STEREO_SWEEP = "stereo_sweep"
    METRONOME_CLICK = "metronome_click"
    SILENCE = "silence"


class TestGeneratorSource(AudioSource):
    """High-precision synthetic test audio generator."""
    __test__ = False

    def __init__(
        self,
        audio_format: Optional[AudioFormat] = None,
        signal_type: str = TestSignalType.SINE_1KHZ,
        frequency: float = 1000.0,
        amplitude: float = 0.5
    ):
        super().__init__(audio_format)
        self.signal_type = signal_type
        self.frequency = float(frequency)
        self.amplitude = float(amplitude)

        self._phase = 0.0
        self._sample_index = 0
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def set_signal_type(self, signal_type: str, frequency: float = 1000.0, amplitude: float = 0.5):
        """Update test signal parameters dynamically."""
        self.signal_type = signal_type
        self.frequency = float(frequency)
        self.amplitude = float(amplitude)

    def generate_frames(self, num_frames: int) -> np.ndarray:
        """Generate a block of test audio frames.

        Args:
            num_frames: Number of multi-channel frames to produce

        Returns:
            np.ndarray: float32 array shaped (num_frames, channels)
        """
        sr = self.audio_format.sample_rate
        ch = self.audio_format.channels
        out = np.zeros((num_frames, ch), dtype=np.float32)

        if self.signal_type == TestSignalType.SINE_1KHZ or self.signal_type == "sine":
            # Generate pure continuous sine wave
            t = (self._sample_index + np.arange(num_frames)) / float(sr)
            sine = (self.amplitude * np.sin(2.0 * np.pi * self.frequency * t)).astype(np.float32)
            for c in range(ch):
                out[:, c] = sine

        elif self.signal_type == TestSignalType.PINK_NOISE or self.signal_type == "pink":
            # Voss-McCartney or filtered white noise approximation for 1/f slope
            white = np.random.uniform(-1.0, 1.0, size=(num_frames, ch)).astype(np.float32)
            # Simple 1st-order IIR pink filter
            b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
            a = [1.0, -2.494956002, 2.017265875, -0.522189400]
            # Fast cumulative convolution or approximation
            for c in range(ch):
                filtered = np.convolve(white[:, c], [0.3, 0.25, 0.2, 0.15, 0.1], mode='same')
                out[:, c] = self.amplitude * (filtered / (np.max(np.abs(filtered)) + 1e-6))

        elif self.signal_type == TestSignalType.STEREO_SWEEP or self.signal_type == "sweep":
            # Sine wave sweeping 100 Hz to 10 kHz with alternating left/right pan
            t = (self._sample_index + np.arange(num_frames)) / float(sr)
            sweep_period = 4.0  # 4 seconds sweep
            sweep_phase = (t % sweep_period) / sweep_period
            f_inst = 100.0 * (100.0 ** sweep_phase)  # 100 Hz to 10,000 Hz
            sine = (self.amplitude * np.sin(2.0 * np.pi * f_inst * t)).astype(np.float32)
            if ch >= 2:
                pan_left = np.cos(np.pi * sweep_phase * 2.0) * 0.5 + 0.5
                pan_right = 1.0 - pan_left
                out[:, 0] = sine * pan_left.astype(np.float32)
                out[:, 1] = sine * pan_right.astype(np.float32)
            else:
                out[:, 0] = sine

        elif self.signal_type == TestSignalType.METRONOME_CLICK or self.signal_type == "metronome":
            # 1 Hz metronome: 1 ms sharp 2.5 kHz burst at the start of each second
            indices = self._sample_index + np.arange(num_frames)
            second_offset = indices % sr
            click_duration_samples = int(sr * 0.002)  # 2 ms pulse
            click_mask = second_offset < click_duration_samples

            t_burst = (second_offset[click_mask]) / float(sr)
            click_wave = self.amplitude * np.sin(2.0 * np.pi * 2500.0 * t_burst) * np.hanning(len(t_burst))

            for c in range(ch):
                out[click_mask, c] = click_wave.astype(np.float32)

        elif self.signal_type == TestSignalType.SILENCE:
            out.fill(0.0)

        self._sample_index += num_frames
        return out

    def read(self, num_frames: int) -> np.ndarray:
        return self.generate_frames(num_frames)

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()

        # Background thread feeding real-time blocks to callback if registered
        def worker():
            block_frames = self.audio_format.duration_to_frames(0.01)  # 10ms chunks
            sleep_duration = 0.01

            while not self._stop_event.is_set():
                t0 = time.perf_counter()
                chunk = self.generate_frames(block_frames)
                self._emit_audio(chunk)
                elapsed = time.perf_counter() - t0
                to_sleep = max(0.0001, sleep_duration - elapsed)
                time.sleep(to_sleep)

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()

    def stop(self):
        self._is_running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
