Your revised code fixes many original issues (duplicate `playAudioPacket`, broadcast cleanup, node disconnection), but several important bugs and usability problems remain. Here are the errors and exactly what to change.

---

## 1. Calibrator does **not** adjust the actual listening delay
**Problem:**  
The `+` / `‑` buttons only change a local `calibrationDelay` variable. This value is used to delay the **beep itself**, but the beep is routed directly to `audioCtx.destination` – bypassing the `delayNode` that controls the stream. The calibration result is never applied to the real audio stream.

**Effect:**  
Turning the calibrator knobs has no effect on lip‑sync. The stream’s delay remains whatever is on the `audioDelayOffset` slider.

**Fix:**  
Make the `+`/`‑` buttons directly update the `audioDelayOffset` slider and trigger its `input` event. This way the stream’s delay changes in real time, and the beep should be played through the same `delayNode` (or you can simply not use a separate beep and rely on the stream itself for calibration).  

Replace the button handlers:

```javascript
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
```

Remove the `calibrationDelay` variable and `calibDelayDisplay` updates (or make `calibDelayDisplay` show `audioDelayOffset.value`). The existing `audioDelayOffset` input handler already updates `delayNode.delayTime`.

Also, **route the calibration beep through the same `delayNode`** so that the beep itself is affected by the slider. In `triggerSyncPulse`, replace:

```javascript
toneGain.connect(audioCtx.destination);
```
with:
```javascript
toneGain.connect(delayNode);
```

Now the beep and stream share the exact same delay path.

---

## 2. WebSocket ping interval leaks on reconnect
**Problem:**  
`startPingLoop()` uses `setInterval` but never clears the old interval when the socket reconnects. After several reconnections you’ll have multiple intervals pinging simultaneously.

**Fix:**  
Store the interval ID and clear it before creating a new connection.

```javascript
let pingInterval = null;

function startPingLoop() {
  if (pingInterval) clearInterval(pingInterval);
  pingInterval = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }));
    }
  }, 2000);
}
```

Also clear `pingInterval` inside `ws.onclose` or before reconnecting to be safe.

---

## 3. Volume changes cause zipper noise / clicks
**Problem:**  
In `playAudioPacket` the gain is set directly (`gainNode.gain.value = ...`) on **every** audio packet (hundreds of times per second). When the user drags the volume slider, the abrupt value jumps create audible clicks.

**Fix:**  
Use `setTargetAtTime` for a smooth 50ms ramp. Replace:

```javascript
if (gainNode) {
  gainNode.gain.value = parseFloat(volumeControl.value || 1.0);
}
```
with:
```javascript
if (gainNode) {
  const target = parseFloat(volumeControl.value || 1.0);
  gainNode.gain.setTargetAtTime(target, audioCtx.currentTime, 0.05);
}
```

Do the same in the volume slider’s `input` handler:

```javascript
volumeControl.addEventListener('input', () => {
  const val = parseFloat(volumeControl.value);
  volumeVal.textContent = `${Math.round(val * 100)}%`;
  if (gainNode) {
    gainNode.gain.setTargetAtTime(val, audioCtx.currentTime, 0.05);
  }
});
```

---

## 4. Visualizer canvas does not resize with window
**Problem:**  
The canvas is drawn only once with its initial dimensions. If the browser window is resized, the visualisation becomes distorted.

**Fix:**  
Add a resize observer or a simple `window.addEventListener('resize', resizeCanvas)`. Inside the visualizer start function:

```javascript
function resizeCanvas() {
  const canvas = document.getElementById('visualizer-canvas');
  canvas.width = canvas.offsetWidth;
  canvas.height = canvas.offsetHeight;
}
window.addEventListener('resize', resizeCanvas);
```

Call `resizeCanvas()` before starting the animation loop.

---

## 5. (Minor) ScriptProcessor fallback wastes resources
**Problem:**  
The fallback uses a dummy looping `BufferSource` to feed a silent input to the `ScriptProcessorNode` because `createScriptProcessor(2048, 1, 1)` requires an input channel. Most modern browsers support **zero** input channels: `createScriptProcessor(2048, 0, 1)`.

**Fix:**  
Try zero input channels first. If that throws, fall back to the dummy source.

```javascript
if (!workletNode && !fallbackProcessor) {
  try {
    fallbackProcessor = audioCtx.createScriptProcessor(2048, 0, 1);
  } catch (e) {
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
```

---

## 6. (Optional) Missing “Copy Client Command” button
The client GStreamer command is displayed but has no copy button. Add one next to the command box for convenience, mirroring the server command button.

---

## Summary of critical changes
- **Calibrator buttons must drive `audioDelayOffset` slider + route beep through `delayNode`.**
- **Fix ping interval leak.**
- **Smooth volume changes with `setTargetAtTime`.**
- **Add canvas resize handler.**
- **Try zero‑input ScriptProcessor to avoid dummy source.**

Apply these changes and the application will work as intended: real‑time lip‑sync control, stable networking, and clean audio.