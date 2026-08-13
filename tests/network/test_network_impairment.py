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
        jb.push(packets[idx], clock_offset=0.0)

    assert jb.packet_count == 5

    # Pop ready packets at simulated arrival time
    ready = jb.pop_ready(current_time=2.0)  # Far enough in future
    assert len(ready) == 5
    # Must be ordered strictly by PTS / playout time
    popped_seqs = [p.sequence_number for p in ready]
    assert popped_seqs == [0, 1, 2, 3, 4]


def test_jitter_buffer_hard_reset_on_excess_lag():
    jb = AdaptiveJitterBuffer(target_delay_sec=0.100)

    # Push 50 packets spanning 500ms (> 250ms hard reset threshold)
    for i in range(50):
        pkt = AudioPacket(sequence_number=i, pts=1.0 + (i * 0.010), target_playout_delay=0.100, frame_count=480, payload=b"\x00" * 48)
        jb.push(pkt, clock_offset=0.0)

    # Hard reset should prune queue
    assert jb.resets_count > 0
    assert jb.get_buffer_depth_sec() < 0.200


def test_pll_recovery_under_burst_jitter():
    pll = PLLController(target_delay_sec=0.100, max_rate_adjustment=0.0005)

    # Simulate random jitter around 100ms
    random.seed(42)
    for _ in range(100):
        jittered_delay = 0.100 + random.uniform(-0.020, 0.020)
        ratio = pll.update(jittered_delay, dt=0.01)
        # Verify strict boundedness
        assert 0.999499 <= ratio <= 1.000501
