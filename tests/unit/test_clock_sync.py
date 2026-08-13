"""Unit tests for NTP clock offset filter and MAD outlier rejection."""

import pytest
from src.sync.clock_filter import ClockSyncFilter, NTPMeasurement


def test_ntp_measurement_math():
    # t0=10.0, t1=10.05, t2=10.05, t3=10.10
    # offset = ((10.05 - 10.0) + (10.05 - 10.10)) / 2 = (0.05 - 0.05) / 2 = 0.0
    # rtt = (10.10 - 10.0) - (10.05 - 10.05) = 0.10
    meas = NTPMeasurement(t0=10.0, t1=10.05, t2=10.05, t3=10.10)
    assert abs(meas.offset - 0.0) < 1e-6
    assert abs(meas.rtt - 0.10) < 1e-6


def test_clock_filter_outlier_rejection():
    filter_engine = ClockSyncFilter(window_size=10, min_samples_for_lock=4)

    # 5 good measurements with 10ms offset and 10ms RTT
    for i in range(5):
        t0 = i * 1.0
        filter_engine.add_measurement(t0=t0, t1=t0 + 0.015, t2=t0 + 0.015, t3=t0 + 0.010)

    # 1 huge Wi-Fi jitter spike with 300ms RTT
    filter_engine.add_measurement(t0=10.0, t1=10.200, t2=10.200, t3=10.300)

    assert filter_engine.is_locked
    # Filtered offset should remain close to ~10ms (0.010s), rejecting the spike
    assert abs(filter_engine.filtered_offset - 0.010) < 0.005
