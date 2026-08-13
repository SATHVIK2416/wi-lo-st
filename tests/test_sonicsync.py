"""
SonicSync - Comprehensive Test Suite
Tests lossless audio bit-accuracy, wire packet serialization, ring buffer mechanics,
NTP 4-timestamp clock synchronization math, jitter buffer scheduling, and multi-client coordination.
"""

import asyncio
import math
import os
import sys
import time
import pytest
import numpy as np

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.audio import (
    AudioFormat,
    AudioFormatCode,
    AudioPacket,
    CompressionType,
    PacketType,
    RingBuffer,
    SyntheticSignalGenerator,
    calculate_rms_and_peak,
)
from src.sync import (
    AdaptiveJitterBuffer,
    ClockSyncFilter,
    MasterSyncCoordinator,
    NTPMessage,
    QueuedAudioFrame,
    SyncStats,
)


class TestAudioEngine:
    def test_lossless_roundtrip_int16(self):
        """Verify bit-exact uncompressed PCM roundtrip for 16-bit integer audio."""
        fmt = AudioFormat(sample_rate=48000, channels=2, format_code=AudioFormatCode.INT16)
        # Generate arbitrary test samples
        orig = np.random.randint(-32768, 32767, size=(512, 2), dtype=np.int16)
        raw_bytes = fmt.pcm_to_bytes(orig)
        assert len(raw_bytes) == 512 * 2 * 2  # 512 frames * 2 ch * 2 bytes = 2048 bytes

        reconstructed = fmt.bytes_to_pcm(raw_bytes, frame_count=512)
        assert reconstructed.shape == (512, 2)
        assert reconstructed.dtype == np.int16
        # Bitwise identity test
        np.testing.assert_array_equal(orig, reconstructed)

    def test_lossless_roundtrip_int24(self):
        """Verify 24-bit packed 3-byte PCM roundtrip."""
        fmt = AudioFormat(sample_rate=96000, channels=2, format_code=AudioFormatCode.INT24)
        orig = np.random.randint(-8388608, 8388607, size=(256, 2), dtype=np.int32)
        raw_bytes = fmt.pcm_to_bytes(orig)
        assert len(raw_bytes) == 256 * 2 * 3  # 256 frames * 2 ch * 3 bytes = 1536 bytes

        reconstructed = fmt.bytes_to_pcm(raw_bytes, frame_count=256)
        assert reconstructed.shape == (256, 2)
        np.testing.assert_array_equal(orig, reconstructed)

    def test_lossless_roundtrip_int32(self):
        """Verify 32-bit integer PCM roundtrip."""
        fmt = AudioFormat(sample_rate=192000, channels=2, format_code=AudioFormatCode.INT32)
        orig = np.random.randint(-2147483648, 2147483647, size=(128, 2), dtype=np.int32)
        raw_bytes = fmt.pcm_to_bytes(orig)
        assert len(raw_bytes) == 128 * 2 * 4

        reconstructed = fmt.bytes_to_pcm(raw_bytes, frame_count=128)
        np.testing.assert_array_equal(orig, reconstructed)

    def test_lossless_roundtrip_float32(self):
        """Verify 32-bit float PCM roundtrip."""
        fmt = AudioFormat(sample_rate=48000, channels=2, format_code=AudioFormatCode.FLOAT32)
        orig = np.random.uniform(-1.0, 1.0, size=(256, 2)).astype(np.float32)
        raw_bytes = fmt.pcm_to_bytes(orig)
        assert len(raw_bytes) == 256 * 2 * 4

        reconstructed = fmt.bytes_to_pcm(raw_bytes, frame_count=256)
        np.testing.assert_array_almost_equal(orig, reconstructed, decimal=6)

    def test_audio_packet_serialization_and_crc(self):
        """Verify binary packet wire packing, unpacking, and CRC integrity checks."""
        payload = b"AUDIOPHILE_LOSSLESS_RAW_PCM_TEST_BYTES" * 10
        pkt = AudioPacket(
            packet_type=PacketType.AUDIO_RAW_PCM,
            format_code=AudioFormatCode.INT16,
            channels=2,
            sample_rate=48000,
            sequence_number=1042,
            pts=1700000000.123456,
            target_delay=0.025,
            frame_count=256,
            payload=payload
        )
        packed = pkt.pack()
        unpacked = AudioPacket.unpack(packed)

        assert unpacked is not None
        assert unpacked.packet_type == PacketType.AUDIO_RAW_PCM
        assert unpacked.format_code == AudioFormatCode.INT16
        assert unpacked.channels == 2
        assert unpacked.sample_rate == 48000
        assert unpacked.sequence_number == 1042
        assert pytest.approx(unpacked.pts, 1e-6) == 1700000000.123456
        assert pytest.approx(unpacked.target_delay, 1e-4) == 0.025
        assert unpacked.frame_count == 256
        assert unpacked.payload == payload

        # Test corrupted payload detection (CRC mismatch)
        corrupted = bytearray(packed)
        corrupted[-1] ^= 0xFF  # Flip bit in payload
        assert AudioPacket.unpack(bytes(corrupted)) is None

        # Test invalid magic detection
        bad_magic = bytearray(packed)
        bad_magic[0] = ord("X")
        assert AudioPacket.unpack(bytes(bad_magic)) is None

    def test_ring_buffer_fifo(self):
        """Verify RingBuffer circular wrapping and reading/writing mechanics."""
        rb = RingBuffer(capacity_frames=1000, channels=2, dtype=np.int16)
        assert rb.available_frames == 0

        # Write 400 frames
        samples1 = np.ones((400, 2), dtype=np.int16) * 10
        written = rb.write(samples1)
        assert written == 400
        assert rb.available_frames == 400

        # Read 300 frames
        out1 = rb.read(300)
        assert len(out1) == 300
        assert np.all(out1 == 10)
        assert rb.available_frames == 100

        # Write 800 frames (wraps around circular buffer)
        samples2 = np.ones((800, 2), dtype=np.int16) * 20
        rb.write(samples2)
        assert rb.available_frames == 900

        # Read remaining 900 frames
        out2 = rb.read(900)
        assert len(out2) == 900
        assert np.all(out2[:100] == 10)
        assert np.all(out2[100:] == 20)
        assert rb.available_frames == 0

        # Underflow read produces silence
        silence = rb.read(50)
        assert len(silence) == 50
        assert np.all(silence == 0)
        assert rb.underflows > 0

    def test_synthetic_signal_generator(self):
        """Verify mathematical purity and phase accuracy of synthetic test signals."""
        fmt = AudioFormat(sample_rate=48000, channels=2, format_code=AudioFormatCode.INT16)
        gen = SyntheticSignalGenerator(fmt, mode="sine", freq=1000.0)

        chunk = gen.generate(480)  # 10ms of 1kHz sine
        assert len(chunk) == 480
        assert chunk.dtype == np.int16

        # Check peak & RMS (for 0.7 amplitude sine, RMS is ~0.495, dBFS is ~ -6.1)
        dbfs, peak = calculate_rms_and_peak(chunk)
        assert -7.0 <= dbfs <= -5.0
        assert 0.65 <= peak <= 0.75


