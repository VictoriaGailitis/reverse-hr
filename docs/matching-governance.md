# Governed semantic matching and qualification advice

Matching now owns versioned catalogs, ranking/advice policies and employer-reviewed intents.
Existing legacy search and `verified-demo-v1` remain compatible; callers opt in explicitly with
`ranking_policy: governed-v1` and a pinned `policy_id`. Candidate advice accepts an explicit
`policy_id` and `policy_mode` and fetches the current policy from Matching through fresh signed RPC.

## Catalog and policy lifecycle

A `content_admin` with MFA submits `/v1/matches/governance/catalogs` and
`/v1/matches/governance/policies`. Documents are immutable versions with UUIDs, a content digest
and revision. An independent `assessment_reviewer` with MFA approves or revokes through
`/governance/versions/{version_id}/decisions`; compare-and-set revision protects concurrent and
late decisions. A revoked version cannot be approved again: create a new version. Fresh Privacy
processing permission for both author and reviewer is checked whenever the version is resolved.
Privacy deletion anonymizes these ownership fields and permanently revokes the version.

A catalog contains canonical competencies/technologies, unique normalized aliases, explicit
rubric evidence keys and allowed specializations. Mapping a technology to several criteria means
**all criteria** must meet the minimum, using their minimum score. Declared skills never satisfy
mapped verified requirements. Mapping is a human content decision: the code does not certify that
a general SQL rubric tests PostgreSQL-specific behavior. Reviewers must map only appropriate
rubric criteria. Unknown terms require a new approved catalog version; no automatic equivalence
or inferred technology proficiency is used.

A policy pins its catalog and weights (competency, assessment, freshness and bounded achievement
bonus), competency threshold, current/expiry periods, practice target and next-grade suggestion
thresholds. Suggestions never assign a grade or shorten Assessment retry/grade cooldowns.
Callers may require a higher competency score or fresher evidence, but cannot weaken policy gates.
Snapshots retain policy/catalog UUIDs and version in each ranked result; current reads suppress
expired or withdrawn evidence and reject revoked policies/catalogs even for an empty snapshot.

## Calibration is a trusted import, not a fabricated validation

Production drafts register `calibration_minimum_precision` **before** any calibration report.
`POST /governance/policies/{policy_id}/calibration` imports one report while the policy is a draft.
The report includes dataset/report SHA-256 digests, labeled-pair count, precision@k, k and the same
previously pinned threshold; it must pass that threshold. Import is immutable, version-checked
and cannot replace the criterion or report. Only afterwards may an independent reviewer approve.
Production approval also requires a production catalog. Calibrated data are not shipped or
invented. Reviewers must inspect the expert labels, provenance and report represented by the
digests; this API validates the declared report and ownership, and does not recompute precision
from arbitrary externally supplied files.

All current CandidateCard and QualificationEvidence contracts remain explicitly synthetic.
Therefore a production governed search does not return those candidates, and production advice
rejects their evidence, even after a production policy has been approved. Demo advice remains
marked demo and uncalibrated when its source evidence is synthetic. Actual production assessment
provenance is a separate rollout prerequisite.

## Employer intent: parse → review/edit → confirm → search

`POST /v1/matches/intent-previews` requires current employer authorization for the existing Need
and an approved catalog. It accepts text (at most 4,000 characters), `catalog_id` and parser:

* `llm`: the configured adapter returns a structured `ParsedIntent` with specialization, grade,
  mandatory/desired terms, conditions, unknowns and verbatim source citations. Every proposed
  fact must have a source quote. Competencies must match catalog terms/aliases in their quotes;
  basic specialization/grade values are checked against the cited text. Missing fields stay
  unknown. Unsupported vocabulary, missing quotes and fabricated basic facts are rejected.
* `explicit`: a deterministic fallback recognizes catalog aliases as **mentions**. It proposes
  desired terms only; mandatory-vs-desired, specialization, grade and conditions stay unknown.
  This fallback does not pretend to understand the complete request.

A saved preview pins the employer, organization, Need digest, catalog, parser and prompt version,
and expires after 30 minutes. Parsing executes no search. The employer edits the proposal and
posts `/intent-previews/{preview_id}/confirmation`, explicitly providing specialization and grade.
Unknown conditions must be resolved before automatic search. Confirmation is one-time; repeated
identical command keys return the original response, changed bodies or competing keys conflict.
A changed Need, expired preview, withdrawn catalog or different employer prevents confirmation.

The employer supplies `intent_preview_id`, `policy_id` and `ranking_policy: governed-v1` to search.
The confirmed specialization, grade and mandatory/desired requirements are used in the actual
Need view for that search, with the underlying organization authorization and original Need digest
still checked. The preview's catalog must equal the policy catalog. This is a search refinement;
it does not silently edit the Hiring-owned Need or vacancy. Stored Needs can be edited through
the existing Hiring API. Employment conditions are shown for human review;
Typed salary, work-format and start-window conditions now compare against explicitly confirmed
candidate self-description; these fields are separate from verified skills. Other unresolved
conditions block automatic ranking rather than silently disappearing. See
[employment conditions](matching-employment-conditions.md) for provenance, filtering and consent gates. Privacy deletion erases employer raw text,
model proposals, confirmed intents and cached command responses.

## Provider setup

The HTTPS adapter is opt-in and disabled by default. Matching settings are:
`HR_MATCHING_LLM_ENABLED`, `HR_MATCHING_LLM_MODEL`, `HR_MATCHING_LLM_CONFIG` (a
`GatewayConfiguration` JSON object) and `HR_MATCHING_LLM_KEY_FILE`. The main Compose configuration
passes operator settings; `compose.matching-llm.yaml` supplies explicit gateway egress and a private
credential-file mount. No provider credentials or requests were used in implementation/testing.

`MatchingIntentGateway` sends one Chat Completions JSON request to the fixed HTTPS origin with
`store=false`, no streaming/tools/retries/fallback/redirects/ambient proxies. Only employer text and
catalog are sent; candidate profiles and contacts are never included. Model ID and system prompt
are pinned. Input bytes, estimated conservative token capacity, reply bytes, reported usage and
15-second execution are bounded. Duplicate JSON keys, non-finite numbers, refusal, tool calls,
truncated output and unpinned model replies fail closed. A timed-out thread keeps the single
execution slot until completion. Preview command replays skip another model call after the first
successful result was stored. Externally configured tariffs are operator estimates, not invoices.

Candidate uses `QualificationPolicyAccess` against `HR_MATCHING_API_URL`. The policy receipt binds
candidate, policy, mode, nonce, requester and issuance time to both request/response signatures;
Matching remembers nonce consumption, rejects replay/stale requests, checks Privacy permissions
and resolves current approval on every fetch. Candidate rechecks the policy before disclosure.

## Validation

`tests/test_matching_governance.py` exercises migrated services, signed Need/Privacy access,
independent approval, actual confirmed-search behavior, all-required rubric mappings, source
citation/unknown checks, expiration, calibration preregistration, signed policy retrieval and
replay, withdrawal, advice thresholds, condition gates and Privacy erasure. Wire tests in
`tests/test_matching_gateway.py` use only synthetic credentials and fake HTTPS responses.
