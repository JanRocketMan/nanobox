"""mitmproxy addon: default-deny egress policy + per-host credential injection.

Always-on, fail-closed blocks:
  - bare IP-literal hosts (the sandbox has no DNS of its own, so a literal IP
    is a deliberate attempt to bypass the allow list)
  - requests whose resolved server address lands in a blocked range (loopback,
    private, CGNAT, link-local, cloud metadata, multicast, reserved)
  - HTTP Host / CONNECT authority that does not match the client's SNI
  - credential injection over plain HTTP (HTTPS only)

Policy is enforced at CONNECT time (before any upstream connection, so it
works even when DNS is unavailable) and again on the inner request.

Hostname allow list (default-deny) applies ONLY when a policy is configured:
  1. $NBOX_POLICY (JSON {"allow": [...]}, written per nbox session)
  2. ~/.config/nanobox/policy.json
  3. ~/.config/nanobox/config.yaml (proxy.allow section), if PyYAML is importable
When no policy is present, hostnames pass through (fail-open) so existing
agents never break; the operator opts into strict mode by configuring
proxy.allow.

Credentials from credentials.json are injected only over HTTPS and only for
the exact mapped host. Header values always overwrite the client's own, so a
sentinel value can be shipped inside the sandbox.

Nothing secret is logged: audit lines contain hosts and header names only.
"""
import ipaddress
import json
import logging
import os
from fnmatch import fnmatch
from pathlib import Path

from mitmproxy import http

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "nanobox"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
POLICY_FILE = CONFIG_DIR / "policy.json"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

# Ranges a sandbox must never reach: cloud metadata (169.254.169.254),
# private networks, loopback, CGNAT, multicast, and reserved space.
BLOCKED_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def ip_in_blocked_range(ip: object) -> bool:
    return any(ip in net for net in BLOCKED_NETS)


def _allow_from_json(path: Path) -> list[str] | None:
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    allow = data.get("allow")
    if isinstance(allow, list):
        return [str(a).lower() for a in allow]
    return None


def load_policy() -> list[str] | None:
    """Return the allow list, or None when no policy is configured.

    None means fail-open for hostnames: security-critical blocks still apply.
    """
    env = os.environ.get("NBOX_POLICY")
    if env:
        allow = _allow_from_json(Path(env))
        if allow is not None:
            return allow
    allow = _allow_from_json(POLICY_FILE)
    if allow is not None:
        return allow
    try:
        import yaml  # not guaranteed in the mitmproxy environment
    except ImportError:
        return None
    if CONFIG_FILE.is_file():
        try:
            with open(CONFIG_FILE) as f:
                cfg = yaml.safe_load(f) or {}
            allow = (cfg.get("proxy") or {}).get("allow")
        except Exception:
            return None
        if isinstance(allow, list):
            return [str(a).lower() for a in allow]
    return None


def host_allowed(host: str, allow: list[str]) -> bool:
    host = host.strip(".").lower()
    return any(fnmatch(host, pat.lower()) for pat in allow)


def block(flow: http.HTTPFlow, reason: str) -> None:
    logger.warning("blocked %s: %s", flow.request.pretty_host, reason)
    msg = (
        "blocked by nbox proxy policy: %s.\n"
        "If this destination is needed, add it to proxy.allow in %s"
        % (reason, CONFIG_FILE)
    )
    flow.response = http.Response.make(403, msg.encode(), {"Content-Type": "text/plain"})


class SandboxProxy:
    def __init__(self) -> None:
        self.policy = load_policy()
        self.mapping = self._load_mapping()
        if self.policy is not None:
            logger.info("enforcing allow list with %d pattern(s)", len(self.policy))
        else:
            logger.warning("no proxy policy configured - hostnames fail open")
        if self.mapping:
            logger.info("loaded credential mappings for %d host(s)", len(self.mapping))

    @staticmethod
    def _load_mapping() -> dict:
        if not CREDENTIALS_FILE.is_file():
            logger.warning("no credential mapping at %s - running without injection", CREDENTIALS_FILE)
            return {}
        try:
            with open(CREDENTIALS_FILE) as f:
                mapping = json.load(f)
        except (OSError, ValueError) as exc:
            logger.warning("cannot read %s: %s", CREDENTIALS_FILE, exc)
            return {}
        return {str(k).lower(): v for k, v in mapping.items() if isinstance(v, dict)}

    def request(self, flow: http.HTTPFlow) -> None:
        # Strip leading/trailing whitespace from header values - HTTP/2
        # (RFC 9113 s8.2.1) forbids it, and tools sometimes write tokens
        # with trailing spaces (e.g. glab's config.yml).
        for name, value in list(flow.request.headers.items(True)):
            stripped = value.strip()
            if stripped != value:
                flow.request.headers[name] = stripped

        host = flow.request.pretty_host.strip(".").lower()

        # Bare IP literals are always rejected.
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None:
            block(flow, f"bare IP address {host} is not allowed")
            return

        # The resolved server address must be public (DNS-rebinding protection).
        addr = flow.server_conn.address
        if addr:
            try:
                server_ip = ipaddress.ip_address(addr[0].strip("[]"))
            except ValueError:
                server_ip = None
            if server_ip is not None and ip_in_blocked_range(server_ip):
                block(flow, f"server resolved to blocked range {addr[0]}")
                return

        # Host header must match the client's SNI (tunnel consistency).
        sni = flow.client_conn.sni
        if sni and sni.strip(".").lower() != host:
            block(flow, f"Host {host} does not match SNI {sni}")
            return

        if not self._allowed(host):
            block(flow, f"{host} is not on the proxy allow list")
            return

        logger.info("allowed %s", host)

        # Credential injection: HTTPS only, exact host match.
        if flow.request.scheme == "https" and host in self.mapping:
            headers = self.mapping[host]
            for name, value in headers.items():
                flow.request.headers[name] = str(value).strip()
            logger.info("injected %d header(s) for %s", len(headers), host)

    def http_connect(self, flow: http.HTTPFlow) -> None:
        """Enforce policy at CONNECT time. Blocks apply before any upstream
        connection is attempted, so they work even when DNS is unavailable.
        Flow.response short-circuits the tunnel (same pattern as proxyauth)."""
        host = self._connect_host(flow)
        if host is None:
            block(flow, "malformed CONNECT authority")
            return

        # Bare IP literals are always rejected.
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None:
            block(flow, f"bare IP address {host} is not allowed")
            return

        # SNI must match the CONNECT authority (tunnel consistency).
        sni = flow.client_conn.sni
        if sni and sni.strip(".").lower() != host:
            block(flow, f"CONNECT {host} does not match SNI {sni}")
            return

        if not self._allowed(host):
            block(flow, f"{host} is not on the proxy allow list")
            return

        logger.info("connect allowed %s", host)

    @staticmethod
    def _connect_host(flow: http.HTTPFlow) -> str | None:
        try:
            host = flow.request.pretty_host
        except Exception:
            return None
        if not host:
            return None
        return host.strip("[]").strip(".").lower()

    def _allowed(self, host: str) -> bool:
        if self.policy is None:
            return True
        return host_allowed(host, self.policy)

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        """Forward server-sent events without buffering the response body."""
        if flow.response is None:
            return
        content_type = flow.response.headers.get("content-type", "").lower()
        if content_type.startswith("text/event-stream"):
            flow.response.stream = True


addons = [SandboxProxy()]