from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .config import Settings
from .scanner import Exclusion, SourceFile, scan

VERSION = "1"


def _chunks(source: SourceFile, size: int, overlap: int) -> Iterator[dict]:
    lines = source.content.splitlines()
    if not lines:
        return
    step = size - overlap
    for start in range(0, len(lines), step):
        end = min(start + size, len(lines))
        yield {
            "id": f"{source.repository.label}:{source.relative_path}:{start + 1}-{end}",
            "repository": source.repository.label, "framework": source.repository.framework,
            "path": source.relative_path, "language": source.language, "git_commit": source.commit,
            "line_start": start + 1, "line_end": end, "source_sha256": source.sha256,
            "text": "\n".join(lines[start:end]),
        }
        if end == len(lines):
            break


def _candidate(chunk: dict) -> dict:
    path = chunk["path"].lower()
    category = "architecture"
    if any(word in path for word in ("test", "spec", "feature")):
        category = "test-behavior"
    elif any(word in path for word in ("controller", "route", "endpoint", "api")):
        category = "api-flow"
    elif any(word in path for word in ("dto", "validator", "guard", "validation")):
        category = "validation"
    elif any(word in path for word in ("error", "exception", "logger", "debug")):
        category = "debug"
    return {"id": chunk["id"], "category": category, "review_required": True,
            "source": {key: chunk[key] for key in ("repository", "path", "line_start", "line_end", "source_sha256")},
            "question_template": f"Explain the {category} role of {chunk['path']} using only the cited source context.",
            "answer": None}


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def _load_previous(output: Path) -> tuple[dict[str, str], dict[str, list[dict]]]:
    manifest_path, chunks_path = output / "manifest.json", output / "chunks.jsonl"
    if not manifest_path.is_file() or not chunks_path.is_file():
        return {}, {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chunks: dict[str, list[dict]] = {}
        for line in chunks_path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
                chunks.setdefault(f"{entry['repository']}:{entry['path']}", []).append(entry)
            except (ValueError, KeyError):
                # A malformed legacy record is regenerated from source on this run.
                continue
        return manifest.get("files", {}), chunks
    except (OSError, ValueError, KeyError):
        return {}, {}


def build(settings: Settings, output: str | Path) -> dict:
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)
    previous_files, previous_chunks = _load_previous(output_path)
    sources, exclusions = scan(settings)
    records: list[dict] = []
    files: dict[str, str] = {}
    reused = 0
    for source in sources:
        key = f"{source.repository.label}:{source.relative_path}"
        files[key] = source.sha256
        if previous_files.get(key) == source.sha256 and key in previous_chunks:
            records.extend(previous_chunks[key])
            reused += 1
        else:
            records.extend(_chunks(source, settings.chunk_lines, settings.chunk_overlap_lines))
    records.sort(key=lambda item: item["id"])
    _write_jsonl(output_path / "chunks.jsonl", records)
    _write_jsonl(output_path / "review-candidates.jsonl", [_candidate(record) for record in records])
    security = [{"repository": item.repository, "path": item.path, "reason": item.reason} for item in exclusions]
    (output_path / "security-report.json").write_text(json.dumps(security, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {"version": VERSION, "generated_at": datetime.now(UTC).isoformat(), "files": files,
                "sources": len(sources), "chunks": len(records), "reused_files": reused}
    (output_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest_parts = ["# LLM-Friendly Code Digest\n"]
    for record in records:
        digest_parts.extend([f"<source repository=\"{record['repository']}\" path=\"{record['path']}\" language=\"{record['language']}\" lines=\"{record['line_start']}-{record['line_end']}\">\n",
                             "```\n", record["text"], "\n```\n</source>\n\n"])
    (output_path / "digest.md").write_text("".join(digest_parts), encoding="utf-8")
    return manifest


def validate_output(output: str | Path) -> None:
    chunks = Path(output) / "chunks.jsonl"
    if not chunks.is_file() or not chunks.read_text(encoding="utf-8").strip():
        raise ValueError("output has no chunks.jsonl records")


def build_sft(reviewed: str | Path, output: str | Path) -> int:
    accepted: list[dict] = []
    for number, line in enumerate(Path(reviewed).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            messages = record["messages"]
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"reviewed line {number}: invalid JSONL messages record") from error
        roles = {message.get("role") for message in messages if isinstance(message, dict)}
        if not {"system", "user", "assistant"}.issubset(roles):
            raise ValueError(f"reviewed line {number}: system, user, and assistant roles are required")
        if any(not isinstance(message.get("content"), str) or not message["content"].strip() for message in messages):
            raise ValueError(f"reviewed line {number}: every message needs non-empty content")
        if record.get("review_status") != "approved":
            raise ValueError(f"reviewed line {number}: review_status must be approved")
        if not isinstance(record.get("reviewer"), str) or not record["reviewer"].strip():
            raise ValueError(f"reviewed line {number}: approved record requires reviewer")
        if not isinstance(record.get("reviewed_at"), str) or not record["reviewed_at"].strip():
            raise ValueError(f"reviewed line {number}: approved record requires reviewed_at")
        accepted.append({"messages": messages})
    if not accepted:
        raise ValueError("reviewed dataset has no accepted records")
    _write_jsonl(Path(output), accepted)
    return len(accepted)
