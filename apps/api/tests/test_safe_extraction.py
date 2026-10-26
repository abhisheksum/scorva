"""
Comprehensive adversarial security tests for Scorva Safe Extractor.
Tests ZipSlip, symlinks, hardlinks, special devices, quotas, and decompression bombs.
"""

import gzip
import io
import os
from pathlib import Path
import stat
import tarfile
import uuid
import zipfile
import pytest

from apps.api.modules.evaluations.safe_extractor import (
    MAX_COMPRESSED_BYTES,
    MAX_DIRECTORY_DEPTH,
    MAX_FILES,
    MAX_PATH_LENGTH,
    MAX_SINGLE_FILE_BYTES,
    MAX_UNCOMPRESSED_BYTES,
    ExtractViolationError,
    ephemeral_extracted_repository,
    safe_extract_archive_bytes,
)


# ==============================================================================
# Helper archive builders
# ==============================================================================
def create_in_memory_tar_gz(members: dict[str, bytes]) -> bytes:
    """Builds an in-memory tar.gz archive from a mapping of {filename: content}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            ti = tarfile.TarInfo(name=name)
            ti.size = len(data)
            ti.mtime = 1700000000
            ti.mode = 0o644
            tar.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def create_in_memory_zip(members: dict[str, bytes]) -> bytes:
    """Builds an in-memory zip archive from a mapping of {filename: content}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ==============================================================================
# Tests: Legitimate Extraction
# ==============================================================================
def test_legitimate_tar_gz_extraction():
    """Valid tar.gz archive extracts properly and populates manifest."""
    files = {
        "repo/README.md": b"# Project Documentation\nClean code.",
        "repo/src/main.py": b"print('hello world')\n",
        "repo/tests/test_main.py": b"def test_app(): assert True\n",
    }
    archive_bytes = create_in_memory_tar_gz(files)
    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_legit_tar_{token}")

    try:
        result = safe_extract_archive_bytes(archive_bytes, destination_root=dest)
        assert result.file_count == 3
        assert result.total_uncompressed_bytes > 0
        assert len(result.manifest) == 3

        readme_entry = next(m for m in result.manifest if "README.md" in m.relative_path)
        assert readme_entry.size_bytes == len(files["repo/README.md"])

        # Assert non-executable file permissions on host
        readme_file = dest / readme_entry.relative_path
        mode = readme_file.stat().st_mode
        assert not (mode & stat.S_IXUSR or mode & stat.S_IXGRP or mode & stat.S_IXOTH)
    finally:
        import shutil
        shutil.rmtree(dest, ignore_errors=True)


def test_legitimate_zip_extraction():
    """Valid zip archive extracts properly and populates manifest."""
    files = {
        "repo/package.json": b'{"name": "scorva-test", "version": "1.0.0"}',
        "repo/index.ts": b"export const version = '1.0.0';",
    }
    archive_bytes = create_in_memory_zip(files)
    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_legit_zip_{token}")

    try:
        result = safe_extract_archive_bytes(archive_bytes, destination_root=dest)
        assert result.file_count == 2
        assert len(result.manifest) == 2
    finally:
        import shutil
        shutil.rmtree(dest, ignore_errors=True)


# ==============================================================================
# Tests: Adversarial ZipSlip / Path Traversal
# ==============================================================================
@pytest.mark.parametrize(
    "evil_path",
    [
        "../../../../../../etc/passwd",
        "../../evil.py",
        "sub/dir/../../../../escaped.txt",
        "/etc/shadow",
        "C:\\Windows\\System32\\cmd.exe",
        "sub/../..",
    ],
)
def test_path_traversal_rejection_tar(evil_path: str):
    """Tarball members attempting directory traversal outside root are immediately rejected."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        ti = tarfile.TarInfo(name=evil_path)
        ti.size = 14
        tar.addfile(ti, io.BytesIO(b"root:x:0:0:root"))
    archive_bytes = buf.getvalue()

    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_traversal_{token}")

    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(archive_bytes, destination_root=dest)
    assert exc.value.code == "PATH_TRAVERSAL_DETECTED"
    # Verify cleanup
    assert not dest.exists()


def test_path_traversal_rejection_zip():
    """Zip members attempting directory traversal outside root are immediately rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("../../etc/passwd", b"malicious content")
    archive_bytes = buf.getvalue()

    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_zipslip_{token}")

    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(archive_bytes, destination_root=dest)
    assert exc.value.code == "PATH_TRAVERSAL_DETECTED"
    assert not dest.exists()


# ==============================================================================
# Tests: Symlinks, Hardlinks, and Special Devices
# ==============================================================================
def test_symlink_rejection_tar():
    """Tarball containing a symbolic link is immediately rejected with LINK_FORBIDDEN."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        ti = tarfile.TarInfo(name="repo/evil_link")
        ti.type = tarfile.SYMTYPE
        ti.linkname = "/etc/passwd"
        tar.addfile(ti)
    archive_bytes = buf.getvalue()

    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_symlink_{token}")

    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(archive_bytes, destination_root=dest)
    assert exc.value.code == "LINK_FORBIDDEN"
    assert not dest.exists()


def test_hardlink_rejection_tar():
    """Tarball containing a hard link is immediately rejected with LINK_FORBIDDEN."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # First file
        t1 = tarfile.TarInfo(name="repo/file1.txt")
        t1.size = 5
        tar.addfile(t1, io.BytesIO(b"hello"))
        # Hard link to file1
        t2 = tarfile.TarInfo(name="repo/file2_link")
        t2.type = tarfile.LNKTYPE
        t2.linkname = "repo/file1.txt"
        tar.addfile(t2)
    archive_bytes = buf.getvalue()

    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_hardlink_{token}")

    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(archive_bytes, destination_root=dest)
    assert exc.value.code == "LINK_FORBIDDEN"
    assert not dest.exists()


