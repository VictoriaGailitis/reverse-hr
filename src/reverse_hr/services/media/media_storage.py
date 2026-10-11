"""Private immutable filesystem blobs; keys are generated solely from owned metadata."""

from fastapi import HTTPException

from reverse_hr.shared.blob_storage import FileBlobStore as FileBlobStore
from reverse_hr.shared.blob_storage import object_key as object_key
from reverse_hr.shared.storage_errors import BlobUnavailable as BlobUnavailable


def configure(engine, settings):
    # String form remains useful for standalone filesystem maintenance.
    if isinstance(settings, str):
        engine.media_store = FileBlobStore(settings) if settings else None
        return
    engine.media_antivirus_required = settings.media_antivirus_required
    if settings.media_storage_backend == "s3":
        from reverse_hr.shared.s3_storage import S3BlobStore, client

        engine.media_store = S3BlobStore(
            client(settings),
            settings.media_s3_bucket,
            settings.media_s3_prefix,
            settings.s3_kms_key_id,
        )
    else:
        engine.media_store = (
            FileBlobStore(settings.media_storage_root) if settings.media_storage_root else None
        )
    if engine.media_store is not None:
        # Bind in a separate startup transaction before any upload can leave an orphan.
        # A rolled-back chunk transaction must not erase the only storage identity.
        from sqlalchemy.orm import Session

        with Session(engine) as session, session.begin():
            store(session, bind=True)


def store(session, *, bind=False):
    from reverse_hr.services.media.domain.media import MediaStorageIdentity

    storage = getattr(session.get_bind(), "media_store", None)
    identity = session.get(MediaStorageIdentity, "primary")
    if identity and (storage is None or storage.identity != identity.identity):
        raise HTTPException(503, "Private media storage identity does not match")
    if bind and storage and identity is None:
        session.add(MediaStorageIdentity(name="primary", identity=storage.identity))
        session.flush()
    return storage
