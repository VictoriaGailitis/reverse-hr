from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from reverse_hr.platform.settings import Settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    subject: UUID
    roles: frozenset[str]
    mfa: bool

    def require(self, role: str, *, mfa: bool = False) -> None:
        if role not in self.roles or (mfa and not self.mfa):
            raise HTTPException(403)


class TokenVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jwks = jwt.PyJWKClient(settings.oidc_jwks_url, timeout=3, lifespan=60)

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
            # Never use a token-supplied URL, algorithm, or key material.
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise jwt.InvalidTokenError()
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud", "typ"]},
            )
            if claims["typ"] != "Bearer" or claims.get("email_verified") is not True:
                raise jwt.InvalidTokenError()
            roles = claims.get("realm_access", {}).get("roles", [])
            amr = claims.get("amr", [])
            if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
                raise jwt.InvalidTokenError()
            if not isinstance(amr, list) or not all(isinstance(method, str) for method in amr):
                raise jwt.InvalidTokenError()
            return Principal(UUID(claims["sub"]), frozenset(roles), "mfa" in amr or "otp" in amr)
        except jwt.PyJWKClientConnectionError as exc:
            raise HTTPException(503) from exc
        except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(401) from exc


def authenticated(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is None or len(credentials.credentials) > 16384:
        raise HTTPException(401)
    actor = request.app.state.token_verifier.verify(credentials.credentials)
    if hasattr(request.app.state, "processing_access"):
        request.app.state.processing_access.check(actor.subject)
    return actor


Actor = Annotated[Principal, Depends(authenticated)]
