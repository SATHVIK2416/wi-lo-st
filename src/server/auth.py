"""Session tokens and access control for LAN streaming."""

import secrets
import time
from typing import Dict, Optional


class SessionManager:
    """Manages ephemeral access tokens and optional PIN protection."""

    def __init__(self, pin_required: bool = False, default_pin: str = "1234"):
        self.pin_required = pin_required
        self.default_pin = default_pin
        self._tokens: Dict[str, float] = {}  # token -> expiration timestamp
        self._default_ttl_sec = 86400.0      # 24 hours

    def generate_token(self, ttl_sec: Optional[float] = None) -> str:
        """Create a new session token."""
        token = secrets.token_urlsafe(16)
        ttl = ttl_sec or self._default_ttl_sec
        self._tokens[token] = time.time() + ttl
        return token

    def validate_token(self, token: Optional[str]) -> bool:
        """Validate whether a token is active."""
        if not self.pin_required and not self._tokens:
            # Open mode
            return True
        if not token or token not in self._tokens:
            return False
        if time.time() > self._tokens[token]:
            del self._tokens[token]
            return False
        return True

    def verify_pin_and_issue_token(self, input_pin: str) -> Optional[str]:
        """Verify PIN and issue a session token if valid."""
        if not self.pin_required or input_pin == self.default_pin:
            return self.generate_token()
        return None
