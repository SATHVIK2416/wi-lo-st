@echo off
echo =========================================================
echo  Wi-Lo-St GStreamer Server Launcher (Windows WASAPI Loopback)
echo =========================================================
echo  Streaming system audio to multicast group 224.0.0.1:5004...
echo  Opus 10ms frames @ 160 kbps
echo.
gst-launch-1.0 -v ^
  wasapisrc loopback=true ! ^
  audioconvert ! audioresample ! ^
  audio/x-raw,rate=48000,channels=2 ! ^
  opusenc frame-size=10 bitrate=160000 ! ^
  rtpopuspay ! ^
  udpsink host=224.0.0.1 port=5004 auto-multicast=true
pause
