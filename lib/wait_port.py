#!/usr/bin/env python3
"""Wait until a TCP port on 127.0.0.1 accepts connections.

Exits 0 as soon as a connection succeeds, or 1 after the timeout.
Used by nbox to verify the proxy finished starting before entering the sandbox.
"""
import socket
import sys
import time

TIMEOUT_SECONDS = 10


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: wait_port.py <port>", file=sys.stderr)
        return 1

    port = int(sys.argv[1])
    deadline = time.time() + TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return 0
        except OSError:
            time.sleep(0.2)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())