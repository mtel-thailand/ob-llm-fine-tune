#!/usr/bin/env python3
"""Combine review queues while retaining one strongest record per source evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def key(record: dict) -> tuple:
    source = record.get("source", {})
    return (source.get("repository"), source.get("path"), source.get("line_start"), source.get("line_end"), record.get("dataset_category"))


def score(record: dict) -> int:
    provider = record.get("generated_by", {}).get("provider")
    # Hand-authored Codex records are preferred over a template when both cite
    # the same source span and category.
    return 2 if provider == "codex-agent" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Combine and de-duplicate reviewed Q&A draft datasets")
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    selected: dict[tuple, dict] = {}
    read = 0
    for location in args.input:
        for line in Path(location).read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            record = json.loads(line); read += 1
            current = selected.get(key(record))
            # Inputs are ordered oldest to newest. At the same quality score,
            # retain the later record so regenerated wording replaces an older
            # template; never replace a stronger hand-authored Codex record.
            if current is None or score(record) >= score(current): selected[key(record)] = record
    records = list(selected.values())
    Path(args.output).write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    print(f"combined review dataset complete: {len(records)} unique records from {read} input records")


if __name__ == "__main__": main()