class TestSyncEngine:
    def test_ntp_packet_serialization(self):
        """Verify binary NTP struct packing and unpacking."""
        ntp = NTPMessage(
            msg_type=PacketType.SYNC_PING,
            client_id=42,
            sequence=101,
            t0=100.123456,
            t1=100.125000,
            t2=100.126000,
            t3=100.128000
        )
        packed = ntp.pack()
        unpacked = NTPMessage.unpack(packed)
        assert unpacked is not None
        assert unpacked.msg_type == PacketType.SYNC_PING
        assert unpacked.client_id == 42
        assert unpacked.sequence == 101
        assert pytest.approx(unpacked.t0, 1e-6) == 100.123456
        assert pytest.approx(unpacked.t1, 1e-6) == 100.125000
        assert pytest.approx(unpacked.t2, 1e-6) == 100.126000
        assert pytest.approx(unpacked.t3, 1e-6) == 100.128000

    def test_ntp_math_and_clock_offset(self):
        """
        Verify exact math of 4-timestamp NTP clock synchronization:
        Simulate true network delay = 5.0ms (0.005s)
        Simulate true clock offset = +12.345s (Receiver is 12.345s ahead of Host)
        """
        sync_filter = ClockSyncFilter(window_size=20)
        true_offset = 12.345
        true_delay = 0.005  # 5ms one-way delay

        for i in range(15):
            t0 = 1000.0 + i * 0.1
            # Ping arrives at receiver: t1 = (t0 + true_delay) + true_offset
            t1 = (t0 + true_delay) + true_offset
            # Receiver processes for 0.5ms: t2 = t1 + 0.0005
            t2 = t1 + 0.0005
            # Pong arrives at host: t3 = (t2 + true_delay) - true_offset
            t3 = (t2 + true_delay) - true_offset

            sync_filter.add_sample(t0, t1, t2, t3)

        stats = sync_filter.get_stats()
        assert stats.is_synchronized is True
        # Offset must match true_offset within 0.1ms
        assert pytest.approx(stats.offset_ms, abs=0.1) == true_offset * 1000.0
        # RTT must match 2 * true_delay = 10.0ms within 0.1ms
        assert pytest.approx(stats.rtt_ms, abs=0.1) == (2 * true_delay) * 1000.0
        assert pytest.approx(stats.one_way_delay_ms, abs=0.1) == true_delay * 1000.0

        # Test timestamp translation
        host_time = 1500.0
        rx_time = sync_filter.host_pts_to_receiver_time(host_time)
        assert pytest.approx(rx_time, abs=0.0002) == host_time + true_offset

    def test_ntp_outlier_rejection(self):
        """Verify that sporadic Wi-Fi latency spikes (e.g. 150ms bufferbloat) are rejected."""
        sync_filter = ClockSyncFilter(window_size=20, outlier_std_threshold=2.0)
        true_offset = 5.000
        normal_delay = 0.003  # 3ms

        # Establish baseline
        for i in range(10):
            t0 = 100.0 + i * 0.1
            t1 = t0 + normal_delay + true_offset
            t2 = t1 + 0.0002
            t3 = t2 + normal_delay - true_offset
            sync_filter.add_sample(t0, t1, t2, t3)

        baseline_rtt = sync_filter.get_stats().rtt_ms

        # Inject massive 200ms lag spike
        spike_delay = 0.200
        t0 = 200.0
        t1 = t0 + spike_delay + true_offset
        t2 = t1 + 0.0002
        t3 = t2 + spike_delay - true_offset
        res = sync_filter.add_sample(t0, t1, t2, t3)

        # Outlier should be rejected
        assert res is None
        # Stats should remain clean
        assert pytest.approx(sync_filter.get_stats().rtt_ms, abs=1.0) == baseline_rtt

    def test_master_sync_coordinator_multi_client(self):
        """
        Verify that MasterSyncCoordinator dynamically selects broadcast delay
        based on the slowest client so all devices play in synchronized lockstep.
        """
        coord = MasterSyncCoordinator(base_safety_margin_ms=15.0)

        # Client 1: Fast Ethernet (RTT 2ms, jitter 0.2ms)
        stats1 = SyncStats(rtt_ms=2.0, one_way_delay_ms=1.0, jitter_ms=0.2, is_synchronized=True)
        coord.update_client_stats(client_id=1, stats=stats1)
        # Delay = 1.0 + 3*0.2 + 15.0 = 16.6ms
        assert pytest.approx(coord.get_target_delay() * 1000.0, abs=0.5) == 16.6

        # Client 2: Distant Wi-Fi (RTT 30ms, jitter 5ms)
        stats2 = SyncStats(rtt_ms=30.0, one_way_delay_ms=15.0, jitter_ms=5.0, is_synchronized=True)
        coord.update_client_stats(client_id=2, stats=stats2)
        # Delay must now adapt to Client 2: 15.0 + 3*5.0 + 15.0 = 45.0ms
        assert pytest.approx(coord.get_target_delay() * 1000.0, abs=0.5) == 45.0

        # Remove slow client 2
        coord.remove_client(client_id=2)
        # Delay should return to Client 1's requirement
        assert pytest.approx(coord.get_target_delay() * 1000.0, abs=0.5) == 16.6

    def test_adaptive_jitter_buffer_scheduling(self):
        """Verify that AdaptiveJitterBuffer holds future packets and releases them on scheduled time."""
        fmt = AudioFormat(sample_rate=48000, channels=2, format_code=AudioFormatCode.INT16)
        sync_filter = ClockSyncFilter()
        sync_filter.filtered_offset = 0.0  # Synchronous clocks for test
        sync_filter.synchronized = True

        jb = AdaptiveJitterBuffer(audio_format=fmt, sync_filter=sync_filter, target_delay_override=0.030)

        now = time.time()
        # Packet scheduled 30ms in future
        pkt_pts = now
        samples = np.ones((256, 2), dtype=np.int16) * 42
        pkt = AudioPacket(
            packet_type=PacketType.AUDIO_RAW_PCM,
            format_code=AudioFormatCode.INT16,
            channels=2,
            sample_rate=48000,
            sequence_number=1,
            pts=pkt_pts,
            target_delay=0.030,
            frame_count=256,
            payload=fmt.pcm_to_bytes(samples)
        )
        jb.push_packet(pkt)

        # Immediate process at t = now (packet is still in future)
        pushed = jb.process_and_fill_output(now=now)
        assert pushed == 0  # Not yet time to play

        # Process at t = now + 32ms (packet is due)
        pushed_due = jb.process_and_fill_output(now=now + 0.032)
        assert pushed_due == 256

        # Pull samples from output ring
        pulled = jb.pull_samples(256)
        assert len(pulled) == 256
        assert np.all(pulled == 42)


