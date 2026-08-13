"""Playlist management for VLC media engine."""

import os
import random
from dataclasses import dataclass, field
from typing import List, Optional
from src.vlc.vlc_metadata import MediaMetadata


@dataclass
class PlaylistItem:
    """An item in the playlist."""
    uri: str
    title: str = ""
    duration_ms: int = 0
    metadata: Optional[MediaMetadata] = None

    def __post_init__(self):
        if not self.title and self.uri:
            # Derive clean title from filename
            clean_uri = self.uri.replace("file:///", "").replace("file://", "")
            self.title = os.path.basename(clean_uri) or self.uri


class VLCPlaylist:
    """Thread-safe playlist manager."""

    def __init__(self):
        self._items: List[PlaylistItem] = []
        self._current_index: int = -1
        self._repeat_mode: str = "off"  # "off", "all", "one"
        self._shuffle: bool = False
        self._unshuffled_indices: List[int] = []

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def repeat_mode(self) -> str:
        return self._repeat_mode

    @repeat_mode.setter
    def repeat_mode(self, mode: str):
        if mode in ("off", "all", "one"):
            self._repeat_mode = mode

    @property
    def shuffle(self) -> bool:
        return self._shuffle

    @shuffle.setter
    def shuffle(self, enabled: bool):
        self._shuffle = bool(enabled)

    def count(self) -> int:
        return len(self._items)

    def get_items(self) -> List[dict]:
        return [
            {
                "index": idx,
                "title": item.title,
                "uri": item.uri,
                "duration_ms": item.duration_ms,
                "is_current": idx == self._current_index
            }
            for idx, item in enumerate(self._items)
        ]

    def add(self, uri: str, title: str = "") -> PlaylistItem:
        item = PlaylistItem(uri=uri, title=title)
        self._items.append(item)
        if self._current_index == -1:
            self._current_index = 0
        return item

    def remove(self, index: int) -> bool:
        if 0 <= index < len(self._items):
            del self._items[index]
            if len(self._items) == 0:
                self._current_index = -1
            elif self._current_index >= len(self._items):
                self._current_index = len(self._items) - 1
            return True
        return False

    def clear(self):
        self._items.clear()
        self._current_index = -1

    def get_current(self) -> Optional[PlaylistItem]:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index]
        return None

    def set_current_index(self, index: int) -> Optional[PlaylistItem]:
        if 0 <= index < len(self._items):
            self._current_index = index
            return self._items[index]
        return None

    def next(self) -> Optional[PlaylistItem]:
        if not self._items:
            return None

        if self._repeat_mode == "one":
            return self.get_current()

        if self._shuffle and len(self._items) > 1:
            next_idx = random.randint(0, len(self._items) - 1)
            self._current_index = next_idx
            return self._items[next_idx]

        if self._current_index + 1 < len(self._items):
            self._current_index += 1
            return self._items[self._current_index]
        elif self._repeat_mode == "all":
            self._current_index = 0
            return self._items[0]

        return None

    def previous(self) -> Optional[PlaylistItem]:
        if not self._items:
            return None

        if self._repeat_mode == "one":
            return self.get_current()

        if self._current_index > 0:
            self._current_index -= 1
            return self._items[self._current_index]
        elif self._repeat_mode == "all":
            self._current_index = len(self._items) - 1
            return self._items[self._current_index]

        return self.get_current()

    def load_m3u(self, content_or_path: str):
        """Parse M3U playlist file or content string."""
        lines = []
        if os.path.exists(content_or_path):
            with open(content_or_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        else:
            lines = content_or_path.splitlines()

        current_title = ""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#EXTINF:"):
                # Parse title after comma
                parts = line.split(",", 1)
                if len(parts) > 1:
                    current_title = parts[1].strip()
            elif not line.startswith("#"):
                self.add(uri=line, title=current_title)
                current_title = ""
