"""Unit tests for SDP and M3U generator."""

import pytest
from src.core.audio_format import AudioFormat, SampleFormat
from src.transport.sdp_generator import generate_sdp, generate_m3u


def test_sdp_generator():
    fmt = AudioFormat(sample_rate=48000, channels=2, sample_format=SampleFormat.FLOAT32)
    sdp = generate_sdp(host_ip="239.255.0.1", port=5004, audio_format=fmt)

    assert "v=0" in sdp
    assert "m=audio 5004 RTP/AVP 96" in sdp
    assert "a=rtpmap:96 L16/48000/2" in sdp
    assert "c=IN IP4 239.255.0.1" in sdp


def test_m3u_generator():
    m3u = generate_m3u(stream_url_or_ip="239.255.0.1", port=5004)
    assert "#EXTM3U" in m3u
    assert "rtp://@239.255.0.1:5004" in m3u
