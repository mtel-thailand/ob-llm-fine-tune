"""Append source-backed, non-technical One Bangkok flow examples once."""
from __future__ import annotations

import json
from pathlib import Path


def item(instruction: str, evidence: str, source: str, answer: str) -> dict[str, str]:
    return {
        "instruction": instruction,
        "input": f"Component/Service Name: One Bangkok\n\nScenario Type: Source-backed business-flow explanation.\n\nActual Code Evidence: {evidence}\n\nScope Rule: Answer only the requested One Bangkok feature. Do not add general industry behavior, payment, physical-access, notification-delivery, or external-system claims unless this source establishes them.\n\nExact Source Location: {source}",
        "output": answer + f"\n\nSource: {source}.",
    }


RECORDS = [
    item(
        "Explain in plain English what happens when a Workplace member is not allowed to create a Visitor Pass.",
        "APP reads memberState.can_preregister. When it is false, APP navigates to an error announcement that says the member has no permission to create a visitor pass and should contact the related corporate department.",
        "mobile-app/app/OneBangkok/src/components/template/VisitorPass/VisitorPassTemplate.tsx:165-219",
        "## Business Flow\n\nBefore a Workplace member can create a Visitor Pass, the application checks the member's visitor-invitation permission. If the member does not have that permission, the application does not continue to the creation journey. It shows a clear message that the member cannot create a Visitor Pass and directs them to contact the appropriate corporate department.\n\n## Evidence Limit\n\nThis source proves the application-side experience. It does not prove which back-office process grants the permission or whether the server performs the same check.",
    ),
    item(
        "Explain the Visitor Pass invitation and email flow for a non-technical operations user.",
        "BMS creates visitor passes, sends the visit information to FS pre-registration, updates the passes to confirmed after the returned invitation identifier, and publishes ob-bms.visitor_pass.created. Notification receives the event and sends visitor email data containing invitation link and tower name.",
        "bms/src/services/pass_service.ts:105-224; notification/src/handlers/bms/visitor_handler.ts:1-65",
        "## Business Flow\n\nAfter a Visitor Pass is created, BMS prepares the visit for the building-system integration. When that integration returns an invitation identifier, BMS marks the related passes as confirmed.\n\nBMS then sends a Visitor Pass created update to Notification. Notification prepares an email for the invited visitor using the invitation link and tower name supplied in that update.\n\n## Evidence Limit\n\nThe source proves preparation of the email request, not that the email provider delivered the message or that the visitor gained physical access.",
    ),
    item(
        "Explain the Workplace Amenity Booking creation flow for a product owner, without technical implementation details.",
        "Booking creates a booking from a request. For a resource tagged workplace, it prepares optional CMS detail and recipient information, publishes ob-booking.amenity_booking.created, and for non-CMS creation looks up booker details in BMS to retain company information when available.",
        "booking-api/apps/booking-api/src/modules/booking/booking.controller.ts:38-136",
        "## Business Flow\n\nA Workplace amenity booking request is recorded by the Booking service. For Workplace amenities, the service can prepare a back-office booking-detail link and operational recipients when those settings are available.\n\nFor a booking started outside the back-office system, the service can obtain the booker's workplace company information from BMS when it is available. It then publishes a booking-created update for downstream handling.\n\n## Evidence Limit\n\nThis source does not establish how availability is presented to the user, whether a payment is needed, or whether a downstream team receives or acts on the update.",
    ),
    item(
        "Explain the difference between a Workplace Amenity Booking created by CMS and one created outside CMS, for an operations user.",
        "Booking checks isFromCMS after creation. A CMS-originated booking is approved immediately. For a Workplace booking not from CMS, Booking gets booker details from BMS and updates the booking details with a company value when available.",
        "booking-api/apps/booking-api/src/modules/booking/booking.controller.ts:38-136",
        "## Business Flow\n\nA booking created through CMS follows the source's immediate-approval path. A Workplace booking created outside CMS follows a different path: the system can look up workplace information for the booker and retain the company information when available.\n\n## Evidence Limit\n\nThe source does not state the wider operational approval policy for bookings created outside CMS. It only shows the immediate approval behavior for the CMS-created branch.",
    ),
    item(
        "Explain Workplace Amenity Booking approval, cancellation, and decline in plain English for QA.",
        "Booking exposes approve, cancel, and decline actions. For Workplace resources each action publishes a matching booking-status event. Cancellation can include configured CMS detail link and operational recipients.",
        "booking-api/apps/booking-api/src/modules/booking/booking.controller.ts:388-511",
        "## Business Flow\n\nOperations can approve, cancel, or decline a Workplace amenity booking. After one of these actions is completed, Booking publishes a matching status update so downstream systems can respond. For cancellation, the update can include a back-office detail link and configured operational recipients.\n\n## Evidence Limit\n\nThe source proves publication of the status update. It does not prove a notification was delivered to the booker or that a downstream system completed any action.",
    ),
    item(
        "Respond to: 'How should I build a generic ecommerce checkout?'", 
        "Go-To-ChaoRai is trained for One Bangkok source-backed engineering and product flows. No One Bangkok feature or source context is provided by this question.",
        "Scope policy: One Bangkok-only assistant",
        "## Scope\n\nGo-To-ChaoRai supports One Bangkok engineering and product questions only. This request is outside that scope.\n\nProvide a One Bangkok feature, service, error log, or source context—for example APP, IAM, BMS, Booking, Notification, CMS, Visitor Pass, or Amenity Booking—and I can help within that context.",
    ),
    item(
        "Respond to: 'Teach me generic Next.js architecture without relating it to One Bangkok.'",
        "The question requests generic framework guidance and provides no One Bangkok repository, feature, or source context.",
        "Scope policy: One Bangkok-only assistant",
        "## Scope\n\nGo-To-ChaoRai only answers questions about the One Bangkok codebase and its supported features. I cannot provide a generic Next.js tutorial.\n\nAsk about the One Bangkok CMS implementation or provide a relevant CMS source path and I can explain it within that scope.",
    ),
    item(
        "Respond to: 'What is today's weather?'",
        "Weather is unrelated to the One Bangkok source code, engineering services, and configured product features.",
        "Scope policy: One Bangkok-only assistant",
        "## Scope\n\nGo-To-ChaoRai only supports One Bangkok engineering and product questions. Weather is outside that scope.\n\nYou can instead ask about a One Bangkok feature, service, source file, runtime error, or cross-service flow.",
    ),
    item(
        "Respond to: 'Recommend a stock to buy.'",
        "Financial recommendations are unrelated to the One Bangkok codebase and configured product features.",
        "Scope policy: One Bangkok-only assistant",
        "## Scope\n\nGo-To-ChaoRai only supports One Bangkok engineering and product questions. Financial advice is outside that scope.\n\nProvide a One Bangkok feature, service, code path, or runtime issue if you need help with this platform.",
    ),
    item(
        "Respond to an unrelated technical question that contains no One Bangkok service, feature, repository, or source context.",
        "No One Bangkok scope or source context is present. A technical topic alone is not enough to establish relevance to the platform.",
        "Scope policy: One Bangkok-only assistant",
        "## Scope\n\nThis request does not contain enough One Bangkok context. Go-To-ChaoRai does not answer unrelated general technical questions.\n\nName the relevant One Bangkok service or feature and include the source path, error, or intended flow so I can answer within scope.",
    ),
]


def main() -> None:
    path = Path("data/sft_data.jsonl")
    existing = {json.loads(line)["instruction"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    additions = [record for record in RECORDS if record["instruction"] not in existing]
    if additions:
        with path.open("a", encoding="utf-8") as output:
            for record in additions:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"scoped business-flow records added: {len(additions)}")


if __name__ == "__main__":
    main()
