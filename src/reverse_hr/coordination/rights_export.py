"""Explicit owner projections and signed, revision-bound streaming export pages.

The digest covers the complete permitted projection on every page. A changing
source aborts capture; immutable Privacy pages never mix source revisions.
"""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from pydantic import RootModel
from sqlalchemy import MetaData, Table, inspect, select

from reverse_hr.shared.signing import sign, verify

CHUNK = 32768
PAGE_RECORDS = 100  # JSON page is additionally bounded by encoded byte size.
# owner: table -> (ownership column, explicitly permitted columns)
SPECS = {
    "achievements": {
        "achievement_connections": (
            "candidate_id",
            "connection_id source_id status external_account version",
        ),
        "achievement_history": ("candidate_id", "achievement_id version action at snapshot"),
        "achievements": (
            "candidate_id",
            "achievement_id source_id data status published demo version",
        ),
    },
    "assessment": {
        "assessment_generated_variants": (
            "created_by",
            "revision_id template_id parameters created_at",
        ),
        "assessment_appeal_actions": ("candidate_id", "appeal_id version action at"),
        "assessment_appeal_decisions": (
            "candidate_id",
            "appeal_id target_grade status score "
            "competency_scores reason created_at "
            "next_attempt_at",
        ),
        "assessment_appeals": (
            "candidate_id",
            "appeal_id session_id decision_id reason status "
            "version submitted_at filing_deadline "
            "review_due_at",
        ),
        "assessment_sessions": (
            "candidate_id",
            "session_id status version created_at current_stage_id stages "
            "selection_policy_id selection_policy_digest",
        ),
        "candidate_grades": (
            "candidate_id",
            "specialization grade decision_id changed_at change_available_at",
        ),
        "company_assignments": (
            "candidate_id",
            "assignment_id organization_id proposal_id "
            "plan_version_id session_id status version "
            "expires_at",
        ),
        "company_schedules": (
            "candidate_id",
            "schedule_id organization_id status version "
            "starts_at expires_in_days interval_seconds "
            "max_occurrences issued_count",
        ),
        "company_subscriptions": ("candidate_id", "organization_id status version consent_id"),
        "grade_decisions": (
            "candidate_id",
            "decision_id session_id specialization "
            "target_grade status score competency_scores "
            "next_attempt_at reason created_at",
        ),
    },
    "candidate": {
        "candidate_task_subscriptions": (
            "candidate_id",
            "enabled stack_tags interval_hours version consent_id",
        ),
        "candidate_task_recommendations": ("candidate_id", "notice_id version_id data created_at"),
        "candidate_contacts": ("candidate_id", "email phone version"),
        "candidate_grade_history": ("candidate_id", "decision_id session_id summary received_at"),
        "candidate_preferences": (
            "candidate_id",
            "document version confirmed_at share_in_matching",
        ),
        "candidate_profiles": (
            "candidate_id",
            "display_name specialization declared_grade additional_specializations version",
        ),
        "candidate_publication": ("candidate_id", "published declared_skills"),
        "candidate_resume_imports": (
            "candidate_id",
            "import_id digest size status version extraction proposal",
        ),
        "candidate_resumes": ("candidate_id", "fields version published"),
    },
    "code-runner": {
        "runner_jobs": (
            "candidate_id",
            "run_id workspace_id snapshot_id snapshot_version format status error_code created_at",
        )
    },
    "coding-workspace": {
        "workspaces": ("candidate_id", "workspace_id session_id stage_id format version")
    },
    "employer": {"memberships": ("subject", "membership_id organization_id role status version")},
    "evaluation": {
        "evaluation_risks": (
            "candidate_id",
            "stage_id source_digest codes rule_version status version "
            "created_at reason verification_stage_id",
        ),
        "evaluation_intakes": (
            "candidate_id",
            "stage_id session_id workspace_id snapshot_id "
            "status version received_at score "
            "review_number",
        ),
        "evaluation_reviews": (
            "candidate_id",
            "review_id stage_id number intake_version decisions score reason created_at",
        ),
    },
    "hiring": {
        "hiring_applications": (
            "candidate_id",
            "application_id organization_id vacancy_id invitation_id status version",
        ),
        "hiring_complaints": ("author_id", "complaint_id dialog_id message_id reason created_at"),
        "hiring_employer_reviews": (
            "author_id",
            "review_id organization_id invitation_id data status version",
        ),
        "hiring_invitation_revisions": (
            "candidate_id",
            "invitation_id version predecessor_id terms recorded_at",
        ),
        "hiring_invitations": (
            "candidate_id",
            "invitation_id organization_id spec status version expires_at",
        ),
        "hiring_messages": ("author_id", "message_id dialog_id text sequence created_at"),
        "hiring_moderation_appeals": (
            "author_id",
            "appeal_id target_id target_version kind data status version",
        ),
        "hiring_notices": ("recipient_id", "notice_id kind invitation_id application_id"),
    },
    "integration": {
        "ats_delivery_counters": ("candidate_id", "organization_id sequence"),
        "ats_status_receipts": ("candidate_id", "receipt_id job_id sequence status"),
        "integration_jobs": (
            "candidate_id",
            "job_id kind connection_id organization_id "
            "invitation_id sequence status version attempts "
            "created_at completed_at error_code external_id "
            "external_status status_sequence",
        ),
    },
    "matching": {
        "matching_candidates": ("candidate_id", "revision card"),
        "matching_snapshots": ("requested_by", "snapshot_id query need_digest"),
    },
    "media": {
        "recordings": (
            "candidate_id",
            "id session_id stage_id format mime size expected_digest "
            "client_duration_ms version status created_at finalized_at "
            "snapshot_id validation",
        )
    },
    "notification": {
        "notification_notices": (
            "recipient_id",
            "notice_id invitation_id assignment_id "
            "appeal_id application_id owner category "
            "kind read version",
        ),
        "notification_preferences": ("subject", "in_app marketing_in_app version"),
    },
    "privacy": {
        "company_result_grants": (
            "candidate_id",
            "grant_id assignment_id organization_id status version",
        ),
        "consents": (
            "candidate_id",
            "consent_id purpose document_version status version granted_at revoked_at",
        ),
        "contact_grants": ("candidate_id", "grant_id invitation_id organization_id status version"),
        "deletion_requests": ("candidate_id", "request_id requested_at completed_at"),
        "privacy_request_history": ("candidate_id", "request_id version action at details"),
        "privacy_subject_requests": (
            "candidate_id",
            "request_id kind domain purpose status data "
            "restriction_active version created_at "
            "due_at completed_at",
        ),
    },
    "proctoring": {
        "integrity_tracks": (
            "candidate_id",
            "id session_id stage_id version timeline_version review_number",
        )
    },
    "whiteboard": {
        "boards": ("candidate_id", "id session_id stage_id format version status state")
    },
}
SPECS["assessment"].update(
    {
        "company_assignment_origins": (
            "candidate_id",
            "assignment_id organization_id schedule_id subscription_version issued_at",
        ),
        "company_delivery_limits": ("candidate_id", "organization_id last_at"),
        "company_jobs": (
            "candidate_id",
            "job_id organization_id schedule_id assignment_id kind status next_at attempts error",
        ),
    }
)
SPECS["code-runner"]["runner_results"] = (
    "candidate_id",
    "run_id status exit_code reason completed_at",
)

