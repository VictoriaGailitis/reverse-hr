"""S3 versions, ClamD protocol, decoder separation and backup completion fences."""

import hashlib
import io
import json
import struct
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import yaml
from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from reverse_hr.platform.settings import Settings
from reverse_hr.services.media.media_decoder import IsolatedDecoder
from reverse_hr.services.privacy.backup_archive import BackupArchive, bind, run_one
from reverse_hr.services.privacy.domain.privacy import DeletionRequest
from reverse_hr.shared.blob_storage import object_key
from reverse_hr.shared.media_antivirus import ClamdScanner
from reverse_hr.shared.s3_storage import S3BlobStore, client
from reverse_hr.shared.storage_errors import BlobUnavailable
from tests.integration.test_deletion_completion import EXTERNAL, ack, apply, prepare
from tests.integration.test_practical_environments import prepared
from tests.services.media.test_media_storage_validation import media as media_fixture
from tests.services.media.test_media_storage_validation import signatures as signatures_fixture
from tests.shared.test_access import headers

media = media_fixture
signatures = signatures_fixture


class S3:
    """Stateful versioned transport fake; pages exercise real adapter iteration."""

    def __init__(self):
        self.values = {}
        self.uploads = []
        self.blocked = set()
        self.counter = 0
        self.versioning = "Enabled"
        self.public = True
        self.requests = []

    def get_bucket_versioning(self, **kw):
        return {"Status": self.versioning}

    def get_public_access_block(self, **kw):
        return {
            "PublicAccessBlockConfiguration": dict.fromkeys(
                [
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                ],
                self.public,
            )
        }

    def put_object(self, **kw):
        self.requests.append(kw)
        key = kw["Key"]
        if kw.get("IfNoneMatch") == "*" and self.values.get(key):
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.counter += 1
        self.values.setdefault(key, []).append((str(self.counter), kw["Body"]))
        return {"VersionId": str(self.counter)}

    def get_object(self, **kw):
        raw = self.values[kw["Key"]][-1][1]
        if raw is None:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(raw), "ContentLength": len(raw)}

    def get_paginator(self, operation):
        def pages(**kw):
            prefix = kw["Prefix"]
            if operation == "list_multipart_uploads":
                items = [u for u in self.uploads if u["Key"].startswith(prefix)]
                return [{"Uploads": items}]
            if operation == "list_objects_v2":
                return [
                    {"Contents": [{"Key": k}]}
                    for k, values in self.values.items()
                    if k.startswith(prefix) and values and values[-1][1] is not None
                ]
            return [
                {"DeleteMarkers" if raw is None else "Versions": [{"Key": k, "VersionId": version}]}
                for k, values in self.values.items()
                if k.startswith(prefix)
                for version, raw in values
            ]

        return SimpleNamespace(paginate=pages)

    def delete_objects(self, **kw):
        errors = []
        for item in kw["Delete"]["Objects"]:
            if item["Key"] in self.blocked:
                errors.append({"Key": item["Key"], "Code": "AccessDenied"})
            else:
                self.values[item["Key"]] = [
                    v for v in self.values[item["Key"]] if v[0] != item["VersionId"]
                ]
        return {"Errors": errors}

    def abort_multipart_upload(self, **kw):
        self.uploads = [u for u in self.uploads if u["UploadId"] != kw["UploadId"]]


