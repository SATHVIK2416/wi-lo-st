"""SonicSync HTTP & WebSocket Application Server."""

import asyncio
import logging
import os
import platform
import time
from typing import Optional
from aiohttp import web
import numpy as np

from src.core.audio_format import AudioFormat, SampleFormat, numpy_float32_to_pcm
from src.core.clock import MasterClock
from src.core.limiter import SoftKneeLimiter
from src.core.packet import AudioPacket
from src.core.ring_buffer import RingBuffer
from src.capture.base_source import AudioSource
from src.capture.test_generator import TestGeneratorSource
from src.capture.wasapi_loopback import WASAPILoopbackSource
from src.vlc.vlc_source import VLCSource
from src.sync.sync_coordinator import MasterSyncCoordinator
from src.transport.rtp_adapter import RTPAdapter
from src.transport.rtcp_adapter import RTCPAdapter
from src.transport.sonicsync_udp import SonicSyncUDPBroadcaster, DEFAULT_MULTICAST_GROUP
from src.transport.websocket_stream import WebSocketStreamManager
from src.server.api import create_api_routes
from src.server.auth import SessionManager
from src.server.qr import get_local_lan_ip

logger = logging.getLogger(__name__)

SONIC_UDP_PORT = 5004   # Native SonicSync binary protocol
RTP_PORT = 5006         # RTP audio for VLC listeners (must differ from SONI port)
RTCP_PORT = 5007        # RTCP sender reports (RTP + 1)


class SourceManager:
    """Manages audio source selection and routing into the central RingBuffer."""

    def __init__(
        self,
        ring_buffer: RingBuffer,
        audio_format: AudioFormat,
        vlc_source: VLCSource,
        wasapi_source: AudioSource,
        test_source: TestGeneratorSource
    ):
        self.ring_buffer = ring_buffer
        self.audio_format = audio_format
        self.vlc_source = vlc_source
        self.wasapi_source = wasapi_source
        self.test_source = test_source

        self._current_type = "test"  # Default start with test/vlc
        self._active_source: AudioSource = self.test_source

        # Register audio ingestion callback to push into central RingBuffer
        self.vlc_source.set_callback(self._on_audio_data)
        self.wasapi_source.set_callback(self._on_audio_data)
        self.test_source.set_callback(self._on_audio_data)

    @property
    def source_type(self) -> str:
        return self._current_type

    @property
    def current_source(self) -> AudioSource:
        return self._active_source

    def switch_source(self, source_type: str):
        """Switch active audio input source."""
        requested = source_type.lower()
        source_type = requested
        if source_type == self._current_type:
            return

        logger.info(f"Switching audio source to: {source_type}")
        self._active_source.stop()

        if source_type == "vlc":
            self._active_source = self.vlc_source
        elif source_type in ("loopback", "wasapi", "system"):
            self._active_source = self.wasapi_source
        elif source_type in ("test", "generator"):
            self._active_source = self.test_source
        else:
            logger.warning(f"Unknown source type {requested!r}, defaulting to test generator")
            source_type = "test"
            self._active_source = self.test_source

        self._current_type = source_type
        self._active_source.start()

    def start(self):
        self._active_source.start()

    def stop(self):
        self.vlc_source.stop()
        self.wasapi_source.stop()
        self.test_source.stop()

    def _on_audio_data(self, data: np.ndarray):
        """Write incoming audio frames to central RingBuffer."""
        self.ring_buffer.write(data)


