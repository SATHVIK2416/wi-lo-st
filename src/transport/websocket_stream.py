"""WebSocket binary audio broadcaster and NTP control plane handler.

Each client owns an outbound queue drained by a dedicated sender task so one
slow listener can never stall the real-time broadcast loop (head-of-line
blocking) or corrupt the 10 ms PTS cadence.
"""

import asyncio
import itertools
import json
import logging
from typing import Optional, Set, Callable, Dict, Any
import aiohttp
from aiohttp import web

from src.core.clock import MasterClock
from src.sync.sync_coordinator import MasterSyncCoordinator

logger = logging.getLogger(__name__)


class _ClientConnection:
    __slots__ = ("ws", "client_id", "queue", "sender_task")

    def __init__(self, ws: web.WebSocketResponse, client_id: str):
        self.ws = ws
        self.client_id = client_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self.sender_task: Optional[asyncio.Task] = None


class WebSocketStreamManager:
    """Manages WebSocket connections for zero-install mobile/desktop browser listeners."""

    def __init__(
        self,
        sync_coordinator: MasterSyncCoordinator,
        stream_info: Optional[Dict[str, Any]] = None,
        auth_check: Optional[Callable[[web.Request], bool]] = None
    ):
        self.sync_coordinator = sync_coordinator
        self.stream_info = stream_info or {}
        self.auth_check = auth_check
        self._clients: Set[_ClientConnection] = set()
        self._id_counter = itertools.count(1)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """Handle incoming WebSocket connection from web browser client or sidecar."""
        if self.auth_check is not None and not self.auth_check(request):
            raise web.HTTPUnauthorized(text="invalid or missing session token")

        ws = web.WebSocketResponse(
            heartbeat=10.0,
            protocols=['binary', 'json']
        )
        await ws.prepare(request)

        client_ip = request.remote or "127.0.0.1"
        client_id = f"client_{next(self._id_counter):04d}"
        conn = _ClientConnection(ws, client_id)

        conn.sender_task = asyncio.create_task(self._sender_loop(conn))
        self._clients.add(conn)
        logger.info(f"WebSocket client connected: {client_id} ({client_ip})")

        try:
            init_msg = {
                "type": "stream_config",
                "client_id": client_id,
                "target_delay_ms": self.sync_coordinator.base_target_delay_ms,
                "server_time": MasterClock.now(),
                **self.stream_info
            }
            await ws.send_str(json.dumps(init_msg))
        except Exception as e:
            logger.debug(f"Failed to send init msg: {e}")

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_text(conn, msg.data, client_ip)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    logger.debug(f"Ignoring {len(msg.data)} binary bytes from {client_id}")
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.debug(f"WebSocket closed with exception: {ws.exception()}")
        finally:
            await self._disconnect(conn)

        return ws

    async def _handle_text(self, conn: _ClientConnection, raw: str, client_ip: str):
        try:
            data = json.loads(raw)
            msg_type = data.get("type")
        except (json.JSONDecodeError, AttributeError) as ex:
            await self._send_error(conn, f"malformed JSON message: {ex}")
            return

        if msg_type == "ntp_request":
            t0 = data.get("t0")
            if not isinstance(t0, (int, float)):
                await self._send_error(conn, "ntp_request requires numeric t0")
                return
            # 4-timestamp NTP protocol exchange
            t1 = MasterClock.now()
            t2 = MasterClock.now()
            reply = {
                "type": "ntp_response",
                "t0": float(t0),
                "t1": t1,
                "t2": t2
            }
            await self._safe_send_json(conn, reply)

        elif msg_type in ("client_report", "buffer_report"):
            # Live telemetry from web player; server-assigned id is authoritative
            try:
                self.sync_coordinator.update_client_report(
                    client_id=conn.client_id,
                    client_type=data.get("client_type", "web"),
                    ip_address=client_ip,
                    buffer_depth_ms=float(data.get("buffer_ms", 100.0)),
                    clock_offset_ms=float(data.get("offset_ms", 0.0)),
                    rtt_ms=float(data.get("rtt_ms", 0.0)),
                    drift_ppm=float(data.get("drift_ppm", 0.0)),
                    is_locked=bool(data.get("is_locked", False)),
                    underruns=int(data.get("underruns", 0)),
                    overruns=int(data.get("overruns", 0)),
                    packet_loss_rate=float(data.get("packet_loss", 0.0)),
                    resample_ratio=float(data.get("resample_ratio", 1.0))
                )
            except (TypeError, ValueError) as ex:
                await self._send_error(conn, f"invalid client_report field: {ex}")

        elif msg_type == "resync_request":
            # Re-anchor the client with fresh server time and target delay
            reply = {
                "type": "sync_lock",
                "server_time": MasterClock.now(),
                "target_delay_ms": self.sync_coordinator.base_target_delay_ms,
                "locked": True
            }
            await self._safe_send_json(conn, reply)

        else:
            await self._send_error(conn, f"unknown message type: {msg_type!r}")

    async def _sender_loop(self, conn: _ClientConnection):
        try:
            while not conn.ws.closed:
                data = await conn.queue.get()
                await conn.ws.send_bytes(data)
        except (ConnectionError, RuntimeError, asyncio.CancelledError):
            pass
        except Exception as ex:
            logger.debug(f"Sender task error for {conn.client_id}: {ex}")

    async def broadcast_binary(self, raw_packet_bytes: bytes):
        """Queue a serialized binary audio packet for all connected WebSocket listeners.

        Never awaits network IO: slow clients simply accumulate queue backpressure
        and are dropped once their queue overflows.
        """
        if not self._clients:
            return

        stale = []
        for conn in list(self._clients):
            if conn.ws.closed:
                stale.append(conn)
                continue
            try:
                conn.queue.put_nowait(raw_packet_bytes)
            except asyncio.QueueFull:
                logger.info(f"Dropping slow WebSocket client {conn.client_id}")
                stale.append(conn)

        for conn in stale:
            await self._disconnect(conn)

    async def _safe_send_json(self, conn: _ClientConnection, payload: dict):
        try:
            await conn.ws.send_str(json.dumps(payload))
        except Exception as ex:
            logger.debug(f"Send JSON failed for {conn.client_id}: {ex}")

    async def _send_error(self, conn: _ClientConnection, message: str):
        await self._safe_send_json(conn, {"type": "error", "message": message})

    async def _disconnect(self, conn: _ClientConnection):
        if conn.sender_task is not None:
            conn.sender_task.cancel()
        self._clients.discard(conn)
        self.sync_coordinator.remove_client(conn.client_id)
        logger.info(f"WebSocket client disconnected: {conn.client_id}")
