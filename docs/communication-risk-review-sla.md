# Communication risk and independent review SLA

Hiring screens each successfully posted dialog message in the message transaction.
`communication-risk-rules-v1` detects insecure, shortened, credential-bearing,
punycode or IP-host links; explicit requests to transfer money/pay a deposit; and
explicit employer salary assertions outside the accepted invitation's stored
range in that same currency (RUB aliases supported, no exchange conversion). Normal HTTPS links, negated payment requests and candidate salary
negotiation do not automatically trigger the corresponding checks.

A signal is a suspicion, never a finding. There are no automated sanctions,
profile restrictions or grading changes. Every signal opens an ordinary Hiring
complaint with an independent human decision (`upheld` / `dismissed`). It retains
message and offer-version references plus controlled codes. Original text stays
in the permission-checked message store, and events carry UUID references only.
The existing complaint evidence API performs fresh processing and employer
independence checks; participants can read their dialog's minimal signal status.

Endpoints:

- `GET /v1/dialogs/{id}/risk-signals`: minimal codes and status for participants.
- `GET /v1/hiring-complaints/{id}/risk-signal`: source reference and rule version
  for an independently authorized moderator.
- Existing complaint decision endpoints: human resolution with MFA, version and
  idempotency checks.

## Durable review scheduling

Hiring, Employer and Assessment each own three migrated tables: `*_review_pool`,
`*_review_sla` and `*_review_actions`. `review-sla` workers share no database across
services. The source case, ledger update, inbox action and outbox record commit
atomically. Subject and source-row locks serialize concurrent workers and Privacy.
Retries after rollback have no partial effect; committed stages are not repeated.

Supported queues: Hiring complaints, pending employer reviews and moderation
appeals; Employer trust/sanction appeals; Assessment result appeals.

`review-sla-v1` sends a reminder one day before the source deadline, rotates the
reviewer when overdue, and escalates two days after the deadline. Existing source
rules provide the deadline: 14 days for Hiring/Employer, the pinned session appeal
review duration for Assessment. A worker does not extend those deadlines.

Reviewers enroll/renew their own 15-minute availability lease through
`PUT /v1/review-sla/availability?enabled=true` with the relevant role and MFA.
`enabled=false` cancels availability. Assignment rechecks the lease after participant
locks, processing permissions, excluded original reviewers/authors and employer
affiliation. Expired availability prevents new selection; it does not itself
remove an already assigned reviewer. Human mutations always require a fresh JWT,
MFA and the assigned independent identity.

No eligible reviewer creates an `unassigned` action and escalation remains visible
in `GET /v1/review-sla/inbox` to independently authorized reviewers. A later available
reviewer recovers the assignment once. Processing restriction of a current reviewer
also permits a fresh independent replacement, including after escalation. Previously
rotated reviewers cannot reclaim the same case. Source versions change with an
assignment, so stale human decisions fail. Terminal cases are never reopened.
Assessment source history includes automatic reassignment/release actions.

The protected SLA inbox and durable outbox are implemented. External message
channels are not sent by this worker. Actions carry no communication text or
contact data. Every inbox read repeats authorization against the current source
case; terminal/deleted/inaccessible cases are omitted. The list response preserves
its existing shape and includes `X-HR-Next-Cursor` when more stored actions remain.
Clients pass that opaque action UUID as `?after=` and continue even when the current
page is empty: each request examines at most 50 actions, including hidden ones.
The cursor contains no case, participant or contact identifier. Privacy cleanup removes
reviewer availability, affected ledgers, actions, cached responses and pending events.
Communication-risk records disappear with their source participants/evidence.

## Scope

Screening is intentionally explainable and conservative; it has no URL reputation
provider or semantic fraud model. It does not fetch links, scan third-party chats
or ingest external recordings. Independent humans must interpret context, including
quoted statements and negotiated offers. Availability is a short authenticated
lease, not a claim that the scheduler refreshes identity-provider roles itself.
