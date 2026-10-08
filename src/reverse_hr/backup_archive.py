"""Catalogued S3 backups: purge whole shared snapshots before Privacy completion.

An operator supplies the complete subject inventory when creating an archive.
Uploads and restore admission serialize against Privacy tombstones. Unknown objects,
missing catalogs, unavailable archives and protected versions fail closed.
"""

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from reverse_hr.media_storage import BlobUnavailable
from reverse_hr.s3_storage import S3Scope, client


class BackupArchive(S3Scope):
    def publish(self, raw, subjects):
        subjects = sorted({str(UUID(str(s))) for s in subjects})
        if not subjects or len(subjects) > 10000 or not 1 <= len(raw) <= 256 * 1024 * 1024:
            raise BlobUnavailable("Invalid backup inventory or size")
        snapshot = uuid4().hex
        manifest = json.dumps(
            {
                "snapshot": snapshot,
                "subjects": subjects,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            },
            sort_keys=True,
        ).encode()
        # Catalog first: an interrupted payload upload is still discoverable for erasure.
        self.immutable(f"snapshots/{snapshot}/manifest.json", manifest)
        self.immutable(f"snapshots/{snapshot}/payload", raw)
        return snapshot

    def catalog(self):
        self.verify_identity()
        keys = set(self.objects("snapshots/"))
        from reverse_hr.s3_storage import available

        with available():
            version_count = 0
            for page in self.sdk.get_paginator("list_object_versions").paginate(
                Bucket=self.bucket, Prefix=self.prefix + "snapshots/"
            ):
                for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
                    version_count += 1
                    if version_count > 10000:
                        raise BlobUnavailable("Excessive backup version inventory")
                    if not item["Key"].startswith(self.prefix + "snapshots/") or len(keys) >= 10000:
                        raise BlobUnavailable("Invalid backup version inventory")
                    keys.add(item["Key"][len(self.prefix) :])
        groups = {}
        for key in keys:
            parts = key.split("/")
            if len(parts) != 3 or parts[0] != "snapshots" or len(parts[1]) != 32:
                raise BlobUnavailable("Unknown backup object")
            try:
                if UUID(hex=parts[1]).hex != parts[1] or parts[2] not in {
                    "manifest.json",
                    "payload",
                }:
                    raise ValueError
            except ValueError as exc:
                raise BlobUnavailable("Invalid backup scope") from exc
            groups.setdefault(parts[1], set()).add(parts[2])
        manifests = {}
        for snapshot, files in groups.items():
            if "manifest.json" not in files:
                raise BlobUnavailable("Uncatalogued backup")
            try:
                manifest = json.loads(self.get(f"snapshots/{snapshot}/manifest.json", 1024 * 1024))
                if (
                    set(manifest) != {"snapshot", "subjects", "sha256", "size"}
                    or manifest["snapshot"] != snapshot
                    or not isinstance(manifest["subjects"], list)
                    or not 1 <= len(manifest["subjects"]) <= 10000
                ):
                    raise ValueError
                if any(not isinstance(s, str) for s in manifest["subjects"]):
                    raise ValueError
                subjects = {str(UUID(s)) for s in manifest["subjects"]}
                if (
                    len(subjects) != len(manifest["subjects"])
                    or not isinstance(manifest["sha256"], str)
                    or re.fullmatch(r"[a-f0-9]{64}", manifest["sha256"]) is None
                    or type(manifest["size"]) is not int
                    or not 1 <= manifest["size"] <= 256 * 1024 * 1024
                ):
                    raise ValueError
                manifests[snapshot] = manifest
            except (ValueError, TypeError, KeyError) as exc:
                raise BlobUnavailable("Invalid backup catalog") from exc
        return manifests

    def purge_subject(self, subject):
        subject = str(UUID(str(subject)))
        for snapshot, manifest in self.catalog().items():
            if subject in manifest["subjects"]:
                self.purge(f"snapshots/{snapshot}/", catalog_last=True)
        if any(subject in m["subjects"] for m in self.catalog().values()):
            raise BlobUnavailable("Subject remains in backups")


def configure(engine, settings):
    engine.backup_purge_required = settings.backup_purge_required
    engine.backup_archive = (
        BackupArchive(
            client(settings),
            settings.backup_s3_bucket,
            settings.backup_s3_prefix,
            settings.s3_kms_key_id,
        )
        if settings.backup_s3_bucket
        else None
    )


