# External notifications

Email delivery is disabled by default. The optional Notification email worker uses a
configured provider with fixed HTTPS origin, no redirects, provider idempotency,
and bounded request timeout. No production API returns verification codes. The
provider must accept `POST /v1/messages` with `Idempotency-Key` equal to the delivery
UUID and JSON `idempotency_key`, `email`, `subject`, `text`; success is HTTP
200/201/202 with `status: accepted`, the same `idempotency_key`, and UUID
`provider_id`. Missing/mismatched acknowledgements are uncertain delivery outcomes.

Authenticated users register their own target through `POST /v1/notifications/email`
with email and an active `external_service_notifications` consent UUID. This is
independent of candidate contact fields and also supports employer accounts. The
response contains only challenge UUID, expiry and target version. Challenge mail
contains a six digit code; `POST /v1/notifications/email/verify` confirms it. Codes
expire after ten minutes, allow five attempts, and are salted hashes plus encrypted
worker material. Encryption keys are loaded lazily from a configured raw 32-byte
AES-GCM key file. Challenges are limited to one per minute and three per hour;
address replacement invalidates previous challenges and cancels previous jobs.

`GET/PUT /v1/notifications/email/preferences` exposes independent service and
marketing flags. The initial preference version is 1; PUT requires the normal
quoted `If-Match` and idempotency key, creates version 2, and requires active
purpose consent for each enabled category. Marketing uses a distinct
`external_marketing_notifications` consent. Opt-out cancels matching pending jobs;
disabling both categories removes the address and challenges. Re-enabling needs
fresh target verification. Direct verified-address correction is unsupported;
register and verify the replacement instead.

The durable worker fans out only notices created after target verification and
that category's opt-in activation. It does not mail historical backlogs. Email
selection is independent of in-app preferences; each send rechecks local subject
state, target generation, category consent through signed Privacy permission, and
fresh source-owner permission. Emails contain a generic alert and a configured
static HTTPS application link, never notice bodies, contacts or assessment details.
Target changes and Privacy erasure hold the same subject fence as sending.

Each delivery has a stable provider idempotency UUID, bounded attempts, an expiring
lease, exponential retry delay capped at one hour, and a durable attempt history.
A signed Audit outbox receipt commits before invoking the provider. An expired
last-attempt lease becomes `uncertain_final` without another send. `submitted`
means acknowledged submission, not delivered email; it awaits a signed callback.
Provider copies cannot be recalled by local erasure. Operators must configure the
provider's deletion/retention policy separately; this code makes no such promise.

The provider posts to the public `POST /v1/notifications/provider-callback`
(the internal alias is also available). No user JWT is required: an Ed25519
signature in `X-HR-Signature` is mandatory. Sign UTF-8 canonical JSON (sorted keys,
compact separators, DTO-normalized timestamps/UUIDs) prefixed by
`reverse-hr.notification-provider-callback.v1` followed by a NUL byte. The public
key is loaded lazily from a configured raw 32-byte Ed25519 key file. Body fields:
`delivery_id`, `provider_id`, `event_id`, `nonce` (UUIDs), `sequence` (positive
integer), `status` (`delivered` or `failed`), `issued_at` (UTC timestamp within
30 seconds). Receipts are retained for 24 hours; event replay is idempotent,
conflicting payload/nonce reuse is rejected, and older sequences cannot replace
newer state. Cancelled jobs and terminal outcomes cannot be revived. Callbacks can
reconcile `uncertain_final` when the provider actually accepted a timed-out send.

`GET /v1/notifications/deliveries` returns only the authenticated user's minimal
status history, with UUID `after` pagination. Privacy exports own address,
preferences and minimal delivery status through bounded iteration; no challenge,
provider identifiers, signature material, other recipients or raw notice content
is exported. Subject erasure purges addresses, codes, jobs, attempts and callbacks,
including delivery jobs tied to source notices involving the erased subject.

Tests use a fake idempotent provider, ephemeral keys and migrated temporary
service databases. No real email or provider request is performed by these tests.
