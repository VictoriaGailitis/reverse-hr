"""Migrated services, signed Privacy/Hiring RPC and real isolated PDF subprocesses."""

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_code_runner import deletion
from test_matching_hiring import consent, invite
from test_matching_hiring import setup as setup
from test_matching_hiring import signatures as signatures

from reverse_hr.db import Outbox
from reverse_hr.domains.candidate import process_deletion_request
from reverse_hr.domains.candidate_resume import Resume, ResumeImport, configure, run_import_one
from reverse_hr.domains.privacy import process_accepted_invitation
from reverse_hr.events import EventEnvelope
from reverse_hr.migrate import migration_config
from reverse_hr.resume_contracts import ExtractedPDF, PDFData
from reverse_hr.resume_pdf_guest import create_app

FONT = str(
    Path.home()
    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler"
    / "poppler/fonts/DejaVuSans.ttf"
)
if not Path(FONT).is_file():
    FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FIELDS = dict(
    display_name="Анна Иванова",
    specialization="backend",
    declared_grade="lead",
    declared_skills=["Python"],
    summary=(
        "Python developer; anna@example.test; +7 (999) 123-45-67; https://t.me/anna; Анна Иванова"
    ),
    experience=["Backend engineering"],
    education=["University"],
    contacts={"email": "anna@example.test", "phone": "+7 (999) 123-45-67"},
)


class Guest:
    def __init__(self, client):
        self.client = client

    def extract(self, raw):
        response = self.client.post("/extract", content=raw)
        if response.status_code != 200:
            raise HTTPException(response.status_code)
        return ExtractedPDF.model_validate(response.json())

    def render(self, data):
        response = self.client.post(
            "/render", json=PDFData.model_validate(data).model_dump(mode="json")
        )
        assert response.status_code == 200, response.text
        return response.content


@pytest.fixture(scope="module")
def guest():
    with TestClient(create_app(isolated=False, font=FONT, languages="eng")) as client:
        assert client.get("/ready").status_code == 200
        yield Guest(client)


@pytest.fixture
def resumes(setup, tmp_path, guest):
    s = setup
    configure(
        s.candidate.app.state.engine,
        SimpleNamespace(
            resume_storage_root=str(tmp_path / "resumes"), resume_antivirus_required=False
        ),
    )
    s.candidate.app.state.resume_guest = guest
    s.guest = guest
    return s


def source(guest):
    return guest.render(
        PDFData(
            variant="full",
            name=FIELDS["display_name"],
            specialization="backend",
            declared_grade="lead",
            confirmed_grade=None,
            declared_skills=["python"],
            summary=FIELDS["summary"],
            experience=FIELDS["experience"],
            education=FIELDS["education"],
            email=FIELDS["contacts"]["email"],
        )
    )


def upload(s, raw=None, key=None):
    return s.candidate.client.post(
        "/v1/candidates/me/resume-imports",
        content=raw if raw is not None else source(s.guest),
        headers=headers(s.auth, key or str(uuid4())) | {"Content-Type": "application/pdf"},
    )


def work(s, **kwargs):
    return run_import_one(
        s.candidate.app.state.engine,
        s.candidate.app.state.processing_access,
        kwargs.pop("guest", s.guest),
        kwargs.pop("scanner", None),
        **kwargs,
    )


def confirm(s):
    item = upload(s).json()
    assert work(s)
    item = s.candidate.client.get(
        "/v1/candidates/me/resume-imports/" + item["import_id"], headers=s.auth
    ).json()
    assert item["status"] == "review_ready", item
    profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    response = s.candidate.client.post(
        "/v1/candidates/me/resume-imports/" + item["import_id"] + "/confirm",
        json=FIELDS | {"profile_version": profile["version"]},
        headers=headers(s.auth, "confirm", item["version"]),
    )
    assert response.status_code == 200, response.text
    return item, response.json()