def bind(session):
    from reverse_hr.domains.privacy import BackupStoreIdentity

    engine = session.get_bind()
    archive = getattr(engine, "backup_archive", None)
    row = session.get(BackupStoreIdentity, "primary")
    if archive is None:
        if row is not None or getattr(engine, "backup_purge_required", False):
            raise BlobUnavailable("Configured backup archive required for deletion")
        return None
    fingerprint = hashlib.sha256(
        f"{archive.bucket}/{archive.prefix}/{archive.identity}".encode()
    ).hexdigest()
    if row is not None and row.fingerprint != fingerprint:
        raise BlobUnavailable("Backup archive identity changed")
    if row is None:
        session.add(BackupStoreIdentity(name="primary", fingerprint=fingerprint))
        session.flush()
    return archive


def run_one(engine):
    from reverse_hr.domains.privacy import (
        DeletionRequest,
        DeletionTarget,
        finalize_deletion,
        subject_lock,
    )

    with Session(engine) as session, session.begin():
        pending = exists(
            select(DeletionTarget.request_id).where(
                DeletionTarget.request_id == DeletionRequest.request_id,
                DeletionTarget.service != "privacy",
                DeletionTarget.status != "deleted",
            )
        )
        row = session.scalar(
            select(DeletionRequest)
            .where(
                DeletionRequest.completed_at.is_(None),
                ~pending,
                or_(
                    DeletionRequest.backup_retry_at.is_(None),
                    DeletionRequest.backup_retry_at <= datetime.now(UTC),
                ),
            )
            .order_by(DeletionRequest.requested_at)
            .limit(1)
        )
        if row is None:
            return False
        subject_lock(session, row.candidate_id, allow_blocked=True)
        session.refresh(row)
        if row.completed_at is not None or (
            row.backup_retry_at is not None
            and row.backup_retry_at.replace(tzinfo=UTC) > datetime.now(UTC)
        ):
            return False
        row.backup_attempts += 1
        try:
            changed = finalize_deletion(session, row, UUID(row.request_id), purge_backups=True)
        except BlobUnavailable:
            row.backup_error = "archive_unavailable"
            row.backup_retry_at = datetime.now(UTC) + timedelta(seconds=30)
            return True
        row.backup_error = None
        row.backup_retry_at = None
        return changed


def main():
    from reverse_hr.db import make_engine
    from reverse_hr.domains.privacy import subject_lock
    from reverse_hr.settings import Settings

    parser = argparse.ArgumentParser(
        description="Publish/admit restore of catalogued private backups"
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    upload = sub.add_parser("publish")
    upload.add_argument("--file", required=True)
    upload.add_argument(
        "--subjects-file", required=True, help="JSON array of every subject in the backup"
    )
    restore = sub.add_parser("restore-check")
    restore.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    settings = Settings(service_name="privacy")
    engine = make_engine(settings.database_url.get_secret_value())
    configure(engine, settings)
    try:
        with Session(engine) as session, session.begin():
            archive = bind(session)
            if archive is None:
                raise BlobUnavailable("Backup archive not configured")
            if args.mode == "publish":
                subjects = json.loads(Path(args.subjects_file).read_text())
                if not isinstance(subjects, list) or not subjects:
                    raise BlobUnavailable("Complete subject inventory required")
            else:
                manifest = archive.catalog().get(UUID(args.snapshot).hex)
                if manifest is None:
                    raise BlobUnavailable("Backup not found")
                subjects = manifest["subjects"]
                raw = archive.get(f"snapshots/{manifest['snapshot']}/payload", manifest["size"])
                if (
                    len(raw) != manifest["size"]
                    or hashlib.sha256(raw).hexdigest() != manifest["sha256"]
                ):
                    raise BlobUnavailable("Invalid backup integrity")
            # Use the live independently retained Privacy ledger, never a restored copy.
            for subject in sorted({str(UUID(s)) for s in subjects}):
                subject_lock(session, subject)
            if args.mode == "publish":
                path = Path(args.file)
                if path.stat().st_size > 256 * 1024 * 1024:
                    raise BlobUnavailable("Backup exceeds size limit")
                result = archive.publish(path.read_bytes(), subjects)
            else:
                result = "admitted; recheck under the live Privacy fence during actual restore"
        print(result)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
