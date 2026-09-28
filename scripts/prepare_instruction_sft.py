#!/usr/bin/env python3
"""Convert strict instruction/input/output JSONL into train-only chat messages."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


SYSTEM = (
    "You are Go-To-ChaoRai, the internal One Bangkok engineering and product assistant. "
    "Answer only questions about the One Bangkok platform. If a question is outside One Bangkok, "
    "refuse briefly and ask for a relevant feature, service, source path, or runtime error. "
    "When source context is supplied, answer only from that context. When no source context is supplied, "
    "use only reviewed One Bangkok domain knowledge and say when more source context is required. "
    "Never replace a One Bangkok feature with a generic meaning from another industry. "
    "Treat graph relationships as static code relationships, not proof of runtime behavior, and do not invent incidents."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert instruction SFT records to Chat Messages JSONL")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--add-direct-curated",
        action="store_true",
        help="Also train curated feature/scope records with the short instruction alone for standalone questions",
    )
    parser.add_argument(
        "--direct-repeat",
        type=int,
        default=1,
        help="How many direct copies to add for each curated/classification record (minimum 1)",
    )
    parser.add_argument(
        "--anchor-repeat",
        type=int,
        default=1,
        help="How many direct copies to add for high-priority domain-anchor records (minimum 1)",
    )
    args = parser.parse_args()
    if args.direct_repeat < 1 or args.anchor_repeat < 1:
        raise SystemExit("--direct-repeat and --anchor-repeat must be at least 1")
    converted = []
    for number, line in enumerate(Path(args.input).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            instruction, context, answer = row["instruction"].strip(), row["input"].strip(), row["output"].strip()
        except (ValueError, KeyError, AttributeError) as error:
            raise SystemExit(f"input line {number}: expected non-empty instruction, input, output strings") from error
        messages = {"messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": instruction + "\n\n" + context},
            {"role": "assistant", "content": answer},
        ]}
        converted.append(messages)
        anchor = "Scenario Type: Direct One Bangkok domain anchor." in context
        direct = (
            "Scenario Type: Curated One Bangkok feature overview." in context
            or "Scope policy: One Bangkok-only assistant" in context
            or anchor
            or "Scenario Type: Source-grounded repository classification." in context
            or "Scenario Type: Source-grounded binary classification." in context
            or "Scenario Type: Source-grounded evidence-boundary guardrail." in context
        )
        if args.add_direct_curated and direct:
            repetitions = args.anchor_repeat if anchor else args.direct_repeat
            for _ in range(repetitions):
                converted.append({"messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": instruction},
                    {"role": "assistant", "content": answer},
                ]})
    if not converted:
        raise SystemExit("input has no records")
    Path(args.output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in converted), encoding="utf-8")
    print(f"chat SFT dataset complete: {len(converted)} records")


if __name__ == "__main__":
    main()
