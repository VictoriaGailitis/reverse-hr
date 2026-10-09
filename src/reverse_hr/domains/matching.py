"""Consent-gated candidate projection and reproducible requirement snapshots."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import JSON, String, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.achievement_contracts import AchievementEvidence
from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, execute
from reverse_hr.contracts import Contract, Grade
from reverse_hr.db import consume_once
from reverse_hr.market_contracts import CandidateCard, NeedView
from reverse_hr.market_state import SubjectColumns, lock
from reverse_hr.matching_conditions import ConditionComparison, compare_conditions
from reverse_hr.test_suites import digest

RANKING_VERSION = "confirmed-grade-declared-skills-v1"


class MatchingBase(DeclarativeBase):
    pass


class MatchingSubject(SubjectColumns, MatchingBase):
    __tablename__ = "matching_subjects"


class Projection(MatchingBase):
    __tablename__ = "matching_candidates"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int]
    card: Mapped[dict | None] = mapped_column(JSON)


class MatchSnapshot(MatchingBase):
    __tablename__ = "matching_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requested_by: Mapped[str] = mapped_column(String(36), index=True)
    need_author: Mapped[str] = mapped_column(String(36), index=True)
    query: Mapped[dict] = mapped_column(JSON)
    need_digest: Mapped[str] = mapped_column(String(64))
    matches: Mapped[list] = mapped_column(JSON)
    next_cursor: Mapped[str | None] = mapped_column(String(36))


class MatchQuery(Contract):
    organization_id: UUID
    need_id: UUID
    mode: Literal["production", "demo"] = "production"
    after: UUID | None = None
    ranking_policy: Literal["legacy", "verified-demo-v1", "governed-v1"] = "legacy"
    policy_id: UUID | None = None
    intent_preview_id: UUID | None = None
    desired_competencies: list[str] = Field(default_factory=list, max_length=20)
    minimum_competency_score: int = Field(default=70, strict=True, ge=0, le=100)
    maximum_evidence_age_days: int = Field(default=365, strict=True, ge=1, le=3650)

    @model_validator(mode="after")
    def competencies(self):
        normalized = [value.strip().casefold() for value in self.desired_competencies]
        if any(
            not value or len(value) > 64 or any(ord(c) < 32 for c in value) for value in normalized
        ) or len(set(normalized)) != len(normalized):
            raise ValueError("Invalid desired competencies")
        self.desired_competencies = sorted(normalized)
        return self


class MatchedCandidate(CandidateCard):
    explanation: str
    score: int = Field(ge=0, le=100)
    ranking_version: Literal[
        "confirmed-grade-declared-skills-v1",
        "confirmed-grade-achievements-v2",
        "verified-competencies-demo-v1",
        "governed-v1",
    ] = RANKING_VERSION
    policy_id: UUID | None = None
    catalog_id: UUID | None = None
    policy_version: str | None = None
    condition_comparison: ConditionComparison | None = None
    score_components: dict[str, int] = Field(default_factory=dict)
    evaluated_on: date | None = None
    calibrated: bool = False
    achievement_evidence: list[AchievementEvidence] = Field(default_factory=list, max_length=50)
    achievement_bonus: int = Field(default=0, ge=0, le=5)
    achievement_ids: list[UUID] = Field(default_factory=list, max_length=50)


class MatchResult(Contract):
    snapshot_id: UUID
    mode: Literal["production", "demo"]
    matches: list[MatchedCandidate]
    next_cursor: UUID | None


router = APIRouter(prefix="/v1/matches", tags=["matching"])


def card_from(receipt, candidate):
    if not receipt.allowed:
        return None
    card = CandidateCard.model_validate(receipt.data)
    if card.candidate_id != candidate or card.version != receipt.revision:
        raise HTTPException(503)
    return card


def process_profile_change(session, event, access):
    candidate_event = event.producer == "candidate" and event.event_type in {
        "candidate.profile_created.v1",
        "candidate.profile_updated.v1",
    }
    consent_event = event.producer == "privacy" and event.event_type == "privacy.consent_revoked.v1"
    if (
        not (candidate_event or consent_event)
        or set(event.payload)
        != ({"candidate_id"} if candidate_event else {"candidate_id", "consent_id"})
        or event.aggregate_id != event.payload["candidate_id" if candidate_event else "consent_id"]
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)
    subject = event.payload["candidate_id"]
    receipt = access.fetch("candidate", "profile", candidate_id=subject)
    card = card_from(receipt, subject)
    if candidate_event and receipt.revision < event.aggregate_version and card is not None:
        raise HTTPException(503)

    def apply(session, event):
        state = lock(session, MatchingSubject, subject, allow_blocked=True)
        if state.blocked:
            return
        row = session.get(Projection, str(subject))
        if row is None:
            row = Projection(candidate_id=str(subject), revision=0)
            session.add(row)
        if not receipt.allowed:
            row.card, row.revision = None, max(row.revision, receipt.revision)
            return
        if receipt.revision < row.revision:
            return
        access.check(subject)
        data = card.model_dump(mode="json")
        if (
            row.card is not None
            and receipt.revision == row.revision
            and CandidateCard.model_validate(row.card).model_dump(mode="json") != data
        ):
            raise HTTPException(409)
        row.card, row.revision = data, receipt.revision

    return consume_once(session, "matching.profile_change", event, apply)


def need_for(request, actor, query):
    actor.require("employer")
    receipt = request.app.state.market_access.require(
        "hiring",
        "need",
        candidate_id=actor.subject,
        actor_id=actor.subject,
        organization_id=query.organization_id,
        need_id=query.need_id,
    )
    need = NeedView.model_validate(receipt.data)
    if (
        need.need_id != query.need_id
        or need.organization_id != query.organization_id
        or need.version != receipt.revision
    ):
        raise HTTPException(503)
    from reverse_hr.domains.matching_governance import reviewed_need

    return reviewed_need(request, actor, query, need)


def rank(card, need, mode):
    if (
        card.confirmed_grade is None
        or card.decision_id is None
        or (mode == "production" and card.demo)
        or card.specialization != need.specialization
        or not set(need.required_skills) <= set(card.declared_skills)
    ):
        return None
    distance = list(Grade).index(card.confirmed_grade) - list(Grade).index(need.confirmed_grade)
    if distance < 0:
        return None
    return MatchedCandidate(
        **card.model_dump(),
        score=100 - 10 * distance,
        explanation="Confirmed specialization/grade meets the need; "
        "required skills match candidate declarations. "
        "Skills are not independently verified; grade distance=" + str(distance),
    ).model_dump(mode="json")


def verified_rank(card, need, query, evaluated_on=None):
    from reverse_hr.qualification import freshness

    proof = card.qualification
    if (
        proof is None
        or card.confirmed_grade is None
        or card.decision_id is None
        or card.specialization != need.specialization
        or list(Grade).index(card.confirmed_grade) < list(Grade).index(need.confirmed_grade)
        or query.mode != "demo"
    ):
        return None
    today = evaluated_on or datetime.now(UTC).date()
    now = datetime.combine(today, datetime.max.time(), tzinfo=UTC)
    if (now - proof.assessed_at).days > query.maximum_evidence_age_days:
        return None
    scores = proof.competency_scores
    if any(scores.get(key, -1) < query.minimum_competency_score for key in need.required_skills):
        return None
    keys = sorted(set(need.required_skills) | set(query.desired_competencies))
    # Unspecified desired requirements are explicit missing evidence, never declarations.
    competency = sum(scores.get(key, 0) for key in keys) // len(keys) if keys else 100
    state, recency = freshness(proof.assessed_at, now)
    components = {
        "competency": competency,
        "assessment": proof.score,
        "freshness": recency,
        "achievement_bonus": 0,
    }
    score = (55 * competency + 25 * proof.score + 15 * recency) // 100
    return MatchedCandidate(
        **card.model_dump(),
        score=score,
        ranking_version="verified-competencies-demo-v1",
        score_components=components,
        evaluated_on=today,
        calibrated=False,
        explanation=f"Human-confirmed {card.confirmed_grade}; reviewed competency coverage "
        f"{competency}/100, assessment {proof.score}/100, evidence {state}. "
        "Demo weights 55/25/15 plus bounded achievement bonus 5; uncalibrated. "
        "Declared skills do not satisfy verified requirements.",
    ).model_dump(mode="json")


def enriched_rank(request, card, need, mode, query=None, evaluated_on=None):
    verified = query is not None and query.ranking_policy in {"verified-demo-v1", "governed-v1"}
    governed = query is not None and query.ranking_policy == "governed-v1"
    if governed:
        from reverse_hr.domains.matching_governance import governed_rank

        value = governed_rank(request, card, need, query, evaluated_on)
    else:
        value = (
            verified_rank(card, need, query, evaluated_on) if verified else rank(card, need, mode)
        )
    if value is None:
        return value
    if need.conditions is not None:
        maximum_age = 90
        if governed:
            from reverse_hr.domains.matching_governance import ranking_context

            maximum_age = ranking_context(request, query.policy_id, mode)[
                0
            ].maximum_preference_age_days
        comparison = compare_conditions(
            need.conditions, card.preferences, maximum_age_days=maximum_age
        )
        if not comparison.eligible:
            return None
        value["condition_comparison"] = comparison.model_dump(mode="json")
        value["explanation"] += (
            "; employment conditions match candidate-confirmed self-description; "
            "these are not verified skills."
        )
    if not request.app.state.settings.matching_achievements_enabled:
        return value
    data = request.app.state.exchange_access.call(
        "achievements", "summary", card.candidate_id, uuid4(), mode=mode
    )
    if (
        set(data) != {"achievements"}
        or not isinstance(data["achievements"], list)
        or len(data["achievements"]) > 50
    ):
        raise HTTPException(503)
    items = [AchievementEvidence.model_validate(item) for item in data["achievements"]]
    relevant = [
        item
        for item in items
        if item.specialization == need.specialization
        and item.format == "individual"
        and (mode == "demo" or not item.demo)
    ]
    cap = 5
    if governed:
        from reverse_hr.domains.matching_governance import ranking_context

        cap = ranking_context(request, query.policy_id, mode)[0].achievement_cap
    bonus = min(cap, 2 * len(relevant))
    value.update(
        score=min(100, value["score"] + bonus),
        ranking_version="governed-v1"
        if governed
        else "verified-competencies-demo-v1"
        if verified
        else "confirmed-grade-achievements-v2",
        achievement_bonus=bonus,
        achievement_ids=[str(item.achievement_id) for item in relevant],
        achievement_evidence=[item.model_dump(mode="json") for item in relevant],
    )
    if verified:
        value["score_components"]["achievement_bonus"] = bonus
    value["explanation"] += (
        f"; relevant confirmed individual achievements={len(relevant)}, bounded bonus={bonus}. "
        "Achievements do not change grade."
    )
    return value


@router.post("", response_model=MatchResult, status_code=201)
def find(request: Request, actor: Actor, body: MatchQuery, idempotency: CommandKey):
    if request.app.state.settings.deployment_mode == "production" and body.mode == "demo":
        raise HTTPException(409, "Demo matching disabled in production")
    if body.ranking_policy == "verified-demo-v1" and body.mode != "demo":
        raise HTTPException(409, "Verified ranking policy requires calibration for production")
    if body.ranking_policy == "governed-v1":
        from reverse_hr.domains.matching_governance import load_policy

        load_policy(request, body.policy_id, body.mode)
    elif body.policy_id is not None or body.intent_preview_id is not None:
        raise HTTPException(422, "Policy and intent require governed ranking")
    need = need_for(request, actor, body)
    with Session(request.app.state.engine) as session:
        query = select(Projection).where(Projection.card["candidate_id"].as_string().is_not(None))
        if body.after:
            query = query.where(Projection.candidate_id > str(body.after))
        rows = list(session.scalars(query.order_by(Projection.candidate_id).limit(201)))
        ids = [UUID(row.candidate_id) for row in rows[:200]]
        next_cursor = str(ids[-1]) if len(rows) > 200 else None
    matches = []
    for subject in ids:
        receipt = request.app.state.market_access.fetch(
            "candidate", "profile", candidate_id=subject
        )
        card = card_from(receipt, subject)
        if card:
            value = enriched_rank(request, card, need, body.mode, body)
            if value:
                matches.append(value)
    matches.sort(key=lambda row: (-row["score"], row["candidate_id"]))

    def guard(session):
        if body.ranking_policy == "governed-v1":
            from reverse_hr.domains.matching_governance import load_policy

            load_policy(request, body.policy_id, body.mode)
        for subject in sorted(
            {str(actor.subject), str(need.created_by)} | {row["candidate_id"] for row in matches}
        ):
            lock(session, MatchingSubject, subject)
        if digest(need_for(request, actor, body)) != digest(need):
            raise HTTPException(409)

    def change(session):
        row = MatchSnapshot(
            snapshot_id=str(uuid4()),
            requested_by=str(actor.subject),
            need_author=str(need.created_by),
            query=body.model_dump(mode="json"),
            need_digest=digest(need),
            matches=matches,
            next_cursor=next_cursor,
        )
        session.add(row)
        return {"snapshot_id": row.snapshot_id}

    def present(session, result):
        return render(request, actor, session.get(MatchSnapshot, result["snapshot_id"]))

    return execute(
        request.app.state.engine,
        actor.subject,
        "find_matches",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=present,
    )


def render(request, actor, row):
    if row is None or row.requested_by != str(actor.subject):
        raise HTTPException(404)
    query = MatchQuery.model_validate(row.query)
    if query.ranking_policy == "governed-v1":
        from reverse_hr.domains.matching_governance import load_policy

        load_policy(request, query.policy_id, query.mode)
    need = need_for(request, actor, query)
    from reverse_hr.domains.matching_governance import need_binding_matches

    if not need_binding_matches(row.need_digest, need):
        raise HTTPException(409)
    result = []
    for match in row.matches:
        receipt = request.app.state.market_access.fetch(
            "candidate", "profile", candidate_id=UUID(match["candidate_id"])
        )
        card = card_from(receipt, UUID(match["candidate_id"]))
        if card is not None and card.version == match["version"]:
            # Any mismatch, withdrawal or changed criteria suppresses stale sensitive fields.
            current = enriched_rank(
                request,
                card,
                need,
                query.mode,
                query,
                date.fromisoformat(match["evaluated_on"]) if match.get("evaluated_on") else None,
            )
            if (
                query.ranking_policy in {"verified-demo-v1", "governed-v1"}
                and card.qualification is not None
            ):
                if (
                    datetime.now(UTC) - card.qualification.assessed_at
                ).days > query.maximum_evidence_age_days:
                    continue
            if current == match:
                result.append(match)
    return MatchResult(
        snapshot_id=row.snapshot_id, mode=query.mode, matches=result, next_cursor=row.next_cursor
    ).model_dump(mode="json")


@router.get("/{snapshot_id}", response_model=MatchResult)
def get_snapshot(request: Request, actor: Actor, snapshot_id: UUID):
    actor.require("employer")
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, MatchingSubject, actor.subject)
        return render(request, actor, session.get(MatchSnapshot, str(snapshot_id)))


def process_deletion_request(session, event):
    from reverse_hr.market_cleanup import erase

    def scrub(subject):
        from reverse_hr.domains.matching_governance import GovernanceVersion, IntentPreview

        session.execute(delete(IntentPreview).where(IntentPreview.actor_id == subject))
        for version in session.scalars(
            select(GovernanceVersion).where(
                (GovernanceVersion.author_id == subject)
                | (GovernanceVersion.reviewer_id == subject)
            )
        ):
            version.status = "revoked"
            version.author_id = str(UUID(int=0))
            version.reviewer_id = None
            version.reason = "Privacy deletion; version unavailable"
            version.revision += 1
        session.execute(delete(Projection).where(Projection.candidate_id == subject))
        # Erase historical queries containing this subject, including cached disclosures.
        for row in session.scalars(select(MatchSnapshot)):
            if (
                row.requested_by == subject
                or row.need_author == subject
                or any(m["candidate_id"] == subject for m in row.matches)
            ):
                session.delete(row)

    return erase(session, event, "matching", MatchingSubject, scrub)


class QueryPreviewCommand(Contract):
    organization_id: UUID
    need_id: UUID
    text: str = Field(min_length=1, max_length=4000)


class QueryPreview(Contract):
    proposed_query: MatchQuery
    confirmed_requirements: NeedView
    unparsed_text: str
    requires_employer_confirmation: Literal[True] = True
    parser_version: Literal["explicit-competency-demo-v1"] = "explicit-competency-demo-v1"
    warnings: list[str]


@router.post("/query-preview", response_model=QueryPreview)
def query_preview(request: Request, actor: Actor, body: QueryPreviewCommand):
    """Bounded deterministic fallback. The existing confirmed need remains authoritative."""
    query = MatchQuery(
        organization_id=body.organization_id,
        need_id=body.need_id,
        mode="demo",
        ranking_policy="verified-demo-v1",
    )
    need = need_for(request, actor, query)
    request.app.state.processing_access.check(actor.subject)
    # Recognize only explicit approved requirements, never fabricate a skills taxonomy.
    import re

    words = set(re.findall(r"[\w.+#-]+", body.text.casefold()))
    query.desired_competencies = sorted(set(need.required_skills) & words)
    return QueryPreview(
        proposed_query=query,
        confirmed_requirements=need,
        unparsed_text=body.text,
        warnings=[
            "No configured LLM parser. Only explicit competency keys from this confirmed need "
            "are recognized; specialization, grade, mandatory requirements and conditions "
            "must be edited and confirmed in the need before searching.",
            "Preview does not execute or save a search. Submit the reviewed query explicitly.",
        ],
    )


class ComparisonCommand(Contract):
    candidate_ids: list[UUID] = Field(min_length=2, max_length=10)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("Duplicate candidate")
        return self


@router.post("/{snapshot_id}/comparison", response_model=MatchResult)
def comparison(request: Request, actor: Actor, snapshot_id: UUID, body: ComparisonCommand):
    actor.require("employer")
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, MatchingSubject, actor.subject)
        data = render(request, actor, session.get(MatchSnapshot, str(snapshot_id)))
        allowed = {item["candidate_id"] for item in data["matches"]}
        if not {str(value) for value in body.candidate_ids} <= allowed:
            raise HTTPException(404, "Candidate unavailable in this current snapshot")
        data["matches"] = [
            item for item in data["matches"] if UUID(item["candidate_id"]) in body.candidate_ids
        ]
        return data


@router.post("/{snapshot_id}/refinements", response_model=MatchResult, status_code=201)
def refine(
    request: Request, actor: Actor, snapshot_id: UUID, body: MatchQuery, idempotency: CommandKey
):
    """A reviewed refinement creates a new snapshot; the prior calculation is immutable."""
    actor.require("employer")
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, MatchingSubject, actor.subject)
        row = session.get(MatchSnapshot, str(snapshot_id))
        if row is None or row.requested_by != str(actor.subject):
            raise HTTPException(404)
        original = MatchQuery.model_validate(row.query)
        if original.organization_id != body.organization_id or original.need_id != body.need_id:
            raise HTTPException(409, "Refinement must retain its authorized need")
    return find(request, actor, body, idempotency)


# Register governance routes and service-owned metadata after the base router is defined.
from reverse_hr.domains import matching_governance as matching_governance  # noqa: E402
