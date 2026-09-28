#!/usr/bin/env python3
"""Add high-signal standalone answers for terms with strong generic-model priors.

The records are intentionally source-backed and concise.  They teach a small
model the meaning of One Bangkok terms before it sees a long technical trace.
They replace prior records produced by this script on every run.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


VISITOR_SOURCE = (
    "mobile-app/app/OneBangkok/src/configs/Menu.tsx:521-640; "
    "mobile-app/app/OneBangkok/src/states/buildingAccess/visitorPass.ts:1-162; "
    "bms/src/controllers/visitors_controller.ts:1-145; "
    "bms/src/services/pass_service.ts:105-224; "
    "notification/src/handlers/bms/visitor_handler.ts:1-65"
)
SYNC_SOURCE = (
    "bms/src/controllers/integrations/fs/members_controller.ts:1-201; "
    "bms/src/events/bms/sync_member_records_handler.ts:1-48; "
    "bms/src/services/member_service.ts:313-640"
)

VISITOR_QUESTIONS = (
    "What is the One Bangkok Visitor Pass feature?",
    "What does Visitor Pass do in One Bangkok?",
    "Explain One Bangkok Visitor Pass in plain English.",
    "Explain the One Bangkok Visitor Pass business flow.",
    "Is One Bangkok Visitor Pass a tourist attraction pass?",
    "Does One Bangkok Visitor Pass provide hotel, restaurant, transport, or attraction discounts?",
    "Who can create a Visitor Pass in One Bangkok?",
    "What happens after a Workplace member creates a Visitor Pass?",
    "What does APP do before Visitor Pass creation?",
    "What does BMS own in the Visitor Pass flow?",
    "Why is FS involved in the One Bangkok Visitor Pass flow?",
    "What happens after FS returns an invitation identifier for a Visitor Pass?",
    "Why does Notification receive a Visitor Pass event?",
    "Explain the APP to BMS flow for creating a One Bangkok Visitor Pass.",
    "What can be concluded from the One Bangkok Visitor Pass source, and what cannot?",
    "Give a short, non-technical explanation of One Bangkok Visitor Pass.",
)

SYNC_QUESTIONS = (
    "What is Sync Member in the One Bangkok Workplace context?",
    "Is One Bangkok Sync Member a loyalty or membership-program flow?",
    "Explain the One Bangkok Sync Member flow in plain English.",
    "What does BMS do when it receives an FS member batch?",
    "What Kafka event is used for the BMS Sync Member handoff?",
    "What information does MemberService synchronize for an active FS member?",
    "Does accepting an FS member batch prove that synchronization has completed?",
    "What happens when an FS member becomes inactive in the One Bangkok sync flow?",
)


def visitor_answer(question: str) -> str:
    lower = question.casefold()
    core = (
        "One Bangkok Visitor Pass is an internal workplace visitor-invitation feature. "
        "An eligible Workplace member can invite a visitor for a scheduled visit. It is not a tourism pass, "
        "attraction ticket, hotel package, transport pass, or discount program."
    )
    if "who can create" in lower or "before visitor pass" in lower:
        body = (
            "APP obtains the current BMS Workplace member context and checks `can_preregister`. "
            "When that capability is not available, the APP should not continue to the creation journey. " + core
        )
    elif "bms own" in lower:
        body = (
            "BMS owns visitor and visitor-schedule creation, pass processing, FS pre-registration, "
            "the confirmed pass state after an FS invitation identifier is returned, and publication of the "
            "Visitor Pass created event. " + core
        )
    elif "why is fs" in lower or "after fs" in lower:
        body = (
            "BMS sends the visit to FS pre-registration. When FS returns an invitation identifier, BMS stores it "
            "as the pass UID and marks the pass confirmed. " + core
        )
    elif "notification" in lower:
        body = (
            "After the pass-processing path, BMS publishes `ob-bms.visitor_pass.created`. Notification registers "
            "that event and invokes its visitor-email path using the event data. " + core
        )
    elif "app to bms" in lower or "after a workplace member" in lower or "business flow" in lower:
        body = (
            "APP uses the current BMS member as the inviter and submits visitor and schedule data. BMS creates the "
            "visitor, schedule, and pass records, performs FS pre-registration, confirms the pass after the FS response, "
            "then publishes an event for Notification's visitor-email path. " + core
        )
    elif "what can be concluded" in lower:
        body = (
            "The cited source supports the APP permission gate, BMS visitor/schedule/pass processing, FS pre-registration, "
            "Kafka event publication, and Notification's email handoff. It does not by itself prove QR rendering, an email "
            "attachment, mailbox delivery, a physical scan, or turnstile admission. " + core
        )
    else:
        body = (
            "APP checks the current member's visitor-invitation capability. BMS creates the visitor, schedule, and pass, "
            "calls FS pre-registration, marks the pass confirmed after the FS invitation response, then publishes an event "
            "for Notification's visitor-email path. " + core
        )
    return f"## Answer\n\n{body}\n\nSource: {VISITOR_SOURCE}."


def sync_answer(question: str) -> str:
    lower = question.casefold()
    core = (
        "One Bangkok Sync Member is an FS-to-BMS workplace-identity synchronization flow. "
        "It is not a generic loyalty or customer membership-program journey."
    )
    if "inactive" in lower:
        body = (
            "For an inactive FS record, BMS clears the member account link and related metadata, deletes tenant-member "
            "and authorized-location relationships in a transaction, emits its offboard boundary event, and clears cache. " + core
        )
    elif "kafka event" in lower:
        body = (
            "The FS integration controller publishes `ob-bms.sync-member-records`. The registered BMS handler validates "
            "the event and calls `MemberService.sync`. " + core
        )
    elif "what information" in lower:
        body = (
            "For an active FS record, BMS synchronizes the member by personID/uid, resolves default location or floor, "
            "synchronizes tenant memberships and authorized locations, removes obsolete tenant relationships, emits a member event, "
            "and clears relevant caches. " + core
        )
    elif "prove" in lower:
        body = (
            "No. HTTP acceptance only establishes that BMS accepted the batch. Synchronization happens asynchronously after "
            "the `ob-bms.sync-member-records` handoff, so jobId, traceId, consumer validation, and MemberService outcome must be checked. " + core
        )
    else:
        body = (
            "FS sends a member batch to the BMS integration endpoint. BMS assigns jobId/traceId, deduplicates or keeps the latest "
            "records, publishes `ob-bms.sync-member-records`, and its handler invokes `MemberService.sync`. " + core
        )
    return f"## Answer\n\n{body}\n\nSource: {SYNC_SOURCE}."


def record(feature: str, question: str, answer: str, source: str) -> dict[str, str]:
    return {
        "instruction": question,
        "input": (
            f"Component/Service Name: {feature}\n\n"
            "Scenario Type: Direct One Bangkok domain anchor.\n\n"
            "Evidence Policy: Use only the stated One Bangkok source-backed behavior. "
            "Do not substitute a generic industry meaning for this feature.\n\n"
            f"Exact Source Location: {source}"
        ),
        "output": answer,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/sft_data.jsonl")
    args = parser.parse_args()
    path = Path(args.dataset)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    retained = [row for row in rows if "Scenario Type: Direct One Bangkok domain anchor." not in row.get("input", "")]
    anchors = [
        *(record("Visitor Pass", question, visitor_answer(question), VISITOR_SOURCE) for question in VISITOR_QUESTIONS),
        *(record("Workplace Sync Member", question, sync_answer(question), SYNC_SOURCE) for question in SYNC_QUESTIONS),
    ]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in retained + anchors), encoding="utf-8")
    print(json.dumps({"removed_prior_anchors": len(rows) - len(retained), "added_anchors": len(anchors), "total_records": len(retained) + len(anchors)}))


if __name__ == "__main__":
    main()
