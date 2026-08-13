"""Adaptive jitter playout buffer with priority queuing and watermark state tracking."""

import heapq
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np

from src.core.packet import AudioPacket


@dataclass(order=True)
class ScheduledPacket:
    """Audio packet wrapped in priority queue with computed playout timestamp."""
    playout_time: float
    packet: AudioPacket = field(compare=False)


class BufferWatermarkState:
    UNDERRUN_RISK = "underrun_risk"  # < 35 ms
    LOW = "low"                      # 35 - 90 ms
    OPTIMAL = "optimal"              # 90 - 110 ms
    HIGH = "high"                    # 110 - 160 ms
    HARD_RESET = "hard_reset"        # > 250 ms


class AdaptiveJitterBuffer:
    """Priority queue timestamp playout scheduler."""

    def __init__(
        self,
        target_delay_sec: float = 0.100,  # 100.0 ms
        sample_rate: int = 48000,
        max_buffer_sec: float = 0.500
    ):
        self.target_delay_sec = float(target_delay_sec)
        self.sample_rate = int(sample_rate)
        self.max_buffer_sec = float(max_buffer_sec)

        self._queue: List[ScheduledPacket] = []
        self._last_popped_pts = 0.0
        self._total_pushed = 0
        self._total_popped = 0
        self._total_dropped_late = 0
        self._total_resets = 0

    @property
    def packet_count(self) -> int:
        return len(self._queue)

    @property
    def dropped_late_count(self) -> int:
        return self._total_dropped_late

    @property
    def resets_count(self) -> int:
        return self._total_resets

    def push(self, packet: AudioPacket, clock_offset: float) -> bool:
        """Schedule an incoming packet based on PTS and estimated clock offset.

        Playout time formula: T_play = PTS_host + theta_client + D_target
        """
        self._total_pushed += 1
        t_play = packet.pts + clock_offset + packet.target_playout_delay

        heapq.heappush(self._queue, ScheduledPacket(playout_time=t_play, packet=packet))

        # Check for hard reset condition (> 250 ms excess)
        depth_sec = self.get_buffer_depth_sec()
        if depth_sec > 0.250:
            self._prune_excess(keep_sec=self.target_delay_sec)
            self._total_resets += 1

        return True

    def pop_ready(self, current_time: float) -> List[AudioPacket]:
        """Pop all packets whose scheduled playout time has arrived."""
        ready_packets: List[AudioPacket] = []

        while self._queue:
            earliest = self._queue[0]
            if earliest.playout_time <= current_time:
                item = heapq.heappop(self._queue)
                ready_packets.append(item.packet)
                self._last_popped_pts = item.packet.pts
                self._total_popped += 1
            else:
                break

        return ready_packets

    def get_buffer_depth_sec(self) -> float:
        """Estimate buffered duration in seconds in the queue."""
        if not self._queue:
            return 0.0
        # Earliest playout time vs latest playout time
        earliest = min(p.playout_time for p in self._queue)
        latest = max(p.playout_time for p in self._queue)
        # Add frame duration of the last packet
        return max(0.0, latest - earliest)

    def get_buffer_depth_ms(self) -> float:
        return self.get_buffer_depth_sec() * 1000.0

    def get_watermark_state(self) -> str:
        depth_ms = self.get_buffer_depth_ms()
        if depth_ms < 35.0:
            return BufferWatermarkState.UNDERRUN_RISK
        elif depth_ms < 90.0:
            return BufferWatermarkState.LOW
        elif depth_ms <= 110.0:
            return BufferWatermarkState.OPTIMAL
        elif depth_ms <= 160.0:
            return BufferWatermarkState.HIGH
        else:
            return BufferWatermarkState.HARD_RESET

    def _prune_excess(self, keep_sec: float):
        """Discard oldest packets until buffer depth is within keep_sec."""
        if len(self._queue) <= 2:
            return
        target_packets = max(2, int(round(keep_sec / 0.010)))
        while len(self._queue) > target_packets:
            heapq.heappop(self._queue)
            self._total_dropped_late += 1

    def clear(self):
        self._queue.clear()
