"""
Comprehensive tests for Scorva SSRF Guard & Segmented Egress Policies.
"""

import ipaddress
import socket
import pytest

from apps.api.core.ssrf_guard import (
    ALLOWED_INTERNAL_AI_HOSTS,
    ALLOWED_INTERNAL_AI_PORTS,
    FORBIDDEN_INTERNAL_PORTS,
    GITHUB_ALLOWED_HOSTNAMES,
    ProfileBAsyncHTTPTransport,
    SSRFViolationError,
    create_profile_b_client,
    is_public_unicast_ip,
    resolve_and_validate_hostname,
    validate_profile_a_url,
    validate_profile_b_url,
)


def test_is_public_unicast_ip_matrix():
    """Validates public vs non-public IP classification across standard and adversarial ranges."""
    # 1. Public Unicast IPs (MUST PASS)
    assert is_public_unicast_ip("140.82.121.4") is True      # GitHub
    assert is_public_unicast_ip("8.8.8.8") is True           # Google DNS
    assert is_public_unicast_ip("1.1.1.1") is True           # Cloudflare DNS
    assert is_public_unicast_ip("20.207.73.85") is True      # Microsoft Azure public
    assert is_public_unicast_ip("2606:4700:4700::1111") is True  # Cloudflare IPv6

    # 2. RFC 1918 Private IPv4 Ranges (MUST BE REJECTED)
    assert is_public_unicast_ip("10.0.0.1") is False
    assert is_public_unicast_ip("10.254.254.254") is False
    assert is_public_unicast_ip("172.16.0.1") is False
    assert is_public_unicast_ip("172.31.255.255") is False
    assert is_public_unicast_ip("192.168.0.1") is False
    assert is_public_unicast_ip("192.168.100.254") is False

    # 3. Loopback Addresses (MUST BE REJECTED)
    assert is_public_unicast_ip("127.0.0.1") is False
    assert is_public_unicast_ip("127.0.0.2") is False
    assert is_public_unicast_ip("127.255.255.255") is False
    assert is_public_unicast_ip("::1") is False

    # 4. Link-Local & Cloud Metadata (MUST BE REJECTED)
    assert is_public_unicast_ip("169.254.169.254") is False  # AWS/GCP/Azure Metadata
    assert is_public_unicast_ip("169.254.1.1") is False
    assert is_public_unicast_ip("fe80::1") is False          # IPv6 link-local

    # 5. Carrier-Grade NAT (RFC 6598) (MUST BE REJECTED)
    assert is_public_unicast_ip("100.64.0.1") is False
    assert is_public_unicast_ip("100.127.255.255") is False

    # 6. Current Network / Broadcast / Multicast / Reserved (MUST BE REJECTED)
    assert is_public_unicast_ip("0.0.0.0") is False
    assert is_public_unicast_ip("224.0.0.1") is False        # Multicast
    assert is_public_unicast_ip("240.0.0.1") is False        # Reserved
    assert is_public_unicast_ip("255.255.255.255") is False  # Broadcast

    # 7. IPv4-Mapped IPv6 Addresses (MUST BE REJECTED)
    assert is_public_unicast_ip("::ffff:127.0.0.1") is False
    assert is_public_unicast_ip("::ffff:169.254.169.254") is False
    assert is_public_unicast_ip("::ffff:10.0.0.1") is False
    assert is_public_unicast_ip("::ffff:192.168.1.1") is False

    # 8. IPv4-Mapped IPv6 Public Address (MUST PASS)
    assert is_public_unicast_ip("::ffff:140.82.121.4") is True


def test_resolve_and_validate_hostname_dns_mocking():
    """Tests DNS pre-resolution assertions with mocked socket responses."""
    # Mock resolver returning public IPs
    def mock_public_resolver(hostname, port):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.121.4", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.121.5", port)),
        ]

    ips = resolve_and_validate_hostname("api.github.com", dns_resolver=mock_public_resolver)
    assert "140.82.121.4" in ips
    assert "140.82.121.5" in ips

    # Mock resolver returning a private IP (SSRF attempt)
    def mock_private_resolver(hostname, port):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port)),
        ]

    with pytest.raises(SSRFViolationError) as exc_private:
        resolve_and_validate_hostname("api.github.com", dns_resolver=mock_private_resolver)
    assert "non-public IP '10.0.0.5'" in str(exc_private.value)

    # Mock resolver returning mixed IPs (one public, one private) -> MUST FAIL
    def mock_mixed_resolver(hostname, port):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.121.4", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port)),
        ]

    with pytest.raises(SSRFViolationError) as exc_mixed:
        resolve_and_validate_hostname("api.github.com", dns_resolver=mock_mixed_resolver)
    assert "non-public IP '169.254.169.254'" in str(exc_mixed.value)


