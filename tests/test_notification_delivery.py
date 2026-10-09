"""External mail with fake provider; real signed source and Privacy permissions."""

import base64
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_code_runner import deletion
from test_event_transport import signatures as signatures_fixture
from test_hiring_dialogs import deliver_grant, deliver_notices, send
from test_hiring_dialogs import flow as dialog_flow
from test_matching_hiring import consent
from test_matching_hiring import setup as market_setup

from reverse_hr.db import Outbox
from reverse_hr.domains.notification import Preference, process_deletion_request
from reverse_hr.domains.notification_delivery import (
    CALLBACK_CONTEXT,
    Delivery,
    EmailChallenge,
    EmailTarget,
    ProviderCallback,
    claim,
    fanout_one,
    run_one,
    send_claim,
)
from reverse_hr.notification_provider import ChallengeCipher, ProviderUncertain
from reverse_hr.processing_access import canonical

signatures = signatures_fixture
setup = market_setup
flow = dialog_flow


class Provider:
    def __init__(self):
        self.messages = {}
        self.calls = []
        self.lose = False

    def send(self, mail):
        self.calls.append(mail)
        if mail.delivery_id in self.messages:
            assert self.messages[mail.delivery_id][0] == mail
        else:
            self.messages[mail.delivery_id] = (mail, str(uuid4()))
        if self.lose:
            self.lose = False
            raise ProviderUncertain()
        return self.messages[mail.delivery_id][1]


@pytest.fixture
def configured(flow):
    s = flow
    settings = s.notification.app.state.settings
    settings.notification_delivery_enabled = True
    settings.notification_application_link = "https://app.example.invalid/notifications"
    s.notification.app.state.notification_challenge_cipher = ChallengeCipher(b"x" * 32)
    s.callback_key = Ed25519PrivateKey.generate()
    s.notification.app.state.notification_provider_callback_key = s.callback_key.public_key()
    s.provider = Provider()
    s.email_consent = consent(s, "external_service_notifications")
    s.marketing_consent = consent(s, "external_marketing_notifications")
    deliver_grant(s)
    deliver_notices(s)
    return s


def request(s):
    return SimpleNamespace(app=s.notification.app, state=SimpleNamespace(trace_id=uuid4()))


def register(s):
    created = s.notification.client.post(
        "/v1/notifications/email",
        json={"email": "candidate@example.invalid", "consent_id": s.email_consent},
        headers=headers(s.auth, "challenge"),
    )
    assert created.status_code == 201, created.text
    assert "code" not in created.json()
    assert run_one(request(s), s.provider)
    mail = s.provider.calls[-1]
    code = re.search(r"\b(\d{6})\b", mail.text).group(1)
    confirmed = s.notification.client.post(
        "/v1/notifications/email/verify",
        json={"challenge_id": created.json()["challenge_id"], "code": code},
        headers=s.auth,
    )
    assert confirmed.status_code == 200 and confirmed.json()["verified"], confirmed.text
    response = s.notification.client.put(
        "/v1/notifications/email/preferences",
        json={
            "service_email": True,
            "marketing_email": False,
            "service_consent_id": s.email_consent,
        },
        headers=headers(s.auth, "emailprefs", 1),
    )
    assert response.status_code == 200, response.text
    return created.json(), mail, code


def new_notice(s):
    response = send(
        s,
        key="external-message",
        auth=s.employer_auth,
        text="PRIVATE BODY candidate-phone+79990001122",
    )
    assert response.status_code == 201, response.text
    deliver_notices(s)
    assert fanout_one(request(s))
    with Session(s.notification.app.state.engine) as session:
        return session.scalar(select(Delivery).where(Delivery.category == "service")).delivery_id


def test_verified_challenge_private_storage_and_email_independent_of_inapp(configured):
    s = configured
    _, mail, code = register(s)
    with Session(s.notification.app.state.engine) as session, session.begin():
        target = session.get(EmailTarget, str(s.candidate_id))
        assert target.verified
        challenge = session.scalar(select(EmailChallenge))
        assert code not in challenge.code_digest and challenge.ciphertext is None
        session.add(
            Preference(subject=str(s.candidate_id), in_app=False, marketing_in_app=False, version=1)
        )
    # Pre-opt-in accepted-invitation notices must not be bulk mailed.
    assert not fanout_one(request(s))
    job = new_notice(s)
    assert run_one(request(s), s.provider)
    assert len(s.provider.calls) == 2
    generic = s.provider.calls[-1]
    assert generic.delivery_id == job
    assert "PRIVATE" not in generic.text and "+7999" not in generic.text
    assert "https://app.example.invalid/notifications" in generic.text
    with Session(s.notification.app.state.engine) as session:
        assert session.get(Delivery, job).status == "submitted"
        assert len(list(session.scalars(select(Outbox)))) == 2


