# SonicSync Binary Wire Protocol & RTP Specification

## 1. 42-Byte Binary Audio Header

Every native SonicSync packet transmitted over UDP and WebSocket begins with a fixed 42-byte binary header packed in network big-endian byte order (`!4sBBBBIIddHII`).

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

### Field Definitions

| Field | Type | Size | Description |
|---|---|---|---|
| Magic Header | `char[4]` | 4 Bytes | Fixed signature `'SONI'` (`0x534F4E49`) |
| Version | `uint8_t` | 1 Byte | Protocol version (currently `0x01`) |
| Packet Type | `uint8_t` | 1 Byte | `0x01` = Audio Data, `0x02` = Control, `0x03` = NTP |
| Format | `uint8_t` | 1 Byte | `0x01` = Int16, `0x02` = Int24, `0x03` = Int32, `0x04` = Float32 |
| Channels | `uint8_t` | 1 Byte | Number of interleaved channels (`1` = Mono, `2` = Stereo) |
| Sample Rate | `uint32_t` | 4 Bytes | Audio sample rate in Hz (e.g. `48000`, `96000`, `192000`) |
| Sequence Number | `uint32_t` | 4 Bytes | Monotonically incrementing sequence counter |
| PTS | `double` | 8 Bytes | Host Presentation Timestamp in fractional seconds (nanosecond precision) |
| Target Delay | `double` | 8 Bytes | Configured presentation delay in seconds (default `0.100` = 100.0 ms) |
| Frame Count | `uint16_t` | 2 Bytes | Number of audio frames per channel in this packet |
| Payload Length | `uint32_t` | 4 Bytes | Total payload byte length |
| CRC32 | `uint32_t` | 4 Bytes | IEEE 802.3 CRC32 checksum over the payload |

---

## 2. RFC 3550 RTP/RTCP VLC Transport

For direct compatibility with standard desktop players like VLC, SonicSync simultaneously broadcasts RFC 3550 RTP datagrams over UDP (`239.255.0.1:5006`).

- **Payload Type**: Dynamic PT 96 (Linear PCM L16 / L24)
- **Packet Duration**: 10 ms (480 samples @ 48 kHz)
- **RTCP Reports**: RFC 3550 Sender Reports transmitted every 200 ms containing 64-bit NTP timestamps mapped to 32-bit RTP presentation timestamps.
