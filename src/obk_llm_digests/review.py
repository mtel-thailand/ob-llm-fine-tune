from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

VALID_STATUSES = {"needs_human_review", "approved", "rejected"}


def _load_jsonl(path: str | Path) -> list[dict]:
    records = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError as error:
            raise ValueError(f"line {number}: invalid JSON") from error
    return records


def _source_index(digest_dir: str | Path) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    chunks = Path(digest_dir) / "chunks.jsonl"
    for row in _load_jsonl(chunks):
        result.add((row["repository"], row["path"], row["source_sha256"]))
    return result


def _has_citation(answer: str, source: dict) -> bool:
    return source.get("path", "") in answer and ":" in answer


def review_report(reviewed: str | Path, digest_dir: str | Path) -> tuple[dict, bool]:
    """Return a report and whether all records are eligible for SFT review handling."""
    records = _load_jsonl(reviewed)
    sources = _source_index(digest_dir)
    errors: list[dict] = []
    warnings: list[dict] = []
    statuses: Counter[str] = Counter()
    repositories: Counter[str] = Counter()
    questions: dict[str, int] = {}
    for line, record in enumerate(records, 1):
        status = record.get("review_status")
        statuses[str(status)] += 1
        if status not in VALID_STATUSES:
            errors.append({"line": line, "reason": "invalid review_status"})
        source = record.get("source")
        if not isinstance(source, dict) or not all(source.get(key) for key in ("repository", "path", "source_sha256")):
            errors.append({"line": line, "reason": "missing source evidence"})
            source = {}
        else:
            repositories[source["repository"]] += 1
            if (source["repository"], source["path"], source["source_sha256"]) not in sources:
                errors.append({"line": line, "reason": "source hash is absent from current digest"})
        messages = record.get("messages")
        if not isinstance(messages, list):
            errors.append({"line": line, "reason": "messages must be an array"})
            continue
        by_role = {item.get("role"): item.get("content") for item in messages if isinstance(item, dict)}
        if not {"system", "user", "assistant"}.issubset(by_role):
            errors.append({"line": line, "reason": "system, user, and assistant messages are required"})
            continue
        if any(not isinstance(value, str) or not value.strip() for value in by_role.values()):
            errors.append({"line": line, "reason": "messages contain empty content"})
            continue
        normalized = re.sub(r"\s+", " ", by_role["user"].strip().lower())
        if normalized in questions:
            warnings.append({"line": line, "reason": f"duplicate user question; also line {questions[normalized]}"})
        else:
            questions[normalized] = line
        if not _has_citation(by_role["assistant"], source):
            warnings.append({"line": line, "reason": "answer has no visible source-path citation"})
        if status == "approved":
            for field in ("reviewer", "reviewed_at"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    errors.append({"line": line, "reason": f"approved record requires {field}"})
            try:
                datetime.fromisoformat(record["reviewed_at"].replace("Z", "+00:00"))
            except (KeyError, ValueError, AttributeError):
                errors.append({"line": line, "reason": "reviewed_at must be ISO-8601"})
            if by_role["assistant"].lstrip().lower().startswith("draft answer"):
                errors.append({"line": line, "reason": "approved answer still has draft marker"})
    report = {
        "records": len(records), "status_counts": dict(statuses), "repository_counts": dict(repositories),
        "errors": errors, "warnings": warnings,
    }
    return report, not errors


def write_review_report(reviewed: str | Path, digest_dir: str | Path, output: str | Path) -> tuple[dict, bool]:
    report, valid = review_report(reviewed, digest_dir)
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report, valid
