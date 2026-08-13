"""Hardware quartz oscillator clock drift estimator (in parts-per-million: ppm)."""

from collections import deque
from typing import Tuple
import numpy as np


class DriftEstimator:
    """Estimates frequency skew (drift in ppm) using linear regression over timestamp history."""

    def __init__(self, history_size: int = 60, min_history_span_sec: float = 5.0):
        self.history_size = history_size
        self.min_history_span_sec = min_history_span_sec
        # Store tuples of (local_time, estimated_offset)
        self._history: deque[Tuple[float, float]] = deque(maxlen=history_size)
        self._drift_ppm: float = 0.0
        self._drift_rate: float = 0.0  # Unitless slope (e.g. 5e-6 = 5 ppm)

    @property
    def drift_ppm(self) -> float:
        """Drift in parts-per-million (positive means client clock runs faster than host)."""
        return self._drift_ppm

    @property
    def drift_rate(self) -> float:
        """Unitless drift slope."""
        return self._drift_rate

    def add_sample(self, current_time: float, offset: float) -> float:
        """Record a time/offset pair and update drift estimate.

        Args:
            current_time: Monotonic local time in seconds
            offset: Current estimated clock offset (host - client) in seconds

        Returns:
            float: Updated drift in ppm
        """
        self._history.append((float(current_time), float(offset)))

        if len(self._history) < 5:
            return self._drift_ppm

        times = np.array([pt[0] for pt in self._history])
        offsets = np.array([pt[1] for pt in self._history])

        time_span = times[-1] - times[0]
        if time_span < self.min_history_span_sec:
            return self._drift_ppm

        # Linear regression: offset = slope * time + intercept
        # slope = d(offset)/dt = (freq_host - freq_client) / freq_host
        t_mean = np.mean(times)
        o_mean = np.mean(offsets)

        t_diff = times - t_mean
        o_diff = offsets - o_mean

        denom = np.sum(t_diff ** 2)
        if denom > 1e-9:
            slope = float(np.sum(t_diff * o_diff) / denom)
            # Clamp to physically plausible quartz oscillator drift (-500 ppm to +500 ppm)
            self._drift_rate = float(np.clip(slope, -0.0005, 0.0005))
            self._drift_ppm = self._drift_rate * 1e6

        return self._drift_ppm

    def reset(self):
        self._history.clear()
        self._drift_ppm = 0.0
        self._drift_rate = 0.0
