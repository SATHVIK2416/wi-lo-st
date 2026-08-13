"""Integration tests for web server REST APIs."""

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from src.server.api import create_api_routes
from src.core.audio_format import AudioFormat
from src.core.limiter import SoftKneeLimiter
from src.core.ring_buffer import RingBuffer
from src.capture.test_generator import TestGeneratorSource
from src.vlc.vlc_source import VLCSource
from src.sync.sync_coordinator import MasterSyncCoordinator
from src.transport.websocket_stream import WebSocketStreamManager
from src.server.auth import SessionManager
from src.server.web_server import SourceManager


@pytest.mark.asyncio
async def test_rest_apis():
    audio_format = AudioFormat(sample_rate=48000, channels=2)
    ring = RingBuffer(capacity_frames=48000, channels=2)
    vlc_src = VLCSource(audio_format)
    wasapi_src = TestGeneratorSource(audio_format)
    test_src = TestGeneratorSource(audio_format)
    source_mgr = SourceManager(ring, audio_format, vlc_src, wasapi_src, test_src)
    sync_coord = MasterSyncCoordinator(base_target_delay_ms=100.0)
    ws_mgr = WebSocketStreamManager(sync_coord)
    limiter = SoftKneeLimiter(sample_rate=48000, channels=2)
    session_mgr = SessionManager()

    app_state = {
        "source_manager": source_mgr,
        "vlc_source": vlc_src,
        "test_generator": test_src,
        "sync_coordinator": sync_coord,
        "ws_manager": ws_mgr,
        "audio_format": audio_format,
        "limiter": limiter,
        "lan_ip": "127.0.0.1",
        "port": 8080,
        "session_manager": session_mgr
    }

    app = web.Application()
    routes = create_api_routes(app_state)
    app.add_routes(routes)

    client = TestClient(TestServer(app))
    await client.start_server()

    try:
        # Test GET /api/status
        resp = await client.get("/api/status")
        assert resp.status == 200
        data = await resp.json()
        assert data["version"] == "1.0.0"
        assert data["sample_rate"] == 48000

        # Test POST /api/control (switch source)
        ctrl_resp = await client.post("/api/control", json={"action": "set_source", "source": "test"})
        assert ctrl_resp.status == 200
        ctrl_data = await ctrl_resp.json()
        assert ctrl_data["active_source"] == "test"

        # Test GET /api/clients
        clients_resp = await client.get("/api/clients")
        assert clients_resp.status == 200

        # Test GET /api/sdp
        sdp_resp = await client.get("/api/sdp")
        assert sdp_resp.status == 200
        sdp_text = await sdp_resp.text()
        assert "v=0" in sdp_text

        # Test GET /api/stream.m3u
        m3u_resp = await client.get("/api/stream.m3u")
        assert m3u_resp.status == 200
        m3u_text = await m3u_resp.text()
        assert "#EXTM3U" in m3u_text

        # Test GET /api/qr
        qr_resp = await client.get("/api/qr?format=json")
        assert qr_resp.status == 200
        qr_data = await qr_resp.json()
        assert "data_uri" in qr_data

    finally:
        await client.close()
