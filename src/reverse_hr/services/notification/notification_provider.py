"""Fixed HTTPS mail adapter; delivery IDs are mandatory provider idempotency keys."""

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from reverse_hr.protocols.processing_access import NoRedirect


class ProviderUncertain(Exception):
    pass


class ProviderRejected(Exception):
    pass


@dataclass(frozen=True)
class Mail:
    delivery_id: str
    email: str
    text: str


class ChallengeCipher:
    def __init__(self, key):
        self.cipher = AESGCM(key)

    @classmethod
    def from_settings(cls, settings):
        return cls(Path(settings.notification_challenge_key_file).read_bytes())

    def encrypt(self, code, challenge_id):
        import os

        nonce = os.urandom(12)
        return base64.b64encode(
            nonce + self.cipher.encrypt(nonce, code.encode(), challenge_id.encode())
        ).decode()

    def decrypt(self, ciphertext, challenge_id):
        raw = base64.b64decode(ciphertext, validate=True)
        return self.cipher.decrypt(raw[:12], raw[12:], challenge_id.encode()).decode()


def static_https(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("A static HTTPS URL is required")
    return value


class HttpMailProvider:
    def __init__(self, settings):
        if not settings.notification_delivery_enabled:
            raise ValueError("External delivery disabled")
        origin = static_https(settings.notification_provider_url)
        if urlsplit(origin).path not in {"", "/"}:
            raise ValueError("Provider origin cannot contain a path")
        self.url = origin.rstrip("/") + "/v1/messages"
        self.timeout = settings.notification_delivery_timeout_seconds
        self.key = Path(settings.notification_provider_key_file).read_text().strip()
        if not self.key or len(self.key) > 4096 or "\n" in self.key or "\r" in self.key:
            raise ValueError("Invalid provider credential")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def send(self, mail):
        raw = json.dumps(
            {
                "idempotency_key": mail.delivery_id,
                "email": mail.email,
                "subject": "Уведомление платформы",
                "text": mail.text,
            },
            separators=(",", ":"),
        ).encode()
        try:
            with self.opener.open(
                Request(
                    self.url,
                    data=raw,
                    method="POST",
                    headers={
                        "Authorization": "Bearer " + self.key,
                        "Content-Type": "application/json",
                        "Idempotency-Key": mail.delivery_id,
                    },
                ),
                timeout=self.timeout,
            ) as response:
                data = json.loads(response.read(4097))
                if (
                    response.status not in {200, 201, 202}
                    or data.get("idempotency_key") != mail.delivery_id
                    or data.get("status") != "accepted"
                ):
                    raise ProviderUncertain()
                from uuid import UUID

                return str(UUID(data["provider_id"]))
        except HTTPError as exc:
            if 400 <= exc.code < 500 and exc.code not in {408, 409, 425, 429}:
                raise ProviderRejected() from None
            raise ProviderUncertain() from None
        except ProviderRejected:
            raise
        except Exception:
            raise ProviderUncertain() from None