def publish(s):
    _, resume = confirm(s)
    s.resume_consent = consent(s, "resume_publication")
    response = s.candidate.client.put(
        "/v1/candidates/me/resume/publication",
        json={"published": True, "consent_id": s.resume_consent},
        headers=headers(s.auth, "publish-resume", resume["version"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def download(s, variant="anonymous", invitation=None, own=False):
    return s.candidate.client.get(
        f"/v1/candidates/{s.candidate_id}/resume.pdf",
        params={"variant": variant, "organization_id": s.organization_id}
        | ({"invitation_id": invitation} if invitation else {}),
        headers=s.auth if own else s.employer_auth,
    )


def text(response):
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages)


def accept(s, application=False):
    if application:
        from test_hiring_vacancies import app_action, apply, publish

        publish(s)
        s.application = app_action(s, apply(s).json(), "invite", body={}).json()
        invitation = s.application["invitation_id"]
    else:
        invitation = invite(s).json()["invitation_id"]
    s.disclosure = consent(s, "contact_disclosure")
    response = s.hiring.client.post(
        "/v1/invitations/" + invitation + "/accept",
        json={"disclosure_consent_id": s.disclosure},
        headers=headers(s.auth, "accept", 1),
    )
    assert response.status_code == 200, response.text
    with Session(s.hiring.app.state.engine) as session:
        event = next(
            EventEnvelope.model_validate(row.envelope)
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "hiring.invitation_accepted.v1"
        )
    with Session(s.privacy.app.state.engine) as session, session.begin():
        process_accepted_invitation(session, event)
    return invitation


def test_import_dedup_confirmation_versions_and_verified_grade(resumes):
    s = resumes
    raw = source(s.guest)
    first = upload(s, raw, "original")
    assert first.status_code == 201, first.text
    assert upload(s, raw, "again").json()["import_id"] == first.json()["import_id"]
    assert not s.candidate.client.get("/v1/candidates/me/resume", headers=s.auth).status_code == 200
    assert work(s)
    assert not work(s)
    item = s.candidate.client.get(
        "/v1/candidates/me/resume-imports/" + first.json()["import_id"], headers=s.auth
    ).json()
    assert "Анна" in item["extraction"]["text"] and item["extraction"]["ocr_pages"] == []
    assert (
        s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()["display_name"]
        == "Candidate"
    )
    profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    body = FIELDS | {"profile_version": profile["version"]}
    path = "/v1/candidates/me/resume-imports/" + item["import_id"] + "/confirm"
    assert (
        s.candidate.client.post(path, json=body, headers=headers(s.auth, "stale", 1)).status_code
        == 409
    )
    confirmed = s.candidate.client.post(
        path, json=body, headers=headers(s.auth, "confirmed", item["version"])
    )
    assert confirmed.status_code == 200, confirmed.text
    assert (
        s.candidate.client.post(
            path, json=body, headers=headers(s.auth, "confirmed", item["version"])
        ).status_code
        == 200
    )
    full = text(download(s, "full", own=True))
    assert "Анна Иванова" in full and "anna@example.test" in full
    assert "Verified grade: middle" in full and "Declared grade: lead" in full
    assert "Declared skills: python" in full


def test_anonymous_output_and_fresh_resume_and_profile_consent(resumes):
    s = resumes
    publish(s)
    anonymous = text(download(s))
    for secret in ("Анна", "Иванова", "anna@example.test", "999", "t.me/anna"):
        assert secret not in anonymous
    assert "Backend engineering" in anonymous and "Verified grade: middle" in anonymous
    assert download(s, "full").status_code == 422
    revoked = s.privacy.client.post(
        "/v1/consents/" + s.resume_consent + "/revoke", headers=headers(s.auth, "revoke", 1)
    )
    assert revoked.status_code == 200, revoked.text
    assert download(s).status_code == 409
    assert download(s, own=True).status_code == 200


@pytest.mark.parametrize("action", ["contacts", "profile", "invitation", "membership", "block"])
def test_full_permission_revocation(resumes, action):
    s = resumes
    publish(s)
    invitation = accept(s, application=action == "invitation")
    assert "anna@example.test" in text(download(s, "full", invitation))
    if action in {"contacts", "profile"}:
        cid = s.disclosure if action == "contacts" else s.consent
        assert (
            s.privacy.client.post(
                "/v1/consents/" + cid + "/revoke", headers=headers(s.auth, "withdraw", 1)
            ).status_code
            == 200
        )
    elif action == "invitation":
        from test_hiring_vacancies import app_action

        assert app_action(s, s.application, "withdraw", auth=s.auth).status_code == 200
    elif action == "membership":
        assert (
            s.employer.client.post(
                f"/v1/organizations/{s.organization_id}/verification",
                json={"status": "rejected", "reason": "Synthetic review"},
                headers=headers(s.moderator, "suspend", 2),
            ).status_code
            == 200
        )
    else:
        response = s.hiring.client.post(
            "/v1/dialogs/" + invitation + "/block",
            headers=headers(s.auth, "block", 1),
        )
        assert response.status_code == 200, response.text
    assert download(s, "full", invitation).status_code == 409


def test_consent_revoked_while_rendering(resumes):
    s = resumes
    publish(s)
    original = s.guest

    def rendering(data):
        result = original.render(data)
        assert (
            s.privacy.client.post(
                "/v1/consents/" + s.resume_consent + "/revoke",
                headers=headers(s.auth, "mid-render", 1),
            ).status_code
            == 200
        )
        return result

    s.candidate.app.state.resume_guest = SimpleNamespace(render=rendering)
    assert download(s).status_code == 409


def test_privacy_deletion_purges_blobs_and_late_processing(resumes):
    s = resumes
    item = upload(s).json()
    engine = s.candidate.app.state.engine
    event = deletion(s.candidate_id)

    def extraction(raw):
        report = s.guest.extract(raw)
        with Session(engine) as session, session.begin():
            process_deletion_request(session, event)
        return report

    assert work(s, guest=SimpleNamespace(extract=extraction))
    with Session(engine) as session:
        assert session.get(ResumeImport, item["import_id"]) is None
        assert session.get(Resume, str(s.candidate_id)) is None
    assert not (Path(engine.resume_store.root) / s.candidate_id.hex).exists()
    assert upload(s).status_code == 409
    assert not work(s)


def test_transient_retry_and_explicit_reprocessing(resumes):
    s = resumes
    item = upload(s).json()
    now = datetime.now(UTC)

    def outage(raw):
        raise HTTPException(503)

    for attempt in range(8):
        assert work(s, guest=SimpleNamespace(extract=outage), now=now + timedelta(days=attempt))
    item = s.candidate.client.get(
        "/v1/candidates/me/resume-imports/" + item["import_id"], headers=s.auth
    ).json()
    assert item["status"] == "failed" and item["attempts"] == 8
    assert (
        s.candidate.client.post(
            "/v1/candidates/me/resume-imports/" + item["import_id"] + "/retry",
            headers=headers(s.auth, "retry", item["version"]),
        ).status_code
        == 200
    )
    assert work(s)
    assert (
        s.candidate.client.get(
            "/v1/candidates/me/resume-imports/" + item["import_id"], headers=s.auth
        ).json()["status"]
        == "review_ready"
    )


def test_untrusted_pdf_limits_and_active_document_rejection(resumes):
    s = resumes
    assert upload(s, b"not PDF").status_code == 422
    assert upload(s, b"%PDF-" + b"x" * (2 * 1024 * 1024)).status_code == 413
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_js('app.alert("bad")')
    output = io.BytesIO()
    writer.write(output)
    item = upload(s, output.getvalue()).json()
    assert work(s)
    result = s.candidate.client.get(
        "/v1/candidates/me/resume-imports/" + item["import_id"], headers=s.auth
    ).json()
    assert result["status"] == "failed" and result["error"] == "invalid_pdf"
    assert (
        s.candidate.client.get(
            "/v1/candidates/me/resume-imports/" + item["import_id"] + "/source.pdf", headers=s.auth
        ).status_code
        == 409
    )


def test_real_ocr_scan(guest):
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import Canvas

    image = Image.new("RGB", (1600, 500), "white")
    ImageDraw.Draw(image).text(
        (60, 80),
        "Anna Engineer\nPython Backend Developer\nFive years experience",
        font=ImageFont.truetype(FONT, 60),
        fill="black",
    )
    output = io.BytesIO()
    canvas = Canvas(output, pagesize=(800, 250))
    canvas.drawImage(ImageReader(image), 0, 0, width=800, height=250)
    canvas.save()
    report = guest.extract(output.getvalue())
    assert report.ocr_pages == [1] and "Python" in report.text


def test_fail_closed_isolation_and_populated_migration(resumes):
    s = resumes
    with TestClient(create_app(font=FONT)) as client:
        assert client.get("/ready").status_code == 503
    confirm(s)
    with pytest.raises(RuntimeError, match="populated resume"):
        command.downgrade(migration_config(s.candidate.app.state.settings), "0005_candidate")
    assert s.candidate.client.get("/v1/candidates/me/resume", headers=s.auth).status_code == 200


def test_employer_cannot_fetch_original_or_another_subject_import(resumes):
    s = resumes
    item, _ = confirm(s)
    path = "/v1/candidates/me/resume-imports/" + item["import_id"]
    assert s.candidate.client.get(path + "/source.pdf", headers=s.auth).status_code == 200
    assert s.candidate.client.get(path + "/source.pdf", headers=s.employer_auth).status_code == 403
    assert s.candidate.client.get(path, headers=s.token(uuid4())).status_code == 404
    assert download(s).status_code == 409


def test_erasure_of_confirmed_resume_preserves_other_subject_and_stops_download(resumes):
    from reverse_hr.db import IdempotencyRecord

    s = resumes
    publish(s)
    engine = s.candidate.app.state.engine
    other = uuid4()
    auth = s.token(other)
    uploaded = s.candidate.client.post(
        "/v1/candidates/me/resume-imports",
        content=source(s.guest),
        headers=headers(auth, "other-source") | {"Content-Type": "application/pdf"},
    )
    assert uploaded.status_code == 201
    with Session(engine) as session, session.begin():
        process_deletion_request(session, deletion(s.candidate_id))
    with Session(engine) as session:
        assert session.get(Resume, str(s.candidate_id)) is None
        assert not list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(s.candidate_id))
            )
        )
        assert session.get(ResumeImport, uploaded.json()["import_id"]) is not None
    assert (engine.resume_store.root / other.hex).is_dir()
    assert not (engine.resume_store.root / s.candidate_id.hex).exists()
    assert download(s).status_code == 409


