# VLC Integration Guide

SonicSync provides four distinct integration strategies for VLC Media Player:

## 1. VLC as Source Engine (Preferred Media Host)
SonicSync taps into libVLC via direct audio memory callbacks (`audio_set_format("FL32", 48000, 2)` and `audio_set_callbacks`).
- Decoded media frames (FLAC, WAV, MP3, AAC, network streams, etc.) pass directly into SonicSync's RingBuffer with **zero loopback latency**.
- SonicSync's web dashboard provides real-time VLC playback control (Play, Pause, Stop, Seek, Volume, Track metadata, Playlist management).

## 2. VLC Direct Listener Mode
Desktop computers running VLC can open SonicSync's network broadcast stream directly:
```bash
vlc --network-caching=120 --quiet --no-audio-time-stretch rtp://@239.255.0.1:5006
```
Or open the generated session files from the dashboard:
- `http://<HOST_IP>:8080/api/stream.m3u`
- `http://<HOST_IP>:8080/api/sdp`

## 3. VLC Sync Sidecar Mode (Assisted Synchronization)
For multi-room desktop listening using VLC:
- The `VLCSyncSidecar` process launches VLC with `--extraintf rc --rc-host 127.0.0.1:4212 --network-caching=120`.
- Sidecar connects to SonicSync's WebSocket control plane, performs 4-timestamp NTP clock estimation, and steers VLC's playback rate via RC commands (`rate <ratio>`) to maintain alignment within the 100.0 ms target delay window.

## 4. System Loopback Fallback
If direct libVLC memory callbacks are unavailable on specific operating systems, SonicSync can fall back to capturing VLC's output via Windows WASAPI Loopback or Linux Pulse/PipeWire monitor.
