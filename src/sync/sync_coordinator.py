"""Master synchronization coordinator and multi-endpoint telemetry aggregator."""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np


@dataclass
class ClientSyncTelemetry:
    """Live synchronization statistics for a connected listener endpoint."""
    client_id: str
    client_type: str = "web"  # "web", "native", "vlc_sidecar", "vlc_direct"
    ip_address: str = ""
    buffer_depth_ms: float = 100.0
    clock_offset_ms: float = 0.0
    rtt_ms: float = 0.0
    drift_ppm: float = 0.0
    is_locked: bool = False
    underruns: int = 0
    overruns: int = 0
    packet_loss_rate: float = 0.0
    resample_ratio: float = 1.0
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "client_id": self.client_id,
            "client_type": self.client_type,
            "ip_address": self.ip_address,
            "buffer_depth_ms": round(self.buffer_depth_ms, 2),
            "clock_offset_ms": round(self.clock_offset_ms, 2),
            "rtt_ms": round(self.rtt_ms, 2),
            "drift_ppm": round(self.drift_ppm, 2),
            "is_locked": self.is_locked,
            "underruns": self.underruns,
            "overruns": self.overruns,
            "packet_loss_rate": round(self.packet_loss_rate, 4),
            "resample_ratio": round(self.resample_ratio, 6),
            "last_seen_sec_ago": round(time.time() - self.last_seen, 1),
        }


class MasterSyncCoordinator:
    """Coordinates global presentation synchronization across all connected clients."""

    def __init__(self, base_target_delay_ms: float = 100.0):
        self.base_target_delay_ms = float(base_target_delay_ms)
        self._clients: Dict[str, ClientSyncTelemetry] = {}
        self._client_timeout_sec = 15.0

    @property
    def target_playout_delay_sec(self) -> float:
        """Global target presentation delay in seconds."""
        return self.base_target_delay_ms / 1000.0

    def update_client_report(
        self,
        client_id: str,
        client_type: str = "web",
        ip_address: str = "",
        buffer_depth_ms: float = 100.0,
        clock_offset_ms: float = 0.0,
        rtt_ms: float = 0.0,
        drift_ppm: float = 0.0,
        is_locked: bool = True,
        underruns: int = 0,
        overruns: int = 0,
        packet_loss_rate: float = 0.0,
        resample_ratio: float = 1.0
    ):
        """Update or register telemetry from a client."""
        client = self._clients.get(client_id)
        if client is None:
            client = ClientSyncTelemetry(client_id=client_id, client_type=client_type, ip_address=ip_address)
            self._clients[client_id] = client

        client.client_type = client_type
        if ip_address:
            client.ip_address = ip_address
        client.buffer_depth_ms = buffer_depth_ms
        client.clock_offset_ms = clock_offset_ms
        client.rtt_ms = rtt_ms
        client.drift_ppm = drift_ppm
        client.is_locked = is_locked
        client.underruns = underruns
        client.overruns = overruns
        client.packet_loss_rate = packet_loss_rate
        client.resample_ratio = resample_ratio
        client.last_seen = time.time()

    def remove_client(self, client_id: str):
        self._clients.pop(client_id, None)

    def prune_stale_clients(self):
        """Remove clients that have stopped sending heartbeats/telemetry."""
        now = time.time()
        stale = [cid for cid, c in self._clients.items() if (now - c.last_seen) > self._client_timeout_sec]
        for cid in stale:
            del self._clients[cid]

    def get_clients(self) -> List[dict]:
        self.prune_stale_clients()
        return [c.to_dict() for c in self._clients.values()]

    def get_sync_report(self) -> dict:
        """Aggregate sync report across all active endpoints."""
        self.prune_stale_clients()
        active = list(self._clients.values())

        if not active:
            return {
                "active_clients": 0,
                "target_delay_ms": self.base_target_delay_ms,
                "locked_clients": 0,
                "mean_rtt_ms": 0.0,
                "mean_offset_ms": 0.0,
                "mean_buffer_depth_ms": 0.0,
                "max_drift_ppm": 0.0,
                "total_underruns": 0,
                "health_status": "Idle",
                "clients": []
            }

        locked_count = sum(1 for c in active if c.is_locked)
        mean_rtt = float(np.mean([c.rtt_ms for c in active]))
        mean_offset = float(np.mean([abs(c.clock_offset_ms) for c in active]))
        mean_buffer = float(np.mean([c.buffer_depth_ms for c in active]))
        max_drift = float(np.max([abs(c.drift_ppm) for c in active]))
        total_underruns = sum(c.underruns for c in active)

        health = "Optimal"
        if locked_count < len(active):
            health = "Synchronizing"
        if mean_rtt > 50.0 or total_underruns > 5:
            health = "Degraded"

        return {
            "active_clients": len(active),
            "target_delay_ms": self.base_target_delay_ms,
            "locked_clients": locked_count,
            "mean_rtt_ms": round(mean_rtt, 2),
            "mean_offset_ms": round(mean_offset, 2),
            "mean_buffer_depth_ms": round(mean_buffer, 2),
            "max_drift_ppm": round(max_drift, 2),
            "total_underruns": total_underruns,
            "health_status": health,
            "clients": [c.to_dict() for c in active]
        }
