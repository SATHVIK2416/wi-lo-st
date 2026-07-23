@echo off
echo =========================================================
echo  Wi-Lo-St GStreamer Client Receiver (Windows)
echo =========================================================
echo  Receiving multicast audio stream from 224.0.0.1:5004...
echo  Jitter buffer latency: 10ms
echo.
gst-launch-1.0 -v ^
  udpsrc multicast-group=224.0.0.1 port=5004 ^
  caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! ^
  rtpjitterbuffer latency=10 ! ^
  rtpopusdepay ! ^
  opusdec ! ^
  audioconvert ! audioresample ! ^
  autoaudiosink
pause
