"""Fresh local TLS peers test authentication; no existing platform data or secrets."""

import asyncio
import importlib.util
import ssl
from uuid import uuid4

import pytest

from reverse_hr.shared.paths import REPOSITORY_ROOT


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = REPOSITORY_ROOT
credentials = load("runner_tls_credentials", ROOT / "scripts/configure_runner_tls.py")
tunnel = load("runner_tls_tunnel", ROOT / "infra/runner/orbstack_tunnel.py")


def test_credentials_are_private_and_never_rotated(tmp_path):
    pin = credentials.create(tmp_path, uuid4())
    assert len(pin) == 64
    key = tmp_path / "runner-tls-client/client.key"
    original = key.read_bytes()
    assert key.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="not rotating"):
        credentials.create(tmp_path, uuid4())
    assert key.read_bytes() == original
    server = tunnel.context("server", tmp_path / "runner-tls-server")
    client = tunnel.context("client", tmp_path / "runner-tls-client")
    assert server.verify_mode == ssl.CERT_REQUIRED
    assert client.verify_mode == ssl.CERT_REQUIRED and client.check_hostname
    assert server.minimum_version == client.minimum_version == ssl.TLSVersion.TLSv1_3


def test_authenticated_relay_rejects_missing_foreign_and_unpinned_clients(tmp_path):
    good = tmp_path / "good"
    foreign = tmp_path / "foreign"
    good.mkdir()
    foreign.mkdir()
    pin = credentials.create(good, uuid4())
    credentials.create(foreign, uuid4())

    async def run():
        requests = []

        async def echo(reader, writer):
            try:
                data = await reader.readexactly(4)
                requests.append(data)
                writer.write(data)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
        destination = ("127.0.0.1", upstream.sockets[0].getsockname()[1])
        server_context = tunnel.context("server", good / "runner-tls-server")
        approved_pin = pin

        async def handler(reader, writer):
            await tunnel.relay(reader, writer, destination, client_pin=approved_pin)

        server = await asyncio.start_server(
            handler, "127.0.0.1", 0, ssl=server_context, ssl_handshake_timeout=1
        )
        address = ("127.0.0.1", server.sockets[0].getsockname()[1])

        async def exchange(context, expected):
            writer = None
            try:
                reader, writer = await asyncio.open_connection(
                    *address, ssl=context, server_hostname="runner-bridge"
                )
                writer.write(b"ping")
                await writer.drain()
                reply = await asyncio.wait_for(reader.read(4), timeout=2)
                assert reply == expected
            except (OSError, asyncio.IncompleteReadError):
                assert expected == b""
            finally:
                if writer:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass

        try:
            client = tunnel.context("client", good / "runner-tls-client")
            await exchange(client, b"ping")
            anonymous = ssl.create_default_context(cafile=good / "runner-tls-server/ca.crt")
            await exchange(anonymous, b"")
            outsider = tunnel.context("client", foreign / "runner-tls-client")
            outsider.load_verify_locations(good / "runner-tls-server/ca.crt")
            await exchange(outsider, b"")
            approved_pin = "0" * 64
            await exchange(client, b"")
            assert requests == [b"ping"]
        finally:
            server.close()
            upstream.close()
            await server.wait_closed()
            await upstream.wait_closed()
        assert tunnel.active == 0

    asyncio.run(run())


def test_bridge_targets_are_fixed_and_no_additional_service_is_reachable():
    assert tunnel.TARGETS == {
        15432: ("postgres", 5432),
        18001: ("privacy", 8000),
        18002: ("assessment", 8000),
        18003: ("coding-workspace", 8000),
        18004: ("evaluation", 8000),
    }
