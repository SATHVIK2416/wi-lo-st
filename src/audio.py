"""
SonicSync - High-Fidelity Lossless Audio Engine
Provides audio format definitions, lossless PCM/FLAC serialization,
low-latency capture/playback abstractions, ring buffers, and test signal generators.
"""

import enum
import io
import math
import struct
import threading
import time
import zlib
from dataclasses import dataclass
from typing import Callable, Optional, Tuple, Union

import numpy as np

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    import soundfile as sf
    HAS_SOUNDFILE = True
except ImportError:
    HAS_SOUNDFILE = False

# Protocol Constants
MAGIC_HEADER = b"SONI"
PROTOCOL_VERSION = 1


class AudioFormatCode(enum.IntEnum):
    INT16 = 1
    INT24 = 2
    INT32 = 3
    FLOAT32 = 4


class PacketType(enum.IntEnum):
    AUDIO_RAW_PCM = 0x01
    AUDIO_FLAC = 0x02
    SYNC_PING = 0x10
    SYNC_PONG = 0x11
    BEACON_DISCOVERY = 0x20
    CONTROL_CMD = 0x30
    TELEMETRY = 0x40


class CompressionType(enum.IntEnum):
    NONE = 0
    FLAC = 1


@dataclass
class AudioFormat:
    sample_rate: int = 48000
    channels: int = 2
    format_code: AudioFormatCode = AudioFormatCode.INT16
    block_size: int = 256
    compression: CompressionType = CompressionType.NONE

    @property
    def numpy_dtype(self) -> np.dtype:
        if self.format_code == AudioFormatCode.INT16:
            return np.int16
        elif self.format_code == AudioFormatCode.INT32 or self.format_code == AudioFormatCode.INT24:
            return np.int32
        elif self.format_code == AudioFormatCode.FLOAT32:
            return np.float32
        return np.int16

    @property
    def bytes_per_sample(self) -> int:
        if self.format_code == AudioFormatCode.INT16:
            return 2
        elif self.format_code == AudioFormatCode.INT24:
            return 3
        elif self.format_code == AudioFormatCode.INT32 or self.format_code == AudioFormatCode.FLOAT32:
            return 4
        return 2

    @property
    def bytes_per_frame(self) -> int:
        return self.channels * self.bytes_per_sample

    def pcm_to_bytes(self, samples: np.ndarray) -> bytes:
        """Converts numpy sample array to raw bytes according to format."""
        if not isinstance(samples, np.ndarray):
            samples = np.asarray(samples)

        # Convert to target dtype
        if self.format_code == AudioFormatCode.INT16:
            if samples.dtype != np.int16:
                if np.issubdtype(samples.dtype, np.floating):
                    samples = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
                else:
                    samples = samples.astype(np.int16)
            return samples.tobytes()

        elif self.format_code == AudioFormatCode.FLOAT32:
            if samples.dtype != np.float32:
                if np.issubdtype(samples.dtype, np.integer):
                    max_val = np.iinfo(samples.dtype).max
                    samples = (samples / float(max_val)).astype(np.float32)
                else:
                    samples = samples.astype(np.float32)
            return samples.tobytes()

        elif self.format_code == AudioFormatCode.INT32:
            if samples.dtype != np.int32:
                if np.issubdtype(samples.dtype, np.floating):
                    samples = (np.clip(samples, -1.0, 1.0) * 2147483647.0).astype(np.int32)
                else:
                    samples = samples.astype(np.int32)
            return samples.tobytes()

        elif self.format_code == AudioFormatCode.INT24:
            # 24-bit PCM: Pack 3 bytes per sample (little-endian)
            if samples.dtype != np.int32:
                if np.issubdtype(samples.dtype, np.floating):
                    samples = (np.clip(samples, -1.0, 1.0) * 8388607.0).astype(np.int32)
                else:
                    samples = samples.astype(np.int32)
            
            # Pack int32 into 3-byte little endian
            flat = samples.flatten()
            b = bytearray(len(flat) * 3)
            for i, val in enumerate(flat):
                v = int(val) & 0xFFFFFF
                b[i * 3] = v & 0xFF
                b[i * 3 + 1] = (v >> 8) & 0xFF
                b[i * 3 + 2] = (v >> 16) & 0xFF
            return bytes(b)

        return samples.tobytes()

    def bytes_to_pcm(self, data: bytes, frame_count: Optional[int] = None) -> np.ndarray:
        """Converts raw bytes to numpy array matching this format."""
        if self.format_code == AudioFormatCode.INT16:
            arr = np.frombuffer(data, dtype=np.int16)
        elif self.format_code == AudioFormatCode.FLOAT32:
            arr = np.frombuffer(data, dtype=np.float32)
        elif self.format_code == AudioFormatCode.INT32:
            arr = np.frombuffer(data, dtype=np.int32)
        elif self.format_code == AudioFormatCode.INT24:
            # Unpack 3-byte little endian into int32
            num_samples = len(data) // 3
            arr = np.empty(num_samples, dtype=np.int32)
            for i in range(num_samples):
                b0 = data[i * 3]
                b1 = data[i * 3 + 1]
                b2 = data[i * 3 + 2]
                val = b0 | (b1 << 8) | (b2 << 16)
                # Sign extend 24-bit to 32-bit
                if val & 0x800000:
                    val -= 0x1000000
                arr[i] = val
        else:
            arr = np.frombuffer(data, dtype=np.int16)

        if self.channels > 1:
            arr = arr.reshape(-1, self.channels)
        else:
            arr = arr.reshape(-1, 1)

        if frame_count is not None and len(arr) > frame_count:
            arr = arr[:frame_count]
        return arr

    def compress(self, pcm_bytes: bytes, frame_count: int) -> Tuple[bytes, PacketType]:
        """Losslessly compresses PCM bytes if FLAC is selected and available, else returns raw PCM."""
        if self.compression == CompressionType.FLAC and HAS_SOUNDFILE:
            pcm_arr = self.bytes_to_pcm(pcm_bytes, frame_count)
            bio = io.BytesIO()
            subtype = 'PCM_16' if self.format_code == AudioFormatCode.INT16 else 'PCM_24'
            sf.write(bio, pcm_arr, self.sample_rate, format='FLAC', subtype=subtype)
            compressed = bio.getvalue()
            # If FLAC is larger than raw PCM (e.g. for tiny blocks), stick to raw PCM
            if len(compressed) < len(pcm_bytes):
                return compressed, PacketType.AUDIO_FLAC
        return pcm_bytes, PacketType.AUDIO_RAW_PCM

    def decompress(self, payload: bytes, packet_type: PacketType, frame_count: int) -> np.ndarray:
        """Decompresses payload back to PCM numpy array."""
        if packet_type == PacketType.AUDIO_FLAC and HAS_SOUNDFILE:
            bio = io.BytesIO(payload)
            data, _ = sf.read(bio, dtype=self.numpy_dtype, always_2d=True)
            return data
        return self.bytes_to_pcm(payload, frame_count)


