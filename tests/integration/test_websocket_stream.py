"""Integration test for WebSocket streaming and NTP message exchange."""

import json
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from src.sync.sync_coordinator import MasterSyncCoordinator
from src.transport.websocket_stream import WebSocketStreamManager


@pytest.mark.asyncio
async def test_websocket_ntp_and_telemetry():
    sync_coord = MasterSyncCoordinator(base_target_delay_ms=100.0)
    ws_mgr = WebSocketStreamManager(sync_coord)

    app = web.Application()
    app.router.add_get("/ws", ws_mgr.handle_ws)

    client = TestClient(TestServer(app))
    await client.start_server()

    try:
        ws = await client.ws_connect("/ws")

        # Receive initial stream_config
        init_msg = await ws.receive_json()
        assert init_msg["type"] == "stream_config"

        # Send NTP request
        t0 = 100.0
        await ws.send_json({"type": "ntp_request", "t0": t0})
        ntp_reply = await ws.receive_json()
        assert ntp_reply["type"] == "ntp_response"
        assert ntp_reply["t0"] == t0
        assert "t1" in ntp_reply
        assert "t2" in ntp_reply

        # Send client report
        report = {
            "type": "client_report",
            "client_id": "test_phone",
            "client_type": "web",
            "buffer_ms": 102.5,
            "offset_ms": 1.2,
            "rtt_ms": 12.0,
            "drift_ppm": 0.5,
            "is_locked": True,
            "underruns": 0,
            "resample_ratio": 1.0001
        }
        await ws.send_json(report)

        # Allow report to be processed in coordinator
        import asyncio
        await asyncio.sleep(0.05)
        clients = sync_coord.get_clients()
        assert len(clients) == 1
        assert clients[0]["client_id"] == "test_phone"
        assert clients[0]["buffer_depth_ms"] == 102.5

        await ws.close()

    finally:
        await client.close()
