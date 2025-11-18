// Listener script
let socket, pc, audioEl, hostIdRef = null;
const bars = [];
let muted = false, volume = 1.0;

// DOM Refs
const qs = id => document.getElementById(id);
const audioStatus = qs('audioStatus');
const connectionStatus = qs('connectionStatus');
const clientsCount = qs('clientsCount');
const vis = qs('audioVisualizer');
const volumeSlider = qs('volumeSlider');
const volumeDisplay = qs('volumeDisplay');
const enableBtn = qs('enableAudio');
const muteBtn = qs('muteAudio');
const note = qs('notification');
const qualityStats = qs('qualityStats');

const setChipState = (el, state) => {
    if (!el) return;
    el.classList.remove('chip--ok', 'chip--warn', 'chip--error');
    if (state) el.classList.add(`chip--${state}`);
};

const setAudioBadge = (message, state = 'idle') => {
    audioStatus.textContent = message;
    audioStatus.classList.remove('badge--idle', 'badge--live', 'badge--error');
    audioStatus.classList.add(state === 'live' ? 'badge--live' : state === 'error' ? 'badge--error' : 'badge--idle');
};

document.addEventListener('DOMContentLoaded', () => {
    initBars();
    initSocket();
    bindUi();
    setAudioBadge('🔇 Waiting for audio stream...');
});

function initBars() {
    for (let i = 0; i < 40; i++) {
        const b = document.createElement('div');
        b.className = 'visualizer-bar';
        vis.appendChild(b);
        bars.push(b);
    }
}

function bindUi() {
    volumeSlider.addEventListener('input', () => {
        volume = volumeSlider.value / 100;
        volumeDisplay.textContent = volumeSlider.value + '%';
        if (audioEl) audioEl.volume = volume;
    });
    enableBtn.addEventListener('click', joinStream);
    muteBtn.addEventListener('click', toggleMute);
}

function initSocket() {
    socket = io();
    socket.on('connect', () => {
        setChipState(connectionStatus, 'ok');
        connectionStatus.textContent = '🟢 Connected';
    });
    socket.on('disconnect', () => {
        setChipState(connectionStatus, 'error');
        connectionStatus.textContent = '🔴 Disconnected';
        setAudioBadge('🔇 Disconnected', 'error');
        teardown();
    });
    socket.on('no-host', () => {
        setAudioBadge('❌ No host', 'error');
        flash('No host streaming', 'error');
        enableBtn.style.display = 'inline-flex';
    });
    socket.on('host-left', () => {
        setAudioBadge('🔇 Host left', 'error');
        flash('Host left', 'error');
        teardown();
    });
    socket.on('host-stopped', () => {
        setAudioBadge('🔇 Waiting for audio stream...', 'idle');
        flash('Host stopped streaming', 'error');
        teardown();
    });
    socket.on('host-streaming', () => {
        if (enableBtn.style.display === 'none') socket.emit('viewer-join');
    });
    socket.on('webrtc-offer', async ({ sdp, hostId }) => {
        hostIdRef = hostId;
        await ensurePeer();
        await pc.setRemoteDescription(new RTCSessionDescription(sdp));
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        socket.emit('webrtc-answer', { hostId, sdp: answer });
    });
    socket.on('webrtc-ice-candidate', ({ candidate, from }) => {
        if (pc && candidate && from === hostIdRef) pc.addIceCandidate(new RTCIceCandidate(candidate)).catch(() => { });
    });
    socket.on('stats', ({ viewerCount }) => {
        clientsCount.textContent = `👥 ${viewerCount} listening`;
    });
}

async function joinStream() {
    enableBtn.style.display = 'none';
    muteBtn.style.display = 'inline-flex';
    setAudioBadge('⏳ Joining...', 'idle');
    socket.emit('viewer-join');
    flash('Request sent');
}

