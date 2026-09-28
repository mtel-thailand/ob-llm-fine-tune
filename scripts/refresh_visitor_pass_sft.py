#!/usr/bin/env python3
"""Replace generic Visitor Pass SFT records with source-backed flow records."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from augment_visitor_pass_flow_sft import RECORDS, SOURCES


FACTS = [
    (
        "member context",
        "APP calls membersIndex to obtain the current BMS member context. APP uses memberState.id as inviter_id when it creates a visitor.",
        "mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-224; mobile-app/app/OneBangkok/src/states/buildingAccess/visitorPass.ts:105-162",
    ),
    (
        "submission payload",
        "APP submits visitor name, email, company/reference, inviter_id, and a visitor_schedule containing time, tower, floor, and repetition through visitorsCreate.",
        "mobile-app/app/OneBangkok/src/states/buildingAccess/visitorPass.ts:1-162",
    ),
    (
        "BMS persistence",
        "BMS VisitorService creates a visitor connected to the inviter member and creates visitor_schedule data. The controller then invokes PassService for the schedule.",
        "bms/src/controllers/visitors_controller.ts:1-145; bms/src/services/visitor_service.ts:1-188",
    ),
    (
        "pass creation",
        "PassService creates one or more pass rows. A repeated schedule can produce multiple pass records rather than a single pass.",
        "bms/src/services/pass_service.ts:105-224",
    ),
    (
        "FS mapping",
        "BMS maps schedule.id, visitor.name, inviter tenant, schedule location UID, and visitor.inviter.uid into the FS pre-registration request.",
        "bms/src/services/pass_service.ts:105-224; bms/src/libs/fs_client.ts:105-214",
    ),
    (
        "FS response",
        "After FS invitePreRegister returns an invite identifier, BMS stores it as the pass UID and sets the pass status to confirmed.",
        "bms/src/services/pass_service.ts:105-224",
    ),
    (
        "Kafka boundary",
        "BMS publishes ob-bms.visitor_pass.created after the pass-processing path. The event payload includes visitor_email, invitation_link, tower_name, and account_id.",
        "bms/src/services/pass_service.ts:105-224; notification/src/utils/kafka/event_registry.ts:105-224",
    ),
    (
        "Notification handling",
        "Notification registers ob-bms.visitor_pass.created, routes it to the BMS visitor handler, and calls MessageService.sendEmailToVisitor.",
        "notification/src/server.ts:1-74; notification/src/handlers/handler_registry.ts:1-93; notification/src/handlers/bms/visitor_handler.ts:1-65",
    ),
    (
        "email boundary",
        "MessageService loads an event-specific HTML email template and sends it to visitor_email. The reviewed handler does not itself prove QR generation or attachment.",
        "notification/src/services/message_service.ts:937-1056",
    ),
    (
        "cancellation and lookup",
        "APP can update a visitor schedule with deleted_at and can retrieve visitor-token/pass information through BMS endpoints. This is separate from the creation path.",
        "mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:105-224; bms/src/controllers/visitor_tokens_controller.ts:1-58; bms/src/controllers/visitor_schedules_controller.ts:1-29",
    ),
]

NORMAL_INTENTS = (
    "Explain the business flow for",
    "Explain the responsibility of each service for",
    "Describe what a developer should expect during",
    "Explain the data relationship involved in",
    "Explain the boundary and limitation of",
)
TECHNICAL_INTENTS = (
    "Trace the source-backed technical implementation of",
    "Analyse how to debug",
    "Explain the code-level integration boundary for",
    "Describe the technical evidence required to validate",
    "Analyse failure isolation for",
)
NORMAL_AUDIENCES = (
    "a product owner validating the feature",
    "a mobile developer following the user journey",
    "a QA engineer preparing end-to-end coverage",
    "an operations engineer checking service ownership",
    "a developer reviewing an integration change",
    "a support engineer explaining expected system behavior",
)
TECHNICAL_AREAS = (
    "request payload and identifiers",
    "database state transition",
    "FS integration boundary",
    "Kafka publication and consumption",
    "email delivery handoff",
    "cross-service failure isolation",
    "source-evidence limitations",
    "safe production observability",
)


def is_old_visitor_record(item: dict[str, object]) -> bool:
    # Only remove the earlier generic generator output. Curated records added
    # by this script intentionally also mention Visitor Pass, so broad text
    # matching would remove them again on every run.
    input_value = str(item.get("input", "")).casefold()
    instruction = str(item.get("instruction", "")).casefold()
    return "feature selection evidence:" in input_value and " for visitor pass" in instruction


def is_curated_visitor_record(item: dict[str, object]) -> bool:
    """Identify this script's prior Visitor Pass output, not other feature data."""
    instruction = str(item.get("instruction", "")).casefold()
    input_value = str(item.get("input", "")).casefold()
    return "visitor pass" in instruction and (
        "source-backed functional explanation" in input_value
        or "source-backed technical architecture trace" in input_value
        or "evidence rule: do not infer qr" in input_value
        or "graph relationship rule: a source relationship" in input_value
    )


