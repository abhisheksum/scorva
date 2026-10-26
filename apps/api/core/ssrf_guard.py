"""
Scorva SSRF Guard & Egress Policy Enforcement.

Implements segmented network security policies:
- Profile A (Public Web Egress): GitHub Archive & API Downloads with IP pinning and redirect re-validation.
- Profile B (Internal Inference Egress): Ollama / Local AI on administrative allowlist with zero redirects.
- Profile C (Default Deny): Blocks all other egress.
"""

import ipaddress
import socket
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse

import httpcore
import httpx


class SSRFViolationError(Exception):
    """Raised when an outbound network request violates SSRF egress policies."""
    pass


# Strict Profile A Hostname Allowlist
GITHUB_ALLOWED_HOSTNAMES: Set[str] = {
    "api.github.com",
    "codeload.github.com",
}

# Strict Profile B Internal AI Host Allowlist
ALLOWED_INTERNAL_AI_HOSTS: Set[str] = {
    "ollama",
    "localhost",
    "127.0.0.1",
}

# Strict Profile B Permitted Internal Ports (Ollama default 11434, plus 443 for internal TLS)
ALLOWED_INTERNAL_AI_PORTS: Set[int] = {
    11434,
    443,
}

# Strictly forbidden ports to prevent internal infrastructure port-scanning
FORBIDDEN_INTERNAL_PORTS: Set[int] = {
    22,     # SSH
    25,     # SMTP
    80,     # Plain HTTP default (prohibits arbitrary unencrypted local services)
    8000,   # Scorva Web API
    5432,   # PostgreSQL
    6379,   # Redis
    9000,   # MinIO API
    9001,   # MinIO Console
    27017,  # MongoDB
    3306,   # MySQL
    2375,   # Docker Daemon
    2376,   # Docker Daemon TLS
}


def is_valid_internal_ai_ip(
    ip: Union[str, ipaddress.IPv4Address, ipaddress.IPv6Address],
    hostname: str,
) -> bool:
    """
    Validates that an IP address is permissible for Profile B internal AI inference.
    Strictly forbids:
    - Cloud metadata (169.254.169.254, 169.254.0.0/16, fe80::/10)
    - Public / globally routable addresses (Profile B is internal only)
    - Multicast, reserved, unspecified, broadcast
    Permits:
    - Loopback (127.0.0.0/8, ::1) for localhost and 127.0.0.1
    - Private network (172.16.0.0/12, 10.0.0.0/8, 192.168.0.0/16) ONLY for 'ollama' docker hostname
    """
    if isinstance(ip, str):
        try:
            ip = ipaddress.ip_address(ip)
        except ValueError as exc:
            raise SSRFViolationError(f"Invalid IP address format: {ip}") from exc

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return is_valid_internal_ai_ip(ip.ipv4_mapped, hostname)

    # Loopback is permitted for localhost, 127.0.0.1, or ollama
    if ip.is_loopback:
        return True

    # Cloud metadata and link-local are strictly forbidden
    if str(ip) == "169.254.169.254" or ip.is_link_local:
        return False

    # Multicast, reserved, unspecified
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False

    # Global public IPs are forbidden for Profile B internal inference
    if ip.is_global:
        return False

    # Private network addresses are permitted ONLY for docker hostname 'ollama'
    if ip.is_private:
        return hostname == "ollama"

    return False


