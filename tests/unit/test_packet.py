"""Unit tests for SonicSync 42-byte binary packet serialization and CRC32 verification."""

import pytest
from src.core.audio_format import SampleFormat
from src.core.packet import AudioPacket, HEADER_SIZE, MAGIC_HEADER


def test_packet_serialization_roundtrip():
    payload = b"\x00\x01\x02\x03\x04\x05\x06\x07" * 10
    pkt = AudioPacket(
        sequence_number=12345,
        pts=100.2505,
        target_playout_delay=0.100,
        frame_count=20,
        payload=payload,
        sample_rate=48000,
        channels=2,
        sample_format=SampleFormat.FLOAT32
    )

    raw_bytes = pkt.serialize()
    assert len(raw_bytes) == HEADER_SIZE + len(payload)
    assert raw_bytes[:4] == MAGIC_HEADER

    recovered = AudioPacket.deserialize(raw_bytes, verify_crc=True)
    assert recovered.sequence_number == 12345
    assert abs(recovered.pts - 100.2505) < 1e-6
    assert abs(recovered.target_playout_delay - 0.100) < 1e-6
    assert recovered.frame_count == 20
    assert recovered.payload == payload
    assert recovered.sample_rate == 48000
    assert recovered.channels == 2
    assert recovered.sample_format == SampleFormat.FLOAT32


def test_packet_crc_corruption_detection():
    payload = b"Hello Audio Payload"
    pkt = AudioPacket(
        sequence_number=1,
        pts=1.0,
        target_playout_delay=0.1,
        frame_count=5,
        payload=payload
    )
    raw_bytes = bytearray(pkt.serialize())

    # Corrupt one payload byte
    raw_bytes[-1] ^= 0xFF

    with pytest.raises(ValueError, match="CRC32 mismatch"):
        AudioPacket.deserialize(bytes(raw_bytes), verify_crc=True)


def test_packet_invalid_magic():
    bad_bytes = b"BADM" + b"\x00" * 50
    with pytest.raises(ValueError, match="Invalid magic header"):
        AudioPacket.deserialize(bad_bytes)