# Compact Binary Header Struct
# 4s  : Magic "SONI" (4 bytes)
# B   : Version (1 byte)
# B   : PacketType (1 byte)
# B   : FormatCode (1 byte)
# B   : Channels (1 byte)
# I   : SampleRate (4 bytes)
# Q   : SequenceNumber (8 bytes)
# d   : HostTimestampPTS (8 bytes)
# f   : TargetDelayOffset (4 bytes)
# H   : FrameCount (2 bytes)
# I   : PayloadLength (4 bytes)
# I   : CRC32 (4 bytes)
# Total Header Size: 4 + 1 + 1 + 1 + 1 + 4 + 8 + 8 + 4 + 2 + 4 + 4 = 42 bytes
HEADER_FORMAT = "!4sBBBBIQdfHII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


@dataclass
class AudioPacket:
    packet_type: PacketType
    format_code: AudioFormatCode
    channels: int
    sample_rate: int
    sequence_number: int
    pts: float                  # Host master clock presentation timestamp in seconds
    target_delay: float         # Server computed broadcast delay in seconds
    frame_count: int
    payload: bytes
    version: int = PROTOCOL_VERSION

    def pack(self) -> bytes:
        """Serializes header and payload into wire format with CRC32 integrity check."""
        crc = zlib.crc32(self.payload) & 0xFFFFFFFF
        header = struct.pack(
            HEADER_FORMAT,
            MAGIC_HEADER,
            self.version,
            int(self.packet_type),
            int(self.format_code),
            self.channels,
            self.sample_rate,
            self.sequence_number,
            self.pts,
            self.target_delay,
            self.frame_count,
            len(self.payload),
            crc
        )
        return header + self.payload

    @classmethod
    def unpack(cls, raw_data: bytes) -> Optional["AudioPacket"]:
        """Unpacks raw wire bytes into an AudioPacket, validating magic and CRC32."""
        if len(raw_data) < HEADER_SIZE:
            return None

        (
            magic,
            version,
            pkt_type_raw,
            fmt_code_raw,
            channels,
            sample_rate,
            seq_num,
            pts,
            target_delay,
            frame_count,
            payload_len,
            crc
        ) = struct.unpack(HEADER_FORMAT, raw_data[:HEADER_SIZE])

        if magic != MAGIC_HEADER:
            return None

        payload = raw_data[HEADER_SIZE:HEADER_SIZE + payload_len]
        if len(payload) != payload_len:
            return None

        # Verify CRC32
        computed_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if computed_crc != crc:
            return None

        return cls(
            packet_type=PacketType(pkt_type_raw),
            format_code=AudioFormatCode(fmt_code_raw),
            channels=channels,
            sample_rate=sample_rate,
            sequence_number=seq_num,
            pts=pts,
            target_delay=target_delay,
            frame_count=frame_count,
            payload=payload,
            version=version
        )


