"""VLC Synchronization Sidecar daemon for multi-room VLC desktop listeners."""

import asyncio
import json
import logging
import os
import platform
import socket
import subprocess
import time
from typing import Optional
import websockets

from src.sync.clock_filter import ClockSyncFilter
from src.sync.drift_estimator import DriftEstimator

logger = logging.getLogger(__name__)

VLC_STREAM_URL = "rtp://@239.255.0.1:5006"


def find_vlc_binary() -> Optional[str]:
    """Locate VLC executable on host system."""
    sys_name = platform.system()
    if sys_name == "Windows":
        candidates = [
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    elif sys_name == "Darwin":
        candidate = "/Applications/VLC.app/Contents/MacOS/VLC"
        if os.path.exists(candidate):
            return candidate
    else:
        # Linux
        import shutil
        return shutil.which("vlc")
    return None


class VLCSyncSidecar:
    """Sidecar manager controlling a local VLC listener instance to synchronize with SonicSync host.

    Rate correction is driven by the estimated *clock drift* (frequency error in
    ppm), not by raw clock offset: VLC's native RTP buffering absorbs phase, so
    only the long-term frequency difference between the client and host quartz
    is correctable via the RC ``rate`` command.
    """

    MAX_RATE_CORRECTION = 0.0005  # ±500 ppm, matching SonicSync PLL limits

    def __init__(
        self,
        host_ip: str = "127.0.0.1",
        host_port: int = 8080,
        stream_url: str = VLC_STREAM_URL,
        rc_port: int = 4212,
        client_id: str = "vlc_sidecar_01",
        ntp_interval_sec: float = 0.5
    ):
        self.host_ip = host_ip
        self.host_port = host_port
        self.stream_url = stream_url
        self.rc_port = rc_port
        self.client_id = client_id
        self.ntp_interval_sec = ntp_interval_sec

        self.clock_filter = ClockSyncFilter()
        self.drift_estimator = DriftEstimator()

        self._vlc_process: Optional[subprocess.Popen] = None
        self._rc_socket: Optional[socket.socket] = None
        self._is_running = False

    def launch_vlc(self) -> bool:
        """Launch local VLC process with RC interface and low network caching."""
        vlc_path = find_vlc_binary()
        if not vlc_path:
            logger.warning("VLC binary not found on this system. VLC sidecar will run in simulated mode.")
            return False

        args = [
            vlc_path,
            "--network-caching=120",
            "--extraintf", "rc",
            "--rc-host", f"127.0.0.1:{self.rc_port}",
            "--quiet",
            "--no-video",
            self.stream_url
        ]
        try:
            self._vlc_process = subprocess.Popen(args)
            logger.info(f"Launched VLC (PID {self._vlc_process.pid}) with RC control on 127.0.0.1:{self.rc_port}")
            time.sleep(1.0)
            return True
        except Exception as e:
            logger.error(f"Failed to launch VLC: {e}")
            return False

    def connect_rc(self, retries: int = 5, retry_delay: float = 1.0) -> bool:
        """Connect TCP socket to VLC's RC interface, consuming the banner."""
        for attempt in range(retries):
            if not self._is_vlc_alive():
                logger.warning("VLC process is not running; cannot connect RC.")
                return False
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect(("127.0.0.1", self.rc_port))
                # Consume the welcome banner so it is not parsed as command output
                sock.settimeout(0.3)
                try:
                    sock.recv(4096)
                except socket.timeout:
                    pass
                sock.settimeout(2.0)
                self._rc_socket = sock
                logger.info("Connected to VLC RC interface.")
                return True
            except OSError as e:
                logger.debug(f"RC connect attempt {attempt + 1}/{retries} failed: {e}")
                try:
                    sock.close()
                except Exception:
                    pass
                time.sleep(retry_delay)
        logger.warning("Could not connect to VLC RC interface after retries.")
        return False

    def _is_vlc_alive(self) -> bool:
        return self._vlc_process is not None and self._vlc_process.poll() is None

    def send_rc_command(self, cmd: str) -> bool:
        """Send command string to VLC RC interface."""
        if self._rc_socket is None:
            return False
        try:
            self._rc_socket.sendall(f"{cmd}\n".encode('utf-8'))
            return True
        except OSError as e:
            logger.warning(f"Failed sending RC command {cmd!r}: {e}")
            return False

    def _apply_drift_correction(self, drift_ppm: float, locked: bool):
        """Convert estimated drift (ppm) into a bounded VLC rate command."""
        if not locked:
            return
        correction = max(-self.MAX_RATE_CORRECTION, min(self.MAX_RATE_CORRECTION, drift_ppm * 1e-6))
        if abs(correction) < 1e-7:
            return
        rate = 1.0 - correction
        self.send_rc_command(f"rate {rate:.6f}")

    async def run_sync_loop(self):
        """Connects to host WebSocket for NTP synchronization and telemetry reporting."""
        self._is_running = True
        ws_url = f"ws://{self.host_ip}:{self.host_port}/ws"

        while self._is_running:
            try:
                logger.info(f"Connecting to SonicSync control plane at {ws_url}...")
                async with websockets.connect(ws_url, open_timeout=5.0) as ws:
                    logger.info("Connected to host WebSocket control plane.")

                    while self._is_running:
                        t0 = time.perf_counter()
                        await ws.send(json.dumps({"type": "ntp_request", "t0": t0}))

                        # Read until the matching ntp_response arrives, skipping
                        # unsolicited frames (stream_config, telemetry echoes,
                        # binary audio) that would otherwise desync the pairing.
                        data = None
                        deadline = asyncio.get_event_loop().time() + 3.0
                        while asyncio.get_event_loop().time() < deadline:
                            remaining = deadline - asyncio.get_event_loop().time()
                            try:
                                resp_raw = await asyncio.wait_for(ws.recv(), timeout=max(0.05, remaining))
                            except asyncio.TimeoutError:
                                break
                            t3 = time.perf_counter()

                            if not isinstance(resp_raw, str):
                                continue
                            try:
                                msg = json.loads(resp_raw)
                            except json.JSONDecodeError:
                                continue

                            if msg.get("type") == "ntp_response" and abs(float(msg.get("t0", -1)) - t0) <= 1e-6:
                                data = (msg, t3)
                                break

                        if data is not None:
                            msg, t3 = data
                            t1 = float(msg["t1"])
                            t2 = float(msg["t2"])
                            offset, rtt, locked = self.clock_filter.add_measurement(t0, t1, t2, t3)
                            drift = self.drift_estimator.add_sample(t3, offset)

                            self._apply_drift_correction(drift, locked)

                            report = {
                                "type": "client_report",
                                "client_type": "vlc_sidecar",
                                "offset_ms": offset * 1000.0,
                                "rtt_ms": rtt * 1000.0,
                                "drift_ppm": drift,
                                "is_locked": locked
                            }
                            await ws.send(json.dumps(report))

                        await asyncio.sleep(self.ntp_interval_sec)

            except Exception as e:
                logger.debug(f"Sidecar connection retry in 2s: {e}")
                await asyncio.sleep(2.0)

    def stop(self):
        self._is_running = False
        if self._rc_socket:
            try:
                self._rc_socket.close()
            except Exception:
                pass
            self._rc_socket = None
        if self._vlc_process:
            try:
                self._vlc_process.terminate()
                try:
                    self._vlc_process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._vlc_process.kill()
                    self._vlc_process.wait(timeout=2.0)
            except Exception as e:
                logger.debug(f"VLC teardown note: {e}")
            self._vlc_process = None
