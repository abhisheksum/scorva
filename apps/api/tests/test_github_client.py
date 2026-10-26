"""
Tests for Scorva GitHub Ingestion Client.
Verifies URL parsing, Profile A SSRF redirects, IP pinning, streaming limits,
and commit SHA resolution.
"""

import io
import tarfile
import pytest
import httpx

from apps.api.core.ssrf_guard import SSRFViolationError
from apps.api.modules.evaluations.github_client import (
    GitHubIngestionClient,
    GitHubIngestionError,
    parse_github_url,
)
from apps.api.modules.evaluations.safe_extractor import MAX_COMPRESSED_BYTES, ExtractViolationError


def test_parse_github_url_valid_and_invalid():
    """Parses legitimate GitHub URLs and rejects non-GitHub or malformed inputs."""
    # Valid formats
    assert parse_github_url("https://github.com/scorva-org/hackathon-eval") == (
        "scorva-org",
        "hackathon-eval",
    )
    assert parse_github_url("https://github.com/user/project.git") == ("user", "project")
    assert parse_github_url("github.com/owner/repo") == ("owner", "repo")
    assert parse_github_url("https://www.github.com/owner-name/my_repo") == (
        "owner-name",
        "my_repo",
    )

    # Invalid hosting providers
    with pytest.raises(GitHubIngestionError) as exc_gl:
        parse_github_url("https://gitlab.com/owner/repo")
    assert "Unsupported Git hosting provider" in str(exc_gl.value)

    with pytest.raises(GitHubIngestionError) as exc_bb:
        parse_github_url("https://bitbucket.org/owner/repo")
    assert "Unsupported Git hosting provider" in str(exc_bb.value)

    # Malformed paths
    with pytest.raises(GitHubIngestionError):
        parse_github_url("https://github.com/onlyowner")

    with pytest.raises(GitHubIngestionError):
        parse_github_url("https://github.com/")


@pytest.mark.asyncio
async def test_resolve_head_commit_sha_mock():
    """Resolves 40-character commit SHA from GitHub commit endpoint."""
    expected_sha = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        assert "/commits/main" in str(request.url)
        return httpx.Response(200, json={"sha": expected_sha})

    transport = httpx.MockTransport(mock_handler)
    mock_client = httpx.AsyncClient(transport=transport)

    client = GitHubIngestionClient(
        token="ghp_test123",
        custom_client=mock_client,
    )
    sha = await client.resolve_head_commit_sha("scorva", "repo", branch="main")
    assert sha == expected_sha


