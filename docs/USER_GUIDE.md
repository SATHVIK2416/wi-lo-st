# 📖 SonicSync Comprehensive User Guide & Audiophile Handbook

Welcome to **SonicSync**, a high-performance local network wireless audio distribution system designed to achieve bit-exact lossless streaming and sub-millisecond, sample-accurate phase synchronization across multiple receiving devices.

---

## Table of Contents
1. [System Overview & Principles](#1-system-overview--principles)
2. [Audiophile Quality & Formats](#2-audiophile-quality--formats)
3. [Zero-Lag Clock Synchronization Explained](#3-zero-lag-clock-synchronization-explained)
4. [OS Audio Routing & Setup](#4-os-audio-routing--setup)
   - [Windows (WASAPI Loopback)](#windows-wasapi-loopback)
   - [macOS (BlackHole)](#macos-blackhole)
   - [Linux (PipeWire / PulseAudio)](#linux-pipewire--pulseaudio)
5. [Wi-Fi Network Optimization & QoS](#5-wi-fi-network-optimization--qos)
6. [Acoustic Verification & Calibration](#6-acoustic-verification--calibration)
7. [CLI Reference & Advanced Commands](#7-cli-reference--advanced-commands)
8. [Troubleshooting & Diagnostics](#8-troubleshooting--diagnostics)

---

## 1. System Overview & Principles

Traditional wireless audio protocols (Bluetooth SBC/AAC, AirPlay 1, Google Cast) introduce noticeable delays (100ms to 2000ms) or lossy psychoacoustic compression that alters timbre and detail.

SonicSync operates on two core pillars:
1. **Uncompressed Lossless Transmission**: Audio is captured directly at the digital audio interface and packetized without lossy codecs. Every single PCM sample arrives unchanged.
2. **Phase-Locked NTP Clock Synchronization**: Host and clients maintain high-frequency timestamp synchronization (10 Hz ping exchanges). The host measures network propagation delay and assigns precise presentation timestamps ($PTS$). Clients schedule sample playback into an adaptive jitter buffer that phase-locks playback across all physical endpoints.

---

## 2. Audiophile Quality & Formats

SonicSync supports multiple bit-depth and sample-rate configurations:

| Format Code | Resolution | Sample Rate | Dynamic Range | Bitrate (Stereo) | Recommended Use Case |
|---|---|---|---|---|---|
| `int16` | 16-bit Integer | 44.1 / 48 kHz | 96 dB | 1.41 - 1.54 Mbps | Redbook CD quality, gaming, standard movies |
| `int24` | 24-bit Integer | 48 / 96 kHz | 144 dB | 2.30 - 4.61 Mbps | High-Res Audiophile, Studio Masters |
| `int32` | 32-bit Integer | 96 / 192 kHz | 192 dB | 6.14 - 12.28 Mbps | Professional Studio Monitoring, Ultra-Res |
| `float32` | 32-bit Float | 48 / 96 / 192 kHz | >1500 dB | 3.07 - 12.28 Mbps | Digital Audio Workstations (DAW) with headroom |

### FLAC Compression Mode
For bandwidth-constrained Wi-Fi networks, you can enable FLAC compression with `--flac`. This compresses PCM blocks losslessly on the fly (saving ~40-60% network bandwidth) while maintaining 100% bit-for-bit mathematical identity upon decompression.

---

## 3. Zero-Lag Clock Synchronization Explained

### The 4-Timestamp NTP Exchange
Every 100ms, the Host and each connected Receiver execute a precision timestamp exchange:
1. **$t_0$**: Host transmits Ping with local timestamp $t_0$.
2. **$t_1$**: Receiver receives Ping and records local timestamp $t_1$.
3. **$t_2$**: Receiver transmits Pong and records local timestamp $t_2$.
4. **$t_3$**: Host receives Pong and records local timestamp $t_3$.

$$\text{Round Trip Time (RTT)} = (t_3 - t_0) - (t_2 - t_1)$$

$$\text{Clock Offset } \theta = \frac{(t_1 - t_0) + (t_2 - t_3)}{2}$$

$$\text{One-Way Latency } D = \frac{RTT}{2}$$

### Dynamic Multi-Client Latency Coordination
When multiple clients are connected simultaneously (e.g. Living Room, Bedroom, Studio), network conditions may vary. The Host server aggregates latency metrics and calculates the master broadcast presentation delay:

$$D_{\text{target}} = \max_{k} \left( D_{k} + 3 \times \sigma_k \right) + \text{SafetyMargin}$$

Where $\sigma_k$ is the network jitter of client $k$. This delay is embedded into every audio packet header. All receiving devices buffer samples and release them at the exact calculated local millisecond:

$$T_{\text{play, local}} = PTS_{\text{host}} + \theta_{\text{receiver}} + D_{\text{target}}$$

### Phase-Locked Loop (PLL) Drift Correction
Physical crystal oscillators on independent motherboards deviate by approximately 10 to 50 parts per million (ppm). Without compensation, an unclocked receiver would drift by ~1 sample every second, eventually causing buffer underflows or overflows.

SonicSync's `AdaptiveJitterBuffer` measures phase timing error in real time. When drift exceeds 2ms:
- If receiver clock is running **fast** (consuming buffer too quickly): gently inserts 1 linearly interpolated sample into the block.
- If receiver clock is running **slow** (buffer growing): gently deletes 1 sample from the block.

This micro-resampling occurs at sub-audible levels, keeping all endpoints permanently locked in phase without audible clicks or pitch warbles.

---

## 4. OS Audio Routing & Setup

### Windows (WASAPI Loopback)
SonicSync automatically uses Windows WASAPI Loopback to capture the system's active sound card output.
- Run the host:
  ```powershell
  .venv\Scripts\python src\host.py --source loopback
  ```
- To capture a specific output or virtual cable, list available device indices:
  ```powershell
  .venv\Scripts\python -c "import sounddevice as sd; print(sd.query_devices())"
  ```
  Pass the desired index:
  ```powershell
  .venv\Scripts\python src\host.py --source loopback --rate 48000
  ```

### macOS (BlackHole)
1. Install [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole) (`brew install blackhole-2ch`).
2. In macOS Audio MIDI Setup, create a Multi-Output Device containing your speakers and BlackHole.
3. Start SonicSync host pointing to BlackHole:
  ```bash
  python src/host.py --source mic --rate 48000
  ```

### Linux (PipeWire / PulseAudio)
Capture desktop audio monitor sink:
```bash
# List sources
pactl list short sources

# Run host
python src/host.py --source mic --rate 48000
```

---

## 5. Wi-Fi Network Optimization & QoS

To achieve consistent sub-millisecond jitter over Wi-Fi:
1. **Use 5 GHz Wi-Fi Bands**: 5 GHz / 6 GHz bands provide significantly wider bandwidth and avoid 2.4 GHz microwave/Bluetooth interference.
2. **Enable WMM / QoS in Router Settings**:
   - Enable **WMM (Wi-Fi Multimedia)** in your router administration page.
   - SonicSync sets high-priority DSCP / TOS flags (`IPTOS_LOWDELAY = 0x10`) on its UDP audio packets, ensuring low latency queuing across network switches and access points.
3. **Dedicated Subnet**: For performance installations or stage audio, use a dedicated 5 GHz SSID or wired Gigabit Ethernet switches.

---

## 6. Acoustic Verification & Calibration

SonicSync includes built-in test signals specifically created to verify acoustic phase alignment:

### 1. The 1-Second Click Metronome
```bash
python src/host.py --source click_metronome
```
Place two receiver devices with speakers next to each other in the same room. Start receivers on both devices.
- **Listen for a single unified click**: If the synchronization is sample-accurate, both speakers produce a single, sharp acoustic impulse with zero echo or flamming.
- If you hear double clicks, check network jitter or adjust `--buffer-margin 20`.

### 2. Stereo Ping-Pong Sweep
```bash
python src/host.py --source stereo_sweep
```
Verifies channel separation (Left $\rightarrow$ Center $\rightarrow$ Right $\rightarrow$ Left).

### 3. Pure 1 kHz Sine Tone
```bash
python src/host.py --source sine
```
For measuring output THD+N (Total Harmonic Distortion) with a physical audio analyzer or oscilloscope.

---

## 7. CLI Reference & Advanced Commands

### Host Server (`src/host.py`)

| Argument | Description | Default |
|---|---|---|
| `--source` | Audio capture source: `loopback`, `mic`, `sine`, `stereo_sweep`, `click_metronome`, `file` | `loopback` |
| `--file` | Path to audio file when `--source file` is used | `None` |
| `--rate` | Sample rate in Hz: `44100`, `48000`, `96000`, `192000` | `48000` |
| `--channels` | Number of audio channels: `1` (Mono) or `2` (Stereo) | `2` |
| `--format` | Lossless format: `int16`, `int24`, `int32`, `float32` | `int16` |
| `--flac` | Enable lossless FLAC chunk compression | Disabled |
| `--port` | UDP audio broadcast port | `50005` |
| `--control-port` | TCP control and NTP synchronization port | `50006` |
| `--no-gui` | Disable Rich terminal dashboard (for background services) | False |

### Receiver Client (`src/receiver.py`)

| Argument | Description | Default |
|---|---|---|
| `--host` | Host IP address (leave blank for auto-discovery via UDP beacon) | Auto |
| `--port` | UDP audio broadcast port | `50005` |
| `--control-port` | TCP control and NTP synchronization port | `50006` |
| `--device` | Output audio DAC device index | Default OS Output |
| `--buffer-margin`| Safety buffer delay override in milliseconds | Auto |
| `--no-gui` | Disable Rich terminal dashboard | False |

---

## 8. Troubleshooting & Diagnostics

- **Receivers not auto-discovering Host:**
  - Check if Windows Defender Firewall or local OS firewall blocks UDP port `50007` or `50005`.
  - Alternatively, pass host IP directly: `python src/receiver.py --host 192.168.1.X`.
- **Audio Stutters or Buffer Underflows:**
  - Increase safety buffer margin in `config/settings.json` (e.g. change `safety_margin_ms` to `25.0` or pass `--buffer-margin 25`).
- **High Jitter on 2.4 GHz Wi-Fi:**
  - Switch receiver and host to a 5 GHz Wi-Fi band or enable FLAC compression (`--flac`) to reduce network throughput demand.
