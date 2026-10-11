import hashlib
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from reverse_hr.shared.storage_errors import BlobUnavailable as BlobUnavailable


def object_key(subject, recording, number, digest):
    if not 0 <= number < 128 or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise BlobUnavailable("Invalid blob reference")
    return f"{UUID(str(subject)).hex}/{UUID(str(recording)).hex}/{number:03d}-{digest}"


class FileBlobStore:
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (
            self.root.is_symlink()
            or not self.root.is_dir()
            or stat.S_IMODE(self.root.stat().st_mode) & 0o077
        ):
            raise BlobUnavailable("Invalid private storage root")
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                fd = os.open(
                    ".identity",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    mode=0o600,
                    dir_fd=directory,
                )
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(str(uuid4()).encode())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(directory)
            fd = os.open(".identity", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise BlobUnavailable("Invalid storage identity")
                self.identity = str(UUID(stream.read(37).decode("ascii")))
        except (OSError, ValueError) as exc:
            raise BlobUnavailable("Private storage identity unavailable") from exc
        finally:
            os.close(directory)

    @contextmanager
    def directory(self, key, *, create=False):
        if not isinstance(key, str) or not re.fullmatch(
            r"[a-f0-9]{32}/[a-f0-9]{32}/\d{3}-[a-f0-9]{64}", key
        ):
            raise BlobUnavailable("Invalid blob reference")
        parts = key.split("/")
        descriptors = []
        try:
            fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(fd)
            for name in parts[:-1]:
                if create:
                    try:
                        os.mkdir(name, mode=0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                descriptors.append(fd)
            yield fd, parts[-1]
        except OSError as exc:
            raise BlobUnavailable("Private storage unavailable") from exc
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def read(self, key, size, digest):
        if not isinstance(size, int) or not 1 <= size <= 262144:
            raise BlobUnavailable("Invalid blob size")
        with self.directory(key) as (directory, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise BlobUnavailable("Invalid blob file")
                raw = stream.read(size + 1)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise BlobUnavailable("Invalid blob integrity")
        return raw

    def put(self, key, raw, digest):
        if not 1 <= len(raw) <= 262144 or hashlib.sha256(raw).hexdigest() != digest:
            raise BlobUnavailable("Invalid blob integrity")
        with self.directory(key, create=True) as (directory, name):
            temporary = ".pending-" + uuid4().hex
            try:
                fd = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    mode=0o600,
                    dir_fd=directory,
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(
                        temporary,
                        name,
                        src_dir_fd=directory,
                        dst_dir_fd=directory,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    if self.read(key, len(raw), digest) != raw:
                        raise BlobUnavailable("Conflicting blob") from None
                os.fsync(directory)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory)
                    os.fsync(directory)
                except FileNotFoundError:
                    pass

    def purge_subject(self, subject):
        """Also remove orphaned writes; no symlink or other subject can be traversed."""
        name = UUID(str(subject)).hex
        try:
            root = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                try:
                    owned = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
                except FileNotFoundError:
                    return
                try:
                    self._purge(owned)
                finally:
                    os.close(owned)
                os.rmdir(name, dir_fd=root)
                os.fsync(root)
            finally:
                os.close(root)
        except OSError as exc:
            raise BlobUnavailable("Private storage deletion unavailable") from exc

    def purge_recording(self, subject, recording):
        key = object_key(subject, recording, 0, "0" * 64)
        try:
            with self.directory(key) as (directory, _):
                self._purge(directory)
        except BlobUnavailable as exc:
            # A directory may already be removed by a previous rolled-back reset.
            if not isinstance(exc.__cause__, FileNotFoundError):
                raise
        # Leave the empty scope directories; later writes and subject erasure use them safely.

    def _purge(self, directory):
        for name in os.listdir(directory):
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                try:
                    self._purge(child)
                finally:
                    os.close(child)
                os.rmdir(name, dir_fd=directory)
            else:
                os.unlink(name, dir_fd=directory)
        os.fsync(directory)
