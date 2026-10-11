"""Exec FFmpeg with Landlock: runtime and one input file readable, no filesystem writes.

Kept stdlib-only so the launcher works with the decoder's sanitized environment.
The container separately enforces network, seccomp, UID and cgroup restrictions.
"""

import ctypes
import os
import platform
import sys
from pathlib import Path

_READ_FILE, _READ_DIR, _EXECUTE = 1 << 2, 1 << 3, 1 << 0
# ABI 3 controls all filesystem rights through TRUNCATE (including rename/link).
_HANDLED = (1 << 15) - 1


class Ruleset(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def libc():
    if sys.platform != "linux" or platform.machine() not in {"aarch64", "arm64", "x86_64"}:
        raise OSError("Unsupported Landlock platform")
    library = ctypes.CDLL(None, use_errno=True)
    library.syscall.restype = ctypes.c_long
    library.prctl.restype = ctypes.c_int
    return library


def checked(result):
    if result < 0:
        raise OSError(ctypes.get_errno(), "Landlock operation unavailable")
    return result


def abi():
    value = checked(libc().syscall(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint32(1)))
    if value < 3:
        raise OSError("Landlock ABI 3 required")
    return value


def restrict(source):
    abi()
    library = libc()
    attributes = Ruleset(_HANDLED)
    ruleset = checked(library.syscall(444, ctypes.byref(attributes), ctypes.sizeof(attributes), 0))
    try:
        paths = [
            (p, _READ_FILE | _READ_DIR | _EXECUTE)
            for p in ("/usr", "/lib", "/lib64", "/etc")
            if Path(p).exists()
        ]
        paths.append((str(Path(source).absolute()), _READ_FILE))
        for path, access in paths:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(access, fd)
                checked(library.syscall(445, ruleset, 1, ctypes.byref(rule), 0))
            finally:
                os.close(fd)
        checked(library.prctl(38, 1, 0, 0, 0))  # PR_SET_NO_NEW_PRIVS
        checked(library.syscall(446, ruleset, 0))
    finally:
        os.close(ruleset)


def main():
    try:
        source, executable, *args = sys.argv[1:]
        if executable not in {"/usr/bin/ffmpeg", "/usr/bin/ffprobe"}:
            raise ValueError("Untrusted decoder")
        restrict(source)
        os.execve(executable, [executable, *args], {"PATH": "/usr/bin:/bin", "LANG": "C"})
    except (OSError, ValueError):
        # No raw media, paths or runtime diagnostics leave the restricted process.
        sys.exit(78)


if __name__ == "__main__":
    main()
