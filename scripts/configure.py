"""Generate local secrets once. Never overwrite existing configuration."""

import os
import secrets
from pathlib import Path

SERVICES = (
    "identity",
    "privacy",
    "candidate",
    "employer",
    "assessment",
    "coding_workspace",
    "code_runner",
    "whiteboard",
    "media",
    "proctoring",
    "evaluation",
    "matching",
    "hiring",
    "achievements",
    "integration",
    "notification",
    "audit",
    "demo_fsp",
    "demo_hackathon_platform",
    "demo_ats",
    "keycloak",
)

path = Path(".env")
with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
    for key in (
        "POSTGRES_PASSWORD",
        "RABBITMQ_PASSWORD",
        "REDIS_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "KC_BOOTSTRAP_ADMIN_PASSWORD",
        *(f"{name.upper()}_DB_PASSWORD" for name in SERVICES),
    ):
        stream.write(f"{key}={secrets.token_hex(32)}\n")
print("Created .env (0600); keep it private and do not commit it.")