def test_consent_revoke_between_claim_send_cancels_without_provider_call(configured):
    s = configured
    register(s)
    job = new_notice(s)
    claimed = claim(request(s))
    assert claimed[0] == job
    revoked = s.privacy.client.post(
        "/v1/consents/" + s.email_consent + "/revoke", headers=headers(s.auth, "revoke-email", 1)
    )
    assert revoked.status_code == 200, revoked.text
    assert send_claim(request(s), s.provider, *claimed)
    assert len(s.provider.calls) == 1
    with Session(s.notification.app.state.engine) as session:
        assert session.get(Delivery, job).status == "cancelled"


def test_uncertain_provider_response_retries_stable_effect_and_old_lease_rejected(configured):
    s = configured
    register(s)
    job = new_notice(s)
    old = claim(request(s))
    s.provider.lose = True
    assert send_claim(request(s), s.provider, *old)
    assert not send_claim(request(s), s.provider, *old)
    future = datetime.now(UTC) + timedelta(seconds=61)
    assert run_one(request(s), s.provider, now=future)
    assert s.provider.calls[-1] == s.provider.calls[-2]
    assert len(s.provider.messages) == 2
    with Session(s.notification.app.state.engine) as session:
        row = session.get(Delivery, job)
        assert row.status == "submitted" and row.attempts == 2


def callback(s, job, *, seq=1, status="delivered", body=None, signature=None):
    with Session(s.notification.app.state.engine) as session:
        provider_id = session.get(Delivery, job).provider_id
    value = body or ProviderCallback(
        delivery_id=UUID(job),
        provider_id=UUID(provider_id),
        event_id=uuid4(),
        nonce=uuid4(),
        sequence=seq,
        status=status,
        issued_at=datetime.now(UTC),
    )
    signed = (
        signature
        or base64.b64encode(s.callback_key.sign(CALLBACK_CONTEXT + canonical(value))).decode()
    )
    response = s.notification.client.post(
        "/v1/notifications/provider-callback",
        content=canonical(value),
        headers={"Content-Type": "application/json", "X-HR-Signature": signed},
    )
    return response, value


def test_signed_callback_replay_outoforder_and_terminal_status(configured):
    s = configured
    register(s)
    job = new_notice(s)
    run_one(request(s), s.provider)
    assert callback(s, job, signature="bad")[0].status_code == 401
    response, body = callback(s, job, seq=3)
    assert response.status_code == 200, response.text
    assert callback(s, job, body=body)[0].json()["replayed"]
    assert callback(s, job, seq=2, status="failed")[0].json()["ignored"]
    assert callback(s, job, seq=4, status="failed")[0].json()["ignored"]
    with Session(s.notification.app.state.engine) as session:
        assert session.get(Delivery, job).status == "delivered"


def test_exhausted_final_crashed_lease_becomes_uncertain_without_send(configured):
    s = configured
    register(s)
    job = new_notice(s)
    now = datetime.now(UTC)
    claimed = claim(request(s), now=now)
    with Session(s.notification.app.state.engine) as session, session.begin():
        session.get(
            Delivery, job
        ).attempts = s.notification.app.state.settings.notification_delivery_max_attempts
    assert run_one(request(s), s.provider, now=now + timedelta(seconds=61))
    with Session(s.notification.app.state.engine) as session:
        assert session.get(Delivery, job).status == "uncertain_final"
    assert len(s.provider.calls) == 1
    assert not send_claim(request(s), s.provider, *claimed, now=now + timedelta(seconds=61))


def test_wrong_challenge_attempt_bounds_expiry_replacement_and_privacy(configured):
    s = configured
    register(s)
    job = new_notice(s)
    with Session(s.notification.app.state.engine) as session, session.begin():
        session.get(EmailTarget, str(s.candidate_id)).next_challenge_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        from reverse_hr.domains.notification_delivery import EmailRateWindow

        session.get(EmailRateWindow, str(s.candidate_id)).next_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
    change = s.notification.client.post(
        "/v1/notifications/email",
        json={"email": "new@example.invalid", "consent_id": s.email_consent},
        headers=headers(s.auth, "replace"),
    )
    assert change.status_code == 201, change.text
    with Session(s.notification.app.state.engine) as session:
        assert not session.get(EmailTarget, str(s.candidate_id)).verified
        assert session.get(Delivery, job).status == "cancelled"
    challenge_id = change.json()["challenge_id"]
    with Session(s.notification.app.state.engine) as session:
        secret = s.notification.app.state.notification_challenge_cipher.decrypt(
            session.get(EmailChallenge, challenge_id).ciphertext, challenge_id
        )
    wrong_code = "000000" if secret != "000000" else "111111"
    for _index in range(5):
        response = s.notification.client.post(
            "/v1/notifications/email/verify",
            json={"challenge_id": challenge_id, "code": wrong_code},
            headers=s.auth,
        )
        assert response.status_code == 200, response.text
    assert (
        s.notification.client.post(
            "/v1/notifications/email/verify",
            json={"challenge_id": challenge_id, "code": wrong_code},
            headers=s.auth,
        ).status_code
        == 409
    )
    with Session(s.notification.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.candidate_id))
    with Session(s.notification.app.state.engine) as session:
        assert list(session.scalars(select(EmailTarget))) == []
        assert list(session.scalars(select(EmailChallenge))) == []
        assert list(session.scalars(select(Delivery))) == []