def test_pdf_import_requires_clean_av_and_never_parses_infected_data(resumes):
    from unittest.mock import Mock

    s = resumes
    item = upload(s).json()
    engine = s.candidate.app.state.engine
    engine.resume_antivirus_required = True
    decoder = Mock()
    assert work(s, guest=decoder)
    decoder.extract.assert_not_called()

    def infected(raw):
        raise HTTPException(422)

    assert work(
        s,
        guest=decoder,
        scanner=SimpleNamespace(scan=infected),
        now=datetime.now(UTC) + timedelta(minutes=2),
    )
    decoder.extract.assert_not_called()
    result = s.candidate.client.get(
        "/v1/candidates/me/resume-imports/" + item["import_id"], headers=s.auth
    ).json()
    assert result["status"] == "failed"


def test_worker_recovers_expired_claim_and_discards_late_completion(resumes):
    s = resumes
    item = upload(s).json()
    engine = s.candidate.app.state.engine
    with Session(engine) as session, session.begin():
        row = session.get(ResumeImport, item["import_id"])
        row.status = "processing"
        row.next_at = datetime.now(UTC) - timedelta(seconds=1)
        row.version += 1

    def old_worker(raw):
        assert not work(s)  # The live lease prevents duplicate parsing.
        assert work(s, now=datetime.now(UTC) + timedelta(minutes=3))
        return ExtractedPDF(text="Late old worker with stale text", pages=1)

    assert work(s, guest=SimpleNamespace(extract=old_worker))
    with Session(engine) as session:
        row = session.get(ResumeImport, item["import_id"])
        assert row.status == "review_ready" and "Анна" in row.extraction["text"]
        assert "Late old worker" not in row.extraction["text"]


