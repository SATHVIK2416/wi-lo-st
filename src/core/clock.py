"""High-resolution monotonic master clock and timestamp manager."""

import time


class MasterClock:
    """High-resolution master clock for presentation timestamp (PTS) generation."""

    def __init__(self):
        self._epoch_offset = time.time() - time.perf_counter()
        self._start_perf = time.perf_counter()

    @staticmethod
    def now() -> float:
        """Return current monotonic time in fractional seconds with sub-microsecond precision."""
        return time.perf_counter()

    @staticmethod
    def now_ms() -> float:
        """Return current monotonic time in milliseconds."""
        return time.perf_counter() * 1000.0

    @staticmethod
    def now_wall_utc() -> float:
        """Return current wall-clock UTC time in seconds."""
        return time.time()

    def get_pts(self) -> float:
        """Generate Presentation Timestamp (PTS) relative to clock start."""
        return time.perf_counter() - self._start_perf

    @staticmethod
    def ntp_timestamp() -> tuple[int, int]:
        """Return (seconds_since_1900, fractional_seconds_32bit) for NTP and RTCP headers."""
        # NTP epoch is Jan 1, 1900. Unix epoch is Jan 1, 1970.
        # Difference = 2208988800 seconds (70 years + 17 leap days)
        NTP_DELTA = 2208988800
        now = time.time()
        ntp_time = now + NTP_DELTA
        sec = int(ntp_time)
        frac = int((ntp_time - sec) * (1 << 32))
        return sec, frac

    @staticmethod
    def ntp_to_seconds(sec: int, frac: int) -> float:
        """Convert NTP timestamp tuple back to Unix seconds."""
        NTP_DELTA = 2208988800
        return (sec - NTP_DELTA) + (frac / float(1 << 32))
