"""
Scorva GitHub Ingestion Client.

Enforces SSRF Profile A validation, IP pinning, redirect interception,
compressed streaming quota enforcement, and commit SHA resolution.
"""

from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse
import uuid

import httpx

from apps.api.core.exceptions import AppException
from apps.api.core.ssrf_guard import (
    GITHUB_ALLOWED_HOSTNAMES,
    PinnedAsyncHTTPTransport,
    SSRFViolationError,
    validate_profile_a_url,
)
from apps.api.modules.evaluations.evidence_indexer import EvidenceIndex, index_extracted_repository
from apps.api.modules.evaluations.safe_extractor import (
    MAX_COMPRESSED_BYTES,
    ExtractionResult,
    ExtractViolationError,
    ephemeral_extracted_repository,
    safe_extract_archive_bytes,
)


class GitHubIngestionError(AppException):
    """Raised when GitHub API operations, authentication, or downloads fail."""

    def __init__(self, message: str, code: str = "GITHUB_INGESTION_ERROR", status_code: int = 400):
        super().__init__(status_code=status_code, code=code, message=message)


def parse_github_url(repo_url: str) -> Tuple[str, str]:
    """
    Parses a GitHub repository URL into (owner, repo).
    Accepts:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - github.com/owner/repo
    Raises GitHubIngestionError on invalid or suspicious format.
    """
    clean = repo_url.strip()
    if not clean:
        raise GitHubIngestionError("Repository URL cannot be empty.", code="MALFORMED_URL")

    # Security check: forbid embedded credentials or user-info
    if "@" in clean:
        raise GitHubIngestionError(
            "Security violation: Embedded credentials or user-info are strictly forbidden in repository URLs.",
            code="CREDENTIALS_IN_URL_FORBIDDEN",
        )

    if not clean.startswith("http://") and not clean.startswith("https://"):
        clean = "https://" + clean

    try:
        parsed = urlparse(clean)
    except Exception as exc:
        raise GitHubIngestionError(f"Malformed repository URL '{repo_url}': {exc}", code="MALFORMED_URL") from exc

    if parsed.username or parsed.password:
        raise GitHubIngestionError(
            "Security violation: Embedded credentials or user-info are strictly forbidden in repository URLs.",
            code="CREDENTIALS_IN_URL_FORBIDDEN",
        )

    if parsed.port not in (None, 80, 443):
        raise GitHubIngestionError(
            f"Security violation: Non-standard port '{parsed.port}' is forbidden.",
            code="UNSUPPORTED_GIT_PORT",
        )

    if parsed.query or parsed.fragment:
        raise GitHubIngestionError(
            "Security violation: Query parameters and URL fragments are forbidden in repository URLs.",
            code="INVALID_URL_COMPONENTS",
        )

    hostname = (parsed.hostname or "").lower()
    if hostname not in ("github.com", "www.github.com"):
        raise GitHubIngestionError(
            f"Unsupported Git hosting provider '{hostname or parsed.netloc}'. Scorva requires GitHub.",
            code="UNSUPPORTED_GIT_PROVIDER",
        )

    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path_parts) < 2:
        raise GitHubIngestionError(
            f"Invalid GitHub repository URL format '{repo_url}'. Expected 'https://github.com/owner/repo'.",
            code="INVALID_REPOSITORY_PATH",
        )

    owner = path_parts[0]
    repo = path_parts[1].removesuffix(".git")

    # Validate characters (alphanumeric, hyphens, underscores, dots)
    if not owner.replace("-", "").replace("_", "").isalnum():
        raise GitHubIngestionError(f"Invalid characters in repository owner '{owner}'.", code="INVALID_REPOSITORY_PATH")
    if not repo.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise GitHubIngestionError(f"Invalid characters in repository name '{repo}'.", code="INVALID_REPOSITORY_PATH")

    return owner, repo



