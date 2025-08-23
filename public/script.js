// ===== Audio-Only App DOM Elements =====
const shareUrlInput = document.getElementById('shareUrlInput');
const copyUrlBtn = document.getElementById('copyUrl');
const listenUrlInput = document.getElementById('listenUrlInput');
const copyListenUrlBtn = document.getElementById('copyListenUrl');
const networkInfo = document.getElementById('networkAddresses');
const startAudioBtn = document.getElementById('startAudioStream');
const stopAudioBtn = document.getElementById('stopAudioStream');
const audioStatus = document.getElementById('audioStatus');
const audioLevelBar = document.getElementById('audioLevelBar');
const connectionStatus = document.getElementById('connectionStatus');
const clientsCount = document.getElementById('clientsCount');
const notificationEl = document.getElementById('notification');
const latencyInput = document.getElementById('latencyInput');
const bitrateInput = document.getElementById('bitrateInput');
const applyTuningBtn = document.getElementById('applyTuning');
const tuneStatus = document.getElementById('tuneStatus');

// ===== Global State =====
let networkAddresses = [];
let socket = null;
let mediaStream = null;
let audioContext = null;
let analyser = null;
let isStreaming = false;
let peers = new Map(); // viewerId -> RTCPeerConnection
let audioTrack = null;
let desiredLatencyMs = 200;
let desiredBitrateKbps = 192;
let senderRegistry = new Map(); // viewerId -> RTCRtpSender
let pendingViewers = new Set(); // viewers awaiting audioTrack

document.addEventListener('DOMContentLoaded', () => {
    initializeSocket();
    loadNetworkInfo();
    setupUiHandlers();
});

function setupUiHandlers() {
    if (copyUrlBtn) copyUrlBtn.addEventListener('click', copyShareUrl);
    if (copyListenUrlBtn) copyListenUrlBtn.addEventListener('click', copyListenUrl);
    if (startAudioBtn) startAudioBtn.addEventListener('click', startAudioStreaming);
    if (stopAudioBtn) stopAudioBtn.addEventListener('click', stopAudioStreaming);
    if (applyTuningBtn) applyTuningBtn.addEventListener('click', applyTuningToAll);
}

// ===== Socket Initialization =====
function initializeSocket() {
    socket = io();

    socket.on('connect', () => {
        console.log('Connected to server');
        connectionStatus.textContent = '🟢 Connected';
        connectionStatus.style.color = '#38a169';
        updateClientsCount();
    });

    socket.on('disconnect', () => {
        connectionStatus.textContent = '🔴 Disconnected';
        connectionStatus.style.color = '#e53e3e';
    });

    // Stats broadcast
    socket.on('stats', ({ viewerCount, hostPresent }) => {
        clientsCount.textContent = `👥 ${viewerCount} listening`;
    });

    // New viewer joined – create peer connection & send offer
    socket.on('viewer-joined', async ({ viewerId }) => {
        if (!audioTrack) {
            console.log('[Host] Viewer', viewerId, 'queued (audio not ready yet)');
            pendingViewers.add(viewerId);
            return;
        }
        await createPeerForViewer(viewerId);
    });

    // Receive answer from viewer
    socket.on('webrtc-answer', async ({ sdp, viewerId }) => {
        const pc = peers.get(viewerId);
        if (pc) {
            console.log('[Host] Answer received from viewer', viewerId);
            try {
                await pc.setRemoteDescription(new RTCSessionDescription(sdp));
                console.log('[Host] Remote description set for', viewerId);
            } catch (err) {
                console.error('[Host] Failed to set remote description for', viewerId, err);
            }
        } else {
            console.warn('[Host] Answer for unknown viewer', viewerId);
        }
    });

    // ICE candidate from viewer
    socket.on('webrtc-ice-candidate', async ({ candidate, from }) => {
        const pc = peers.get(from);
        if (pc && candidate) {
            try { await pc.addIceCandidate(new RTCIceCandidate(candidate)); } catch(e){ console.warn('ICE add failed', e); }
        }
    });

    socket.on('viewer-left', ({ viewerId }) => {
        const pc = peers.get(viewerId);
        if (pc) { pc.close(); peers.delete(viewerId); }
    });

    socket.emit('register-host');
}

// ===== Network Info =====
async function loadNetworkInfo() {
    try {
        const response = await fetch('/network-info');
        const data = await response.json();
        
        networkAddresses = data.addresses;
        
        let html = `<div class="network-address">
            <strong>Local:</strong> ${data.localUrl}
        </div>`;
        
        data.addresses.forEach(addr => {
            html += `<div class="network-address">
                <strong>${addr.interface}:</strong> ${addr.url}
            </div>`;
        });
        
        networkInfo.innerHTML = html;
        
    const shareUrl = data.addresses.length > 0 ? data.addresses[0].url : data.localUrl;
    if (shareUrlInput) shareUrlInput.value = shareUrl;
    const listenUrl = shareUrl + '/listen';
    if (listenUrlInput) listenUrlInput.value = listenUrl;
        
    } catch (error) {
        console.error('Failed to load network info:', error);
        networkInfo.innerHTML = '<div class="network-address"><strong>Error:</strong> Could not load network information</div>';
    }
}

