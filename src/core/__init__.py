"""SonicSync Core Module."""

from src.core.audio_format import SampleFormat, AudioFormat, numpy_float32_to_pcm, pcm_to_numpy_float32
from src.core.ring_buffer import RingBuffer
from src.core.limiter import SoftKneeLimiter, soft_limit
from src.core.dither import apply_tpdf_dither
from src.core.packet import AudioPacket, HEADER_SIZE, MAGIC_HEADER
from src.core.clock import MasterClock

__all__ = [
    "SampleFormat",
    "AudioFormat",
    "numpy_float32_to_pcm",
    "pcm_to_numpy_float32",
    "RingBuffer",
    "SoftKneeLimiter",
    "soft_limit",
    "apply_tpdf_dither",
    "AudioPacket",
    "HEADER_SIZE",
    "MAGIC_HEADER",
    "MasterClock",
]
