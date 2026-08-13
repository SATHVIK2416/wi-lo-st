# SonicSync — Complete Architecture & Planning Document

**Project:** SonicSync  
**Focus:** Lossless, ultra-low-latency, multi-room wireless audio broadcasting  
**Priority:** VLC-first integration, sample-domain synchronization, zero-install web listening  
**Target Presentation Delay:** `100.0 ms`  
**Document Type:** Consolidated architecture, strategy, and implementation plan

---

## Table of Contents

1. [Original SonicSync Comprehensive Architecture & Technical Summary](#1-original-sonicsync-comprehensive-architecture--technical-summary)
2. [VLC-First Strategic Priority](#2-vlc-first-strategic-priority)
3. [Final Architecture Plan](#3-final-architecture-plan)
4. [Supported System Modes](#4-supported-system-modes)
5. [High-Level Architecture](#5-high-level-architecture)
6. [Core Architectural Layers](#6-core-architectural-layers)
7. [Clock Synchronization Architecture](#7-clock-synchronization-architecture)
8. [Transport Architecture](#8-transport-architecture)
9. [VLC Integration Strategy](#9-vlc-integration-strategy)
10. [Client Architecture](#10-client-architecture)
11. [Final Wire Protocol Strategy](#11-final-wire-protocol-strategy)
12. [Control Plane Architecture](#12-control-plane-architecture)
13. [Host Dashboard Plan](#13-host-dashboard-plan)
14. [Security Plan](#14-security-plan)
15. [Audio Fidelity Plan](#15-audio-fidelity-plan)
16. [Synchronization Guarantee Matrix](#16-synchronization-guarantee-matrix)
17. [Repository Structure](#17-repository-structure)
18. [Implementation Roadmap](#18-implementation-roadmap)
19. [Test Plan](#19-test-plan)
20. [Risk Register](#20-risk-register)
21. [Release Acceptance Criteria](#21-release-acceptance-criteria)
22. [Final Recommended Architecture Statement](#22-final-recommended-architecture-statement)

---

# 1. Original SonicSync Comprehensive Architecture & Technical Summary

## 🎵 SonicSync — Comprehensive Architecture & Technical Summary

**Lossless, Ultra-Low Latency Multi-Room Wireless Audio Broadcasting with Sample-Accurate Clock Synchronization & Zero-Install Web Streaming.**

---

## 📌 1.1 Executive Summary

SonicSync is an audiophile-grade wireless audio distribution platform designed to broadcast high-fidelity, lossless audio from a host computer — Windows, macOS, or Linux — to multiple listening devices across a local Wi-Fi or Ethernet network.

The system provides:

### Absolute Lossless Audio Fidelity

Native 32-bit float and 24-bit/16-bit uncompressed PCM streaming up to 192 kHz sample rates with zero compression artifacts.

Target metrics:

- Signal-to-Noise Ratio: `SNR > 120 dB`
- Total Harmonic Distortion: `THD < 0.0001%`
- Flat frequency response target: `±0.001 dB`, 20 Hz–20,000 Hz

### Deterministic Zero-Lag Synchronization

Uses 4-timestamp NTP clock estimation:

\[
t_0, t_1, t_2, t_3
\]

Combined with an Adaptive Phase-Locked Loop PLL jitter buffer that locks all connected devices to a constant:

```text
100.0 ms presentation delay
```

### Zero-Install Mobile Web Audio Player

Mobile listeners on:

- iPhone Safari
- Android Chrome
- macOS Safari/Chrome
- Windows Chrome/Edge/Firefox

can scan a QR code displayed on the host dashboard and listen in real time via the Web Audio API without installing any apps.

### Hardware Drift Immunity

Continuous sub-sample Hermite micro-resampling corrects natural hardware quartz crystal oscillator variations, typically ppm-level drift, without pitch changes or audible clicks.

---

## 🏗️ 1.2 High-Level System Architecture

```text
+---------------------------------------------------------------------------------------------------------+
|                                              HOST SYSTEM                                                |
|                                                                                                         |
|  [Audio Source]                                                                                         |
|   ├── Windows WASAPI Loopback (soundcard / COM MediaFoundation)                                         |
|   ├── Microphone / Line-In (sounddevice)                                                                |
|   └── Precision Test Generator (1kHz Sine / Metronome / Pink Noise)                                     |
|           │                                                                                             |
|           ▼                                                                                             |
|  [Audio Engine & Ingestion (src/audio.py)]                                                              |
|   ├── RingBuffer (FIFO Thread-Safe Circular Buffer)                                                     |
|   ├── Studio Soft-Knee Limiter (Anti-Clipping & Dialogue Protection)                                    |
|   └── AudioPacket Wire Serialization (42-Byte Binary Header + Host PTS + CRC32)                         |
|           │                                                                                             |
|           ├─────────────────────────────────────────┬──────────────────────────────────────────┐        |
|           ▼                                         ▼                                          ▼        |
|  [UDP Audio Broadcaster]                  [WebSocket Stream Broadcaster]             [NTP Control Plane] |
|   ├── Multicast (239.255.0.1)              ├── aiohttp Web Server (Port 8080)         ├── 10 Hz Ping/   |
|   └── Subnet Broadcast (255.255.255.255)   ├── TCP_NODELAY Zero-Buffer Sockets            Pong Loops    |
|                                            └── Dynamic QR Code Generator (/api/qr)    └── Master Delay  |
|                                                                                           Coordinator   |
+---------------------------------------------------------------------------------------------------------+
                                    │ (UDP Audio Stream)         │ (WebSocket Binary Audio & NTP)
                                    ▼                            ▼
+--------------------------------------------------+  +---------------------------------------------------+
|             NATIVE RECEIVER CLIENT               |  |             MOBILE / WEB AUDIO LISTENER           |
|                (src/receiver.py)                 |  |                  (web/listen.html)                |
|                                                  |  |                                                   |
|  1. UDP Stream Ingestion & CRC32 Validation      |  |  1. WebSocket Direct Float32 Frame Decoder        |
|  2. NTP Clock Synchronizer (t0, t1, t2, t3)      |  |  2. Continuous Circular Sample Queue (4s Ring)    |
|  3. Adaptive Jitter Buffer & Playout Priority Q  |  |  3. Sub-Sample Hermite PLL Resampler              |
|  4. Hardware DAC Output Callback (PortAudio)     |  |  4. DSP Equalizer & De-Esser Chain                |
|  5. Micro-Sample Stuffing/Trimming PLL Engine    |  |  5. Studio Dynamics Compressor (Peak Limiter)     |
|                                                  |  |  6. Web Audio API AudioContext Destination (DAC)  |
+--------------------------------------------------+  +---------------------------------------------------+
```

---

## 🧩 1.3 Core Subsystems & Components

### 1.3.1 Lossless Audio Engine — `src/audio.py`

#### AudioFormat

Configures:

- Sample rates:
  - 44.1 kHz
  - 48 kHz
  - 96 kHz
  - 192 kHz
- Channel counts:
  - Mono
  - Stereo
- Bit depths:
  - `int16`
  - `int24`
  - `int32`
  - `float32`

#### AudioCapture

##### WASAPI Loopback

Native Windows MediaFoundation loopback recorder via COM multi-threading:

```python
ctypes.windll.ole32.CoInitialize
```

Captures bit-exact digital audio playing through PC speakers/headphones.

##### Synthetic Generator

Provides:

- Pure harmonic sine
- Stereo ping-pong sweeps
- 1 Hz millisecond-sharp click metronomes for acoustic phase calibration

#### soft_limit

Studio-grade soft-knee peak compressor preventing digital inter-sample clipping on loud dialogue or movie explosions.

#### pcm_to_bytes & bytes_to_pcm

Memory-mapped binary serializers with Triangular Probability Density Function TPDF dithering for integer formats.

---

### 1.3.2 Clock Synchronization & Jitter Scheduler — `src/sync.py`

#### ClockSyncFilter

Implements 4-timestamp NTP clock offset and Round-Trip Time estimation:

\[
\theta = \frac{(t_1 - t_0) + (t_2 - t_3)}{2}
\]

\[
RTT = (t_3 - t_0) - (t_2 - t_1)
\]

Includes standard deviation outlier filtering to reject Wi-Fi latency spikes and bufferbloat.

#### MasterSyncCoordinator

Aggregates network statistics across all connected endpoints and anchors the global target playout delay:

\[
D_{\text{target}} = 100.0 \text{ ms}
\]

#### AdaptiveJitterBuffer

Priority-queue timestamp scheduler that releases packets when:

\[
T_{\text{play}} = PTS_{\text{host}} + \theta_{\text{client}} + D_{\text{target}}
\]

---

### 1.3.3 Integrated Web Server & Control Plane — `src/web_server.py`

Built on asynchronous Python `aiohttp`.

Features:

- Generates high-resolution PNG QR codes pointing directly to:

```text
http://<LAN_IP>:8080/listen
```

- Streams binary audio frames to WebSocket clients with `TCP_NODELAY` socket optimizations.
- Hosts REST APIs:

```text
GET  /api/status
POST /api/control
GET  /api/qr
```

---

### 1.3.4 Web Audio Listener Client — `web/listen.html`

#### Zero-Install Client

Runs natively inside:

- Mobile Safari
- Chrome
- Edge
- Firefox

#### Continuous Circular Sample Streamer

Uses a continuous ring queue with Hermite sub-sample interpolation to eliminate packet boundary clicks.

#### Phase-Locked Loop PLL Micro-Resampler

Modulates playback speed by:

\[
\pm 0.05\%
\]

if the client buffer drifts, maintaining the 100 ms anchor without dropping frames.

#### Acoustic DSP Chain

##### Cinema & Smooth Vocals — Default

Dedicated:

- de-essing notch: `-2.5 dB @ 5.5 kHz`
- smooth high-shelf: `-1.5 dB @ 12 kHz`
- grounded low-end warmth: `+1.8 dB @ 85 Hz`

##### Direct Bit-Exact Flat

100% uncolored studio master passthrough.

##### Warm Tube Analog

Silky smooth vintage high-end roll-off and rich bass body.

##### Studio Presence

Crisp acoustic speech clarity.

#### DynamicsCompressorNode

Transparent lookahead limiter preventing digital clipping.

---

## 📦 1.4 Binary Wire Protocol Specification

Every audio packet transmitted across UDP and WebSocket starts with a compact 42-byte binary header.

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       Magic Header ('S','O','N','I') [4 Bytes: 0x534F4E49]    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|  Ver (0x01)   | PktType(0x01) | Format (0x04) | Channels(0x02)|
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     Sample Rate (uint32_t)                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                   Sequence Number (uint32_t)                  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|             Presentation Timestamp (PTS: double 64-bit)       |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|              Target Playout Delay (double 64-bit)             |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|      Frame Count (uint16_t)   |    Payload Length (uint32_t)  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                   CRC32 Checksum (uint32_t)                   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       AUDIO PAYLOAD DATA                      |
|                  (Raw Float32 / PCM Samples)                  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

---

## 🛠️ 1.5 Key Engineering Challenges Solved

| Challenge | Root Cause | Engineering Solution |
|---|---|---|
| Windows Loopback Capture | Standard PortAudio APIs reject output endpoints as having 0 input channels. | Integrated Windows MediaFoundation WASAPI Loopback with explicit COM thread initialization. |
| Sharp Highs & Mushy Lows | Individual `AudioBufferSourceNode` instances created per packet generated micro-gaps and phase discontinuities at block edges. | Continuous circular sample queue with sub-sample Hermite interpolation for seamless sample-to-sample phase continuity. |
| Inconsistency & Piercing Vocals | TCP/Wi-Fi jitter caused brief buffer starvation, creating square-wave dropouts that boosted speech sibilance around 4–6 kHz. | Adaptive PLL micro-resampler, de-essing filter, and `TCP_NODELAY`. |
| Digital Inter-Sample Clipping | High-volume movie explosions and dialogue peaked above 0 dBFS on consumer phone DACs. | Dual-stage studio peak limiting: host-side `soft_limit` plus Web `DynamicsCompressorNode`. |
| Crystal Oscillator Drift | Physical quartz crystal differences between devices, around 2–5 samples/sec drift. | Dynamic PLL buffer water-mark tracking dynamically micro-adjusts playout speed without pitch alteration. |

---

## 🧪 1.6 Test Suite & Quality Verification

The project includes an automated test suite with:

```text
20 / 20 passing unit & integration tests
```

Run with:

```bash
.venv\Scripts\python -m pytest tests/test_sonicsync.py -v
```

### Verified Metrics

#### Audio Fidelity

- SNR > 120 dB
- THD < 0.0001%
- Flat Frequency Response: `±0.001 dB`, 20 Hz–20,000 Hz

#### Loopback Capture

Real-time WASAPI Windows system audio loopback verified.

#### Synchronization

Deterministic 100.0 ms constant sync delay lock verified.

#### Browser Compatibility

Live Chrome DevTools verification confirmed 100% buffer lock on mobile Web Audio clients.

---

## 🚀 1.7 Quick Start Guide

### 1-Click Launch — Host

On Windows:

Double-click:

```text
start_host.bat
```

or run:

```bash
python run.py
```

This:

- Starts the audio capture engine.
- Starts the web server and generates the QR code.
- Automatically opens the Host Dashboard at:

```text
http://localhost:8080
```

### Listen In — Zero Install

1. Point any smartphone camera, iPhone or Android, at the QR code on the Host Dashboard.
2. Tap:

```text
▶ Tap to Listen
```

to begin streaming synchronized lossless audio immediately.

---

# 2. VLC-First Strategic Priority

## 2.1 Priority Statement

The final direction of SonicSync prioritizes **VLC Media Player** as the primary media engine and preferred desktop listening surface.

VLC is treated as top priority because it provides:

- Excellent codec support
- Playlist management
- Cross-platform desktop support
- Familiar audiophile/media-user experience
- Network streaming capabilities
- Command-line and API control options
- Strong desktop/living-room PC usability

However, VLC alone is not sufficient for sample-accurate multi-room synchronization. Therefore, SonicSync remains responsible for the synchronization layer.

---

## 2.2 Core VLC Strategy

The final strategy is:

> VLC is the preferred media engine and desktop listening surface, but SonicSync remains the authoritative clock, buffer, and synchronization layer.

This means:

1. VLC can act as the primary source player.
2. SonicSync captures or receives decoded audio from VLC.
3. SonicSync applies clock synchronization, buffering, drift correction, and multi-room alignment.
4. VLC can also act as a listener/client through RTP/RTCP or assisted sidecar control.
5. Web Audio remains the zero-install mobile fallback.
6. Native SonicSync receivers remain the reference implementation for highest precision.

---

## 2.3 Why VLC Cannot Be the Only Sync Engine

VLC is designed primarily for robust media playback, not deterministic multi-room sample synchronization.

VLC commonly uses:

- Large network caching
- Internal jitter buffering
- OS-level audio scheduling
- Device-specific audio output latency
- No guaranteed external presentation-time alignment

Therefore, if VLC is used without SonicSync synchronization control, multiple VLC clients may drift or buffer differently.

The final architecture avoids this by using SonicSync to:

- Estimate host/client clock offset
- Track drift in ppm
- Maintain a 100 ms target buffer watermark
- Apply micro-rate correction or sidecar-assisted control
- Monitor underruns, overruns, and network health

---

# 3. Final Architecture Plan

## 3.1 Executive Summary

SonicSync becomes a hybrid VLC-first multi-room audio platform.

It combines:

1. **VLC media playback**
2. **SonicSync clock synchronization**
3. **Lossless PCM/Float32 transport**
4. **RTP/RTCP streaming for VLC compatibility**
5. **WebSocket zero-install web listening**
6. **Native high-precision receivers**
7. **Host dashboard control**

The final product can support:

- VLC as source
- System audio capture
- Test generator
- VLC desktop listening
- Native receiver listening
- Mobile web listening
- Multi-room synchronization
- Audiophile measurement and calibration

---

## 3.2 Primary Product Goal

> A user can play any local file, network stream, disc, playlist, or system audio source from a SonicSync host, optionally through VLC, and broadcast that audio to multiple rooms with stable 100 ms synchronized playback. Listeners can use VLC, a native SonicSync receiver, or a zero-install mobile web player.

---

## 3.3 Core Product Principles

### 3.3.1 VLC First

VLC is the preferred source engine and desktop listening experience.

### 3.3.2 SonicSync Controls Time

SonicSync remains responsible for:

- Master clock
- Presentation timestamps
- Offset estimation
- Drift correction
- Jitter buffering
- Target delay enforcement

### 3.3.3 Lossless Transport

The main transport remains uncompressed PCM or Float32 wherever possible.

Lossy compression is only a fallback for constrained environments.

### 3.3.4 Deterministic Latency

The system prioritizes stable 100 ms presentation delay over the lowest possible instantaneous latency.

### 3.3.5 Multi-Path Delivery

SonicSync supports:

- VLC/RTP path
- Native UDP binary path
- WebSocket web path

This ensures compatibility across VLC, native receivers, and browsers.

---

# 4. Supported System Modes

| Mode | Description | Priority | Sync Guarantee | Best Use |
|---|---|---:|---|---|
| VLC Source Mode | VLC plays media; SonicSync captures decoded audio and broadcasts it | High | High | Main media server mode |
| System Audio Capture Mode | Captures WASAPI / CoreAudio / PulseAudio / PipeWire loopback | Medium | High | Movie/game/system audio |
| VLC Direct Listener Mode | VLC opens SonicSync RTP/network stream directly | High | Medium | Simple desktop listening |
| VLC Sync Sidecar Mode | VLC is launched/controlled by SonicSync to maintain target delay | High | Medium-High | Multi-room VLC listening |
| Web Listener Mode | Phone/browser scans QR and listens via Web Audio API | High | Medium-High | Zero-install mobile listening |
| Native Receiver Mode | SonicSync receiver with PortAudio and custom PLL | Reference | Highest | Critical listening / DAC endpoints |

---

# 5. High-Level Architecture

```text
+--------------------------------------------------------------------------------------------------+
|                                        SONICSYNC HOST                                            |
|                                                                                                  |
|  +----------------------------------+                                                            |
|  |          SOURCE LAYER            |                                                            |
|  |                                  |                                                            |
|  | 1. VLC Media Engine              |                                                            |
|  |    - Local FLAC/WAV/MP3/M4A      |                                                            |
|  |    - Network streams             |                                                            |
|  |    - Discs / playlists           |                                                            |
|  |    - Controlled via libVLC/RC    |                                                            |
|  |                                  |                                                            |
|  | 2. System Audio Loopback         |                                                            |
|  |    - WASAPI / CoreAudio          |                                                            |
|  |    - PulseAudio / PipeWire       |                                                            |
|  |                                  |                                                            |
|  | 3. Test Generator                |                                                            |
|  |    - 1 kHz sine                  |                                                            |
|  |    - Pink noise                  |                                                            |
|  |    - Metronome click             |                                                            |
|  +----------------+-----------------+                                                            |
|                   |                                                                              |
|                   v                                                                              |
|  +----------------------------------+                                                            |
|  |       SONICSYNC AUDIO CORE       |                                                            |
|  |                                  |                                                            |
|  | - Thread-safe RingBuffer         |                                                            |
|  | - Sample format conversion       |                                                            |
|  | - Soft-knee limiter              |                                                            |
|  | - TPDF dither for integer PCM    |                                                            |
|  | - Host master clock              |                                                            |
|  | - PTS generation                 |                                                            |
|  +----------------+-----------------+                                                            |
|                   |                                                                              |
|                   v                                                                              |
|  +----------------------------------+                                                            |
|  |       TRANSPORT ADAPTERS         |                                                            |
|  |                                  |                                                            |
|  | - RTP/RTCP Adapter for VLC       |                                                            |
|  | - SonicSync UDP Binary Adapter   |                                                            |
|  | - WebSocket Adapter for web      |                                                            |
|  | - Control/Telemetry Channel      |                                                            |
|  +-----+----------------+------+----+                                                            |
|        |                |      |                                                                 |
+--------|----------------|------|-----------------------------------------------------------------+
         |                |      |
         v                v      v
+----------------+  +----------------+  +------------------+
| VLC LISTENER   |  | NATIVE         |  | WEB LISTENER     |
|                |  | RECEIVER       |  |                  |
| - VLC Direct   |  |                |  | - QR code access |
| - VLC + Sync   |  | - SonicSync    |  | - WebSocket      |
|   Sidecar      |  |   PLL engine   |  | - AudioWorklet   |
| - RTP/RTCP     |  | - PortAudio    |  | - Hermite PLL    |
| - SDP/M3U      |  | - DAC output   |  | - DSP presets    |
+----------------+  +----------------+  +------------------+
```

---

# 6. Core Architectural Layers

## 6.1 Source Layer

The source layer provides raw audio to the SonicSync core.

### Primary Source: VLC Media Engine

VLC becomes the primary source engine for local media and playlists.

Capabilities:

- Play local audio files:
  - FLAC
  - WAV
  - MP3
  - M4A
  - OGG
  - Opus
  - AAC
  - ALAC
- Play network streams.
- Play discs and playlists.
- Provide transport controls:
  - play
  - pause
  - stop
  - next
  - previous
  - seek
  - volume
- Expose metadata to the SonicSync dashboard.

### Implementation Options

#### Preferred: `python-vlc` / libVLC decoded audio callback

- VLC decodes media.
- Decoded PCM/Float32 samples are passed directly to SonicSync RingBuffer.
- Avoids OS loopback latency.
- Best for bit-exact pipeline control.

#### Fallback: VLC output to loopback capture

- VLC plays to a system audio device or virtual audio device.
- SonicSync captures using WASAPI loopback, PulseAudio monitor, or PipeWire monitor.
- Easier to implement.
- Slightly more dependent on OS audio stack.

---

## 6.2 Secondary Source: System Audio Loopback

Retained from the original SonicSync design.

Use cases:

- Movie audio
- Game audio
- Browser audio
- Music players other than VLC
- Conference calls
- System-wide sound

Platform support:

- Windows: WASAPI loopback / MediaFoundation
- macOS: CoreAudio aggregate device or virtual loopback
- Linux: PulseAudio monitor or PipeWire monitor

---

## 6.3 Tertiary Source: Test Generator

Used for calibration and testing.

Signals:

- 1 kHz sine
- Pink noise
- Stereo sweep
- Metronome click
- Millisecond-sharp impulse

Purpose:

- Acoustic synchronization verification
- Buffer calibration
- THD/SNR measurement
- Inter-room alignment testing

---

## 6.4 SonicSync Audio Core

The SonicSync Audio Core remains the central audio processing engine.

### Responsibilities

- Receive decoded audio from source layer.
- Maintain continuous lock-free circular buffer.
- Apply safety limiting.
- Generate presentation timestamps.
- Prepare packets for transport adapters.
- Maintain host master clock.

### Components

#### AudioFormat

Supports:

- Sample rates:
  - 44.1 kHz
  - 48 kHz
  - 96 kHz
  - 192 kHz
- Channels:
  - mono
  - stereo
- Bit depths:
  - int16
  - int24
  - int32
  - float32

Recommended default:

```text
48 kHz / 24-bit PCM / stereo
```

Expert modes:

```text
96 kHz / 24-bit PCM
192 kHz / 24-bit PCM
192 kHz / Float32
```

Rationale:

- 48 kHz / 24-bit provides excellent fidelity and lower bandwidth/CPU usage.
- Higher rates are useful for audiophile testing but can stress Wi-Fi and CPU.

#### RingBuffer

Requirements:

- Thread-safe FIFO
- Lock-free or low-lock design
- No allocations during real-time audio path
- Capacity at least 2 seconds of audio
- Overrun and underrun counters

#### Soft-Knee Limiter

Purpose:

- Prevent digital clipping
- Protect mobile DACs
- Handle sudden loud movie effects
- Maintain transparent dynamics

Characteristics:

- Soft-knee compression
- Fast attack
- Smooth release
- No harsh pumping
- Optional bypass for bit-exact flat mode

#### Presentation Timestamp Generator

Each audio frame receives a host presentation timestamp:

```text
PTS_host = host_master_clock_time
```

The client playout time is calculated as:

\[
T_{\text{play}} = PTS_{\text{host}} + \theta_{\text{client}} + D_{\text{target}}
\]

Where:

- `PTS_host` = original host timestamp
- `theta_client` = estimated clock offset between host and client
- `D_target` = fixed presentation delay, normally `100.0 ms`

---

# 7. Clock Synchronization Architecture

SonicSync keeps its NTP-style clock synchronization model but upgrades it into a proper clock discipline system.

## 7.1 NTP-Style Offset Estimation

The system uses four timestamps:

\[
\theta = \frac{(t_1 - t_0) + (t_2 - t_3)}{2}
\]

Round-trip time:

\[
RTT = (t_3 - t_0) - (t_2 - t_1)
\]

Where:

- `t0` = client request sent
- `t1` = host request received
- `t2` = host reply sent
- `t3` = client reply received

---

## 7.2 Clock Filtering

The clock filter must reject bad measurements caused by Wi-Fi spikes and bufferbloat.

Recommended filters:

- Median RTT filter
- Outlier rejection using median absolute deviation
- Minimum sample count before lock
- Confidence scoring
- Drift estimation in ppm

---

## 7.3 PLL Controller

Instead of directly correcting every offset error, use a PI controller.

Control law:

\[
r = 1 + K_p e + K_i \int e \, dt
\]

Where:

- `r` = resampling ratio or playback rate correction
- `e` = timing error
- `Kp` = proportional gain
- `Ki` = integral gain

Constraints:

```text
Maximum correction: ±0.05%
Correction ramp: smooth
No abrupt clock jumps
```

---

## 7.4 Buffer Watermarks

Target delay:

```text
D_target = 100 ms
```

Recommended buffer states:

| State | Value | Action |
|---|---:|---|
| Hard underrun risk | < 35 ms | Emergency correction / concealment |
| Minimum | 45 ms | Speed up playback slightly |
| Target | 90–110 ms | Normal operation |
| Maximum | 160 ms | Slow down playback slightly |
| Hard reset | > 250 ms | Discard old audio and resynchronize |

---

# 8. Transport Architecture

The final architecture uses multiple transport adapters. This is necessary because VLC compatibility, native precision, and web zero-install access have different requirements.

## 8.1 RTP/RTCP Adapter for VLC

This is the primary VLC-facing transport.

Purpose:

- Allow VLC to receive SonicSync streams using standard network streaming concepts.
- Provide RTCP sender reports containing host timing information.
- Allow generation of `.sdp` or `.m3u` files for one-click VLC launch.

Recommended design:

```text
Transport: UDP
Protocol: RTP/RTCP
Payload: Dynamic PCM payload
Packet duration: 10 ms
RTCP interval: 100–250 ms
Clock source: SonicSync host master clock
```

Packet duration examples:

| Sample Rate | Samples per 10 ms Packet |
|---:|---:|
| 44.1 kHz | 441 |
| 48 kHz | 480 |
| 96 kHz | 960 |
| 192 kHz | 1920 |

RTCP sender reports should include:

- NTP timestamp
- RTP timestamp
- Packet count
- Octet count
- Sender sequence number

Additional SonicSync telemetry may be sent through:

- RTCP APP-defined packets
- WebSocket control channel
- HTTP REST API

---

## 8.2 SonicSync UDP Binary Adapter

This preserves the existing high-precision native receiver path.

Uses the existing SonicSync binary wire format:

- Magic header: `SONI`
- Version
- Packet type
- Audio format
- Channel count
- Sample rate
- Sequence number
- Presentation timestamp
- Target playout delay
- Frame count
- Payload length
- CRC32
- Audio payload

This adapter remains the reference path for:

- Native desktop receivers
- Highest synchronization precision
- CRC validation
- Controlled jitter buffering
- PLL micro-resampling

---

## 8.3 WebSocket Adapter

Used for browser clients.

Features:

- Binary audio frames
- JSON control messages
- NTP-style ping/pong synchronization
- `TCP_NODELAY` where applicable
- Reconnection support
- Client telemetry reporting

Browser audio path:

```text
WebSocket -> Packet Parser -> Ring Buffer -> PLL Watermark Controller -> Hermite Resampler -> AudioWorklet -> DSP -> AudioContext
```

---

# 9. VLC Integration Strategy

VLC integration is divided into four parts.

---

## 9.1 VLC as Source Engine

This is the highest-priority VLC feature.

### Goal

Allow SonicSync to broadcast whatever VLC is playing.

### Features

- Load files, folders, playlists, URLs, discs
- Play/pause/stop
- Next/previous
- Seek
- Volume/mute
- Metadata display
- Playlist management

### Implementation

Preferred:

```text
python-vlc / libVLC audio callback -> SonicSync RingBuffer
```

Fallback:

```text
VLC audio output -> system audio device -> SonicSync loopback capture
```

### Host Dashboard Integration

The SonicSync dashboard should display:

- Current VLC media title
- Current playlist position
- Playback state
- Seek position
- Volume
- Repeat/shuffle state

The dashboard should expose controls:

- Play
- Pause
- Stop
- Next
- Previous
- Seek bar
- Volume slider
- Playlist browser

---

## 9.2 VLC Direct Listener Mode

In this mode, VLC opens a SonicSync stream directly.

Example:

```text
rtp://@239.255.0.1:5004
```

or generated playlist:

```text
sonicsync_room.m3u
```

or SDP file:

```text
sonicsync_room.sdp
```

Recommended VLC launch flags:

```bash
vlc --network-caching=120 --quiet --no-audio-time-stretch rtp://@239.255.0.1:5004
```

Notes:

- Exact flags may vary by VLC version.
- `--network-caching` should be kept low but stable.
- Time-stretch behavior should be tested carefully to avoid artifacts.
- VLC Direct Mode is best-effort synchronization unless assisted by SonicSync sidecar.

---

## 9.3 VLC Sync Sidecar Mode

This is the recommended way to use VLC for synchronized multi-room desktop playback.

### Concept

A small SonicSync sidecar runs on the client machine alongside VLC.

The sidecar:

1. Launches VLC with low-latency stream settings.
2. Receives SonicSync timing information from the host.
3. Estimates clock offset and drift.
4. Monitors VLC playback state.
5. Adjusts VLC playback rate or buffer position when needed.
6. Reports client health back to the host dashboard.

### Communication with VLC

Possible control interfaces:

- VLC RC interface
- VLC Telnet interface
- VLC HTTP interface
- VLC Lua extension
- Future custom VLC audio filter plugin

Example launch concept:

```bash
vlc --extraintf rc --rc-host 127.0.0.1:4212 --network-caching=120 rtp://@239.255.0.1:5004
```

### Sidecar Responsibilities

- Maintain 100 ms target presentation delay
- Keep VLC buffer near target watermark
- Apply small rate corrections
- Detect underrun or overrun conditions
- Trigger resynchronization if drift becomes too large
- Show client sync status in host dashboard

### Important Limitation

VLC rate correction may introduce subtle pitch or timing artifacts depending on VLC version and audio output path.

Therefore:

- VLC Sync Sidecar Mode is considered high-quality desktop mode.
- Native SonicSync Receiver remains the reference mode for critical audiophile synchronization.

---

## 9.4 Future VLC Plugin

Long-term, the cleanest VLC receiver solution is a custom VLC plugin.

Possible plugin functions:

- Receive SonicSync RTP/UDP stream
- Parse SonicSync timing metadata
- Implement SonicSync PLL inside VLC audio pipeline
- Output directly through VLC audio output
- Report buffer health and sync status
- Provide SonicSync menu inside VLC

This is not required for v1 but should be the long-term VLC-native goal.

---

# 10. Client Architecture

## 10.1 VLC Client

Primary desktop listener path.

Components:

- VLC media player
- SonicSync generated `.m3u` or `.sdp`
- Optional SonicSync Sync Sidecar
- Optional VLC plugin in future

Best for:

- Desktop listening
- VLC enthusiasts
- DAC-connected living room systems
- Users who prefer VLC over browsers

---

## 10.2 Native SonicSync Receiver

Reference synchronization client.

Components:

- UDP SonicSync binary receiver
- CRC validation
- NTP clock filter
- Adaptive jitter buffer
- PLL micro-resampler
- PortAudio / WASAPI / CoreAudio / ALSA output

Best for:

- Critical listening
- Sample-accurate validation
- Low-latency stable environments
- Measurement and testing

---

## 10.3 Web Audio Listener

Zero-install mobile path.

Components:

- QR code access
- WebSocket binary stream
- Circular sample queue
- Hermite interpolation
- PLL micro-resampler
- DSP presets
- AudioWorklet renderer where supported

Best for:

- iPhone Safari
- Android Chrome
- Guest listening
- Temporary listeners
- No-install environments

Recommended web architecture:

```text
WebSocket Binary Frames
        |
        v
Packet Parser / Validation
        |
        v
Sample Ring Buffer
        |
        v
PLL Watermark Controller
        |
        v
Hermite / Linear Resampler
        |
        v
AudioWorklet Processor
        |
        v
DSP Chain
        |
        v
AudioContext Destination
```

---

# 11. Final Wire Protocol Strategy

The final architecture uses two wire strategies.

---

## 11.1 VLC-Compatible RTP Stream

Used for VLC listeners.

Responsibilities:

- Standard network streaming compatibility
- RTCP timing reports
- SDP session description
- Multicast or unicast UDP
- Optional HTTP announcement

Design principles:

- Keep payload VLC-decodable
- Avoid non-standard payload modifications
- Use RTCP for timing metadata where possible
- Use separate control channel for advanced SonicSync telemetry

---

## 11.2 SonicSync Binary Protocol

Used for native receivers and possibly WebSocket framing.

Retains existing header design:

```text
Magic Header: 'S','O','N','I'
Version
Packet Type
Format
Channels
Sample Rate
Sequence Number
Presentation Timestamp
Target Playout Delay
Frame Count
Payload Length
CRC32
Audio Payload
```

This protocol remains important because it provides:

- Explicit CRC integrity
- Explicit target delay
- Explicit PTS
- Tight integration with SonicSync PLL
- Native receiver precision

---

# 12. Control Plane Architecture

The control plane is responsible for configuration, status, QR codes, client management, and VLC media control.

## 12.1 REST API

Recommended endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/status` | Host status, source, sample rate, clients |
| GET | `/api/qr` | QR code for web listener |
| GET | `/api/clients` | Client list and sync health |
| POST | `/api/control` | Play/pause/stop/volume/source selection |
| POST | `/api/vlc/playlist` | Load VLC playlist or URL |
| GET | `/api/vlc/metadata` | Current VLC media metadata |
| GET | `/api/sync/report` | Sync statistics |
| POST | `/api/test-tone` | Enable test generator |
| GET | `/api/sdp` | Generate VLC SDP/M3U session file |

---

## 12.2 WebSocket Control Messages

Used by web clients and sidecars.

Message types:

```text
ntp_request
ntp_response
client_report
buffer_report
sync_lock
resync_request
stream_config
error
```

Client report fields:

```json
{
  "client_id": "phone-01",
  "buffer_ms": 102.4,
  "offset_ms": 1.2,
  "rtt_ms": 8.7,
  "drift_ppm": 0.4,
  "underruns": 0,
  "overruns": 0,
  "packet_loss": 0,
  "resample_ratio": 1.00002
}
```

---

# 13. Host Dashboard Plan

The host dashboard becomes the main user interface.

## 13.1 Status Page

Displays:

- Host IP
- QR code
- VLC session file download
- Current source
- Sample rate
- Bit depth
- Channels
- Stream health
- Client count

---

## 13.2 VLC Media Page

Displays:

- Playlist
- Current item
- Playback state
- Seek position
- Volume
- Metadata

Controls:

- Play
- Pause
- Stop
- Next
- Previous
- Seek
- Volume
- Shuffle
- Repeat

---

## 13.3 Clients Page

Displays per client:

- Client name/type
- Transport mode
- Buffer depth
- Offset
- RTT
- Drift
- Underruns
- Connection state
- Last report time

Actions:

- Disconnect client
- Adjust target delay per client
- Calibrate client delay
- Mute client
- Resync client

---

## 13.4 Audio Settings Page

Controls:

- Source selection
- Sample rate
- Bit depth
- Channel mode
- Target delay
- Limiter enable/disable
- DSP preset
- Test generator

---

## 13.5 Diagnostics Page

Displays:

- Logs
- Network stats
- Buffer graphs
- Sync error graphs
- Packet loss
- CPU usage
- Diagnostic download

---

# 14. Security Plan

SonicSync is LAN-first but should still protect access.

## 14.1 Session Tokens

QR and stream URLs should include short-lived tokens:

```text
http://192.168.1.20:8080/listen?token=abc123
```

---

## 14.2 Client Authorization

Host should be able to:

- Approve clients
- Block clients
- Limit number of clients
- Expire tokens
- Rotate tokens

---

## 14.3 Optional PIN

For stricter environments:

- Host displays PIN
- User enters PIN before listening
- Token issued after PIN validation

---

## 14.4 LAN Restrictions

Default behavior:

- Bind only to local interface
- Do not expose to WAN
- Optional HTTPS for dashboard if deployed beyond localhost
- Disable remote control unless explicitly enabled

---

# 15. Audio Fidelity Plan

## 15.1 Target Measurements

| Metric | Target |
|---|---:|
| SNR | > 120 dB |
| THD | < 0.0001% |
| Frequency response | ±0.001 dB, 20 Hz–20 kHz |
| Presentation delay | 100 ms ± 5 ms |
| Native receiver inter-device sync | Median < 2 ms |
| VLC assisted sync | Median < 5 ms where feasible |
| Underruns | < 1 per hour under normal LAN |

---

## 15.2 Fidelity Rules

1. Default transport is uncompressed PCM or Float32.
2. No lossy compression in main lossless path.
3. Optional lossy fallback only for constrained mobile/Web fallback.
4. DSP presets must be bypassable.
5. Direct Bit-Exact Flat mode must disable EQ and limiting where possible.
6. Dither only when reducing bit depth.
7. Limiter should be transparent unless protecting against clipping.

---

# 16. Synchronization Guarantee Matrix

| Client Type | Timing Source | Sync Mechanism | Expected Precision |
|---|---|---|---|
| Native Receiver | SonicSync UDP header + NTP | Custom PLL + PortAudio | Highest |
| Web Listener | WebSocket NTP messages | AudioWorklet PLL + resampling | High |
| VLC Direct | RTP/RTCP | VLC internal buffering | Medium |
| VLC + Sidecar | RTP/RTCP + SonicSync control | Sidecar-assisted VLC rate control | Medium-High |
| VLC plugin future | SonicSync inside VLC | Custom PLL inside VLC | High |

---

## Important Claim Adjustment

For technical credibility, public wording should be:

> SonicSync provides deterministic presentation synchronization with sub-sample drift correction. Absolute acoustic sample accuracy may require per-device output latency calibration.

This avoids overclaiming because acoustic output depends on:

- DAC latency
- Bluetooth latency
- OS audio stack
- Browser audio implementation
- VLC audio output module
- Hardware buffering

---

# 17. Repository Structure

Recommended final project structure:

```text
sonicsync/
├── run.py
├── start_host.bat
├── requirements.txt
├── README.md
├── docs/
│   ├── FINAL_ARCHITECTURE_PLAN.md
│   ├── wire_protocol.md
│   ├── vlc_integration.md
│   └── testing.md
│
├── src/
│   ├── core/
│   │   ├── audio_format.py
│   │   ├── ring_buffer.py
│   │   ├── limiter.py
│   │   ├── dither.py
│   │   ├── packet.py
│   │   └── clock.py
│   │
│   ├── capture/
│   │   ├── base_source.py
│   │   ├── wasapi_loopback.py
│   │   ├── coreaudio_loopback.py
│   │   ├── pulse_monitor.py
│   │   ├── pipewire_monitor.py
│   │   └── test_generator.py
│   │
│   ├── vlc/
│   │   ├── vlc_source.py
│   │   ├── vlc_control.py
│   │   ├── vlc_playlist.py
│   │   ├── vlc_metadata.py
│   │   └── vlc_loopback_fallback.py
│   │
│   ├── sync/
│   │   ├── clock_filter.py
│   │   ├── drift_estimator.py
│   │   ├── pll_controller.py
│   │   ├── jitter_buffer.py
│   │   └── sync_coordinator.py
│   │
│   ├── transport/
│   │   ├── rtp_adapter.py
│   │   ├── rtcp_adapter.py
│   │   ├── sdp_generator.py
│   │   ├── sonicsync_udp.py
│   │   ├── websocket_stream.py
│   │   └── receiver_report.py
│   │
│   ├── server/
│   │   ├── web_server.py
│   │   ├── api.py
│   │   ├── qr.py
│   │   ├── session.py
│   │   └── auth.py
│   │
│   └── clients/
│       ├── native_receiver.py
│       └── vlc_sync_sidecar.py
│
├── web/
│   ├── listen.html
│   ├── dashboard.html
│   ├── audio_worklet.js
│   ├── pll.js
│   ├── resampler.js
│   ├── dsp.js
│   └── ui.js
│
└── tests/
    ├── unit/
    ├── integration/
    ├── vlc/
    ├── network/
    └── acoustic/
```

---

# 18. Implementation Roadmap

## Phase 1 — Foundation and Metrics

Goal: Stabilize existing SonicSync engine and define measurable targets.

Tasks:

- Preserve existing UDP binary protocol
- Add sync telemetry logging
- Add buffer/RTT/offset/underrun metrics
- Establish baseline performance
- Define acceptance criteria

Exit Criteria:

- Current native receiver and web listener remain functional
- Metrics are visible in dashboard/logs
- Baseline report is generated

---

## Phase 2 — VLC Source Integration

Goal: Make VLC the primary media source.

Tasks:

- Integrate `python-vlc`
- Create `VLCSource`
- Implement playback control API
- Implement metadata reporting
- Implement playlist loading
- Add dashboard VLC controls
- Add loopback fallback if direct callback is unstable

Exit Criteria:

- SonicSync can broadcast audio from VLC
- Dashboard can control VLC play/pause/next/previous
- No audio dropouts during normal VLC playback
- Metadata appears correctly

---

## Phase 3 — RTP/RTCP Transport for VLC

Goal: Make SonicSync streams openable by VLC.

Tasks:

- Implement RTP packetizer
- Implement RTCP sender reports
- Implement SDP generator
- Generate `.m3u` and `.sdp` downloads from dashboard
- Test VLC Direct Listener Mode
- Test multicast and unicast fallback

Exit Criteria:

- VLC can open SonicSync stream
- Audio plays without manual packet inspection
- RTCP reports are visible/parseable
- VLC Direct Mode works on LAN

---

## Phase 4 — VLC Sync Sidecar

Goal: Improve VLC multi-room synchronization.

Tasks:

- Build lightweight sidecar client
- Launch VLC with low-latency flags
- Connect sidecar to SonicSync control plane
- Estimate offset and drift
- Control VLC through RC/Telnet/HTTP
- Add client health reporting
- Add resync behavior

Exit Criteria:

- VLC client maintains more stable target delay
- Sidecar reports buffer/sync health
- Temporary network spikes recover cleanly
- VLC client can be used for multi-room listening with acceptable sync

---

## Phase 5 — Web Listener Hardening

Goal: Keep mobile zero-install path strong.

Tasks:

- Use AudioWorklet where available
- Improve ring buffer
- Improve reconnect logic
- Add diagnostics overlay
- Improve iOS Safari start flow
- Keep QR code access simple

Exit Criteria:

- Phones can join by QR quickly
- Audio start is reliable
- Buffer lock is visible
- Reconnect works cleanly

---

## Phase 6 — Validation and Release Candidate

Goal: Prove the VLC-first architecture.

Tasks:

- VLC source tests
- VLC listener tests
- Native receiver sync tests
- Web listener mobile tests
- Network impairment tests
- Acoustic metronome tests
- CPU/battery sanity tests
- Final dashboard polish

Exit Criteria:

- VLC source streaming is stable
- VLC listener mode is usable
- Native receiver remains reference-grade
- Web listener remains zero-install
- Sync metrics meet release targets

---

# 19. Test Plan

## 19.1 Unit Tests

Cover:

- Audio format conversion
- PCM serialization
- CRC32
- Ring buffer
- RTP packetizer
- RTCP parser
- SDP generator
- Clock offset calculation
- PLL controller limits
- Limiter behavior
- Dither behavior

---

## 19.2 Integration Tests

Cover:

- VLC source -> SonicSync core -> RTP adapter
- VLC source -> SonicSync core -> WebSocket adapter
- VLC source -> SonicSync core -> native UDP adapter
- VLC control API -> VLC playback actions
- Client reconnect behavior
- Buffer underrun recovery
- RTCP timing report handling

---

## 19.3 VLC-Specific Tests

Cover:

- VLC opens generated `.m3u`
- VLC opens generated `.sdp`
- VLC plays RTP stream
- VLC sidecar can launch VLC
- VLC sidecar can adjust playback rate
- VLC sidecar reports health
- VLC playlist controls work
- VLC metadata updates correctly

---

## 19.4 Network Impairment Tests

Use:

- Linux `tc`
- Windows Clumsy
- macOS Network Link Conditioner

Test conditions:

- Added latency
- Jitter
- Packet loss
- Burst loss
- Bandwidth restriction
- Wi-Fi roaming-like interruption

---

## 19.5 Acoustic Synchronization Tests

Method:

1. Host emits metronome click.
2. Multiple devices record output simultaneously.
3. Cross-correlate recordings.
4. Measure inter-device offset.

Target:

- Native receivers: median < 2 ms
- Assisted VLC clients: median < 5 ms where achievable
- Web listeners: stable and subjectively coherent

---

# 20. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|---|---:|---:|---|
| VLC default buffering too large | High | High | Use low network caching, sidecar control, native receiver fallback |
| VLC rate adjustment artifacts | Medium | Medium | Keep correction tiny; use native receiver for critical listening; develop VLC plugin |
| `python-vlc` audio callback complexity | High | Medium | Provide VLC loopback fallback source |
| Multicast blocked on some networks | Medium | High | Provide unicast RTP, WebSocket fallback |
| iOS Safari autoplay restrictions | Medium | High | Tap-to-listen gesture, AudioContext resume, clear status |
| Wi-Fi jitter causes underruns | High | High | Adaptive PLL, watermark buffer, receiver reports |
| VLC client clock drift | Medium | High | Sidecar-assisted drift correction |
| High sample rates overload network/CPU | Medium | Medium | Default 48 kHz/24-bit, expert mode for high rates |
| Security exposure on LAN | Medium | Low | Tokenized URLs, client approval, optional PIN |
| Overclaiming sample accuracy | Medium | Medium | Use “presentation-synchronized” language unless calibrated |

---

# 21. Release Acceptance Criteria

## 21.1 Host

- One-command host launch works.
- Dashboard opens automatically.
- VLC source can play local media.
- VLC playback controls work from dashboard.
- QR code is generated correctly.
- VLC `.m3u` or `.sdp` session file is generated correctly.
- Test generator works.

---

## 21.2 Audio

- No audible clicks between packets.
- No repeated underruns under normal LAN conditions.
- Limiter prevents clipping without harsh distortion.
- Lossless transport path is verified.
- SNR and THD targets are measured.

---

## 21.3 Synchronization

- Clients reach stable lock.
- Target delay remains around 100 ms.
- Drift correction does not create obvious pitch shift.
- Temporary network spikes do not cause permanent desync.
- Native receiver demonstrates reference-grade sync.

---

## 21.4 VLC

- VLC can open SonicSync stream.
- VLC source mode works.
- VLC sidecar can launch and control VLC.
- VLC client health is visible in dashboard.
- VLC mode is clearly labeled as assisted/best-effort where appropriate.

---

## 21.5 Web

- QR scan to audio starts quickly.
- Mobile Safari and Android Chrome work.
- Tap-to-start flow is clear.
- Buffer diagnostics are visible.
- Reconnect works cleanly.

---

# 22. Final Recommended Architecture Statement

The final SonicSync architecture should be:

> **A VLC-first lossless multi-room audio system where VLC provides media playback and listener convenience, while SonicSync provides the master clock, jitter buffering, drift correction, and deterministic 100 ms presentation synchronization.**

## Final Priority Order

1. **VLC source integration**
2. **SonicSync clock and buffer stability**
3. **RTP/RTCP transport for VLC listeners**
4. **VLC Sync Sidecar for assisted multi-room synchronization**
5. **Native receiver for reference-grade precision**
6. **Web listener for zero-install mobile access**
7. **Dashboard UX and diagnostics**
8. **Security and deployment polish**

This architecture preserves SonicSync’s technical differentiation while making VLC a first-class citizen.