You’re aiming for a local‑network audio distribution system that streams the audio track of a movie from a laptop to several friends, who listen on their own devices (phones/laptops) while watching the same laptop screen. The hard part is keeping lip‑sync – the audio must be extremely low‑latency (ideally < 40 ms end‑to‑end) because the video is on the laptop display and cannot be delayed easily.

Below I’ll walk you through a technically solid way to build this using GStreamer and the Opus codec over multicast RTP/UDP. It avoids writing low‑level code, gives you AAC‑beating quality, and can hit latencies in the 20–50 ms range on a wired LAN (Wi‑Fi adds jitter, so ethernet is strongly preferred).

1. Why these choices
Requirement	Best choice	Rationale
Low latency	RTP over UDP multicast + tiny jitter buffer	No TCP retransmissions; multicast delivers to many clients simultaneously without extra server load.
High quality	Opus @ 128–256 kbps stereo	Opus is the state‑of‑the‑art codec – transparent at ~128 kbps, exceeding AAC quality. It supports frames as small as 2.5 ms, so algorithmic delay can be as low as 5 ms.
Sync with video	Opus with 10 ms frames + minimal jitter buffer	Total pipeline latency: capture (5 ms) + Opus encode (5 ms algorithmic + CPU) + network (1–5 ms on wired LAN) + jitter buffer (10 ms) + Opus decode (5 ms) + playout (5–10 ms) ≈ 30–40 ms. That’s below the noticeable lip‑sync threshold (~45 ms).
Ease of implementation	GStreamer pipelines	You can literally run two one‑liner commands – no programming needed, and every component is production‑grade.
2. Overall architecture
text
Laptop (server)                         Friend devices (clients)
┌─────────────────────┐                 ┌─────────────────────┐
│ Movie player        │                 │ GStreamer client    │
│ (e.g., VLC, mpv)    │                 │  udpsrc → jitterbuf │
│         │           │                 │  → opusdec → alsa   │
│         ▼           │                 └─────────────────────┘
│  System audio       │                          ▲
│  (loopback capture) │                          │
│         │           │                 Multicast UDP (224.0.0.x)
│         ▼           │                          │
│  GStreamer server   │◄─────────────────────────┘
│  capture → opusenc  │
│  → rtpopuspay → udpsink (multicast)
└─────────────────────┘
The server captures whatever audio the laptop is playing (the movie’s soundtrack).

It encodes with Opus (10 ms frames, 48 kHz, stereo, 160 kbps to start).

Packets are sent to a multicast address. Every client on the LAN subscribes to that address.

Each client receives, buffers for 10 ms (to smooth jitter), decodes, and plays through the earphones.

3. Step‑by‑step implementation with GStreamer
3.1 Install GStreamer (all platforms)
You need the base, good, bad, and ugly plugin sets, plus the Opus and RTP plugins.

Linux (Debian/Ubuntu)

bash
sudo apt install gstreamer1.0-tools gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly gstreamer1.0-libav \
  gstreamer1.0-opus gstreamer1.0-rtp
Windows
Download the runtime and development installers from gstreamer.freedesktop.org. Make sure to select “full” or “complete” installation.

macOS

bash
brew install gstreamer gst-plugins-base gst-plugins-good \
  gst-plugins-bad gst-plugins-ugly gst-libav
3.2 Find the loopback audio device
You need the name of the monitor source that captures system output (the movie’s audio).

Linux (PulseAudio)
List sources:
pactl list sources short | grep monitor
Typical name: alsa_output.pci-0000_00_1f.3.analog-stereo.monitor

Windows (WASAPI)
The loopback device is always "wasapi-loopback" (used with wasapisrc).

macOS (CoreAudio)
Use osxaudiosrc; often you need a virtual device like BlackHole to loop back. Install BlackHole, then the source will be something like "BlackHole 2ch".

3.3 Server pipeline (laptop)
Replace <LOOPBACK_DEVICE> with your actual device string. For Windows you’d use wasapisrc loopback=true.

bash
gst-launch-1.0 -v \
  pulsesrc device="<LOOPBACK_DEVICE>" ! \
  audioconvert ! audioresample ! \
  audio/x-raw,rate=48000,channels=2,format=S16LE ! \
  opusenc frame-size=10 bitrate=160000 ! \
  rtpopuspay ! \
  udpsink host=224.0.0.1 port=5004 auto-multicast=true
Explanation:

opusenc frame-size=10 → 10 ms frames (the sweet spot: low latency, still efficient).

bitrate=160000 → 160 kbps (stereo, transparent). You can go up to 510 kbps if you want lossless‑like quality.

rtpopuspay → packetises Opus inside RTP with proper timestamps.

udpsink host=224.0.0.1 auto-multicast=true → sends to multicast group 224.0.0.1; all devices on the LAN can join.

