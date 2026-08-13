"""VLC Media Engine Source with direct decoded PCM/Float32 callback ingestion."""

import ctypes
import logging
import os
from typing import Optional, Callable
import numpy as np

from src.capture.base_source import AudioSource
from src.core.audio_format import AudioFormat, SampleFormat, pcm_to_numpy_float32
from src.vlc.vlc_control import VLCController, VLCPlaybackState
from src.vlc.vlc_playlist import VLCPlaylist, PlaylistItem
from src.vlc.vlc_metadata import extract_vlc_metadata, MediaMetadata

logger = logging.getLogger(__name__)


class VLCSource(AudioSource):
    """VLC Media Source capturing decoded PCM/Float32 directly from libVLC."""

    def __init__(self, audio_format: Optional[AudioFormat] = None):
        super().__init__(audio_format)
        self.playlist = VLCPlaylist()
        self.controller = VLCController()
        self.metadata = MediaMetadata()

        self._instance = None
        self._player = None
        self._current_media = None
        self._callbacks_registered = False

        # Keep references to callbacks so ctypes doesn't garbage collect them
        self._play_cb = None
        self._pause_cb = None
        self._resume_cb = None
        self._flush_cb = None
        self._drain_cb = None

        self._init_vlc()

    def _init_vlc(self):
        """Initialize libVLC instance and player."""
        try:
            import vlc
            # Use headless audio flags
            vlc_args = [
                "--quiet",
                "--no-video",
                "--no-sub-autodetect-file",
                "--aout=amem"  # Audio memory output
            ]
            self._instance = vlc.Instance(*vlc_args)
            self._player = self._instance.media_player_new()
            self.controller.attach_player(self._player)
            self._setup_callbacks()
            logger.info("libVLC audio memory engine initialized successfully.")
        except Exception as e:
            logger.warning(f"Could not initialize libVLC audio engine: {e}. Media controls will run in virtual mode.")

    def _setup_callbacks(self):
        """Set up audio memory callbacks for direct float32 frame capture."""
        if self._player is None or self._instance is None:
            return

        import vlc

        # Audio format callback or setup
        sr = self.audio_format.sample_rate
        ch = self.audio_format.channels

        # Configure memory audio output format: FL32 (Float 32-bit native)
        try:
            self._player.audio_set_format("FL32", sr, ch)
        except Exception as e:
            logger.debug(f"audio_set_format error: {e}")

        # Define ctypes callbacks
        # play_cb: void (*play)(void *data, const void *samples, unsigned count, int64_t pts)
        def _on_play(data_ptr, samples_ptr, count, pts):
            if count <= 0 or not samples_ptr:
                return
            try:
                # 4 bytes per float32 * channels * count
                byte_count = count * ch * 4
                raw_bytes = ctypes.string_at(samples_ptr, byte_count)
                arr = np.frombuffer(raw_bytes, dtype=np.float32).reshape(-1, ch)
                self._emit_audio(arr.copy())
            except Exception as ex:
                logger.error(f"Error in VLC play callback: {ex}")

        def _on_pause(data_ptr, pts):
            logger.debug("VLC audio paused callback")

        def _on_resume(data_ptr, pts):
            logger.debug("VLC audio resumed callback")

        def _on_flush(data_ptr, pts):
            logger.debug("VLC audio flushed callback")

        def _on_drain(data_ptr):
            logger.debug("VLC audio drained callback")

        # Wrap in libVLC ctypes callback types if available
        try:
            self._play_cb = vlc.CallbackDecorators.AudioPlayCb(_on_play)
            self._pause_cb = vlc.CallbackDecorators.AudioPauseCb(_on_pause)
            self._resume_cb = vlc.CallbackDecorators.AudioResumeCb(_on_resume)
            self._flush_cb = vlc.CallbackDecorators.AudioFlushCb(_on_flush)
            self._drain_cb = vlc.CallbackDecorators.AudioDrainCb(_on_drain)

            self._player.audio_set_callbacks(
                self._play_cb,
                self._pause_cb,
                self._resume_cb,
                self._flush_cb,
                self._drain_cb,
                None
            )
            self._callbacks_registered = True
        except Exception as e:
            logger.warning(f"Could not bind direct libVLC audio callbacks: {e}")

    def load_media(self, uri_or_path: str, title: str = "") -> bool:
        """Load a media URI or file into player and start/queue."""
        if not uri_or_path:
            return False

        item = self.playlist.add(uri=uri_or_path, title=title)

        if self._instance is not None and self._player is not None:
            try:
                import vlc
                if os.path.exists(uri_or_path):
                    media = self._instance.media_new_path(uri_or_path)
                else:
                    media = self._instance.media_new_location(uri_or_path)

                self._current_media = media
                self._player.set_media(media)
                self.metadata = extract_vlc_metadata(media)
                item.metadata = self.metadata
                return True
            except Exception as e:
                logger.error(f"Failed to load media in VLC: {e}")
                return False

        # Virtual mode
        self.metadata = MediaMetadata(title=item.title, uri=uri_or_path)
        return True

    def play_index(self, index: int) -> bool:
        """Play a specific track from the playlist."""
        item = self.playlist.set_current_index(index)
        if item:
            return self.load_media(item.uri, item.title) and self.controller.play()
        return False

    def next(self) -> bool:
        """Play next track in playlist."""
        item = self.playlist.next()
        if item:
            return self.load_media(item.uri, item.title) and self.controller.play()
        return False

    def previous(self) -> bool:
        """Play previous track in playlist."""
        item = self.playlist.previous()
        if item:
            return self.load_media(item.uri, item.title) and self.controller.play()
        return False

    def get_status(self) -> dict:
        """Get comprehensive VLC player and playlist status dictionary."""
        current_item = self.playlist.get_current()
        return {
            "state": self.controller.get_state(),
            "position": self.controller.get_position(),
            "time_ms": self.controller.get_time_ms(),
            "length_ms": self.controller.get_length_ms() or (self.metadata.duration_ms if self.metadata else 0),
            "volume": self.controller.get_volume(),
            "repeat": self.playlist.repeat_mode,
            "shuffle": self.playlist.shuffle,
            "metadata": self.metadata.to_dict() if self.metadata else {},
            "current_track": current_item.title if current_item else "None",
            "playlist_count": self.playlist.count(),
            "playlist": self.playlist.get_items(),
        }

    def start(self):
        self._is_running = True
        self.controller.play()

    def stop(self):
        self._is_running = False
        self.controller.stop()

    def read(self, num_frames: int) -> np.ndarray:
        return np.zeros((num_frames, self.audio_format.channels), dtype=np.float32)