def test_fifo_device_rejection_tar():
    """Tarball containing a character/block device or FIFO is immediately rejected."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        ti = tarfile.TarInfo(name="repo/my_fifo")
        ti.type = tarfile.FIFOTYPE
        tar.addfile(ti)
    archive_bytes = buf.getvalue()

    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_fifo_{token}")

    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(archive_bytes, destination_root=dest)
    assert exc.value.code == "SPECIAL_FILE_FORBIDDEN"
    assert not dest.exists()


# ==============================================================================
# Tests: Numerical Quotas & Decompression Bomb
# ==============================================================================
def test_single_file_size_limit_breach():
    """Archive with an individual file exceeding 10MB is immediately aborted."""
    oversized_data = b"0" * (MAX_SINGLE_FILE_BYTES + 1024)
    archive_bytes = create_in_memory_tar_gz({"repo/large_file.bin": oversized_data})

    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_oversized_{token}")

    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(archive_bytes, destination_root=dest)
    assert exc.value.code == "SINGLE_FILE_SIZE_EXCEEDED"
    assert not dest.exists()


def test_file_count_limit_breach():
    """Archive with more than MAX_FILES (2000) files is aborted."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for i in range(MAX_FILES + 5):
            ti = tarfile.TarInfo(name=f"repo/file_{i}.txt")
            ti.size = 1
            tar.addfile(ti, io.BytesIO(b"a"))
    archive_bytes = buf.getvalue()

    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_max_files_{token}")

    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(archive_bytes, destination_root=dest)
    assert exc.value.code == "FILE_COUNT_EXCEEDED"
    assert not dest.exists()


def test_directory_depth_limit_breach():
    """Archive with directory depth > MAX_DIRECTORY_DEPTH (10) is rejected."""
    nested_path = "a/" * 12 + "file.txt"
    archive_bytes = create_in_memory_tar_gz({nested_path: b"deep"})

    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_depth_{token}")

    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(archive_bytes, destination_root=dest)
    assert exc.value.code == "DIRECTORY_DEPTH_EXCEEDED"
    assert not dest.exists()


def test_path_length_limit_breach():
    """Archive with path length > MAX_PATH_LENGTH (255) is rejected."""
    long_path = "repo/" + "a" * 260 + ".txt"
    archive_bytes = create_in_memory_tar_gz({long_path: b"long"})

    token = uuid.uuid4().hex[:8]
    dest = Path(f"/tmp/scorva/test_path_len_{token}")

    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(archive_bytes, destination_root=dest)
    assert exc.value.code == "PATH_LENGTH_EXCEEDED"
    assert not dest.exists()


def test_compressed_size_limit_breach():
    """Compressed input exceeding MAX_COMPRESSED_BYTES (50MB) is rejected immediately."""
    fake_oversized = b"PK\x03\x04" + b"0" * (MAX_COMPRESSED_BYTES + 10)
    with pytest.raises(ExtractViolationError) as exc:
        safe_extract_archive_bytes(fake_oversized)
    assert exc.value.code == "COMPRESSED_SIZE_EXCEEDED"


def test_ephemeral_context_manager_cleanup():
    """ephemeral_extracted_repository context manager cleans up directory upon exit."""
    files = {"repo/main.py": b"print('clean')"}
    archive_bytes = create_in_memory_tar_gz(files)

    temp_path = None
    with ephemeral_extracted_repository(archive_bytes) as result:
        temp_path = result.root_directory
        assert temp_path.exists()
        assert (temp_path / "repo/main.py").exists()

    # After exit from context manager, directory must be completely removed
    assert not temp_path.exists()


def test_scratch_directory_restrictive_permissions():
    """SEC-M3-04 Regression: Scratch root and subdirectories are created with strict 0o700 permissions."""
    files = {
        "repo/sub/module/main.py": b"print('secure')",
        "repo/config.json": b"{}",
    }
    archive_bytes = create_in_memory_tar_gz(files)

    with ephemeral_extracted_repository(archive_bytes) as result:
        dest_root = result.root_directory
        assert dest_root.exists()

        # Check root directory permissions via os.stat
        root_stat = os.stat(dest_root)
        root_mode = stat.S_IMODE(root_stat.st_mode)
        assert root_mode == 0o700, f"Expected 0o700 on scratch root, got {oct(root_mode)}"

        # Check subdirectories have 0o700 permissions
        sub_dir = dest_root / "repo" / "sub" / "module"
        assert sub_dir.exists()
        sub_mode = stat.S_IMODE(os.stat(sub_dir).st_mode)
        assert sub_mode == 0o700, f"Expected 0o700 on sub directory, got {oct(sub_mode)}"

        # Check extracted files are non-executable
        file_path = sub_dir / "main.py"
        assert file_path.exists()
        file_mode = stat.S_IMODE(os.stat(file_path).st_mode)
        assert not (file_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)), "File must not be executable"

