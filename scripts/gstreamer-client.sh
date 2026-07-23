#!/usr/bin/env bash
echo "========================================================="
echo " Wi-Lo-St GStreamer Client Receiver (Linux / macOS)"
echo "========================================================="
echo "Receiving multicast audio stream from 224.0.0.1:5004..."

JITTER="${1:-10}"

gst-launch-1.0 -v \
  udpsrc multicast-group=224.0.0.1 port=5004 \
  caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! \
  rtpjitterbuffer latency="$JITTER" ! \
  rtpopusdepay ! \
  opusdec ! \
  audioconvert ! audioresample ! \
  autoaudiosink