Windows alternative (WASAPI loopback):

bash
gst-launch-1.0 -v \
  wasapisrc loopback=true ! \
  audioconvert ! audioresample ! \
  audio/x-raw,rate=48000,channels=2 ! \
  opusenc frame-size=10 bitrate=160000 ! \
  rtpopuspay ! \
  udpsink host=224.0.0.1 port=5004 auto-multicast=true
3.4 Client pipeline (each friend’s device)
Friends run this on their own machine (Linux/macOS/Windows, assuming GStreamer installed). They plug in earphones and make sure the default audio sink points to them.

bash
gst-launch-1.0 -v \
  udpsrc multicast-group=224.0.0.1 port=5004 \
  caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! \
  rtpjitterbuffer latency=10 ! \
  rtpopusdepay ! \
  opusdec ! \
  audioconvert ! audioresample ! \
  autoaudiosink
The key tuning knob is latency=10 (in milliseconds). This sets the size of the jitter buffer. It must be at least as large as the expected network jitter. On a quiet wired LAN, 5–10 ms is often enough; Wi‑Fi may need 20–40 ms, increasing overall delay.

If clients hear dropouts, increase latency to 20 or 30. If you want to measure actual jitter, run the pipeline with -v and watch the “jitter” stats.

4. Getting lip‑sync right
Because the video stays on the laptop screen, the total audio pipeline delay must be imperceptible (<45 ms). Here’s how to keep it low:

Use a wired Ethernet connection – Wi‑Fi easily adds 20–50 ms of variable latency, ruining sync.

Stick to 10 ms Opus frames – shorter frames reduce encoder/decoder algorithmic delay.

Set the jitter buffer to the minimum that doesn’t cause glitches. Start with latency=10 and increase only if needed.

Avoid re‑sampling or unnecessary conversions in the pipeline. The example pipeline uses audioresample to force 48 kHz; that’s fine.

If your movie player supports it, you can add a video delay to the laptop screen equal to the measured audio latency. For example, in mpv you can press +/- to adjust audio/video sync (but that shifts audio, not video). To delay video you would need to use a video player that can buffer the video output (e.g., OBS Studio with a “Render Delay” filter, then fullscreen the preview). This is more complex, so focusing on minimal latency is the cleaner route.

5. Advanced: measuring and matching latency
If you find the out‑of‑the‑box latency is still noticeable (e.g., >60 ms), you can:

Measure end‑to‑end delay by generating a click sound (e.g., a short pulse) from the laptop and recording both the screen flash and the headphone output with a high‑speed camera / microphone. Then calculate the offset.

Add a video delay using a loopback screen capture with a delay filter. For instance, you could capture the movie window with OBS, apply a “Render Delay” filter (set to the measured audio delay), and project the delayed preview to the laptop screen. This works but adds complexity.

6. Why not AAC / other approaches?
AAC – standard AAC (AAC‑LC) uses 1024‑sample frames (~21 ms at 48 kHz) and incurs additional delay from the psychoacoustic model. AAC‑LD (Low Delay) can match Opus’s latency, but Opus is more flexible (2.5–60 ms frames), royalty‑free, and generally provides better quality at a given bitrate.

PCM (uncompressed) – latency can be <5 ms, but a 48 kHz/16‑bit stereo stream requires ~1.5 Mbps. On a LAN that’s fine, but multicast to several Wi‑Fi clients may cause congestion. Opus at 160 kbps is far more bandwidth‑efficient.

RTP multicast vs. separate unicast streams – Multicast avoids duplicating packets; the server sends once and the switch replicates. This keeps the server load minimal and latency identical for all listeners.

7. Taking it further – custom application
If you want to wrap this in a dedicated app rather than command‑line GStreamer:

Embed GStreamer in a Python/Go/Rust/C application. Python’s gi bindings let you build the same pipeline programmatically.

For an all‑in‑one Rust crate, use gstreamer-rs (the official Rust bindings). Example skeleton:

rust
// Server:
pipeline.add_many(&[pulsesrc, audioconvert, resample, capsfilter,
                    opusenc, rtpopuspay, udpsink])?;
The same logic applies: capture loopback, Opus 10 ms, RTP multicast, jitter buffer of 10 ms on the client.

Summary
With GStreamer, Opus, and RTP multicast you can build a high‑quality, ultra‑low‑latency local‑network audio streaming system in just a couple of command lines. The pipeline is:

Server captures system audio → Opus 10 ms frames → RTP → multicast.
Client receives multicast RTP → 10 ms jitter buffer → Opus decode → play.

Tune the jitter buffer and codec bitrate to your taste, and you’ll have studio‑grade wireless audio that stays in perfect sync with the movie on screen. If you need help adapting the pipeline to your specific OS or audio hardware, just ask.