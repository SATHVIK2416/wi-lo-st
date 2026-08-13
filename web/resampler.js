/**
 * SonicSync 4-point Hermite and Cubic Sub-Sample Micro-Resampler.
 */

class HermiteResampler {
    constructor(channels = 2) {
        this.channels = channels;
    }

    /**
     * Resample a multi-channel Float32 buffer by an exact speed ratio.
     * @param {Float32Array[]} inputChannels Array of Float32Array per channel [left, right]
     * @param {number} ratio Playback speed ratio (e.g. 1.0005 = 0.05% faster)
     * @returns {Float32Array[]} Resampled Float32Array per channel
     */
    resample(inputChannels, ratio) {
        if (Math.abs(ratio - 1.0) < 1e-6) {
            return inputChannels;
        }

        const inLength = inputChannels[0].length;
        if (inLength < 4) {
            return inputChannels;
        }

        const outLength = Math.max(1, Math.round(inLength / ratio));
        const outChannels = [];

        for (let ch = 0; ch < this.channels; ch++) {
            const inData = inputChannels[ch];
            const outData = new Float32Array(outLength);

            for (let outIdx = 0; outIdx < outLength; outIdx++) {
                const t = (outIdx * ratio);
                const i = Math.floor(t);
                const frac = t - i;

                const i0 = Math.max(0, Math.min(inLength - 1, i - 1));
                const i1 = Math.max(0, Math.min(inLength - 1, i));
                const i2 = Math.max(0, Math.min(inLength - 1, i + 1));
                const i3 = Math.max(0, Math.min(inLength - 1, i + 2));

                const y0 = inData[i0];
                const y1 = inData[i1];
                const y2 = inData[i2];
                const y3 = inData[i3];

                // 4-point Catmull-Rom / Hermite spline interpolation
                const c0 = y1;
                const c1 = 0.5 * (y2 - y0);
                const c2 = y0 - 2.5 * y1 + 2.0 * y2 - 0.5 * y3;
                const c3 = 0.5 * (y3 - y0) + 1.5 * (y1 - y2);

                outData[outIdx] = ((c3 * frac + c2) * frac + c1) * frac + c0;
            }
            outChannels.push(outData);
        }

        return outChannels;
    }
}

if (typeof module !== 'undefined') {
    module.exports = { HermiteResampler };
}
