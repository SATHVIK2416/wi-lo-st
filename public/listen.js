(() => {
    'use strict';

    const $ = id => document.getElementById(id);
    const dom = {
        status: $('audioStatus'),
        connection: $('connectionStatus'),
        clients: $('clientsCount'),
        visualizer: $('audioVisualizer'),
        volume: $('volumeSlider'),
        volumeDisplay: $('volumeDisplay'),
        enableBtn: $('enableAudio'),
        muteBtn: $('muteAudio'),
        notification: $('notification'),
        qualityStats: $('qualityStats')
    };

    let socket, pc, audioEl, audioContext, analyser;
    let muted = false, volume = 1;
    let currentLatencyMs = 150;
    const bars = [];

    const setStatus = (msg, type) => {
        dom.status.textContent = msg;
        dom.status.style.color = type === 'error' ? '#f87171' : type === 'live' ? '#4ade80' : '#fff';
    };

    const flash = msg => {
        dom.notification.textContent = msg;
        dom.notification.classList.add('show');
        setTimeout(() => dom.notification.classList.remove('show'), 3000);
    };

    const enhanceOpusSDP = (sdp) => {
        const opusFmtp = 'minptime=10;stereo=1;sprop-stereo=1;maxaveragebitrate=510000;maxplaybackrate=48000;cbr=0;useinbandfec=0;usedtx=0';
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
                result.push(`a=fmtp:${opusPayload} ${opusFmtp}`);
                addedFmtp = true;
            } else {
                result.push(line);
                if (!addedFmtp && line.includes(`rtpmap:${opusPayload} opus`)) {
                    result.push(`a=fmtp:${opusPayload} ${opusFmtp}`);
                    addedFmtp = true;
                }
            }
        }
        return result.join('\r\n');
    };

    const initBars = () => {
        if (!dom.visualizer) return;
        dom.visualizer.innerHTML = '';
        for (let i = 0; i < 32; i++) {
            const bar = document.createElement('div');
            bar.className = 'bar';
            dom.visualizer.appendChild(bar);
            bars.push(bar);
        }
    };

    const applyPlayoutDelay = () => {
        if (!pc) return;
        const receivers = pc.getReceivers();
        for (const receiver of receivers) {
            if (receiver.track && receiver.track.kind === 'audio') {
                if ('playoutDelayHint' in receiver) {
                    receiver.playoutDelayHint = currentLatencyMs / 1000;
                    console.log(`Applied playout delay hint: ${receiver.playoutDelayHint}s`);
                }
            }
        }
    };

    const initSocket = () => {
        socket = io();
        socket.on('connect', () => {
            if (dom.connection) { dom.connection.textContent = 'Connected'; dom.connection.style.color = '#4ade80'; }
        });
        socket.on('disconnect', () => {
            if (dom.connection) { dom.connection.textContent = 'Disconnected'; dom.connection.style.color = '#f87171'; }
            setStatus('Disconnected', 'error');
            teardown();
        });
        socket.on('host-left', () => { setStatus('Host left', 'error'); teardown(); });
        socket.on('host-stopped', () => { setStatus('Stopped', ''); teardown(); });
        socket.on('host-streaming', () => { if (dom.enableBtn && dom.enableBtn.hidden === false) joinStream(); });

        socket.on('stats', ({ viewerCount }) => {
            if (dom.clients) dom.clients.textContent = `${viewerCount} listeners`;
        });
        
        socket.on('tune-settings', ({ latency }) => {
            if (latency) {
                currentLatencyMs = latency;
                applyPlayoutDelay();
                console.log(`Received new tune settings, latency: ${latency}ms`);
            }
        });
    };

    const setupPeerConnection = async () => {
        if (pc) return;

        pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
        pc.addTransceiver('audio', { direction: 'recvonly' });

        pc.ontrack = e => {
            const stream = e.streams[0];
            if (!audioEl) {
                audioEl = document.createElement('audio');
                audioEl.autoplay = true;
                audioEl.playsInline = true;
                document.body.appendChild(audioEl);
            }
            audioEl.srcObject = stream;
            audioEl.volume = volume;

            if ('playoutDelayHint' in e.receiver) {
                e.receiver.playoutDelayHint = currentLatencyMs / 1000;
            }

            if (!audioContext) {
                audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000 });
                analyser = audioContext.createAnalyser();
                analyser.fftSize = 64;
                const source = audioContext.createMediaStreamSource(stream);
                source.connect(analyser);
            }

            audioEl.play().catch(() => setStatus('Tap to enable', 'error'));
            setStatus('LIVE', 'live');
            animate();
        };

        pc.onconnectionstatechange = () => {
            const state = pc.connectionState;
            if (['failed', 'disconnected', 'closed'].includes(state)) teardown();
        };

        const offer = await pc.createOffer();
        offer.sdp = enhanceOpusSDP(offer.sdp);
        await pc.setLocalDescription(offer);

        const whepUrl = `http://${window.location.hostname}:8889/live/whep`;
        const response = await fetch(whepUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/sdp' },
            body: pc.localDescription.sdp
        });

        if (!response.ok) {
            throw new Error(`MediaMTX WHEP failed: ${response.status}`);
        }

        const answerSdp = await response.text();
        const enhancedAnswer = enhanceOpusSDP(answerSdp);
        await pc.setRemoteDescription(new RTCSessionDescription({ type: 'answer', sdp: enhancedAnswer }));
    };

    const joinStream = async () => {
        if (dom.enableBtn) dom.enableBtn.hidden = true;
        if (dom.muteBtn) dom.muteBtn.hidden = false;
        setStatus('Joining...', '');
        
        try {
            await setupPeerConnection();
            socket.emit('viewer-join');
        } catch (e) {
            console.error(e);
            setStatus('Failed to connect', 'error');
            flash('Failed to connect to MediaMTX SFU. Is it running?');
            teardown();
        }
    };

    const toggleMute = () => {
        muted = !muted;
        if (audioEl) audioEl.muted = muted;
        if (dom.muteBtn) dom.muteBtn.textContent = muted ? 'Unmute' : 'Mute';
    };

    const teardown = () => {
        if (pc) { pc.close(); pc = null; }
        if (audioEl) { audioEl.srcObject = null; audioEl.remove(); audioEl = null; }
        if (audioContext) { audioContext.close(); audioContext = null; analyser = null; }
        bars.forEach(b => { if (b) b.style.height = '4px'; });
        if (dom.enableBtn) dom.enableBtn.hidden = false;
        if (dom.muteBtn) dom.muteBtn.hidden = true;
        setStatus('Waiting', '');
    };

    const animate = () => {
        if (!analyser) return;
        const data = new Uint8Array(analyser.frequencyBinCount);
        const step = () => {
            if (!pc || !audioEl) return;
            analyser.getByteFrequencyData(data);
            for (let i = 0; i < bars.length; i++) {
                const value = data[i] || 0;
                const height = Math.max(4, (value / 255) * 100);
                if (bars[i]) bars[i].style.height = `${height}px`;
            }
            requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    };

    dom.enableBtn?.addEventListener('click', joinStream);
    dom.muteBtn?.addEventListener('click', toggleMute);
    dom.volume?.addEventListener('input', e => {
        volume = e.target.value / 100;
        if (audioEl) audioEl.volume = volume;
        if (dom.volumeDisplay) dom.volumeDisplay.textContent = `${e.target.value}%`;
    });

    document.addEventListener('DOMContentLoaded', () => {
        initBars();
        initSocket();
    });

})();
