// Wi-Lo-St Core Client JavaScript Application (v2 - Crack/Pop Fixed)
document.addEventListener('DOMContentLoaded', () => {
  // =============================================
  // 1. DOM ELEMENT REFERENCES (all at top)
  // =============================================
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabPanels = document.querySelectorAll('.tab-panel');

  // Stream Config Inputs
  const osSelect = document.getElementById('os-select');
  const multicastIpInput = document.getElementById('multicast-ip');
  const multicastPortInput = document.getElementById('multicast-port');
  const opusBitrateInput = document.getElementById('opus-bitrate');
  const bitrateDisplay = document.getElementById('bitrate-display');
  const frameSizeSelect = document.getElementById('frame-size');
  const jitterBufInput = document.getElementById('jitter-buf');
  const deviceNameInput = document.getElementById('device-name');
  const deviceOverrideGroup = document.getElementById('device-override-group');

  // Command Outputs
  const cmdServerOutput = document.getElementById('cmd-server-output');
  const cmdClientOutput = document.getElementById('cmd-client-output');
  const btnCopyServerCmd = document.getElementById('btn-copy-server-cmd');
  const btnCopyClientCmd = document.getElementById('btn-copy-client-cmd'); // added in HTML

  // Header Status
  const broadcastBadge = document.getElementById('broadcast-badge');
  const broadcastStatusText = document.getElementById('broadcast-status-text');
  const connectedCount = document.getElementById('connected-count');
  const latencyVal = document.getElementById('latency-val');
  const ipAddressList = document.getElementById('ip-address-list');

  // Receiver Controls
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

  // Sync Calibrator
  const syncFlashBox = document.getElementById('sync-flash-box');
  const syncFlashText = document.getElementById('sync-flash-text');
  const btnTogglePulse = document.getElementById('btn-toggle-pulse');
  const btnDelayMinus = document.getElementById('btn-delay-minus');
  const btnDelayPlus = document.getElementById('btn-delay-plus');
  const calibDelayDisplay = document.getElementById('calib-delay-display');

  // Broadcast Buttons
  const btnWebBroadcast = document.getElementById('btn-web-broadcast');
  const btnScreenBroadcast = document.getElementById('btn-screen-broadcast');
  const btnSynthBroadcast = document.getElementById('btn-synth-broadcast');
  const secureNotice = document.getElementById('secure-notice');

  // =============================================
  // 2. STATE VARIABLES
  // =============================================
  let audioCtx = null;
  let gainNode = null;
  let delayNode = null;
  let analyser = null;
  let isWebBroadcasting = false;
  let isReceivingAudio = false;
  let ws = null;
  let pulseInterval = null;
  let pingInterval = null;

  // Ring buffer & worklet/fallback
  let ringBufferStorage = new Float32Array(48000 * 2);
  let ringWritePos = 0;
  let ringReadPos = 0;
  let ringAvailable = 0;
  let workletNode = null;
  let fallbackProcessor = null;
  let dummyInputNode = null;
  let silenceTimeout = null;

  // =============================================
  // 3. TAB SWITCHING
  // =============================================
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetTab = btn.getAttribute('data-tab');
      tabBtns.forEach(b => b.classList.remove('active'));
      tabPanels.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(targetTab).classList.add('active');
    });
  });

  // =============================================
  // 4. SERVER INFO & GStreamer COMMAND GENERATOR
  // =============================================
  async function fetchServerInfo() {
    try {
      const res = await fetch('/api/info');
      const data = await res.json();
      const p = data.portHttp || data.port || window.location.port || 3000;
      const pSsl = data.portHttps || 3443;

      if (data.localIps && data.localIps.length > 0) {
        ipAddressList.innerHTML = data.localIps.map(ip => `
          <div class="ip-pill"><i class="fa-solid fa-wifi"></i> http://${ip.address}:${p}</div>
        `).join('');
      } else {
        ipAddressList.innerHTML = `<div class="ip-pill">http://localhost:${p}</div>`;
      }

      if (secureNotice && !window.isSecureContext && 
          window.location.hostname !== 'localhost' && 
          window.location.hostname !== '127.0.0.1') {
        secureNotice.innerHTML = `
          <i class="fa-solid fa-shield-halved"></i>
          <span><b>Host Laptop Note:</b> Browser Web Audio Capture requires running on 
          <a href="http://localhost:${p}" style="color: var(--accent-cyan); font-weight: 700; text-decoration: underline;">http://localhost:${p}</a> or 
          <a href="https://${window.location.hostname}:${pSsl}" style="color: var(--accent-cyan); font-weight: 700; text-decoration: underline;">https://${window.location.hostname}:${pSsl}</a></span>
        `;
        secureNotice.style.display = 'flex';
      }

      if (data.platform === 'win32') osSelect.value = 'windows';
      else if (data.platform === 'darwin') osSelect.value = 'macOS';
      else osSelect.value = 'linux';

      updateGStreamerCommands();
    } catch (e) {
      console.warn('Unable to fetch server info, using defaults');
    }
  }

  function updateGStreamerCommands() {
    const os = osSelect.value;
    const host = multicastIpInput.value.trim() || '224.0.0.1';
    const port = multicastPortInput.value.trim() || '5004';
    const bitrate = opusBitrateInput.value;
    const frameSize = frameSizeSelect.value;
    const jitter = jitterBufInput.value;
    const customDevice = deviceNameInput.value.trim();

    bitrateDisplay.textContent = `${Math.round(bitrate / 1000)} kbps`;
    deviceOverrideGroup.style.display = (os === 'linux' || os === 'macOS') ? 'block' : 'none';

    let serverCmd = '';
    // Simple client pipeline for phones - just copy and run if needed
    let clientCmd = `gst-launch-1.0 -v udpsrc multicast-group=${host} port=${port} caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS" ! rtpjitterbuffer latency=500 ! rtpopusdepay ! opusdec ! audioconvert ! autoaudiosink`;

    if (os === 'windows') {
      serverCmd = `gst-launch-1.0 -v wasapisrc loopback=true ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! opusenc frame-size=${frameSize} bitrate=${bitrate} music-mode=true ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`;
    } else if (os === 'linux') {
      const dev = customDevice || '<LOOPBACK_MONITOR_DEVICE>';
      serverCmd = `gst-launch-1.0 -v pulsesrc device="${dev}" ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2,format=S16LE ! opusenc frame-size=${frameSize} bitrate=${bitrate} music-mode=true ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`;
    } else if (os === 'macOS') {
      const dev = customDevice || 'BlackHole 2ch';
      serverCmd = `gst-launch-1.0 -v osxaudiosrc device="${dev}" ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! opusenc frame-size=${frameSize} bitrate=${bitrate} music-mode=true ! rtpopuspay ! udpsink host=${host} port=${port} auto-multicast=true`;
    }

    cmdServerOutput.textContent = serverCmd;
    cmdClientOutput.textContent = clientCmd;
  }

  // Input listeners for dynamic updates
  [osSelect, multicastIpInput, multicastPortInput, opusBitrateInput, 
   frameSizeSelect, jitterBufInput, deviceNameInput].forEach(el => {
    el.addEventListener('input', updateGStreamerCommands);
    el.addEventListener('change', updateGStreamerCommands);
  });

  // Copy command buttons
  btnCopyServerCmd.addEventListener('click', () => {
    navigator.clipboard.writeText(cmdServerOutput.textContent);
    btnCopyServerCmd.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
    setTimeout(() => { btnCopyServerCmd.innerHTML = '<i class="fa-solid fa-copy"></i> Copy GStreamer Cmd'; }, 2000);
  });

  if (btnCopyClientCmd) {
    btnCopyClientCmd.addEventListener('click', () => {
      navigator.clipboard.writeText(cmdClientOutput.textContent);
      btnCopyClientCmd.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
      setTimeout(() => { btnCopyClientCmd.innerHTML = '<i class="fa-solid fa-copy"></i>'; }, 2000);
    });
  }

  // =============================================
  // 5. WEBSOCKET & NETWORK
  // =============================================
  function initWebSocket() {
    if (ws) {
      try { ws.close(); } catch(e) {}
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}`;
    ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
      console.log('WebSocket connected.');
      startPingLoop();
    };

    ws.onmessage = async (event) => {
      if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'pong') {
            latencyVal.textContent = Math.max(1, Date.now() - msg.timestamp);
          } else if (msg.type === 'stats_update') {
            connectedCount.textContent = msg.stats.activeClients || 0;
            if (msg.stats.isBroadcasting) {
              setBroadcastState(true, 'Broadcasting Live Audio');
            } else {
              setBroadcastState(false, 'Server Ready');
            }
          }
        } catch (e) {}
      } else if (isReceivingAudio && audioCtx) {
        let bufferData = event.data;
        if (event.data instanceof Blob) {
          bufferData = await event.data.arrayBuffer();
        }
        if (bufferData instanceof ArrayBuffer) {
          await playAudioPacket(bufferData);
        }
      }
    };

    ws.onclose = () => {
      if (pingInterval) clearInterval(pingInterval);
      setTimeout(initWebSocket, 3000);
    };
  }

  function startPingLoop() {
    if (pingInterval) clearInterval(pingInterval);
    pingInterval = setInterval(() => {
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
      broadcastStatusText.textContent = text;
    }
  }

  // =============================================
  // 6. AUDIO WORKLET & FALLBACK RING BUFFER
  // =============================================
  const workletCode = `
    class RingBufferWorklet extends AudioWorkletProcessor {
      constructor() {
        super();
        this.capacity = 48000 * 2;
        this.buffer = new Float32Array(this.capacity);
        this.readIndex = 0;
        this.writeIndex = 0;
        this.count = 0;

        this.port.onmessage = (e) => {
          if (e.data.type === 'audio') {
            const samples = e.data.samples;
            for (let i = 0; i < samples.length; i++) {
              this.buffer[this.writeIndex] = samples[i];
              this.writeIndex = (this.writeIndex + 1) % this.capacity;
              if (this.count < this.capacity) {
                this.count++;
              } else {
                this.readIndex = (this.readIndex + 1) % this.capacity;
              }
            }
          } else if (e.data.type === 'clear') {
            this.buffer.fill(0);
            this.readIndex = 0;
            this.writeIndex = 0;
            this.count = 0;
          }
        };
      }

      process(inputs, outputs) {
        const output = outputs[0];
        if (!output || !output[0]) return true;
        const channel = output[0];
        for (let i = 0; i < channel.length; i++) {
          if (this.count > 0) {
            channel[i] = this.buffer[this.readIndex];
            this.readIndex = (this.readIndex + 1) % this.capacity;
            this.count--;
          } else {
            channel[i] = 0.0;
          }
        }
        return true;
      }
    }
    registerProcessor('ring-buffer-worklet', RingBufferWorklet);
  `;

  function pushToRingBuffer(samples) {
    for (let i = 0; i < samples.length; i++) {
      ringBufferStorage[ringWritePos] = samples[i];
      ringWritePos = (ringWritePos + 1) % ringBufferStorage.length;
      if (ringAvailable < ringBufferStorage.length) {
        ringAvailable++;
      } else {
        ringReadPos = (ringReadPos + 1) % ringBufferStorage.length;
      }
    }
  }

  function readFromRingBuffer(output) {
    for (let i = 0; i < output.length; i++) {
      if (ringAvailable > 0) {
        output[i] = ringBufferStorage[ringReadPos];
        ringReadPos = (ringReadPos + 1) % ringBufferStorage.length;
        ringAvailable--;
      } else {
        output[i] = 0.0;
      }
    }
  }

  function clearRingBuffer() {
    ringBufferStorage.fill(0);
    ringWritePos = 0;
    ringReadPos = 0;
    ringAvailable = 0;
  }

  // =============================================
  // 7. RECEIVER START / STOP (CLEAN)
  // =============================================
  function stopAudioReceiver() {
    isReceivingAudio = false;
    clearRingBuffer();

    if (silenceTimeout) {
      clearTimeout(silenceTimeout);
      silenceTimeout = null;
    }

    // Smoothly fade out
    if (gainNode) {
      try { gainNode.gain.setTargetAtTime(0, audioCtx.currentTime, 0.02); } catch(e) {}
    }

    // Disconnect and nullify all processing nodes
    if (dummyInputNode) {
      try { dummyInputNode.stop(); } catch(e) {}
      try { dummyInputNode.disconnect(); } catch(e) {}
      dummyInputNode = null;
    }
    if (fallbackProcessor) {
      try { fallbackProcessor.disconnect(); } catch(e) {}
      fallbackProcessor = null;
    }
    if (workletNode) {
      try { workletNode.disconnect(); } catch(e) {}
      workletNode = null;
    }
    if (delayNode) {
      try { delayNode.disconnect(); } catch(e) {}
    }
    if (gainNode) {
      try { gainNode.disconnect(); } catch(e) {}
    }

    playPrompt.style.display = 'flex';
    visualWave.classList.add('paused');
    playerStatus.textContent = 'Receiver Offline';
  }

  btnStartAudio.addEventListener('click', async () => {
    if (isReceivingAudio) {
      stopAudioReceiver();
      return;
    }

    // Initialize AudioContext if needed
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
    }
    if (audioCtx.state === 'suspended') {
      await audioCtx.resume();
    }

    // Create fresh graph nodes
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;

    gainNode = audioCtx.createGain();
    gainNode.gain.value = parseFloat(volumeControl.value || 1.0);

    delayNode = audioCtx.createDelay(1.0);
    delayNode.delayTime.value = Math.max(0, parseInt(audioDelayOffset.value) / 1000);

    // Connect: worklet/fallback -> delay -> gain -> analyser -> destination
    delayNode.connect(gainNode);
    gainNode.connect(analyser);
    analyser.connect(audioCtx.destination);

    // Load AudioWorklet if possible
    if (!workletNode && audioCtx.audioWorklet) {
      try {
        const blob = new Blob([workletCode], { type: 'application/javascript' });
        const workletUrl = URL.createObjectURL(blob);
        await audioCtx.audioWorklet.addModule(workletUrl);
        workletNode = new AudioWorkletNode(audioCtx, 'ring-buffer-worklet');
      } catch (err) {
        console.warn('AudioWorklet failed, using ScriptProcessor fallback:', err);
      }
    }

    // Fallback processor
    if (!workletNode && !fallbackProcessor) {
      // Try zero input channels first
      try {
        fallbackProcessor = audioCtx.createScriptProcessor(2048, 0, 1);
      } catch (e) {
        // Some browsers require at least one input channel
        fallbackProcessor = audioCtx.createScriptProcessor(2048, 1, 1);
        const dummyBuf = audioCtx.createBuffer(1, 2048, audioCtx.sampleRate);
        dummyInputNode = audioCtx.createBufferSource();
        dummyInputNode.buffer = dummyBuf;
        dummyInputNode.loop = true;
        dummyInputNode.start();
        dummyInputNode.connect(fallbackProcessor);
      }
      fallbackProcessor.onaudioprocess = (e) => {
        const out = e.outputBuffer.getChannelData(0);
        readFromRingBuffer(out);
      };
    }

    // Connect active engine to graph
    if (workletNode) {
      workletNode.connect(delayNode);
    } else if (fallbackProcessor) {
      fallbackProcessor.connect(delayNode);
    }

    isReceivingAudio = true;
    playPrompt.style.display = 'none';
    visualWave.classList.remove('paused');
    playerStatus.textContent = 'Streaming Live Audio';

    startVisualizerCanvas();
  });

  // =============================================
  // 8. VOLUME & DELAY CONTROLS (SMOOTH)
  // =============================================
  volumeControl.addEventListener('input', () => {
    const val = parseFloat(volumeControl.value);
    volumeVal.textContent = `${Math.round(val * 100)}%`;
    if (gainNode) {
      gainNode.gain.setTargetAtTime(val, audioCtx.currentTime, 0.05);
    }
  });

  clientJitter.addEventListener('input', () => {
    clientJitterVal.textContent = `${clientJitter.value} ms`;
    bufferMs.textContent = clientJitter.value;
  });

  audioDelayOffset.addEventListener('input', () => {
    const ms = parseInt(audioDelayOffset.value);
    delayOffsetVal.textContent = `${ms} ms`;
    calibDelayDisplay.textContent = `${ms} ms`; // keep calibrator display in sync
    if (delayNode) {
      delayNode.delayTime.value = Math.max(0, ms / 1000);
    }
  });

  // =============================================
  // 9. HIGH-QUALITY ASYNC AUDIO PACKET PLAYBACK (FIXED)
  // =============================================
  async function playAudioPacket(arrayBuffer) {
    if (!audioCtx || !isReceivingAudio) return;
    try {
      if (audioCtx.state === 'suspended') await audioCtx.resume();
      if (arrayBuffer.byteLength <= 4) return;

      const view = new DataView(arrayBuffer);
      let packetSampleRate = 48000;
      let pcmOffset = 0;
      const headerRate = view.getUint32(0, true);
      if (headerRate >= 8000 && headerRate <= 192000) {
        packetSampleRate = headerRate;
        pcmOffset = 4;
      }

      const int16 = new Int16Array(arrayBuffer, pcmOffset);
      if (int16.length === 0) return;

      const targetSampleRate = audioCtx.sampleRate;
      let float32;

      // Resample if necessary using OfflineAudioContext (high quality)
      if (packetSampleRate !== targetSampleRate) {
        const offlineCtx = new OfflineAudioContext(1, int16.length, packetSampleRate);
        const buffer = offlineCtx.createBuffer(1, int16.length, packetSampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < int16.length; i++) {
          data[i] = int16[i] / 32768.0; // int16 to float
        }
        const source = offlineCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(offlineCtx.destination);
        source.start();
        const rendered = await offlineCtx.startRendering();
        float32 = rendered.getChannelData(0);
      } else {
        // No resampling needed, just convert
        float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) {
          float32[i] = int16[i] / 32768.0;
        }
      }

      // Apply soft clipping
      for (let i = 0; i < float32.length; i++) {
        if (float32[i] > 0.95) float32[i] = 0.95 + (float32[i] - 0.95) * 0.1;
        if (float32[i] < -0.95) float32[i] = -0.95 + (float32[i] + 0.95) * 0.1;
      }

      // Smooth gain (avoids clicks)
      if (gainNode) {
        const targetVol = parseFloat(volumeControl.value || 1.0);
        gainNode.gain.setTargetAtTime(targetVol, audioCtx.currentTime, 0.02);
      }

      // Silence watchdog: if no audio for 300ms, fade out and clear
      if (silenceTimeout) clearTimeout(silenceTimeout);
      silenceTimeout = setTimeout(() => {
        if (gainNode) gainNode.gain.setTargetAtTime(0, audioCtx.currentTime, 0.03);
        clearRingBuffer();
        if (workletNode) workletNode.port.postMessage({ type: 'clear' });
      }, 300);

      // Route to worklet or fallback buffer
      if (workletNode) {
        workletNode.port.postMessage({ type: 'audio', samples: float32 });
      } else {
        pushToRingBuffer(float32);
      }
    } catch (e) {
      console.error('Audio playback exception:', e);
    }
  }

  // =============================================
  // 10. BROADCASTER (MIC / SCREEN / SYNTH) - FULLY CLEANED
  // =============================================
  let activeBroadcastStream = null;
  let activeBroadcastCtx = null;
  let synthOscillator = null;

  function stopBroadcastEngine() {
    isWebBroadcasting = false;
    if (activeBroadcastStream) {
      activeBroadcastStream.getTracks().forEach(track => track.stop());
      activeBroadcastStream = null;
    }
    if (synthOscillator) {
      try { synthOscillator.stop(); synthOscillator.disconnect(); } catch(e) {}
      synthOscillator = null;
    }
    if (activeBroadcastCtx) {
      try { activeBroadcastCtx.close(); } catch(e) {}
      activeBroadcastCtx = null;
    }
  }

  function startAudioStreamProcessing(stream) {
    stopBroadcastEngine();
    isWebBroadcasting = true; // RE-ENABLE after stopBroadcastEngine wipes it
    activeBroadcastStream = stream;
    activeBroadcastCtx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
    if (activeBroadcastCtx.state === 'suspended') activeBroadcastCtx.resume();

    const source = activeBroadcastCtx.createMediaStreamSource(stream);
    const processor = activeBroadcastCtx.createScriptProcessor(2048, 1, 1);
    source.connect(processor);

    // Mute local speakers
    const muteGain = activeBroadcastCtx.createGain();
    muteGain.gain.value = 0;
    processor.connect(muteGain);
    muteGain.connect(activeBroadcastCtx.destination);

    const sampleRate = activeBroadcastCtx.sampleRate || 48000;
    processor.onaudioprocess = (e) => {
      if (ws && ws.readyState === WebSocket.OPEN && isWebBroadcasting) {
        const inputData = e.inputBuffer.getChannelData(0);
        const packet = new ArrayBuffer(4 + inputData.length * 2);
        const dataView = new DataView(packet);
        dataView.setUint32(0, sampleRate, true);
        const pcm16 = new Int16Array(packet, 4);
        for (let i = 0; i < inputData.length; i++) {
          pcm16[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7FFF;
        }
        ws.send(packet);
      }
    };
  }

  function handleSecureContextCheck() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert('Your browser does not support media capture. Please use a modern browser and ensure the page is served over HTTPS or localhost.');
      return false;
    }
    return true;
  }

  // Mic Broadcast
  btnWebBroadcast.addEventListener('click', async () => {
    if (!isWebBroadcasting) {
      if (!handleSecureContextCheck()) return;
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ 
          audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } 
        });
        startAudioStreamProcessing(stream);
        btnWebBroadcast.classList.replace('btn-primary', 'btn-secondary');
        btnWebBroadcast.innerHTML = '<i class="fa-solid fa-stop"></i> Stop Broadcast';
        setBroadcastState(true, 'Mic Audio Broadcasting');
      } catch (err) {
        alert('Could not capture microphone: ' + err.message);
      }
    } else {
      stopBroadcastEngine();
      btnWebBroadcast.classList.replace('btn-secondary', 'btn-primary');
      btnWebBroadcast.innerHTML = '<i class="fa-solid fa-microphone-lines"></i> Start Mic/Audio Broadcast';
      setBroadcastState(false, 'Server Ready');
    }
  });

  // Screen / Movie Tab Broadcast
  btnScreenBroadcast.addEventListener('click', async () => {
    if (!isWebBroadcasting) {
      if (!handleSecureContextCheck()) return;
      try {
        const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
        startAudioStreamProcessing(stream);
        btnScreenBroadcast.classList.replace('btn-secondary', 'btn-primary');
        btnScreenBroadcast.innerHTML = '<i class="fa-solid fa-stop"></i> Stop Movie Tab Broadcast';
        setBroadcastState(true, 'Screen Audio Broadcasting');
      } catch (err) {
        console.warn('Screen capture cancelled or denied', err);
      }
    } else {
      stopBroadcastEngine();
      btnScreenBroadcast.classList.replace('btn-primary', 'btn-secondary');
      btnScreenBroadcast.innerHTML = '<i class="fa-solid fa-desktop"></i> Broadcast Movie Tab Audio';
      setBroadcastState(false, 'Server Ready');
    }
  });

  // Synth Test Tone
  btnSynthBroadcast.addEventListener('click', () => {
    if (!isWebBroadcasting) {
      stopBroadcastEngine();
      isWebBroadcasting = true; // RE-ENABLE after wipe
      activeBroadcastCtx = new (window.AudioContext || window.webkitAudioContext)();
      if (activeBroadcastCtx.state === 'suspended') activeBroadcastCtx.resume();

      synthOscillator = activeBroadcastCtx.createOscillator();
      synthOscillator.type = 'sine';
      synthOscillator.frequency.value = 440;

      const processor = activeBroadcastCtx.createScriptProcessor(2048, 1, 1);
      synthOscillator.connect(processor);

      const muteGain = activeBroadcastCtx.createGain();
      muteGain.gain.value = 0;
      processor.connect(muteGain);
      muteGain.connect(activeBroadcastCtx.destination);

      synthOscillator.start();
      const sampleRate = activeBroadcastCtx.sampleRate || 48000;
      processor.onaudioprocess = (e) => {
        if (ws && ws.readyState === WebSocket.OPEN && isWebBroadcasting) {
          const inputData = e.inputBuffer.getChannelData(0);
          const packet = new ArrayBuffer(4 + inputData.length * 2);
          const dataView = new DataView(packet);
          dataView.setUint32(0, sampleRate, true);
          const pcm16 = new Int16Array(packet, 4);
          for (let i = 0; i < inputData.length; i++) {
            pcm16[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7FFF;
          }
          ws.send(packet);
        }
      };

      btnSynthBroadcast.classList.replace('btn-primary', 'btn-secondary');
      btnSynthBroadcast.innerHTML = '<i class="fa-solid fa-stop"></i> Stop Synth Tone';
      setBroadcastState(true, 'Synth Tone Broadcasting');
    } else {
      isWebBroadcasting = false;
      if (synthOscillator) {
        try { synthOscillator.stop(); synthOscillator.disconnect(); } catch(e) {}
        synthOscillator = null;
      }
      if (activeBroadcastCtx) {
        try { activeBroadcastCtx.close(); } catch(e) {}
        activeBroadcastCtx = null;
      }
      btnSynthBroadcast.classList.replace('btn-secondary', 'btn-primary');
      btnSynthBroadcast.innerHTML = '<i class="fa-solid fa-wave-square"></i> Broadcast Test Tone';
      setBroadcastState(false, 'Server Ready');
    }
  });

  // =============================================
  // 11. VISUALIZER CANVAS (WITH RESIZE)
  // =============================================
  function startVisualizerCanvas() {
    const canvas = document.getElementById('visualizer-canvas');
    const ctx = canvas.getContext('2d');
    const bufferLength = analyser ? analyser.frequencyBinCount : 64;
    const dataArray = new Uint8Array(bufferLength);

    function resizeCanvas() {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    }
    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();

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

  // =============================================
  // 12. LIP-SYNC CALIBRATOR (FULLY FUNCTIONAL)
  // =============================================
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

  // Buttons directly adjust the delay slider
  btnDelayMinus.addEventListener('click', () => {
    let currentVal = parseInt(audioDelayOffset.value);
    let newVal = Math.max(0, currentVal - 5);
    audioDelayOffset.value = newVal;
    audioDelayOffset.dispatchEvent(new Event('input'));
  });

  btnDelayPlus.addEventListener('click', () => {
    let currentVal = parseInt(audioDelayOffset.value);
    let newVal = Math.min(200, currentVal + 5);
    audioDelayOffset.value = newVal;
    audioDelayOffset.dispatchEvent(new Event('input'));
  });

  function triggerSyncPulse() {
    // Flash visual
    syncFlashBox.classList.add('flash');
    setTimeout(() => syncFlashBox.classList.remove('flash'), 80);

    // Play beep through the same delayNode (so it respects the slider)
    if (audioCtx) {
      const osc = audioCtx.createOscillator();
      const toneGain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 1000;
      toneGain.gain.setValueAtTime(0.3, audioCtx.currentTime);
      toneGain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.08);

      osc.connect(toneGain);
      if (delayNode) {
        toneGain.connect(delayNode);  // <- goes through the same delay!
      } else {
        toneGain.connect(audioCtx.destination);
      }
      osc.start();
      osc.stop(audioCtx.currentTime + 0.15);
    }
  }

  // =============================================
  // 13. INITIALIZATION
  // =============================================
  window.copyText = function(id) {
    const text = document.getElementById(id).textContent;
    navigator.clipboard.writeText(text);
  };

  fetchServerInfo();
  initWebSocket();
});