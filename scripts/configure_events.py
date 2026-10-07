"""Generate service signing identities and RabbitMQ users/topology for the local demo."""

import base64
import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values

from reverse_hr.settings import SERVICES

root = Path(".secrets")
root.mkdir(mode=0o700, exist_ok=True)
root.chmod(0o700)
env = Path(".env")
values = dotenv_values(env)
missing = [
    (service.upper().replace("-", "_") + "_AMQP_PASSWORD", secrets.token_hex(32))
    for service in SERVICES
    if not values.get(service.upper().replace("-", "_") + "_AMQP_PASSWORD")
]
if not values.get("RABBITMQ_PASSWORD"):
    raise SystemExit("Run configure.py first")
with env.open("a") as stream:
    for key, value in missing:
        stream.write(f"{key}={value}\n")
        values[key] = value
env.chmod(0o600)


def password_hash(password):
    salt = os.urandom(4)
    return base64.b64encode(salt + hashlib.sha256(salt + password.encode()).digest()).decode()


public = {}
users = [
    {
        "name": "hr",
        "password_hash": password_hash(values["RABBITMQ_PASSWORD"]),
        "hashing_algorithm": "rabbit_password_hashing_sha256",
        "tags": "administrator",
    }
]
permissions = [{"user": "hr", "vhost": "/", "configure": ".*", "write": ".*", "read": ".*"}]
exchanges, queues, bindings = [], [], []
for service in SERVICES:
    path = root / f"{service}.key"
    if not path.exists():
        private = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        # Parent is 0700. Only this file is bound for container UID 10001.
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444), "wb") as stream:
            stream.write(private)
    key = Ed25519PrivateKey.from_private_bytes(path.read_bytes())
    public[service] = base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode()
    users.append(
        {
            "name": service,
            "password_hash": password_hash(
                values[service.upper().replace("-", "_") + "_AMQP_PASSWORD"]
            ),
            "hashing_algorithm": "rabbit_password_hashing_sha256",
            "tags": "",
        }
    )
    name = re.escape(service)
    permissions.append(
        {
            "user": service,
            "vhost": "/",
            "configure": "^$",
            "write": rf"^(events|incoming|retry|dead)\.{name}$",
            "read": rf"^{name}\.(incoming|dead)$",
        }
    )
    for kind in ("events", "incoming", "retry", "dead"):
        exchanges.append(
            {
                "name": f"{kind}.{service}",
                "vhost": "/",
                "type": "topic" if kind == "events" else "direct",
                "durable": True,
                "auto_delete": False,
                "internal": False,
                "arguments": {},
            }
        )
    for kind in ("incoming", "retry", "dead"):
        args = {"x-queue-type": "quorum"}
        if kind == "retry":
            args |= {
                "x-message-ttl": 5000,
                "x-dead-letter-exchange": f"incoming.{service}",
                "x-dead-letter-routing-key": service,
            }
        queues.append(
            {
                "name": f"{service}.{kind}",
                "vhost": "/",
                "durable": True,
                "auto_delete": False,
                "arguments": args,
            }
        )
        bindings.append(
            {
                "source": f"{kind}.{service}",
                "vhost": "/",
                "destination": f"{service}.{kind}",
                "destination_type": "queue",
                "routing_key": service,
                "arguments": {},
            }
        )
    # Preserve events in Audit even before its business worker exists.
    bindings.append(
        {
            "source": f"events.{service}",
            "vhost": "/",
            "destination": "audit.incoming",
            "destination_type": "queue",
            "routing_key": "#",
            "arguments": {},
        }
    )
bindings.append(
    {
        "source": "events.hiring",
        "vhost": "/",
        "destination": "privacy.incoming",
        "destination_type": "queue",
        "routing_key": "hiring.invitation_accepted.v1",
        "arguments": {},
    }
)
bindings.append(
    {
        "source": "events.coding-workspace",
        "vhost": "/",
        "destination": "code-runner.incoming",
        "destination_type": "queue",
        "routing_key": "coding-workspace.run_requested.v1",
        "arguments": {},
    }
)
for kind in ("run_accepted", "run_diagnosed", "run_started", "run_finished", "run_cancelled"):
    bindings.append(
        {
            "source": "events.code-runner",
            "vhost": "/",
            "destination": "coding-workspace.incoming",
            "destination_type": "queue",
            "routing_key": f"code-runner.{kind}.v1",
            "arguments": {},
        }
    )
bindings.append(
    {
        "source": "events.assessment",
        "vhost": "/",
        "destination": "evaluation.incoming",
        "destination_type": "queue",
        "routing_key": "assessment.stage_submitted.v1",
        "arguments": {},
    }
)
bindings.append(
    {
        "source": "events.assessment",
        "vhost": "/",
        "destination": "code-runner.incoming",
        "destination_type": "queue",
        "routing_key": "assessment.stage_submitted.v1",
        "arguments": {},
    }
)
bindings.append(
    {
        "source": "events.assessment",
        "vhost": "/",
        "destination": "candidate.incoming",
        "destination_type": "queue",
        "routing_key": "assessment.grade_decision_recorded.v1",
        "arguments": {},
    }
)
for event_type in (
    "candidate.profile_created.v1",
    "candidate.profile_updated.v1",
    "privacy.consent_revoked.v1",
):
    bindings.append(
        {
            "source": "events." + event_type.split(".")[0],
            "vhost": "/",
            "destination": "matching.incoming",
            "destination_type": "queue",
            "routing_key": event_type,
            "arguments": {},
        }
    )
bindings.append(
    {
        "source": "events.hiring",
        "vhost": "/",
        "destination": "notification.incoming",
        "destination_type": "queue",
        "routing_key": "hiring.notification_requested.v1",
        "arguments": {},
    }
)
# Deletion fan-out and independently signed acknowledgements to the coordinator.
for service in SERVICES:
    if service == "privacy":
        continue
    bindings.append(
        {
            "source": "events.privacy",
            "vhost": "/",
            "destination": f"{service}.incoming",
            "destination_type": "queue",
            "routing_key": "privacy.deletion_requested.v1",
            "arguments": {},
        }
    )
    bindings.append(
        {
            "source": f"events.{service}",
            "vhost": "/",
            "destination": "privacy.incoming",
            "destination_type": "queue",
            "routing_key": f"{service}.data_deleted.v1",
            "arguments": {},
        }
    )
    bindings.append(
        {
            "source": f"events.{service}",
            "vhost": "/",
            "destination": "privacy.incoming",
            "destination_type": "queue",
            "routing_key": f"{service}.data_restricted.v1",
            "arguments": {},
        }
    )
definitions = {
    "vhosts": [{"name": "/"}],
    "users": users,
    "permissions": permissions,
    "exchanges": exchanges,
    "queues": queues,
    "bindings": bindings,
    "policies": [
        {
            "name": "reliable-retry",
            "vhost": "/",
            "pattern": r"\.retry$",
            "apply-to": "queues",
            "priority": 0,
            "definition": {"dead-letter-strategy": "at-least-once", "overflow": "reject-publish"},
        }
    ],
}
for name, content in (("public-keys.json", public), ("rabbitmq-definitions.json", definitions)):
    temporary = root / (name + ".tmp")
    temporary.write_text(json.dumps(content, indent=2) + "\n")
    temporary.chmod(0o444)
    temporary.replace(root / name)
print(
    "Configured service signing identities, broker users and durable topology; credentials omitted"
)
