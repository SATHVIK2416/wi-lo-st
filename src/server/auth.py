"""Session tokens and access control for LAN streaming.

Security model (ARCHITECTURE §14):
- Open by default for frictionless LAN use.
- When a PIN is configured, control APIs and the WebSocket require a session
  token; the QR code embeds a bootstrap token so scanning just works, and
  manual visitors can exchange the PIN for a token via POST /api/auth.
"""

import hmac
import logging
import secrets
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages ephemeral access tokens and optional PIN protection."""

    MAX_PIN_ATTEMPTS = 5
    PIN_LOCKOUT_SEC = 60.0

    def __init__(self, token_ttl_sec: float = 86400.0):
        self._pin: Optional[str] = None
        self._tokens: Dict[str, float] = {}  # token -> expiration (monotonic)
        self._token_ttl_sec = float(token_ttl_sec)
        self._lock = threading.Lock()
        self._pin_failures: list = []

    @property
    def pin_enabled(self) -> bool:
        return self._pin is not None

    def configure_pin(self, pin: Optional[str]):
        """Enable PIN protection with the given PIN, or disable with None."""
        with self._lock:
            self._pin = str(pin) if pin else None

    def generate_token(self, ttl_sec: Optional[float] = None) -> str:
        """Create a new session token."""
        token = secrets.token_urlsafe(16)
        ttl = ttl_sec or self._token_ttl_sec
        with self._lock:
            self._tokens[token] = time.monotonic() + ttl
        return token

    def validate_token(self, token: Optional[str]) -> bool:
        """Validate whether a token is active. Open mode always returns True."""
        if not self.pin_enabled:
            return True
        if not token:
            return False
        now = time.monotonic()
        with self._lock:
            expires = self._tokens.get(token)
            if expires is None:
                return False
            if now > expires:
                del self._tokens[token]
                return False
            return True

    def verify_pin_and_issue_token(self, input_pin: str) -> Optional[str]:
        """Verify PIN (timing-safe) and issue a session token if valid.

        Repeated failures trigger a temporary lockout to slow brute forcing.
        """
        if not self.pin_enabled:
            return self.generate_token()

        now = time.monotonic()
        with self._lock:
            self._pin_failures = [t for t in self._pin_failures if now - t < self.PIN_LOCKOUT_SEC]
            if len(self._pin_failures) >= self.MAX_PIN_ATTEMPTS:
                logger.warning("PIN attempt lockout active")
                return None

        # hmac.compare_digest leaks no timing information about the PIN
        matches = hmac.compare_digest(str(input_pin or ""), self._pin or "")
        if not matches:
            with self._lock:
                self._pin_failures.append(now)
            return None

        with self._lock:
            self._pin_failures.clear()
        return self.generate_token()

    def extract_token(self, request) -> Optional[str]:
        """Pull the session token from query string, header, or bearer auth."""
        token = request.query.get("token")
        if token:
            return token
        token = request.headers.get("X-Session-Token")
        if token:
            return token
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return None
