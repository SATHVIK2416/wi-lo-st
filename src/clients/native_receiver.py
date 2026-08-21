"""Native high-precision SonicSync Python receiver with PortAudio hardware DAC output.

Synchronization chain:
    UDP in -> seq loss tracking -> NTP-filtered clock offset -> adaptive jitter
    buffer -> playout scheduler thread -> PLL-driven continuous Hermite
    micro-resampler -> DAC playout ring -> PortAudio callback.

The NTP exchange runs over the host's WebSocket control channel in a
background thread; the filtered offset (theta) converts host PTS into
client-local playout deadlines, which is what makes cross-machine sync work.
"""

import asyncio
import json
import logging
import threading
import time
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

_SEQ_MASK = 0xFFFFFFFF
_SEQ_GAP_WINDOW = 1024


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


class ContinuousResampler:
    """Hermite micro-resampler carrying sub-sample phase across chunk boundaries.

    Stateless per-chunk resampling restarts the interpolation phase at zero for
    every chunk, producing boundary discontinuities of up to half a sample.
    This variant keeps the last four input frames as interpolation history so
    the fractional read position evolves continuously across chunks.
    """

    def __init__(self, channels: int = 2):
        self.channels = int(channels)
        self._tail = np.zeros((4, self.channels), dtype=np.float32)
        self._phase = 2.0

    def reset(self):
        self._tail = np.zeros((4, self.channels), dtype=np.float32)
        self._phase = 2.0

    def process(self, samples: np.ndarray, ratio: float) -> np.ndarray:
        n = len(samples)
        if n == 0:
            return samples

        if abs(ratio - 1.0) < 1e-7:
            self._tail = samples[-4:].copy()
            self._phase = 2.0
            return samples

        data = np.concatenate([self._tail, samples], axis=0)
        limit = len(data) - 2

        if limit <= self._phase:
            self._tail = data[-4:].copy()
            return np.zeros((0, self.channels), dtype=np.float32)

        positions = np.arange(self._phase, limit, ratio, dtype=np.float64)
        i = np.floor(positions).astype(np.int32)
        frac = (positions - i)[:, np.newaxis]

        i0 = np.clip(i - 1, 0, len(data) - 1)
        i1 = np.clip(i, 0, len(data) - 1)
        i2 = np.clip(i + 1, 0, len(data) - 1)
        i3 = np.clip(i + 2, 0, len(data) - 1)

        c0 = data[i1]
        c1 = 0.5 * (data[i2] - data[i0])
        c2 = data[i0] - 2.5 * data[i1] + 2.0 * data[i2] - 0.5 * data[i3]
        c3 = 0.5 * (data[i3] - data[i0]) + 1.5 * (data[i1] - data[i2])

        resampled = ((c3 * frac + c2) * frac + c1) * frac + c0

        end_pos = float(positions[-1] + ratio)
        self._tail = data[-4:].copy()
        self._phase = end_pos - (len(data) - 4)

        return resampled.astype(np.float32)


