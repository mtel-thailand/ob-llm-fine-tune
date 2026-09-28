"""Replace noisy keyword records with curated One Bangkok feature overviews."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


FEATURES = [
    {
        "name": "Amenity Booking (Workplace and Retail)",
        "summary": "Amenity Booking lets One Bangkok users or operators reserve configured resources. Booking owns validation, availability and policy checks, booking state, and the approve, decline, cancel, update, and session lifecycle.",
        "flow": "A request reaches Booking with the selected resource, booker, and time. Booking loads the resource and resource type, checks booking permission and configured policy, rejects unavailable or conflicting requests, and creates the booking with a policy-driven status. Workplace status changes can publish events for Notification; Retail and Workplace then follow their source-proven session behavior.",
        "checks": "Confirm the resource and resource-type policy, booker permission, requested time, overlap result, initial status, persisted booking, exact event publication, and downstream handling as separate stages.",
        "limit": "Do not assume payment, a particular APP screen, notification delivery, QR rendering, or provider success unless the cited source proves it.",
        "source": "booking-api/apps/booking-api/src/modules/booking/booking.service.ts:105-224; booking-api/apps/booking-api/src/modules/booking/booking.controller.ts:38-136; booking-api/apps/booking-api/src/modules/booking/booking.controller.ts:388-511; notification/src/handlers/booking/amenity_booking_handler.ts:1-120",
    },
    {
        "name": "Visitor Pass",
        "summary": "Visitor Pass lets an eligible Workplace member invite a visitor for a scheduled visit and lets the visitor receive an invitation link prepared from the confirmed pass flow.",
        "flow": "APP checks the member's can_preregister capability. BMS creates the visitor and visit schedule, creates one or more passes, sends the schedule to FS pre-registration, and marks passes confirmed after receiving an invitation identifier. BMS publishes the created event and Notification prepares the visitor email with invitation link and tower name.",
        "checks": "Confirm account-to-member mapping, can_preregister, inviter and location scope, visitor and schedule persistence, FS response, confirmed pass state, event publication, Notification consumption, and email-provider result separately.",
        "limit": "Do not claim QR rendering, an email attachment, successful delivery, scanning, or turnstile admission without the responsible source and runtime evidence.",
        "source": "mobile-app/app/OneBangkok/src/configs/Menu.tsx:521-640; bms/src/controllers/visitors_controller.ts:20-70; bms/src/services/pass_service.ts:105-224; notification/src/handlers/bms/visitor_handler.ts:1-65",
    },
    {
        "name": "Workplace Role Management",
        "summary": "Workplace Role Management connects an authenticated One Bangkok account to a BMS Workplace member and limits available Workplace capabilities by member, tenant, location, and permission data.",
        "flow": "APP uses the authenticated session to request the current BMS member. It stores the BMS member identifier, FS uid, tenant and location information, and capability fields. Visitor Access and other Workplace actions use those capabilities for navigation and availability, while BMS remains responsible for authoritative server-side scope.",
        "checks": "Keep IAM account_id, BMS member id, BMS uid, tenant membership, locations, feature flags, and permission values distinct; verify both APP gating and BMS authorization.",
        "limit": "A successful login does not prove Workplace enrollment, and a visible or hidden menu does not prove server authorization or physical-building access.",
        "source": "mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-337; mobile-app/app/OneBangkok/src/configs/Menu.tsx:521-640; bms/src/controllers/members_controller.ts:1-251",
    },
    {
        "name": "Authentication",
        "summary": "Authentication is the IAM-owned entry point for establishing and renewing the One Bangkok account session across supported login strategies, account lifecycle checks, identity checks, OTP where enabled, and token issuance.",
        "flow": "An APP request reaches IAM AuthController and is delegated to AuthService or AccountService. Login selects the applicable strategy, resolves the account, checks lifecycle and security conditions, completes any required OTP step, and returns the strategy-specific token result. Renew and logout are separate token-lifecycle operations.",
        "checks": "Identify the exact operation and strategy, then verify account state, identity/provider, OTP state when applicable, token type, device association, cache state, and returned error independently without logging credentials.",
        "limit": "Do not treat every login as password authentication, conflate access and refresh tokens, or claim successful downstream Workplace enrollment from IAM success alone.",
        "source": "iam/src/controllers/auth_controller.ts:1-170; iam/src/services/auth_service/index.ts:90-210; iam/src/services/auth_service/index.ts:625-668; iam/src/services/otp_service/index.ts:1-237",
    },
    {
        "name": "Notification",
        "summary": "Notification consumes registered One Bangkok events and turns supported event payloads into channel-specific work such as in-app messages, visitor email, amenity-booking email, push delivery, or live updates where the corresponding handler proves it.",
        "flow": "The service registers exact event names and routes each consumed event to its handler. The handler validates or maps the supplied payload and calls the relevant MessageService operation. Message preparation, persistence, FCM/email/websocket invocation, provider acceptance, and user-visible delivery are separate outcomes.",
        "checks": "Verify the exact event name and payload, consumer registration, selected handler, recipient lookup, template and language data, persisted message state, provider response, retry behavior, and user-visible result separately.",
        "limit": "Do not infer a channel from the word notification, and do not claim delivery merely because a producer published an event or a handler called a provider adapter.",
        "source": "notification/src/server.ts:1-74; notification/src/handlers/handler_registry.ts:1-93; notification/src/handlers/bms/visitor_handler.ts:1-65; notification/src/handlers/booking/amenity_booking_handler.ts:1-120; notification/src/services/message_service.ts:1-120",
    },
]


def records(feature: dict[str, str]) -> list[dict[str, str]]:
    base = (
        f"Component/Service Name: {feature['name']}\n\n"
        "Scenario Type: Curated One Bangkok feature overview.\n\n"
        f"Source-backed Summary: {feature['summary']}\n\n"
        f"Supported Flow: {feature['flow']}\n\n"
        f"Validation Focus: {feature['checks']}\n\n"
        f"Evidence Boundary: {feature['limit']}\n\n"
        f"Exact Source Location: {feature['source']}"
    )
    name = feature["name"]
    source = feature["source"]
    return [
        {"instruction": f"What does the One Bangkok {name} feature do? Explain it in plain English and remain inside this feature's scope.", "input": base,
         "output": f"## Purpose\n\n{feature['summary']}\n\n## Main Flow\n\n{feature['flow']}\n\n## Scope Boundary\n\n{feature['limit']}\n\nSource: {source}."},
        {"instruction": f"Explain the detailed end-to-end flow of One Bangkok {name} without adding behavior that the source does not prove.", "input": base,
         "output": f"## End-to-End Flow\n\n{feature['flow']}\n\n## Responsibility Check\n\n{feature['checks']}\n\n## Not Proven\n\n{feature['limit']}\n\nSource: {source}."},
        {"instruction": f"Create a focused QA validation plan for the One Bangkok {name} feature using only its source-backed behavior.", "input": base,
         "output": f"## QA Objective\n\nValidate this feature contract: {feature['summary']}\n\n## Validation Path\n\n{feature['checks']}\n\nTest the successful path, denied or invalid input, boundary state, repeated request where applicable, and each observable cross-service boundary independently.\n\n## Acceptance Boundary\n\n{feature['limit']}\n\nSource: {source}."},
        {"instruction": f"A user reports that One Bangkok {name} is not working, but provides no log. Explain the correct scoped troubleshooting flow without inventing a root cause.", "input": base,
         "output": f"## Current Finding\n\nNo root cause is confirmed because no request, response, log, or correlation identifier is supplied. The expected feature behavior is: {feature['flow']}\n\n## Troubleshooting\n\n{feature['checks']}\n\nStop at the first stage whose required input exists but whose expected output is absent. Collect sanitized identifiers and service-specific logs for that boundary before proposing a fix.\n\n## Evidence Boundary\n\n{feature['limit']}\n\nSource: {source}."},
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/sft_data.jsonl")
    args = parser.parse_args()
    path = Path(args.dataset)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    retained = [row for row in rows if "Feature Selection Evidence:" not in row.get("input", "") and "Scenario Type: Curated One Bangkok feature overview." not in row.get("input", "")]
    generated = [row for feature in FEATURES for row in records(feature)]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in retained + generated), encoding="utf-8")
    print(json.dumps({"removed_noisy_or_prior": len(rows) - len(retained), "added_curated": len(generated), "total": len(retained) + len(generated)}))


if __name__ == "__main__":
    main()