SPECS["employer"]["employer_trust_appeals"] = (
    "author_id",
    "appeal_id organization_id target_id data status version",
)
SPECS["matching"].update(
    {
        "matching_intent_previews": (
            "actor_id",
            "preview_id organization_id need_id document expires_at confirmed",
        ),
        "matching_governance_versions": (
            "author_id",
            "version_id kind content_digest status revision",
        ),
    }
)

# Creator projections are separate from recipient projections, and reviewer
# actions contain only their action references, never another person's result.
OWN_ACTIONS = {
    "assessment": [
        ("assessment_selection_policies", "created_by", "policy_id data status version created_at"),
        (
            "assessment_variant_templates",
            "created_by",
            "template_id data status version created_at",
        ),
        ("assessment_selection_policies", "reviewed_by", "policy_id status version review_reason"),
        ("assessment_variant_templates", "reviewed_by", "template_id status version review_reason"),
        (
            "company_task_proposals",
            "created_by",
            "proposal_id organization_id name content digest status version "
            "created_at reviewed_at revision_id",
        ),
        ("content_revisions", "created_by", "revision_id family_id number content status version"),
        ("plan_versions", "created_by", "plan_version_id name specialization grade version"),
        ("grade_decisions", "reviewer_id", "decision_id status created_at"),
        ("assessment_appeals", "reviewer_id", "appeal_id status version"),
        (
            "company_assignments",
            "created_by",
            "assignment_id organization_id status version expires_at",
        ),
        (
            "company_schedules",
            "created_by",
            "schedule_id organization_id starts_at interval_seconds status version",
        ),
    ],
    "hiring": [
        ("hiring_needs", "created_by", "need_id organization_id spec version"),
        (
            "hiring_vacancies",
            "created_by",
            "vacancy_id need_id organization_id spec status revision version",
        ),
        (
            "hiring_invitations",
            "created_by",
            "invitation_id organization_id spec status version expires_at",
        ),
    ],
    "employer": [
        (
            "verification_decisions",
            "reviewer_id",
            "decision_id organization_id status source decided_at",
        ),
        ("ownership_recoveries", "reviewer_id", "recovery_id organization_id decided_at"),
        (
            "employer_trust_decisions",
            "reviewer_id",
            "decision_id organization_id dimension status source decided_at version",
        ),
        (
            "employer_sanctions",
            "reviewer_id",
            "sanction_id organization_id starts_at ends_at status version",
        ),
    ],
    "evaluation": [("evaluation_reviews", "reviewer_id", "review_id stage_id number created_at")],
    "matching": [
        ("matching_governance_versions", "reviewer_id", "version_id kind status revision")
    ],
    "achievements": [
        ("achievement_history", "actor_id", "history_id achievement_id version action at")
    ],
    "privacy": [("privacy_request_history", "actor_id", "history_id request_id version action at")],
}

