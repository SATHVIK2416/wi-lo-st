"""Tests for VLCSource and VLCPlaylist."""

import pytest
from src.core.audio_format import AudioFormat
from src.vlc.vlc_playlist import VLCPlaylist
from src.vlc.vlc_source import VLCSource


def test_vlc_playlist_queue_and_navigation():
    pl = VLCPlaylist()
    pl.add("track1.flac", "Track 1")
    pl.add("track2.flac", "Track 2")
    pl.add("track3.flac", "Track 3")

    assert pl.count() == 3
    assert pl.get_current().title == "Track 1"

    nxt = pl.next()
    assert nxt.title == "Track 2"

    prev = pl.previous()
    assert prev.title == "Track 1"


def test_vlc_playlist_repeat_and_shuffle():
    pl = VLCPlaylist()
    pl.add("track1.flac", "Track 1")
    pl.add("track2.flac", "Track 2")

    pl.repeat_mode = "all"
    pl.set_current_index(1)
    # Next should loop back to 0
    nxt = pl.next()
    assert nxt.title == "Track 1"


def test_vlc_source_status():
    fmt = AudioFormat(sample_rate=48000, channels=2)
    src = VLCSource(fmt)
    src.load_media("test_audio.flac", "Test FLAC")

    status = src.get_status()
    assert "state" in status
    assert "playlist" in status
    assert status["playlist_count"] == 1