def test_s3_immutable_hash_private_versions_orphans_and_uploads():
    sdk = S3()
    store = S3BlobStore(sdk, "private-bucket", "media/")
    subject, record, other = uuid4(), uuid4(), uuid4()
    raw = b"owned payload"
    digest = hashlib.sha256(raw).hexdigest()
    key = object_key(subject, record, 0, digest)
    foreign = object_key(other, record, 0, digest)
    store.put(key, raw, digest)
    store.put(key, raw, digest)
    store.put(foreign, raw, digest)
    assert store.read(key, len(raw), digest) == raw
    assert all(
        r["IfNoneMatch"] == "*" and r["ServerSideEncryption"] == "AES256" for r in sdk.requests
    )
    assert S3BlobStore(sdk, "private-bucket", "media/").identity == store.identity
    sdk.put_object(Key="media/" + key, Body=b"corrupt")
    with pytest.raises(BlobUnavailable):
        store.read(key, len(raw), digest)
    sdk.put_object(Key="media/" + subject.hex + "/orphan", Body=b"uncommitted")
    sdk.put_object(Key="media/" + key, Body=None)  # Delete marker hides prior versions.
    sdk.uploads.append({"Key": "media/" + subject.hex + "/pending", "UploadId": "unfinished"})
    store.purge_subject(subject)
    store.purge_subject(subject)
    assert not sdk.uploads
    assert not any(v for k, v in sdk.values.items() if k.startswith("media/" + subject.hex + "/"))
    assert store.read(foreign, len(raw), digest) == raw


@pytest.mark.parametrize(
    "public,versioning", [(False, "Enabled"), (True, "Suspended"), (True, None)]
)
def test_s3_requires_private_versioned_bucket(public, versioning):
    sdk = S3()
    sdk.public, sdk.versioning = public, versioning
    with pytest.raises(BlobUnavailable):
        S3BlobStore(sdk, "bucket", "media/")


def test_s3_lock_failure_and_prefix_escape_fail_closed():
    sdk = S3()
    store = S3BlobStore(sdk, "bucket", "media/")
    subject = uuid4()
    key = object_key(subject, uuid4(), 0, hashlib.sha256(b"x").hexdigest())
    store.put(key, b"x", key[-64:])
    sdk.blocked.add("media/" + key)
    with pytest.raises(BlobUnavailable):
        store.purge_subject(subject)
    with pytest.raises(BlobUnavailable):
        store.put("../escape", b"x", key[-64:])
    assert sdk.values["media/" + key]


def test_s3_client_requires_private_explicit_credentials_and_https(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"access_key_id": "test", "secret_access_key": "test-secret"}))
    path.chmod(0o600)
    settings = Settings(s3_credentials_file=str(path), s3_endpoint="https://storage.example")
    sdk = client(settings)
    assert sdk.meta.endpoint_url == "https://storage.example"
    assert sdk.meta.config.proxies == {}
    with pytest.raises(BlobUnavailable):
        client(settings.model_copy(update={"s3_endpoint": "http://storage.example"}))
    path.chmod(0o644)
    with pytest.raises(BlobUnavailable):
        client(settings)


def test_backup_purge_shared_snapshot_all_versions_and_other_subject_preserved():
    sdk = S3()
    archive = BackupArchive(sdk, "backups", "archive/")
    subject, coowner, other = uuid4(), uuid4(), uuid4()
    shared = archive.publish(b"database snapshot with two subjects", [subject, coowner])
    retained = archive.publish(b"other snapshot", [other])
    sdk.put_object(Key=f"archive/snapshots/{shared}/payload", Body=b"historical copy")
    archive.purge_subject(subject)
    assert set(archive.catalog()) == {retained}
    assert not any(v for k, v in sdk.values.items() if shared in k)


def test_backup_payload_lock_retains_catalog_for_retry():
    sdk = S3()
    archive = BackupArchive(sdk, "backups", "archive/")
    subject = uuid4()
    snapshot = archive.publish(b"snapshot", [subject])
    sdk.blocked.add(f"archive/snapshots/{snapshot}/payload")
    with pytest.raises(BlobUnavailable):
        archive.purge_subject(subject)
    assert snapshot in archive.catalog()
    sdk.blocked.clear()
    archive.purge_subject(subject)
    assert not archive.catalog()