// Copy share URL
function copyShareUrl() {
    if (!shareUrlInput) return;
    shareUrlInput.select();
    shareUrlInput.setSelectionRange(0, 99999);
    try {
        document.execCommand('copy');
        showNotification('Control page URL copied', 'success');
    } catch {
        showNotification('Copy failed', 'error');
    }
}

// Copy listen URL
function copyListenUrl() {
    if (!listenUrlInput) return;
    listenUrlInput.select();
    listenUrlInput.setSelectionRange(0, 99999);
    try {
        document.execCommand('copy');
        showNotification('Listener URL copied', 'success');
    } catch {
        showNotification('Copy failed', 'error');
    }
}

// Notification helper
function showNotification(message, type = 'info') {
    if (!notificationEl) return;
    notificationEl.textContent = message;
    notificationEl.className = `notification ${type}`;
    notificationEl.classList.add('show');
    setTimeout(() => notificationEl.classList.remove('show'), 2500);
}

// ===== Live Audio Streaming (System Audio) =====
async function startAudioStreaming() {
    try {
        console.log('[Host] Requesting display media with system audio');
        // Request screen share with audio to capture system audio
        mediaStream = await navigator.mediaDevices.getDisplayMedia({ 
            video: { frameRate: { ideal: 5, max: 10 }, width: { ideal: 640 }, height: { ideal: 360 } }, // keep video lightweight to reduce overhead
            audio: {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
                suppressLocalAudioPlayback: false
            } 
        });
        
        // Check if audio track is available
        const audioTracks = mediaStream.getAudioTracks();
        if (audioTracks.length === 0) {
            throw new Error('No audio track available. Make sure to check "Share audio" when selecting screen/window.');
        }
        
    // Use the direct audio track from original display stream (keep video track running to avoid capture termination)
    const audioOnlyStream = new MediaStream();
    audioOnlyStream.addTrack(audioTracks[0]);
        
        // Setup audio context for visualization
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(audioOnlyStream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        
    // Extract track reference for WebRTC peers (keep original display session alive)
    audioTrack = audioOnlyStream.getAudioTracks()[0];
    // Reduce video overhead (not needed but must stay active to keep system audio in many browsers)
    try {
        mediaStream.getVideoTracks().forEach(vt => vt.applyConstraints({ frameRate: { max: 5 }, width: { ideal: 320 }, height: { ideal: 180 } }));
    } catch(_){ }
    console.log('[Host] Audio track ready, id=', audioTrack.id);
    // Flush any pending viewers
    if (pendingViewers.size) {
        console.log('[Host] Connecting pending viewers:', Array.from(pendingViewers));
        for (const vid of pendingViewers) {
            await createPeerForViewer(vid);
        }
        pendingViewers.clear();
    }
        
        isStreaming = true;
        startAudioBtn.style.display = 'none';
        stopAudioBtn.style.display = 'inline-flex';
        audioStatus.textContent = '🔊 Streaming system audio...';
        audioStatus.style.color = '#e53e3e';
        
        // Start audio level visualization
        visualizeAudioLevel();
        
    showNotification('System audio streaming started (WebRTC)', 'success');
    // Notify server so existing viewers (opened early) trigger offers
    socket.emit('announce-streaming');
    console.log('[Host] Announced streaming');
        
        // Handle stream end (when user stops screen sharing)
        // Track end handlers
        mediaStream.getVideoTracks().forEach(track => {
            track.onended = () => { console.log('[Host] Video track ended'); stopAudioStreaming(); };
        });
        audioOnlyStream.getAudioTracks().forEach(track => {
            track.onended = () => { console.log('[Host] Audio track ended'); stopAudioStreaming(); };
        });
        
    } catch (error) {
        console.error('Error starting system audio stream:', error);
    if (error && error.name === 'NotAllowedError') {
            showNotification('Screen sharing was denied. Please allow screen sharing to capture system audio.', 'error');
        } else if (error.message.includes('No audio track')) {
            showNotification('No audio track found. Make sure to check "Share audio" when selecting screen/window.', 'error');
        } else {
            showNotification('Failed to start system audio stream: ' + error.message, 'error');
        }
    }
}

function stopAudioStreaming() {
    if (mediaStream) {
    mediaStream.getTracks().forEach(track => { try { track.stop(); } catch(_){} });
        mediaStream = null;
    }
    
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    
    isStreaming = false;
    startAudioBtn.style.display = 'inline-flex';
    stopAudioBtn.style.display = 'none';
    audioStatus.textContent = '🔇 System audio not shared';
    audioStatus.style.color = '#718096';
    audioLevelBar.style.width = '0%';
    
    // Notify other clients
    // Close all peer connections
    peers.forEach((pc) => pc.close());
    peers.clear();
    audioTrack = null;
    pendingViewers.clear();
    senderRegistry.clear();
    
    showNotification('System audio streaming stopped', 'info');
}

function visualizeAudioLevel() {
    if (!analyser || !isStreaming) return;
    
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    
    function updateLevel() {
        if (!isStreaming) return;
        
        analyser.getByteFrequencyData(dataArray);
        
        // Calculate average volume
        const average = dataArray.reduce((sum, value) => sum + value, 0) / bufferLength;
        const percentage = (average / 255) * 100;
        
        audioLevelBar.style.width = percentage + '%';
        
        requestAnimationFrame(updateLevel);
    }
    
    updateLevel();
}

// Removed playReceivedAudio (host only)

async function updateClientsCount() {
    // legacy leftover - stats now via socket 'stats'
}

// If a listener opened /listen before host began, they may wait for host-streaming broadcast
if (typeof window !== 'undefined') {
    // This script runs only on host page, but safe guard anyway
    if (socket) {
        socket.on('host-streaming', () => {
            // no action host-side; listeners react
        });
    }
}

async function createPeerForViewer(viewerId) {
    if (!audioTrack) return;
    console.log('[Host] Creating peer for viewer', viewerId);
    const pc = new RTCPeerConnection({
        iceServers: [
            { urls: 'stun:stun.l.google.com:19302' }
        ]
    });
    peers.set(viewerId, pc);
    pc.onicecandidate = (e) => {
        if (e.candidate) {
            socket.emit('webrtc-ice-candidate', { targetId: viewerId, candidate: e.candidate });
        }
    };
    pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected' || pc.connectionState === 'closed') {
            pc.close();
            peers.delete(viewerId);
            // Retry once if audioTrack still alive
            if (audioTrack && pc.connectionState === 'failed') {
                console.log('[Host] Retrying viewer', viewerId);
                setTimeout(()=>{ if(audioTrack && !peers.has(viewerId)) createPeerForViewer(viewerId); }, 1000);
            }
        }
    };
    pc.oniceconnectionstatechange = () => {
        console.log('[Host] ICE state viewer', viewerId, pc.iceConnectionState);
    };
        // Add track with stream reference for Safari compatibility
        const outboundStream = new MediaStream([audioTrack]);
        const sender = pc.addTrack(audioTrack, outboundStream);
        senderRegistry.set(viewerId, sender);
        // Attempt to prefer Opus + tune encoding (low-latency high-quality)
        try {
            // Reorder codecs so Opus first
            if (RTCRtpSender.getCapabilities) {
                const caps = RTCRtpSender.getCapabilities('audio');
                if (caps && caps.codecs) {
                    const opus = caps.codecs.filter(c=>/opus/i.test(c.mimeType));
                    const others = caps.codecs.filter(c=>!/opus/i.test(c.mimeType));
                    const ordered = [...opus, ...others];
                    const tx = pc.getTransceivers().find(t=>t.sender === sender);
                    if (tx && tx.setCodecPreferences) {
                        tx.setCodecPreferences(ordered);
                    }
                }
            }
        } catch(e) { console.warn('[Host] Codec preference failed', e); }
        // Tune sender parameters
        tuneSender(sender);
        // Ensure transceiver direction is sendonly
        const tx = pc.getTransceivers().find(t=>t.sender && t.sender.track === audioTrack);
        if (tx) { try { tx.direction = 'sendonly'; } catch(_){} }
    console.log('[Host] Added audio track to peer', viewerId);
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    socket.emit('webrtc-offer', { viewerId, sdp: offer });
    console.log('[Host] Sent offer to viewer', viewerId);
}