class TestEndToEndIntegration:
    @pytest.mark.asyncio
    async def test_e2e_host_receiver_sync_and_audio(self):
        """
        Verify end-to-end integration:
        1. Start Host on test ports
        2. Connect Receiver client
        3. Exchange NTP pings and verify clock sync locks
        4. Broadcast synthetic audio packets and verify receiver receives and buffers them
        """
        from src.host import SonicHost
        from src.receiver import SonicReceiver

        test_audio_port = 55105
        test_control_port = 55106
        test_discovery_port = 55107

        # Initialize Host with synthetic sine source
        host = SonicHost(
            source="sine",
            rate=48000,
            channels=2,
            format="int16",
            port=test_audio_port,
            control_port=test_control_port,
            broadcast_ip="127.0.0.1"
        )
        host.discovery_port = test_discovery_port

        # Initialize Receiver
        receiver = SonicReceiver(
            host_ip="127.0.0.1",
            port=test_audio_port,
            control_port=test_control_port
        )
        receiver.discovery_port = test_discovery_port

        host_task = asyncio.create_task(host.run(enable_dashboard=False))
        # Give host server a moment to bind
        await asyncio.sleep(0.1)

        rx_task = asyncio.create_task(receiver.run(enable_dashboard=False))

        # Wait for sync handshake and audio broadcast
        for _ in range(30):
            await asyncio.sleep(0.1)
            stats = receiver.sync_filter.get_stats()
            if stats.is_synchronized and receiver.total_packets_received > 5:
                break

        # Assertions
        stats = receiver.sync_filter.get_stats()
        assert stats.samples_count > 0
        assert stats.rtt_ms >= 0.0
        assert receiver.total_packets_received > 0
        assert receiver.jitter_buffer is not None
        metrics = receiver.jitter_buffer.get_metrics()
        assert metrics["total_received"] > 0

        # Clean shutdown
        host.running = False
        receiver.running = False
        host_task.cancel()
        rx_task.cancel()
        await asyncio.gather(host_task, rx_task, return_exceptions=True)
