"""Dynamic SDP (Session Description Protocol) and M3U session file generator for VLC."""

import time
from typing import Optional
from src.core.audio_format import AudioFormat, SampleFormat

RTP_DEFAULT_PORT = 5006
MULTICAST_GROUP = "239.255.0.1"


def generate_sdp(
    host_ip: str = MULTICAST_GROUP,
    port: int = RTP_DEFAULT_PORT,
    audio_format: Optional[AudioFormat] = None,
    session_name: str = "SonicSync Lossless Stream",
    is_multicast: bool = True
) -> str:
    """Generate RFC 4566 Session Description Protocol (SDP) text for VLC."""
    fmt = audio_format or AudioFormat()
    session_id = int(time.time())

    # Map format name for SDP rtpmap
    # L16 for 16-bit linear PCM, L24 for 24-bit linear PCM
    encoding_name = "L16"
    if fmt.sample_format == SampleFormat.INT24:
        encoding_name = "L24"
    elif fmt.sample_format == SampleFormat.FLOAT32:
        encoding_name = "L16"  # VLC best compatibility

    sdp_lines = [
        "v=0",
        f"o=- {session_id} 1 IN IP4 {host_ip}",
        f"s={session_name}",
        f"c=IN IP4 {host_ip}",
        "t=0 0",
        f"m=audio {port} RTP/AVP 96",
        f"a=rtpmap:96 {encoding_name}/{fmt.sample_rate}/{fmt.channels}",
        "a=recvonly" if not is_multicast else "a=sendonly",
        "a=ptime:10",  # 10 ms packet duration
    ]
    return "\r\n".join(sdp_lines) + "\r\n"


def generate_m3u(
    stream_url_or_ip: str = MULTICAST_GROUP,
    port: int = RTP_DEFAULT_PORT,
    title: str = "SonicSync Lossless Multi-Room Audio"
) -> str:
    """Generate M3U playlist file content for 1-click opening in VLC."""
    if "://" in stream_url_or_ip:
        target_url = stream_url_or_ip
    else:
        target_url = f"rtp://@{stream_url_or_ip}:{port}"

    return f"#EXTM3U\n#EXTINF:-1,{title}\n{target_url}\n"
