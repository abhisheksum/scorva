"""
Scorva Safe Extraction Engine.

Enforces zero-code execution, streaming decompression quotas, path containment (anti-ZipSlip),
and special file rejection (anti-symlink/hardlink) on untrusted repository archives.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import io
import os
from pathlib import Path
import shutil
import stat
import tarfile
from typing import Generator, List, Optional, Union
import uuid
import zipfile

from apps.api.core.exceptions import AppException


# ==============================================================================
# Security Quotas and Limits (Non-Negotiable Invariants)
# ==============================================================================
MAX_COMPRESSED_BYTES: int = 52_428_800       # 50 MB
MAX_UNCOMPRESSED_BYTES: int = 262_144_000    # 250 MB
MAX_SINGLE_FILE_BYTES: int = 10_485_760      # 10 MB
MAX_FILES: int = 2000
MAX_DIRECTORY_DEPTH: int = 10
MAX_PATH_LENGTH: int = 255
CHUNK_SIZE: int = 65_536                     # 64 KB


class ExtractViolationError(AppException):
    """Raised when an archive breaches path containment, special file, or quota rules."""

    def __init__(self, message: str, code: str = "EXTRACT_VIOLATION"):
        super().__init__(status_code=400, code=code, message=message)


@dataclass
class ExtractedFileInfo:
    """Metadata for an extracted regular file."""
    relative_path: str
    size_bytes: int
    sha256_hash: str


@dataclass
class ExtractionResult:
    """Outcome of safe archive extraction."""
    root_directory: Path
    file_count: int
    total_uncompressed_bytes: int
    manifest: List[ExtractedFileInfo] = field(default_factory=list)
    tree_sha: Optional[str] = None


def ensure_private_directory(target_path: Path) -> Path:
    """
    Creates target_path with restrictive private permissions (0o700 / rwx------).
    Enforces mode via os.chmod immediately after creation to protect against permissive umasks.
    """
    parent = target_path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(parent, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        except OSError:
            pass

    target_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return target_path


def validate_member_path(member_name: str, target_root: Path) -> Path:
    """
    Validates that a member's target path is strictly contained within target_root.
    Rejects directory traversal (..), absolute paths, and excessive depth.
    """
    if not member_name or not member_name.strip():
        raise ExtractViolationError("Archive member has an empty path.", code="INVALID_PATH")

    clean_name = member_name.replace("\\", "/")

    # Reject null bytes in path
    if "\0" in clean_name:
        raise ExtractViolationError("Null byte detected in archive path.", code="SECURITY_VIOLATION")

    # Reject leading slashes or drive letters
    if clean_name.startswith("/") or re_has_drive_letter(clean_name):
        raise ExtractViolationError(
            f"Absolute paths forbidden in archive: '{clean_name}'.",
            code="PATH_TRAVERSAL_DETECTED",
        )

    # Reject '..' traversal segments
    parts = clean_name.split("/")
    if ".." in parts:
        raise ExtractViolationError(
            f"Directory traversal ('..') detected in archive member: '{clean_name}'.",
            code="PATH_TRAVERSAL_DETECTED",
        )

    # Check path length
    if len(clean_name) > MAX_PATH_LENGTH:
        raise ExtractViolationError(
            f"Archive path exceeds maximum length of {MAX_PATH_LENGTH} characters: '{clean_name}'.",
            code="PATH_LENGTH_EXCEEDED",
        )

    # Check directory depth
    relative_path = Path(clean_name)
    if len(relative_path.parts) > MAX_DIRECTORY_DEPTH:
        raise ExtractViolationError(
            f"Archive directory nesting depth exceeds maximum of {MAX_DIRECTORY_DEPTH}: '{clean_name}'.",
            code="DIRECTORY_DEPTH_EXCEEDED",
        )

    target_resolved = target_root.resolve()
    destination = (target_root / relative_path).resolve()

    if not destination.is_relative_to(target_resolved):
        raise ExtractViolationError(
            f"ZipSlip path traversal attempt: '{clean_name}' escapes destination root.",
            code="PATH_TRAVERSAL_DETECTED",
        )

    return destination


def re_has_drive_letter(path_str: str) -> bool:
    """Checks for Windows-style drive letter prefix (e.g. C:, D:)."""
    return len(path_str) >= 2 and path_str[0].isalpha() and path_str[1] == ":"


def safe_extract_tar_stream(
    stream: io.BytesIO,
    destination_root: Path,
) -> ExtractionResult:
    """
    Safely decompresses a tar.gz / tar archive from a binary stream into destination_root.
    Enforces strict streaming quotas and immediate abort on any violation.
    """
    total_uncompressed = 0
    file_count = 0
    manifest: List[ExtractedFileInfo] = []

    ensure_private_directory(destination_root)

    try:
        with tarfile.open(fileobj=stream, mode="r:*") as tar:
            for member in tar:
                # 1. Reject dangerous file types
                if member.issym() or member.islnk():
                    raise ExtractViolationError(
                        f"Archive contains forbidden symbolic or hard link: '{member.name}'.",
                        code="LINK_FORBIDDEN",
                    )
                if member.ischr() or member.isblk() or member.isfifo():
                    raise ExtractViolationError(
                        f"Archive contains forbidden device or special file: '{member.name}'.",
                        code="SPECIAL_FILE_FORBIDDEN",
                    )

                # 2. Check path containment
                dest_path = validate_member_path(member.name, destination_root)

                # 3. Handle directory
                if member.isdir():
                    dest_path.mkdir(parents=True, exist_ok=True, mode=0o700)
                    try:
                        os.chmod(dest_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
                    except OSError:
                        pass
                    continue

                # 4. Handle regular file
                if not member.isreg():
                    # Reject unknown member types
                    raise ExtractViolationError(
                        f"Unsupported archive member type: '{member.name}'.",
                        code="UNSUPPORTED_MEMBER_TYPE",
                    )

                file_count += 1
                if file_count > MAX_FILES:
                    raise ExtractViolationError(
                        f"Archive exceeds maximum allowed file count ({MAX_FILES}).",
                        code="FILE_COUNT_EXCEEDED",
                    )

                # Ensure parent directories exist with 0o700 permissions
                dest_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                try:
                    os.chmod(dest_path.parent, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
                except OSError:
                    pass

                file_obj = tar.extractfile(member)
                if file_obj is None:
                    continue

                current_file_bytes = 0
                hasher = hashlib.sha256()

                # Open destination for writing with strict non-executable permissions
                with open(dest_path, "wb") as out_f:
                    while True:
                        chunk = file_obj.read(CHUNK_SIZE)
                        if not chunk:
                            break

                        chunk_len = len(chunk)
                        current_file_bytes += chunk_len
                        total_uncompressed += chunk_len

                        if current_file_bytes > MAX_SINGLE_FILE_BYTES:
                            raise ExtractViolationError(
                                f"Single file '{member.name}' exceeds maximum allowed size ({MAX_SINGLE_FILE_BYTES} bytes).",
                                code="SINGLE_FILE_SIZE_EXCEEDED",
                            )

                        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                            raise ExtractViolationError(
                                f"Archive decompression bomb detected: total uncompressed bytes exceed {MAX_UNCOMPRESSED_BYTES} bytes.",
                                code="DECOMPRESSION_BOMB_DETECTED",
                            )

                        hasher.update(chunk)
                        out_f.write(chunk)

                # Set non-executable permissions (rw-r--r--)
                os.chmod(dest_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

                rel_str = str(dest_path.relative_to(destination_root))
                manifest.append(
                    ExtractedFileInfo(
                        relative_path=rel_str,
                        size_bytes=current_file_bytes,
                        sha256_hash=hasher.hexdigest(),
                    )
                )

    except Exception:
        # Guarantee complete cleanup of scratch directory upon failure
        shutil.rmtree(destination_root, ignore_errors=True)
        raise

    return ExtractionResult(
        root_directory=destination_root,
        file_count=file_count,
        total_uncompressed_bytes=total_uncompressed,
        manifest=manifest,
    )


def safe_extract_zip_stream(
    stream: io.BytesIO,
    destination_root: Path,
) -> ExtractionResult:
    """
    Safely decompresses a zip archive from a binary stream into destination_root.
    Enforces strict streaming quotas and immediate abort on any violation.
    """
    total_uncompressed = 0
    file_count = 0
    manifest: List[ExtractedFileInfo] = []

    ensure_private_directory(destination_root)

    try:
        with zipfile.ZipFile(stream, mode="r") as zf:
            for zip_info in zf.infolist():
                # 1. Reject symlinks in zip archives
                # Check POSIX symlink bit in external_attr (0o120000)
                mode = zip_info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ExtractViolationError(
                        f"Archive contains forbidden symbolic link: '{zip_info.filename}'.",
                        code="LINK_FORBIDDEN",
                    )
                if stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode):
                    raise ExtractViolationError(
                        f"Archive contains forbidden special device or FIFO: '{zip_info.filename}'.",
                        code="SPECIAL_FILE_FORBIDDEN",
                    )

                # 2. Check path containment
                dest_path = validate_member_path(zip_info.filename, destination_root)

                # 3. Handle directory
                if zip_info.is_dir() or zip_info.filename.endswith("/"):
                    dest_path.mkdir(parents=True, exist_ok=True, mode=0o700)
                    try:
                        os.chmod(dest_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
                    except OSError:
                        pass
                    continue

                file_count += 1
                if file_count > MAX_FILES:
                    raise ExtractViolationError(
                        f"Archive exceeds maximum allowed file count ({MAX_FILES}).",
                        code="FILE_COUNT_EXCEEDED",
                    )

                dest_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                try:
                    os.chmod(dest_path.parent, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
                except OSError:
                    pass

                current_file_bytes = 0
                hasher = hashlib.sha256()

                with zf.open(zip_info, mode="r") as file_obj, open(dest_path, "wb") as out_f:
                    while True:
                        chunk = file_obj.read(CHUNK_SIZE)
                        if not chunk:
                            break

                        chunk_len = len(chunk)
                        current_file_bytes += chunk_len
                        total_uncompressed += chunk_len

                        if current_file_bytes > MAX_SINGLE_FILE_BYTES:
                            raise ExtractViolationError(
                                f"Single file '{zip_info.filename}' exceeds maximum allowed size ({MAX_SINGLE_FILE_BYTES} bytes).",
                                code="SINGLE_FILE_SIZE_EXCEEDED",
                            )

                        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                            raise ExtractViolationError(
                                f"Archive decompression bomb detected: total uncompressed bytes exceed {MAX_UNCOMPRESSED_BYTES} bytes.",
                                code="DECOMPRESSION_BOMB_DETECTED",
                            )

                        hasher.update(chunk)
                        out_f.write(chunk)

                os.chmod(dest_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

                rel_str = str(dest_path.relative_to(destination_root))
                manifest.append(
                    ExtractedFileInfo(
                        relative_path=rel_str,
                        size_bytes=current_file_bytes,
                        sha256_hash=hasher.hexdigest(),
                    )
                )

    except Exception:
        shutil.rmtree(destination_root, ignore_errors=True)
        raise

    return ExtractionResult(
        root_directory=destination_root,
        file_count=file_count,
        total_uncompressed_bytes=total_uncompressed,
        manifest=manifest,
    )


def safe_extract_archive_bytes(
    archive_bytes: bytes,
    destination_root: Optional[Path] = None,
    job_id: Optional[Union[uuid.UUID, str]] = None,
) -> ExtractionResult:
    """
    Inspects archive magic bytes, enforces compressed size limit, and extracts safely.
    """
    compressed_len = len(archive_bytes)
    if compressed_len > MAX_COMPRESSED_BYTES:
        raise ExtractViolationError(
            f"Compressed archive size ({compressed_len} bytes) exceeds maximum of {MAX_COMPRESSED_BYTES} bytes.",
            code="COMPRESSED_SIZE_EXCEEDED",
        )

    if destination_root is None:
        token = str(job_id or uuid.uuid4())
        destination_root = Path(f"/tmp/scorva/eval_{token}")

    stream = io.BytesIO(archive_bytes)

    # Check magic header: GZIP (0x1F 0x8B), ZIP (0x50 0x4B)
    if archive_bytes.startswith(b"\x1f\x8b"):
        return safe_extract_tar_stream(stream, destination_root)
    elif archive_bytes.startswith(b"PK\x03\x04") or archive_bytes.startswith(b"PK\x05\x06"):
        return safe_extract_zip_stream(stream, destination_root)
    else:
        # Check standard uncompressed tar
        try:
            stream.seek(0)
            if tarfile.is_tarfile(stream):
                stream.seek(0)
                return safe_extract_tar_stream(stream, destination_root)
        except Exception:
            pass

        raise ExtractViolationError(
            "Unsupported or corrupted archive format. Expected tar.gz or zip.",
            code="UNSUPPORTED_ARCHIVE_FORMAT",
        )


@contextmanager
def ephemeral_extracted_repository(
    archive_bytes: bytes,
    job_id: Optional[Union[uuid.UUID, str]] = None,
) -> Generator[ExtractionResult, None, None]:
    """
    Context manager guaranteeing that extracted ephemeral files are completely
    purged from the host filesystem upon completion or error.
    """
    token = str(job_id or uuid.uuid4())
    temp_dir = Path(f"/tmp/scorva/eval_{token}")
    result = safe_extract_archive_bytes(archive_bytes, destination_root=temp_dir, job_id=token)
    try:
        yield result
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
