"""Unit tests for SoftKneeLimiter and fast soft-knee functions."""

import numpy as np
import pytest
from src.core.limiter import SoftKneeLimiter, soft_limit


def test_soft_limit_preserves_low_level_signals():
    x = np.linspace(-0.5, 0.5, 100, dtype=np.float32)
    out = soft_limit(x, threshold=0.9)
    np.testing.assert_allclose(out, x, atol=1e-6)


def test_soft_limit_compresses_hot_signals():
    hot = np.array([-2.0, -1.5, 1.2, 3.0], dtype=np.float32)
    limited = soft_limit(hot, threshold=0.9)
    assert np.all(limited <= 1.0)
    assert np.all(limited >= -1.0)


def test_limiter_lookahead_and_peak_clamp():
    limiter = SoftKneeLimiter(sample_rate=48000, channels=2, threshold_db=-0.5, enabled=True)
    # Sudden explosion pulse: amplitude 2.5
    burst = np.ones((480, 2), dtype=np.float32) * 2.5
    out = limiter.process(burst)

    assert out.shape == (480, 2)
    assert np.all(out <= 1.0)
    assert np.all(out >= -1.0)
    assert limiter.last_gain_reduction_db < 0.0


def test_limiter_bounds_sustained_over_threshold_input():
    threshold = 10.0 ** (-0.2 / 20.0)
    limiter = SoftKneeLimiter(
        sample_rate=48000,
        channels=2,
        threshold_db=-0.2,
        attack_ms=1.0,
        release_ms=50.0,
        enabled=True
    )

    # Constant 2.0 amplitude: far above threshold for a sustained period
    # (long enough for the gain envelope to fully settle past its attack)
    hot = np.ones((12000, 2), dtype=np.float32) * 2.0
    out = limiter.process(hot)

    settled = out[9600:]
    peak_after_attack = float(np.max(np.abs(settled)))

    # The limiter must actually bound output near the threshold (within ~5%),
    # not merely rely on the final hard clip.
    assert peak_after_attack <= threshold * 1.05
    assert peak_after_attack >= threshold * 0.95


def test_limiter_bypass_mode():
    limiter = SoftKneeLimiter(sample_rate=48000, channels=2, enabled=False)
    data = np.array([[1.5, -1.5]], dtype=np.float32)
    out = limiter.process(data)
    np.testing.assert_allclose(out, data)
