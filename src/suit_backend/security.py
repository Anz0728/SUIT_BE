from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from .config import get_settings

password_hash = PasswordHash.recommended()


class InvalidTokenError(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def create_access_token(*, user_id: str, organization_id: str, role: str) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "org": organization_id,
        "role": role,
        "iat": now,
        "nbf": now,
        "exp": expires,
        "iss": "suit-api",
        "aud": "suit-web",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int((expires - now).total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience="suit-web",
            issuer="suit-api",
            options={"require": ["sub", "org", "role", "exp", "iat", "nbf"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError from exc

