"""
SonicSync - Host Server Application
Broadcasts lossless audio over UDP, coordinates multi-client NTP clock synchronization,
automatically calculates optimal latency delay, and displays real-time live telemetry.
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
from typing import Dict, Optional

import numpy as np

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.audio import (
    AudioCapture,
    AudioFormat,
    AudioFormatCode,
    AudioPacket,
    CompressionType,
    PacketType,
    calculate_rms_and_peak,
)
from src.sync import (
    ClockSyncFilter,
    MasterSyncCoordinator,
    NTPMessage,
    SyncStats,
)

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SonicSync.Host")


class SonicHost:
    def __init__(self, config_path: str = "config/settings.json", **cli_overrides):
        self.config = self._load_config(config_path)
        self._apply_cli_overrides(cli_overrides)

        # Audio Format
        fmt_code = AudioFormatCode.INT16
        fmt_str = self.config["audio"].get("format", "int16").lower()
        if fmt_str == "int24":
            fmt_code = AudioFormatCode.INT24
        elif fmt_str == "int32":
            fmt_code = AudioFormatCode.INT32
        elif fmt_str == "float32":
            fmt_code = AudioFormatCode.FLOAT32

        comp = CompressionType.FLAC if self.config["audio"].get("compression") == "flac" else CompressionType.NONE

        self.audio_format = AudioFormat(
            sample_rate=self.config["audio"].get("sample_rate", 48000),
            channels=self.config["audio"].get("channels", 2),
            format_code=fmt_code,
            block_size=self.config["audio"].get("block_size", 256),
            compression=comp
        )

        # Network Settings
        self.audio_port = self.config["network"].get("audio_port", 50005)
        self.control_port = self.config["network"].get("control_port", 50006)
        self.discovery_port = self.config["network"].get("discovery_port", 50007)
        self.broadcast_ip = self.config["network"].get("broadcast_ip", "255.255.255.255")
        self.multicast_ip = self.config["network"].get("multicast_ip", "239.255.0.1")
        self.network_mode = self.config["network"].get("mode", "broadcast")

        # Sync Coordinator
        safety_margin = self.config["sync"].get("safety_margin_ms", 15.0)
        self.sync_coordinator = MasterSyncCoordinator(base_safety_margin_ms=safety_margin)

        # State
        self.running = False
        self.sequence_number = 0
        self.total_bytes_sent = 0
        self.total_packets_sent = 0
        self.current_dbfs = -100.0
        self.current_peak = 0.0
        self.connected_clients: Dict[int, dict] = {}
        self.lock = threading.Lock()

        # UDP Audio Socket
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if self.network_mode == "broadcast":
            self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            # Set high priority DSCP / TOS if supported
            self.udp_sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0x10)
        except Exception:
            pass

        # Audio Capture
        capture_source = self.config["audio"].get("source", "loopback")
        file_path = self.config["audio"].get("file_path", None)
        self.audio_capture = AudioCapture(
            audio_format=self.audio_format,
            source=capture_source,
            device_index=self.config["audio"].get("input_device"),
            file_path=file_path,
            callback=self._on_audio_chunk
        )

        self.ntp_filters: Dict[int, ClockSyncFilter] = {}

    def _load_config(self, path: str) -> dict:
        default_config = {
            "audio": {"sample_rate": 48000, "channels": 2, "format": "int16", "block_size": 256, "source": "loopback"},
            "network": {"audio_port": 50005, "control_port": 50006, "discovery_port": 50007, "broadcast_ip": "255.255.255.255", "mode": "broadcast"},
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

    def _apply_cli_overrides(self, overrides: dict):
        if overrides.get("source"):
            self.config["audio"]["source"] = overrides["source"]
        if overrides.get("rate"):
            self.config["audio"]["sample_rate"] = int(overrides["rate"])
        if overrides.get("channels"):
            self.config["audio"]["channels"] = int(overrides["channels"])
        if overrides.get("format"):
            self.config["audio"]["format"] = overrides["format"]
        if overrides.get("flac"):
            self.config["audio"]["compression"] = "flac"
        if overrides.get("port"):
            self.config["network"]["audio_port"] = int(overrides["port"])
        if overrides.get("control_port"):
            self.config["network"]["control_port"] = int(overrides["control_port"])
        if overrides.get("file"):
            self.config["audio"]["file_path"] = overrides["file"]
            self.config["audio"]["source"] = "file"

    def _on_audio_chunk(self, samples: np.ndarray, pts: float):
        """Audio callback triggered by AudioCapture engine."""
        if not self.running:
            return

        dbfs, peak = calculate_rms_and_peak(samples)
        self.current_dbfs = dbfs
        self.current_peak = peak

        # Convert to PCM bytes and compress if configured
        raw_pcm = self.audio_format.pcm_to_bytes(samples)
        payload, pkt_type = self.audio_format.compress(raw_pcm, len(samples))

        # Get optimal target playout delay across all synced receivers
        target_delay = self.sync_coordinator.get_target_delay()

        packet = AudioPacket(
            packet_type=pkt_type,
            format_code=self.audio_format.format_code,
            channels=self.audio_format.channels,
            sample_rate=self.audio_format.sample_rate,
            sequence_number=self.sequence_number,
            pts=pts,
            target_delay=target_delay,
            frame_count=len(samples),
            payload=payload
        )
        self.sequence_number += 1

        wire_bytes = packet.pack()
        dest_addr = (self.broadcast_ip, self.audio_port)
        try:
            self.udp_sock.sendto(wire_bytes, dest_addr)
            self.total_bytes_sent += len(wire_bytes)
            self.total_packets_sent += 1
        except Exception as e:
            logger.debug(f"Audio send error: {e}")

    async def _start_beacon_broadcaster(self):
        """Broadcasts UDP discovery beacons so receivers can automatically detect host."""
        beacon_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        beacon_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        beacon_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        beacon_sock.setblocking(False)

        while self.running:
            try:
                beacon_data = json.dumps({
                    "service": "sonicsync",
                    "version": 1,
                    "audio_port": self.audio_port,
                    "control_port": self.control_port,
                    "sample_rate": self.audio_format.sample_rate,
                    "channels": self.audio_format.channels,
                    "format": self.audio_format.format_code.name,
                    "compression": self.audio_format.compression.name
                }).encode("utf-8")

                beacon_sock.sendto(beacon_data, (self.broadcast_ip, self.discovery_port))
            except Exception as e:
                logger.debug(f"Beacon error: {e}")
            await asyncio.sleep(1.0)

    async def _handle_control_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handles TCP control connection and NTP sync with a connected receiver."""
        client_addr = writer.get_extra_info("peername")
        client_ip = client_addr[0] if client_addr else "Unknown"
        client_id = hash(client_addr) & 0xFFFF
        logger.info(f"Receiver connected from {client_addr} (ID: {client_id})")

        with self.lock:
            self.connected_clients[client_id] = {
                "id": client_id,
                "ip": client_ip,
                "name": f"Receiver-{client_id:04x}",
                "connected_at": time.time(),
                "last_seen": time.time(),
                "rtt_ms": 0.0,
                "offset_ms": 0.0,
                "jitter_ms": 0.0,
                "one_way_ms": 0.0,
                "synced": False
            }
            if client_id not in self.ntp_filters:
                self.ntp_filters[client_id] = ClockSyncFilter()

        # Send initial HELLO handshake with format info
        hello_msg = json.dumps({
            "type": "HELLO",
            "client_id": client_id,
            "sample_rate": self.audio_format.sample_rate,
            "channels": self.audio_format.channels,
            "format": self.audio_format.format_code.name,
            "compression": self.audio_format.compression.name,
            "block_size": self.audio_format.block_size
        }).encode("utf-8") + b"\n"
        writer.write(hello_msg)
        await writer.drain()

        # Background ping loop for this client
        async def ping_loop():
            seq = 0
            while self.running and not writer.is_closing():
                t0 = time.time()
                ntp_ping = NTPMessage(
                    msg_type=PacketType.SYNC_PING,
                    client_id=client_id,
                    sequence=seq,
                    t0=t0
                )
                raw_ntp = ntp_ping.pack()
                # Send binary NTP packet prefixed with length (2 bytes)
                try:
                    writer.write(struct.pack("!H", len(raw_ntp)) + raw_ntp)
                    await writer.drain()
                except Exception:
                    break
                seq += 1
                await asyncio.sleep(0.1)  # 10 Hz NTP ping loop

        ping_task = asyncio.create_task(ping_loop())

        try:
            while self.running:
                # Read 2-byte prefix or line
                header = await reader.readexactly(2)
                pkt_len = struct.unpack("!H", header)[0]
                body = await reader.readexactly(pkt_len)

                # Check if NTP response
                if body.startswith(b"SONI"):
                    ntp_resp = NTPMessage.unpack(body)
                    if ntp_resp and ntp_resp.msg_type == PacketType.SYNC_PONG:
                        t3 = time.time()
                        res = self.ntp_filters[client_id].add_sample(
                            t0=ntp_resp.t0,
                            t1=ntp_resp.t1,
                            t2=ntp_resp.t2,
                            t3=t3
                        )
                        stats = self.ntp_filters[client_id].get_stats()
                        self.sync_coordinator.update_client_stats(client_id, stats)

                        with self.lock:
                            if client_id in self.connected_clients:
                                c = self.connected_clients[client_id]
                                c["rtt_ms"] = stats.rtt_ms
                                c["offset_ms"] = stats.offset_ms
                                c["jitter_ms"] = stats.jitter_ms
                                c["one_way_ms"] = stats.one_way_delay_ms
                                c["synced"] = stats.is_synchronized
                                c["last_seen"] = time.time()
                else:
                    # JSON Telemetry message
                    try:
                        telemetry = json.loads(body.decode("utf-8"))
                        if telemetry.get("type") == "TELEMETRY":
                            with self.lock:
                                if client_id in self.connected_clients:
                                    self.connected_clients[client_id].update(telemetry)
                    except Exception:
                        pass

        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            ping_task.cancel()
            writer.close()
            with self.lock:
                if client_id in self.connected_clients:
                    del self.connected_clients[client_id]
                self.sync_coordinator.remove_client(client_id)
            logger.info(f"Receiver disconnected: ID {client_id}")

    def _render_dashboard(self) -> Table:
        table = Table(title="🎵 SonicSync - Audiophile Lossless Network Broadcaster", expand=True)
        table.add_column("Property", style="cyan", no_wrap=True)
        table.add_column("Value", style="green")

        bitrate = (self.audio_format.sample_rate * self.audio_format.bytes_per_frame * 8) / 1_000_000.0
        table.add_row("Stream Quality", f"{self.audio_format.sample_rate} Hz / {self.audio_format.format_code.name} / {self.audio_format.channels}ch (Lossless PCM)")
        table.add_row("Audio Source", f"{self.audio_capture.source.upper()}")
        table.add_row("Raw Bitrate", f"{bitrate:.2f} Mbps (Uncompressed)")
        table.add_row("Global Sync Target Delay", f"{self.sync_coordinator.get_target_delay() * 1000.0:.2f} ms")
        table.add_row("Packets Broadcasted", f"{self.total_packets_sent:,} ({self.total_bytes_sent / (1024*1024):.1f} MB)")

        # Volume VU meter
        vu_bars = int(max(0, min(30, (self.current_dbfs + 60) * 0.5)))
        meter = "█" * vu_bars + "░" * (30 - vu_bars)
        table.add_row("Audio Level (Peak / RMS)", f"{meter} [{self.current_dbfs:.1f} dBFS | Peak {self.current_peak:.2f}]")

        # Clients sub-table
        client_table = Table(title="Connected Receivers (Auto Phase-Locked Sync)", expand=True)
        client_table.add_column("Client ID", style="bold yellow")
        client_table.add_column("IP Address", style="white")
        client_table.add_column("RTT (Lag)", style="magenta")
        client_table.add_column("1-Way Latency", style="cyan")
        client_table.add_column("Clock Offset", style="blue")
        client_table.add_column("Jitter", style="yellow")
        client_table.add_column("Sync Status", style="green")

        with self.lock:
            for cid, c in self.connected_clients.items():
                status_str = "🟢 IN SYNC (<0.5ms)" if c.get("synced") else "🟡 SYNCHRONIZING..."
                client_table.add_row(
                    f"0x{cid:04x}",
                    c.get("ip", "Unknown"),
                    f"{c.get('rtt_ms', 0.0):.2f} ms",
                    f"{c.get('one_way_ms', 0.0):.2f} ms",
                    f"{c.get('offset_ms', 0.0):+.2f} ms",
                    f"{c.get('jitter_ms', 0.0):.2f} ms",
                    status_str
                )

        layout_table = Table.grid(expand=True)
        layout_table.add_row(table)
        layout_table.add_row(client_table)
        return layout_table

    async def run(self, enable_dashboard: bool = True):
        self.running = True
        self.audio_capture.start()

        # Start Discovery Beacon
        beacon_task = asyncio.create_task(self._start_beacon_broadcaster())

        # Start TCP Control / NTP Server
        server = await asyncio.start_server(
            self._handle_control_client,
            "0.0.0.0",
            self.control_port
        )
        logger.info(f"Host Control Server listening on port {self.control_port}")
        logger.info(f"Broadcasting Lossless Audio on UDP port {self.audio_port}")

        if HAS_RICH and enable_dashboard:
            with Live(self._render_dashboard(), refresh_per_second=8) as live:
                try:
                    while self.running:
                        live.update(self._render_dashboard())
                        await asyncio.sleep(0.125)
                except asyncio.CancelledError:
                    pass
        else:
            print(f"[*] SonicSync Host is live! Broadcasting on UDP {self.audio_port}, Control TCP {self.control_port}")
            try:
                while self.running:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                pass

        beacon_task.cancel()
        server.close()
        await server.wait_closed()
        self.audio_capture.stop()
        self.udp_sock.close()


