# SonicSync Test & Verification Guide

## Automated Test Suite

Run the complete test suite with pytest:
```bash
python -m pytest tests/ -v
```

### Test Categories
- **Unit Tests (`tests/unit/`)**:
  - `test_audio_format.py`: Validates byte conversion routines, packing, unpacking, scaling.
  - `test_ring_buffer.py`: Tests thread safety, overrun/underrun metrics, wrap-around reading/writing.
  - `test_limiter.py`: Verifies soft-knee compression curves, lookahead delay, and peak limiting below 0 dBFS.
  - `test_dither.py`: Tests TPDF probability distribution and noise floor flatness.
  - `test_packet.py`: Tests 42-byte binary header serialization, deserialization, and CRC32 verification.
  - `test_clock_sync.py`: Tests 4-timestamp NTP math and Median Absolute Deviation (MAD) outlier rejection.
  - `test_rtp_rtcp.py`: Verifies RFC 3550 RTP/RTCP serialization and byte offsets.
  - `test_sdp.py`: Verifies SDP and M3U file generation.
  - `test_pll.py`: Verifies PI controller response and rate limits ($\pm 0.05\%$).
- **Integration Tests (`tests/integration/`)**:
  - `test_audio_pipeline.py`: Full audio flow from test generator -> ring buffer -> limiter -> packetizer -> deserializer.
  - `test_web_server_api.py`: Tests REST APIs (`/api/status`, `/api/control`, `/api/qr`, `/api/sdp`, `/api/stream.m3u`).
  - `test_websocket_stream.py`: Tests WebSocket binary audio streaming and NTP ping/pong handling.
  - `test_client_lifecycle.py`: Tests client connect, telemetry report, timeout pruning.
- **VLC Tests (`tests/vlc/`)**:
  - `test_vlc_source.py`: Tests VLC playlist queue, shuffle/repeat, metadata extraction, controller state.
  - `test_vlc_sidecar.py`: Tests sidecar RC command generation and rate calculation.
- **Network Impairment Tests (`tests/network/`)**:
  - `test_network_impairment.py`: Simulates packet loss, high jitter, and burst dropouts to verify PLL buffer recovery.
- **Acoustic Synchronization Tests (`tests/acoustic/`)**:
  - `test_metronome_sync.py`: Simulates metronome impulse broadcasts and calculates inter-device cross-correlation offset.
