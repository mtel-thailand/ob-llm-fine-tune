#!/usr/bin/env python3
"""Replace generic Workplace records with detailed, source-grounded SFT data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SCENARIOS = [
    {
        "title": "Workplace identity model",
        "components": "APP, IAM identity boundary, BMS, and FS",
        "evidence": (
            "APP stores the BMS member id, FS uid, tenant, default floor, towers, passes, "
            "passed_turnstile, is_fs_member, and can_preregister. BMS resolves a member by "
            "account_id or x-account-id. The BMS member uid is the identifier passed to FS."
        ),
        "flow": "IAM account_id -> BMS member.account_id -> BMS member.uid -> FS person identity.",
        "checks": "Verify the IAM account identifier, BMS member id, BMS uid, and FS person identifier as separate values; never substitute one for another.",
        "risk": "A successful IAM login does not prove that a linked BMS/FS Workplace identity exists.",
        "missing": "The reviewed source does not establish the internal IAM flow that originally creates every FS external identity.",
        "sources": "mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-337; bms/src/controllers/members_controller.ts:1-251",
    },
    {
        "title": "APP Workplace member bootstrap",
        "components": "APP and BMS",
        "evidence": (
            "APP configures the BMS SDK with the authenticated token and calls membersIndex. "
            "When a member is returned, APP stores member identity and Workplace capability data; "
            "when no member is returned or the call fails, APP sets is_fs_member to false."
        ),
        "flow": "APP authenticated session -> BMS SDK token -> membersIndex -> Workplace member state.",
        "checks": "Inspect token setup, the membersIndex response, memberState.id, memberState.uid, is_fs_member, tenant, and can_preregister.",
        "risk": "Treating authentication success as Workplace enrollment can expose unusable menus or misleading UI state.",
        "missing": "A production failure cannot be diagnosed without the actual HTTP status and APP/BMS correlation data.",
        "sources": "mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-337; bms/src/controllers/members_controller.ts:1-251",
    },
    {
        "title": "Tenant permission ceiling",
        "components": "BMS Member access model",
        "evidence": (
            "BMS membersShow loads tenant authorized locations and member authorized locations. "
            "A returned tower must match a tenant-authorized location, while its returned floor must "
            "match a member-authorized floor. This read path implements an effective intersection."
        ),
        "flow": "Tenant authorized locations INTERSECT Member authorized locations -> effective APP tower/floor view.",
        "checks": "Compare tenant location ids, member floor/location ids, and the towers/floors serialized by membersShow.",
        "risk": "The inspected read path enforces the ceiling, but it is not evidence that every permission write path enforces the same invariant.",
        "missing": "No database constraint proving member authorization is always a subset of tenant authorization was established from these excerpts.",
        "sources": "bms/src/controllers/members_controller.ts:1-251; bms/src/services/authorized_location_service.ts:1-422",
    },
    {
        "title": "Location-specific turnstile state",
        "components": "APP, BMS, and FS",
        "evidence": (
            "When location_id is supplied to BMS membersShow, BMS maps the BMS location to its FS uid "
            "and calls FS getMemberExitsTower with member.uid and the FS location id. The returned state "
            "is exposed to APP as passed_turnstile."
        ),
        "flow": "APP member detail request with location -> BMS location mapping -> FS exit/entry state -> passed_turnstile.",
        "checks": "Verify the requested BMS location id, mapped location uid, member.uid, FS response, and final passed_turnstile value.",
        "risk": "Turnstile state is location-sensitive and should not be reused across towers without refreshing it.",
        "missing": "The excerpt does not prove the physical reader decision or every FS transition after a scan.",
        "sources": "bms/src/controllers/members_controller.ts:1-251; bms/src/libs/fs_client.ts:105-214",
    },
    {
        "title": "FS member batch ingestion",
        "components": "FS integration and BMS Kafka processing",
        "evidence": (
            "POST /integrations/fs/members accepts a batch, establishes jobId and traceId, deduplicates "
            "or selects the latest records, and publishes ob-bms.sync-member-records. The registered "
            "BMS handler validates the event and calls MemberService.sync."
        ),
        "flow": "FS integration request -> BMS controller -> ob-bms.sync-member-records -> SyncMemberRecordsHandler -> MemberService.sync.",
        "checks": "Follow jobId and traceId from ingestion through Kafka consumption; compare input count, deduplicated records, handler validation, and sync outcome.",
        "risk": "HTTP acceptance of the batch is not proof that asynchronous synchronization completed.",
        "missing": "Retry count, dead-letter behavior, and broker delivery guarantees require Kafka configuration not cited here.",
        "sources": "bms/src/controllers/integrations/fs/members_controller.ts:1-201; bms/src/events/bms/sync_member_records_handler.ts:1-48; bms/src/events/handler_registry.ts:1-24",
    },
    {
        "title": "Active member synchronization",
        "components": "BMS MemberService and database",
        "evidence": (
            "For an active FS record, MemberService syncs the member by personID/uid, resolves default "
            "location or floor, synchronizes tenant_members and authorized_locations, removes obsolete "
            "tenant relationships, emits ob-bms.member.created, and clears relevant caches."
        ),
        "flow": "FS person record -> BMS member upsert -> tenant membership sync -> location authorization sync -> event/cache boundary.",
        "checks": "Compare personID, tenantIDs, locations, active flag, updateTime, resulting member row, tenant_members, authorized_locations, emitted event, and cache eviction.",
        "risk": "Partial or stale relationship data can produce a valid member row with an incorrect effective access scope.",
        "missing": "The event name proves publication intent, not that every external consumer completed its work.",
        "sources": "bms/src/services/member_service.ts:313-640; bms/src/services/authorized_location_service.ts:1-422",
    },
    {
        "title": "Member offboarding",
        "components": "BMS, IAM event boundary, and dependent Workplace features",
        "evidence": (
            "For an inactive FS record, BMS clears member account_id, metadata, and default floor, "
            "deletes tenant_members and authorized_locations in a transaction, emits an offboard event, "
            "and clears cache. The integration controller also has an IAM member-deleted event path."
        ),
        "flow": "Inactive/offboard input -> BMS relationship removal -> account unlink -> event publication -> APP loses usable Workplace context after refresh.",
        "checks": "Verify active=false, member uid, transaction result, deleted relationships, account_id state, emitted event, and cache invalidation before checking APP behavior.",
        "risk": "Leaving any authorization relationship or stale cache behind can preserve access after offboarding.",
        "missing": "The cited source does not prove when downstream physical credentials are finally revoked inside FS.",
        "sources": "bms/src/services/member_service.ts:313-640; bms/src/controllers/integrations/fs/members_controller.ts:1-201",
    },
    {
        "title": "IAM external identity linkage",
        "components": "IAM Kafka boundary and BMS",
        "evidence": (
            "BMS consumes ob-iam.external_identity.created. For external_identity.type equal to fs, "
            "it finds the BMS member whose uid matches the external identity uid, writes the IAM "
            "account_id to that member, and clears cache. Non-FS identity types are skipped."
        ),
        "flow": "IAM external identity event -> type=fs check -> BMS member lookup by uid -> account_id link -> cache clear.",
        "checks": "Confirm exact event name, identity type, external uid, member.uid match, account_id update, and cache eviction.",
        "risk": "A mismatched uid leaves IAM authentication valid while BMS cannot resolve a Workplace member for the account.",
        "missing": "The BMS consumer does not prove which IAM request or workflow created the external identity.",
        "sources": "bms/src/events/iam/external_identity_handler.ts:1-128; bms/src/events/handler_registry.ts:1-24",
    },
    {
        "title": "IAM permanent deletion cleanup",
        "components": "IAM Kafka boundary and BMS",
        "evidence": "The BMS IAM account handler clears account_id on associated members when it processes the permanent-deleted account event.",
        "flow": "IAM permanent account deletion event -> BMS member association lookup -> account_id cleared.",
        "checks": "Confirm the account event, affected account_id, number of linked members, database update, and subsequent membersIndex behavior.",
        "risk": "Clearing account linkage and revoking physical access are related but distinct operations and must not be assumed to occur in one handler.",
        "missing": "This handler alone does not establish removal of tenant_members, authorized_locations, or FS credentials.",
        "sources": "bms/src/events/iam/account_handler.ts:1-26; bms/src/events/iam/external_identity_handler.ts:1-128",
    },
    {
        "title": "Workplace home refresh",
        "components": "APP, BMS, and content services",
        "evidence": (
            "The Workplace home refresh invokes news/announcement loading, member-and-tower loading, "
            "and content loading under the Workplace persona. Feature data is therefore assembled from "
            "more than one backend rather than returned by one Workplace endpoint."
        ),
        "flow": "Workplace persona refresh -> parallel/related content requests plus BMS member/tower context -> composed home state.",
        "checks": "Separate failures in member/tower loading from content and news requests; record which request failed instead of labeling the whole Workplace backend unavailable.",
        "risk": "A partially populated home page can be caused by one dependency while authentication and other features remain healthy.",
        "missing": "Without a runtime network trace, request ordering and the failed dependency cannot be concluded for a production incident.",
        "sources": "mobile-app/app/OneBangkok/src/components/template/HomeTemplate.tsx; mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-337",
    },
    {
        "title": "Workplace menu capability gates",
        "components": "APP and BMS member capabilities",
        "evidence": (
            "APP exposes Workplace quick-menu entries including Call Elevator, Visitor Access, and "
            "Building Service. Visitor Access checks memberState.can_preregister before navigation, "
            "while other areas also use feature flags or permission lists."
        ),
        "flow": "Remote/config capability plus member state plus permission list -> menu/action availability.",
        "checks": "Inspect remote feature configuration, the current member capability fields, permission list, and the navigation guard independently.",
        "risk": "Hiding a menu is a usability control, not a sufficient backend authorization boundary.",
        "missing": "The menu configuration alone does not prove server-side authorization for every invoked endpoint.",
        "sources": "mobile-app/app/OneBangkok/src/configs/Menu.tsx:521-640; mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-337",
    },
    {
        "title": "What’s Happening publication flow",
        "components": "CMS, Document API, and APP",
        "evidence": (
            "CMS creates or updates /whathappening documents and uploads images. APP uses the Document "
            "SDK to load whathappening content, keeps published entries inside their display window, "
            "localizes them, and sorts event or suggested content."
        ),
        "flow": "CMS operator -> Document API/S3-backed content -> APP WhatHappeningService -> localized Workplace display.",
        "checks": "Verify publish state, showStartDate/showEndDate, timezone interpretation, language payload, image upload result, sequence, and APP filtering.",
        "risk": "Publishing content and delivering a Workplace notification are separate behaviors; this flow does not itself prove a Notification event.",
        "missing": "No BMS member-location filter for What’s Happening was established in the inspected APP service.",
        "sources": "cms/app/src/services/what-happening/service.ts:1-224; mobile-app/app/OneBangkok/src/services/whatHappeningService.ts:1-208",
    },
    {
        "title": "Call Elevator preconditions",
        "components": "APP, BMS, device permissions, and FS",
        "evidence": (
            "APP checks Bluetooth and location permissions, scans a beacon to establish current context, "
            "uses the member tower/floor state, and blocks the call path when passed_turnstile is false."
        ),
        "flow": "Device permission -> beacon context -> member tower/floor -> turnstile state -> lift.call request.",
        "checks": "Check OS Bluetooth/location permission, beacon result, selected BMS location/floor, refreshed passed_turnstile value, and whether the SDK request was sent.",
        "risk": "A device/beacon failure can prevent an elevator call before BMS or FS is contacted.",
        "missing": "A UI precondition does not prove that BMS independently authorizes the requested destination.",
        "sources": "mobile-app/app/OneBangkok/src/components/template/CallElevatorTemplate.tsx:1-328; mobile-app/app/OneBangkok/src/services/bmsService/BuildingAccessService.ts:1-78",
    },
    {
        "title": "Call Elevator command mapping",
        "components": "APP, BMS CommandService, and FS",
        "evidence": (
            "APP submits a member command named lift.call with destination_floor_id and location_id. "
            "BMS resolves the member, location, and floor, maps member.uid to personID, location.uid "
            "to locationID, and floor.uid to destinationFloorID, calls FS, and stores command status/result."
        ),
        "flow": "APP membersCommandsCreate -> BMS CommandsController -> CommandService -> FS liftCall -> stored command result.",
        "checks": "Trace member_id, BMS location/floor ids, their FS uids, FS request/response, persisted command status, and the lift name returned to APP.",
        "risk": "Using a BMS database id where an FS uid is required causes a cross-system identifier mismatch.",
        "missing": "The current excerpt does not establish physical elevator arrival or completion after FS accepts the request.",
        "sources": "bms/src/controllers/members/commands_controller.ts:1-48; bms/src/services/command_service.ts:1-96; bms/src/libs/fs_client.ts:105-214",
    },
    {
        "title": "Call Elevator server-side authorization gap",
        "components": "BMS CommandService security boundary",
        "evidence": (
            "The inspected command path resolves the requested location and destination floor and forwards "
            "their FS uids. An explicit check that the destination is inside the member/tenant effective "
            "authorized floor set was not identified in this path."
        ),
        "flow": "Untrusted requested floor -> BMS lookup -> authorization check should occur -> FS request.",
        "checks": "Test an authorized floor, another floor in the same tower, a floor outside the tenant scope, and a location belonging to another tenant; inspect whether BMS rejects before FS.",
        "risk": "Relying on APP filtering or an undocumented FS rule leaves the BMS API trust boundary unclear.",
        "missing": "Absence in the reviewed excerpt is not proof that FS permits unauthorized access; FS may enforce its own policy.",
        "sources": "bms/src/controllers/members/commands_controller.ts:1-48; bms/src/services/command_service.ts:1-96; bms/src/controllers/members_controller.ts:1-251",
    },
    {
        "title": "Visitor Access capability boundary",
        "components": "APP and BMS Workplace member",
        "evidence": (
            "APP checks memberState.can_preregister before navigating to VisitorPassScreen. The inviter "
            "identity used during creation is the BMS member id obtained from the current Workplace context."
        ),
        "flow": "IAM-authenticated APP -> BMS Workplace member -> can_preregister gate -> Visitor Pass submission.",
        "checks": "Verify the current account-to-member link, memberState.id, can_preregister, tenant/location scope, and backend response separately.",
        "risk": "APP gating must not replace BMS validation of the inviter and requested visit location.",
        "missing": "This navigation code does not prove QR rendering or physical turnstile admission.",
        "sources": "mobile-app/app/OneBangkok/src/configs/Menu.tsx:521-640; mobile-app/app/OneBangkok/src/states/buildingAccess/visitorPass.ts:1-162",
    },
    {
        "title": "Visitor Pass cross-service handoff",
        "components": "APP, BMS, FS, Kafka, and Notification",
        "evidence": (
            "APP submits visitor and schedule data using the BMS member as inviter. BMS owns visitor, "
            "schedule, token/pass processing and FS pre-registration, then publishes ob-bms.visitor_pass.created. "
            "Notification consumes that event and invokes the visitor email path."
        ),
        "flow": "APP -> BMS visitor/schedule/pass -> FS pre-registration -> BMS Kafka event -> Notification email handler.",
        "checks": "Trace inviter member id, visitor id, schedule id, pass id/uid, FS response, exact event name, Notification handler, template, and provider result as separate stages.",
        "risk": "A created database record, successful FS call, published event, consumed event, and delivered email are different success boundaries.",
        "missing": "The reviewed handler does not by itself prove how QR code generation, attachment, scan validation, or turnstile admission works.",
        "sources": "mobile-app/app/OneBangkok/src/states/buildingAccess/visitorPass.ts:1-162; bms/src/controllers/visitors_controller.ts:1-145; bms/src/services/pass_service.ts:105-224; notification/src/handlers/bms/visitor_handler.ts:1-65",
    },
    {
        "title": "AQI Workplace selection flow",
        "components": "APP, BMS SensorService, and TCC AQI integration",
        "evidence": (
            "APP loads the member tower/outdoor choices and calls BMS sensorsIndex with tower id, language, "
            "and member id. BMS maps the selected tower and floors to external AQI identifiers, obtains a "
            "cached TCC token, loads AQI data, and applies configured/localized indicator ranges."
        ),
        "flow": "APP member tower selection -> BMS SensorsController -> SensorService -> TCC AQI -> localized APP display.",
        "checks": "Verify member tower state, selected tower/outdoor zone, member_id query, external tower mapping, token acquisition/cache, floor-code mapping, and localization.",
        "risk": "An empty AQI screen can originate from access context, external mapping, token, upstream data, or localization rather than one generic BMS error.",
        "missing": "The source does not establish that every outdoor reading is tenant-specific.",
        "sources": "mobile-app/app/OneBangkok/src/screens/AirQualityScreen.tsx:1-220; bms/src/controllers/sensors_controller.ts:1-103; bms/src/services/sensor_service.ts:1-223",
    },
    {
        "title": "AQI authorized-floor filtering review",
        "components": "BMS SensorsController permission boundary",
        "evidence": (
            "SensorsController includes authorized_locations filtered by member_id while loading floors, "
            "but the inspected floorIds construction maps the parent floor collection without an obvious "
            "filter that removes parents whose nested authorized_locations result is empty."
        ),
        "flow": "Tower floors plus nested member authorization -> expected authorized floor ids -> SensorService query.",
        "checks": "Run tests for a member authorized to one floor, no floor, another tenant's tower, and all floors; capture the exact floorIds passed to SensorService.",
        "risk": "The intended member-scoped AQI view may include more floors than the member is authorized to view.",
        "missing": "This is a code-review finding, not proof of production exposure; reproduce with actual query results before changing behavior.",
        "sources": "bms/src/controllers/sensors_controller.ts:1-103; bms/src/services/sensor_service.ts:1-223",
    },
    {
        "title": "Building Service APP eligibility",
        "components": "APP and Workplace permission state",
        "evidence": (
            "APP exposes Service Request only when the building-service feature flag and canDoServiceRequest "
            "permission are enabled, and exposes the air-conditioner request according to its corresponding "
            "flag and canDoACRequest permission. With no eligible shortcuts it renders restricted access."
        ),
        "flow": "Remote feature flag plus permissionList -> eligible Building Service action -> request form.",
        "checks": "Inspect remote configuration, permissionList, current member context, shortcut construction, and navigation result.",
        "risk": "Client eligibility controls presentation; the BMS endpoint still requires its own authorization policy.",
        "missing": "The APP component alone does not prove the backend role/permission middleware for every request type.",
        "sources": "mobile-app/app/OneBangkok/src/components/template/BuildingServiceTemplate.tsx:1-408",
    },
    {
        "title": "Building Service request lifecycle",
        "components": "APP, BMS, Kafka, and Notification",
        "evidence": (
            "APP submits tower, floor, issue type, title, description, image, and requester context. BMS "
            "creates the service request with submitted status and emits ob-bms.service_request.created. "
            "Status changes emit ob-bms.service_request_status.updated."
        ),
        "flow": "APP request form -> BMS persisted request/reference -> created/status Kafka events -> Notification handlers.",
        "checks": "Trace member requester_id, tower/floor, issue type, persisted reference/status, event publication, consumption, and recipient account independently.",
        "risk": "A BMS success response does not prove an operational email or requester notification was delivered.",
        "missing": "No production incident should be diagnosed without a request reference, event/correlation data, Notification logs, and provider result.",
        "sources": "mobile-app/app/OneBangkok/src/states/buildingAccess/requestService.tsx:1-67; bms/src/controllers/service_requests_controller.ts:1-128; notification/src/handlers/bms/service_request.handler.ts:1-45",
    },
    {
        "title": "Building Service Notification ownership",
        "components": "BMS and Notification",
        "evidence": (
            "Notification handles the BMS service-request-created event by sending an operational/admin "
            "email. It handles the status-updated event by creating an automatic/in-app message for the "
            "requester's account_id."
        ),
        "flow": "BMS created event -> admin email; BMS status-updated event -> requester account notification.",
        "checks": "Match the exact event name and payload, then inspect the corresponding handler, requester account_id, template/message construction, and delivery result.",
        "risk": "Created and updated events have different audiences and channels; testing only one handler does not validate the full lifecycle.",
        "missing": "These handlers do not establish that every event is sent through FCM, SMS, email, webhook, and WebSocket simultaneously.",
        "sources": "notification/src/handlers/bms/service_request.handler.ts:1-45; notification/src/handlers/handler_registry.ts:1-93",
    },
    {
        "title": "CMS role versus Workplace access",
        "components": "CMS, IAM identity boundary, and BMS",
        "evidence": (
            "CMS Member & Roles supports invitation, role assignment, removal, suspension, reactivation, "
            "and resend-invite operations for back-office users. The inspected CMS code does not show that "
            "these operations create BMS members, tenant_members, authorized_locations, or FS identities."
        ),
        "flow": "CMS administrative member/role lifecycle is a separate authorization domain from BMS physical Workplace access.",
        "checks": "Identify whether the problem concerns CMS page/action authorization or BMS/FS building access before inspecting roles, accounts, members, and locations.",
        "risk": "Conflating CMS RBAC with physical Workplace permission leads to incorrect access fixes and unsafe assumptions.",
        "missing": "No direct CMS InviteMember -> BMS member/FS identity integration was proven by the cited service code.",
        "sources": "cms/app/src/components/role/member/member-upsert.tsx:1-730; cms/app/src/services/member/service.ts:1-87; cms/app/src/services/member/model.ts:1-119",
    },
    {
        "title": "CMS Building Service implementation boundary",
        "components": "CMS and BMS",
        "evidence": (
            "The inspected CMS Building Service service-request and air-conditioner service files use mock "
            "data. They are not sufficient evidence that the current CMS production UI reads or updates BMS requests."
        ),
        "flow": "CMS mock service -> local/mock response; a real CMS -> BMS integration requires an actual API client path.",
        "checks": "Confirm whether the deployed build replaces the mock, locate the real endpoint/client if present, and capture the network request before attributing a BMS status change to CMS.",
        "risk": "Training the model to claim a CMS-to-BMS production flow from mock code would encode a false architecture relationship.",
        "missing": "The source reviewed here cannot establish the deployed operational update flow.",
        "sources": "cms/app/src/services/buildingservice/servicerequest/service.ts:1-22; cms/app/src/services/buildingservice/acrequest/service.ts:1-69",
    },
    {
        "title": "Member sync operational report",
        "components": "BMS Kafka boundary and Notification",
        "evidence": (
            "Notification has a BMS sync-member report handler that formats report date, total, failure, "
            "success rate, categorized errors, summary, recipients, and an HTML table for email delivery."
        ),
        "flow": "BMS member-sync report event -> Notification report handler -> operational email.",
        "checks": "Verify the exact report event, totals, categorized failures, recipients, rendered template/table, and mail-provider result.",
        "risk": "A report email summarizes synchronization; it does not replace record-level tracing with jobId and traceId.",
        "missing": "The consumer source alone does not establish the exact producer schedule or retry policy.",
        "sources": "notification/src/handlers/bms/sync_member_report_handler.ts:1-29; bms/src/controllers/integrations/fs/members_controller.ts:1-201",
    },
    {
        "title": "Kafka as an asynchronous boundary",
        "components": "BMS and Notification",
        "evidence": (
            "Workplace flows use named Kafka events for member synchronization, visitor email handoff, "
            "service-request notifications, and operational reports. Producer completion and consumer "
            "business completion are separate observable stages."
        ),
        "flow": "Database/API stage -> event producer -> broker -> registered consumer -> handler -> external delivery or state change.",
        "checks": "Use the exact event name and a non-sensitive correlation identifier to verify producer call, broker acknowledgement where available, consumer receipt, handler outcome, and external provider outcome.",
        "risk": "Describing Kafka publication as guaranteed downstream success hides partial failures and retry behavior.",
        "missing": "Do not invent topic mapping, partition key, retry count, idempotency, or dead-letter behavior without their configuration/source.",
        "sources": "bms/src/events/handler_registry.ts:1-24; notification/src/handlers/handler_registry.ts:1-93; notification/src/server.ts:1-74",
    },
    {
        "title": "Cache invalidation after identity changes",
        "components": "BMS MemberService and IAM event handlers",
        "evidence": (
            "The member sync, offboarding, and IAM external-identity linkage paths clear relevant caches "
            "after changing member identity or authorization relationships."
        ),
        "flow": "Identity/access database mutation -> cache eviction -> next APP/BMS read observes updated context.",
        "checks": "Confirm transaction success, exact cache key/eviction call, subsequent cache miss, database reload, and APP state refresh.",
        "risk": "A correct database update can appear ineffective when stale member or permission data remains cached or in APP state.",
        "missing": "The cited paths do not prove cache eviction for every unrelated administrative write path.",
        "sources": "bms/src/services/member_service.ts:313-640; bms/src/events/iam/external_identity_handler.ts:1-128; bms/src/events/iam/account_handler.ts:1-26",
    },
    {
        "title": "Workplace service ownership map",
        "components": "APP, IAM, BMS, CMS, FS, Document API, TCC AQI, Kafka, and Notification",
        "evidence": (
            "APP composes the user journey; IAM owns authenticated account identity; BMS owns Workplace "
            "member, tenant, location, visitor, command, sensor, and service-request orchestration; FS owns "
            "external building identity/access operations; CMS owns back-office/content UI; Notification "
            "turns supported events into messages; Document API stores What’s Happening content; TCC supplies AQI."
        ),
        "flow": "APP routes by feature to BMS or content APIs; BMS integrates synchronously with FS/TCC and asynchronously with Notification where source proves an event.",
        "checks": "Classify the failing capability first, then follow only the owning API and its proven downstream dependencies.",
        "risk": "Treating Workplace as one monolithic service produces incorrect escalation, monitoring, and root-cause conclusions.",
        "missing": "A service ownership map does not prove runtime availability or a completed transaction.",
        "sources": "mobile-app/app/OneBangkok/src/states/buildingAccess/member.ts:1-337; bms/src/controllers/members_controller.ts:1-251; cms/app/src/services/what-happening/service.ts:1-224; notification/src/handlers/handler_registry.ts:1-93",
    },
]


MODES = (
    "explain",
    "flow",
    "debug",
    "analyse",
    "qa",
    "security",
    "ownership",
    "failure-isolation",
)

AUDIENCES = (
    "a mobile developer",
    "a BMS developer",
    "a CMS developer",
    "a Notification developer",
    "a QA engineer",
    "a product owner",
    "an operations engineer",
    "a solution architect",
)

LENSES = (
    "identifier and identity mapping",
    "Tenant and Member authorization boundaries",
    "production observability and correlation",
    "database, cache, and client-state consistency",
    "external-system and asynchronous success boundaries",
    "safe recovery and regression prevention",
)


def is_generic_workplace_record(row: dict[str, object]) -> bool:
    """Remove only the old broad generator output, not curated feature records."""
    instruction = str(row.get("instruction", "")).casefold()
    input_value = str(row.get("input", "")).casefold()
    return (
        "feature selection evidence: workplace, permission" in input_value
        and "workplace role management" in instruction
    )


def is_curated_workplace_record(row: dict[str, object]) -> bool:
    return "workplace evidence class: code-proven with explicit evidence limits" in str(
        row.get("input", "")
    ).casefold()


def make_instruction(mode: str, title: str, audience: str, lens: str, variation: int) -> str:
    forms = {
        "explain": (
            "Explain {title} in detail for {audience}, including identifiers, service boundaries, and evidence limits.",
            "Give {audience} a source-grounded explanation of {title} without assuming unverified runtime behavior.",
        ),
        "flow": (
            "Trace the end-to-end flow for {title} for {audience}; separate synchronous calls, database work, external integrations, and Kafka handoffs.",
            "Describe how {title} moves across the proven components and where each success boundary ends.",
        ),
        "debug": (
            "Debug a reported problem around {title} using only the supplied code evidence; no runtime log has been provided.",
            "Provide a production debugging plan for {title} without inventing an error, endpoint, or successful downstream result.",
        ),
        "analyse": (
            "Analyse {title} as a Workplace architecture and data-consistency concern for {audience}.",
            "Review the implementation evidence, limitations, and operational implications of {title}.",
        ),
        "qa": (
            "Design detailed source-backed QA coverage for {title}, including positive, negative, boundary, and cross-service cases.",
            "Explain how QA should validate {title} without treating a structural code relationship as runtime proof.",
        ),
        "security": (
            "Perform a security and authorization review of {title} using the current Workplace source evidence.",
            "Identify the trust boundaries and least-privilege checks relevant to {title}; do not claim an exploit without reproduction.",
        ),
        "ownership": (
            "Clarify service ownership and escalation responsibility for {title} for {audience}.",
            "Map each proven responsibility in {title} to APP, BMS, CMS, IAM, FS, Kafka, or Notification as applicable.",
        ),
        "failure-isolation": (
            "Explain how to isolate partial failures in {title} across every proven service boundary.",
            "Create an evidence-first failure-isolation guide for {title}, distinguishing accepted requests from completed downstream work.",
        ),
    }
    base = forms[mode][variation % len(forms[mode])].format(title=title, audience=audience)
    return f"{base} Focus specifically on {lens}."


def make_output(mode: str, scenario: dict[str, str], audience: str, lens: str) -> str:
    title = scenario["title"]
    evidence = scenario["evidence"]
    flow = scenario["flow"]
    checks = scenario["checks"]
    risk = scenario["risk"]
    missing = scenario["missing"]
    sources = scenario["sources"]

    if mode in {"explain", "flow", "ownership"}:
        emphasis = {
            "explain": "The explanation must keep identity, authorization, feature eligibility, and delivery outcome as separate concepts.",
            "flow": "Each arrow describes a code-supported handoff; it is not proof that a production transaction completed every arrow.",
            "ownership": "Escalate the issue to the owner of the first boundary whose input is present but whose expected output is absent.",
        }[mode]
        return (
            f"## Source-Backed Explanation\n\n{evidence}\n\n"
            f"## End-to-End Flow\n\n`{flow}`\n\n{emphasis}\n\n"
            f"## Responsibilities and Validation\n\nThe requested analytical lens is **{lens}**. "
            f"For {audience}, the practical validation is: {checks} "
            f"The principal engineering risk is: {risk}\n\n"
            f"## Evidence Boundary\n\n{missing}\n\nSource: {sources}."
        )

    if mode in {"debug", "failure-isolation"}:
        return (
            "## 【Root Cause Analysis】\n\n"
            f"No runtime log, stack trace, request identifier, or production response is supplied, so no root cause is confirmed. "
            f"The requested analytical lens is **{lens}**. The code-proven behavior for {title} is: {evidence} The supported flow is `{flow}`. "
            f"A failure can occur at any transition; success at one transition must not be used as proof of the next.\n\n"
            "## 【Step-by-Step Debugging Guide】\n\n"
            f"1. Establish the exact account, member, location, feature, request, event, or external identifier relevant to this flow without logging tokens or personal content.\n"
            f"2. Validate the first boundary using the cited source. {checks}\n"
            "3. Compare persisted state with the response returned to the caller; do not infer database success from a UI state.\n"
            "4. If Kafka is present in this flow, confirm producer execution, exact event name, consumer receipt, handler result, and external delivery separately.\n"
            "5. If FS, TCC, email, or another external system is present, retain the sanitized request mapping, response status, and correlation data.\n"
            f"6. Reproduce the boundary associated with this risk: {risk}\n\n"
            "## 【Production-Grade Fix】\n\n"
            "Do not prescribe a behavioral code change until the failing boundary is reproduced. Add correlation-safe observability, "
            "preserve server-side authorization, keep database and asynchronous delivery results distinct, and add a regression test at the confirmed boundary. "
            f"Evidence limit: {missing}\n\nSource: {sources}."
        )

    if mode == "qa":
        return (
            f"## Test Objective\n\nValidate {title}, with emphasis on **{lens}**, against this code-proven behavior: {evidence}\n\n"
            f"## Test Matrix\n\n"
            f"1. Happy path: provide valid identifiers and prerequisites and verify every observable stage in `{flow}`.\n"
            "2. Identity negative case: use a valid IAM account without the required linked Workplace member or external identity.\n"
            "3. Authorization boundary: test access inside the effective tenant/member scope and outside that scope.\n"
            "4. Stale-state case: change the underlying member or permission data and verify cache eviction plus APP refresh behavior.\n"
            "5. Dependency failure: fail the proven external or asynchronous boundary and confirm the upstream state is represented accurately.\n"
            "6. Idempotency/retry observation: repeat the request or event only where the implementation contract permits it; do not assume broker policy.\n"
            f"7. Evidence assertions: {checks}\n\n"
            f"## Acceptance and Non-Claims\n\nThe test must detect this risk: {risk} "
            f"It must not claim the following without additional source/runtime evidence: {missing}\n\nSource: {sources}."
        )

    if mode == "security":
        return (
            f"## Security Model\n\nThe requested review lens is **{lens}**. {evidence}\n\nThe supported data/control path is `{flow}`. "
            "Treat APP input, path identifiers, body identifiers, Kafka payloads, and external-system mappings as separate trust boundaries.\n\n"
            "## Review Procedure\n\n"
            "1. Authenticate the caller at the owning API boundary.\n"
            "2. Resolve the authoritative BMS member from server-controlled identity context where applicable.\n"
            "3. Enforce Tenant authorization as a ceiling and Member authorization as the narrower effective scope.\n"
            "4. Validate that requested locations, floors, records, and recipients belong to that effective scope.\n"
            "5. Avoid logging access tokens, visitor data, email content, or external credentials; use sanitized identifiers and correlation ids.\n"
            f"6. Verify the actual implementation with this evidence check: {checks}\n\n"
            f"## Finding and Limit\n\nRisk: {risk} This is a review finding, not proof of exploitation. "
            f"Evidence limit: {missing}\n\nSource: {sources}."
        )

    return (
        f"## Architecture Finding\n\nAnalytical lens: **{lens}**. {evidence}\n\n"
        f"## Data and Control Flow\n\n`{flow}`\n\n"
        f"## Operational Analysis\n\nValidation should proceed as follows: {checks} "
        f"The principal risk is: {risk}\n\n"
        f"## What Cannot Be Concluded\n\n{missing} This distinction prevents documentation, graph edges, or UI behavior from being presented as proof of a completed runtime transaction.\n\n"
        f"Source: {sources}."
    )


def make_record(index: int) -> dict[str, str]:
    scenario = SCENARIOS[index % len(SCENARIOS)]
    cycle = index // len(SCENARIOS)
    mode = MODES[cycle % len(MODES)]
    audience = AUDIENCES[(cycle // len(MODES) + index) % len(AUDIENCES)]
    lens = LENSES[(cycle // (len(MODES) * 2)) % len(LENSES)]
    instruction = make_instruction(mode, scenario["title"], audience, lens, cycle // len(MODES))
    input_value = (
        f"Component/Service Name: {scenario['components']}\n\n"
        "Workplace Evidence Class: Code-proven with explicit evidence limits\n\n"
        "Exact Runtime Log or Stack Trace: No runtime log or stack trace is supplied. Do not invent one.\n\n"
        f"Actual Code Evidence: {scenario['evidence']}\n\n"
        f"Supported Flow: {scenario['flow']}\n\n"
        f"Requested Analysis Lens: {lens}\n\n"
        "Grounding Rule: Use source and graph relationships only to establish the cited structure. "
        "Do not convert a UI condition, graph edge, event publication, or external API call into proof of downstream runtime success.\n\n"
        f"Exact Source Location: {scenario['sources']}"
    )
    return {
        "instruction": instruction,
        "input": input_value,
        "output": make_output(mode, scenario, audience, lens),
    }


def signature(row: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/sft_data.jsonl")
    parser.add_argument("--count", type=int, default=1200)
    args = parser.parse_args()
    if args.count < len(SCENARIOS) * len(MODES):
        raise SystemExit(f"--count must be at least {len(SCENARIOS) * len(MODES)} to cover every scenario and mode")

    path = Path(args.dataset)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    retained = [
        row for row in rows
        if not is_generic_workplace_record(row) and not is_curated_workplace_record(row)
    ]

    generated: list[dict[str, str]] = []
    seen: set[str] = set()
    for index in range(args.count):
        row = make_record(index)
        row_signature = signature(row)
        if row_signature in seen:
            raise SystemExit(f"duplicate generated record at index {index}")
        seen.add(row_signature)
        generated.append(row)

    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in retained + generated),
        encoding="utf-8",
    )
    print(json.dumps({
        "removed_generic_workplace_records": len(rows) - len(retained),
        "added_source_backed_workplace_records": len(generated),
        "scenario_count": len(SCENARIOS),
        "mode_count": len(MODES),
        "total_records": len(retained) + len(generated),
    }))


if __name__ == "__main__":
    main()
