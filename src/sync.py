"""
SonicSync - Precision Clock Synchronization & Adaptive Jitter Buffer
Implements NTP 4-timestamp exchange, outlier-resilient statistical filtering,
multi-client latency coordinator, and phase-locked loop (PLL) jitter buffer.
"""

import collections
import heapq
import logging
import math
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.audio import AudioFormat, AudioPacket, AudioFormatCode, RingBuffer

logger = logging.getLogger("SonicSync.Sync")

# NTP Binary Protocol
# Packet format:
# 4s : Magic "SONI"
# B  : Version (1)
# B  : PacketType (SYNC_PING=0x10, SYNC_PONG=0x11)
# H  : Client ID (uint16)
# I  : Sequence (uint32)
# d  : t0 (float64 seconds)
# d  : t1 (float64 seconds)
# d  : t2 (float64 seconds)
# d  : t3 (float64 seconds)
NTP_PACKET_FORMAT = "!4sBBHI4d"
NTP_PACKET_SIZE = struct.calcsize(NTP_PACKET_FORMAT)
NTP_MAGIC = b"SONI"


@dataclass
class NTPMessage:
    msg_type: int
    client_id: int
    sequence: int
    t0: float = 0.0
    t1: float = 0.0
    t2: float = 0.0
    t3: float = 0.0

    def pack(self) -> bytes:
        return struct.pack(
            NTP_PACKET_FORMAT,
            NTP_MAGIC,
            1,
            self.msg_type,
            self.client_id,
            self.sequence,
            self.t0,
            self.t1,
            self.t2,
            self.t3
        )

    @classmethod
    def unpack(cls, data: bytes) -> Optional["NTPMessage"]:
        if len(data) < NTP_PACKET_SIZE:
            return None
        magic, ver, msg_type, client_id, seq, t0, t1, t2, t3 = struct.unpack(
            NTP_PACKET_FORMAT, data[:NTP_PACKET_SIZE]
        )
        if magic != NTP_MAGIC:
            return None
        return cls(
            msg_type=msg_type,
            client_id=client_id,
            sequence=seq,
            t0=t0,
            t1=t1,
            t2=t2,
            t3=t3
        )


@dataclass
class SyncStats:
    rtt_ms: float = 0.0
    offset_ms: float = 0.0
    jitter_ms: float = 0.0
    one_way_delay_ms: float = 0.0
    drift_ppm: float = 0.0
    samples_count: int = 0
    is_synchronized: bool = False


class ClockSyncFilter:
    """
    Statistical filter for NTP measurements.
    Rejects network jitter outliers and computes exponential moving averages (EMA)
    for clock offset and round-trip time.
    """

    def __init__(self, window_size: int = 30, outlier_std_threshold: float = 2.0):
        self.window_size = window_size
        self.outlier_threshold = outlier_std_threshold
        self.history: collections.deque = collections.deque(maxlen=window_size)
        self.filtered_offset = 0.0  # seconds (Receiver_Time - Host_Time)
        self.filtered_rtt = 0.0     # seconds
        self.filtered_jitter = 0.0  # seconds
        self.lock = threading.Lock()
        self.synchronized = False
        self.min_samples_for_sync = 5

    def add_sample(self, t0: float, t1: float, t2: float, t3: float) -> Optional[Tuple[float, float]]:
        """
        Processes a completed 4-timestamp NTP exchange:
        t0: Host transmit ping
        t1: Receiver receive ping
        t2: Receiver transmit pong
        t3: Host receive pong

        Returns (rtt_seconds, offset_seconds) if valid, else None.
        """
        # Round-trip time excluding receiver turnaround time
        rtt = (t3 - t0) - (t2 - t1)
        if rtt < 0:
            # Clock anomaly or negative turnaround; clamp
            rtt = max(1e-6, (t3 - t0))

        # Clock offset: Receiver Clock - Host Clock
        # theta = ((t1 - t0) + (t2 - t3)) / 2
        offset = ((t1 - t0) + (t2 - t3)) / 2.0

        with self.lock:
            # Outlier rejection based on RTT history
            if len(self.history) >= self.min_samples_for_sync:
                rtts = [s[0] for s in self.history]
                median_rtt = float(np.median(rtts))
                std_rtt = float(np.std(rtts)) if len(rtts) > 2 else 0.005
                cutoff = median_rtt + self.outlier_threshold * max(0.002, std_rtt)
                if rtt > cutoff:
                    # Drop outlier sample
                    return None

            self.history.append((rtt, offset, time.time()))

            # Weight lower RTT samples more heavily (closest to true unqueued propagation)
            rtts = np.array([s[0] for s in self.history])
            offsets = np.array([s[1] for s in self.history])

            # Select lowest 40% RTT samples for offset estimation
            k = max(1, int(len(rtts) * 0.4))
            best_indices = np.argsort(rtts)[:k]
            best_offsets = offsets[best_indices]
            best_rtts = rtts[best_indices]

            target_offset = float(np.median(best_offsets))
            target_rtt = float(np.median(best_rtts))

            if not self.synchronized and len(self.history) >= self.min_samples_for_sync:
                self.filtered_offset = target_offset
                self.filtered_rtt = target_rtt
                self.synchronized = True
            elif self.synchronized:
                alpha = 0.15  # EMA smoothing factor
                self.filtered_offset = (1.0 - alpha) * self.filtered_offset + alpha * target_offset
                self.filtered_rtt = (1.0 - alpha) * self.filtered_rtt + alpha * target_rtt
                
                # Jitter estimation (mean deviation)
                jitter_sample = abs(offset - self.filtered_offset)
                self.filtered_jitter = (1.0 - alpha) * self.filtered_jitter + alpha * jitter_sample

            return self.filtered_rtt, self.filtered_offset

    def get_stats(self) -> SyncStats:
        with self.lock:
            return SyncStats(
                rtt_ms=self.filtered_rtt * 1000.0,
                offset_ms=self.filtered_offset * 1000.0,
                jitter_ms=self.filtered_jitter * 1000.0,
                one_way_delay_ms=(self.filtered_rtt / 2.0) * 1000.0,
                samples_count=len(self.history),
                is_synchronized=self.synchronized
            )

    def host_pts_to_receiver_time(self, host_pts: float) -> float:
        """Converts Host Master Clock timestamp to Receiver local clock time."""
        with self.lock:
            return host_pts + self.filtered_offset

    def receiver_time_to_host_time(self, receiver_time: float) -> float:
        """Converts Receiver local clock time to Host Master Clock time."""
        with self.lock:
            return receiver_time - self.filtered_offset