def test_structured_sections_are_only_unconfirmed_declarations():
    from reverse_hr.domains.candidate_resume import proposed, redact

    fields = proposed(
        "Anna Engineer\nSpecialization: backend\nSkills: Python, SQL\nExperience\n"
        "Developer 2022-2026\nEducation\nUniversity\nSummary\nBuild APIs"
    )
    assert fields["experience"] == ["Developer 2022-2026"]
    assert fields["education"] == ["University"] and fields["declared_skills"] == ["python", "sql"]
    assert fields["specialization"] == "backend" and "confirmed_grade" not in fields
    hidden = redact(
        "Anna Engineer: anna [at] example [dot] com; anna at example dot com; "
        "www.example.com; +7 (999) 123-45-67",
        "Anna Engineer",
        None,
    )
    assert not any(secret in hidden for secret in ["Anna", "anna", "example", "999"])


def test_pdf_guest_compose_has_no_network_credentials_or_source_volume():
    import yaml

    data = yaml.safe_load(Path("compose.yaml").read_text())
    guest = data["services"]["resume-pdf"]
    assert guest["network_mode"] == "none" and guest["read_only"] and guest["cap_drop"] == ["ALL"]
    assert guest["volumes"] == ["pdf-socket:/run/pdf"]
    assert not guest.get("environment") and guest["pids_limit"] <= 32
    assert (
        data["services"]["candidate-consumer"]["environment"]["HR_RESUME_STORAGE_ROOT"]
        == "/var/lib/reverse-hr/resumes"
    )


