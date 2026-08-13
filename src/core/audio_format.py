"""Audio format definitions and conversions for SonicSync."""

from dataclasses import dataclass
from enum import IntEnum
import numpy as np


class SampleFormat(IntEnum):
    """Supported binary sample formats."""
    INT16 = 0x01
    INT24 = 0x02
    INT32 = 0x03
    FLOAT32 = 0x04

    @property
    def bytes_per_sample(self) -> int:
        if self == SampleFormat.INT16:
            return 2
        elif self == SampleFormat.INT24:
            return 3
        elif self == SampleFormat.INT32:
            return 4
        elif self == SampleFormat.FLOAT32:
            return 4
        raise ValueError(f"Unknown SampleFormat: {self}")

    @property
    def numpy_dtype(self):
        if self == SampleFormat.INT16:
            return np.int16
        elif self == SampleFormat.INT32:
            return np.int32
        elif self == SampleFormat.FLOAT32:
            return np.float32
        elif self == SampleFormat.INT24:
            return np.int32  # 24-bit processed as 32-bit integer in memory
        raise ValueError(f"Unknown SampleFormat: {self}")


@dataclass(frozen=True)
class AudioFormat:
    """Audio configuration specifications."""
    sample_rate: int = 48000
    channels: int = 2
    sample_format: SampleFormat = SampleFormat.FLOAT32

    @property
    def bytes_per_sample(self) -> int:
        return self.sample_format.bytes_per_sample

    @property
    def frame_size(self) -> int:
        """Size in bytes of one multi-channel frame."""
        return self.channels * self.bytes_per_sample

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.frame_size

    def frames_to_bytes(self, num_frames: int) -> int:
        return num_frames * self.frame_size

    def bytes_to_frames(self, num_bytes: int) -> int:
        return num_bytes // self.frame_size

    def duration_to_frames(self, duration_seconds: float) -> int:
        return int(round(duration_seconds * self.sample_rate))

    def frames_to_duration(self, num_frames: int) -> float:
        return num_frames / float(self.sample_rate)


def numpy_float32_to_pcm(data: np.ndarray, target_format: SampleFormat) -> bytes:
    """Convert float32 numpy array (normalized -1.0 to 1.0) to raw PCM bytes.

    Args:
        data: Numpy float32 array of shape (frames, channels) or (frames,)
        target_format: The target SampleFormat

    Returns:
        bytes: Raw serialized PCM bytes
    """
    data = np.asarray(data, dtype=np.float32)
    # Clip to legal range
    clipped = np.clip(data, -1.0, 1.0)

    if target_format == SampleFormat.FLOAT32:
        return clipped.astype('<f4').tobytes()

    elif target_format == SampleFormat.INT16:
        scaled = np.round(clipped * 32767.0).astype('<i2')
        return scaled.tobytes()

    elif target_format == SampleFormat.INT32:
        scaled = np.round(clipped * 2147483647.0).astype('<i4')
        return scaled.tobytes()

    elif target_format == SampleFormat.INT24:
        # Scale to 24-bit signed integer [-8388608, 8388607]
        scaled = np.round(clipped * 8388607.0).astype(np.int32)
        # Flatten array
        flat = scaled.ravel()
        # Convert each 32-bit int to 3 bytes (little-endian)
        # Using uint8 byte slicing for maximum performance
        raw32 = flat.astype('<i4').tobytes()
        # raw32 has 4 bytes per sample [B0, B1, B2, B3]. We take [B0, B1, B2]
        arr_bytes = np.frombuffer(raw32, dtype=np.uint8).reshape(-1, 4)
        packed24 = arr_bytes[:, :3].tobytes()
        return packed24

    raise ValueError(f"Unsupported target format: {target_format}")


def pcm_to_numpy_float32(raw_bytes: bytes, source_format: SampleFormat, channels: int = 2) -> np.ndarray:
    """Convert raw PCM bytes to normalized float32 numpy array [-1.0, 1.0].

    Args:
        raw_bytes: Raw PCM byte buffer
        source_format: The source SampleFormat
        channels: Number of audio channels

    Returns:
        np.ndarray: float32 array shaped (frames, channels)
    """
    if len(raw_bytes) == 0:
        return np.zeros((0, channels), dtype=np.float32)

    if source_format == SampleFormat.FLOAT32:
        arr = np.frombuffer(raw_bytes, dtype='<f4')
        return arr.reshape(-1, channels).astype(np.float32)

    elif source_format == SampleFormat.INT16:
        arr = np.frombuffer(raw_bytes, dtype='<i2').astype(np.float32)
        arr /= 32767.0
        return arr.reshape(-1, channels)

    elif source_format == SampleFormat.INT32:
        arr = np.frombuffer(raw_bytes, dtype='<i4').astype(np.float32)
        arr /= 2147483647.0
        return arr.reshape(-1, channels)

    elif source_format == SampleFormat.INT24:
        # Unpack 3-byte little endian to 32-bit signed ints
        raw_arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        num_samples = len(raw_arr) // 3
        # Reshape to (num_samples, 3)
        triplets = raw_arr[:num_samples * 3].reshape(num_samples, 3)
        # Pad with 0 for least significant or sign byte
        # Little endian 24-bit: byte0 = LSB, byte1 = MID, byte2 = MSB (signed)
        # Construct 32-bit signed int by shifting byte2 to MSB of int32
        b0 = triplets[:, 0].astype(np.int32)
        b1 = triplets[:, 1].astype(np.int32)
        b2 = triplets[:, 2].astype(np.int32)

        # Handle sign extension for 24-bit negative numbers (where b2 & 0x80 != 0)
        sign = (b2 >= 128).astype(np.int32) * (-16777216)  # 0xFF000000
        val = b0 | (b1 << 8) | (b2 << 16) | sign
        arr = val.astype(np.float32) / 8388607.0
        return arr.reshape(-1, channels)

    raise ValueError(f"Unsupported source format: {source_format}")
