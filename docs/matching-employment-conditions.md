# Matching employment conditions

Candidate employment preferences are explicitly confirmed **self-description**, not verified
skills, a confirmed employment status or a guarantee that the candidate can start work.

## Candidate control and provenance

`GET /v1/candidates/me/preferences` returns the current preference version and own values.
`PUT /v1/candidates/me/preferences` requires `If-Match: "0"` for the first record or its current
version, an idempotency key and explicit JSON `confirmed: true`. It accepts:

* `salary`: positive integer RUB/month minimum/maximum with explicit `gross` or `net` basis;
* `salary_tolerance_percent`: explicit 0–25% tolerance applied to that stated range;
* `work_formats`: any explicit choices from `remote`, `hybrid`, `onsite`;
* `start_window`: both `earliest` and `latest` ISO calendar dates, inclusive;
* `share_in_matching`: false by default, independent of keeping the values in the private account.

Missing salary, no selected format or an absent start window remain unknown. A tolerance without
an explicit range is invalid. Dates cannot be timestamps or inferred open-ended windows. Each
update stamps server confirmation time, advances the preference and Candidate profile versions
and emits the existing profile-change event. Signed cards contain only shared preferences and
only while the profile publication consent and processing permission remain valid, checked
before and after card construction. Cards label `candidate_confirmed_self_description`, version
and `confirmed_at`, and never gain candidate contacts. Withholding preferences immediately
suppresses their use and invalidates previously returned candidates through the fresh profile
version check. Command replays return current own values after later correction or withdrawal.

Privacy correction uses the same validated helper with source-preference version and optional
source-profile version CAS. The Privacy rights registry can export own document, version,
confirmation and sharing state. Deletion removes preferences before the Candidate ACK; the local
subject tombstone blocks old command replay and late writes. Candidate migration `0007_candidate`
also supplies contact versions for separate Privacy contact-correction CAS.

## Company terms and actual filtering

Hiring's typed `Need.conditions` and vacancy/invitation `conditions` use `EmploymentConditions`.
A newly supplied typed vacancy condition copies its advertised salary to the matching Need;
conflicting top-level/nested salaries or conditions are rejected. An application invitation uses
the same approved vacancy snapshot conditions. Existing unstructured vacancies without typed
conditions retain their earlier behavior until explicitly edited to use them.

Every selected candidate is compared against any typed company constraints:

* RUB/month ranges overlap inclusively after the candidate's stated tolerance. Gross/net mismatch
  is unknown, not a tax calculation; other currency/period inputs are rejected. There is no FX.
* At least one explicitly chosen work format must overlap. An empty candidate list is unknown.
* Explicit start windows overlap and include a current/future UTC calendar day. An elapsed
  window cannot establish future availability. An omitted bound cannot mean unlimited availability.

Unknown or incompatible required conditions exclude the candidate. The result includes a typed
`condition_comparison`, provenance, preference version and explanations. This filter does not
add verified competency points or change grade. Governed policies pin
`maximum_preference_age_days` (default 90); legacy typed-condition searches use 90 days.
Expired preference confirmation is unknown for those conditions. Saved comparisons rerun fresh
candidate permission and condition gates, so withheld values, revised preferences, withdrawn
publication, elapsed windows and stale confirmations cannot disclose a historical candidate card.

## Semantic request confirmation

Parser prompt `employer-intent-v2` adds `employment_conditions` to the editable structured
proposal. Every salary component, work choice and date bound needs an exact supporting source
quote. Currency, monthly period and gross/net basis must be stated in the source, even though
RUB/month are the fixed API contract defaults. Numeric/date values are checked against the
quoted source; missing years, inferred FX, ambiguous tax basis and omitted mentioned conditions
remain unknown. The explicit fallback recognizes mentions and marks mentioned employment
conditions unknown rather than inventing ranges or employment status.

Employer confirmation does not privately change company terms: supplied typed conditions must
match the current Hiring-owned Need. Alter them through Hiring, then parse and confirm against
the new Need version. Actual search always uses the authoritative company conditions, even if a
proposal omits them. Unresolved free-text conditions and specific unknowns still block automatic
matching. The older general `conditions` unknown marker only indicates that no additional
conditions were supplied; a mentioned missing salary, format or availability is a specific unknown.

Immutable catalog/policy documents keep their original raw JSON digest when a new optional
preference-age field is introduced. Legacy Need digests without optional `conditions` remain
compatible only while current conditions are still absent; adding company constraints invalidates
the old binding.

## Tests

`tests/test_matching_conditions.py` covers signed migrated services, hidden/public preferences,
actual governed condition filtering, publication withdrawal, stale confirmation, net/gross and
currency refusal, touching ranges, explicit tolerance, inclusive and elapsed date boundaries,
source quotes and unknowns, typed confirmation → search → invitation acceptance, Privacy erasure,
correction CAS and replay after edits. Synthetic tests do not call a provider or make claims about
actual candidate employment availability.