def test_validate_profile_a_url_allowlist_and_scheme():
    """Profile A requires https scheme and hostname in GITHUB_ALLOWED_HOSTNAMES."""
    def mock_dns(h, p):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("140.82.121.4", p))]

    # Valid URLs
    h1, ip1, p1 = validate_profile_a_url("https://api.github.com/repos/org/repo", dns_resolver=mock_dns)
    assert h1 == "api.github.com"
    assert ip1 == "140.82.121.4"
    assert p1 == 443

    h2, ip2, p2 = validate_profile_a_url("https://codeload.github.com/org/repo/tar.gz/main", dns_resolver=mock_dns)
    assert h2 == "codeload.github.com"
    assert ip2 == "140.82.121.4"

    # Rejects http (unencrypted)
    with pytest.raises(SSRFViolationError) as exc_scheme:
        validate_profile_a_url("http://api.github.com/repos/org/repo")
    assert "must be 'https'" in str(exc_scheme.value)

    # Rejects non-allowlisted domains
    for evil_url in [
        "https://evil.com/archive.tar.gz",
        "https://github.com.evil.com/tar.gz",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost:443/api",
        "https://google.com/",
    ]:
        with pytest.raises(SSRFViolationError) as exc_domain:
            validate_profile_a_url(evil_url)
        assert "not in approved GitHub allowlist" in str(exc_domain.value)

    # Rejects non-standard ports (SEC-M3-10)
    for bad_port_url in [
        "https://api.github.com:8443/repos/org/repo",
        "https://api.github.com:80/repos/org/repo",
        "https://codeload.github.com:22/org/repo",
    ]:
        with pytest.raises(SSRFViolationError) as exc_port:
            validate_profile_a_url(bad_port_url, dns_resolver=mock_dns)
        assert "permits port 443 only" in str(exc_port.value)


def test_validate_profile_b_url_internal_ai_hosts():
    """Profile B validates administrator-configured Ollama/internal AI endpoints with IP and port enforcement."""
    def mock_internal_dns(host, port):
        if host == "ollama":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.18.0.2", port))]
        if host == "localhost":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
        raise socket.gaierror(-2, "Name or service not known")

    # Valid internal AI hosts
    h1, ip1, p1 = validate_profile_b_url("http://ollama:11434", dns_resolver=mock_internal_dns)
    assert h1 == "ollama"
    assert ip1 == "172.18.0.2"
    assert p1 == 11434

    h2, ip2, p2 = validate_profile_b_url("http://localhost:11434/api/chat", dns_resolver=mock_internal_dns)
    assert h2 == "localhost"
    assert ip2 == "127.0.0.1"
    assert p2 == 11434

    h3, ip3, p3 = validate_profile_b_url("http://127.0.0.1:11434")
    assert h3 == "127.0.0.1"
    assert ip3 == "127.0.0.1"
    assert p3 == 11434

    # Rejects unauthorized external or private hosts
    for forbidden_url in [
        "http://attacker.com:11434",
        "http://192.168.1.50:11434",
        "https://remote-llm.corp.internal:11434",
        "ftp://ollama:11434",
        "http://user:pass@localhost:11434",
    ]:
        with pytest.raises(SSRFViolationError):
            validate_profile_b_url(forbidden_url, dns_resolver=mock_internal_dns)

    # Rejects forbidden internal infrastructure ports (Postgres, Redis, SSH, API)
    for forbidden_port_url in [
        "http://127.0.0.1:5432",   # PostgreSQL
        "http://127.0.0.1:6379",   # Redis
        "http://localhost:22",      # SSH
        "http://localhost:8000",    # Scorva Web API
        "http://127.0.0.1:9000",   # MinIO
        "http://localhost:80",      # Port 80
    ]:
        with pytest.raises(SSRFViolationError) as exc_port:
            validate_profile_b_url(forbidden_port_url, dns_resolver=mock_internal_dns)
        assert "forbidden" in str(exc_port.value) or "not in approved" in str(exc_port.value)

    # Rejects resolution to cloud metadata even if hostname was 'ollama'
    def mock_metadata_dns(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    with pytest.raises(SSRFViolationError) as exc_meta:
        validate_profile_b_url("http://ollama:11434", dns_resolver=mock_metadata_dns)
    assert "non-permitted IP '169.254.169.254'" in str(exc_meta.value)

    # Rejects resolution to public IP for internal Profile B
    def mock_public_dns(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]

    with pytest.raises(SSRFViolationError) as exc_pub:
        validate_profile_b_url("http://ollama:11434", dns_resolver=mock_public_dns)
    assert "non-permitted IP '8.8.8.8'" in str(exc_pub.value)


@pytest.mark.asyncio
async def test_profile_b_transport_zero_redirect_live():
    """
    Live TCP test proving ProfileBAsyncHTTPTransport rejects HTTP redirects
    at the transport level without making an outbound hop.
    """
    import asyncio

    async def handle_client(reader, writer):
        req = await reader.read(1024)
        # Respond with 302 Redirect to cloud metadata
        redirect_resp = (
            b"HTTP/1.1 302 Found\r\n"
            b"Location: http://169.254.169.254/latest/meta-data/\r\n"
            b"Content-Length: 0\r\n"
            b"Connection: close\r\n\r\n"
        )
        writer.write(redirect_resp)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    try:
        base_url = f"http://127.0.0.1:{server_port}"
        client = create_profile_b_client(
            base_url=base_url,
            allowed_ports={server_port},
        )
        async with client:
            with pytest.raises(SSRFViolationError) as exc_info:
                await client.post("/api/chat", json={"test": True})
            assert "Profile B internal AI egress strictly forbids HTTP redirects" in str(exc_info.value)
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_profile_b_transport_live_success():
    """
    Live TCP test proving ProfileBAsyncHTTPTransport successfully communicates
    with approved internal endpoints over pinned loopback sockets.
    """
    import asyncio

    async def handle_client(reader, writer):
        req = await reader.read(2048)
        resp = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 15\r\n"
            b"Connection: close\r\n\r\n"
            b'{"status":"ok"}'
        )
        writer.write(resp)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    try:
        base_url = f"http://127.0.0.1:{server_port}"
        client = create_profile_b_client(
            base_url=base_url,
            allowed_ports={server_port},
        )
        async with client:
            resp = await client.post("/api/chat", json={"prompt": "hi"})
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
    finally:
        server.close()
        await server.wait_closed()
