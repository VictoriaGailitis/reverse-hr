"""Inactive OrbStack fallback tunnels are accepted only with no addresses or routes."""

import errno
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from reverse_hr.shared.decoder_network import require_no_network


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "unknown",
        "up",
        "running",
        "state",
        "type",
        "ipv4-address",
        "ioctl",
        "ipv4-route",
        "ipv6-route",
        "ipv6-address",
        "missing",
    ],
)
def test_inert_tunnels_cannot_hide_connectivity(monkeypatch, failure):
    files = {
        "/proc/net/dev": "lo: data\ntunl0: data\nsit0: data\nip6tnl0: data",
        "/proc/net/route": "Iface Destination Gateway Flags",
        "/proc/net/ipv6_route": "0 0 0 0 0 0 0 0 0 lo",
        "/proc/net/if_inet6": "0 0 0 0 0 lo",
    }
    for name, kind in [("tunl0", 768), ("sit0", 776), ("ip6tnl0", 769)]:
        files[f"/sys/class/net/{name}/type"] = str(kind)
        files[f"/sys/class/net/{name}/flags"] = "0x80"
        files[f"/sys/class/net/{name}/operstate"] = "down"
    if failure == "unknown":
        files["/proc/net/dev"] += "\nveth0: data"
    if failure == "up":
        files["/sys/class/net/tunl0/flags"] = "0x81"
    if failure == "running":
        files["/sys/class/net/tunl0/flags"] = "0xc0"
    if failure == "state":
        files["/sys/class/net/tunl0/operstate"] = "unknown"
    if failure == "type":
        files["/sys/class/net/tunl0/type"] = "1"
    if failure == "ipv4-route":
        files["/proc/net/route"] += "\ntunl0 0 0 1"
    if failure == "ipv6-route":
        files["/proc/net/ipv6_route"] += "\n0 0 0 0 0 0 0 0 0 sit0"
    if failure == "ipv6-address":
        files["/proc/net/if_inet6"] += "\n0 0 0 0 0 ip6tnl0"
    if failure == "missing":
        del files["/proc/net/ipv6_route"]

    def read(path):
        if str(path) not in files:
            raise FileNotFoundError(str(path))
        return files[str(path)]

    def ioctl(*args):
        if failure == "ipv4-address":
            return bytes(256)
        raise OSError(errno.EPERM if failure == "ioctl" else errno.EADDRNOTAVAIL, "synthetic")

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(
        "reverse_hr.shared.decoder_network.socket.socket",
        lambda *_: nullcontext(SimpleNamespace(fileno=lambda: 7)),
    )
    monkeypatch.setattr("reverse_hr.shared.decoder_network.fcntl.ioctl", ioctl)
    if failure is None:
        require_no_network()
    else:
        with pytest.raises((ValueError, OSError)):
            require_no_network()
