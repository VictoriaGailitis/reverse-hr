"""Local fixed-target TLS tunnel; only a pinned Runner certificate is admitted."""

import argparse
import asyncio
import hashlib
import os
import ssl
from pathlib import Path

TARGETS = {
    15432: ("postgres", 5432),
    18001: ("privacy", 8000),
    18002: ("assessment", 8000),
    18003: ("coding-workspace", 8000),
    18004: ("evaluation", 8000),
}
MAX_CONNECTIONS = 64
active = 0


def context(side, directory):
    directory = Path(directory)
    if side == "server":
        result = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        result.verify_mode = ssl.CERT_REQUIRED
    else:
        result = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    result.minimum_version = ssl.TLSVersion.TLSv1_3
    result.load_verify_locations(directory / "ca.crt")
    result.load_cert_chain(directory / f"{side}.crt", directory / f"{side}.key")
    return result


async def copy(reader, writer):
    while data := await asyncio.wait_for(reader.read(8192), timeout=60):
        writer.write(data)
        await asyncio.wait_for(writer.drain(), timeout=10)


async def relay(reader, writer, target, *, outgoing_tls=None, client_pin=None):
    global active
    peer = writer.get_extra_info("ssl_object")
    if client_pin and (
        peer is None or hashlib.sha256(peer.getpeercert(binary_form=True)).hexdigest() != client_pin
    ):
        writer.close()
        return
    if active >= MAX_CONNECTIONS:
        writer.close()
        return
    active += 1
    upstream = None
    tasks = []
    try:
        options = {"ssl": outgoing_tls, "server_hostname": "runner-bridge"} if outgoing_tls else {}
        remote, upstream = await asyncio.wait_for(
            asyncio.open_connection(*target, **options), timeout=3
        )
        tasks = [
            asyncio.create_task(copy(reader, upstream)),
            asyncio.create_task(copy(remote, writer)),
        ]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except (OSError, TimeoutError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for connection in (writer, upstream):
            if connection:
                connection.close()
                try:
                    await asyncio.wait_for(connection.wait_closed(), timeout=1)
                except (OSError, TimeoutError):
                    pass
        active -= 1


async def serve(side, directory, bridge_host):
    tls = context(side, directory)
    client_pin = os.environ.get("RUNNER_CLIENT_CERT_SHA256", "")
    if side == "server" and (
        len(client_pin) != 64 or any(char not in "0123456789abcdef" for char in client_pin)
    ):
        raise ValueError("Exact approved Runner certificate fingerprint required")
    servers = []
    for port, target in TARGETS.items():
        destination = target if side == "server" else (bridge_host, port)

        async def handler(reader, writer, destination=destination):
            await relay(
                reader,
                writer,
                destination,
                outgoing_tls=tls if side == "client" else None,
                client_pin=client_pin if side == "server" else None,
            )

        servers.append(
            await asyncio.start_server(
                handler,
                "0.0.0.0" if side == "server" else "127.0.0.1",
                port,
                ssl=tls if side == "server" else None,
                **({"ssl_handshake_timeout": 3} if side == "server" else {}),
            )
        )
    await asyncio.gather(*(server.serve_forever() for server in servers))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("side", choices=["client", "server"])
    parser.add_argument("--certificates", required=True)
    parser.add_argument("--bridge-host", default="reverse-hr-runner-bridge-1.orb.local")
    args = parser.parse_args()
    asyncio.run(serve(args.side, args.certificates, args.bridge_host))
