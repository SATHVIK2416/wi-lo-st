# 🎵 SonicSync — Audiophile Lossless Network Audio Streamer with Auto Zero-Lag Sync

> **Broadcast high-fidelity lossless audio from one host computer to multiple receiving devices across your local Wi-Fi / Ethernet network with sample-accurate, zero-lag synchronization.**

---

## 🌟 Key Features

1. **Absolute Lossless Audiophile Quality**
   - **Zero compression artifacts**: Streams pure uncompressed PCM or FLAC lossless audio.
   - **Audiophile resolutions**: Supports **16-bit**, **24-bit**, **32-bit**, and **32-bit float** formats up to **192 kHz** sampling rates.
   - **Low Latency Frame Sizes**: Ultra-low chunk block sizes (128 to 512 samples) down to ~2.6ms buffer slices.

2. **Automatic Zero-Lag NTP Synchronization**
   - **4-Timestamp NTP Clock Engine**: Precision sub-millisecond clock offset ($\theta$) and Round-Trip Time ($RTT$) estimation.
   - **Statistical Outlier Rejection**: Rejects transient Wi-Fi jitter spikes and bufferbloat to maintain a rock-solid time base.
   - **Multi-Client Master Coordinator**: Dynamically calculates the optimal global broadcast delay $D_{\text{target}} = \max(RTT_i/2) + JitterMargin$ so all receiving endpoints play the exact same acoustic wave at the exact same physical instant.
   - **Adaptive Phase-Locked Loop (PLL) Jitter Buffer**: Corrects natural crystal clock drift between different sound cards (parts-per-million drift) via sub-perceptual micro-sample stuffing/trimming without audible clicks or pitch distortions.

3. **High-Performance Network Architecture**
   - **UDP Audio Streaming**: Raw low-latency UDP broadcast/multicast audio pipeline with high-priority DSCP QoS flags.
   - **TCP / ZeroMQ Control Plane**: Reliable client discovery, registration, 10Hz NTP sync loops, and live telemetry.
   - **Zero-Config Auto-Discovery**: UDP discovery beacons allow receivers to automatically detect and bind to the host without manual IP entry.

4. **Built-In Precision Test Signal Generator**
   - **Pure Sine Wave (1000 Hz / 440 Hz)**: Perfect harmonic purity for measuring DAC output.
   - **Stereo Ping-Pong Sweep**: Panning tone verifying left/right channel separation.
   - **Click Metronome**: 1 Hz millisecond-sharp pulses for acoustic phase alignment verification across multiple physical speakers in the same room.

5. **Live Terminal Telemetry Dashboard**
   - Real-time display of connected clients, RTT (lag in ms), clock offset, jitter, buffer levels, phase timing error, and stereo RMS/peak VU meters.

---

## 🏗️ Architecture

```
+-------------------------------------------------------------------------------+
|                                  HOST SERVER                                  |
|                                                                               |
|  +-------------------+      +---------------------+      +-----------------+  |
|  | Audio Capture     | ---> | PCM Packetizer      | ---> | UDP Broadcast / | ===> (Lossless Audio)
|  | (WASAPI/Line/Gen) |      | (Header + Host PTS) |      | Multicast Out   |  |
|  +-------------------+      +---------------------+      +-----------------+  |
|                                                              |                |
|  +-----------------------------------------------------------+                |
|  | Master Sync Coordinator (NTP Ping/Pong Engine)                             |
|  | - Measures RTT & clock offset for every connected client                   |
|  | - Calculates global target playout delay: D_target = max(RTT_i/2) + margin  |
|  | - Control Plane (TCP / ZeroMQ) for discovery, sync, and telemetry          |
|  +----------------------------------------------------------------------------+
+-------------------------------------------------------------------------------+
                                        | (NTP Sync & Telemetry)
                                        v
+-------------------------------------------------------------------------------+
|                               RECEIVER CLIENT                                 |
|                                                                               |
|  +-------------------+      +---------------------+      +-----------------+  |
|  | UDP Audio Stream  | ---> | Adaptive Jitter     | ---> | Lossless Audio  | ===> (DAC / Speakers)
|  | Receiver          |      | Buffer & Scheduler  |      | Output Callback |  |
|  +-------------------+      +---------------------+      +-----------------+  |
|                                        ^                                      |
|  +-------------------------------------+                                      |
|  | Local Clock Synchronizer & PLL                                             |
|  | - Calculates Offset (theta) and RTT to Host master clock                   |
|  | - Schedules sample playout: T_play = Host_PTS + theta + D_target           |
|  | - Continuous micro-drift phase-locked loop (PLL) / resampler               |
|  +----------------------------------------------------------------------------+
+-------------------------------------------------------------------------------+
```

---

## 📁 Repository Structure

```
.
├── README.md                 # Project overview and documentation
├── requirements.txt          # Python dependencies
├── config/
│   └── settings.json        # Stream and network configuration
├── src/
│   ├── audio.py             # Audio capture, playback, ring buffer, format conversions
│   ├── sync.py              # NTP clock sync, jitter buffer, PLL drift compensator
│   ├── host.py              # Host broadcasting server and monitoring dashboard
│   └── receiver.py          # Receiver client application
├── tests/
│   └── test_sonicsync.py    # Automated test suite (unit + E2E integration)
└── docs/
    └── USER_GUIDE.md        # Detailed user setup, audiophile and network guide
```

---

## 🚀 Quick Start

### 1. Installation & Environment Setup

```bash
# Clone repository
git clone https://github.com/SATHVIK2416/wi-lo-st.git
cd wi-lo-st

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

### 2. Running the Host Server

#### Broadcast Windows System Audio (Loopback)
```bash
python src/host.py --source loopback --rate 48000 --format int16
```

#### Broadcast High-Res 96kHz 24-bit Audio
```bash
python src/host.py --source loopback --rate 96000 --format int24
```

#### Broadcast Built-in Click Metronome (for Phase Sync Verification)
```bash
python src/host.py --source click_metronome
```

#### Broadcast a FLAC/WAV Audio File
```bash
python src/host.py --source file --file "path/to/song.flac"
```

---

### 3. Running the Receiver Client

#### Auto-Discovery Mode (Recommended)
Automatically searches the local network for the active SonicSync Host:
```bash
python src/receiver.py
```

#### Direct IP Connection
```bash
python src/receiver.py --host 192.168.1.100
```

---

## ⚙️ Configuration (`config/settings.json`)

```json
{
  "audio": {
    "sample_rate": 48000,
    "channels": 2,
    "format": "int16",
    "block_size": 256,
    "compression": "none",
    "input_device": null,
    "output_device": null,
    "source": "loopback"
  },
  "network": {
    "audio_port": 50005,
    "control_port": 50006,
    "discovery_port": 50007,
    "broadcast_ip": "255.255.255.255",
    "multicast_ip": "239.255.0.1",
    "mode": "broadcast"
  },
  "sync": {
    "ntp_interval_seconds": 0.1,
    "safety_margin_ms": 15.0,
    "drift_correction_threshold_ms": 1.5,
    "filter_window_size": 25,
    "outlier_rejection_std": 2.0
  }
}
```

---

## 🧪 Running Automated Tests

Run the complete pytest test suite:
```bash
pytest tests/test_sonicsync.py -v
```

---

## 📜 License

MIT License. Designed for audiophiles, multi-room audio, and synchronized stage setups.
