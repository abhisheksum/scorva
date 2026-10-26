"""
Scorva Evidence Indexer & Secret Redaction Engine.

Statically parses, categorizes, indexes, and redacts repository evidence
without executing any untrusted code.
"""

from dataclasses import dataclass, field
from enum import Enum
import fnmatch
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import xml.etree.ElementTree as ET


class TaxonomyCategory(str, Enum):
    DOCUMENTATION = "documentation"
    BUILD_CONFIG = "build_config"
    TEST_SUITES = "test_suites"
    SOURCE_CODE = "source_code"
    OTHER = "other"


# Secret & Sensitive Files to unconditionally exclude from evidence indexing
EXCLUDED_FILE_PATTERNS: Set[str] = {
    ".git",
    ".env*",
    "*.env",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "*.p12",
    "*.pfx",
    "credentials.json",
    "service-account*.json",
    "*.cert",
    "*.crt",
    "*.keystore",
}

# Directories to unconditionally ignore
EXCLUDED_DIRECTORY_PATTERNS: Set[str] = {
    ".git",
    "node_modules",
    "target",
    "dist",
    "build",
    "__pycache__",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
}

# Regex patterns for redacting credentials and tokens from code snippets
SECRET_REDACTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # GitHub Tokens (classic, fine-grained, app, OAuth)
    (re.compile(r"ghp_[a-zA-Z0-9]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{20,}"), "[REDACTED_GITHUB_PAT]"),
    (re.compile(r"gh[opurs]_[a-zA-Z0-9]{20,}"), "[REDACTED_GITHUB_TOKEN]"),
    # AWS Access Keys & STS Temporary Keys
    (re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    # Stripe API Keys
    (re.compile(r"(?:sk|rk)_(?:live|test)_[a-zA-Z0-9]{20,}"), "[REDACTED_API_KEY]"),
    # OpenAI & Generic API Keys
    (re.compile(r"sk-[a-zA-Z0-9_-]{20,}"), "[REDACTED_API_KEY]"),
    # JSON Web Tokens (JWT)
    (re.compile(r"eyJ[a-zA-Z0-9_-]{20,}\.eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}"), "[REDACTED_JWT]"),
    # Hardcoded passwords/secrets in code (e.g. password = "mysecret123" or password: "secret")
    (
        re.compile(
            r"""(?i)(password|secret[_-]?key|secret|api[_-]?key|access[_-]?token|private[_-]?key|auth[_-]?token)\s*([:=])\s*['"](?!\[REDACTED_)[^'"]{6,}['"]"""
        ),
        r'\1 \2 "[REDACTED_SECRET]"',
    ),
]


def sanitize_xml_text(text: str) -> str:
    """Removes control characters disallowed by XML 1.0 (permitting \t, \n, \r)."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]", "", text)


def redact_secrets_from_text(content: str) -> str:
    """
    Sanitizes untrusted repository text by masking known credential patterns,
    API keys, AWS tokens, JWTs, and hardcoded passwords with explicit placeholders.
    """
    if not content:
        return ""

    sanitized = content
    for pattern, replacement in SECRET_REDACTION_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    return sanitized


def is_path_excluded(relative_path: Path) -> bool:
    """Checks whether a file path belongs to an excluded directory or secret pattern."""
    parts = relative_path.parts
    # Check directory exclusion
    for part in parts[:-1]:
        for pattern in EXCLUDED_DIRECTORY_PATTERNS:
            if fnmatch.fnmatch(part, pattern):
                return True

    # Check filename exclusion
    filename = parts[-1] if parts else ""
    for pattern in EXCLUDED_FILE_PATTERNS:
        if fnmatch.fnmatch(filename.lower(), pattern):
            return True

    return False


def classify_file(relative_path: Path) -> TaxonomyCategory:
    """Classifies a relative file path into an architectural evidence taxonomy."""
    path_str = str(relative_path).lower().replace("\\", "/")
    filename = relative_path.name.lower()
    suffix = relative_path.suffix.lower()

    # Build and Package Configurations (evaluated first to capture requirements.txt)
    if (
        filename in (
            "package.json",
            "cargo.toml",
            "pyproject.toml",
            "requirements.txt",
            "go.mod",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "makefile",
            "dockerfile",
            "gemfile",
            "composer.json",
        )
        or filename.startswith("requirements")
    ):
        return TaxonomyCategory.BUILD_CONFIG

    # Test Suites
    if (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith(".spec.ts")
        or filename.endswith(".test.ts")
        or filename.endswith(".spec.js")
        or filename.endswith(".test.js")
        or "tests/" in path_str
        or "test/" in path_str
        or "__tests__/" in path_str
    ):
        return TaxonomyCategory.TEST_SUITES

    # Documentation
    if (
        filename.startswith("readme")
        or filename.startswith("architecture")
        or filename.startswith("contributing")
        or filename.startswith("license")
        or filename.startswith("spec")
        or path_str.startswith("docs/")
        or path_str.startswith("doc/")
        or suffix in (".md", ".rst", ".txt", ".adoc")
    ):
        return TaxonomyCategory.DOCUMENTATION

    # Source Code
    if suffix in (
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".rs",
        ".go",
        ".java",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".sql",
        ".sh",
        ".swift",
        ".kt",
        ".scala",
        ".html",
        ".css",
    ):
        return TaxonomyCategory.SOURCE_CODE

    return TaxonomyCategory.OTHER


@dataclass
class IndexedFile:
    """Structured line-indexed record for an extracted repository file."""
    relative_path: str
    category: TaxonomyCategory
    total_lines: int
    size_bytes: int
    lines: List[str] = field(default_factory=list)

    def get_line_range_snippet(self, start_line: int, end_line: int, max_chars: int = 500) -> str:
        """
        Extracts and redacts a 1-indexed snippet between start_line and end_line (inclusive).
        Truncates to max_chars with ellipsis to fit evidence reference constraints.
        """
        if start_line < 1:
            start_line = 1
        if end_line > self.total_lines:
            end_line = self.total_lines
        if start_line > end_line:
            return ""

        selected_lines = self.lines[start_line - 1 : end_line]
        snippet_raw = "\n".join(selected_lines)
        redacted = redact_secrets_from_text(snippet_raw)

        if len(redacted) > max_chars:
            return redacted[: max_chars - 3] + "..."
        return redacted


@dataclass
class EvidenceIndex:
    """Repository-wide index of sanitized source files and architectural statistics."""
    files: Dict[str, IndexedFile] = field(default_factory=dict)
    total_lines_of_code: int = 0
    languages: Dict[str, int] = field(default_factory=dict)
    has_automated_tests: bool = False
    test_frameworks: List[str] = field(default_factory=list)
    documentation_files: List[str] = field(default_factory=list)
    build_files: List[str] = field(default_factory=list)

    def get_xml_framed_evidence(
        self,
        relative_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """
        Formats an untrusted evidence snippet inside strict structural XML delimiters
        for safe prompt construction in Milestone 4.
        Escapes all repository-controlled text and attributes to prevent prompt injection.
        """
        safe_path = sanitize_xml_text(relative_path)
        indexed = self.files.get(relative_path)
        if not indexed:
            elem = ET.Element("UNTRUSTED_REPOSITORY_EVIDENCE", {
                "file": safe_path,
                "status": "FILE_NOT_FOUND",
            })
            return ET.tostring(elem, encoding="unicode")

        s_line = start_line or 1
        e_line = end_line or min(indexed.total_lines, 100)
        snippet = indexed.get_line_range_snippet(s_line, e_line, max_chars=2000)

        elem = ET.Element("UNTRUSTED_REPOSITORY_EVIDENCE", {
            "file": safe_path,
            "lines": f"{s_line}-{e_line}",
        })
        elem.text = f"\n{sanitize_xml_text(snippet)}\n"
        return ET.tostring(elem, encoding="unicode")


def is_binary_file(file_path: Path) -> bool:
    """Heuristic check: reads initial 1024 bytes to detect null bytes or non-text markers."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            if b"\0" in chunk:
                return True
            # Attempt UTF-8 decoding
            chunk.decode("utf-8", errors="replace")
            return False
    except Exception:
        return True