class SonicSyncServer:
    """Integrated SonicSync Host Server."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        sample_rate: int = 48000,
        channels: int = 2,
        target_delay_ms: float = 100.0,
        default_source: str = "test",
        web_root: Optional[str] = None,
        pin: Optional[str] = None
    ):
        self.host = host
        self.port = int(port)
        self.lan_ip = get_local_lan_ip()
        self.web_root = web_root or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "web"))

        self.audio_format = AudioFormat(
            sample_rate=sample_rate,
            channels=channels,
            sample_format=SampleFormat.FLOAT32
        )

        # Core subsystems
        self.clock = MasterClock()
        self.ring_buffer = RingBuffer(capacity_frames=sample_rate * 4, channels=channels)
        self.limiter = SoftKneeLimiter(sample_rate=sample_rate, channels=channels, enabled=True)
        self.sync_coordinator = MasterSyncCoordinator(base_target_delay_ms=target_delay_ms)
        self.session_manager = SessionManager()
        if pin:
            self.session_manager.configure_pin(str(pin))
            logger.info("PIN protection enabled: control APIs and WebSocket require a session token.")
        # Bootstrap token embedded in the QR code when PIN mode is active
        self.bootstrap_token = self.session_manager.generate_token() if self.session_manager.pin_enabled else ""

        # Capture sources
        self.vlc_source = VLCSource(self.audio_format)
        if platform.system() == "Windows":
            self.loopback_source = WASAPILoopbackSource(self.audio_format)
        else:
            from src.capture.pulse_monitor import PulseAudioMonitorSource
            self.loopback_source = PulseAudioMonitorSource(self.audio_format)
        self.test_source = TestGeneratorSource(self.audio_format)

        self.source_manager = SourceManager(
            ring_buffer=self.ring_buffer,
            audio_format=self.audio_format,
            vlc_source=self.vlc_source,
            wasapi_source=self.loopback_source,
            test_source=self.test_source
        )

        # Transport adapters
        self.udp_broadcaster = SonicSyncUDPBroadcaster(port=SONIC_UDP_PORT, interface_ip=self.lan_ip)
        self.rtp_adapter = RTPAdapter(self.audio_format)
        self.rtcp_adapter = RTCPAdapter(self.rtp_adapter.ssrc)
        self.ws_manager = WebSocketStreamManager(
            self.sync_coordinator,
            stream_info={
                "sample_rate": self.audio_format.sample_rate,
                "channels": self.audio_format.channels,
                "format": self.audio_format.sample_format.name
            },
            auth_check=self._ws_authorized
        )

        # Background broadcast loop
        self._is_running = False
        self._broadcast_task: Optional[asyncio.Task] = None
        self._rtcp_task: Optional[asyncio.Task] = None
        self._runner: Optional[web.AppRunner] = None
        self._seq_num = 0
        self._default_source = default_source

    def _ws_authorized(self, request) -> bool:
        """Auth hook for the WebSocket endpoint: token required when PIN is set."""
        return self.session_manager.validate_token(self.session_manager.extract_token(request))

    async def _audio_broadcast_loop(self):
        """High-frequency real-time audio broadcast loop (~10ms cadence)."""
        sr = self.audio_format.sample_rate
        chunk_frames = self.audio_format.duration_to_frames(0.010)  # 10 ms (480 frames @ 48kHz)
        dt = 0.010

        logger.info(f"Audio broadcast loop started (chunk={chunk_frames} frames, {dt*1000:.1f}ms).")

        while self._is_running:
            loop_start = time.perf_counter()

            # Read 10ms block from ring buffer (padded with silence if starved)
            audio_block = self.ring_buffer.read(chunk_frames, fill_silence=True)

            # Apply limiter
            limited_audio = self.limiter.process(audio_block)

            # Generate host presentation timestamp
            pts = self.clock.now()

            # 1. Native SonicSync binary packet (Float32 payload)
            float_payload = numpy_float32_to_pcm(limited_audio, SampleFormat.FLOAT32)
            packet = AudioPacket(
                sequence_number=self._seq_num,
                pts=pts,
                target_playout_delay=self.sync_coordinator.target_playout_delay_sec,
                frame_count=chunk_frames,
                payload=float_payload,
                sample_rate=sr,
                channels=self.audio_format.channels,
                sample_format=SampleFormat.FLOAT32
            )
            raw_packet_bytes = packet.serialize()

            # Broadcast UDP binary packet
            self.udp_broadcaster.send_packet(packet)

            # Broadcast WebSocket binary packet to connected browsers
            if self.ws_manager.client_count > 0:
                await self.ws_manager.broadcast_binary(raw_packet_bytes)

            # 2. RTP packet for VLC (separate port so VLC never sees SONI packets)
            rtp_pkt = self.rtp_adapter.packetize(limited_audio, SampleFormat.INT16)
            rtp_bytes = rtp_pkt.serialize()
            self.udp_broadcaster.send_raw(rtp_bytes, target_ip=DEFAULT_MULTICAST_GROUP, target_port=RTP_PORT)
            self.rtcp_adapter.record_packet(len(rtp_bytes))

            self._seq_num = (self._seq_num + 1) & 0xFFFFFFFF

            # Precise timing wait
            elapsed = time.perf_counter() - loop_start
            to_sleep = max(0.0005, dt - elapsed)
            await asyncio.sleep(to_sleep)

    async def _rtcp_report_loop(self):
        """Sends RTCP Sender Reports every 200 ms for VLC clock alignment."""
        while self._is_running:
            await asyncio.sleep(0.200)
            try:
                sr = self.rtcp_adapter.create_sender_report(self.rtp_adapter.current_rtp_timestamp)
                sr_bytes = sr.serialize()
                self.udp_broadcaster.send_raw(sr_bytes, target_ip=DEFAULT_MULTICAST_GROUP, target_port=RTCP_PORT)
            except Exception as e:
                logger.debug(f"RTCP sender report note: {e}")

    async def start(self) -> web.AppRunner:
        """Start web application, background workers, and audio source."""
        self._is_running = True

        app = web.Application()

        # Shared application state
        app_state = {
            "source_manager": self.source_manager,
            "vlc_source": self.vlc_source,
            "test_generator": self.test_source,
            "sync_coordinator": self.sync_coordinator,
            "ws_manager": self.ws_manager,
            "audio_format": self.audio_format,
            "limiter": self.limiter,
            "lan_ip": self.lan_ip,
            "port": self.port,
            "session_manager": self.session_manager,
            "bootstrap_token": self.bootstrap_token
        }

        # Setup API routes
        routes = create_api_routes(app_state)
        app.add_routes(routes)

        # Setup WebSocket handler
        app.router.add_get("/ws", self.ws_manager.handle_ws)

        # Serve static web dashboard and listener
        async def serve_dashboard(request):
            dash_path = os.path.join(self.web_root, "dashboard.html")
            if os.path.exists(dash_path):
                return web.FileResponse(dash_path)
            return web.Response(text="<h1>SonicSync Host Dashboard</h1><p>dashboard.html not found</p>", content_type="text/html")

        async def serve_listener(request):
            listen_path = os.path.join(self.web_root, "listen.html")
            if os.path.exists(listen_path):
                return web.FileResponse(listen_path)
            return web.Response(text="<h1>SonicSync Mobile Listener</h1><p>listen.html not found</p>", content_type="text/html")

        app.router.add_get("/", serve_dashboard)
        app.router.add_get("/listen", serve_listener)

        # Serve other assets from web folder
        if os.path.exists(self.web_root):
            app.router.add_static("/static/", path=self.web_root, name="static")

        # Start initial audio source
        self.source_manager.switch_source(self._default_source)

        # Launch background audio broadcast tasks
        self._broadcast_task = asyncio.create_task(self._audio_broadcast_loop())
        self._rtcp_task = asyncio.create_task(self._rtcp_report_loop())

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        self._runner = runner

        logger.info(f"SonicSync Host running at http://localhost:{self.port} and http://{self.lan_ip}:{self.port}")
        return runner

    async def stop(self):
        if not self._is_running and self._runner is None:
            return
        self._is_running = False

        for task in (self._broadcast_task, self._rtcp_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._broadcast_task = None
        self._rtcp_task = None

        self.source_manager.stop()
        self.udp_broadcaster.close()

        if self._runner is not None:
            try:
                await self._runner.cleanup()
            except Exception as e:
                logger.debug(f"Runner cleanup note: {e}")
            self._runner = None
