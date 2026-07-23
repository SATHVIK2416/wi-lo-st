#!/usr/bin/env bash
echo "========================================================="
echo " Wi-Lo-St GStreamer Server Launcher (Linux PulseAudio / macOS)"
echo "========================================================="
echo "Streaming audio to multicast group 224.0.0.1:5004..."

MONITOR_DEV="${1:-$(pactl list sources short 2>/dev/null | grep monitor | head -n 1 | cut -f2)}"

if [ -z "$MONITOR_DEV" ]; then
  echo "No PulseAudio monitor device detected automatically."
  echo "Usage: ./gstreamer-server.sh <MONITOR_DEVICE_NAME>"
  exit 1
fi

echo "Using audio source monitor: $MONITOR_DEV"

gst-launch-1.0 -v \
  pulsesrc device="$MONITOR_DEV" ! \
  audioconvert ! audioresample ! \
  audio/x-raw,rate=48000,channels=2,format=S16LE ! \
  opusenc frame-size=10 bitrate=160000 ! \
  rtpopuspay ! \
  udpsink host=224.0.0.1 port=5004 auto-multicast=true