SPECS["evaluation"]["evaluation_model_attempts"] = (
    "candidate_id",
    "attempt_id stage_id number model prompt_version status duration_ms created_at output",
)
OWN_ACTIONS["hiring"].append(
    (
        "hiring_invitation_revisions",
        "created_by",
        "invitation_id version predecessor_id terms recorded_at",
    )
)


SPECS["assessment"].update(
    {
        "assessment_generation_references": (
            "author_id",
            "version_id reference_id number data digest status version created_at",
        ),
        "assessment_generation_previews": (
            "author_id",
            "preview_id version_id specification digest expires_at generation_id",
        ),
        "assessment_generation_jobs": (
            "author_id",
            "generation_id version_id status attempts error specification output "
            "created_at plan_version_id",
        ),
        "assessment_automatic_reviews": (
            "candidate_id",
            "session_id status reasons created_at updated_at appeal_id case_origin",
        ),
    }
)
SPECS["evaluation"]["evaluation_automatic_reviews"] = (
    "candidate_id",
    "stage_id status reason updated_at",
)
OWN_ACTIONS["assessment"].append(
    (
        "assessment_generation_references",
        "approved_by",
        "version_id reference_id number digest status version",
    )
)
# Provenance is part of a subject's permitted history.
for service, table in (("assessment", "grade_decisions"), ("evaluation", "evaluation_reviews")):
    owner, fields = SPECS[service][table]
    SPECS[service][table] = (owner, fields + " origin")


