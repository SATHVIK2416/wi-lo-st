"""Unit tests for RingBuffer."""

import numpy as np
import pytest
from src.core.ring_buffer import RingBuffer


def test_ring_buffer_write_and_read():
    rb = RingBuffer(capacity_frames=1000, channels=2)
    assert rb.available_read() == 0
    assert rb.available_write() == 1000

    data = np.ones((200, 2), dtype=np.float32) * 0.75
    written = rb.write(data)
    assert written == 200
    assert rb.available_read() == 200
    assert rb.available_write() == 800

    read_data = rb.read(200)
    assert read_data.shape == (200, 2)
    np.testing.assert_allclose(read_data, data)
    assert rb.available_read() == 0


def test_ring_buffer_wraparound():
    rb = RingBuffer(capacity_frames=500, channels=2)
    data1 = np.ones((400, 2), dtype=np.float32)
    rb.write(data1)
    rb.read(300)  # Read 300, 100 left, write pointer at 400

    data2 = np.ones((350, 2), dtype=np.float32) * 2.0
    rb.write(data2)  # Writes 100 to end, wraps and writes 250 to start

    assert rb.available_read() == 450
    out = rb.read(450)
    assert out.shape == (450, 2)
    np.testing.assert_allclose(out[:100], 1.0)
    np.testing.assert_allclose(out[100:], 2.0)


def test_ring_buffer_underrun_silence_padding():
    rb = RingBuffer(capacity_frames=500, channels=2)
    data = np.ones((50, 2), dtype=np.float32)
    rb.write(data)

    out = rb.read(100, fill_silence=True)
    assert out.shape == (100, 2)
    np.testing.assert_allclose(out[:50], 1.0)
    np.testing.assert_allclose(out[50:], 0.0)
    assert rb.underruns == 50


def test_ring_buffer_overrun_tracking():
    rb = RingBuffer(capacity_frames=100, channels=2)
    data = np.ones((150, 2), dtype=np.float32)
    rb.write(data)
    assert rb.overruns > 0
    assert rb.available_read() == 100
