"""Dynamic QR code generation and local LAN IP discovery for zero-install mobile listening."""

import base64
import io
import socket
from typing import Tuple


def get_local_lan_ip() -> str:
    """Discover primary LAN IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually transmit data; connects UDP socket to determine outgoing interface IP
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


def generate_listener_qr_code(
    host_ip: str,
    port: int = 8080,
    token: str = "",
    use_https: bool = False
) -> Tuple[bytes, str, str]:
    """Generate high-resolution PNG QR code pointing to web listener URL.

    Returns:
        Tuple[bytes, str, str]: (raw_png_bytes, base64_data_uri, full_target_url)
    """
    protocol = "https" if use_https else "http"
    target_url = f"{protocol}://{host_ip}:{port}/listen"
    if token:
        target_url += f"?token={token}"

    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(target_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#00E5FF", back_color="#0D1117")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()
        b64_str = base64.b64encode(raw_bytes).decode('ascii')
        data_uri = f"data:image/png;base64,{b64_str}"
        return raw_bytes, data_uri, target_url

    except Exception:
        # Fallback dummy 1x1 png if qrcode library fails
        dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        b64_str = base64.b64encode(dummy_png).decode('ascii')
        return dummy_png, f"data:image/png;base64,{b64_str}", target_url


def print_terminal_qr(target_url: str):
    """Print ASCII QR code directly into terminal for instant scanning from console."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(target_url)
        qr.make(fit=True)
        print("\n" + "=" * 46)
        print("  SCAN WITH SMARTPHONE CAMERA TO LISTEN:")
        print("=" * 46)
        qr.print_ascii(invert=True)
        print("=" * 46 + "\n")
    except Exception:
        pass

