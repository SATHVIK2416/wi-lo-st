/**
 * SonicSync AudioWorklet Sample Streaming Processor.
 * Runs on the dedicated high-priority audio rendering thread: continuous ring
 * buffer, Hermite sub-sample micro-resampling with phase carry, watermark
 * reporting, and underrun re-priming. The main thread only pushes samples and
 * receives telemetry, so GC pauses and tab jitter never reach the audio path.
 */

class SonicSyncProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.capacity = sampleRate * 4; // 4 s of context-rate audio
        this.bufferL = new Float32Array(this.capacity);
        this.bufferR = new Float32Array(this.capacity);

        this.writeIdx = 0;
        this.readPos = 0.0;
        this.bufferedFrames = 0;

        this.streamRate = 48000;          // rate of incoming audio frames
        this.baseRatio = 1.0;             // streamRate / contextRate
        this.resampleRatio = 1.0;         // PLL micro-adjustment around 1.0
        this.prebufferFrames = Math.round(0.1 * 48000);
        this.isPlaying = false;
        this.wasPlaying = false;

        this.underruns = 0;
        this.overflowDrops = 0;
        this.lastWatermarkFrame = 0;

        this.port.onmessage = (e) => {
            const data = e.data;
            switch (data.type) {
                case 'samples':
                    this.pushSamples(data.left, data.right);
                    break;
                case 'init': {
                    this.streamRate = Math.max(8000, data.streamRate || 48000);
                    this.baseRatio = this.streamRate / sampleRate;
                    this.prebufferFrames = Math.round(((data.prebufferMs || 100) / 1000) * this.streamRate);
                    break;
                }
                case 'set_ratio':
                    // PLL corrections stay within ±0.05% (500 ppm)
                    this.resampleRatio = Math.max(0.9995, Math.min(1.0005, data.ratio));
                    break;
                case 'clear':
                    this.clear();
                    break;
            }
        };
    }

    pushSamples(left, right) {
        const n = left.length;
        if (n === 0) return;

        // Overflow guard: drop the OLDEST audio so the freshest frames fit.
        // (Wrapping writeIdx over unread audio would corrupt the stream.)
        if (this.bufferedFrames + n > this.capacity) {
            const drop = this.bufferedFrames + n - this.capacity;
            this.readPos = (this.readPos + drop) % this.capacity;
            this.bufferedFrames -= drop;
            this.overflowDrops += drop;
        }

        for (let i = 0; i < n; i++) {
            const idx = (this.writeIdx + i) % this.capacity;
            this.bufferL[idx] = left[i];
            this.bufferR[idx] = right ? right[i] : left[i];
        }
        this.writeIdx = (this.writeIdx + n) % this.capacity;
        this.bufferedFrames += n;

        if (!this.isPlaying && this.bufferedFrames >= this.prebufferFrames) {
            this.isPlaying = true;
            this.readPos = (this.writeIdx - this.bufferedFrames + this.capacity) % this.capacity;
            this.port.postMessage({ type: 'started', buffered_ms: this.bufferedMs() });
        }
    }

    clear() {
        this.writeIdx = 0;
        this.readPos = 0.0;
        this.bufferedFrames = 0;
        this.isPlaying = false;
        this.wasPlaying = false;
        this.bufferL.fill(0);
        this.bufferR.fill(0);
    }

    bufferedMs() {
        return (this.bufferedFrames / this.streamRate) * 1000.0;
    }

    process(inputs, outputs) {
        const output = outputs[0];
        const outL = output[0];
        const outR = output[1] || output[0];
        const blockSize = outL.length;

        if (!this.isPlaying || this.bufferedFrames < blockSize * this.baseRatio * this.resampleRatio + 4) {
            outL.fill(0);
            if (output[1]) outR.fill(0);
            if (this.wasPlaying && this.isPlaying) {
                // Ran dry mid-playback: count it and re-prime from scratch
                this.isPlaying = false;
                this.underruns++;
                this.port.postMessage({ type: 'underrun', total: this.underruns });
            }
            this.reportWatermark();
            return true;
        }
        this.wasPlaying = true;

        const cap = this.capacity;
        const step = this.baseRatio * this.resampleRatio;
        let pos = this.readPos;

        for (let i = 0; i < blockSize; i++) {
            const iPos = Math.floor(pos);
            const frac = pos - iPos;

            const i0 = (iPos - 1 + cap) % cap;
            const i1 = iPos % cap;
            const i2 = (iPos + 1) % cap;
            const i3 = (iPos + 2) % cap;

            const l0 = this.bufferL[i0], l1 = this.bufferL[i1], l2 = this.bufferL[i2], l3 = this.bufferL[i3];
            const lc1 = 0.5 * (l2 - l0);
            const lc2 = l0 - 2.5 * l1 + 2.0 * l2 - 0.5 * l3;
            const lc3 = 0.5 * (l3 - l0) + 1.5 * (l1 - l2);
            outL[i] = ((lc3 * frac + lc2) * frac + lc1) * frac + l1;

            const r0 = this.bufferR[i0], r1 = this.bufferR[i1], r2 = this.bufferR[i2], r3 = this.bufferR[i3];
            const rc1 = 0.5 * (r2 - r0);
            const rc2 = r0 - 2.5 * r1 + 2.0 * r2 - 0.5 * r3;
            const rc3 = 0.5 * (r3 - r0) + 1.5 * (r1 - r2);
            outR[i] = ((rc3 * frac + rc2) * frac + rc1) * frac + r1;

            pos += step;
            if (pos >= cap) pos -= cap;
        }

        this.readPos = pos;
        this.bufferedFrames = Math.max(0, this.bufferedFrames - blockSize * step);

        this.reportWatermark();
        return true;
    }

    reportWatermark() {
        // ~4 reports per second is plenty for PLL control and UI
        if (currentFrame - this.lastWatermarkFrame < sampleRate * 0.25) return;
        this.lastWatermarkFrame = currentFrame;
        this.port.postMessage({
            type: 'watermark',
            buffered_ms: this.bufferedMs(),
            buffered_frames: this.bufferedFrames,
            underruns: this.underruns,
            overflow_drops: this.overflowDrops,
            is_playing: this.isPlaying
        });
    }
}

registerProcessor('sonicsync-processor', SonicSyncProcessor);
