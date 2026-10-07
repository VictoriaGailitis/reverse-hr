"""Authentication, request binding, replay and delivery through signed service boundaries."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_event_transport import signatures as signatures_fixture
from test_matching_hiring import matches
from test_matching_hiring import setup as market_setup

from reverse_hr.db import Outbox
from reverse_hr.domains.matching import Projection
from reverse_hr.event_transport import MatchingConsumer
from reverse_hr.events import EventEnvelope
from reverse_hr.market_access import MarketAccess, context
from reverse_hr.market_contracts import MarketReceipt, MarketRequest
from reverse_hr.processing_access import canonical, sign

signatures = signatures_fixture
setup = market_setup


def request_for(s):
    return MarketRequest(
        candidate_id=s.candidate_id,
        requester="matching",
        purpose="profile",
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    )


def test_profile_export_nonce_signature_purpose_and_jwt_boundaries(setup):
    s = setup
    body = request_for(s)

    def send(body, signed):
        return s.candidate.client.post(
            "/internal/v1/market/profile",
            json=body.model_dump(mode="json"),
            headers={"X-HR-Signature": signed},
        )

    signed = sign(s.signatures["matching"], context("candidate", "profile", "request"), body)
    assert (
        s.candidate.client.post(
            "/internal/v1/market/profile", json=body.model_dump(mode="json"), headers=s.auth
        ).status_code
        == 401
    )
    assert (
        send(
            body, sign(s.signatures["hiring"], context("candidate", "profile", "request"), body)
        ).status_code
        == 401
    )
    assert (
        send(
            body, sign(s.signatures["matching"], context("candidate", "contacts", "request"), body)
        ).status_code
        == 401
    )
    assert send(body.model_copy(update={"candidate_id": uuid4()}), signed).status_code == 401
    response = send(body, signed)
    assert response.status_code == 200, response.text
    assert response.json()["allowed"] and response.json()["data"]["candidate_id"] == str(
        s.candidate_id
    )
    assert send(body, signed).status_code == 401
    denied = body.model_copy(update={"requester": "candidate", "nonce": uuid4()})
    assert (
        send(
            denied,
            sign(s.signatures["candidate"], context("candidate", "profile", "request"), denied),
        ).status_code
        == 401
    )
    stale = body.model_copy(
        update={"issued_at": datetime.now(UTC) - timedelta(minutes=1), "nonce": uuid4()}
    )
    assert (
        send(
            stale, sign(s.signatures["matching"], context("candidate", "profile", "request"), stale)
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "mutation", ["nonce", "candidate_id", "stale", "signature", "oversized", "extra_data"]
)
def test_matching_rejects_replayed_unbound_or_wrong_schema_receipt(setup, mutation):
    s = setup
    access = MarketAccess(s.matching.app.state.settings)
    access._signatures = s.signatures["matching"]
    original = s.matching.app.state.market_access.fetch(
        "candidate", "profile", candidate_id=s.candidate_id
    )

    def send(route, raw, signed, **_):
        body = MarketRequest.model_validate_json(raw)
        receipt = MarketReceipt(
            **body.model_dump(), allowed=True, revision=original.revision, data=original.data
        )
        if mutation in {"nonce", "candidate_id"}:
            receipt = receipt.model_copy(update={mutation: uuid4()})
        if mutation == "stale":
            receipt = receipt.model_copy(
                update={"issued_at": datetime.now(UTC) - timedelta(minutes=1)}
            )
        if mutation == "extra_data":
            receipt = receipt.model_copy(
                update={"data": receipt.data | {"email": "private@example.test"}}
            )
        signer = s.signatures["matching" if mutation == "signature" else "candidate"]
        return (b"x" * 16385 if mutation == "oversized" else canonical(receipt)), sign(
            signer, context("candidate", "profile", "response"), receipt
        )

    access._send = send
    with pytest.raises(HTTPException) as exc:
        access.fetch("candidate", "profile", candidate_id=s.candidate_id)
    assert exc.value.status_code == 503


def test_signed_consumer_forgery_retry_and_atomic_projection(setup):
    s = setup
    with Session(s.candidate.app.state.engine) as session:
        event = max(
            [
                EventEnvelope.model_validate(r.envelope)
                for r in session.scalars(select(Outbox))
                if r.envelope["event_type"] == "candidate.profile_updated.v1"
            ],
            key=lambda e: e.aggregate_version,
        )
    consumer = MatchingConsumer(
        s.matching.app.state.engine, s.signatures["matching"], s.matching.app.state.settings
    )
    consumer.access = s.matching.app.state.market_access
    channel = Mock()
    raw, signed = s.signatures["candidate"].sign(event)
    properties = SimpleNamespace(headers=signed, message_id=str(event.event_id))
    method = SimpleNamespace(exchange="events.candidate", delivery_tag=1)

    def ack(**_):
        with Session(s.matching.app.state.engine) as session:
            assert session.get(Projection, str(s.candidate_id)).card["confirmed_grade"] == "middle"

    channel.basic_ack.side_effect = ack
    consumer(channel, method, properties, raw)
    assert channel.basic_ack.call_count == 1
    channel.basic_publish.assert_not_called()
    channel.reset_mock()
    channel.basic_ack.side_effect = None
    consumer(channel, method, properties, raw + b" ")
    assert channel.basic_publish.call_args.kwargs["body"] == b'{"code":"invalid_event"}'
    channel.reset_mock()

    def unavailable(*_, **__):
        raise HTTPException(503)

    consumer.access = SimpleNamespace(fetch=unavailable)
    another = event.model_copy(update={"event_id": uuid4()})
    raw, signed = s.signatures["candidate"].sign(another)
    consumer(
        channel, method, SimpleNamespace(headers=signed, message_id=str(another.event_id)), raw
    )
    assert channel.basic_publish.call_args.kwargs["exchange"] == "retry.matching"


def test_unavailable_candidate_source_never_returns_cached_match(setup):
    s = setup
    saved = matches(s).json()

    def unavailable(*_, **__):
        raise HTTPException(503)

    original = s.matching.app.state.market_access.fetch

    def fetch(owner, purpose, **refs):
        if owner == "candidate":
            return unavailable()
        return original(owner, purpose, **refs)

    s.matching.app.state.market_access.fetch = fetch
    response = s.matching.client.get("/v1/matches/" + saved["snapshot_id"], headers=s.employer_auth)
    assert response.status_code == 503 and "Candidate" not in response.text
