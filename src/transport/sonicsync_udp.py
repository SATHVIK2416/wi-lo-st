"""SonicSync UDP Binary Transport (Multicast, Subnet Broadcast, Unicast)."""

import logging
import socket
import struct
import threading
from collections import deque
from typing import Optional, Callable, Set
from src.core.packet import AudioPacket

logger = logging.getLogger(__name__)

DEFAULT_MULTICAST_GROUP = "239.255.0.1"
DEFAULT_UDP_PORT = 5004

_DEDUP_WINDOW = 1024


class SonicSyncUDPBroadcaster:
    """Transmits SonicSync 42-byte binary packets across local network via UDP.

    By default only multicast is used. Subnet broadcast duplicates every
    datagram on the wire and caused every receiver to play each packet twice;
    enable it explicitly only for networks where multicast is unavailable.
    """

    def __init__(
        self,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
        port: int = DEFAULT_UDP_PORT,
        enable_broadcast: bool = False,
        enable_multicast: bool = True,
        interface_ip: Optional[str] = None
    ):
        self.multicast_group = multicast_group
        self.port = int(port)
        self.enable_broadcast = enable_broadcast
        self.enable_multicast = enable_multicast

        self._send_failures = 0

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

        # Multicast TTL 2 keeps the stream on the local subnet
        ttl = struct.pack('b', 2)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        # Explicitly allow loopback delivery so same-host receivers work
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        # Pin multicast egress to the LAN interface on multi-homed hosts
        if interface_ip:
            try:
                self._sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(interface_ip)
                )
            except OSError as e:
                logger.warning(f"Could not pin multicast interface to {interface_ip}: {e}")

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
            self._send_failures = 0
            return True
        except OSError as e:
            self._send_failures += 1
            if self._send_failures == 1 or self._send_failures % 500 == 0:
                logger.warning(f"UDP send error (x{self._send_failures}): {e}")
            return False

    def send_raw(self, raw_bytes: bytes, target_ip: Optional[str] = None, target_port: Optional[int] = None):
        """Send arbitrary raw UDP datagram (e.g. for RTP)."""
        ip = target_ip or self.multicast_group
        p = target_port or self.port
        try:
            self._sock.sendto(raw_bytes, (ip, p))
        except OSError as e:
            logger.debug(f"Raw UDP send error to {ip}:{p}: {e}")

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


class SonicSyncUDPReceiver:
    """Listens for SonicSync UDP binary packets and delivers deserialized AudioPackets.

    Duplicate datagrams (e.g. from dual multicast/broadcast senders or IGMP
    refresh glitches) are suppressed via a sequence-number window.
    """

    def __init__(
        self,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
        port: int = DEFAULT_UDP_PORT,
        bind_ip: str = "0.0.0.0",
        dedup_enabled: bool = True
    ):
        self.multicast_group = multicast_group
        self.port = int(port)
        self.bind_ip = bind_ip
        self.dedup_enabled = dedup_enabled

        self._sock: Optional[socket.socket] = None
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[AudioPacket], None]] = None
        self._lifecycle_lock = threading.Lock()

        self.last_sender: Optional[tuple] = None
        self.packets_received = 0
        self.crc_errors = 0
        self.duplicates_dropped = 0

        self._recent_seqs: deque = deque(maxlen=_DEDUP_WINDOW)
        self._seq_set: Set[int] = set()

    def start(self, callback: Callable[[AudioPacket], None]):
        """Start listening loop in background thread."""
        with self._lifecycle_lock:
            if self._is_running:
                return

            self._callback = callback
            self._is_running = True

            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
                self._sock.bind((self.bind_ip, self.port))
            except OSError as e:
                logger.error(f"Failed to bind UDP socket to port {self.port}: {e}")
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
                self._is_running = False
                return

            # Join multicast group
            try:
                mreq = struct.pack("4sl", socket.inet_aton(self.multicast_group), socket.INADDR_ANY)
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError as e:
                logger.warning(f"Multicast join failed (unicast/broadcast still received): {e}")

            self._thread = threading.Thread(target=self._loop, daemon=True, name="sonicsync-udp-rx")
            self._thread.start()

    def _loop(self):
        sock = self._sock
        if sock is None:
            return
        sock.settimeout(0.5)
        while self._is_running and sock is not None:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                packet = AudioPacket.deserialize(data, verify_crc=True)
            except ValueError as ex:
                self.crc_errors += 1
                if self.crc_errors == 1 or self.crc_errors % 500 == 0:
                    logger.warning(f"Dropping malformed UDP packet (x{self.crc_errors}): {ex}")
                continue

            if self.dedup_enabled and self._is_duplicate(packet.sequence_number):
                self.duplicates_dropped += 1
                continue

            self.last_sender = addr
            self.packets_received += 1
            if self._callback is not None:
                try:
                    self._callback(packet)
                except Exception as ex:
                    logger.error(f"Receiver callback error: {ex}", exc_info=True)

    def _is_duplicate(self, seq: int) -> bool:
        if seq in self._seq_set:
            return True
        if len(self._recent_seqs) == self._recent_seqs.maxlen:
            self._seq_set.discard(self._recent_seqs[0])
        self._recent_seqs.append(seq)
        self._seq_set.add(seq)
        return False

    def stop(self):
        with self._lifecycle_lock:
            self._is_running = False
            sock = self._sock
            self._sock = None
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            thread = self._thread
            self._thread = None

        if thread is not None:
            thread.join(timeout=1.0)