function tuneSender(sender){
    if(!sender) return;
    try {
        const params = sender.getParameters();
        if (!params.encodings) params.encodings = [{}];
        const enc = params.encodings[0];
        enc.maxBitrate = Math.round(desiredBitrateKbps * 1000); // bps
        // Attempt to set ptime based on latency target (keep a minimal 2 * ptime buffer ≈ target)
        // Choose closest typical packetization (10,20,40)
        const target = desiredLatencyMs;
        let ptime = 20;
        if (target <= 140) ptime = 10; else if (target >= 300) ptime = 40; else ptime = 20;
        enc.ptime = ptime;
        enc.dtx = false;
        sender.setParameters(params).catch(()=>{});
        if (tuneStatus) tuneStatus.textContent = `Target: ${desiredLatencyMs}ms / ${desiredBitrateKbps}kbps (ptime ${ptime}ms)`;
    } catch(e) { console.warn('[Host] tuneSender failed', e); }
}

function applyTuningToAll(){
    if (latencyInput) desiredLatencyMs = Math.max(80, Math.min(800, parseInt(latencyInput.value)||200));
    if (bitrateInput) desiredBitrateKbps = Math.max(64, Math.min(320, parseInt(bitrateInput.value)||192));
    senderRegistry.forEach(sender => tuneSender(sender));
    showNotification('Applied new tuning', 'info');
}
