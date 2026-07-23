/**
 * Host Control Script - Maximum Audio Quality (WHIP Client for MediaMTX)
 * Streams system audio to MediaMTX SFU
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
    let socket, mediaStream, audioContext, analyser, processedTrack, whipPc;
    let isStreaming = false;

    // Audio Quality Settings
    const AUDIO_CONFIG = {
        opusFmtp: 'minptime=10;stereo=1;sprop-stereo=1;maxaveragebitrate=510000;maxplaybackrate=48000;cbr=0;useinbandfec=0;usedtx=0',
        maxBitrate: 510000,
        displayMedia: {
            video: { frameRate: { max: 1 }, width: { ideal: 320 }, height: { ideal: 180 } },
            audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false, sampleRate: 48000, sampleSize: 16, channelCount: 2 }
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
            if (dom.connection) { dom.connection.textContent = 'Connected'; dom.connection.style.color = '#4ade80'; }
        });
        socket.on('disconnect', () => {
            if (dom.connection) { dom.connection.textContent = 'Disconnected'; dom.connection.style.color = '#f87171'; }
        });
        socket.on('stats', ({ viewerCount }) => {
            if (dom.clients) dom.clients.textContent = `${viewerCount} listening`;
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

    const enhanceOpusSDP = (sdp) => {
        const lines = sdp.split('\r\n');
        const result = [];
        let opusPayload = null;
        for (const line of lines) {
            if (line.includes('opus/48000/2')) {
                const match = line.match(/rtpmap:(\d+)/);
                if (match) opusPayload = match[1];
            }
        }
        if (!opusPayload) return sdp;
        let addedFmtp = false;
        for (const line of lines) {
            if (line.startsWith(`a=fmtp:${opusPayload}`)) {
                result.push(`a=fmtp:${opusPayload} ${AUDIO_CONFIG.opusFmtp}`);
                addedFmtp = true;
            } else {
                result.push(line);
                if (!addedFmtp && line.includes(`rtpmap:${opusPayload} opus`)) {
                    result.push(`a=fmtp:${opusPayload} ${AUDIO_CONFIG.opusFmtp}`);
                    addedFmtp = true;
                }
            }
        }
        return result.join('\r\n');
    };

    const startWhipConnection = async () => {
        if (!processedTrack) return;
        whipPc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
        whipPc.onconnectionstatechange = () => {
            if (['failed', 'closed'].includes(whipPc.connectionState)) stopAudio();
        };

        const sender = whipPc.addTrack(processedTrack, new MediaStream([processedTrack]));
        try {
            const params = sender.getParameters();
            if (!params.encodings || !params.encodings.length) params.encodings = [{}];
            params.encodings[0].maxBitrate = AUDIO_CONFIG.maxBitrate;
            params.encodings[0].priority = 'high';
            params.encodings[0].networkPriority = 'high';
            await sender.setParameters(params);
        } catch (e) { console.warn('Could not set sender parameters:', e); }

        try {
            const transceiver = whipPc.getTransceivers().find(t => t.sender === sender);
            if (transceiver) {
                transceiver.direction = 'sendonly';
                if (RTCRtpSender.getCapabilities) {
                    const caps = RTCRtpSender.getCapabilities('audio');
                    if (caps?.codecs) {
                        const opusCodecs = caps.codecs.filter(c => c.mimeType === 'audio/opus');
                        const otherCodecs = caps.codecs.filter(c => c.mimeType !== 'audio/opus');
                        if (transceiver.setCodecPreferences) transceiver.setCodecPreferences([...opusCodecs, ...otherCodecs]);
                    }
                }
            }
        } catch (e) { console.warn('Could not set codec preferences:', e); }

        const offer = await whipPc.createOffer();
        offer.sdp = enhanceOpusSDP(offer.sdp);
        await whipPc.setLocalDescription(offer);

        await new Promise(resolve => {
            if (whipPc.iceGatheringState === 'complete') resolve();
            else {
                const checkState = () => {
                    if (whipPc.iceGatheringState === 'complete') {
                        whipPc.removeEventListener('icegatheringstatechange', checkState);
                        resolve();
                    }
                };
                whipPc.addEventListener('icegatheringstatechange', checkState);
                setTimeout(resolve, 2000);
            }
        });

        const whipUrl = `http://${window.location.hostname}:8889/live/whip`;
        const response = await fetch(whipUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/sdp' },
            body: whipPc.localDescription.sdp
        });

        if (!response.ok) {
            throw new Error(`MediaMTX WHIP failed: ${response.status}`);
        }

        const answerSdp = await response.text();
        await whipPc.setRemoteDescription(new RTCSessionDescription({ type: 'answer', sdp: answerSdp }));
    };

    const startAudio = async () => {
        try {
            mediaStream = await navigator.mediaDevices.getDisplayMedia(AUDIO_CONFIG.displayMedia);
            const audioTracks = mediaStream.getAudioTracks();
            if (!audioTracks.length) throw new Error('No audio track - make sure to check "Share audio"');

            audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000, latencyHint: 'playback' });
            const source = audioContext.createMediaStreamSource(new MediaStream([audioTracks[0]]));
            analyser = audioContext.createAnalyser();
            analyser.fftSize = 256;
            const destination = audioContext.createMediaStreamDestination();
            source.connect(analyser);
            analyser.connect(destination);
            processedTrack = destination.stream.getAudioTracks()[0];

            mediaStream.getVideoTracks().forEach(v => { try { v.applyConstraints({ frameRate: { max: 1 } }); } catch { } });

            const onTrackEnd = () => stopAudio();
            audioTracks[0].onended = onTrackEnd;
            mediaStream.getVideoTracks().forEach(v => v.onended = onTrackEnd);

            await startWhipConnection();

            isStreaming = true;
            if (dom.startBtn) dom.startBtn.hidden = true;
            if (dom.stopBtn) dom.stopBtn.hidden = false;
            setStatus('LIVE', 'accent');
            dom.visualizer?.classList.add('is-active');

            visualize();
            notify('Streaming to MediaMTX via WHIP', 'success');
            socket.emit('announce-streaming');
        } catch (e) {
            console.error('Start audio failed:', e);
            let msg = 'Failed to start streaming';
            if (e.message && e.message.includes('MediaMTX')) msg = 'MediaMTX not running! Please start MediaMTX server on port 8889.';
            else if (e.name === 'NotAllowedError') msg = 'Screen sharing was denied';
            else if (e.message && e.message.includes('No audio')) msg = e.message;
            notify(msg, 'error');
            stopAudio();
        }
    };

    const stopAudio = () => {
        if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }
        if (audioContext) { audioContext.close(); audioContext = null; }
        if (whipPc) { whipPc.close(); whipPc = null; }
        processedTrack = null;
        isStreaming = false;

        if (dom.startBtn) dom.startBtn.hidden = false;
        if (dom.stopBtn) dom.stopBtn.hidden = true;
        if (dom.levelBar) dom.levelBar.style.width = '0%';
        dom.visualizer?.classList.remove('is-active');
        setStatus('OFFLINE', 'neutral');

        socket.emit('host-stopped-streaming');
        notify('Stream stopped');
    };

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

    const applyTuning = async () => {
        const latency = parseInt(dom.latency.value, 10);
        const bitrateKbps = parseInt(dom.bitrate.value, 10);
        if (isNaN(latency) || isNaN(bitrateKbps)) return;

        AUDIO_CONFIG.maxBitrate = bitrateKbps * 1000;
        if (dom.tuneStatus) dom.tuneStatus.textContent = `48kHz Stereo | ${bitrateKbps}kbps | ${latency}ms Latency`;

        socket.emit('tune-settings', { latency });

        if (whipPc) {
            const senders = whipPc.getSenders();
            for (const sender of senders) {
                if (sender.track && sender.track.kind === 'audio') {
                    try {
                        const params = sender.getParameters();
                        if (params.encodings && params.encodings.length > 0) {
                            params.encodings[0].maxBitrate = AUDIO_CONFIG.maxBitrate;
                            await sender.setParameters(params);
                        }
                    } catch (e) { console.warn('Failed to apply new bitrate', e); }
                }
            }
        }
        notify(`Tuning applied: ${bitrateKbps}kbps, ${latency}ms`, 'success');
    };

    const bindUI = () => {
        dom.copyUrl?.addEventListener('click', () => copyToClipboard(dom.shareUrl, 'Console URL copied'));
        dom.copyListenUrl?.addEventListener('click', () => copyToClipboard(dom.listenUrl, 'Listener URL copied'));
        dom.startBtn?.addEventListener('click', startAudio);
        dom.tuneBtn?.addEventListener('click', applyTuning);
        dom.stopBtn?.addEventListener('click', stopAudio);
    };

    document.addEventListener('DOMContentLoaded', () => {
        initSocket();
        loadNetworkInfo();
        bindUI();
        setStatus('OFFLINE', 'neutral');
    });

    Object.defineProperty(window, 'socket', { get: () => socket, configurable: true });
})();

// Inline logic for stats
(() => {
    const wait = () => {
        if (!window.socket) return setTimeout(wait, 100);
        const $ = id => document.getElementById(id);
        const viewerList = $('viewerList');
        const viewerCount = $('viewerCountInline');
        const qualityPanel = $('qualityPanel');
        
        socket.on('stats', ({ viewerIds = [], viewerCount: count }) => {
            if (viewerCount) viewerCount.textContent = count || 0;
            if (viewerList) {
                viewerList.innerHTML = count > 0 
                    ? `<div class="viewer-chip">MediaMTX SFU Active</div>`
                    : '<div class="viewer-empty">No listeners connected</div>';
            }
            if (qualityPanel) {
                qualityPanel.hidden = count === 0;
                qualityPanel.textContent = count > 0 ? 'Routing audio via MediaMTX SFU' : 'Waiting...';
            }
        });
    };
    wait();
})();