@pytest.mark.parametrize("hidden", [False, True])
def test_unknown_or_hidden_backup_without_catalog_never_acknowledged(hidden):
    sdk = S3()
    archive = BackupArchive(sdk, "backups", "archive/")
    key = f"archive/snapshots/{uuid4().hex}/payload"
    sdk.put_object(Key=key, Body=b"uncatalogued")
    if hidden:
        sdk.put_object(Key=key, Body=None)
    with pytest.raises(BlobUnavailable):
        archive.purge_subject(uuid4())


def test_backup_outage_blocks_privacy_completion_and_same_ack_retries(service, token):
    privacy = service("privacy")
    engine = privacy.app.state.engine
    sdk = S3()
    archive = BackupArchive(sdk, "backups", "archive/")
    engine.backup_archive, engine.backup_purge_required = archive, True
    subject = uuid4()
    snapshot = archive.publish(b"all-service database backup", [subject])
    result, _ = prepare(privacy, subject, token)
    for name in EXTERNAL[:-1]:
        apply(privacy, ack(result, name))
    final = ack(result, EXTERNAL[-1])
    sdk.blocked.add(f"archive/snapshots/{snapshot}/payload")
    assert apply(privacy, final)
    assert not apply(privacy, final)
    assert run_one(engine)
    assert not run_one(engine)
    with Session(engine) as session:
        row = session.get(DeletionRequest, result["request_id"])
        assert row.completed_at is None and row.backup_error == "archive_unavailable"
        assert row.backup_attempts == 1
    with Session(engine) as session, session.begin():
        session.get(DeletionRequest, result["request_id"]).backup_retry_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    sdk.blocked.clear()
    assert run_one(engine)
    assert not run_one(engine)
    assert not archive.catalog()
    with Session(engine) as session:
        assert session.get(DeletionRequest, result["request_id"]).completed_at is not None
        engine.backup_archive = None
        with pytest.raises(BlobUnavailable):
            bind(session)


class Socket:
    def __init__(self, response):
        self.response = bytearray(response)
        self.sent = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def settimeout(self, value):
        assert 0 < value <= 15

    def sendall(self, raw):
        self.sent.extend(raw)

    def recv(self, size):
        raw = bytes(self.response[: min(7, size)])
        del self.response[: len(raw)]
        return raw


def scanner(monkeypatch, verdict=b"stream: OK\0", age=timedelta()):
    now = datetime.now(UTC) - age
    version = f"ClamAV 1.4.3/27700/{now.strftime('%a %b %d %H:%M:%S %Y')}\0".encode()
    sockets = [Socket(version), Socket(verdict)]
    pending = iter(sockets)
    monkeypatch.setattr(
        "reverse_hr.shared.media_antivirus.socket.create_connection", lambda *a, **k: next(pending)
    )
    return ClamdScanner(Settings()), sockets


def test_clamd_stream_framing_and_digest_bound_clean_verdict(monkeypatch):
    scan, sockets = scanner(monkeypatch)
    raw = b"x" * 70000
    report = scan.scan(raw)
    assert report.digest == hashlib.sha256(raw).hexdigest()
    expected = (
        b"zINSTREAM\0"
        + struct.pack("!I", 65536)
        + raw[:65536]
        + struct.pack("!I", 4464)
        + raw[65536:]
        + b"\0" * 4
    )
    assert sockets[1].sent == expected
    assert report.verdict == "clean" and report.signature_version == 27700


@pytest.mark.parametrize(
    "verdict,status",
    [
        (b"stream: Eicar-Test-Signature FOUND\0", 422),
        (b"INSTREAM size limit exceeded. ERROR\0", 503),
        (b"stream: OK", 503),
        (b"x" * 1025, 503),
    ],
)
def test_antivirus_rejects_malware_unknown_truncated_or_excessive_verdict(
    monkeypatch, verdict, status
):
    scan, _ = scanner(monkeypatch, verdict)
    with pytest.raises(HTTPException) as exc:
        scan.scan(b"payload")
    assert exc.value.status_code == status


def test_stale_signatures_prevent_sending_source(monkeypatch):
    scan, sockets = scanner(monkeypatch, age=timedelta(days=3))
    with pytest.raises(HTTPException) as exc:
        scan.scan(b"private source")
    assert exc.value.status_code == 503
    assert sockets[1].sent == b""