class RingBuffer:
    """
    Thread-safe circular FIFO ring buffer for audio samples.
    Bridging network receive threads and real-time audio DAC callbacks.
    """

    def __init__(self, capacity_frames: int, channels: int = 2, dtype: np.dtype = np.int16):
        self.capacity = capacity_frames
        self.channels = channels
        self.dtype = dtype
        self.buffer = np.zeros((capacity_frames, channels), dtype=dtype)
        self.read_pos = 0
        self.write_pos = 0
        self.available_frames = 0
        self.lock = threading.Lock()
        self.underflows = 0
        self.overflows = 0

    def write(self, samples: np.ndarray) -> int:
        """Writes samples into ring buffer. Returns number of frames written."""
        if samples.ndim == 1:
            samples = samples.reshape(-1, 1)
        frames_to_write = len(samples)
        if frames_to_write == 0:
            return 0

        with self.lock:
            free_space = self.capacity - self.available_frames
            if frames_to_write > free_space:
                # Buffer overflow: advance read pointer (drop oldest)
                drop = frames_to_write - free_space
                self.read_pos = (self.read_pos + drop) % self.capacity
                self.available_frames -= drop
                self.overflows += 1

            # First chunk
            first_chunk = min(frames_to_write, self.capacity - self.write_pos)
            self.buffer[self.write_pos:self.write_pos + first_chunk] = samples[:first_chunk]
            
            # Second wrapped chunk if any
            second_chunk = frames_to_write - first_chunk
            if second_chunk > 0:
                self.buffer[0:second_chunk] = samples[first_chunk:first_chunk + second_chunk]

            self.write_pos = (self.write_pos + frames_to_write) % self.capacity
            self.available_frames += frames_to_write
            return frames_to_write

    def read(self, requested_frames: int) -> np.ndarray:
        """Reads requested frames from ring buffer. Pads with silence on underflow."""
        with self.lock:
            out = np.zeros((requested_frames, self.channels), dtype=self.dtype)
            available = min(requested_frames, self.available_frames)

            if available < requested_frames:
                self.underflows += 1

            if available > 0:
                first_chunk = min(available, self.capacity - self.read_pos)
                out[:first_chunk] = self.buffer[self.read_pos:self.read_pos + first_chunk]

                second_chunk = available - first_chunk
                if second_chunk > 0:
                    out[first_chunk:first_chunk + second_chunk] = self.buffer[0:second_chunk]

                self.read_pos = (self.read_pos + available) % self.capacity
                self.available_frames -= available

            return out

    def get_fill_percentage(self) -> float:
        with self.lock:
            return (self.available_frames / self.capacity) * 100.0

    def clear(self):
        with self.lock:
            self.read_pos = 0
            self.write_pos = 0
            self.available_frames = 0
            self.buffer.fill(0)


