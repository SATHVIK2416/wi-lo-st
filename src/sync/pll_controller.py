"""Proportional-Integral (PI) Phase-Locked Loop (PLL) watermark controller."""

import numpy as np


class PLLController:
    """PI Controller for adaptive micro-resampling and playout buffer watermark stabilization."""

    def __init__(
        self,
        target_delay_sec: float = 0.100,  # 100.0 ms target presentation delay
        kp: float = 0.05,                  # Proportional gain
        ki: float = 0.005,                 # Integral gain
        max_rate_adjustment: float = 0.0005,  # Max ±0.05% (500 ppm)
        max_slew_per_sec: float = 0.0001     # Slew rate limit to prevent pitch modulations
    ):
        self.target_delay_sec = float(target_delay_sec)
        self.kp = float(kp)
        self.ki = float(ki)
        self.max_rate_adjustment = float(max_rate_adjustment)
        self.max_slew_per_sec = float(max_slew_per_sec)

        self._integral_error = 0.0
        self._current_ratio = 1.0
        self._last_error = 0.0
        self._last_update_time = 0.0

    @property
    def current_ratio(self) -> float:
        """Current resampling ratio (e.g. 1.0002 = speed up playback by 0.02%)."""
        return self._current_ratio

    @property
    def error_ms(self) -> float:
        """Last timing error in milliseconds."""
        return self._last_error * 1000.0

    def update(self, current_buffer_delay_sec: float, dt: float = 0.1) -> float:
        """Update PLL state and calculate new resample ratio.

        Args:
            current_buffer_delay_sec: Measured playout buffer depth / delay in seconds
            dt: Elapsed time since last update in seconds

        Returns:
            float: Recommended resampling ratio r around 1.0
        """
        dt = max(0.001, min(1.0, float(dt)))
        # Error: positive if buffer has more delay than target (need to speed up, r > 1.0)
        error = current_buffer_delay_sec - self.target_delay_sec
        self._last_error = error

        # Integrate error with anti-windup
        self._integral_error += error * dt
        # Clamp integral term to prevent saturation
        max_integral = self.max_rate_adjustment / max(1e-6, self.ki)
        self._integral_error = float(np.clip(self._integral_error, -max_integral, max_integral))

        # PI control law
        raw_adjustment = (self.kp * error) + (self.ki * self._integral_error)

        # Hard clamp rate adjustment to ±0.05%
        clamped_adjustment = float(np.clip(raw_adjustment, -self.max_rate_adjustment, self.max_rate_adjustment))
        target_ratio = 1.0 + clamped_adjustment

        # Slew rate limiting to smooth transitions
        max_step = self.max_slew_per_sec * dt
        ratio_delta = np.clip(target_ratio - self._current_ratio, -max_step, max_step)
        self._current_ratio += float(ratio_delta)

        return self._current_ratio

    def reset(self):
        self._integral_error = 0.0
        self._current_ratio = 1.0
        self._last_error = 0.0
