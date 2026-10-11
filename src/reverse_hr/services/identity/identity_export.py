"""Optional bounded, own-account Keycloak projection for signed Privacy exports."""

import json
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID

from fastapi import HTTPException

from reverse_hr.protocols.processing_access import NoRedirect

MAX_RESPONSE = 131072
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "keycloak"}
_SENSITIVE = re.compile(
    r"password|secret|token|credential|private|cookie|session|authorization", re.I
)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate field")
            result[key] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON constant")),
    )


def _text(value, *, limit=4096):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Invalid account field")
    return value


class KeycloakIdentityExport:
    """Construct lazily; credential files are opened only when exporting an account.

    No user-controlled origins, searches, pagination or admin writes are exposed.
    Provider permissions must be limited to viewing users in the configured realm.
    """

    def __init__(self, settings):
        if not settings.identity_export_enabled:
            raise ValueError("Identity export disabled")
        origin = settings.identity_export_origin
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (
                parsed.scheme == "http"
                and not (settings.identity_export_trusted_local and parsed.hostname in _LOCAL_HOSTS)
            )
        ):
            raise ValueError("Fixed HTTPS or explicitly trusted local identity origin required")
        # Force port validation before any credential is loaded.
        _ = parsed.port
        self.origin = origin.rstrip("/")
        self.realm = settings.identity_export_realm
        self.client_id = settings.identity_export_client_id
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.realm):
            raise ValueError("Invalid fixed identity realm")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", self.client_id):
            raise ValueError("Invalid identity client")
        self.timeout = settings.identity_export_timeout_seconds
        if type(self.timeout) is not int or not 1 <= self.timeout <= 15:
            raise ValueError("Invalid identity timeout")
        self.key_file = settings.identity_export_key_file
        self.attributes = tuple(settings.identity_export_attribute_names)
        if len(self.attributes) > 32 or len(set(self.attributes)) != len(self.attributes):
            raise ValueError("Invalid attribute allowlist")
        for name in self.attributes:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", name) or _SENSITIVE.search(name):
                raise ValueError("Sensitive or invalid account attribute")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self._token = None
        self._expires = 0
        self._token_lock = threading.Lock()

    def _request(self, path, *, data=None, token=None):
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        with self.opener.open(
            Request(
                self.origin + path, data=data, headers=headers, method="POST" if data else "GET"
            ),
            timeout=self.timeout,
        ) as response:
            if (
                response.status != 200
                or response.headers.get("Content-Encoding", "identity") != "identity"
            ):
                raise ValueError("Invalid identity response")
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("Oversized identity response")
        return _json(raw)

    def _access_token(self):
        with self._token_lock:
            if self._token and time.monotonic() < self._expires:
                return self._token
            with Path(self.key_file).open("rb") as stream:
                raw = stream.read(4097)
            secret = raw.decode("ascii").strip()
            if len(raw) > 4096 or not secret or any(ord(c) <= 32 or ord(c) >= 127 for c in secret):
                raise ValueError("Invalid identity service credential")
            started = time.monotonic()
            result = self._request(
                f"/realms/{self.realm}/protocol/openid-connect/token",
                data=urlencode(
                    dict(
                        grant_type="client_credentials",
                        client_id=self.client_id,
                        client_secret=secret,
                    )
                ).encode(),
            )
            if not isinstance(result, dict) or result.get("token_type", "").casefold() != "bearer":
                raise ValueError("Invalid identity token")
            token, lifespan = result.get("access_token"), result.get("expires_in")
            if (
                not isinstance(token, str)
                or not 1 <= len(token) <= 16384
                or any(ord(c) <= 32 or ord(c) >= 127 for c in token)
                or type(lifespan) is not int
                or not 1 <= lifespan <= 3600
            ):
                raise ValueError("Invalid identity token")
            self._token, self._expires = token, started + max(0, min(60, lifespan - 5))
            return token

    def records(self, subject):
        # Parse before network/secret access; neither arbitrary account names nor paths work.
        try:
            subject = UUID(str(subject))
            token = self._access_token()
            path = f"/admin/realms/{self.realm}/users/{subject}"
            account = self._request(path, token=token)
            credentials = self._request(path + "/credentials", token=token)
            return self._project(subject, account, credentials)
        except HTTPError as exc:
            if exc.code == 401:
                with self._token_lock:
                    self._token, self._expires = None, 0
            raise HTTPException(503, "Identity source unavailable") from None
        except Exception:
            raise HTTPException(503, "Identity source unavailable") from None

    def _project(self, subject, account, credentials):
        if not isinstance(account, dict) or UUID(_text(account.get("id"), limit=36)) != subject:
            raise ValueError("Account ownership mismatch")
        profile = {"id": str(subject)}
        for field in ("username", "email", "firstName", "lastName"):
            if field in account and account[field] is not None:
                profile[field] = _text(account[field])
        for field in ("emailVerified", "enabled"):
            if field in account:
                if type(account[field]) is not bool:
                    raise ValueError("Invalid account state")
                profile[field] = account[field]
        if "createdTimestamp" in account:
            if type(account["createdTimestamp"]) is not int or account["createdTimestamp"] < 0:
                raise ValueError("Invalid account timestamp")
            profile["createdTimestamp"] = account["createdTimestamp"]
        attributes = account.get("attributes", {})
        if not isinstance(attributes, dict):
            raise ValueError("Invalid account attributes")
        profile["attributes"] = {}
        for name in sorted(self.attributes):
            if name in attributes:
                values = attributes[name]
                if not isinstance(values, list) or len(values) > 32:
                    raise ValueError("Invalid account attributes")
                profile["attributes"][name] = [_text(value) for value in values]
        if not isinstance(credentials, list) or len(credentials) > 64:
            raise ValueError("Invalid credential metadata")
        result = [{"table": "keycloak_account", "key": str(subject), "data": profile}]
        seen = set()
        for credential in credentials:
            if not isinstance(credential, dict):
                raise ValueError("Invalid credential metadata")
            identifier = _text(credential.get("id"), limit=256)
            if not identifier or identifier in seen:
                raise ValueError("Ambiguous credential metadata")
            seen.add(identifier)
            metadata = {"id": identifier, "type": _text(credential.get("type"), limit=128)}
            if "userLabel" in credential and credential["userLabel"] is not None:
                metadata["userLabel"] = _text(credential["userLabel"], limit=256)
            if "createdDate" in credential:
                if type(credential["createdDate"]) is not int or credential["createdDate"] < 0:
                    raise ValueError("Invalid credential timestamp")
                metadata["createdDate"] = credential["createdDate"]
            result.append(
                {
                    "table": "keycloak_credential_metadata",
                    "key": str(subject) + ":" + identifier,
                    "data": metadata,
                }
            )
        # Stable order supports the generic owner revision fingerprint on subsequent pages.
        return tuple(sorted(result, key=lambda row: (row["table"], row["key"])))