def test_scanner_is_before_decoder_and_failed_scan_has_no_snapshot(media):
    s = media
    s.raw = s.raw[:100]
    calls = []

    def reject(raw):
        calls.append("scan")
        raise HTTPException(422)

    s.env.app.state.media_scanner = SimpleNamespace(scan=reject)
    original = s.env.app.state.media_validator
    s.env.app.state.media_validator = SimpleNamespace(validate=lambda *a: calls.append("decode"))
    # prepared's finalize expects success, so build/upload explicitly.
    import base64

    from tests.integration.test_practical_environments import create

    row = create(s).json()
    path = f"/v1/recordings/{row['recording_id']}"
    assert (
        s.env.client.put(
            path + "/chunks/0",
            headers=headers(s.auth, "upload", 1),
            json={
                "data_base64": base64.b64encode(s.raw).decode(),
                "digest": hashlib.sha256(s.raw).hexdigest(),
            },
        ).status_code
        == 200
    )
    assert (
        s.env.client.post(path + "/finalize", headers=headers(s.auth, "finalize", 2)).status_code
        == 422
    )
    assert calls == ["scan"]
    assert s.env.client.get(path, headers=s.auth).json()["snapshot_id"] is None
    s.env.app.state.media_validator = original


def test_clean_scan_receipt_is_persisted_and_legacy_read_fenced(media, monkeypatch):
    s = media
    scan, _ = scanner(monkeypatch)
    s.env.app.state.media_scanner = scan
    s.env.app.state.engine.media_antivirus_required = True
    _, row = prepared(s)
    assert row["validation"]["antivirus"]["digest"] == hashlib.sha256(s.raw).hexdigest()
    assert s.env.client.get(s.env_path + "/content", headers=s.auth).status_code == 200
    from reverse_hr.services.media.domain.media import Recording

    with Session(s.env.app.state.engine) as session, session.begin():
        record = session.query(Recording).one()
        record.validation = None
    assert s.env.client.get(s.env_path + "/content", headers=s.auth).status_code == 503


def test_isolated_decoder_required_has_no_host_fallback(tmp_path):
    settings = Settings(
        media_decoder_required=True, media_decoder_socket=str(tmp_path / "missing.sock")
    )
    with pytest.raises(HTTPException) as exc:
        IsolatedDecoder(settings).validate(b"recording", "audio/webm", "voice")
    assert exc.value.status_code == 503


def test_decoder_service_rejects_unknown_mime_and_oversized_stream(monkeypatch):
    from reverse_hr.services.media.media_decoder import create_app

    monkeypatch.setattr("reverse_hr.services.media.media_decoder._LIMIT", 8)
    app = TestClient(create_app(Settings(decoder_container_required=False)))
    assert (
        app.post(
            "/validate",
            content=b"x",
            headers={"Content-Type": "text/plain", "X-Recording-Format": "voice"},
        ).status_code
        == 422
    )
    assert (
        app.post(
            "/validate",
            content=b"x" * 9,
            headers={"Content-Type": "audio/webm", "X-Recording-Format": "voice"},
        ).status_code
        == 413
    )


def test_compose_decoder_has_no_network_credentials_or_media_volume():
    from pathlib import Path

    data = yaml.safe_load(Path("compose.yaml").read_text())
    decoder = data["services"]["media-decoder"]
    assert decoder["network_mode"] == "none" and decoder["cap_drop"] == ["ALL"]
    assert decoder["read_only"] is True and decoder["pids_limit"] <= 32
    assert decoder["volumes"] == ["decoder-socket:/run/decoder"]
    assert set(decoder["environment"]) == {"HR_MEDIA_VALIDATION_TIMEOUT_SECONDS"}
    assert data["services"]["clamav"]["networks"] == ["antivirus"]
    assert data["networks"]["antivirus"]["internal"] is True
    assert data["services"]["media"]["environment"]["HR_MEDIA_ANTIVIRUS_REQUIRED"] == "true"