JOINS = {
    "assessment": [
        (
            "assessment_stages",
            "assessment_sessions",
            "session_id",
            "session_id",
            "stage_id position status version started_at deadline submitted_at "
            "workspace_id snapshot_id snapshot_version digest",
        )
    ],
    "coding-workspace": [
        (
            "workspace_snapshots",
            "workspaces",
            "workspace_id",
            "workspace_id",
            "snapshot_id version digest created_at files",
        )
    ],
    "hiring": [
        (
            "hiring_application_changes",
            "hiring_applications",
            "application_id",
            "application_id",
            "change_id version status changed_at",
        )
    ],
    "proctoring": [
        (
            "proctor_events",
            "integrity_tracks",
            "track_id",
            "id",
            "id ordinal source kind sequence client_time elapsed_ms occurred_at received_at flags",
        ),
        (
            "integrity_reviews",
            "integrity_tracks",
            "track_id",
            "id",
            "id number timeline_version outcome reason created_at",
        ),
    ],
    "whiteboard": [
        (
            "board_operations",
            "boards",
            "board_id",
            "id",
            "operation_id version command received_at",
        ),
        ("board_snapshots", "boards", "board_id", "id", "id version state digest"),
    ],
}

EXCLUDED_KEYS = {
    "reviewer_id",
    "actor_id",
    "author_id",
    "created_by",
    "recipient_id",
    "employer_contact",
    "test_pins",
    "hidden_tests",
    "reference_answer",
    "rubric",
    "private_rubric",
    "test_suite",
    "secret",
    "object_key",
    "lease_id",
    "execution",
    "test_proof_digest",
    "prompt",
    "system_prompt",
    "gateway_configuration",
    "candidate_id",
    "representative_subject",
}


def safe(value):
    if isinstance(value, dict):
        return {k: safe(v) for k, v in value.items() if k not in EXCLUDED_KEYS}
    if isinstance(value, list):
        return [safe(v) for v in value]
    return value


def encode(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda x: x.isoformat(),
    ).encode()


