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
from src.sync.pll_controller import PLLController

logger = logging.getLogger(__name__)


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
    """Sidecar manager controlling a local VLC listener instance to synchronize with SonicSync host."""

    def __init__(
        self,
        host_ip: str = "127.0.0.1",
        host_port: int = 8080,
        stream_url: str = "rtp://@239.255.0.1:5004",
        rc_port: int = 4212,
        client_id: str = "vlc_sidecar_01"
    ):
        self.host_ip = host_ip
        self.host_port = host_port
        self.stream_url = stream_url
        self.rc_port = rc_port
        self.client_id = client_id

        self.clock_filter = ClockSyncFilter()
        self.drift_estimator = DriftEstimator()
        self.pll = PLLController(target_delay_sec=0.100)

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

    def connect_rc(self) -> bool:
        """Connect TCP socket to VLC's RC interface."""
        try:
            self._rc_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._rc_socket.connect(("127.0.0.1", self.rc_port))
            logger.info("Connected to VLC RC interface.")
            return True
        except Exception as e:
            logger.debug(f"Could not connect to VLC RC: {e}")
            return False

    def send_rc_command(self, cmd: str) -> bool:
        """Send command string to VLC RC interface."""
        if self._rc_socket is None:
            return False
        try:
            self._rc_socket.sendall(f"{cmd}\n".encode('utf-8'))
            return True
        except Exception as e:
            logger.debug(f"Failed sending RC command: {e}")
            return False

    async def run_sync_loop(self):
        """Connects to host WebSocket for NTP synchronization and telemetry reporting."""
        self._is_running = True
        ws_url = f"ws://{self.host_ip}:{self.host_port}/ws"

        while self._is_running:
            try:
                logger.info(f"Connecting to SonicSync control plane at {ws_url}...")
                async with websockets.connect(ws_url) as ws:
                    logger.info("Connected to host WebSocket control plane.")

                    while self._is_running:
                        # 1. Send NTP ping
                        t0 = time.perf_counter()
                        req = {"type": "ntp_request", "t0": t0}
                        await ws.send(json.dumps(req))

                        # 2. Receive response
                        resp_raw = await ws.recv()
                        t3 = time.perf_counter()

                        if isinstance(resp_raw, str):
                            data = json.loads(resp_raw)
                            if data.get("type") == "ntp_response":
                                t1 = float(data["t1"])
                                t2 = float(data["t2"])
                                offset, rtt, locked = self.clock_filter.add_measurement(t0, t1, t2, t3)
                                drift = self.drift_estimator.add_sample(t3, offset)

                                # Micro rate adjustment via VLC RC
                                if locked and abs(offset) > 0.005:  # > 5ms error
                                    ratio = self.pll.update(0.100 + offset, dt=1.0)
                                    self.send_rc_command(f"rate {ratio:.4f}")

                                # 3. Send telemetry report back to host
                                report = {
                                    "type": "client_report",
                                    "client_id": self.client_id,
                                    "client_type": "vlc_sidecar",
                                    "buffer_ms": 120.0,
                                    "offset_ms": offset * 1000.0,
                                    "rtt_ms": rtt * 1000.0,
                                    "drift_ppm": drift,
                                    "is_locked": locked,
                                    "underruns": 0,
                                    "overruns": 0,
                                    "resample_ratio": self.pll.current_ratio
                                }
                                await ws.send(json.dumps(report))

                        await asyncio.sleep(1.0)

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
            except Exception:
                pass
            self._vlc_process = None
