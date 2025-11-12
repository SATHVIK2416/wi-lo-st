// Host control script (cleaned) – functionality unchanged
(() => {
    'use strict';

    // DOM refs
    const $ = id => document.getElementById(id);
    const shareUrlInput = $('shareUrlInput');
    const copyUrlBtn = $('copyUrl');
    const listenUrlInput = $('listenUrlInput');
    const copyListenUrlBtn = $('copyListenUrl');
    const networkInfo = $('networkAddresses');
    const startAudioBtn = $('startAudioStream');
    const stopAudioBtn = $('stopAudioStream');
    const audioStatus = $('audioStatus');
    const audioLevelBar = $('audioLevelBar');
    const connectionStatus = $('connectionStatus');
    const clientsCount = $('clientsCount');
    const notificationEl = $('notification');
    const latencyInput = $('latencyInput');
    const bitrateInput = $('bitrateInput');
    const applyTuningBtn = $('applyTuning');
    const tuneStatus = $('tuneStatus');

    // State
    let socket; let mediaStream; let audioContext; let analyser; let isStreaming=false; let audioTrack;
    const peers = new Map();
    const senderRegistry = new Map();
    const pendingViewers = new Set();
    let desiredLatencyMs = 150; let desiredBitrateKbps = 510; // Max Opus bitrate for music quality

    document.addEventListener('DOMContentLoaded', () => { initSocket(); loadNetworkInfo(); bindUI(); });

    function bindUI(){
        copyUrlBtn && copyUrlBtn.addEventListener('click', () => copyField(shareUrlInput,'Control page URL copied'));
        copyListenUrlBtn && copyListenUrlBtn.addEventListener('click', () => copyField(listenUrlInput,'Listener URL copied'));
        startAudioBtn && startAudioBtn.addEventListener('click', startAudio);
        stopAudioBtn && stopAudioBtn.addEventListener('click', stopAudio);
        applyTuningBtn && applyTuningBtn.addEventListener('click', applyTuningToAll);
    }

    function initSocket(){
        socket = io();
        socket.on('connect', () => { connectionStatus.textContent='🟢 Connected'; connectionStatus.style.color='#38a169'; });
        socket.on('disconnect', () => { connectionStatus.textContent='🔴 Disconnected'; connectionStatus.style.color='#e53e3e'; });
        socket.on('stats', ({ viewerCount }) => { clientsCount.textContent = `👥 ${viewerCount} listening`; });
        socket.on('viewer-joined', async ({ viewerId }) => { if(!audioTrack){ pendingViewers.add(viewerId); return; } await createPeer(viewerId); });
        socket.on('webrtc-answer', async ({ sdp, viewerId }) => { const pc = peers.get(viewerId); if(!pc) return; try{ await pc.setRemoteDescription(new RTCSessionDescription(sdp)); }catch(e){ console.error('setRemoteDescription',e);} });
        socket.on('webrtc-ice-candidate', async ({ candidate, from }) => { const pc = peers.get(from); if(pc && candidate) try{ await pc.addIceCandidate(new RTCIceCandidate(candidate)); }catch(e){ console.warn('ICE add failed',e);} });
        socket.on('viewer-left', ({ viewerId }) => { const pc = peers.get(viewerId); if(pc){ pc.close(); peers.delete(viewerId); senderRegistry.delete(viewerId);} });
        socket.emit('register-host');
    }

    async function loadNetworkInfo(){
        try {
            const res = await fetch('/network-info');
            const data = await res.json();
            let html = `<div class="network-address"><strong>Local:</strong> ${data.localUrl}</div>`;
            data.addresses.forEach(a => { html += `<div class="network-address"><strong>${a.interface}:</strong> ${a.url}</div>`; });
            networkInfo.innerHTML = html;
            const shareUrl = data.addresses[0]?.url || data.localUrl;
            shareUrlInput && (shareUrlInput.value = shareUrl);
            listenUrlInput && (listenUrlInput.value = shareUrl + '/listen');
        } catch(e){ networkInfo.innerHTML = '<div class="network-address"><strong>Error:</strong> Could not load network information</div>'; }
    }

    function copyField(el,msg){ if(!el) return; el.select(); el.setSelectionRange(0,99999); try{ document.execCommand('copy'); notify(msg,'success'); }catch{ notify('Copy failed','error'); } }
    function notify(message,type='info'){ if(!notificationEl) return; notificationEl.textContent=message; notificationEl.className=`notification ${type} show`; setTimeout(()=>notificationEl.classList.remove('show'),2500); }

    async function startAudio(){
        try {
            mediaStream = await navigator.mediaDevices.getDisplayMedia({ video:{ frameRate:{ ideal:5,max:10 }, width:{ ideal:640 }, height:{ ideal:360 } }, audio:{ echoCancellation:false, noiseSuppression:false, autoGainControl:false, suppressLocalAudioPlayback:false, sampleRate:{ ideal:48000 }, sampleSize:{ ideal:16 }, channelCount:{ ideal:2 } } });
            const audioTracks = mediaStream.getAudioTracks();
            if(!audioTracks.length) throw new Error('No audio track available. Ensure "Share audio" is checked.');
            const audioOnlyStream = new MediaStream([audioTracks[0]]);
            audioContext = new (window.AudioContext||window.webkitAudioContext)();
            const src = audioContext.createMediaStreamSource(audioOnlyStream); analyser = audioContext.createAnalyser(); analyser.fftSize=256; src.connect(analyser);
            audioTrack = audioOnlyStream.getAudioTracks()[0];
            try { mediaStream.getVideoTracks().forEach(v=>v.applyConstraints({ frameRate:{ max:5 }, width:{ ideal:320 }, height:{ ideal:180 } })); } catch(_){ }
            if(pendingViewers.size){ for(const id of pendingViewers) await createPeer(id); pendingViewers.clear(); }
            isStreaming=true; startAudioBtn.style.display='none'; stopAudioBtn.style.display='inline-flex'; audioStatus.textContent='🔊 Streaming system audio...'; audioStatus.style.color='#e53e3e';
            visualizeLevel(); notify('System audio streaming started (WebRTC)','success'); socket.emit('announce-streaming');
            mediaStream.getVideoTracks().forEach(t=> t.onended = () => stopAudio());
            audioOnlyStream.getAudioTracks().forEach(t=> t.onended = () => stopAudio());
        } catch(e){
            const msg = e?.name==='NotAllowedError' ? 'Screen sharing denied.' : (e.message.includes('No audio track') ? 'No audio track – check the Share audio box.' : 'Failed to start: '+e.message);
            notify(msg,'error');
        }
    }

    function stopAudio(){
        if(mediaStream){ mediaStream.getTracks().forEach(t=>{ try{ t.stop(); }catch(_){} }); mediaStream=null; }
        if(audioContext){ audioContext.close(); audioContext=null; }
        isStreaming=false; startAudioBtn.style.display='inline-flex'; stopAudioBtn.style.display='none'; audioStatus.textContent='🔇 System audio not shared'; audioStatus.style.color='#718096'; audioLevelBar.style.width='0%';
        peers.forEach(pc=>pc.close()); peers.clear(); audioTrack=null; pendingViewers.clear(); senderRegistry.clear(); 
        socket.emit('host-stopped-streaming'); // Notify server that streaming stopped
        notify('System audio streaming stopped','info');
    }

    function visualizeLevel(){ if(!analyser||!isStreaming) return; const len=analyser.frequencyBinCount; const data=new Uint8Array(len); (function loop(){ if(!isStreaming) return; analyser.getByteFrequencyData(data); const avg=data.reduce((s,v)=>s+v,0)/len; audioLevelBar.style.width=((avg/255)*100)+'%'; requestAnimationFrame(loop); })(); }

    async function createPeer(viewerId){ 
        if(!audioTrack) return; 
        const pc = new RTCPeerConnection({ 
            iceServers:[{ urls:'stun:stun.l.google.com:19302' }],
            sdpSemantics: 'unified-plan'
        }); 
        peers.set(viewerId, pc); 
        
        pc.onicecandidate = e=>{ 
            if(e.candidate) socket.emit('webrtc-ice-candidate',{ targetId:viewerId, candidate:e.candidate }); 
        }; 
        
        pc.onconnectionstatechange=()=>{ 
            if(['failed','disconnected','closed'].includes(pc.connectionState)){ 
                pc.close(); 
                peers.delete(viewerId); 
                if(audioTrack && pc.connectionState==='failed'){ 
                    setTimeout(()=>{ if(audioTrack && !peers.has(viewerId)) createPeer(viewerId); },1000); 
                } 
            } 
        }; 
        
        const outboundStream = new MediaStream([audioTrack]); 
        const sender = pc.addTrack(audioTrack, outboundStream); 
        senderRegistry.set(viewerId, sender); 
        
        // Configure Opus for high-quality music (stereo, full bandwidth)
        try{ 
            if(RTCRtpSender.getCapabilities){ 
                const caps=RTCRtpSender.getCapabilities('audio'); 
                if(caps&&caps.codecs){ 
                    // Find stereo Opus with highest sample rate
                    const opusStereo = caps.codecs.find(c => 
                        c.mimeType === 'audio/opus' && 
                        c.sdpFmtpLine && 
                        c.sdpFmtpLine.includes('stereo=1')
                    );
                    const opusAny = caps.codecs.filter(c=>c.mimeType === 'audio/opus');
                    const others=caps.codecs.filter(c=>c.mimeType !== 'audio/opus');
                    
                    // Prefer stereo Opus, then any Opus, then others
                    const ordered = opusStereo ? [opusStereo, ...opusAny, ...others] : [...opusAny, ...others];
                    
                    const tx=pc.getTransceivers().find(t=>t.sender===sender); 
                    if(tx&&tx.setCodecPreferences) tx.setCodecPreferences(ordered); 
                } 
            }
        }catch(e){ console.warn('Codec preference failed:', e); }
        
        tuneSender(sender); 
        
        const tx=pc.getTransceivers().find(t=>t.sender&&t.sender.track===audioTrack); 
        if(tx){ 
            try{ tx.direction='sendonly'; }catch(_){} 
        } 
        
        // Create offer with high-quality audio constraints
        const offer = await pc.createOffer({
            offerToReceiveAudio: false,
            offerToReceiveVideo: false,
            voiceActivityDetection: false
        });
        
        // Modify SDP to force stereo, full bandwidth, and disable packet loss concealment
        offer.sdp = enhanceOpusSDP(offer.sdp);
        
        await pc.setLocalDescription(offer); 
        socket.emit('webrtc-offer',{ viewerId, sdp:offer }); 
    }
    
    function enhanceOpusSDP(sdp) {
        // Split SDP into lines
        const lines = sdp.split('\r\n');
        let opusPayloadType = null;
        
        // Find Opus payload type
        for (const line of lines) {
            if (line.includes('opus/48000/2')) {
                const match = line.match(/rtpmap:(\d+)/);
                if (match) opusPayloadType = match[1];
                break;
            }
        }
        
        if (!opusPayloadType) return sdp;
        
        // Enhance SDP for music quality
        const enhanced = [];
        let foundFmtp = false;
        
        for (let line of lines) {
            // Update existing fmtp line for Opus
            if (line.startsWith(`a=fmtp:${opusPayloadType}`)) {
                foundFmtp = true;
                // Force stereo, max bitrate, full bandwidth, disable FEC/DTX for quality
                line = `a=fmtp:${opusPayloadType} minptime=10; useinbandfec=0; stereo=1; sprop-stereo=1; maxaveragebitrate=510000; maxplaybackrate=48000; cbr=0; usedtx=0; complexity=10`;
            }
            enhanced.push(line);
            
            // Add fmtp if it doesn't exist
            if (!foundFmtp && line.includes(`rtpmap:${opusPayloadType} opus/48000`)) {
                enhanced.push(`a=fmtp:${opusPayloadType} minptime=10; useinbandfec=0; stereo=1; sprop-stereo=1; maxaveragebitrate=510000; maxplaybackrate=48000; cbr=0; usedtx=0; complexity=10`);
                foundFmtp = true;
            }
        }
        
        return enhanced.join('\r\n');
    }

    function tuneSender(sender){ 
        if(!sender) return; 
        try{ 
            const params=sender.getParameters(); 
            if(!params.encodings) params.encodings=[{}]; 
            const enc=params.encodings[0]; 
            
            // High bitrate for music quality
            enc.maxBitrate=Math.round(desiredBitrateKbps*1000); 
            enc.minBitrate=Math.round(desiredBitrateKbps*1000*0.9); // Higher minimum
            enc.networkPriority='high'; 
            enc.priority='high'; 
            
            const target=desiredLatencyMs; 
            let ptime=20; 
            if(target<=140) ptime=10; 
            else if(target>=300) ptime=40; 
            enc.ptime=ptime; 
            enc.dtx=false; // Disable discontinuous transmission for music
            
            sender.setParameters(params).catch(e=>console.warn('setParameters failed:', e)); 
            tuneStatus && (tuneStatus.textContent=`Target: ${desiredLatencyMs}ms / ${desiredBitrateKbps}kbps (ptime ${ptime}ms) • HiFi Mode`);
        }catch(e){
            console.error('tuneSender error:', e);
        }
    }
    
    function applyTuningToAll(){ 
        if(latencyInput) desiredLatencyMs=Math.max(80,Math.min(800,parseInt(latencyInput.value)||150)); 
        if(bitrateInput) desiredBitrateKbps=Math.max(128,Math.min(510,parseInt(bitrateInput.value)||510)); // Allow up to 510kbps
        senderRegistry.forEach(s=>tuneSender(s)); 
        notify('Applied new tuning - Quality: ' + desiredBitrateKbps + 'kbps','info'); 
    }

})();
