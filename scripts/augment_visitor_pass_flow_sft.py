#!/usr/bin/env python3
"""Add curated, code-backed Visitor Pass flow records to an SFT JSONL file."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SOURCES = (
    "mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-224; "
    "mobile-app/app/OneBangkok/src/states/buildingAccess/visitorPass.ts:1-162; "
    "bms/src/controllers/visitors_controller.ts:1-145; "
    "bms/src/services/visitor_service.ts:1-188; "
    "bms/src/services/pass_service.ts:105-224; "
    "bms/src/libs/fs_client.ts:105-214; "
    "notification/src/server.ts:1-74; "
    "notification/src/handlers/bms/visitor_handler.ts:1-65; "
    "notification/src/services/message_service.ts:937-1056"
)

BUSINESS_INPUT = (
    "Component/Service Name: APP (React Native), BMS (Node.js), FS integration, "
    "and Notification (Node.js)\n\n"
    "Scenario Type: Source-backed functional-flow explanation; this is not a confirmed production incident.\n\n"
    "Verified Source Evidence: APP loads BMS member context with membersIndex and sends "
    "visitorsCreate with inviter_id, visitor data, and visitor_schedule. BMS creates visitor, "
    "schedule and pass records, calls FS invitePreRegister, stores the returned invite identifier, "
    "and emits ob-bms.visitor_pass.created. Notification consumes that event and calls sendEmailToVisitor.\n\n"
    "Evidence Boundary: The supplied source does not directly prove QR rendering/attachment or a successful "
    "turnstile scan."
)

TECHNICAL_INPUT = (
    "Component/Service Name: APP (React Native), IAM identity boundary, BMS, FS integration, Kafka, "
    "and Notification\n\n"
    "Scenario Type: Source-backed technical architecture trace; this is not a confirmed production incident.\n\n"
    "Exact Source Locations: " + SOURCES + ".\n\n"
    "Actual Code Evidence: APP uses memberState.id as inviter_id and calls visitorsCreate. "
    "BMS connects the inviter member, creates visitor_schedule and pass rows, maps visitor/schedule/inviter "
    "data into FS invitePreRegister, stores inviteID as the pass uid with confirmed status, and emits "
    "ob-bms.visitor_pass.created. Notification registers the exact event and calls MessageService.sendEmailToVisitor.\n\n"
    "Exact Runtime Log or Stack Trace: No runtime log or stack trace is present in the supplied source context."
)

RECORDS = [
    {
        "instruction": "Explain the Visitor Pass flow from opening the APP feature until the visitor email is requested. Clearly separate proven behavior from behavior that needs more source context.",
        "input": BUSINESS_INPUT,
        "output": """## Overview

The proven flow starts when APP loads the signed-in user's BMS member context. APP calls membersIndex() and retains the BMS member id, uid, tenant-related information, and access-related state. APP later uses the member id as the inviter identity.

The user fills in visitor details such as name, email, company/reference, tower, floor, and visit time. On submit, APP calls BMS visitorsCreate with these values and a visitor_schedule.

BMS creates a visitor connected to the inviter member, creates its schedule, creates one or more pass rows, and sends a pre-registration request to FS. When FS returns an invite identifier, BMS stores it on the pass and marks the pass confirmed. BMS then emits ob-bms.visitor_pass.created; Notification consumes that event and requests an email to the visitor.

## What is not yet proven

The reviewed sources prove an email request with an invitation link and tower data. They do not prove that the email contains a QR code, where QR code rendering happens, or that a turnstile scan grants entry. Those claims need the email template, web-view/QR source, and FS access-result or callback source.

Source: """ + SOURCES,
    },
    {
        "instruction": "Explain why a Workplace Member is required before APP can create a Visitor Pass.",
        "input": BUSINESS_INPUT,
        "output": """## Explanation

APP first reads a member through membersIndex() and uses memberState.id as inviter_id in the visitor creation request. BMS VisitorService.create connects the new visitor to that inviter member. Without a resolved member record, APP has no source-backed inviter identifier for this API contract.

BMS supports member lookup through account identity information and uses member.uid in FS-related member operations. This supports the business relationship between the signed-in identity, BMS member record, and building-domain identity.

The sources do not prove that every UI route is blocked when no member exists. They prove that the Visitor Pass submission payload requires an inviter member identifier.

Source: mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-224; mobile-app/app/OneBangkok/src/states/buildingAccess/visitorPass.ts:105-162; bms/src/services/visitor_service.ts:1-188.""",
    },
    {
        "instruction": "Trace the technical Visitor Pass request and event flow across APP, BMS, FS, Kafka, and Notification. Distinguish verified calls from assumptions.",
        "input": TECHNICAL_INPUT,
        "output": """## 【Root Cause Analysis】

