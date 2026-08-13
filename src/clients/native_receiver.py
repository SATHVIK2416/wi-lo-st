"""Native high-precision SonicSync Python receiver with PortAudio hardware DAC output."""

import logging
import math
import socket
import time
import threading
from typing import Optional
import numpy as np

from src.core.audio_format import AudioFormat, SampleFormat, pcm_to_numpy_float32
from src.core.clock import MasterClock
from src.core.packet import AudioPacket
from src.core.ring_buffer import RingBuffer
from src.sync.clock_filter import ClockSyncFilter
from src.sync.drift_estimator import DriftEstimator
from src.sync.jitter_buffer import AdaptiveJitterBuffer
from src.sync.pll_controller import PLLController
from src.transport.sonicsync_udp import SonicSyncUDPReceiver

logger = logging.getLogger(__name__)


def hermite_resample_chunk(samples: np.ndarray, ratio: float) -> np.ndarray:
    """4-point Hermite cubic polynomial micro-resampler for continuous rate modulation."""
    if abs(ratio - 1.0) < 1e-7:
        return samples

    num_frames, ch = samples.shape
    if num_frames < 4:
        return samples

    out_frames = max(1, int(round(num_frames / ratio)))
    t_out = np.linspace(0, num_frames - 1, out_frames, endpoint=False, dtype=np.float32)

    # Integer indices and fractional offsets
    i = np.floor(t_out).astype(np.int32)
    frac = t_out - i

    i0 = np.clip(i - 1, 0, num_frames - 1)
    i1 = np.clip(i, 0, num_frames - 1)
    i2 = np.clip(i + 1, 0, num_frames - 1)
    i3 = np.clip(i + 2, 0, num_frames - 1)

    # 4-point Catmull-Rom / Hermite coefficients
    c0 = samples[i1]
    c1 = 0.5 * (samples[i2] - samples[i0])
    c2 = samples[i0] - 2.5 * samples[i1] + 2.0 * samples[i2] - 0.5 * samples[i3]
    c3 = 0.5 * (samples[i3] - samples[i0]) + 1.5 * (samples[i1] - samples[i2])

    f = frac[:, np.newaxis]
    resampled = ((c3 * f + c2) * f + c1) * f + c0
    return resampled.astype(np.float32)


class NativeReceiverClient:
    """Reference high-precision native SonicSync receiver with custom PLL."""

    def __init__(
        self,
        multicast_group: str = "239.255.0.1",
        port: int = 5004,
        target_delay_ms: float = 100.0,
        sample_rate: int = 48000,
        channels: int = 2
    ):
        self.multicast_group = multicast_group
        self.port = port
        self.audio_format = AudioFormat(sample_rate=sample_rate, channels=channels, sample_format=SampleFormat.FLOAT32)

        self.clock_filter = ClockSyncFilter()
        self.drift_estimator = DriftEstimator()
        self.jitter_buffer = AdaptiveJitterBuffer(target_delay_sec=target_delay_ms / 1000.0, sample_rate=sample_rate)
        self.pll = PLLController(target_delay_sec=target_delay_ms / 1000.0)
        self.playout_ring = RingBuffer(capacity_frames=sample_rate * 2, channels=channels)

        self.udp_receiver = SonicSyncUDPReceiver(multicast_group=multicast_group, port=port)
        self._audio_stream = None
        self._is_running = False
        self._packets_received = 0
        self._crc_errors = 0

    def start(self):
        """Start UDP reception and DAC output playback."""
        if self._is_running:
            return
        self._is_running = True

        # Start UDP listener
        self.udp_receiver.start(self._on_packet_received)

        # Start PortAudio output stream
        try:
            import sounddevice as sd

            def dac_callback(outdata, frames, time_info, status):
                if status:
                    logger.debug(f"DAC callback status: {status}")

                # Read from playout ring buffer
                audio_frames = self.playout_ring.read(frames, fill_silence=True)
                outdata[:] = audio_frames

            self._audio_stream = sd.OutputStream(
                samplerate=self.audio_format.sample_rate,
                channels=self.audio_format.channels,
                dtype='float32',
                callback=dac_callback,
                blocksize=self.audio_format.duration_to_frames(0.010)
            )
            self._audio_stream.start()
            logger.info("Native DAC playback output stream started.")
        except Exception as e:
            logger.warning(f"Could not open hardware DAC: {e}. Running in headless receiver mode.")

    def _on_packet_received(self, packet: AudioPacket):
        """Handle incoming binary audio packet."""
        self._packets_received += 1

        # Estimate clock offset: for local network, use PTS vs local clock
        t_local = MasterClock.now()
        offset = t_local - packet.pts  # Approximate or updated via NTP

        # Push to adaptive jitter buffer
        self.jitter_buffer.push(packet, clock_offset=0.0)

        # Pop packets ready for playout
        ready_packets = self.jitter_buffer.pop_ready(t_local)

        for pkt in ready_packets:
            raw_float = pcm_to_numpy_float32(pkt.payload, pkt.sample_format, pkt.channels)

            # Measure current buffer depth and update PLL
            buffered_sec = self.playout_ring.buffered_duration_ms(self.audio_format.sample_rate) / 1000.0
            ratio = self.pll.update(buffered_sec, dt=0.01)

            # Apply Hermite micro-resampling
            resampled = hermite_resample_chunk(raw_float, ratio)

            # Write into DAC playout ring
            self.playout_ring.write(resampled)

    def stop(self):
        self._is_running = False
        self.udp_receiver.stop()
        if self._audio_stream is not None:
            try:
                self._audio_stream.stop()
                self._audio_stream.close()
            except Exception:
                pass
            self._audio_stream = None