def index_extracted_repository(
    repository_root: Path,
    max_file_read_bytes: int = 1_048_576,  # 1 MB max text read per file
) -> EvidenceIndex:
    """
    Recursively scans an extracted repository directory, excludes secret/build directories,
    classifies files, counts lines of code, and constructs a sanitized EvidenceIndex.
    Guarantees ZERO code execution (strictly read-only static analysis).
    """
    index = EvidenceIndex()

    if not repository_root.exists() or not repository_root.is_dir():
        return index

    # If the repository root contains a single top-level directory (standard GitHub archive behavior),
    # unpack the view to that root directory.
    sub_entries = [p for p in repository_root.iterdir() if not p.name.startswith(".")]
    effective_root = repository_root
    if len(sub_entries) == 1 and sub_entries[0].is_dir():
        effective_root = sub_entries[0]

    for current_path in effective_root.rglob("*"):
        if not current_path.is_file():
            continue

        rel_path = current_path.relative_to(effective_root)

        # 1. Skip excluded directories and secret-bearing files
        if is_path_excluded(rel_path):
            continue

        # 2. Skip binary files (images, compiled binaries, archives)
        if is_binary_file(current_path):
            continue

        category = classify_file(rel_path)
        path_str = str(rel_path).replace("\\", "/")

        # 3. Read and index lines
        try:
            file_size = current_path.stat().st_size
            if file_size > max_file_read_bytes:
                # Truncate very large source files to first max_file_read_bytes
                with open(current_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(max_file_read_bytes)
            else:
                with open(current_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

            lines = content.splitlines()
            total_lines = len(lines)

            # Redact secrets from indexed lines
            redacted_lines = [redact_secrets_from_text(line) for line in lines]

            indexed_file = IndexedFile(
                relative_path=path_str,
                category=category,
                total_lines=total_lines,
                size_bytes=file_size,
                lines=redacted_lines,
            )
            index.files[path_str] = indexed_file

            # Accumulate statistics
            if category in (TaxonomyCategory.SOURCE_CODE, TaxonomyCategory.TEST_SUITES):
                index.total_lines_of_code += total_lines
                ext = rel_path.suffix.lstrip(".").lower() or "other"
                index.languages[ext] = index.languages.get(ext, 0) + total_lines

            if category == TaxonomyCategory.DOCUMENTATION:
                index.documentation_files.append(path_str)
            elif category == TaxonomyCategory.BUILD_CONFIG:
                index.build_files.append(path_str)
            elif category == TaxonomyCategory.TEST_SUITES:
                index.has_automated_tests = True

            # Detect test frameworks from build config or test files
            if "pytest" in content or "unittest" in content:
                if "pytest" not in index.test_frameworks:
                    index.test_frameworks.append("pytest")
            if "jest" in content:
                if "jest" not in index.test_frameworks:
                    index.test_frameworks.append("jest")
            if "cargo test" in content or (rel_path.name == "Cargo.toml" and "[dev-dependencies]" in content):
                if "cargo-test" not in index.test_frameworks:
                    index.test_frameworks.append("cargo-test")

        except Exception:
            # Skip unreadable or corrupted files without halting indexing
            continue

    return index
