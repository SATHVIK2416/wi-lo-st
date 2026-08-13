"""Media metadata extraction and representations for VLC source."""

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class MediaMetadata:
    """Metadata container for currently playing media."""
    title: str = "Unknown Title"
    artist: str = "Unknown Artist"
    album: str = "Unknown Album"
    genre: str = "Unknown Genre"
    track_number: Optional[int] = None
    duration_ms: int = 0
    artwork_url: Optional[str] = None
    uri: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def extract_vlc_metadata(media) -> MediaMetadata:
    """Extract metadata fields from a vlc.Media instance."""
    if media is None:
        return MediaMetadata()

    try:
        import vlc
        media.parse() if hasattr(media, 'parse') else None

        title = media.get_meta(vlc.Meta.Title) or ""
        artist = media.get_meta(vlc.Meta.Artist) or ""
        album = media.get_meta(vlc.Meta.Album) or ""
        genre = media.get_meta(vlc.Meta.Genre) or ""
        track_num = media.get_meta(vlc.Meta.TrackNumber)
        art_url = media.get_meta(vlc.Meta.ArtworkURL)
        duration = media.get_duration()
        uri = media.get_mrl() or ""

        # Fallback to filename if title is empty
        if not title and uri:
            import os
            title = os.path.basename(uri.replace("file:///", "").replace("file://", ""))

        return MediaMetadata(
            title=title or "Unknown Title",
            artist=artist or "Unknown Artist",
            album=album or "Unknown Album",
            genre=genre or "Unknown Genre",
            track_number=int(track_num) if (track_num and track_num.isdigit()) else None,
            duration_ms=max(0, duration),
            artwork_url=art_url,
            uri=uri
        )
    except Exception:
        return MediaMetadata()
