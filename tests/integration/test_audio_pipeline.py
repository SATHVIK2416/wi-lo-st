"""Integration test for complete end-to-end audio pipeline."""

import numpy as np
import pytest
from src.core.audio_format import AudioFormat, SampleFormat, numpy_float32_to_pcm, pcm_to_numpy_float32
from src.core.clock import MasterClock
from src.core.limiter import SoftKneeLimiter
from src.core.packet import AudioPacket
from src.core.ring_buffer import RingBuffer
from src.capture.test_generator import TestGeneratorSource, TestSignalType


def test_complete_audio_flow():
    fmt = AudioFormat(sample_rate=48000, channels=2, sample_format=SampleFormat.FLOAT32)
    clock = MasterClock()
    ring = RingBuffer(capacity_frames=48000, channels=2)
    limiter = SoftKneeLimiter(sample_rate=48000, channels=2)
    gen = TestGeneratorSource(audio_format=fmt, signal_type=TestSignalType.SINE_1KHZ)

    # 1. Generate 10ms audio chunk
    frames = gen.generate_frames(480)
    assert frames.shape == (480, 2)

    # 2. Write to ring buffer
    ring.write(frames)
    assert ring.available_read() == 480

    # 3. Read from ring buffer and limit
    read_chunk = ring.read(480)
    limited = limiter.process(read_chunk)
    assert np.all(limited <= 1.0)
    assert np.all(limited >= -1.0)

    # 4. Serialize to 42-byte binary packet
    payload = numpy_float32_to_pcm(limited, SampleFormat.FLOAT32)
    pkt = AudioPacket(
        sequence_number=1,
        pts=clock.now(),
        target_playout_delay=0.100,
        frame_count=480,
        payload=payload
    )
    raw = pkt.serialize()
    assert len(raw) == 42 + (480 * 2 * 4)

    # 5. Receiver deserializes and extracts audio
    rec_pkt = AudioPacket.deserialize(raw, verify_crc=True)
    recovered_audio = pcm_to_numpy_float32(rec_pkt.payload, rec_pkt.sample_format, rec_pkt.channels)

    np.testing.assert_allclose(recovered_audio, limited, atol=1e-6)
