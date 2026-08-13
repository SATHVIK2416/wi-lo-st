# SonicSync Final Architecture & Technical Specification

## System Vision
SonicSync is a hybrid VLC-first multi-room audio platform delivering bit-exact uncompressed audio across Wi-Fi/Ethernet with deterministic 100.0 ms presentation synchronization.

```text
+--------------------------------------------------------------------------------------------------+
|                                        SONICSYNC HOST                                            |
|                                                                                                  |
|  +----------------------------------+                                                            |
|  |          SOURCE LAYER            |                                                            |
|  |                                  |                                                            |
|  | 1. VLC Media Engine (Preferred)  |                                                            |
|  | 2. System Audio Loopback         |                                                            |
|  | 3. Precision Test Generator      |                                                            |
|  +----------------+-----------------+                                                            |
|                   |                                                                              |
|                   v                                                                              |
|  +----------------------------------+                                                            |
|  |       SONICSYNC AUDIO CORE       |                                                            |
|  |                                  |                                                            |
|  | - Thread-safe RingBuffer         |                                                            |
|  | - Studio Soft-Knee Limiter       |                                                            |
|  | - TPDF Dithering for PCM         |                                                            |
|  | - Host Master Clock (PTS)        |                                                            |
|  +----------------+-----------------+                                                            |
|                   |                                                                              |
|                   v                                                                              |
|  +----------------------------------+                                                            |
|  |       TRANSPORT ADAPTERS         |                                                            |
|  |                                  |                                                            |
|  | - RFC 3550 RTP/RTCP Adapter      |                                                            |
|  | - SonicSync 42-Byte UDP Binary   |                                                            |
|  | - WebSocket Stream Broadcaster   |                                                            |
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

## Core Guarantees
- **Lossless Audio Transport**: Native uncompressed 32-bit float and 24-bit/16-bit PCM up to 192 kHz.
- **Clock Discipline**: 4-timestamp NTP estimation with Median Absolute Deviation filtering and PI PLL micro-resampling rate control ($\pm 0.05\%$ max).
- **Zero-Install Web Audio**: Instant streaming in Safari, Chrome, Edge, and Firefox via QR code scan.
- **VLC Priority**: First-class source decoding via libVLC and desktop listening via RTP/RTCP.
