"""Signed arrival evidence, bounded Privacy export and concurrent chain writes."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.protocols.audit_access import REQUEST_CONTEXT, DisclosureRequest, record_disclosure
from reverse_hr.services.audit.consumer import AuditConsumer
from reverse_hr.services.audit.domain.audit import (
    AuditEntry,
    ChainHead,
    Stream,
    append,
    erase_subject,
    prune,
    subject_export_records,
    verify_chain,
)
from reverse_hr.shared.db import Outbox
from reverse_hr.shared.event_transport import canonical
from reverse_hr.shared.signing import canonical as dto_canonical
from reverse_hr.shared.signing import sign
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture


@pytest.fixture
def target(service, signatures):
    result = service("audit")
    result.app.state.audit_signatures = signatures["audit"]
    result.app.state.processing_access = SimpleNamespace(check=lambda *_: None)
    return result


def event(*, actor=None, candidate=None, aggregate=None, version=1, **kwargs):
    return EventEnvelope(
        producer="hiring",
        event_type="hiring.contacts_disclosed.v1",
        aggregate_id=aggregate or uuid4(),
        aggregate_version=version,
        correlation_id=uuid4(),
        payload={
            "actor_id": actor or uuid4(),
            "candidate_id": candidate or uuid4(),
            "resource_id": uuid4(),
        },
        **kwargs,
    )


def archive(target, signatures, value, **kwargs):
    body, headers = signatures[value.producer].sign(value)
    with Session(target.app.state.engine) as session, session.begin():
        row = append(
            session,
            value,
            body,
            headers["hr-signature"],
            signatures["audit"],
            target.app.state.settings,
            **kwargs,
        )
        return row.sequence if row else None


def audit_headers(token, subject=None, *, mfa=True, role="audit_reviewer"):
    return token(subject, (role,), amr=["mfa"] if mfa else [])


def test_verified_consumer_original_proof_replay_gap_and_stale(target, signatures):
    consumer = AuditConsumer(
        target.app.state.engine,
        signatures["audit"],
        target.app.state.settings,
        processing=target.app.state.processing_access,
    )
    aggregate = uuid4()
    values = [event(aggregate=aggregate, version=v) for v in (1, 3, 2, 3, 4)]
    channel = Mock()
    for value in values + [values[0]]:
        body, headers = signatures["hiring"].sign(value)
        consumer(
            channel,
            SimpleNamespace(exchange="events.hiring", delivery_tag=1),
            SimpleNamespace(headers=headers, message_id=str(value.event_id)),
            body,
        )
    assert channel.basic_ack.call_count == 6
    assert not channel.basic_publish.called
    with Session(target.app.state.engine) as session, session.begin():
        rows = list(session.scalars(select(AuditEntry).order_by(AuditEntry.sequence)))
        assert [r.delivery for r in rows] == ["initial", "gap", "stale", "same_version", "next"]
        assert rows[0].original_body.encode() == canonical(values[0])
        assert rows[0].original_signature == signatures["hiring"].sign(values[0])[1]["hr-signature"]
        assert session.scalar(select(Stream)).version == 4
        assert verify_chain(session, signatures["audit"])["verified"]


def test_forged_wrong_route_and_conflicting_signed_replay_are_rejected(target, signatures):
    value = event()
    body, headers = signatures["hiring"].sign(value)
    consumer = AuditConsumer(
        target.app.state.engine,
        signatures["audit"],
        target.app.state.settings,
        processing=target.app.state.processing_access,
    )
    channel = Mock()
    consumer(
        channel,
        SimpleNamespace(exchange="events.hiring", delivery_tag=1),
        SimpleNamespace(
            headers=headers | {"hr-signature": base64.b64encode(b"x" * 64).decode()},
            message_id=str(value.event_id),
        ),
        body,
    )
    assert channel.basic_publish.call_args.kwargs["exchange"] == "dead.audit"
    channel.reset_mock()
    consumer(
        channel,
        SimpleNamespace(exchange="events.employer", delivery_tag=1),
        SimpleNamespace(headers=headers, message_id=str(value.event_id)),
        body,
    )
    assert channel.basic_publish.call_args.kwargs["exchange"] == "dead.audit"
    with Session(target.app.state.engine) as session:
        assert session.scalar(select(AuditEntry)) is None
    archive(target, signatures, value)
    changed = value.model_copy(update={"aggregate_version": 2})
    with pytest.raises(HTTPException) as error:
        archive(target, signatures, changed)
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "column,value",
    [
        ("original_body", "{}"),
        ("original_signature", "bad"),
        ("references", {"candidate_id": str(uuid4())}),
        ("event_type", "hiring.forged.v1"),
        ("chain_digest", "0" * 64),
        ("erased", True),
    ],
)
def test_tampering_is_detected(target, signatures, column, value):
    archive(target, signatures, event())
    with Session(target.app.state.engine) as session, session.begin():
        setattr(session.get(AuditEntry, 1), column, value)
    with (
        Session(target.app.state.engine) as session,
        session.begin(),
        pytest.raises(HTTPException) as error,
    ):
        verify_chain(session, signatures["audit"])
    assert error.value.status_code == 409


def test_concurrent_global_chain_serialization_and_duplicate(target, signatures):
    values = [event() for _ in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        sequences = list(
            pool.map(lambda item: archive(target, signatures, item), values + [values[0]])
        )
    assert len(set(sequences)) == 8
    with Session(target.app.state.engine) as session, session.begin():
        assert verify_chain(session, signatures["audit"])["last_sequence"] == 8
        rows = list(session.scalars(select(AuditEntry).order_by(AuditEntry.sequence)))
        assert rows[-1].chain_digest == session.get(ChainHead, 1).digest


def test_search_independence_mfa_case_actor_and_read_receipts(target, signatures, token):
    actor, candidate = uuid4(), uuid4()
    value = event(actor=actor, candidate=candidate)
    archive(target, signatures, value)
    auth = audit_headers(token)
    assert (
        target.client.get("/v1/audit/entries", headers=audit_headers(token, mfa=False)).status_code
        == 403
    )
    assert (
        target.client.get(
            "/v1/audit/entries", headers=audit_headers(token, role="employer")
        ).status_code
        == 403
    )
    own = target.client.get("/v1/audit/entries", headers=audit_headers(token, actor))
    assert own.status_code == 200 and own.json() == []
    rows = target.client.get(
        "/v1/audit/entries",
        params={"by_actor": str(candidate), "by_case": str(value.aggregate_id)},
        headers=auth,
    )
    assert rows.status_code == 200, rows.text
    assert rows.json()[0]["entry_id"] == str(value.event_id)
    assert "original_body" not in rows.json()[0]
    assert (
        target.client.get("/v1/audit/entries/" + str(value.event_id), headers=auth).status_code
        == 200
    )
    assert target.client.get("/v1/audit/verify", headers=auth).json()["verified"]
    with Session(target.app.state.engine) as session:
        receipts = list(session.scalars(select(Outbox)))
        assert len(receipts) == 4
        assert all(r.envelope["event_type"] == "audit.journal_read.v1" for r in receipts)


def test_signed_disclosure_effect_retry_conflict_and_no_raw_contacts(target, signatures):
    body = DisclosureRequest(
        owner="hiring",
        kind="contacts",
        effect_id=uuid4(),
        resource_id=uuid4(),
        actor_id=uuid4(),
        candidate_id=uuid4(),
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    )

    def submit(value, signature=None):
        return target.client.post(
            "/internal/v1/audit/disclosures",
            content=dto_canonical(value),
            headers={
                "Content-Type": "application/json",
                "X-HR-Signature": signature or sign(signatures["hiring"], REQUEST_CONTEXT, value),
            },
        )

    assert submit(body, "invalid").status_code == 401
    first = submit(body)
    assert first.status_code == 200, first.text
    assert submit(body).status_code == 409
    retry = body.model_copy(update={"nonce": uuid4(), "issued_at": datetime.now(UTC)})
    result = submit(retry)
    assert result.status_code == 200, result.text
    assert result.json()["entry_id"] == first.json()["entry_id"]
    changed = retry.model_copy(update={"nonce": uuid4(), "candidate_id": uuid4()})
    assert submit(changed).status_code == 409
    raw = body.model_dump(mode="json") | {"contacts": "private@example.invalid"}
    assert target.client.post("/internal/v1/audit/disclosures", json=raw).status_code == 422
    with Session(target.app.state.engine) as session, session.begin():
        assert verify_chain(session, signatures["audit"])["last_sequence"] == 1


def test_owner_outbox_and_privacy_redaction_late_delivery_finite_retention(target, signatures):
    subject = uuid4()
    value = event(candidate=subject)
    archive(target, signatures, value)
    with Session(target.app.state.engine) as session:
        export = list(subject_export_records(session, subject))
        assert len(export) == 1
        assert str(value.payload["actor_id"]) not in str(export)
        assert str(subject) not in str(export)
    deletion = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        aggregate_id=uuid4(),
        aggregate_version=1,
        correlation_id=uuid4(),
        payload={"candidate_id": subject, "request_id": uuid4()},
    )
    deletion = deletion.model_copy(update={"aggregate_id": deletion.payload["request_id"]})
    with Session(target.app.state.engine) as session, session.begin():
        assert erase_subject(
            session, deletion, target.app.state.settings, signatures=signatures["audit"]
        )
        assert not erase_subject(
            session, deletion, target.app.state.settings, signatures=signatures["audit"]
        )
    assert archive(target, signatures, value) == 1
    archive(target, signatures, event(candidate=subject))
    with Session(target.app.state.engine) as session, session.begin():
        rows = list(session.scalars(select(AuditEntry)))
        assert all(row.original_body is None and row.references == {} for row in rows)
        assert verify_chain(session, signatures["audit"])["verified"]
        assert list(subject_export_records(session, subject)) == []
        assert (
            prune(
                session,
                target.app.state.settings,
                now=datetime.now(UTC) + timedelta(days=366),
                signatures=signatures["audit"],
            )
            == 0
        )
        # Both original records were already Privacy-redacted; proof-only boundary remains.
        assert len(list(session.scalars(select(AuditEntry)))) == 1
        assert verify_chain(session, signatures["audit"])["verified"]
    # Owner helper only appends UUID refs and rolls back with business transaction.
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(service_name="hiring"))),
        state=SimpleNamespace(trace_id=uuid4()),
    )
    with Session(target.app.state.engine) as session, session.begin():
        receipt = record_disclosure(session, request, "contacts", uuid4(), uuid4(), subject)
    with Session(target.app.state.engine) as session:
        row = session.get(Outbox, str(receipt))
        assert set(row.envelope["payload"]) == {"resource_id", "actor_id", "candidate_id"}


def test_privacy_consumer_ack_and_restriction_minimum_proof(target, signatures):
    subject = uuid4()
    archive(target, signatures, event(candidate=subject))
    deletion = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        aggregate_id=uuid4(),
        aggregate_version=1,
        correlation_id=uuid4(),
        payload={"candidate_id": subject, "request_id": uuid4()},
    )
    deletion = deletion.model_copy(update={"aggregate_id": deletion.payload["request_id"]})

    def restricted(candidate):
        if candidate == subject:
            raise HTTPException(409)

    consumer = AuditConsumer(
        target.app.state.engine,
        signatures["audit"],
        target.app.state.settings,
        processing=SimpleNamespace(check=restricted),
    )
    channel = Mock()
    for value in [deletion, deletion, event(candidate=subject)]:
        body, headers = signatures[value.producer].sign(value)
        consumer(
            channel,
            SimpleNamespace(exchange="events." + value.producer, delivery_tag=1),
            SimpleNamespace(headers=headers, message_id=str(value.event_id)),
            body,
        )
    assert channel.basic_ack.call_count == 3
    assert not channel.basic_publish.called
    with Session(target.app.state.engine) as session, session.begin():
        entries = list(session.scalars(select(AuditEntry)))
        assert all(e.erased and e.original_body is None and e.redaction_signature for e in entries)
        assert verify_chain(session, signatures["audit"])["verified"]
        assert len(list(session.scalars(select(Outbox)))) == 1
        assert session.scalar(select(Outbox)).envelope["event_type"] == "audit.data_deleted.v1"


def test_tail_or_head_corruption_cannot_be_sealed_by_next_append(target, signatures):
    archive(target, signatures, event())
    with Session(target.app.state.engine) as session, session.begin():
        session.get(ChainHead, 1).digest = "f" * 64
    with pytest.raises(HTTPException) as error:
        archive(target, signatures, event())
    assert error.value.status_code == 409
    with Session(target.app.state.engine) as session:
        assert len(list(session.scalars(select(AuditEntry)))) == 1
