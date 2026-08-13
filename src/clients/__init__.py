"""SonicSync Client Applications."""

from src.clients.native_receiver import NativeReceiverClient
from src.clients.vlc_sync_sidecar import VLCSyncSidecar

__all__ = [
    "NativeReceiverClient",
    "VLCSyncSidecar",
]
