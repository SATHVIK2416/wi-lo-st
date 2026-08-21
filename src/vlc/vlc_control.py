"""VLC media playback controller."""

import logging

logger = logging.getLogger(__name__)


class VLCPlaybackState:
    NOTHING_SPECIAL = "idle"
    OPENING = "opening"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    ENDED = "ended"
    ERROR = "error"


class VLCController:
    """Controls playback, position, and volume of VLC instance."""

    def __init__(self, media_player=None):
        self._player = media_player
        self._volume: int = 100
        self._is_muted: bool = False
        self._mock_state: str = VLCPlaybackState.STOPPED
        self._mock_position: float = 0.0
        self._mock_time_ms: int = 0

    def attach_player(self, media_player):
        self._player = media_player

    def play(self) -> bool:
        if self._player is not None:
            try:
                res = self._player.play()
                # libvlc returns 0 on success / -1 on error; some python-vlc
                # versions return None when playback was merely initiated.
                return True if res is None else int(res) >= 0
            except Exception as e:
                logger.error(f"Error playing VLC player: {e}")
                return False
        self._mock_state = VLCPlaybackState.PLAYING
        return True

    def pause(self) -> bool:
        if self._player is not None:
            try:
                self._player.pause()
                return True
            except Exception as e:
                logger.error(f"Error pausing VLC player: {e}")
                return False
        self._mock_state = VLCPlaybackState.PAUSED
        return True

    def stop(self) -> bool:
        if self._player is not None:
            try:
                self._player.stop()
                return True
            except Exception as e:
                logger.error(f"Error stopping VLC player: {e}")
                return False
        self._mock_state = VLCPlaybackState.STOPPED
        self._mock_position = 0.0
        self._mock_time_ms = 0
        return True

    def toggle_pause(self) -> bool:
        state = self.get_state()
        if state == VLCPlaybackState.PLAYING:
            return self.pause()
        else:
            return self.play()

    def seek(self, position: float) -> bool:
        """Seek to relative position 0.0 to 1.0."""
        pos = max(0.0, min(1.0, float(position)))
        if self._player is not None:
            try:
                self._player.set_position(pos)
                return True
            except Exception as e:
                logger.error(f"Error seeking: {e}")
                return False
        self._mock_position = pos
        return True

    def seek_ms(self, time_ms: int) -> bool:
        """Seek to absolute millisecond offset."""
        if self._player is not None:
            try:
                self._player.set_time(int(time_ms))
                return True
            except Exception as e:
                logger.error(f"Error seeking time: {e}")
                return False
        self._mock_time_ms = max(0, int(time_ms))
        return True

    def set_volume(self, volume: int) -> bool:
        """Set volume 0 to 100."""
        self._volume = max(0, min(100, int(volume)))
        if self._player is not None:
            try:
                self._player.audio_set_volume(self._volume)
                return True
            except Exception as e:
                logger.debug(f"Could not set VLC volume: {e}")
        return True

    def get_volume(self) -> int:
        if self._player is not None:
            try:
                v = self._player.audio_get_volume()
                if v >= 0:
                    self._volume = v
            except Exception as e:
                logger.warning(f"Could not read VLC volume: {e}")
        return self._volume

    def set_mute(self, mute: bool) -> bool:
        self._is_muted = bool(mute)
        if self._player is not None:
            try:
                self._player.audio_set_mute(self._is_muted)
                return True
            except Exception as e:
                logger.warning(f"Could not set VLC mute state: {e}")
        return True

    def get_state(self) -> str:
        """Get standardized playback state string."""
        if self._player is not None:
            try:
                import vlc
                state = self._player.get_state()
                mapping = {
                    vlc.State.NothingSpecial: VLCPlaybackState.NOTHING_SPECIAL,
                    vlc.State.Opening: VLCPlaybackState.OPENING,
                    vlc.State.Buffering: VLCPlaybackState.BUFFERING,
                    vlc.State.Playing: VLCPlaybackState.PLAYING,
                    vlc.State.Paused: VLCPlaybackState.PAUSED,
                    vlc.State.Stopped: VLCPlaybackState.STOPPED,
                    vlc.State.Ended: VLCPlaybackState.ENDED,
                    vlc.State.Error: VLCPlaybackState.ERROR,
                }
                return mapping.get(state, VLCPlaybackState.STOPPED)
            except Exception as e:
                logger.warning(f"Could not read VLC playback state: {e}")
        return self._mock_state

    def get_position(self) -> float:
        """Get current position in track (0.0 to 1.0)."""
        if self._player is not None:
            try:
                pos = self._player.get_position()
                if pos >= 0:
                    return float(pos)
            except Exception as e:
                logger.warning(f"Could not read VLC position: {e}")
        return self._mock_position

    def get_time_ms(self) -> int:
        """Get current playback time in milliseconds."""
        if self._player is not None:
            try:
                t = self._player.get_time()
                if t >= 0:
                    return int(t)
            except Exception as e:
                logger.warning(f"Could not read VLC playback time: {e}")
        return self._mock_time_ms

    def get_length_ms(self) -> int:
        """Get media total length in milliseconds."""
        if self._player is not None:
            try:
                l = self._player.get_length()
                if l >= 0:
                    return int(l)
            except Exception as e:
                logger.warning(f"Could not read VLC media length: {e}")
        return 0