def records(session, owner, subject):
    if owner == "identity":
        provider = getattr(session.get_bind(), "identity_export_provider", None)
        if provider is None:
            raise HTTPException(503, "External Identity export is not configured")
        yield from provider.records(subject)
        return
    if owner == "audit":
        from reverse_hr.services.audit.domain.audit import subject_export_records

        yield from subject_export_records(session, subject)
        return
    if owner not in SPECS:
        raise HTTPException(409, "Owner has no subject-export capability")
    schema = MetaData()
    available = set(inspect(session.connection()).get_table_names())
    for name, (ownership, permitted) in sorted(SPECS[owner].items()):
        if name not in available:
            raise HTTPException(503, "Required owner export table is missing")
        table = Table(name, schema, autoload_with=session.connection())
        if ownership not in table.c:
            raise HTTPException(503, "Owner export schema does not match ownership contract")
        if any(n not in table.c for n in permitted.split()):
            raise HTTPException(503, "Required owner export column is missing")
        columns = [table.c[n] for n in permitted.split()]
        primary = list(table.primary_key.columns)
        query = (
            select(*primary, *[c for c in columns if c not in primary])
            .where(table.c[ownership] == str(subject))
            .order_by(*primary)
        )
        if name == "hiring_invitations":
            query = query.where(table.c.status != "draft")
        if name == "hiring_invitation_revisions":
            invitation = Table(
                "hiring_invitations",
                schema,
                autoload_with=session.connection(),
                extend_existing=True,
            )
            query = query.join(
                invitation, table.c.invitation_id == invitation.c.invitation_id
            ).where(invitation.c.status != "draft")
        for row in session.execute(query.execution_options(yield_per=64)).mappings():
            data = safe({c.name: row[c.name] for c in columns})
            if name == "assessment_sessions":
                progress = Table(
                    "assessment_stages",
                    schema,
                    autoload_with=session.connection(),
                    extend_existing=True,
                )
                submitted = set(
                    session.scalars(
                        select(progress.c.stage_id).where(
                            progress.c.session_id == row["session_id"],
                            progress.c.status == "submitted",
                        )
                    )
                )
                for stage in data.get("stages", []):
                    if stage.get("follows_stage_id") and stage["follows_stage_id"] not in submitted:
                        stage.pop("instruction", None)
            yield {"table": name, "key": ":".join(str(row[c.name]) for c in primary), "data": data}

    for name, ownership, permitted in OWN_ACTIONS.get(owner, []):
        if name not in available:
            raise HTTPException(503, "Required action export table is missing")
        table = Table(name, schema, autoload_with=session.connection(), extend_existing=True)
        if ownership not in table.c or any(n not in table.c for n in permitted.split()):
            raise HTTPException(503, "Required action export column is missing")
        columns = [table.c[n] for n in permitted.split()]
        primary = list(table.primary_key.columns)
        query = (
            select(*primary, *[c for c in columns if c not in primary])
            .where(table.c[ownership] == str(subject))
            .order_by(*primary)
            .execution_options(yield_per=64)
        )
        for row in session.execute(query).mappings():
            yield {
                "table": name + "@own_action",
                "key": ":".join(str(row[c.name]) for c in primary),
                "data": safe({c.name: row[c.name] for c in columns}),
            }
    for child, parent, foreign, parent_key, permitted in JOINS.get(owner, []):
        if child not in available or parent not in available:
            raise HTTPException(503, "Required owner export table is missing")
        table = Table(child, schema, autoload_with=session.connection(), extend_existing=True)
        owning = Table(parent, schema, autoload_with=session.connection(), extend_existing=True)
        if foreign not in table.c or parent_key not in owning.c:
            raise HTTPException(503, "Required owner export join is missing")
        if any(n not in table.c for n in permitted.split()):
            raise HTTPException(503, "Required owner export column is missing")
        columns = [table.c[n] for n in permitted.split()]
        primary = list(table.primary_key.columns)
        query = (
            select(*primary, *[c for c in columns if c not in primary])
            .join(owning, table.c[foreign] == owning.c[parent_key])
            .where(owning.c.candidate_id == str(subject))
            .order_by(*primary)
        )
        for row in session.execute(query.execution_options(yield_per=64)).mappings():
            yield {
                "table": child,
                "key": ":".join(str(row[c.name]) for c in primary),
                "data": safe({c.name: row[c.name] for c in columns}),
            }

    if owner == "employer":
        from reverse_hr.services.employer.domain.employer_trust import TrustDecision

        query = (
            select(TrustDecision)
            .where(TrustDecision.facts["representative_subject"].as_string() == str(subject))
            .order_by(TrustDecision.decision_id)
            .execution_options(yield_per=64)
        )
        for row in session.scalars(query):
            yield {
                "table": "employer_representative_facts",
                "key": row.decision_id,
                "data": {
                    "organization_id": row.organization_id,
                    "corporate_domain": row.facts.get("corporate_domain"),
                    "evidence_reference": row.facts.get("evidence_reference"),
                    "status": row.status,
                    "version": row.version,
                },
            }
    if owner == "coding-workspace":
        from reverse_hr.services.coding_workspace.domain.coding_workspace import RunRequest as Run
        from reverse_hr.services.coding_workspace.domain.coding_workspace import Snapshot, Workspace

        query = (
            select(Run)
            .join(Snapshot, Run.snapshot_id == Snapshot.snapshot_id)
            .join(Workspace, Snapshot.workspace_id == Workspace.workspace_id)
            .where(Workspace.candidate_id == str(subject))
            .order_by(Run.run_id)
            .execution_options(yield_per=64)
        )
        for row in session.scalars(query):
            yield {
                "table": "workspace_runs",
                "key": row.run_id,
                "data": {
                    "run_id": row.run_id,
                    "snapshot_id": row.snapshot_id,
                    "status": row.status,
                    "runner_version": row.runner_version,
                    "created_at": row.created_at,
                },
            }
    if owner == "candidate":
        from reverse_hr.services.candidate.domain.candidate_resume import ResumeImport, read_source

        for row in session.scalars(
            select(ResumeImport)
            .where(ResumeImport.candidate_id == str(subject))
            .order_by(ResumeImport.import_id)
            .execution_options(yield_per=1)
        ):
            if row.manifest:
                content = read_source(session, row)
                for number in range(0, len(content), CHUNK):
                    yield {
                        "table": "resume_source_pdf",
                        "key": f"{row.import_id}:{number // CHUNK}",
                        "data": {
                            "import_id": row.import_id,
                            "digest": row.digest,
                            "offset": number,
                            "base64": base64.b64encode(content[number : number + CHUNK]).decode(),
                        },
                    }

    if owner == "notification":
        from reverse_hr.services.notification.domain.notification_delivery import (
            subject_export_records,
        )

        yield from subject_export_records(session, subject)

    if owner == "media":
        from reverse_hr.services.media.domain.media import Recording, RecordingChunk, chunk_bytes

        query = (
            select(RecordingChunk, Recording)
            .join(Recording, RecordingChunk.recording_id == Recording.id)
            .where(Recording.candidate_id == str(subject))
            .order_by(RecordingChunk.recording_id, RecordingChunk.number)
            .execution_options(yield_per=1)
        )
        for part, recording in session.execute(query):
            raw = chunk_bytes(session, recording, part)
            for offset in range(0, len(raw), CHUNK):
                yield {
                    "table": "recording_source",
                    "key": f"{recording.id}:{part.number}:{offset}",
                    "data": {
                        "recording_id": recording.id,
                        "chunk": part.number,
                        "digest": part.digest,
                        "offset": offset,
                        "base64": base64.b64encode(raw[offset : offset + CHUNK]).decode(),
                    },
                }


