import re
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import jwt
from pwdlib import PasswordHash

from .config import get_settings

password_hash = PasswordHash.recommended()


class InvalidTokenError(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_one_time_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_and_update_password(password: str, encoded: str) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(password, encoded)


def password_policy_error(password: str, email: str) -> str | None:
    normalized = password.casefold()
    local_part = email.split("@", maxsplit=1)[0].casefold()
    common = {
        "password1234",
        "qwer1234!@#$",
        "admin12345678",
        "123456789012",
        "suit12345678",
    }
    if normalized in common:
        return "Password is too common"
    if len(local_part) >= 4 and local_part in normalized:
        return "Password must not contain the email account name"
    if len(password) >= 16:
        return None
    classes = sum(
        bool(re.search(pattern, password))
        for pattern in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]")
    )
    if classes < 3:
        return "Password must be 16+ characters or use at least three character types"
    return None


def create_access_token(
    *, user_id: str, organization_id: str, role: str, auth_version: int
) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "org": organization_id,
        "role": role,
        "ver": auth_version,
        "jti": str(uuid.uuid4()),
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
            options={
                "require": ["sub", "org", "role", "ver", "jti", "exp", "iat", "nbf"]
            },
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError from exc