class MasterSyncCoordinator:
    """
    Host-side Synchronization Coordinator.
    Gathers RTT, one-way delay, and jitter from all active clients.
    Computes the optimal global playback broadcast delay so all clients play in exact lockstep.
    """

    def __init__(self, base_safety_margin_ms: float = 15.0, max_delay_cap_ms: float = 150.0):
        self.base_safety_margin_ms = base_safety_margin_ms
        self.max_delay_cap_ms = max_delay_cap_ms
        self.clients: Dict[int, SyncStats] = {}
        self.last_client_seen: Dict[int, float] = {}
        self.lock = threading.Lock()
        self.target_broadcast_delay = base_safety_margin_ms / 1000.0  # seconds

    def update_client_stats(self, client_id: int, stats: SyncStats):
        with self.lock:
            self.clients[client_id] = stats
            self.last_client_seen[client_id] = time.time()
            self._recalculate_global_delay()

    def remove_client(self, client_id: int):
        with self.lock:
            if client_id in self.clients:
                del self.clients[client_id]
            if client_id in self.last_client_seen:
                del self.last_client_seen[client_id]
            self._recalculate_global_delay()

    def _recalculate_global_delay(self):
        now = time.time()
        # Filter active clients seen in last 5 seconds
        active_delays = []
        for cid, stats in list(self.clients.items()):
            if now - self.last_client_seen.get(cid, 0) < 5.0:
                # Needed delay for this client = one-way network delay + 3 * jitter
                req_delay_ms = stats.one_way_delay_ms + 3.0 * stats.jitter_ms
                active_delays.append(req_delay_ms)
            else:
                del self.clients[cid]
                if cid in self.last_client_seen:
                    del self.last_client_seen[cid]

        if active_delays:
            max_needed_ms = max(active_delays)
            total_delay_ms = max_needed_ms + self.base_safety_margin_ms
            total_delay_ms = min(self.max_delay_cap_ms, max(self.base_safety_margin_ms, total_delay_ms))
            self.target_broadcast_delay = total_delay_ms / 1000.0
        else:
            self.target_broadcast_delay = self.base_safety_margin_ms / 1000.0

    def get_target_delay(self) -> float:
        """Returns current global broadcast delay in seconds."""
        with self.lock:
            return self.target_broadcast_delay

    def get_all_clients(self) -> Dict[int, SyncStats]:
        with self.lock:
            return dict(self.clients)


@dataclass(order=True)
class QueuedAudioFrame:
    scheduled_play_time: float
    sequence_number: int
    pts: float = field(compare=False)
    samples: np.ndarray = field(compare=False)
    frame_count: int = field(compare=False)


