"""Integration tests for multi-client lifecycle and coordinator reporting."""

import time
import pytest
from src.sync.sync_coordinator import MasterSyncCoordinator


def test_coordinator_lifecycle():
    coord = MasterSyncCoordinator(base_target_delay_ms=100.0)
    assert coord.get_sync_report()["active_clients"] == 0

    # Register 3 clients
    coord.update_client_report("client_1", "web", "192.168.1.10", buffer_depth_ms=100.0, rtt_ms=10.0, is_locked=True)
    coord.update_client_report("client_2", "vlc_sidecar", "192.168.1.11", buffer_depth_ms=120.0, rtt_ms=15.0, is_locked=True)
    coord.update_client_report("client_3", "native", "192.168.1.12", buffer_depth_ms=98.0, rtt_ms=5.0, is_locked=True)

    report = coord.get_sync_report()
    assert report["active_clients"] == 3
    assert report["locked_clients"] == 3
    assert report["health_status"] == "Optimal"
    assert len(report["clients"]) == 3

    # Remove 1 client
    coord.remove_client("client_1")
    assert len(coord.get_clients()) == 2
