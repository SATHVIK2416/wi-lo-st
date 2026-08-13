"""
SonicSync - Receiver Client Application
Auto-discovers host, locks clocks via precision NTP synchronization,
receives lossless audio over UDP, and plays through adaptive PLL jitter buffer.
"""

import argparse
import asyncio
import json
import logging
import os
import socket
import struct
import sys
import threading
import time
from typing import Optional

import numpy as np

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.audio import (
    AudioFormat,
    AudioFormatCode,
    AudioPacket,
    AudioPlayer,
    CompressionType,
    PacketType,
    calculate_rms_and_peak,
)
from src.sync import (
    AdaptiveJitterBuffer,
    ClockSyncFilter,
    NTPMessage,
    SyncStats,
)

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SonicSync.Receiver")


class SonicReceiver:
    def __init__(self, host_ip: Optional[str] = None, config_path: str = "config/settings.json", **cli_overrides):
        self.config = self._load_config(config_path)
        self.host_ip = host_ip or self.config["network"].get("host_ip")
        self.audio_port = cli_overrides.get("port") or self.config["network"].get("audio_port", 50005)
        self.control_port = cli_overrides.get("control_port") or self.config["network"].get("control_port", 50006)
        self.discovery_port = self.config["network"].get("discovery_port", 50007)
        self.output_device = cli_overrides.get("device", self.config["audio"].get("output_device"))
        self.buffer_margin_override = cli_overrides.get("buffer_margin")

        # Initial default format (updated upon handshake)
        self.audio_format = AudioFormat(
            sample_rate=self.config["audio"].get("sample_rate", 48000),
            channels=self.config["audio"].get("channels", 2),
            format_code=AudioFormatCode.INT16,
            block_size=self.config["audio"].get("block_size", 256)
        )

        self.sync_filter = ClockSyncFilter()
        self.jitter_buffer: Optional[AdaptiveJitterBuffer] = None
        self.audio_player: Optional[AudioPlayer] = None

        self.running = False
        self.connected_to_host = False
        self.client_id = 0
        self.total_bytes_received = 0
        self.total_packets_received = 0
        self.current_dbfs = -100.0
        self.current_peak = 0.0
        self.lock = threading.Lock()

        # UDP Audio Socket
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Increase OS receive buffer to prevent packet drops under load
        try:
            self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024)
        except Exception:
            pass

    def _load_config(self, path: str) -> dict:
        default_config = {
            "audio": {"sample_rate": 48000, "channels": 2, "format": "int16", "block_size": 256},
            "network": {"audio_port": 50005, "control_port": 50006, "discovery_port": 50007},
            "sync": {"safety_margin_ms": 15.0}
        }
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    for k in default_config:
                        if k in data:
                            default_config[k].update(data[k])
                return default_config
            except Exception as e:
                logger.warning(f"Error loading config {path}: {e}")
        return default_config

    async def _discover_host(self) -> str:
        """Listens for Host UDP discovery beacons."""
        print(f"[*] Scanning local network for SonicSync Host on UDP port {self.discovery_port}...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except Exception:
                pass
        sock.bind(("", self.discovery_port))
        sock.setblocking(False)

        loop = asyncio.get_event_loop()
        while self.running:
            try:
                data, addr = await loop.sock_recvfrom(sock, 4096)
                info = json.loads(data.decode("utf-8"))
                if info.get("service") == "sonicsync":
                    discovered_ip = addr[0]
                    self.audio_port = info.get("audio_port", self.audio_port)
                    self.control_port = info.get("control_port", self.control_port)
                    print(f"[+] Found SonicSync Host at {discovered_ip}:{self.control_port}")
                    sock.close()
                    return discovered_ip
            except Exception:
                await asyncio.sleep(0.2)
        sock.close()
        return "127.0.0.1"

    def _setup_audio_pipeline(self):
        """Initializes jitter buffer and audio output player."""
        override_delay = (self.buffer_margin_override / 1000.0) if self.buffer_margin_override else None
        self.jitter_buffer = AdaptiveJitterBuffer(
            audio_format=self.audio_format,
            sync_filter=self.sync_filter,
            target_delay_override=override_delay
        )

        def pull_audio_cb(frames: int) -> np.ndarray:
            if not self.jitter_buffer:
                return np.zeros((frames, self.audio_format.channels), dtype=self.audio_format.numpy_dtype)
            samples = self.jitter_buffer.pull_samples(frames)
            dbfs, peak = calculate_rms_and_peak(samples)
            self.current_dbfs = dbfs
            self.current_peak = peak
            return samples

        self.audio_player = AudioPlayer(
            audio_format=self.audio_format,
            device_index=self.output_device,
            pull_callback=pull_audio_cb
        )
        self.audio_player.start()

    async def _udp_receive_loop(self):
        """Asynchronous UDP audio reception loop."""
        try:
            self.udp_sock.bind(("", self.audio_port))
        except Exception as e:
            print(f"[!] Failed to bind UDP audio port {self.audio_port}: {e}")
            return

        self.udp_sock.setblocking(False)
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                data, _ = await loop.sock_recvfrom(self.udp_sock, 65535)
                packet = AudioPacket.unpack(data)
                if packet and packet.packet_type in [PacketType.AUDIO_RAW_PCM, PacketType.AUDIO_FLAC]:
                    self.total_bytes_received += len(data)
                    self.total_packets_received += 1
                    if self.jitter_buffer:
                        self.jitter_buffer.push_packet(packet)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"UDP Recv error: {e}")
                await asyncio.sleep(0.001)

    async def _control_and_sync_client(self, host_ip: str):
        """Connects to Host TCP control server, handles HELLO handshake and NTP Ping/Pong responses."""
        while self.running:
            try:
                print(f"[*] Connecting to Host control server at {host_ip}:{self.control_port}...")
                reader, writer = await asyncio.open_connection(host_ip, self.control_port)
                self.connected_to_host = True
                print(f"[+] Connected to SonicSync Host! Locking clock synchronization...")

                # Read HELLO
                hello_line = await reader.readline()
                hello_data = json.loads(hello_line.decode("utf-8"))
                if hello_data.get("type") == "HELLO":
                    self.client_id = hello_data.get("client_id", 0)
                    fmt_name = hello_data.get("format", "INT16")
                    fmt_code = getattr(AudioFormatCode, fmt_name, AudioFormatCode.INT16)
                    self.audio_format = AudioFormat(
                        sample_rate=hello_data.get("sample_rate", 48000),
                        channels=hello_data.get("channels", 2),
                        format_code=fmt_code,
                        block_size=hello_data.get("block_size", 256)
                    )
                    self._setup_audio_pipeline()

                # Start Telemetry Reporter Task
                async def telemetry_loop():
                    while self.running and not writer.is_closing():
                        await asyncio.sleep(1.0)
                        if self.jitter_buffer:
                            metrics = self.jitter_buffer.get_metrics()
                            stats = self.sync_filter.get_stats()
                            payload = json.dumps({
                                "type": "TELEMETRY",
                                "rtt_ms": stats.rtt_ms,
                                "offset_ms": stats.offset_ms,
                                "jitter_ms": stats.jitter_ms,
                                "phase_error_ms": metrics["phase_error_ms"],
                                "buffer_level_ms": metrics["buffer_level_ms"],
                                "drift_adjustments": metrics["drift_adjustments"],
                                "dropped_late": metrics["dropped_late"]
                            }).encode("utf-8")
                            try:
                                writer.write(struct.pack("!H", len(payload)) + payload)
                                await writer.drain()
                            except Exception:
                                break

                telemetry_task = asyncio.create_task(telemetry_loop())

                # Read NTP Pings from Host and reply with Pongs
                while self.running:
                    header = await reader.readexactly(2)
                    pkt_len = struct.unpack("!H", header)[0]
                    body = await reader.readexactly(pkt_len)

                    if body.startswith(b"SONI"):
                        t1 = time.time()  # Receiver receive timestamp
                        ntp_msg = NTPMessage.unpack(body)
                        if ntp_msg and ntp_msg.msg_type == PacketType.SYNC_PING:
                            t2 = time.time()  # Receiver transmit timestamp
                            pong = NTPMessage(
                                msg_type=PacketType.SYNC_PONG,
                                client_id=self.client_id,
                                sequence=ntp_msg.sequence,
                                t0=ntp_msg.t0,
                                t1=t1,
                                t2=t2,
                                t3=0.0
                            )
                            # Local filter update as well
                            self.sync_filter.add_sample(ntp_msg.t0, t1, t2, time.time())
                            raw_pong = pong.pack()
                            writer.write(struct.pack("!H", len(raw_pong)) + raw_pong)
                            await writer.drain()

            except (ConnectionRefusedError, asyncio.IncompleteReadError, OSError) as e:
                self.connected_to_host = False
                logger.warning(f"Connection lost ({e}). Retrying in 2 seconds...")
                await asyncio.sleep(2.0)

    def _render_dashboard(self) -> Table:
        table = Table(title="🎧 SonicSync - Audiophile Receiver (Sample-Accurate Auto Sync)", expand=True)
        table.add_column("Diagnostic", style="cyan", no_wrap=True)
        table.add_column("Live Telemetry", style="green")

        stats = self.sync_filter.get_stats()
        metrics = self.jitter_buffer.get_metrics() if self.jitter_buffer else {}

        table.add_row("Host Connection", f"{self.host_ip}:{self.control_port} ({'🟢 CONNECTED' if self.connected_to_host else '🔴 SEARCHING'})")
        table.add_row("Audio Stream", f"{self.audio_format.sample_rate} Hz | {self.audio_format.format_code.name} | {self.audio_format.channels}ch (Lossless PCM)")
        
        sync_badge = "🟢 PHASE-LOCKED (<0.5ms)" if stats.is_synchronized else "🟡 LOCKING CLOCK..."
        table.add_row("Clock Sync State", f"{sync_badge} (Samples: {stats.samples_count})")
        table.add_row("Network RTT (Lag)", f"{stats.rtt_ms:.2f} ms [One-way: {stats.one_way_delay_ms:.2f} ms]")
        table.add_row("Clock Offset (θ)", f"{stats.offset_ms:+.3f} ms")
        table.add_row("Network Jitter (σ)", f"{stats.jitter_ms:.2f} ms")
        table.add_row("Jitter Buffer Level", f"{metrics.get('buffer_level_ms', 0.0):.1f} ms ({metrics.get('queued_packets', 0)} frames queued)")
        table.add_row("Phase Timing Error", f"{metrics.get('phase_error_ms', 0.0):+.2f} ms")
        table.add_row("PLL Drift Adjustments", f"{metrics.get('drift_adjustments', 0)} samples adjusted")
        table.add_row("Packets Received / Dropped", f"{self.total_packets_received:,} / Late: {metrics.get('dropped_late', 0)}")

        # Volume VU meter
        vu_bars = int(max(0, min(30, (self.current_dbfs + 60) * 0.5)))
        meter = "█" * vu_bars + "░" * (30 - vu_bars)
        table.add_row("DAC Output Level", f"{meter} [{self.current_dbfs:.1f} dBFS | Peak {self.current_peak:.2f}]")

        return table

    async def run(self, enable_dashboard: bool = True):
        self.running = True

        if not self.host_ip:
            self.host_ip = await self._discover_host()

        # Start background tasks
        udp_task = asyncio.create_task(self._udp_receive_loop())
        ctrl_task = asyncio.create_task(self._control_and_sync_client(self.host_ip))

        if HAS_RICH and enable_dashboard:
            with Live(self._render_dashboard(), refresh_per_second=8) as live:
                try:
                    while self.running:
                        live.update(self._render_dashboard())
                        await asyncio.sleep(0.125)
                except asyncio.CancelledError:
                    pass
        else:
            print(f"[*] SonicSync Receiver running. Connected to {self.host_ip}")
            try:
                while self.running:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                pass

        udp_task.cancel()
        ctrl_task.cancel()
        if self.audio_player:
            self.audio_player.stop()
        self.udp_sock.close()


def main():
    parser = argparse.ArgumentParser(description="SonicSync Lossless Audio Receiver Client")
    parser.add_argument("--host", type=str, default=None, help="Host server IP address (omit for auto-discovery)")
    parser.add_argument("--port", type=int, default=50005, help="UDP Audio Port")
    parser.add_argument("--control-port", type=int, default=50006, help="TCP Control & NTP Port")
    parser.add_argument("--device", type=int, default=None, help="Audio output device index")
    parser.add_argument("--buffer-margin", type=float, default=None, help="Override safety buffer margin in ms")
    parser.add_argument("--no-gui", action="store_true", help="Disable Rich terminal UI")

    args = parser.parse_args()

    receiver = SonicReceiver(
        host_ip=args.host,
        port=args.port,
        control_port=args.control_port,
        device=args.device,
        buffer_margin=args.buffer_margin
    )

    try:
        asyncio.run(receiver.run(enable_dashboard=not args.no_gui))
    except KeyboardInterrupt:
        print("\nShutting down SonicSync Receiver...")


if __name__ == "__main__":
    main()
