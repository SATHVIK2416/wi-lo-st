"""Client receiver telemetry schema and parsing."""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class ReceiverReport:
    """Telemetry report transmitted from listener client to host."""
    client_id: str
    client_type: str = "web"
    buffer_depth_ms: float = 100.0
    clock_offset_ms: float = 0.0
    rtt_ms: float = 0.0
    drift_ppm: float = 0.0
    underruns: int = 0
    overruns: int = 0
    packet_loss_rate: float = 0.0
    resample_ratio: float = 1.0
    is_locked: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReceiverReport":
        """Parse dictionary or JSON payload into structured ReceiverReport."""
        return cls(
            client_id=str(data.get("client_id", "unknown")),
            client_type=str(data.get("client_type", "web")),
            buffer_depth_ms=float(data.get("buffer_ms", data.get("buffer_depth_ms", 100.0))),
            clock_offset_ms=float(data.get("offset_ms", data.get("clock_offset_ms", 0.0))),
            rtt_ms=float(data.get("rtt_ms", 0.0)),
            drift_ppm=float(data.get("drift_ppm", 0.0)),
            underruns=int(data.get("underruns", 0)),
            overruns=int(data.get("overruns", 0)),
            packet_loss_rate=float(data.get("packet_loss", data.get("packet_loss_rate", 0.0))),
            resample_ratio=float(data.get("resample_ratio", 1.0)),
            is_locked=bool(data.get("is_locked", True))
        )