def test_decoder_real_local_socket_transport_and_full_decode(tmp_path):
    """Real UDS + FFmpeg, with host isolation explicitly disabled for this transport test."""
    import shutil
    import socket
    import subprocess
    import tempfile
    import threading
    import time

    import uvicorn

    from reverse_hr.services.media.media_decoder import create_app

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg unavailable")
    source = tmp_path / "source.webm"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.1",
            "-c:a",
            "libopus",
            str(source),
        ],
        check=True,
    )
    socket_directory = tempfile.TemporaryDirectory(prefix="hr-uds-", dir="/tmp")
    path = socket_directory.name + "/decoder.sock"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.bind(socket_directory.name + "/probe.sock")
    except PermissionError:
        socket_directory.cleanup()
        pytest.skip("Host sandbox forbids binding Unix sockets")
    app = create_app(Settings(decoder_container_required=False))
    server = uvicorn.Server(uvicorn.Config(app, uds=path, log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        decoder = IsolatedDecoder(Settings(media_decoder_socket=path))
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        decoder.ready()
        report = decoder.validate(source.read_bytes(), "audio/webm", "voice")
        assert report.validator == "ffmpeg-isolated-container-v1"
        assert 90 <= report.duration_ms <= 150 and report.audio_codec == "opus"
        with pytest.raises(HTTPException) as exc:
            decoder.validate(b"forged container", "audio/webm", "voice")
        assert exc.value.status_code == 422
    finally:
        server.should_exit = True
        thread.join(5)
        assert not thread.is_alive()
        socket_directory.cleanup()


def test_decoder_refuses_host_execution_by_default():
    from reverse_hr.services.media.media_decoder import create_app

    client = TestClient(create_app())
    assert client.get("/ready").status_code == 503
    assert (
        client.post(
            "/validate",
            content=b"upload",
            headers={"Content-Type": "audio/webm", "X-Recording-Format": "voice"},
        ).status_code
        == 503
    )


@pytest.mark.parametrize(
    "failure",
    ["valid", "network", "capabilities", "writable", "memory", "cpu", "pids", "secret", "seccomp"],
)
def test_decoder_runtime_attestation_rejects_weakened_isolation(monkeypatch, failure):
    import os
    from pathlib import Path

    from reverse_hr.shared.decoder_isolation import require_isolation

    monkeypatch.setattr("reverse_hr.shared.decoder_guest.abi", lambda: 3)
    monkeypatch.setattr("reverse_hr.shared.decoder_isolation.sys.platform", "linux")
    monkeypatch.setattr("reverse_hr.shared.decoder_isolation.os.getuid", lambda: 10001)
    monkeypatch.setattr(
        "reverse_hr.shared.decoder_isolation.os.statvfs",
        lambda *a: SimpleNamespace(f_flag=0 if failure == "writable" else os.ST_RDONLY),
    )
    monkeypatch.setattr(
        "reverse_hr.shared.decoder_isolation.os.environ",
        {"HR_DATABASE_URL": "secret"} if failure == "secret" else {},
    )
    files = {
        "/proc/self/status": (
            "CapEff:\t00000000\nCapPrm:\t00000000\nCapBnd:\t00000000\nNoNewPrivs:\t1\nSeccomp:\t2"
        ),
        "/proc/net/dev": "lo: data",
        "/proc/net/route": "Iface Destination Gateway Flags",
        "/proc/net/ipv6_route": "",
        "/proc/net/if_inet6": "",
        "/sys/fs/cgroup/pids.max": "32",
        "/sys/fs/cgroup/memory.max": "536870912",
        "/sys/fs/cgroup/cpu.max": "100000 100000",
    }
    if failure == "network":
        files["/proc/net/dev"] += "\neth0: data"
    if failure == "capabilities":
        files["/proc/self/status"] = files["/proc/self/status"].replace(
            "CapEff:\t00000000", "CapEff:\t00000001"
        )
    if failure == "seccomp":
        files["/proc/self/status"] = files["/proc/self/status"].replace(
            "Seccomp:\t2", "Seccomp:\t0"
        )
    if failure == "memory":
        files["/sys/fs/cgroup/memory.max"] = "max"
    if failure == "cpu":
        files["/sys/fs/cgroup/cpu.max"] = "200000 100000"
    if failure == "pids":
        files["/sys/fs/cgroup/pids.max"] = "max"
    monkeypatch.setattr(Path, "read_text", lambda self: files[str(self)])
    if failure == "valid":
        require_isolation()
    else:
        with pytest.raises(HTTPException) as exc:
            require_isolation()
        assert exc.value.status_code == 503


def test_s3_sdk_parameters_use_conditional_write_and_explicit_version_deletion():
    import boto3
    from botocore.stub import Stubber

    sdk = boto3.client(
        "s3", aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1"
    )
    with Stubber(sdk) as stub:
        stub.add_response(
            "get_bucket_versioning", {"Status": "Enabled"}, {"Bucket": "private-bucket"}
        )
        block = dict.fromkeys(
            ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"],
            True,
        )
        stub.add_response(
            "get_public_access_block",
            {"PublicAccessBlockConfiguration": block},
            {"Bucket": "private-bucket"},
        )
        from botocore.stub import ANY

        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "private-bucket",
                "Key": "media/.identity",
                "Body": ANY,
                "IfNoneMatch": "*",
                "ServerSideEncryption": "AES256",
            },
        )
        identity = str(uuid4()).encode()
        stub.add_response(
            "get_object",
            {"Body": io.BytesIO(identity), "ContentLength": 36},
            {"Bucket": "private-bucket", "Key": "media/.identity"},
        )
        store = S3BlobStore(sdk, "private-bucket", "media/")
        subject = uuid4()
        prefix = "media/" + subject.hex + "/"
        key = prefix + "orphan"
        stub.add_response(
            "get_object",
            {"Body": io.BytesIO(identity), "ContentLength": 36},
            {"Bucket": "private-bucket", "Key": "media/.identity"},
        )
        stub.add_response(
            "list_multipart_uploads", {}, {"Bucket": "private-bucket", "Prefix": prefix}
        )
        stub.add_response(
            "list_object_versions",
            {
                "Versions": [{"Key": key, "VersionId": "historical"}],
                "DeleteMarkers": [{"Key": key, "VersionId": "marker"}],
            },
            {"Bucket": "private-bucket", "Prefix": prefix},
        )
        stub.add_response(
            "delete_objects",
            {},
            {
                "Bucket": "private-bucket",
                "Delete": {
                    "Objects": [
                        {"Key": key, "VersionId": "historical"},
                        {"Key": key, "VersionId": "marker"},
                    ],
                    "Quiet": True,
                },
            },
        )
        stub.add_response(
            "list_object_versions", {}, {"Bucket": "private-bucket", "Prefix": prefix}
        )
        stub.add_response("list_objects_v2", {}, {"Bucket": "private-bucket", "Prefix": prefix})
        stub.add_response(
            "list_multipart_uploads", {}, {"Bucket": "private-bucket", "Prefix": prefix}
        )
        # Identity must be checked before and after permanent deletion.
        stub.add_response(
            "get_object",
            {"Body": io.BytesIO(identity), "ContentLength": 36},
            {"Bucket": "private-bucket", "Key": "media/.identity"},
        )
        store.purge_subject(subject)
        stub.assert_no_pending_responses()


