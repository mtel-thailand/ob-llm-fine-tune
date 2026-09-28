#!/usr/bin/env python3
"""Add detailed, source-grounded Notification knowledge to the SFT dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


COMMIT = "c988bcb415cf79f36afc0b7d50be0f99f91f61b9"

# Every fact below was checked against the current Notification repository.  Keep
# facts atomic so generated questions teach one reliable concept at a time rather
# than encouraging the model to invent an end-to-end flow from unrelated files.
FACTS = [
    {
        "title": "service responsibility",
        "components": "Notification, PostgreSQL, Kafka, and delivery providers",
        "fact": "Notification is both a persistent message-inbox service and a multi-channel delivery orchestrator. It consumes domain events, stores recipient messages, applies per-notification-group settings, and dispatches through push, email, SMS, or WebSocket adapters.",
        "flow": "REST or Kafka input -> handler/controller -> MessageService -> PostgreSQL message -> enabled delivery channels.",
        "checks": "Separate message persistence, channel eligibility, provider submission, and user-visible delivery; they are different success boundaries.",
        "risk": "Treating an HTTP 200 or a stored message as proof of provider delivery creates false-positive incident conclusions.",
        "limit": "The source does not provide end-device delivery receipts for every provider.",
        "sources": "notification/src/app.ts:1-57; notification/src/services/message_service.ts:555-863; notification/db/schema.prisma:139-246",
    },
    {
        "title": "Kafka consumer dispatch",
        "components": "IAM, BMS, Booking, Parking, Kafka, and Notification",
        "fact": "server.ts subscribes consumer group ob-notification to explicit IAM, BMS, Booking, Parking, and SSO topics. handler_registry.ts maps each exact event name to a bound handler method.",
        "flow": "Producer service -> Kafka topic named by the domain event -> ob-notification consumer -> eventHandlers[event.name] -> domain handler.",
        "checks": "Verify the exact event name, producer acknowledgement, consumer-group lag, handler registration, payload contract, and handler completion in that order.",
        "risk": "A similarly named event is not handled unless it is both subscribed and registered.",
        "limit": "Registration proves an intended route, not that a particular production event was delivered.",
        "sources": "notification/src/server.ts:1-74; notification/src/handlers/handler_registry.ts:1-93",
    },
    {
        "title": "async Kafka completion boundary",
        "components": "Notification Kafka consumer",
        "fact": "The callback passed to EventConsumer.start invokes handler(event, raw) without returning or awaiting the handler promise. The surrounding synchronous try/catch therefore does not reliably observe asynchronous rejection from a handler.",
        "flow": "Kafka callback -> unawaited async handler -> callback can complete before handler work settles.",
        "checks": "Force an async handler rejection, inspect unhandled-rejection logs and offset behavior, then verify that the callback awaits and propagates the promise.",
        "risk": "The consumer may advance while persistence or provider dispatch is still failing, and its try/catch may not log the real error.",
        "limit": "Source establishes the missing await; production message-loss behavior still requires Kafka runtime and offset evidence.",
        "sources": "notification/src/server.ts:50-73; notification/src/utils/kafka/ob_event.ts:105-181",
    },
    {
        "title": "recipient projection from IAM",
        "components": "IAM, Kafka, and Notification RecipientService",
        "fact": "Notification keeps a local recipient projection keyed by account_id and optional sso_id. IAM events update profile, identities, device data, push token, language/settings, account lifecycle, and combined device-token state.",
        "flow": "IAM authoritative mutation -> ob-iam event -> Notification IAM handler -> recipient JSON or setting rows.",
        "checks": "Compare IAM source state, event payload, consumer processing, recipient.data, setting rows, and timestamps without logging identity or token values.",
        "risk": "A missed or out-of-order event can leave Notification routing with a stale email, phone, device, token, or preference.",
        "limit": "Notification's recipient row is a delivery projection, not the authoritative IAM account.",
        "sources": "notification/src/handlers/handler_registry.ts:1-93; notification/src/services/recipient_service.ts:1-455; notification/db/schema.prisma:139-154",
    },
    {
        "title": "recipient bootstrap",
        "components": "Notification RecipientService, notification groups, and target groups",
        "fact": "Creating a recipient initializes one setting row for every notification group and adds the recipient to the target group named all.",
        "flow": "account-created event -> recipient create -> notification-group settings create -> all target-group membership.",
        "checks": "Verify the recipient row, count of active notification groups, generated settings, existence of the all group, and target_group_member row.",
        "risk": "The create path assumes the all target group exists; missing seed data can break recipient bootstrap.",
        "limit": "Membership in all does not mean every channel is enabled or that every campaign targets that group.",
        "sources": "notification/src/services/recipient_service.ts:1-120; notification/db/schema.prisma:110-154; notification/db/schema.prisma:218-246",
    },
    {
        "title": "per-group channel selection",
        "components": "Notification MessageService and recipient settings",
        "fact": "sendMessage reads the setting associated with the message template's notification group. SMS, email, in-app WebSocket, and push are independently gated by sms_enabled, email_enabled, in_app_enabled, and push_enabled.",
        "flow": "message template -> notification group -> recipient setting -> channel-specific identity/device/token lookup -> adapter.",
        "checks": "Inspect the template group, recipient setting row, default identity, device_unique_id, push token value/type, and the selected adapter.",
        "risk": "Checking only push_enabled misses absent tokens, and checking only a token misses a disabled group setting.",
        "limit": "An enabled setting means eligible to attempt delivery, not delivered.",
        "sources": "notification/src/services/message_service.ts:776-863; notification/db/schema.prisma:218-246",
    },
    {
        "title": "auto-message creation",
        "components": "Kafka domain handler, auto_message, message_template, recipient, and MessageService",
        "fact": "autoMessageCreate resolves an auto_message by event name, loads its template, finds the recipient by account_id, personalizes multilingual template data, persists one message, and starts channel dispatch. Booking approved, declined, and auto-cancellation events are normalized to the booking-updated template lookup.",
        "flow": "domain event -> auto_message event mapping -> template personalization -> message row -> sendMessage.",
        "checks": "Verify event normalization, auto_message configuration, template/group relation, account recipient, replacement values, message insert, and each channel separately.",
        "risk": "Missing configuration can make a valid upstream event produce no usable user message.",
        "limit": "Template lookup and message insertion do not prove push/email/WebSocket delivery.",
        "sources": "notification/src/services/message_service.ts:555-668; notification/db/schema.prisma:31-52; notification/db/schema.prisma:196-208",
    },
    {
        "title": "direct individual notification API",
        "components": "Calling service and Notification REST API",
        "fact": "POST /notifications/send resolves recipient and template, personalizes content/title, creates a message, and delegates channel delivery through sendMessage.",
        "flow": "caller -> /notifications/send -> recipient/template lookup -> message create -> enabled channels.",
        "checks": "Validate account_id, template id, replacement payload, recipient existence, message id, group settings, and provider response.",
        "risk": "A boolean result should not be interpreted as an end-device delivery receipt.",
        "limit": "No runtime request or provider receipt is supplied, so a specific incident outcome cannot be asserted.",
        "sources": "notification/src/controllers/notifications_controller.ts:1-52; notification/src/services/message_service.ts:670-724",
    },
    {
        "title": "bulk notification API",
        "components": "Calling service and Notification bulk delivery",
        "fact": "POST /notifications/send-bulk supports persistent messages plus push, in-app WebSocket, and email processing for multiple recipients; its controller explicitly does not support SMS and invokes the bulk service without awaiting completion.",
        "flow": "bulk request -> immediate controller response -> asynchronous recipient/template processing -> message rows -> eligible channels.",
        "checks": "Distinguish request acceptance from background completion; inspect recipient selection, createMany result, language grouping, WebSocket, email, and multicast outcomes.",
        "risk": "The caller can receive success before the bulk operation fails, and retrying without idempotency can duplicate messages.",
        "limit": "The route's response does not prove all recipients were processed.",
        "sources": "notification/src/controllers/notifications_controller.ts:1-52; notification/src/services/message_service.ts:1510-1830",
    },
    {
        "title": "persistent inbox versus real-time delivery",
        "components": "APP, Notification PostgreSQL, and WebSocket service",
        "fact": "The message table is the durable APP inbox. WebSocket broadcast is a separate real-time path, and push is a third OS-level path. A WebSocket failure does not erase an already persisted message.",
        "flow": "message insert -> APP can fetch /me/message; separately -> WebSocket live event; separately -> FCM/HMS push.",
        "checks": "Query the message row first, then test /me/message serialization, device WebSocket targeting, and push provider independently.",
        "risk": "Conflating the three paths causes teams to debug FCM when only live UI refresh failed, or vice versa.",
        "limit": "Persistence does not prove the APP refreshed or displayed the record.",
        "sources": "notification/src/controllers/message_controller.ts:1-280; notification/src/adapters/websocket_adapter.ts:1-17; notification/db/schema.prisma:155-174",
    },
    {
        "title": "message inbox ownership and lifecycle",
        "components": "APP and Notification MessageController",
        "fact": "The APP-facing message routes list and retrieve messages by recipient account context, support read/unread changes and soft deletion through deleted_at, expose the latest approved-sent announcement, and rebroadcast unread count after mutations.",
        "flow": "x-account-id -> recipient-scoped query -> read/unread or soft-delete mutation -> recount -> WebSocket badge update.",
        "checks": "Test cross-account message IDs, deleted_at filtering, read state, category/date filters, pagination, announcement status, and unread broadcast.",
        "risk": "A mutation that filters only by message id can become an IDOR even when list queries are account-scoped.",
        "limit": "Gateway authentication and header provenance are outside the controller excerpt and must be verified separately.",
        "sources": "notification/src/controllers/message_controller.ts:1-280; notification/src/services/message_service.ts:1-555",
    },
    {
        "title": "unread count",
        "components": "Notification database, MessageService, WebSocket, and APP",
        "fact": "Unread count is the count of recipient messages where read is false and deleted_at is null. MessageService sends notification_counting.updated through WebSocket using the recipient device_unique_id.",
        "flow": "message mutation -> DB unread count -> device-targeted WebSocket broadcast -> APP badge refresh.",
        "checks": "Compare DB count with recipient id, deleted/read flags, device_unique_id, WebSocket endpoint response, and APP state.",
        "risk": "A correct DB count can coexist with a stale APP badge when device identity or WebSocket delivery fails.",
        "limit": "The WebSocket adapter catches errors, so upstream completion is not reliable proof of badge delivery.",
        "sources": "notification/src/services/message_service.ts:1-555; notification/src/adapters/websocket_adapter.ts:1-17",
    },
    {
        "title": "FCM individual push",
        "components": "Notification, Firebase Admin, Android, and iOS",
        "fact": "The FCM service builds notification and data payloads, includes message id and badge count, supplies APNS badge/sound and Android channel/count/sound, and returns null when its caught send operation fails.",
        "flow": "eligible FCM token -> Firebase Admin message -> provider response or caught failure.",
        "checks": "Inspect token type, message id, title/body, badge, platform payload, Firebase response, and caught-error log using redacted token fingerprints.",
        "risk": "A swallowed provider error can leave the caller unable to distinguish delivery submission failure.",
        "limit": "Firebase acceptance is not proof the user saw the notification.",
        "sources": "notification/src/services/fcm_messages_service.ts:1-138; notification/src/utils/notification_adapter.ts:1-83",
    },
    {
        "title": "FCM multicast batching",
        "components": "Notification campaign/bulk path and Firebase Admin",
        "fact": "FCM multicast groups work into chunks of at most 500 tokens, uses sendEach, and produces per-recipient success information. Failed-token logging currently includes token values.",
        "flow": "recipient data -> token chunks <= 500 -> Firebase sendEach -> per-token result mapping.",
        "checks": "Verify chunk boundaries, duplicate tokens, per-token result order, partial failure handling, retry policy, and redacted logs.",
        "risk": "Retrying an entire partially successful batch can duplicate successful sends; logging raw tokens exposes credentials/PII-like identifiers.",
        "limit": "The implementation result is provider submission status, not notification-open analytics.",
        "sources": "notification/src/services/fcm_messages_service.ts:1-138; notification/src/config/chunk_sizes.ts:1-20",
    },
    {
        "title": "Huawei push routing",
        "components": "Notification Adapter and Huawei Push Kit",
        "fact": "notificationAdapter routes tokenType hms to Huawei and other token types to FCM. Huawei obtains and caches an OAuth token, renews it before expiry, limits concurrent sends, and clamps badge values to 0-99.",
        "flow": "HMS recipient token -> cached/renewed Huawei access token -> rate-limited provider request.",
        "checks": "Verify normalized token type, client configuration, token expiry buffer, concurrency behavior, badge clamp, and provider response.",
        "risk": "Raw recipient token logging in success/error paths leaks a reusable device routing identifier.",
        "limit": "Huawei API success does not prove display on the handset.",
        "sources": "notification/src/utils/notification_adapter.ts:1-83; notification/src/services/huawei_push_message_service.ts:1-165",
    },
    {
        "title": "email provider selection and templates",
        "components": "Notification MessageService, ConnectX, AWS SES, and HTML templates",
        "fact": "sendEmail loads an event-specific HTML file, loads translations, preprocesses replacements, substitutes placeholders, and uses ConnectX for OTP events while using AWS SES for other email events.",
        "flow": "event name -> EMAIL_TEMPLATE mapping -> HTML/translation replacement -> OTP to ConnectX or other email to SES.",
        "checks": "Verify template mapping/file existence, language file, replacement keys, subject, recipient list, provider branch, and provider response without exposing sensitive values.",
        "risk": "Missing placeholders can produce malformed email, while caught provider errors can still leave upstream code appearing successful.",
        "limit": "Template rendering does not prove inbox placement or that a recipient opened the email.",
        "sources": "notification/src/services/message_service.ts:943-1144; notification/src/services/aws_service.ts:1-64; notification/src/templates/OB_email",
    },
    {
        "title": "sensitive delivery logging",
        "components": "Notification email and push providers",
        "fact": "The inspected source logs replacement payloads, some recipient email/provider payload data, and push tokens in several success or failure paths. OTP replacement data can include code/reference values.",
        "flow": "delivery preparation/provider result -> application logger -> centralized logs.",
        "checks": "Search production-safe logs for replacement payloads, email addresses, phone numbers, invitation links, OTP data, FCM/HMS tokens, and provider credentials.",
        "risk": "Operational logs can become a secondary store of secrets and personal data.",
        "limit": "Source presence does not establish which log level or sink is enabled in a specific deployment.",
        "sources": "notification/src/services/message_service.ts:980-1144; notification/src/services/fcm_messages_service.ts:1-138; notification/src/services/huawei_push_message_service.ts:1-165",
    },
    {
        "title": "visitor-pass invitation email",
        "components": "BMS, Kafka, Notification, and visitor email",
        "fact": "For ob-bms.visitor_pass.created, the handler passes account_id, visitor_email, invitation_link, and tower_name to MessageService. Notification resolves the inviter's name/language and sends an event-specific email to visitor_email.",
        "flow": "BMS pass creation -> Kafka event -> visitorHandler -> inviter recipient lookup -> HTML replacement -> SES email.",
        "checks": "Trace the exact event payload, inviter recipient, language, template file, invitation_link replacement, visitor address, and SES result.",
        "risk": "A missing inviter projection can degrade personalization even when BMS created the pass correctly.",
        "limit": "The reviewed Notification path sends an invitation link; QR generation/attachment and turnstile acceptance are not proven here.",
        "sources": "notification/src/handlers/bms/visitor_handler.ts:1-65; notification/src/services/message_service.ts:943-1025; notification/src/utils/qr_generate.ts:1-30",
    },
    {
        "title": "visitor-arrival notification",
        "components": "BMS visitor domain and Notification",
        "fact": "For ob-bms.visitor.visited, Notification extracts the issuer account_id and visitor name from payload.pass[0], then creates an automatic message for the inviter.",
        "flow": "BMS visit observation -> visitor.visited event -> inviter account -> auto-message mapping -> inbox/channels.",
        "checks": "Verify that pass is a non-empty array, issuer account_id, nested visitor name, auto-message configuration, recipient row, and created message.",
        "risk": "The handler directly indexes pass[0]; an empty or schema-incompatible payload can fail before message creation.",
        "limit": "The event proves BMS reported a visit, not the complete physical-access decision inside FS.",
        "sources": "notification/src/handlers/bms/visitor_handler.ts:1-37; notification/src/services/message_service.ts:555-668",
    },
    {
        "title": "BMS service-request notifications",
        "components": "BMS, Kafka, Notification, requester, and admin email",
        "fact": "ob-bms.service_request.created produces an admin email using issue type, title, reference, and status. ob-bms.service_request_status.updated creates an auto message for requester.account_id.",
        "flow": "BMS create -> admin email path; BMS status update -> requester auto-message path.",
        "checks": "Confirm which of the two events occurred, requester account projection, admin recipient configuration, replacement fields, template, message persistence, and provider result.",
        "risk": "Debugging the status-update inbox path as though it were the create-time admin-email path examines the wrong recipient and channel.",
        "limit": "The handler does not prove the BMS transaction that produced the event.",
        "sources": "notification/src/handlers/bms/service_request.handler.ts:1-45",
    },
    {
        "title": "Booking admin email flow",
        "components": "Booking, Kafka, Notification, CMS, and operations email",
        "fact": "Amenity booking created/cancelled events are converted to Bangkok date/time and sent to booking-admin recipients with room name, booking code, date, time, and a CMS detail URL. The URL uses the event value or a CMS_URL/CMS_VIEW_BOOKING_PATH fallback.",
        "flow": "Booking event -> amenity handler -> timezone formatting -> admin email template -> SES.",
        "checks": "Verify event payload fields, timezone input, formatted value, recipientEmails, CMS URL construction, template, and SES response.",
        "risk": "Calling split on an absent replaceValue.recipientEmails occurs before the environment fallback and can throw.",
        "limit": "The email handler does not prove that the Booking database mutation committed or that CMS can open the URL.",
        "sources": "notification/src/handlers/booking/amenity_booking_handler.ts:1-104; notification/src/services/message_service.ts:900-942",
    },
    {
        "title": "Booking lifecycle user messages",
        "components": "Booking, Kafka, Notification, and APP inbox",
        "fact": "Booking approved, declined, autoCancellation, and updated handlers build bilingual replacement values and call autoMessageCreate for accountId. Auto-cancellation varies wording for workplace versus retail, and updated includes formatted changed date/time.",
        "flow": "Booking lifecycle event -> bilingual payload -> auto-message/template -> persisted account message -> enabled channels.",
        "checks": "Verify accountId, roomName languages, bookingId, type branch, date/time, event-template mapping, recipient setting, and delivery adapter.",
        "risk": "A correct Booking state can coexist with a missing Notification template or stale recipient projection.",
        "limit": "Approved text references access to a QR code through booking details, but these sources do not prove QR rendering or validation.",
        "sources": "notification/src/handlers/booking/amenity_booking_handler.ts:91-216; notification/src/services/message_service.ts:555-668",
    },
    {
        "title": "Booking Kafka health handshake",
        "components": "Booking, Kafka, and Notification",
        "fact": "When Notification consumes ob-booking.amenity_booking.health.sent, it publishes ob-booking.amenity_booking.health.received with an empty payload.",
        "flow": "Booking health.sent -> Notification handler -> Booking health.received.",
        "checks": "Inspect both topics, timestamps, correlation strategy, producer errors, and consumer lag; do not use unrelated delivery-provider health as a substitute.",
        "risk": "Because the producer call is not awaited in the handler, a log of handler entry does not prove the acknowledgement event reached Kafka.",
        "limit": "This handshake tests the event path, not PostgreSQL, FCM, SES, SNS, or WebSocket health.",
        "sources": "notification/src/handlers/booking/amenity_booking_handler.ts:1-31; notification/src/handlers/handler_registry.ts:75-90",
    },
    {
        "title": "campaign lifecycle",
        "components": "CMS/operations, Notification CampaignController, and CampaignService",
        "fact": "Campaigns progress through DRAFT, WATING_FOR_APPROVAL, APPROVED_SCHEDULED, APPROVED_SENT, or REJECTED. Submit and approve/reject record transitions; sent() processes due campaigns, rejects overdue waiting campaigns, and sends approved scheduled campaigns.",
        "flow": "create draft -> submit -> approve or reject -> scheduled_at due -> recipient processing -> APPROVED_SENT.",
        "checks": "Verify current status, scheduled_at, transition history, actor account, target group, template, push data, and sent-job invocation.",
        "risk": "WATING_FOR_APPROVAL is the actual misspelled enum value; renaming it without a coordinated migration breaks persisted/API compatibility.",
        "limit": "APPROVED_SENT is application workflow state, not proof every provider delivered every notification.",
        "sources": "notification/db/schema.prisma:63-97; notification/src/controllers/v2/campaigns_controller.ts:1-352; notification/src/services/campaign_service.ts:313-536",
    },
    {
        "title": "campaign target resolution",
        "components": "Campaign, target_group, target_group_member, and recipient",
        "fact": "A campaign links to one or more target groups through campaign_target_group; target_group_member links each group to local recipient rows. Delivery publicIds are first resolved against recipient.sso_id and merged into accountIds before a target group can be created.",
        "flow": "campaign -> campaign_target_group -> target_group -> target_group_member -> recipient.",
        "checks": "Inspect duplicate accounts, missing sso_id matches, soft-deleted recipients, group membership, and final distinct account list.",
        "risk": "A correct campaign can reach no one when IAM projection or target-group membership is stale.",
        "limit": "Group membership establishes selection, not channel eligibility or provider delivery.",
        "sources": "notification/db/schema.prisma:74-138; notification/src/controllers/v2/campaigns_controller.ts:268-328",
    },
    {
        "title": "campaign batching and cursor correctness",
        "components": "Notification CampaignService, PostgreSQL, and push adapters",
        "fact": "Campaign processing pages target-group members in chunks of 2,000, divides provider token work into chunks of 500, and groups unread-count queries up to 10,000 identifiers. Cursor ordering is used to avoid losing the 2,001st or 100,001st record at a page boundary.",
        "flow": "due campaign -> ordered member cursor pages -> token chunks -> message/unread/transaction batches -> multicast.",
        "checks": "Test 0, 1, 499, 500, 501, 1,999, 2,000, 2,001, duplicates, and partial provider failures while comparing selected, inserted, attempted, and successful counts.",
        "risk": "Offset pagination over a set mutated by transaction creation can skip records; a single oversized createMany can exceed database parameter limits.",
        "limit": "Benchmark test presence is not a production performance guarantee for a different database or provider quota.",
        "sources": "notification/src/config/chunk_sizes.ts:1-20; notification/src/services/campaign_service.ts:313-848; notification/tests/services/message_service.test.ts:1-286",
    },
    {
        "title": "campaign message transaction semantics",
        "components": "CampaignService, message, and message_transaction",
        "fact": "Campaign push paths create one message per recipient and use message_transaction rows as an idempotency marker for messages queued/sent through the push path. Subsequent sendingMessage queries exclude messages that already have transactions.",
        "flow": "campaign message -> eligible push attempt -> message_transaction -> excluded on later run.",
        "checks": "Compare message rows, eligible tokens/settings, provider results, transaction rows, and retry selection; distinguish messages with no eligible push.",
        "risk": "Writing a transaction before a confirmed provider result can suppress a needed retry, while writing only after success can duplicate sends if the process crashes between provider acceptance and DB write.",
        "limit": "message_transaction is not an email/WebSocket receipt and is not proof that a device displayed the push.",
        "sources": "notification/src/services/message_service.ts:396-517; notification/src/services/campaign_service.ts:625-848; notification/db/schema.prisma:155-193",
    },
    {
        "title": "bulk email privacy and throttling",
        "components": "Notification MessageService and AWS SES",
        "fact": "Bulk email groups recipients by language, sends each address separately to avoid exposing the recipient list, processes batches of ten, and waits one second between batches because the source documents a 14-per-second SES quota assumption.",
        "flow": "eligible email recipients -> language groups -> batches of ten -> individual SES requests -> one-second pacing.",
        "checks": "Verify default email identities, language grouping, batch timing, partial failures, provider quota, and that no multi-recipient To list is exposed.",
        "risk": "A controller that returns before this work finishes hides late quota or template failures from the caller.",
        "limit": "The hard-coded pacing assumption may not equal the quota of every deployment account.",
        "sources": "notification/src/services/message_service.ts:1786-1830; notification/src/controllers/notifications_controller.ts:1-52",
    },
    {
        "title": "authorization trust boundary",
        "components": "Gateway and Notification Authorizer",
        "fact": "Authorizer base64-decodes x-permissions and checks resource_type/actions. It does not cryptographically verify the header inside Notification. The campaign delivery route explicitly applies this middleware, while equivalent controller-level middleware is not visible on every campaign route.",
        "flow": "trusted gateway should validate identity -> replace client headers -> Notification decodes permissions -> route action check.",
        "checks": "Confirm direct-network exposure, gateway header stripping, JWT verification upstream, route-by-route middleware, wildcard semantics, and forged-header tests.",
        "risk": "If clients can reach Notification directly or preserve their own x-permissions header, Base64 is not an authorization control.",
        "limit": "Absence of controller middleware does not prove a public vulnerability when infrastructure or generated global middleware may enforce access.",
        "sources": "notification/src/middlewares/authorizer.ts:1-35; notification/src/controllers/v2/campaigns_controller.ts:268-328",
    },
    {
        "title": "template-processing failure visibility",
        "components": "MessageService template processing and callers",
        "fact": "processMessages catches template-processing exceptions and returns empty content structures rather than propagating the failure. sendEmail also catches provider errors and returns without a delivery result.",
        "flow": "invalid replacement/template or provider error -> caught/logged -> empty/void result -> caller can continue.",
        "checks": "Inject missing or invalid replacement data, assert the resulting message body, observe caller response, and require structured failure metrics rather than only logs.",
        "risk": "The system can persist or report success for an empty message or failed email.",
        "limit": "The source shows failure masking, not its production frequency.",
        "sources": "notification/src/services/message_service.ts:741-775; notification/src/services/message_service.ts:980-1144",
    },
    {
        "title": "notification observability model",
        "components": "All Notification boundaries",
        "fact": "A useful trace must distinguish event/API acceptance, recipient/template resolution, message persistence, channel eligibility, provider submission, provider result, and APP read/open state. The current code does not consistently expose one durable status spanning all stages.",
        "flow": "correlation id -> ingress -> domain resolution -> DB message id -> per-channel attempt id -> provider result -> optional client telemetry.",
        "checks": "Record non-sensitive identifiers and counters at each boundary, reconcile counts, and never infer a later stage from an earlier one.",
        "risk": "One generic 'notification sent' log cannot localize failure and may leak payload data if teams compensate by logging whole objects.",
        "limit": "This is an architectural recommendation derived from current boundaries, not proof that a central tracing platform is absent.",
        "sources": "notification/src/server.ts:1-74; notification/src/services/message_service.ts:555-863; notification/src/utils/notification_adapter.ts:1-83",
    },
]

EXPLAIN_INTENTS = (
    "Explain the source-backed behavior of",
    "Describe the end-to-end responsibility and boundaries of",
    "Explain to a new engineer how the code implements",
    "Summarize the business and technical meaning of",
    "Explain what is proven and not proven about",
)
DEBUG_INTENTS = (
    "Debug a failure involving",
    "Build a production troubleshooting plan for",
    "Analyse why a user-visible result could fail in",
    "Trace the failure boundaries of",
    "Diagnose an inconsistent state involving",
)
AUDIENCES = (
    "a backend developer",
    "a mobile developer",
    "a QA engineer",
    "an SRE investigating production",
    "a solution architect",
    "an operations engineer",
)
FOCI = (
    "data ownership and identifiers",
    "asynchronous completion and retries",
    "channel eligibility and provider outcome",
    "security and privacy",
    "idempotency and duplicate prevention",
    "cross-service observability",
    "edge cases and test coverage",
    "runtime failure isolation",
)


def signature(item: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def is_prior_curated_notification(item: dict[str, object]) -> bool:
    return "Notification Knowledge Version: source-grounded-v1" in str(item.get("input", ""))


def make_explanation(fact: dict[str, str], intent: str, audience: str, focus: str) -> dict[str, str]:
    return {
        "instruction": f"{intent} Notification {fact['title']} for {audience}, focusing on {focus}. Use only current source evidence.",
        "input": (
            f"Component/Service Name: {fact['components']}\n\n"
            "Scenario Type: Source-backed explanation; no production incident log is supplied.\n\n"
            "Notification Knowledge Version: source-grounded-v1\n\n"
            f"Code-Proven Fact: {fact['fact']}\n\n"
            f"Source-Backed Flow: {fact['flow']}\n\n"
            "Evidence Rule: Do not invent an endpoint, event, provider result, delivery receipt, database mutation, or APP behavior. "
            "A registered relationship is not proof that a particular runtime transaction completed.\n\n"
            f"Repository Commit: {COMMIT}\nExact Source Location: {fact['sources']}"
        ),
        "output": (
            "## Explanation\n\n"
            f"{fact['fact']}\n\n"
            f"The verified execution boundary is: {fact['flow']} The important {focus} point is that each arrow is independently observable; "
            "an earlier successful stage must not be used as evidence that a later stage succeeded.\n\n"
            f"For {audience}, the practical validation is: {fact['checks']}\n\n"
            f"Production risk: {fact['risk']}\n\n"
            f"Evidence limit: {fact['limit']}\n\n"
            f"Source: {fact['sources']}. Repository commit: {COMMIT}."
        ),
    }


def make_debug(fact: dict[str, str], intent: str, audience: str, focus: str) -> dict[str, str]:
    return {
        "instruction": f"{intent} Notification {fact['title']} for {audience}, with emphasis on {focus}. Do not invent a runtime error.",
        "input": (
            f"Component/Service Name: {fact['components']}\n\n"
            "Exact Runtime Log or Stack Trace: No runtime log, request ID, Kafka offset, message ID, or provider receipt was supplied.\n\n"
            "Notification Knowledge Version: source-grounded-v1\n\n"
            f"Actual Code Evidence: {fact['fact']}\n\n"
            f"Expected Source Flow: {fact['flow']}\n\n"
            f"Repository Commit: {COMMIT}\nExact Source Location: {fact['sources']}"
        ),
        "output": (
            "## 【Root Cause Analysis】\n\n"
            f"No production root cause is confirmed because runtime evidence is absent. The current source proves that {fact['fact']} "
            f"The relevant sequence is {fact['flow']} For {focus}, do not collapse those stages into a single 'sent' state. "
            f"For {audience}, the first responsibility is to establish the last verified boundary before escalating to another service. "
            f"The main code-level risk is: {fact['risk']}\n\n"
            "## 【Step-by-Step Debugging Guide】\n\n"
            "1. Capture a safe correlation identifier, ingress timestamp, exact route or Kafka event name, and responsible account/message/campaign identifier; redact tokens and personal values.\n"
            "2. Verify the upstream producer or REST caller independently from Notification consumer/controller acceptance.\n"
            "3. Confirm recipient and template resolution, notification-group settings, required identity/device/token data, and message persistence.\n"
            "4. Follow only the selected channel into its adapter and provider result; do not use another channel's success as evidence.\n"
            "5. Reconcile attempted, successful, failed, and persisted counts, including retry/idempotency state.\n"
            f"6. Apply the fact-specific check: {fact['checks']}\n"
            f"7. Stop at the evidence boundary: {fact['limit']}\n\n"
            "## 【Production-Grade Fix】\n\n"
            "Do not change production behavior until the failing boundary is reproduced. Preserve source-of-truth ownership, await and propagate asynchronous work where completion is promised, "
            "return an explicit accepted/queued/result status, add idempotency at retryable boundaries, and emit structured redacted metrics for every channel. "
            "Add a regression test at the exact boundary before deploying the smallest verified correction.\n\n"
            f"Source: {fact['sources']}. Repository commit: {COMMIT}."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/sft_data.jsonl")
    parser.add_argument("--count", type=int, default=1000)
    args = parser.parse_args()
    if args.count < len(FACTS) * 2:
        raise SystemExit(f"--count must be at least {len(FACTS) * 2}")

    path = Path(args.dataset)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    retained = [row for row in rows if not is_prior_curated_notification(row)]

    replacement: list[dict[str, str]] = []
    for index in range(args.count):
        pair = index // 2
        fact = FACTS[pair % len(FACTS)]
        cycle = pair // len(FACTS)
        audience = AUDIENCES[cycle % len(AUDIENCES)]
        focus = FOCI[(cycle // len(AUDIENCES)) % len(FOCI)]
        if index % 2:
            replacement.append(make_debug(fact, DEBUG_INTENTS[cycle % len(DEBUG_INTENTS)], audience, focus))
        else:
            replacement.append(make_explanation(fact, EXPLAIN_INTENTS[cycle % len(EXPLAIN_INTENTS)], audience, focus))

    existing = {signature(row) for row in retained}
    additions = [row for row in replacement if signature(row) not in existing]
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in retained + additions),
        encoding="utf-8",
    )
    print(json.dumps({
        "removed_previous_curated_notification_records": len(rows) - len(retained),
        "added_source_grounded_notification_records": len(additions),
        "notification_facts": len(FACTS),
        "total_records": len(retained) + len(additions),
    }))


if __name__ == "__main__":
    main()
