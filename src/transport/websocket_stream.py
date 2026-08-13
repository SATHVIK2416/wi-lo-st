"""WebSocket binary audio broadcaster and NTP control plane handler."""

import asyncio
import json
import logging
import time
from typing import Set, Optional
import aiohttp
from aiohttp import web

from src.core.clock import MasterClock
from src.core.packet import AudioPacket
from src.sync.sync_coordinator import MasterSyncCoordinator

logger = logging.getLogger(__name__)


class WebSocketStreamManager:
    """Manages WebSocket connections for zero-install mobile/desktop browser listeners."""

    def __init__(self, sync_coordinator: MasterSyncCoordinator):
        self.sync_coordinator = sync_coordinator
        self._clients: Set[web.WebSocketResponse] = set()
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """Handle incoming WebSocket connection from web browser client or sidecar."""
        ws = web.WebSocketResponse(
            heartbeat=10.0,
            protocols=['binary', 'json']
        )
        await ws.prepare(request)

        client_ip = request.remote or "127.0.0.1"
        client_id = f"client_{id(ws) % 10000:04d}"

        self._clients.add(ws)
        logger.info(f"WebSocket client connected: {client_id} ({client_ip})")

        # Send initial stream configuration
        try:
            init_msg = {
                "type": "stream_config",
                "client_id": client_id,
                "target_delay_ms": self.sync_coordinator.base_target_delay_ms,
                "server_time": MasterClock.now()
            }
            await ws.send_str(json.dumps(init_msg))
        except Exception as e:
            logger.debug(f"Failed to send init msg: {e}")

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        msg_type = data.get("type")

                        if msg_type == "ntp_request":
                            # 4-timestamp NTP protocol exchange
                            t0 = float(data.get("t0", 0.0))
                            t1 = MasterClock.now()
                            t2 = MasterClock.now()
                            reply = {
                                "type": "ntp_response",
                                "t0": t0,
                                "t1": t1,
                                "t2": t2
                            }
                            await ws.send_str(json.dumps(reply))

                        elif msg_type == "client_report":
                            # Live telemetry from web player
                            self.sync_coordinator.update_client_report(
                                client_id=data.get("client_id", client_id),
                                client_type=data.get("client_type", "web"),
                                ip_address=client_ip,
                                buffer_depth_ms=float(data.get("buffer_ms", 100.0)),
                                clock_offset_ms=float(data.get("offset_ms", 0.0)),
                                rtt_ms=float(data.get("rtt_ms", 0.0)),
                                drift_ppm=float(data.get("drift_ppm", 0.0)),
                                is_locked=bool(data.get("is_locked", True)),
                                underruns=int(data.get("underruns", 0)),
                                overruns=int(data.get("overruns", 0)),
                                packet_loss_rate=float(data.get("packet_loss", 0.0)),
                                resample_ratio=float(data.get("resample_ratio", 1.0))
                            )

                    except Exception as ex:
                        logger.debug(f"Error handling WS message: {ex}")

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.debug(f"WebSocket closed with exception: {ws.exception()}")

        finally:
            self._clients.discard(ws)
            self.sync_coordinator.remove_client(client_id)
            logger.info(f"WebSocket client disconnected: {client_id}")

        return ws

    async def broadcast_binary(self, raw_packet_bytes: bytes):
        """Broadcast serialized binary audio packet to all connected WebSocket listeners."""
        if not self._clients:
            return

        stale_clients = []
        for ws in list(self._clients):
            if ws.closed:
                stale_clients.append(ws)
                continue
            try:
                await ws.send_bytes(raw_packet_bytes)
            except Exception:
                stale_clients.append(ws)

        for ws in stale_clients:
            self._clients.discard(ws)
