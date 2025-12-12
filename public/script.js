/**
 * Host Control Script - Maximum Audio Quality
 * Streams system audio via WebRTC with highest possible fidelity
 */
(() => {
    'use strict';

    // DOM Cache
    const $ = id => document.getElementById(id);
    const dom = {
        shareUrl: $('shareUrlInput'),
        listenUrl: $('listenUrlInput'),
        copyUrl: $('copyUrl'),
        copyListenUrl: $('copyListenUrl'),
        network: $('networkAddresses'),
        startBtn: $('startAudioStream'),
        stopBtn: $('stopAudioStream'),
        status: $('audioStatus'),
        levelBar: $('audioLevelBar'),
        visualizer: document.querySelector('.audio-visualizer'),
        connection: $('connectionStatus'),
        clients: $('clientsCount'),
        notification: $('notification'),
        latency: $('latencyInput'),
        bitrate: $('bitrateInput'),
        tuneBtn: $('applyTuning'),
        tuneStatus: $('tuneStatus')
    };

    // State
    let socket, mediaStream, audioContext, analyser, processedTrack;
    let isStreaming = false;
    const peers = new Map();
    const pendingViewers = new Set();

    // Audio Quality Settings - Maximum Quality
    const AUDIO_CONFIG = {
        // Opus parameters for maximum quality
        // stereo=1: Enable stereo
        // sprop-stereo=1: Signal stereo capability
        // maxaveragebitrate=510000: Maximum Opus bitrate (510kbps)
        // maxplaybackrate=48000: Maximum sample rate
        // cbr=0: Variable bitrate for better quality
        // useinbandfec=0: Disable forward error correction (adds latency)
        // usedtx=0: Disable discontinuous transmission (keeps quality constant)
        opusFmtp: 'minptime=10;stereo=1;sprop-stereo=1;maxaveragebitrate=510000;maxplaybackrate=48000;cbr=0;useinbandfec=0;usedtx=0',

        // RTP encoding parameters
        maxBitrate: 510000,  // 510kbps - max for Opus

        // Display media constraints - highest quality audio capture
        displayMedia: {
            video: {
                frameRate: { max: 1 }, // Minimal video
                width: { ideal: 320 },
                height: { ideal: 180 }
            },
            audio: {
                // Disable all processing to preserve original audio
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false,
                // Request highest quality
                sampleRate: 48000,
                sampleSize: 16,
                channelCount: 2  // Stereo
            }
        }
    };

    // Utilities
    const setStatus = (msg, variant = 'neutral') => {
        if (!dom.status) return;
        dom.status.textContent = msg;
        dom.status.className = `pill pill--${variant === 'accent' ? 'accent' : 'neutral'}`;
    };

    const notify = (message, type = 'info') => {
        if (!dom.notification) return;
        dom.notification.textContent = message;
        dom.notification.className = `notification ${type} show`;
        setTimeout(() => dom.notification.classList.remove('show'), 3000);
    };

    const copyToClipboard = async (el, successMsg) => {
        if (!el) return;
        try {
            await navigator.clipboard.writeText(el.value);
            notify(successMsg, 'success');
        } catch {
            el.select();
            document.execCommand('copy');
            notify(successMsg, 'success');
        }
    };

    // Socket.IO
    const initSocket = () => {
        socket = io();

        socket.on('connect', () => {
            if (dom.connection) {
                dom.connection.textContent = 'Connected';
                dom.connection.style.color = '#4ade80';
            }
        });

        socket.on('disconnect', () => {
            if (dom.connection) {
                dom.connection.textContent = 'Disconnected';
                dom.connection.style.color = '#f87171';
            }
        });

        socket.on('stats', ({ viewerCount }) => {
            if (dom.clients) dom.clients.textContent = `${viewerCount} listening`;
        });

        socket.on('viewer-joined', async ({ viewerId }) => {
            if (!processedTrack) {
                pendingViewers.add(viewerId);
                return;
            }
            await createPeerConnection(viewerId);
        });

        socket.on('webrtc-answer', async ({ sdp, viewerId }) => {
            const pc = peers.get(viewerId);
            if (pc) {
                try {
                    await pc.setRemoteDescription(new RTCSessionDescription(sdp));
                } catch (e) {
                    console.error('Failed to set remote description:', e);
                }
            }
        });

        socket.on('webrtc-ice-candidate', async ({ candidate, from }) => {
            const pc = peers.get(from);
            if (pc && candidate) {
                try {
                    await pc.addIceCandidate(new RTCIceCandidate(candidate));
                } catch (e) {
                    console.warn('Failed to add ICE candidate:', e);
                }
            }
        });

        socket.on('viewer-left', ({ viewerId }) => {
            const pc = peers.get(viewerId);
            if (pc) {
                pc.close();
                peers.delete(viewerId);
            }
        });

        socket.emit('register-host');
    };

    // Network Info
    const loadNetworkInfo = async () => {
        try {
            const res = await fetch('/network-info');
            const data = await res.json();

            const html = [`<div class="network-address"><strong>Local:</strong> ${data.localUrl}</div>`];
            data.addresses.forEach(a => {
                html.push(`<div class="network-address"><strong>${a.interface}:</strong> ${a.url}</div>`);
            });
            if (dom.network) dom.network.innerHTML = html.join('');

            const shareUrl = data.addresses[0]?.url || data.localUrl;
            if (dom.shareUrl) dom.shareUrl.value = shareUrl;
            if (dom.listenUrl) dom.listenUrl.value = `${shareUrl}/listen`;
        } catch {
            if (dom.network) dom.network.innerHTML = '<div class="network-address">Failed to load network info</div>';
        }
    };

    // Start Audio Stream
    const startAudio = async () => {
        try {
            // Get display media with audio
            mediaStream = await navigator.mediaDevices.getDisplayMedia(AUDIO_CONFIG.displayMedia);

            const audioTracks = mediaStream.getAudioTracks();
            if (!audioTracks.length) {
                throw new Error('No audio track - make sure to check "Share audio" when selecting screen');
            }

            // Create audio context for visualization
            audioContext = new (window.AudioContext || window.webkitAudioContext)({
                sampleRate: 48000,
                latencyHint: 'playback'
            });

            // Set up audio processing chain
            const source = audioContext.createMediaStreamSource(new MediaStream([audioTracks[0]]));
            analyser = audioContext.createAnalyser();
            analyser.fftSize = 256;

            // Create destination for processed audio
            const destination = audioContext.createMediaStreamDestination();

            // Connect: source -> analyser -> destination (no EQ, preserve original)
            source.connect(analyser);
            analyser.connect(destination);

            processedTrack = destination.stream.getAudioTracks()[0];

            // Minimize video overhead
            mediaStream.getVideoTracks().forEach(v => {
                try {
                    v.applyConstraints({ frameRate: { max: 1 } });
                } catch { }
            });

            // Handle track end
            const onTrackEnd = () => stopAudio();
            audioTracks[0].onended = onTrackEnd;
            mediaStream.getVideoTracks().forEach(v => v.onended = onTrackEnd);

            // Connect pending viewers
            for (const viewerId of pendingViewers) {
                await createPeerConnection(viewerId);
            }
            pendingViewers.clear();

            // Update UI
            isStreaming = true;
            if (dom.startBtn) dom.startBtn.hidden = true;
            if (dom.stopBtn) dom.stopBtn.hidden = false;
            setStatus('LIVE', 'accent');
            dom.visualizer?.classList.add('is-active');

            visualize();
            notify('Streaming at maximum quality (510kbps stereo)', 'success');
            socket.emit('announce-streaming');

        } catch (e) {
            console.error('Start audio failed:', e);
            let msg = 'Failed to start streaming';
            if (e.name === 'NotAllowedError') msg = 'Screen sharing was denied';
            else if (e.message.includes('No audio')) msg = e.message;
            notify(msg, 'error');
        }
    };

    // Stop Audio Stream
    const stopAudio = () => {
        if (mediaStream) {
            mediaStream.getTracks().forEach(t => t.stop());
            mediaStream = null;
        }

        if (audioContext) {
            audioContext.close();
            audioContext = null;
        }

        processedTrack = null;
        isStreaming = false;

        peers.forEach(pc => pc.close());
        peers.clear();
        pendingViewers.clear();

        if (dom.startBtn) dom.startBtn.hidden = false;
        if (dom.stopBtn) dom.stopBtn.hidden = true;
        if (dom.levelBar) dom.levelBar.style.width = '0%';
        dom.visualizer?.classList.remove('is-active');
        setStatus('OFFLINE', 'neutral');

        socket.emit('host-stopped-streaming');
        notify('Stream stopped');
    };

    // Audio Level Visualization
    const visualize = () => {
        if (!analyser || !isStreaming) return;

        const data = new Uint8Array(analyser.frequencyBinCount);

        const loop = () => {
            if (!isStreaming) return;

            analyser.getByteFrequencyData(data);
            let sum = 0;
            for (let i = 0; i < data.length; i++) sum += data[i];
            const avg = sum / data.length;

            if (dom.levelBar) dom.levelBar.style.width = `${(avg / 255) * 100}%`;

            requestAnimationFrame(loop);
        };

        requestAnimationFrame(loop);
    };

    // WebRTC Peer Connection with Maximum Quality Settings
    const createPeerConnection = async (viewerId) => {
        if (!processedTrack) return;

        const pc = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });

        peers.set(viewerId, pc);

        pc.onicecandidate = e => {
            if (e.candidate) {
                socket.emit('webrtc-ice-candidate', { targetId: viewerId, candidate: e.candidate });
            }
        };

        pc.onconnectionstatechange = () => {
            const state = pc.connectionState;
            if (state === 'failed' || state === 'disconnected' || state === 'closed') {
                pc.close();
                peers.delete(viewerId);
            }
        };

        // Add the audio track
        const sender = pc.addTrack(processedTrack, new MediaStream([processedTrack]));

        // Configure sender for maximum quality
        try {
            const params = sender.getParameters();
            if (!params.encodings || params.encodings.length === 0) {
                params.encodings = [{}];
            }

            // Set maximum bitrate
            params.encodings[0].maxBitrate = AUDIO_CONFIG.maxBitrate;
            params.encodings[0].priority = 'high';
            params.encodings[0].networkPriority = 'high';

            await sender.setParameters(params);
        } catch (e) {
            console.warn('Could not set sender parameters:', e);
        }

        // Set preferred codecs (Opus stereo first)
        try {
            const transceiver = pc.getTransceivers().find(t => t.sender === sender);
            if (transceiver) {
                transceiver.direction = 'sendonly';

                if (RTCRtpSender.getCapabilities) {
                    const caps = RTCRtpSender.getCapabilities('audio');
                    if (caps?.codecs) {
                        // Prefer Opus with stereo
                        const opusCodecs = caps.codecs.filter(c => c.mimeType === 'audio/opus');
                        const otherCodecs = caps.codecs.filter(c => c.mimeType !== 'audio/opus');

                        if (transceiver.setCodecPreferences) {
                            transceiver.setCodecPreferences([...opusCodecs, ...otherCodecs]);
                        }
                    }
                }
            }
        } catch (e) {
            console.warn('Could not set codec preferences:', e);
        }

        // Create offer
        const offer = await pc.createOffer({
            offerToReceiveAudio: false,
            offerToReceiveVideo: false,
            voiceActivityDetection: false
        });

        // Enhance SDP for maximum Opus quality
        offer.sdp = enhanceOpusSDP(offer.sdp);

        await pc.setLocalDescription(offer);
        socket.emit('webrtc-offer', { viewerId, sdp: offer });
    };

    // Enhance SDP to set Opus to maximum quality
    const enhanceOpusSDP = (sdp) => {
        const lines = sdp.split('\r\n');
        const result = [];
        let opusPayload = null;

        // Find Opus payload type
        for (const line of lines) {
            if (line.includes('opus/48000/2')) {
                const match = line.match(/rtpmap:(\d+)/);
                if (match) opusPayload = match[1];
            }
        }

        if (!opusPayload) return sdp;

        // Build new SDP with enhanced Opus parameters
        let addedFmtp = false;
        for (const line of lines) {
            if (line.startsWith(`a=fmtp:${opusPayload}`)) {
                // Replace existing fmtp line with our high-quality settings
                result.push(`a=fmtp:${opusPayload} ${AUDIO_CONFIG.opusFmtp}`);
                addedFmtp = true;
            } else {
                result.push(line);
                // Add fmtp after rtpmap if not already present
                if (!addedFmtp && line.includes(`rtpmap:${opusPayload} opus`)) {
                    result.push(`a=fmtp:${opusPayload} ${AUDIO_CONFIG.opusFmtp}`);
                    addedFmtp = true;
                }
            }
        }

        return result.join('\r\n');
    };

    // UI Event Bindings
    const bindUI = () => {
        dom.copyUrl?.addEventListener('click', () => copyToClipboard(dom.shareUrl, 'Console URL copied'));
        dom.copyListenUrl?.addEventListener('click', () => copyToClipboard(dom.listenUrl, 'Listener URL copied'));
        dom.startBtn?.addEventListener('click', startAudio);
        dom.stopBtn?.addEventListener('click', stopAudio);
    };

    // Initialize
    document.addEventListener('DOMContentLoaded', () => {
        initSocket();
        loadNetworkInfo();
        bindUI();
        setStatus('OFFLINE', 'neutral');
    });

    // Expose socket for inline scripts
    Object.defineProperty(window, 'socket', {
        get: () => socket,
        configurable: true
    });
})();
