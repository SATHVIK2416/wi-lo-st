"""SonicSync UDP Binary Transport (Multicast, Subnet Broadcast, Unicast)."""

import logging
import socket
import struct
import threading
from typing import Optional, Callable
from src.core.packet import AudioPacket

logger = logging.getLogger(__name__)

DEFAULT_MULTICAST_GROUP = "239.255.0.1"
DEFAULT_UDP_PORT = 5004


class SonicSyncUDPBroadcaster:
    """Transmits SonicSync 42-byte binary packets across local network via UDP."""

    def __init__(
        self,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
        port: int = DEFAULT_UDP_PORT,
        enable_broadcast: bool = True,
        enable_multicast: bool = True
    ):
        self.multicast_group = multicast_group
        self.port = int(port)
        self.enable_broadcast = enable_broadcast
        self.enable_multicast = enable_multicast

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        # Set multicast TTL to 2 (local subnet)
        ttl = struct.pack('b', 2)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)

        # Enable broadcast
        if self.enable_broadcast:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def send_packet(self, packet: AudioPacket) -> bool:
        """Serialize and transmit audio packet via multicast and/or broadcast."""
        try:
            data = packet.serialize()
            if self.enable_multicast:
                self._sock.sendto(data, (self.multicast_group, self.port))
            if self.enable_broadcast:
                self._sock.sendto(data, ("255.255.255.255", self.port))
            return True
        except Exception as e:
            logger.debug(f"UDP send error: {e}")
            return False

    def send_raw(self, raw_bytes: bytes, target_ip: Optional[str] = None, target_port: Optional[int] = None):
        """Send arbitrary raw UDP datagram (e.g. for RTP)."""
        ip = target_ip or self.multicast_group
        p = target_port or self.port
        try:
            self._sock.sendto(raw_bytes, (ip, p))
        except Exception as e:
            logger.debug(f"Raw UDP send error: {e}")

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


class SonicSyncUDPReceiver:
    """Listens for SonicSync UDP binary packets and delivers deserialized AudioPackets."""

    def __init__(
        self,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
        port: int = DEFAULT_UDP_PORT,
        bind_ip: str = "0.0.0.0"
    ):
        self.multicast_group = multicast_group
        self.port = int(port)
        self.bind_ip = bind_ip

        self._sock: Optional[socket.socket] = None
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[AudioPacket], None]] = None

    def start(self, callback: Callable[[AudioPacket], None]):
        """Start listening loop in background thread."""
        if self._is_running:
            return

        self._callback = callback
        self._is_running = True

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self._sock.bind((self.bind_ip, self.port))
        except Exception as e:
            logger.error(f"Failed to bind UDP socket to port {self.port}: {e}")
            self._is_running = False
            return

        # Join multicast group
        try:
            mreq = struct.pack("4sl", socket.inet_aton(self.multicast_group), socket.INADDR_ANY)
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except Exception as e:
            logger.debug(f"Multicast membership note: {e}")

        def loop():
            self._sock.settimeout(0.5)
            while self._is_running:
                try:
                    data, addr = self._sock.recvfrom(65535)
                    packet = AudioPacket.deserialize(data, verify_crc=True)
                    if self._callback is not None:
                        self._callback(packet)
                except socket.timeout:
                    continue
                except Exception as ex:
                    logger.debug(f"UDP receive error: {ex}")

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._is_running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
