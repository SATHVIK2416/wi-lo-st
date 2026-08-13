"""Thread-safe high-performance circular audio ring buffer."""

import threading
import numpy as np


class RingBuffer:
    """Thread-safe circular FIFO buffer for multi-channel float32 audio data."""

    def __init__(self, capacity_frames: int = 192000, channels: int = 2):
        """Initialize RingBuffer with capacity in frames.

        Args:
            capacity_frames: Total number of frames capacity (e.g. 192000 = 4s @ 48kHz).
            channels: Number of audio channels (e.g. 2 for stereo).
        """
        self.capacity_frames = max(1, int(capacity_frames))
        self.channels = int(channels)
        self._buffer = np.zeros((self.capacity_frames, self.channels), dtype=np.float32)

        self._read_idx = 0
        self._write_idx = 0
        self._size = 0
        self._lock = threading.Lock()

        # Telemetry metrics
        self._overruns = 0
        self._underruns = 0
        self._total_written_frames = 0
        self._total_read_frames = 0

    @property
    def overruns(self) -> int:
        return self._overruns

    @property
    def underruns(self) -> int:
        return self._underruns

    @property
    def total_written_frames(self) -> int:
        return self._total_written_frames

    @property
    def total_read_frames(self) -> int:
        return self._total_read_frames

    def available_read(self) -> int:
        """Return number of frames currently available to read."""
        with self._lock:
            return self._size

    def available_write(self) -> int:
        """Return number of frames available before buffer overflows."""
        with self._lock:
            return self.capacity_frames - self._size

    def fill_percentage(self) -> float:
        """Return buffer fill percentage (0.0 to 100.0)."""
        with self._lock:
            return (self._size / self.capacity_frames) * 100.0

    def buffered_duration_ms(self, sample_rate: int = 48000) -> float:
        """Return buffered duration in milliseconds."""
        with self._lock:
            return (self._size / float(sample_rate)) * 1000.0

    def write(self, data: np.ndarray) -> int:
        """Write frames into the circular buffer.

        Args:
            data: Numpy float32 array shaped (frames, channels) or (frames,) for mono.

        Returns:
            int: Number of frames successfully written.
        """
        data = np.asarray(data, dtype=np.float32)
        if data.ndim == 1:
            data = data.reshape(-1, self.channels)

        frames_to_write = data.shape[0]
        if frames_to_write == 0:
            return 0

        with self._lock:
            free_space = self.capacity_frames - self._size

            # If writing more than capacity, only write latest slice that fits
            if frames_to_write > self.capacity_frames:
                self._overruns += (frames_to_write - free_space)
                data = data[-self.capacity_frames:]
                frames_to_write = self.capacity_frames
                self._read_idx = 0
                self._write_idx = 0
                self._size = 0
                free_space = self.capacity_frames
            elif frames_to_write > free_space:
                # Overrun: advance read index to make room
                overflow = frames_to_write - free_space
                self._overruns += overflow
                self._read_idx = (self._read_idx + overflow) % self.capacity_frames
                self._size -= overflow

            # Write chunk(s)
            part1 = min(frames_to_write, self.capacity_frames - self._write_idx)
            part2 = frames_to_write - part1

            self._buffer[self._write_idx:self._write_idx + part1] = data[:part1]
            if part2 > 0:
                self._buffer[0:part2] = data[part1:part1 + part2]

            self._write_idx = (self._write_idx + frames_to_write) % self.capacity_frames
            self._size += frames_to_write
            self._total_written_frames += frames_to_write

            return frames_to_write

    def read(self, num_frames: int, fill_silence: bool = True) -> np.ndarray:
        """Read frames from the circular buffer.

        Args:
            num_frames: Number of frames to read.
            fill_silence: If True, pad missing frames with 0.0 on underrun.

        Returns:
            np.ndarray: Array shaped (num_frames, channels) or available frames if fill_silence is False.
        """
        if num_frames <= 0:
            return np.zeros((0, self.channels), dtype=np.float32)

        with self._lock:
            frames_available = self._size

            if frames_available == 0:
                self._underruns += num_frames
                if fill_silence:
                    return np.zeros((num_frames, self.channels), dtype=np.float32)
                return np.zeros((0, self.channels), dtype=np.float32)

            frames_to_read = min(num_frames, frames_available)
            out = np.zeros((num_frames if fill_silence else frames_to_read, self.channels), dtype=np.float32)

            part1 = min(frames_to_read, self.capacity_frames - self._read_idx)
            part2 = frames_to_read - part1

            out[:part1] = self._buffer[self._read_idx:self._read_idx + part1]
            if part2 > 0:
                out[part1:part1 + part2] = self._buffer[0:part2]

            self._read_idx = (self._read_idx + frames_to_read) % self.capacity_frames
            self._size -= frames_to_read
            self._total_read_frames += frames_to_read

            if frames_to_read < num_frames:
                self._underruns += (num_frames - frames_to_read)
                # Remainder is already zeroed in `out`

            return out

    def peek(self, num_frames: int) -> np.ndarray:
        """Peek frames without advancing read pointer."""
        with self._lock:
            frames_to_read = min(num_frames, self._size)
            if frames_to_read <= 0:
                return np.zeros((0, self.channels), dtype=np.float32)

            out = np.zeros((frames_to_read, self.channels), dtype=np.float32)
            part1 = min(frames_to_read, self.capacity_frames - self._read_idx)
            part2 = frames_to_read - part1

            out[:part1] = self._buffer[self._read_idx:self._read_idx + part1]
            if part2 > 0:
                out[part1:part1 + part2] = self._buffer[0:part2]

            return out

    def clear(self):
        """Reset buffer state and zero memory."""
        with self._lock:
            self._read_idx = 0
            self._write_idx = 0
            self._size = 0
            self._buffer.fill(0.0)
