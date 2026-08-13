"""Unit tests for PI PLL watermark controller."""

import pytest
from src.sync.pll_controller import PLLController


def test_pll_steady_state_target():
    pll = PLLController(target_delay_sec=0.100, max_rate_adjustment=0.0005)
    # If delay is exactly target 100ms, ratio should stay near 1.0
    ratio = pll.update(0.100, dt=0.1)
    assert abs(ratio - 1.0) < 1e-5


def test_pll_speedup_on_overfill():
    pll = PLLController(target_delay_sec=0.100, max_rate_adjustment=0.0005)
    # Buffer has 150ms (> 100ms) -> needs to speed up (r > 1.0)
    for _ in range(5):
        ratio = pll.update(0.150, dt=0.1)
    assert ratio > 1.0
    # Must never exceed ±0.05% (1.0005)
    assert ratio <= 1.000501


def test_pll_slowdown_on_underfill():
    pll = PLLController(target_delay_sec=0.100, max_rate_adjustment=0.0005)
    # Buffer has 60ms (< 100ms) -> needs to slow down (r < 1.0)
    for _ in range(5):
        ratio = pll.update(0.060, dt=0.1)
    assert ratio < 1.0
    assert ratio >= 0.999499
