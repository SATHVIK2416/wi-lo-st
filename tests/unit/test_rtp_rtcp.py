"""Unit tests for RFC 3550 RTP and RTCP packetization."""

import numpy as np
import pytest
from src.core.audio_format import AudioFormat, SampleFormat
from src.transport.rtp_adapter import RTPAdapter, RTPPacket
from src.transport.rtcp_adapter import RTCPAdapter, RTCPSenderReport


def test_rtp_packet_roundtrip():
    payload = b"\x12\x34\x56\x78" * 10
    pkt = RTPPacket(
        sequence_number=500,
        timestamp=960000,
        ssrc=123456,
        payload=payload,
        payload_type=96
    )
    raw = pkt.serialize()
    assert len(raw) == 12 + len(payload)

    recovered = RTPPacket.deserialize(raw)
    assert recovered.sequence_number == 500
    assert recovered.timestamp == 960000
    assert recovered.ssrc == 123456
    assert recovered.payload == payload
    assert recovered.payload_type == 96


def test_rtcp_sender_report_roundtrip():
    sr = RTCPSenderReport(
        ssrc=8888,
        ntp_msw=3900000000,
        ntp_lsw=1000000,
        rtp_timestamp=480000,
        packet_count=1000,
        octet_count=960000
    )
    raw = sr.serialize()
    assert len(raw) == 28

    recovered = RTCPSenderReport.deserialize(raw)
    assert recovered.ssrc == 8888
    assert recovered.ntp_msw == 3900000000
    assert recovered.ntp_lsw == 1000000
    assert recovered.rtp_timestamp == 480000
    assert recovered.packet_count == 1000
    assert recovered.octet_count == 960000


def test_rtp_adapter_packetize():
    adapter = RTPAdapter(AudioFormat(sample_rate=48000, channels=2))
    audio_data = np.zeros((480, 2), dtype=np.float32)  # 10ms
    pkt = adapter.packetize(audio_data, SampleFormat.INT16)

    assert pkt.payload_type == 96
    assert len(pkt.payload) == 480 * 2 * 2  # 1920 bytes for 10ms L16
