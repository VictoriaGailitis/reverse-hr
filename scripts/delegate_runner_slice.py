"""Root-only systemd pre-start: permit migration solely within the dedicated Runner slice."""

import os
import pwd
from pathlib import Path

if os.getuid() != 0:
    raise SystemExit("Operator privilege required")
entries = [
    line[3:]
    for line in Path("/proc/self/cgroup").read_text().splitlines()
    if line.startswith("0::")
]
if len(entries) != 1:
    raise SystemExit("Unified cgroup required")
group = Path("/sys/fs/cgroup") / entries[0].lstrip("/")
unit = group.parent if group.name in {"anchor", ".control"} else group
boundary = unit.parent
if unit.name != "reverse-hr-runner-scope.service" or boundary.name != "reverse-hr-runner.slice":
    raise SystemExit(f"Dedicated Runner slice required; pre-start cgroup: {group}")
worker = pwd.getpwnam("runner")
if worker.pw_uid == 0:
    raise SystemExit("Non-root worker required")
# cgroup v2 requires permission on the destination and the common ancestor's procs.
# No permission is granted on system.slice, the cgroup root or resource controllers.
for name in ("cgroup.procs", "cgroup.threads"):
    os.chown(boundary / name, worker.pw_uid, worker.pw_gid)
