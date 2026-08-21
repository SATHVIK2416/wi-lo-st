/**
 * SonicSync Client-Side NTP Clock Filter and PI Phase-Locked Loop (PLL).
 */

class NTPClientSync {
    constructor(windowSize = 20) {
        this.windowSize = windowSize;
        this.measurements = [];
        this.offset = 0.0;
        this.rtt = 0.0;
        this.isLocked = false;
        this.confidence = 0.0;
        this.driftPpm = 0.0;

        this._history = []; // [time, offset]
    }

    addMeasurement(t0, t1, t2, t3) {
        // Reject bogus exchanges (reply before request / negative raw RTT)
        if (t3 < t0 || ((t3 - t0) - (t2 - t1)) < 0) {
            return { offset: this.offset, rtt: this.rtt, isLocked: this.isLocked, driftPpm: this.driftPpm, confidence: this.confidence };
        }
        const offset = ((t1 - t0) + (t2 - t3)) / 2.0;
        const rtt = Math.max(0.0, (t3 - t0) - (t2 - t1));

        this.measurements.push({ offset, rtt });
        if (this.measurements.length > this.windowSize) {
            this.measurements.shift();
        }

        this._recalculate(t3);
        return { offset: this.offset, rtt: this.rtt, isLocked: this.isLocked, driftPpm: this.driftPpm, confidence: this.confidence };
    }

    _recalculate(currentTime) {
        if (this.measurements.length < 3) {
            this.isLocked = false;
            this.confidence = this.measurements.length / 5.0;
            const last = this.measurements[this.measurements.length - 1];
            this.offset = last.offset;
            this.rtt = last.rtt;
            return;
        }

        // Sort by RTT and select the best 60% (lowest-RTT samples are the
        // most accurate offset estimates on Wi-Fi)
        const sorted = [...this.measurements].sort((a, b) => a.rtt - b.rtt);
        const bestCount = Math.max(2, Math.floor(sorted.length * 0.6));
        const best = sorted.slice(0, bestCount);

        let sumWeight = 0;
        let weightedOffset = 0;
        for (const m of best) {
            const w = 1.0 / Math.max(0.0001, m.rtt);
            sumWeight += w;
            weightedOffset += m.offset * w;
        }

        this.offset = weightedOffset / sumWeight;
        this.rtt = best[0].rtt;

        // Confidence from offset spread across the best subset; lock requires
        // sample count AND low variance so a terrible link never claims lock
        let mean = 0;
        for (const m of best) mean += m.offset;
        mean /= best.length;
        let variance = 0;
        for (const m of best) variance += (m.offset - mean) * (m.offset - mean);
        const stdMs = Math.sqrt(variance / best.length) * 1000.0;
        this.confidence = Math.max(0.1, Math.min(1.0, 1.0 - stdMs / 10.0));
        this.isLocked = this.measurements.length >= 5 && this.confidence >= 0.5;

        // Record history for drift regression
        this._history.push([currentTime, this.offset]);
        if (this._history.length > 30) this._history.shift();

        if (this._history.length >= 5) {
            const span = this._history[this._history.length - 1][0] - this._history[0][0];
            if (span > 3.0) {
                let sumT = 0, sumO = 0;
                const n = this._history.length;
                for (const [t, o] of this._history) { sumT += t; sumO += o; }
                const meanT = sumT / n, meanO = sumO / n;

                let num = 0, den = 0;
                for (const [t, o] of this._history) {
                    num += (t - meanT) * (o - meanO);
                    den += (t - meanT) * (t - meanT);
                }
                if (den > 1e-9) {
                    const slope = num / den;
                    this.driftPpm = Math.max(-500, Math.min(500, slope * 1e6));
                }
            }
        }
    }
}

class ClientPLLController {
    constructor(targetDelaySec = 0.100) {
        this.targetDelaySec = targetDelaySec;
        this.kp = 0.04;
        this.ki = 0.004;
        this.maxAdjustment = 0.0005; // ±0.05% max
        this.integralError = 0.0;
        this.currentRatio = 1.0;
        this.lastError = 0.0;
    }

    update(currentBufferDelaySec, dt = 0.1) {
        dt = Math.max(0.01, Math.min(1.0, dt));
        const error = currentBufferDelaySec - this.targetDelaySec;
        this.lastError = error;

        this.integralError += error * dt;
        const maxInt = this.maxAdjustment / Math.max(1e-6, this.ki);
        this.integralError = Math.max(-maxInt, Math.min(maxInt, this.integralError));

        const rawAdj = (this.kp * error) + (this.ki * this.integralError);
        const clampedAdj = Math.max(-this.maxAdjustment, Math.min(this.maxAdjustment, rawAdj));

        // Smooth toward target ratio
        const targetRatio = 1.0 + clampedAdj;
        this.currentRatio += (targetRatio - this.currentRatio) * Math.min(1.0, dt * 5.0);

        return this.currentRatio;
    }
}

if (typeof module !== 'undefined') {
    module.exports = { NTPClientSync, ClientPLLController };
}
