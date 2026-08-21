"""Tests for SessionManager (auth), DriftEstimator, and MasterClock NTP conversion."""

import time

import pytest

from src.core.clock import MasterClock
from src.server.auth import SessionManager
from src.sync.drift_estimator import DriftEstimator


class TestSessionManager:
    def test_open_mode_allows_everything(self):
        sm = SessionManager()
        assert not sm.pin_enabled
        assert sm.validate_token(None) is True
        assert sm.validate_token("anything") is True

    def test_pin_mode_requires_token(self):
        sm = SessionManager()
        sm.configure_pin("2468")
        assert sm.pin_enabled
        assert sm.validate_token(None) is False
        assert sm.validate_token("bogus") is False

    def test_pin_exchange_and_validation(self):
        sm = SessionManager()
        sm.configure_pin("2468")
        token = sm.verify_pin_and_issue_token("2468")
        assert token is not None
        assert sm.validate_token(token) is True
        # A different manager with the same PIN must not accept foreign tokens
        assert sm.validate_token("other-token") is False

    def test_wrong_pin_rejected(self):
        sm = SessionManager()
        sm.configure_pin("2468")
        assert sm.verify_pin_and_issue_token("0000") is None

    def test_token_expiry(self):
        sm = SessionManager(token_ttl_sec=0.05)
        sm.configure_pin("2468")  # tokens only gate access when PIN mode is on
        token = sm.generate_token()
        assert sm.validate_token(token) is True
        time.sleep(0.08)
        assert sm.validate_token(token) is False

    def test_pin_lockout_after_repeated_failures(self):
        sm = SessionManager()
        sm.configure_pin("9999")
        for _ in range(SessionManager.MAX_PIN_ATTEMPTS):
            assert sm.verify_pin_and_issue_token("0000") is None
        # Even the correct PIN is refused during lockout
        assert sm.verify_pin_and_issue_token("9999") is None


class TestDriftEstimator:
    def test_detects_known_positive_drift(self):
        est = DriftEstimator(min_history_span_sec=1.0)
        # Client clock gains 25 us per second relative to host -> ~25 ppm
        t0 = 1000.0
        offset0 = 5.0
        drift = 0.0
        n = 40
        for i in range(n):
            t = t0 + i * 0.1
            offset = offset0 + 25e-6 * (t - t0)
            drift = est.add_sample(t, offset)
        assert abs(est.drift_ppm - 25.0) < 3.0
        assert drift == pytest.approx(est.drift_ppm)

    def test_no_drift_on_stable_offset(self):
        est = DriftEstimator(min_history_span_sec=1.0)
        for i in range(40):
            est.add_sample(2000.0 + i * 0.1, 3.3)
        assert abs(est.drift_ppm) < 2.0

    def test_clamped_to_sane_bounds(self):
        est = DriftEstimator()
        est.add_sample(1.0, 0.0)
        est.add_sample(2.0, 5.0)  # absurd jump -> huge raw slope
        assert abs(est.drift_ppm) <= 500.0

    def test_reset(self):
        est = DriftEstimator()
        est.add_sample(1.0, 1.0)
        est.reset()
        assert est.drift_ppm == 0.0


class TestMasterClock:
    def test_ntp_roundtrip(self):
        sec, frac = MasterClock.ntp_timestamp()
        unix = MasterClock.ntp_to_seconds(sec, frac)
        assert abs(unix - time.time()) < 1.0

    def test_now_monotonic_and_ordered(self):
        a = MasterClock.now()
        b = MasterClock.now()
        assert b >= a
