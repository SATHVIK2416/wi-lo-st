"""Tests for VLCController."""

import pytest
from src.vlc.vlc_control import VLCController, VLCPlaybackState


def test_vlc_controller_mock_flow():
    ctrl = VLCController()
    assert ctrl.get_state() == VLCPlaybackState.STOPPED

    ctrl.play()
    assert ctrl.get_state() == VLCPlaybackState.PLAYING

    ctrl.pause()
    assert ctrl.get_state() == VLCPlaybackState.PAUSED

    ctrl.set_volume(85)
    assert ctrl.get_volume() == 85

    ctrl.seek(0.5)
    assert ctrl.get_position() == 0.5
