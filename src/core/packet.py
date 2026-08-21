"""SonicSync 42-byte binary wire protocol packetizer and deserializer."""

import struct
import zlib
from dataclasses import dataclass
from typing import Optional
from src.core.audio_format import SampleFormat


MAGIC_HEADER = b"SONI"
PROTOCOL_VERSION = 0x02
PACKET_TYPE_AUDIO = 0x01
PACKET_TYPE_CONTROL = 0x02
PACKET_TYPE_NTP = 0x03
VALID_PACKET_TYPES = (PACKET_TYPE_AUDIO, PACKET_TYPE_CONTROL, PACKET_TYPE_NTP)

# Struct format: 4s (Magic), B (Ver), B (PktType), B (Format), B (Channels),
#                I (SampleRate), I (SeqNum), d (PTS), d (TargetDelay),
#                H (FrameCount), I (PayloadLen), I (CRC32)
HEADER_STRUCT_FORMAT = "!4sBBBBIIddHII"
HEADER_SIZE = struct.calcsize(HEADER_STRUCT_FORMAT)  # 42 bytes


@dataclass
class AudioPacket:
    """SonicSync binary audio packet."""
    sequence_number: int
    pts: float
    target_playout_delay: float
    frame_count: int
    payload: bytes
    sample_rate: int = 48000
    channels: int = 2
    sample_format: SampleFormat = SampleFormat.FLOAT32
    version: int = PROTOCOL_VERSION
    packet_type: int = PACKET_TYPE_AUDIO
    crc32: Optional[int] = None

    def serialize(self) -> bytes:
        """Serialize audio packet into binary buffer with 42-byte header."""
        payload_len = len(self.payload)
        header = struct.pack(
            HEADER_STRUCT_FORMAT,
            MAGIC_HEADER,
            self.version,
            self.packet_type,
            int(self.sample_format),
            self.channels,
            self.sample_rate,
            self.sequence_number,
            float(self.pts),
            float(self.target_playout_delay),
            self.frame_count,
            payload_len,
            0
        )
        checksum = zlib.crc32(header + self.payload) & 0xFFFFFFFF
        header = header[:-4] + struct.pack("!I", checksum)
        return header + self.payload

    @classmethod
    def deserialize(cls, data: bytes, verify_crc: bool = True) -> "AudioPacket":
        """Parse raw bytes into AudioPacket.

        Args:
            data: Binary buffer containing header and payload
            verify_crc: If True, validate CRC32 checksum

        Raises:
            ValueError: If packet is malformed, too short, has invalid magic,
                unsupported version, unknown packet type, inconsistent payload
                length, or fails CRC32
        """
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Packet too short: {len(data)} bytes (expected >= {HEADER_SIZE})")

        (
            magic,
            version,
            pkt_type,
            fmt,
            channels,
            sample_rate,
            seq_num,
            pts,
            target_delay,
            frame_count,
            payload_len,
            checksum
        ) = struct.unpack(HEADER_STRUCT_FORMAT, data[:HEADER_SIZE])

        if magic != MAGIC_HEADER:
            raise ValueError(f"Invalid magic header: {magic!r} (expected {MAGIC_HEADER!r})")

        if version != PROTOCOL_VERSION:
            raise ValueError(f"Unsupported protocol version: {version:#04x} (expected {PROTOCOL_VERSION:#04x})")

        if pkt_type not in VALID_PACKET_TYPES:
            raise ValueError(f"Unknown packet type: {pkt_type:#04x}")

        expected_payload_len = frame_count * channels * SampleFormat(fmt).bytes_per_sample
        if payload_len != expected_payload_len:
            raise ValueError(
                f"Payload length mismatch: header declares {payload_len} bytes, "
                f"but frame_count={frame_count} x channels={channels} x "
                f"{SampleFormat(fmt).bytes_per_sample} bytes/sample = {expected_payload_len}"
            )

        payload = data[HEADER_SIZE:HEADER_SIZE + payload_len]
        if len(payload) < payload_len:
            raise ValueError(f"Truncated payload: got {len(payload)} bytes, expected {payload_len}")

        if verify_crc:
            # Recompute over header+payload with the CRC field itself zeroed,
            # matching how serialize() computed it
            crc_region = bytearray(data[:HEADER_SIZE + payload_len])
            crc_region[HEADER_SIZE - 4:HEADER_SIZE] = b"\x00\x00\x00\x00"
            actual_crc = zlib.crc32(bytes(crc_region)) & 0xFFFFFFFF
            if actual_crc != checksum:
                raise ValueError(f"CRC32 mismatch: calculated {actual_crc:#010x}, expected {checksum:#010x}")

        return cls(
            sequence_number=seq_num,
            pts=pts,
            target_playout_delay=target_delay,
            frame_count=frame_count,
            payload=payload,
            sample_rate=sample_rate,
            channels=channels,
            sample_format=SampleFormat(fmt),
            version=version,
            packet_type=pkt_type,
            crc32=checksum
        )