def test_employer_self_verified_registration_and_authorized_dialog_notice(configured):
    s = configured
    candidate_auth = s.auth
    s.auth = s.employer_auth
    s.email_consent = consent(s, "external_service_notifications")
    register(s)
    response = send(s, key="candidate-employer-mail", auth=candidate_auth, text="private details")
    assert response.status_code == 201
    deliver_notices(s)
    assert fanout_one(request(s))
    assert run_one(request(s), s.provider)
    assert len(s.provider.calls) == 2
    assert "private details" not in s.provider.calls[-1].text
    assert (
        s.notification.client.get("/v1/notifications/email", headers=candidate_auth).json()["email"]
        is None
    )


def test_marketing_requires_independent_optin_and_fresh_purpose(configured, monkeypatch):
    from reverse_hr.domains.notification import NotificationRow
    from reverse_hr.domains.notification_delivery import EmailPreference

    s = configured
    register(s)
    with Session(s.notification.app.state.engine) as session, session.begin():
        row = session.scalar(
            select(NotificationRow).where(NotificationRow.recipient_id == str(s.candidate_id))
        )
        row.category = "marketing"
        row.created_at = datetime.now(UTC)
    assert not fanout_one(request(s))
    prefs = s.notification.client.put(
        "/v1/notifications/email/preferences",
        json={
            "service_email": True,
            "marketing_email": True,
            "service_consent_id": s.email_consent,
            "marketing_consent_id": s.email_consent,
        },
        headers=headers(s.auth, "bad-marketing", 2),
    )
    assert prefs.status_code == 409
    prefs = s.notification.client.put(
        "/v1/notifications/email/preferences",
        json={
            "service_email": True,
            "marketing_email": True,
            "service_consent_id": s.email_consent,
            "marketing_consent_id": s.marketing_consent,
        },
        headers=headers(s.auth, "marketing-optin", 2),
    )
    assert prefs.status_code == 200
    # Synthetic source fixture isolates category consent. Ordinary dialog source binding
    # is covered by the real signed service/email path above.
    monkeypatch.setattr("reverse_hr.domains.notification_delivery.available", lambda *a, **k: True)
    with Session(s.notification.app.state.engine) as session, session.begin():
        row = session.scalar(
            select(NotificationRow).where(NotificationRow.recipient_id == str(s.candidate_id))
        )
        row.created_at = datetime.now(UTC)
    assert fanout_one(request(s))
    assert not fanout_one(request(s))
    claimed = claim(request(s))
    revoked = s.privacy.client.post(
        "/v1/consents/" + s.marketing_consent + "/revoke",
        headers=headers(s.auth, "revoke-marketing", 1),
    )
    assert revoked.status_code == 200
    assert send_claim(request(s), s.provider, *claimed)
    assert len(s.provider.calls) == 1
    with Session(s.notification.app.state.engine) as session:
        assert session.get(EmailPreference, str(s.candidate_id)).service_email
        assert session.get(Delivery, claimed[0]).status == "cancelled"


def test_recovered_permission_cannot_send_without_committed_audit(configured, monkeypatch):
    from fastapi import HTTPException

    from reverse_hr.domains import notification_delivery

    s = configured
    register(s)
    job = new_notice(s)
    original, calls = notification_delivery.authorize_job, []

    def transient_first_check(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise HTTPException(503)
        return original(*args, **kwargs)

    monkeypatch.setattr(notification_delivery, "authorize_job", transient_first_check)
    assert run_one(request(s), s.provider)
    assert len(s.provider.calls) == 1  # Verification only; no unjournaled notice.
    with Session(s.notification.app.state.engine) as session:
        row = session.get(Delivery, job)
        assert row.status == "uncertain"
        retry_at = row.next_at.replace(tzinfo=UTC) + timedelta(seconds=1)
        assert len(list(session.scalars(select(Outbox)))) == 1
    assert run_one(request(s), s.provider, now=retry_at)
    assert len(s.provider.calls) == 2
    with Session(s.notification.app.state.engine) as session:
        assert session.get(Delivery, job).status == "submitted"
        assert len(list(session.scalars(select(Outbox)))) == 2
