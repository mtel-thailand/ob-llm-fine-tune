from __future__ import annotations

import fnmatch
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_EXTENSIONS, Repository, Settings


DEFAULT_EXCLUDES = (
    ".git/**", ".next/**", ".venv/**", "bin/**", "build/**", "coverage/**", "dist/**",
    "node_modules/**", "obj/**", "Pods/**", "target/**", "vendor/**",
    "**/.git/**", "**/.next/**", "**/.venv/**", "**/.expo/**", "**/.gradle/**",
    "**/bin/**", "**/build/**", "**/coverage/**", "**/dist/**", "**/DerivedData/**",
    "**/node_modules/**", "**/obj/**", "**/Pods/**", "**/target/**", "**/vendor/**",
    "**/generated/**", "**/__generated__/**", "**/*.generated.*", "**/*.lock",
    "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml", "**/*.min.js", "**/*.map",
)
SENSITIVE_NAME = re.compile(r"(^|/)(\.env[^/]*|id_rsa|credentials[^/]*|.*\.(pem|key|p12|pfx))$", re.I)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*[\"'][^\"'\s]{8,}"),
)
LANGUAGES = {".cs": "csharp", ".ts": "typescript", ".tsx": "typescript-react", ".js": "javascript",
             ".jsx": "javascript-react", ".py": "python", ".go": "go", ".java": "java", ".kt": "kotlin",
             ".swift": "swift", ".rb": "ruby", ".rs": "rust", ".php": "php", ".sql": "sql", ".md": "markdown"}


@dataclass(frozen=True)
class SourceFile:
    repository: Repository
    path: Path
    relative_path: str
    content: str
    sha256: str
    language: str
    commit: str | None


@dataclass(frozen=True)
class Exclusion:
    repository: str
    path: str
    reason: str


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch("/" + path, pattern) for pattern in patterns)


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _is_text(payload: bytes) -> bool:
    if b"\0" in payload:
        return False
    try:
        payload.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def scan(settings: Settings) -> tuple[list[SourceFile], list[Exclusion]]:
    sources: list[SourceFile] = []
    excluded: list[Exclusion] = []
    for repository in settings.repositories:
        if not repository.path.is_dir():
            raise FileNotFoundError(f"repository path does not exist: {repository.path}")
        commit = _git_commit(repository.path)
        for file_path in sorted(path for path in repository.path.rglob("*") if path.is_file()):
            relative = file_path.relative_to(repository.path).as_posix()
            if any(ord(character) < 32 for character in relative):
                excluded.append(Exclusion(repository.label, "<unsafe-path>", "control character in filename"))
                continue
            if _matches(relative, DEFAULT_EXCLUDES + repository.exclude):
                continue
            if SENSITIVE_NAME.search(relative):
                excluded.append(Exclusion(repository.label, relative, "sensitive filename"))
                continue
            if repository.include and not _matches(relative, repository.include):
                continue
            if file_path.stat().st_size > settings.max_file_bytes:
                excluded.append(Exclusion(repository.label, relative, "file exceeds max_file_bytes"))
                continue
            payload = file_path.read_bytes()
            extension = file_path.suffix.lower()
            known_extension = extension in DEFAULT_EXTENSIONS or extension in settings.text_extensions
            if not known_extension and not settings.allow_unknown_text:
                continue
            if not _is_text(payload):
                excluded.append(Exclusion(repository.label, relative, "binary or non-UTF-8 file"))
                continue
            content = payload.decode("utf-8")
            if any(pattern.search(content) for pattern in SECRET_PATTERNS):
                excluded.append(Exclusion(repository.label, relative, "possible secret in content"))
                continue
            sources.append(SourceFile(repository, file_path, relative, content,
                                      hashlib.sha256(payload).hexdigest(), LANGUAGES.get(extension, extension.lstrip(".") or "text"), commit))
    return sources, excluded
