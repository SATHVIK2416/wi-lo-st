# 🔊 Live Audio Share (WebRTC Edition)

Live stream your system audio (anything playing on your computer) to phones, tablets, or other PCs on the same Wi‑Fi with low latency using WebRTC.

> Legacy video upload + chunked audio code was removed. Architecture now uses one WebRTC audio track per listener for smoother, gap‑free playback.

## ✨ Features

- 🖥️ **System Audio Capture** – Share any app / browser / media player output
- 🛰️ **WebRTC Transport** – Continuous Opus stream with built‑in jitter buffering
- 👥 **Unlimited Listeners** – A RTCPeerConnection is created on demand per viewer
- 📊 **Live Stats** – Real‑time listener count (broadcast via Socket.IO)
- 🎚️ **Level Meter** – Host-side audio level visualization
- 🔗 **Simple URLs** – `/` (host control) + `/listen` (lightweight listener)
- � **LAN Friendly** – Prints all local network URLs for easy sharing
- 🔄 **Resilient** – Late joiners instantly receive a fresh offer

## 🚀 Quick Start

### Prerequisites
- Node.js 16+ (14 usually fine but 16+ recommended)
- Modern Chromium / Firefox / Edge (WebRTC + getDisplayMedia)
- Permission to share screen + audio (browser prompt)

### Install & Run
```bash
npm install
npm start
```
Dev (auto‑restart):
```bash
npm run dev
```

Then open:
- Host: http://localhost:3000
- LAN: use one of the printed `http://<LAN_IP>:3000` addresses

## ▶️ Hosting a Stream
1. Open the host page (`/`).
2. Click **🔊 Share System Audio**.
3. In the share picker choose Entire Screen (or a window) AND tick **Share audio**.
4. Once approved the status shows streaming; level bar animates.
5. Share the Listener URL (shown on page) e.g. `http://<LAN_IP>:3000/listen`.
6. Stop anytime with **⏹️ Stop Sharing**.

## 🎧 Joining as a Listener
1. Open the `/listen` URL on the same Wi‑Fi.
2. Press **Enable Audio** (required for autoplay policies).
3. The page negotiates a WebRTC connection and starts playback.
4. Adjust volume / mute locally – it doesn’t affect the host or others.

## 🔍 How It Works
| Phase | Flow |
|-------|------|
| Capture | Host calls `getDisplayMedia({ video:true, audio:true })` (video track discarded, audio kept). |
| Signaling | Socket.IO messages: `register-host`, `viewer-join`, `webrtc-offer`, `webrtc-answer`, `webrtc-ice-candidate`. |
| Connection | Host creates a RTCPeerConnection per viewer, adds the system audio track, sends SDP offer. |
| Response | Viewer sets remote offer, creates answer, sends back; ICE candidates exchanged. |
| Playback | Viewer attaches received stream to an `<audio>` element (autoplay). |
| Stats | Server tracks viewer sockets, periodically emits `stats` with listener count. |

## 🛠️ Technical Architecture
**Backend (`server.js`)**
- Express serves static assets.
- Socket.IO roomless signaling (custom events, host socket ID tracking).
- STUN: `stun:stun.l.google.com:19302` for NAT traversal.
- Lightweight stats broadcaster.

**Frontend Host (`public/script.js`)**
- Captures system audio → extracts one `MediaStreamTrack`.
- On `viewer-joined` creates RTCPeerConnection, adds track, generates offer.
- Handles answers + ICE from viewers; cleans up on disconnect.
- AnalyserNode drives level meter (visual only – not sent to viewers).

**Frontend Listener (`public/listen.html`)**
- Connects via Socket.IO.
- Requests to join; receives offer → answer → ICE.
- Plays audio in a single persistent element (no per‑chunk artifacts).
- Simple CSS visualizer (pseudo‑random) for lightweight feedback.

## 📁 File Structure
```
wi-lo-st/
├── server.js          # Express + Socket.IO signaling server
├── package.json       # Scripts & deps
├── public/
│   ├── index.html     # Host UI
│   ├── listen.html    # Listener UI (WebRTC)
│   ├── script.js      # Host logic (capture + signaling)
│   └── styles.css     # Shared styles (minor)
└── README.md
```

## � Migration Note (Why the Old Chunk Method Failed)
The original build used `MediaRecorder` → small Opus chunks → Socket.IO broadcast → create & play an `<audio>` element per chunk. Problems:
1. Latency / Gaps – Browser scheduling many short elements introduced timing drift & gaps.
2. Autoplay Policies – Frequent element creation could be blocked or delayed.
3. Jitter – No adaptive buffer; network variability caused stutter.
4. Memory & GC Pressure – Rapid blob URL creation/destruction.
5. No Congestion Control – Raw sockets lacked media‑aware pacing.

WebRTC solves all of these with a continuous track, jitter buffer, congestion control, and codec negotiation.

## ⚙️ Configuration
Environment PORT override:
```bash
PORT=8080 npm start
```
Change STUN? Edit the `iceServers` array in `script.js` & `listen.html`.

## 🚨 Security
- Intended for trusted local networks only.
- No auth / encryption beyond WebRTC DTLS + HTTPS (if you add TLS).
- Don’t expose publicly without adding authentication & HTTPS termination.

## � Troubleshooting
| Symptom | Fix |
|---------|-----|
| Listener shows "No host" | Host hasn’t clicked Share yet or host tab closed. |
| No audio after sharing | Ensure "Share audio" was ticked; re‑start and pick the full screen. |
| Works on host, silent on phone | Phone muted / autoplay blocked: tap Enable Audio again. |
| Frequent disconnects | Wi‑Fi instability – keep devices closer to router; reduce other traffic. |
| High latency | Use 5GHz Wi‑Fi; close other heavy network apps. |
| ICE failed | Corporate / restrictive NAT – add TURN server (not included). |

## 🧪 Extending
- Add TURN for wider NAT traversal (e.g. `coturn`).
- Real analyser‑based visualizer on listener side using AudioContext.
- Optional auth token to restrict who can join.
- Single mixed stream approach (SFU) if scaling to dozens+ listeners.

## 🎯 Use Cases
- Share movie / music audio around the house.
- Classroom / study group synchronized audio.
- Quick demo / presentation sound distribution.
- Quiet listening (headphones on devices instead of speakers).

## 🔄 Updating
```bash
git pull
npm install
npm restart   # or stop + start
```

## 🙌 Enjoy
Happy low‑latency streaming! 🔊