@pytest.mark.asyncio
async def test_profile_a_redirect_to_codeload_and_auth_stripping():
    """
    Simulates standard GitHub 302 redirect from api.github.com to codeload.github.com.
    Asserts Authorization header is stripped on codeload.github.com and archive is downloaded.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        ti = tarfile.TarInfo(name="repo/README.md")
        ti.size = 12
        tar.addfile(ti, io.BytesIO(b"Hello Scorva"))
    fake_tarball = buf.getvalue()

    call_history = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        call_history.append((request.url.host, str(request.url), dict(request.headers)))
        if request.url.host == "api.github.com":
            # Initial tarball endpoint redirects to codeload
            assert "authorization" in request.headers
            return httpx.Response(
                302,
                headers={"Location": "https://codeload.github.com/scorva/repo/legacy.tar.gz/main"},
            )
        elif request.url.host == "codeload.github.com":
            # Target endpoint: MUST NOT have Authorization header!
            assert "authorization" not in request.headers
            return httpx.Response(200, content=fake_tarball)
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))

    client = GitHubIngestionClient(
        token="ghp_SuperSecretToken1234",
        custom_client=mock_client,
    )

    downloaded = await client.download_repository_tarball("scorva", "repo", "main")
    assert downloaded == fake_tarball
    assert len(call_history) == 2
    assert call_history[0][0] == "api.github.com"
    assert call_history[1][0] == "codeload.github.com"


@pytest.mark.asyncio
async def test_profile_a_rejects_ssrf_redirect_to_unapproved_host():
    """If GitHub API redirects to an unapproved host or metadata service, SSRF guard aborts."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        # Malicious redirect targeting AWS metadata
        return httpx.Response(
            302,
            headers={"Location": "https://169.254.169.254/latest/meta-data"},
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    client = GitHubIngestionClient(custom_client=mock_client)

    with pytest.raises(SSRFViolationError) as exc:
        await client.download_repository_tarball("scorva", "repo", "main")
    assert "not in approved GitHub allowlist" in str(exc.value)


@pytest.mark.asyncio
async def test_profile_a_rejects_redirect_loop_exceeding_max():
    """Redirect loops exceeding max_redirects (3) are aborted with SSRFViolationError."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        # Endless loop on approved host
        return httpx.Response(
            302,
            headers={"Location": "https://api.github.com/loop"},
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    client = GitHubIngestionClient(custom_client=mock_client)

    with pytest.raises(SSRFViolationError) as exc:
        await client.download_repository_tarball("scorva", "repo", "main")
    assert "exceeded maximum allowed redirects" in str(exc.value)


@pytest.mark.asyncio
async def test_full_repository_ingestion_pipeline():
    """End-to-end ingestion pipeline downloads, extracts, and indexes evidence."""
    expected_sha = "0123456789abcdef0123456789abcdef01234567"

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        d1 = b"# Project Documentation"
        t1 = tarfile.TarInfo(name="repo/README.md")
        t1.size = len(d1)
        tar.addfile(t1, io.BytesIO(d1))

        d2 = b"def multiply(x, y):\n    return x * y\n"
        t2 = tarfile.TarInfo(name="repo/src/calc.py")
        t2.size = len(d2)
        tar.addfile(t2, io.BytesIO(d2))
    archive_bytes = buf.getvalue()

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if "/commits/" in str(request.url):
            return httpx.Response(200, json={"sha": expected_sha})
        elif "/tarball/" in str(request.url):
            return httpx.Response(
                302,
                headers={"Location": "https://codeload.github.com/org/repo/tarball"},
            )
        elif request.url.host == "codeload.github.com":
            return httpx.Response(200, content=archive_bytes)
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    client = GitHubIngestionClient(custom_client=mock_client)

    commit_sha, extract_result, evidence_index = await client.ingest_repository(
        "https://github.com/scorva/test-project",
        target_branch="main",
    )

    assert commit_sha == expected_sha
    assert extract_result.file_count == 2
    assert "README.md" in evidence_index.files
    assert "src/calc.py" in evidence_index.files
    assert evidence_index.total_lines_of_code > 0

    # SEC-M3-03: Verify scratch directory was purged upon exit
    assert not extract_result.root_directory.exists()


@pytest.mark.asyncio
async def test_ingest_repository_cleanup_on_failure():
    """SEC-M3-03 Regression: Scratch directory is guaranteed purged even when extraction fails."""
    expected_sha = "0123456789abcdef0123456789abcdef01234567"

    # Corrupt archive payload
    bad_archive = b"\x1f\x8b\x08corrupted_tarball_stream_here"

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if "/commits/" in str(request.url):
            return httpx.Response(200, json={"sha": expected_sha})
        elif "/tarball/" in str(request.url):
            return httpx.Response(200, content=bad_archive)
        return httpx.Response(404)

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    client = GitHubIngestionClient(custom_client=mock_client)

    with pytest.raises(Exception):
        await client.ingest_repository("https://github.com/scorva/bad-project")

    # Verify no eval_* directories remain in /tmp/scorva
    from pathlib import Path
    lingering = list(Path("/tmp/scorva").glob("eval_*"))
    assert len(lingering) == 0


@pytest.mark.asyncio
async def test_streaming_early_content_length_rejection():
    """SEC-M3-02 Regression: Content-Length header exceeding limit is rejected early before reading body."""
    async def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(MAX_COMPRESSED_BYTES + 1024)},
            content=b"never_read",
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    client = GitHubIngestionClient(custom_client=mock_client)

    with pytest.raises(ExtractViolationError) as exc:
        await client.download_repository_tarball("scorva", "repo", "main")
    assert exc.value.code == "COMPRESSED_DOWNLOAD_EXCEEDED"
    assert "Content-Length" in str(exc.value)


@pytest.mark.asyncio
async def test_streaming_incremental_consumption_and_early_abort_live_transport(monkeypatch):
    """
    SEC-M3-02 Regression: Live TLS socket test verifying PinnedAsyncHTTPTransport
    incrementally consumes chunks and terminates socket connection immediately on limit breach.
    """
    import asyncio
    import socket
    import ssl
    import subprocess
    from pathlib import Path
    import shutil
    from apps.api.core.ssrf_guard import PinnedAsyncHTTPTransport

    cert_dir = Path("/tmp/scorva/test_tls_stream")
    cert_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_file = cert_dir / "key.pem"
    cert_file = cert_dir / "cert.pem"

    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(key_file), "-out", str(cert_file),
        "-days", "1", "-nodes",
        "-subj", "/CN=codeload.github.com"
    ], check=True, capture_output=True)

    ssl_server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_server_ctx.load_cert_chain(cert_file, key_file)

    chunks_sent = 0

    async def handle_client(reader, writer):
        nonlocal chunks_sent
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

        writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
        await writer.drain()

        try:
            for _ in range(50):
                chunk = b"X" * 65536
                writer.write(f"{len(chunk):X}\r\n".encode("ascii") + chunk + b"\r\n")
                await writer.drain()
                chunks_sent += 1
                await asyncio.sleep(0.01)
            writer.write(b"0\r\n\r\n")
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError, Exception):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = await asyncio.start_server(handle_client, "127.0.0.1", port, ssl=ssl_server_ctx)
    server_task = asyncio.create_task(server.serve_forever())

    try:
        import apps.api.modules.evaluations.github_client as gc_mod

        original_limit = gc_mod.MAX_COMPRESSED_BYTES
        gc_mod.MAX_COMPRESSED_BYTES = 131072  # 128 KB ceiling

        ssl_client_ctx = ssl.create_default_context(cafile=str(cert_file))
        transport = PinnedAsyncHTTPTransport(
            pinned_map={"codeload.github.com": "127.0.0.1"},
            verify=ssl_client_ctx,
        )
        client = httpx.AsyncClient(transport=transport)
        ingest_client = GitHubIngestionClient(custom_client=client)

        try:
            with monkeypatch.context() as m:
                m.setattr(
                    "apps.api.modules.evaluations.github_client.validate_profile_a_url",
                    lambda url, dns_resolver=None: ("codeload.github.com", "127.0.0.1", port),
                )
                with pytest.raises(ExtractViolationError) as exc:
                    await ingest_client._make_profile_a_request(
                        f"https://codeload.github.com:{port}/tarball",
                        stream_response=True,
                    )
                assert exc.value.code == "COMPRESSED_DOWNLOAD_EXCEEDED"
                # Server sent at most 3-4 chunks before client aborted socket stream!
                assert chunks_sent < 15, f"Expected early socket abort, but server sent {chunks_sent} chunks"
        finally:
            gc_mod.MAX_COMPRESSED_BYTES = original_limit
            await client.aclose()
    finally:
        server.close()
        await server.wait_closed()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
        shutil.rmtree(cert_dir, ignore_errors=True)


