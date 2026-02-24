const fs = require('fs');
let content = fs.readFileSync('public/script.js', 'utf8');

// Replace handle tuning
const tuningLogic = `
    const applyTuning = () => {
        const latency = parseInt(dom.latency.value, 10);
        const bitrateKbps = parseInt(dom.bitrate.value, 10);
        
        if (isNaN(latency) || isNaN(bitrateKbps)) return;

        AUDIO_CONFIG.maxBitrate = bitrateKbps * 1000;
        
        // Update DOM
        if (dom.tuneStatus) {
            dom.tuneStatus.textContent = \`48kHz Stereo | \${bitrateKbps}kbps | \${latency}ms Latency\`;
        }

        // Notify server to tell listeners
        socket.emit('tune-settings', { latency });

        // Update active peers
        peers.forEach(async (pc, viewerId) => {
            const senders = pc.getSenders();
            for (const sender of senders) {
                if (sender.track && sender.track.kind === 'audio') {
                    try {
                        const params = sender.getParameters();
                        if (params.encodings && params.encodings.length > 0) {
                            params.encodings[0].maxBitrate = AUDIO_CONFIG.maxBitrate;
                            await sender.setParameters(params);
                        }
                    } catch (e) {
                        console.warn('Failed to apply new bitrate to peer', e);
                    }
                }
            }
        });
        
        notify(\`Tuning applied: \${bitrateKbps}kbps, \${latency}ms\`, 'success');
    };

    // UI Event Bindings
`;

content = content.replace('    // UI Event Bindings', tuningLogic);
content = content.replace('        dom.startBtn?.addEventListener(\'click\', startAudio);', '        dom.startBtn?.addEventListener(\'click\', startAudio);\n        dom.tuneBtn?.addEventListener(\'click\', applyTuning);');

fs.writeFileSync('public/script.js', content);