def test_s3_is_wired_into_upload_playback_and_privacy_erasure(media):
    from reverse_hr.services.media.domain.media import process_deletion_request
    from tests.services.media.test_media_storage_validation import deletion

    s = media
    sdk = S3()
    storage = S3BlobStore(sdk, "media", "objects/")
    s.env.app.state.engine.media_store = storage
    # Fixture initially configures an empty file store; replace its technical binding
    # before any recording exists to exercise a fresh S3 deployment.
    from reverse_hr.services.media.domain.media import MediaStorageIdentity

    with Session(s.env.app.state.engine) as session, session.begin():
        session.get(MediaStorageIdentity, "primary").identity = storage.identity
    prepared(s)
    assert s.env.client.get(s.env_path + "/content", headers=s.auth).content == s.raw
    assert storage.objects(s.subject.hex + "/")
    with Session(s.env.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, deletion(s.subject))
    assert not storage.objects(s.subject.hex + "/")
    assert s.env.client.get(s.env_path + "/content", headers=s.auth).status_code == 409


def test_backup_failure_does_not_starve_another_ready_subject(service, token):
    privacy = service("privacy")
    engine = privacy.app.state.engine
    sdk = S3()
    archive = BackupArchive(sdk, "backups", "archive/")
    engine.backup_archive, engine.backup_purge_required = archive, True
    first, second = uuid4(), uuid4()
    blocked = archive.publish(b"protected", [first])
    archive.publish(b"deletable", [second])
    requests = [prepare(privacy, subject, token)[0] for subject in [first, second]]
    for request in requests:
        for name in EXTERNAL:
            apply(privacy, ack(request, name))
    sdk.blocked.add(f"archive/snapshots/{blocked}/payload")
    assert run_one(engine)
    assert run_one(engine)
    with Session(engine) as session:
        assert session.get(DeletionRequest, requests[0]["request_id"]).completed_at is None
        assert session.get(DeletionRequest, requests[1]["request_id"]).completed_at is not None


