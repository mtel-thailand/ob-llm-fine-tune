#!/usr/bin/env python3
"""Create a balanced, evidence-only 100-record review queue without an LLM API.

This is deliberately a draft generator, not an automatic fine-tuning step. It
uses facts syntactically present in source/graph context and marks every record
for human review.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


CATEGORIES = ("api-flow", "architecture", "validation-access", "debug-error", "test-behavior", "technical-dependencies")


def classify(context: dict) -> set[str]:
    path = context["source"]["path"].lower()
    text = "\n".join(chunk.get("text", "") for chunk in context.get("source_chunks", [])).lower()
    kinds = set()
    if "controller" in path or re.search(r"@(get|post|put|delete|patch)\b", text): kinds.add("api-flow")
    if any(part in path for part in ("service", "repository", "module", "provider", "serializer")): kinds.add("architecture")
    if any(word in text for word in ("validate", "validator", "guard", "authoriz", "permission", "authentication")): kinds.add("validation-access")
    if any(word in text for word in ("throw ", "catch (", "error", "logger", "logging.")): kinds.add("debug-error")
    if any(word in path for word in (".spec.", ".test.", "__tests__", "e2e")): kinds.add("test-behavior")
    if len(context.get("source_chunks", [])) > 1 and any(part in path for part in ("controller", "service", "repository", "handler")):
        kinds.add("technical-dependencies")
    return kinds or {"architecture"}


def facts(context: dict) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str]]:
    text = "\n".join(chunk.get("text", "") for chunk in context.get("source_chunks", []))
    symbols = re.findall(r"\b(?:class|function|interface|enum|const)\s+([A-Za-z_$][\w$]*)", text)[:5]
    routes = [f"{method.upper()} {route or '/'}" for method, route in re.findall(r"@(Get|Post|Put|Delete|Patch)\s*\(\s*['\"]?([^'\")]+)?", text)[:4]]
    relations = [f"{edge['source']} --[{edge['relation']}]--> {edge['target']}" for edge in context.get("graph_edges", [])[:3]]
    imports = re.findall(r"from\s+['\"]([^'\"]+)['\"]", text)[:4]
    awaits = re.findall(r"await\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)", text)[:4]
    errors = re.findall(r"throw\s+new\s+([A-Za-z_$][\w$]*)", text)[:3]
    return symbols, routes, relations, imports, awaits, errors


def qa(context: dict, category: str) -> tuple[str, str]:
    source = context["source"]
    symbols, routes, relations, imports, awaits, errors = facts(context)
    citation = f"{source['repository']}/{source['path']}:{source['line_start']}-{source['line_end']}"
    unit = f"{source['path']} lines {source['line_start']}-{source['line_end']}"
    symbol_text = ", ".join(symbols) if symbols else "the declarations in the cited source"
    import_text = ", ".join(imports) if imports else "no import dependency was extracted"
    await_text = ", ".join(awaits) if awaits else "no awaited call was extracted"
    error_text = ", ".join(errors) if errors else "no explicit thrown error class was extracted"
    related = []
    for chunk in context.get("source_chunks", [])[1:4]:
        related.append(f"{chunk['repository']}/{chunk['path']}:{chunk['line_start']}-{chunk['line_end']}")
    related_text = ", ".join(related) if related else "ไม่มี related source ที่ยืนยันได้ใน context นี้"
    primary_text = context.get("source_chunks", [{}])[0].get("text", "")
    excerpt = "\n".join(line for line in primary_text.splitlines() if line.strip())[:500]
    if any("\u0e00" <= character <= "\u0e7f" for character in excerpt):
        excerpt = "// Excerpt omitted because this source contains a localized literal. See the citation below."
    if category == "api-flow":
        question = f"What request-processing flow is implemented in {unit}?"
        answer = f"The code-supported flow is: 1) a client calls {', '.join(routes) if routes else 'the handler declared in this source'}; 2) the handler receives and processes data through declarations such as {symbol_text}; 3) it performs awaited work such as {await_text}; 4) it uses dependencies including {import_text}; and 5) it returns a result or an error according to the implementation. A reviewer must confirm validation and state changes in the cited source before approval. Source: {citation}."
    elif category == "validation-access":
        question = f"What validation or access-control flow is implemented in {unit}?"
        answer = f"The code-supported flow is: 1) input enters declarations such as {symbol_text}; 2) dependencies such as {import_text} validate or look up related data; 3) the implementation continues through operations such as {await_text}; and 4) failed conditions can surface errors such as {error_text}. A reviewer must confirm the exact rule, account/member lookup, and response in the cited source before approval. Source: {citation}."
    elif category == "debug-error":
        question = f"How should a developer debug failures in {unit}?"
        answer = f"Start with the input reaching declarations such as {symbol_text}. Then inspect awaited work such as {await_text}, followed by the catch/throw path and error classes such as {error_text}. Finally, inspect dependencies including {import_text} and the returned response. This answer is limited to code evidence, so a reviewer must verify actual error codes and log fields before approval. Source: {citation}."
    elif category == "test-behavior":
        question = f"What behavior does {unit} cover, and how should its test flow be reviewed?"
        answer = f"Review the setup around declarations such as {symbol_text}, then inspect dependencies or mocks including {import_text}. Confirm the assertion, expected result, and edge case directly in the test code. This dataset does not extend behavior beyond what the test proves. Source: {citation}."
    elif category == "technical-dependencies":
        question = f"Which services, controllers, or modules are technically related to {unit}, and how does the call flow continue?"
        answer = f"The primary component is {source['repository']}/{source['path']}. Its code imports dependencies including {import_text} and continues through calls such as {await_text}. Related source context includes {related_text}. To trace the flow, begin at this controller or handler, follow the invoked service or repository, then inspect its imported types and interfaces. Short source excerpt:\n```ts\n{excerpt}\n```\nOnly components supported by source evidence are listed; no additional service is inferred. Source: {citation}."
    else:
        question = f"What responsibility does {unit} have, and which components does it work with?"
        answer = f"This component defines or uses {symbol_text}. The observed flow receives data or invokes this component, uses dependencies including {import_text}, and continues through operations such as {await_text}. A reviewer should verify the actual input, output, and side effects in the cited source because this answer does not infer behavior beyond code evidence. Source: {citation}."
    return question, answer


def evidence_context(context: dict, category: str) -> dict:
    """Use the chunk that proves the stated flow as the cited primary source."""
    for chunk in context.get("source_chunks", []):
        candidate = {"source": chunk, "source_chunks": [chunk]}
        if category in classify(candidate):
            source = {key: chunk[key] for key in ("repository", "path", "line_start", "line_end", "source_sha256")}
            source["lines"] = f"{source['line_start']}-{source['line_end']}"
            return {**context, "source": source, "source_chunks": [chunk]}
    return context


def main() -> None:
    parser = argparse.ArgumentParser(description="Create balanced offline Q&A review drafts from graph chunks")
    parser.add_argument("--contexts", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--total", type=int, default=100)
    args = parser.parse_args()
    if args.total < len(CATEGORIES): raise SystemExit("--total must be at least 5")
    contexts = [json.loads(line) for line in Path(args.contexts).read_text(encoding="utf-8").splitlines() if line.strip()]
    buckets: dict[str, list[dict]] = defaultdict(list)
    for context in contexts:
        for category in classify(context): buckets[category].append(context)
    target = args.total // len(CATEGORIES)
    selected: list[tuple[str, dict]] = []
    used: set[str] = set()
    for category in CATEGORIES:
        for context in buckets[category]:
            key = context["id"]
            if key not in used and sum(1 for current, _ in selected if current == category) < target:
                selected.append((category, context)); used.add(key)
    # Fill gaps from all contexts, retaining their strongest available category.
    for context in contexts:
        if len(selected) >= args.total: break
        if context["id"] in used: continue
        category = next(iter(sorted(classify(context))))
        selected.append((category, context)); used.add(context["id"])
    if len(selected) < args.total:
        raise SystemExit(f"only {len(selected)} unique contexts available; cannot create {args.total} records")
    records = []
    for number, (category, context) in enumerate(selected[:args.total], 1):
        context = evidence_context(context, category)
        question, answer = qa(context, category)
        records.append({"id": f"offline-review:{number:03d}:{context['id']}", "review_status": "needs_human_review",
            "dataset_category": category, "generated_by": {"provider": "offline-evidence-template", "mode": "no-api"},
            "source": context["source"], "graph_context": {key: context[key] for key in ("primary_node", "primary_nodes", "graph_nodes", "graph_edges") if key in context},
            "messages": [{"role": "system", "content": "You are Go-To-ChaoRai, an internal One Bangkok assistant. Answer only from verified source context, cite supplied sources, and do not guess."},
                         {"role": "user", "content": question}, {"role": "assistant", "content": answer}]})
    Path(args.output).write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    print(f"offline review drafts complete: {len(records)} records")


if __name__ == "__main__": main()
