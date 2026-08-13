"""SonicSync VLC Media Integration Module."""

from src.vlc.vlc_metadata import MediaMetadata, extract_vlc_metadata
from src.vlc.vlc_playlist import VLCPlaylist, PlaylistItem
from src.vlc.vlc_control import VLCController, VLCPlaybackState
from src.vlc.vlc_source import VLCSource
from src.vlc.vlc_loopback_fallback import VLCLoopbackFallbackSource

__all__ = [
    "MediaMetadata",
    "extract_vlc_metadata",
    "VLCPlaylist",
    "PlaylistItem",
    "VLCController",
    "VLCPlaybackState",
    "VLCSource",
    "VLCLoopbackFallbackSource",
]