def test_remove_original_is_idempotent_and_keeps_confirmed_declarations(resumes):
    s = resumes
    item, resume = confirm(s)
    path = "/v1/candidates/me/resume-imports/" + item["import_id"]
    item = s.candidate.client.get(path, headers=s.auth).json()
    auth = headers(s.auth, "remove-original", item["version"])
    assert s.candidate.client.delete(path, headers=auth).status_code == 200
    assert s.candidate.client.delete(path, headers=auth).status_code == 200
    assert s.candidate.client.get(path + "/source.pdf", headers=s.auth).status_code == 404
    assert (
        s.candidate.client.get("/v1/candidates/me/resume", headers=s.auth).json()["fields"][
            "display_name"
        ]
        == resume["fields"]["display_name"]
    )
    assert "anna@example.test" in text(download(s, "full", own=True))


def test_confirmed_resume_edit_requires_fresh_profile_version_and_republication(resumes):
    s = resumes
    row = publish(s)
    profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    assert (
        s.candidate.client.put(
            "/v1/candidates/me/resume",
            json=FIELDS | {"profile_version": profile["version"] - 1},
            headers=headers(s.auth, "stale-edit", row["version"]),
        ).status_code
        == 409
    )
    result = s.candidate.client.put(
        "/v1/candidates/me/resume",
        json=FIELDS | {"profile_version": profile["version"]},
        headers=headers(s.auth, "edit", row["version"]),
    )
    assert result.status_code == 200, result.text
    assert result.json()["published"] is False and result.json()["consent_id"] is None
    assert download(s).status_code == 409
    assert "Verified grade: middle" in text(download(s, "full", own=True))


def test_full_export_hiring_rpc_and_render_do_not_hold_candidate_fence(resumes):
    from unittest.mock import patch

    from reverse_hr.domains import candidate_resume

    s = resumes
    publish(s)
    invitation = accept(s)
    active = []
    original = candidate_resume.Session

    class TrackedSession:
        def __init__(self, *args, **kwargs):
            self.session = original(*args, **kwargs)

        def __enter__(self):
            active.append(True)
            return self.session.__enter__()

        def __exit__(self, *args):
            active.pop()
            return self.session.__exit__(*args)

    market = s.candidate.app.state.market_access
    real_require = market.require

    def require(owner, purpose, **refs):
        if owner == "hiring":
            assert not active
        return real_require(owner, purpose, **refs)

    real_render = s.guest.render

    def render(data):
        assert not active
        return real_render(data)

    with (
        patch.object(candidate_resume, "Session", TrackedSession),
        patch.object(market, "require", require),
    ):
        s.candidate.app.state.resume_guest = SimpleNamespace(render=render)
        assert download(s, "full", invitation).status_code == 200


def test_profile_changed_during_render_cannot_return_stale_pdf(resumes):
    s = resumes
    publish(s)
    original = s.guest

    def render(data):
        result = original.render(data)
        profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
        updated = s.candidate.client.put(
            "/v1/candidates/me",
            json={
                "display_name": "Changed Candidate",
                "specialization": "backend",
                "declared_grade": "lead",
            },
            headers=headers(s.auth, "during-render", profile["version"]),
        )
        assert updated.status_code == 200, updated.text
        return result

    s.candidate.app.state.resume_guest = SimpleNamespace(render=render)
    assert download(s).status_code == 409


def test_deleted_import_cannot_be_resurrected_by_upload_replay(resumes):
    s = resumes
    raw = source(s.guest)
    item = upload(s, raw, "source-to-remove").json()
    path = "/v1/candidates/me/resume-imports/" + item["import_id"]
    assert (
        s.candidate.client.delete(
            path, headers=headers(s.auth, "delete-pending", item["version"])
        ).status_code
        == 200
    )
    assert upload(s, raw, "source-to-remove").status_code == 404
    assert not work(s)
