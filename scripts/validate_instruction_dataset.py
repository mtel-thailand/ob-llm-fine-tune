#!/usr/bin/env python3
"""Validate the canonical instruction dataset and record its source snapshot.

This gate deliberately does not promote generated graph/digest candidates into
training data. New source contexts remain review material until a human has
verified the answer; the canonical SFT dataset is only checked and fingerprinted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


REQUIRED_FIELDS = {"instruction", "input", "output"}
FEATURE_TERMS = {
    "amenity-booking": ("amenity", "booking"),
    "visitor-pass": ("visitor pass", "visitor_pass", "visitor-pass"),
    "workplace": ("workplace", "tenant member", "sync member"),
    "authentication": ("authentication", "login", "jwt", "refresh token", "external identity"),
    "notification": ("notification", "fcm", "email", "message service"),
}
KNOWN_GENERIC_HALLUCINATIONS = (
    "skip the check-in and check-out process",
    "enjoy a hotel room without the hotel",
    "explore the city without a hotel",
    "membership or loyalty program",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: record must be an object")
            records.append(value)
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--graph-chunks", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    dataset = Path(args.dataset)
    digest_dir = Path(args.digest)
    graph_chunks = Path(args.graph_chunks)
    output = Path(args.output)
    errors: list[str] = []
    warnings: list[str] = []

    rows = load_jsonl(dataset)
    if not rows:
        errors.append("dataset is empty")

    normalized_questions: dict[str, int] = {}
    coverage: Counter[str] = Counter()
    source_citations = 0
    for number, row in enumerate(rows, 1):
        if set(row) != REQUIRED_FIELDS:
            errors.append(f"line {number}: fields must be exactly instruction, input, output")
            continue
        if any(not isinstance(row[field], str) or not row[field].strip() for field in REQUIRED_FIELDS):
            errors.append(f"line {number}: instruction, input, and output must be non-empty strings")
            continue
        question = re.sub(r"\s+", " ", row["instruction"].strip().casefold())
        if question in normalized_questions:
            errors.append(f"line {number}: duplicate instruction (first seen at line {normalized_questions[question]})")
        else:
            normalized_questions[question] = number
        combined = "\n".join((row["instruction"], row["input"], row["output"])).casefold()
        for feature, terms in FEATURE_TERMS.items():
            if any(term in combined for term in terms):
                coverage[feature] += 1
        if "source:" in row["output"].casefold() or "exact source location:" in row["input"].casefold():
            source_citations += 1
        for phrase in KNOWN_GENERIC_HALLUCINATIONS:
            if phrase in combined:
                errors.append(f"line {number}: contains known generic hallucination phrase: {phrase}")

    for feature in FEATURE_TERMS:
        if coverage[feature] < 5:
            errors.append(f"feature coverage too low for {feature}: {coverage[feature]} records")

    chunks_file = digest_dir / "chunks.jsonl"
    manifest_file = digest_dir / "manifest.json"
    if not chunks_file.is_file() or not chunks_file.stat().st_size:
        errors.append("digest chunks.jsonl is missing or empty")
        digest_manifest: dict = {}
    elif not manifest_file.is_file():
        errors.append("digest manifest.json is missing")
        digest_manifest = {}
    else:
        digest_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

    graph_count = 0
    if graph_chunks.is_file():
        with graph_chunks.open(encoding="utf-8") as stream:
            graph_count = sum(1 for line in stream if line.strip())
    if graph_count == 0:
        errors.append("graph-chunks output is missing or empty")

    citation_ratio = source_citations / len(rows) if rows else 0.0
    if citation_ratio < 0.8:
        warnings.append(f"only {citation_ratio:.1%} of records contain a visible source marker")

    report = {
        "dataset": str(dataset),
        "dataset_sha256": sha256(dataset),
        "records": len(rows),
        "unique_instructions": len(normalized_questions),
        "source_citation_records": source_citations,
        "feature_coverage": dict(coverage),
        "digest": {
            "chunks": digest_manifest.get("chunks", 0),
            "sources": digest_manifest.get("sources", 0),
            "reused_files": digest_manifest.get("reused_files", 0),
            "manifest_sha256": sha256(manifest_file) if manifest_file.is_file() else None,
        },
        "graph_chunks": graph_count,
        "errors": errors,
        "warnings": warnings,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
