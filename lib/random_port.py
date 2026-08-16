#!/usr/bin/env python3
"""Print a free ephemeral TCP port on 127.0.0.1 to stdout.

Used by nbox to pick a per-session proxy port. Binding to port 0 lets the
kernel assign a free port; we print it and close the socket. The race window
between this and the actual proxy bind is negligible on a local loopback.
"""
import socket


def main() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        print(s.getsockname()[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())