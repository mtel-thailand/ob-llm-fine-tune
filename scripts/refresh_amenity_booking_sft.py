#!/usr/bin/env python3
"""Replace generic Amenity Booking SFT data with document- and code-backed Q&A."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


DOC = "Amenity Booking (Workplace & Retail) (1).docx, sections 1-4 and OBK Booking API Documentation"
BOOKING = "booking-api/apps/booking-api/src/modules/booking/booking.service.ts"
CONTROLLER = "booking-api/apps/booking-api/src/modules/booking/booking.controller.ts"
SESSION = "booking-api/apps/booking-api/src/modules/session/session.service.ts"
NOTIFICATION = "notification/src/handlers/booking/amenity_booking_handler.ts"

# Each fact explicitly identifies whether it is a requirement in the supplied
# document, proven by code, or supported by both. This is essential because
# product documentation can describe a target flow that is not yet deployed.
FACTS = [
    ("shared architecture", "Both", "Retail and Workplace share one Booking API model. The domain is selected through ResourceType/Resource tags such as retail and workplace.", f"{DOC}; {BOOKING}:105-224"),
    ("resource taxonomy", "Both", "Workplace maps Amenity Type to ResourceType and Room to Resource. Retail API examples map Amenity Type to ResourceType and Asset Item to Resource.", f"{DOC}; {BOOKING}:105-224"),
    ("Retail purpose", "Document requirement", "Retail is an operational asset-reservation domain with service points, asset items, pickup, return, and operational booking management.", DOC),
    ("Workplace purpose", "Document requirement", "Workplace is a facility-reservation domain with room management, policy enforcement, approval, transaction limits, and check-in operations.", DOC),
    ("create request", "Both", "Booking creation accepts resourceId, bookerId, from, optional to, details, isFromCMS, and operator. The service loads Resource and ResourceType before applying policies.", f"{DOC}; {CONTROLLER}:1-120; {BOOKING}:105-224"),
    ("resource availability", "Code-proven behavior", "Booking creation rejects a missing resource and rejects a resource whose properties.allowBooking is false. It also checks ResourceType allowBooking and visibility where applicable.", f"{BOOKING}:105-224; {BOOKING}:833-952"),
    ("Workplace time validation", "Both", "Workplace slot bookings require from and to, require from before to, reject overlap, require the same day, and must be within configured operation hours.", f"{DOC}; {BOOKING}:729-848; {BOOKING}:937-1056"),
    ("Retail time validation", "Both", "Retail uses ResourceType policy for operation hours, rejects past bookings, and can enforce blockWholeDay for active bookings on the selected day.", f"{DOC}; {BOOKING}:833-1056"),
    ("booking window", "Both", "maxDaysInAdvance limits how far ahead a booking may start. The code compares requested from time with the end of the allowed future day range.", f"{DOC}; {BOOKING}:833-952"),
    ("permission policy", "Code-proven behavior", "The service activates or updates booking permission for bookerId, then enforces allowPermissionType. CORPORATE access requires both corporate permission and isWorkplace true.", f"{BOOKING}:105-224; {BOOKING}:729-848"),
    ("transaction limit", "Both", "For Workplace, enabled ResourceType transaction limits count the user's bookings across resources in that type and reject when count reaches limitCount.", f"{DOC}; {BOOKING}:105-224; {BOOKING}:833-1056"),
    ("initial status", "Code-proven behavior", "The create service sets PENDING when the selected policy requires approval; otherwise it sets APPROVED. Status is policy-driven, not determined solely by Retail or Workplace.", f"{BOOKING}:105-224"),
    ("concurrency and booking code", "Code-proven behavior", "The booking create transaction uses a PostgreSQL advisory transaction lock keyed by booking-code and date before generating the daily booking code.", f"{BOOKING}:105-224"),
    ("update behavior", "Both", "Retail update requires resourceId. Workplace update removes resourceId to prevent changing the booked room. CMS edits can bypass the normal Workplace edit window and are approved.", f"{DOC}; {BOOKING}:209-432; {CONTROLLER}:105-224"),
    ("edit window", "Both", "Retail editing is rejected within one minute of start. Workplace editing is rejected after maxEditableHour before the booking time unless the update is from CMS.", f"{DOC}; {BOOKING}:209-328; {BOOKING}:729-848"),
    ("cancel behavior", "Both", "An active booking can be cancelled. Workplace user cancellation is restricted by maxCancelHour unless it is CMS or auto-cancellation. Auto-cancellation emits an amenity booking event.", f"{DOC}; {BOOKING}:625-744"),
    ("approval and decline", "Both", "Approve sets APPROVED and records an activity log. Decline sets DECLINED, stores the decline comment in details, and records an activity log.", f"{DOC}; {BOOKING}:625-744; {BOOKING}:729-848"),
    ("availability and history", "Both", "Booking list supports filters including booker, booking code, tag, resource/resource type, service point, date, status, location, search, and pagination. Resource slots expose available time ranges.", f"{DOC}; {BOOKING}:417-536"),
    ("Retail session lifecycle", "Both", "Creating a Retail session completes the booking and creates a session in IN_PROGRESS, representing pickup/in-use. Completing the session represents return and can change resource allowBooking or location.", f"{DOC}; {SESSION}:1-126"),
    ("Workplace session lifecycle", "Both", "Creating a Workplace session completes the booking and creates the session with COMPLETED status, representing the check-in completion path in the current code.", f"{DOC}; {SESSION}:1-120"),
    ("CMS behavior", "Both", "Booking API accepts isFromCMS and operator. CMS creation is approved by the controller after creation; CMS update is also approved and emits an updated-booking event.", f"{DOC}; {CONTROLLER}:1-224"),
    ("Kafka created event", "Code-proven behavior", "The controller emits ob-booking.amenity_booking.created for Workplace booking creation, with room, booking, date/time, CMS view URL, and recipient-email data.", f"{CONTROLLER}:1-120"),
    ("Notification consumption", "Code-proven behavior", "Notification subscribes to amenity booking created, cancelled, approved, declined, auto-cancellation, reset-location, and updated events. The created handler formats Bangkok date/time and sends an admin email template.", f"notification/src/server.ts:1-74; notification/src/handlers/handler_registry.ts:1-93; {NOTIFICATION}:1-120"),
    ("event reliability boundary", "Code-proven behavior", "EventProducer validates that payload keys exactly match the event-registry shape before sending. Booking persistence and Kafka delivery must therefore be investigated as separate boundaries.", "booking-api/apps/booking-api/src/utils/kafka/event_producer.ts:1-31"),
    ("QR evidence boundary", "Code-proven behavior", "The Notification approved handler tells the user to access a QR code through booking details, but the reviewed sources do not prove the QR rendering implementation or scan validation path.", f"{NOTIFICATION}:1-120"),
]

NORMAL_INTENTS = (
    "Explain",
    "Describe the end-to-end business flow for",
    "Explain the operational purpose of",
    "Explain what a QA engineer should validate for",
    "Explain the difference between the requirement and implementation for",
)
TECHNICAL_INTENTS = (
    "Trace the source-backed implementation of",
    "Analyse how to debug",
    "Explain the technical boundary for",
    "Diagnose likely failure stages for",
    "Review the production risks of",
)
AUDIENCES = (
    "a product owner",
    "a mobile developer",
    "a CMS operator",
    "a QA engineer",
    "a Booking API developer",
    "a support engineer",
)
AREAS = (
    "request validation",
    "policy selection",
    "state transition",
    "database transaction",
    "cross-service event flow",
    "availability calculation",
    "permission enforcement",
    "operational recovery",
)


def is_old_amenity_record(item: dict[str, object]) -> bool:
    instruction = str(item.get("instruction", "")).casefold()
    input_value = str(item.get("input", "")).casefold()
    return "feature selection evidence:" in input_value and " for amenity booking" in instruction


def is_curated_amenity_record(item: dict[str, object]) -> bool:
    """Identify records produced by this script so a rerun replaces, not duplicates, them."""
    instruction = str(item.get("instruction", "")).casefold()
    input_value = str(item.get("input", "")).casefold()
    return "amenity booking" in instruction and (
        "evidence classification:" in input_value
        or "source-backed functional explanation" in input_value
    )


def make_normal(focus: str, source_kind: str, evidence: str, source: str, intent: str, audience: str) -> dict[str, str]:
    return {
        "instruction": f"{intent} Amenity Booking {focus} for {audience}. Use only the supplied document and current code evidence.",
        "input": (
            "Component/Service Name: Booking API (NestJS), CMS/APP integration, Kafka, and Notification\n\n"
            f"Evidence Classification: {source_kind}\n\n"
            f"Source-backed Fact: {evidence}\n\n"
            "Rule: A document requirement is not proof of runtime behavior. Do not invent an endpoint, database table, "
            "mobile screen, QR implementation, payment flow, or consumer result that is absent from the cited source.\n\n"
            f"Source: {source}"
        ),
        "output": (
            "## Explanation\n\n"
            f"{evidence}\n\n"
            "The common model is APP/CMS to Booking API. Booking API owns validation, booking state, "
            "activity tracking, and session behavior. Kafka is an asynchronous boundary to Notification; "
            "it must not be described as a synchronous guarantee.\n\n"
            f"For {audience}, treat this as {source_kind.lower()}. "
            "When an investigation needs a runtime conclusion, collect booking code, booking ID, resource ID, "
            "event name, and logs from the responsible service.\n\n"
            f"Source: {source}."
        ),
    }


def make_technical(focus: str, source_kind: str, evidence: str, source: str, intent: str, area: str) -> dict[str, str]:
    return {
        "instruction": f"{intent} Amenity Booking {focus}, focusing on {area}. Separate code-proven behavior from document requirements.",
        "input": (
            "Component/Service Name: Booking API (NestJS), BMS integration, Kafka, and Notification\n\n"
            "Exact Runtime Log or Stack Trace: No runtime incident log is supplied.\n\n"
            f"Evidence Classification: {source_kind}\n\n"
            f"Actual Source Evidence: {evidence}\n\n"
            f"Source: {source}"
        ),
        "output": (
            "## 【Root Cause Analysis】\n\n"
            f"This is a source-backed analysis, not a confirmed incident. {evidence} "
            f"The diagnostic focus is {area}. A statement marked Document requirement describes intended behavior; "
            "a statement marked Code-proven behavior is supported by the cited implementation.\n\n"
            "## 【Step-by-Step Debugging Guide】\n\n"
            "1. Identify booking ID/code, resource ID, booker ID, tag, and current booking status.\n"
            "2. Load the Resource and ResourceType policy before interpreting a validation failure.\n"
            "3. Check the applicable branch: Workplace uses room/resource policy for time rules; Retail uses ResourceType policy for its retail branch.\n"
            "4. Check activity logs and session state separately from booking status.\n"
            "5. For a notification issue, verify Booking API event production, event payload shape, Notification consumption, handler, template, and delivery separately.\n"
            "6. Do not infer QR rendering, a mobile UI result, or Kafka delivery without the relevant source and runtime correlation data.\n\n"
            "## 【Production-Grade Fix】\n\n"
            "No code change is prescribed without a reproduced defect. Keep policies authoritative in Booking API, "
            "preserve the transactional booking write, and add correlation-safe logs at the API, event producer, "
            "and Notification consumer boundaries.\n\n"
            f"Source: {source}."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/sft_data.jsonl")
    parser.add_argument("--count", type=int, default=600)
    args = parser.parse_args()
    if args.count < 2:
        raise SystemExit("--count must be at least 2")
    path = Path(args.dataset)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    retained = [
        row for row in rows
        if not is_old_amenity_record(row) and not is_curated_amenity_record(row)
    ]
    replacement: list[dict[str, str]] = []
    for index in range(args.count):
        pair = index // 2
        focus, source_kind, evidence, source = FACTS[pair % len(FACTS)]
        intent_index = pair // len(FACTS)
        if index % 2:
            replacement.append(make_technical(
                focus, source_kind, evidence, source,
                TECHNICAL_INTENTS[intent_index % len(TECHNICAL_INTENTS)],
                AREAS[(intent_index // len(TECHNICAL_INTENTS)) % len(AREAS)],
            ))
        else:
            replacement.append(make_normal(
                focus, source_kind, evidence, source,
                NORMAL_INTENTS[intent_index % len(NORMAL_INTENTS)],
                AUDIENCES[(intent_index // len(NORMAL_INTENTS)) % len(AUDIENCES)],
            ))
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in retained + replacement), encoding="utf-8")
    print(json.dumps({
        "removed_generic_amenity_records": len(rows) - len(retained),
        "added_document_and_code_backed_amenity_records": len(replacement),
        "total_records": len(retained) + len(replacement),
    }))


if __name__ == "__main__":
    main()