class NativeReceiverClient:
    """Reference high-precision native SonicSync receiver with custom PLL."""

    DEVICE_BUFFER_TARGET_SEC = 0.040  # DAC ring watermark; the 100 ms sync anchor
                                      # lives in the jitter buffer ahead of it

    def __init__(
        self,
        multicast_group: str = "239.255.0.1",
        port: int = 5004,
        target_delay_ms: float = 100.0,
        sample_rate: int = 48000,
        channels: int = 2,
        host_ws_port: int = 8080,
        ntp_enabled: bool = True
    ):
        self.multicast_group = multicast_group
        self.port = port
        self.host_ws_port = int(host_ws_port)
        self.ntp_enabled = ntp_enabled
        self.audio_format = AudioFormat(sample_rate=sample_rate, channels=channels, sample_format=SampleFormat.FLOAT32)

        self.clock_filter = ClockSyncFilter()
        self.drift_estimator = DriftEstimator()
        self.jitter_buffer = AdaptiveJitterBuffer(target_delay_sec=target_delay_ms / 1000.0, sample_rate=sample_rate)
        self.pll = PLLController(target_delay_sec=self.DEVICE_BUFFER_TARGET_SEC)
        self.playout_ring = RingBuffer(capacity_frames=sample_rate * 2, channels=channels)
        self.resampler = ContinuousResampler(channels=channels)

        self.udp_receiver = SonicSyncUDPReceiver(multicast_group=multicast_group, port=port)
        self._audio_stream = None
        self._is_running = False

        self._packets_received = 0
        self._packets_lost = 0
        self._last_seq: Optional[int] = None
        self._clock_offset = 0.0
        self._offset_locked = False

        self._playout_thread: Optional[threading.Thread] = None
        self._control_thread: Optional[threading.Thread] = None

    def start(self):
        """Start UDP reception, playout scheduling, NTP sync, and DAC output."""
        if self._is_running:
            return
        self._is_running = True

        self.udp_receiver.start(self._on_packet_received)

        self._playout_thread = threading.Thread(target=self._playout_loop, daemon=True, name="sonicsync-playout")
        self._playout_thread.start()

        if self.ntp_enabled:
            self._control_thread = threading.Thread(target=self._control_thread_main, daemon=True, name="sonicsync-ntp")
            self._control_thread.start()

        try:
            import sounddevice as sd

            def dac_callback(outdata, frames, time_info, status):
                if status:
                    logger.debug(f"DAC callback status: {status}")
                outdata[:] = self.playout_ring.read(frames, fill_silence=True)

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
        """UDP thread: track loss, schedule packet with the filtered clock offset."""
        self._packets_received += 1

        if self._last_seq is not None:
            gap = (packet.sequence_number - self._last_seq) & _SEQ_MASK
            if 0 < gap < _SEQ_GAP_WINDOW:
                self._packets_lost += gap - 1
        self._last_seq = packet.sequence_number

        self.jitter_buffer.push(packet, clock_offset=self._clock_offset)

    def _playout_loop(self):
        """Pop due packets on schedule (independent of arrival timing) and render them."""
        while self._is_running:
            try:
                ready = self.jitter_buffer.pop_ready(MasterClock.now())
                for pkt in ready:
                    self._render_packet(pkt)
            except Exception as ex:
                logger.error(f"Playout loop error: {ex}", exc_info=True)
            time.sleep(0.004)

    def _render_packet(self, pkt: AudioPacket):
        raw_float = pcm_to_numpy_float32(pkt.payload, pkt.sample_format, pkt.channels)
        if raw_float.ndim == 1:
            raw_float = raw_float.reshape(-1, pkt.channels)

        buffered_sec = self.playout_ring.buffered_duration_ms(self.audio_format.sample_rate) / 1000.0
        ratio = self.pll.update(buffered_sec, dt=None)

        resampled = self.resampler.process(raw_float, ratio)
        if len(resampled):
            self.playout_ring.write(resampled)

    def _control_thread_main(self):
        """Background NTP + telemetry session against the host WebSocket."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ntp_session())
        except Exception as ex:
            logger.debug(f"NTP control session ended: {ex}")
        finally:
            loop.close()

    async def _ntp_session(self):
        try:
            import websockets
        except ImportError:
            logger.warning("websockets package unavailable; receiver runs without clock sync.")
            return

        host_ip = await self._wait_for_host_ip(timeout=10.0)
        if host_ip is None:
            logger.warning("No host discovered on the stream; clock sync disabled.")
            return

        uri = f"ws://{host_ip}:{self.host_ws_port}/ws"
        logger.info(f"Connecting NTP control channel to {uri}")

        async for ws in self._connect_with_retry(websockets, uri):
            try:
                await self._ntp_exchange_loop(ws)
            except Exception as ex:
                logger.warning(f"NTP session error, reconnecting: {ex}")
            if not self._is_running:
                break

    async def _connect_with_retry(self, websockets, uri):
        backoff = 1.0
        while self._is_running:
            try:
                connect = websockets.connect(uri, open_timeout=5.0)
                async for ws in connect:
                    backoff = 1.0
                    yield ws
            except Exception as ex:
                logger.debug(f"Control channel connect failed: {ex}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 10.0)

    async def _wait_for_host_ip(self, timeout: float) -> Optional[str]:
        deadline = time.monotonic() + timeout
        while self._is_running and time.monotonic() < deadline:
            sender = self.udp_receiver.last_sender
            if sender:
                return sender[0]
            await asyncio.sleep(0.1)
        return None

    async def _ntp_exchange_loop(self, ws):
        last_report = 0.0
        async for _ in self._keepalive():
            if not self._is_running:
                return

            offset_ok = await self._ntp_exchange(ws)
            now = time.monotonic()
            if offset_ok and now - last_report >= 1.0:
                last_report = now
                await self._send_telemetry(ws)

    async def _keepalive(self):
        while self._is_running:
            yield None
            await asyncio.sleep(0.25)

    async def _ntp_exchange(self, ws) -> bool:
        t0 = MasterClock.now()
        await ws.send(json.dumps({"type": "ntp_request", "t0": t0}))

        deadline = asyncio.get_event_loop().time() + 2.0
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return False
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                return False

            if isinstance(raw, bytes):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            if msg_type == "ntp_response":
                t3 = MasterClock.now()
                try:
                    t1 = float(msg["t1"])
                    t2 = float(msg["t2"])
                    resp_t0 = float(msg.get("t0", t0))
                except (KeyError, TypeError, ValueError):
                    continue
                if abs(resp_t0 - t0) > 1e-6:
                    continue  # stale/mismatched reply
                offset, rtt, locked = self.clock_filter.add_measurement(t0, t1, t2, t3)
                drift = self.drift_estimator.add_sample(t3, offset)
                if locked:
                    self._clock_offset = offset
                    self._offset_locked = True
                else:
                    self._offset_locked = False
                logger.debug(
                    f"NTP offset={offset * 1000:.2f}ms rtt={rtt * 1000:.2f}ms "
                    f"drift={drift:.2f}ppm locked={locked}"
                )
                return True
            elif msg_type == "error":
                logger.warning(f"Host reported error: {msg.get('message')}")
            # stream_config and other messages are consumed and ignored here

    async def _send_telemetry(self, ws):
        report = {
            "type": "client_report",
            "client_type": "native",
            "buffer_ms": self.jitter_buffer.get_buffer_depth_ms(),
            "offset_ms": self._clock_offset * 1000.0,
            "rtt_ms": self.clock_filter.filtered_rtt * 1000.0,
            "drift_ppm": self.drift_estimator.drift_ppm,
            "is_locked": self._offset_locked,
            "underruns": self.playout_ring.underruns,
            "overruns": self.playout_ring.overruns,
            "packet_loss": self._packet_loss_rate(),
            "resample_ratio": self.pll.current_ratio
        }
        try:
            await ws.send(json.dumps(report))
        except Exception as ex:
            logger.debug(f"Telemetry send failed: {ex}")

    def _packet_loss_rate(self) -> float:
        total = self._packets_received + self._packets_lost
        if total <= 0:
            return 0.0
        return self._packets_lost / float(total)

    def get_status(self) -> dict:
        return {
            "running": self._is_running,
            "packets_received": self._packets_received,
            "packets_lost": self._packets_lost,
            "packet_loss_rate": self._packet_loss_rate(),
            "crc_errors": self.udp_receiver.crc_errors,
            "duplicates_dropped": self.udp_receiver.duplicates_dropped,
            "clock_offset_ms": self._clock_offset * 1000.0,
            "ntp_locked": self._offset_locked,
            "ntp_confidence": self.clock_filter.confidence,
            "rtt_ms": self.clock_filter.filtered_rtt * 1000.0,
            "drift_ppm": self.drift_estimator.drift_ppm,
            "jitter_depth_ms": self.jitter_buffer.get_buffer_depth_ms(),
            "watermark": self.jitter_buffer.get_watermark_state(),
            "jitter_drops": self.jitter_buffer.dropped_late_count,
            "resets": self.jitter_buffer.resets_count,
            "ring_underruns": self.playout_ring.underruns,
            "resample_ratio": self.pll.current_ratio
        }

    def stop(self):
        self._is_running = False
        self.udp_receiver.stop()
        for thread in (self._playout_thread, self._control_thread):
            if thread is not None:
                thread.join(timeout=1.0)
        self._playout_thread = None
        self._control_thread = None
        if self._audio_stream is not None:
            try:
                self._audio_stream.stop()
                self._audio_stream.close()
            except Exception:
                pass
            self._audio_stream = None
