# SonicSync 🎵
**Lossless, Ultra-Low-Latency Multi-Room Wireless Audio Broadcasting**
*VLC-First Integration • Sample-Domain Clock Synchronization • Zero-Install Web Streaming*

---

## ⚡ Quick Start

### 1. Launch Host (Windows / macOS / Linux)
```bash
# 1-Click Launch on Windows:
start_host.bat

# Or run via Python (a virtual environment is recommended):
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Linux/macOS: .venv/bin/pip ...
.venv\Scripts\python run.py --mode host --source test
```
The Host Dashboard opens automatically in your browser at `http://localhost:8080`.

### 2. Zero-Install Mobile Listening
1. Point your smartphone camera (iPhone / Android) at the **QR Code** displayed on the host dashboard.
2. Tap **"Tap to Listen"** to begin streaming synchronized lossless audio with a real-time visualizer, live sync telemetry, and studio acoustic presets.

### 3. VLC Media Player Listening
- **1-Click M3U Stream**: Open `http://<LAN_IP>:8080/api/stream.m3u` in VLC.
- **RTP Direct**: Open network stream `rtp://@239.255.0.1:5006` in VLC.

### Optional: PIN-protected mode
```bash
python run.py --mode host --pin 4821
```
When a PIN is set, control APIs and the WebSocket require a session token.
The QR code embeds a bootstrap token so scanning just works; manual visitors
get a PIN prompt and exchange it via `POST /api/auth`.

---

## 🛠️ Architecture Highlights

- **Lossless Ingestion**: Native 32-bit float and 24-bit PCM streaming up to 192 kHz.
- **VLC-First Strategy**: Uses `libVLC` direct audio callbacks (`amem`) to capture decoded audio from local FLAC/WAV/MP3 files, playlists, and network streams without OS loopback latency — with an automatic failover watchdog that switches to OS loopback capture if VLC callbacks stall.
- **NTP Clock Discipline**: 4-timestamp offset/RTT estimation with MAD outlier rejection, bogus-sample rejection, and confidence-gated locking; drift estimated in ppm via linear regression.
- **Cross-Machine Sync**: The native receiver runs the NTP exchange over the host's WebSocket control channel and schedules playout as `T_play = PTS_host + θ_client + D_target`.
- **Adaptive Jitter Scheduling**: Priority-queue playout buffer measuring true *time-to-underrun*, locked to a deterministic `100.0 ms` presentation delay, with hard-reset resync and overflow bounding.
- **Micro-Resampling PLL**: Sub-sample 4-point Hermite cubic interpolation with continuous phase carry modulates playout rate by ±0.05% max — no pitch shifts, no chunk-boundary clicks.
- **AudioWorklet Web Player**: The mobile listener renders from a continuous ring buffer on the audio thread (not per-packet buffer sources), auto-resamples between stream and device rates (e.g., 48 kHz stream → 44.1 kHz iPhone DAC), tracks packet loss/duplicates by sequence number, and re-primes cleanly after underruns.
- **Per-Client WebSocket Fan-out**: Each listener owns an outbound queue drained by its own task, so one slow phone can never stall the 10 ms broadcast cadence for everyone else.
- **Transport Separation**: SonicSync binary protocol (UDP 5004) and VLC-compatible RTP/RTCP (UDP 5006/5007) run on dedicated ports.
- **Studio Acoustic DSP**: Four real-time Web Audio presets:
  - *Cinema & Smooth Vocals* (Default: de-essing notch, high-shelf, bass warmth)
  - *Direct Bit-Exact Flat* (EQ + compressor fully bypassed)
  - *Warm Tube Analog* (Silky high-end roll-off and rich bass body)
  - *Studio Presence* (Crisp acoustic clarity)

## 🖥️ Host Dashboard

Five tabs, all wired to live backend endpoints:

| Tab | Features |
|---|---|
| **Status** | Stream health, QR + copyable listen URL, .m3u/.sdp downloads, broadcast start/stop |
| **Media** | Full VLC transport controls, seek bar, volume, playlist management, file upload & host-side browse |
| **Clients** | Per-listener telemetry table (buffer, offset, RTT, drift, loss, underruns) with stale/unlocked highlighting |
| **Settings** | Source selection (test / loopback / VLC), safety limiter toggle, test-tone generator |
| **Diagnostics** | Aggregate sync metrics, buffer-depth history chart, control-channel RTT |

---

## 🔌 Port Reference

| Port | Protocol | Purpose |
|---|---|---|
| 8080 | HTTP/WebSocket | Dashboard, listener page, REST API, NTP control channel |
| 5004 | UDP multicast | SonicSync binary audio protocol (native receivers) |
| 5006 | UDP multicast | RTP audio (VLC listeners) |
| 5007 | UDP multicast | RTCP sender reports |

---

## 🧪 Automated Test Suite

Run the full automated test suite:
```bash
python -m pytest tests/ -v
```

---

## 📄 License
MIT License.