async function ensurePeer() {
    if (pc) return;
    pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });

    pc.onicecandidate = e => {
        if (e.candidate && hostIdRef) socket.emit('webrtc-ice-candidate', { targetId: hostIdRef, candidate: e.candidate });
    };

    pc.ontrack = e => {
        if (!audioEl) {
            audioEl = document.createElement('audio');
            audioEl.autoplay = true;
            audioEl.playsInline = true;
            audioEl.controls = false;
            audioEl.style.display = 'none';
            audioEl.volume = volume;
            document.body.appendChild(audioEl);
        }
        audioEl.srcObject = e.streams[0];
        const p = audioEl.play();
        if (p) p.catch(() => { setAudioBadge('⚠️ Tap Enable Audio again', 'error'); });

        setAudioBadge('🎵 Live', 'live');
        vis.classList.add('is-live');
        animate();
    };

    pc.onconnectionstatechange = () => {
        if (['failed', 'disconnected', 'closed'].includes(pc.connectionState)) teardown();
    };
}

function toggleMute() {
    muted = !muted;
    if (audioEl) audioEl.muted = muted;
    muteBtn.textContent = muted ? '🔊 Unmute' : '🔇 Mute';
}

function teardown() {
    if (pc) { pc.close(); pc = null; }
    if (audioEl) { audioEl.srcObject = null; audioEl.remove(); audioEl = null; }
    bars.forEach(b => b.style.height = '18%');
    enableBtn.style.display = 'inline-flex';
    muteBtn.style.display = 'none';
    vis.classList.remove('is-live');
    setAudioBadge('🔇 Waiting for audio stream...', 'idle');
}

function animate() {
    const step = () => {
        if (!pc || !audioEl || audioEl.paused) {
            vis.classList.remove('is-live');
            return;
        }
        bars.forEach(b => { b.style.height = (Math.random() * 80 + 20) + '%'; });
        requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
    updateStatsLoop();
}

async function updateStatsLoop() {
    if (!pc) return;
    try {
        const stats = await pc.getStats();
        let jitterMs = '-', rttMs = '-', bitrateKbps = '-', packetsLost = 0, packetsRecv = 0, fractionLoss = '-';
        let inboundRtp;
        let prevBytes = updateStatsLoop._prevBytes || 0;
        let prevTime = updateStatsLoop._prevTime || performance.now();
        const now = performance.now();

        stats.forEach(r => {
            if (r.type === 'remote-inbound-rtp' && r.kind === 'audio') {
                if (r.jitter) jitterMs = (r.jitter * 1000).toFixed(1);
                if (r.packetsLost != null) packetsLost = r.packetsLost;
            }
            if (r.type === 'inbound-rtp' && r.kind === 'audio') {
                inboundRtp = r;
                if (r.packetsReceived != null) packetsRecv = r.packetsReceived;
            }
            if (r.type === 'candidate-pair' && r.currentRoundTripTime !== undefined && r.nominated) {
                rttMs = (r.currentRoundTripTime * 1000).toFixed(0);
            }
        });

        if (inboundRtp && inboundRtp.bytesReceived != null) {
            const bytes = inboundRtp.bytesReceived;
            const deltaBytes = bytes - prevBytes;
            const deltaTime = now - prevTime;
            if (deltaTime > 0) bitrateKbps = ((deltaBytes * 8) / deltaTime).toFixed(1);
            updateStatsLoop._prevBytes = bytes;
            updateStatsLoop._prevTime = now;
        }

        if (packetsRecv > 0) fractionLoss = ((packetsLost / (packetsLost + packetsRecv)) * 100).toFixed(1) + '%';

        qualityStats.textContent = `⏱️ rtt ${rttMs}ms • jitter ${jitterMs}ms • bitrate ${bitrateKbps}kbps • loss ${fractionLoss}`;

        const lossValue = parseFloat(fractionLoss) || 0;
        const rttValue = parseFloat(rttMs) || 0;
        let qualityState = 'ok';
        if (lossValue > 5 || rttValue > 250) qualityState = 'error';
        else if (lossValue > 2 || rttValue > 150) qualityState = 'warn';
        setChipState(qualityStats, qualityState);

        socket.emit('listener-stats', { rttMs, jitterMs, bitrateKbps, fractionLoss, packetsLost, packetsRecv });
    } catch (_) { }
    setTimeout(updateStatsLoop, 1000);
}

function flash(msg, type = 'success') {
    note.textContent = msg;
    note.className = `notification ${type} show`;
    setTimeout(() => note.classList.remove('show'), 2500);
}
