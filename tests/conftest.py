import json
import time
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from alembic import command
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from reverse_hr.app import create_app
from reverse_hr.migrate import migration_config
from reverse_hr.settings import Settings


@pytest.fixture(scope="module")
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    return private, public | {"kid": "test-key", "use": "sig", "alg": "RS256"}


@pytest.fixture
def service(tmp_path, keys):
    clients = []

    def make(name):
        settings = Settings(
            media_antivirus_required=False,
            media_decoder_required=False,
            service_name=name,
            database_url=f"sqlite:///{tmp_path}/{name}.db",
            media_storage_root=str(tmp_path / "media-objects") if name == "media" else "",
        )
        command.upgrade(migration_config(settings), "head")
        app = create_app(settings)
        if name in {
            "candidate",
            "employer",
            "assessment",
            "coding-workspace",
            "code-runner",
            "evaluation",
            "matching",
            "hiring",
            "notification",
            "media",
            "whiteboard",
            "proctoring",
        }:
            app.state.processing_access = SimpleNamespace(
                check=lambda *_: None, check_assessment=lambda *_: None
            )
        app.state.token_verifier.jwks.fetch_data = lambda: {"keys": [keys[1]]}
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return SimpleNamespace(app=app, client=client)

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def token(keys):
    def make(subject=None, roles=("candidate",), **overrides):
        claims = {
            "sub": str(subject or uuid4()),
            "iss": Settings().oidc_issuer,
            "aud": "reverse-hr-api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "typ": "Bearer",
            "email_verified": True,
            "realm_access": {"roles": list(roles)},
        } | overrides
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                claims,
                keys[0],
                algorithm="RS256",
                headers={"kid": "test-key"},
            )
        }

    return make
