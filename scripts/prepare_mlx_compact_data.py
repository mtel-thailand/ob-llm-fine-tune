#!/usr/bin/env python3
"""Make compact, label-preserving Chat JSONL for MLX LoRA training."""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path


SYSTEM = "You are Go-To-ChaoRai. Answer only from supplied code evidence; do not invent behavior."


def extract(label: str, text: str, limit: int) -> str:
    match = re.search(re.escape(label) + r"\s*([^\n]+)", text)
    return match.group(1).strip()[:limit] if match else "not available"


def extract_first(labels: tuple[str, ...], text: str, limit: int) -> str:
    """Read the first available evidence label used by a curated dataset."""
    for label in labels:
        value = extract(label, text, limit)
        if value != "not available":
            return value
    return "not available"


def compact_answer(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:700]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create compact MLX Chat JSONL from source-grounded I/O records")
    parser.add_argument("--input", required=True, help="instruction/input/output JSONL")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--valid-count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260924)
    args = parser.parse_args()
    records = []
    for line in Path(args.input).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        context = row["input"]
        evidence = "\n".join((
            "Component: " + extract("Component/Service Name:", context, 100),
            "Source: " + extract("Exact Source Location:", context, 180),
            "Code facts: " + extract_first(
                ("Actual Code Evidence:", "Code-Proven Fact:", "Source-backed Fact:"), context, 420
            ),
            "Flow: " + extract_first(
                ("Expected Source Flow:", "Source-Backed Flow:"), context, 280
            ),
            "Graph: " + extract("Graph Relationships (structural only, not runtime proof):", context, 280),
        ))
        user = (row["instruction"].strip() + "\n\n" + evidence)[:700]
        answer = compact_answer(row["output"])
        if len(answer) < 40:
            continue
        records.append({"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": answer},
        ]})
    if len(records) < 2 or not 1 <= args.valid_count < len(records):
        raise SystemExit("not enough valid records")
    random.Random(args.seed).shuffle(records)
    valid, train = records[:args.valid_count], records[args.valid_count:]
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    for filename, group in (("train.jsonl", train), ("valid.jsonl", valid)):
        (output / filename).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in group), encoding="utf-8")
    print(json.dumps({"train": len(train), "valid": len(valid), "output": str(output)}))


if __name__ == "__main__":
    main()
