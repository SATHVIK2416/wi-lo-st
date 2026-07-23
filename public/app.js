// Wi-Lo-St Core Client JavaScript Application
document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabPanels = document.querySelectorAll('.tab-panel');

  // Stream Configuration Inputs
  const osSelect = document.getElementById('os-select');
  const multicastIpInput = document.getElementById('multicast-ip');
  const multicastPortInput = document.getElementById('multicast-port');
  const opusBitrateInput = document.getElementById('opus-bitrate');
  const bitrateDisplay = document.getElementById('bitrate-display');
  const frameSizeSelect = document.getElementById('frame-size');
  const jitterBufInput = document.getElementById('jitter-buf');
  const deviceNameInput = document.getElementById('device-name');
  const deviceOverrideGroup = document.getElementById('device-override-group');

  // Command Output Elements
  const cmdServerOutput = document.getElementById('cmd-server-output');
  const cmdClientOutput = document.getElementById('cmd-client-output');
  const btnCopyServerCmd = document.getElementById('btn-copy-server-cmd');
  const btnWebBroadcast = document.getElementById('btn-web-broadcast');

  // Header Elements
  const broadcastBadge = document.getElementById('broadcast-badge');
  const broadcastStatusText = document.getElementById('broadcast-status-text');
  const connectedCount = document.getElementById('connected-count');
  const latencyVal = document.getElementById('latency-val');
  const ipAddressList = document.getElementById('ip-address-list');

  // Receiver Elements
  const btnStartAudio = document.getElementById('btn-start-audio');
  const playPrompt = document.getElementById('play-prompt');
  const visualWave = document.getElementById('visual-wave');
  const playerStatus = document.getElementById('player-status');
  const volumeControl = document.getElementById('volume-control');
  const volumeVal = document.getElementById('volume-val');
  const clientJitter = document.getElementById('client-jitter');
  const clientJitterVal = document.getElementById('client-jitter-val');
  const audioDelayOffset = document.getElementById('audio-delay-offset');
  const delayOffsetVal = document.getElementById('delay-offset-val');
  const bufferMs = document.getElementById('buffer-ms');

  // Sync Calibrator Elements
  const syncFlashBox = document.getElementById('sync-flash-box');
  const syncFlashText = document.getElementById('sync-flash-text');
  const btnTogglePulse = document.getElementById('btn-toggle-pulse');
  const btnDelayMinus = document.getElementById('btn-delay-minus');
  const btnDelayPlus = document.getElementById('btn-delay-plus');
  const calibDelayDisplay = document.getElementById('calib-delay-display');

  // Web Audio Context & Visualizer state
  let audioCtx = null;
  let gainNode = null;
  let delayNode = null;
  let analyser = null;
  let isWebBroadcasting = false;
  let isReceivingAudio = false;
  let ws = null;
  let pulseInterval = null;
  let calibrationDelay = 0;

  // 1. Tab Switching Logic
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetTab = btn.getAttribute('data-tab');
      tabBtns.forEach(b => b.classList.remove('active'));
      tabPanels.forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      document.getElementById(targetTab).classList.add('active');
    });
  });

  // 2. Fetch Server Network Info
  async function fetchServerInfo() {
    try {
      const res = await fetch('/api/info');
      const data = await res.json();
      
      // Populate LAN IPs
      if (data.localIps && data.localIps.length > 0) {
        ipAddressList.innerHTML = data.localIps.map(ip => `
          <div class="ip-pill"><i class="fa-solid fa-wifi"></i> http://${ip.address}:${data.port}</div>
        `).join('');
      } else {
        ipAddressList.innerHTML = `<div class="ip-pill">http://localhost:${data.port}</div>`;
      }

      // Detect OS default
      if (data.platform === 'win32') {
        osSelect.value = 'windows';
      } else if (data.platform === 'darwin') {
        osSelect.value = 'macOS';
      } else {
        osSelect.value = 'linux';
      }
      updateGStreamerCommands();
    } catch (e) {
      console.warn('Unable to connect to server info API, using fallback UI defaults.');
    }
  }

  // 3. GStreamer Command Builder Update
  function updateGStreamerCommands() {
    const os = osSelect.value;
    const host = multicastIpInput.value.trim() || '224.0.0.1';
    const port = multicastPortInput.value.trim() || '5004';
    const bitrate = opusBitrateInput.value;
    const frameSize = frameSizeSelect.value;
    const jitter = jitterBufInput.value;
    const customDevice = deviceNameInput.value.trim();

    bitrateDisplay.textContent = `${Math.round(bitrate / 1000)} kbps`;

    // Toggle custom device input visibility for Linux / macOS
    if (os === 'linux' || os === 'macOS') {
      deviceOverrideGroup.style.display = 'block';
    } else {
      deviceOverrideGroup.style.display = 'none';
    }

    let serverCmd = '';
    let clientCmd = `gst-launch-1.0 -v udpsrc multicast-group=${host} port=${port} caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! rtpjitterbuffer latency=${jitter} ! rtpopusdepay ! opusdec ! audioconvert ! audioresample ! autoaudiosink`;

    if (os === 'windows') {
      serverCmd = `gst-launch-1.0 -v wasapisrc loopback=true ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! opusenc frame-size=${frameSize} bitrate=${bitrate} ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`;
    } else if (os === 'linux') {
      const dev = customDevice || '<LOOPBACK_MONITOR_DEVICE>';
      serverCmd = `gst-launch-1.0 -v pulsesrc device="${dev}" ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2,format=S16LE ! opusenc frame-size=${frameSize} bitrate=${bitrate} ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`;
    } else if (os === 'macOS') {
      const dev = customDevice || 'BlackHole 2ch';
      serverCmd = `gst-launch-1.0 -v osxaudiosrc device="${dev}" ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! opusenc frame-size=${frameSize} bitrate=${bitrate} ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`;
    }

    cmdServerOutput.textContent = serverCmd;
    cmdClientOutput.textContent = clientCmd;
  }

  // Event Listeners for form inputs
  osSelect.addEventListener('change', updateGStreamerCommands);
  multicastIpInput.addEventListener('input', updateGStreamerCommands);
  multicastPortInput.addEventListener('input', updateGStreamerCommands);
  opusBitrateInput.addEventListener('input', updateGStreamerCommands);
  frameSizeSelect.addEventListener('change', updateGStreamerCommands);
  jitterBufInput.addEventListener('input', updateGStreamerCommands);
  deviceNameInput.addEventListener('input', updateGStreamerCommands);

  // Copy command button
  btnCopyServerCmd.addEventListener('click', () => {
    navigator.clipboard.writeText(cmdServerOutput.textContent);
    btnCopyServerCmd.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
    setTimeout(() => {
      btnCopyServerCmd.innerHTML = '<i class="fa-solid fa-copy"></i> Copy GStreamer Command';
    }, 2000);
  });

  // 4. WebSocket Setup & Ping Measurement
  function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket connected.');
      startPingLoop();
    };

    ws.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'pong') {
            const rtt = Math.max(1, Date.now() - msg.timestamp);
            latencyVal.textContent = rtt;
          } else if (msg.type === 'stats_update') {
            connectedCount.textContent = msg.stats.activeClients || 0;
            if (msg.stats.isBroadcasting) {
              setBroadcastState(true, 'Multicast Server Active');
            }
          }
        } catch (e) {}
      } else if (event.data instanceof ArrayBuffer && isReceivingAudio && audioCtx) {
        // Play low-latency raw audio buffer packet
        playAudioPacket(event.data);
      }
    };

    ws.onclose = () => {
      setTimeout(initWebSocket, 3000);
    };
  }

  function startPingLoop() {
    setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }));
      }
    }, 2000);
  }

  function setBroadcastState(active, text) {
    if (active) {
      broadcastBadge.className = 'status-badge active';
      broadcastStatusText.textContent = text;
    } else {
      broadcastBadge.className = 'status-badge idle';
      broadcastStatusText.textContent = 'Server Ready';
    }
  }

  // 5. Web Audio Receiver Engine
  btnStartAudio.addEventListener('click', async () => {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
    }
    if (audioCtx.state === 'suspended') {
      await audioCtx.resume();
    }

    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;

    gainNode = audioCtx.createGain();
    gainNode.gain.value = parseFloat(volumeControl.value);

    delayNode = audioCtx.createDelay(1.0);
    delayNode.delayTime.value = Math.max(0, parseInt(audioDelayOffset.value) / 1000);

    // Audio graph: Source -> Delay -> Gain -> Analyser -> Output
    delayNode.connect(gainNode);
    gainNode.connect(analyser);
    analyser.connect(audioCtx.destination);

    isReceivingAudio = true;
    playPrompt.style.display = 'none';
    visualWave.classList.remove('paused');
    playerStatus.textContent = 'Streaming Live Audio';

    startVisualizerCanvas();
  });

  // Volume & Delay Controls
  volumeControl.addEventListener('input', () => {
    const val = parseFloat(volumeControl.value);
    volumeVal.textContent = `${Math.round(val * 100)}%`;
    if (gainNode) gainNode.gain.value = val;
  });

  clientJitter.addEventListener('input', () => {
    clientJitterVal.textContent = `${clientJitter.value} ms`;
    bufferMs.textContent = clientJitter.value;
  });

  audioDelayOffset.addEventListener('input', () => {
    delayOffsetVal.textContent = `${audioDelayOffset.value} ms`;
    if (delayNode) {
      delayNode.delayTime.value = Math.max(0, parseInt(audioDelayOffset.value) / 1000);
    }
  });

  // 6. Web Audio Direct Broadcaster (Browser Loopback / Mic Streamer)
  btnWebBroadcast.addEventListener('click', async () => {
    if (!isWebBroadcasting) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
        const mediaCtx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
        const source = mediaCtx.createMediaStreamSource(stream);
        
        // Use ScriptProcessor for real-time audio chunk capture
        const processor = mediaCtx.createScriptProcessor(512, 1, 1);
        source.connect(processor);
        processor.connect(mediaCtx.destination);

        processor.onaudioprocess = (e) => {
          if (ws && ws.readyState === WebSocket.OPEN) {
            const inputData = e.inputBuffer.getChannelData(0);
            const pcm16 = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
              pcm16[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7FFF;
            }
            ws.send(pcm16.buffer);
          }
        };

        isWebBroadcasting = true;
        btnWebBroadcast.classList.remove('btn-primary');
        btnWebBroadcast.classList.add('btn-secondary');
        btnWebBroadcast.innerHTML = '<i class="fa-solid fa-stop"></i> Stop Web Broadcast';
        setBroadcastState(true, 'Web Audio Broadcasting');
      } catch (err) {
        alert('Could not capture audio stream: ' + err.message);
      }
    } else {
      isWebBroadcasting = false;
      btnWebBroadcast.classList.remove('btn-secondary');
      btnWebBroadcast.classList.add('btn-primary');
      btnWebBroadcast.innerHTML = '<i class="fa-solid fa-microphone-lines"></i> Start Web Audio Broadcast';
      setBroadcastState(false, 'Server Ready');
    }
  });

  function playAudioPacket(arrayBuffer) {
    if (!audioCtx || !isReceivingAudio) return;
    try {
      const int16 = new Int16Array(arrayBuffer);
      const float32 = new Float32Array(int16.length);
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768.0;
      }
      const buffer = audioCtx.createBuffer(1, float32.length, audioCtx.sampleRate);
      buffer.getChannelData(0).set(float32);

      const src = audioCtx.createBufferSource();
      src.buffer = buffer;
      src.connect(delayNode);
      src.start();
    } catch (e) {}
  }

  // 7. Visualizer Canvas Animation
  function startVisualizerCanvas() {
    const canvas = document.getElementById('visualizer-canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;

    const bufferLength = analyser ? analyser.frequencyBinCount : 64;
    const dataArray = new Uint8Array(bufferLength);

    function renderFrame() {
      requestAnimationFrame(renderFrame);
      if (!analyser) return;

      analyser.getByteFrequencyData(dataArray);

      ctx.fillStyle = '#050811';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const barWidth = (canvas.width / bufferLength) * 2.5;
      let x = 0;

      for (let i = 0; i < bufferLength; i++) {
        const barHeight = (dataArray[i] / 255) * canvas.height * 0.8;
        const gradient = ctx.createLinearGradient(0, canvas.height, 0, 0);
        gradient.addColorStop(0, '#00f2fe');
        gradient.addColorStop(1, '#7f00ff');

        ctx.fillStyle = gradient;
        ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
        x += barWidth + 2;
      }
    }
    renderFrame();
  }

  // 8. Lip-Sync Calibrator Engine
  btnTogglePulse.addEventListener('click', () => {
    if (!pulseInterval) {
      btnTogglePulse.innerHTML = '<i class="fa-solid fa-square"></i> Stop Calibration Pulse';
      syncFlashText.textContent = 'PULSE ACTIVE - Align Screen Flash with Earphone Beep';
      pulseInterval = setInterval(triggerSyncPulse, 1000);
    } else {
      clearInterval(pulseInterval);
      pulseInterval = null;
      btnTogglePulse.innerHTML = '<i class="fa-solid fa-play"></i> Start Calibration Pulse (1 Pulse/sec)';
      syncFlashText.textContent = 'Click "Start Calibration Pulse" below';
      syncFlashBox.classList.remove('flash');
    }
  });

  btnDelayMinus.addEventListener('click', () => {
    calibrationDelay = Math.max(-200, calibrationDelay - 5);
    calibDelayDisplay.textContent = `${calibrationDelay} ms`;
  });

  btnDelayPlus.addEventListener('click', () => {
    calibrationDelay = Math.min(200, calibrationDelay + 5);
    calibDelayDisplay.textContent = `${calibrationDelay} ms`;
  });

  function triggerSyncPulse() {
    // 1. Flash visual canvas box
    syncFlashBox.classList.add('flash');
    setTimeout(() => {
      syncFlashBox.classList.remove('flash');
    }, 80);

    // 2. Play sharp 1000Hz audio beep tone on AudioContext
    if (audioCtx) {
      const osc = audioCtx.createOscillator();
      const toneGain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 1000;
      toneGain.gain.setValueAtTime(0.3, audioCtx.currentTime);
      toneGain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.08);

      const delayOffsetSec = Math.max(0, calibrationDelay / 1000);
      osc.connect(toneGain);
      toneGain.connect(audioCtx.destination);
      osc.start(audioCtx.currentTime + delayOffsetSec);
      osc.stop(audioCtx.currentTime + delayOffsetSec + 0.08);
    }
  }

  // Helper copy function
  window.copyText = function(id) {
    const text = document.getElementById(id).textContent;
    navigator.clipboard.writeText(text);
  };

  // Initialize
  fetchServerInfo();
  initWebSocket();
});
