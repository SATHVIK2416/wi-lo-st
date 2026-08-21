"""REST API handlers for SonicSync host, VLC control, and stream telemetry."""

import json
import logging
import os
import numpy as np
from aiohttp import web

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".aiff", ".m3u"}


def _parse_float(value, default=None):
    """Parse a float from a JSON value, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_int(value, default=None):
    """Parse an int from a JSON value, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def create_api_routes(app_state: dict) -> list[web.RouteDef]:
    """Create REST API route definitions."""

    def _auth_denied(request: web.Request):
        """Return a 401 response when the request lacks a valid session token.

        Open mode (no PIN configured) never denies. Read-only informational
        routes do not call this; only state-changing endpoints are guarded.
        """
        session_manager = app_state.get("session_manager")
        if session_manager is None or not session_manager.pin_enabled:
            return None
        token = session_manager.extract_token(request)
        if session_manager.validate_token(token):
            return None
        return web.json_response({"error": "valid session token required"}, status=401)

    async def post_auth(request: web.Request) -> web.Response:
        """POST /api/auth - Exchange a PIN for a session token."""
        session_manager = app_state.get("session_manager")
        if session_manager is None:
            return web.json_response({"error": "auth unavailable"}, status=500)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        pin = data.get("pin", "")
        token = session_manager.verify_pin_and_issue_token(str(pin))
        if token is None:
            return web.json_response({"error": "invalid PIN or locked out"}, status=403)
        return web.json_response({"status": "success", "token": token})

    async def get_status(request: web.Request) -> web.Response:
        """GET /api/status - Comprehensive system state."""
        source_manager = app_state["source_manager"]
        sync_coordinator = app_state["sync_coordinator"]
        ws_manager = app_state["ws_manager"]
        audio_format = app_state["audio_format"]
        lan_ip = app_state["lan_ip"]
        port = app_state["port"]

        vlc_status = {}
        if hasattr(source_manager.current_source, "get_status"):
            vlc_status = source_manager.current_source.get_status()

        def _safe_json_default(obj):
            if hasattr(obj, 'item'):
                return obj.item()
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

        status_data = {
            "version": "1.0.0",
            "host_ip": str(lan_ip),
            "port": int(port),
            "active_source": str(source_manager.source_type),
            "sample_rate": int(audio_format.sample_rate),
            "channels": int(audio_format.channels),
            "format": str(audio_format.sample_format.name),
            "target_delay_ms": float(sync_coordinator.base_target_delay_ms),
            "connected_clients": int(ws_manager.client_count),
            "limiter_enabled": bool(app_state["limiter"].enabled),
            "limiter_reduction_db": round(float(app_state["limiter"].last_gain_reduction_db), 1),
            "vlc": vlc_status,
            "sdp_url": f"http://{lan_ip}:{port}/api/sdp",
            "m3u_url": f"http://{lan_ip}:{port}/api/stream.m3u",
            "listen_url": f"http://{lan_ip}:{port}/listen",
            "auth_required": bool(app_state.get("session_manager") and app_state["session_manager"].pin_enabled),
        }
        return web.json_response(status_data, dumps=lambda obj: json.dumps(obj, default=_safe_json_default))

    async def post_control(request: web.Request) -> web.Response:
        """POST /api/control - Playback, volume, source selection, and settings."""
        denied = _auth_denied(request)
        if denied:
            return denied
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        action = data.get("action")
        source_manager = app_state["source_manager"]

        if action == "set_source":
            new_source = data.get("source", "vlc")
            source_manager.switch_source(new_source)
            return web.json_response({"status": "success", "active_source": source_manager.source_type})

        elif action == "play":
            if hasattr(source_manager.current_source, "controller"):
                source_manager.current_source.controller.play()
            return web.json_response({"status": "success"})

        elif action == "pause":
            if hasattr(source_manager.current_source, "controller"):
                source_manager.current_source.controller.pause()
            return web.json_response({"status": "success"})

        elif action == "stop":
            if hasattr(source_manager.current_source, "controller"):
                source_manager.current_source.controller.stop()
            return web.json_response({"status": "success"})

        elif action == "toggle_pause":
            if hasattr(source_manager.current_source, "controller"):
                source_manager.current_source.controller.toggle_pause()
            return web.json_response({"status": "success"})

        elif action == "seek":
            pos = _parse_float(data.get("position"), 0.0)
            if pos is None:
                return web.json_response({"error": "invalid position"}, status=400)
            if hasattr(source_manager.current_source, "controller"):
                source_manager.current_source.controller.seek(pos)
            return web.json_response({"status": "success", "position": pos})

        elif action == "volume":
            vol = _parse_int(data.get("volume"), 100)
            if vol is None:
                return web.json_response({"error": "invalid volume"}, status=400)
            if hasattr(source_manager.current_source, "controller"):
                source_manager.current_source.controller.set_volume(vol)
            return web.json_response({"status": "success", "volume": vol})

        elif action == "next":
            if hasattr(source_manager.current_source, "next"):
                source_manager.current_source.next()
            return web.json_response({"status": "success"})

        elif action == "previous":
            if hasattr(source_manager.current_source, "previous"):
                source_manager.current_source.previous()
            return web.json_response({"status": "success"})

        elif action == "set_limiter":
            enabled = bool(data.get("enabled", True))
            app_state["limiter"].enabled = enabled
            return web.json_response({"status": "success", "limiter_enabled": enabled})

        return web.json_response({"error": f"Unknown action: {action}"}, status=400)

    async def get_clients(request: web.Request) -> web.Response:
        """GET /api/clients - Live client telemetry."""
        sync_coordinator = app_state["sync_coordinator"]
        clients = sync_coordinator.get_clients()
        return web.json_response({"clients": clients})

    async def post_vlc_playlist(request: web.Request) -> web.Response:
        """POST /api/vlc/playlist - Add item or command to VLC playlist."""
        denied = _auth_denied(request)
        if denied:
            return denied
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        cmd = data.get("command", "add")
        vlc_src = app_state["vlc_source"]
        source_manager = app_state["source_manager"]

        if cmd == "add":
            uri = data.get("uri", "")
            title = data.get("title", "")
            if uri:
                source_manager.switch_source("vlc")
                vlc_src.load_media(uri, title, autoplay=True)
                return web.json_response({"status": "success", "playlist": vlc_src.playlist.get_items()})
            return web.json_response({"error": "Missing uri"}, status=400)

        elif cmd == "play_index":
            idx = _parse_int(data.get("index"), 0)
            if idx is None:
                return web.json_response({"error": "invalid index"}, status=400)
            source_manager.switch_source("vlc")
            vlc_src.play_index(idx)
            return web.json_response({"status": "success"})

        elif cmd == "clear":
            vlc_src.playlist.clear()
            return web.json_response({"status": "success"})

        elif cmd == "repeat":
            mode = data.get("mode", "off")
            vlc_src.playlist.repeat_mode = mode
            return web.json_response({"status": "success", "repeat": mode})

        elif cmd == "shuffle":
            shuf = bool(data.get("enabled", False))
            vlc_src.playlist.shuffle = shuf
            return web.json_response({"status": "success", "shuffle": shuf})

        return web.json_response({"error": f"Unknown playlist command: {cmd}"}, status=400)

    async def post_vlc_upload(request: web.Request) -> web.Response:
        """POST /api/vlc/upload - Upload file directly from browser into media staging and play."""
        denied = _auth_denied(request)
        if denied:
            return denied
        reader = await request.multipart()
        field = await reader.next()
        if not field or not field.filename:
            return web.json_response({"error": "No file uploaded"}, status=400)

        filename = os.path.basename(field.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            return web.json_response({"error": f"Unsupported file type: {ext or 'unknown'}"}, status=415)

        try:
            body = await field.read()
        except Exception:
            return web.json_response({"error": "Failed to read upload"}, status=400)

        if len(body) > MAX_UPLOAD_BYTES:
            return web.json_response({"error": "File too large (max 100 MB)"}, status=413)

        media_dir = os.path.abspath("media")
        os.makedirs(media_dir, exist_ok=True)
        dest_path = os.path.join(media_dir, filename)

        with open(dest_path, "wb") as f:
            f.write(body)

        source_manager = app_state["source_manager"]
        vlc_src = app_state["vlc_source"]
        source_manager.switch_source("vlc")
        vlc_src.load_media(dest_path, filename, autoplay=True)
        return web.json_response({"status": "success", "file": filename})

    async def post_vlc_browse(request: web.Request) -> web.Response:
        """POST /api/vlc/browse - Open Windows native file dialog to select local file."""
        denied = _auth_denied(request)
        if denied:
            return denied
        import asyncio
        loop = asyncio.get_event_loop()

        def _open_dialog():
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            selected = filedialog.askopenfilename(
                title="Select Movie / Video / Audio File",
                filetypes=[
                    ("Media Files", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.mp3 *.flac *.wav *.m4a *.aac *.ogg"),
                    ("All Files", "*.*")
                ]
            )
            root.destroy()
            return selected

        selected_path = await loop.run_in_executor(None, _open_dialog)
        if selected_path:
            source_manager = app_state["source_manager"]
            vlc_src = app_state["vlc_source"]
            source_manager.switch_source("vlc")
            vlc_src.load_media(selected_path, os.path.basename(selected_path), autoplay=True)
            return web.json_response({"status": "success", "path": selected_path})
        return web.json_response({"status": "cancelled"})

    async def get_vlc_metadata(request: web.Request) -> web.Response:
        """GET /api/vlc/metadata - Current track metadata."""
        vlc_src = app_state["vlc_source"]
        return web.json_response(vlc_src.metadata.to_dict())

    async def get_sync_report(request: web.Request) -> web.Response:
        """GET /api/sync/report - Master synchronization metrics."""
        sync_coordinator = app_state["sync_coordinator"]
        return web.json_response(sync_coordinator.get_sync_report())

    async def post_test_tone(request: web.Request) -> web.Response:
        """POST /api/test-tone - Change synthetic test signal type."""
        denied = _auth_denied(request)
        if denied:
            return denied
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        sig_type = data.get("signal_type", "sine_1khz")
        freq = _parse_float(data.get("frequency"), 1000.0)
        amp = _parse_float(data.get("amplitude"), 0.5)
        if freq is None or amp is None:
            return web.json_response({"error": "invalid frequency or amplitude"}, status=400)

        test_gen = app_state["test_generator"]
        test_gen.set_signal_type(sig_type, freq, amp)
        return web.json_response({"status": "success", "signal_type": sig_type, "frequency": freq, "amplitude": amp})

    async def get_sdp(request: web.Request) -> web.Response:
        """GET /api/sdp - Session Description Protocol for VLC."""
        from src.transport.sdp_generator import generate_sdp, MULTICAST_GROUP, RTP_DEFAULT_PORT
        audio_format = app_state["audio_format"]
        sdp_content = generate_sdp(host_ip=MULTICAST_GROUP, port=RTP_DEFAULT_PORT, audio_format=audio_format)
        return web.Response(
            text=sdp_content,
            content_type="application/sdp",
            headers={"Content-Disposition": 'attachment; filename="sonicsync_stream.sdp"'}
        )

    async def get_m3u(request: web.Request) -> web.Response:
        """GET /api/stream.m3u - M3U playlist file for VLC."""
        from src.transport.sdp_generator import generate_m3u, MULTICAST_GROUP, RTP_DEFAULT_PORT
        m3u_content = generate_m3u(stream_url_or_ip=MULTICAST_GROUP, port=RTP_DEFAULT_PORT)
        return web.Response(
            text=m3u_content,
            content_type="audio/x-mpegurl",
            headers={"Content-Disposition": 'attachment; filename="sonicsync_stream.m3u"'}
        )

    async def get_qr(request: web.Request) -> web.Response:
        """GET /api/qr - QR Code image for zero-install mobile listening."""
        from src.server.qr import generate_listener_qr_code
        lan_ip = app_state["lan_ip"]
        port = app_state["port"]
        session_manager = app_state.get("session_manager")
        # When PIN mode is on, the QR embeds the bootstrap token so scanning
        # a phone in the room just works without typing the PIN.
        token = app_state.get("bootstrap_token", "") if (session_manager and session_manager.pin_enabled) else ""
        raw_png, data_uri, target_url = generate_listener_qr_code(host_ip=lan_ip, port=port, token=token)

        format_req = request.query.get("format", "png")
        if format_req == "json":
            return web.json_response({"data_uri": data_uri, "target_url": target_url})
        return web.Response(body=raw_png, content_type="image/png")

    return [
        web.get("/api/status", get_status),
        web.post("/api/auth", post_auth),
        web.post("/api/control", post_control),
        web.get("/api/clients", get_clients),
        web.post("/api/vlc/playlist", post_vlc_playlist),
        web.post("/api/vlc/upload", post_vlc_upload),
        web.post("/api/vlc/browse", post_vlc_browse),
        web.get("/api/vlc/metadata", get_vlc_metadata),
        web.get("/api/sync/report", get_sync_report),
        web.post("/api/test-tone", post_test_tone),
        web.get("/api/sdp", get_sdp),
        web.get("/api/stream.m3u", get_m3u),
        web.get("/api/qr", get_qr),
    ]
