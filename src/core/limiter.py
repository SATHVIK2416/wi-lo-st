"""Studio-grade soft-knee lookahead peak limiter and dynamics protector."""

import numpy as np


class SoftKneeLimiter:
    """Studio-grade lookahead peak limiter to prevent inter-sample clipping on DACs."""

    def __init__(
        self,
        sample_rate: int = 48000,
        channels: int = 2,
        threshold_db: float = -0.2,
        knee_db: float = 2.0,
        lookahead_ms: float = 3.0,
        attack_ms: float = 1.0,
        release_ms: float = 50.0,
        enabled: bool = True
    ):
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.threshold_db = float(threshold_db)
        self.knee_db = float(knee_db)
        self.lookahead_ms = float(lookahead_ms)
        self.attack_ms = float(attack_ms)
        self.release_ms = float(release_ms)
        self.enabled = bool(enabled)

        # Precompute constants
        self._threshold_linear = 10.0 ** (self.threshold_db / 20.0)
        self._lookahead_frames = max(1, int(round((self.lookahead_ms / 1000.0) * self.sample_rate)))
        self._attack_coeff = np.exp(-1.0 / (max(0.0001, self.attack_ms / 1000.0) * self.sample_rate))
        self._release_coeff = np.exp(-1.0 / (max(0.001, self.release_ms / 1000.0) * self.sample_rate))

        # Internal state
        self._envelope = 0.0
        self._lookahead_buffer = np.zeros((self._lookahead_frames, self.channels), dtype=np.float32)
        self._last_gain_reduction_db = 0.0
        self._max_peak = 0.0

    @property
    def last_gain_reduction_db(self) -> float:
        return self._last_gain_reduction_db

    @property
    def max_peak(self) -> float:
        return self._max_peak

    def process(self, audio_data: np.ndarray) -> np.ndarray:
        """Process incoming audio block through lookahead soft-knee limiter.

        Args:
            audio_data: float32 numpy array shaped (frames, channels) or (frames,)

        Returns:
            np.ndarray: Limited float32 numpy array
        """
        if not self.enabled:
            return audio_data

        data = np.asarray(audio_data, dtype=np.float32)
        orig_ndim = data.ndim
        if orig_ndim == 1:
            data = data.reshape(-1, 1)

        num_frames, ch = data.shape
        if num_frames == 0:
            return audio_data

        # Measure instantaneous peak across channels
        abs_peaks = np.max(np.abs(data), axis=1)
        self._max_peak = max(self._max_peak, float(np.max(abs_peaks)))

        # Envelope follower with asymmetric attack/release
        gains = np.ones(num_frames, dtype=np.float32)
        env = self._envelope
        att = self._attack_coeff
        rel = self._release_coeff
        thresh = self._threshold_linear

        for i in range(num_frames):
            x = abs_peaks[i]
            # Desired target gain based on soft knee
            if x <= thresh:
                target_gain = 1.0
            else:
                # Soft knee compression
                overshoot = x - thresh
                target_gain = thresh / (thresh + np.tanh(overshoot / thresh) * thresh)

            # Attack (gain reduction) is fast; release (gain recovery) is slow
            if target_gain < env:
                env = att * env + (1.0 - att) * target_gain
            else:
                env = rel * env + (1.0 - rel) * target_gain

            gains[i] = env

        self._envelope = float(env)
        min_gain = float(np.min(gains))
        self._last_gain_reduction_db = float(20.0 * np.log10(max(1e-5, min_gain)))

        # Lookahead delay line
        full_stream = np.vstack([self._lookahead_buffer, data])
        delayed_audio = full_stream[:num_frames]
        self._lookahead_buffer = full_stream[num_frames:]

        # Apply gain curve to delayed audio
        limited = delayed_audio * gains[:, np.newaxis]
        # Hard safety clamp to [-1.0, 1.0] to guarantee no DAC overflow
        np.clip(limited, -1.0, 1.0, out=limited)

        if orig_ndim == 1:
            return limited.ravel()
        return limited


def soft_limit(data: np.ndarray, threshold: float = 0.98) -> np.ndarray:
    """Fast stateless soft-knee polynomial limiter for numpy arrays."""
    data = np.asarray(data, dtype=np.float32)
    # Tanh soft-clip transfer
    mask = np.abs(data) > threshold
    if not np.any(mask):
        return data

    out = data.copy()
    sign = np.sign(out[mask])
    mag = np.abs(out[mask])
    # Smooth asymptotic approach to 1.0
    out[mask] = sign * (threshold + (1.0 - threshold) * np.tanh((mag - threshold) / (1.0 - threshold)))
    return out