def test_s3_identity_replacement_prevents_erasure_ack():
    sdk = S3()
    storage = S3BlobStore(sdk, "media", "objects/")
    subject = uuid4()
    raw = b"owned"
    digest = hashlib.sha256(raw).hexdigest()
    key = object_key(subject, uuid4(), 0, digest)
    storage.put(key, raw, digest)
    sdk.put_object(Key="objects/.identity", Body=str(uuid4()).encode())
    with pytest.raises(BlobUnavailable):
        storage.purge_subject(subject)
    assert sdk.values["objects/" + key]


def test_revocation_during_storage_read_prevents_content_response(media, monkeypatch):
    s = media
    prepared(s)
    storage = s.env.app.state.engine.media_store
    original = storage.read
    revoked = []

    def read(*args):
        result = original(*args)
        revoked.append(True)
        return result

    def check(*args):
        if revoked:
            raise HTTPException(409)

    monkeypatch.setattr(storage, "read", read)
    monkeypatch.setattr(s.env.app.state.recording_access, "check_recording", check)
    result = s.env.client.get(s.env_path + "/content", headers=s.auth)
    assert result.status_code == 409 and s.raw not in result.content


@pytest.mark.parametrize("version", [-1, 1, 2])
def test_decoder_landlock_rejects_missing_or_old_abi(monkeypatch, version):
    from reverse_hr.shared import decoder_guest

    monkeypatch.setattr(decoder_guest, "libc", lambda: SimpleNamespace(syscall=lambda *a: version))
    with pytest.raises(OSError):
        decoder_guest.abi()


