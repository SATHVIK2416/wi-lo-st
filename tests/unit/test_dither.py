"""Unit tests for TPDF audio dithering."""

import numpy as np
import pytest
from src.core.dither import apply_tpdf_dither


def test_tpdf_dither_preserves_range():
    data = np.linspace(-0.9, 0.9, 1000, dtype=np.float32)
    dithered = apply_tpdf_dither(data, bit_depth=16)
    assert np.all(dithered >= -1.0)
    assert np.all(dithered <= 1.0)


def test_tpdf_dither_noise_properties():
    # Constant DC level
    dc = np.zeros(10000, dtype=np.float32)
    dithered = apply_tpdf_dither(dc, bit_depth=16)
    noise = dithered - dc
    # Mean of TPDF noise is ~0
    assert abs(np.mean(noise)) < 1e-4
    # Max noise within 2 LSBs
    lsb_16 = 1.0 / 32767.0
    assert np.max(np.abs(noise)) <= (2.0 * lsb_16 + 1e-6)
