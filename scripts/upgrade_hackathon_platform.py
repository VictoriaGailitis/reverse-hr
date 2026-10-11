"""Prepare existing demo configuration for the abstract hackathon adapter.

Keep the original database and signing key; never print secrets or change live data.
Run before configure_events.py on a previously configured deployment.
"""

import os
import shutil
from pathlib import Path
from urllib.parse import quote

from dotenv import dotenv_values


def upgrade(root: Path):
    env = root / ".env"
    if not env.exists():
        return
    values = dotenv_values(env)
    password = values.get("DEMO_CODENROCK_DB_PASSWORD")
    additions = {}
    if password and not values.get("DEMO_HACKATHON_PLATFORM_DB_PASSWORD"):
        additions["DEMO_HACKATHON_PLATFORM_DB_PASSWORD"] = password
        if not values.get("DEMO_HACKATHON_PLATFORM_DATABASE_URL"):
            additions["DEMO_HACKATHON_PLATFORM_DATABASE_URL"] = (
                "postgresql+psycopg://demo_codenrock:"
                + quote(password, safe="")
                + "@postgres:5432/demo_codenrock"
            )
    if additions:
        with env.open("a") as stream:
            stream.write("\n")
            for name, value in additions.items():
                stream.write(f"{name}={value}\n")
        env.chmod(0o600)
    old = root / ".secrets/demo-codenrock.key"
    new = root / ".secrets/demo-hackathon-platform.key"
    if old.exists() and not new.exists():
        # Preserve the demo identity rather than regenerate its private key.
        with os.fdopen(os.open(new, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444), "wb") as out:
            with old.open("rb") as source:
                shutil.copyfileobj(source, out)


if __name__ == "__main__":
    upgrade(Path.cwd())
    print("Hackathon Platform configuration prepared; run configure_events.py next.")
