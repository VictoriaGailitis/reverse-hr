"""Prove that a decoder namespace has no usable non-loopback network interface."""

import errno
import fcntl
import socket
import struct
from pathlib import Path

# Linux may create these fallback tunnel devices even with Docker network_mode=none.
# Names alone are not evidence: require their expected type, DOWN state, no address/routes.
INERT_TUNNELS = {"tunl0": 768, "sit0": 776, "ip6tnl0": 769}


def require_no_network():
    interfaces = {
        line.split(":", 1)[0].strip()
        for line in Path("/proc/net/dev").read_text().splitlines()
        if ":" in line
    }
    if "lo" not in interfaces or interfaces - {"lo"} - INERT_TUNNELS.keys():
        raise ValueError("Unexpected decoder interface")
    for name in interfaces - {"lo"}:
        device = Path("/sys/class/net") / name
        if (
            int((device / "type").read_text()) != INERT_TUNNELS[name]
            or int((device / "flags").read_text(), 16) not in {0, 0x80}
            or (device / "operstate").read_text().strip() != "down"
        ):
            raise ValueError("Decoder tunnel is not inert")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            try:
                fcntl.ioctl(probe.fileno(), 0x8915, struct.pack("256s", name.encode()))
            except OSError as exc:
                if exc.errno != errno.EADDRNOTAVAIL:
                    raise
            else:
                raise ValueError("Decoder tunnel has an IPv4 address")
    for line in Path("/proc/net/route").read_text().splitlines()[1:]:
        if line.split()[0] != "lo":
            raise ValueError("Decoder has an IPv4 route")
    for source in ("/proc/net/ipv6_route", "/proc/net/if_inet6"):
        for line in Path(source).read_text().splitlines():
            if line.split()[-1] != "lo":
                raise ValueError("Decoder has a non-loopback IPv6 address or route")
