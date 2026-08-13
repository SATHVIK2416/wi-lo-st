"""Unit tests for audio format representations and conversions."""

import numpy as np
import pytest
from src.core.audio_format import (
    AudioFormat,
    SampleFormat,
    numpy_float32_to_pcm,
    pcm_to_numpy_float32
)


def test_audio_format_properties():
    fmt = AudioFormat(sample_rate=48000, channels=2, sample_format=SampleFormat.FLOAT32)
    assert fmt.bytes_per_sample == 4
    assert fmt.frame_size == 8
    assert fmt.bytes_per_second == 48000 * 8
    assert fmt.duration_to_frames(0.1) == 4800
    assert fmt.frames_to_duration(4800) == 0.1


def test_float32_conversion_roundtrip():
    orig = np.array([[0.0, 0.5], [-0.5, 1.0], [-1.0, 0.25]], dtype=np.float32)
    raw = numpy_float32_to_pcm(orig, SampleFormat.FLOAT32)
    recovered = pcm_to_numpy_float32(raw, SampleFormat.FLOAT32, channels=2)
    np.testing.assert_allclose(recovered, orig, atol=1e-6)


def test_int16_conversion_roundtrip():
    orig = np.array([[0.0, 0.5], [-0.5, 1.0], [-1.0, 0.25]], dtype=np.float32)
    raw = numpy_float32_to_pcm(orig, SampleFormat.INT16)
    recovered = pcm_to_numpy_float32(raw, SampleFormat.INT16, channels=2)
    # Int16 has quantization error < 1/32767 ≈ 3e-5
    np.testing.assert_allclose(recovered, orig, atol=1e-4)


def test_int24_conversion_roundtrip():
    orig = np.array([[0.0, 0.75], [-0.75, 0.99], [-0.99, 0.123]], dtype=np.float32)
    raw = numpy_float32_to_pcm(orig, SampleFormat.INT24)
    assert len(raw) == orig.shape[0] * 2 * 3  # 3 bytes per sample
    recovered = pcm_to_numpy_float32(raw, SampleFormat.INT24, channels=2)
    np.testing.assert_allclose(recovered, orig, atol=1e-6)


def test_clipping_bounds():
    out_of_bounds = np.array([-2.5, 3.8], dtype=np.float32)
    raw = numpy_float32_to_pcm(out_of_bounds, SampleFormat.FLOAT32)
    recovered = pcm_to_numpy_float32(raw, SampleFormat.FLOAT32, channels=1)
    assert np.all(recovered <= 1.0)
    assert np.all(recovered >= -1.0)