class GitHubIngestionClient:
    """
    Client for acquiring repository tarballs from GitHub with Profile A SSRF defense,
    IP pinning, streaming transfer limits, and redirect validation.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        dns_resolver: Optional[Any] = None,
        timeout_seconds: float = 60.0,
        custom_client: Optional[httpx.AsyncClient] = None,
    ):
        self.token = token
        self.dns_resolver = dns_resolver
        self.timeout_seconds = timeout_seconds
        self._custom_client = custom_client

    def _get_headers(self, host: str) -> Dict[str, str]:
        headers = {
            "User-Agent": "Scorva-Ingestion-Engine/1.0",
            "Accept": "application/vnd.github.v3+json",
        }
        if self.token and host == "api.github.com":
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _make_profile_a_request(
        self,
        url_str: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        max_redirects: int = 3,
        stream_response: bool = False,
    ) -> Union[httpx.Response, bytes]:
        """
        Executes an HTTP request adhering strictly to Profile A security:
        1. Validates URL against GITHUB_ALLOWED_HOSTNAMES and public unicast IPs.
        2. Pins connection IP.
        3. Intercepts redirects up to max_redirects and re-validates target.
        4. Strips Authorization header if redirect changes hostname.
        5. Enforces MAX_COMPRESSED_BYTES limit on stream.
        """
        current_url = url_str
        redirects_followed = 0

        while True:
            # 1. Profile A Validation & IP Pinning
            hostname, pinned_ip, port = validate_profile_a_url(
                current_url, dns_resolver=self.dns_resolver
            )

            req_headers = headers.copy() if headers else self._get_headers(hostname)
            # If redirected from api.github.com to codeload.github.com, strip Authorization header
            if hostname != "api.github.com" and "Authorization" in req_headers:
                del req_headers["Authorization"]

            # Use injected client if present (e.g. for testing with custom transports)
            if self._custom_client:
                client = self._custom_client
                should_close = False
            else:
                transport = PinnedAsyncHTTPTransport(
                    pinned_map={hostname: pinned_ip},
                    verify=True,
                )
                client = httpx.AsyncClient(transport=transport, timeout=self.timeout_seconds)
                should_close = True

            resp: Optional[httpx.Response] = None
            try:
                # SEC-M3-02: Use build_request and send with stream=True to prevent buffering full response into RAM
                req = client.build_request(
                    method=method,
                    url=current_url,
                    headers=req_headers,
                )
                try:
                    resp = await client.send(
                        req,
                        stream=stream_response,
                        follow_redirects=False,
                    )
                except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                    raise GitHubIngestionError(
                        f"Network error communicating with GitHub endpoint '{current_url}': {exc}",
                        code="GITHUB_NETWORK_ERROR",
                    ) from exc

                # Check for redirect (301, 302, 307, 308)
                if resp.status_code in (301, 302, 307, 308):
                    location = resp.headers.get("Location")
                    await resp.aclose()
                    if not location:
                        raise GitHubIngestionError(
                            f"Redirect {resp.status_code} received without Location header from {current_url}."
                        )

                    redirects_followed += 1
                    if redirects_followed > max_redirects:
                        raise SSRFViolationError(
                            f"SSRF violation: exceeded maximum allowed redirects ({max_redirects})."
                        )

                    # Resolve relative redirect URLs against current URL
                    next_url = urljoin(current_url, location)
                    current_url = next_url
                    continue

                # Not a redirect, check response status
                if resp.status_code == 404:
                    await resp.aclose()
                    if "/branches/" in current_url or "/commits/" in current_url:
                        raise GitHubIngestionError(
                            f"Branch or commit not found on GitHub (HTTP 404): {current_url}.",
                            code="BRANCH_NOT_FOUND",
                            status_code=404,
                        )
                    raise GitHubIngestionError(
                        f"Repository resource not found on GitHub (HTTP 404): {current_url}. "
                        "Verify repository URL or ensure access credentials have 'contents:read' scope.",
                        code="GITHUB_REPOSITORY_NOT_FOUND",
                        status_code=404,
                    )
                elif resp.status_code == 401 or resp.status_code == 403:
                    remaining = resp.headers.get("x-ratelimit-remaining")
                    msg = (await resp.aread()).decode("utf-8", errors="replace")[:200]
                    await resp.aclose()
                    if remaining == "0" or "rate limit" in msg.lower():
                        raise GitHubIngestionError(
                            f"GitHub API rate limit exceeded: {msg}",
                            code="GITHUB_RATE_LIMITED",
                            status_code=429,
                        )
                    if resp.status_code == 403:
                        raise GitHubIngestionError(
                            f"GitHub repository access forbidden (HTTP 403): {msg}",
                            code="PRIVATE_REPO_UNAUTHORIZED",
                            status_code=403,
                        )
                    raise GitHubIngestionError(
                        f"GitHub authentication error (HTTP 401): {msg}",
                        code="GITHUB_AUTH_ERROR",
                        status_code=401,
                    )
                elif resp.status_code >= 500:
                    msg = (await resp.aread()).decode("utf-8", errors="replace")[:200]
                    await resp.aclose()
                    raise GitHubIngestionError(
                        f"GitHub service unavailable (HTTP {resp.status_code}): {msg}",
                        code="GITHUB_UNAVAILABLE",
                        status_code=502,
                    )
                elif resp.status_code >= 400:
                    msg = (await resp.aread()).decode("utf-8", errors="replace")[:200]
                    await resp.aclose()
                    raise GitHubIngestionError(
                        f"GitHub API error (HTTP {resp.status_code}): {msg}",
                        code="GITHUB_API_ERROR",
                        status_code=resp.status_code,
                    )

                if stream_response:
                    # Early check: reject Content-Length exceeding MAX_COMPRESSED_BYTES if present
                    cl_header = resp.headers.get("Content-Length")
                    if cl_header:
                        try:
                            cl_val = int(cl_header.strip())
                            if cl_val > MAX_COMPRESSED_BYTES:
                                await resp.aclose()
                                raise ExtractViolationError(
                                    f"Downloaded compressed repository archive Content-Length ({cl_val} bytes) exceeded maximum size limit of {MAX_COMPRESSED_BYTES} bytes.",
                                    code="COMPRESSED_DOWNLOAD_EXCEEDED",
                                )
                        except ValueError:
                            pass

                    # Enforce MAX_COMPRESSED_BYTES quota while streaming chunks from socket
                    content_chunks: List[bytes] = []
                    total_bytes = 0
                    try:
                        async for chunk in resp.aiter_bytes():
                            total_bytes += len(chunk)
                            if total_bytes > MAX_COMPRESSED_BYTES:
                                raise ExtractViolationError(
                                    f"Downloaded compressed repository archive exceeded maximum size limit of {MAX_COMPRESSED_BYTES} bytes.",
                                    code="COMPRESSED_DOWNLOAD_EXCEEDED",
                                )
                            content_chunks.append(chunk)

                        return b"".join(content_chunks)
                    finally:
                        await resp.aclose()
                else:
                    return resp

            finally:
                if should_close:
                    await client.aclose()

    async def resolve_head_commit_sha(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
    ) -> str:
        """
        Queries GitHub API to resolve the exact 40-character hexadecimal commit SHA
        for the target branch.
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
        resp = await self._make_profile_a_request(url, method="GET", stream_response=False)
        assert isinstance(resp, httpx.Response)

        try:
            payload = resp.json()
            sha = payload.get("sha")
            if not sha or len(sha) != 40 or not all(c in "0123456789abcdefABCDEF" for c in sha):
                raise ValueError(f"Invalid commit SHA format: {sha}")
            return sha.lower()
        except Exception as exc:
            raise GitHubIngestionError(
                f"Failed to parse commit SHA from GitHub response: {exc}",
                code="INVALID_COMMIT_RESPONSE",
            ) from exc

    async def verify_repository_access(
        self,
        owner: str,
        repo: str,
        target_branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Queries GitHub API with Profile A security to verify:
        1. Repository existence and accessibility
        2. Default branch and visibility
        3. Target branch existence and commit SHA
        Returns metadata dictionary on success.
        Raises GitHubIngestionError on failure.
        """
        # 1. Check repo metadata
        repo_url = f"https://api.github.com/repos/{owner}/{repo}"
        repo_resp = await self._make_profile_a_request(repo_url, method="GET", stream_response=False)
        assert isinstance(repo_resp, httpx.Response)

        repo_data = repo_resp.json()
        default_branch = repo_data.get("default_branch") or "main"
        is_private = bool(repo_data.get("private", False))

        # 2. Determine target branch
        requested_branch = target_branch.strip() if target_branch and target_branch.strip() else default_branch

        # 3. Check requested branch commit SHA
        commit_sha = await self.resolve_head_commit_sha(owner, repo, branch=requested_branch)

        return {
            "owner": owner,
            "repo": repo,
            "canonical_repo_id": f"{owner}/{repo}",
            "default_branch": default_branch,
            "target_branch": requested_branch,
            "commit_sha": commit_sha,
            "is_private": is_private,
            "is_accessible": True,
        }


    async def download_repository_tarball(
        self,
        owner: str,
        repo: str,
        commit_sha: str,
    ) -> bytes:
        """
        Downloads the tarball archive for a repository at a frozen commit SHA.
        Follows Profile A redirects (e.g. from api.github.com to codeload.github.com).
        Enforces MAX_COMPRESSED_BYTES limit (50MB).
        """
        url = f"https://api.github.com/repos/{owner}/{repo}/tarball/{commit_sha}"
        archive_bytes = await self._make_profile_a_request(
            url,
            method="GET",
            stream_response=True,
        )
        assert isinstance(archive_bytes, bytes)
        return archive_bytes

    async def ingest_repository(
        self,
        repo_url: str,
        target_branch: str = "main",
        job_id: Optional[Union[uuid.UUID, str]] = None,
    ) -> Tuple[str, ExtractionResult, EvidenceIndex]:
        """
        Full Milestone 3 Ingestion Pipeline:
        1. Parses repository URL.
        2. Resolves frozen commit SHA.
        3. Downloads archive with Profile A validation.
        4. Extracts safely under strict numerical quotas.
        5. Indexes files and redacts secrets.
        Returns (commit_sha, ExtractionResult, EvidenceIndex).
        """
        owner, repo = parse_github_url(repo_url)
        commit_sha = await self.resolve_head_commit_sha(owner, repo, branch=target_branch)
        archive_bytes = await self.download_repository_tarball(owner, repo, commit_sha)

        token = str(job_id or uuid.uuid4())
        with ephemeral_extracted_repository(archive_bytes, job_id=token) as extract_result:
            evidence_index = index_extracted_repository(extract_result.root_directory)

        return commit_sha, extract_result, evidence_index
