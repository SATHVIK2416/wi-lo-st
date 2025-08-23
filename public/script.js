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

// ===== Global State =====
let networkAddresses = [];
let socket = null;
let mediaStream = null;
let audioContext = null;
let analyser = null;
let isStreaming = false;
let peers = new Map(); // viewerId -> RTCPeerConnection
let audioTrack = null;

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
        if (!audioTrack) return;
        await createPeerForViewer(viewerId);
    });

    // Receive answer from viewer
    socket.on('webrtc-answer', async ({ sdp, viewerId }) => {
        const pc = peers.get(viewerId);
        if (pc) {
            await pc.setRemoteDescription(new RTCSessionDescription(sdp));
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
        // Request screen share with audio to capture system audio
        mediaStream = await navigator.mediaDevices.getDisplayMedia({ 
            video: true, // required to enable system audio capture
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
        
        // Create audio-only stream
        const audioOnlyStream = new MediaStream();
        audioTracks.forEach(track => audioOnlyStream.addTrack(track));
        
        // Setup audio context for visualization
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(audioOnlyStream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        
    // Extract track reference for WebRTC peers
    audioTrack = audioOnlyStream.getAudioTracks()[0];

    // Stop video capture tracks (we only keep audio track object reference)
    mediaStream.getVideoTracks().forEach(t => t.stop());
        
        isStreaming = true;
        startAudioBtn.style.display = 'none';
        stopAudioBtn.style.display = 'inline-flex';
        audioStatus.textContent = '🔊 Streaming system audio...';
        audioStatus.style.color = '#e53e3e';
        
        // Start audio level visualization
        visualizeAudioLevel();
        
    showNotification('System audio streaming started (WebRTC)', 'success');
        
        // Handle stream end (when user stops screen sharing)
        mediaStream.getVideoTracks().forEach(track => {
            track.onended = () => {
                stopAudioStreaming();
            };
        });
        
        audioOnlyStream.getAudioTracks().forEach(track => {
            track.onended = () => {
                stopAudioStreaming();
            };
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
        mediaStream.getTracks().forEach(track => track.stop());
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

async function createPeerForViewer(viewerId) {
    if (!audioTrack) return;
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
        }
    };
    pc.addTrack(audioTrack);
    const offer = await pc.createOffer({ offerToReceiveAudio: false, offerToReceiveVideo: false });
    await pc.setLocalDescription(offer);
    socket.emit('webrtc-offer', { viewerId, sdp: offer });
}
