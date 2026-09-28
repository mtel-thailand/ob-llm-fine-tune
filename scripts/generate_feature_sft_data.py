#!/usr/bin/env python3
"""Create source-grounded, feature-balanced SFT records without an LLM call."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


HEADERS = ("【Root Cause Analysis】", "【Step-by-Step Debugging Guide】", "【Production-Grade Fix】")


WEAK_SINGLE_TERMS = {"email", "iam", "workplace", "member", "pass", "token"}


def feature_matches(context: dict, feature_id: str, keywords: list[str]) -> list[str]:
    """Match the feature in the primary file only, with conservative rules.

    Related graph chunks may be useful for an explanation, but using their text
    to classify the primary source caused unrelated IAM files to enter the
    Notification slice simply because a related file mentioned ``email``.
    """
    primary = context.get("source_chunks", [{}])[0]
    # A file or repository name is not behavioral evidence. Match only the
    # primary source body, consistent with the source-grounding policy.
    evidence = primary.get("text", "").casefold()
    matches = [word for word in keywords if word.casefold() in evidence]
    strong = [word for word in matches if word.casefold() not in WEAK_SINGLE_TERMS]
    # Notification requires a notification-specific signal. Email alone is a
    # transport word, not evidence that a source implements the feature.
    if feature_id == "notification":
        return strong if any(word.casefold() in {"notification", "notify", "push", "fcm"} for word in strong) else []
    # Workplace role is only feature-specific when workplace occurs alongside
    # a role/permission/authorization signal in the same primary source.
    if feature_id == "workplace-role":
        has_workplace = "workplace" in matches
        has_access_term = any(word.casefold() in {"role", "permission", "authorization"} for word in matches)
        return matches if has_workplace and has_access_term else []
    # Authentication must have an authentication-specific term, never merely
    # the repository/service label "iam".
    if feature_id == "authentication":
        return matches if any(word.casefold() in {"authentication", "authenticate", "auth", "login", "jwt", "token"} for word in matches) else []
    # Amenity and visitor records require a direct feature term. A generic
    # workplace/member/pass occurrence alone is not sufficient.
    if feature_id == "amenity-booking":
        return matches if any(word.casefold() in {"amenity", "booking", "reservation", "retail"} for word in matches) else []
    if feature_id == "visitor-pass":
        return matches if any(word.casefold() in {"visitor", "visitor pass", "visitor-pass", "guest"} for word in matches) else []
    return strong


def cite(chunk: dict) -> str:
    return f"{chunk['repository']}/{chunk['path']}:{chunk['line_start']}-{chunk['line_end']}"


def found(pattern: str, text: str, fallback: str) -> str:
    values = re.findall(pattern, text)
    if values and isinstance(values[0], tuple):
        values = [" ".join(value for value in item if value) for item in values]
    return ", ".join(dict.fromkeys(values[:6])) if values else fallback


def source_facts(chunks: list[dict]) -> dict[str, object]:
    text = "\n".join(item.get("text", "") for item in chunks)
    return {
        "declarations": found(r"\b(?:class|function|interface|enum|const)\s+([A-Za-z_$][\w$]*)", text, "no named declaration was extracted"),
        "routes": found(r"@(Get|Post|Put|Patch|Delete)\s*\(\s*['\"]?([^'\")]+)?", text, "no route decorator was extracted"),
        "imports": found(r"from\s+['\"]([^'\"]+)['\"]", text, "no import path was extracted"),
        "awaits": found(r"await\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)", text, "no awaited call was extracted"),
        "errors": found(r"throw\s+new\s+([A-Za-z_$][\w$]*)", text, "no explicit thrown error class was extracted"),
        "events": found(r"EventProducer\.send\s*\(\s*\{\s*name:\s*['\"]([^'\"]+)", text, "no EventProducer event name was extracted"),
        "has_producer": "EventProducer.send" in text,
        "has_consumer": "EventConsumer" in text,
    }


def safe_excerpt(text: str) -> str:
    result = "\n".join(line for line in text.splitlines() if line.strip())[:650]
    if any("\u0e00" <= char <= "\u0e7f" for char in result):
        return "// Excerpt omitted because it contains a localized literal; use the cited source."
    return result or "// No non-empty source excerpt is available."


def graph_relationships(context: dict) -> str:
    """Render graph edges as static relationships, never as runtime behavior."""
    primary_ids = {item.get("id") for item in context.get("primary_nodes", [])}
    if context.get("primary_node", {}).get("id"):
        primary_ids.add(context["primary_node"]["id"])
    nodes = {item.get("id"): item for item in context.get("graph_nodes", [])}
    rendered: list[str] = []
    for edge in context.get("graph_edges", []):
        if edge.get("source") not in primary_ids and edge.get("target") not in primary_ids:
            continue
        source = nodes.get(edge.get("source"), {})
        target = nodes.get(edge.get("target"), {})
        source_label = source.get("label") or edge.get("source", "unknown")
        target_label = target.get("label") or edge.get("target", "unknown")
        relation = edge.get("relation", "related_to")
        rendered.append(f"{source_label} --[{relation}]--> {target_label}")
        if len(rendered) == 8:
            break
    return "; ".join(rendered) if rendered else "no primary graph edge is available in this context"


def notification_subscriptions(contexts: list[dict]) -> dict[str, str]:
    """Map event names to the exact Notification consumer source citation."""
    result: dict[str, str] = {}
    for context in contexts:
        for chunk in context.get("source_chunks", []):
            text = chunk.get("text", "")
            if chunk.get("repository") != "notification" or "EventConsumer.start" not in text:
                continue
            for event in re.findall(r"['\"](ob-[^'\"]+)['\"]", text):
                result[event] = cite(chunk)
    return result


def make_record(feature: dict, context: dict, index: int, subscriptions: dict[str, str]) -> dict:
    chunks = context["source_chunks"]
    primary = chunks[0]
    primary_citation = cite(primary)
    citations = ", ".join(cite(item) for item in chunks[:3])
    facts = source_facts(chunks)
    mode, technical = (
        ("overall implementation flow", False),
        ("component responsibility", False),
        ("request or handler flow", False),
        ("input, validation, and error-handling flow", False),
        ("dependency relationship", False),
        ("debugging and observability approach", False),
        ("cross-component event boundary", False),
        ("data and asynchronous-call flow", False),
        ("technical implementation", True),
        ("technical dependency trace", True),
    )[index % 10]
    # The supplementary data set deliberately uses different question intents
    # from the broad overview records, while retaining the same strict evidence
    # policy.  This gives the fine-tune corpus explicit Explain/Debug/Analyse
    # coverage instead of adding a byte-for-byte duplicate.
    focus = feature.get("_generation_focus")
    if focus == "explain-debug-analyse":
        mode, technical = (
            ("end-to-end code-backed flow", False),
            ("proven error, logging, and asynchronous boundaries", False),
            ("graph-backed component relationships", False),
            ("technical debugging path", True),
            ("implementation details", True),
        )[index % 5]
    if focus == "complex":
        mode, technical = (
            ("multi-component implementation flow", False),
            ("cross-service event boundary", False),
            ("failure-tracing path across related components", False),
            ("graph-backed architecture dependency analysis", True),
            ("asynchronous side-effect and implementation path", True),
        )[index % 5]
    matched = ", ".join(feature_matches(context, feature["id"], feature["keywords"]))
    excerpt = safe_excerpt(primary.get("text", ""))
    graph = graph_relationships(context)
    kafka = bool(facts["has_producer"] or facts["has_consumer"])
    matched_consumers = [f"{event} → {subscriptions[event]}" for event in str(facts["events"]).split(", ") if event in subscriptions]
    consumer_detail = (
        " Exact producer-to-Notification-consumer matches found in current source: " + "; ".join(matched_consumers) + "."
        if matched_consumers else
        " No matching Notification consumer event is asserted unless an exact event-name match is listed in the cited source."
    )
    if kafka:
        instruction = f"Trace the source-proven Kafka-related {mode} for {feature['title']}; distinguish concrete event code from any unproven downstream behavior."
        kafka_detail = (f"The cited code contains Kafka-related implementation: EventProducer.send present={facts['has_producer']}; "
                        f"EventConsumer present={facts['has_consumer']}; extracted producer event name={facts['events']}. "
                        "It does not prove a recipient service, delivery result, retry policy, topic configuration, or completed cross-service flow unless that behavior is directly shown here.")
        kafka_detail += consumer_detail
    else:
        if focus == "explain-debug-analyse":
            instruction = (
                f"{('Explain', 'Debug', 'Analyse', 'Debug', 'Explain')[index % 5]} the source-backed {mode} "
                f"for {feature['title']} in a practical, detailed way."
            )
        else:
            instruction = f"Explain the source-backed {mode} for {feature['title']} in a practical, detailed way."
        kafka_detail = "No Kafka producer or consumer implementation was extracted from this source context; no Kafka or cross-service flow is claimed."
    technical_evidence = f"\n\nShort Code Evidence:\n```ts\n{excerpt}\n```" if technical else ""
    technical_fix_evidence = f"\n\n```ts\n{excerpt}\n```" if technical else ""
    input_value = (
        f"Component/Service Name: {primary['repository']}\n\nFeature Selection Evidence: {matched}\n\n"
        f"Exact Source Location: {primary_citation}\n\n"
        "Exact Runtime Log or Stack Trace: No runtime log or stack trace is present in the supplied source context.\n\n"
        f"Actual Code Evidence: declarations: {facts['declarations']}; routes: {facts['routes']}; awaited calls: {facts['awaits']}; "
        f"explicit thrown errors: {facts['errors']}; imports: {facts['imports']}.\n\n"
        f"Graph Relationships (structural only, not runtime proof): {graph}.\n\n"
        f"Related Source Context: {citations}.{technical_evidence}"
    )
    output_value = (
        f"## {HEADERS[0]}\n\n"
        f"This explanation is limited to current source evidence, not a confirmed production incident. The supplied excerpts declare {facts['declarations']}, expose {facts['routes']}, "
        f"and contain awaited calls {facts['awaits']}. The graph supplies these static relationships: {graph}. "
        f"Graph edges are used only to locate related source; they do not prove runtime behavior. {kafka_detail} Evidence: {citations}.\n\n"
        f"## {HEADERS[1]}\n\n"
        f"1. Begin at `{primary_citation}` and identify the declaration or entry point: {facts['declarations']}.\n"
        f"2. Use the graph relationship list to choose related files, then verify each dependency in source: {graph}.\n"
        f"3. Trace only imports shown by the current source: {facts['imports']}.\n"
        f"4. Inspect the source-supported asynchronous calls: {facts['awaits']}.\n"
        f"5. Inspect explicit thrown errors: {facts['errors']}.\n"
        "6. If Kafka-related code is present, verify the producer or consumer call and its event name in the cited source; do not assume a downstream recipient.\n"
        "7. Collect an actual request, correlation identifier, and runtime log before diagnosing a production failure.\n\n"
        f"## {HEADERS[2]}\n\n"
        "No production fix is generated because the supplied source does not prove a defect. Use the cited current code to reproduce an observed failure before changing behavior."
        f"{technical_fix_evidence}\n\nSource: {primary_citation}."
    )
    return {"instruction": instruction, "input": input_value, "output": output_value}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate source-grounded SFT records for every configured feature")
    parser.add_argument("--contexts", default="data/graph-chunks.jsonl")
    parser.add_argument("--features", default="config/features.json")
    parser.add_argument("--output", default="data/sft_data.jsonl")
    parser.add_argument("--per-feature", type=int, default=1000)
    parser.add_argument("--append", action="store_true", help="Append the newly generated records to --output")
    parser.add_argument("--focus", choices=("overview", "explain-debug-analyse", "complex"), default="overview")
    args = parser.parse_args()
    if args.per_feature < 1:
        raise SystemExit("--per-feature must be positive")
    contexts = [json.loads(line) for line in Path(args.contexts).read_text(encoding="utf-8").splitlines() if line.strip()]
    features = json.loads(Path(args.features).read_text(encoding="utf-8")).get("features", [])
    if not isinstance(features, list) or not features:
        raise SystemExit("feature config requires a non-empty features array")
    subscriptions = notification_subscriptions(contexts)
    records, counts = [], {}
    for feature in features:
        feature = {**feature, "_generation_focus": args.focus}
        candidates = [context for context in contexts if feature_matches(context, feature["id"], feature["keywords"])]
        if args.focus == "complex":
            candidates = [context for context in candidates if len(context.get("source_chunks", [])) >= 2 and context.get("graph_edges")]
        if not candidates:
            raise SystemExit(f"no source-backed context matches feature: {feature['id']}")
        records.extend(make_record(feature, candidates[index % len(candidates)], index, subscriptions) for index in range(args.per_feature))
        counts[feature["id"]] = args.per_feature
    output = Path(args.output)
    prior = output.read_text(encoding="utf-8") if args.append and output.is_file() else ""
    output.write_text(prior + "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    print(json.dumps({"records_added": len(records), "per_feature": counts, "output": args.output, "append": args.append}, ensure_ascii=False))


if __name__ == "__main__":
    main()