class AdaptiveJitterBuffer:
    """
    Receiver-side Adaptive Jitter Buffer & Phase-Locked Loop (PLL) Scheduler.
    Reorders incoming UDP packets, buffers them for their scheduled playout time,
    and micro-adjusts sample rate (PLL) to eliminate crystal clock drift between sound cards.
    """

    def __init__(
        self,
        audio_format: AudioFormat,
        sync_filter: ClockSyncFilter,
        target_delay_override: Optional[float] = None
    ):
        self.format = audio_format
        self.sync_filter = sync_filter
        self.target_delay_override = target_delay_override
        
        self.queue: List[QueuedAudioFrame] = []
        self.lock = threading.Lock()
        self.next_expected_seq = 0
        self.drift_correction_samples = 0
        self.total_packets_received = 0
        self.total_packets_dropped_late = 0
        self.total_packets_dropped_duplicate = 0
        self.received_seqs = collections.deque(maxlen=200)

        # Internal FIFO ring buffer for output DAC callback
        self.out_ring = RingBuffer(
            capacity_frames=audio_format.sample_rate * 2,
            channels=audio_format.channels,
            dtype=audio_format.numpy_dtype
        )

        # Running status
        self.buffer_level_ms = 0.0
        self.phase_error_ms = 0.0

    def push_packet(self, packet: AudioPacket):
        """Pushes an incoming network AudioPacket into the jitter buffer."""
        self.total_packets_received += 1

        # Duplicate check
        if packet.sequence_number in self.received_seqs:
            self.total_packets_dropped_duplicate += 1
            return
        self.received_seqs.append(packet.sequence_number)

        # Decode samples
        samples = self.format.decompress(packet.payload, packet.packet_type, packet.frame_count)

        # Calculate exact scheduled playout time in Receiver Local Clock
        target_delay = self.target_delay_override if self.target_delay_override is not None else packet.target_delay
        rx_pts = self.sync_filter.host_pts_to_receiver_time(packet.pts)
        scheduled_play_time = rx_pts + target_delay

        now = time.time()
        # If packet arrived too late (more than 20ms in the past), drop it
        if scheduled_play_time < now - 0.020:
            self.total_packets_dropped_late += 1
            return

        frame = QueuedAudioFrame(
            scheduled_play_time=scheduled_play_time,
            sequence_number=packet.sequence_number,
            pts=packet.pts,
            samples=samples,
            frame_count=packet.frame_count
        )

        with self.lock:
            heapq.heappush(self.queue, frame)

    def process_and_fill_output(self, now: Optional[float] = None) -> int:
        """
        Transfers queued frames that are due for playback into the output ring buffer.
        Performs micro-drift sample stuffing / trimming if clock drift occurs.
        """
        if now is None:
            now = time.time()

        frames_pushed = 0
        with self.lock:
            while self.queue:
                peek = self.queue[0]
                # If frame is ready to play (within 5ms window or already past)
                if peek.scheduled_play_time <= now + 0.005:
                    frame = heapq.heappop(self.queue)
                    samples = frame.samples

                    # Calculate phase error: difference between now and scheduled time
                    phase_error = now - frame.scheduled_play_time
                    self.phase_error_ms = phase_error * 1000.0

                    # Micro-Drift Correction (PLL):
                    # If receiver is running slightly fast (phase_error < -2ms), gently insert 1 interpolated sample
                    # If receiver is running slightly slow (phase_error > +2ms), gently drop 1 sample
                    if phase_error < -0.003 and len(samples) > 10:
                        # Insert sample at midpoint
                        mid = len(samples) // 2
                        interpolated = (samples[mid - 1].astype(np.float32) + samples[mid].astype(np.float32)) / 2.0
                        samples = np.insert(samples, mid, interpolated.astype(self.format.numpy_dtype), axis=0)
                        self.drift_correction_samples += 1

                    elif phase_error > 0.003 and len(samples) > 10:
                        # Drop 1 sample at midpoint
                        mid = len(samples) // 2
                        samples = np.delete(samples, mid, axis=0)
                        self.drift_correction_samples -= 1

                    self.out_ring.write(samples)
                    frames_pushed += len(samples)
                else:
                    break

            # Buffer duration in ms currently queued
            if self.queue:
                self.buffer_level_ms = max(0.0, (self.queue[-1].scheduled_play_time - now) * 1000.0)
            else:
                self.buffer_level_ms = 0.0

        return frames_pushed

    def pull_samples(self, frame_count: int) -> np.ndarray:
        """Called by real-time audio DAC thread to pull samples."""
        self.process_and_fill_output()
        return self.out_ring.read(frame_count)

    def get_metrics(self) -> dict:
        with self.lock:
            return {
                "queued_packets": len(self.queue),
                "buffer_level_ms": self.buffer_level_ms,
                "phase_error_ms": self.phase_error_ms,
                "total_received": self.total_packets_received,
                "dropped_late": self.total_packets_dropped_late,
                "dropped_duplicate": self.total_packets_dropped_duplicate,
                "drift_adjustments": self.drift_correction_samples,
                "ring_fill_pct": self.out_ring.get_fill_percentage()
            }
