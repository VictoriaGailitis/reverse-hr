import os
import sys
from pathlib import Path

from fastapi import HTTPException


def require_isolation():
    try:
        from reverse_hr.shared.decoder_guest import abi

        abi()
        if sys.platform != "linux" or os.getuid() == 0 or not os.statvfs("/").f_flag & os.ST_RDONLY:
            raise ValueError
        status = dict(
            line.split(":", 1)
            for line in Path("/proc/self/status").read_text().splitlines()
            if ":" in line
        )
        if (
            any(int(status[key].strip(), 16) for key in ("CapEff", "CapPrm", "CapBnd"))
            or status["NoNewPrivs"].strip() != "1"
            or status["Seccomp"].strip() != "2"
        ):
            raise ValueError
        from reverse_hr.shared.decoder_network import require_no_network

        require_no_network()
        cgroup = Path("/sys/fs/cgroup")
        if (
            not 1 <= int((cgroup / "pids.max").read_text()) <= 64
            or not 1 <= int((cgroup / "memory.max").read_text()) <= 512 * 1024 * 1024
        ):
            raise ValueError
        quota, period = (cgroup / "cpu.max").read_text().split()
        if not 0 < int(quota) <= int(period):
            raise ValueError
        if any(
            key.startswith("HR_") and key != "HR_MEDIA_VALIDATION_TIMEOUT_SECONDS"
            for key in os.environ
        ):
            raise ValueError
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Decoder container isolation is not established") from exc
