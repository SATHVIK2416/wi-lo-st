# 🔊 Live Audio Share (MediaMTX SFU Edition)

Live stream your system audio (anything playing on your computer) to phones, tablets, or other PCs on the same Wi‑Fi with ultra-low latency using WebRTC.

> **Architecture Revamp**: The project has migrated from a P2P mesh network to a **Selective Forwarding Unit (SFU)** architecture using [MediaMTX](https://github.com/bluenviron/mediamtx). This solves Wi-Fi congestion and CPU scaling issues by having the host upload a single stream to the SFU, which distributes it to all listeners.

## ✨ Features

- 🖥️ **System Audio Capture** – Share any app / browser / media player output
- 🛰️ **WebRTC Transport via SFU** – Continuous Opus stream distributed by MediaMTX
- 👥 **Massively Scalable** – Host only uploads once regardless of listener count
- 📊 **Live Stats** – Real‑time listener count (broadcast via Socket.IO)
- 🎚️ **Live Audio Tuning** – Adjust latency and bitrate on the fly
- 🔗 **Zero Install for Listeners** – Listeners just open a web URL (`/listen`)
- 🔄 **WHIP & WHEP** – Uses modern WebRTC-HTTP ingestion/egress protocols

## 🚀 Quick Start

### Prerequisites
1. **Node.js 16+** (to serve the UI)
2. **MediaMTX** (to route the WebRTC traffic)
   - Download the latest binary from [MediaMTX Releases](https://github.com/bluenviron/mediamtx/releases).
3. Modern Chromium / Firefox / Edge (WebRTC + `getDisplayMedia`)

### 1. Start MediaMTX
Place the `mediamtx` executable in the project root directory alongside the included `mediamtx.yml` configuration file. Run it:
```bash
./mediamtx
# or on Windows: mediamtx.exe
```
Ensure it binds to ports 8889 (WebRTC) and 9997 (API).

### 2. Start the Node.js Server
```bash
npm install
npm start
```
Dev (auto‑restart):
```bash
npm run dev
```

### 3. Open the UIs
- **Host**: `http://localhost:3000`
- **Listener (LAN)**: Use one of the printed `http://<LAN_IP>:3000/listen` addresses

## ▶️ Hosting a Stream
1. Ensure both MediaMTX and the Node.js server are running.
2. Open the host page (`/`).
3. Click **🔊 Share System Audio**.
4. In the share picker choose Entire Screen (or a window) AND tick **Share audio**.
5. The browser will use WHIP to push the stream to MediaMTX.
6. Share the Listener URL e.g. `http://<LAN_IP>:3000/listen`.
7. Adjust bitrate and latency in the host UI to tune performance vs quality.

## 🎧 Joining as a Listener
1. Open the `/listen` URL on the same Wi‑Fi.
2. Press **Join Stream** (required for autoplay policies).
3. The page uses WHEP to pull the stream from MediaMTX.
4. Adjust volume locally – it doesn’t affect the host or others.

## 🔍 How It Works
| Component | Flow |
|-----------|------|
| **Host** (`script.js`) | Calls `getDisplayMedia`, creates an RTCPeerConnection, and sends an SDP offer via HTTP POST (WHIP) to MediaMTX. |
| **MediaMTX** | Receives the WebRTC stream via WHIP, answers with an SDP, and holds the stream in its internal router. |
| **Listener** (`listen.js`) | Creates an RTCPeerConnection (recvonly) and sends an SDP offer via HTTP POST (WHEP) to MediaMTX. Receives answer and plays audio. |
| **Node.js UI** | Serves static assets, keeps track of viewer counts via Socket.IO, and broadcasts tune settings (playout delays) from host to listeners. |

## 🛠️ Technical Architecture

**MediaMTX (`mediamtx.yml`)**
- `webrtc: yes` on `:8889`
- Acts as the central WebRTC router (SFU).

**Backend (`server.js`)**
- Express serves static assets.
- Socket.IO tracks simple viewer connections for UI stats.

**Frontend Host (`public/script.js`)**
- WHIP Client for ingestion.
- Modifies SDP to force maximum Opus quality (510kbps, stereo, minptime=10).

**Frontend Listener (`public/listen.js`)**
- WHEP Client for egress.
- Applies `playoutDelayHint` based on host tuning settings.

## 🚨 Security
- Intended for trusted local networks only.
- No auth / encryption beyond WebRTC DTLS + HTTPS (if you add TLS).

##  Troubleshooting
| Symptom | Fix |
|---------|-----|
| Host fails to stream | Ensure MediaMTX is running on port 8889. |
| Listener shows "Failed to connect" | Ensure MediaMTX is reachable via the LAN IP on port 8889. Check firewall. |
| No audio after sharing | Ensure "Share audio" was ticked; re‑start and pick the full screen. |
| Frequent disconnects / Stutter | Adjust latency higher (e.g. 300ms) or bitrate lower via the Host Tuning UI. |

## 🙌 Enjoy
Happy low‑latency streaming! 🔊
