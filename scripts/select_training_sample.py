#!/usr/bin/env python3
"""Select a diverse, source-grounded 1k training subset from SFT records."""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


FEATURES = (
    "Amenity Booking (Retail and Workplace)", "Visitor Pass",
    "Workplace Role Management", "Authentication", "Notification",
)


def location(row: dict) -> str:
    match = re.search(r"Exact Source Location: ([^\n]+)", row["input"])
    return match.group(1) if match else "unknown"


def category(row: dict) -> str:
    text = row["instruction"].casefold()
    if any(word in text for word in ("multi-component", "cross-service", "failure-tracing", "architecture dependency", "asynchronous side-effect")):
        return "complex"
    if "debug" in text:
        return "debug"
    if "analyse" in text or "analysis" in text:
        return "analyse"
    if "technical" in text:
        return "technical"
    return "explain"


def select(rows: list[dict], count: int) -> list[dict]:
    """Pick by intent then round-robin source location, avoiding duplicate Q&A."""
    targets = {"complex": 80, "debug": 40, "analyse": 40, "technical": 20, "explain": 20}
    selected, seen, location_count = [], set(), defaultdict(int)

    def add_from(pool: list[dict], limit: int) -> None:
        nonlocal selected
        candidates = [row for row in pool if (row["instruction"], location(row)) not in seen]
        while candidates and limit and len(selected) < count:
            candidates.sort(key=lambda row: (location_count[location(row)], location(row), row["instruction"]))
            row = candidates.pop(0)
            signature = (row["instruction"], location(row))
            if signature in seen:
                continue
            selected.append(row)
            seen.add(signature)
            location_count[location(row)] += 1
            limit -= 1

    for intent, target in targets.items():
        add_from([row for row in rows if category(row) == intent], target)
    add_from(rows, count - len(selected))
    if len(selected) != count:
        raise ValueError(f"needed {count} records but selected {len(selected)}")
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description="Select a balanced complex SFT sample")
    parser.add_argument("--input", default="data/sft_data.jsonl")
    parser.add_argument("--output", default="data/sft_data_sample_1000.jsonl")
    parser.add_argument("--per-feature", type=int, default=200)
    args = parser.parse_args()
    rows = [json.loads(line) for line in Path(args.input).read_text(encoding="utf-8").splitlines() if line.strip()]
    output, report = [], {}
    for feature in FEATURES:
        group = [row for row in rows if feature in row.get("instruction", "")]
        picked = select(group, args.per_feature)
        output.extend(picked)
        report[feature] = {
            "records": len(picked),
            "source_locations": len({location(row) for row in picked}),
            "intents": {name: sum(category(row) == name for row in picked) for name in ("complex", "debug", "analyse", "technical", "explain")},
        }
    Path(args.output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8")
    print(json.dumps({"records": len(output), "report": report, "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
