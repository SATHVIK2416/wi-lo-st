"""Unit tests for SonicSync 42-byte binary packet serialization and CRC32 verification."""

import pytest
from src.core.audio_format import SampleFormat
from src.core.packet import (
    AudioPacket,
    HEADER_SIZE,
    MAGIC_HEADER,
    PROTOCOL_VERSION,
    PACKET_TYPE_AUDIO,
    PACKET_TYPE_CONTROL,
    PACKET_TYPE_NTP,
)


def test_packet_serialization_roundtrip():
    payload = b"\x00\x01\x02\x03\x04\x05\x06\x07" * 10
    pkt = AudioPacket(
        sequence_number=12345,
        pts=100.2505,
        target_playout_delay=0.100,
        frame_count=10,
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
    assert recovered.frame_count == 10
    assert recovered.payload == payload
    assert recovered.sample_rate == 48000
    assert recovered.channels == 2
    assert recovered.sample_format == SampleFormat.FLOAT32
    assert recovered.version == PROTOCOL_VERSION


def test_packet_crc_corruption_detection():
    payload = b"Hello Audio Payload\x00\x00\x00\x00\x00"
    pkt = AudioPacket(
        sequence_number=1,
        pts=1.0,
        target_playout_delay=0.1,
        frame_count=3,
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


def test_packet_wrong_version_rejected():
    pkt = AudioPacket(
        sequence_number=1,
        pts=1.0,
        target_playout_delay=0.1,
        frame_count=2,
        payload=b"\x00" * 16,
        version=0x01
    )
    raw_bytes = pkt.serialize()

    with pytest.raises(ValueError, match="Unsupported protocol version"):
        AudioPacket.deserialize(raw_bytes, verify_crc=True)


def test_packet_payload_len_mismatch_rejected():
    pkt = AudioPacket(
        sequence_number=1,
        pts=1.0,
        target_playout_delay=0.1,
        frame_count=99,
        payload=b"\x00" * 16,
        channels=2,
        sample_format=SampleFormat.FLOAT32
    )
    raw_bytes = pkt.serialize()

    with pytest.raises(ValueError, match="Payload length mismatch"):
        AudioPacket.deserialize(raw_bytes, verify_crc=True)


def test_packet_unknown_type_rejected():
    pkt = AudioPacket(
        sequence_number=1,
        pts=1.0,
        target_playout_delay=0.1,
        frame_count=2,
        payload=b"\x00" * 16,
        packet_type=0x7F
    )
    raw_bytes = pkt.serialize()

    with pytest.raises(ValueError, match="Unknown packet type"):
        AudioPacket.deserialize(raw_bytes, verify_crc=True)


def test_packet_known_types_accepted():
    for pkt_type in (PACKET_TYPE_AUDIO, PACKET_TYPE_CONTROL, PACKET_TYPE_NTP):
        pkt = AudioPacket(
            sequence_number=1,
            pts=1.0,
            target_playout_delay=0.1,
            frame_count=2,
            payload=b"\x00" * 16,
            packet_type=pkt_type
        )
        recovered = AudioPacket.deserialize(pkt.serialize(), verify_crc=True)
        assert recovered.packet_type == pkt_type


def test_packet_serialize_does_not_mutate_crc32():
    pkt = AudioPacket(
        sequence_number=7,
        pts=2.5,
        target_playout_delay=0.1,
        frame_count=4,
        payload=b"\x01\x02\x03\x04" * 8
    )
    assert pkt.crc32 is None

    first = pkt.serialize()
    assert pkt.crc32 is None

    second = pkt.serialize()
    assert first == second
    assert pkt.crc32 is None


def test_packet_header_corruption_detected():
    pkt = AudioPacket(
        sequence_number=42,
        pts=1.0,
        target_playout_delay=0.1,
        frame_count=2,
        payload=b"\x00" * 16
    )
    raw_bytes = bytearray(pkt.serialize())

    # Flip a bit inside the header (sequence number field)
    raw_bytes[10] ^= 0x01

    with pytest.raises(ValueError, match="CRC32 mismatch"):
        AudioPacket.deserialize(bytes(raw_bytes), verify_crc=True)
