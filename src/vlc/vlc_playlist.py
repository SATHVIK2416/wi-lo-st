"""Playlist management for VLC media engine."""

import os
import random
import threading
from dataclasses import dataclass
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
        self._shuffle_order: List[int] = []
        self._shuffle_pos: int = 0
        self._lock = threading.RLock()

    @property
    def current_index(self) -> int:
        with self._lock:
            return self._current_index

    @property
    def repeat_mode(self) -> str:
        with self._lock:
            return self._repeat_mode

    @repeat_mode.setter
    def repeat_mode(self, mode: str):
        if mode in ("off", "all", "one"):
            with self._lock:
                self._repeat_mode = mode

    @property
    def shuffle(self) -> bool:
        with self._lock:
            return self._shuffle

    @shuffle.setter
    def shuffle(self, enabled: bool):
        with self._lock:
            enabled = bool(enabled)
            if enabled == self._shuffle:
                return
            self._shuffle = enabled
            if enabled and len(self._items) > 1:
                self._unshuffled_indices = list(range(len(self._items)))
                rest = [i for i in self._unshuffled_indices if i != self._current_index]
                random.shuffle(rest)
                if 0 <= self._current_index < len(self._items):
                    self._shuffle_order = [self._current_index] + rest
                else:
                    self._shuffle_order = rest
                self._shuffle_pos = 0
            else:
                # Restore original playback order; the item list itself is
                # never reordered, so resetting the play order is sufficient.
                self._shuffle_order = []
                self._shuffle_pos = 0

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    def get_items(self) -> List[dict]:
        with self._lock:
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
        with self._lock:
            item = PlaylistItem(uri=uri, title=title)
            self._items.append(item)
            new_index = len(self._items) - 1
            if self._current_index == -1:
                self._current_index = 0
            if self._shuffle and self._shuffle_order:
                insert_at = random.randint(self._shuffle_pos + 1, len(self._shuffle_order))
                self._shuffle_order.insert(insert_at, new_index)
            return item

    def remove(self, index: int) -> bool:
        with self._lock:
            if not (0 <= index < len(self._items)):
                return False
            del self._items[index]
            if not self._items:
                self._current_index = -1
            else:
                if index < self._current_index:
                    self._current_index -= 1
                self._current_index = min(max(self._current_index, 0), len(self._items) - 1)
            if self._shuffle_order:
                self._shuffle_order = [i - 1 if i > index else i for i in self._shuffle_order if i != index]
                self._shuffle_pos = min(max(self._shuffle_pos, 0), max(0, len(self._shuffle_order) - 1))
            return True

    def clear(self):
        with self._lock:
            self._items.clear()
            self._current_index = -1
            self._shuffle_order = []
            self._shuffle_pos = 0
            self._unshuffled_indices = []

    def get_current(self) -> Optional[PlaylistItem]:
        with self._lock:
            if 0 <= self._current_index < len(self._items):
                return self._items[self._current_index]
            return None

    def set_current_index(self, index: int) -> Optional[PlaylistItem]:
        with self._lock:
            if 0 <= index < len(self._items):
                self._current_index = index
                if self._shuffle and index in self._shuffle_order:
                    self._shuffle_pos = self._shuffle_order.index(index)
                return self._items[index]
            return None

    def next(self) -> Optional[PlaylistItem]:
        with self._lock:
            if not self._items:
                return None

            if self._repeat_mode == "one":
                return self.get_current()

            if self._shuffle and len(self._shuffle_order) > 1:
                if self._shuffle_pos + 1 < len(self._shuffle_order):
                    self._shuffle_pos += 1
                elif self._repeat_mode == "all":
                    self._shuffle_pos = 0
                else:
                    return None
                self._current_index = self._shuffle_order[self._shuffle_pos]
                return self._items[self._current_index]

            if self._current_index + 1 < len(self._items):
                self._current_index += 1
                return self._items[self._current_index]
            elif self._repeat_mode == "all":
                self._current_index = 0
                return self._items[0]

            return None

    def previous(self) -> Optional[PlaylistItem]:
        with self._lock:
            if not self._items:
                return None

            if self._repeat_mode == "one":
                return self.get_current()

            if self._shuffle and len(self._shuffle_order) > 1:
                if self._shuffle_pos > 0:
                    self._shuffle_pos -= 1
                elif self._repeat_mode == "all":
                    self._shuffle_pos = len(self._shuffle_order) - 1
                else:
                    return self.get_current()
                self._current_index = self._shuffle_order[self._shuffle_pos]
                return self._items[self._current_index]

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