class SyntheticSignalGenerator:
    """
    Precision audiophile synthetic signal generator.
    Generates exact mathematically pure test signals with sub-millisecond phase tracking.
    Modes:
      - 'sine': Pure 440 Hz (or custom freq) sine wave (zero distortion)
      - 'stereo_sweep': Ping-pong stereo panning sine wave
      - 'click_metronome': Precise 1-second pulse tick (audible phase sync calibration)
      - 'pink_noise': Calibrated broadband noise
    """

    def __init__(self, audio_format: AudioFormat, mode: str = "sine", freq: float = 440.0):
        self.format = audio_format
        self.mode = mode
        self.freq = freq
        self.phase = 0.0
        self.total_samples_generated = 0

    def generate(self, frame_count: int) -> np.ndarray:
        t = (self.total_samples_generated + np.arange(frame_count)) / self.format.sample_rate
        out = np.zeros((frame_count, self.format.channels), dtype=np.float32)

        if self.mode == "sine":
            val = 0.7 * np.sin(2.0 * np.pi * self.freq * t)
            for c in range(self.format.channels):
                out[:, c] = val

        elif self.mode == "stereo_sweep":
            # Panning L to R over 2 second cycle
            pan = 0.5 * (1.0 + np.sin(2.0 * np.pi * 0.5 * t))
            val = 0.7 * np.sin(2.0 * np.pi * self.freq * t)
            if self.format.channels >= 2:
                out[:, 0] = val * (1.0 - pan)
                out[:, 1] = val * pan
            else:
                out[:, 0] = val

        elif self.mode == "click_metronome":
            # 1 Hz click track (10ms sharp pulse at every integer second)
            mod_t = t % 1.0
            click_mask = mod_t < 0.010  # 10 ms burst
            pulse_val = 0.8 * np.sin(2.0 * np.pi * 1000.0 * t) * click_mask
            for c in range(self.format.channels):
                out[:, c] = pulse_val

        elif self.mode == "pink_noise":
            # Simplified high quality noise
            noise = np.random.uniform(-0.3, 0.3, size=frame_count)
            for c in range(self.format.channels):
                out[:, c] = noise

        self.total_samples_generated += frame_count
        self.phase = (self.phase + 2.0 * np.pi * self.freq * frame_count / self.format.sample_rate) % (2.0 * np.pi)

        # Convert float32 [-1, 1] to target dtype
        if self.format.format_code == AudioFormatCode.INT16:
            return (np.clip(out, -1.0, 1.0) * 32767.0).astype(np.int16)
        elif self.format.format_code == AudioFormatCode.INT32 or self.format.format_code == AudioFormatCode.INT24:
            return (np.clip(out, -1.0, 1.0) * 2147483647.0).astype(np.int32)
        return out.astype(np.float32)


class AudioCapture:
    """
    Lossless Audio Capture Engine.
    Supports Windows WASAPI loopback, standard line/mic input, synthetic generator, or audio files.
    """

    def __init__(
        self,
        audio_format: AudioFormat,
        source: str = "loopback",
        device_index: Optional[int] = None,
        file_path: Optional[str] = None,
        callback: Optional[Callable[[np.ndarray, float], None]] = None,
    ):
        self.format = audio_format
        self.source = source
        self.device_index = device_index
        self.file_path = file_path
        self.callback = callback
        self.running = False
        self.stream = None
        self.generator = None
        self.thread = None
        self.ring_buffer = RingBuffer(
            capacity_frames=audio_format.sample_rate * 2,
            channels=audio_format.channels,
            dtype=audio_format.numpy_dtype
        )

        if self.source in ["sine", "stereo_sweep", "click_metronome", "pink_noise", "synthetic"]:
            gen_mode = "sine" if self.source == "synthetic" else self.source
            self.generator = SyntheticSignalGenerator(audio_format, mode=gen_mode)

    def _find_wasapi_loopback_device(self) -> Optional[int]:
        """Finds default WASAPI output device index for loopback capture on Windows."""
        if not HAS_SOUNDDEVICE:
            return None
        try:
            devices = sd.query_devices()
            wasapi_hostapi_idx = None
            for idx, hostapi in enumerate(sd.query_hostapis()):
                if "WASAPI" in hostapi["name"]:
                    wasapi_hostapi_idx = idx
                    break

            if wasapi_hostapi_idx is not None:
                default_out = sd.default.device[1]
                if default_out is not None and default_out >= 0:
                    dev_info = devices[default_out]
                    if dev_info.get("hostapi") == wasapi_hostapi_idx:
                        return default_out
                # Fallback to first WASAPI output device
                for idx, dev in enumerate(devices):
                    if dev.get("hostapi") == wasapi_hostapi_idx and dev.get("max_output_channels", 0) > 0:
                        return idx
        except Exception:
            pass
        return None

    def start(self):
        """Starts audio capture."""
        if self.running:
            return
        self.running = True

        if self.generator is not None:
            self._start_synthetic_thread()
            return

        if not HAS_SOUNDDEVICE:
            print("[AudioCapture] sounddevice not installed; falling back to synthetic sine generator.")
            self.generator = SyntheticSignalGenerator(self.format, mode="sine")
            self._start_synthetic_thread()
            return

        try:
            device = self.device_index
            extra_settings = None

            if self.source == "loopback":
                # Check for Windows WASAPI loopback
                import platform
                if platform.system() == "Windows":
                    loopback_dev = device if device is not None else self._find_wasapi_loopback_device()
                    if loopback_dev is not None:
                        device = loopback_dev
                        extra_settings = sd.WasapiSettings(loopback=True)
                        print(f"[AudioCapture] Using WASAPI Loopback capture on device {device}")

            def audio_cb(indata, frames, time_info, status):
                if status:
                    pass
                pts = time.time()
                samples = indata.copy()
                self.ring_buffer.write(samples)
                if self.callback:
                    self.callback(samples, pts)

            self.stream = sd.InputStream(
                device=device,
                channels=self.format.channels,
                samplerate=self.format.sample_rate,
                blocksize=self.format.block_size,
                dtype=self.format.numpy_dtype,
                extra_settings=extra_settings,
                callback=audio_cb,
                latency='low'
            )
            self.stream.start()
            print(f"[AudioCapture] Live capture started: {self.format.sample_rate}Hz, {self.format.channels}ch, {self.format.format_code.name}")

        except Exception as e:
            print(f"[AudioCapture] Failed to open audio device ({e}). Falling back to synthetic signal generator.")
            self.generator = SyntheticSignalGenerator(self.format, mode="sine")
            self._start_synthetic_thread()

    def _start_synthetic_thread(self):
        def worker():
            frame_duration = self.format.block_size / self.format.sample_rate
            next_time = time.time()
            while self.running:
                pts = time.time()
                samples = self.generator.generate(self.format.block_size)
                self.ring_buffer.write(samples)
                if self.callback:
                    self.callback(samples, pts)

                next_time += frame_duration
                sleep_duration = next_time - time.time()
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
                else:
                    next_time = time.time()

        self.thread = threading.Thread(target=worker, daemon=True, name="AudioCaptureSynthetic")
        self.thread.start()
        print(f"[AudioCapture] Synthetic generator started: {self.generator.mode} at {self.format.sample_rate}Hz")

    def read(self, frame_count: int) -> np.ndarray:
        return self.ring_buffer.read(frame_count)

    def stop(self):
        self.running = False
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None
        print("[AudioCapture] Stopped.")


