"""Tests for the native receiver: continuous resampler, loss tracking, NTP wiring."""

import numpy as np
import pytest

from src.clients.native_receiver import ContinuousResampler, NativeReceiverClient
from src.core.audio_format import SampleFormat
from src.core.packet import AudioPacket


def _sine_chunk(num_frames=480, freq=440.0, sr=48000, phase0=0.0):
    t = (np.arange(num_frames) + phase0) / sr
    mono = np.sin(2 * np.pi * freq * t).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def test_continuous_resampler_identity_passthrough():
    r = ContinuousResampler(channels=2)
    chunk = _sine_chunk()
    out = r.process(chunk, ratio=1.0)
    assert out.shape == chunk.shape
    np.testing.assert_allclose(out, chunk)


def test_continuous_resampler_ratio_scales_output_length():
    r = ContinuousResampler(channels=2)
    total_out = 0
    for _ in range(10):
        out = r.process(_sine_chunk(480), ratio=1.0005)
        total_out += len(out)
    # 10 chunks of 480 frames at ratio 1.0005 -> ~4797.6 output frames
    assert abs(total_out - 480 * 10 / 1.0005) <= 3


def test_continuous_resampler_no_phase_discontinuity_across_chunks():
    """Output must stay within the input's amplitude envelope (no boundary spikes)."""
    r = ContinuousResampler(channels=2)
    outs = []
    for i in range(20):
        outs.append(r.process(_sine_chunk(480, phase0=i * 480), ratio=1.0003))
    joined = np.concatenate(outs, axis=0)[:, 0]
    # A boundary discontinuity would show as a sample-to-sample jump far beyond
    # the sine's natural slew (2*pi*440/48000 ~ 0.058 per sample)
    max_jump = float(np.max(np.abs(np.diff(joined))))
    assert max_jump < 0.2


def test_continuous_resampler_amplitude_preserved():
    r = ContinuousResampler(channels=2)
    outs = [r.process(_sine_chunk(480), ratio=1.0002) for _ in range(5)]
    joined = np.concatenate(outs, axis=0)
    peak = float(np.max(np.abs(joined)))
    assert 0.9 < peak < 1.01  # no attenuation, no overshoot blowup


def test_receiver_schedules_with_filtered_offset_not_zero():
    """Regression: the measured clock offset must actually reach the jitter buffer."""
    from src.core.clock import MasterClock

    rx = NativeReceiverClient(ntp_enabled=False)
    rx._clock_offset = 0.250  # simulated filtered offset
    pts = MasterClock.now()
    pkt = AudioPacket(
        sequence_number=0,
        pts=pts,
        target_playout_delay=0.100,
        frame_count=480,
        payload=np.zeros((480, 2), dtype=np.float32).tobytes(),
        sample_rate=48000,
        channels=2,
        sample_format=SampleFormat.FLOAT32,
    )
    rx._on_packet_received(pkt)
    assert rx.jitter_buffer.packet_count == 1
    scheduled = rx.jitter_buffer._queue[0].playout_time
    # playout = pts + offset + delay (offset must NOT be dropped on the floor)
    assert abs(scheduled - (pts + 0.250 + 0.100)) < 1e-6


def test_receiver_sequence_gap_counts_loss():
    rx = NativeReceiverClient(ntp_enabled=False)
    payload = np.zeros((480, 2), dtype=np.float32).tobytes()

    def mk(seq):
        return AudioPacket(
            sequence_number=seq, pts=100.0, target_playout_delay=0.1,
            frame_count=480, payload=payload, sample_rate=48000, channels=2,
            sample_format=SampleFormat.FLOAT32,
        )

    rx._on_packet_received(mk(0))
    rx._on_packet_received(mk(5))  # gap of 4 -> 4 lost
    assert rx._packets_received == 2
    assert rx._packets_lost == 4
    assert abs(rx._packet_loss_rate() - 4 / 6) < 1e-9
