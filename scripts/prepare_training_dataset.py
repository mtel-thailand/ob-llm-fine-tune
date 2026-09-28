#!/usr/bin/env python3
"""Create minimal approved-review and train-only JSONL from a reviewed queue."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove non-training metadata and approve a reviewed dataset")
    parser.add_argument("--input", required=True)
    parser.add_argument("--reviewed-output", required=True, help="Minimal records required by build-sft")
    parser.add_argument("--sft-output", required=True, help="Final train-only Chat Messages JSONL")
    parser.add_argument("--reviewer", default="dataset-owner")
    args = parser.parse_args()
    reviewed, sft = [], []
    timestamp = datetime.now(UTC).isoformat()
    for number, line in enumerate(Path(args.input).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        messages = record.get("messages")
        if not isinstance(messages, list) or not messages:
            raise SystemExit(f"input line {number}: messages missing")
        cleaned = []
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise SystemExit(f"input line {number}: invalid message")
            content = message["content"].strip()
            if message.get("role") == "assistant":
                content = content.removeprefix("Draft answer for human review: ").strip()
            cleaned.append({"role": message.get("role"), "content": content})
        approved = {"review_status": "approved", "reviewer": args.reviewer, "reviewed_at": timestamp, "messages": cleaned}
        reviewed.append(approved)
        sft.append({"messages": cleaned})
    if not reviewed:
        raise SystemExit("no records found")
    Path(args.reviewed_output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in reviewed), encoding="utf-8")
    Path(args.sft_output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in sft), encoding="utf-8")
    print(f"training dataset complete: {len(sft)} approved examples")


if __name__ == "__main__": main()