def test_decoder_landlock_rules_exclude_socket_directory_and_all_writes(monkeypatch):
    import os
    from pathlib import Path

    from reverse_hr.shared import decoder_guest

    rules, opened, operations = [], {}, []

    def syscall(number, *args):
        operations.append(number)
        if number == 444:
            if getattr(args[0], "value", "not-null") is None:
                return 3
            assert args[0]._obj.handled_access_fs == (1 << 15) - 1
            return 77
        if number == 445:
            rule = args[2]._obj
            rules.append((opened[rule.parent_fd], rule.allowed_access))
        return 0

    def open_file(path, flags):
        fd = 100 + len(opened)
        opened[fd] = str(path)
        return fd

    library = SimpleNamespace(syscall=syscall, prctl=lambda *a: 0)
    monkeypatch.setattr(decoder_guest, "libc", lambda: library)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(os, "O_PATH", 0x200000, raising=False)
    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(os, "close", lambda *a: None)
    decoder_guest.restrict("/tmp/recording")
    assert rules == [(p, 13) for p in ["/usr", "/lib", "/lib64", "/etc"]] + [("/tmp/recording", 4)]
    assert operations[-1] == 446
    assert all(not mask & (1 << 1 | 1 << 14 | 1 << 8 | 1 << 9) for _, mask in rules)
    assert not any(path.startswith("/run/") for path, _ in rules)


def test_decoder_landlock_actual_kernel_restricts_read_write_and_truncate(tmp_path):
    import subprocess
    import sys

    from reverse_hr.shared.decoder_guest import abi

    try:
        abi()
    except OSError:
        pytest.skip("Linux Landlock ABI 3 unavailable on this host")
    source, forbidden = tmp_path / "source", tmp_path / "forbidden"
    source.write_bytes(b"readable")
    forbidden.write_bytes(b"secret")
    # Restrict a fresh interpreter; the test process itself stays outside the sandbox.
    script = """import sys
from pathlib import Path
from reverse_hr.shared.decoder_guest import restrict
source, forbidden, output = map(Path, sys.argv[1:])
restrict(source)
assert source.read_bytes() == b"readable"
actions = [lambda: forbidden.read_bytes(), lambda: output.write_bytes(b"persist"),
           lambda: source.write_bytes(b"truncate")]
for action in actions:
    try:
        action()
    except PermissionError:
        pass
    else:
        raise AssertionError("Landlock restriction bypassed")
"""
    subprocess.run(
        [sys.executable, "-c", script, str(source), str(forbidden), str(tmp_path / "output")],
        check=True,
    )
    assert source.read_bytes() == b"readable" and not (tmp_path / "output").exists()


def test_decoder_cleanup_kills_group_even_after_leader_exits(monkeypatch):
    import os
    import signal

    from reverse_hr.services.media.media_validation import command

    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"output")
    os.close(write_fd)
    stream = os.fdopen(read_fd, "rb")
    process = SimpleNamespace(stdout=stream, pid=12345, poll=lambda: 0, wait=lambda **kw: 0)
    killed = []
    monkeypatch.setattr(
        "reverse_hr.services.media.media_validation.subprocess.Popen", lambda *a, **kw: process
    )
    monkeypatch.setattr(
        "reverse_hr.services.media.media_validation.os.killpg", lambda *a: killed.append(a)
    )
    assert command(["decoder"], 1) == b"output"
    assert killed == [(12345, signal.SIGKILL)] and stream.closed


def test_storage_binding_survives_orphaned_first_write_without_any_chunk_row(media):
    from reverse_hr.services.media.domain.media import (
        MediaStorageIdentity,
        process_deletion_request,
    )
    from tests.services.media.test_media_storage_validation import deletion

    s = media
    storage = s.env.app.state.engine.media_store
    with Session(s.env.app.state.engine) as session:
        assert session.get(MediaStorageIdentity, "primary").identity == storage.identity
    raw = b"orphan from rolled-back upload"
    key = object_key(s.subject, uuid4(), 0, hashlib.sha256(raw).hexdigest())
    storage.put(key, raw, key[-64:])
    event = deletion(s.subject)
    s.env.app.state.engine.media_store = None
    with (
        pytest.raises(HTTPException) as exc,
        Session(s.env.app.state.engine) as session,
        session.begin(),
    ):
        process_deletion_request(session, event)
    assert exc.value.status_code == 503
    assert storage.read(key, len(raw), key[-64:]) == raw
    s.env.app.state.engine.media_store = storage
    with Session(s.env.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, event)
    with pytest.raises(BlobUnavailable):
        storage.read(key, len(raw), key[-64:])
