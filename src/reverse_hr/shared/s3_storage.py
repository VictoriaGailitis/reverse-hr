"""Private versioned S3 scopes. No public URLs, ambient credentials or delete-marker ACKs."""

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from reverse_hr.shared.storage_errors import BlobUnavailable


@contextmanager
def available():
    try:
        yield
    except BlobUnavailable:
        raise
    except Exception:
        # SDK messages can contain bucket names, endpoints and request credentials.
        raise BlobUnavailable("S3 operation unavailable") from None


def client(settings):
    import boto3
    from botocore.config import Config

    with available():
        path = Path(settings.s3_credentials_file)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 4096:
                raise BlobUnavailable("Private S3 credentials required")
            credentials = json.loads(stream.read(4097))
        if set(credentials) not in (
            {"access_key_id", "secret_access_key"},
            {"access_key_id", "secret_access_key", "session_token"},
        ) or any(not isinstance(v, str) or not v for v in credentials.values()):
            raise BlobUnavailable("Invalid S3 credentials")
        endpoint = settings.s3_endpoint or None
        if endpoint:
            parsed = urlsplit(endpoint)
            if (
                (
                    parsed.scheme != "https"
                    and not (
                        settings.s3_allow_insecure_local
                        and parsed.scheme == "http"
                        and parsed.hostname in {"minio", "localhost", "127.0.0.1", "::1"}
                    )
                )
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise BlobUnavailable("Invalid S3 endpoint")
        return boto3.client(
            "s3",
            region_name=settings.s3_region,
            endpoint_url=endpoint,
            aws_access_key_id=credentials["access_key_id"],
            aws_secret_access_key=credentials["secret_access_key"],
            aws_session_token=credentials.get("session_token"),
            config=Config(
                connect_timeout=3,
                read_timeout=10,
                proxies={},
                retries={"mode": "standard", "total_max_attempts": 2},
            ),
        )


class S3Scope:
    def __init__(self, sdk, bucket, prefix, kms_key_id=""):
        if not bucket or not re.fullmatch(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*/", prefix):
            raise BlobUnavailable("Invalid S3 scope")
        self.sdk, self.bucket, self.prefix = sdk, bucket, prefix
        self.encryption = (
            {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key_id}
            if kms_key_id
            else {"ServerSideEncryption": "AES256"}
        )
        with available():
            if sdk.get_bucket_versioning(Bucket=bucket).get("Status") != "Enabled":
                raise BlobUnavailable("S3 versioning required")
            block = sdk.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
            if not all(
                block.get(k) is True
                for k in (
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                )
            ):
                raise BlobUnavailable("S3 public access must be blocked")
            value = str(uuid4()).encode()
            self.immutable(".identity", value)
            marker = self.marker = str(UUID(self.get(".identity", 36).decode("ascii")))
            endpoint = getattr(getattr(sdk, "meta", None), "endpoint_url", "")
            self.identity = str(uuid5(NAMESPACE_URL, f"{endpoint}/{bucket}/{prefix}/{marker}"))

    def verify_identity(self):
        with available():
            current = str(UUID(self.get(".identity", 36).decode("ascii")))
            if current != self.marker:
                raise BlobUnavailable("S3 storage identity changed")

    def immutable(self, key, raw):
        if hasattr(self, "marker"):
            self.verify_identity()
        with available():
            try:
                self.sdk.put_object(
                    Bucket=self.bucket,
                    Key=self.prefix + key,
                    Body=raw,
                    IfNoneMatch="*",
                    **self.encryption,
                )
            except Exception as exc:
                code = getattr(exc, "response", {}).get("Error", {}).get("Code")
                if code not in {"PreconditionFailed", "412"}:
                    raise
                # The identity is an existing store's identifier, not a replacement.
                if key != ".identity" and self.get(key, len(raw)) != raw:
                    raise BlobUnavailable("Conflicting immutable S3 object") from exc

    def get(self, key, limit):
        with available():
            response = self.sdk.get_object(Bucket=self.bucket, Key=self.prefix + key)
            body = response["Body"]
            try:
                if response["ContentLength"] > limit:
                    raise BlobUnavailable("S3 object exceeds limit")
                raw = body.read(limit + 1)
                if len(raw) != response["ContentLength"] or len(raw) > limit:
                    raise BlobUnavailable("Incomplete S3 object")
                return raw
            finally:
                body.close()

    def objects(self, relative):
        """Bounded inventory including pagination; callers validate each returned key."""
        prefix = self.prefix + relative
        with available():
            keys = []
            pages = self.sdk.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=prefix
            )
            for page in pages:
                for item in page.get("Contents", []):
                    if not item["Key"].startswith(prefix) or len(keys) >= 10000:
                        raise BlobUnavailable("Invalid or excessive S3 inventory")
                    keys.append(item["Key"][len(self.prefix) :])
            return keys

    def purge(self, relative, *, catalog_last=False):
        """Permanently delete every version and marker, abort uploads, verify empty scope.

        Writers must already be fenced by Privacy's subject lock before this call.
        Object Lock/legal hold/access-denied always prevent acknowledgement.
        """
        if not relative.endswith("/") or relative.startswith("/") or ".." in relative:
            raise BlobUnavailable("Invalid purge scope")
        prefix = self.prefix + relative
        self.verify_identity()
        with available():
            upload_count = 0
            for page in self.sdk.get_paginator("list_multipart_uploads").paginate(
                Bucket=self.bucket, Prefix=prefix
            ):
                for item in page.get("Uploads", []):
                    upload_count += 1
                    if upload_count > 10000:
                        raise BlobUnavailable("Excessive multipart inventory")
                    if not item["Key"].startswith(prefix):
                        raise BlobUnavailable("Invalid multipart scope")
                    self.sdk.abort_multipart_upload(
                        Bucket=self.bucket, Key=item["Key"], UploadId=item["UploadId"]
                    )
            versions = []
            for page in self.sdk.get_paginator("list_object_versions").paginate(
                Bucket=self.bucket, Prefix=prefix
            ):
                for item in page.get("Versions", []) + page.get("DeleteMarkers", []):
                    if not item["Key"].startswith(prefix) or len(versions) >= 10000:
                        raise BlobUnavailable("Invalid or excessive version inventory")
                    versions.append({"Key": item["Key"], "VersionId": item["VersionId"]})
            groups = [versions]
            if catalog_last:
                # Preserve subject membership until every payload version is gone.
                groups = [
                    [v for v in versions if not v["Key"].endswith("/manifest.json")],
                    [v for v in versions if v["Key"].endswith("/manifest.json")],
                ]
            for index, group in enumerate(groups):
                if catalog_last and index == 1:
                    for page in self.sdk.get_paginator("list_object_versions").paginate(
                        Bucket=self.bucket, Prefix=prefix
                    ):
                        if any(
                            not v["Key"].endswith("/manifest.json")
                            for v in page.get("Versions", []) + page.get("DeleteMarkers", [])
                        ):
                            raise BlobUnavailable("Backup payload versions remain")
                for start in range(0, len(group), 1000):
                    result = self.sdk.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": group[start : start + 1000], "Quiet": True},
                    )
                    if result.get("Errors"):
                        raise BlobUnavailable("S3 permanent deletion failed")
            for page in self.sdk.get_paginator("list_object_versions").paginate(
                Bucket=self.bucket, Prefix=prefix
            ):
                if page.get("Versions") or page.get("DeleteMarkers"):
                    raise BlobUnavailable("S3 versions remain after deletion")
            if self.objects(relative):
                raise BlobUnavailable("S3 objects remain after deletion")
            for page in self.sdk.get_paginator("list_multipart_uploads").paginate(
                Bucket=self.bucket, Prefix=prefix
            ):
                if page.get("Uploads"):
                    raise BlobUnavailable("S3 uploads remain after deletion")
            self.verify_identity()


class S3BlobStore(S3Scope):
    @staticmethod
    def key(key):
        if not isinstance(key, str) or not re.fullmatch(
            r"[a-f0-9]{32}/[a-f0-9]{32}/\d{3}-[a-f0-9]{64}", key
        ):
            raise BlobUnavailable("Invalid blob reference")
        return key

    def put(self, key, raw, digest):
        self.key(key)
        if (
            not 1 <= len(raw) <= 262144
            or hashlib.sha256(raw).hexdigest() != digest
            or key[-64:] != digest
        ):
            raise BlobUnavailable("Invalid blob integrity")
        self.immutable(key, raw)

    def read(self, key, size, digest):
        self.verify_identity()
        self.key(key)
        if not isinstance(size, int) or not 1 <= size <= 262144 or key[-64:] != digest:
            raise BlobUnavailable("Invalid blob size or digest")
        raw = self.get(key, size)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise BlobUnavailable("Invalid blob integrity")
        return raw

    def purge_subject(self, subject):
        self.purge(UUID(str(subject)).hex + "/")

    def purge_recording(self, subject, recording):
        self.purge(UUID(str(subject)).hex + "/" + UUID(str(recording)).hex + "/")