def signature(item: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def make_normal(focus: str, evidence: str, source: str, intent: str, audience: str) -> dict[str, str]:
    return {
        "instruction": f"{intent} the Visitor Pass {focus} for {audience}, using only the current codebase.",
        "input": (
            "Component/Service Name: APP, BMS, FS integration, and Notification\n\n"
            "Scenario Type: Source-backed functional explanation. No production error is supplied.\n\n"
            f"Actual Code Evidence: {evidence}\n\n"
            "Evidence Rule: Do not infer QR generation, email attachment behavior, Kafka delivery, "
            "or turnstile entry unless directly established by cited source.\n\n"
            f"Exact Source Location: {source}"
        ),
        "output": (
            "## Explanation\n\n"
            f"{evidence}\n\n"
            "In the end-to-end flow, APP submits the request to BMS. BMS owns visitor, schedule, "
            "and pass processing, then uses FS for pre-registration. Notification is reached through "
            "the BMS Kafka event, not through a direct APP-to-Notification request.\n\n"
            f"This answer is aimed at {audience}. Only claim the part relevant to this question. If the question concerns QR code display "
            "or physical turnstile access, request the email-template, QR/web-view, or FS callback source.\n\n"
            f"Source: {source}."
        ),
    }


def make_technical(focus: str, evidence: str, source: str, intent: str, area: str) -> dict[str, str]:
    return {
        "instruction": f"{intent} the Visitor Pass {focus}, focusing on {area}; distinguish code-proven behavior from unproven runtime behavior.",
        "input": (
            "Component/Service Name: APP (React Native), IAM identity boundary, BMS, FS, Kafka, and Notification\n\n"
            "Exact Runtime Log or Stack Trace: No runtime log or stack trace is present in the supplied source context.\n\n"
            f"Actual Code Evidence: {evidence}\n\n"
            "Graph Relationship Rule: A source relationship is structural evidence, not proof of a completed runtime transaction.\n\n"
            f"Exact Source Location: {source}"
        ),
        "output": (
            "## 【Root Cause Analysis】\n\n"
            f"This is source analysis, not a confirmed incident. {evidence} "
            f"The primary diagnostic area is {area}. The APP-to-BMS request, BMS-to-FS integration, and BMS-to-Notification event boundary "
            "must be checked independently. IAM provides the authenticated identity boundary, but the "
            "reviewed submit path does not prove an additional IAM REST request after submission.\n\n"
            "## 【Step-by-Step Debugging Guide】\n\n"
            "1. Start at the cited source and identify the identifier or payload used at this boundary.\n"
            "2. Trace the corresponding BMS visitor, schedule, and pass state where applicable.\n"
            "3. For FS behavior, compare the BMS request mapping with the FS response identifier.\n"
            "4. For email behavior, verify BMS event publication, Notification consumption, template loading, and provider result separately.\n"
            "5. Do not conclude QR or turnstile behavior without its responsible source and an actual runtime correlation identifier.\n\n"
            "## 【Production-Grade Fix】\n\n"
            "No defect is proven by the source alone. Preserve service boundaries and add non-sensitive "
            "correlation-safe logs around the current request, FS, and event transitions before changing behavior.\n\n"
            f"Source: {source}."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/sft_data.jsonl")
    parser.add_argument("--count", type=int, default=600, help="Total curated Visitor Pass records to keep")
    args = parser.parse_args()
    if args.count < len(RECORDS):
        raise SystemExit(f"--count must be at least {len(RECORDS)}")

    path = Path(args.dataset)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    retained = [row for row in rows if not is_old_visitor_record(row) and not is_curated_visitor_record(row)]
    replacement = list(RECORDS)
    for index in range(args.count - len(RECORDS)):
        # One normal and one technical question form a pair. Deriving each
        # dimension from the pair index avoids repeatedly emitting the same
        # question wording while keeping every answer tied to a named source fact.
        pair = index // 2
        focus, evidence, source = FACTS[pair % len(FACTS)]
        intent_index = (pair // len(FACTS))
        if index % 2:
            replacement.append(make_technical(
                focus,
                evidence,
                source,
                TECHNICAL_INTENTS[intent_index % len(TECHNICAL_INTENTS)],
                TECHNICAL_AREAS[(intent_index // len(TECHNICAL_INTENTS)) % len(TECHNICAL_AREAS)],
            ))
        else:
            replacement.append(make_normal(
                focus,
                evidence,
                source,
                NORMAL_INTENTS[intent_index % len(NORMAL_INTENTS)],
                NORMAL_AUDIENCES[(intent_index // len(NORMAL_INTENTS)) % len(NORMAL_AUDIENCES)],
            ))

    existing = {signature(row) for row in retained}
    additions = [row for row in replacement if signature(row) not in existing]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in retained + additions),
        encoding="utf-8",
    )
    print(json.dumps({
        "removed_generic_visitor_records": len(rows) - len(retained),
        "added_source_backed_visitor_records": len(additions),
        "total_records": len(retained) + len(additions),
    }))


if __name__ == "__main__":
    main()
