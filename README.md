# SonicSync 🎵
**Lossless, Ultra-Low-Latency Multi-Room Wireless Audio Broadcasting**
*VLC-First Integration • Sample-Domain Clock Synchronization • Zero-Install Web Streaming*

---

## ⚡ Quick Start

### 1. Launch Host (Windows / macOS / Linux)
```bash
# 1-Click Launch on Windows:
start_host.bat

# Or run via Python:
python run.py --mode host --source test
```
The Host Dashboard opens automatically in your browser at `http://localhost:8080`.

### 2. Zero-Install Mobile Listening
1. Point your smartphone camera (iPhone / Android) at the **QR Code** displayed on the host dashboard.
2. Tap **"Tap to Listen"** to begin streaming synchronized lossless audio immediately with real-time visualizer and studio acoustic presets.

### 3. VLC Media Player Listening
- **1-Click M3U Stream**: Open `http://<LAN_IP>:8080/api/stream.m3u` in VLC.
- **RTP Direct**: Open network stream `rtp://@239.255.0.1:5004` in VLC.

---

## 🛠️ Architecture Highlights

- **Lossless Ingestion**: Native 32-bit float and 24-bit PCM streaming up to 192 kHz.
- **VLC-First Strategy**: Uses `libVLC` direct audio callbacks to capture decoded audio from local FLAC/WAV/MP3 files, playlists, and network streams without OS loopback latency.
- **NTP Clock Discipline**: 4-timestamp offset and RTT estimation with Median Absolute Deviation (MAD) outlier filtering.
- **Adaptive Jitter Scheduling**: Priority queue playout buffer locked to a deterministic `100.0 ms` presentation delay.
- **Micro-Resampling PLL**: Sub-sample 4-point Hermite cubic interpolation modulates playout rate by $\pm 0.05\%$ max to eliminate quartz crystal oscillator drift without audible pitch shifts.
- **Studio Acoustic DSP**: Includes 4 real-time Web Audio DSP presets:
  - *Cinema & Smooth Vocals* (Default: de-essing notch, high-shelf, bass warmth)
  - *Direct Bit-Exact Flat* (100% uncolored passthrough)
  - *Warm Tube Analog* (Silky high-end roll-off and rich bass body)
  - *Studio Presence* (Crisp acoustic clarity)

---

## 🧪 Automated Test Suite

Run the full automated test suite:
```bash
python -m pytest tests/ -v
```

---

## 📄 License
MIT License.