def is_public_unicast_ip(ip: Union[str, ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    """
    Validates that an IP address is a globally routable, public unicast address.
    Strictly rejects:
    - Loopback (127.0.0.0/8, ::1)
    - Private networks (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
    - Link-local (169.254.0.0/16, fe80::/10)
    - Cloud metadata (169.254.169.254)
    - Carrier Grade NAT (100.64.0.0/10)
    - Multicast (224.0.0.0/4, ff00::/8)
    - Reserved / IETF / Current network (240.0.0.0/4, 0.0.0.0/8, 192.0.0.0/24, 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24)
    - IPv4-mapped IPv6 addresses representing non-public IPs (e.g. ::ffff:127.0.0.1)
    """
    if isinstance(ip, str):
        try:
            ip = ipaddress.ip_address(ip)
        except ValueError as exc:
            raise SSRFViolationError(f"Invalid IP address format: {ip}") from exc

    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return is_public_unicast_ip(ip.ipv4_mapped)

    if not ip.is_global:
        return False
    if ip.is_private:
        return False
    if ip.is_loopback:
        return False
    if ip.is_link_local:
        return False
    if ip.is_reserved:
        return False
    if ip.is_multicast:
        return False
    if ip.is_unspecified:
        return False

    # Extra defensive check for cloud metadata IP 169.254.169.254
    if str(ip) == "169.254.169.254":
        return False

    return True


def resolve_and_validate_hostname(
    hostname: str,
    port: int = 443,
    dns_resolver: Optional[Any] = None,
) -> List[str]:
    """
    Synchronously resolves hostname and asserts that EVERY resolved IP is a public unicast IP.
    Returns list of verified public IP string addresses.
    Raises SSRFViolationError on private, loopback, or cloud metadata resolution.
    """
    if not hostname:
        raise SSRFViolationError("Target hostname cannot be empty.")

    # Check if hostname is an explicit IP literal
    try:
        ip_obj = ipaddress.ip_address(hostname)
        if not is_public_unicast_ip(ip_obj):
            raise SSRFViolationError(
                f"SSRF violation: direct IP '{hostname}' is not a public unicast address."
            )
        return [str(ip_obj)]
    except ValueError:
        pass  # Not an IP literal, resolve via DNS

    try:
        if dns_resolver:
            addr_info = dns_resolver(hostname, port)
        else:
            addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFViolationError(f"DNS resolution failed for hostname '{hostname}': {exc}") from exc

    resolved_ips: List[str] = []
    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        if not is_public_unicast_ip(ip_str):
            raise SSRFViolationError(
                f"SSRF violation: hostname '{hostname}' resolved to non-public IP '{ip_str}'."
            )
        if ip_str not in resolved_ips:
            resolved_ips.append(ip_str)

    if not resolved_ips:
        raise SSRFViolationError(f"No IP addresses resolved for hostname '{hostname}'.")

    return resolved_ips


def validate_profile_a_url(
    url_str: str,
    dns_resolver: Optional[Any] = None,
) -> Tuple[str, str, int]:
    """
    Profile A: External Web Egress (GitHub Downloads).
    - URL scheme MUST be 'https'.
    - Hostname MUST be in GITHUB_ALLOWED_HOSTNAMES ('api.github.com', 'codeload.github.com').
    - Synchronous DNS pre-resolution: EVERY resolved IP must be a public unicast IP.
    Returns (hostname, pinned_ip, port).
    """
    try:
        parsed = urlparse(url_str)
    except Exception as exc:
        raise SSRFViolationError(f"Malformed URL '{url_str}': {exc}") from exc

    if parsed.scheme != "https":
        raise SSRFViolationError(
            f"SSRF violation: Profile A scheme must be 'https', got '{parsed.scheme}'."
        )

    hostname = (parsed.hostname or "").lower()
    if hostname not in GITHUB_ALLOWED_HOSTNAMES:
        raise SSRFViolationError(
            f"SSRF violation: Hostname '{hostname}' is not in approved GitHub allowlist: {GITHUB_ALLOWED_HOSTNAMES}."
        )

    port = parsed.port or 443
    if port != 443:
        raise SSRFViolationError(
            f"SSRF violation: Profile A public egress strictly permits port 443 only, got port {port}."
        )
    valid_ips = resolve_and_validate_hostname(hostname, port=port, dns_resolver=dns_resolver)
    pinned_ip = valid_ips[0]

    return hostname, pinned_ip, port


def validate_profile_b_url(
    url_str: str,
    allowed_hosts: Optional[Set[str]] = None,
    allowed_ports: Optional[Set[int]] = None,
    dns_resolver: Optional[Any] = None,
) -> Tuple[str, str, int]:
    """
    Profile B: Internal Inference Egress (Ollama / Local AI).
    - Hostname MUST be in approved internal allowlist ('ollama', 'localhost', '127.0.0.1').
    - Scheme must be 'http' or 'https'.
    - Port MUST be in approved internal AI ports (default: 11434, 443) and NOT in forbidden ports.
    - Synchronous DNS resolution: Every resolved IP must be loopback (for localhost/127.0.0.1)
      or private network (for docker hostname 'ollama'). Cloud metadata and public IPs are strictly blocked.
    Returns (hostname, pinned_ip, port).
    """
    try:
        parsed = urlparse(url_str)
    except Exception as exc:
        raise SSRFViolationError(f"Malformed URL '{url_str}': {exc}") from exc

    if parsed.scheme not in ("http", "https"):
        raise SSRFViolationError(
            f"SSRF violation: Profile B scheme must be 'http' or 'https', got '{parsed.scheme}'."
        )

    if parsed.username or parsed.password:
        raise SSRFViolationError("SSRF violation: User-info components are forbidden in Profile B URLs.")

    hostname = (parsed.hostname or "").lower()
    effective_allowed_hosts = allowed_hosts if allowed_hosts is not None else ALLOWED_INTERNAL_AI_HOSTS
    if hostname not in effective_allowed_hosts:
        raise SSRFViolationError(
            f"SSRF violation: AI inference host '{hostname}' is not in approved internal allowlist: {effective_allowed_hosts}."
        )

    port = parsed.port or (443 if parsed.scheme == "https" else (11434 if hostname == "ollama" else 80))
    if port in FORBIDDEN_INTERNAL_PORTS:
        raise SSRFViolationError(
            f"SSRF violation: Port {port} is strictly forbidden for internal AI egress."
        )

    effective_allowed_ports = allowed_ports if allowed_ports is not None else ALLOWED_INTERNAL_AI_PORTS
    if port not in effective_allowed_ports:
        raise SSRFViolationError(
            f"SSRF violation: Port {port} is not in approved internal AI ports: {effective_allowed_ports}."
        )

    # Synchronous DNS resolution & validation
    if hostname == "127.0.0.1":
        pinned_ip = "127.0.0.1"
    else:
        try:
            if dns_resolver:
                addr_info = dns_resolver(hostname, port)
            else:
                addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise SSRFViolationError(f"DNS resolution failed for internal AI host '{hostname}': {exc}") from exc

        resolved_ips: List[str] = []
        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            if not is_valid_internal_ai_ip(ip_str, hostname):
                raise SSRFViolationError(
                    f"SSRF violation: Internal AI host '{hostname}' resolved to non-permitted IP '{ip_str}'."
                )
            if ip_str not in resolved_ips:
                resolved_ips.append(ip_str)

        if not resolved_ips:
            raise SSRFViolationError(f"No IP addresses resolved for internal AI host '{hostname}'.")
        pinned_ip = resolved_ips[0]

    return hostname, pinned_ip, port


# ==============================================================================
# IP-Pinned HTTPX Transport to Eliminate DNS Rebinding TOCTOU
# ==============================================================================

class PinnedAsyncNetworkBackend(httpcore.AnyIOBackend):
    """
    Custom network backend connecting TCP sockets directly to pre-validated IP addresses.
    Prevents DNS rebinding by eliminating runtime DNS re-resolution.
    """

    def __init__(self, pinned_map: Dict[str, str]):
        super().__init__()
        self._pinned_map = pinned_map

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[Any] = None,
    ) -> httpcore.AsyncNetworkStream:
        connect_host = self._pinned_map.get(host, host)
        return await super().connect_tcp(
            connect_host,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )


class PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """
    HTTPX Async Transport with pinned IP mapping.
    Connects to pinned_ip while presenting the legitimate hostname during TLS SNI validation.
    """

    def __init__(self, pinned_map: Dict[str, str], *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._pool._network_backend = PinnedAsyncNetworkBackend(pinned_map)


class ProfileBAsyncHTTPTransport(PinnedAsyncHTTPTransport):
    """
    HTTPX Async Transport for Profile B Internal AI Egress.
    Enforces IP pinning and guarantees zero redirects:
    intercepts any 3xx response and raises SSRFViolationError immediately.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        if response.is_redirect or 300 <= response.status_code < 400:
            await response.aclose()
            raise SSRFViolationError(
                f"AI_PROVIDER_REDIRECT_DISALLOWED: Profile B internal AI egress strictly forbids HTTP redirects. "
                f"Received status {response.status_code}."
            )
        return response


def create_profile_b_client(
    base_url: str,
    timeout_seconds: float = 120.0,
    allowed_hosts: Optional[Set[str]] = None,
    allowed_ports: Optional[Set[int]] = None,
    dns_resolver: Optional[Any] = None,
    verify_tls: bool = True,
) -> httpx.AsyncClient:
    """
    Factory creating an HTTPX AsyncClient configured with Profile B SSRF protection.
    Validates base_url, pins connection to resolved IP, disables redirects, and intercepts 3xx.
    """
    hostname, pinned_ip, port = validate_profile_b_url(
        base_url,
        allowed_hosts=allowed_hosts,
        allowed_ports=allowed_ports,
        dns_resolver=dns_resolver,
    )
    transport = ProfileBAsyncHTTPTransport(
        pinned_map={hostname: pinned_ip},
        verify=verify_tls,
    )
    return httpx.AsyncClient(
        base_url=base_url,
        transport=transport,
        follow_redirects=False,
        timeout=httpx.Timeout(timeout_seconds),
    )