This is an architecture trace, not a confirmed failure. APP sets the BMS SDK access token from its authentication state, obtains member context, then sends visitorsCreate. The payload uses memberState.id as inviter_id and includes visitor_schedule. BMS creates visitor/schedule/pass rows, then PassService calls FS invitePreRegister. After FS returns inviteID, BMS updates the pass UID and status to confirmed, then publishes ob-bms.visitor_pass.created. Notification registers that exact event and its visitor handler calls MessageService.sendEmailToVisitor.

IAM is an identity/authentication boundary: BMS can resolve members by account identity and APP uses an authenticated token for BMS access. The extracted submission code does not prove an additional IAM REST call during Visitor Pass submission.

## 【Step-by-Step Debugging Guide】

1. Verify APP has resolved memberState.id before createPass.
2. Inspect the BMS visitorsCreate request for visitor data, inviter_id, and schedule values.
3. Verify BMS created visitor, schedule, and pass rows.
4. Trace the FS pre-registration request and capture the returned invite identifier without logging credentials.
5. Verify the pass update contains the FS identifier and confirmed status.
6. Search BMS publish logs and Notification consumer/handler logs with a correlation identifier.
7. Inspect the email template/web view separately when investigating QR content.

## 【Production-Grade Fix】

No production defect is proven by the supplied source. Preserve the asynchronous boundary and add correlation-safe observability rather than making APP call Notification directly.

Source: """ + SOURCES,
    },
    {
        "instruction": "Debug why a Visitor Pass may exist in BMS but no visitor email is received, using only the source-backed service boundaries.",
        "input": TECHNICAL_INPUT,
        "output": """## 【Root Cause Analysis】

The code contains independent boundaries after BMS persistence: BMS-to-FS pre-registration and BMS-to-Notification event handling. A visitor or schedule can exist before all downstream work succeeds. The reviewed code proves BMS emits ob-bms.visitor_pass.created after pass processing, and Notification maps that exact event to visitorPassCreated, which requests sendEmailToVisitor. It does not prove Kafka delivery, consumer success, template availability, or mail-provider acceptance for a specific request.

## 【Step-by-Step Debugging Guide】

1. Confirm visitor, schedule, and pass records exist in BMS.
2. Confirm the pass contains an FS invite identifier and confirmed status.
3. Search BMS logs for ob-bms.visitor_pass.created.
4. Search Notification consumer and visitor-handler logs for the same correlation identifier.
5. Verify visitor_email exists in the event payload.
6. Verify template loading and the mail-provider result.
7. Do not diagnose a QR issue until QR/template source is available.

## 【Production-Grade Fix】

No production defect is proven. Add non-sensitive correlation identifiers at publish and consumption boundaries.

Source: """ + SOURCES,
    },
    {
        "instruction": "Explain the technical evidence boundary for QR code and turnstile behavior in the current Visitor Pass source.",
        "input": TECHNICAL_INPUT,
        "output": """## 【Root Cause Analysis】

The reviewed code proves BMS invokes FS pre-registration and stores the returned invite identifier on a pass. It also proves Notification requests an event-specific email and loads an HTML template. This is insufficient evidence to claim that a QR code is generated, embedded, attached, scanned at a turnstile, or accepted by a physical-access system.

A BMS member operation calls FS to check member presence in a tower, but it is not proof of a visitor turnstile transaction.

## 【Step-by-Step Debugging Guide】

1. Inspect the event-specific email template for QR placeholders or assets.
2. Inspect the invitation-link web view for QR rendering code.
3. Inspect the FS integration for invitation retrieval and scan/access callbacks.
4. Inspect BMS pass/access-log paths for a callback or polling mechanism.

## 【Production-Grade Fix】

No change is generated because QR and physical-access source is not included. Do not add speculative QR behavior until the responsible contract is verified.

Source: bms/src/services/pass_service.ts:105-224; bms/src/libs/fs_client.ts:105-214; notification/src/services/message_service.ts:937-1056.""",
    },
]


def signature(item: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/sft_data.jsonl")
    args = parser.parse_args()
    output = Path(args.output)
    existing: set[str] = set()
    if output.exists():
        for line_no, line in enumerate(output.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    existing.add(signature(json.loads(line)))
                except json.JSONDecodeError as error:
                    raise SystemExit(f"Invalid JSONL at {output}:{line_no}: {error}") from error
    additions = [item for item in RECORDS if signature(item) not in existing]
    with output.open("a", encoding="utf-8") as stream:
        for item in additions:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"visitor-pass flow augmentation complete: {len(additions)} added, {len(RECORDS) - len(additions)} already present")


if __name__ == "__main__":
    main()
