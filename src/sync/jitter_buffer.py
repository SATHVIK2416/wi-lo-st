"""Adaptive jitter playout buffer with priority queuing and watermark state tracking."""

import heapq
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

from src.core.packet import AudioPacket


@dataclass(order=True)
class ScheduledPacket:
    """Audio packet wrapped in priority queue with computed playout timestamp."""
    playout_time: float
    packet: AudioPacket = field(compare=False)


class BufferWatermarkState:
    UNDERRUN_RISK = "underrun_risk"  # < 35 ms of held audio
    LOW = "low"                      # 35 - 90 ms
    OPTIMAL = "optimal"              # 90 - 110 ms
    HIGH = "high"                    # 110 - 160 ms
    HARD_RESET = "hard_reset"        # > 250 ms


class AdaptiveJitterBuffer:
    """Priority queue timestamp playout scheduler.

    Two distinct quantities govern behaviour:

    - *Held audio* (watermarks, capacity): total playable duration currently
      queued. It drains toward zero when the network stalls, which is exactly
      what an underrun-risk indicator must show.
    - *Scheduling excess* (hard reset): how far the earliest packet's playout
      time lies beyond ``now + target_delay``. A jump in clock-offset estimates
      pushes every deadline into the far future without changing held audio;
      the reset skips audio forward to restore the latency anchor.

    Playout time formula: T_play = PTS_host + theta_client + D_target
    """

    HARD_RESET_EXCESS_SEC = 0.250

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
        self._held_frames = 0
        self._total_pushed = 0
        self._total_popped = 0
        self._total_dropped_late = 0
        self._total_dropped_overflow = 0
        self._total_resets = 0
        self._lock = threading.Lock()

    @property
    def packet_count(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def dropped_late_count(self) -> int:
        return self._total_dropped_late

    @property
    def dropped_overflow_count(self) -> int:
        return self._total_dropped_overflow

    @property
    def resets_count(self) -> int:
        return self._total_resets

    def push(self, packet: AudioPacket, clock_offset: float, current_time: Optional[float] = None) -> bool:
        """Schedule an incoming packet based on PTS and estimated clock offset.

        Args:
            packet: The audio packet to schedule.
            clock_offset: Estimated host-vs-client clock offset (seconds).
            current_time: Client-local current time; defaults to perf_counter().

        Returns:
            False if the packet was rejected as uselessly late, True otherwise.
        """
        now = time.perf_counter() if current_time is None else current_time
        t_play = packet.pts + clock_offset + packet.target_playout_delay

        with self._lock:
            if t_play < now - self.HARD_RESET_EXCESS_SEC:
                self._total_dropped_late += 1
                return False

            self._total_pushed += 1
            heapq.heappush(self._queue, ScheduledPacket(playout_time=t_play, packet=packet))
            self._held_frames += packet.frame_count

            # Hard reset: deadlines pushed far beyond the target delay anchor
            if self._queue:
                earliest = self._queue[0].playout_time
                if earliest - now > self.target_delay_sec + self.HARD_RESET_EXCESS_SEC:
                    self._prune_excess_unlocked(now, keep_until=now + self.target_delay_sec)
                    self._total_resets += 1

            self._enforce_capacity_unlocked()

        return True

    def pop_ready(self, current_time: Optional[float] = None) -> List[AudioPacket]:
        """Pop all packets whose scheduled playout time has arrived."""
        now = time.perf_counter() if current_time is None else current_time
        ready_packets: List[AudioPacket] = []

        with self._lock:
            while self._queue:
                earliest = self._queue[0]
                if earliest.playout_time <= now:
                    item = heapq.heappop(self._queue)
                    ready_packets.append(item.packet)
                    self._held_frames -= item.packet.frame_count
                    self._total_popped += 1
                else:
                    break

        return ready_packets

    def get_buffer_depth_sec(self, current_time: Optional[float] = None) -> float:
        """Total playable audio duration currently held in the queue (seconds)."""
        del current_time  # held audio is clock-independent
        with self._lock:
            return self._held_frames / float(self.sample_rate)

    def get_queue_span_sec(self) -> float:
        """Diagnostics: playout-time span between earliest and latest queued packets."""
        with self._lock:
            if not self._queue:
                return 0.0
            earliest = self._queue[0].playout_time
            latest = max(p.playout_time for p in self._queue)
            return max(0.0, latest - earliest)

    def get_scheduling_lead_sec(self, current_time: Optional[float] = None) -> float:
        """How far the earliest deadline lies in the future (time to underrun)."""
        now = time.perf_counter() if current_time is None else current_time
        with self._lock:
            if not self._queue:
                return 0.0
            return max(0.0, self._queue[0].playout_time - now)

    def get_buffer_depth_ms(self, current_time: Optional[float] = None) -> float:
        return self.get_buffer_depth_sec(current_time) * 1000.0

    def get_watermark_state(self, current_time: Optional[float] = None) -> str:
        depth_ms = self.get_buffer_depth_ms(current_time)
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

    def clear(self):
        with self._lock:
            self._queue.clear()
            self._held_frames = 0

    def _prune_excess_unlocked(self, now: float, keep_until: float):
        """Skip audio forward until the earliest deadline is within keep_until.

        May drain the queue entirely: if every queued packet is scheduled
        further ahead than the hard-reset threshold (e.g. after an offset
        estimation jump), holding them would anchor excess latency; fresh
        correctly-scheduled packets restore continuity instead.
        """
        while self._queue and self._queue[0].playout_time > keep_until:
            item = heapq.heappop(self._queue)
            self._held_frames -= item.packet.frame_count
            self._total_dropped_late += 1

    def _enforce_capacity_unlocked(self):
        """Hard bound on held audio to keep memory finite."""
        max_frames = int(self.max_buffer_sec * self.sample_rate)
        while self._queue and self._held_frames > max_frames:
            item = heapq.heappop(self._queue)
            self._held_frames -= item.packet.frame_count
            self._total_dropped_overflow += 1
