#!/usr/bin/env python3
"""Create deterministic train/validation Chat JSONL files for MLX-LM."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare MLX-LM train.jsonl and valid.jsonl")
    parser.add_argument("--input", required=True, help="Chat Messages JSONL")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--valid-count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument(
        "--keep-direct-in-train",
        action="store_true",
        help="Keep short direct-question examples out of validation so every curated standalone example is trained",
    )
    args = parser.parse_args()
    rows = [json.loads(line) for line in Path(args.input).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) < 2 or not 1 <= args.valid_count < len(rows):
        raise SystemExit("valid-count must be between 1 and the number of records minus one")
    if any(not isinstance(row.get("messages"), list) for row in rows):
        raise SystemExit("input must contain Chat Messages JSONL records")
    rng = random.Random(args.seed)
    if args.keep_direct_in_train:
        direct, contextual = [], []
        for row in rows:
            user_messages = [m.get("content", "") for m in row["messages"] if m.get("role") == "user"]
            (direct if user_messages and "\n\n" not in user_messages[-1] else contextual).append(row)
        if args.valid_count >= len(contextual):
            raise SystemExit("valid-count must be smaller than the contextual record count")
        rng.shuffle(contextual)
        valid, train = contextual[:args.valid_count], contextual[args.valid_count:] + direct
        rng.shuffle(train)
    else:
        rng.shuffle(rows)
        valid, train = rows[:args.valid_count], rows[args.valid_count:]
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for name, records in (("train.jsonl", train), ("valid.jsonl", valid)):
        (output / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    print(json.dumps({"train": len(train), "valid": len(valid), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
