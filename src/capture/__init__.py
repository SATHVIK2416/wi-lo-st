"""SonicSync Audio Capture Sources."""

from src.capture.base_source import AudioSource
from src.capture.wasapi_loopback import WASAPILoopbackSource
from src.capture.coreaudio_loopback import CoreAudioLoopbackSource
from src.capture.pulse_monitor import PulseAudioMonitorSource
from src.capture.pipewire_monitor import PipeWireMonitorSource
from src.capture.test_generator import TestGeneratorSource, TestSignalType

__all__ = [
    "AudioSource",
    "WASAPILoopbackSource",
    "CoreAudioLoopbackSource",
    "PulseAudioMonitorSource",
    "PipeWireMonitorSource",
    "TestGeneratorSource",
    "TestSignalType",
]
