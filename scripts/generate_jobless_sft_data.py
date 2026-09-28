#!/usr/bin/env python3
"""Generate strict source-grounded debugging data from current code only."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def values(pattern: str, text: str, fallback: str, limit: int = 6) -> str:
    found = re.findall(pattern, text)[:limit]
    if found and isinstance(found[0], tuple):
        found = [" ".join(part for part in item if part) for item in found]
    return ", ".join(found) if found else fallback


def excerpt(text: str) -> str:
    result = "\n".join(line for line in text.splitlines() if line.strip())[:700]
    if any("\u0e00" <= character <= "\u0e7f" for character in result):
        return "// Source excerpt omitted because it contains a localized literal. Use the cited source location."
    return result or "// No non-empty source excerpt is available."


def classify(path: str, text: str) -> str:
    lower = path.lower()
    if any(value in lower for value in (".spec.", ".test.", "__tests__", "e2e")): return "test behavior"
    if "throw " in text or "catch (" in text or "logging." in text or "logger." in text: return "error and logging behavior"
    if re.search(r"@(Get|Post|Put|Delete|Patch)\b", text): return "request handler flow"
    if any(value in lower for value in ("service", "repository", "handler", "consumer")): return "component dependency flow"
    return "component responsibility"


def make_record(context: dict) -> dict:
    source = context["source"]
    chunk = context.get("source_chunks", [{}])[0]
    text = chunk.get("text", "")
    location = f"{source['repository']}/{source['path']}:{source['line_start']}-{source['line_end']}"
    kind = classify(source["path"], text)
    declarations = values(r"\b(?:class|function|interface|enum|const)\s+([A-Za-z_$][\w$]*)", text, "no named declaration was extracted")
    routes = values(r"@(Get|Post|Put|Delete|Patch)\s*\(\s*['\"]?([^'\")]+)?", text, "no route decorator was extracted")
    imports = values(r"from\s+['\"]([^'\"]+)['\"]", text, "no import path was extracted")
    awaits = values(r"await\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)", text, "no awaited call was extracted")
    errors = values(r"throw\s+new\s+([A-Za-z_$][\w$]*)", text, "no explicit thrown error class was extracted")
    log_state = "logging calls are present" if re.search(r"\b(?:logging|logger|console)\.(?:info|warn|error|debug)\s*\(", text) else "no runtime logging call was extracted"
    related = [f"{item['repository']}/{item['path']}:{item['line_start']}-{item['line_end']}" for item in context.get("source_chunks", [])[1:3]]
    related_text = ", ".join(related) if related else "no related source chunk is available"
    code = excerpt(text)
    return {
        "instruction": f"Analyze the current {kind} in {source['repository']}/{source['path']} using only source-supported evidence.",
        "input": f"Component/Service Name: {source['repository']}\n\nCurrent Code Location: {location}\n\nExact Runtime Log or Stack Trace: No runtime log or stack trace is available in the current source context. Do not infer one.\n\nCurrent System Context: The source declares {declarations}. It exposes {routes}. It imports {imports}. Related current source context: {related_text}.\n\nCode Evidence:\n```ts\n{code}\n```",
        "output": f"## 【Root Cause Analysis】\n\nThe current source establishes {kind}, not a confirmed production incident. It contains declarations {declarations}; awaited operations: {awaits}; explicit errors: {errors}; and {log_state}. Because no runtime failure evidence is present, no additional root cause is asserted.\n\n## 【Step-by-Step Debugging Guide】\n\n1. Start at {location}.\n2. Trace the declared route or entry point: {routes}.\n3. Inspect dependencies imported from: {imports}.\n4. Verify awaited work: {awaits}.\n5. Inspect the existing error and logging behavior: {errors}; {log_state}.\n6. Collect a real production log, request identifier, and failing input before concluding the root cause.\n\n## 【Production-Grade Fix】\n\nNo code change is generated because the current source context does not prove a defect. Preserve the existing behavior, reproduce with real runtime evidence, and apply a fix only after the failing path is identified.\n\nCurrent source evidence:\n```ts\n{code}\n```\n\nSource: {location}."
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate source-grounded SFT JSONL from current graph chunks")
    parser.add_argument("--contexts", default="data/graph-chunks.jsonl")
    parser.add_argument("--output", default="data/sft_data.jsonl")
    parser.add_argument("--total", type=int, default=1000)
    args = parser.parse_args()
    contexts = [json.loads(line) for line in Path(args.contexts).read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.total < 1 or len(contexts) < args.total:
        raise SystemExit(f"requested {args.total} records but only {len(contexts)} current source contexts are available")
    records = [make_record(context) for context in contexts[:args.total]]
    Path(args.output).write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
    print(f"source-grounded SFT data complete: {len(records)} records")


if __name__ == "__main__": main()
