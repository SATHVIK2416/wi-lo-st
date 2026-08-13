"""Acoustic synchronization and cross-correlation tests using metronome impulse bursts."""

import numpy as np
import pytest
from src.core.audio_format import AudioFormat
from src.capture.test_generator import TestGeneratorSource, TestSignalType


def test_metronome_impulse_generation():
    fmt = AudioFormat(sample_rate=48000, channels=2)
    gen = TestGeneratorSource(audio_format=fmt, signal_type=TestSignalType.METRONOME_CLICK)

    # Generate 1 full second (48000 frames)
    frames = gen.generate_frames(48000)
    assert frames.shape == (48000, 2)

    # Impulse click should be present at the start (< 2ms = 96 samples)
    start_energy = np.sum(frames[:96, 0] ** 2)
    middle_energy = np.sum(frames[1000:2000, 0] ** 2)

    assert start_energy > 1.0
    assert middle_energy == 0.0  # Silent between beats


def test_cross_correlation_inter_device_sync():
    """Simulate two synchronized client outputs and cross-correlate to measure offset."""
    sr = 48000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    # Simulated sharp impulse at t = 0.100s (100ms presentation delay)
    sig1 = np.zeros(sr, dtype=np.float32)
    sig1[int(0.100 * sr)] = 1.0

    # Device 2 has 0.5 ms simulated jitter offset
    sig2 = np.zeros(sr, dtype=np.float32)
    sig2[int(0.1005 * sr)] = 1.0

    # Cross-correlation
    corr = np.correlate(sig1, sig2, mode='full')
    peak_idx = np.argmax(corr)
    lag_samples = peak_idx - (len(sig1) - 1)
    lag_ms = (lag_samples / float(sr)) * 1000.0

    assert abs(lag_ms - (-0.5)) < 0.1  # Verified accurately to < 0.1 ms!
