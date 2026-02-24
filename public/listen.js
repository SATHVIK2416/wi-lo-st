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

    let socket, pc, audioEl, audioContext, analyser, hostId = null;
    let muted = false, volume = 1;
    let currentLatencyMs = 150; // default latency
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

    // Enhance SDP for maximum Opus quality
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
            dom.connection.textContent = 'Connected';
            dom.connection.style.color = '#4ade80';
        });

        socket.on('disconnect', () => {
            dom.connection.textContent = 'Disconnected';
            dom.connection.style.color = '#f87171';
            setStatus('Disconnected', 'error');
            teardown();
        });

        socket.on('no-host', () => {
            setStatus('No host', 'error');
            flash('No host streaming');
            dom.enableBtn.hidden = false;
        });

        socket.on('host-left', () => { setStatus('Host left', 'error'); teardown(); });
        socket.on('host-stopped', () => { setStatus('Stopped', ''); teardown(); });
        socket.on('host-streaming', () => { if (dom.enableBtn.hidden) socket.emit('viewer-join'); });

        socket.on('webrtc-offer', async ({ sdp, hostId: hid }) => {
            hostId = hid;
            await setupPeerConnection();

            // Enhance the incoming offer SDP
            const enhancedOffer = enhanceOpusSDP(sdp);
            await pc.setRemoteDescription(new RTCSessionDescription({ type: 'offer', sdp: enhancedOffer }));

            const answer = await pc.createAnswer();

            // Enhance the answer SDP to request maximum quality
            answer.sdp = enhanceOpusSDP(answer.sdp);

            await pc.setLocalDescription(answer);
            socket.emit('webrtc-answer', { hostId, sdp: answer });
            
            // Apply playout delay after SDP exchange
            setTimeout(applyPlayoutDelay, 500);
        });

        socket.on('webrtc-ice-candidate', ({ candidate, from }) => {
            if (pc && candidate && from === hostId) {
                pc.addIceCandidate(new RTCIceCandidate(candidate)).catch(() => { });
            }
        });

        socket.on('stats', ({ viewerCount }) => {
            dom.clients.textContent = `${viewerCount} listeners`;
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

        pc = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
        });

        pc.onicecandidate = e => {
            if (e.candidate && hostId) {
                socket.emit('webrtc-ice-candidate', { targetId: hostId, candidate: e.candidate });
            }
        };

        pc.ontrack = e => {
            const stream = e.streams[0];

            // Create audio element
            if (!audioEl) {
                audioEl = document.createElement('audio');
                audioEl.autoplay = true;
                audioEl.playsInline = true;
                document.body.appendChild(audioEl);
            }

            audioEl.srcObject = stream;
            audioEl.volume = volume;

            // Apply playout delay when track arrives
            if ('playoutDelayHint' in e.receiver) {
                e.receiver.playoutDelayHint = currentLatencyMs / 1000;
            }

            // Create audio context for visualization
            if (!audioContext) {
                audioContext = new (window.AudioContext || window.webkitAudioContext)({
                    sampleRate: 48000
                });
                analyser = audioContext.createAnalyser();
                analyser.fftSize = 64;

                const source = audioContext.createMediaStreamSource(stream);
                source.connect(analyser);
                // Don't connect to destination - audio element handles playback
            }

            audioEl.play().catch(() => setStatus('Tap to enable', 'error'));
            setStatus('LIVE', 'live');
            animate();
        };

        pc.onconnectionstatechange = () => {
            const state = pc.connectionState;
            if (['failed', 'disconnected', 'closed'].includes(state)) {
                teardown();
            }
        };
    };

    const joinStream = () => {
        dom.enableBtn.hidden = true;
        dom.muteBtn.hidden = false;
        setStatus('Joining...', '');
        socket.emit('viewer-join');
    };

    const toggleMute = () => {
        muted = !muted;
        if (audioEl) audioEl.muted = muted;
        dom.muteBtn.textContent = muted ? 'Unmute' : 'Mute';
    };

    const teardown = () => {
        if (pc) { pc.close(); pc = null; }
        if (audioEl) { audioEl.srcObject = null; audioEl.remove(); audioEl = null; }
        if (audioContext) { audioContext.close(); audioContext = null; analyser = null; }
        bars.forEach(b => b.style.height = '4px');
        dom.enableBtn.hidden = false;
        dom.muteBtn.hidden = true;
        setStatus('Waiting', '');
    };

    const animate = () => {
        if (!analyser) return;

        const data = new Uint8Array(analyser.frequencyBinCount);

        const step = () => {
            if (!pc || !au
