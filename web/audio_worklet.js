/**
 * SonicSync AudioWorklet Sample Streaming Processor.
 * Runs on dedicated high-priority audio thread for zero-dropout playout.
 */

class SonicSyncProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.capacity = 192000; // 4s buffer @ 48kHz
        this.bufferL = new Float32Array(this.capacity);
        this.bufferR = new Float32Array(this.capacity);

        this.writeIdx = 0;
        this.readPos = 0.0;
        this.bufferedFrames = 0;
        this.resampleRatio = 1.0;
        this.isPlaying = false;

        this.port.onmessage = (e) => {
            const data = e.data;
            if (data.type === 'push') {
                this.pushSamples(data.left, data.right);
            } else if (data.type === 'set_ratio') {
                this.resampleRatio = Math.max(0.9990, Math.min(1.0010, data.ratio));
            } else if (data.type === 'clear') {
                this.clear();
            }
        };
    }

    pushSamples(left, right) {
        const len = left.length;
        for (let i = 0; i < len; i++) {
            const idx = (this.writeIdx + i) % this.capacity;
            this.bufferL[idx] = left[i];
            this.bufferR[idx] = right ? right[i] : left[i];
        }
        this.writeIdx = (this.writeIdx + len) % this.capacity;
        this.bufferedFrames += len;

        // Auto-start when we have buffered >= 60ms (2880 frames @ 48kHz)
        if (!this.isPlaying && this.bufferedFrames >= 2880) {
            this.isPlaying = true;
        }
    }

    clear() {
        this.writeIdx = 0;
        this.readPos = 0.0;
        this.bufferedFrames = 0;
        this.isPlaying = false;
        this.bufferL.fill(0);
        this.bufferR.fill(0);
    }

    process(inputs, outputs, parameters) {
        const output = outputs[0];
        const outL = output[0];
        const outR = output[1] || output[0];
        const blockSize = outL.length;

        if (!this.isPlaying || this.bufferedFrames < blockSize) {
            outL.fill(0);
            if (output[1]) outR.fill(0);
            return true;
        }

        const cap = this.capacity;
        let pos = this.readPos;
        const ratio = this.resampleRatio;

        for (let i = 0; i < blockSize; i++) {
            const iPos = Math.floor(pos);
            const frac = pos - iPos;

            const i0 = (iPos - 1 + cap) % cap;
            const i1 = iPos % cap;
            const i2 = (iPos + 1) % cap;
            const i3 = (iPos + 2) % cap;

            // Hermite interpolation Left channel
            const l0 = this.bufferL[i0], l1 = this.bufferL[i1], l2 = this.bufferL[i2], l3 = this.bufferL[i3];
            const lc0 = l1;
            const lc1 = 0.5 * (l2 - l0);
            const lc2 = l0 - 2.5 * l1 + 2.0 * l2 - 0.5 * l3;
            const lc3 = 0.5 * (l3 - l0) + 1.5 * (l1 - l2);
            outL[i] = ((lc3 * frac + lc2) * frac + lc1) * frac + lc0;

            // Hermite interpolation Right channel
            const r0 = this.bufferR[i0], r1 = this.bufferR[i1], r2 = this.bufferR[i2], r3 = this.bufferR[i3];
            const rc0 = r1;
            const rc1 = 0.5 * (r2 - r0);
            const rc2 = r0 - 2.5 * r1 + 2.0 * r2 - 0.5 * r3;
            const rc3 = 0.5 * (r3 - r0) + 1.5 * (r1 - r2);
            outR[i] = ((rc3 * frac + rc2) * frac + rc1) * frac + rc0;

            pos = (pos + ratio) % cap;
        }

        const consumed = blockSize * ratio;
        this.readPos = pos;
        this.bufferedFrames = Math.max(0, this.bufferedFrames - consumed);

        // Report buffer watermark every 8 blocks (~20ms)
        if ((currentFrame % (blockSize * 8)) === 0) {
            this.port.postMessage({
                type: 'watermark',
                buffered_frames: this.bufferedFrames,
                buffered_ms: (this.bufferedFrames / 48000) * 1000.0
            });
        }

        return true;
    }
}

registerProcessor('sonicsync-processor', SonicSyncProcessor);
