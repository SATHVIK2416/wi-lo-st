"""SonicSync CLI Entry Point.

Lossless, Ultra-Low-Latency Multi-Room Wireless Audio Broadcasting.
"""

import argparse
import asyncio
import logging
import sys
import webbrowser

from src.server.web_server import SonicSyncServer
from src.clients.native_receiver import NativeReceiverClient
from src.clients.vlc_sync_sidecar import VLCSyncSidecar
from src.server.qr import get_local_lan_ip


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")


def main():
    parser = argparse.ArgumentParser(description="SonicSync - VLC-First Lossless Multi-Room Audio Platform")
    parser.add_argument("--mode", choices=["host", "receiver", "sidecar"], default="host", help="Execution mode (default: host)")
    parser.add_argument("--source", choices=["vlc", "loopback", "test"], default="test", help="Initial audio source (default: test)")
    parser.add_argument("--host", default="0.0.0.0", help="Host bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Web dashboard HTTP/WS port (default: 8080)")
    parser.add_argument("--rate", type=int, default=48000, help="Sample rate in Hz (default: 48000)")
    parser.add_argument("--channels", type=int, default=2, help="Audio channels (default: 2)")
    parser.add_argument("--target-delay", type=float, default=100.0, help="Target presentation delay in ms (default: 100.0)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser on launch")
    parser.add_argument("--pin", default=None, help="Require this PIN for control APIs and listening (QR embeds a token)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    setup_logging(args.debug)

    logger = logging.getLogger("sonicsync")
    logger.info("=" * 60)
    logger.info(" SonicSync -- Lossless Multi-Room Wireless Audio")
    logger.info(f" Mode: {args.mode.upper()} | Sample Rate: {args.rate} Hz | Target Delay: {args.target_delay} ms")
    logger.info("=" * 60)

    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    if args.mode == "host":
        server = SonicSyncServer(
            host=args.host,
            port=args.port,
            sample_rate=args.rate,
            channels=args.channels,
            target_delay_ms=args.target_delay,
            default_source=args.source,
            pin=args.pin
        )

        lan_ip = get_local_lan_ip()
        dash_url = f"http://localhost:{args.port}"
        lan_url = f"http://{lan_ip}:{args.port}"
        token_suffix = f"?token={server.bootstrap_token}" if server.bootstrap_token else ""
        listen_url = f"{lan_url}/listen{token_suffix}"

        print("\n" + "=" * 60)
        print("   SonicSync -- Lossless Multi-Room Audio Host")
        print("=" * 60)
        print(f"  * Local Dashboard : {dash_url}")
        print(f"  * Mobile Player   : {listen_url}")
        print(f"  * VLC Stream (M3U): {lan_url}/api/stream.m3u")
        print("=" * 60)
        print("  [1] Scan the QR code below on your phone to listen.")
        print("  [2] Tap 'Tap to Listen' to hear synchronized lossless audio!")
        print("=" * 60)

        # Print terminal QR code
        try:
            from src.server.qr import print_terminal_qr
            print_terminal_qr(listen_url)
        except Exception:
            pass

        if not args.no_browser:
            try:
                webbrowser.open(dash_url)
            except Exception:
                pass

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(server.start())
            loop.run_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down SonicSync host...")
            loop.run_until_complete(server.stop())
        finally:
            loop.close()

    elif args.mode == "receiver":
        import time as _time
        receiver = NativeReceiverClient(
            target_delay_ms=args.target_delay,
            sample_rate=args.rate,
            channels=args.channels
        )
        receiver.start()
        print("\n[+] Native Receiver listening for UDP broadcast... Press Ctrl+C to stop.\n")
        try:
            while True:
                _time.sleep(1.0)
        except KeyboardInterrupt:
            status = receiver.get_status()
            logger.info(
                "Receiver stats: received={packets_received} lost={packets_lost} "
                "dupes={duplicates_dropped} offset={clock_offset_ms:.2f}ms locked={ntp_locked}".format(**status)
            )
            receiver.stop()

    elif args.mode == "sidecar":
        sidecar = VLCSyncSidecar(
            host_ip=args.host if args.host != "0.0.0.0" else "127.0.0.1",
            host_port=args.port
        )
        sidecar.launch_vlc()
        sidecar.connect_rc()
        print("\n[+] VLC Sync Sidecar running... Press Ctrl+C to stop.\n")
        try:
            asyncio.run(sidecar.run_sync_loop())
        except KeyboardInterrupt:
            sidecar.stop()


if __name__ == "__main__":
    main()
