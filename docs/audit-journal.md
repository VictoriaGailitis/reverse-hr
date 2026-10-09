# Audit evidence, disclosures and investigations

Audit has an independent database and consumer. Producer events are authenticated
with the existing Ed25519 transport before any effect. The journal preserves the
exact canonical signed envelope and producer signature while their configured
retention window remains active. Event payloads contain UUID references only;
contact values, PDF bytes, external message contents and arbitrary text cannot
be sent to this journal.

Duplicates with the same event ID/proof are no-ops. Conflicting content for the
same ID is rejected. Arrival order is distinct from business aggregate order:
the journal retains `initial`, `next`, `gap`, `stale` and `same_version` classifications,
and the per-producer aggregate watermark only increases. A gap is an observable
missing delivery, not an invented business action. Delayed events older than
the retention window are ignored to prevent historical data resurrection.

A singleton head is locked using a real database UPDATE plus SELECT FOR UPDATE.
SQLite and PostgreSQL concurrent arrivals therefore allocate one global sequence
and authenticate a single predecessor chain. Each audit signature covers the
sequence, predecessor, original content hash and immutable receipt metadata.
Searchable projection hashes are included in that signed metadata. Changed
original signatures, original bytes, action types, references, chain links,
sequence or head records fail verification. Appends also validate the latest
head proof before signing a new link. Privacy/retention redactions have separate
signed receipts; changing an `erased` flag without a valid receipt fails.

## Protected APIs

- `GET /v1/audit/entries`: search by `by_actor`, `by_case`, `producer`, aware
  `occurred_from` / `occurred_to`; sequence cursor `after`.
- `GET /v1/audit/entries/{event_id}`: verified minimal action/references.
- `GET /v1/audit/verify`: streaming structural/source-signature verification and
  the signed current head, suitable for recording an external checkpoint.

All require `audit_reviewer`, MFA and fresh processing permission. A reviewer
cannot access their own involved actions. Every disclosed row is independently
integrity checked and its current subjects' processing permissions checked.
Sensitive original proof bytes are not returned by these search endpoints.
Successful searches/details/verifications commit UUID-only `audit.journal_read`
receipts to Audit's own outbox before returning the response.

Search examines at most 50 entries per page; `X-HR-Next-Cursor` advances through
hidden/nonmatching records as well, so an empty filtered page is not the end.
Query parameters and results are not copied as arbitrary text into an event.

## Concrete disclosure evidence

Owner services call `audit_access.record_disclosure` inside their business
transaction and commit before returning protected contacts/PDF or preparing an
ATS delivery. It inserts `<owner>.<kind>_disclosed.v1` into the owner's outbox,
using `contacts`, `resume_pdf`, `ats_export` or `external_delivery`, plus resource,
actor, candidate and optional organization/recipient UUIDs. The normal signed
consumer archives the receipt even if Audit was unavailable during the response.
A receipt attests the authorized response; it does not claim the remote user
successfully received every byte.

`POST /internal/v1/audit/disclosures` also accepts signed owner-reported delivery
receipts. It enforces a fixed kind/owner allowlist, 30-second request freshness,
nonce replay protection and a stable `effect_id`. A retry with a fresh nonce
returns the same effect receipt; changed content conflicts. Responses are
signed and bound to the request. No publicly supplied raw contact fields are
accepted. These proofs trust the named owner service to report its own effect;
Audit does not independently attest a third-party transport's delivery status.

## Privacy and retention

`HR_AUDIT_RETENTION_DAYS` is configurable (default 365, allowed 1–3650). This is a
technical retention setting and requires a separately approved organizational
policy; it is not a claim about a legally required retention duration. Expiry is
pinned at receipt time. Expired entries cannot be read/exported even before the
retention worker runs.

Privacy deletion atomically removes original envelopes and all searchable UUID
projections for affected entries, records a signed redaction receipt, removes
pending historical read receipts and emits one `audit.data_deleted` acknowledgement.
Only content/receipt hashes and signed chain proofs remain. Privacy exports use
`subject_export_records`: only the subject's own action/date/producer/delivery
classification, never another actor, recipient, payload or unrelated subject.

A short-lived hashed anti-resurrection marker survives until the configured
retention window expires. Subsequent consumer deliveries also request fresh
Privacy processing permissions. A denied/restricted subject causes a minimum
proof-only signed redaction immediately; a processing outage retries the delivery.
This fail-closed technical rule does not silently retain restricted UUID metadata
for investigators. It also prevents a new delivery from recreating an erased
projection after its local marker expires.

The `audit-retention` worker removes expired original proofs/projections and old
stream/nonce/tombstone records. It drops contiguous expired prefixes and retains
one signed nonidentifying boundary proof when all personal entries expire.
Different pinned expiries can leave temporary proof-only interior records until
the older prefix expires. This keeps chain verification meaningful after cleanup.

A database rollback to a previously valid complete snapshot cannot be detected
using that database alone. Compare exported head checkpoints against an external
trusted witness to detect that threat; a WORM store/external witness is not
implemented here. Broker/dead-letter retention is managed independently of the
Audit database policy.
