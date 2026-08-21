"""4-Timestamp NTP clock offset and RTT estimation with statistical outlier filtering."""

import logging
from collections import deque
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class NTPMeasurement:
    """4-timestamp NTP exchange measurement."""
    t0: float  # Client send time
    t1: float  # Host receive time
    t2: float  # Host transmit time
    t3: float  # Client receive time

    @property
    def is_valid(self) -> bool:
        """Reject bogus exchanges where replies appear before requests.

        A negative raw RTT means the timestamps are inconsistent (clock step,
        tampering, or a mispaired response) and the sample must be discarded;
        clamping it to zero would give it maximal inverse-RTT weight instead.
        """
        return (self.t3 >= self.t0) and ((self.t3 - self.t0) - (self.t2 - self.t1)) >= 0.0

    @property
    def offset(self) -> float:
        """Estimated clock offset theta = ((t1 - t0) + (t2 - t3)) / 2."""
        return ((self.t1 - self.t0) + (self.t2 - self.t3)) / 2.0

    @property
    def rtt(self) -> float:
        """Round trip time RTT = (t3 - t0) - (t2 - t1)."""
        return max(0.0, (self.t3 - self.t0) - (self.t2 - self.t1))


class ClockSyncFilter:
    """NTP Clock Filter with Median Absolute Deviation (MAD) outlier rejection."""

    def __init__(self, window_size: int = 20, min_samples_for_lock: int = 5):
        self.window_size = window_size
        self.min_samples_for_lock = min_samples_for_lock
        self._measurements: deque[NTPMeasurement] = deque(maxlen=window_size)
        self._filtered_offset: float = 0.0
        self._filtered_rtt: float = 0.0
        self._is_locked: bool = False
        self._confidence: float = 0.0

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    @property
    def filtered_offset(self) -> float:
        return self._filtered_offset

    @property
    def filtered_rtt(self) -> float:
        return self._filtered_rtt

    @property
    def confidence(self) -> float:
        return self._confidence

    def add_measurement(self, t0: float, t1: float, t2: float, t3: float) -> tuple:
        """Record a new 4-timestamp measurement and update filtered estimates.

        Args:
            t0: Client request sent time
            t1: Host request received time
            t2: Host reply sent time
            t3: Client reply received time

        Returns:
            Tuple[float, float, bool]: (filtered_offset, filtered_rtt, is_locked)
        """
        meas = NTPMeasurement(t0=t0, t1=t1, t2=t2, t3=t3)
        if not meas.is_valid:
            logger.debug("Discarding inconsistent NTP exchange (t3 < t0 or negative RTT)")
            return self._filtered_offset, self._filtered_rtt, self._is_locked

        self._measurements.append(meas)
        self._recalculate()
        return self._filtered_offset, self._filtered_rtt, self._is_locked

    def _recalculate(self):
        if len(self._measurements) < self.min_samples_for_lock:
            self._is_locked = False
            self._confidence = len(self._measurements) / float(self.min_samples_for_lock)
            if len(self._measurements) > 0:
                self._filtered_offset = np.mean([m.offset for m in self._measurements])
                self._filtered_rtt = np.mean([m.rtt for m in self._measurements])
            return

        rtts = np.array([m.rtt for m in self._measurements])
        offsets = np.array([m.offset for m in self._measurements])

        # Step 1: Select measurements with lowest RTT (NTP standard: lowest 50% RTTs are most accurate)
        median_rtt = np.median(rtts)
        mad_rtt = np.median(np.abs(rtts - median_rtt))

        # Accept measurements within 2.5 * MAD of median RTT or below median
        valid_mask = (rtts <= median_rtt + 2.5 * max(1e-6, mad_rtt))
        if not np.any(valid_mask):
            valid_mask = np.ones(len(rtts), dtype=bool)

        valid_offsets = offsets[valid_mask]
        valid_rtts = rtts[valid_mask]

        # Weight inversely by RTT
        weights = 1.0 / np.maximum(valid_rtts, 1e-4)
        weights /= np.sum(weights)

        self._filtered_offset = float(np.sum(valid_offsets * weights))
        self._filtered_rtt = float(np.median(valid_rtts))

        # Confidence based on offset standard deviation & sample count
        offset_std = float(np.std(valid_offsets))
        # High confidence if std < 2ms (0.002s)
        self._confidence = min(1.0, max(0.1, 1.0 - (offset_std / 0.010)))
        # Lock requires enough samples AND a stable (low-variance) offset estimate;
        # a client on a terrible link must not claim lock just from sample count.
        self._is_locked = len(self._measurements) >= self.min_samples_for_lock and self._confidence >= 0.5

    def reset(self):
        self._measurements.clear()
        self._filtered_offset = 0.0
        self._filtered_rtt = 0.0
        self._is_locked = False
        self._confidence = 0.0
