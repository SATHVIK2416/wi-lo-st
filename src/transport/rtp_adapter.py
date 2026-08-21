"""RFC 3550 RTP Audio Packetizer for standard VLC and streaming clients."""

import random
import struct
from dataclasses import dataclass
from typing import Optional
import numpy as np

from src.core.audio_format import AudioFormat, SampleFormat, numpy_float32_to_pcm


RTP_HEADER_SIZE = 12  # Standard 12-byte RFC 3550 header


@dataclass
class RTPPacket:
    """RFC 3550 RTP Audio Packet."""
    sequence_number: int
    timestamp: int
    ssrc: int
    payload: bytes
    payload_type: int = 96  # Dynamic payload type (e.g. 96 for L16/L24/Float32)
    marker: bool = False

    def serialize(self) -> bytes:
        """Serialize into 12-byte RTP header + payload."""
        # Byte 0: V=2, P=0, X=0, CC=0 -> 0x80
        byte0 = 0x80
        # Byte 1: Marker (1 bit) | Payload Type (7 bits)
        byte1 = (int(self.marker) << 7) | (self.payload_type & 0x7F)

        header = struct.pack(
            "!BBHII",
            byte0,
            byte1,
            self.sequence_number & 0xFFFF,
            self.timestamp & 0xFFFFFFFF,
            self.ssrc & 0xFFFFFFFF
        )
        return header + self.payload

    @classmethod
    def deserialize(cls, data: bytes) -> "RTPPacket":
        if len(data) < RTP_HEADER_SIZE:
            raise ValueError(f"RTP packet too short: {len(data)} bytes")

        byte0, byte1, seq, ts, ssrc = struct.unpack("!BBHII", data[:RTP_HEADER_SIZE])
        version = (byte0 >> 6) & 0x03
        if version != 2:
            raise ValueError(f"Unsupported RTP version: {version}")

        marker = bool((byte1 >> 7) & 0x01)
        pt = byte1 & 0x7F
        payload = data[RTP_HEADER_SIZE:]

        return cls(
            sequence_number=seq,
            timestamp=ts,
            ssrc=ssrc,
            payload=payload,
            payload_type=pt,
            marker=marker
        )


class RTPAdapter:
    """Packetizes raw audio blocks into RFC 3550 standard RTP packets."""

    def __init__(
        self,
        audio_format: Optional[AudioFormat] = None,
        payload_type: int = 96,
        ssrc: Optional[int] = None
    ):
        self.audio_format = audio_format or AudioFormat()
        self.payload_type = payload_type
        self.ssrc = ssrc if ssrc is not None else random.randint(100000, 999999)
        self._seq = random.randint(0, 65535)
        self._rtp_timestamp = random.randint(0, 4294967295)

    @property
    def current_rtp_timestamp(self) -> int:
        """Current RTP timestamp for RTCP sender reports."""
        return self._rtp_timestamp

    def packetize(self, audio_data: np.ndarray, sample_format: Optional[SampleFormat] = None) -> RTPPacket:
        """Convert a block of audio frames to an RTPPacket.

        Args:
            audio_data: float32 numpy array shaped (frames, channels)
            sample_format: Sample format to encode payload in (default: INT16 or FLOAT32)

        Returns:
            RTPPacket: Constructed RTP packet
        """
        fmt = sample_format or SampleFormat.INT16
        # Standard VLC PCM streaming commonly uses big-endian or little-endian L16
        # When sending L16 in RTP (RFC 3551), samples are big-endian 16-bit
        if fmt == SampleFormat.INT16:
            clipped = np.clip(audio_data, -1.0, 1.0)
            scaled = np.round(clipped * 32767.0).astype('>i2')  # Big-endian for RFC 3551 L16
            payload = scaled.tobytes()
        else:
            payload = numpy_float32_to_pcm(audio_data, fmt)

        num_frames = audio_data.shape[0] if audio_data.ndim > 1 else len(audio_data)

        packet = RTPPacket(
            sequence_number=self._seq,
            timestamp=self._rtp_timestamp,
            ssrc=self.ssrc,
            payload=payload,
            payload_type=self.payload_type
        )

        self._seq = (self._seq + 1) & 0xFFFF
        self._rtp_timestamp = (self._rtp_timestamp + num_frames) & 0xFFFFFFFF
        return packet
