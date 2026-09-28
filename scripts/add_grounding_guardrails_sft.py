#!/usr/bin/env python3
"""Add explicit source-boundary examples for high-risk One Bangkok answers.

These records are regenerated, rather than accumulated, so a repeat pipeline
run is deterministic.  They are also deliberately marked as direct-answer
examples: a small model must learn to decline unsupported claims even when a
user asks without pasting source context.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


CASES = {
    "Visitor Pass": [
        ("the exact QR-code generator or attachment implementation", "the event-specific email template and the invitation web-view/QR source"),
        ("the physical turnstile scan request or access decision", "the FS scan/access API contract and the BMS callback or access-log source"),
        ("the Kafka topic configuration, retry count, or dead-letter policy", "the Kafka client configuration and consumer retry/dead-letter implementation"),
        ("the exact database schema or constraints for visitor-related tables", "the Prisma schema or database migration files"),
        ("that APP blocks the Visitor Pass screen for every non-member", "the screen navigation and authorization-guard source"),
        ("that an FS pre-registration always results in a usable QR code", "the FS response contract and QR retrieval/rendering code"),
        ("the exact email-provider delivery result for a visitor", "a runtime correlation identifier, Notification logs, and provider delivery records"),
        ("the cancellation behavior in FS after BMS marks a schedule deleted", "the cancellation integration path and FS response handling source"),
        ("the exact IAM API request executed during Visitor Pass submission", "the APP network/client source for the submission path and IAM request trace"),
        ("the physical visitor-entry status transition after scanning", "the access-control event consumer or BMS visitor/pass update source"),
    ],
    "Amenity Booking": [
        ("the exact mobile screen component that calls a booking endpoint", "the APP navigation and API-client source"),
        ("the exact CMS page permission or role guard", "the CMS page/server-side authorization source"),
        ("the Kafka topic configuration, retry count, or dead-letter policy", "the Kafka producer/consumer configuration and retry implementation"),
        ("that a Notification email was accepted or delivered to a mailbox", "a booking ID, event correlation identifier, Notification logs, and mail-provider result"),
        ("the QR rendering implementation or scan-validation request", "the booking-detail QR component and access/scan integration source"),
        ("the database migration or physical table schema behind Booking API", "the Prisma schema and migration files"),
        ("the scheduler cadence for service-point reset", "the scheduler/cron registration source"),
        ("the scheduler cadence for transaction-limit reset", "the scheduler/cron registration source"),
        ("that an API controller has an authentication guard", "the controller, global guard, gateway, or middleware source"),
        ("the payment workflow for a booking", "the payment integration source and its event/API contract"),
    ],
}

QUESTION_FORMS = (
    "Can you confirm {claim}?",
    "Explain exactly how the system implements {claim}.",
    "Which endpoint, table, and service guarantee {claim}?",
    "Debug a production issue involving {claim} using the supplied context.",
    "Provide a production code fix for {claim}.",
)


def signature(item: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def make_record(feature: str, claim: str, needed: str, form: str) -> dict[str, str]:
    # Include the feature in every prompt.  Apart from making the decision
    # unambiguous for a small model, this prevents same-worded evidence-gap
    # questions from colliding with records created by earlier curators.
    instruction = form.format(claim=f"{claim} for One Bangkok {feature}")
    input_value = (
        f"Component/Service Name: {feature}\n\n"
        "Scenario Type: Source-grounded evidence-boundary guardrail.\n\n"
        "Evidence Policy: Answer only from supplied repository/document context. "
        "The requested behavior is not directly established by the current cited source.\n\n"
        "Current Verified Context: The dataset contains source-backed flow and integration facts, "
        "but no direct implementation evidence for this requested claim."
    )
    output = (
        "## Evidence Decision\n\n"
        f"I cannot confirm {claim} from the supplied context. It would be speculation to invent an endpoint, "
        "database table, event payload, retry policy, code snippet, or runtime outcome.\n\n"
        "## What Is Known\n\n"
        "Use only the source-backed behavior already cited in the current question context. "
        "Do not extend a structural relationship into a completed runtime transaction.\n\n"
        "## Required Context Before Answering\n\n"
        f"Please provide {needed}. With that source, trace the exact identifiers and calls before proposing a fix."
    )
    return {"instruction": instruction, "input": input_value, "output": output}


def main() -> None:
    dataset = Path("data/sft_data.jsonl")
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    marker = "Scenario Type: Source-grounded evidence-boundary guardrail."
    retained = [row for row in rows if marker not in row.get("input", "")]
    known = {signature(row) for row in retained}
    additions = [
        make_record(feature, claim, needed, form)
        for feature, cases in CASES.items()
        for claim, needed in cases
        for form in QUESTION_FORMS
    ]
    known_instructions = {str(row.get("instruction", "")).strip() for row in retained}
    additions = [
        row for row in additions
        if signature(row) not in known and row["instruction"] not in known_instructions
    ]
    dataset.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in retained + additions),
        encoding="utf-8",
    )
    print(json.dumps({
        "removed_prior_grounding_guardrails": len(rows) - len(retained),
        "added_grounding_guardrails": len(additions),
        "total_records": len(retained) + len(additions),
    }))


if __name__ == "__main__":
    main()
