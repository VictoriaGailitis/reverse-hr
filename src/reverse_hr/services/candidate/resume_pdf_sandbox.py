"""Landlock PDF child: immutable runtime, one temporary workspace, no socket access."""

import ctypes
import os
import sys
from pathlib import Path

from reverse_hr.shared.decoder_guest import (
    _EXECUTE,
    _HANDLED,
    _READ_DIR,
    _READ_FILE,
    PathRule,
    Ruleset,
    abi,
    checked,
    libc,
)


def restrict(directory):
    abi()
    library = libc()
    attributes = Ruleset(_HANDLED)
    ruleset = checked(library.syscall(444, ctypes.byref(attributes), ctypes.sizeof(attributes), 0))
    try:
        read = _READ_FILE | _READ_DIR | _EXECUTE
        paths = [
            (path, read)
            for path in (
                "/usr",
                "/lib",
                "/lib64",
                "/etc",
                sys.prefix,
                str(Path(__file__).resolve().parents[3]),
            )
            if Path(path).exists()
        ]
        paths += [
            (directory, _HANDLED & ~_EXECUTE),
            ("/dev/null", _READ_FILE | (1 << 1)),
            ("/dev/urandom", _READ_FILE),
        ]
        for path, access in paths:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathRule(access, fd)
                checked(library.syscall(445, ruleset, 1, ctypes.byref(rule), 0))
            finally:
                os.close(fd)
        checked(library.prctl(38, 1, 0, 0, 0))
        checked(library.syscall(446, ruleset, 0))
    finally:
        os.close(ruleset)
