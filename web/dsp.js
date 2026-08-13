/**
 * SonicSync Studio Acoustic DSP Chain and Equalizer Presets.
 */

class AudioDSPChain {
    constructor(audioContext) {
        this.ctx = audioContext;

        // Create EQ filters
        this.lowShelf = this.ctx.createBiquadFilter();
        this.lowShelf.type = "lowshelf";
        this.lowShelf.frequency.value = 85;
        this.lowShelf.gain.value = 1.8;

        this.deEsser = this.ctx.createBiquadFilter();
        this.deEsser.type = "peaking";
        this.deEsser.frequency.value = 5500;
        this.deEsser.Q.value = 2.0;
        this.deEsser.gain.value = -2.5;

        this.highShelf = this.ctx.createBiquadFilter();
        this.highShelf.type = "highshelf";
        this.highShelf.frequency.value = 12000;
        this.highShelf.gain.value = -1.5;

        // Dynamics Compressor / Studio Lookahead Limiter
        this.compressor = this.ctx.createDynamicsCompressor();
        this.compressor.threshold.value = -1.0;
        this.compressor.knee.value = 2.0;
        this.compressor.ratio.value = 12.0;
        this.compressor.attack.value = 0.001;
        this.compressor.release.value = 0.050;

        // Master Gain
        this.gainNode = this.ctx.createGain();
        this.gainNode.gain.value = 1.0;

        // Connect chain: input -> lowShelf -> deEsser -> highShelf -> compressor -> gainNode -> destination
        this.inputNode = this.lowShelf;
        this.lowShelf.connect(this.deEsser);
        this.deEsser.connect(this.highShelf);
        this.highShelf.connect(this.compressor);
        this.compressor.connect(this.gainNode);
        this.gainNode.connect(this.ctx.destination);

        this.currentPreset = "cinema";
        this.setPreset("cinema");
    }

    setPreset(presetName) {
        const t = this.ctx.currentTime;
        const ramp = 0.05; // 50ms smooth parameter ramp

        switch (presetName) {
            case "cinema": // Cinema & Smooth Vocals (Default)
                this.lowShelf.frequency.setValueAtTime(85, t);
                this.lowShelf.gain.linearRampToValueAtTime(1.8, t + ramp);
                this.deEsser.frequency.setValueAtTime(5500, t);
                this.deEsser.gain.linearRampToValueAtTime(-2.5, t + ramp);
                this.highShelf.frequency.setValueAtTime(12000, t);
                this.highShelf.gain.linearRampToValueAtTime(-1.5, t + ramp);
                this.compressor.threshold.setValueAtTime(-1.0, t);
                break;

            case "flat": // Direct Bit-Exact Flat
                this.lowShelf.gain.linearRampToValueAtTime(0.0, t + ramp);
                this.deEsser.gain.linearRampToValueAtTime(0.0, t + ramp);
                this.highShelf.gain.linearRampToValueAtTime(0.0, t + ramp);
                this.compressor.threshold.setValueAtTime(-0.1, t);
                break;

            case "tube": // Warm Tube Analog
                this.lowShelf.frequency.setValueAtTime(120, t);
                this.lowShelf.gain.linearRampToValueAtTime(2.8, t + ramp);
                this.deEsser.frequency.setValueAtTime(3000, t);
                this.deEsser.gain.linearRampToValueAtTime(0.5, t + ramp);
                this.highShelf.frequency.setValueAtTime(9000, t);
                this.highShelf.gain.linearRampToValueAtTime(-2.2, t + ramp);
                this.compressor.threshold.setValueAtTime(-2.0, t);
                break;

            case "presence": // Studio Presence & Vocals
                this.lowShelf.frequency.setValueAtTime(100, t);
                this.lowShelf.gain.linearRampToValueAtTime(-1.0, t + ramp);
                this.deEsser.frequency.setValueAtTime(3200, t);
                this.deEsser.gain.linearRampToValueAtTime(2.5, t + ramp);
                this.highShelf.frequency.setValueAtTime(10000, t);
                this.highShelf.gain.linearRampToValueAtTime(1.5, t + ramp);
                this.compressor.threshold.setValueAtTime(-1.5, t);
                break;
        }
        this.currentPreset = presetName;
    }

    setVolume(volumeFraction) {
        const v = Math.max(0.0, Math.min(1.0, volumeFraction));
        this.gainNode.gain.linearRampToValueAtTime(v, this.ctx.currentTime + 0.02);
    }
}

if (typeof module !== 'undefined') {
    module.exports = { AudioDSPChain };
}