def main():
    parser = argparse.ArgumentParser(description="SonicSync Lossless Audio Host Server")
    parser.add_argument("--source", choices=["loopback", "mic", "sine", "stereo_sweep", "click_metronome", "file"], default="loopback", help="Audio capture source")
    parser.add_argument("--file", type=str, help="Path to WAV/FLAC audio file (if --source file)")
    parser.add_argument("--rate", type=int, default=48000, help="Sample rate (e.g. 44100, 48000, 96000, 192000)")
    parser.add_argument("--channels", type=int, default=2, help="Number of audio channels (1 or 2)")
    parser.add_argument("--format", choices=["int16", "int24", "int32", "float32"], default="int16", help="Lossless bit depth format")
    parser.add_argument("--flac", action="store_true", help="Enable FLAC lossless compression")
    parser.add_argument("--port", type=int, default=50005, help="UDP Audio Broadcast Port")
    parser.add_argument("--control-port", type=int, default=50006, help="TCP Control & NTP Port")
    parser.add_argument("--no-gui", action="store_true", help="Disable Rich terminal dashboard")

    args = parser.parse_args()

    host = SonicHost(
        config_path="config/settings.json",
        source=args.source,
        file=args.file,
        rate=args.rate,
        channels=args.channels,
        format=args.format,
        flac=args.flac,
        port=args.port,
        control_port=args.control_port
    )

    try:
        asyncio.run(host.run(enable_dashboard=not args.no_gui))
    except KeyboardInterrupt:
        print("\nShutting down SonicSync Host...")


if __name__ == "__main__":
    main()
