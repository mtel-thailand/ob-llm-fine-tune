#!/usr/bin/env python3
"""Replace broad Authentication records with detailed source-grounded IAM SFT data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


S = [
    {
        "title": "IAM authentication entry points",
        "components": "APP and IAM AuthController",
        "fact": "IAM exposes login, resident-iPad login, logout, register, reactivate, renew, and SSO validation operations. AuthController delegates account authentication and token lifecycle behavior to AuthService or AccountService.",
        "flow": "APP request -> IAM AuthController -> AuthService/AccountService -> typed response or CustomError.",
        "check": "Start with the exact route and operation, then identify which service method owns the behavior before following repositories or downstream integrations.",
        "risk": "Treating all auth operations as one login path hides different validation, token, device, and event behavior.",
        "limit": "Controller declarations prove routing and delegation, not the internal transaction behavior of an undigested AccountService implementation.",
        "src": "iam/src/controllers/auth_controller.ts:1-170",
    },
    {
        "title": "composite login strategy selection",
        "components": "IAM AuthService",
        "fact": "AuthService.login resolves an account and selected strategy through ssoIdStrategy, apiKeyStrategy, tokenStrategy, and passwordStrategy. API-key login has a separate existing-token reuse branch and returns FS-building-access metadata.",
        "flow": "Login request -> compositeStrategy -> account plus strategy -> strategy-specific checks -> token result.",
        "check": "Record the submitted provider and credential type, selected strategy, resolved account id, and exact branch without logging the credential.",
        "risk": "Diagnosing a password flow while the request selected SSO, API-key, or token strategy leads to a false root cause.",
        "limit": "The source does not prove which upstream gateway supplied or validated every API key.",
        "src": "iam/src/services/auth_service/index.ts:90-210",
    },
    {
        "title": "blacklist and deleted-account login rejection",
        "components": "IAM AuthService and identity repositories",
        "fact": "After resolving an account, login checks the account blacklist and looks for identities or social external identities connected to a deleted account. Matching conditions stop login before normal token issuance.",
        "flow": "Resolved account -> blacklist lookup -> deleted identity/external-identity lookup -> continue or reject.",
        "check": "Verify account id, blacklist state, account deleted_at state, normalized identifier/provider, and social external-identity ownership.",
        "risk": "A valid password or SSO assertion is insufficient when lifecycle state marks the account unusable.",
        "limit": "Without the actual error response and account state, no production rejection reason can be selected from source alone.",
        "src": "iam/src/services/auth_service/index.ts:121-204",
    },
    {
        "title": "two-factor authentication challenge",
        "components": "IAM AuthService, OTP, and Identity",
        "fact": "When account settings enable 2FA and the selected strategy is password or SSO-id, AuthService validates the supplied OTP. If the challenge is incomplete, IAM returns the default identity of the opposite provider so the caller can continue the OTP flow.",
        "flow": "Primary authentication -> setting lookup -> OTP strategy -> success or alternate default identity challenge.",
        "check": "Verify account setting, selected login strategy, OTP id/reference, opposite-provider default identity, and challenge response separately.",
        "risk": "A missing default alternate identity can block an account whose 2FA setting is enabled.",
        "limit": "The source does not prove successful delivery of the OTP; delivery is a separate SMS or Notification boundary.",
        "src": "iam/src/services/auth_service/index.ts:625-668; iam/src/services/otp_service/index.ts:1-237",
    },
    {
        "title": "access-token issuance and permission claims",
        "components": "IAM AuthService, permission repository, token repository, and cache",
        "fact": "Access-token generation loads attached permissions, creates an HS256 JWT containing sub, iss, iat, exp, and permission, caches token material, and upserts an account/type token record. Issuance fails when no attached permission is available.",
        "flow": "account id -> primary attached-permission lookup -> JWT creation -> cache -> token upsert -> caller.",
        "check": "Verify account id, permission count/content, configured issuer and secret presence, timestamps, token type, cache writes, and repository upsert without exposing token values.",
        "risk": "A stale or empty attached-permission set directly affects newly issued authorization claims.",
        "limit": "JWT creation does not prove that every downstream service validates the token and resource scope correctly.",
        "src": "iam/src/services/auth_service/index.ts:470-554; iam/src/services/auth_service/index.ts:973-1008",
    },
    {
        "title": "refresh-token issuance",
        "components": "IAM AuthService, token repository, and cache",
        "fact": "Refresh-token generation also embeds attached permissions in an HS256 JWT, uses a separately configured expiry, writes a hashed cache entry, and upserts a refresh-token record by account and type.",
        "flow": "account id -> attached permissions -> refresh JWT -> refresh cache -> token repository.",
        "check": "Compare normal and resident-iPad token types, expiry configuration, cache TTL, repository expiry, and permission snapshot.",
        "risk": "A long-lived refresh token preserves a permission snapshot and increases impact if stored or logged insecurely.",
        "limit": "Issuance code alone does not establish device binding, one-time use, or refresh-token rotation.",
        "src": "iam/src/services/auth_service/index.ts:556-607",
    },
    {
        "title": "token validation through cache and repository",
        "components": "IAM AuthService, JWT verification, cache, and token repository",
        "fact": "validateToken removes an optional Bearer prefix, verifies and extracts the JWT subject, compares a hash with cached access/refresh hashes, then falls back to token repository lookup and repopulates cache.",
        "flow": "presented JWT -> signature/expiry verification -> account id -> cache hash check -> repository fallback -> validation result.",
        "check": "Inspect token type, JWT verification result, subject, hash comparison, repository match, and cache repopulation using only fingerprints.",
        "risk": "Mixing access and refresh validation semantics can allow the wrong token class at an endpoint if callers do not enforce intent.",
        "limit": "No token value should be reproduced in a dataset, diagnostic answer, or production log.",
        "src": "iam/src/services/auth_service/index.ts:432-468; iam/src/services/auth_service/index.ts:994-1008",
    },
    {
        "title": "access-token renewal without refresh rotation",
        "components": "APP and IAM AuthService",
        "fact": "IAM renew requires a refresh_token, validates it, returns the cached access JWT when still valid, or generates a new access token after expiry. The inspected renew path does not issue a replacement refresh token or revoke the used refresh token.",
        "flow": "APP refresh token -> IAM validateToken -> reuse valid cached access token or generate new access token.",
        "check": "Verify refresh-token validation, cached access JWT, access expiry, generated access record, and response fields; do not expect a rotated refresh token unless the implementation changes.",
        "risk": "Describing this implementation as one-time refresh-token rotation gives developers and security reviewers a false guarantee.",
        "limit": "The code proves renewal/reuse behavior, not refresh-token rotation.",
        "src": "iam/src/controllers/auth_controller.ts:130-150; iam/src/services/auth_service/index.ts:753-798",
    },
    {
        "title": "account logout and client-state reset",
        "components": "APP and IAM",
        "fact": "IAM logout clears token cache, marks active device records inactive in a transaction, and deletes token records for the account. APP removes local access/refresh tokens and resets account, persona, member, notification, permission, and building-access state.",
        "flow": "APP logout -> IAM token/device cleanup -> APP AsyncStorage and domain-state cleanup.",
        "check": "Verify the IAM response, token row deletion, device state, cache eviction, AsyncStorage removal, SDK header reset, and domain state reset.",
        "risk": "Clearing only the UI state or only the server token leaves an inconsistent logout result.",
        "limit": "The inspected flow does not prove revocation inside every third-party provider session.",
        "src": "iam/src/services/auth_service/index.ts:340-350; mobile-app/app/OneBangkok/src/states/authen/authenState.tsx:1-140",
    },
    {
        "title": "APP token persistence",
        "components": "React Native APP",
        "fact": "APP persists access and refresh tokens in React Native AsyncStorage, restores/renews them through auth actions, and installs the access token into multiple service SDK headers.",
        "flow": "IAM token response -> Hookstate plus AsyncStorage -> setHeaderSDK -> authenticated service calls.",
        "check": "Verify token persistence, restoration, SDK header installation, logout removal, and migration behavior without printing token contents.",
        "risk": "AsyncStorage is not the same as a platform hardware-backed Keychain/Keystore or SecureStore and should be reviewed for production token threat models.",
        "limit": "The current code does not support a claim that Expo SecureStore protects these token values.",
        "src": "mobile-app/app/OneBangkok/src/states/authen/authenAction.tsx:1-89; mobile-app/app/OneBangkok/src/helpers/api.tsx:1-328",
    },
    {
        "title": "APP concurrent 401 refresh handling",
        "components": "React Native APP API helper and IAM renew",
        "fact": "The APP response interceptor queues requests after eligible 401 responses, serializes refresh with an in-memory lock, updates X-Access-Token, and retries queued requests. Source TODOs note possible repeated-401 deadlock and returning the old response instead of retry responses.",
        "flow": "Service 401 -> request queue -> single refresh -> SDK header update -> queued retries.",
        "check": "Test multiple simultaneous 401s, renew returning 401, one retry failing, queue clearing, response propagation, and unauthorized logout behavior.",
        "risk": "A refresh implementation can obtain a valid new token yet still return an old 401 or leave requests queued.",
        "limit": "A source TODO is a review finding, not proof that a production deadlock has occurred.",
        "src": "mobile-app/app/OneBangkok/src/helpers/api.tsx:40-224",
    },
    {
        "title": "account registration boundary",
        "components": "APP and IAM AuthController",
        "fact": "APP registration builds profile, identities, password, device, push token, SSO registration data, app version, optional address, preferences, invitation code, and registration method. It supports direct /auth/register and a job-based /v2/register path. AuthController returns access and refresh tokens from AccountService.register.",
        "flow": "APP registration state -> direct or job-based IAM endpoint -> AccountService boundary -> token result.",
        "check": "Capture the selected registration path, sanitized payload shape, HTTP/job status, AccountService result, and final local token persistence.",
        "risk": "Combining direct and job-based responses without separate tests can mis-handle PROCESSING or upstream failure states.",
        "limit": "The AccountService registration transaction is absent from the selected digest, so its internal writes and rollback order must not be invented.",
        "src": "mobile-app/app/OneBangkok/src/states/signUp.tsx:313-524; iam/src/controllers/auth_controller.ts:75-120",
    },
    {
        "title": "OTP request and delivery",
        "components": "APP, IAM OTP service, AWS SMS, Kafka, and Notification",
        "fact": "APP obtains OTP encryption/API-key configuration, encrypts the identifier, and calls the v2 request endpoint. IAM sanitizes the identifier, rate-limits generation, creates a reference and expiring code, sends phone OTP by SMS, or publishes ob-iam.otp_reference.created for Notification email delivery.",
        "flow": "APP encrypted identifier -> IAM OTP generation/cache -> phone SMS or Kafka -> Notification email.",
        "check": "Verify identifier normalization, encryption/config availability, rate limit, reference, expiry, channel selection, event publication, Notification consumption, and provider result separately.",
        "risk": "OTP generation success does not prove SMS/email delivery.",
        "limit": "Do not include OTP codes, encrypted identifiers, API keys, or recipient values in training examples or logs.",
        "src": "mobile-app/app/OneBangkok/src/services/OTPService.ts:1-168; iam/src/services/otp_service/index.ts:1-237; notification/src/handlers/iam/otp_handler.ts:1-26",
    },
    {
        "title": "OTP verification and magic-code configuration",
        "components": "IAM OTP service",
        "fact": "OTP verification resolves a record by reference, checks the supplied code and expiry, and can accept 000000 when ENABLE_MAGIC_OTP is true. OTP generation uses a default five-minute expiry and an hourly request-count policy.",
        "flow": "reference plus code -> cached/database OTP -> optional magic-code branch -> code and expiry checks.",
        "check": "Test valid, wrong, expired, unknown, rate-limited, and magic-code cases in an environment-safe configuration.",
        "risk": "Accidentally enabling magic OTP in production bypasses normal possession verification.",
        "limit": "The presence of a configuration branch does not prove its production value.",
        "src": "iam/src/services/otp_service/index.ts:24-237; iam/src/controllers/otp_controller.ts:1-80",
    },
    {
        "title": "identity validation and lifecycle",
        "components": "IAM IdentityController, SSO client, identity repository, and Notification",
        "fact": "IAM supports validating, creating, listing, setting default, and deleting email/phone/SSO-style identities. Validation checks provider format and queries SSO existing-identity state. Identity lifecycle operations can publish events consumed by Notification recipient handlers.",
        "flow": "Identity API -> format/SSO validation -> repository mutation -> identity event -> Notification recipient update.",
        "check": "Verify normalized identifier, provider, SSO result, account ownership, default flag, mutation result, exact event, and recipient update.",
        "risk": "An Identity used to log in is not interchangeable with an External Identity that maps to another domain system.",
        "limit": "A validation result does not prove ownership unless the required authentication/OTP path is completed.",
        "src": "iam/src/controllers/identity_controller.ts:1-147; iam/src/services/identity_service/index.ts:1-224; notification/src/handlers/iam/identity_handler.ts:1-44",
    },
    {
        "title": "default identity update",
        "components": "IAM IdentityService, BMS lookup, ConnectX, and Notification",
        "fact": "Setting a default identity clears defaults for the same provider, marks the selected identity default, updates BZB metadata when applicable, checks BMS for an FS member when no matching FS external identity exists, publishes email/phone default-set events, and triggers ConnectX update.",
        "flow": "Identity selection -> transactional default change -> optional external metadata/member binding -> Kafka recipient event -> ConnectX update.",
        "check": "Verify account ownership, provider peer updates, BZB cache invalidation, FS identity lookup, BMS member result, event payload, and ConnectX boundary.",
        "risk": "A default-login-identity change can alter recipient routing and Workplace binding, not only display preference.",
        "limit": "Asynchronous calls in this flow do not prove all downstream updates completed.",
        "src": "iam/src/services/identity_service/index.ts:209-301",
    },
    {
        "title": "identity deletion and binding reconciliation",
        "components": "IAM, SSO, BMS, TCC, and Notification",
        "fact": "IAM refuses deletion of a default identity, deletes an owned non-default identity transactionally, publishes ob-iam.identity.deleted, synchronizes deletion to SSO, removes applicable non-FS/non-resident external identities, and then reconciles Workplace/Resident bindings.",
        "flow": "Delete request -> ownership/default validation -> identity mutation/event -> SSO/TCC work -> external-identity binding reconciliation.",
        "check": "Trace identity id/account ownership, default flag, transaction result, exact event, SSO response, remaining identities, and external-identity state.",
        "risk": "Deleting a login identity can indirectly remove or unbind a persona when no remaining identifier matches its external member data.",
        "limit": "The source does not prove successful TCC/SSO completion when those calls are not awaited or errors are handled separately.",
        "src": "iam/src/services/identity_service/index.ts:302-369; iam/src/services/identity_service/index.ts:480-630",
    },
    {
        "title": "external identity domain model",
        "components": "IAM ExternalIdentityController and ExternalIdentityService",
        "fact": "External Identity maps an IAM account and login identifier to a third-party type, uid, and metadata. IAM exposes link, validate, search, index, current-account, EV, and e-gift operations, and caches lookups by account id, uid, and identifier.",
        "flow": "IAM account plus identity -> external type/uid/meta mapping -> persona or feature-specific use.",
        "check": "Keep account_id, identifier, type, uid, and meta semantically separate and confirm which external system owns the uid.",
        "risk": "Using an IAM account id where an FS/TCC/BZB uid is expected creates cross-system identity corruption.",
        "limit": "The external-identity types observed in source are not proof that the list is exhaustive across all deployments.",
        "src": "iam/src/controllers/external_identity_controller.ts:1-226; iam/src/services/external_identity_service/index.ts:59-140",
    },
    {
        "title": "social external-identity linking",
        "components": "APP social SDKs and IAM ExternalIdentityService",
        "fact": "APP obtains Facebook, Line, or Apple provider data and calls IAM external_identity/link. IAM validates duplicate external identity, verifies an existing IAM Identity, creates the external mapping for that account, clears cache, and recalculates default persona. If the IAM Identity does not exist, link returns false for sign-up handling.",
        "flow": "Third-party APP SDK -> provider uid/token/profile -> IAM link -> existing Identity/account -> external identity and persona update.",
        "check": "Verify provider result, normalized identifier, duplicate type/uid check, IAM identity ownership, created mapping, cache eviction, and APP sign-up fallback.",
        "risk": "A third-party provider uid and an email supplied by that provider have different trust and uniqueness semantics.",
        "limit": "The inspected IAM link method catches internal errors and returns a generic IAM identity error; it does not prove provider token validation details.",
        "src": "mobile-app/app/OneBangkok/src/services/SSOService.ts:1-220; iam/src/services/external_identity_service/index.ts:59-140",
    },
    {
        "title": "external identity to APP persona mapping",
        "components": "IAM and React Native APP",
        "fact": "APP loads /external_identity/me and maps SSO to User, FS to Workplace, Resident to Residence, and BZB to a retail tier. IAM filters FS identities with empty metadata from the current-account response, and APP falls back to Guest when no persona identity remains.",
        "flow": "IAM external identities -> filtered current-account response -> APP persona list and current persona.",
        "check": "Inspect external type, FS metadata, IAM response filtering, BZB tier data, persona ordering, deduplication, and fallback behavior.",
        "risk": "A database external-identity row can exist while its persona is intentionally hidden because required metadata is empty.",
        "limit": "Persona visibility is not proof of physical building authorization or third-party account health.",
        "src": "iam/src/controllers/external_identity_controller.ts:154-173; mobile-app/app/OneBangkok/src/states/account/accountAction.tsx:280-328; mobile-app/app/OneBangkok/src/states/persona/personaAction.tsx:1-117",
    },
    {
        "title": "BMS member-created to IAM FS identity synchronization",
        "components": "BMS, Kafka, IAM, Identity, and profile persona",
        "fact": "IAM consumes ob-bms.member.created, retries ExternalIdentityService.sync up to three attempts, matches member phones/emails to default IAM identities, upserts FS external identities using member.personID and member metadata, updates persona, and publishes ob-iam.external_identity.created.",
        "flow": "BMS member event -> IAM retry handler -> identity match -> FS external identity -> persona/cache work -> IAM external-identity event.",
        "check": "Follow member personID, phone/email arrays, default Identity matches, account ids, upserted FS rows, retries, emitted event, and persona update.",
        "risk": "BMS member creation success is not proof that IAM matched an Account or completed external-identity creation.",
        "limit": "Kafka topic, partition, and dead-letter policy are not established by the handler source.",
        "src": "iam/src/handlers/bms/member_handler.ts:1-100; iam/src/services/external_identity_service/index.ts:143-233",
    },
    {
        "title": "registration-time BMS member discovery",
        "components": "IAM ExternalIdentityService and BMS",
        "fact": "IAM can query BMS by an email/phone identifier during account or identity workflows. When a member exists and is unbound or already bound to the same account, IAM creates an FS external identity with member.uid and metadata, updates persona/cache, and emits ob-iam.external_identity.created.",
        "flow": "IAM identifier/account -> BMS members lookup -> ownership check -> FS external identity -> BMS link event.",
        "check": "Verify normalized identifier, BMS response shape, existing member.account_id, requested account id, member.uid, metadata, cache eviction, and event.",
        "risk": "IAM catches BMS lookup failures in this path, so account creation can succeed while Workplace binding remains absent.",
        "limit": "A missing Workplace persona after registration is not proof that authentication failed.",
        "src": "iam/src/services/external_identity_service/index.ts:235-280; iam/src/services/identity_service/index.ts:373-404",
    },
    {
        "title": "IAM FS identity event back to BMS",
        "components": "IAM Kafka producer and BMS consumer",
        "fact": "BMS consumes ob-iam.external_identity.created only for type fs, finds a member by external_identity.uid, writes external_identity.account_id to the member, and clears BMS member cache. Other external-identity types are skipped.",
        "flow": "IAM FS mapping event -> BMS type check -> member lookup by uid -> account_id link -> member cache clear.",
        "check": "Match exact event name, type, uid, account_id, BMS member update result, and cache eviction.",
        "risk": "A uid mismatch leaves a valid IAM Workplace external identity without a linked BMS member account.",
        "limit": "Event publication is not proof of BMS consumption or successful database update.",
        "src": "bms/src/events/iam/external_identity_handler.ts:1-128; iam/src/utils/kafka/event_registry.ts:105-224",
    },
    {
        "title": "FS external-identity sync retry exhaustion",
        "components": "IAM and BMS",
        "fact": "IAM's BMS member-created handler retries synchronization with delays of zero, thirty seconds, and sixty seconds. After exhaustion it publishes ob-iam.external_identity.failed_sync, which BMS records as a failed synchronization log when the personID identifies an existing member.",
        "flow": "BMS member event -> three IAM attempts -> failed-sync event -> BMS failed sync log.",
        "check": "Use personID and trace context to correlate all attempts, final error classification, failed event publication, BMS member lookup, and sync-role log.",
        "risk": "A retry-exhausted IAM sync can leave BMS member data present but no usable Workplace account binding.",
        "limit": "The handlers do not establish automatic recovery after the failed-sync log is written.",
        "src": "iam/src/handlers/bms/member_handler.ts:1-60; bms/src/events/iam/external_identity_handler.ts:65-128",
    },
    {
        "title": "Workplace identity deletion and BMS unbind",
        "components": "IAM IdentityService, BMS, and Kafka",
        "fact": "After identity deletion, IAM compares remaining Account identities with the email/phone metadata of bound BMS members, deletes obsolete FS external identities, creates missing mappings for still-matching identifiers, and publishes ob-iam.external_identity.unbind when no matching Workplace identity remains.",
        "flow": "Deleted Identity -> load bound BMS members -> reconcile remaining identifiers and FS mappings -> optional unbind event.",
        "check": "Verify deleted identifier, BMS member metadata, remaining identities, created/deleted FS rows, shouldUnbind decision, event, and cache/persona refresh.",
        "risk": "Removing a secondary login identity can unintentionally remove Workplace binding if external member metadata is stale or incomplete.",
        "limit": "A structural unbind event does not prove physical FS access revocation without the BMS/FS path.",
        "src": "iam/src/services/identity_service/index.ts:480-630; bms/src/events/handler_registry.ts:1-24",
    },
    {
        "title": "Workplace and Resident offboarding interaction",
        "components": "BMS event and IAM ExternalIdentityService",
        "fact": "IAM consumes BMS offboard/member-deleted events. For Workplace offboarding, it clears FS metadata when a Resident identity must preserve the shared FS relationship, otherwise deletes FS identities. Resident offboarding always deletes Resident identity. It then clears cache and recalculates persona.",
        "flow": "BMS offboard state -> IAM external-identity branching -> delete or clear FS metadata -> persona/cache update.",
        "check": "Verify uid/account_id resolution, isWorkplace/isResident flags, Resident presence, FS metadata/result, cache clear, and resulting APP persona visibility.",
        "risk": "Deleting every FS row unconditionally can break Residence, while retaining full Workplace metadata can preserve a persona after offboarding.",
        "limit": "IAM persona removal does not by itself prove final credential revocation in the physical FS system.",
        "src": "iam/src/handlers/bms/member_handler.ts:60-100; iam/src/services/external_identity_service/index.ts:384-468",
    },
    {
        "title": "base attached permissions",
        "components": "IAM permission model",
        "fact": "IAM base permissions cover self account, profile, identity, setting, and token capabilities. BMS service-request and AC-request permissions begin with empty actions, FS integration has a separate wildcard permission, and Workplace Amenity Booking has a separate permission value with initially empty actions.",
        "flow": "Base permission definition -> attached permissions for account -> JWT permission claim -> service authorization.",
        "check": "Compare permission name, service, resource_type, resource scope, actions, permittee type, and the claim embedded in the issued token.",
        "risk": "A named permission with an empty actions array does not authorize the feature.",
        "limit": "Permission constants do not prove which administrative workflow attached or activated them for a specific account.",
        "src": "iam/src/constants/base_permission.ts:1-96; iam/src/services/auth_service/index.ts:470-554",
    },
    {
        "title": "x-permissions authorization trust boundary",
        "components": "Gateway boundary and IAM middleware",
        "fact": "The inspected IAM middleware Base64-decodes x-permissions into request context, and authorization helpers compare resource_type, actions, and optional resource. This middleware does not verify a signature on x-permissions itself.",
        "flow": "Trusted upstream JWT validation -> generated x-permissions header -> IAM decode -> resource/action check.",
        "check": "Verify that the gateway removes client-supplied x-permissions, validates JWT signature/expiry, derives permissions server-side, and prevents direct service bypass.",
        "risk": "If IAM is directly reachable and accepts an arbitrary client header, Base64 encoding provides no authenticity.",
        "limit": "The middleware alone does not prove a deployment vulnerability; gateway and network policy must be inspected.",
        "src": "iam/src/midlewares/decodeXPermission.ts:1-12; iam/src/midlewares/authorizer.ts:1-30; iam/src/utils/authorization.ts:1-78",
    },
    {
        "title": "Workplace Amenity Booking permission propagation",
        "components": "IAM, Kafka, and Booking API",
        "fact": "IAM PATCH /permissions/booking sets the Workplace booking permission actions to wildcard for CORPORATE or empty otherwise, creates or updates the attached permission, emits ob-iam.workplace.amenity.booking.permission, and clears permission/access-JWT cache entries. Booking API consumes the event and upserts its local user permission and Workplace/Retail flags.",
        "flow": "IAM permission mutation -> cache invalidation -> Kafka event -> Booking UserService upsert.",
        "check": "Verify account id, permission enum, attached permission row, cache eviction, exact event payload, Booking consumption, and local user result.",
        "risk": "IAM database success and Booking local-user update are separate consistency boundaries.",
        "limit": "The event source does not prove broker delivery, consumer retry, or an already-issued client JWT being replaced on-device.",
        "src": "iam/src/controllers/permissions_controller.ts:70-177; booking-api/apps/booking-api/src/handlers/iam/iam_handler.ts:1-27",
    },
    {
        "title": "generic permission update cache behavior",
        "components": "IAM PermissionsController and token cache",
        "fact": "The generic permission update mutates one attached permission and clears ATTACHED_PERMISSION for the account. Unlike the booking-specific path, the inspected generic path does not explicitly clear the cached access JWT.",
        "flow": "Permission update -> attached-permission repository -> permission cache clear -> future token issuance.",
        "check": "Test an already-issued token, access-JWT cache, gateway claims, renewed token, and new login after a permission reduction.",
        "risk": "Permissions embedded in an existing JWT may remain stale until token replacement or expiry, depending on gateway enforcement.",
        "limit": "This is a code-review concern; actual revocation behavior requires gateway and runtime verification.",
        "src": "iam/src/controllers/permissions_controller.ts:1-90; iam/src/services/auth_service/index.ts:470-554",
    },
    {
        "title": "device and FCM synchronization",
        "components": "APP, IAM, Kafka, and Notification",
        "fact": "During login IAM can create/replace an active device and emit ob-iam.device_and_fcm_token.added, or emit ob-iam.fcm_token.updated when device storing is disabled. Notification updates recipient device and push-token state; the combined event also creates a device-added automatic message.",
        "flow": "APP device/push token -> IAM login/device service -> Kafka event -> Notification recipient update.",
        "check": "Verify notification permission/token acquisition, submitted device id/OS, IAM feature flag, device mutation, exact event, and recipient result.",
        "risk": "Authentication can succeed while push delivery later fails because device/recipient synchronization is asynchronous.",
        "limit": "An FCM token stored by Notification does not prove Firebase accepted or delivered a message.",
        "src": "iam/src/services/auth_service/index.ts:209-232; iam/src/services/device_service/index.ts:1-103; notification/src/handlers/iam/device_fcm_token_handler.ts:1-25",
    },
    {
        "title": "IAM-driven Notification recipient projection",
        "components": "IAM Kafka events and Notification",
        "fact": "Notification maintains recipient data from IAM account, profile, identity, device, FCM token, setting, and permanent-delete events. It also creates supported automatic messages for account lifecycle, identity, device, password, reactivation, and 2FA events.",
        "flow": "IAM authoritative mutation -> named Kafka event -> Notification handler -> recipient projection or automatic message.",
        "check": "Match the exact event and account id, compare IAM authoritative state with Notification recipient state, and inspect handler/provider results separately.",
        "risk": "A stale Notification recipient can route a correct business notification to an old identity, device, or language.",
        "limit": "Registration or event publication does not prove message delivery to a device or mailbox.",
        "src": "notification/src/handlers/handler_registry.ts:1-93; notification/src/handlers/iam/account_handler.ts:1-87; notification/src/handlers/iam/identity_handler.ts:1-44",
    },
    {
        "title": "SSO account reconciliation",
        "components": "APP, IAM, SSO, and Notification recipient boundary",
        "fact": "APP builds an SSO synchronization request from account, SSO profile, identities, push token, and device. IAM checks whether reconciliation is enabled and whether SSO identity/token state already exists, calls SSO sync when needed, reconciles the account, and may asynchronously upsert recipient data.",
        "flow": "APP current account state -> /me/account/sync/sso -> IAM SSO checks/call -> account reconciliation -> recipient boundary.",
        "check": "Verify feature flag, account id, SSO public id, SSO external identity, cached/repository SSO tokens, upstream response, reconciliation result, and recipient event.",
        "risk": "Returning synced=false may represent disabled reconciliation, missing SSO state, upstream failure, or reconciliation failure and requires stage-specific evidence.",
        "limit": "The selected digest does not include AccountService.reconcileWithSSO internals, so its field-level writes must not be invented.",
        "src": "mobile-app/app/OneBangkok/src/states/account/accountAction.tsx:417-482; iam/src/controllers/account_controller.ts:150-273; iam/src/services/auth_service/index.ts:1112-1188",
    },
    {
        "title": "IAM QR token versus Visitor Pass QR",
        "components": "APP and IAM token services",
        "fact": "APP can request IAM QR token data from /me/qr_token. IAM protects QR operations with token or FS permissions and exposes integration endpoints that resolve token/account/detail/profile data. This identity token flow is separate from BMS Visitor Pass creation and visitor invitation handling.",
        "flow": "Authenticated account -> IAM QR service -> short-lived token/encrypted identity data -> authorized integration lookup.",
        "check": "Identify whether the reported QR belongs to IAM account identity or BMS Visitor Pass before tracing controller, token id, permission, expiry, and consumer.",
        "risk": "Conflating the two QR domains produces incorrect endpoints, tables, ownership, and debugging steps.",
        "limit": "The IAM QR controller does not prove Visitor Pass QR generation or turnstile admission.",
        "src": "mobile-app/app/OneBangkok/src/services/QRTokenService.ts:1-59; iam/src/controllers/qr_token_controller.ts:1-127",
    },
    {
        "title": "external-identity cache consistency",
        "components": "IAM ExternalIdentityService, profile persona, and cache",
        "fact": "IAM caches external-identity lookups by account id, uid, and identifier and records related cache keys per account for invalidation. Link, upsert, member binding, identity reconciliation, and offboarding paths perform cache clearing with varying scopes.",
        "flow": "External-identity read -> multi-key cache -> database mutation -> related-key invalidation -> persona/read refresh.",
        "check": "Compare database rows, account key list, uid/identifier entries, profile cache, post-mutation read, and APP persona refresh.",
        "risk": "A correct database update can remain invisible or expose stale persona state when one lookup key is not invalidated.",
        "limit": "The presence of invalidation calls in selected paths does not prove every mutation path clears every related key.",
        "src": "iam/src/services/external_identity_service/index.ts:281-382; iam/src/services/external_identity_service/index.ts:539-598",
    },
    {
        "title": "sensitive-token logging",
        "components": "IAM AuthService observability",
        "fact": "The inspected auth source logs decoded JWT data and includes raw token variables in several failure/SSO renewal log messages. These values should be treated as credentials or sensitive authentication material.",
        "flow": "Token verification/renewal error -> logging statement -> log aggregation and retention boundary.",
        "check": "Search structured logs and error paths for raw access, refresh, or JWT values; replace them with event type, account id where permitted, token fingerprint, and correlation id.",
        "risk": "Credential material in centralized logs expands access and retention exposure beyond the authentication system.",
        "limit": "The source proves risky logging statements, not that a particular production log store currently contains a usable token.",
        "src": "iam/src/services/auth_service/index.ts:994-1050",
    },
    {
        "title": "password-bearing TCC login event",
        "components": "IAM login, Kafka, and TCC integration",
        "fact": "When ON_EVENT is enabled, the login path publishes ob-iam.on-event.login_tcct with accountId and the account password, and an IAM consumer uses that payload to log in to TCC. The handler logs only accountId in its explicit start/done context, but the credential still crosses Kafka.",
        "flow": "Successful IAM login -> password-bearing event -> IAM consumer -> TCC login.",
        "check": "Review broker ACLs, serialization, retention, tracing, dead-letter behavior, consumer logs, and replace the password with a short-lived exchange mechanism.",
        "risk": "Publishing a reusable password expands credential exposure to the message infrastructure and its operators.",
        "limit": "Do not include a real password or event payload value in any diagnostic or training record.",
        "src": "iam/src/services/auth_service/index.ts:234-253; iam/src/handlers/iam/iam_on_event_event_handler.ts:116-136",
    },
    {
        "title": "profile update propagation",
        "components": "IAM, BMS, Kafka, and Notification",
        "fact": "IAM profile updates can emit ob-iam.profile.updated. Notification updates its recipient profile, while BMS resolves the Workplace member by account_id and updates created_by display values on AC and Service Requests.",
        "flow": "IAM profile mutation -> profile event -> Notification recipient projection plus BMS historical/request display update.",
        "check": "Verify IAM persisted profile, exact event payload, Notification recipient result, BMS member resolution, and affected request rows.",
        "risk": "Profile state can be correct in IAM while recipient or operational request display data remains stale after an event failure.",
        "limit": "The event does not prove every service storing a name consumes profile updates.",
        "src": "iam/src/services/profile_service/index.ts:105-224; notification/src/handlers/iam/profile_handler.ts:1-12; bms/src/events/iam/profile_handler.ts:1-35",
    },
    {
        "title": "permanent account deletion propagation",
        "components": "IAM event boundary, BMS, and Notification",
        "fact": "The IAM event registry defines ob-iam.account.permanent-deleted with account_ids. BMS consumes it to clear matching member.account_id values, and Notification consumes it to delete recipient records.",
        "flow": "IAM permanent deletion event -> BMS account unlink plus Notification recipient deletion.",
        "check": "Verify account_ids, event publication, both consumer receipts, BMS member updates, Notification recipient deletion, and cache cleanup requirements.",
        "risk": "Partial consumption can leave a deleted account linked in BMS or retained as a Notification recipient.",
        "limit": "The registry and consumers do not establish the exact IAM producer trigger or data-retention deletion scope.",
        "src": "iam/src/utils/kafka/event_registry.ts:417-484; bms/src/events/iam/account_handler.ts:1-26; notification/src/handlers/iam/account_handler.ts:1-87",
    },
]

MODES = ("explain", "flow", "debug", "analyse", "qa", "security", "ownership", "failure-isolation")
AUDIENCES = (
    "an APP developer", "an IAM developer", "a BMS developer", "a Booking developer",
    "a Notification developer", "a QA engineer", "an operations engineer", "a solution architect",
)
LENSES = (
    "identifier and credential semantics", "authorization and trust boundaries",
    "cache and persistence consistency", "Kafka and external-system completion boundaries",
    "production observability without sensitive data", "safe recovery and regression prevention",
)


def is_old(row: dict[str, object]) -> bool:
    q = str(row.get("instruction", "")).casefold()
    i = str(row.get("input", "")).casefold()
    return "feature selection evidence:" in i and " for authentication" in q


def is_curated(row: dict[str, object]) -> bool:
    return "iam evidence class: code-proven with explicit evidence limits" in str(row.get("input", "")).casefold()


def question(mode: str, title: str, audience: str, lens: str, variant: int) -> str:
    forms = {
        "explain": ["Explain {title} in detail for {audience}.", "Teach {audience} how {title} works from the current source."],
        "flow": ["Trace the end-to-end source-backed flow for {title}.", "Map every proven handoff involved in {title} for {audience}."],
        "debug": ["Debug a reported problem around {title}; no runtime log is supplied.", "Create an evidence-first production debugging plan for {title}."],
        "analyse": ["Analyse the architecture, state, and evidence boundaries of {title}.", "Review the implementation implications of {title} for {audience}."],
        "qa": ["Design comprehensive source-backed QA coverage for {title}.", "Define positive, negative, boundary, and cross-service tests for {title}."],
        "security": ["Perform a source-backed security review of {title}.", "Review the authentication and authorization trust boundaries of {title}."],
        "ownership": ["Clarify service and data ownership for {title}.", "Explain escalation responsibility for each boundary in {title}."],
        "failure-isolation": ["Explain how to isolate partial failures in {title}.", "Build a stage-by-stage failure-isolation guide for {title}."],
    }
    return forms[mode][variant % 2].format(title=title, audience=audience) + f" Focus on {lens}."


def answer(mode: str, x: dict[str, str], audience: str, lens: str) -> str:
    if mode in {"debug", "failure-isolation"}:
        return (
            "## 【Root Cause Analysis】\n\nNo runtime log, stack trace, correlation id, or concrete failed response is supplied, so no incident root cause is confirmed. "
            f"The source-proven behavior is: {x['fact']} The supported path is `{x['flow']}`. The diagnostic lens is **{lens}**.\n\n"
            "## 【Step-by-Step Debugging Guide】\n\n"
            "1. Identify the exact route, account/identity type, token class, event name, and owning service without recording credentials.\n"
            f"2. Validate this scenario-specific evidence: {x['check']}\n"
            "3. Compare cache, persistent state, API response, producer result, consumer result, and external-provider result as separate stages.\n"
            "4. Use sanitized account/member ids, token fingerprints, event names, and trace ids; never log passwords, OTP codes, tokens, or provider assertions.\n"
            f"5. Reproduce and regression-test the relevant risk: {x['risk']}\n\n"
            "## 【Production-Grade Fix】\n\nDo not change authentication behavior until the failing boundary is reproduced. Apply the smallest fix at the authoritative owner, invalidate affected state, and add tests for both success and denial paths. "
            f"Evidence limit: {x['limit']}\n\nSource: {x['src']}."
        )
    if mode == "qa":
        return (
            f"## Test Objective\n\nValidate {x['title']} with emphasis on **{lens}**. Code-proven behavior: {x['fact']}\n\n"
            "## Test Matrix\n\n"
            f"1. Happy path: exercise each observable stage in `{x['flow']}`.\n"
            "2. Credential/identity negative path: wrong type, wrong owner, missing mapping, expired state, or denied permission as applicable.\n"
            "3. Cache/persistence path: compare a warm-cache request, cache miss, mutation, invalidation, and next read.\n"
            "4. Cross-service path: stop or fail the proven Kafka/external boundary and verify that upstream success is not misreported as downstream completion.\n"
            "5. Security path: assert that logs, errors, fixtures, and reports contain no password, OTP, access token, refresh token, provider assertion, or secret.\n"
            f"6. Scenario assertions: {x['check']}\n\n"
            f"## Acceptance Boundary\n\nDetect this risk: {x['risk']} Do not assert beyond the evidence: {x['limit']}\n\nSource: {x['src']}."
        )
    if mode == "security":
        return (
            f"## Security Model\n\nAnalytical lens: **{lens}**. {x['fact']} The supported control/data path is `{x['flow']}`.\n\n"
            "## Review Checklist\n\n"
            "1. Authenticate at the owning boundary and distinguish access, refresh, OTP, third-party, and integration credentials.\n"
            "2. Authorize account ownership, resource, action, and external-identity type server-side.\n"
            "3. Treat APP headers, Kafka payloads, caches, logs, and external mappings as separate trust boundaries.\n"
            "4. Redact passwords, OTPs, tokens, provider assertions, API keys, and personal identifiers from observability.\n"
            f"5. Verify the actual implementation: {x['check']}\n\n"
            f"## Finding and Evidence Limit\n\nRisk: {x['risk']} This is a source review, not proof of exploitation. {x['limit']}\n\nSource: {x['src']}."
        )
    if mode in {"explain", "flow", "ownership"}:
        note = {
            "explain": "Keep Account, Identity, External Identity, permission, persona, and token concepts separate.",
            "flow": "Every arrow is a code-supported boundary, not proof that a production transaction completed it.",
            "ownership": "Escalate to the owner of the first boundary whose required input exists but expected output does not.",
        }[mode]
        return (
            f"## Source-Backed Explanation\n\n{x['fact']}\n\n"
            f"## End-to-End Flow\n\n`{x['flow']}`\n\n{note}\n\n"
            f"## Practical Validation\n\nFor {audience}, focus on **{lens}**. {x['check']} Principal risk: {x['risk']}\n\n"
            f"## Evidence Boundary\n\n{x['limit']}\n\nSource: {x['src']}."
        )
    return (
        f"## Architecture Finding\n\nAnalytical lens: **{lens}**. {x['fact']}\n\n"
        f"## Data and Control Flow\n\n`{x['flow']}`\n\n"
        f"## Operational Analysis\n\n{x['check']} Principal risk: {x['risk']}\n\n"
        f"## What Cannot Be Concluded\n\n{x['limit']} Structural source or an emitted event must not be presented as a completed runtime outcome.\n\nSource: {x['src']}."
    )


def make(index: int) -> dict[str, str]:
    x = S[index % len(S)]
    cycle = index // len(S)
    mode = MODES[cycle % len(MODES)]
    audience = AUDIENCES[(index + cycle // len(MODES)) % len(AUDIENCES)]
    lens = LENSES[(cycle // (len(MODES) * 2)) % len(LENSES)]
    return {
        "instruction": question(mode, x["title"], audience, lens, cycle // len(MODES)),
        "input": (
            f"Component/Service Name: {x['components']}\n\n"
            "IAM Evidence Class: Code-proven with explicit evidence limits\n\n"
            "Exact Runtime Log or Stack Trace: No runtime log or stack trace is supplied. Do not invent one.\n\n"
            f"Actual Code Evidence: {x['fact']}\n\nSupported Flow: {x['flow']}\n\nRequested Analysis Lens: {lens}\n\n"
            "Grounding Rule: Never invent a credential, incident, endpoint, table, event result, provider result, or authorization guarantee. "
            "Treat controller calls, cache writes, Kafka publication, consumer registration, and external API calls as separate evidence boundaries.\n\n"
            f"Exact Source Location: {x['src']}"
        ),
        "output": answer(mode, x, audience, lens),
    }


def sig(row: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="data/sft_data.jsonl")
    p.add_argument("--count", type=int, default=1600)
    args = p.parse_args()
    minimum = len(S) * len(MODES)
    if args.count < minimum:
        raise SystemExit(f"--count must be at least {minimum} to cover every scenario and mode")
    path = Path(args.dataset)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = [r for r in rows if not is_old(r) and not is_curated(r)]
    generated = []
    seen = set()
    for index in range(args.count):
        row = make(index)
        signature = sig(row)
        if signature in seen:
            raise SystemExit(f"duplicate generated record at index {index}")
        seen.add(signature)
        generated.append(row)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept + generated), encoding="utf-8")
    print(json.dumps({
        "removed_generic_or_prior_iam_records": len(rows) - len(kept),
        "added_source_backed_iam_records": len(generated),
        "scenario_count": len(S),
        "mode_count": len(MODES),
        "total_records": len(kept) + len(generated),
    }))


if __name__ == "__main__":
    main()