class AudioPlayer:
    """
    High-Fidelity Audio Output Engine.
    Feeds synchronized audio samples to DAC / sound card using low-latency callback.
    """

    def __init__(
        self,
        audio_format: AudioFormat,
        device_index: Optional[int] = None,
        pull_callback: Optional[Callable[[int], np.ndarray]] = None,
    ):
        self.format = audio_format
        self.device_index = device_index
        self.pull_callback = pull_callback
        self.running = False
        self.stream = None
        self.ring_buffer = RingBuffer(
            capacity_frames=audio_format.sample_rate * 2,
            channels=audio_format.channels,
            dtype=audio_format.numpy_dtype
        )

    def write(self, samples: np.ndarray) -> int:
        """Enqueues samples into playback ring buffer."""
        return self.ring_buffer.write(samples)

    def start(self):
        if self.running:
            return
        self.running = True

        if not HAS_SOUNDDEVICE:
            print("[AudioPlayer] sounddevice not installed; running in mock output mode.")
            return

        try:
            def audio_cb(outdata, frames, time_info, status):
                if status:
                    pass
                if self.pull_callback:
                    samples = self.pull_callback(frames)
                else:
                    samples = self.ring_buffer.read(frames)

                if len(samples) < frames:
                    outdata[:len(samples)] = samples
                    outdata[len(samples):].fill(0)
                else:
                    outdata[:] = samples[:frames]

            self.stream = sd.OutputStream(
                device=self.device_index,
                channels=self.format.channels,
                samplerate=self.format.sample_rate,
                blocksize=self.format.block_size,
                dtype=self.format.numpy_dtype,
                callback=audio_cb,
                latency='low'
            )
            self.stream.start()
            print(f"[AudioPlayer] Output stream started: {self.format.sample_rate}Hz, {self.format.channels}ch, {self.format.format_code.name}")
        except Exception as e:
            print(f"[AudioPlayer] Failed to open output device ({e}). Running in headless mode.")

    def stop(self):
        self.running = False
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        print("[AudioPlayer] Stopped.")


def calculate_rms_and_peak(samples: np.ndarray) -> Tuple[float, float]:
    """Calculates RMS (dBFS) and peak amplitude of audio samples for volume meters."""
    if len(samples) == 0:
        return -100.0, 0.0
    if np.issubdtype(samples.dtype, np.integer):
        max_int = np.iinfo(samples.dtype).max
        norm = samples.astype(np.float32) / float(max_int)
    else:
        norm = samples.astype(np.float32)

    peak = float(np.max(np.abs(norm)))
    rms = float(np.sqrt(np.mean(norm ** 2)))
    dbfs = 20.0 * math.log10(rms) if rms > 1e-7 else -100.0
    return dbfs, peak
