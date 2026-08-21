"""Tests for VLCSyncSidecar."""

import pytest
from src.clients.vlc_sync_sidecar import VLCSyncSidecar


def test_vlc_sidecar_init():
    sidecar = VLCSyncSidecar(host_ip="127.0.0.1", host_port=8080)
    assert sidecar.host_ip == "127.0.0.1"
    assert sidecar.rc_port == 4212
    assert sidecar.stream_url == "rtp://@239.255.0.1:5006"
