#!/usr/bin/env python3
"""Add source-backed repository-routing and binary-decision SFT records.

Training records and held-out evaluation prompts use different wording so the
eval measures generalisation rather than exact-question memorisation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROUTES = (
    {
        "feature": "Visitor Pass",
        "primary": "mobile-app, bms, notification",
        "supporting": "iam for authentication/account-to-member identity context; FS is an external integration, not a configured repository",
        "reason": "Read mobile-app for the permission gate and submission payload, bms for visitor/schedule/pass persistence plus FS pre-registration and event publication, and notification for the visitor-email handler.",
        "source": "mobile-app/app/OneBangkok/src/states/buildingAccess/visitorPass.ts:1-162; bms/src/controllers/visitors_controller.ts:1-145; bms/src/services/pass_service.ts:105-224; notification/src/handlers/bms/visitor_handler.ts:1-65",
    },
    {
        "feature": "Amenity Booking",
        "primary": "booking-api",
        "supporting": "mobile-app for the user journey, cms for back-office operations, bms for Workplace booker context, notification for downstream messages, and iam for permission propagation",
        "reason": "Start in booking-api for booking/resource policy and lifecycle ownership, then follow only the client, identity, Workplace-context, CMS, or Notification boundary relevant to the reported stage.",
        "source": "booking-api/apps/booking-api/src/modules/booking/booking.controller.ts:38-136; booking-api/apps/booking-api/src/modules/booking/booking.service.ts:1-560; booking-api/apps/booking-api/src/handlers/iam/iam_handler.ts:1-27; notification/src/handlers/booking/amenity_booking_handler.ts:1-240",
    },
    {
        "feature": "Authentication",
        "primary": "iam",
        "supporting": "mobile-app for client token/session handling, notification for IAM-event recipient/device projections, and bms when external identity links an account to a Workplace member",
        "reason": "IAM owns login strategies, account checks, token issuance and validation. Read another repository only for its proven client or event-consumer boundary.",
        "source": "iam/src/controllers/auth_controller.ts:1-170; iam/src/services/auth_service/index.ts:1-760; notification/src/handlers/iam/index.ts:1-120; bms/src/events/iam/external_identity_created_handler.ts:1-120",
    },
    {
        "feature": "Workplace Role and Member Access",
        "primary": "bms, mobile-app",
        "supporting": "iam for account/external identity, cms for proven back-office role operations, and notification for member/event messages",
        "reason": "BMS owns Workplace member, tenant and authorized-location state; mobile-app consumes the resulting member scope and gates Workplace journeys.",
        "source": "mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-337; bms/src/controllers/members_controller.ts:1-251; bms/src/services/authorized_location_service.ts:1-422",
    },
    {
        "feature": "Notification",
        "primary": "notification",
        "supporting": "iam, bms and booking-api as source-backed event producers; mobile-app only where a retrieved source proves client display or device-token behavior",
        "reason": "Notification owns recipient projections, templates, channel settings and provider adapters. Producer repositories explain why an event was emitted, not whether delivery completed.",
        "source": "notification/src/services/message_service.ts:555-1264; notification/src/utils/kafka/event_registry.ts:1-240; notification/src/utils/notification_adapter.ts:1-160",
    },
    {
        "feature": "Sync Member",
        "primary": "bms",
        "supporting": "iam for account/external-identity linkage and notification for the source-backed sync-report handler",
        "reason": "BMS accepts FS member batches, publishes ob-bms.sync-member-records, consumes the event and synchronizes member, tenant and authorization state.",
        "source": "bms/src/controllers/integrations/fs/members_controller.ts:1-201; bms/src/events/bms/sync_member_records_handler.ts:1-48; bms/src/services/member_service.ts:313-640",
    },
)

ROUTE_FORMS = (
    "Which repositories should I inspect for the One Bangkok {feature} feature?",
    "Classify repository ownership and supporting repositories for {feature}.",
    "A {feature} issue is reported. Which repository should be checked first, and which repositories are conditional follow-ups?",
)

BINARY_FACTS = (
    ("Visitor Pass", "One Bangkok Visitor Pass is a tourism or attraction-discount pass.", False, "It is a Workplace visitor-invitation feature, not a tourism product.", ROUTES[0]["source"]),
    ("Visitor Pass", "APP checks the Workplace member's can_preregister capability before continuing to Visitor Pass creation.", True, "The cited APP flow contains this capability gate.", ROUTES[0]["source"]),
    ("Visitor Pass", "The supplied Visitor Pass submission source proves that APP calls an IAM REST endpoint during every submission.", False, "IAM is an identity boundary, but the cited submission path does not prove an extra IAM REST call.", ROUTES[0]["source"]),
    ("Visitor Pass", "BMS owns visitor, schedule and pass processing in the cited Visitor Pass flow.", True, "The BMS controller/services create and process those records.", ROUTES[0]["source"]),
    ("Visitor Pass", "After FS returns an invitation identifier, BMS stores the pass UID and marks the pass confirmed.", True, "This state transition is present in the cited PassService flow.", ROUTES[0]["source"]),
    ("Visitor Pass", "Publishing ob-bms.visitor_pass.created proves the visitor received an email.", False, "Publication, consumption, provider acceptance and mailbox delivery are separate boundaries.", ROUTES[0]["source"]),
    ("Visitor Pass", "The cited Visitor Pass handler proves QR attachment and turnstile admission.", False, "Those outcomes require their own source and runtime evidence.", ROUTES[0]["source"]),
    ("Amenity Booking", "booking-api is the primary repository for Amenity Booking lifecycle and resource-policy behavior.", True, "Booking API owns the cited booking and resource lifecycle.", ROUTES[1]["source"]),
    ("Amenity Booking", "BMS is the system of record for every Amenity Booking.", False, "BMS can supply Workplace context, while booking-api owns the cited booking records and lifecycle.", ROUTES[1]["source"]),
    ("Amenity Booking", "A booking-status event by itself proves Notification delivered a message.", False, "Event publication is not proof of downstream processing or provider delivery.", ROUTES[1]["source"]),
    ("Amenity Booking", "Every One Bangkok Amenity Booking necessarily includes a payment workflow.", False, "The supplied source does not establish payment as a universal booking requirement.", ROUTES[1]["source"]),
    ("Authentication", "IAM is the primary repository for One Bangkok login and token lifecycle behavior.", True, "IAM owns the cited authentication controller and AuthService behavior.", ROUTES[2]["source"]),
    ("Authentication", "Every IAM login uses the password strategy.", False, "The source includes multiple strategies such as SSO, API key, token and password.", ROUTES[2]["source"]),
    ("Authentication", "Successful IAM authentication proves the account has a linked BMS Workplace member.", False, "Authentication success and Workplace enrollment are separate states.", ROUTES[2]["source"]),
    ("Authentication", "The inspected renew path proves refresh-token rotation on every use.", False, "The reviewed path does not issue a replacement refresh token or revoke the used refresh token.", ROUTES[2]["source"]),
    ("Workplace", "A Workplace member's effective building/location access must not exceed the Tenant's authorized scope.", True, "The cited BMS read path applies the tenant ceiling and member-specific authorized locations.", ROUTES[3]["source"]),
    ("Workplace", "An APP menu gate is sufficient proof of server-side authorization.", False, "Client gating cannot replace BMS authorization at the API boundary.", ROUTES[3]["source"]),
    ("Sync Member", "HTTP acceptance of an FS member batch proves MemberService synchronization completed.", False, "The synchronization continues asynchronously through Kafka and its handler.", ROUTES[5]["source"]),
    ("Sync Member", "Sync Member is a loyalty-program membership flow.", False, "It synchronizes FS Workplace identity and access state into BMS.", ROUTES[5]["source"]),
    ("Sync Member", "BMS uses ob-bms.sync-member-records in the cited asynchronous member-sync handoff.", True, "The integration controller publishes it and the registered handler calls MemberService.sync.", ROUTES[5]["source"]),
    ("Notification", "notification is the primary repository for templates, recipient projections, channel settings and provider adapters.", True, "Those responsibilities are implemented in the Notification service.", ROUTES[4]["source"]),
    ("Notification", "A recipient having an FCM token guarantees that push delivery succeeds.", False, "Settings, token eligibility, adapter/provider processing and provider outcome remain separate checks.", ROUTES[4]["source"]),
    ("Notification", "Logging a complete FCM token is required to debug Notification delivery.", False, "Use redacted fingerprints and correlation identifiers instead of reusable token values.", ROUTES[4]["source"]),
    ("Evidence", "A Graphify calls edge proves that the call completed successfully in production.", False, "Graph relationships are static structural evidence, not runtime-success evidence.", "Graph evidence policy; data/graph-chunks.jsonl"),
    ("Evidence", "When source context is missing, Go-To-ChaoRai should invent a likely endpoint or database table.", False, "The assistant must state the evidence gap and request the responsible source or runtime context.", "Scope policy: One Bangkok-only source-grounded assistant"),
)


def route_record(route: dict[str, str], form: str) -> dict[str, str]:
    question = form.format(feature=route["feature"])
    return {
        "instruction": question,
        "input": (
            f"Component/Service Name: {route['feature']}\n\n"
            "Scenario Type: Source-grounded repository classification.\n\n"
            "Classification Rule: Separate primary code ownership from conditional supporting repositories. "
            "Do not claim that reading a repository proves a completed cross-service transaction.\n\n"
            f"Exact Source Location: {route['source']}"
        ),
        "output": (
            f"## Classification\n\nPrimary repository/repositories: **{route['primary']}**.\n\n"
            f"Conditional supporting repositories: **{route['supporting']}**.\n\n"
            f"## Reason\n\n{route['reason']}\n\nSource: {route['source']}."
        ),
    }


def binary_record(feature: str, statement: str, label: bool, reason: str, source: str) -> dict[str, str]:
    value = "TRUE" if label else "FALSE"
    return {
        "instruction": f"TRUE or FALSE: {statement}",
        "input": (
            f"Component/Service Name: {feature}\n\n"
            "Scenario Type: Source-grounded binary classification.\n\n"
            "Decision Rule: Return a binary label, then justify it only from the cited One Bangkok evidence.\n\n"
            f"Exact Source Location: {source}"
        ),
        "output": f"## Label\n\n**{value}**\n\n## Reason\n\n{reason}\n\nSource: {source}.",
    }


def evaluation_records() -> list[dict]:
    return [
        {"type": "repository-classification", "question": "A Visitor Pass defect spans invite creation and visitor email. Which repositories contain the primary evidence?", "expected_primary": ["mobile-app", "bms", "notification"], "forbidden": ["tourism", "hotel", "attraction"]},
        {"type": "repository-classification", "question": "Where should an engineer begin investigating an Amenity Booking lifecycle defect?", "expected_primary": ["booking-api"], "expected_supporting": ["mobile-app", "cms", "bms", "notification", "iam"]},
        {"type": "repository-classification", "question": "Route an account-login and token-validation issue to the correct One Bangkok repository.", "expected_primary": ["iam"]},
        {"type": "repository-classification", "question": "Which codebases should be consulted for Workplace member access and its client presentation?", "expected_primary": ["bms", "mobile-app"]},
        {"type": "repository-classification", "question": "Which repository owns message templates and FCM/provider delivery adapters?", "expected_primary": ["notification"]},
        {"type": "repository-classification", "question": "Which repository owns the FS member-batch synchronization pipeline?", "expected_primary": ["bms"]},
        {"type": "binary", "question": "TRUE or FALSE: One Bangkok Visitor Pass is a sightseeing package.", "expected": "FALSE", "must_include": ["Workplace", "visitor"]},
        {"type": "binary", "question": "TRUE or FALSE: Kafka publication proves that a visitor email reached the mailbox.", "expected": "FALSE", "must_include": ["delivery"]},
        {"type": "binary", "question": "TRUE or FALSE: BMS is responsible for visitor, schedule and pass processing in the cited flow.", "expected": "TRUE", "must_include": ["BMS"]},
        {"type": "binary", "question": "TRUE or FALSE: Every authenticated IAM account is automatically a Workplace member.", "expected": "FALSE", "must_include": ["separate"]},
        {"type": "binary", "question": "TRUE or FALSE: Accepting an FS member batch means asynchronous synchronization has finished.", "expected": "FALSE", "must_include": ["Kafka"]},
        {"type": "binary", "question": "TRUE or FALSE: A static graph edge is proof of a successful production call.", "expected": "FALSE", "must_include": ["runtime"]},
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/sft_data.jsonl")
    parser.add_argument("--eval-output", default="data/go-to-chaorai-v10-classification-eval.jsonl")
    args = parser.parse_args()
    dataset = Path(args.dataset)
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    scenario_markers = (
        "Scenario Type: Source-grounded repository classification.",
        "Scenario Type: Source-grounded binary classification.",
    )
    retained = [row for row in rows if not any(marker in row.get("input", "") for marker in scenario_markers)]
    generated = [route_record(route, form) for route in ROUTES for form in ROUTE_FORMS]
    generated.extend(binary_record(*fact) for fact in BINARY_FACTS)
    dataset.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in retained + generated), encoding="utf-8")
    evaluation = evaluation_records()
    Path(args.eval_output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in evaluation), encoding="utf-8")
    print(json.dumps({
        "removed_prior_classification_records": len(rows) - len(retained),
        "added_training_records": len(generated),
        "held_out_eval_records": len(evaluation),
        "total_records": len(retained) + len(generated),
    }))


if __name__ == "__main__":
    main()
