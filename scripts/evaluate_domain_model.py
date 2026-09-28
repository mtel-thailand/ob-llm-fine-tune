#!/usr/bin/env python3
"""Run deterministic held-out classification checks against one MLX model."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from mlx_lm import generate, load
from mlx_lm.sample_utils import make_sampler


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def score(case: dict, answer: str) -> tuple[bool, list[str]]:
    lowered = answer.casefold()
    failures: list[str] = []
    if case["type"] == "binary":
        labels = re.findall(r"\b(?:true|false)\b", lowered)
        expected = case["expected"].casefold()
        if not labels or labels[0] != expected:
            failures.append(f"first binary label must be {case['expected']}")
    # A repository name anywhere in a prose answer is not a routing answer.
    # Require it in the declared Primary field, otherwise a model can receive a
    # false pass by saying e.g. "BMS owns this, Notification may be related".
    primary_match = re.search(
        r"(?:primary(?:\s+repository(?:/repositories)?)?|primary)\s*:\s*([^\n]+)", lowered
    )
    primary_text = primary_match.group(1) if primary_match else ""
    if case.get("expected_primary") and not primary_match:
        failures.append("missing explicit Primary repository field")
    for term in case.get("expected_primary", []):
        if term.casefold() not in primary_text:
            failures.append(f"missing primary repository: {term}")
    supporting_match = re.search(r"conditional supporting repositories\s*:\s*([^\n]+)", lowered)
    supporting_text = supporting_match.group(1) if supporting_match else ""
    for term in case.get("expected_supporting", []):
        if term.casefold() not in supporting_text:
            failures.append(f"missing supporting repository: {term}")
    for term in case.get("must_include", []):
        if term.casefold() not in lowered:
            failures.append(f"missing required term: {term}")
    for term in case.get("forbidden", []):
        if term.casefold() in lowered:
            failures.append(f"contains forbidden term: {term}")
    return not failures, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--eval", default="data/go-to-chaorai-v10-classification-eval.jsonl")
    parser.add_argument("--system", default="config/go-to-chaorai-system.txt")
    parser.add_argument("--output", default="data/go-to-chaorai-v10-classification-results.json")
    parser.add_argument("--max-tokens", type=int, default=450)
    args = parser.parse_args()

    cases = load_jsonl(Path(args.eval))
    if not cases:
        raise SystemExit("evaluation set is empty")
    system = Path(args.system).read_text(encoding="utf-8").strip()
    model, tokenizer = load(args.model)
    sampler = make_sampler(temp=0.0)
    results = []
    for index, case in enumerate(cases, 1):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": case["question"]},
        ]
        try:
            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
        except TypeError:
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        answer = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=args.max_tokens,
            sampler=sampler,
            verbose=False,
        )
        passed, failures = score(case, answer)
        results.append({
            "index": index,
            "type": case["type"],
            "question": case["question"],
            "passed": passed,
            "failures": failures,
            "answer": answer,
        })
        print(f"[{index}/{len(cases)}] {'PASS' if passed else 'FAIL'} {case['question']}")

    passed_count = sum(result["passed"] for result in results)
    report = {
        "model": args.model,
        "eval": args.eval,
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "accuracy": passed_count / len(results),
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("passed", "failed", "accuracy")}, ensure_ascii=False))
    if passed_count != len(results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
