from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_EXTENSIONS = {
    ".c", ".cc", ".cs", ".cpp", ".css", ".csv", ".dart", ".go", ".h", ".hpp",
    ".html", ".java", ".jl", ".js", ".json", ".jsx", ".kt", ".kts", ".md", ".mjs",
    ".php", ".py", ".rb", ".rs", ".scala", ".sh", ".sql", ".swift", ".toml", ".ts",
    ".tsx", ".vue", ".xml", ".yaml", ".yml", ".zig",
}


@dataclass(frozen=True)
class Repository:
    label: str
    path: Path
    framework: str | None = None
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settings:
    repositories: tuple[Repository, ...]
    chunk_lines: int = 120
    chunk_overlap_lines: int = 16
    max_file_bytes: int = 1_048_576
    allow_unknown_text: bool = False
    text_extensions: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_file(cls, location: str | Path) -> "Settings":
        config_path = Path(location).resolve()
        data = json.loads(config_path.read_text(encoding="utf-8"))
        repositories = []
        labels: set[str] = set()
        for item in data.get("repositories", []):
            label = item["label"]
            if label in labels:
                raise ValueError(f"duplicate repository label: {label}")
            labels.add(label)
            path = Path(item["path"])
            if not path.is_absolute():
                path = (config_path.parent / path).resolve()
            repositories.append(Repository(
                label=label, path=path, framework=item.get("framework"),
                include=tuple(item.get("include", [])), exclude=tuple(item.get("exclude", [])),
            ))
        if not repositories:
            raise ValueError("config must contain at least one repository")
        chunk_lines = int(data.get("chunk_lines", 120))
        overlap = int(data.get("chunk_overlap_lines", 16))
        if chunk_lines < 1 or overlap < 0 or overlap >= chunk_lines:
            raise ValueError("chunk_lines must be positive and overlap must be smaller")
        extensions = {str(value).lower() for value in data.get("text_extensions", [])}
        if any(not value.startswith(".") for value in extensions):
            raise ValueError("text_extensions must begin with a dot")
        return cls(
            repositories=tuple(repositories), chunk_lines=chunk_lines,
            chunk_overlap_lines=overlap, max_file_bytes=int(data.get("max_file_bytes", 1_048_576)),
            allow_unknown_text=bool(data.get("allow_unknown_text", False)),
            text_extensions=frozenset(extensions),
        )