def fragments(session, owner, subject):
    for record in records(session, owner, subject):
        raw = encode(record)
        count = max(1, (len(raw) + CHUNK - 1) // CHUNK)
        for part in range(count):
            yield {
                "table": record["table"],
                "key": record["key"],
                "part": part,
                "parts": count,
                "digest": hashlib.sha256(raw).hexdigest(),
                "base64": base64.b64encode(raw[part * CHUNK : (part + 1) * CHUNK]).decode(),
            }


def fingerprint(session, owner, subject):
    state = hashlib.sha256()
    for fragment in fragments(session, owner, subject):
        state.update(encode(fragment))
    return state.hexdigest()


def cursor_context(owner):
    return f"reverse-hr.subject-rights.{owner}.cursor.v1\0".encode()


def make_cursor(signatures, owner, binding, source, offset):
    payload = dict(
        binding,
        source=source,
        offset=offset,
        expires=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    )
    return (
        base64.urlsafe_b64encode(encode(payload)).decode()
        + "."
        + sign(signatures, cursor_context(owner), RootModel[dict](payload))
    )


def read_cursor(signatures, owner, token, binding):
    try:
        raw, signature = token.split(".", 1)
        payload = json.loads(base64.urlsafe_b64decode(raw))
        verify(signatures, owner, signature, cursor_context(owner), RootModel[dict](payload))
        if any(payload.get(k) != v for k, v in binding.items()) or datetime.fromisoformat(
            payload["expires"]
        ) < datetime.now(UTC):
            raise ValueError("Unbound or expired cursor")
        if type(payload["offset"]) is not int or payload["offset"] < 0:
            raise ValueError("Invalid offset")
        return payload
    except Exception as exc:
        raise HTTPException(401, "Invalid export cursor") from exc


def page(session, owner, subject, request_id, revision, signatures, token=None):
    binding = {
        "owner": owner,
        "subject": str(subject),
        "request_id": str(request_id),
        "revision": revision,
    }
    previous = read_cursor(signatures, owner, token, binding) if token else None
    offset = previous["offset"] if previous else 0
    items, more = [], False
    state = hashlib.sha256()
    # Capture and digest the same stream: an A -> B -> A source change must
    # never attach A's fingerprint to a page containing B's data.
    for index, fragment in enumerate(fragments(session, owner, subject)):
        state.update(encode(fragment))
        if index < offset:
            continue
        if (
            more
            or len(items) == PAGE_RECORDS
            or (items and len(encode(items + [fragment])) > 56000)
        ):
            more = True
            continue
        items.append(fragment)
    source = state.hexdigest()
    if previous and previous["source"] != source:
        raise HTTPException(409, "Permitted source changed during archive capture")
    if fingerprint(session, owner, subject) != source:
        raise HTTPException(409, "Permitted source changed during page capture")
    return {
        "source_digest": source,
        "records": items,
        "next_cursor": make_cursor(signatures, owner, binding, source, offset + len(items))
        if more
        else None,
        "complete": not more,
    }
