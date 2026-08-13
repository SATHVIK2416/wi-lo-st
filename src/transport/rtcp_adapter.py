"""RFC 3550 RTCP Sender Report (SR) generator for VLC clock synchronization."""

import struct
from dataclasses import dataclass
from typing import Optional, Tuple
from src.core.clock import MasterClock


RTCP_SR_PAYLOAD_TYPE = 200
RTCP_APP_PAYLOAD_TYPE = 204


@dataclass
class RTCPSenderReport:
    """RFC 3550 RTCP Sender Report."""
    ssrc: int
    ntp_msw: int
    ntp_lsw: int
    rtp_timestamp: int
    packet_count: int
    octet_count: int

    def serialize(self) -> bytes:
        """Serialize 28-byte RTCP Sender Report."""
        byte0 = 0x80  # V=2, P=0, RC=0
        pt = RTCP_SR_PAYLOAD_TYPE
        length = 6    # (28 / 4) - 1

        return struct.pack(
            "!BBHIIIIII",
            byte0,
            pt,
            length,
            self.ssrc & 0xFFFFFFFF,
            self.ntp_msw & 0xFFFFFFFF,
            self.ntp_lsw & 0xFFFFFFFF,
            self.rtp_timestamp & 0xFFFFFFFF,
            self.packet_count & 0xFFFFFFFF,
            self.octet_count & 0xFFFFFFFF
        )

    @classmethod
    def deserialize(cls, data: bytes) -> "RTCPSenderReport":
        if len(data) < 28:
            raise ValueError(f"RTCP packet too short: {len(data)} bytes")

        byte0, pt, length, ssrc, msw, lsw, rtp_ts, pkt_cnt, oct_cnt = struct.unpack("!BBHIIIIII", data[:28])
        if pt != RTCP_SR_PAYLOAD_TYPE:
            raise ValueError(f"Expected RTCP SR (PT=200), got PT={pt}")

        return cls(
            ssrc=ssrc,
            ntp_msw=msw,
            ntp_lsw=lsw,
            rtp_timestamp=rtp_ts,
            packet_count=pkt_cnt,
            octet_count=oct_cnt
        )


class RTCPAdapter:
    """Manages RTCP telemetry generation."""

    def __init__(self, ssrc: int):
        self.ssrc = ssrc
        self._packet_count = 0
        self._octet_count = 0

    def record_packet(self, octets: int):
        self._packet_count = (self._packet_count + 1) & 0xFFFFFFFF
        self._octet_count = (self._octet_count + octets) & 0xFFFFFFFF

    def create_sender_report(self, current_rtp_timestamp: int) -> RTCPSenderReport:
        """Create a new RTCP Sender Report with current NTP time."""
        msw, lsw = MasterClock.ntp_timestamp()
        return RTCPSenderReport(
            ssrc=self.ssrc,
            ntp_msw=msw,
            ntp_lsw=lsw,
            rtp_timestamp=current_rtp_timestamp,
            packet_count=self._packet_count,
            octet_count=self._octet_count
        )
