"""Pytest fixtures and configuration for SonicSync test suite."""

import pytest
import numpy as np
from src.core.audio_format import AudioFormat, SampleFormat
from src.core.ring_buffer import RingBuffer
from src.core.limiter import SoftKneeLimiter
from src.sync.sync_coordinator import MasterSyncCoordinator


@pytest.fixture
def default_format():
    return AudioFormat(sample_rate=48000, channels=2, sample_format=SampleFormat.FLOAT32)


@pytest.fixture
def default_ring_buffer():
    return RingBuffer(capacity_frames=48000, channels=2)


@pytest.fixture
def default_limiter():
    return SoftKneeLimiter(sample_rate=48000, channels=2, enabled=True)


@pytest.fixture
def default_sync_coordinator():
    return MasterSyncCoordinator(base_target_delay_ms=100.0)


@pytest.fixture
def sine_wave_48k():
    """Generates 100ms of 1kHz sine wave stereo at 48kHz."""
    t = np.linspace(0, 0.1, 4800, endpoint=False, dtype=np.float32)
    sine = (0.5 * np.sin(2.0 * np.pi * 1000.0 * t)).astype(np.float32)
    return np.column_stack([sine, sine])
