"""Network impairment tests simulating Wi-Fi jitter, packet drops, and buffer recovery."""

import random
import pytest
import numpy as np
from src.core.audio_format import SampleFormat
from src.core.packet import AudioPacket
from src.sync.jitter_buffer import AdaptiveJitterBuffer, BufferWatermarkState
from src.sync.pll_controller import PLLController


def test_jitter_buffer_reordering():
    jb = AdaptiveJitterBuffer(target_delay_sec=0.100)

    # Generate 5 packets with sequence 0..4
    packets = [
        AudioPacket(sequence_number=i, pts=1.0 + (i * 0.010), target_playout_delay=0.100, frame_count=480, payload=b"\x00" * 48)
        for i in range(5)
    ]

    # Push in scrambled order: 2, 0, 4, 1, 3
    scrambled_indices = [2, 0, 4, 1, 3]
    for idx in scrambled_indices:
        jb.push(packets[idx], clock_offset=0.0, current_time=1.0)

    assert jb.packet_count == 5

    # Depth is total held audio: 5 packets x 480 frames @48kHz = 50 ms
    assert abs(jb.get_buffer_depth_sec(current_time=1.0) - 0.050) < 0.001

    # Scheduling lead (time to underrun) is earliest deadline minus now = 100 ms
    assert abs(jb.get_scheduling_lead_sec(current_time=1.0) - 0.100) < 0.001

    # Pop ready packets at simulated arrival time
    ready = jb.pop_ready(current_time=2.0)  # Far enough in future
    assert len(ready) == 5
    # Must be ordered strictly by PTS / playout time
    popped_seqs = [p.sequence_number for p in ready]
    assert popped_seqs == [0, 1, 2, 3, 4]


def test_jitter_buffer_hard_reset_on_excess_future_scheduling():
    jb = AdaptiveJitterBuffer(target_delay_sec=0.100)

    # Packets scheduled 500ms..990ms into the future relative to now=1.0
    # (e.g. after an offset estimation jump): depth far exceeds target + 250ms,
    # so the hard reset must skip audio forward back to ~target delay.
    for i in range(50):
        pkt = AudioPacket(sequence_number=i, pts=1.400 + (i * 0.010), target_playout_delay=0.100, frame_count=480, payload=b"\x00" * 48)
        jb.push(pkt, clock_offset=0.0, current_time=1.0)

    assert jb.resets_count > 0
    assert jb.dropped_late_count > 0
    assert jb.get_buffer_depth_sec(current_time=1.0) <= 0.101


def test_jitter_buffer_watermark_drains_on_stall():
    """Held audio drains toward zero when no new packets arrive (network stall)."""
    jb = AdaptiveJitterBuffer(target_delay_sec=0.100)

    for i in range(20):
        pkt = AudioPacket(sequence_number=i, pts=1.0 + (i * 0.010), target_playout_delay=0.100, frame_count=480, payload=b"\x00" * 48)
        jb.push(pkt, clock_offset=0.0, current_time=1.0)

    assert jb.get_buffer_depth_sec(current_time=1.0) > 0.15

    # Simulate a stall: time passes, packets come due and get popped
    for t in [1.2, 1.4, 1.6, 1.8, 2.0]:
        jb.pop_ready(current_time=t)

    assert jb.packet_count == 0
    assert abs(jb.get_buffer_depth_sec()) < 1e-9
    assert jb.get_watermark_state() == BufferWatermarkState.UNDERRUN_RISK


def test_jitter_buffer_burst_refill_is_not_a_reset():
    """A stall followed by a burst of already-due-to-play-soon packets is normal."""
    jb = AdaptiveJitterBuffer(target_delay_sec=0.100)

    # Burst spanning 500ms arriving at once, all due within the next 600ms
    for i in range(50):
        pkt = AudioPacket(sequence_number=i, pts=1.0 + (i * 0.010), target_playout_delay=0.100, frame_count=480, payload=b"\x00" * 48)
        jb.push(pkt, clock_offset=0.0, current_time=1.0)

    assert jb.resets_count == 0
    assert jb.packet_count == 50


def test_jitter_buffer_rejects_uselessly_late_packets():
    jb = AdaptiveJitterBuffer(target_delay_sec=0.100)
    pkt = AudioPacket(sequence_number=0, pts=1.0, target_playout_delay=0.100, frame_count=480, payload=b"\x00" * 48)

    # Playout time 1.1 is > 250ms in the past relative to now=2.0 -> rejected
    assert jb.push(pkt, clock_offset=0.0, current_time=2.0) is False
    assert jb.packet_count == 0


def test_udp_receiver_dedups_duplicate_datagrams():
    import numpy as np
    from src.transport.sonicsync_udp import SonicSyncUDPReceiver

    rx = SonicSyncUDPReceiver(dedup_enabled=True)
    received = []
    payload = np.zeros((480, 2), dtype=np.float32).tobytes()
    pkt = AudioPacket(
        sequence_number=42,
        pts=1234.5,
        target_playout_delay=0.1,
        frame_count=480,
        payload=payload,
        sample_rate=48000,
        channels=2,
    )
    raw = pkt.serialize()

    rx._is_duplicate(42)
    rx._is_duplicate(43)
    assert rx._is_duplicate(42) is True   # duplicate within window
    assert rx._is_duplicate(44) is False  # fresh sequence passes
    assert len(rx._recent_seqs) == 3


def test_pll_recovery_under_burst_jitter():
    pll = PLLController(target_delay_sec=0.100, max_rate_adjustment=0.0005)

    # Simulate random jitter around 100ms
    random.seed(42)
    for _ in range(100):
        jittered_delay = 0.100 + random.uniform(-0.020, 0.020)
        ratio = pll.update(jittered_delay, dt=0.01)
        # Verify strict boundedness
        assert 0.999499 <= ratio <= 1.000501
